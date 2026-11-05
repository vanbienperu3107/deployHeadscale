# edge-vpn4 — chia sẻ cổng 443 giữa DERP, CLIProxyAPI và hai OpenCode độc lập

vpn4 chỉ có **một IP công khai** (`149.104.66.174`, không IPv6) nhưng cần nhiều dịch vụ
trên cổng 443:

| Dịch vụ | Lý do phải đi qua 443 |
|---|---|
| `derper` (DERP relay) | Mọi peer trong tailnet đều relay qua `vpn4-vn`; client sau proxy hạn chế chỉ ra được 443 |
| `CLIProxyAPI` | Mạng của người dùng gần như chỉ cho `CONNECT :443` |
| `opencode-server` | Cho client bên ngoài tailnet (vd. Zed) nối tới OpenCode remote qua HTTPS |
| `opencode2` | OpenCode v2 public deployment, độc lập với v1 ở backend, listener, log và fail2ban |

## Kiến trúc

```
Internet :443
     │
     ▼
nginx (stream + ssl_preread, KHÔNG giải mã TLS)
     ├── SNI vpn4.hangocthanh.io.vn ─────┐
     ├── (không có SNI / không khớp) ────┤──→ derper:443   ← TLS + cert của chính derper
     ├── SNI cliproxy.hangocthanh.io.vn ──→ caddy-edge:8444 ──→ cliproxy:8317
     ├── SNI opencode.hangocthanh.io.vn ──→ 127.0.0.1:8446 ──PROXY──→ caddy-edge:8445 ──→ opencode-server:4096
     └── SNI opencode2.hangocthanh.io.vn ─→ 127.0.0.1:8451 ──PROXY──→ caddy-edge:8450 ──→ opencode2:4096

Cổng 80  → derper (ACME HTTP-01 của autocert)
Cổng 3478/udp → derper (STUN, nginx không proxy UDP)
Cổng 28417 → cliproxy (đường cũ, giữ nguyên cho máy đã cấu hình)
```

**fail2ban cho opencode v1 (2026-08-30):** log Caddy ghi nhận scanner Internet quét
`opencode.hangocthanh.io.vn` liên tục (401 hàng loạt, UA giả). Đã thêm:
nginx tách nhánh opencode qua chặng nội bộ `127.0.0.1:8446` gắn **PROXY
protocol** (bắt buộc — không có nó Caddy chỉ thấy IP nội bộ của nginx, ban vô
nghĩa); Caddy `:8445` chỉ tin header từ Docker network `172.16.0.0/12`, ghi log JSON
riêng `/var/log/caddy/opencode-access.log`; fail2ban đọc file đó, **5 lần 401/10
phút → ban IP 1 giờ** tại iptables host. DERP/cliproxy không đổi đường đi.
Xem jail/filter trong `fail2ban/`. Kiểm tra IP đang bị ban:
`docker exec edge-fail2ban fail2ban-client status opencode-401`.

**OpenCode v2 là đường hoàn toàn riêng:** nginx SNI chuyển `opencode2` qua
`127.0.0.1:8451`, gắn PROXY protocol đến Caddy `:8450`; listener đó chỉ tin dải
Docker `172.16.0.0/12`, dùng TLS-ALPN và reverse proxy `opencode2:4096` với
`flush_interval -1` cho SSE. Caddy ghi JSON riêng tại
`/var/log/caddy/opencode2-access.log`; jail `opencode2-401` đọc đúng file này và
ban 5 lần 401/10 phút trong 1 giờ qua `DOCKER-USER`. Xem trạng thái bằng
`docker exec edge-fail2ban fail2ban-client status opencode2-401`.

**Cảnh báo bảo mật riêng cho `opencode-server`:** tiến trình này được phép chạy `bash`
và sửa file trong workspace (xem [[opencode-api-do-duoc]]). Route này lộ nó ra Internet —
lớp bảo vệ DUY NHẤT là HTTP Basic Auth (`OPENCODE_SERVER_PASSWORD`) mà chính
opencode-server thực thi. **Không được** thêm bypass/anonymous path vào Caddyfile.
Workflow deploy chỉ cảnh báo (không fail) nếu backend chưa chạy, để không làm
CLIProxyAPI không vào được, chứ **không được làm chết DERP**.

## Đường truy cập

