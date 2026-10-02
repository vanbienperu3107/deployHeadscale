#!/usr/bin/env bash
# Integration that cho kho Postgres (PGSTORE): chay CHINH docker-compose.yml +
# pgstore.sh nhu deploy, voi Postgres that (thay cho duong ham sang vpn6) va anh
# proxy that. Kiem chung yeu cau 2026-10-02:
#   1. Bat PGSTORE: proxy bao "postgres-backed token store enabled".
#   2. KHOA CU: khoa them tay truoc do (chi co trong config.yaml cu) VAN goi duoc;
#      khoa trong file dung chung/secret duoc them vao.
#   3. Key them qua Management API (nhu tren web) nam trong DB va SONG qua
#      recreate + mot lan "deploy" nua (khong bi seed ghi de).
#   4. Token OAuth trong ./auths vao DB.
#   5. Tat PGSTORE (secret rong): config + token keo ve file, khoa cu van goi duoc.
set -euo pipefail

# Chay voi CHINH anh dang chay tren vpn4 (fork cliproxy_mod), khong phai tag mac dinh
# eceasy cu trong compose: kiem PGSTORE tren anh khac la kiem sai doi tuong.
# Ghi de bang CLIPROXY_IMAGE neu can.
export CLIPROXY_IMAGE="${CLIPROXY_IMAGE:-ghcr.io/vanbienperu3107/cliproxy_mod:main-df5a5b7}"
echo "anh proxy: $CLIPROXY_IMAGE"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STACK="$ROOT/cliproxy"
OLD_KEY="ci-old-web-key-$RANDOM$RANDOM"
NEW_KEY="ci-secret-key-$RANDOM$RANDOM"
MGMT="ci-mgmt-$RANDOM$RANDOM"
PGPASS="cistore$RANDOM$RANDOM$RANDOM"
PGC=cliproxy-pgstore-ci-db
TMP=$(mktemp -d)

cleanup() {
  echo "--- don dep ---"
  (cd "$STACK" && docker compose down -v --remove-orphans >/dev/null 2>&1 || true)
  docker rm -f "$PGC" >/dev/null 2>&1 || true
  (cd "$STACK" && docker compose down -v --remove-orphans >/dev/null 2>&1 || true)
  docker network rm edge cliproxy_chatdb >/dev/null 2>&1 || true
  # spool/backups do container (root) ghi -> can sudo de xoa tren runner.
  sudo -n rm -rf "$STACK/pgstore-spool" "$STACK/backups" "$STACK/auths" 2>/dev/null || true
  rm -rf "$STACK/config.yaml" "$STACK/auths" "$STACK/logs" "$STACK/pgstore-spool" \
    "$STACK/backups" "$STACK/.env" "$STACK/.pgstore.env" "$STACK/.pgstore-state" \
    "$STACK/.keys-wanted" "$STACK/.config.prev.yaml" "$TMP"
}
trap cleanup EXIT

docker network inspect edge >/dev/null 2>&1 || docker network create edge >/dev/null
# Mang cliproxy_chatdb PHAI do compose tao (co label cua compose), neu tao tay thi
# compose tu choi dung lai. `compose create` tao mang ma khong chay container nao.
(cd "$STACK" && touch config.yaml && docker compose create --no-recreate cliproxy >/dev/null 2>&1 || true)
(cd "$STACK" && docker compose rm -fs cliproxy >/dev/null 2>&1 || true)
docker network inspect cliproxy_chatdb >/dev/null

echo "==> [1/8] Postgres that, alias cliproxy-pg-tunnel, ap migration 003"
docker run -d --name "$PGC" --network cliproxy_chatdb --network-alias cliproxy-pg-tunnel \
  -e POSTGRES_USER=derp -e POSTGRES_PASSWORD=derp -e POSTGRES_DB=derp postgres:16-alpine >/dev/null
# KHONG dung pg_isready qua socket: entrypoint chay mot server TAM (chi socket) de
# init roi tat va khoi dong lai -> socket bao san sang qua som. Server that moi nghe
# TCP, nen doi mot truy van qua 127.0.0.1 thanh cong.
pgok=0
for _ in $(seq 1 90); do
  if docker exec "$PGC" psql -h 127.0.0.1 -U derp -d derp -qtAc 'SELECT 1' >/dev/null 2>&1; then pgok=1; break; fi
  sleep 1
done
[ "$pgok" = "1" ] || { echo "::error::Postgres test khong len"; docker logs --tail 40 "$PGC"; exit 1; }
docker cp "$STACK/sql/003_cliproxy_store.sql" "$PGC:/tmp/003.sql"
docker exec "$PGC" psql -U derp -d derp -v ON_ERROR_STOP=1 -qf /tmp/003.sql
docker exec "$PGC" psql -U derp -d derp -v ON_ERROR_STOP=1 -qc "ALTER ROLE cliproxy_store WITH LOGIN PASSWORD '$PGPASS'"

