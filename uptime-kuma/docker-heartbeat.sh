#!/bin/sh
# Giam sat TOAN BO container Docker tren host nay -> 1 Push monitor Uptime Kuma.
#
# Cach hoat dong (auto-discover, khong liet ke tay):
#   - Quet `docker ps -a`. Moi container co restart policy always/unless-stopped
#     (tuc la DUOC KY VONG chay 24/7) ma khong Running, hoac Running nhung
#     healthcheck bao unhealthy -> tinh la CHET.
#   - Khong co container chet: push status=up, msg = "N containers ok".
#   - Co container chet: push status=DOWN, msg = ten cac container chet
#     -> Kuma bao Telegram dich danh container nao sap.
#   - Host chet / mat duong ra: khong push gi -> Kuma bao theo nguong heartbeat.
#   - Container moi them sau nay TU DONG duoc giam sat (mien co restart policy).
#
# Container stop TAY (restart policy 'no') khong tinh la chet — do la chu dich.
# Muon bo qua them container cu the: liet ke trong IGNORE cua file conf.
#
# Config /etc/kuma-heartbeat.conf (duoc `.`-source, chmod 600):
#   TOKEN=<push token cua monitor Push tren Kuma>
#   IGNORE=ten1,ten2        # tuy chon
#   KUMA_BASE=https://status.hangocthanh.io.vn/api/push   # tuy chon, mac dinh nhu vay
set -u

CONF="${1:-/etc/kuma-heartbeat.conf}"
[ -f "$CONF" ] || { echo "Khong thay $CONF" >&2; exit 1; }
. "$CONF"
KUMA_BASE="${KUMA_BASE:-https://status.hangocthanh.io.vn/api/push}"
IGNORE="${IGNORE:-}"
[ -n "${TOKEN:-}" ] || { echo "Thieu TOKEN trong $CONF" >&2; exit 1; }

DEAD=""
TOTAL=0
IMAGES=""

# docker ps -a: duyet MOI container (ke ca exited) de bat ca truong hop
# container 24/7 bi stop/creash ma docker khong keo len duoc.
for NAME in $(docker ps -a --format '{{.Names}}'); do
  case ",$IGNORE," in *",$NAME,"*) continue;; esac

  POLICY=$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$NAME" 2>/dev/null || echo no)
  case "$POLICY" in always|unless-stopped) ;; *) continue;; esac
  TOTAL=$((TOTAL+1))

  RUNNING=$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null || echo false)
  HEALTH=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$NAME" 2>/dev/null || echo none)

  if [ "$RUNNING" != "true" ] || { [ "$HEALTH" != "none" ] && [ "$HEALTH" != "healthy" ]; }; then
    IMG=$(docker inspect -f '{{.Config.Image}}' "$NAME" 2>/dev/null || echo '?')
    DEAD="$DEAD $NAME[$IMG]($RUNNING/$HEALTH)"
  else
    IMG=$(docker inspect -f '{{.Config.Image}}' "$NAME" 2>/dev/null || echo '?')
    IMAGES="$IMAGES $NAME=$IMG"
  fi
done

if [ -z "$DEAD" ]; then
  STATUS="up"
  # Nhung ten image dang chay vao msg (xem duoc o lich su heartbeat tren Kuma).
  # Kuma cat msg dai -> tu gioi han ~230 ky tu.
  MSG="$TOTAL ok |$IMAGES"
  if [ ${#MSG} -gt 230 ]; then
    MSG="$(printf '%s' "$MSG" | cut -c1-227)..."
  fi
else
  STATUS="down"; MSG="DEAD:$DEAD"
  echo "CANH BAO:$DEAD"
fi

# -G + --data-urlencode: msg co the chua space/(); -m 10 vi duong ra co the cham.
curl -fsS -m 10 -G "$KUMA_BASE/$TOKEN" \
  --data-urlencode "status=$STATUS" \
  --data-urlencode "msg=$MSG" >/dev/null 2>&1 || echo "Push len Kuma FAIL (duong ra?)" >&2
