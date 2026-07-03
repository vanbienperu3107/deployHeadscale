# DERP vpn4-v2 — derper v1.100.0 + cutover domain vpn5

> Nguồn chuẩn: file `.md` này. Bản `DERP-VPN4-V2-CUTOVER.html` (cùng thư mục)
> là bản đọc offline, nội dung tương đương.

## 0. Tóm tắt

- Thêm **instance derper thứ 2** chạy trên cùng host **vpn4** (149.104.66.174),
  pin `TAILSCALE_VERSION=v1.100.0` (bản chính thức mới nhất từ
  `tailscale/tailscale` tại thời điểm triển khai — mới hơn `v1.80.0` đang
  chạy ở `derp-vpn3/`, `derp-vpn4/`, `derp-relay/`).
- Instance mới dùng domain **`vpn5.hangocthanh.io.vn`** — **cutover** từ
  server vpn5 cũ (204.199.161.89, stack `relay-vpn5/`, DERP relay tự viết
  khác derper). Đây là quyết định chủ động của người vận hành: domain
  `vpn5.hangocthanh.io.vn` đổi trỏ hẳn sang vpn4, khiến server vpn5 cũ mất
  domain hợp lệ (cert LE của nó không còn renew được sau khi DNS đổi).
- Instance cũ trên vpn4 (`derp-vpn4/`, v1.80.0, domain
  `vpn4.hangocthanh.io.vn`) **không bị đổi** — vẫn chạy nguyên trên port
  80/443/3478-udp.

## 1. Vì sao có instance thứ 2 thay vì nâng cấp instance cũ?

Muốn có bản derper mới hơn để test/so sánh song song mà không rủi ro relay
đang chạy thật (`vpn4.hangocthanh.io.vn`, region DERP 1001). Nếu bản mới có
vấn đề, tắt riêng instance thứ 2 (`derper2`) không ảnh hưởng instance cũ.

## 2. Vì sao instance thứ 2 không dùng port 80/443 trực tiếp?

Một host chỉ có 1 IPv4. Instance cũ (`derper` container trong `derp-vpn4/`)
đã bind port 80/443/3478-udp và tự quản cert Let's Encrypt cho domain
`vpn4.hangocthanh.io.vn` qua `--certmode=letsencrypt`. `derper` không hỗ trợ
nhiều domain trên 1 process (flag `--hostname` chỉ nhận 1 domain), nên
instance thứ 2 **không thể** cùng bind 2 port đó cho domain khác.

Instance `derper2` dùng port riêng: **8443** (DERP/HTTPS), **8080**
(HTTP), **3479/udp** (STUN) — publish trực tiếp trên host, không qua Caddy
(vpn4 hiện không chạy Caddy).

## 3. Cert cho vpn5.hangocthanh.io.vn — bootstrap 1 lần, gián đoạn tạm thời

`--certmode=manual` không tự xin cert — cần bootstrap một lần bằng
`--certmode=letsencrypt` qua HTTP-01, đòi port 80/443. Vì port đó đang bị
instance cũ giữ, workflow deploy (`deploy-derp-vpn4-v2.yml`) làm:

1. Kiểm tra cert hiện có trong volume `derper2_certs` còn hạn > 30 ngày
   không (`openssl x509 -checkend`). Nếu còn hạn → bỏ qua bước bootstrap.
2. Nếu cần bootstrap: `docker compose stop derper` (dừng **tạm** instance
   cũ, ~1-2 phút, **có gián đoạn relay `vpn4.hangocthanh.io.vn` trong lúc
   này** — đây là đánh đổi đã được xác nhận, xem §5).
3. Chạy container tạm bind port 80/443, `--certmode=letsencrypt` xin cert
   cho `vpn5.hangocthanh.io.vn`, cert lưu vào volume `derper2_certs`.
4. `docker compose start derper` — khôi phục instance cũ ngay khi có cert
   (hoặc timeout 90s).
5. `docker compose up -d` cho `derper2` steady-state (`--certmode=manual`,
   đọc cert từ volume, port 8443/8080/3479).

Vì LE cert hết hạn sau 90 ngày, bước 1-4 sẽ **tự lặp lại mỗi lần deploy**
khi cert còn dưới 30 ngày hạn → gián đoạn tạm thời instance cũ định kỳ
(khoảng mỗi 60 ngày). Nếu muốn loại bỏ hẳn gián đoạn này, cần chuyển sang
DNS-01 challenge (Cloudflare API token) — chưa triển khai, xem §6.

## 4. Headscale DERPMap (`config/derp.yaml`)

Region **1002** (trước đây trỏ server vpn5 cũ) nay trỏ về vpn4:

```yaml
1002:
  regionname: "VPN5 (derper v1.100.0, chay tren host vpn4)"
  nodes:
    - hostname: "vpn5.hangocthanh.io.vn"
      ipv4: "149.104.66.174"
      stunport: 3479
      derpport: 8443
```

Region 1001 (vpn4 cũ, v1.80.0) giữ nguyên `derpport: 443`.

## 5. Việc người vận hành cần tự làm (ngoài phạm vi repo)

- [ ] **Đổi bản ghi DNS A** `vpn5.hangocthanh.io.vn` từ `204.199.161.89`
      sang `149.104.66.174` (Cloudflare/registrar — repo không có tự động
      hoá DNS).
- [ ] **Tắt server vpn5 cũ** (204.199.161.89, stack `relay-vpn5/`) sau khi
      xác nhận cutover ổn định — nó vẫn chạy nhưng domain không còn trỏ về
      nó nữa (orphaned).
- [ ] Xác nhận đã chấp nhận: mỗi lần cert `vpn5.hangocthanh.io.vn` gần hết
      hạn (~mỗi 60 ngày), deploy sẽ dừng tạm relay `vpn4.hangocthanh.io.vn`
      (region 1001) khoảng 1-2 phút để bootstrap lại cert.

## 6. Tailscale sidecar + ping-reporter (thêm 2026-07-03)

`derper2` giờ có sidecar `tailscale` (join tailnet với hostname `vpn5`,
container `ts-vpn5`) + `ping-reporter-vpn5` — để xuất hiện trong danh sách
"Node DERP / hạ tầng" của headscale-admin/dashboard giống vpn3/vpn4/vpn6,
và có dữ liệu latency (`src=vpn5`) trên `/derp-status`. TS_AUTHKEY được
tạo trên GitHub Actions runner (giống pattern `deploy-derp-vpn4.yml`), ghi
vào `derp-vpn4-v2/.env` trước khi `docker compose up`.

## 7. Follow-up (chưa làm)

- Chuyển bootstrap cert sang DNS-01 (Cloudflare API token) để bỏ hẳn bước
  dừng tạm instance cũ mỗi chu kỳ renew.