echo "==> [2/8] Trang thai 'truoc deploy': config.yaml cu co khoa them tay + Gemini key + 1 token"
cd "$STACK"
mkdir -p auths logs
chmod 700 auths
printf '%s\n' "$NEW_KEY" > "$TMP/shared.key"
export CLIPROXY_KEY_FILE="$TMP/shared.key" CLIPROXY_API_KEY="$NEW_KEY" CLIPROXY_MGMT_KEY="$MGMT"
python3 render-config.py config.template.yaml config.yaml
# Mo phong: khoa cu chi co trong config dang chay (them tay qua web), khong co trong
# file dung chung hay secret.
python3 -c "import sys,pathlib;p=pathlib.Path('config.yaml');t=p.read_text();t=t.replace('api-keys:\n','api-keys:\n  - \"'+sys.argv[1]+'\"\n',1);t+='\ngemini-api-key:\n  - api-key: \"AIzaSy-ci-web-added\"\n';p.write_text(t)" "$OLD_KEY"
printf '{"type":"claude","email":"ci@example.com","access_token":"x","refresh_token":"y","expired":"2099-01-01T00:00:00Z"}' > auths/claude-ci@example.com.json
chmod 600 auths/*.json

deploy_like() {
  # Dung trinh tu cua deploy-cliproxy.yml (khong qua ssh-action).
  cp config.yaml .config.prev.yaml 2>/dev/null || true
  python3 render-config.py config.template.yaml config.yaml
  bash pgstore.sh snapshot-keys
  grep '^PGSTORE_DSN=' .env > .env.keep 2>/dev/null || true
  printf 'CLIPROXY_IMAGE=%s\n' "${CLIPROXY_IMAGE:-}" > .env
  cat .env.keep >> .env; rm -f .env.keep
  test -z "$1" || PGSTORE_TUNNEL_SERVICE="" PGSTORE_DSN="postgresql://cliproxy_store:$1@cliproxy-pg-tunnel:5432/derp?sslmode=disable" bash pgstore.sh enable
  test -n "$1" || bash pgstore.sh off
  docker compose up -d --no-deps cliproxy
  docker compose up -d --force-recreate --no-deps cliproxy
  bash pgstore.sh verify
  rm -f .config.prev.yaml
}

echo "==> [3/8] Chay proxy o che do file (giong vpn4 hien tai)"
docker compose up -d --no-deps cliproxy
for _ in $(seq 1 60); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OLD_KEY" http://127.0.0.1:28417/v1/models || true)
  [ "$c" = "200" ] && break; sleep 2
done
[ "$c" = "200" ] || { echo "::error::proxy che do file khong len"; docker compose logs --tail 60 cliproxy; exit 1; }

echo "==> [4/8] 'Deploy' bat PGSTORE"
deploy_like "$PGPASS"
docker logs cliproxy 2>&1 | grep -q 'postgres-backed token store enabled'

q() { docker exec "$PGC" psql -U derp -d derp -qtAXc "$1"; }
echo "==> [5/8] Kiem DB: config co khoa cu + Gemini key, token da vao"
cfg=$(q "SELECT content FROM cliproxy_store.config_store WHERE id='config'")
case "$cfg" in *"$OLD_KEY"*) ;; *) echo "::error::khoa cu khong co trong DB"; exit 1 ;; esac
case "$cfg" in *"$NEW_KEY"*) ;; *) echo "::error::khoa secret khong co trong DB"; exit 1 ;; esac
case "$cfg" in *"AIzaSy-ci-web-added"*) ;; *) echo "::error::Gemini key them tay bi mat khi seed"; exit 1 ;; esac
[ "$(q "SELECT count(*) FROM cliproxy_store.auth_store")" = "1" ] || { echo "::error::token khong vao DB"; exit 1; }
[ "$(q "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE '%_store'")" = "0" ]

echo "==> [6/8] Them key qua Management API (nhu web) -> phai vao DB"
WEB_KEY="ci-added-on-web-$RANDOM"
curl -sf -X PATCH -H "Authorization: Bearer $MGMT" -H 'Content-Type: application/json' \
  -d "{\"old\":\"$WEB_KEY\",\"new\":\"$WEB_KEY\"}" http://127.0.0.1:28417/v0/management/api-keys >/dev/null
for _ in $(seq 1 30); do
  q "SELECT content FROM cliproxy_store.config_store WHERE id='config'" | grep -q "$WEB_KEY" && break; sleep 1
done
q "SELECT content FROM cliproxy_store.config_store WHERE id='config'" | grep -q "$WEB_KEY" || { echo "::error::key them qua API khong ghi vao DB"; exit 1; }

echo "==> [7/8] 'Deploy' lan nua: KHONG ghi de key them tu web, moi khoa van goi duoc"
deploy_like "$PGPASS"
grep -q '^SEEDED_CONFIG=0' .pgstore-state
for k in "$OLD_KEY" "$NEW_KEY" "$WEB_KEY"; do
  c=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $k" http://127.0.0.1:28417/v1/models || true)
  [ "$c" = "200" ] || { echo "::error::mot khoa khong goi duoc sau redeploy (HTTP $c)"; exit 1; }
done

echo "==> [8/8] Tat PGSTORE (secret rong): keo ve file, moi khoa van goi duoc"
deploy_like ""
grep -q '^PGSTORE_DSN=$' .env
grep -q "$WEB_KEY" config.yaml || { echo "::error::key them tu web mat khi tat PGSTORE"; exit 1; }
test -s auths/claude-ci@example.com.json

echo "PASS: PGSTORE bat/tat duoc, khoa cu + key them tu web deu song."
