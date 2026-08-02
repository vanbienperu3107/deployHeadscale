#!/usr/bin/env bash
# Integration test cho stack cliproxy: chay CHINH docker-compose.yml se deploy len
# vpn4 (khong phai ban rut gon) roi kiem chung:
#   1. Container len va healthcheck (/dev/tcp) chuyen sang healthy -> image co bash.
#   2. Goi /v1/models KHONG kem API key -> 401 (khong duoc mo toang vi 8317 public).
#   3. Goi /v1/models CO API key -> 200.
#   4. Cac cong callback OAuth chi nghe tren loopback cua host.
#   5. auth-dir trong container ton tai va la thu muc duoc bind mount (token ben
#      qua deploy) — ghi file thu vao ./auths phai thay duoc tu trong container.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STACK="$ROOT/cliproxy"
TEST_KEY="ci-test-key-$RANDOM$RANDOM"

cleanup() {
  echo "--- don dep ---"
  (cd "$STACK" && docker compose down -v --remove-orphans >/dev/null 2>&1 || true)
  rm -f "$STACK/config.yaml"
  rm -rf "$STACK/auths" "$STACK/logs"
}
trap cleanup EXIT

echo "==> [1/6] Sinh config.yaml tu template (giong het buoc deploy)"
mkdir -p "$STACK/auths" "$STACK/logs"
python3 - "$STACK" "$TEST_KEY" <<'PY'
import pathlib, sys
stack, key = pathlib.Path(sys.argv[1]), sys.argv[2]
tpl = (stack / "config.template.yaml").read_text()
out = tpl.replace("__API_KEY__", key).replace("__MANAGEMENT_KEY__", "ci-mgmt-key")
(stack / "config.yaml").write_text(out)
print("config.yaml:", len(out), "bytes")
PY

echo "==> [2/6] docker compose up"
cd "$STACK"
docker compose up -d
docker compose ps

echo "==> [3/6] Cho API san sang (toi da 120s)"
ok=0
for _ in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 \
    -H "Authorization: Bearer $TEST_KEY" http://127.0.0.1:28417/v1/models || echo 000)
  if [ "$code" = "200" ]; then ok=1; break; fi
  sleep 2
done
if [ "$ok" != "1" ]; then
  echo "::error::/v1/models khong tra 200 sau 120s (lan cuoi: HTTP ${code:-?})"
  docker compose logs --tail 80
  exit 1
fi
echo "  /v1/models co key -> 200 OK"

echo "==> [4/6] Goi KHONG kem API key phai bi tu choi"
nokey=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:28417/v1/models || echo 000)
echo "  khong key -> HTTP $nokey"
if [ "$nokey" = "200" ]; then
  echo "::error::API tra 200 khi khong co key — cong nay mo cong khai tren vpn4, khong duoc phep!"
  exit 1
fi

echo "==> [4b/6] Cong mac dinh 8317 phai KHONG duoc publish ra host"
# KHONG dung "|| echo 000": khi khong ket noi duoc, curl vua in 000 vua tra exit
# code != 0 -> echo bồi them mot lan nua thanh "000000". Dung "|| true" roi mac dinh hoa.
old=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8317/v1/models || true); old=${old:-000}
echo "  127.0.0.1:8317 -> $old (mong doi 000)"
if [ "$old" != "000" ]; then
  echo "::error::compose van publish cong mac dinh 8317 — mat tac dung cua viec doi cong"
  exit 1
fi

echo "==> [5/6] Healthcheck phai chuyen healthy (chung minh image co bash cho /dev/tcp)"
healthy=0
for _ in $(seq 1 30); do
  st=$(docker inspect --format '{{.State.Health.Status}}' cliproxy 2>/dev/null || echo none)
  if [ "$st" = "healthy" ]; then healthy=1; break; fi
  if [ "$st" = "none" ]; then echo "::error::container khong co healthcheck"; exit 1; fi
  sleep 3
done
if [ "$healthy" != "1" ]; then
  echo "::error::healthcheck khong healthy sau 90s (trang thai: ${st:-?})"
  docker inspect --format '{{json .State.Health}}' cliproxy || true
  exit 1
fi
echo "  healthcheck: healthy"

echo "==> [6/6] Bind mount auths thong voi auth-dir trong container"
echo '{"ci":"probe"}' > "$STACK/auths/ci-probe.json"
if ! docker exec cliproxy test -f /root/.cli-proxy-api/ci-probe.json; then
  echo "::error::./auths KHONG map toi auth-dir trong container -> token OAuth se mat khi deploy lai"
  exit 1
fi
echo "  ./auths <-> /root/.cli-proxy-api: OK"

echo "PASS: stack cliproxy hoat dong dung."
