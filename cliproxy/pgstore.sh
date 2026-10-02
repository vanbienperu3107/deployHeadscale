#!/usr/bin/env bash
# Bat/tat/kiem kho Postgres (PGSTORE) cho CLIProxy tren vpn4. Chay tu thu muc
# cliproxy/; deploy-cliproxy.yml goi, chay tay cung duoc:
#
#   bash pgstore.sh snapshot-keys          # TRUOC moi thay doi: gom moi khoa cu
#   PGSTORE_DSN=... bash pgstore.sh enable # kiem DB, backup, seed lan dau, ghi .env
#   bash pgstore.sh off                    # PGSTORE_DSN rong: tat, keo config/token ve file
#   bash pgstore.sh verify                 # sau compose up: kho dung + MOI khoa cu goi duoc
#   bash pgstore.sh export                 # spool DB -> config.yaml + auths/ (rollback tay)
#
# Vi sao la file rieng: appleboy/ssh-action chen dong kiem exit code sau MOI dong
# script nen cam heredoc va else (test_cliproxy_config.py). Logic re nhanh + rollback
# chi viet an toan o day.
#
# Nguyen tac (quyet dinh nguoi dung 2026-10-02):
#   1. DB la NGUON SU THAT cua config + token; deploy chi SEED khi DB trong.
#   2. Khoa API: chi THEM khoa thieu (file dung chung OpenCode + secret), khong xoa.
#   3. KHOA CU PHAI CON DUNG DUOC: moi khoa dang chay truoc deploy deu duoc dua vao
#      danh sach can giu, them lai qua Management API neu thieu, roi goi that
#      /v1/models bang TUNG khoa. Mot khoa 401 = deploy do (+ rollback neu vua bat).
#   4. Rollback tu dong chi xoa du lieu DB khi CHINH lan nay vua seed; DB co du lieu
#      tu truoc thi giu nguyen, chi tat PGSTORE.
set -euo pipefail

cd "$(dirname "$0")"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

PSQL_IMAGE="${PSQL_IMAGE:-postgres:16-alpine}"
NETWORK="${PGSTORE_NETWORK:-cliproxy_chatdb}"
STATE=".pgstore-state"
ENV_FILE=".pgstore.env"
WANTED=".keys-wanted"
SPOOL="pgstore-spool"
SPOOL_CFG="$SPOOL/pgstore/config/config.yaml"
SPOOL_AUTHS="$SPOOL/pgstore/auths"
BACKUP_DIR="${PGSTORE_BACKUP_DIR:-backups}"
API_PORT="${CLIPROXY_PUBLIC_PORT:-28417}"
export CLIPROXY_PUBLIC_PORT="$API_PORT"

log() { echo "  [pgstore] $*"; }

