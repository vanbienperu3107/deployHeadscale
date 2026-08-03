# edge-vpn4 — chia sẻ cổng 443 giữa DERP và CLIProxyAPI

vpn4 chỉ có **một IP công khai** (`149.104.66.174`, không IPv6) nhưng cần hai dịch vụ
trên cổng 443:

| Dịch vụ | Vì sao phải là 443 |
|---|---|
| `derper` (DERP relay) | Mọi peer trong tailnet đều relay qua `vpn4-vn`; client sau proxy hạn chế chỉ ra được 443 |
| `CLIProxyAPI` | Mạng của người dùng gần như chỉ cho `CONNECT :443` |

## Kiến trúc

```
Internet :443
     │
  nginx (ssl_preread — CHỈ đọc SNI, không giải mã)
     ├── SNI vpn4.hangocthanh.io.vn ─────┐
     ├── (không có SNI / không khớp) ────┤──→ derper:443   ← TLS + cert của chính derper
     └── SNI cliproxy.hangocthanh.io.vn ──→ caddy-edge:8444 ──→ cliproxy:8317

Cổng 80  → derper (ACME HTTP-01 của autocert)
Cổng 3478/udp → derper (STUN, nginx không proxy UDP)
Cổng 28417 → cliproxy (đường cũ, giữ nguyên cho máy đã cấu hình)
```

Điểm mấu chốt: nginx **không** terminate TLS. Nó chỉ đọc trường SNI trong ClientHello
rồi nối TCP thẳng. Nhờ vậy:

- derper giữ nguyên chứng chỉ autocert và cách nó tự xử lý TLS — hành vi DERP không đổi,
  chỉ khác chỗ ai bind cổng trên host.
- Chi phí CPU gần như bằng 0, quan trọng vì vpn4 là relay chính của cả tailnet.
- Đổi lại: **không định tuyến được theo đường dẫn**, mỗi dịch vụ phải có tên miền riêng.

`default` trong bảng SNI cố ý trỏ về derper: cấu hình tên miền sai thì cùng lắm là
CLIProxyAPI không vào được, chứ **không được làm chết DERP**.

## Endpoint

| Đường | Dùng khi |
|---|---|
| `https://cliproxy.hangocthanh.io.vn/v1` | Mạng chỉ cho 443 (mặc định nên dùng) |
| `http://149.104.66.174:28417/v1` | Đường cũ, vẫn chạy, không TLS |

## Triển khai

Yêu cầu trước: bản ghi DNS `A cliproxy.hangocthanh.io.vn → 149.104.66.174`.
Workflow kiểm tra DNS **trước khi** đụng tới derper — thiếu là dừng ngay, DERP không suy suyển.

```bash
gh workflow run deploy-edge-vpn4.yml --ref main
```

Thứ tự cắt chuyển trong workflow: kiểm tra DNS → tạo mạng `edge` → kiểm cú pháp
`nginx.conf` → recreate derper (nhả 443) → recreate cliproxy → bật nginx + Caddy
(giành 443) → verify từ Internet cả `/derp/probe`, `cliproxy` qua 443, và đường cũ 28417.

## Chứng chỉ

- `vpn4.hangocthanh.io.vn` — do **derper** tự xin qua ACME HTTP-01 trên cổng 80. Không đổi.
- `cliproxy.hangocthanh.io.vn` — do **Caddy** xin qua **TLS-ALPN-01** trên cổng 8444.
  Không dùng HTTP-01 được vì cổng 80 thuộc về derper; nginx chuyển tiếp đúng SNI nên
  Let's Encrypt vẫn bắt tay được. Chứng chỉ nằm trong volume `caddy_edge_data` — mất là
  phải xin lại (có rate limit của Let's Encrypt, 5 lần/tuần cho mỗi tên miền).

## Rollback

Nếu DERP có vấn đề sau khi cắt chuyển:

```bash
cd /opt/deployHeadscale/edge-vpn4 && docker compose down
cd /opt/deployHeadscale/derp-vpn4
# tạm thời trả 443 cho derper
sed -i 's|- "3478:3478/udp"|- "443:443"\n      - "3478:3478/udp"|' docker-compose.yml
docker compose up -d
```

Rồi revert commit tương ứng trên `main` để lần deploy sau không lặp lại.

## Sự cố thường gặp

| Triệu chứng | Nguyên nhân / xử lý |
|---|---|
| `https://cliproxy.hangocthanh.io.vn` báo lỗi chứng chỉ | Caddy chưa xin được cert. `docker logs caddy-edge`; kiểm tra DNS đã trỏ đúng và nginx đang chạy (TLS-ALPN đi xuyên nginx). |
| DERP chết sau khi deploy | `docker logs edge-nginx` xem SNI có vào đúng `derper` không; kiểm tra `docker network inspect edge` có cả derper lẫn nginx. Không cứu được thì rollback ở trên. |
| Client "đứng hình" khi model đang trả lời | Thiếu `flush_interval -1` trong Caddyfile → phản hồi SSE bị đệm. |
| Kết nối DERP bị ngắt sau ~10 phút | `proxy_timeout` trong `nginx.conf` quá ngắn. Đang đặt 1h. |
| `docker compose up` báo thiếu network `edge` | `docker network create edge` rồi chạy lại. Các workflow deploy đều tự tạo. |

## Chuyển sang server khác

1. **Chuẩn bị máy mới**: Docker + Docker Compose, cổng 443/80/3478 chưa ai dùng.
2. **Trỏ DNS**: cả `vpn4.hangocthanh.io.vn` (hoặc tên mới cho DERP) và
   `cliproxy.hangocthanh.io.vn` phải trỏ về IP máy mới **trước khi** deploy — cả derper
   lẫn Caddy đều xin chứng chỉ theo tên miền.
3. **Sửa `nginx.conf`** nếu đổi tên miền: cập nhật khoá trong khối `map`. Giữ nhánh
   `default` trỏ về derper.
4. **Sửa workflow**: `deploy-edge-vpn4.yml` đang dùng `secrets.SSH_HOST_VPN4`; đổi sang
   secret host mới, và đổi `concurrency.group` nếu máy mới không phải vpn4.
5. **Thứ tự deploy trên máy mới**: `docker network create edge` → derp → cliproxy → edge.
6. **Chứng chỉ**: không cần bê theo. Cả hai đều tự xin mới. Nếu muốn tránh rate limit của
   Let's Encrypt thì copy volume `caddy_edge_data` và `derper_certs` sang.
7. **Cập nhật DERPMap**: region của vpn4 trong DB (`derp_servers`) phải trỏ tới IP/hostname
   mới — xem `docs/derp-management.md`.
8. **Tắt máy cũ** sau khi `https://<host-moi>/derp/probe` trả 200 và client đã chuyển region.
