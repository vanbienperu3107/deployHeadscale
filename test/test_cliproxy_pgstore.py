"""Kho Postgres (PGSTORE) cho CLIProxy + bao dam KHOA CU van dung duoc.

Yeu cau 2026-10-02:
  - Luu config (key them tu web) + token OAuth vao Postgres vpn6.
  - Deploy chi SEED lan dau; DB la nguon su that.
  - Khoa API: chi THEM khoa thieu tu file dung chung OpenCode + secret.
  - Quota failover chay qua Management API.
  - "Phai dam bao key cu van dung duoc".

Lop test:
  - Cau truc (compose/workflow/sql) — chay moi noi.
  - pgstore-keys.py voi Management API GIA lap (HTTP server that, logic handler
    PATCH chep tu upstream) — chay moi noi.
  - pgstore-seed.sh voi Postgres + psql THAT — chi chay khi co `psql`/`initdb`
    (bien PG_BIN), nguoc lai SKIP (khong tinh PASS).
"""
import http.server
import importlib.util
import json
import os
import pathlib
import shutil
import socket
import subprocess
import tempfile
import threading
import time

import pytest
import yaml

ROOT = pathlib.Path(__file__).parent.parent
STACK = ROOT / "cliproxy"
COMPOSE = STACK / "docker-compose.yml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy-cliproxy.yml"
MIGRATE = ROOT / ".github" / "workflows" / "migrate-cliproxy-store.yml"
FAILOVER = ROOT / ".github" / "workflows" / "configure-cliproxy-quota-failover.yml"
SQL = STACK / "sql" / "003_cliproxy_store.sql"
SEED = STACK / "pgstore-seed.sh"
PGSTORE_SH = STACK / "pgstore.sh"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


keys_mod = _load("pgstore_keys", STACK / "pgstore-keys.py")


# ---------------------------------------------------------------- cau truc


def _svc():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["cliproxy"]


def test_compose_pgstore_mac_dinh_tat_va_co_spool():
    env = _svc()["environment"]
    assert "PGSTORE_DSN=${PGSTORE_DSN:-}" in env, "PGSTORE phai TAT khi .env khong co DSN"
    assert "PGSTORE_LOCAL_PATH=/pgstore-spool" in env
    assert not any(e.startswith("PGSTORE_SCHEMA") for e in env), (
        "PGSTORE_SCHEMA phai de trong: co gia tri thi proxy chay CREATE SCHEMA moi lan "
        "khoi dong va bi tu choi (role khong co quyen CREATE tren database)"
    )
    vols = _svc()["volumes"]
    assert "./pgstore-spool:/pgstore-spool" in vols
    assert "./auths:/root/.cli-proxy-api" in vols, "van giu auths de rollback ve file"


def test_gitignore_chan_du_lieu_pgstore():
    gi = (STACK / ".gitignore").read_text(encoding="utf-8")
    for item in ("pgstore-spool/", ".pgstore.env", ".pgstore-state", "backups/"):
        assert item in gi


def test_sql_tao_role_schema_rieng_khong_public():
    sql = SQL.read_text(encoding="utf-8")
    assert "CREATE SCHEMA IF NOT EXISTS cliproxy_store AUTHORIZATION cliproxy_store" in sql
    assert "REVOKE ALL ON SCHEMA cliproxy_store FROM PUBLIC" in sql
    assert "SET search_path = cliproxy_store;" in sql, "search_path chi duoc co schema rieng"
    assert "PASSWORD" not in sql.split("--")[0] and "PASSWORD '" not in sql


def test_deploy_dung_dung_buoc_pgstore():
    wf = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    ssh = [s for s in wf["jobs"]["deploy"]["steps"] if s.get("uses", "").startswith("appleboy/ssh-action")][0]
    script = ssh["with"]["script"]
    assert "CLIPROXY_STORE_PG_PASSWORD" in ssh["with"]["envs"]
    assert ssh["env"]["CLIPROXY_STORE_PG_PASSWORD"] == "${{ secrets.CLIPROXY_STORE_PG_PASSWORD }}"
    order = [
        "cp config.yaml .config.prev.yaml",
        "python3 render-config.py",
        "bash pgstore.sh snapshot-keys",
        "bash pgstore.sh enable",
        "docker compose up -d --remove-orphans",
        "bash pgstore.sh verify",
    ]
    pos = [script.index(x) for x in order]
    assert pos == sorted(pos), "thu tu buoc PGSTORE sai: %s" % order
    assert "@cliproxy-pg-tunnel:5432/derp" in script
    assert "test -n \"$CLIPROXY_STORE_PG_PASSWORD\" || bash pgstore.sh off" in script
    # .env bi ghi lai moi lan deploy -> phai giu dong PGSTORE_DSN cu.
    assert script.index("grep '^PGSTORE_DSN=' .env > .env.keep") < script.index(
        "printf 'CLIPROXY_IMAGE=%s\\n'"
    )


