# Hướng dẫn chuyển sang server mới (CI/CD tự động)

Chuyển toàn bộ stack Headscale sang **VPS mới `165.22.12.169`**, vẫn deploy tự động qua GitHub Actions (push → CI → SSH deploy).

> Hướng dẫn này **giữ nguyên domain** `vpn2.hangocthanh.io.vn`, chỉ đổi IP. Muốn đổi luôn domain → xem [Phụ lục A](#phụ-lục-a--nếu-đổi-sang-domain-mới). Muốn giữ các thiết bị đã đăng ký (không phải join lại) → xem [Phụ lục B](#phụ-lục-b--giữ-thiết-bị-đã-đăng-ký-migrate-data).

Vì workflow Deploy **tự bootstrap** (tự cài git/docker + clone repo), trên VPS mới bạn gần như chỉ cần: mở port + nạp SSH key + đổi vài giá trị → push.

---

## Checklist tổng

- [ ] B1. Chuẩn bị VPS mới `165.22.12.169` (mở port, SSH vào được)
- [ ] B2. Nạp deploy public key vào VPS mới
- [ ] B3. Đổi GitHub Secret `SSH_HOST` → `165.22.12.169`
- [ ] B4. Sửa `config/config.yaml`: DERP `ipv4` → `165.22.12.169`
- [ ] B5. Trỏ DNS `vpn2.hangocthanh.io.vn` → `165.22.12.169`
- [ ] B6. Commit + push → CI/CD tự deploy
- [ ] B7. Kiểm tra service lên (`/health`, cert, API)
- [ ] B8. Đưa thiết bị vào lại (hoặc Phụ lục B nếu giữ data)
- [ ] B9. Dọn server cũ `138.68.58.101`

---

## Bước 1 — Chuẩn bị VPS mới `165.22.12.169`

| Cần | Ghi chú |
|-----|---------|
| SSH vào được | user `root` (hoặc user có `sudo` không cần mật khẩu) |
| Mở port | **TCP 80, 443** (Caddy/TLS), **UDP 3478** (DERP/STUN), và cổng **SSH** (22) |
| Docker | **Không cần cài tay** — workflow tự cài lần đầu |

> ⚠️ **Quan trọng (lỗi đã gặp ở server cũ):** nếu nhà cung cấp có **Cloud Firewall** (DigitalOcean) thì phải mở các cổng trên ở đó nữa. Cổng SSH **bị chặn/DROP** sẽ làm deploy lỗi `dial tcp i/o timeout`. GitHub runner dùng **IP động** nên cổng SSH phải mở cho mọi IP (hoặc whitelist dải IP GitHub Actions).

Kiểm tra port sau khi mở (từ máy local):

```powershell
Test-NetConnection 165.22.12.169 -Port 22
```

---

## Bước 2 — Nạp deploy public key vào VPS mới

Dùng lại đúng deploy key cũ (`C:\Users\Hoanglong\keys\deploy_key`) → khỏi đổi secret `SSH_KEY`.

Xem public key trên máy local:

```powershell
Get-Content "$HOME\keys\deploy_key.pub"
```

SSH vào VPS mới rồi dán chuỗi đó vào `authorized_keys`:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "DÁN_PUBLIC_KEY_Ở_ĐÂY" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Test deploy key từ local (phải ra `OK`):

```powershell
ssh -i "$HOME\keys\deploy_key" root@165.22.12.169 "echo OK"
```

- `connection refused` → sai cổng SSH (đặt lại `SSH_PORT` ở B3).
- `i/o timeout` → firewall chặn cổng SSH (mở lại ở Bước 1).
- `Permission denied` → public key chưa vào đúng `authorized_keys` / sai user.

---

## Bước 3 — Đổi GitHub Secret `SSH_HOST`

Chỉ cần đổi **IP**. Các secret khác (`SSH_USER`, `SSH_KEY`, `SSH_PORT`, `DEPLOY_PATH`, `OAUTH2_PROXY_*`) **giữ nguyên** nếu user/cổng SSH không đổi.

```powershell
gh secret set SSH_HOST --repo vanbienperu3107/deployHeadscale --body "165.22.12.169"
```

Nếu VPS mới dùng cổng SSH khác 22, đổi thêm:

```powershell
gh secret set SSH_PORT --repo vanbienperu3107/deployHeadscale --body "CỔNG_SSH_MỚI"
```

Kiểm tra: `gh secret list --repo vanbienperu3107/deployHeadscale` → vẫn đủ 8 secret.

---

## Bước 4 — Sửa config trỏ IP mới

Chỉ **1 chỗ bắt buộc** (vì giữ domain): IP của DERP trong [`config/config.yaml`](../config/config.yaml).

```yaml
# config/config.yaml  (mục derp.server)
    ipv4: 165.22.12.169    # ← đổi từ 138.68.58.101 sang IP server mới
```

> DERP embedded quảng bá IP này cho client làm relay. Quên đổi → relay trỏ về server cũ, P2P fallback hỏng. `server_url`, `base_domain`, `Caddyfile`, `docker-compose.yml` **không đổi** vì giữ nguyên domain.

---

## Bước 5 — Trỏ DNS sang IP mới

Tại nhà quản lý domain, sửa bản ghi **A**:

```
vpn2.hangocthanh.io.vn   A   165.22.12.169
```

- Đợi DNS lan rồi kiểm tra: `nslookup vpn2.hangocthanh.io.vn` → phải ra `165.22.12.169`.
- `tail.hangocthanh.io.vn` (base_domain) **không cần** bản ghi A — nó chỉ dùng nội bộ cho MagicDNS.
- Hạ TTL trước vài giờ nếu muốn DNS đổi nhanh.

---

## Bước 6 — Commit + push → tự deploy

```powershell
cd "$HOME\deployHeadscale"
git add config/config.yaml
git commit -m "migrate: chuyen sang server moi 165.22.12.169"
git push origin main
```

Theo dõi pipeline:

```powershell
gh run watch --repo vanbienperu3107/deployHeadscale
```

Trình tự đúng: **CI** xanh ✅ → **Deploy** tự chạy (trigger `workflow_run`) → SSH vào `165.22.12.169` → tự cài docker + clone repo + `docker compose up -d --force-recreate`.

Nếu Deploy không tự kích hoạt, chạy tay:

```powershell
gh workflow run deploy.yml --repo vanbienperu3107/deployHeadscale
```

---

## Bước 7 — Kiểm tra service trên server mới

```bash
# Cert + control plane (đợi Caddy ~30–60s để xin cert Let's Encrypt cho IP mới)
curl -fsS https://vpn2.hangocthanh.io.vn/health        # → {"status":"pass"}

# API còn sống? (thay <APIKEY> bằng key thật)
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer <APIKEY>" https://vpn2.hangocthanh.io.vn/api/v1/node   # → 200
```

- Web UI: mở `https://vpn2.hangocthanh.io.vn/admin` → đăng nhập Google → vào Nodes (ô **URL** trong Settings = `https://vpn2.hangocthanh.io.vn`, **không** kèm `/admin`).
- Lỗi cert → DNS chưa trỏ IP mới hoặc 80/443 chưa mở.

---

## Bước 8 — Đưa thiết bị vào lại

> Bỏ qua bước này nếu bạn làm theo [Phụ lục B](#phụ-lục-b--giữ-thiết-bị-đã-đăng-ký-migrate-data) (giữ data — thiết bị tự nối lại).

Server mới khởi tạo **DB trống**, nên cần tạo user + cho thiết bị join lại:

```bash
# Trên VPS mới
docker exec headscale headscale users create votam
docker exec headscale headscale preauthkeys create --user votam --reusable --expiration 24h
# → hskey-xxxx
```

Trên từng máy (dùng `--reset` để ghi đè cấu hình cũ trỏ server cũ):

```powershell
tailscale up --reset --login-server=https://vpn2.hangocthanh.io.vn --authkey=hskey-xxxx
```

Android (app mới bỏ ô custom server) → web-auth:

```bash
docker exec headscale headscale nodes register --user votam --key <KEY_TỪ_ĐIỆN_THOẠI>
```

---

## Bước 9 — Dọn server cũ `138.68.58.101`

Chỉ làm **sau khi** server mới chạy ổn và thiết bị đã nối lại:

```bash
# Trên server cũ (nếu còn vào được)
cd /opt/deployHeadscale && docker compose down
```

Rồi huỷ Droplet cũ + xoá bản ghi DNS cũ. Giữ lại bản backup DB nếu cần (xem Phụ lục B).

---

## Phụ lục A — Nếu đổi sang domain mới

Ngoài các bước trên, khi đổi domain (vd `hs.example.com`) phải sửa thêm:

| File | Sửa |
|------|-----|
| [`config/config.yaml`](../config/config.yaml) | `server_url: https://hs.example.com` |
| [`config/config.yaml`](../config/config.yaml) | `base_domain:` (đổi nếu muốn base domain MagicDNS mới — phải khác `server_url`) |
| [`Caddyfile`](../Caddyfile) | dòng nhãn site → `hs.example.com {` |
| [`docker-compose.yml`](../docker-compose.yml) | oauth2-proxy: `--redirect-url=https://hs.example.com/oauth2/callback`, `--whitelist-domain=hs.example.com`, `--cookie-domain=hs.example.com` |

Và trong **Google Cloud Console → OAuth client**: thêm **Authorized redirect URI** mới `https://hs.example.com/oauth2/callback`. `oauth2-proxy/emails.txt` giữ nguyên.

---

## Phụ lục B — Giữ thiết bị đã đăng ký (migrate data)

Sao chép dữ liệu Headscale (DB + khoá noise/derp) từ server cũ sang mới → thiết bị **không cần join lại**, danh tính server được bảo toàn.

> Yêu cầu: vẫn truy cập được **server cũ** (SSH hoặc console nhà cung cấp).

**1) Backup trên server cũ** (dừng headscale để DB nhất quán):

```bash
cd /opt/deployHeadscale
docker compose stop headscale
docker run --rm --volumes-from headscale -v "$(pwd)":/backup alpine \
  tar czf /backup/hs-data.tar.gz -C /var/lib/headscale .
docker compose start headscale     # bật lại (hoặc cứ để down nếu sắp huỷ)
```

`--volumes-from headscale` mount đúng volume dữ liệu theo đường dẫn container, khỏi cần biết tên volume.

**2) Copy file sang server mới:**

