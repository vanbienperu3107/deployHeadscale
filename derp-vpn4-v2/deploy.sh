#!/bin/sh
# Deploy derper2 (v1.100.0) tren host vpn4 - xem docs/DERP-VPN4-V2-CUTOVER.md.
#
# Chay boi .github/workflows/deploy-derp-vpn4-v2.yml qua SSH. Logic phuc tap
# (if/for nhieu dong) duoc dat trong FILE nay thay vi nam truc tiep trong
# script: cua appleboy/ssh-action, vi action do chen kiem tra exit-code sau
# TUNG DONG THO cua script (khong hieu cu phap shell), pha vo moi cau truc
# nhieu dong (if/then, chuoi quote nhieu dong...). File nay chay binh thuong
# qua "bash deploy.sh" nen khong bi anh huong.
set -e

if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; else SUDO=""; fi
cd "$(dirname "$0")"

# Mo firewall cho port rieng cua derper2 (8443 TCP, 3479 UDP). Neu khong
# lam buoc nay, health-check tu server khac (vd. dashboard tren vpn2) se
# bao "chet" du derper2 chay binh thuong - vi curl tu CHINH host vpn4 co
# the di qua hairpin NAT/loopback va khong phan anh dung firewall that.
if command -v ufw >/dev/null 2>&1; then
  $SUDO ufw allow 8443/tcp >/dev/null 2>&1 || true
  $SUDO ufw allow 3479/udp >/dev/null 2>&1 || true
fi

echo "==> [2/5] Kiem tra cert vpn5.hangocthanh.io.vn con han >30 ngay khong"
$SUDO docker volume create derp-vpn4-v2_derper2_certs >/dev/null 2>&1 || true

$SUDO docker run --rm -v derp-vpn4-v2_derper2_certs:/data alpine:3.20 sh -c '
  apk add --no-cache openssl >/tmp/apk.log 2>&1
  echo "  Noi dung volume cert:" 1>&2
  ls -la /data 1>&2 2>/dev/null || true
  f=$(find /data -maxdepth 1 -type f -name "vpn5.hangocthanh.io.vn*" ! -name "*+token" ! -name "*.cert_status" | head -1)
  if [ -n "$f" ] && openssl x509 -in "$f" -checkend 2592000 -noout 2>/dev/null; then
    echo OK > /data/.cert_status
  else
    echo EXPIRED > /data/.cert_status
  fi
' || true
CERT_STATUS=$($SUDO docker run --rm -v derp-vpn4-v2_derper2_certs:/data alpine:3.20 cat /data/.cert_status 2>/dev/null || echo EXPIRED)
echo "  Cert status: $CERT_STATUS (OK = con han >30 ngay)"

NEED_BOOTSTRAP=1
if [ "$CERT_STATUS" = "OK" ]; then
  NEED_BOOTSTRAP=0
  echo "  Cert con han (>30 ngay) - bo qua bootstrap"
else
  echo "  Cert thieu hoac sap het han - can bootstrap lai"
fi

if [ "$NEED_BOOTSTRAP" = "1" ]; then
  echo "==> [3/5] BOOTSTRAP cert HTTP-01 cho vpn5.hangocthanh.io.vn"
  echo "  Dung tam derper cu (derp-vpn4) de giai phong port 80/443 (~1-2 phut)"
  (cd ../derp-vpn4 && $SUDO docker compose stop derper) || true
  # Bat ke buoc nao ben duoi fail, LUON khoi phuc derper cu khi script thoat
  # (kho phai chi khi thanh cong) - tranh lap lai su co de derper cu bi bo
  # quen o trang thai stopped neu vd. docker build fail.
  trap '(cd ../derp-vpn4 && $SUDO docker compose start derper) >/dev/null 2>&1 || true' EXIT

  $SUDO docker build -t derper2-bootstrap -f Dockerfile.derper .
  $SUDO docker rm -f derper2-bootstrap 2>/dev/null || true
  $SUDO docker run -d --name derper2-bootstrap \
    -v derp-vpn4-v2_derper2_certs:/data/derper-certs \
    -p 80:80 -p 443:443 \
    derper2-bootstrap \
    --hostname=vpn5.hangocthanh.io.vn --a=:443 --http-port=80 \
    --certmode=letsencrypt --certdir=/data/derper-certs --stun=false

  echo "  Cho cert duoc cap (toi da 90s)..."
  # derper --certmode=letsencrypt cap cert ON-DEMAND: chi thuc su goi Let's
  # Encrypt khi co ket noi TLS THAT toi voi dung SNI. Phai tu "go cua" bang
  # curl --resolve moi vong lap de kich hoat autocert, khong chi ngoi cho.
  OK=0
  i=1
  while [ "$i" -le 18 ]; do
    TRIGGER_CODE=$(curl -sk -m 8 --resolve vpn5.hangocthanh.io.vn:443:127.0.0.1 \
      -o /dev/null -w "%{http_code}" "https://vpn5.hangocthanh.io.vn/derp/probe" 2>&1 || echo "curl_err")
    echo "  [vong $i] trigger SNI vpn5 -> HTTP $TRIGGER_CODE"
    if $SUDO docker run --rm -v derp-vpn4-v2_derper2_certs:/data alpine:3.20 \
      sh -c 'find /data -maxdepth 1 -type f -name "vpn5.hangocthanh.io.vn*" ! -name "*+token" ! -name "*.cert_status" | grep -q .' 2>/dev/null; then
      OK=1
      break
    fi
    sleep 5
    i=$((i + 1))
  done
  echo "  --- derper2-bootstrap log: dong lien quan vpn5/cert (loc bot spam SNI vpn4) ---"
  $SUDO docker logs derper2-bootstrap 2>&1 | grep -iv "vpn4.hangocthanh" | tail -60 || true
  echo "  --- derper2-bootstrap log: 15 dong cuoi (khong loc) ---"
  $SUDO docker logs --tail 15 derper2-bootstrap 2>&1 || true
  $SUDO docker rm -f derper2-bootstrap 2>/dev/null || true

  echo "  Khoi phuc derper cu (derp-vpn4)"
  (cd ../derp-vpn4 && $SUDO docker compose start derper)
  sleep 5
  (cd ../derp-vpn4 && $SUDO docker compose ps)
  trap - EXIT

  if [ "$OK" != "1" ]; then
    echo "  LOI: khong lay duoc cert cho vpn5.hangocthanh.io.vn - dung lai, khong deploy derper2"
    exit 1
  fi
  echo "  Cert da san sang"
