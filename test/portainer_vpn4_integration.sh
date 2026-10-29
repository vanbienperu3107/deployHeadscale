#!/usr/bin/env bash
# Local-only integration test for the Portainer ingress route.
#
# This deliberately does not run Portainer or mount /var/run/docker.sock.  All
# containers are test stubs on a unique Docker network; the only host binding
# is Docker's dynamically selected 127.0.0.1 port for the disposable nginx.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUFFIX="$$-${RANDOM}"
NETWORK="portainer-vpn4-test-${SUFFIX}"
PROXY_NETWORK="portainer-vpn4-proxy-test-${SUFFIX}"
NGINX="portainer-vpn4-test-nginx-${SUFFIX}"
DERP="portainer-vpn4-test-derp-${SUFFIX}"
CADDY="portainer-vpn4-test-caddy-${SUFFIX}"
PORTAINER_STUB="portainer-vpn4-test-backend-${SUFFIX}"
GATE_STUB="portainer-vpn4-test-gate-${SUFFIX}"
TMP="$(mktemp -d)"
PORTAINER_SNI="portainer.hangocthanh.io.vn"
# This hostname is intentionally NOT listed in the repository's SNI map, so
# it must take Nginx's default -> derper branch. Using vpn4's real DERP name
# also gives the TLS stub a concrete host to serve while remaining entirely
# local through curl --resolve below.
DERP_DEFAULT_SNI="vpn4.hangocthanh.io.vn"

cleanup() {
  status=$?
  echo "==> Cleanup disposable Docker resources"
  docker rm -f "$NGINX" "$DERP" "$CADDY" "$PORTAINER_STUB" "$GATE_STUB" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  docker network rm "$PROXY_NETWORK" >/dev/null 2>&1 || true
  rm -rf "$TMP"
  trap - EXIT
  exit "$status"
}
trap cleanup EXIT

fail() {
  echo "::error::$1" >&2
  echo "--- nginx log ---" >&2
  docker logs "$NGINX" 2>&1 || true
  echo "--- caddy edge log ---" >&2
  docker logs "$CADDY" 2>&1 || true
  echo "--- DERP stub log ---" >&2
  docker logs "$DERP" 2>&1 || true
  echo "--- SSO gate stub log ---" >&2
  docker logs "$GATE_STUB" 2>&1 || true
  exit 1
}

require_local_docker() {
  context="$(docker context show 2>/dev/null || true)"
  [ "$context" = "default" ] || {
    echo "Refusing non-default Docker context: ${context:-<none>}" >&2
    exit 2
  }
  endpoint="$(docker context inspect default --format '{{ .Endpoints.docker.Host }}' 2>/dev/null || true)"
  case "$endpoint" in
    unix://*) ;;
    *) echo "Refusing non-local Docker endpoint: ${endpoint:-<none>}" >&2; exit 2 ;;
  esac
  docker info >/dev/null
}

echo "==> [1/7] Require the local default Docker daemon"
require_local_docker

echo "==> [2/7] Render Portainer Compose and verify it publishes no host port"
docker compose --project-name portainer-vpn4 -f "$ROOT/portainer-vpn4/docker-compose.yml" config --quiet
docker compose --project-name portainer-vpn4 -f "$ROOT/portainer-vpn4/docker-compose.yml" config --format json \
  | python3 -c '
import json
import sys

rendered = json.load(sys.stdin)["services"]
for name in ("portainer", "oauth2-proxy"):
    service = rendered[name]
    ports = service.get("ports", [])
    assert not ports, f"{name} rendered host ports must be empty: {ports!r}"
    networks = service.get("networks")
    names = networks if isinstance(networks, list) else list(networks or {})
    assert names == ["portainer_proxy"], (name, networks)

gate = " ".join(str(part) for part in rendered["oauth2-proxy"]["command"])
assert "--provider=google" in gate, gate
assert "--authenticated-emails-file=" in gate, gate
assert "/var/run/docker.sock" not in str(rendered["oauth2-proxy"].get("volumes", []))
print("rendered Portainer stack publishes no host port and gates on Google SSO")
'

