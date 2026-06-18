#!/usr/bin/env python3
"""
node-dedup + collector: gop node trung cua headscale ("1 thiet bi = 1 node") VA
thu thap MAC / latency giua cac node do client gui ve.

PHAN 1 - DEDUP (nhu cu):
Headscale tao node MOI moi khi machine key doi (state moi / tai ban build moi roi
giai nen vao thu muc khac). Cac node nay co cung `name` (hostname) nhung `given_name`
bi them hau to (vd itop-thanhhn5-i8shta5a). Service nay:
  - gom node theo (user, hostname)
  - giu lai 1 node (uu tien dang ONLINE, roi last_seen moi nhat)
  - XOA cac node trung dang OFFLINE (khong bao gio xoa node online)
  - doi `given_name` cua node giu lai ve hostname sach (bo hau to)
  - luu lich su thiet bi vao SQLite

PHAN 2 - COLLECTOR (moi):
Headscale KHONG luu MAC va KHONG do latency giua cac node. Nen moi node tu:
  - doc MAC card chinh cua no
  - `tailscale ping` cac peer -> RTT + di thang/DERP
  - POST ve VPS: { hostname, ipv4, mac, samples:[{dst,dst_ip,rtt_ms,path,ok}] }
Service nay mo 1 HTTP server nho (cung tien trinh, cung 1 connection SQLite) nhan
POST /metrics/report -> cap nhat devices.mac + ghi bang node_latency. Xem tap
trung qua GET /metrics/latency.

XAC THUC = KHONG dung token. Container nay chay trong network namespace cua
tailscale sidecar (network_mode: service:tailscale), nen collector chi lang nghe
TREN tailnet; chi peer tailnet (hoac loopback) toi duoc. Handler con kiem tra IP
nguon thuoc dai Tailscale (100.64/10, fd7a:115c:a1e0::/48) cho chac.

Bien moi truong:
  HS_API_URL    (http://headscale:8080 - resolve qua DNS Docker ngay trong netns)
  HS_API_KEY    (bat buoc) - headscale apikey
  POLL_INTERVAL (giay, mac dinh 30)
  DB_PATH       (mac dinh /data/devices.db)
  DRY_RUN       (true/false) - true = chi LOG ke hoach, khong xoa/doi ten that
  METRICS_PORT  (mac dinh 8090) - cong HTTP collector (lang nghe trong tailnet)
"""
import html
import http.client
import http.server
import ipaddress
import json
import os
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request

HS_API_URL = os.environ.get("HS_API_URL", "http://headscale:8080").rstrip("/")
HS_API_KEY = os.environ.get("HS_API_KEY", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
DB_PATH = os.environ.get("DB_PATH", "/data/devices.db")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() in ("1", "true", "yes")
METRICS_PORT = int(os.environ.get("METRICS_PORT", "8090"))
LATENCY_WINDOW = int(os.environ.get("LATENCY_WINDOW", "3600"))  # cua so tong hop GET
# Socket LocalAPI cua tailscale sidecar (chia se qua volume) -> server tu ping node.
TS_SOCKET = os.environ.get("TS_SOCKET", "/var/run/tailscale/tailscaled.sock")
SRC_NAME = os.environ.get("SRC_NAME", "collector")  # ten "nguon" khi server ping

# 1 connection SQLite dung chung giua main-loop va HTTP thread -> phai khoa.
DB_LOCK = threading.Lock()


def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), *a, flush=True)


def _api(method, path):
    req = urllib.request.Request(HS_API_URL + path, method=method)
    req.add_header("Authorization", "Bearer " + HS_API_KEY)
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read().decode()
        return json.loads(body) if body.strip() else {}


