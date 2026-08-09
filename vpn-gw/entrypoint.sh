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
# Dich probe "duong con song that": host:port BEN TRONG mang Bitel. Mac dinh la
# RDP cua may IT OPS — dung dich vu nguoi dung can, khong phai mot IP moc bat ky.
PROBE_TARGET="${PROBE_TARGET:-10.121.124.155:3389}"
PROBE_TIMEOUT="${PROBE_TIMEOUT:-4}"
# =1: healthcheck coi ip_forward=0 la HONG (bat khi node lam subnet router).
REQUIRE_FORWARD="${REQUIRE_FORWARD:-0}"

log() { echo "$(date -u +%H:%M:%S) vpn-gw: $*"; }

# probe_ok: TCP connect toi PROBE_TARGET qua tun0.
#
# Vi sao KHONG dung `ip link show tun0 up` hay `ping`: da do tren prod
# 2026-08-09 — (1) tun0 co the UP ma duong van chet (Bitel chan theo TAI KHOAN:
# ca dai 10.121.13.x timeout du co route, trong khi 10.121.124.x thong);
# (2) may dich chan ICMP nen ping that bai 100% trong khi TCP 3389 bat tay
# thanh cong. Chi TCP toi dung cong dich vu moi noi len su that.
# KHONG dung `nc -z`: busybox trong alpine chi co `-z` khi build kem NC_EXTRA,
# khong bao dam. Dang `nc -w T host port </dev/null` chay duoc tren CA busybox
# lan openbsd-netcat: ket noi duoc thi stdin EOF ngay -> exit 0; refused/timeout
# -> exit != 0. Server co gui banner cung khong sao — ta chi hoi "TCP mo khong".
probe_ok() {
  local hp="${1:-$PROBE_TARGET}" h p
  [ -n "$hp" ] || return 0          # khong cau hinh dich -> khong danh gia, coi nhu OK
  h="${hp%%:*}"; p="${hp##*:}"
  [ -n "$h" ] && [ -n "$p" ] || return 1
  nc -w "$PROBE_TIMEOUT" "$h" "$p" </dev/null >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# healthcheck: goi boi Docker HEALTHCHECK. Proxy phai song; neu dang chay VPN
# thi tun0 phai con len.
# ---------------------------------------------------------------------------
if [ "${1:-run}" = "healthcheck" ]; then
  pidof tinyproxy >/dev/null 2>&1 || { echo "tinyproxy chet"; exit 1; }
  if [ "$OVPN_SKIP" != "1" ]; then
    ip link show tun0 up >/dev/null 2>&1 || { echo "tun0 khong len"; exit 1; }
  fi
  # Khi node lam subnet router, ip_forward=0 nghia la no quang ba route ma
  # KHONG chuyen tiep duoc goi nao — hong im lang, `list-routes` van xanh.
  if [ "$REQUIRE_FORWARD" = "1" ]; then
    [ "$(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null || echo 0)" = "1" ] \
      || { echo "ip_forward=0 nhung REQUIRE_FORWARD=1"; exit 1; }
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

  # NAT ra tun0: cho phep may CO TUN (accept-routes) di route thang qua vpngw ->
  # tun0 -> Bitel (khong can proxy). SNAT src ve IP tun0 de jump reply ve dung.
  iptables -t nat -C POSTROUTING -o tun0 -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -o tun0 -j MASQUERADE
  log "NAT MASQUERADE ra tun0 (subnet route cho may co TUN)"

  # ---- Mat phang forward cho subnet-route ----
  # Truoc 2026-08-09 ba thu duoi day chi ton tai vi co nguoi go tay trong netns:
  # KHONG co trong image, nen moi lan recreate la mat sach va gateway "quang ba
  # route" ma khong chuyen tiep duoc goi nao. Dua han vao day.
  #
  # ip_forward do RUNTIME dat qua `sysctls:` cua ts-vpngw trong compose — netns
  # nay la cua sidecar va /proc/sys trong container KHONG ghi duoc (da do:
  # "sysctl: error setting key 'net.ipv4.ip_forward': Read-only file system").
  # O day chi kiem tra + canh bao, tuyet doi khong `sysctl -w` (script chay
  # `set -e`, lenh that bai se giet luon tinyproxy dang chay tot).
  fwd=$(cat /proc/sys/net/ipv4/ip_forward 2>/dev/null || echo 0)
  if [ "$fwd" != "1" ]; then
    log "CANH BAO: ip_forward=$fwd — subnet route se KHONG forward duoc. Them 'sysctls: [net.ipv4.ip_forward=1]' cho ts-vpngw."
  fi

  # tailscale0 do sidecar tao; no khoi dong truoc nhung tailscaled can vai giay.
  ts_up=0
  for _ in $(seq 1 30); do
    if ip link show tailscale0 >/dev/null 2>&1; then ts_up=1; break; fi
    sleep 1
  done

  if [ "$ts_up" = "1" ]; then
    # Khong dua vao policy ACCEPT mac dinh cua FORWARD: tailscaled co the doi
    # policy khi bat netfilter.
    iptables -C FORWARD -i tailscale0 -o tun0 -j ACCEPT 2>/dev/null \
      || iptables -A FORWARD -i tailscale0 -o tun0 -j ACCEPT || true
    iptables -C FORWARD -i tun0 -o tailscale0 -j ACCEPT 2>/dev/null \
      || iptables -A FORWARD -i tun0 -o tailscale0 -j ACCEPT || true

    # CHONG RO — quan trong. OpenVPN chi push ~42 route roi rac, KHONG phai ca
    # 10.121.0.0/16. Goi tu tailnet toi mot IP 10.121.x ngoai tap do se khop
    # DEFAULT ROUTE -> ra eth0 voi src 100.64.x (MASQUERADE chi gan `-o tun0`)
    # -> roi ra internet cong cong, va nguoi dung thay TREO chu khong thay loi.
    # Vi du that: 10.121.13.135 (remote DC) `ip route get` -> dev eth0.
    # Chan thang + tra ICMP de fail NHANH. Kill-switch san co KHONG che duoc ca
    # nay: no chi dung chain OUTPUT, con traffic subnet-route di qua FORWARD.
    iptables -C FORWARD -i tailscale0 ! -o tun0 -j REJECT --reject-with icmp-net-unreachable 2>/dev/null \
      || iptables -A FORWARD -i tailscale0 ! -o tun0 -j REJECT --reject-with icmp-net-unreachable || true

    # MSS clamp: WireGuard (1280) long trong OpenVPN lam PMTU vo — RDP/SMB bat
    # tay xong roi treo giua chung khi goi lon. Kep MSS theo PMTU that.
    iptables -t mangle -C FORWARD -p tcp --syn -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null \
      || iptables -t mangle -A FORWARD -p tcp --syn -j TCPMSS --clamp-mss-to-pmtu || true

    log "forward plane san sang (ACCEPT tailnet<->tun0, REJECT ro ra eth0, MSS clamp)"
  else
    log "CANH BAO: khong thay tailscale0 sau 30s — bo qua luat FORWARD"
  fi

  # Bao ngay duong that con song hay khong (probe TCP, khong phai link-state).
  if probe_ok; then
    log "probe $PROBE_TARGET: OK"
  else
    log "probe $PROBE_TARGET: THAT BAI — tun0 len nhung duong toi dich khong thong"
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
  # KHONG de mot lenh loi (vd grep khong khop khi config rong) giet vong lap
  # reporter — entrypoint chay set -e, tat rieng trong subshell reporter.
  set +e
  log "reporter: bao trang thai moi ${iv}s toi ${DASHBOARD_URL} (gateway=${VPN_GW_NAME})"
  while true; do
    state=""; tunip=""; tsip=""; egress=""; cfg=""; pport=""
    # state = tun0 UP **VA** duong toi dich that su thong. Link-state mot minh
    # noi doi: Bitel chan theo tai khoan thi tun0 van UP ma khong toi duoc gi.
    # Dashboard dua vao `state` de xep hang gateway (computeGatewayHealth) va
    # route-agent dua vao no de rut/khoi phuc advertise.
    if ip link show tun0 up >/dev/null 2>&1 && probe_ok; then state="up"; else state="error"; fi
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
