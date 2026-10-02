#!/usr/bin/env python3
"""Giu cho MOI khoa API cu cua CLIProxy van goi duoc, ke ca khi doi kho config.

    python3 pgstore-keys.py extract <config.yaml>... > .keys-wanted
    python3 pgstore-keys.py sync  .keys-wanted     # them khoa thieu qua Management API
    python3 pgstore-keys.py check .keys-wanted     # moi khoa phai duoc /v1/models tra 200

Bien moi truong: CLIPROXY_MGMT_KEY (sync), CLIPROXY_PUBLIC_PORT (mac dinh 28417),
CLIPROXY_BASE_URL (ghi de host, dung trong test).

Vi sao can (yeu cau 2026-10-02 "phai dam bao key cu van dung duoc"):
  - Khi bat PGSTORE, proxy doc config tu Postgres chu khong tu config.yaml nua, va
    deploy "chi seed lan dau" -> khoa moi trong file dung chung
    /opt/opencode/secrets/cliproxy.key hay secret CLIPROXY_API_KEY se KHONG tu vao
    DB. Lap lai dung su co 401 ngay 26-27/09.
  - Khi tat PGSTORE, proxy quay ve config.yaml sinh tu template -> khoa them qua
    web luc dang dung DB se mat.
  Ca hai huong deu giai bang mot cach: gom khoa tu MOI nguon cu (config.yaml dang
  chay, spool cua DB, config moi render), roi CHI THEM khoa thieu qua Management
  API — proxy tu ghi vao noi dang la nguon su that (DB hoac file). Khong bao gio
  xoa khoa nao.

Khong in khoa ra log: log GitHub Actions khong xoa duoc. Chi in so thu tu + do dai.
Khong phu thuoc PyYAML (vpn4 chi co python3 tran) — doc khoi api-keys bang tay.
"""
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request


def _scalar(raw):
    """Gia tri vo huong YAML don gian: "..." / '...' / tran. None neu khong phai."""
    v = raw.strip()
    if not v or v.startswith("#"):
        return None
    if v.startswith('"'):
        end = 1
        while end < len(v):
            if v[end] == "\\":
                end += 2
                continue
            if v[end] == '"':
                break
            end += 1
        try:
            return json.loads(v[: end + 1])
        except ValueError:
            return None
    if v.startswith("'"):
        end = v.find("'", 1)
        while end != -1 and end + 1 < len(v) and v[end + 1] == "'":
            end = v.find("'", end + 2)
        if end == -1:
            return None
        return v[1:end].replace("''", "'")
    # Tran: cat chu thich cuoi dong. Mapping ("name: x") khong phai khoa client.
    if " #" in v:
        v = v.split(" #", 1)[0].rstrip()
    if ": " in v or v.endswith(":") or v.startswith(("{", "[", "&", "*", "!")):
        return None
    return v


def _flow_list(raw):
    v = raw.strip()
    if " #" in v and not v.startswith('["'):
        v = v.split(" #", 1)[0].rstrip()
    if not (v.startswith("[") and v.endswith("]")):
        return None
    try:
        arr = json.loads(v)
    except ValueError:
        inner = v[1:-1].strip()
        if not inner:
            return []
        arr = [_scalar(p) for p in inner.split(",")]
    return [a for a in arr if isinstance(a, str) and a]


def keys_from_text(text):
    """Khoa client trong config: `access.api-keys` (v8) hoac `api-keys` cap goc (cu).

    O layout v8, `api-keys` cap goc la NHOM PROVIDER (danh sach mapping) chu khong
    phai khoa client -> chi nhan cac muc vo huong, bo qua mapping.
    """
    lines = text.splitlines()
    found = []
    i = 0
    parent_access = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and stripped and not stripped.startswith("#"):
            parent_access = stripped.startswith("access:")
        is_top = indent == 0 and stripped.startswith("api-keys:")
        is_access = parent_access and indent > 0 and stripped.startswith("api-keys:")
        if not (is_top or is_access):
            i += 1
            continue
        rest = stripped[len("api-keys:"):]
        flow = _flow_list(rest)
        if flow is not None:
            found.extend(flow)
            i += 1
            continue
        i += 1
        while i < len(lines):
            item = lines[i]
            s = item.strip()
            ind = len(item) - len(item.lstrip(" "))
            if not s or s.startswith("#"):
                i += 1
                continue
            # Het khoi khi gap dong cung/nong hon muc cha ma khong phai "- ".
            if ind < indent or (ind == indent and not s.startswith("- ")):
                break
            if s.startswith("- ") and ind <= indent + 2:
                val = _scalar(s[2:])
                if val:
                    found.append(val)
            i += 1
    out = []
    for k in found:
        if k not in out:
            out.append(k)
    return out


# Khoa mau trong config.example.yaml cua upstream. Neu chung tung lot vao config
# (proxy tu chep file mau khi DB trong), TUYET DOI khong duoc "giu" chung lai.
KHOA_MAU = {"your-api-key-1", "your-api-key-2", "your-api-key-3"}


