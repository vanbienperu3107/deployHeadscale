#!/usr/bin/env bash
# Integration test cho edge-vpn4: chay CHINH nginx.conf se deploy len vpn4, voi hai
# backend gia mang dung ten container ma config tro toi (derper, caddy-edge), roi
# chung minh nginx dinh tuyen theo SNI ma KHONG giai ma TLS:
#
#   1. SNI vpn4.hangocthanh.io.vn      -> backend derper
#   2. SNI cliproxy.hangocthanh.io.vn  -> backend caddy-edge
#   3. Khong gui SNI (goi bang IP)     -> derper (nhanh default, an toan cho DERP)
#   4. Moi backend tu terminate TLS bang cert RIENG cua no -> chung minh nginx chi
#      noi TCP, khong dung toi noi dung (dieu kien de derper giu autocert).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NET="edge-test-$$"
TMP="$(mktemp -d)"
PORT=8443

cleanup() {
  echo "--- don dep ---"
  docker rm -f edge-test-nginx edge-test-derper edge-test-caddy >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "==> [1/5] Dung hai backend gia (moi cai mot cert tu ky rieng)"
cat > "$TMP/derper.Caddyfile" <<'EOF'
{
	admin off
}
https://vpn4.hangocthanh.io.vn:443 {
	tls internal
	respond "DERPER" 200
}
EOF

cat > "$TMP/cliproxy.Caddyfile" <<'EOF'
{
	admin off
}
https://cliproxy.hangocthanh.io.vn:8444 {
	tls internal
	respond "CLIPROXY" 200
}
EOF

docker network create "$NET" >/dev/null

# Ten container phai TRUNG voi upstream trong nginx.conf that.
docker run -d --name edge-test-derper --network "$NET" --network-alias derper \
  -v "$TMP/derper.Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.8-alpine >/dev/null
docker run -d --name edge-test-caddy --network "$NET" --network-alias caddy-edge \
  -v "$TMP/cliproxy.Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.8-alpine >/dev/null

echo "==> [2/5] Kiem tra cu phap nginx.conf that"
docker run --rm -v "$ROOT/edge-vpn4/nginx.conf:/etc/nginx/nginx.conf:ro" nginx:1.27-alpine nginx -t

echo "==> [3/5] Chay nginx voi chinh nginx.conf se deploy"
docker run -d --name edge-test-nginx --network "$NET" -p "$PORT:443" \
  -v "$ROOT/edge-vpn4/nginx.conf:/etc/nginx/nginx.conf:ro" nginx:1.27-alpine >/dev/null

echo "  cho backend san sang..."
ready=0
for _ in $(seq 1 30); do
  out=$(curl -sk --max-time 3 --resolve "vpn4.hangocthanh.io.vn:$PORT:127.0.0.1" \
    "https://vpn4.hangocthanh.io.vn:$PORT/" 2>/dev/null || true)
  if [ "$out" = "DERPER" ]; then ready=1; break; fi
  sleep 2
done
if [ "$ready" != "1" ]; then
  echo "::error::backend khong len sau 60s"
  docker logs edge-test-nginx 2>&1 | tail -20
  docker logs edge-test-derper 2>&1 | tail -20
  exit 1
fi

echo "==> [4/5] Dinh tuyen theo SNI"
a=$(curl -sk --max-time 10 --resolve "vpn4.hangocthanh.io.vn:$PORT:127.0.0.1" \
  "https://vpn4.hangocthanh.io.vn:$PORT/" || true)
echo "  SNI vpn4.hangocthanh.io.vn -> '$a'"
if [ "$a" != "DERPER" ]; then
  echo "::error::SNI cua derper bi dinh tuyen sai (nhan '$a')"
  exit 1
fi

b=$(curl -sk --max-time 10 --resolve "cliproxy.hangocthanh.io.vn:$PORT:127.0.0.1" \
  "https://cliproxy.hangocthanh.io.vn:$PORT/" || true)
echo "  SNI cliproxy.hangocthanh.io.vn -> '$b'"
if [ "$b" != "CLIPROXY" ]; then
  echo "::error::SNI cua cliproxy bi dinh tuyen sai (nhan '$b')"
  exit 1
fi

echo "==> [5/5] Khong co SNI phai duoc DINH TUYEN ve derper (bat bien an toan cho DERP)"
# Goi bang IP -> khong co SNI. Bat tay TLS se that bai (ca derper that lan backend
# gia deu can SNI de chon cert) nen KHONG kiem tra noi dung tra ve — thu can kiem
# la NGINX QUYET DINH DI DAU. Log dinh tuyen cua nginx tra loi chinh xac dieu do.
curl -sk --max-time 5 "https://127.0.0.1:$PORT/" >/dev/null 2>&1 || true
sleep 1
# Bien rong trong context `stream` duoc in ra la RONG (khac http log, noi no thanh '-').
routed=$(docker logs edge-test-nginx 2>&1 | grep -cE "sni=-? -> derper:443" || true)
echo "  so ket noi khong SNI duoc dinh tuyen ve derper: $routed"
if [ "${routed:-0}" -lt 1 ]; then
  echo "::error::ket noi khong co SNI KHONG duoc dinh tuyen ve derper — loi ten mien se lam chet DERP"
  echo "--- log nginx ---"
  docker logs edge-test-nginx 2>&1 | tail -15
  exit 1
fi

# Chung minh nginx khong giai ma: hai backend co cert khac nhau, curl xac minh
# duoc rang cert nhan duoc dung la cert do backend phat ra.
echo "--- kiem chung TLS di xuyen qua (cert do backend giu) ---"
subj_a=$(curl -skv --max-time 10 --resolve "vpn4.hangocthanh.io.vn:$PORT:127.0.0.1" \
  "https://vpn4.hangocthanh.io.vn:$PORT/" 2>&1 | grep -i "subject:" | head -1 || true)
subj_b=$(curl -skv --max-time 10 --resolve "cliproxy.hangocthanh.io.vn:$PORT:127.0.0.1" \
  "https://cliproxy.hangocthanh.io.vn:$PORT/" 2>&1 | grep -i "subject:" | head -1 || true)
echo "  cert derper  : $subj_a"
echo "  cert cliproxy: $subj_b"
if [ "$subj_a" = "$subj_b" ]; then
  echo "::error::hai backend tra ve cung mot cert — nginx dang terminate TLS chu khong passthrough"
  exit 1
fi

echo "PASS: nginx dinh tuyen dung theo SNI va khong dung toi TLS."
