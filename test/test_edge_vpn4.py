#!/usr/bin/env python3
"""Cac kiem tra cau hinh cho edge-vpn4.

Khong ket noi VPN that. Moi test doc YAML/config trong repo de chan regression
nguy hiem: derper mat 443, nginx resolve Docker luc startup, hoac route moi lam
hong duong CLIProxy cu.
"""

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).parent.parent
EDGE = ROOT / "edge-vpn4"
HAPROXY_CONF = EDGE / "haproxy.cfg"
CADDYFILE = EDGE / "Caddyfile"
EDGE_COMPOSE = EDGE / "docker-compose.yml"
DERP_COMPOSE = ROOT / "derp-vpn4" / "docker-compose.yml"
CLIPROXY_COMPOSE = ROOT / "cliproxy" / "docker-compose.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-edge-vpn4.yml"

CLIPROXY_HOST = "cliproxy.hangocthanh.io.vn"
OPENCODE_HOST = "opencode.hangocthanh.io.vn"
OPENCODE2_HOST = "opencode2.hangocthanh.io.vn"
PORTAINER_HOST = "portainer.hangocthanh.io.vn"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def ports_of(compose_path, service):
    return [str(p) for p in load(compose_path)["services"][service].get("ports", [])]


# ---------- ai giu cong nao ----------

def test_chi_haproxy_giu_443():
    assert "443:443" in ports_of(EDGE_COMPOSE, "haproxy"), "haproxy phai publish 443"


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
        (EDGE_COMPOSE, "haproxy"),
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


# ---------- HAProxy ----------

def test_haproxy_dinh_tuyen_sni_l4_khong_giai_ma():
    conf = HAPROXY_CONF.read_text(encoding="utf-8")
    assert "mode tcp" in conf and "req.ssl_sni" in conf
    assert "bind :443" in conf
    assert "backend=%b/%s" in conf
    assert "ssl " not in conf, "HAProxy KHONG duoc terminate TLS"


def test_sni_khong_khop_thi_ve_derper():
    """Bat bien an toan: cau hinh ten mien sai khong duoc lam chet DERP."""
    conf = HAPROXY_CONF.read_text(encoding="utf-8")
    assert re.search(r"default_backend\s+derper", conf)


def test_haproxy_resolve_docker_backend_luc_chay():
    conf = HAPROXY_CONF.read_text(encoding="utf-8")
    assert "nameserver docker 127.0.0.11:53" in conf
    assert "resolvers docker" in conf


def test_ten_mien_cliproxy_duoc_dinh_tuyen():
    conf = HAPROXY_CONF.read_text(encoding="utf-8")
    assert CLIPROXY_HOST in conf, f"thieu route cho {CLIPROXY_HOST}"


def test_ten_mien_opencode_duoc_dinh_tuyen():
    conf = HAPROXY_CONF.read_text(encoding="utf-8")
    assert OPENCODE_HOST in conf, f"thieu route cho {OPENCODE_HOST}"


def test_portainer_sni_route_is_exact_and_existing_routes_stay_unchanged():
    """Portainer chi duoc them vao map SNI; DERP va hai duong cu phai bat bien."""
    conf = HAPROXY_CONF.read_text(encoding="utf-8")
    for host, backend in ((PORTAINER_HOST, "portainer"), (CLIPROXY_HOST, "cliproxy"), (OPENCODE_HOST, "opencode")):
        assert host in conf and f"use_backend {backend}" in conf


def test_send_proxy_chi_duoc_gui_truc_tiep_toi_hai_backend_opencode():
    conf = HAPROXY_CONF.read_text(encoding="utf-8")
    for backend, port in (("opencode", "8445"), ("opencode2", "8450")):
        block = re.search(rf"backend {backend}\n(.*?)(?=\nbackend |\Z)", conf, re.DOTALL)
        assert block and f"caddy-edge:{port}" in block.group(1) and "send-proxy" in block.group(1)
    for backend in ("derper", "cliproxy", "portainer"):
        block = re.search(rf"backend {backend}\n(.*?)(?=\nbackend |\Z)", conf, re.DOTALL)
        assert block and "send-proxy" not in block.group(1)


def test_opencode2_has_an_isolated_proxy_protocol_ingress_and_fail2ban_jail():
    """v2 must not reuse v1 or Portainer listeners, logs, or fail2ban state."""
    conf = HAPROXY_CONF.read_text(encoding="utf-8")
    caddy = CADDYFILE.read_text(encoding="utf-8")
    jail = (EDGE / "fail2ban" / "jail.d" / "opencode2.conf").read_text(encoding="utf-8")
    filt = (EDGE / "fail2ban" / "filter.d" / "opencode2-401.conf").read_text(encoding="utf-8")

    route = re.search(r"backend opencode2\n(.*?)(?=\nbackend |\Z)", conf, re.DOTALL)
    assert route and "caddy-edge:8450" in route.group(1) and "send-proxy" in route.group(1)

    listener = caddy[caddy.index("servers :8450 {"):caddy.index("https://cliproxy", caddy.index("servers :8450 {"))]
    assert "proxy_protocol" in listener and "fallback_policy require" in listener
    assert "servers :8447" not in caddy, "Portainer phai giu TLS thuong, khong nhan PROXY"
    site = f"https://{OPENCODE2_HOST}:8450"
    assert site in caddy and "reverse_proxy opencode2:4096" in caddy
    assert "output file /var/log/caddy/opencode2-access.log" in caddy

    assert "[opencode2-401]" in jail
    assert "logpath = /remotelogs/opencode2-access.log" in jail
    assert "chain = DOCKER-USER" in jail
    assert '"remote_ip":"<HOST>"' in filt and '"status":401' in filt
    assert "8447" not in jail + filt and "8448" not in jail + filt