def test_migrate_workflow_kiem_mat_khau_an_toan_url():
    body = MIGRATE.read_text(encoding="utf-8")
    assert "^[A-Za-z0-9]{24,}$" in body
    assert "ALTER ROLE cliproxy_store WITH LOGIN PASSWORD" in body
    wf = yaml.safe_load(body)
    for step in wf["jobs"]["migrate"]["steps"]:
        if step.get("uses", "").startswith("appleboy/ssh-action"):
            assert "<<" not in step["with"]["script"]


def test_failover_khong_con_sua_file_tren_vpn4():
    body = FAILOVER.read_text(encoding="utf-8")
    assert "appleboy/ssh-action" not in body, "phai goi Management API, khong SSH sua file"
    assert "python3 cliproxy/quota-failover.py" in body
    assert "concurrency" in body


def test_script_bash_khong_loi_cu_phap():
    for f in (PGSTORE_SH,):
        subprocess.run(["bash", "-n", str(f)], check=True)
    subprocess.run(["sh", "-n", str(SEED)], check=True)


# ---------------------------------------------------------------- doc khoa


def test_doc_khoa_layout_cu_va_v8_va_flow():
    cu = 'port: 8317\napi-keys:\n  - "sk-a"\n  - \'sk-b\'\n  - sk-c # ghi chu\n\ndebug: false\n'
    assert keys_mod.keys_from_text(cu) == ["sk-a", "sk-b", "sk-c"]
    v8 = (
        "access:\n  api-keys:\n    - \"sk-v8\"\n"
        "api-keys:\n  - name: grp\n    api-key: sk-provider-KHONG-phai-khoa-client\n"
    )
    assert keys_mod.keys_from_text(v8) == ["sk-v8"]
    assert keys_mod.keys_from_text('api-keys: ["sk-x", "sk-y"]\n') == ["sk-x", "sk-y"]