```bash
scp -i ~/keys/deploy_key /opt/deployHeadscale/hs-data.tar.gz root@165.22.12.169:/tmp/
```

**3) Restore trên server mới** — làm **sau khi đã deploy lần đầu** (B6) để volume tồn tại:

```bash
cd /opt/deployHeadscale
docker compose stop headscale
docker run --rm --volumes-from headscale -v /tmp:/backup alpine \
  sh -c "cd /var/lib/headscale && rm -rf ./* && tar xzf /backup/hs-data.tar.gz"
docker compose start headscale
```

Sau đó các thiết bị tự nối lại (vì `server_url` + khoá server không đổi, IP DERP đã cập nhật ở B4). Kiểm tra: `docker exec headscale headscale nodes list` thấy đủ node cũ.

---

## Phụ lục C — Thành phần / cấu hình bổ sung (phải có khi dựng server mới)

Các thứ dưới đây **deploy tự động theo repo** (push → CI → deploy), nhưng cần biết để không quên phần cấu hình **bên ngoài repo** (Google Console, secret, bật/tắt cờ).

### C.1 — Admin Headplane (đăng nhập Google, không cần nhập key)
- Phục vụ tại `/admin` (Caddy route → `headplane`). Cấu hình: [`headplane/config.yaml`](../headplane/config.yaml).
- **Quan trọng:** đã ép `oidc.token_endpoint_auth_method: "client_secret_post"`. Nếu bỏ dòng này, openid-client v6 gửi `client_secret_basic` và **Google trả `invalid_client / "The OAuth client was not found"`** → SSO hỏng. headscale (Go) dùng post nên không bị; Headplane phải ép post.
- Secret cần (GitHub Secrets, workflow tự ghi vào `.env`): `HEADPLANE_HS_API_KEY` (1 headscale apikey), `HEADPLANE_COOKIE_SECRET` (chuỗi ngẫu nhiên). Tái dùng `OAUTH2_PROXY_CLIENT_ID/_SECRET` cho OIDC.
- Tạo lại khi cần: `docker exec headscale headscale apikeys create --expiration 8760h` → set vào secret `HEADPLANE_HS_API_KEY`.

