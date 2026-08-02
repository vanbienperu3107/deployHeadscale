"""Validate stack edge-vpn4 (chia se cong 443 giua derper va CLIProxyAPI).

vpn4 chi co MOT IP cong khai ma can hai dich vu tren 443. nginx doc SNI roi noi
TCP thang, KHONG giai ma. Cac bat bien duoi day bao ve chinh diem yeu cua kien
truc do — derper la relay chinh cua ca tailnet, hong no la hong het:

  1. nginx phai la thu duy nhat giu 443; derper KHONG duoc publish 443 nua.
  2. derper van phai giu cong 80 (ACME HTTP-01 cua chinh no) va 3478/udp (STUN).
  3. SNI khong khop phai ve derper (default) — loi ten mien khong duoc lam chet DERP.
  4. proxy_timeout phai du dai cho ket noi DERP song lau.
  5. Caddy khong duoc dung http challenge (cong 80 la cua derper).
  6. reverse_proxy phai tat dem (flush_interval -1) neu khong SSE se dung hinh.
  7. Ba stack phai cung mang 'edge' thi nginx moi goi duoc backend.
"""
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).parent.parent
EDGE = ROOT / "edge-vpn4"
NGINX_CONF = EDGE / "nginx.conf"
CADDYFILE = EDGE / "Caddyfile"
EDGE_COMPOSE = EDGE / "docker-compose.yml"
DERP_COMPOSE = ROOT / "derp-vpn4" / "docker-compose.yml"
CLIPROXY_COMPOSE = ROOT / "cliproxy" / "docker-compose.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-edge-vpn4.yml"

CLIPROXY_HOST = "cliproxy.hangocthanh.io.vn"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def ports_of(compose_path, service):
    return [str(p) for p in load(compose_path)["services"][service].get("ports", [])]


# ---------- ai giu cong nao ----------

def test_chi_nginx_giu_443():
    assert "443:443" in ports_of(EDGE_COMPOSE, "nginx"), "nginx phai publish 443"


def test_derper_khong_con_publish_443():
    """Hai container cung doi 443 -> container thu hai khong khoi dong duoc."""
    ports = ports_of(DERP_COMPOSE, "derper")
    assert not any(p.startswith("443:") or p == "443" for p in ports), (
        f"derper van publish 443, se dung do voi nginx: {ports}"
    )


def test_derper_van_giu_80_va_stun():
    ports = ports_of(DERP_COMPOSE, "derper")
    assert "80:80" in ports, (
        "derper phai giu cong 80 — autocert cua no xin chung chi qua HTTP-01 o day"
    )
    assert "3478:3478/udp" in ports, "STUN la UDP, nginx khong proxy duoc, phai bind thang"


def test_caddy_edge_khong_publish_cong_nao():
    """Caddy chi duoc goi tu nginx qua mang noi bo, khong ho ra Internet."""
    caddy = load(EDGE_COMPOSE)["services"]["caddy-edge"]
    assert not caddy.get("ports"), f"caddy-edge khong duoc publish cong: {caddy.get('ports')}"


# ---------- mang dung chung ----------

def test_ba_stack_cung_mang_edge():
    for path, service in (
        (EDGE_COMPOSE, "nginx"),
        (EDGE_COMPOSE, "caddy-edge"),
        (DERP_COMPOSE, "derper"),
        (CLIPROXY_COMPOSE, "cliproxy"),
    ):
        nets = load(path)["services"][service].get("networks", [])
        assert "edge" in nets, f"{path.parent.name}/{service} phai o mang edge, dang co: {nets}"


def test_mang_edge_khai_bao_external_o_moi_stack():
    """Ba compose khac project — mang phai la external, cung ten 'edge'."""
    for path in (EDGE_COMPOSE, DERP_COMPOSE, CLIPROXY_COMPOSE):
        net = load(path)["networks"]["edge"]
        assert net.get("external") is True, f"{path}: mang edge phai external"
        assert net.get("name") == "edge", f"{path}: ten mang phai la 'edge'"


# ---------- nginx ----------

def test_nginx_dinh_tuyen_bang_ssl_preread_khong_giai_ma():
    conf = NGINX_CONF.read_text(encoding="utf-8")
    assert "ssl_preread on" in conf, "phai bat ssl_preread de doc SNI"
    assert "ssl_certificate" not in conf, (
        "nginx KHONG duoc terminate TLS — derper phai tu giu cert cua no"
    )
    assert "stream {" in conf, "phai dinh tuyen o tang stream (TCP), khong phai http"


