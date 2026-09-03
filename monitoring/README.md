# Monitoring lớp 2 — thông tin image Docker

Bổ trợ cho Uptime Kuma (lớp 1 = sống/chết): lớp này trả lời "đang chạy image gì,
có bản mới chưa, xem chi tiết ở đâu".

| Thành phần | Ở đâu | Vai trò |
|---|---|---|
| Portainer CE | vpn6 — https://portainer.hangocthanh.io.vn | Web xem container/image/version/log/volume của CẢ 2 host |
| Portainer Agent | vpn4, cổng 9001 (ufw chỉ mở cho IP vpn6 + AGENT_SECRET) | Cho server vpn6 nhìn thấy docker vpn4 |
| Diun | cả vpn4 + vpn6 | 6h sáng mỗi ngày so image đang chạy với registry, có tag/digest mới → báo Telegram (@VotamAIbot). CHỈ báo, không tự update |
| Heartbeat msg | có sẵn trong docker-heartbeat.sh | Push Kuma kèm danh sách `container=image:tag`, xem ở lịch sử heartbeat |

## Deploy
1. Thêm DNS A `portainer.hangocthanh.io.vn` → 45.119.87.220.
2. Chạy workflow `deploy-monitoring.yml` (2 job vpn6 + vpn4 song song).
3. Chạy lại `kuma-autoconfig.yml` để cập nhật bản heartbeat mới (nhúng image) lên 2 host.
4. Mở Portainer UI **trong vòng 5 phút** sau deploy → tạo admin (quá hạn thì `docker restart portainer` rồi vào lại).
5. Trong Portainer: Environments → Add environment → Agent → address `149.104.66.174:9001` (secret đã cấu hình sẵn qua env) → đặt tên `vpn4`.

## Chuyển server (server-migration)
- Portainer: state trong volume `portainer_data` (user, endpoint) — backup/restore volume như Kuma, trỏ lại DNS `portainer`, chạy lại workflow trên server mới.
- Diun: baseline trong volume `diun_data`; mất cũng không sao (lần quét đầu tự ghi lại, FIRSTCHECKNOTIF=false nên không spam).
- Agent vpn4: stateless, chỉ cần chạy lại workflow.
