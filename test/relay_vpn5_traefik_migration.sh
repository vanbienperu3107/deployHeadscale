#!/bin/bash
# Kiem tra step 4 cua deploy-relay-vpn5.yml: logic migration Traefik filename->directory.
#
# Mo phong moi truong vpn5 hien tai:
#   $HOME/opt/pangolin/config/traefik/traefik_config.yml  <- filename mode
#   $HOME/opt/pangolin/config/traefik/dynamic_config.yml  <- routes hien co
# + container pan-traefik dang chay (nginx:alpine lam gia lap)
#
# Kiem tra:
#   1. Migration lan 1: filename -> directory, copy file, restart container
#   2. Verify: file output dung, noi dung chinh xac
#   3. Migration lan 2 (idempotent): bo qua, khong restart traefik
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Dung HOME gia lap rieng biet de khong anh huong moi truong that
MOCK_HOME="$(mktemp -d)"
PANGOLIN_TRAEFIK_DIR="$MOCK_HOME/opt/pangolin/config/traefik"
TRAEFIK_CFG="$PANGOLIN_TRAEFIK_DIR/traefik_config.yml"
DYNAMIC_DIR="$PANGOLIN_TRAEFIK_DIR/dynamic"
DEPLOY_PATH="$REPO_ROOT"

cleanup() {
  docker rm -f pan-traefik 2>/dev/null || true
  rm -rf "$MOCK_HOME"
}
trap cleanup EXIT

echo "==> [1/4] Tao mock moi truong Traefik vpn5 (filename mode)"
mkdir -p "$PANGOLIN_TRAEFIK_DIR"

# traefik_config.yml: file chinh xac giong thuc te vpn5 (providers.file.filename)
cat > "$TRAEFIK_CFG" << 'TRAEFIK_EOF'
api:
  dashboard: true
  insecure: false
entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"
    proxyProtocol:
      trustedIPs:
        - "127.0.0.1"
providers:
  file:
    filename: /etc/traefik/dynamic_config.yml
certificatesResolvers:
  letsencrypt:
    acme:
      email: datht.official@gmail.com
      storage: /etc/traefik/acme.json
      dnsChallenge:
        provider: cloudflare
TRAEFIK_EOF

# dynamic_config.yml: cac route hien co phai duoc bao toan sau migration
cat > "$PANGOLIN_TRAEFIK_DIR/dynamic_config.yml" << 'DYN_EOF'
http:
  routers:
    pangolin:
      rule: "Host(`pan.dat-hoang.com`)"
      entryPoints: [websecure]
      service: pangolin
      tls:
        certResolver: letsencrypt
    xray:
      rule: "Host(`pan.dat-hoang.com`) && PathPrefix(`/xray`)"
      entryPoints: [websecure]
      service: xray
      tls:
        certResolver: letsencrypt
  services:
    pangolin:
      loadBalancer:
        servers:
          - url: "http://pangolin:3000"
    xray:
      loadBalancer:
        servers:
          - url: "http://gerbil:3001"
DYN_EOF

echo "  traefik_config.yml (truoc migration):"
grep "filename\|directory" "$TRAEFIK_CFG" || echo "  (khong tim thay keyword)"

echo ""
echo "==> [2/4] Start mock pan-traefik container (nginx:alpine)"
# Ten container phai la 'pan-traefik' de khop chinh xac voi lenh trong deploy script
docker run -d --name pan-traefik nginx:alpine >/dev/null
echo "  pan-traefik: $(docker inspect --format '{{.State.Status}}' pan-traefik)"

RESTART_COUNT_BEFORE=$(docker inspect --format '{{.RestartCount}}' pan-traefik)

echo ""
echo "==> [3/4] Chay migration logic (trich tu deploy-relay-vpn5.yml step 4)"
echo "  PANGOLIN_TRAEFIK_DIR=$PANGOLIN_TRAEFIK_DIR"
echo "  DEPLOY_PATH=$DEPLOY_PATH"

# Ghi de HOME de bien ${HOME}/opt/... giai quyet dung
export HOME="$MOCK_HOME"

# --- BAT DAU: copy nguyen van tu deploy-relay-vpn5.yml step 4 ---
if ! grep -q "directory:" "$TRAEFIK_CFG" 2>/dev/null; then
  echo "  Doi Traefik tu filename sang directory..."
  mkdir -p "$DYNAMIC_DIR"
  if [ -f "${PANGOLIN_TRAEFIK_DIR}/dynamic_config.yml" ] && \
     [ ! -f "${DYNAMIC_DIR}/dynamic_config.yml" ]; then
    cp "${PANGOLIN_TRAEFIK_DIR}/dynamic_config.yml" \
       "${DYNAMIC_DIR}/dynamic_config.yml"
  fi
  sed -i "s|filename: /etc/traefik/dynamic_config.yml|directory: /etc/traefik/dynamic|g" \
    "$TRAEFIK_CFG"
  echo "  Restart pan-traefik de ap dung static config moi..."
  docker restart pan-traefik
  sleep 3
