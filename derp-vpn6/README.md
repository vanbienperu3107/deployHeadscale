# vpn6 — DERP chuẩn (derper) dùng chung cổng 443 qua sslh

> Nhánh `vpn6-derper-sslh`. **Chưa deploy prod.** Mục tiêu: vpn6 chạy **derper chuẩn
> giống vpn4** (tự lo TLS + STUN, handshake DERP trả `101`), thay cho custom relay
> tcp/udp (relay-vpn6) vốn không hoạt động như DERP thật (trả `426` qua Caddy).

## Bối cảnh cổng trên vpn6 (box memory-stack)
- **80** = Caddy memory-caddy (HTTP/ACME) — **không đụng**.
- **443** = **sslh** (đang dạng CLI đơn giản: `--ssh 127.0.0.1:22 --tls 127.0.0.1:8443`).
  → Hiện sslh đẩy **toàn bộ TLS → `127.0.0.1:8443` = Caddy**. **Chưa route theo SNI.**
- **8443** = Caddy (HTTPS nội bộ, nhận từ sslh). **derper KHÔNG được dùng 8443.**
- **3478/udp** = trống (STUN sẽ dùng).

## Giải pháp (sạch, không mix code)
- derper nghe TLS **nội bộ** `127.0.0.1:8444` (KHÔNG phải 8443 của Caddy).
- **Nâng sslh** từ dạng CLI → dạng **config có `sni_hostnames`**, route:
  - SNI `vpn6.hangocthanh.io.vn` → `127.0.0.1:8444` (derper)
  - còn lại (gồm `claude.hangocthanh.io.vn`) → `127.0.0.1:8443` (Caddy, như cũ)
  - SSH → `127.0.0.1:22` (như cũ)
- sslh forward **raw TLS** (không giải mã) → derper tự terminate TLS + tự xin cert
  Let's Encrypt qua **TLS-ALPN-01** (challenge `acme-tls/1` cũng mang SNI=vpn6 nên sslh
  route đúng vào derper).
- STUN `3478/udp` mở thẳng ra host. Cổng 80 vẫn của Caddy (`--http-port=-1`).

```
   :443 (public)                              :80 (public, KHÔNG đổi)
        │                                          │
     [ sslh ]  ── route theo SNI                [ Caddy :80 ]
     /        \
 vpn6→127.0.0.1:8444     else→127.0.0.1:8443
      │                        │
  [ derper ]               [ Caddy HTTPS ]  (claude.hangocthanh.io.vn ...)
  TLS-ALPN cert, DERP 101,
  STUN :3478/udp
```

## Rule sslh — CHUYỂN từ CLI sang config (TEMPLATE, chỉnh theo bản sslh thật)

sslh-select/sslh-ev hỗ trợ `sni_hostnames`. Tạo `/etc/sslh/sslh.cfg` (hoặc sửa
`/etc/default/sslh` để trỏ tới config này), đặt rule vpn6 **TRƯỚC** rule TLS catch-all:

```conf
verbose: false;
listen: ( { host: "0.0.0.0"; port: "443"; } );
protocols:
(
    { name: "ssh";  host: "127.0.0.1"; port: "22"; },

    # >>> THEM: vpn6 SNI -> derper. PHAI dat truoc rule tls catch-all duoi.
    { name: "tls"; host: "127.0.0.1"; port: "8444"; sni_hostnames: [ "vpn6.hangocthanh.io.vn" ]; },

    # (giu nhu cu) moi TLS khac -> Caddy 8443
    { name: "tls"; host: "127.0.0.1"; port: "8443"; }
);
```

> Nếu bản sslh trên box **không** hỗ trợ `sni_hostnames`, cần `apt install` bản
> `sslh` mới (sslh-select ≥ v1.21) hoặc dùng `sslh-ev`. **Xác nhận khi recon mai.**

## Cutover (làm trên box vpn6 — MAI, sau khi CI xanh)

> Thay đổi mạng trên **box prod memory-stack** → làm cẩn thận, có rollback.

1. **Recon**: đọc lệnh/cấu hình sslh thật (`systemctl cat sslh` / `/etc/default/sslh`),
   xác nhận bản sslh có hỗ trợ SNI, 8443 đúng là Caddy, 8444 trống. **Backup** mọi file đụng tới.
2. **Up derper** (chưa đụng sslh):
   ```bash
   cd $DEPLOY_PATH/derp-vpn6 && docker compose up -d --build
   sudo ufw allow 3478/udp
   ss -tln | grep 8444     # derper LISTEN noi bo (cert chua co la binh thuong)
   ```
3. **Chuyển sslh sang config có SNI** (template trên) → test cú pháp → restart sslh.
4. **Chờ cert** (≈10–60s, derper xin LE qua TLS-ALPN-01). Kiểm tra:
   ```bash
   curl -sk -i -H "Upgrade: DERP" -H "Connection: Upgrade" https://vpn6.hangocthanh.io.vn/derp | head
   # KY VONG: HTTP/1.1 101 Switching Protocols + Derp-Public-Key  (KHONG con 426)
   ```
5. **Kiểm tra memory-stack KHÔNG vỡ**: `curl -I https://claude.hangocthanh.io.vn` vẫn 200/302.
6. **Headscale**: region 1003 trong `config/derp.yaml` giữ `derpport: 443` (cổng public
   client gọi, sslh route), `stunport: 3478`. Reload headscale để client nhận map mới.
7. **Xác minh thật**: 1 node tailnet → `tailscale netcheck` thấy region 1003 có latency;
   dashboard `/derp` thấy `vpn6-vn` online + đo được.
8. (Tùy chọn) Gỡ block Caddy `vpn6...` trong Caddyfile — không còn cần (sslh chặn vpn6
   trước khi tới Caddy); để lại cũng vô hại.

## Rollback (nếu hỏng)
1. Khôi phục cấu hình sslh từ backup → restart sslh (memory-stack về như cũ ngay).
2. `cd derp-vpn6 && docker compose down`.
3. (Tùy chọn) bật lại relay-vpn6 cũ: stack relay vẫn còn trên `main`, không bị xóa.

## Lưu ý
- **Không** xóa code relay tcp/udp (relay-vpn5/relay-vpn6) — vẫn còn trên `main`.
- Khác biệt duy nhất so với vpn4: port nội bộ `:8444` + `--http-port=-1` (cert TLS-ALPN).
  Phần còn lại (derper, STUN, ts sidecar, ping-reporter) **y hệt vpn4**.
