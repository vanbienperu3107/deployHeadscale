#!/bin/bash
# Build derper DUNG nhu deploy (docker compose build tren compose that cua stack)
# roi chay image do voi CHINH bo co trong compose, chi thay cert Let's Encrypt
# bang cert tu ky (CI khong co domain/LE). Kiem tra:
#   1. image build ra dung TAILSCALE_VERSION trong compose
#   2. derper chap nhan moi co prod (co sai/khong con ton tai -> derper chet ngay)
#   3. TLS tren :443 trong container + /derp/probe 200
#   4. bat tay DERP that (derpdial, doc them 1 frame) thanh cong
#
# Dung: bash test/derp_compose_build.sh derp-vpn4|derp-vpn6
# Can: docker (compose v2), openssl, python3, go (cho derpdial).
set -euo pipefail

STACK="${1:?can ten stack, vd derp-vpn4}"
COMPOSE="$STACK/docker-compose.yml"
NAME="ci-$STACK"
WORK="$(mktemp -d)"
PORT=18443

cleanup() {
  docker logs "$NAME" >"$WORK/derper.log" 2>&1 || true
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> [1/5] docker compose build derper ($COMPOSE) — y het lenh deploy"
docker compose -f "$COMPOSE" build derper
IMAGE=$(docker compose -f "$COMPOSE" config --images | head -1)
docker image inspect "$IMAGE" >/dev/null
WANT=$(docker compose -f "$COMPOSE" config --format json \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["services"]["derper"]["build"]["args"]["TAILSCALE_VERSION"])')
GOT=$(docker run --rm "$IMAGE" --version | head -1)
echo "  image=$IMAGE  mong=$WANT  derper --version=$GOT"
case "$GOT" in
  "${WANT#v}"*) ;;
  *) echo "FAIL: version khong khop"; exit 1 ;;
esac

echo "==> [2/5] Tao CA + cert tu ky cho 'localhost' (thay Let's Encrypt)"
CERTDIR="$WORK/certs"; mkdir -p "$CERTDIR"
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 1 \
  -subj /CN=derp-ci-ca -keyout "$WORK/ca.key" -out "$WORK/ca.crt" 2>/dev/null
openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -subj /CN=localhost \
  -keyout "$CERTDIR/localhost.key" -out "$WORK/l.csr" 2>/dev/null
printf 'subjectAltName=DNS:localhost\nbasicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\n' >"$WORK/ext"
openssl x509 -req -in "$WORK/l.csr" -CA "$WORK/ca.crt" -CAkey "$WORK/ca.key" \
  -CAcreateserial -days 1 -extfile "$WORK/ext" -out "$CERTDIR/localhost.crt" 2>/dev/null
chmod 644 "$CERTDIR"/*

echo "==> [3/5] Chay derper voi co PROD tu compose (chi doi hostname/certmode/certdir)"
mapfile -t ARGS < <(docker compose -f "$COMPOSE" config --format json | python3 -c '
import sys, json
cmd = json.load(sys.stdin)["services"]["derper"]["command"]
out = []
for a in cmd:
    k = a.split("=", 1)[0]
    if k == "--hostname":   a = "--hostname=localhost"
    elif k == "--certmode": a = "--certmode=manual"
    elif k == "--certdir":  a = "--certdir=/certs"
    out.append(a)
assert "--a=:443" in out, "compose phai nghe --a=:443 (TLS trong container)"
print("\n".join(out))')
printf '  co: %s\n' "${ARGS[*]}"
docker run -d --name "$NAME" -p "127.0.0.1:${PORT}:443" \
  -v "$CERTDIR:/certs:ro" "$IMAGE" "${ARGS[@]}" >/dev/null

CODE=000
for i in $(seq 1 15); do
  sleep 2
  if [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" != "true" ]; then
    echo "FAIL: derper da thoat (co prod khong hop le voi ban moi?)"
    docker logs "$NAME" 2>&1 | tail -30
    exit 1
  fi
  CODE=$(curl -s --cacert "$WORK/ca.crt" -o /dev/null -w '%{http_code}' \
    "https://localhost:${PORT}/derp/probe" || echo 000)
  [ "$CODE" = "200" ] && break
  echo "  lan $i: HTTP $CODE, cho them..."
done

echo "==> [4/5] /derp/probe qua TLS (verify bang CA CI)"
echo "  HTTP $CODE"
[ "$CODE" = "200" ] || { docker logs "$NAME" 2>&1 | tail -30; echo "FAIL: probe"; exit 1; }

echo "==> [5/5] Bat tay DERP that bang derpdial (client cung version tailscale)"
(cd scripts/derpdial && go build -o "$WORK/derpdial" .)
"$WORK/derpdial" -url "https://localhost:${PORT}/derp" -ca "$WORK/ca.crt" -n 5 -min-ok 5

echo "  Log derper:"; docker logs "$NAME" 2>&1 | tail -8 | sed 's/^/    /'
echo "OK: $STACK — derper $GOT build bang compose, chay co prod, TLS + bat tay DERP thanh cong"