def test_extract_gop_nhieu_nguon_bo_trung_bo_khoa_mau(tmp_path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text('api-keys:\n  - "sk-cu-web"\n  - "sk-opencode"\n', encoding="utf-8")
    b.write_text('api-keys:\n  - "sk-opencode"\n  - "your-api-key-1"\n  - "__API_KEY__"\n', encoding="utf-8")
    got = keys_mod.extract([str(a), str(tmp_path / "khong-co.yaml"), str(b)])
    assert got == ["sk-cu-web", "sk-opencode"]


def test_doc_khoa_tu_template_that_sau_render(tmp_path, monkeypatch):
    """Khoa ma render-config.py sinh ra phai doc lai duoc (dinh dang trich dan khop)."""
    rc = _load("render_config_t", STACK / "render-config.py")
    kf = tmp_path / "k"
    kf.write_text('sk-"la"\\x\nsk-binh-thuong\n', encoding="utf-8")
    monkeypatch.setenv("CLIPROXY_KEY_FILE", str(kf))
    monkeypatch.setenv("CLIPROXY_API_KEY", "sk-secret")
    monkeypatch.setenv("CLIPROXY_MGMT_KEY", "m")
    out = tmp_path / "config.yaml"
    assert rc.main(["x", str(STACK / "config.template.yaml"), str(out)]) == 0
    assert keys_mod.extract([str(out)]) == ['sk-"la"\\x', "sk-binh-thuong", "sk-secret"]
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["api-keys"] == [
        'sk-"la"\\x', "sk-binh-thuong", "sk-secret"
    ]


# ------------------------------------------- Management API gia lap (HTTP that)


class FakeProxy:
    """Mo phong cac endpoint CLIProxyAPI ma pgstore-keys.py dung.

    PATCH /v0/management/api-keys chep logic patchStringList cua upstream:
    {old,new} voi old khong ton tai -> append new.
    """

    def __init__(self, keys, mgmt="mgmt-ok"):
        self.keys = list(keys)
        self.mgmt = mgmt
        self.patches = 0
        self.bad_mgmt = 0
        owner = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _tok(self):
                return self.headers.get("Authorization", "")[len("Bearer "):]

            def do_GET(self):
                if self.path == "/v1/models":
                    if self._tok() in owner.keys:
                        return self._send(200, {"data": [{"id": "m"}]})
                    return self._send(401, {"error": "Invalid API key"})
                if self.path == "/v0/management/api-keys":
                    if self._tok() != owner.mgmt:
                        owner.bad_mgmt += 1
                        return self._send(401, {"error": "invalid management key"})
                    return self._send(200, {"api-keys": owner.keys})
                self._send(404, {})

            def do_PATCH(self):
                if self.path != "/v0/management/api-keys" or self._tok() != owner.mgmt:
                    return self._send(401, {})
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(n))
                owner.patches += 1
                for i, k in enumerate(owner.keys):
                    if k == body["old"]:
                        owner.keys[i] = body["new"]
                        return self._send(200, {"status": "ok"})
                owner.keys.append(body["new"])
                self._send(200, {"status": "ok"})

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def _run_keys(cmd, wanted_file, url, mgmt="mgmt-ok"):
    env = dict(os.environ, CLIPROXY_BASE_URL=url, CLIPROXY_MGMT_KEY=mgmt, PGSTORE_KEYS_CHECK_SECONDS="2")
    return subprocess.run(
        ["python3", str(STACK / "pgstore-keys.py"), cmd, str(wanted_file)],
        env=env, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture
def wanted(tmp_path):
    f = tmp_path / ".keys-wanted"
    f.write_text("sk-cu-web\nsk-opencode\nsk-secret\n", encoding="utf-8")
    return f


def test_sync_them_khoa_cu_thieu_khong_xoa_khoa_moi(wanted):
    # DB/seed chi co 1 khoa cu + 1 khoa them tren web sau nay.
    p = FakeProxy(["sk-opencode", "sk-chi-co-tren-web"])
    try:
        r = _run_keys("sync", wanted, p.url)
        assert r.returncode == 0, r.stderr
        assert p.keys == ["sk-opencode", "sk-chi-co-tren-web", "sk-cu-web", "sk-secret"]
        assert p.patches == 2
        r = _run_keys("check", wanted, p.url)
        assert r.returncode == 0, r.stderr
        assert "3/3 khoa cu goi duoc" in r.stderr
        # KHONG lo khoa ra log.
        for k in ("sk-cu-web", "sk-opencode", "sk-secret"):
            assert k not in r.stderr and k not in r.stdout
    finally:
        p.close()


def test_sync_idempotent_khi_du_khoa(wanted):
    p = FakeProxy(["sk-secret", "sk-cu-web", "sk-opencode"])
    try:
        assert _run_keys("sync", wanted, p.url).returncode == 0
        assert p.patches == 0
    finally:
        p.close()


def test_check_do_khi_mot_khoa_cu_401(wanted):
    p = FakeProxy(["sk-opencode", "sk-secret"])
    try:
        r = _run_keys("check", wanted, p.url)
        assert r.returncode != 0
        assert "1/3 khoa cu KHONG goi duoc" in r.stderr
    finally:
        p.close()


def test_sync_sai_management_key_dung_ngay_khong_thu_lai(wanted):
    """Sai key 5 lan = IP bi ban 30 phut -> chi duoc goi 1 lan roi dung."""
    p = FakeProxy(["sk-opencode"])
    try:
        r = _run_keys("sync", wanted, p.url, mgmt="sai")
        assert r.returncode != 0
        assert p.bad_mgmt == 1
        assert p.patches == 0
    finally:
        p.close()


def test_danh_sach_rong_thi_tu_choi(tmp_path):
    f = tmp_path / "w"
    f.write_text("\n", encoding="utf-8")
    r = _run_keys("check", f, "http://127.0.0.1:9")
    assert r.returncode != 0 and "rong" in r.stderr


def test_failover_doi_session_affinity_chi_trong_routing():
    fo = _load("qf", STACK / "quota-failover.py") if False else None  # noqa: F841
    src = (STACK / "quota-failover.py").read_text(encoding="utf-8")
    ns = {}
    # Chi lay ham thuan, khong chay phan doc bien moi truong o dau module.
    start = src.index("def set_session_affinity_false")
    end = src.index("def main")
    exec(src[start:end], ns)
    text = "routing:\n  strategy: x\n  session-affinity: true # c\nother:\n  session-affinity: true\n"
    out, changed = ns["set_session_affinity_false"](text)
    assert changed
    assert out == "routing:\n  strategy: x\n  session-affinity: false\nother:\n  session-affinity: true\n"


# ------------------------------------------- pgstore-seed.sh voi Postgres THAT


def _pg_bin():
    d = os.environ.get("PG_BIN", "")
    if d and (pathlib.Path(d) / "initdb").exists():
        return pathlib.Path(d)
    p = shutil.which("initdb")
    return pathlib.Path(p).parent if p and shutil.which("psql") else None


PG = _pg_bin()
needs_pg = pytest.mark.skipif(PG is None, reason="khong co initdb/psql (dat PG_BIN)")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def pg():
    if PG is None:
        pytest.skip("khong co postgres")
    d = pathlib.Path(tempfile.mkdtemp(prefix="pgstore-test-"))
    data = d / "data"
    port = _free_port()
    subprocess.run([str(PG / "initdb"), "-D", str(data), "-U", "derp", "-A", "trust"],
                   check=True, capture_output=True)
    subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-o",
                    "-p %d -k %s -c listen_addresses=127.0.0.1" % (port, d),
                    "-l", str(d / "log"), "-w", "start"], check=True, capture_output=True)
    base = "postgresql://derp@127.0.0.1:%d/postgres" % port
    subprocess.run([str(PG / "psql"), base, "-qc", "CREATE DATABASE derp"], check=True)
    admin = "postgresql://derp@127.0.0.1:%d/derp" % port
    # Bang cua derp/headscale co san trong public: role moi KHONG duoc dung toi.
    subprocess.run([str(PG / "psql"), admin, "-qc", "CREATE TABLE public.nodes(id int)"], check=True)
    subprocess.run([str(PG / "psql"), admin, "-v", "ON_ERROR_STOP=1", "-qf", str(SQL)], check=True)
    subprocess.run([str(PG / "psql"), admin, "-v", "ON_ERROR_STOP=1", "-qf", str(SQL)], check=True)  # idempotent
    subprocess.run([str(PG / "psql"), admin, "-qc",
                    "ALTER ROLE cliproxy_store WITH LOGIN PASSWORD 'abc'"], check=True)
    yield {"admin": admin, "store": "postgresql://cliproxy_store:abc@127.0.0.1:%d/derp" % port}
    subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "stop"], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


