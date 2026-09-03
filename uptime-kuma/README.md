# Uptime Kuma trên vpn6 — giám sát vpn4/vpn6, cảnh báo Telegram

- Dashboard: https://status.hangocthanh.io.vn (Caddy memory-stack → 127.0.0.1:3001)
- Deploy: workflow `deploy-uptime-kuma.yml` (workflow_dispatch). Workflow tự thêm
  block `status.hangocthanh.io.vn` vào Caddyfile memory-stack (idempotent, có
  backup + `caddy validate` trước khi reload).
- Plan chi tiết: `docs/plan-uptime-kuma.md`.

## Sau lần deploy đầu (làm tay trong UI)
1. Mở https://status.hangocthanh.io.vn → tạo tài khoản admin.
2. Settings → Notifications → Telegram: dán Bot Token của @VotamAIbot + Chat ID
   (lấy chat id: nhắn bot rồi `curl https://api.telegram.org/bot<TOKEN>/getUpdates`).
   Bật "Default enabled" để mọi monitor mới tự gắn.
   Lưu ý: Kuma chỉ gọi `sendMessage` nên KHÔNG xung đột polling của TelegramAgent.
3. Thêm monitors:
   | Monitor | Kiểu | Đích |
   |---|---|---|
   | DERP vpn6 | HTTP(s) | https://vpn6.hangocthanh.io.vn/derp — accept status 200-499 (426 Upgrade Required = derper sống) |
   | DERP vpn4 | TCP Port | 149.104.66.174:443 |
   | Headscale | HTTP(s) | https://vpn2.hangocthanh.io.vn/health |
   | Dashboard | HTTP(s) | https://dashboard.hangocthanh.io.vn |
   | CLIProxy | HTTP(s) | https://cliproxy.hangocthanh.io.vn (accept 401/404 — chỉ cần TLS sống) |
   | vpn4 alive | Push | tạo monitor Push, interval 120s |
4. Heartbeat vpn4: lấy push-URL từ monitor Push, SSH vpn4 (jump qua vpn6) thêm cron:
   `* * * * * curl -fsS -m 10 'https://status.hangocthanh.io.vn/api/push/<TOKEN>?status=up' >/dev/null 2>&1`
   → vpn4 chết (hoặc đứt đường ra) là Kuma báo Telegram sau ~2 phút.

## Giới hạn đã biết
- STUN 3478/udp không check trực tiếp được (Kuma port-monitor chỉ TCP) — tín hiệu
  gián tiếp qua monitor derper.
- Kuma nằm TRÊN vpn6: vpn6 sập thì mất luôn cảnh báo (chấp nhận, xem plan GP1/GP3).

## Chuyển server (server-migration)
Toàn bộ trạng thái (monitor, notification, user) nằm trong volume `uptime-kuma_data`.
Chuyển server mới: `docker run --rm -v uptime-kuma_uptime-kuma_data:/d alpine tar cz -C /d . > kuma-data.tgz`,
copy sang server mới, restore vào volume cùng tên trước khi `docker compose up -d`,
trỏ lại DNS `status` → IP mới, thêm block Caddy tương ứng.
