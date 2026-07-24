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

# ---- 4. reporter: bao trang thai len dashboard (Phase 5 telemetry) ----
# Moi REPORT_INTERVAL giay: state (tun0 up?), tun_ip, egress_ip (curl qua proxy
# -> phai la IP Bitel). POST /api/vpn/agent/status voi Bearer token per-gateway.
# Chi chay khi du DASHBOARD_URL + VPN_GW_NAME + VPN_GW_AGENT_TOKEN.
report_loop() {
  if [ -z "${DASHBOARD_URL:-}" ] || [ -z "${VPN_GW_NAME:-}" ] || [ -z "${VPN_GW_AGENT_TOKEN:-}" ]; then
    log "reporter: thieu DASHBOARD_URL/VPN_GW_NAME/VPN_GW_AGENT_TOKEN -> tat telemetry"
    return
  fi
  local iv="${REPORT_INTERVAL:-30}"
  log "reporter: bao trang thai moi ${iv}s toi ${DASHBOARD_URL} (gateway=${VPN_GW_NAME})"
  while true; do
    local state tunip tsip egress cfg pport
    if ip link show tun0 up >/dev/null 2>&1; then state="up"; else state="error"; fi
    tunip=$(ip -4 -o addr show tun0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
    # IP tailnet (100.x) tu interface tailscale0 (chung netns voi sidecar) -> dashboard
    # tu cap nhat vpn_gateways.tailnet_ip, KHONG hardcode IP o deploy.
    tsip=$(ip -4 -o addr show tailscale0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
    # Lay proxy_port tu DB (khong hardcode) — fallback PROXY_PORT cuc bo neu API loi.
    cfg=$(curl -s --max-time 10 -H "Authorization: Bearer ${VPN_GW_AGENT_TOKEN}" \
      "${DASHBOARD_URL}/api/vpn/agent/config?gateway=${VPN_GW_NAME}" 2>/dev/null || echo "")
    pport=$(printf '%s' "$cfg" | grep -o '"proxyPort":[0-9]*' | grep -o '[0-9]*' | head -1)
    [ -n "$pport" ] || pport="${PROXY_PORT:-8888}"
    egress=$(curl -s --max-time 12 -x "http://127.0.0.1:${pport}" https://api.ipify.org 2>/dev/null || echo "")
    curl -s --max-time 12 -X POST \
      -H "Authorization: Bearer ${VPN_GW_AGENT_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{\"state\":\"${state}\",\"tunIp\":\"${tunip}\",\"tailnetIp\":\"${tsip}\",\"egressIp\":\"${egress}\",\"agentVersion\":\"vpn-gw-1\"}" \
      "${DASHBOARD_URL}/api/vpn/agent/status?gateway=${VPN_GW_NAME}" >/dev/null 2>&1 || true
    sleep "$iv"
  done
}
report_loop &

# ---- 5. supervise: theo doi tinyproxy; stream log openvpn ----
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