def test_caddy_8445_nhan_proxy_protocol_con_8444_thi_khong():
    """Chi cong opencode nhan PROXY protocol. Bat nham cho 8444 (cliproxy —
    nginx noi thang KHONG gui header) la moi ket noi cliproxy hong ngay."""
    body = CADDYFILE.read_text(encoding="utf-8")
    vi_tri = body.find("servers :8445")
    assert vi_tri >= 0, "Caddyfile phai co global option `servers :8445`"
    assert "proxy_protocol" in body[vi_tri:vi_tri + 200], (
        "khoi servers :8445 phai bat listener_wrappers proxy_protocol"
    )
    assert not re.search(r"servers :8444", body), (
        "KHONG duoc bat listener_wrappers cho 8444 — nginx khong gui PROXY header toi do"
    )


def test_fail2ban_cau_hinh_day_du():
    """fail2ban chi co tac dung khi du 3 manh: doc dung file log Caddy ghi ra,
    filter bat dung dang JSON cua Caddy, va compose noi dung volume."""
    jail = (EDGE / "fail2ban" / "jail.d" / "opencode.conf").read_text(encoding="utf-8")
    filt = (EDGE / "fail2ban" / "filter.d" / "opencode-401.conf").read_text(encoding="utf-8")
    caddy = CADDYFILE.read_text(encoding="utf-8")
    compose = load(EDGE_COMPOSE)

    m_log = re.search(r"output file (\S+opencode[^\s{]+)", caddy)
    assert m_log, "Caddyfile phai ghi log site opencode ra file"
    ten_file = m_log.group(1).rsplit("/", 1)[-1]
    assert ten_file in jail, f"jail phai tro toi dung file log {ten_file}"

    assert '"client_ip":"<HOST>"' in filt, "filter phai bat client_ip (IP that qua PROXY protocol)"
    assert "401" in filt, "filter phai loc theo status 401"

    f2b = compose["services"]["fail2ban"]
    assert f2b.get("network_mode") == "host", "fail2ban phai o host network moi ban duoc iptables host"
    assert "NET_ADMIN" in f2b.get("cap_add", []), "thieu NET_ADMIN thi khong sua duoc iptables"
    vols = [str(v) for v in f2b.get("volumes", [])]
    assert any("caddy_edge_logs" in v for v in vols), "fail2ban phai mount volume log cua caddy"
    caddy_vols = [str(v) for v in compose["services"]["caddy-edge"].get("volumes", [])]
    assert any("caddy_edge_logs" in v for v in caddy_vols), "caddy-edge phai ghi log vao volume chung"


def test_proxy_timeout_du_dai_cho_derp():
    """Mac dinh 10 phut se cat nham ket noi DERP dang im lang giua cac keepalive."""
    conf = HAPROXY_CONF.read_text(encoding="utf-8")
    assert "timeout client 1h" in conf and "timeout server 1h" in conf


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
    assert "reverse_proxy opencode-server:4096" in body
    assert OPENCODE_HOST in body


def test_portainer_caddy_site_terminates_normal_tls_and_forwards_browser_origin():
    """8447 la TLS thuong nhu 8444, khong phai chang PROXY protocol cua OpenCode."""
    body = CADDYFILE.read_text(encoding="utf-8")
    site = f"https://{PORTAINER_HOST}:8447"
    assert site in body, "Caddy phai nghe TLS cho Portainer tren 8447"

    site_body = body[body.index(site):]
    next_site = site_body.find("\nhttps://", 1)
    if next_site >= 0:
        site_body = site_body[:next_site]

    assert "disable_http_challenge" in site_body, (
        "Portainer phai dung TLS-ALPN vi derper giu host port 80"
    )
    assert "reverse_proxy portainer:9000" in site_body
    assert "header_up X-Forwarded-Proto https" in site_body
    assert "header_up Host {http.request.host}" in site_body
    assert "output stdout" in site_body and "format json" in site_body, (
        "access log Portainer phai la JSON ra stdout"
    )
    assert "proxy_protocol" not in site_body
    assert not re.search(r"servers\s+:8447\s*\{", body), (
        "8447 khong duoc co listener wrapper PROXY protocol"
    )


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


def test_workflow_kiem_tra_dns_opencode():
    body = WORKFLOW.read_text(encoding="utf-8")
    assert OPENCODE_HOST in body, f"thieu buoc kiem tra DNS cho {OPENCODE_HOST}"


def test_workflow_kiem_tra_dns_va_xac_thuc_opencode2_ma_khong_deploy_backend():
    body = WORKFLOW.read_text(encoding="utf-8")
    assert OPENCODE2_HOST in body
    assert f"https://{OPENCODE2_HOST}/api/info" in body
    assert f"{OPENCODE2_HOST}/global/health" not in body
    assert '"${CODE:-000}" = "200"' in body, "200 khong xac thuc phai la loi bao mat"
    assert '"${CODE:-000}" != "401"' in body
    assert "--force-recreate haproxy caddy-edge fail2ban" in body
    assert "docker compose up -d --remove-orphans --force-recreate haproxy caddy-edge fail2ban" in body
    assert "haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg" in body


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
