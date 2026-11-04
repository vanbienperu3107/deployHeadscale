# OpenCode v2 Public Deployment

Ngày: 2026-11-04

## Mục tiêu

Vận hành OpenCode v2 độc lập tại `https://opencode2.hangocthanh.io.vn`. Người dùng truy cập qua Internet sau HTTP Basic Auth; instance gọi CLIProxy hiện có, có Internet thật cho Git và package registry, nhưng không được cấp Docker socket, SSH key, host filesystem, source hay secret của hạ tầng hiện hữu.

## Quyết định đã chốt

- Public repo độc lập: `vanbienperu3107/opencode2-deploy`.
- Image pin: `ghcr.io/anomalyco/opencode:2.0.32`.
- Basic Auth bắt buộc trên toàn bộ OpenCode API và pairing flow.
- CLIProxy OpenAI-compatible: `https://cliproxy.hangocthanh.io.vn/v1`.
- Persistent volumes riêng cho `/workspace/projects` và `/home/opencode`.
- Workspace lúc tạo trống và không chia sẻ với hạ tầng hiện hữu.
- Container có outbound Internet, không có privileged mode/capability/Docker socket/host bind mount.

## Kiến trúc

```text
Browser
  -> HTTPS/SNI opencode2.hangocthanh.io.vn
  -> edge-nginx :443
  -> Caddy :8447 (TLS-ALPN, PROXY protocol, log riêng)
  -> opencode2 :4096
     -> opencode2_workspace : /workspace/projects
     -> opencode2_state     : /home/opencode
     -> CLIProxy + Internet outbound
```

Port `4096` không publish ra host. Port `443` chỉ thuộc `edge-nginx`; port `80` vẫn dành cho DERP. Nginx giữ TLS passthrough theo SNI, thêm PROXY protocol trước Caddy để log được client IP thật. Caddy giữ `flush_interval -1` cho stream/SSE.

## Secrets và provider

Chỉ dùng GitHub Secrets và `.env` mode `0600` trên VPS:

- `OPENCODE_SERVER_USERNAME`
- `OPENCODE_SERVER_PASSWORD`
- `CLIPROXY_API_KEY`

Workflow fail trước deploy nếu secret rỗng và không in secret vào log. Provider v2 dùng `aisdk:@ai-sdk/openai-compatible`; API key chỉ nội suy từ environment. Model ID được xác nhận qua `GET /v1/models` của CLIProxy ngay trước deploy.

## Ingress và bảo vệ brute-force

DNS cần có: `A opencode2.hangocthanh.io.vn -> 149.104.66.174`.

- Nginx map SNI mới qua listener loopback `8448` đến Caddy `8447` với `proxy_protocol on`.
- Caddy listener `8447` chỉ tin PROXY protocol từ network `edge`, terminate TLS và proxy `opencode2:4096`.
- Caddy có JSON access log riêng cho OpenCode v2.
- fail2ban độc lập: 5 lần `401` trong 10 phút, ban IP 1 giờ ở `DOCKER-USER`.
- Không dùng listener/access log OpenCode v1: tránh blast radius sang DERP, CLIProxy và `opencode.hangocthanh.io.vn`.

## Persistence và rollback

`opencode2_workspace` giữ source clone/artifact. `opencode2_state` giữ SQLite, sessions, config và auth state. Redeploy không xóa volumes. Backup state mã hóa và nhất quán trước update. Rollback image/config giữ volume; nếu database không downgrade được, restore backup state trước update.

## Kiểm chứng bắt buộc

| ID | Kỳ vọng |
|---|---|
| TC-01 | Compose/config validation và secret scan xanh |
| TC-02 | DNS đúng VPN4 trước khi đụng edge |
| TC-03 | Health nội bộ `opencode2:4096` healthy |
| TC-04 | Public health không credential trả `401` |
| TC-05 | Public health credential đúng trả `200` |
| TC-06 | CLIProxy completion thực tế trả nội dung UTF-8 không rỗng |
| TC-07 | DERP `/derp/probe` vẫn `200` sau edge deploy |
| TC-08 | CLIProxy `/v1/models` vẫn `200` sau edge deploy |
| TC-09 | Browser pairing OpenCode desktop + mobile: snapshot, screenshot, console không error mới |
| TC-10 | Project/session còn sau restart/recreate không `-v` |

Test fail2ban chỉ chạy khi có IP test an toàn; nếu không có phải ghi `NOT_RUN`, không suy luận PASS.

## Rollback

1. Regression DERP/CLIProxy: revert route `opencode2`, force-recreate nginx/Caddy, rồi xác minh DERP và CLIProxy.
2. Service/config lỗi: recreate `opencode2` về image/config revision trước, giữ volumes.
3. State migration lỗi: restore encrypted state backup rồi restart service.
4. Nghi lộ Basic Auth: xoay secret, redeploy và kiểm tra fail2ban logs.
