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
import http.server
import ipaddress
import json
import os
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
            if not self._authed():
                self._send(401, {"error": "unauthorized"})
                return
            if self.path.split("?")[0].rstrip("/") != "/metrics/latency":
                self._send(404, {"error": "not found"})
                return
            with lock:
                rows = query_latency(conn, LATENCY_WINDOW)
            self._send(200, {"window_s": LATENCY_WINDOW,
                             "pairs": aggregate_latency(rows)})

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