# Spool do proxy (root trong container) ghi voi quyen 0700 -> user deploy khong
# phai root thi phai doc qua sudo, roi tra quyen so huu ve user deploy.
spool_pull() {
  local dst_cfg="$1" dst_auths="$2"
  if $SUDO test -s "$SPOOL_CFG"; then
    $SUDO cat "$SPOOL_CFG" > "$dst_cfg"
    chmod 600 "$dst_cfg"
  fi
  if [ -n "$dst_auths" ]; then
    mkdir -p "$dst_auths"
    chmod 700 "$dst_auths"
    $SUDO sh -c 'cp "$1"/*.json "$2"/ 2>/dev/null || true' _ "$SPOOL_AUTHS" "$dst_auths"
    $SUDO chown -R "$(id -u):$(id -g)" "$dst_auths"
    chmod 600 "$dst_auths"/*.json 2>/dev/null || true
  fi
}

seedctl() {
  $SUDO docker run --rm --network "$NETWORK" --env-file "$ENV_FILE" \
    -v "$PWD:/w:ro" "$PSQL_IMAGE" sh /w/pgstore-seed.sh "$@"
}

env_get() {
  grep "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true
}

set_env() {
  touch .env
  grep -v "^$1=" .env > .env.tmp || true
  printf '%s=%s\n' "$1" "$2" >> .env.tmp
  mv .env.tmp .env
  chmod 600 .env
}

state_get() {
  grep "^$1=" "$STATE" 2>/dev/null | tail -1 | cut -d= -f2- || true
}

backup() {
  mkdir -p "$BACKUP_DIR"
  chmod 700 "$BACKUP_DIR"
  local bk="$BACKUP_DIR/cliproxy-$1-$(date +%Y%m%d-%H%M%S).tgz"
  local items="config.yaml auths"
  if $SUDO test -d "$SPOOL/pgstore"; then items="$items $SPOOL/pgstore"; fi
  # shellcheck disable=SC2086
  $SUDO tar czf "$bk" $items 2>/dev/null || true
  $SUDO chown "$(id -u):$(id -g)" "$bk" 2>/dev/null || true
  chmod 600 "$bk" 2>/dev/null || true
  log "backup -> $bk"
}

# Gom MOI khoa dang co hieu luc truoc deploy: config.yaml cu (dang chay khi PGSTORE
# tat), spool cua DB (dang chay khi PGSTORE bat), va config.yaml moi render (file
# dung chung OpenCode + secret). Goi TRUOC render-config de config.yaml cu chua
# bi ghi de -> deploy chep config.yaml cu ra .config.prev.yaml truoc.
snapshot_keys() {
  umask 077
  rm -f .spool-config.yaml
  spool_pull .spool-config.yaml ""
  python3 pgstore-keys.py extract .config.prev.yaml .spool-config.yaml config.yaml > "$WANTED"
  rm -f .spool-config.yaml
  chmod 600 "$WANTED"
  log "so khoa can giu: $(wc -l < "$WANTED")"
  if [ "$(wc -l < "$WANTED")" -lt 1 ]; then
    echo "::error::Khong tim thay khoa API nao de giu — dung lai de khong khoa ngoai client"
    exit 1
  fi
}

enable() {
  : "${PGSTORE_DSN:?thieu PGSTORE_DSN}"
  umask 077
  printf 'PGSTORE_DSN=%s\n' "$PGSTORE_DSN" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  # Docker tu tao ./pgstore-spool voi chu root neu bind mount chay truoc -> phai sudo.
  $SUDO mkdir -p "$SPOOL"
  $SUDO chmod 700 "$SPOOL"
  : > "$STATE"
  echo "WAS_ENABLED=$( [ -n "$(env_get PGSTORE_DSN)" ] && echo 1 || echo 0 )" >> "$STATE"

  # Ten service duong ham; CI dat rong vi dung container postgres gia lap mang alias.
  local tunnel="${PGSTORE_TUNNEL_SERVICE-cliproxy-pg-tunnel}"
  if [ -n "$tunnel" ]; then
    log "bat duong ham Postgres ($tunnel)"
    $SUDO docker compose up -d "$tunnel"
  fi
  local ok=0
  for _ in $(seq 1 30); do
    if seedctl check > /tmp/pgstore-check.out 2>&1; then ok=1; break; fi
    sleep 2
  done
  if [ "$ok" != "1" ]; then
    cat /tmp/pgstore-check.out >&2 || true
    # KHONG thoat o day: config.yaml vua render co the da lam rot khoa cu (khoa
    # them tay), va chi buoc verify moi them lai chung. Ghi dau loi, giu che do
    # hien tai, de deploy chay tiep toi verify roi moi bao do.
    echo "ENABLE_FAILED=1" >> "$STATE"
    echo "::error::Khong ket noi/kiem duoc kho Postgres — GIU NGUYEN che do hien tai, khong bat PGSTORE"
    return 0
  fi
  log "$(grep '^SCHEMA=' /tmp/pgstore-check.out || true)"

  local need src
  need=$(seedctl need-seed | grep '^NEED_SEED=' | cut -d= -f2)
  if [ "$need" = "1" ]; then
    backup pre-pgstore
    # Seed tu config DANG CHAY (.config.prev.yaml = ban truoc khi render ghi de):
    # no chua Gemini/OpenAI key... da them qua web. Config vua render chi co
    # template + khoa API -> seed tu do la mat het provider key them tay.
    # Khoa API moi (file dung chung/secret) se duoc them o buoc verify.
    src=config.yaml
    if [ -s .config.prev.yaml ] && grep -q 'api-keys' .config.prev.yaml; then src=.config.prev.yaml; fi
    # PGSTORE tung bat (DB bi xoa/lam moi): spool moi la ban moi nhat, khong phai file.
    rm -f .spool-config.yaml
    spool_pull .spool-config.yaml ""
    if [ -s .spool-config.yaml ] && grep -q 'api-keys' .spool-config.yaml; then src=.spool-config.yaml; fi
    log "seed config tu $src"
    seedctl seed "/w/$src" /w/auths | tee -a "$STATE"
    rm -f .spool-config.yaml
  else
    log "DB da co du lieu -> KHONG seed, khong ghi de (DB la nguon su that)"
    printf 'SEEDED_CONFIG=0\nSEEDED_AUTH=0\n' >> "$STATE"
    seedctl count | tee -a "$STATE"
  fi
  set_env PGSTORE_DSN "$PGSTORE_DSN"
  log "PGSTORE_DSN da ghi vao .env -> cliproxy doc config + token tu Postgres"
}

# PGSTORE_DSN rong ma lan truoc dang bat: keo config + token moi nhat tu spool ve
# file truoc khi tat, de key/token them qua web luc dung DB khong bien mat.
off() {
  : > "$STATE"
  if [ -z "$(env_get PGSTORE_DSN)" ]; then
    set_env PGSTORE_DSN ""
    log "PGSTORE dang tat, giu nguyen"
    return 0
  fi
  log "PGSTORE dang bat nhung secret/DSN rong -> tat va keo du lieu ve file"
  backup pre-disable
  spool_pull config.yaml auths
  set_env PGSTORE_DSN ""
}

rollback() {
  echo "::error::$1"
  local sc sa
  sc=$(state_get SEEDED_CONFIG)
  sa=$(state_get SEEDED_AUTH)
  set_env PGSTORE_DSN ""
  if [ "${sc:-0}" != "0" ] || [ "${sa:-0}" != "0" ]; then
    log "lan nay vua seed -> xoa ban sao trong DB de lan sau seed lai tu dau"
    seedctl reset || true
  else
    log "DB co du lieu tu truoc -> GIU NGUYEN, chi tat PGSTORE"
    # Dang dung DB tu truoc: keo ban moi nhat ve file de khong mat key them tu web.
    spool_pull config.yaml auths
  fi
  $SUDO docker compose up -d --force-recreate --no-deps cliproxy
  # Sau rollback van phai bao dam khoa cu dung duoc. Bo qua sync neu management
  # key da bi tu choi (moi lan sai la mot buoc toi lenh ban IP 30 phut).
  if [ "${MGMT_REJECTED:-0}" != "1" ]; then python3 pgstore-keys.py sync "$WANTED" || true; fi
  python3 pgstore-keys.py check "$WANTED" || true
  log "da quay ve config.yaml + auths/"
  exit 1
}

verify() {
  local dsn
  dsn=$(env_get PGSTORE_DSN)
  if [ -n "$dsn" ]; then
    local up=0 logs
    for _ in $(seq 1 30); do
      # Doc log vao bien roi so khop: `docker logs | grep -q` duoi pipefail co the
      # tra loi SIGPIPE (grep thoat som) -> dieu kien sai du chuoi co trong log.
      logs=$($SUDO docker logs cliproxy 2>&1 || true)
      if [[ "$logs" == *"postgres-backed token store enabled"* ]]; then up=1; break; fi
      if [[ "$logs" == *"failed to initialize postgres"* || "$logs" == *"failed to bootstrap postgres"* ]]; then break; fi
      sleep 2
    done
    if [ "$up" != "1" ]; then
      $SUDO docker logs --tail 40 cliproxy 2>&1 || true
      rollback "cliproxy khong bat duoc postgres-backed token store"
    fi
    log "cliproxy: postgres-backed token store enabled"
  fi

  # Khoa cu: them khoa thieu (vao DB hoac config.yaml, tuy kho dang bat) roi goi
  # that bang TUNG khoa.
  local rc=0
  python3 pgstore-keys.py sync "$WANTED" || rc=$?
  if [ "$rc" = "3" ]; then
    # Management key lech (vd doi tren web ma chua cap nhat secret). Khong phai loi
    # cua kho: KHONG rollback, van kiem khoa ben duoi; neu khoa cu con chay thi chi canh bao.
    MGMT_REJECTED=1
    echo "::warning::CLIPROXY_MGMT_KEY bi proxy tu choi — khong them duoc khoa thieu. Cap nhat secret cho khop key dang dung tren web."
  elif [ "$rc" != "0" ]; then
    if [ -n "$dsn" ]; then rollback "Khong them lai duoc khoa cu qua Management API"; fi
    echo "::error::Khong them lai duoc khoa cu qua Management API"
    exit 1
  fi
  if ! python3 pgstore-keys.py check "$WANTED"; then
    if [ -n "$dsn" ]; then rollback "Co khoa cu khong con goi duoc sau khi bat PGSTORE"; fi
    echo "::error::Co khoa cu khong con goi duoc"
    exit 1
  fi

  if [ -n "$dsn" ]; then
    local before after
    before=$(ls -1 auths/*.json 2>/dev/null | wc -l)
    after=$($SUDO docker exec cliproxy sh -c 'ls -1 /pgstore-spool/pgstore/auths/*.json 2>/dev/null | wc -l' || echo 0)
    log "token: file cu=$before, trong DB/spool=$after"
    if [ "$(state_get SEEDED_AUTH)" != "0" ] && [ "${after:-0}" -lt "$before" ]; then
      rollback "Token trong DB ($after) it hon file cu ($before) ngay sau khi seed"
    fi
    seedctl count
  fi
  if [ "$(state_get ENABLE_FAILED)" = "1" ]; then
    echo "::error::Khoa cu van goi duoc, nhung KHONG bat duoc kho Postgres (xem loi o buoc 4b)"
    exit 1
  fi
}

export_db() {
  $SUDO test -s "$SPOOL_CFG" || { echo "spool chua co config — PGSTORE chua tung chay?" >&2; exit 1; }
  backup before-export
  spool_pull config.yaml auths
  log "da export spool -> config.yaml + auths/"
}

case "${1:-}" in
  snapshot-keys) snapshot_keys ;;
  enable) enable ;;
  off) off ;;
  verify) verify ;;
  export) export_db ;;
  *) echo "dung: pgstore.sh snapshot-keys|enable|off|verify|export" >&2; exit 2 ;;
esac
