#!/usr/bin/env bash
# Disposable execution test for OpenCode v2's complete ingress path:
# the deploy haproxy.cfg TLS/SNI -> PROXY -> Caddy :8450 -> backend.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NET="opencode2-edge-test-$$"
TMP="$(mktemp -d)"
PORT=8453

cleanup() {
  docker rm -f opencode2-edge-haproxy opencode2-edge-caddy opencode2-edge-backend opencode2-edge-fail2ban opencode2-edge-client >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

fail() {
  echo "::error::$*" >&2
  for container in opencode2-edge-haproxy opencode2-edge-caddy opencode2-edge-backend; do
    echo "--- $container ---" >&2
    docker logs "$container" 2>&1 | tail -40 >&2 || true
  done
  exit 1
}

cat > "$TMP/Caddyfile" <<'EOF'
{
    admin off
    auto_https disable_redirects
    servers :8450 {
        listener_wrappers {
            proxy_protocol {
                timeout 5s
                allow 172.16.0.0/12
                fallback_policy require
            }
            tls
        }
    }
}

https://opencode2.hangocthanh.io.vn:8450 {
    tls internal
    reverse_proxy opencode2:4096
    log {
        output file /var/log/caddy/opencode2-access.log
        format json
    }
}
EOF

mkdir -p "$TMP/backend/global" "$TMP/caddy-logs"
echo 'OPENCODE2-INTEGRATION-OK' > "$TMP/backend/global/health"
mkdir -p "$TMP/fail2ban/jail.d" "$TMP/fail2ban/filter.d"
cp "$ROOT/edge-vpn4/fail2ban/jail.d/opencode2.conf" "$TMP/fail2ban/jail.d/opencode2.conf"
cp "$ROOT/edge-vpn4/fail2ban/filter.d/opencode2-401.conf" "$TMP/fail2ban/filter.d/opencode2-401.conf"
cat > "$TMP/backend.conf" <<'EOF'
server {
    listen 4096;
    location = /global/health { root /usr/share/nginx/html; }
    location / { return 401; }
}
EOF

docker network create "$NET" >/dev/null
docker run -d --name opencode2-edge-backend --network "$NET" --network-alias opencode2 \
  -v "$TMP/backend:/usr/share/nginx/html:ro" \
  -v "$TMP/backend.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine >/dev/null
docker run -d --name opencode2-edge-caddy --network "$NET" --network-alias caddy-edge \
  -v "$TMP/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v "$TMP/caddy-logs:/var/log/caddy" caddy:2.8-alpine >/dev/null

docker run --rm -v "$ROOT/edge-vpn4/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" haproxy:3.0.12-alpine haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg
docker run -d --name opencode2-edge-haproxy --network "$NET" -p "$PORT:443" \
  -v "$ROOT/edge-vpn4/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" haproxy:3.0.12-alpine >/dev/null

echo '==> v2 real SNI -> PROXY -> 8450 -> backend'
body=''
for _ in $(seq 1 30); do
  body="$(curl -sk --max-time 3 --resolve "opencode2.hangocthanh.io.vn:$PORT:127.0.0.1" \
    "https://opencode2.hangocthanh.io.vn:$PORT/global/health" 2>/dev/null || true)"
  [ "$body" = 'OPENCODE2-INTEGRATION-OK' ] && break
  sleep 1
done
[ "$body" = 'OPENCODE2-INTEGRATION-OK' ] || fail "v2 ingress did not reach the real backend (body=$body)"

echo '==> direct TLS without PROXY to :8450 is rejected'
docker run -d --name opencode2-edge-client --network "$NET" alpine:3.20 sleep 90 >/dev/null
direct="$(docker exec opencode2-edge-client wget -q -T 5 --no-check-certificate \
  -S -O /tmp/body https://caddy-edge:8450/global/health 2>&1 || true)"
if grep -q 'HTTP/' <<<"$direct"; then
  fail 'Caddy :8450 returned an HTTP response to direct TLS without PROXY protocol'
fi

echo '==> Caddy records the proxied client request as a v2 401 access log'
status="$(curl -sk --max-time 5 --resolve "opencode2.hangocthanh.io.vn:$PORT:127.0.0.1" \
  -o /dev/null -w '%{http_code}' "https://opencode2.hangocthanh.io.vn:$PORT/protected" || true)"
[ "$status" = '401' ] || fail "stub 401 did not cross v2 ingress (status=$status)"
for _ in $(seq 1 10); do
  docker exec opencode2-edge-caddy cat /var/log/caddy/opencode2-access.log > "$TMP/caddy-runtime.log" 2>/dev/null || true
  grep -q '"status":401' "$TMP/caddy-runtime.log" 2>/dev/null && break
  sleep 1
done
grep -q '"status":401' "$TMP/caddy-runtime.log" \
  || fail 'Caddy did not write the proxied 401 to opencode2 access log'

echo '==> fail2ban starts the configured v2 jail and filter matches that Caddy runtime log'
docker run -d --name opencode2-edge-fail2ban --network none --cap-add NET_ADMIN --cap-add NET_RAW \
  -e TZ=Etc/UTC \
  -v "$TMP/fail2ban/jail.d:/config/fail2ban/jail.d:ro" \
  -v "$TMP/fail2ban/filter.d:/config/fail2ban/filter.d:ro" \
  -v "$TMP/caddy-runtime.log:/remotelogs/opencode2-access.log:ro" \
  lscr.io/linuxserver/fail2ban:1.1.0 >/dev/null
for _ in $(seq 1 30); do
  if docker exec opencode2-edge-fail2ban fail2ban-client status opencode2-401 >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec opencode2-edge-fail2ban fail2ban-client status opencode2-401 \
  || fail 'fail2ban did not load the opencode2-401 jail'
docker exec opencode2-edge-fail2ban fail2ban-regex \
  /remotelogs/opencode2-access.log /config/fail2ban/filter.d/opencode2-401.conf \
  | tee "$TMP/fail2ban-regex.txt"
grep -Eq '1 matched' "$TMP/fail2ban-regex.txt" || fail 'fail2ban filter did not match exactly the runtime 401 Caddy log entry'

echo 'PASS: OpenCode v2 traffic reached the stub only through PROXY-protected Caddy; fail2ban filter matched runtime log.'
