#!/bin/sh
# Heartbeat tung dich vu tren vpn4 -> Uptime Kuma (vpn6) qua Push monitor.
#
# Vi sao push thay vi de Kuma check chu dong: phan lon dich vu vpn4 khong lo
# cong ra ngoai (vpn-gw, fail2ban, ping-reporter, ts-vpngw...) va duong
# VN->vpn4 (Bitel) hay bi chan per-account — check tu ngoai vao khong tin duoc.
# Script nay chay LOCAL bang cron moi phut: container nao dang chay (va healthy
# neu co healthcheck) thi push token cua no; container chet -> KHONG push ->
# Kuma bao Telegram sau nguong (dat 120s trong UI).
#
# Config: /etc/kuma-heartbeat.conf, moi dong: <ten_container|host> <push_token>
#   host  <token>   -> luon push (vpn4 con song / con duong ra Internet)
#   derper abc123   -> push khi container derper Running (+healthy neu co)
# Dong bat dau bang # bi bo qua. Token lay tu URL Push monitor trong UI Kuma:
#   https://status.hangocthanh.io.vn/api/push/<TOKEN>
set -u

CONF="${1:-/etc/kuma-heartbeat.conf}"
KUMA_BASE="https://status.hangocthanh.io.vn/api/push"

[ -f "$CONF" ] || { echo "Khong thay $CONF" >&2; exit 1; }

push() {
  # -m 10: duong ra co the cham; cron chay lai sau 1 phut nen khong retry.
  curl -fsS -m 10 "$KUMA_BASE/$1?status=up&msg=ok" >/dev/null 2>&1 || true
}

while read -r NAME TOKEN _; do
  case "$NAME" in ""|\#*) continue;; esac
  [ -n "${TOKEN:-}" ] || continue

  if [ "$NAME" = "host" ]; then
    push "$TOKEN"
    continue
  fi

  RUNNING=$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null || echo false)
  # Container co healthcheck thi doi hoi healthy; khong co thi Running la du.
  HEALTH=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$NAME" 2>/dev/null || echo none)

  if [ "$RUNNING" = "true" ] && { [ "$HEALTH" = "none" ] || [ "$HEALTH" = "healthy" ]; }; then
    push "$TOKEN"
  else
    echo "SKIP $NAME (running=$RUNNING health=$HEALTH) -> Kuma se bao"
  fi
done < "$CONF"
