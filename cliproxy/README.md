# CLIProxyAPI trên vpn4

Biến subscription **Claude Code** và **OpenAI Codex** đã đăng nhập sẵn trên server
thành API tương thích OpenAI / Anthropic / Gemini, để mọi ứng dụng khác (WhatsApp
agent, wikiAgent, script…) gọi được mà không cần API key trả tiền riêng.

- Upstream: [router-for-me/CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)
- Host: **vpn4** (`149.104.66.174` / `vpn4.hangocthanh.io.vn`)
- Endpoint: `http://<vpn4>:8317` — **công khai**, xác thực bằng API key
- Deploy: workflow [`deploy-cliproxy.yml`](../.github/workflows/deploy-cliproxy.yml) (`workflow_dispatch`)

## 1. Vì sao cổng 8317 mà không phải 443

Trên vpn4, `derper` đã chiếm 80/443/3478 (Let's Encrypt autocert của
`vpn4.hangocthanh.io.vn`). Stack này vì thế chỉ dùng:

| Cổng | Bind | Dùng để |
|---|---|---|
| `8317` | `0.0.0.0` | API chính, ai cũng gọi được → **bắt buộc** có `api-keys` |
| `54545` | `127.0.0.1` | Callback OAuth Claude Code (chỉ dùng lúc đăng nhập, qua SSH tunnel) |
| `1455` | `127.0.0.1` | Callback OAuth OpenAI Codex |
| `8085` | `127.0.0.1` | Callback OAuth Gemini CLI (dự phòng) |

