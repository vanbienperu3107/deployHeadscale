#!/usr/bin/env bash
# Static contract for OpenCode v2's SNI -> PROXY -> Caddy ingress.
set -euo pipefail

readonly haproxy_conf="edge-vpn4/haproxy.cfg"
readonly caddyfile="edge-vpn4/Caddyfile"
readonly jail="edge-vpn4/fail2ban/jail.d/opencode2.conf"
readonly filter="edge-vpn4/fail2ban/filter.d/opencode2-401.conf"
readonly workflow=".github/workflows/deploy-edge-vpn4.yml"

grep -Fq 'use_backend opencode2 if { req.ssl_sni -i opencode2.hangocthanh.io.vn }' "$haproxy_conf"
grep -A2 -F 'backend opencode2' "$haproxy_conf" | grep -Fq 'caddy-edge:8450'
grep -A2 -F 'backend opencode2' "$haproxy_conf" | grep -Fq 'send-proxy'

grep -Fq 'servers :8450 {' "$caddyfile"
grep -Fq 'allow 172.16.0.0/12' "$caddyfile"
grep -Fq 'fallback_policy require' "$caddyfile"
grep -Fq 'https://opencode2.hangocthanh.io.vn:8450 {' "$caddyfile"
grep -Fq 'reverse_proxy opencode2:4096 {' "$caddyfile"
grep -Fq 'flush_interval -1' "$caddyfile"
grep -Fq 'dial_timeout 10s' "$caddyfile"
grep -Fq 'output file /var/log/caddy/opencode2-access.log {' "$caddyfile"

# The v2 fail2ban configuration must not carry the abandoned v2 listener ports.
if grep -Eq '844[78]' "$jail" "$filter"; then
    echo "OpenCode v2 fail2ban configuration must not retain 8447/8448 assumptions" >&2
    exit 1
fi

grep -Fq 'filter = opencode2-401' "$jail"
grep -Fq 'logpath = /remotelogs/opencode2-access.log' "$jail"
grep -Fq 'maxretry = 5' "$jail"
grep -Fq 'findtime = 600' "$jail"
grep -Fq 'bantime = 3600' "$jail"
grep -Fq 'banaction = iptables-allports' "$jail"
grep -Fq 'chain = DOCKER-USER' "$jail"
grep -Fq '"remote_ip":"<HOST>"' "$filter"
grep -Fq '"status":401' "$filter"

grep -Fq 'Kiem tra DNS opencode2.hangocthanh.io.vn' "$workflow"
grep -Fq 'https://opencode2.hangocthanh.io.vn/global/health' "$workflow"
grep -Fq '"${CODE:-000}" != "401"' "$workflow"
grep -Fq -- '--force-recreate haproxy caddy-edge fail2ban' "$workflow"

# Regression guards: unaffected public routes retain their exact ingress.
grep -Fq 'use_backend cliproxy if { req.ssl_sni -i cliproxy.hangocthanh.io.vn }' "$haproxy_conf"
grep -Fq 'use_backend opencode if { req.ssl_sni -i opencode.hangocthanh.io.vn }' "$haproxy_conf"
grep -Fq 'default_backend derper' "$haproxy_conf"
grep -Fq 'use_backend portainer if { req.ssl_sni -i portainer.hangocthanh.io.vn }' "$haproxy_conf"
grep -Fq 'https://portainer.hangocthanh.io.vn:8447 {' "$caddyfile"

git diff --exit-code HEAD -- \
    portainer-vpn4 \
    test/test_portainer_vpn4.py \
    .github/workflows/deploy-portainer-vpn4.yml