def extract(paths):
    out = []
    for p in paths:
        try:
            text = pathlib.Path(p).read_text(encoding="utf-8")
        except OSError:
            continue
        for k in keys_from_text(text):
            if k in KHOA_MAU or k.startswith("__"):
                continue
            if k not in out:
                out.append(k)
    return out


def read_wanted(path):
    out = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        k = line.strip()
        if k and k not in out:
            out.append(k)
    return out


def base_url():
    override = os.environ.get("CLIPROXY_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")
    return "http://127.0.0.1:%s" % os.environ.get("CLIPROXY_PUBLIC_PORT", "28417")


def http(method, path, token, body=None, timeout=10):
    data = None
    req = urllib.request.Request(base_url() + path, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError):
        return 0, b""


def wait_ready(seconds):
    """Proxy song = /v1/models tra BAT KY ma HTTP nao (401 cung tinh)."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        code, _ = http("GET", "/v1/models", "probe-not-a-key", timeout=3)
        if code:
            return True
        time.sleep(2)
    return False


def label(idx, key):
    return "khoa#%d(len=%d)" % (idx + 1, len(key))


def present_keys(mgmt):
    code, raw = http("GET", "/v0/management/api-keys", mgmt)
    if code in (401, 403):
        # KHONG thu lai: sai management key 5 lan la IP bi ban 30 phut.
        # Ma thoat 3 rieng de pgstore.sh phan biet voi loi kho (khong rollback).
        sys.stderr.write(
            "GET /v0/management/api-keys -> HTTP %d: CLIPROXY_MGMT_KEY khong khop proxy "
            "(doi tren web?) hoac IP dang bi ban.\n" % code
        )
        raise SystemExit(3)
    if code != 200:
        raise SystemExit("GET /v0/management/api-keys -> HTTP %d" % code)
    try:
        return list(json.loads(raw.decode("utf-8")).get("api-keys") or [])
    except ValueError:
        raise SystemExit("phan hoi /v0/management/api-keys khong phai JSON")


def sync(wanted, mgmt):
    if not wait_ready(120):
        raise SystemExit("proxy khong tra loi sau 120s")
    present = present_keys(mgmt)
    missing = [k for k in wanted if k not in present]
    for idx, k in enumerate(wanted):
        if k not in missing:
            continue
        # PATCH {old, new} voi old khong ton tai -> handler APPEND new (chi them,
        # khong dung toi khoa khac). Ghi vao DB hoac config.yaml tuy kho dang bat.
        code, raw = http("PATCH", "/v0/management/api-keys", mgmt, {"old": k, "new": k})
        if code != 200:
            raise SystemExit("them %s that bai: HTTP %d %s" % (label(idx, k), code, raw[:200]))
        sys.stderr.write("  da them %s\n" % label(idx, k))
    after = present_keys(mgmt)
    still = [k for k in wanted if k not in after]
    if still:
        raise SystemExit("sau khi them van thieu %d khoa" % len(still))
    sys.stderr.write(
        "pgstore-keys sync: %d khoa can giu, %d da co, %d vua them, proxy dang co %d khoa\n"
        % (len(wanted), len(wanted) - len(missing), len(missing), len(after))
    )
    return 0


def check(wanted, seconds):
    """Moi khoa cu phai goi duoc that. Them khoa qua API -> proxy nap lai config
    bat dong bo, nen cho mot luc truoc khi ket luan."""
    if not wait_ready(120):
        raise SystemExit("proxy khong tra loi sau 120s")
    deadline = time.time() + seconds
    pending = list(range(len(wanted)))
    last = {}
    while pending:
        nxt = []
        for idx in pending:
            code, _ = http("GET", "/v1/models", wanted[idx])
            last[idx] = code
            if code != 200:
                nxt.append(idx)
        pending = nxt
        if not pending or time.time() > deadline:
            break
        time.sleep(2)
    for idx, k in enumerate(wanted):
        sys.stderr.write("  %s -> HTTP %s\n" % (label(idx, k), last.get(idx, 200)))
    if pending:
        raise SystemExit("%d/%d khoa cu KHONG goi duoc" % (len(pending), len(wanted)))
    sys.stderr.write("pgstore-keys check: %d/%d khoa cu goi duoc (200)\n" % (len(wanted), len(wanted)))
    return 0


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("dung: pgstore-keys.py extract <config>... | sync <file> | check <file>\n")
        return 2
    cmd = argv[1]
    if cmd == "extract":
        for k in extract(argv[2:]):
            sys.stdout.write(k + "\n")
        return 0
    wanted = read_wanted(argv[2])
    if not wanted:
        raise SystemExit("danh sach khoa can giu rong — tu choi chay (khong co gi de bao ve)")
    if cmd == "sync":
        mgmt = os.environ.get("CLIPROXY_MGMT_KEY", "").strip()
        if not mgmt:
            raise SystemExit("thieu CLIPROXY_MGMT_KEY")
        return sync(wanted, mgmt)
    if cmd == "check":
        return check(wanted, float(os.environ.get("PGSTORE_KEYS_CHECK_SECONDS", "60")))
    sys.stderr.write("lenh khong ro: %s\n" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