### C.2 — Google OAuth: các redirect URI phải có
Trong Google Cloud Console → OAuth client (`pq2e20...`), mục **Authorized redirect URIs** phải có ĐỦ:
```
https://vpn2.hangocthanh.io.vn/oauth2/callback        (oauth2-proxy)
https://vpn2.hangocthanh.io.vn/oidc/callback          (headscale - đăng ký node)
https://vpn2.hangocthanh.io.vn/admin/oidc/callback    (headplane - admin)
```
Đổi domain → thêm bộ tương ứng. `allowed_users` (node) ở [`config/config.yaml`](../config/config.yaml); email admin sẽ là người đăng nhập Google đầu tiên vào `/admin`.

### C.3 — Tự duyệt route LAN (subnet routing)
[`config/acl.json`](../config/acl.json) có `autoApprovers.routes` cho `10.0.0.0/8` → owner là email user. Nhờ vậy máy "itop" chạy `--advertise-routes=10.0.0.0/8` được **duyệt tự động**, máy khác `--accept-routes` đi vào LAN qua nó (xem bản portable tailscale_mod). Server mới có sẵn vì deploy theo repo.

### C.4 — node-dedup (1 thiết bị = 1 node)
- Service [`node-dedup/dedup.py`](../node-dedup/dedup.py) (trong `docker-compose.yml`) poll headscale API, gộp node trùng theo **hostname**: xoá bản trùng offline + đổi tên node giữ lại về hostname sạch. Lưu lịch sử vào SQLite (volume `dedup_data`).
- Dùng `HEADPLANE_HS_API_KEY` sẵn có (không cần secret mới).
- **Mặc định chạy THẬT (live)** → tự gộp node trùng. Muốn kiểm tra trước (chỉ LOG kế hoạch, không xoá/đổi tên) thì set `DEDUP_DRY_RUN=true`:
  ```bash
  echo 'DEDUP_DRY_RUN=true' >> /opt/deployHeadscale/.env   # tren server
  docker compose up -d --force-recreate node-dedup
  docker logs node-dedup     # xem dong [DRY] ...
  ```
  (Logic đã có **unit test pytest trong CI** chạy trước mỗi deploy, nên live mặc định là an toàn. Lưu ý deploy ghi lại `.env` từ secrets, nên cờ thêm tay vào `.env` sẽ bị ghi đè ở lần deploy sau.)

