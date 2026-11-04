# OpenCode v2: Public, Persistent, Tailnet-Aware

Ngày: 2026-11-04

## Mục tiêu

Vận hành OpenCode v2 độc lập tại `https://opencode2.hangocthanh.io.vn`. Người dùng vào qua HTTP Basic Auth; instance gọi CLIProxy, dùng Internet thật cho Git/package registries và SSH mọi node Tailnet. Nó không có Docker socket, host filesystem, privileged mode, capability của application container, source hay SSH key hạ tầng hiện hữu.

## Quyết định đã xác nhận

- Public repo độc lập: `vanbienperu3107/opencode2-deploy`.
- Image pin: `ghcr.io/anomalyco/opencode:2.0.32`.
- Basic Auth bắt buộc cho API và pairing flow.
- CLIProxy OpenAI-compatible: `https://cliproxy.hangocthanh.io.vn/v1`.
- Volumes persistent riêng cho `/workspace/projects`, `/home/opencode` và state Tailscale.
- Workspace trống, tách hoàn toàn khỏi hạ tầng hiện hữu.
- OpenCode tự chạy mọi action/tool không hỏi lại bằng permission wildcard `allow`.
- Headscale ACL giữ `allow all`: node `opencode2` có thể kết nối mọi node Tailnet.
- SSH chỉ dùng key Ed25519/user `opencode` riêng, không-root/không-sudo; không dùng lại key deploy/hạ tầng.

## Kiến trúc

```text
Browser
  -> HTTPS/SNI opencode2.hangocthanh.io.vn
  -> edge-nginx :443
  -> Caddy :8447 (TLS-ALPN, PROXY protocol, log riêng)
  -> ts-opencode2 (Headscale/Tailnet identity opencode2)
  -> opencode2 :4096, chung network namespace với sidecar
     -> workspace/state volumes
     -> CLIProxy + Internet outbound
     -> SSH mọi node Tailnet với user opencode
```

Port `4096` không publish ra host. `edge-nginx` là process public `443`; `80` vẫn dành cho DERP. Sidecar là service duy nhất có `/dev/net/tun` và `NET_ADMIN`. OpenCode không dùng host network, privileged mode, Docker socket hoặc host bind mount.

## Secrets, provider và SSH

GitHub Secrets và `.env` VPS mode `0600` chứa:

- `OPENCODE_SERVER_USERNAME`
- `OPENCODE_SERVER_PASSWORD`
- `CLIPROXY_API_KEY`
- `TS_AUTHKEY`, chỉ dành cho identity Headscale `opencode2`
- `OPENCODE_SSH_PRIVATE_KEY`
- `OPENCODE_SSH_KNOWN_HOSTS`

Workflow phải fail trước deploy nếu secret rỗng và không in giá trị ra log. Provider dùng `aisdk:@ai-sdk/openai-compatible`; model ID xác nhận qua `GET /v1/models` trước deploy.

Private key được tạo thành `/run/secrets/opencode-ssh-key` read-only; `known_hosts` được pin tại `/run/secrets/opencode-known-hosts`. SSH luôn dùng `StrictHostKeyChecking=yes`, không dùng root/public IP/key hạ tầng cũ. User `opencode` trên node được quản trị không thuộc `sudo`, `wheel` hay `docker`.

## Permissions tự động

OpenCode v2 phải dùng schema v2, không phải field `permission`/action `bash` của v1:

```jsonc
{
  "permissions": [
    { "action": "*", "resource": "*", "effect": "allow" }
  ]
}
```

Wildcard cho phép shell, edit, webfetch, websearch, external directory, MCP và plugin tools không prompt. SSH là shell command tự động. Basic Auth mạnh, Tailnet identity/key riêng, known-host pinning, audit và khả năng revoke key/node là các kiểm soát bắt buộc.

## Tailnet và giới hạn thực tế

ACL Headscale hiện `src: ["*"]`, `dst: ["*:*"]` và được giữ nguyên theo yêu cầu. Vì vậy không có allowlist network/port; giới hạn SSH nằm ở user/key/host-key verification. Tailscale state dùng volume `opencode2_tailscale_state`, tách khỏi state OpenCode, không tái dùng socket hoặc state host/service khác.

## Ingress và chống brute-force

DNS cần có: `A opencode2.hangocthanh.io.vn -> 149.104.66.174`.

- Nginx map SNI mới qua loopback `8448` đến Caddy `8447` cùng PROXY protocol.
- Caddy chỉ tin PROXY protocol từ network `edge`, terminate TLS, proxy `opencode2:4096` và có JSON access log riêng.
- TLS dùng ALPN; `flush_interval -1` giữ SSE streaming.
- fail2ban độc lập: 5 phản hồi `401`/10 phút, ban 1 giờ ở `DOCKER-USER`.
- Không dùng listener/access log OpenCode v1 để giảm blast radius cho DERP, CLIProxy và OpenCode v1.

## Persistence và rollback

`opencode2_workspace` giữ source/artifact, `opencode2_state` giữ SQLite/session/config/auth và `opencode2_tailscale_state` giữ Tailnet identity. Redeploy không xóa volume. Backup state mã hóa, nhất quán trước update và không vào repository/CI artifact. Image rollback giữ volumes; nếu database không downgrade được thì restore backup state trước update.

## Trình tự deploy

1. Tạo repo public, CI validate Compose/config/schema/secret scan.
2. Tạo GitHub secrets và DNS A.
3. Tạo preauth key Headscale riêng; cài user/public key/fingerprints `known_hosts` trên từng node cần quản trị.
4. Deploy `/opt/opencode2`, giữ OpenCode/Tailscale volumes và network `edge`.
5. Deploy edge SNI route với force-recreate nginx/Caddy.
6. Verify; nếu DERP hoặc CLIProxy regression, rollback edge ngay.

## Kiểm chứng bắt buộc

| ID | Kỳ vọng |
|---|---|
| TC-01 | Compose/config/schema/secret scan pass, image pin 2.0.32 |
| TC-02 | DNS đúng VPN4 trước thay đổi edge |
| TC-03 | Health nội bộ `opencode2:4096` healthy |
| TC-04 | Public health không credential `401`; credential đúng `200` |
| TC-05 | CLIProxy completion thực trả UTF-8 không rỗng |
| TC-06 | DERP probe và CLIProxy models vẫn `200` sau edge deploy |
| TC-07 | Sidecar `opencode2` online, đúng Headscale login server |
| TC-08 | `ssh opencode@<tailnet-host> true` pass; root/sai fingerprint bị từ chối |
| TC-09 | `opencode debug config` xác nhận wildcard `action:*`, `resource:*`, `allow` |
| TC-10 | Browser desktop/mobile pairing: snapshot, screenshot, không lỗi console mới |
| TC-11 | Project/session/Tailscale state tồn tại sau restart/recreate không `-v` |
| TC-12 | Thiếu secret làm deploy fail trước service start |

Fail2ban test chỉ chạy với IP test an toàn. SSH test chỉ dùng node đã có user/key riêng; không bootstrap bằng key hạ tầng.

## Rollback

1. DERP/CLIProxy regression: revert route `opencode2`, force-recreate nginx/Caddy, verify dịch vụ hiện hữu.
2. Service/config lỗi: recreate `opencode2` revision trước, giữ volumes.
3. Migration lỗi: restore encrypted state backup, restart service.
4. Basic Auth lộ: xoay secret, redeploy, kiểm tra fail2ban logs.
5. SSH key/Tailscale node lộ: revoke auth key, remove `opencode2`, xoá public key ở nodes, xoay SSH key và Basic Auth trước khi tạo lại sidecar.