def _seed(dsn, *args):
    env = dict(os.environ, PGSTORE_DSN=dsn, PATH="%s:%s" % (PG, os.environ["PATH"]))
    return subprocess.run(["sh", str(SEED), *args], env=env, capture_output=True, text=True)


def _psql(dsn, q):
    return subprocess.run([str(PG / "psql"), dsn, "-qtAXc", q], check=True,
                          capture_output=True, text=True).stdout.strip()


def _kv(out):
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "auths").mkdir()
    (tmp_path / "config.yaml").write_text('api-keys:\n  - "sk-cu"\nport: 8317\n# ghi chu tieng Viet: đã\n',
                                          encoding="utf-8")
    (tmp_path / "auths" / "claude-a@x.com.json").write_text('{"type":"claude","email":"a@x.com","refresh_token":"r1"}')
    (tmp_path / "auths" / "codex-b.json").write_text('{"type":"codex","x":"it\'s"}')
    return tmp_path


@needs_pg
def test_pg_role_khong_doc_duoc_bang_derp_va_bang_vao_schema_rieng(pg, ws):
    _seed(pg["store"], "reset")
    r = _seed(pg["store"], "check")
    assert r.returncode == 0, r.stderr
    assert "SCHEMA=cliproxy_store" in r.stdout
    assert _psql(pg["admin"], "SELECT count(*) FROM information_schema.tables "
                 "WHERE table_schema='public' AND table_name LIKE '%_store'") == "0"
    bad = subprocess.run([str(PG / "psql"), pg["store"], "-qtAXc", "SELECT * FROM public.nodes"],
                         capture_output=True, text=True)
    assert bad.returncode != 0, "role cliproxy_store khong duoc doc bang cua derp"


