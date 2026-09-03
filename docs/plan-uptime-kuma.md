# Plan: Giám sát vpn4 + vpn6 bằng Uptime Kuma, cảnh báo Telegram

AGENT MODE: SINGLE_AGENT
RISK: STANDARD (deploy container mới lên box production, thêm rule định tuyến 443)

## Yêu cầu người dùng (latest)
Triển khai giám sát cho vpn4, vpn6 với nền tảng https://github.com/louislam/uptime-kuma → tích hợp Telegram.

## Bối cảnh hạ tầng (đã khảo sát)
- **vpn4** (149.104.66.174): nginx stream `ssl_preread` chiếm 443, route SNI → derper (default) / caddy-edge:8444 (cliproxy) / 8446→8445 (opencode). Thêm service = thêm domain + 1 dòng map + 1 site Caddy.
- **vpn6** (45.119.87.220): sslh chiếm 443, SNI vpn6 → derper:8444, còn lại → Caddy memory-stack:8443 (đang phục vụ claude/vpn2/sql...). Thêm service = thêm 1 site vào Caddy memory-stack, KHÔNG đụng sslh.
- Deploy pattern chuẩn: workflow_dispatch → appleboy/ssh-action → git reset --hard → docker compose up (script phẳng, không if/else nhiều dòng — bài học drone-ssh).
- vpn6 từng bị log Docker không rotate (2.5GB) → mọi container mới PHẢI có logging max-size.

## Giải pháp đề xuất

### GP1 — 1 instance Kuma trên vpn6, giám sát cả vpn4 + vpn6 (ĐỀ XUẤT)
- Container `uptime-kuma` (image chính chủ `louislam/uptime-kuma:1`) trên vpn6, listen 127.0.0.1:3001.
- Caddy memory-stack thêm site `status.hangocthanh.io.vn` → reverse_proxy 127.0.0.1:3001 (cần WebSocket — Caddy tự xử lý).
- Nhược: vpn6 chết → mất luôn cảnh báo (khắc phục một phần bằng monitor "push heartbeat" từ vpn4 — xem dưới).

### GP2 — 1 instance trên vpn4
- vpn4 mạng Bitel hay bị chặn/timeout từ VN (memory: SSH vpn4 phải jump qua vpn6) → truy cập dashboard kém tin cậy. Loại.

### GP3 — 2 instance cross-monitor (vpn4 ↔ vpn6)
- Chống điểm chết đơn tốt nhất nhưng ×2 công vận hành, 2 domain, 2 cấu hình notification. Overhead > lợi ích ở quy mô hiện tại. Loại (có thể nâng cấp sau).

**Chọn GP1** + 1 monitor kiểu **Push** (heartbeat): cron trên vpn4 curl URL push của Kuma mỗi 60s → nếu vpn6 sống mà vpn4 chết, Kuma báo; nếu vpn6 chết thì tự khắc mọi domain trên vpn6 chết, user tự thấy — chấp nhận ở mức chi phí này.

## Thiết kế

### Thư mục mới `uptime-kuma/` trong deployHeadscale
```
uptime-kuma/
  docker-compose.yml   # louislam/uptime-kuma:1, 127.0.0.1:3001:3001,
                       # volume uptime-kuma_data, logging json-file max-size 10m/3 file
  README.md
```

### Định tuyến vpn6
- DNS: thêm bản ghi A `status.hangocthanh.io.vn` → 45.119.87.220.
- Caddy memory-stack (file trên vpn6, ngoài repo này): thêm block
  ```
  status.hangocthanh.io.vn {
      reverse_proxy 127.0.0.1:3001
  }
  ```
  (sslh default đã trỏ về Caddy nên KHÔNG sửa sslh.)

### Monitors khởi tạo (cấu hình trong UI Kuma sau deploy)
| # | Monitor | Kiểu | Đích |
|---|---------|------|------|
| 1 | DERP vpn4 | HTTP(s) keyword | https://vpn4... `/derp` kỳ vọng 426/101 hoặc TCP 443 |
| 2 | DERP vpn6 | HTTP(s) | https://vpn6.hangocthanh.io.vn/derp |
| 3 | Headscale | HTTP(s) | https://vpn2.hangocthanh.io.vn/health |
| 4 | Dashboard | HTTP(s) | https://dashboard... /api healthcheck |
| 5 | CLIProxy | TCP | 149.104.66.174:443 (SNI route) |
| 6 | STUN vpn4/vpn6 | Port | 3478/udp không check được bằng Kuma port-monitor (TCP only) → dùng HTTP tới derper là proxy-signal |
| 7 | vpn4 alive | Push | cron trên vpn4 curl push-URL 60s |

### Telegram
- Uptime Kuma có notification provider Telegram sẵn: chỉ cần **Bot Token + Chat ID**, cấu hình trong UI (Settings → Notifications), gắn default cho mọi monitor.
- Kuma chỉ gọi `sendMessage`, không `getUpdates` → dùng lại token @VotamAIbot KHÔNG xung đột polling của TelegramAgent; nhưng tách bot riêng (@BotFather tạo mới) sạch hơn về phân quyền. → HỎI USER.

### Deploy workflow `.github/workflows/deploy-uptime-kuma.yml`
- `workflow_dispatch`, concurrency group riêng, appleboy/ssh-action vào vpn6 (SSH_HOST_VPN6), script phẳng:
  clone/reset repo → `docker compose up -d` trong `uptime-kuma/` → health check `curl -s 127.0.0.1:3001`.
- Bước sửa Caddyfile memory-stack + reload Caddy: làm trong cùng workflow (thêm block nếu chưa có, `caddy reload`) — idempotent, có kiểm tra `caddy validate` trước reload, lỗi thì không reload (giữ config cũ).

## Implementation Steps
1. Tạo `uptime-kuma/docker-compose.yml` + README (repo deployHeadscale).
2. Tạo workflow deploy-uptime-kuma.yml.
3. PR vào deployHeadscale, CI pass.
4. User thêm DNS A `status` → vpn6. (thao tác tay của user)
5. Chạy workflow → Kuma sống tại https://status.hangocthanh.io.vn.
6. Cấu hình tay trong UI: tạo admin, add Telegram notification (token+chat id), add monitors theo bảng, tạo Push monitor → lấy push URL.
7. Cron heartbeat trên vpn4 (thêm vào workflow diag hoặc SSH tay 1 dòng crontab).
8. Cập nhật docs + memory.

## Risk & Rollback
- Rủi ro chính: sửa Caddyfile memory-stack sai → mất claude/vpn2/sql. Giảm thiểu: backup Caddyfile trước khi sửa, `caddy validate` bắt buộc, rollback = restore backup + reload.
- Kuma là container độc lập, rollback = `docker compose down`, không đụng dịch vụ khác.
- Log rotate: khai báo logging trong compose (bài học vpn6-docker-log-khong-rotate).

## Câu hỏi chặn (cần user trả lời)
1. Bot Telegram: dùng lại @VotamAIbot hay tạo bot mới?
2. Domain `status.hangocthanh.io.vn` OK không (user phải thêm DNS)?
