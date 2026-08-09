#!/bin/bash
# route-agent — quyet dinh vpngw CO advertise subnet route hay khong, dua tren
# duong VPN co THAT SU song hay khong (advertise-on-healthy).
#
# Chay tren HOST vpn4 (systemd timer), KHONG chay trong container vpn-gw. Ly do:
# no can `tailscale set` tren socket cua ts-vpngw, ma mount socket LocalAPI vao
# container dang chay tinyproxy — thu mo cho ca tailnet voi ACL `*->*` — se bien
# mot lo hong tinyproxy/openvpn thanh quyen dieu khien node (`logout`,
# `--login-server=<ke tan cong>`, doc nodekey). Giu container proxy bat luc.
#
# ─── Vi sao khong de containerboot lo viec nay ─────────────────────────────
# containerboot ap TS_ROUTES vo dieu kien luc khoi dong (tailscaled.go:139-141
# qua `up`, :172-174 qua `set`), trong khi TUN_WAIT=90 bao dam tun0 chua len
# trong hang chuc giay dau. Neu itop offline dung luc do, gateway gianh primary
# route trong trang thai chua forward duoc gi. Nen compose de TS_ROUTES RONG va
# file nay la NGUOI GHI DUY NHAT.
#
# ─── Vi sao probe TCP chu khong phai ping/link-state ───────────────────────
# Do tren prod 2026-08-09:
#   - ping 10.121.124.155 that bai 100% (may dich chan ICMP) nhung TCP 3389 bat
#     tay THANH CONG  -> ping se bao "chet" khi duong dang song.
#   - ca dai 10.121.13.x timeout du CO route trong tun0 (Bitel chan theo TAI
#     KHOAN) trong khi 10.121.124.x thong -> link-state tun0 UP se bao "song"
#     khi duong da chet.
# Chi TCP toi dung cong dich vu moi noi len su that.
#
# ─── Chong dao dong (flapping) ─────────────────────────────────────────────
# Moi lan primary route doi, headscale phat FULL MAP cho MOI node dang ket noi
# (hscontrol/mapper/batcher_lockfree.go:288-306). Mot tun0 chap chon 30s ma
# khong co hysteresis se tu DoS control plane — nhat la khi headscale dang
# co-host cung dashboard + Postgres tren vpn6.
set -uo pipefail

TS_CONTAINER="${TS_CONTAINER:-ts-vpngw}"
GW_CONTAINER="${GW_CONTAINER:-vpn-gw}"
ROUTES="${VPN_GW_ROUTES:-}"                       # rong = tinh nang TAT
PROBE_TARGET="${PROBE_TARGET:-10.121.124.155:3389}"
PROBE_TIMEOUT="${PROBE_TIMEOUT:-4}"
FAIL_THRESHOLD="${FAIL_THRESHOLD:-3}"             # 3 lan fail lien tiep -> rut
OK_THRESHOLD="${OK_THRESHOLD:-6}"                 # 6 lan OK lien tiep -> advertise
MIN_HOLD_SEC="${MIN_HOLD_SEC:-300}"               # giu it nhat 5' sau khi rut
MAX_FLAPS_PER_HOUR="${MAX_FLAPS_PER_HOUR:-4}"     # vuot -> khoa o trang thai rut
STATE_DIR="${STATE_DIR:-/var/lib/vpngw-route-agent}"

mkdir -p "$STATE_DIR"
F_OK="$STATE_DIR/ok_streak"; F_FAIL="$STATE_DIR/fail_streak"
F_STATE="$STATE_DIR/advertised"                   # "1" | "0"
F_LASTCHG="$STATE_DIR/last_change_epoch"
F_FLAPS="$STATE_DIR/flaps"                        # dong: epoch cua moi lan doi
F_LOCK="$STATE_DIR/locked"                        # ton tai = khoa o trang thai rut

log() { echo "$(date -u +%FT%TZ) route-agent: $*"; }
rd()  { cat "$1" 2>/dev/null || echo "${2:-0}"; }

[ -n "$ROUTES" ] || { log "VPN_GW_ROUTES rong -> khong lam gi (tinh nang tat)"; exit 0; }

# ── probe: TCP toi dich, chay TRONG netns cua gateway (host khong co route 10.121.x)
# KHONG dung `nc -z` (busybox alpine khong bao dam co co do). Dang duoi day chay
# duoc tren ca busybox lan openbsd-netcat — xem probe_ok() trong entrypoint.sh.
host="${PROBE_TARGET%%:*}"; port="${PROBE_TARGET##*:}"
if docker exec "$GW_CONTAINER" nc -w "$PROBE_TIMEOUT" "$host" "$port" </dev/null >/dev/null 2>&1; then
  probe=ok
else
  probe=fail
fi

ok=$(rd "$F_OK"); fail=$(rd "$F_FAIL")
if [ "$probe" = ok ]; then ok=$((ok+1)); fail=0; else fail=$((fail+1)); ok=0; fi
echo "$ok" >"$F_OK"; echo "$fail" >"$F_FAIL"

cur=$(rd "$F_STATE" 0)
now=$(date +%s)
last=$(rd "$F_LASTCHG" 0)

# ── dem so lan lat trong 1 gio gan nhat (chong dao dong)
if [ -f "$F_FLAPS" ]; then
  awk -v cut=$((now-3600)) '$1>cut' "$F_FLAPS" >"$F_FLAPS.tmp" && mv "$F_FLAPS.tmp" "$F_FLAPS"
fi
flaps=$(wc -l <"$F_FLAPS" 2>/dev/null || echo 0)

apply() { # $1 = chuoi routes ("" de rut)
  docker exec "$TS_CONTAINER" tailscale set --advertise-routes="$1"
}

if [ -f "$F_LOCK" ]; then
  log "DANG KHOA (lat qua $MAX_FLAPS_PER_HOUR lan/gio) — giu trang thai rut. Xoa $F_LOCK de mo."
  exit 0
fi

if [ "$fail" -ge "$FAIL_THRESHOLD" ] && [ "$cur" = "1" ]; then
  if apply ""; then
    echo 0 >"$F_STATE"; echo "$now" >"$F_LASTCHG"; echo "$now" >>"$F_FLAPS"
    log "RUT advertise (probe $PROBE_TARGET fail $fail lan lien tiep)"
    if [ "$((flaps+1))" -ge "$MAX_FLAPS_PER_HOUR" ]; then
      : >"$F_LOCK"
      log "CANH BAO: lat $((flaps+1)) lan trong 1 gio -> KHOA o trang thai rut (fail-safe: itop la duong chinh)"
    fi
  else
    log "LOI: khong rut duoc advertise"
  fi
  exit 0
fi

if [ "$ok" -ge "$OK_THRESHOLD" ] && [ "$cur" != "1" ]; then
  if [ "$((now-last))" -lt "$MIN_HOLD_SEC" ]; then
    log "probe OK $ok lan nhung con $((MIN_HOLD_SEC-(now-last)))s cooldown -> chua advertise"
    exit 0
  fi
  if apply "$ROUTES"; then
    echo 1 >"$F_STATE"; echo "$now" >"$F_LASTCHG"; echo "$now" >>"$F_FLAPS"
    log "ADVERTISE $ROUTES (probe $PROBE_TARGET OK $ok lan lien tiep)"
  else
    log "LOI: khong advertise duoc"
  fi
  exit 0
fi

log "probe=$probe ok=$ok fail=$fail advertised=$cur flaps1h=$flaps — khong doi gi"
