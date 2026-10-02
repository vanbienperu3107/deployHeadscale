#!/usr/bin/env python3
"""Dat thu tu dung tai khoan Claude (primary -> backup) + bat chuyen khi het quota,
qua MANAGEMENT API cua CLIProxy (khong sua file tren may).

    CLIPROXY_BASE_URL=https://cliproxy.hangocthanh.io.vn \\
    CLIPROXY_MGMT_KEY=... \\
    PRIMARY_EMAIL=a@x PRIMARY_PRIORITY=2 BACKUP_EMAIL=b@x BACKUP_PRIORITY=1 \\
    python3 quota-failover.py

Vi sao doi tu sua file sang API (2026-10-02): khi bat kho Postgres (PGSTORE), proxy
doc config + token tu DB; sua ./auths/*.json hay ./config.yaml tren vpn4 khong con
tac dung. Management API thi dung cho CA HAI che do — proxy tu ghi vao kho dang bat.

Thay doi:
  - Tai khoan Claude cua 2 email: priority theo input, weight=1, bat lai neu dang tat.
  - quota-exceeded.switch-project = true, switch-preview-model = true.
  - routing.session-affinity = false (affinity giu phien o tai khoan het quota).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit("thieu bien %s" % name)
    return v


BASE = env("CLIPROXY_BASE_URL").rstrip("/")
MGMT = env("CLIPROXY_MGMT_KEY")


def call(method, path, body=None, raw=None, content_type="application/json"):
    req = urllib.request.Request(BASE + "/v0/management" + path, method=method)
    req.add_header("Authorization", "Bearer " + MGMT)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", content_type)
    elif raw is not None:
        data = raw
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def must(method, path, **kw):
    code, raw = call(method, path, **kw)
    if code == 401 or code == 403:
        # KHONG thu lai: sai key 5 lan la IP runner bi ban 30 phut.
        raise SystemExit("%s %s -> HTTP %d: management key sai hoac remote bi tat" % (method, path, code))
    if code < 200 or code >= 300:
        raise SystemExit("%s %s -> HTTP %d %s" % (method, path, code, raw[:300]))
    return raw


def find_email(entry):
    for key in ("email", "label", "account"):
        v = entry.get(key)
        if isinstance(v, str) and "@" in v:
            return v.strip().lower()
    return ""


def set_session_affinity_false(text):
    """Doi `session-affinity: true` -> false trong khoi routing (giu nguyen moi dong khac)."""
    out, changed, in_routing = [], False, False
    for line in text.splitlines():
        s = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and s and not s.startswith("#"):
            in_routing = s.startswith("routing:")
        if in_routing and indent > 0 and s.startswith("session-affinity:"):
            val = s.split(":", 1)[1].split("#", 1)[0].strip().lower()
            if val == "true":
                line = line[: indent] + "session-affinity: false"
                changed = True
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), changed


def main():
    targets = {
        env("PRIMARY_EMAIL").lower(): (int(env("PRIMARY_PRIORITY")), "primary"),
        env("BACKUP_EMAIL").lower(): (int(env("BACKUP_PRIORITY")), "backup"),
    }
    files = json.loads(must("GET", "/auth-files").decode("utf-8")).get("files") or []
    seen, changed = set(), []
    for f in files:
        provider = str(f.get("provider") or f.get("type") or "").strip().lower()
        if provider and provider != "claude":
            continue
        email = find_email(f)
        if email not in targets:
            continue
        priority, role = targets[email]
        name = f.get("name") or f.get("id")
        must("PATCH", "/auth-files/fields", body={"name": name, "priority": priority, "weight": 1})
        if f.get("disabled"):
            must("PATCH", "/auth-files/status", body={"name": name, "disabled": False})
        seen.add(email)
        changed.append((name, email, role, priority))
    for name, email, role, priority in changed:
        print("updated %s: %s role=%s priority=%d weight=1 enabled=true" % (name, email, role, priority))
    missing = set(targets) - seen
    if missing:
        raise SystemExit("missing target emails: " + ", ".join(sorted(missing)))
    if len(changed) < 2:
        raise SystemExit("expected at least two changed Claude auth files")

    must("PUT", "/quota-exceeded/switch-project", body={"value": True})
    must("PUT", "/quota-exceeded/switch-preview-model", body={"value": True})
    print("quota-exceeded: switch-project=true switch-preview-model=true")

    cfg_text = must("GET", "/config.yaml").decode("utf-8")
    new_text, did = set_session_affinity_false(cfg_text)
    if did:
        must("PUT", "/config.yaml", raw=new_text.encode("utf-8"), content_type="application/yaml")
        print("updated config: routing.session-affinity=false")
    else:
        print("config: session-affinity already not true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
