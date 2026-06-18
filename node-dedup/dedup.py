#!/usr/bin/env python3
"""
node-dedup: gop node trung cua headscale -> "1 thiet bi = 1 node".

Headscale tao node MOI moi khi machine key doi (state moi / tai ban build moi roi
giai nen vao thu muc khac). Cac node nay co cung `name` (hostname) nhung `given_name`
bi them hau to (vd itop-thanhhn5-i8shta5a). Service nay:
  - gom node theo (user, hostname)
  - giu lai 1 node (uu tien dang ONLINE, roi last_seen moi nhat)
  - XOA cac node trung dang OFFLINE (khong bao gio xoa node online)
  - doi `given_name` cua node giu lai ve hostname sach (bo hau to)
  - luu lich su thiet bi vao SQLite (hostname=ten thiet bi, mac neu co, node id, ip, thoi gian)

LUU Y: Headscale KHONG luu/khong nhan MAC -> khoa dinh danh thiet bi la HOSTNAME
(on dinh theo may, headscale gui san). Cot `mac` de san cho tuong lai neu client
gui MAC (vd nhung vao hostname).

Bien moi truong:
  HS_API_URL    (mac dinh http://headscale:8080)
  HS_API_KEY    (bat buoc) - headscale apikey
  POLL_INTERVAL (giay, mac dinh 30)
  DB_PATH       (mac dinh /data/devices.db)
  DRY_RUN       (true/false) - true = chi LOG ke hoach, khong xoa/doi ten that
"""
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

HS_API_URL = os.environ.get("HS_API_URL", "http://headscale:8080").rstrip("/")
HS_API_KEY = os.environ.get("HS_API_KEY", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
DB_PATH = os.environ.get("DB_PATH", "/data/devices.db")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() in ("1", "true", "yes")


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


def main():
    if not HS_API_KEY:
        log("THIEU HS_API_KEY -> thoat")
        sys.exit(1)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    log("node-dedup chay. API=%s poll=%ss DRY_RUN=%s" % (HS_API_URL, POLL_INTERVAL, DRY_RUN))
    while True:
        try:
            raw = _api("GET", "/api/v1/node").get("nodes", [])
            nodes = normalize(raw)
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