else
  echo "  Traefik da dung directory mode, bo qua."
fi
mkdir -p "$DYNAMIC_DIR"
cp "$DEPLOY_PATH/relay-vpn5/traefik-relay-vpn5.yml" \
   "$DYNAMIC_DIR/traefik-relay-vpn5.yml"
sleep 1
# --- KET THUC: code deploy ---

echo ""
echo "==> [4/4] Kiem tra ket qua migration"
FAIL=0

echo "--- traefik_config.yml sau migration ---"
cat "$TRAEFIK_CFG"
echo ""

# [A] 'directory:' phai co mat
if grep -q "directory: /etc/traefik/dynamic" "$TRAEFIK_CFG"; then
  echo "PASS  [A] 'directory:' da duoc them"
else
  echo "FAIL  [A] 'directory:' khong tim thay trong traefik_config.yml"
  FAIL=1
fi

# [B] 'filename:' cu phai bi xoa
if grep -q "filename: /etc/traefik/dynamic_config.yml" "$TRAEFIK_CFG"; then
  echo "FAIL  [B] 'filename:' van con trong traefik_config.yml"
  FAIL=1
else
  echo "PASS  [B] 'filename:' da bi xoa"
fi

# [C] dynamic_config.yml duoc copy vao dynamic/ (bao toan route cu)
if [ -f "$DYNAMIC_DIR/dynamic_config.yml" ]; then
  echo "PASS  [C] dynamic_config.yml da copy vao dynamic/"
  if grep -q "pangolin" "$DYNAMIC_DIR/dynamic_config.yml"; then
    echo "PASS  [C] Noi dung route pangolin con nguyen"
  else
    echo "FAIL  [C] dynamic_config.yml trong hoac thieu route pangolin"
    FAIL=1
  fi
else
  echo "FAIL  [C] dynamic_config.yml khong duoc copy vao dynamic/"
  FAIL=1
fi

# [D] traefik-relay-vpn5.yml duoc deploy vao dynamic/
if [ -f "$DYNAMIC_DIR/traefik-relay-vpn5.yml" ]; then
  echo "PASS  [D] traefik-relay-vpn5.yml da deploy vao dynamic/"
  if grep -q "vpn5.hangocthanh.io.vn" "$DYNAMIC_DIR/traefik-relay-vpn5.yml"; then
    echo "PASS  [D] Route hostname chinh xac"
  else
    echo "FAIL  [D] traefik-relay-vpn5.yml thieu hostname vpn5.hangocthanh.io.vn"
    FAIL=1
  fi
else
  echo "FAIL  [D] traefik-relay-vpn5.yml khong duoc deploy"
  FAIL=1
fi

# [E] pan-traefik da duoc restart (RestartCount tang them 1)
RESTART_COUNT_AFTER=$(docker inspect --format '{{.RestartCount}}' pan-traefik)
if [ "$RESTART_COUNT_AFTER" -gt "$RESTART_COUNT_BEFORE" ]; then
  echo "PASS  [E] pan-traefik da restart ($RESTART_COUNT_BEFORE -> $RESTART_COUNT_AFTER)"
else
  echo "FAIL  [E] pan-traefik chua duoc restart (count: $RESTART_COUNT_BEFORE -> $RESTART_COUNT_AFTER)"
  FAIL=1
fi

echo ""
echo "--- Kiem tra idempotent: chay migration lan 2 ---"
RESTART_BEFORE_2ND=$(docker inspect --format '{{.RestartCount}}' pan-traefik)
SKIPPED=0

if ! grep -q "directory:" "$TRAEFIK_CFG" 2>/dev/null; then
  echo "FAIL  Idempotent: lan 2 van vao nhanh migration (khong idempotent)"
  FAIL=1
else
  echo "  Traefik da dung directory mode, bo qua."
  SKIPPED=1
fi
mkdir -p "$DYNAMIC_DIR"
cp "$DEPLOY_PATH/relay-vpn5/traefik-relay-vpn5.yml" \
   "$DYNAMIC_DIR/traefik-relay-vpn5.yml"

RESTART_AFTER_2ND=$(docker inspect --format '{{.RestartCount}}' pan-traefik)

if [ "$SKIPPED" = "1" ]; then
  echo "PASS  Idempotent: bo qua migration lan 2"
fi

# Lan 2 khong duoc restart Traefik (chi restart khi migration thuc su chay)
if [ "$RESTART_AFTER_2ND" = "$RESTART_BEFORE_2ND" ]; then
  echo "PASS  Idempotent: pan-traefik KHONG bi restart lan 2 (dung)"
else
  echo "FAIL  Idempotent: pan-traefik bi restart them ($RESTART_BEFORE_2ND -> $RESTART_AFTER_2ND)"
  FAIL=1
fi

echo ""
if [ "$FAIL" = "0" ]; then
  echo "OK: Traefik migration test PASS"
else
  echo "FAIL: Traefik migration test that bai"
  exit 1
fi
