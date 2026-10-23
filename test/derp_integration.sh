#!/bin/bash
# Integration test: build derper image va kiem tra health endpoint /derp/probe.
# Chay trong CI (khong can VPS that). derper --dev chay tren port 3340 (HTTP, khong TLS).
set -e

# Build DUNG phien ban dang deploy (build.args cua derp-vpn4/docker-compose.yml),
# khong phai ARG mac dinh v1.80.0 cua Dockerfile — neu khong CI se xanh du ban
# that su len prod khong build duoc.
GO_VERSION=$(sed -n 's/^ *GO_VERSION: *"\{0,1\}\([0-9.]*\)"\{0,1\} *$/\1/p' derp-vpn4/docker-compose.yml)
TAILSCALE_VERSION=$(sed -n 's/^ *TAILSCALE_VERSION: *\(v[0-9.]*\) *$/\1/p' derp-vpn4/docker-compose.yml)
if [ -z "$GO_VERSION" ] || [ -z "$TAILSCALE_VERSION" ]; then
  echo "FAIL: khong doc duoc GO_VERSION/TAILSCALE_VERSION tu derp-vpn4/docker-compose.yml"
  exit 1
fi

echo "==> [1/3] Build derper ${TAILSCALE_VERSION} (Go ${GO_VERSION}) tu derp-vpn3/Dockerfile.derper"
docker build -t derper-ci -f derp-vpn3/Dockerfile.derper \
  --build-arg GO_VERSION="$GO_VERSION" \
  --build-arg TAILSCALE_VERSION="$TAILSCALE_VERSION" \
  derp-vpn3/
GOT=$(docker run --rm derper-ci --version | head -1)
echo "  derper --version: $GOT"
case "$GOT" in
  "${TAILSCALE_VERSION#v}"*) ;;
  *) echo "FAIL: image build ra '$GOT', mong ${TAILSCALE_VERSION#v}"; exit 1 ;;
esac

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