def _g(d, *keys, default=None):
    """Lay gia tri theo nhieu ten key (API HTTP camelCase, CLI snake_case)."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


class _UnixHTTP(http.client.HTTPConnection):
    """HTTPConnection qua unix socket - de goi LocalAPI cua tailscale sidecar."""

    def __init__(self, path, timeout):
        super().__init__("local-tailscaled.sock", timeout=timeout)
        self._uds = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._uds)
        self.sock = s


def localapi_ping(ip, ptype="disco", timeout=8):
    """SERVER tu ping 1 IP tailnet qua LocalAPI sidecar. None neu loi/chua san sang."""
    try:
        conn = _UnixHTTP(TS_SOCKET, timeout)
        conn.request("POST", "/localapi/v0/ping?ip=%s&type=%s" % (ip, ptype))
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return json.loads(body or b"{}") if resp.status == 200 else None
    except Exception:  # noqa: BLE001 - socket chua co / peer offline -> coi nhu fail
        return None


def parse_pingresult(pr):
    """PURE: PingResult (LocalAPI) -> {ok, rtt_ms, path}. Tach rieng de test."""
    if not isinstance(pr, dict) or pr.get("Err"):
        return {"ok": False, "rtt_ms": None, "path": ""}
    lat = pr.get("LatencySeconds") or 0
    if not lat:
        return {"ok": False, "rtt_ms": None, "path": ""}
    if pr.get("Endpoint"):
        path = "direct"
    else:
        derp = pr.get("DERPRegionCode") or pr.get("DERPRegionID")
        path = ("derp:%s" % derp) if derp else "direct"
    return {"ok": True, "rtt_ms": round(float(lat) * 1000, 1), "path": path}


def server_ping_all(nodes):
    """Server (sidecar) tu ping MOI node -> list sample (src = SRC_NAME)."""
    out = []
    for n in nodes:
        if not n["hostname"] or n["hostname"] == SRC_NAME:
            continue
        ip4 = next((ip for ip in n["ips"] if ":" not in ip), "")
        if not ip4:
            continue
        r = parse_pingresult(localapi_ping(ip4))
        out.append({"dst": n["hostname"], "dst_ip": ip4,
                    "rtt_ms": r["rtt_ms"], "path": r["path"], "ok": r["ok"]})
    return out


def record_samples(conn, src, samples, now):
    cur = conn.cursor()
    for s in samples:
        cur.execute(
            "INSERT INTO node_latency(ts,src,dst,dst_ip,rtt_ms,path,ok) VALUES(?,?,?,?,?,?,?)",
            (now, src, s["dst"], s["dst_ip"], s["rtt_ms"], s["path"], 1 if s["ok"] else 0))
    conn.commit()
    return len(samples)


def normalize(raw_nodes):
    """Chuyen JSON node tho -> dict gon. Tach rieng de test duoc."""
    out = []
    for n in raw_nodes:
        ls = _g(n, "lastSeen", "last_seen", default={}) or {}
        last = ls.get("seconds", 0) if isinstance(ls, dict) else 0
        user = _g(n, "user", default={}) or {}
        out.append({
            "id": str(_g(n, "id", default="")),
            "hostname": _g(n, "name", default="") or "",
            "given_name": _g(n, "givenName", "given_name", default="") or "",
            "user": (user.get("name", "") if isinstance(user, dict) else str(user)) or "",
            "online": bool(_g(n, "online", default=False)),
            "last_seen": int(last or 0),
            "ips": _g(n, "ipAddresses", "ip_addresses", default=[]) or [],
            "machine_key": _g(n, "machineKey", "machine_key", default="") or "",
        })
    return out


def plan_actions(nodes):
    """PURE: tra ve danh sach hanh dong (delete/rename/skip). Test doc lap duoc."""
    groups = {}
    for n in nodes:
        groups.setdefault((n["user"], n["hostname"]), []).append(n)

    actions = []
    for (user, hostname), group in sorted(groups.items()):
        if not hostname:
            continue
        # keeper: online truoc, roi last_seen moi nhat, roi id (on dinh)
        keeper = sorted(
            group,
            key=lambda n: (1 if n["online"] else 0, n["last_seen"], n["id"]),
            reverse=True,
        )[0]
        for n in group:
            if n["id"] == keeper["id"]:
                continue
            if n["online"]:
                actions.append({"action": "skip", "id": n["id"],
                                "name": n["given_name"],
                                "reason": "trung nhung dang ONLINE -> khong xoa"})
            else:
                actions.append({"action": "delete", "id": n["id"],
                                "name": n["given_name"],
                                "reason": "trung hostname '%s' (user %s)" % (hostname, user)})
        if keeper["given_name"] != hostname:
            actions.append({"action": "rename", "id": keeper["id"],
                            "from": keeper["given_name"], "to": hostname})
    return actions


def apply_action(a):
    if a["action"] == "delete":
        _api("DELETE", "/api/v1/node/%s" % a["id"])
    elif a["action"] == "rename":
        _api("POST", "/api/v1/node/%s/rename/%s" % (a["id"], a["to"]))


def init_db(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS devices(
            user TEXT, hostname TEXT, mac TEXT, node_id TEXT, ipv4 TEXT,
            machine_key TEXT, first_seen INTEGER, last_seen INTEGER, seen_count INTEGER,
            PRIMARY KEY(user, hostname))"""
    )
    conn.commit()


