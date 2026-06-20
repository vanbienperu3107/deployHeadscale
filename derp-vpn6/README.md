# vpn6 — DERP chuẩn (derper) dùng chung cổng 443 qua sslh

> Nhánh `vpn6-derper-sslh`. **Chưa deploy prod.** Mục tiêu: vpn6 chạy **derper chuẩn
> giống vpn4** (tự lo TLS + STUN, handshake DERP trả `101`), thay cho custom relay
> tcp/udp (relay-vpn6) vốn không hoạt động như DERP thật (trả `426` qua Caddy).

## Vì sao cần sslh
vpn6 là box **memory-stack** (`claude.hangocthanh.io.vn`). Cổng 443 đã có **sslh**
nghe sẵn (multiplex SSH/TLS). derper không thể tự chiếm 443. Giải pháp **sạch, không
mix code**:

- derper nghe TLS **nội bộ** `127.0.0.1:8443`.
- sslh (đã có) thêm **1 rule SNI**: `vpn6.hangocthanh.io.vn` → `127.0.0.1:8443` (derper);
  mọi SNI khác giữ nguyên → Caddy memory-stack.
- sslh forward **raw TLS** (không giải mã) → derper tự terminate TLS + tự xin cert
  Let's Encrypt qua **TLS-ALPN-01** (challenge `acme-tls/1` cũng mang SNI=vpn6 nên sslh
  route đúng vào derper).
- STUN `3478/udp` mở thẳng ra host (UDP, sslh không đụng tới).
- Cổng 80 vẫn của Caddy memory-stack — **không đụng** (derper dùng `--http-port=-1`).

```
          :443 (public)                          :80 (public, KHÔNG đổi)
              │                                       │
           [ sslh ]                                [ Caddy memory-stack ]
         /         \  (SNI)
  vpn6...→127.0.0.1:8443    else→Caddy(:9443 nội bộ)
        │
     [ derper ]  ── TLS-ALPN cert, DERP 101, STUN :3478/udp
```

## Rule sslh cần thêm (TEMPLATE — chỉnh theo config thật của box)

sslh kiểu config-file (`sslh-select`/`sslh-ev`, hỗ trợ `sni_hostnames`). Thêm protocol
**TRƯỚC** rule TLS catch-all (đầu danh sách `protocols` match trước):

```conf
protocols:
(
    # >>> THEM: vpn6 SNI -> derper noi bo. Phai dat TRUOC rule tls -> caddy.
    { name: "tls"; host: "127.0.0.1"; port: "8443"; sni_hostnames: [ "vpn6.hangocthanh.io.vn" ]; },

    # (giu nguyen) cac rule cu, vi du:
    # { name: "ssh"; host: "127.0.0.1"; port: "22"; },
    # { name: "tls"; host: "127.0.0.1"; port: "9443"; },   # catch-all TLS -> Caddy
);
```

> Nếu sslh trên box là bản **chỉ phân biệt protocol** (không có `sni_hostnames`), cần
> nâng lên `sslh-select`/`sslh-ev` ≥ v1.21 để route theo SNI. **Xác nhận khi recon mai.**

## Cutover (làm trên box vpn6 — MAI, sau khi CI xanh)

> Đây là thay đổi mạng trên **box prod memory-stack** → làm cẩn thận, có rollback.

1. **Recon** config sslh thật: tìm file config, cổng nội bộ Caddy đang nhận TLS
   (vd `127.0.0.1:9443`), bản sslh có hỗ trợ SNI không. Backup file config sslh.
2. **Up derper** (chưa đụng sslh):
   ```bash
   cd $DEPLOY_PATH/derp-vpn6 && docker compose up -d --build
   sudo ufw allow 3478/udp
   curl -sk https://127.0.0.1:8443/derp/probe   # noi bo, derper song chua (co the 000 truoc khi co cert)
   ```
3. **Thêm rule SNI** vào sslh (xem template trên) → `sslh -t` (test config nếu có) →
   restart/reload sslh.
4. **Chờ cert**: derper xin LE qua TLS-ALPN-01 (≈10–60s). Kiểm tra:
   ```bash
   curl -sk -i -H "Upgrade: DERP" -H "Connection: Upgrade" https://vpn6.hangocthanh.io.vn/derp | head
   # KY VONG: HTTP/1.1 101 Switching Protocols + Derp-Public-Key  (KHONG con 426)
   ```
5. **Kiểm tra memory-stack KHÔNG vỡ**: `curl -I https://claude.hangocthanh.io.vn` vẫn 200/302.
6. **Headscale**: region 1003 trong `config/derp.yaml` giữ `derpport: 443` (cổng public
   client gọi, sslh route), `stunport: 3478`. Reload headscale để client nhận map mới.
7. **Xác minh thật**: từ 1 node tailnet → `tailscale netcheck` thấy region 1003 có latency;
   dashboard `/derp` thấy `vpn6-vn` online + đo được.

## Rollback (nếu hỏng)
1. Khôi phục file config sslh từ backup → reload sslh (memory-stack về như cũ ngay).
2. `cd derp-vpn6 && docker compose down`.
3. (Tùy chọn) bật lại relay-vpn6 cũ: stack relay vẫn còn trên `main`, không bị xóa.

## Lưu ý
- **Không** xóa code relay tcp/udp (relay-vpn5/relay-vpn6) — vẫn còn trên `main`.
- Khác biệt duy nhất so với vpn4: port nội bộ `:8443` + `--http-port=-1` (cert TLS-ALPN).
  Phần còn lại (derper, STUN, ts sidecar, ping-reporter) **y hệt vpn4**.