echo "==> [3/7] Binary-validate exact repository Nginx and Caddy configs"
docker run --rm \
  -v "$ROOT/edge-vpn4/nginx.conf:/etc/nginx/nginx.conf:ro" \
  nginx:1.27-alpine nginx -t

# `caddy validate` provisions reverse_proxy transport modules but must not
# require production backends.  Map every config backend to loopback inside the
# one-shot validation container, matching the existing CI's isolated preflight.
docker run --rm \
  --add-host cliproxy:127.0.0.1 \
  --add-host portainer:127.0.0.1 \
  --add-host portainer-oauth2-proxy:127.0.0.1 \
  --add-host opencode-server:127.0.0.1 \
  -v "$ROOT/edge-vpn4/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.8-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile

cat > "$TMP/derp.Caddyfile" <<'EOF'
{
	admin off
	auto_https disable_redirects
}

https://vpn4.hangocthanh.io.vn {
	tls internal
	respond "DERP STUB" 200
}
EOF

cat > "$TMP/portainer.Caddyfile" <<'EOF'
{
	admin off
}

:9000 {
	respond "PORTAINER STUB" 200
}
EOF

# Stub cua oauth2-proxy: /oauth2/auth tra 202 khi co cookie `testauth=1`, con
# lai 401 — dung giao uoc ma Caddy forward_auth dung o production. Khong goi
# Google de test chay duoc tren CI va cho ket qua xac dinh.
cat > "$TMP/gate.Caddyfile" <<'EOF'
{
	admin off
}

