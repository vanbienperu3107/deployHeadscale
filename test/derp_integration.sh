#!/bin/bash
# Integration test: build derper image va kiem tra health endpoint /derp/probe.
# Chay trong CI (khong can VPS that). derper --dev chay tren port 3340 (HTTP, khong TLS).
set -e

echo "==> [1/3] Build derper image tu derp-vpn3/Dockerfile.derper"
docker build -t derper-ci -f derp-vpn3/Dockerfile.derper derp-vpn3/

echo "==> [2/3] Start derper (dev mode: HTTP, port 3340, khong can cert)"
docker run -d --name ci-derper -p 3340:3340 \
  derper-ci --dev

# Cho derper khoi dong (Let's Encrypt / cert setup mat vai giay trong prod,
# nhung dev mode khoi dong nhanh hon)
for i in $(seq 1 10); do
  sleep 2
  CODE=$(curl -sk -o /dev/null -w "%{http_code}" \
    "http://localhost:3340/derp/probe" 2>/dev/null || echo "000")
  if [ "$CODE" = "200" ]; then break; fi
  echo "  lan $i: HTTP $CODE, cho them..."
done

echo "==> [3/3] Kiem tra /derp/probe"
CODE=$(curl -sk -o /dev/null -w "%{http_code}" \
  "http://localhost:3340/derp/probe" 2>/dev/null || echo "000")
echo "  DERP probe HTTP $CODE"
docker rm -f ci-derper >/dev/null 2>&1 || true

if [ "$CODE" = "200" ]; then
  echo "OK: DERP health probe thanh cong"
else
  echo "FAIL: /derp/probe tra $CODE, mong 200"
  exit 1
fi