### C.5 — Collector MAC + latency
**Kiến trúc (đã tách để chống lỗi 502):**
- `node-dedup` là **container RIÊNG** trên compose network (KHÔNG còn `network_mode: service:tailscale`). Nó phục vụ `/stats` + `/metrics/latency` từ SQLite. Caddy `handle /stats*` → `reverse_proxy node-dedup:8090`.
- `tailscale` sidecar tham gia tailnet như node **`collector`**: (1) cung cấp **LocalAPI** cho server tự ping; (2) là điểm có **IP tailnet** để node gửi MAC tới. `node-dedup` gọi LocalAPI qua **socket chia sẻ** (volume `ts_sock` ở `/var/run/tailscale` trên cả 2 container) — **không cần chung netns**.
- `ts-forward` (socat) chạy **trong netns sidecar** (có IP tailnet), đẩy `:8090` → `node-dedup:8090`. Nhờ vậy node vẫn POST MAC tới peer `collector` được dù `node-dedup` đã rời tailnet. Sidecar/forwarder chết thì chỉ MAC-report tạm ngừng, `/stats` vẫn sống.
- ⚠️ **Vì sao tách:** trước kia `node-dedup` nằm trong netns của sidecar. Khi thiếu `TS_AUTHKEY`, sidecar **restart-loop** → mỗi lần restart làm mất cổng 8090 → Caddy báo `dial tcp ...:8090: connect: connection refused` → **`/stats` 502**. Tách ra: `/stats` LUÔN sống, độc lập với sức khỏe của sidecar. (CI có test `stats-integration` dựng stack KHÔNG có sidecar và khẳng định `/stats` vẫn 200 + POST report 200.)

