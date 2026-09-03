#!/bin/sh
# Ghep block status.hangocthanh.io.vn vao Caddyfile cua memory-stack tren vpn6
# va noi container uptime-kuma vao network cua Caddy.
#
# - Idempotent: chay lai khong pha gi (block da co -> chi dam bao network + reload bo qua).
# - An toan: backup Caddyfile truoc, `caddy validate` TRONG container truoc khi
#   reload; validate fail -> restore backup, KHONG reload (giu config dang chay).
# - Duong dan Caddyfile + network KHONG hardcode: do tu container Caddy dang chay
#   (tranh doan sai path tren vpn6 — governance: never guess).
#
# Upstream: Caddy bridge-network khong voi duoc 127.0.0.1:3001 cua host, nen
# noi uptime-kuma vao network Caddy va proxy toi uptime-kuma:3001. Neu Caddy
# chay network_mode=host thi dung 127.0.0.1:3001 truc tiep.
# Tong quat hoa: DOMAIN/SVC_CT/SVC_PORT override duoc qua env de tai dung cho
# dich vu khac sau Caddy (vd Portainer). Mac dinh = Uptime Kuma.
set -eu

DOMAIN="${DOMAIN:-status.hangocthanh.io.vn}"
KUMA_CT="${SVC_CT:-uptime-kuma}"
SVC_PORT="${SVC_PORT:-3001}"

# 1) Tim container Caddy dang chay (memory-stack).
CADDY_CT=$(docker ps --format '{{.Names}} {{.Image}}' | awk 'tolower($0) ~ /caddy/ {print $1; exit}')
if [ -z "$CADDY_CT" ]; then
  echo "LOI: khong tim thay container Caddy dang chay tren host nay" >&2
  exit 1
fi
echo "Caddy container: $CADDY_CT"

# 2) Xac dinh upstream theo network mode cua Caddy.
NETMODE=$(docker inspect "$CADDY_CT" --format '{{.HostConfig.NetworkMode}}')
if [ "$NETMODE" = "host" ]; then
  UPSTREAM="127.0.0.1:$SVC_PORT"
else
  CADDY_NET=$(docker inspect "$CADDY_CT" \
    --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' | head -n1)
  if [ -z "$CADDY_NET" ]; then
    echo "LOI: khong doc duoc network cua $CADDY_CT" >&2
    exit 1
  fi
  echo "Noi $KUMA_CT vao network $CADDY_NET (idempotent)"
  docker network connect "$CADDY_NET" "$KUMA_CT" 2>/dev/null || true
  UPSTREAM="$KUMA_CT:$SVC_PORT"
fi
echo "Upstream: $UPSTREAM"

# 3) Tim Caddyfile tren host qua mount /etc/caddy/Caddyfile.
CADDYFILE=$(docker inspect "$CADDY_CT" \
  --format '{{range .Mounts}}{{.Source}} {{.Destination}}{{"\n"}}{{end}}' \
  | awk '$2=="/etc/caddy/Caddyfile"{print $1; exit}')
if [ -z "$CADDYFILE" ] || [ ! -f "$CADDYFILE" ]; then
  echo "LOI: khong xac dinh duoc Caddyfile tren host (mount /etc/caddy/Caddyfile)" >&2
  exit 1
fi
echo "Caddyfile: $CADDYFILE"

# 4) Idempotent: block da ton tai -> xong (network o buoc 2 da dam bao).
if grep -q "$DOMAIN" "$CADDYFILE"; then
  echo "Block $DOMAIN da ton tai — khong sua Caddyfile."
  exit 0
fi

# 5) Backup roi append block.
BACKUP="${CADDYFILE}.bak-$(date +%Y%m%d-%H%M%S)"
cp "$CADDYFILE" "$BACKUP"
echo "Backup: $BACKUP"

cat >> "$CADDYFILE" <<EOF

# Uptime Kuma (deployHeadscale/uptime-kuma) — them tu dong boi setup-caddy.sh
$DOMAIN {
	reverse_proxy $UPSTREAM
}
EOF

# 6) Validate TRONG container (dung binary/plugin dang chay that).
if ! docker exec "$CADDY_CT" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
  echo "LOI: caddy validate FAIL — restore backup, KHONG reload" >&2
  cp "$BACKUP" "$CADDYFILE"
  exit 1
fi

# 7) Reload khong downtime.
docker exec "$CADDY_CT" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
echo "Da them + reload block $DOMAIN OK"
