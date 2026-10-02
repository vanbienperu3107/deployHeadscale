#!/bin/sh
# Thao tac voi kho Postgres cua CLIProxy (PGSTORE). Chay BEN TRONG container
# postgres:*-alpine (co psql) do pgstore.sh khoi chay tren mang cliproxy_chatdb:
#
#   pgstore-seed.sh check                     # ket noi duoc + tao bang neu chua co
#   pgstore-seed.sh need-seed                 # in NEED_SEED=0|1
#   pgstore-seed.sh seed <config.yaml> <dir>  # seed LAN DAU: chi ghi bang dang trong
#   pgstore-seed.sh count                     # in CONFIG_ROWS=.. AUTH_ROWS=..
#   pgstore-seed.sh reset                     # xoa config + auth (chi dung khi rollback)
#
# DSN lay tu bien moi truong PGSTORE_DSN (truyen qua --env-file, khong qua argv).
#
# "Chi seed lan dau" (quyet dinh cua nguoi dung 2026-10-02): khi da co du lieu thi
# database la nguon su that duy nhat — deploy KHONG ghi de api-keys, provider key
# hay token. config_store seed khi chua co dong 'config'; auth_store CHI seed o
# lan dau that su (ca hai bang deu trong) — xem nhanh `seed` ben duoi.
#
# Luoc do bang GIONG HET CLIProxyAPI tu tao (internal/store/postgresstore.go,
# EnsureSchema) de proxy khoi dong sau do thay bang da co va dung luon.
#
# Noi dung file di qua base64 de khong phai trich dan chuoi SQL: base64 chi gom
# [A-Za-z0-9+/=], an toan trong '...'. Ten file auth thanh khoa chinh -> chi chap
# nhan ky tu an toan, ten la thi DUNG lai thay vi bo qua am tham.
set -eu

: "${PGSTORE_DSN:?thieu PGSTORE_DSN}"

psql_q() {
  psql "$PGSTORE_DSN" -v ON_ERROR_STOP=1 -qtAX "$@"
}

b64() {
  base64 < "$1" | tr -d '\n'
}

ensure_tables() {
  psql_q <<'SQL'
CREATE TABLE IF NOT EXISTS config_store (
  id TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS auth_store (
  id TEXT PRIMARY KEY,
  content JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS cooldown_store (
  auth_id TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  content JSONB NOT NULL,
  deleted BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (auth_id, model)
);
SQL
}

config_rows() {
  psql_q -c "SELECT count(*) FROM config_store WHERE id = 'config'"
}

auth_rows() {
  psql_q -c "SELECT count(*) FROM auth_store"
}

cmd="${1:-}"
case "$cmd" in
  check)
    # Bang phai nam trong schema rieng (search_path cua role), KHONG phai public:
    # token OAuth roi vao public la lo cho moi role khac trong database `derp`.
    # Kiem TRUOC khi tao bang de khong de lai bang rac trong public.
    schema=$(psql_q -c "SELECT coalesce(current_schema(), '')")
    echo "SCHEMA=$schema"
    if [ -z "$schema" ] || { [ "$schema" = "public" ] && [ "${PGSTORE_ALLOW_PUBLIC:-0}" != "1" ]; }; then
      echo "search_path cua role khong tro vao schema rieng (dang: '${schema}') — chay migrate-cliproxy-store.yml truoc" >&2
      exit 3
    fi
    ensure_tables
    ;;
  need-seed)
    ensure_tables
    c=$(config_rows); a=$(auth_rows)
    # Thieu dong config la LUON phai seed: neu khong, CLIProxyAPI tu chep
    # config.example.yaml cua image (api-keys mau "your-api-key-1"...) vao DB va
    # mo cong 28417 voi khoa ai cung biet.
    if [ "$c" = "0" ]; then echo "NEED_SEED=1"; else echo "NEED_SEED=0"; fi
    ;;
  seed)
    cfg="${2:?thieu duong dan config.yaml}"
    dir="${3:?thieu thu muc auths}"
    ensure_tables
    seeded_cfg=0
    seeded_auth=0
    # Token chi seed o LAN DAU THAT SU (ca hai bang deu trong). Neu config da co
    # ma auth_store trong, nghia la nguoi dung da xoa het token qua web — chep lai
    # ./auths cu se hoi sinh tai khoan da go.
    first_time=0
    if [ "$(config_rows)" = "0" ] && [ "$(auth_rows)" = "0" ]; then first_time=1; fi
    if [ "$(config_rows)" = "0" ]; then
      if [ ! -s "$cfg" ]; then
        echo "config_store trong ma khong co config nguon ($cfg) de seed" >&2
        exit 4
      fi
      printf "INSERT INTO config_store (id, content) VALUES ('config', convert_from(decode('%s', 'base64'), 'UTF8')) ON CONFLICT (id) DO NOTHING;\n" "$(b64 "$cfg")" | psql_q
      seeded_cfg=1
    fi
    if [ "$first_time" = "1" ]; then
      # Mot transaction: hoac du tat ca token, hoac khong co gi (lan sau seed lai).
      {
        echo "BEGIN;"
        for f in "$dir"/*.json; do
          [ -f "$f" ] || continue
          name=$(basename "$f")
          case "$name" in
            *[!A-Za-z0-9._@+-]*)
              echo "ten file auth khong an toan: $name" >&2
              exit 5
              ;;
          esac
          [ -s "$f" ] || continue
          printf "INSERT INTO auth_store (id, content) VALUES ('%s', convert_from(decode('%s', 'base64'), 'UTF8')::jsonb) ON CONFLICT (id) DO NOTHING;\n" "$name" "$(b64 "$f")"
        done
        echo "COMMIT;"
      } > /tmp/pgstore-seed-auth.sql
      psql_q -f /tmp/pgstore-seed-auth.sql
      rm -f /tmp/pgstore-seed-auth.sql
      seeded_auth=$(auth_rows)
    fi
    echo "SEEDED_CONFIG=$seeded_cfg"
    echo "SEEDED_AUTH=$seeded_auth"
    echo "CONFIG_ROWS=$(config_rows)"
    echo "AUTH_ROWS=$(auth_rows)"
    ;;
  count)
    echo "CONFIG_ROWS=$(config_rows)"
    echo "AUTH_ROWS=$(auth_rows)"
    ;;
  reset)
    psql_q -c "BEGIN; DELETE FROM config_store; DELETE FROM auth_store; DELETE FROM cooldown_store; COMMIT;"
    echo "RESET=1"
    ;;
  *)
    echo "dung: pgstore-seed.sh check|need-seed|seed <config> <dir>|count|reset" >&2
    exit 2
    ;;
esac