- **Nguồn latency CHÍNH = server tự ping:** mỗi vòng (`POLL_INTERVAL` = 30s) `node-dedup` đồng bộ danh sách node từ headscale API rồi gọi **LocalAPI `POST /localapi/v0/ping`** của sidecar (qua socket chia sẻ) để **tự ping** (disco) → ghi `node_latency` với `src=collector`. **Không phụ thuộc node có chạy gì hay không.** Cần `TS_AUTHKEY` để sidecar join; chưa có → ping fail nhẹ nhàng, `/stats` vẫn mở (chỉ trống số liệu).
- **CHỈ giám sát node SỐNG:** [`pingable_nodes`](../node-dedup/dedup.py) lọc ra **chỉ node `online`** (có IPv4 tailnet, khác `collector`) để ping; node **offline bỏ qua hoàn toàn**. Lý do: vòng ping là **tuần tự** và `localapi_ping` cho node chết phải chờ hết timeout (~8s/node) → nhiều node chết sẽ kéo vòng poll vượt xa 30s (trễ cả ping node sống lẫn dedup). Vậy nên `/stats` chỉ hiện các cặp node đang sống; node chết không sinh mẫu `ok=false` rác. (CI test `test_pingable_nodes_chi_online` + `test_server_ping_all_khong_ping_node_chet`.)
- **MAC (node tự báo cáo):** node chạy reporter (portable v1.4+) gửi `{hostname,ipv4,mac,samples[]}` tới peer `collector:8090/metrics/report` trong tailnet → qua `ts-forward` → `node-dedup` cập nhật `devices.mac`. Đây là cách DUY NHẤT lấy MAC (headscale không có). MAC chỉ lưu cho thiết bị đã có trong bảng `devices` (đã từng poll thấy).
- **Xác thực POST:** chấp nhận nguồn tailnet/loopback **hoặc** mạng docker nội bộ (`10/8, 172.16/12, 192.168/16`) — vì `ts-forward` (socat) làm mất IP tailnet gốc, `node-dedup` chỉ thấy IP compose. Compose network nội bộ (không publish) nên an toàn. GET `/stats`,`/metrics/latency` mở (đã gated SSO ở Caddy).
- **`TS_AUTHKEY` TỰ SINH (không cần làm tay):** deploy bước **[7/7]** tự kiểm: nếu chưa có secret/file thì tạo **preauth key reusable** trên headscale (`headscale preauthkeys create --user <first-user> --reusable --expiration 8760h`), lưu vào `$DEPLOY_PATH/.ts_authkey` (gitignored, 600), ghi vào `.env`, recreate `tailscale`+`ts-forward`. Lần deploy sau đọc lại file → KHÔNG tạo trùng. **Server mới**: tự sinh lại (chỉ cần đã có ≥1 user headscale = đã đăng nhập `/admin` 1 lần). Muốn ép key riêng: đặt secret `TS_AUTHKEY` (ưu tiên cao nhất).
- **GUI (khuyến nghị):** `https://vpn2.hangocthanh.io.vn/stats` — thẻ tổng quan + **biểu đồ** (Chart.js: avg latency mỗi cặp + RTT theo thời gian) + bảng latency + bảng thiết bị/MAC, tự refresh 30s. Đăng nhập **Google SSO** (oauth2-proxy) như `/admin`. Caddy `handle /stats*` → `reverse_proxy node-dedup:8090` (container riêng, độc lập sidecar); chỉ GET, đã gated SSO.
- **Nút trong panel:** trang `/admin` (Headplane) có 1 **nút nổi "📊 Thống kê"** góc dưới-phải → bấm mở `/stats`. Headplane không cho thêm link qua config, nên Caddy dùng plugin **replace-response** (xem `caddy/Dockerfile`) chèn nút vào HTML: `handle /admin*` có directive `replace </body> ...`. CI build image Caddy tùy biến này rồi mới `caddy validate`.
- **Dòng lệnh (tuỳ chọn):**
  ```bash
  # tren VPS (loopback duoc collector chap nhan):
  docker exec node-dedup python3 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8090/metrics/latency').read().decode())"
  # tu 1 node trong tailnet: curl http://collector:8090/metrics/latency (userspace: them --socks5-hostname 127.0.0.1:7654)
  ```
- **Khi dựng server mới:** đặt lại secret `TS_AUTHKEY` (tạo preauth key mới trên server mới). Code/Caddy/compose theo repo. Bảng `node_latency` ở volume `dedup_data`; state node collector ở volume `tailscale_collector` (Phụ lục B nếu muốn giữ).

---

## Khắc phục sự cố