| URL | Khi nào dùng |
|---|---|
| `https://vpn4.hangocthanh.io.vn` | DERP relay (Tailscale tự dùng, không cần cấu hình thủ công) |
| `https://cliproxy.hangocthanh.io.vn/v1` | Mạng chỉ cho 443 (mặc định nên dùng) |
| `http://149.104.66.174:28417/v1` | Đường cũ, vẫn chạy, không TLS |
| `https://opencode.hangocthanh.io.vn` | OpenCode remote (API opencode-server, Basic Auth) |
| `https://opencode2.hangocthanh.io.vn` | OpenCode v2 (Basic Auth; backend `opencode2:4096`) |

## Triển khai

Yêu cầu trước: bản ghi DNS `A cliproxy.hangocthanh.io.vn → 149.104.66.174`,
`A opencode.hangocthanh.io.vn → 149.104.66.174` và
`A opencode2.hangocthanh.io.vn → 149.104.66.174`.
Workflow kiểm tra DNS **trước khi** đụng tới derper — thiếu là dừng ngay, DERP không suy suyển.
Sau thay đổi bind mount, workflow recreate đúng `nginx`, `caddy-edge` và
`fail2ban` với `--force-recreate`; không deploy backend OpenCode v2. Sau khi các
container lên,
workflow giữ các smoke test DERP, CLIProxy, OpenCode v1 và kiểm tra
`https://opencode2.hangocthanh.io.vn/global/health` **không có credentials**:
`401` là thành công, `200` là lỗi bảo mật và fail job; trạng thái khác chỉ cảnh
báo khi backend v2 chủ ý chưa deploy.
Stack `opencode-server` tự nó nằm ở repo `TelegramAgent` (`/opt/opencode`, deploy qua
`deploy.yml` của repo đó) — workflow của `edge-vpn4` chỉ tạo đường route, không khởi
động opencode-server; nếu chưa deploy stack đó thì route trả 502, không phải lỗi ở đây.

### Rollback

Nếu deploy làm hỏng route hoặc DERP không còn trả lời:

1. Từ VPS, dừng edge stack: `cd /opt/deployHeadscale/edge-vpn4 && docker compose down`.
2. Khôi phục `443:443` cho derper trong `derp-vpn4/docker-compose.yml`.
3. Khởi động lại derper: `cd ../derp-vpn4 && docker compose up -d`.
4. Kiểm tra `https://vpn4.hangocthanh.io.vn/derp/probe` trả 200.
5. Rồi revert commit tương ứng trên `main` để lần deploy sau không lặp lại.

## Sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `https://cliproxy.hangocthanh.io.vn` báo lỗi chứng chỉ | Caddy chưa xin được cert. `docker logs caddy-edge`; kiểm tra DNS đã trỏ đúng và nginx đang chạy (TLS-ALPN đi xuyên nginx). |
| `https://opencode.hangocthanh.io.vn` trả 502 | opencode-server chưa chạy hoặc chưa vào mạng `edge` — kiểm `docker network inspect edge` ở máy đang chạy stack `/opt/opencode`. |
| `https://opencode.hangocthanh.io.vn` (hoặc `cliproxy...`) trả HTTP 000 / lỗi TLS ngay cả khi backend healthy | **Bẫy đã gặp thật (2026-08-27)**: `nginx.conf`/`Caddyfile` là bind mount, `docker compose up -d` không phát hiện nội dung file đổi (chỉ so hash service/image/env) nên container cũ vẫn chạy cấu hình cũ vô thời hạn dù deploy "thành công" nhiều lần. Deploy workflow đã sửa dùng `--force-recreate` ở bước bật nginx+caddy; nếu vẫn gặp lại (sửa tay ngoài workflow) thì `docker compose up -d --force-recreate nginx caddy-edge`. |
| `https://opencode2.hangocthanh.io.vn` không xác thực không trả 401 | Backend OpenCode v2 chưa chạy/không ở network `edge` thì workflow chỉ cảnh báo; trả **200** là sự cố bảo mật, phải tắt route và kiểm tra Basic Auth ngay. |
| `https://opencode.hangocthanh.io.vn` trả 200 không cần mật khẩu | **Sự cố bảo mật nghiêm trọng** — `OPENCODE_SERVER_PASSWORD` rỗng hoặc chưa được nạp vào `opencode-server`. Tắt route ngay (dừng `edge-vpn4` hoặc xoá nhánh opencode khỏi `nginx.conf`) cho tới khi xác nhận lại biến môi trường. |
| DERP chết sau khi deploy | `docker logs edge-nginx` xem SNI có vào đúng `derper` không; kiểm tra `docker network inspect edge` có cả derper lẫn nginx. Không cứu được thì rollback ở trên. |
| Client "đứng hình" khi model đang trả lời | Thiếu `flush_interval -1` trong Caddyfile → phản hồi SSE bị đệm. |