def init_latency_db(conn):
    """Bang luu tung lan ping (1 mau = 1 dong). Tach rieng de test duoc."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS node_latency(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER, src TEXT, dst TEXT, dst_ip TEXT,
            rtt_ms REAL, path TEXT, ok INTEGER)"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_latency_ts ON node_latency(ts)")
    conn.commit()


def upsert_db(conn, nodes):
    now = int(time.time())
    cur = conn.cursor()
    for n in nodes:
        if not n["hostname"]:
            continue
        ipv4 = next((ip for ip in n["ips"] if ":" not in ip), "")
        cur.execute(
            """INSERT INTO devices(user,hostname,mac,node_id,ipv4,machine_key,first_seen,last_seen,seen_count)
               VALUES(?,?,?,?,?,?,?,?,1)
               ON CONFLICT(user,hostname) DO UPDATE SET
                 node_id=excluded.node_id, ipv4=excluded.ipv4,
                 machine_key=excluded.machine_key, last_seen=excluded.last_seen,
                 seen_count=devices.seen_count+1""",
            (n["user"], n["hostname"], None, n["id"], ipv4, n["machine_key"], now, now),
        )
    conn.commit()


# ---------------- COLLECTOR (PURE helpers - test duoc) ----------------

def validate_report(obj):
    """PURE: kiem tra + chuan hoa 1 ban bao cao tu node. Loi -> ValueError."""
    if not isinstance(obj, dict):
        raise ValueError("report phai la object")
    hostname = str(obj.get("hostname", "")).strip()
    if not hostname:
        raise ValueError("thieu hostname")
    ipv4 = str(obj.get("ipv4", "")).strip()
    mac = str(obj.get("mac", "")).strip()
    raw = obj.get("samples", []) or []
    # PowerShell 5.1 serialize mang 1 phan tu thanh OBJECT -> chap nhan luon.
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("samples phai la list")
    samples = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        dst = str(s.get("dst", "")).strip()
        if not dst:
            continue
        rtt = s.get("rtt_ms")
        try:
            rtt = float(rtt) if rtt is not None else None
        except (TypeError, ValueError):
            rtt = None
        samples.append({
            "dst": dst,
            "dst_ip": str(s.get("dst_ip", "")).strip(),
            "rtt_ms": rtt,
            "path": str(s.get("path", "")).strip(),
            "ok": bool(s.get("ok", rtt is not None)),
        })
    return {"hostname": hostname, "ipv4": ipv4, "mac": mac, "samples": samples}


def aggregate_latency(rows):
    """PURE: tong hop theo cap (src,dst): count/min/avg/max/%ok/%direct/last."""
    groups = {}
    for r in rows:
        groups.setdefault((r["src"], r["dst"]), []).append(r)
    out = []
    for (src, dst), g in sorted(groups.items()):
        rtts = [x["rtt_ms"] for x in g if x["ok"] and x["rtt_ms"] is not None]
        latest = max(g, key=lambda x: x["ts"])
        direct = sum(1 for x in g if (x["path"] or "").lower().startswith("direct"))
        oks = sum(1 for x in g if x["ok"])
        out.append({
            "src": src, "dst": dst, "count": len(g),
            "min_ms": round(min(rtts), 1) if rtts else None,
            "avg_ms": round(sum(rtts) / len(rtts), 1) if rtts else None,
            "max_ms": round(max(rtts), 1) if rtts else None,
            "ok_pct": round(100.0 * oks / len(g), 1) if g else 0.0,
            "direct_pct": round(100.0 * direct / len(g), 1) if g else 0.0,
            "last_ms": latest["rtt_ms"], "last_path": latest["path"],
            "last_ts": latest["ts"],
        })
    return out


def record_report(conn, report, now):
    """Ghi 1 ban bao cao vao DB: cap nhat devices.mac + chen node_latency."""
    cur = conn.cursor()
    if report["mac"]:
        if report["ipv4"]:
            cur.execute("UPDATE devices SET mac=? WHERE ipv4=?",
                        (report["mac"], report["ipv4"]))
        if cur.rowcount == 0:
            cur.execute("UPDATE devices SET mac=? WHERE hostname=?",
                        (report["mac"], report["hostname"]))
    for s in report["samples"]:
        cur.execute(
            "INSERT INTO node_latency(ts,src,dst,dst_ip,rtt_ms,path,ok) VALUES(?,?,?,?,?,?,?)",
            (now, report["hostname"], s["dst"], s["dst_ip"],
             s["rtt_ms"], s["path"], 1 if s["ok"] else 0),
        )
    conn.commit()
    return len(report["samples"])


def query_latency(conn, window):
    cur = conn.cursor()
    cur.execute(
        "SELECT src,dst,dst_ip,rtt_ms,path,ok,ts FROM node_latency "
        "WHERE ts>=? ORDER BY ts DESC LIMIT 10000",
        (int(time.time()) - window,),
    )
    return [{"src": r[0], "dst": r[1], "dst_ip": r[2], "rtt_ms": r[3],
             "path": r[4], "ok": bool(r[5]), "ts": r[6]} for r in cur.fetchall()]


def query_devices(conn):
    cur = conn.cursor()
    cur.execute("SELECT hostname,mac,ipv4,last_seen,seen_count FROM devices ORDER BY hostname")
    return [{"hostname": r[0], "mac": r[1], "ipv4": r[2],
             "last_seen": r[3], "seen_count": r[4]} for r in cur.fetchall()]


def latency_series(rows):
    """PURE: gom raw rows -> chuoi thoi gian theo cap (cho bieu do duong)."""
    series = {}
    for r in rows:
        if not r["ok"] or r["rtt_ms"] is None:
            continue
        key = r["src"] + " -> " + r["dst"]
        series.setdefault(key, []).append({"t": r["ts"], "rtt": r["rtt_ms"]})
    out = []
    for k in sorted(series):
        pts = sorted(series[k], key=lambda x: x["t"])
        out.append({"pair": k, "points": pts})
    return out


# Trang dashboard: render het o client tu bien D (nhung server-side). Dung
# .replace (khong .format/%) de khoi dung do CSS/JS co dau { } va %.
_STATS_PAGE = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Tailnet - Thong ke</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root{color-scheme:dark}
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;background:#0b1220;color:#e2e8f0}
header{padding:18px 24px;background:#111a2e;border-bottom:1px solid #24304a}
h1{margin:0;font-size:18px}.muted{color:#94a3b8;font-size:12px}
main{padding:20px 24px;max-width:1100px;margin:0 auto}
.cards{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:20px}
.card{background:#131d33;border:1px solid #24304a;border-radius:12px;padding:14px 18px;min-width:130px}
.card .v{font-size:26px;font-weight:700}.card .l{color:#94a3b8;font-size:12px;margin-top:4px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:22px}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.panel{background:#131d33;border:1px solid #24304a;border-radius:12px;padding:14px}
.panel h2{margin:2px 0 10px;font-size:14px;color:#cbd5e1}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid #24304a;padding:7px 10px;text-align:left;font-size:13px}
th{color:#94a3b8;font-weight:600}
.tag{padding:1px 8px;border-radius:999px;font-size:11px}
.direct{background:#064e3b;color:#6ee7b7}.derp{background:#4a2d0b;color:#fcd34d}
.bad{color:#fca5a5}
</style></head><body>
<header><h1>Tailnet - Latency &amp; Devices</h1>
<div class="muted" id="sub"></div></header>
<main>
<div class="cards" id="cards"></div>
<div class="grid">
  <div class="panel"><h2>Avg latency moi cap (ms)</h2><canvas id="bar" height="160"></canvas></div>
  <div class="panel"><h2>RTT theo thoi gian</h2><canvas id="line" height="160"></canvas></div>
</div>
<div class="panel" style="margin-bottom:22px"><h2>Chi tiet latency</h2>
<table><thead><tr><th>src</th><th>dst</th><th>min</th><th>avg</th><th>max</th><th>last</th><th>path</th><th>%direct</th><th>mau</th></tr></thead><tbody id="lat"></tbody></table></div>
<div class="panel"><h2>Thiet bi (MAC tu node bao cao)</h2>
<table><thead><tr><th>hostname</th><th>MAC</th><th>tailnet ip</th><th>lan thay</th></tr></thead><tbody id="dev"></tbody></table></div>
</main>
<script>
const D = __DATA__;
const esc = s => String(s==null?"":s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const fmt = v => v==null?"-":v;
const ts = D.pairs.reduce((a,p)=>a+p.count,0);
const wd = ts? D.pairs.reduce((a,p)=>a+p.direct_pct*p.count,0)/ts : 0;
document.getElementById("sub").textContent =
  "Cua so "+D.window_min+" phut - cap nhat "+new Date(D.generated*1000).toLocaleString()+" - tu refresh 30s";
const cards=[[D.devices.length,"thiet bi"],[D.pairs.length,"cap node"],[ts,"mau ("+D.window_min+"p)"],[wd.toFixed(0)+"%","di thang"]];
document.getElementById("cards").innerHTML = cards.map(c=>
  '<div class="card"><div class="v">'+esc(c[0])+'</div><div class="l">'+esc(c[1])+'</div></div>').join("");
document.getElementById("lat").innerHTML = D.pairs.length? D.pairs.map(p=>
  "<tr><td>"+esc(p.src)+"</td><td>"+esc(p.dst)+"</td><td>"+fmt(p.min_ms)+"</td><td>"+fmt(p.avg_ms)+"</td><td>"+fmt(p.max_ms)+"</td><td>"+fmt(p.last_ms)+"</td><td>"+esc(p.last_path||"")+"</td><td>"+p.direct_pct+"%</td><td>"+p.count+"</td></tr>").join("")
  : '<tr><td colspan="9" class="muted">chua co du lieu - kiem tra node da chay reporter + thay peer collector chua</td></tr>';
document.getElementById("dev").innerHTML = D.devices.length? D.devices.map(d=>
  "<tr><td>"+esc(d.hostname)+"</td><td>"+(d.mac?esc(d.mac):'<span class="bad">(chua bao cao)</span>')+"</td><td>"+esc(d.ipv4)+"</td><td>"+(d.seen_count||0)+"</td></tr>").join("")
  : '<tr><td colspan="4" class="muted">chua co thiet bi</td></tr>';
const palette=["#38bdf8","#f472b6","#a3e635","#fbbf24","#c084fc","#fb7185","#34d399"];
new Chart(document.getElementById("bar"),{type:"bar",
  data:{labels:D.pairs.map(p=>p.src+"->"+p.dst),datasets:[{label:"avg ms",data:D.pairs.map(p=>p.avg_ms),backgroundColor:"#38bdf8"}]},
  options:{plugins:{legend:{display:false}},scales:{y:{title:{display:true,text:"ms"},beginAtZero:true}}}});
new Chart(document.getElementById("line"),{type:"line",
  data:{datasets:D.series.map((s,i)=>({label:s.pair,data:s.points.map(pt=>({x:pt.t*1000,y:pt.rtt})),borderColor:palette[i%palette.length],backgroundColor:palette[i%palette.length],tension:.3,pointRadius:2}))},
  options:{scales:{x:{type:"linear",ticks:{callback:v=>new Date(v).toLocaleTimeString()}},y:{title:{display:true,text:"ms"},beginAtZero:true}}}});
</script></body></html>"""