| Triệu chứng | Nguyên nhân / cách xử lý |
|-------------|--------------------------|
| Deploy: `dial tcp ***:*** i/o timeout` | Firewall/Cloud Firewall VPS mới **chặn cổng SSH** (gói bị DROP). Mở cổng SSH cho mọi IP; kiểm tra Cloud Firewall của nhà cung cấp |
| Deploy: `connection refused` | Sai `SSH_PORT`, hoặc sshd chưa chạy trên VPS mới |
| Deploy: `Permission denied (publickey)` | Public key chưa vào `authorized_keys` đúng user / sai `SSH_USER` |
| `/health` lỗi, không có cert | DNS chưa trỏ `165.22.12.169`, hoặc 80/443 chưa mở |
| Client nối được nhưng P2P/relay chập chờn | Quên đổi DERP `ipv4` sang `165.22.12.169` (B4) |
| Thiết bị offline sau khi chuyển | Chọn "làm mới" mà chưa join lại (B8), hoặc client còn trỏ server cũ → `tailscale up --reset ...` |
| `/admin` cứ đòi nhập key | Ô **URL** trong Settings phải là `https://vpn2.hangocthanh.io.vn` (không kèm `/admin`) |
| `/admin` SSO lỗi "Authentication with the SSO provider failed"; log `invalid_client / The OAuth client was not found` | Headplane thiếu `oidc.token_endpoint_auth_method: client_secret_post` (Phụ lục C.1), hoặc thiếu redirect URI `/admin/oidc/callback` (C.2). Tạm vào bằng API key |
| Một máy tạo ra nhiều node (tên có hậu tố lạ) | Mỗi lần state mới (giải nén bản build vào thư mục khác) = machine key mới = node mới. Giữ 1 thư mục cố định; node-dedup (Phụ lục C.4) tự gộp |
| `/stats` lỗi **502** (`This page isn't working`) | Caddy không tới được collector. Xem `docker logs caddy` tìm `dial tcp ...:8090: connect: connection refused`. Nguyên nhân kinh điển: `node-dedup` từng nằm trong netns sidecar mà sidecar restart-loop (thiếu `TS_AUTHKEY`). **Đã sửa**: `node-dedup` là container riêng (Caddy → `node-dedup:8090`). Kiểm: `docker compose ps` (cả `node-dedup` lẫn `caddy` đều `Up`), `docker exec caddy wget -qO- http://node-dedup:8090/stats` |
| `/stats` có cặp node nhưng latency/biểu đồ trống (avg = `-`, mẫu > 0) | Server có ping nhưng tất cả **fail** (`ok=false`, rtt null) vì `collector` chưa join tailnet. Kiểm `docker logs node-dedup` phải thấy "server ping: **x/y** node OK" với x>0. Nếu 0/y: `TS_AUTHKEY` chưa có/không join → deploy [7/7] tự sinh key; xem `docker logs ts-collector` (đã join chưa). Cần ≥1 user headscale tồn tại để tự sinh key |
| Cột `mac` trống `(chua bao cao)` | (1) Node chưa chạy reporter (portable v1.4+) hoặc chưa thấy peer `collector` trong `tailscale status`. (2) `ts-forward` phải `Up`: `docker compose ps`. (3) Thiết bị phải đã có trong `devices` (đã poll thấy) thì MAC mới gán. (4) `collector` đã join chưa (cần `TS_AUTHKEY`) |
| `docker logs ts-collector` báo lỗi đăng nhập | `TS_AUTHKEY` sai/hết hạn → xoá `$DEPLOY_PATH/.ts_authkey` để deploy [7/7] tự sinh key mới (hoặc đặt secret `TS_AUTHKEY` thủ công) rồi deploy lại |
| Node `collector` bị trùng / nhiều bản | Mỗi lần volume `tailscale_collector` mất state → join lại = node mới. node-dedup tự gộp (C.4); preauth key nên `--reusable` |
| Card DERP `vpnX-vn` trên `/derp` báo `<urlopen error timed out>` dù server mới đã `/derp/probe` 200 | **DNS cache cũ trên vpn2.** Sau khi đổi IP DERP relay, systemd-resolved trên vpn2 còn cache IP cũ (đã chết) → node-dedup probe ra IP cũ → timeout. Sửa: `resolvectl flush-caches` rồi `docker restart node-dedup`. Kiểm: `docker exec node-dedup python3 -c "import socket;print(socket.gethostbyname('vpnX.hangocthanh.io.vn'))"` phải ra IP mới |

---

## Phụ lục D — Chuyển / Thêm DERP relay

### D.1 — Kiến trúc DERP hiện tại (3 region)