:4180 {
	@authed header_regexp Cookie testauth=1
	handle /oauth2/auth {
		respond @authed 202
		respond 401
	}
	handle /oauth2/* {
		respond "SSO LOGIN PAGE" 200
	}
}
EOF

# MIRROR cau truc that cua site portainer trong edge-vpn4/Caddyfile: handle
# /oauth2/* truoc, roi route{} co forward_auth dung truoc reverse_proxy.
cat > "$TMP/caddy-edge.Caddyfile" <<'EOF'
{
	admin off
	auto_https disable_redirects
}

https://portainer.hangocthanh.io.vn:8447 {
	tls internal

	handle /oauth2/* {
		reverse_proxy portainer-oauth2-proxy:4180
	}

	handle {
		route {
			forward_auth portainer-oauth2-proxy:4180 {
				uri /oauth2/auth
				copy_headers X-Auth-Request-Email X-Auth-Request-User
				@unauth status 401
				handle_response @unauth {
					redir * /oauth2/start?rd={http.request.uri}
				}
			}

			reverse_proxy portainer:9000
		}
	}
}
EOF

echo "==> [4/7] Start only disposable local stubs on $NETWORK"
docker network create "$NETWORK" >/dev/null
docker network create "$PROXY_NETWORK" >/dev/null
docker run -d --name "$DERP" --network "$NETWORK" --network-alias derper \
  --tmpfs /data:rw,noexec,nosuid,size=16m \
  --tmpfs /config:rw,noexec,nosuid,size=16m \
  -v "$TMP/derp.Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.8-alpine >/dev/null
docker run -d --name "$PORTAINER_STUB" --network "$PROXY_NETWORK" --network-alias portainer \
  --tmpfs /data:rw,noexec,nosuid,size=16m \
  --tmpfs /config:rw,noexec,nosuid,size=16m \
  -v "$TMP/portainer.Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.8-alpine >/dev/null
docker run -d --name "$GATE_STUB" --network "$PROXY_NETWORK" --network-alias portainer-oauth2-proxy \
  --tmpfs /data:rw,noexec,nosuid,size=16m \
  --tmpfs /config:rw,noexec,nosuid,size=16m \
  -v "$TMP/gate.Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.8-alpine >/dev/null
docker run -d --name "$CADDY" --network "$NETWORK" --network-alias caddy-edge \
  --tmpfs /data:rw,noexec,nosuid,size=16m \
  --tmpfs /config:rw,noexec,nosuid,size=16m \
  -v "$TMP/caddy-edge.Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.8-alpine >/dev/null
docker network connect "$PROXY_NETWORK" "$CADDY"
PROXY_MEMBERS="$(docker network inspect "$PROXY_NETWORK" --format '{{range .Containers}}{{.Name}} {{end}}' | tr ' ' '\n' | sed '/^$/d; s#^/##' | sort | tr '\n' ' ')"
EXPECTED_PROXY_MEMBERS="$(printf '%s\n%s\n%s\n' "$CADDY" "$PORTAINER_STUB" "$GATE_STUB" | sort | tr '\n' ' ')"
[ "$PROXY_MEMBERS" = "$EXPECTED_PROXY_MEMBERS" ] || fail "private proxy test network members differ: ${PROXY_MEMBERS:-<empty>}"

echo "==> [5/7] Start exact repository Nginx with a random loopback-only port"
docker run -d --name "$NGINX" --network "$NETWORK" -p 127.0.0.1::443 \
  -v "$ROOT/edge-vpn4/nginx.conf:/etc/nginx/nginx.conf:ro" \
  nginx:1.27-alpine >/dev/null
HOST_PORT="$(docker port "$NGINX" 443/tcp | python3 -c 'import sys; print(sys.stdin.read().strip().rsplit(":", 1)[1])')"
case "$HOST_PORT" in
  ''|*[!0-9]*) fail "could not determine disposable loopback port" ;;
esac
echo "  local test endpoint: 127.0.0.1:$HOST_PORT (not a production address)"

request() {
  local sni="$1"
  local path="$2"
  shift 2
  curl --noproxy '*' --silent --show-error --insecure --max-time 5 \
    --resolve "$sni:$HOST_PORT:127.0.0.1" \
    "$@" \
    "https://$sni:$HOST_PORT$path"
}

status_of() {
  local sni="$1"
  local path="$2"
  shift 2
  curl --noproxy '*' --silent --show-error --insecure --max-time 5 \
    --resolve "$sni:$HOST_PORT:127.0.0.1" \
    -o /dev/null -w '%{http_code}' "$@" \
    "https://$sni:$HOST_PORT$path"
}

echo "==> [6/7] Portainer must be unreachable without a session, reachable with one"
ready=0
for _ in $(seq 1 20); do
  authed="$(request "$PORTAINER_SNI" /api/status -H 'Cookie: testauth=1' 2>/dev/null || true)"
  if [ "$authed" = "PORTAINER STUB" ]; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" = 1 ] || fail "an authenticated request did not reach the private Portainer backend (got ${authed:-<empty>})"
echo "  authenticated: $PORTAINER_SNI -> $authed"

# Bang chung cho lo hong 2026-10-21: request KHONG co phien phai bi chan o cong,
# khong duoc cham toi Portainer.
anon_body="$(request "$PORTAINER_SNI" /api/status 2>/dev/null || true)"
case "$anon_body" in
  *"PORTAINER STUB"*) fail "unauthenticated request reached Portainer -- the SSO gate is not enforcing" ;;
esac
anon_code="$(status_of "$PORTAINER_SNI" /api/status 2>/dev/null || true)"
[ "$anon_code" = "302" ] || fail "unauthenticated request returned $anon_code, expected a 302 redirect to the gate"
anon_target="$(curl --noproxy '*' --silent --insecure --max-time 5 \
  --resolve "$PORTAINER_SNI:$HOST_PORT:127.0.0.1" \
  -o /dev/null -w '%{redirect_url}' \
  "https://$PORTAINER_SNI:$HOST_PORT/api/status" 2>/dev/null || true)"
case "$anon_target" in
  */oauth2/start*) ;;
  *) fail "unauthenticated request was not redirected to the login gate: ${anon_target:-<empty>}" ;;
esac
echo "  anonymous: $PORTAINER_SNI -> $anon_code $anon_target"

echo "==> [7/7] Default SNI must stay on the DERP stub, never Portainer"
derp_ready=0
for _ in $(seq 1 20); do
  actual="$(request "$DERP_DEFAULT_SNI" / 2>/dev/null || true)"
  if [ "$actual" = "DERP STUB" ]; then
    derp_ready=1
    break
  fi
  sleep 1
done
[ "$derp_ready" = 1 ] || fail "default SNI escaped DERP default or reached Portainer (got ${actual:-<empty>})"
echo "  $DERP_DEFAULT_SNI -> $actual"

echo "PASS: local disposable SNI routing keeps Portainer exact and DERP default."
