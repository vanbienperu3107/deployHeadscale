# Bug history — derper2/vpn5 trên vpn4 (2026-07-02 → 2026-07-03)

> Nhật ký sự cố + cách sửa khi thêm instance `derper` thứ 2 (v1.100.0) lên
> host vpn4, phục vụ domain `vpn5.hangocthanh.io.vn` (cutover từ server vpn5
> cũ). Xem kiến trúc đầy đủ ở `docs/DERP-VPN4-V2-CUTOVER.md`. Mục đích file
> này: tránh lặp lại đúng những lỗi đã tốn thời gian debug.

## 1. Test cũ hardcode kỳ vọng cấu hình vpn5 cũ

**Lỗi**: `test/test_derp_config.py` và assertion inline trong `ci.yml` giả
định cứng `derpport=443`, `stunport=3478`, `ipv4=204.199.161.89` cho region
1002 (vpn5) — chặn CI ngay khi đổi `config/derp.yaml` sang giá trị mới.

**Sửa**: cập nhật test/assertion khớp giá trị cutover (`derpport=8443`,
`ipv4=149.104.66.174`). PR #8.

## 2. `appleboy/ssh-action` phá vỡ script nhiều dòng

**Lỗi**: `script:` của `appleboy/ssh-action` (dùng `script_stop: true`) tự
chèn kiểm tra exit-code sau **từng dòng thô**, không hiểu cú pháp shell —
phá cả `if/then` nhiều dòng lẫn chuỗi `sh -c '...'` nhiều dòng, bất kể
`set -e`/`set +e` trong chính script. Triệu chứng: job chết câm lặng giữa
chừng, log không có gì bất thường trước đó.

**Sửa** (qua 4 lần thử trước khi tìm đúng gốc, PR #9–#11): cuối cùng
chuyển **toàn bộ logic** sang file `derp-vpn4-v2/deploy.sh` thật, `script:`
chỉ còn gọi `bash deploy.sh` — không còn gì để action đó phá vỡ. PR #12.

## 3. Go builder quá cũ cho derper v1.100.0

**Lỗi**: `Dockerfile.derper` dùng `golang:1.23-alpine`, nhưng
`tailscale.com@v1.100.0` yêu cầu `go >= 1.26.4` → build fail. Vì build fail
xảy ra **sau khi** đã dừng tạm derper cũ (`docker compose stop derper`) để
giải phóng port 80/443 cho bootstrap cert, và `set -e` thoát script trước
bước khôi phục → **relay production `vpn4.hangocthanh.io.vn` bị bỏ quên ở
trạng thái dừng 2 lần liên tiếp** (sự cố thật, không phải chỉ lỗi CI).

**Sửa**: nâng builder lên `golang:1.26-alpine`; thêm
`trap '...docker compose start derper...' EXIT` ngay sau lệnh stop, đảm
bảo derper cũ luôn được khôi phục ở **mọi** đường thoát script (thành công
lẫn fail), không chỉ path thành công. PR #13.

## 4. `derper --certmode=letsencrypt` cấp cert on-demand, không chủ động

**Lỗi**: derper chỉ thực sự gọi Let's Encrypt khi nhận được kết nối TLS
thật với đúng SNI. Vòng lặp chờ ban đầu chỉ polling file cert một cách thụ
động — không có traffic nào gõ đúng domain mới trong suốt 90s chờ (chỉ có
traffic tailscale client cũ gõ nhầm SNI `vpn4...`, bị autocert từ chối) nên
cert không bao giờ được xin.

**Sửa**: mỗi vòng lặp chủ động gọi `curl --resolve vpn5...:443:127.0.0.1
https://vpn5.../derp/probe` để ép đúng SNI, kích hoạt autocert thật sự xin
cert. PR #14.

## 5. Sai tên file cert cần kiểm tra

**Lỗi**: script tìm file `vpn5.hangocthanh.io.vn.crt`, nhưng
`autocert.DirCache` của Go lưu cert dưới **đúng tên hostname, không có đuôi
`.crt`** — nên dù cert đã cấp thành công (bằng chứng: 18/18 lần trigger đều
nhận HTTP 200), script vẫn báo "không lấy được cert".

**Sửa**: đổi sang tìm file theo pattern `vpn5.hangocthanh.io.vn*` thay vì
đoán đuôi cố định. PR #16.

## 6. Race condition port giữa 2 workflow

**Lỗi**: `deploy-derp-vpn4.yml` (tự redeploy relay cũ mỗi lần CI pass) và
`deploy-derp-vpn4-v2.yml` (bootstrap, tạm chiếm port 80/443) cùng trigger
từ **1 sự kiện CI success**, chạy song song trên cùng host → đụng độ
port (`port is already allocated`). `trap` ở mục 3 đã cứu production lần
đó, nhưng gốc rễ (race) chưa được sửa.

**Sửa**: đặt `concurrency.group` **giống nhau** (`deploy-vpn4-host`) cho cả
2 workflow — GitHub tự xếp hàng tuần tự thay vì chạy song song (tính năng
này hoạt động xuyên nhiều file workflow khác nhau, không chỉ trong 1 file).
PR #16.

## 7. Định dạng file cert khác nhau giữa 2 certmode

**Lỗi**: `--certmode=manual` (dùng cho instance thật, steady-state) cần 2
file riêng `<hostname>.crt` + `<hostname>.key`. Nhưng bootstrap dùng
`--certmode=letsencrypt` lưu cache theo định dạng `autocert.DirCache`: 1
file PEM gộp chung (private key + cert) dưới tên hostname trần. Không tách
→ derper báo `can not load x509 key pair: no such file or directory`.

**Sửa**: thêm bước tách file bằng `openssl x509`/`openssl pkey` trước khi
khởi động steady-state. PR #17.

## 8. `openssl x509` chỉ lấy 1 khối cert, làm mất chain trung gian

**Lỗi** (tinh vi nhất, tốn nhiều thời gian nhất để tìm ra): sau khi sửa
mục 7, cert **tồn tại** và derper2 **chạy được**, `[5/5]` tự probe bằng
`curl -sk` **luôn báo 200** — nhưng dashboard quản lý (`/app`, xác thực TLS
đầy đủ qua `fetch()`) vẫn báo region "Chết".

Nguyên nhân: `openssl x509 -in file -out file.crt` chỉ trích xuất đúng
**khối CERTIFICATE đầu tiên** (leaf). Let's Encrypt trả về leaf +
intermediate (≥2 khối), nên file `.crt` kết quả **thiếu chain trung
gian**. `curl -k` bỏ qua xác thực chứng chỉ nên không phát hiện ra; client
xác thực chuẩn (dashboard, trình duyệt thật) từ chối chain thiếu.

**Bài học**: `curl -k`/`-sk` trong bất kỳ script tự-probe nào **không phải
bằng chứng cert hợp lệ** — chỉ chứng minh server có trả lời qua TLS, không
chứng minh chain đầy đủ.

**Sửa**: dùng `sed -n '/BEGIN CERTIFICATE/,/END CERTIFICATE/p' file` để
lấy **tất cả** khối CERTIFICATE (giữ nguyên chain), thay vì `openssl x509`
chỉ lấy 1 khối. PR #19.

## 9. Firewall chưa mở port riêng của derper2 (nghi vấn phụ, đã phòng ngừa)

**Lỗi tiềm ẩn**: repo chưa từng quản lý `ufw` cho port 8443/3479 mới trên
vpn4. Probe tự thực hiện từ chính host vpn4 gọi vào IP công khai của chính
nó có thể đi qua hairpin NAT, né được firewall — không phản ánh đúng khả
năng truy cập từ bên ngoài (như dashboard trên vpn2 gọi tới).

**Sửa**: thêm `ufw allow 8443/tcp` + `ufw allow 3479/udp` vào bước khởi
động steady-state. PR #18. (Không chắc đây có phải nguyên nhân chính hay
không — mục 8 mới là fix quyết định — nhưng vẫn cần thiết để đúng đắn về
lâu dài.)

