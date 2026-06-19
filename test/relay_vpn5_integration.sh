#!/bin/bash
# Integration test: build relay-vpn5 va kiem tra health endpoints.
# Mo phong moi truong vpn5: pangolin_network + relay container.
# Khong can Tailscale sidecar — relay xu ly thieu socket gracefully (chi log loi).
#
# Phu hop voi moi truong CI (ubuntu-latest) lan chay local.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="ci-relay-vpn5"
VOLUME="relay-vpn5-ci-data"
NETWORK="pangolin_network"
PORT=18080   # tranh xung dot port 8080 co the da co tren runner

cleanup() {
  docker rm -f "$CONTAINER" 2>/dev/null || true
  docker volume rm "$VOLUME" 2>/dev/null || true
  # Chi xoa network neu test nay tao ra (khong xoa neu da ton tai truoc)
  if [ "${NET_CREATED:-0}" = "1" ]; then
    docker network rm "$NETWORK" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "==> [1/4] Build relay-vpn5 Docker image"
docker build -t relay-vpn5-ci "$REPO_ROOT/relay-vpn5/"

echo "==> [2/4] Tao pangolin_network (giong production vpn5)"
if docker network create "$NETWORK" 2>/dev/null; then
  NET_CREATED=1
  echo "  Tao moi: $NETWORK"
else
  NET_CREATED=0
  echo "  Da ton tai: $NETWORK"
fi

echo "==> [3/4] Start relay container (khong co Tailscale sidecar)"
# -ts-socket tro vao duong dan khong ton tai -> EndpointCache chi log loi, khong crash
docker run -d --name "$CONTAINER" \
  --network "$NETWORK" \
  -p "${PORT}:8080" \
  -v "${VOLUME}:/data" \
  relay-vpn5-ci \
  -addr=:8080 \
  -ts-socket=/tmp/nonexistent.sock \
  -key-file=/data/relay.key \
  -cache-ttl=5s

echo "==> [4/4] Kiem tra health endpoints (toi da 30s)"
PROBE_OK=0
for i in $(seq 1 15); do
  sleep 2
  CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "http://localhost:${PORT}/relay/probe" 2>/dev/null || echo "000")
  echo "  lan $i: /relay/probe HTTP $CODE"
  if [ "$CODE" = "200" ]; then PROBE_OK=1; break; fi
done

echo ""
echo "--- Ket qua kiem tra ---"
FAIL=0

# /relay/probe -> 200 OK
CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/relay/probe" || echo "000")
if [ "$CODE" = "200" ]; then
  echo "  PASS  /relay/probe  : HTTP $CODE"
else
  echo "  FAIL  /relay/probe  : HTTP $CODE (mong 200)"
  FAIL=1
fi

# /derp/probe (alias) -> 200 OK
CODE2=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/derp/probe" || echo "000")
if [ "$CODE2" = "200" ]; then
  echo "  PASS  /derp/probe   : HTTP $CODE2"
else
  echo "  FAIL  /derp/probe   : HTTP $CODE2 (mong 200)"
  FAIL=1
fi

# / khong co Upgrade header -> 426 Upgrade Required
CODE3=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/" || echo "000")
if [ "$CODE3" = "426" ]; then
  echo "  PASS  / (no Upgrade): HTTP $CODE3"
else
  echo "  WARN  / (no Upgrade): HTTP $CODE3 (mong 426, khong fatal)"
fi

# Container van dang chay (khong crash sau khi mat socket TS)
STATUS=$(docker inspect --format '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo "missing")
if [ "$STATUS" = "running" ]; then
  echo "  PASS  Container status: $STATUS"
else
  echo "  FAIL  Container status: $STATUS (mong 'running')"
  FAIL=1
fi

# Body cua /relay/probe phai la "OK"
BODY=$(curl -s "http://localhost:${PORT}/relay/probe" 2>/dev/null || echo "")
if [ "$BODY" = "OK" ]; then
  echo "  PASS  Body /relay/probe: \"$BODY\""
else
  echo "  FAIL  Body /relay/probe: \"$BODY\" (mong \"OK\")"
  FAIL=1
fi

echo ""
echo "--- Relay log (20 dong cuoi) ---"
docker logs --tail 20 "$CONTAINER" 2>&1 || true

echo ""
if [ "$FAIL" = "0" ]; then
  echo "OK: relay-vpn5 integration test PASS"
else
  echo "FAIL: relay-vpn5 integration test that bai"
  exit 1
fi