| Server | Vai trò | Region |
|--------|---------|--------|
| `vpn2.hangocthanh.io.vn` (165.22.12.169) | Headscale control plane + **embedded DERP relay** | 999 (`myderp`) |
| `vpn3.hangocthanh.io.vn` (64.176.23.196) | **DERP relay** (derper) | 1000 (`vpn3-vn`) |
| `vpn4.hangocthanh.io.vn` (149.104.66.174) | **DERP relay** (derper) | 1001 (`vpn4-vn`) |

Tailscale client **tự đo latency cả 3 region** và chọn con **gần nhất** (latency thấp nhất) mỗi vài giây. Không cần cấu hình phía client. Không dùng `avoid: true` — tất cả region bình đẳng.

### D.2 — Hành vi khi một server chết

**vpn3 hoặc vpn4 (DERP relay) chết:**
- Tailscale phát hiện ~5–15s (DERP heartbeat timeout).
- Client tự chuyển sang 1 trong 2 region còn lại — **không cần can thiệp**.
- Khi server hồi phục, client tự load-balance lại theo latency.

**vpn2 (headscale control plane) chết:**
- Các kết nối WireGuard peer-to-peer đang hoạt động **vẫn tiếp tục**.
- DERP relay vpn3 (1000) và vpn4 (1001) **vẫn hoạt động** — relay không phụ thuộc headscale.
- Node **không thể re-auth** hoặc join mới cho đến khi vpn2 khôi phục.
- Khôi phục: restart stack vpn2, các node tự reconnect.

### D.3 — Chuyển vpn3 sang VPS mới

1. **Chuẩn bị VPS mới** — mở port TCP 80, 443 và UDP 3478.

2. **Cập nhật GitHub Secrets:**

   | Secret | Giá trị cũ | Giá trị mới |
   |--------|-----------|------------|
   | `SSH_HOST_VPN3` | IP cũ | IP VPS mới |

3. **Cập nhật `config/derp.yaml`** — đổi `ipv4` của node vpn3:
   ```yaml
   nodes:
     - name: "vpn3-vn-1"
       hostname: "vpn3.hangocthanh.io.vn"
       ipv4: "<IP_MỚI>"
   ```

4. **Trỏ DNS** `vpn3.hangocthanh.io.vn` → IP VPS mới.

5. **Commit + push** → CI validate → Deploy DERP tự SSH vào VPS mới.

6. **Kiểm tra:** `curl -sk https://vpn3.hangocthanh.io.vn/derp/probe` → `200 OK`.

7. **Restart headscale** trên vpn2 để nạp lại `derp.yaml`:
   ```bash
   docker compose restart headscale
   ```
   Client sẽ nhận DERP map mới trong vòng 30–60s.

### D.4 — Chuyển vpn4 sang VPS mới

Tương tự D.3 nhưng dùng secret `SSH_HOST_VPN4` và `config/derp.yaml` region 1001:

1. Đổi `SSH_HOST_VPN4` → IP VPS mới.
2. Đổi `ipv4: "<IP_MỚI>"` trong region `1001` của `config/derp.yaml`.
3. Trỏ DNS `vpn4.hangocthanh.io.vn` → IP mới.
4. Commit + push → CI → Deploy DERP (vpn4) tự deploy.
5. Kiểm tra: `curl -sk https://vpn4.hangocthanh.io.vn/derp/probe` → `200 OK`.
6. Restart headscale trên vpn2: `docker compose restart headscale`.

### D.5 — Thêm DERP region thứ 4+

1. Thêm region mới (ID tăng dần) vào `config/derp.yaml`.
2. Tạo thư mục `derp-vpnN/docker-compose.yml` theo mẫu `derp-vpn4/docker-compose.yml` (đổi hostname).
3. Tạo `deploy-derp-vpnN.yml` theo mẫu `deploy-derp-vpn4.yml` (đổi `SSH_HOST_VPNN`, health probe URL).
4. Thêm secret `SSH_HOST_VPNN` vào GitHub.
5. Bootstrap SSH key trên VPS mới (xem DEPLOYMENT.md).
6. Commit + push → CI → auto-deploy.

---

> Tham chiếu: dựng từ đầu xem [DEPLOYMENT.md](DEPLOYMENT.md); chi tiết CI/CD xem [CICD.md](CICD.md).