> ⚠️ 8317 là **HTTP trần** — API key đi trong header không mã hoá. Chấp nhận được
> cho traffic nội bộ/cá nhân; muốn siết thì xem mục [6. Siết bảo mật](#6-siết-bảo-mật).

## 2. Cấu trúc thư mục (trên vpn4: `/opt/deployHeadscale/cliproxy`)

```
cliproxy/
├── docker-compose.yml       # commit — stack thật
├── config.template.yaml     # commit — template, chứa placeholder
├── config.yaml              # KHÔNG commit — workflow sinh ra từ template + secrets
├── auths/                   # KHÔNG commit — token OAuth Claude/Codex (bind mount)
└── logs/                    # KHÔNG commit
```

**`auths/` là thứ quý nhất**: mất nó = phải đăng nhập lại toàn bộ. Nó là bind mount
nên deploy lại (`git reset --hard` + `compose up`) không đụng tới. Workflow deploy
cố tình **không** có `git clean` hay `docker compose down -v`
([test](../test/test_cliproxy_config.py) chặn việc đó tái xuất hiện).

## 3. Deploy

Secrets cần có trong repo:

| Secret | Ý nghĩa |
|---|---|
| `CLIPROXY_API_KEY` | Key client phải gửi kèm khi gọi 8317 |
| `CLIPROXY_MGMT_KEY` | Key của Management API (`/v0/management`, chỉ localhost) |
| `SSH_HOST_VPN4`, `SSH_USER`, `SSH_KEY`, `SSH_PORT`, `DEPLOY_PATH` | đã có sẵn, dùng chung với các stack vpn4 khác |

```bash
gh workflow run deploy-cliproxy.yml --ref main
# nâng version image:
gh workflow run deploy-cliproxy.yml --ref main -f image_tag=v7.2.112
```

Workflow sẽ: cập nhật repo trên vpn4 → sinh `config.yaml` (chmod 600) → `docker compose pull/up`
→ verify **có key = 200 / không key = 401** từ cả trong host lẫn từ Internet.

## 4. Đăng nhập Claude và Codex (làm 1 lần, sau đó token tự refresh)

Server không có trình duyệt, còn OAuth của Claude/Codex bắt buộc redirect về
`localhost` — nên phải **đưa cổng callback về máy có trình duyệt bằng SSH tunnel**.

**Bước 1 — mở tunnel** (chạy trên máy cá nhân, giữ cửa sổ này mở):

```bash
ssh -N -L 54545:127.0.0.1:54545 -L 1455:127.0.0.1:1455 <user>@149.104.66.174
```

**Bước 2 — chạy lệnh login trong container** (SSH cửa sổ khác vào vpn4):

```bash
# Claude Code (callback 54545)
docker exec -it cliproxy ./CLIProxyAPI -claude-login -no-browser

# OpenAI Codex (callback 1455)
docker exec -it cliproxy ./CLIProxyAPI -codex-login -no-browser
```

Lệnh in ra một URL → mở URL đó bằng trình duyệt **trên máy đang mở tunnel** →
đăng nhập/authorize → trình duyệt nhảy về `localhost:54545` (hoặc `1455`) → tunnel
đẩy ngược vào container → token được ghi vào `auths/`.

Codex còn có đường không cần tunnel (device code, nhập mã trên máy khác):

```bash
docker exec -it cliproxy ./CLIProxyAPI -codex-device-login
```

**Bước 3 — kiểm tra:**

```bash
ls -1 /opt/deployHeadscale/cliproxy/auths          # phải thấy claude-*.json, codex-*.json
curl -s -H "Authorization: Bearer $CLIPROXY_API_KEY" http://127.0.0.1:8317/v1/models
```

Sau khi có token, `/v1/models` phải liệt kê model Claude + GPT.

## 5. Cách gọi

```bash
# OpenAI-compatible
curl http://149.104.66.174:8317/v1/chat/completions \
  -H "Authorization: Bearer $CLIPROXY_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"claude-opus-5","messages":[{"role":"user","content":"ping"}]}'

# Anthropic-compatible
curl http://149.104.66.174:8317/v1/messages \
  -H "x-api-key: $CLIPROXY_API_KEY" -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-opus-5","max_tokens":64,"messages":[{"role":"user","content":"ping"}]}'
```

Trỏ công cụ sẵn có vào proxy:

```bash
# Claude Code
export ANTHROPIC_BASE_URL=http://149.104.66.174:8317
export ANTHROPIC_AUTH_TOKEN=$CLIPROXY_API_KEY

# SDK OpenAI / thư viện bất kỳ
export OPENAI_BASE_URL=http://149.104.66.174:8317/v1
export OPENAI_API_KEY=$CLIPROXY_API_KEY
```

`GET /v1/models` là cách nhanh nhất để biết account nào đang sống.

## 6. Siết bảo mật

Theo thứ tự đáng làm:

1. **Đổi key**: sửa secret `CLIPROXY_API_KEY` rồi chạy lại workflow. Key cũ chết ngay.
2. **Giới hạn IP nguồn** (không cần TLS, hiệu quả nhất nếu chỉ vài máy gọi):
   ```bash
   iptables -I DOCKER-USER -p tcp --dport 8317 ! -s <IP-được-phép> -j DROP
   ```
   Nhớ ghi vào runbook vì rule iptables không nằm trong repo.
3. **Bật TLS**: đặt cert/key vào `cliproxy/` rồi sửa `tls.enable: true` trong
   `config.template.yaml`. Không dùng chung cert của derper được vì derper giữ
   autocert cache riêng và tự gia hạn.
4. **Management API**: đang `allow-remote: false` → chỉ gọi được từ chính vpn4
   (`curl -H "Authorization: Bearer $CLIPROXY_MGMT_KEY" http://127.0.0.1:8317/v0/management/...`).
   Đừng bật `allow-remote` khi chưa có TLS.

## 7. Vận hành

```bash
cd /opt/deployHeadscale/cliproxy
docker compose ps                    # trạng thái + healthcheck
docker compose logs --tail 100 -f    # log
docker compose restart               # restart nhanh
ls -1 auths/                          # các account đang có
```

- **Gỡ 1 account**: xoá file `auths/<provider>-*.json` rồi `docker compose restart`.
- **Backup**: `tar czf cliproxy-auths-$(date +%F).tgz -C /opt/deployHeadscale/cliproxy auths`
  — file này chứa refresh token, giữ như mật khẩu.
- **Nâng version**: `gh workflow run deploy-cliproxy.yml -f image_tag=vX.Y.Z`. Muốn
  cố định lâu dài thì sửa tag mặc định trong `docker-compose.yml` (CI chặn `:latest`).

## 8. Chuyển sang server khác

Stack không phụ thuộc gì vào vpn4 ngoài việc 80/443 đã bận. Các bước:

1. **Backup token trên server cũ**:
   ```bash
   tar czf /tmp/cliproxy-auths.tgz -C /opt/deployHeadscale/cliproxy auths
   ```
   Copy về máy cá nhân (`scp`). Không có bước này thì phải login lại từ đầu —
   không mất mát gì ngoài thời gian, nhưng phải có trình duyệt + tunnel.
2. **Chuẩn bị server mới**: Docker + Docker Compose, cổng 8317 chưa ai dùng
   (`ss -tlnp | grep 8317`), không firewall chặn.
3. **Đổi secret trỏ host**: workflow đang dùng `secrets.SSH_HOST_VPN4`. Nếu sang
   host khác thì sửa `deploy-cliproxy.yml` dùng secret host mới (vd `SSH_HOST_VPN7`)
   và đảm bảo `SSH_USER`/`SSH_KEY`/`DEPLOY_PATH` đúng cho host đó. Đồng thời đổi
   `concurrency.group` nếu host mới không phải vpn4 (group hiện tại là
   `deploy-vpn4-host`, dùng để xếp hàng với derper/vpn-gw).
4. **Deploy**: `gh workflow run deploy-cliproxy.yml --ref main` → stack lên nhưng
   chưa có token.
5. **Phục hồi token**:
   ```bash
   tar xzf cliproxy-auths.tgz -C /opt/deployHeadscale/cliproxy
   chmod 700 /opt/deployHeadscale/cliproxy/auths
   docker compose -f /opt/deployHeadscale/cliproxy/docker-compose.yml restart
   ```
   Token OAuth không gắn với IP server nên bê nguyên sang máy khác vẫn chạy.
6. **Cập nhật client**: mọi nơi đang trỏ `http://149.104.66.174:8317` phải đổi sang
   IP/host mới (`ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, biến trong app).
7. **Tắt server cũ** sau khi `GET /v1/models` trên server mới trả 200 kèm đủ model,
   và nhớ xoá `auths/` trên server cũ (`shred -u auths/*.json`) vì nó còn refresh token.

## 9. Sự cố thường gặp

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| `/v1/models` trả 401 dù có key | Key không khớp `config.yaml` trên server. Chạy lại workflow để ghi lại config từ secret. |
| `/v1/models` trả 200 nhưng `data` rỗng | Chưa login account nào, hoặc token hết hạn/bị revoke → xem mục 4, kiểm tra `ls auths/`. |
| Login xong trình duyệt báo "không kết nối được localhost" | Tunnel SSH chưa mở hoặc sai cổng (Claude 54545, Codex 1455). |
| Gọi API bị 429/quota | Subscription hết hạn mức. Thêm account thứ 2 bằng cách login lần nữa — `routing.strategy: round-robin` sẽ tự chia tải. |
| Container `unhealthy` | `docker compose logs --tail 100`; healthcheck chỉ mở TCP tới 8317 nên unhealthy = tiến trình chết hoặc chưa bind được cổng. |
| vpn4 hết RAM | Stack bị chặn ở `mem_limit: 512m`; nếu đụng trần thì giảm tải hoặc nâng RAM — derper + vpn-gw cũng đang chạy trên 2GB. |

## 10. Lưu ý

Proxy này dùng chính subscription cá nhân (Claude Code / Codex) để phục vụ ứng dụng
khác. Tuân theo điều khoản của từng nhà cung cấp là trách nhiệm của người vận hành;
đừng chia sẻ API key ra ngoài phạm vi mình kiểm soát.