def render_stats_html(pairs, series, devices, window_s, now):
    data = {"generated": now, "window_min": max(1, window_s // 60),
            "pairs": pairs, "series": series, "devices": devices}
    return _STATS_PAGE.replace("__DATA__", json.dumps(data))


_TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
_TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


def is_tailnet_ip(ip):
    """PURE: True neu IP thuoc dai Tailscale (100.64/10, fd7a:115c:a1e0::/48)
    hoac loopback. Dung lam 'auth' thay token (collector chi mo trong tailnet)."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if a.is_loopback:
        return True
    return a in (_TAILNET_V4 if a.version == 4 else _TAILNET_V6)


def make_metrics_handler(conn, lock):
    class Handler(http.server.BaseHTTPRequestHandler):
        # HTTP/1.1 + luon co Content-Length (da set) -> Caddy reverse_proxy on dinh,
        # tranh 502 voi response lon nhu trang /stats.
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # im lang, dung spam log
            pass

        def _authed(self):
            # Khong token: chi chap nhan ket noi tu dai tailnet (hoac loopback).
            return is_tailnet_ip(self.client_address[0])

        def _send(self, code, payload):
            body = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _sendhtml(self, code, body):
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not self._authed():
                self._send(401, {"error": "unauthorized"})
                return
            if self.path.rstrip("/") != "/metrics/report":
                self._send(404, {"error": "not found"})
                return
            try:
                n = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(n) if n > 0 else b"{}"
                report = validate_report(json.loads(raw.decode() or "{}"))
            except Exception as e:  # noqa: BLE001
                self._send(400, {"error": str(e)})
                return
            with lock:
                stored = record_report(conn, report, int(time.time()))
            self._send(200, {"ok": True, "stored": stored})

        def do_GET(self):
            # GET = chi doc -> mo (tailnet truc tiep, hoac Caddy /stats da gated SSO).
            # Ghi (POST) van bat buoc tu tailnet.
            p = self.path.split("?")[0].rstrip("/")
            if p == "/metrics/latency":
                with lock:
                    rows = query_latency(conn, LATENCY_WINDOW)
                self._send(200, {"window_s": LATENCY_WINDOW,
                                 "pairs": aggregate_latency(rows)})
                return
            if p in ("/stats", "/metrics/stats", "/metrics/dashboard", ""):
                with lock:
                    rows = query_latency(conn, LATENCY_WINDOW)
                    devs = query_devices(conn)
                page = render_stats_html(aggregate_latency(rows), latency_series(rows),
                                         devs, LATENCY_WINDOW, int(time.time()))
                self._sendhtml(200, page.encode("utf-8"))
                return
            self._send(404, {"error": "not found"})

    return Handler


def start_metrics_server(conn, lock):
    handler = make_metrics_handler(conn, lock)
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", METRICS_PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log("collector chay :%d (tailnet-only; POST /metrics/report, GET /metrics/latency)" % METRICS_PORT)


def main():
    if not HS_API_KEY:
        log("THIEU HS_API_KEY -> thoat")
        sys.exit(1)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    init_db(conn)
    init_latency_db(conn)
    start_metrics_server(conn, DB_LOCK)
    log("node-dedup chay. API=%s poll=%ss DRY_RUN=%s" % (HS_API_URL, POLL_INTERVAL, DRY_RUN))
    while True:
        try:
            raw = _api("GET", "/api/v1/node").get("nodes", [])
            nodes = normalize(raw)
            with DB_LOCK:
                upsert_db(conn, nodes)
            # SERVER tu ping moi node (qua LocalAPI sidecar) - nguon chinh cua
            # latency, KHONG phu thuoc node co chay reporter hay khong. Ping ngoai
            # lock (cham), chi ghi DB trong lock.
            samples = server_ping_all(nodes)
            if samples:
                with DB_LOCK:
                    record_samples(conn, SRC_NAME, samples, int(time.time()))
                up = sum(1 for s in samples if s["ok"])
                log("server ping: %d/%d node OK" % (up, len(samples)))
            for a in plan_actions(nodes):
                label = a.get("name") or a.get("from", "")
                if a["action"] == "skip":
                    log("SKIP", label, "-", a["reason"])
                elif DRY_RUN:
                    log("[DRY]", a["action"].upper(), label, "->", a.get("to", ""), a.get("reason", ""))
                else:
                    apply_action(a)
                    log(a["action"].upper(), label, "->", a.get("to", ""), a.get("reason", ""))
        except urllib.error.URLError as e:
            log("API loi:", e)
        except Exception as e:  # noqa: BLE001 - service vong lap, khong duoc chet
            log("Loi:", repr(e))
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