## 10. `node-dedup` (trang `/derp-status` cũ) hard-code danh sách region

**Vấn đề kiến trúc** (không phải bug, nhưng gây nhầm lẫn): `/derp-status`
đọc `DERP_PROBE_URLS` hard-code trong `node-dedup/dedup.py`, không đọc
`config/derp.yaml` lẫn DB. Sửa entry vpn5 trong biến này chỉ ảnh hưởng
trang cũ — **không** tự động đăng ký lên dashboard chính (`/app`), vì
dashboard đó dùng bảng `derp_servers` trong Postgres (nguồn dữ liệu thật,
CRUD qua API có xác thực). Phải thêm/sửa region vpn5 **thủ công qua UI**
`/app`, không phải qua code. PR #16 (điểm 1).

---

## Tổng kết bài học chung

Xem thêm memory nội bộ `derp-deploy-debugging-lessons` (không nằm trong
repo) để có checklist đầy đủ hơn. Tóm gọn:

1. `curl -k` không chứng minh cert hợp lệ — luôn kiểm chứng bằng client
   xác thực TLS đầy đủ.
2. `derper --certmode=letsencrypt` cấp cert on-demand — phải chủ động kích
   hoạt bằng kết nối thật, không chỉ chờ passively.
3. `appleboy/ssh-action` không hiểu cú pháp shell nhiều dòng — logic phức
   tạp nên nằm trong file script thật, không nằm trực tiếp trong `script:`.
4. Hai workflow chạy trên cùng host cần `concurrency.group` chung để tránh
   race port.
5. Bất kỳ chỗ nào dừng service production tạm thời đều cần `trap ... EXIT`
   để đảm bảo khôi phục ở mọi đường thoát, không chỉ path thành công.
6. Đừng hard-code cấu hình có sẵn nguồn DB/API thật — ưu tiên cập nhật qua
   UI/API, chỉ sửa code khi thực sự cần thay đổi hành vi.
7. Probe từ chính host không chứng minh được khả năng truy cập từ bên
   ngoài (hairpin NAT có thể che giấu lỗi firewall).
