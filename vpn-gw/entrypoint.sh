#!/bin/bash
# entrypoint cho image vpn-gw. Dieu phoi dnsmasq (split-DNS) + openvpn (tun0) +
# tinyproxy (HTTP forward-proxy). Xem docs/plan-vpn-gateway-bitel.md.
set -euo pipefail

# ---- Cau hinh qua env (co mac dinh an toan, da kiem chung tren vpn4) ----
OVPN_CONFIG="${OVPN_CONFIG:-/config/client.ovpn}"
OVPN_AUTH="${OVPN_AUTH:-/config/auth.txt}"
PROXY_PORT="${PROXY_PORT:-8888}"
BITEL_DOMAIN="${BITEL_DOMAIN:-bitel.com.pe}"
BITEL_DNS1="${BITEL_DNS1:-10.121.127.193}"   # DNS noi bo Bitel (verified 2026-07-23)
BITEL_DNS2="${BITEL_DNS2:-10.121.127.194}"
UPSTREAM_DNS="${UPSTREAM_DNS:-1.1.1.1}"       # DNS public cho domain con lai
UPSTREAM_DNS2="${UPSTREAM_DNS2:-8.8.8.8}"
OVPN_SKIP="${OVPN_SKIP:-0}"                    # =1: bo qua openvpn (smoke test proxy)
TUN_WAIT="${TUN_WAIT:-60}"                     # so giay cho tun0 len
KILLSWITCH="${KILLSWITCH:-0}"                  # =1: chan dai Bitel neu tun0 down

log() { echo "$(date -u +%H:%M:%S) vpn-gw: $*"; }

# ---------------------------------------------------------------------------
# healthcheck: goi boi Docker HEALTHCHECK. Proxy phai song; neu dang chay VPN
# thi tun0 phai con len.
# ---------------------------------------------------------------------------
if [ "${1:-run}" = "healthcheck" ]; then
  pidof tinyproxy >/dev/null 2>&1 || { echo "tinyproxy chet"; exit 1; }
  if [ "$OVPN_SKIP" != "1" ]; then
    ip link show tun0 up >/dev/null 2>&1 || { echo "tun0 khong len"; exit 1; }
  fi
  exit 0
fi

# ---- 1. dnsmasq: split-DNS ----
# glibc (tinyproxy) -> 127.0.0.1 (dnsmasq) -> *.bitel.com.pe di DNS noi bo,
# con lai di DNS public. dnsmasq forward query khong EDNS khi client khong gui
# EDNS (glibc khong gui) -> tranh FORMERR cua DNS Bitel cu.
log "cau hinh dnsmasq split-DNS (*.$BITEL_DOMAIN -> $BITEL_DNS1)"
cat >/etc/dnsmasq.conf <<EOF
no-resolv
no-poll
listen-address=127.0.0.1
bind-interfaces
server=/${BITEL_DOMAIN}/${BITEL_DNS1}
server=/${BITEL_DOMAIN}/${BITEL_DNS2}
server=${UPSTREAM_DNS}
server=${UPSTREAM_DNS2}
edns-packet-max=1232
cache-size=1000
EOF
dnsmasq --conf-file=/etc/dnsmasq.conf
echo "nameserver 127.0.0.1" >/etc/resolv.conf
log "dnsmasq len, resolv.conf -> 127.0.0.1"

# ---- 2. tinyproxy ----
export PROXY_PORT
sed "s/\${PROXY_PORT}/${PROXY_PORT}/g" /etc/vpn-gw/tinyproxy.conf.tmpl >/etc/vpn-gw/tinyproxy.conf
tinyproxy -c /etc/vpn-gw/tinyproxy.conf
sleep 1
pidof tinyproxy >/dev/null 2>&1 || { log "tinyproxy KHONG khoi dong duoc"; exit 1; }
log "tinyproxy nghe :$PROXY_PORT"

# ---- 3. openvpn (tru khi OVPN_SKIP=1) ----
if [ "$OVPN_SKIP" = "1" ]; then
  log "OVPN_SKIP=1 -> bo qua openvpn (che do test proxy public)"
else
  [ -f "$OVPN_CONFIG" ] || { log "THIEU $OVPN_CONFIG"; exit 1; }
  [ -f "$OVPN_AUTH" ]   || { log "THIEU $OVPN_AUTH"; exit 1; }
  log "khoi dong openvpn -> $(grep -m1 '^remote ' "$OVPN_CONFIG" || echo '?')"
  # --auth-nocache: khong giu pass trong RAM. --auth-retry nointeract: tu
  # reconnect voi credentials khi rot (user/pass tinh, khong OTP). --pull: nhan
  # ~42 route noi bo (KHONG route-nopull) de toi 10.121.13.186 (jump).
  openvpn \
    --config "$OVPN_CONFIG" \
    --auth-user-pass "$OVPN_AUTH" \
    --auth-nocache \
    --auth-retry nointeract \
    --daemon ovpn \
    --writepid /run/vpn-gw/ovpn.pid \
    --log /var/log/vpn-gw/openvpn.log
  # cho tun0 len
  up=0
  for i in $(seq 1 "$TUN_WAIT"); do
    if ip link show tun0 up >/dev/null 2>&1; then up=1; break; fi
    sleep 1
  done
  if [ "$up" = "1" ]; then
    log "tun0 LEN: $(ip -4 -o addr show tun0 | awk '{print $4}')"
  else
    # Khong exit: giu container song de tinyproxy phuc vu domain non-bitel va
    # de openvpn tu reconnect; healthcheck se bao unhealthy.
    log "CANH BAO: tun0 chua len sau ${TUN_WAIT}s — tiep tuc, openvpn se retry"
    tail -n 20 /var/log/vpn-gw/openvpn.log 2>/dev/null || true
  fi

  # ---- kill-switch (optional) ----
  if [ "$KILLSWITCH" = "1" ]; then
    log "bat kill-switch: chan dai Bitel neu khong ra qua tun0"
    for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
      iptables -A OUTPUT -d "$net" -o tun0 -j ACCEPT
      iptables -A OUTPUT -d "$net" -j REJECT --reject-with icmp-net-unreachable
    done
  fi
fi

# ---- 4. supervise: theo doi tinyproxy; stream log openvpn ----
log "vpn-gw san sang. Proxy tren :$PROXY_PORT"
if [ "$OVPN_SKIP" != "1" ]; then
  tail -F /var/log/vpn-gw/openvpn.log &
fi
# Giu PID1 song, thoat neu tinyproxy chet (de docker restart ca container).
while pidof tinyproxy >/dev/null 2>&1; do
  sleep 10
done
log "tinyproxy da chet — thoat de docker restart"
exit 1