else
  echo "==> [3/5] Bo qua bootstrap (cert con han)"
fi

# Ghi .env cho tailscale sidecar (TS_AUTHKEY tu runner qua bien moi truong).
# Neu runner khong tao duoc key lan nay, dung lai key da luu tu lan truoc
# (preauthkey reusable=true nen van con hieu luc) - giong pattern derp-vpn4.
if [ -z "${TS_AUTHKEY:-}" ] && [ -f ".ts_authkey" ]; then
  TS_AUTHKEY=$(cat .ts_authkey | tr -d '\n\r')
  echo "  Dung .ts_authkey da luu: ${TS_AUTHKEY:0:8}..."
fi
if [ -n "${TS_AUTHKEY:-}" ]; then
  printf '%s' "$TS_AUTHKEY" > .ts_authkey
  chmod 600 .ts_authkey
fi
umask 077
printf 'TS_AUTHKEY=%s\n' "${TS_AUTHKEY:-}" > .env

echo "==> [4/5] Khoi dong derper2 (steady-state, port 8443/8080/3479, doc cert tu volume)"
# --certmode=manual doc cap file rieng <hostname>.crt + <hostname>.key,
# khac voi dinh dang autocert.DirCache (1 file PEM gop chung key+cert,
# ten = hostname, khong duoi) ma buoc bootstrap [3/5] tao ra. Tach ra truoc
# khi khoi dong steady-state, neu khong derper se bao "no such file".
$SUDO docker run --rm -v derp-vpn4-v2_derper2_certs:/data alpine:3.20 sh -c '
  src=/data/vpn5.hangocthanh.io.vn
  if [ -f "$src" ]; then
    # QUAN TRONG: "openssl x509 -in .. -out .." chi lay 1 khoi CERTIFICATE
    # DAU TIEN (leaf), lam mat chain trung gian (LE tra ve leaf+intermediate
    # trong file cache goc). Client xac thuc TLS day du (vd. fetch() cua
    # dashboard) se fail chain incomplete du curl -k van "thanh cong" vi bo
    # qua xac thuc. Dung sed lay TAT CA khoi CERTIFICATE de giu nguyen chain.
    sed -n "/BEGIN CERTIFICATE/,/END CERTIFICATE/p" "$src" > "$src.crt"
    sed -n "/BEGIN.*PRIVATE KEY/,/END.*PRIVATE KEY/p" "$src" > "$src.key"
  fi
' || true
$SUDO docker compose up -d --build --force-recreate --remove-orphans

echo "==> [5/5] Kiem tra derper2 + derper cu (khong bi anh huong)"
sleep 5
CODE2=$(curl -sk -o /dev/null -w "%{http_code}" "https://vpn5.hangocthanh.io.vn:8443/derp/probe" 2>/dev/null || echo 000)
echo "  derper2 (vpn5.hangocthanh.io.vn:8443) /derp/probe: HTTP $CODE2"
CODE1=$(curl -sk -o /dev/null -w "%{http_code}" "https://vpn4.hangocthanh.io.vn/derp/probe" 2>/dev/null || echo 000)
echo "  derper cu (vpn4.hangocthanh.io.vn) /derp/probe: HTTP $CODE1 (phai van la 200)"
$SUDO docker logs --tail 20 derper2 2>&1 || true
