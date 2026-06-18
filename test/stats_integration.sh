#!/usr/bin/env bash
# Test tich hop /stats: chung minh /stats song QUA Caddy -> node-dedup ma KHONG
# can tailscale sidecar (tai hien & chong tai phat loi 502 connection refused).
# Chay boi job 'stats-integration' tren GitHub CI.
set -euo pipefail

COMPOSE="docker compose -f docker-compose.test.yml"
BASE="http://localhost:8088"

cleanup() { $COMPOSE down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> Build & up stack test (KHONG co tailscale sidecar)"
$COMPOSE up -d --build

echo "==> Doi node-dedup phuc vu :8090 (toi da 40s)"
ok=0
for _ in $(seq 1 40); do
  if $COMPOSE logs node-dedup 2>&1 | grep -q "collector chay :8090"; then ok=1; break; fi
  sleep 1
done
if [ "$ok" != "1" ]; then echo "FAIL: node-dedup khong khoi dong"; $COMPOSE logs node-dedup; exit 1; fi

echo "==> Doi Caddy san sang (toi da 30s)"
code=000
for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/stats" || echo 000)
  [ "$code" != "000" ] && break
  sleep 1
done
echo "  caddy http_code dau tien=$code"

fail=0

echo "==> TEST 1: /stats CHUA dang nhap -> mong 302"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/stats" || echo ERR)
if [ "$code" = "302" ]; then echo "  PASS (302)"; else echo "  FAIL: nhan '$code' (mong 302)"; fail=1; fi

echo "==> TEST 2: /stats DA dang nhap (cookie testauth=1) -> mong 200 + HTML dashboard"
code=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: testauth=1" "$BASE/stats" || echo ERR)
body=$(curl -s -H "Cookie: testauth=1" "$BASE/stats" || true)
if [ "$code" = "200" ]; then echo "  PASS (200)"; else echo "  FAIL: nhan '$code' (mong 200)"; fail=1; fi
if printf '%s' "$body" | grep -qi "<html"; then echo "  PASS (co <html>)"; else echo "  FAIL: body khong phai HTML"; fail=1; fi

echo "==> TEST 3: xac nhan stack KHONG co tailscale sidecar (chung minh doc lap)"
if $COMPOSE ps --services | grep -qx "tailscale"; then
  echo "  FAIL: stack van co service 'tailscale'"; fail=1
else
  echo "  PASS (khong co sidecar ma /stats van 200)"
fi

echo "==> TEST 4: POST /metrics/report tu IP mang noi bo (gia lap node bao cao qua forwarder) -> mong 200 ok"
post_out=$($COMPOSE run --rm --no-deps -T node-dedup python3 -c '
import urllib.request, json
d = json.dumps({"hostname": "t", "ipv4": "100.64.0.9", "mac": "AA:BB:CC:DD:EE:FF", "samples": []}).encode()
req = urllib.request.Request("http://node-dedup:8090/metrics/report", data=d, headers={"Content-Type": "application/json"})
r = urllib.request.urlopen(req, timeout=10)
print(r.status, r.read().decode())
' 2>&1 || true)
echo "  $post_out"
if printf '%s' "$post_out" | grep -q '200' && printf '%s' "$post_out" | grep -q '"ok": true'; then
  echo "  PASS (POST 200 ok tu IP noi bo)"
else
  echo "  FAIL: POST khong duoc chap nhan"; fail=1
fi

if [ "$fail" = "0" ]; then echo "==> TAT CA PASS"; else echo "==> CO TEST FAIL"; $COMPOSE logs caddy node-dedup oauth2-proxy; exit 1; fi