def test_sni_khong_khop_thi_ve_derper():
    """Bat bien an toan: cau hinh ten mien sai khong duoc lam chet DERP."""
    conf = NGINX_CONF.read_text(encoding="utf-8")
    m = re.search(r"default\s+([\w.:-]+);", conf)
    assert m, "map phai co nhanh default"
    assert m.group(1).startswith("derper:"), (
        f"default phai tro ve derper, dang la {m.group(1)}"
    )


def test_khong_dung_upstream_block_de_nginx_t_chay_doc_lap():
    """Khoi `upstream` bat nginx resolve NGAY luc doc config: `nginx -t` trong
    workflow (chay truoc khi derper vao mang edge) se that bai, va derper khoi dong
    lai doi IP thi nginx cung khong bat kip. Phai dung resolver + bien.
    """
    conf = NGINX_CONF.read_text(encoding="utf-8")
    assert not re.search(r"^\s*upstream\s+", conf, re.MULTILINE), (
        "khong duoc dung khoi upstream — dung `resolver` + bien trong proxy_pass"
    )
    assert "resolver 127.0.0.11" in conf, "phai khai bao DNS noi bo cua Docker"
    assert "proxy_pass $backend" in conf, "proxy_pass phai dung bien de resolve luc chay"


def test_ten_mien_cliproxy_duoc_dinh_tuyen():
    conf = NGINX_CONF.read_text(encoding="utf-8")
    assert CLIPROXY_HOST in conf, f"thieu route cho {CLIPROXY_HOST}"


def test_proxy_timeout_du_dai_cho_derp():
    """Mac dinh 10 phut se cat nham ket noi DERP dang im lang giua cac keepalive."""
    conf = NGINX_CONF.read_text(encoding="utf-8")
    m = re.search(r"proxy_timeout\s+(\d+)([smh]);", conf)
    assert m, "phai dat proxy_timeout tuong minh"
    value, unit = int(m.group(1)), m.group(2)
    seconds = value * {"s": 1, "m": 60, "h": 3600}[unit]
    assert seconds >= 1800, f"proxy_timeout {value}{unit} qua ngan cho DERP"


# ---------- caddy ----------

def test_caddy_khong_dung_http_challenge():
    """Cong 80 thuoc ve derper — Caddy phai xin chung chi bang TLS-ALPN."""
    body = CADDYFILE.read_text(encoding="utf-8")
    assert "disable_http_challenge" in body, (
        "phai tat http challenge, neu khong Caddy se doi cong 80 cua derper"
    )


def test_caddy_tat_dem_de_sse_chay_ngay():
    body = CADDYFILE.read_text(encoding="utf-8")
    assert "flush_interval -1" in body, (
        "thieu flush_interval -1 thi phan hoi streaming bi dem lai, client 'dung hinh'"
    )


def test_caddy_tro_dung_backend():
    body = CADDYFILE.read_text(encoding="utf-8")
    assert "reverse_proxy cliproxy:8317" in body
    assert CLIPROXY_HOST in body


# ---------- workflow ----------

def test_workflow_kiem_tra_dns_truoc_khi_dung_toi_derper():
    """Cat 443 khi ten mien chua san = DERP chet ma cliproxy cung khong len."""
    wf = load(WORKFLOW)
    steps = wf["jobs"]["deploy"]["steps"]
    names = [s.get("name", "") for s in steps]
    dns_idx = next((i for i, n in enumerate(names) if "DNS" in n), None)
    ssh_idx = next((i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("appleboy")), None)
    assert dns_idx is not None, "phai co buoc kiem tra DNS"
    assert ssh_idx is not None
    assert dns_idx < ssh_idx, "kiem tra DNS phai chay TRUOC khi SSH vao dung toi derper"


def test_workflow_verify_derp_con_song():
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "/derp/probe" in body, "phai verify DERP con song sau khi doi cong"
    assert "rollback" in body.lower(), "thong bao loi phai chi duong rollback"


def test_workflow_giu_duong_cu_28417():
    """Doi may dang dung cong 28417 khong duoc gay hong khi them 443."""
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "28417" in body, "phai verify duong cu 28417 van con"


def test_workflow_chung_concurrency_group_vpn4():
    wf = load(WORKFLOW)
    assert wf["concurrency"]["group"] == "deploy-vpn4-host"


def test_workflow_khong_dung_heredoc_hay_else_trong_script_ssh():
    """Bay ssh-action: dong kiem tra exit code duoc chen sau MOI dong."""
    wf = load(WORKFLOW)
    for step in wf["jobs"]["deploy"]["steps"]:
        if not str(step.get("uses", "")).startswith("appleboy/ssh-action"):
            continue
        script = step["with"]["script"]
        assert "<<" not in script, "khong duoc dung heredoc trong script ssh-action"
        for line in script.splitlines():
            assert line.strip() != "else", "khong duoc dung nhanh else trong script ssh-action"