@needs_pg
def test_pg_seed_lan_dau_dung_noi_dung_byte(pg, ws):
    _seed(pg["store"], "reset")
    assert _kv(_seed(pg["store"], "need-seed").stdout)["NEED_SEED"] == "1"
    r = _seed(pg["store"], "seed", str(ws / "config.yaml"), str(ws / "auths"))
    assert r.returncode == 0, r.stderr
    kv = _kv(r.stdout)
    assert kv["SEEDED_CONFIG"] == "1" and kv["SEEDED_AUTH"] == "2"
    content = _psql(pg["store"], "SELECT content FROM config_store WHERE id='config'")
    assert content + "\n" == (ws / "config.yaml").read_text(encoding="utf-8")
    tok = json.loads(_psql(pg["store"], "SELECT content FROM auth_store WHERE id='claude-a@x.com.json'"))
    assert tok["refresh_token"] == "r1"
    assert _kv(_seed(pg["store"], "need-seed").stdout)["NEED_SEED"] == "0"


@needs_pg
def test_pg_seed_lan_hai_khong_ghi_de_key_them_tu_web(pg, ws):
    _seed(pg["store"], "reset")
    _seed(pg["store"], "seed", str(ws / "config.yaml"), str(ws / "auths"))
    _psql(pg["store"], "UPDATE config_store SET content = content || 'gemini-api-key: [web]' WHERE id='config'")
    _psql(pg["store"], "DELETE FROM auth_store WHERE id='codex-b.json'")  # go tren web
    r = _seed(pg["store"], "seed", str(ws / "config.yaml"), str(ws / "auths"))
    kv = _kv(r.stdout)
    assert kv["SEEDED_CONFIG"] == "0" and kv["SEEDED_AUTH"] == "0"
    assert "gemini-api-key" in _psql(pg["store"], "SELECT content FROM config_store")
    assert _psql(pg["store"], "SELECT count(*) FROM auth_store WHERE id='codex-b.json'") == "0", (
        "token da go tren web khong duoc hoi sinh"
    )


@needs_pg
def test_pg_xoa_het_token_tren_web_thi_khong_seed_lai(pg, ws):
    _seed(pg["store"], "reset")
    _seed(pg["store"], "seed", str(ws / "config.yaml"), str(ws / "auths"))
    _psql(pg["store"], "DELETE FROM auth_store")
    kv = _kv(_seed(pg["store"], "seed", str(ws / "config.yaml"), str(ws / "auths")).stdout)
    assert kv["SEEDED_AUTH"] == "0" and kv["AUTH_ROWS"] == "0"


@needs_pg
def test_pg_ten_file_la_dung_lai_khong_ghi_gi(pg, ws):
    _seed(pg["store"], "reset")
    (ws / "auths" / "x';DROP TABLE auth_store;--.json").write_text("{}")
    r = _seed(pg["store"], "seed", str(ws / "config.yaml"), str(ws / "auths"))
    assert r.returncode != 0
    assert _psql(pg["store"], "SELECT count(*) FROM auth_store") == "0"
    assert _psql(pg["store"], "SELECT to_regclass('auth_store') IS NOT NULL") == "t"


@needs_pg
def test_pg_json_hong_thi_rollback_ca_lo(pg, ws):
    _seed(pg["store"], "reset")
    (ws / "auths" / "z-hong.json").write_text("{khong phai json")
    r = _seed(pg["store"], "seed", str(ws / "config.yaml"), str(ws / "auths"))
    assert r.returncode != 0
    assert _psql(pg["store"], "SELECT count(*) FROM auth_store") == "0", "phai all-or-nothing"


@needs_pg
def test_pg_search_path_public_bi_chan(pg):
    _psql(pg["admin"], "DO $$BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='lac') "
          "THEN CREATE ROLE lac LOGIN PASSWORD 'x'; END IF; END$$")
    _psql(pg["admin"], "GRANT CREATE ON SCHEMA public TO lac")
    dsn = pg["store"].replace("cliproxy_store:abc", "lac:x")
    r = _seed(dsn, "check")
    assert r.returncode == 3, r.stdout + r.stderr
    assert _psql(pg["admin"], "SELECT count(*) FROM information_schema.tables "
                 "WHERE table_schema='public' AND table_name LIKE '%_store'") == "0"
