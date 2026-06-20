#!/usr/bin/env python3
"""Ping-reporter chay tren DERP server (vpn3/vpn4).
Dung tailscale LocalAPI de:
  1. Doc danh sach peer tailnet dang online (GET /localapi/v0/status)
  2. Ping tung peer (POST /localapi/v0/ping - disco)
  3. POST ket qua len collector (vpn2) qua tailnet: POST /metrics/report

Bien moi truong:
  TS_SOCKET     - unix socket tailscaled (mac dinh /var/run/tailscale/tailscaled.sock)
  REPORTER_NAME - ten nguon ghi vao DB (mac dinh 'vpn3') - phai khop DERP region code
  COLLECTOR_PORT- cong collector tren vpn2 (mac dinh 8090)
  POLL_INTERVAL - giay giua cac lan ping (mac dinh 30)
  PING_TIMEOUT  - giay cho moi ping (mac dinh 8)
"""
import http.client
import json
import os
import socket
import time

TS_SOCKET = os.environ.get("TS_SOCKET", "/var/run/tailscale/tailscaled.sock")
REPORTER_NAME = os.environ.get("REPORTER_NAME", "vpn3")
COLLECTOR_PORT = int(os.environ.get("COLLECTOR_PORT", "8090"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
PING_TIMEOUT = int(os.environ.get("PING_TIMEOUT", "8"))

COLLECTOR_HOSTNAME = "collector"   # ten headscale node cua vpn2


def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), *a, flush=True)


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("local-tailscaled.sock", timeout=timeout)
        self._uds = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._uds)
        self.sock = s


def _localapi(method, path, timeout=10):
    try:
        conn = _UnixHTTP(TS_SOCKET, timeout)
        conn.request(method, path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return json.loads(body or b"{}") if resp.status == 200 else None
    except Exception:
        return None


def get_peers_and_collector():
    """Doc status LocalAPI -> (list peers online, collector_ip)."""
    status = _localapi("GET", "/localapi/v0/status")
    if not status:
        return [], None
    peers = []
    collector_ip = None         # fallback: collector OFFLINE (chi dung khi khong co ban online)
    collector_online_ip = None  # uu tien: collector dang ONLINE
    debug_online = []
    debug_offline = []
    for _, peer in (status.get("Peer") or {}).items():
        ips = peer.get("TailscaleIPs") or []
        ip4 = next((ip for ip in ips if ":" not in ip), "")
        if not ip4:
            continue
        host = (peer.get("HostName") or (peer.get("DNSName") or "").split(".")[0]).lower()
        online = bool(peer.get("Online"))
        if host == COLLECTOR_HOSTNAME:
            # Sau deploy co the ton tai 2 node 'collector' (ban cu OFFLINE + ban moi
            # ONLINE) -> uu tien ban ONLINE, tranh POST vao IP chet. Chi dung ban
            # offline khi khong tim thay ban online nao.
            if online:
                collector_online_ip = ip4
            elif collector_ip is None:
                collector_ip = ip4
        elif online:
            peers.append((host, ip4))
        (debug_online if online else debug_offline).append(host)
    collector_ip = collector_online_ip or collector_ip
    if not collector_ip:
        log("DEBUG peers Online=%s Offline=%s" % (debug_online, debug_offline))
    return peers, collector_ip


def ping_peer(ip4):
    """Disco ping mot peer qua LocalAPI -> {ok, rtt_ms, path}."""
    result = _localapi(
        "POST",
        "/localapi/v0/ping?ip=%s&type=disco" % ip4,
        timeout=PING_TIMEOUT,
    )
    if not isinstance(result, dict) or result.get("Err") or not result.get("LatencySeconds"):
        return {"ok": False, "rtt_ms": None, "path": ""}
    lat = float(result.get("LatencySeconds", 0) or 0)
    if result.get("Endpoint"):
        path = "direct"
    else:
        derp = result.get("DERPRegionCode") or result.get("DERPRegionID")
        path = ("derp:%s" % derp) if derp else "direct"
    return {"ok": True, "rtt_ms": round(lat * 1000, 1), "path": path}


def post_to_collector(collector_ip, samples):
    """POST samples len collector:COLLECTOR_PORT/metrics/report. True neu 200."""
    payload = json.dumps({
        "hostname": REPORTER_NAME,
        "ipv4": "",
        "mac": "",
        "samples": samples,
    }).encode()
    try:
        conn = http.client.HTTPConnection(collector_ip, COLLECTOR_PORT, timeout=10)
        conn.request("POST", "/metrics/report", body=payload,
                     headers={"Content-Type": "application/json",
                               "Content-Length": str(len(payload))})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.status == 200
    except Exception as e:
        log("POST collector ERR:", repr(e))
        return False


def main():
    log("ping-reporter [%s] start socket=%s poll=%ss" % (
        REPORTER_NAME, TS_SOCKET, POLL_INTERVAL))
    while True:
        try:
            peers, collector_ip = get_peers_and_collector()
            if not collector_ip:
                log("'collector' chua thay trong tailnet, thu lai sau...")
            elif not peers:
                log("khong co peer online ngoai collector")
            else:
                samples = []
                for host, ip4 in peers:
                    r = ping_peer(ip4)
                    samples.append({
                        "dst": host, "dst_ip": ip4,
                        "rtt_ms": r["rtt_ms"], "path": r["path"], "ok": r["ok"],
                    })
                ok = post_to_collector(collector_ip, samples)
                up = sum(1 for s in samples if s["ok"])
                log("[%s] ping %d/%d OK -> collector %s: %s" % (
                    REPORTER_NAME, up, len(samples), collector_ip,
                    "OK" if ok else "FAIL"))
        except Exception as e:
            log("ERR:", repr(e))
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
