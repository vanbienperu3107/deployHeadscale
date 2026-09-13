"""Validate failover setup va cau truc compose - chay trong CI truoc deploy.

DERPMap KHONG con lay tu config/derp.yaml tinh (da xoa): nguon duy nhat la
derp-backend (DB Postgres) qua config.yaml derp.urls -> /derpmap.json. Cac test
o day chi con kiem tra config.yaml tro dung toi nguon dong + cau truc docker
compose cua tung relay/derper. Danh sach node (hostname/ipv4/region/port) do
dashboard/DB quan ly, khong assert tinh trong repo nua.
"""
import pathlib
import yaml

ROOT = pathlib.Path(__file__).parent.parent
HS_CONFIG = ROOT / "config" / "config.yaml"


def load_hs():
    return yaml.safe_load(HS_CONFIG.read_text())


# ---------- headscale config: nguon DERP dong + failover setup ----------

def test_headscale_config_co_derp_source_dong():
    """DERP map DONG: config.yaml lay region tu derp-backend (DB Postgres) qua derp.urls
    + auto_update (thay cho derp.paths tinh). Bat/tat/them node tren dashboard -> headscale
    tu fetch lai /derpmap.json, client tu chuyen, khong reload."""
    cfg = load_hs()
    derp = cfg.get("derp", {})
    urls = derp.get("urls", [])
    assert any("derpmap.json" in u for u in urls), (
        f"config.yaml: derp.urls phai tro toi /derpmap.json cua derp-backend. Hien tai: {urls}"
    )
    assert derp.get("auto_update_enabled") is True, (
        "derp.auto_update_enabled phai = true (headscale tu fetch lai DERP map dinh ky)"
    )


def test_headscale_co_nguon_dong_de_failover():
    """
    Khi 1 region chet, client phai co region du phong.

    Kien truc hien tai: embedded DERP region 999 (controller vpn2) da TAT
    co chu dich (derp.server.enabled=false). Failover den tu NHIEU region DONG
    lay tu derp-backend (DB derp_servers) qua derp.urls -> /derpmap.json, cap
    nhat lien tuc bang auto_update. So luong region (>=2) do DB quan ly, khong
    assert tu file config tinh nua. O tang config, chi can dam bao nguon dong
    external duoc bat + auto_update de headscale luon co DERP map moi nhat.
    """
    cfg = load_hs()
    derp = cfg.get("derp", {})
    urls = derp.get("urls", [])

    has_external = any("derpmap.json" in u for u in urls)
    assert has_external, (
        "Nguon DERP dong (external) phai duoc bat de co failover da-region: "
        f"derp.urls phai tro toi /derpmap.json cua derp-backend. Hien tai: {urls}"
    )
    assert derp.get("auto_update_enabled") is True, (
        "derp.auto_update_enabled phai = true de headscale tu fetch lai DERP map "
        "(region moi bat/tat tren DB duoc phan anh, dam bao con region du phong)"
    )


def test_headscale_khong_dung_derp_tailscale_com():
    """Full self-host: derp.urls CHI duoc tro toi self-host (derp-backend), KHONG duoc dung
    DERP cua Tailscale Inc (controlplane.tailscale.com)."""
    cfg = load_hs()
    urls = cfg.get("derp", {}).get("urls", [])
    for u in urls:
        assert "tailscale.com" not in u, (
            f"derp.urls khong duoc tro toi Tailscale Inc (full self-host). Vi pham: {u}"
        )


# ---------- derp-vpn3 docker-compose ----------

def test_derp_vpn3_compose_ton_tai():
    compose = ROOT / "derp-vpn3" / "docker-compose.yml"
    assert compose.exists(), "derp-vpn3/docker-compose.yml phai ton tai"


def test_derp_vpn3_compose_co_derper_service():
    compose = ROOT / "derp-vpn3" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    assert "derper" in data.get("services", {}), (
        "derp-vpn3/docker-compose.yml phai co service 'derper'"
    )


def test_derp_vpn3_expose_port_443_va_3478():
    compose = ROOT / "derp-vpn3" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    ports = data["services"]["derper"].get("ports", [])
    ports_str = " ".join(str(p) for p in ports)
    assert "443" in ports_str, "derper phai expose port 443 (DERP/HTTPS)"
    assert "3478" in ports_str, "derper phai expose port 3478/udp (STUN)"


# ---------- derp-vpn4 docker-compose ----------

def test_derp_vpn4_compose_ton_tai():
    compose = ROOT / "derp-vpn4" / "docker-compose.yml"
    assert compose.exists(), "derp-vpn4/docker-compose.yml phai ton tai"


def test_derp_vpn4_compose_co_derper_service():
    compose = ROOT / "derp-vpn4" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    assert "derper" in data.get("services", {}), (
        "derp-vpn4/docker-compose.yml phai co service 'derper'"
    )


def test_derp_vpn4_van_phuc_vu_443_nhung_qua_nginx():
    """Tu 2026-08-02 vpn4 chia se cong 443 voi CLIProxyAPI (vpn4 chi co MOT IP).

    nginx cua stack edge-vpn4 giu 443 va dinh tuyen theo SNI; derper VAN nghe :443
    ben trong container va van tu terminate TLS bang autocert cua no. Y dinh cu
    ("DERP phai den duoc qua 443") khong doi, chi doi ai la nguoi bind cong tren
    host. Chi tiet o test/test_edge_vpn4.py.
    """
    data = yaml.safe_load((ROOT / "derp-vpn4" / "docker-compose.yml").read_text())
    derper = data["services"]["derper"]
    ports = [str(p) for p in derper.get("ports", [])]

    assert not any(p.startswith("443:") for p in ports), (
        f"derper KHONG duoc publish 443 nua (nginx giu cong do): {ports}"
    )
    assert "3478:3478/udp" in ports, "derp-vpn4 phai expose 3478/udp (STUN) truc tiep"
    assert "80:80" in ports, "derper phai giu cong 80 cho ACME HTTP-01 cua chinh no"

    cmd_str = " ".join(str(c) for c in derper.get("command", []))
    assert "--a=:443" in cmd_str, "derper van phai nghe :443 ben trong container"

    edge = yaml.safe_load((ROOT / "edge-vpn4" / "docker-compose.yml").read_text())
    edge_ports = [str(p) for p in edge["services"]["nginx"].get("ports", [])]
    assert "443:443" in edge_ports, (
        "phai co nginx cua edge-vpn4 giu 443, neu khong DERP mat duong vao"
    )


def test_derp_vpn4_hostname_trong_compose():
    compose = ROOT / "derp-vpn4" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    cmd = data["services"]["derper"].get("command", [])
    cmd_str = " ".join(str(c) for c in cmd)
    assert "vpn4.hangocthanh.io.vn" in cmd_str, (
        "derp-vpn4 compose phai dung --hostname=vpn4.hangocthanh.io.vn"
    )


# ---------- ping-reporter network_mode (POST toi collector qua tailnet) ----------

def test_derp_vpn3_reporter_dung_netns_sidecar():
    """ping-reporter vpn3 phai chung netns voi sidecar de POST toi collector qua WireGuard."""
    compose = ROOT / "derp-vpn3" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    nm = data["services"]["ping-reporter"].get("network_mode")
    assert nm == "service:tailscale", (
        "ping-reporter vpn3 phai co network_mode: service:tailscale "
        "(neu khong se khong route duoc toi collector 100.64.0.1:8090 -> POST timeout)"
    )


import pytest


@pytest.mark.parametrize("compose_dir", ["derp-vpn4", "derp-vpn6"])
def test_stack_con_song_khong_con_ping_reporter(compose_dir):
    """Bat bien (2026-09-11): cac stack DANG CHAY (vpn4, vpn6) KHONG duoc khai
    ping-reporter nua.

    Ly do go:
      - no POST toi node tailnet 'collector' — node do chet tu 2026-08-02, moi
        chu ky TimeoutError 10s roi thu lai mai (log: 'POST collector ERR:
        TimeoutError', 'collector 100.64.0.1: FAIL');
      - viec cua no da do daemon tailscale_mod lam (metricsreport.go ->
        POST /api/metrics/report);
      - derp-vpn6 va relay-vpn6 tung khai TRUNG ten container
        'ping-reporter-vpn6' -> deploy-relay-vpn6 do moi lan merge.
    vpn3/vpn5 da retire nen khong nam trong danh sach nay.
    """
    compose = ROOT / compose_dir / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    services = data.get("services", {})
    assert "ping-reporter" not in services, (
        f"{compose_dir} van khai service ping-reporter — da go 2026-09-11, xem docstring"
    )
    names = [s.get("container_name", "") for s in services.values()]
    assert not any(n.startswith("ping-reporter") for n in names), (
        f"{compose_dir} van co container ten ping-reporter-*: {names}"
    )


# ---------- derp-vpn5 (DERP chuan, doi tu relay lai sang giong vpn4) ----------

def test_derp_vpn5_compose_ton_tai():
    compose = ROOT / "derp-vpn5" / "docker-compose.yml"
    assert compose.exists(), "derp-vpn5/docker-compose.yml phai ton tai"


def test_derp_vpn5_compose_co_derper_service():
    compose = ROOT / "derp-vpn5" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    assert "derper" in data.get("services", {}), (
        "derp-vpn5 phai co service 'derper' (DERP chuan, khong phai relay lai)"
    )


def test_derp_vpn5_expose_port_443_va_3478():
    compose = ROOT / "derp-vpn5" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    ports = data["services"]["derper"].get("ports", [])
    ports_str = " ".join(str(p) for p in ports)
    assert "443" in ports_str, "derp-vpn5 phai expose port 443 (DERP/HTTPS)"
    assert "3478" in ports_str, "derp-vpn5 phai expose port 3478/udp (STUN)"


def test_derp_vpn5_hostname_trong_compose():
    compose = ROOT / "derp-vpn5" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    cmd = data["services"]["derper"].get("command", [])
    cmd_str = " ".join(str(c) for c in cmd)
    assert "vpn5.hangocthanh.io.vn" in cmd_str, (
        "derp-vpn5 compose phai dung --hostname=vpn5.hangocthanh.io.vn"
    )


def test_derp_vpn5_reporter_dung_netns_sidecar():
    """ping-reporter vpn5 phai chung netns voi sidecar de POST toi collector qua WireGuard."""
    compose = ROOT / "derp-vpn5" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    nm = data["services"]["ping-reporter"].get("network_mode")
    assert nm == "service:tailscale", (
        "ping-reporter vpn5 phai co network_mode: service:tailscale"
    )


# Ghi chu: so luong region + trang thai retire cua vpn5-replay gio do DB
# derp_servers quan ly (khong con derp.yaml tinh de assert). Kiem tra tinh
# dung dan cua danh sach region thuc hien o tang dashboard/derp-backend.


# ---------- relay-vpn5 compose ----------

def test_relay_vpn5_compose_ton_tai():
    compose = ROOT / "relay-vpn5" / "docker-compose.yml"
    assert compose.exists(), "relay-vpn5/docker-compose.yml phai ton tai"


def test_relay_vpn5_compose_co_relay_va_tailscale():
    compose = ROOT / "relay-vpn5" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    svcs = data.get("services", {})
    assert "relay" in svcs, "relay-vpn5 compose phai co service 'relay'"
    assert "tailscale" in svcs, "relay-vpn5 compose phai co service 'tailscale' (sidecar)"


def test_relay_vpn5_expose_udp_41641():
    compose = ROOT / "relay-vpn5" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    ports = data["services"]["relay"].get("ports", [])
    ports_str = " ".join(str(p) for p in ports)
    assert "41641" in ports_str, "relay-vpn5 phai expose UDP 41641 (WireGuard outbound)"


def test_relay_vpn5_join_pangolin_network():
    compose = ROOT / "relay-vpn5" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    nets = data.get("networks", {})
    assert "pangolin_net" in nets, "relay-vpn5 phai join pangolin_net"
    assert nets["pangolin_net"].get("external") is True, (
        "pangolin_net phai la external network (cua Pangolin stack)"
    )


def test_relay_vpn5_dockerfile_ton_tai():
    assert (ROOT / "relay-vpn5" / "Dockerfile").exists(), (
        "relay-vpn5/Dockerfile phai ton tai"
    )


def test_relay_vpn5_go_mod_ton_tai():
    assert (ROOT / "relay-vpn5" / "go.mod").exists(), (
        "relay-vpn5/go.mod phai ton tai"
    )


# ---------- relay-vpn6 compose (co-host tren memory-stack) ----------
# Region 1003 (vpn6) hostname/ipv4/regionid gio do DB derp_servers quan ly,
# khong con assert tu derp.yaml tinh. Cac test duoi kiem tra cau truc compose.

def test_relay_vpn6_da_go_va_khong_con_auto_deploy():
    """Bat bien (2026-09-11): relay-vpn6 (hybrid relay cu) DA RETIRE.

    Tu 2026-09-05 vpn6 chay derper chuan (derp-vpn6); sslh route SNI vpn6 thang
    vao derper nen relay-vpn6 khong nhan duoc request nao tren 443. Van de that la
    deploy-relay-vpn6.yml tu DUNG LAI no sau MOI lan merge main (workflow_run CI).
    Go bang teardown-relay-vpn6.yml (chay tay). Test nay chan ca hai: thu muc stack
    va workflow auto-deploy khong duoc quay lai.
    """
    assert not (ROOT / "relay-vpn6" / "docker-compose.yml").exists(), (
        "relay-vpn6/docker-compose.yml da go 2026-09-11 — vpn6 dung derp-vpn6"
    )
    assert not (ROOT / ".github" / "workflows" / "deploy-relay-vpn6.yml").exists(), (
        "deploy-relay-vpn6.yml da go: no tu dung lai relay-vpn6 moi lan merge main"
    )
    assert (ROOT / ".github" / "workflows" / "teardown-relay-vpn6.yml").exists(), (
        "phai con teardown-relay-vpn6.yml de go container dang chay tren vpn6"
    )


# ---------- derp-vpn6 (DERP chuan giong vpn4, dung chung 443 qua sslh) ----------
# Nhanh vpn6-derper-sslh: vpn6 chuyen tu custom relay sang derper chuan.
# Khac vpn4: nghe noi bo :8443 (sslh route SNI vao), --http-port=-1 (cert TLS-ALPN-01).

def test_derp_vpn6_compose_ton_tai():
    compose = ROOT / "derp-vpn6" / "docker-compose.yml"
    assert compose.exists(), "derp-vpn6/docker-compose.yml phai ton tai"


def test_derp_vpn6_co_derper_service():
    compose = ROOT / "derp-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    assert "derper" in data.get("services", {}), (
        "derp-vpn6 phai co service 'derper' (DERP chuan, KHONG phai relay lai)"
    )


def test_derp_vpn6_nghe_noi_bo_8444():
    """Host chi publish 127.0.0.1:8444 (sslh route SNI vao); BEN TRONG container
    derper PHAI nghe :443 vi derper chi bat TLS/autocert khi dia chi nghe la cong
    443 (tsweb.IsProd443). Cau hinh --a=:8444 truoc day lam derper phuc vu
    plaintext, sslh forward TLS vao bi 'wrong version number' (2026-09-05)."""
    compose = ROOT / "derp-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    cmd_str = " ".join(str(c) for c in data["services"]["derper"].get("command", []))
    assert "--a=:443" in cmd_str, (
        "derper vpn6 phai nghe :443 TRONG container, neu khong derper khong bat TLS"
    )
    assert "--a=:8444" not in cmd_str, (
        "derper nghe :8444 se phuc vu plaintext (khong TLS) — sslh forward TLS vao se hong"
    )
    ports_str = " ".join(str(p) for p in data["services"]["derper"].get("ports", []))
    assert "127.0.0.1:8444:443" in ports_str, (
        "host phai publish 127.0.0.1:8444 -> container 443 (chi sslh tren host goi toi)"
    )
    assert "443:443" not in ports_str and " 443:" not in (" " + ports_str), (
        "derper vpn6 KHONG duoc chiem cong 443 cua host (sslh dang giu)"
    )
    assert "8443" not in ports_str, (
        "derper vpn6 KHONG duoc dung 8443 (Caddy memory-stack dang giu)"
    )


def test_derp_vpn6_http_port_tat():
    """--http-port=-1 -> cert qua TLS-ALPN-01, khong dung cong 80 (Caddy memory-stack giu)."""
    compose = ROOT / "derp-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    cmd_str = " ".join(str(c) for c in data["services"]["derper"].get("command", []))
    assert "--http-port=-1" in cmd_str, (
        "derper vpn6 phai dat --http-port=-1 (tat HTTP, cert qua TLS-ALPN-01)"
    )


def test_derp_vpn6_co_stun_3478():
    compose = ROOT / "derp-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    cmd_str = " ".join(str(c) for c in data["services"]["derper"].get("command", []))
    ports_str = " ".join(str(p) for p in data["services"]["derper"].get("ports", []))
    assert "--stun" in cmd_str, "derper vpn6 phai bat --stun"
    assert "3478" in ports_str, "derper vpn6 phai expose 3478/udp (STUN)"


def test_derp_vpn6_hostname_vpn6():
    compose = ROOT / "derp-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    cmd_str = " ".join(str(c) for c in data["services"]["derper"].get("command", []))
    assert "vpn6.hangocthanh.io.vn" in cmd_str, (
        "derp-vpn6 compose phai dung --hostname=vpn6.hangocthanh.io.vn"
    )


def test_derp_vpn6_khong_dung_lai_sidecar_tailscale():
    """derp-vpn6 va relay-vpn6 deu tung khai container 'ts-vpn6'.

    Sua moi relay-vpn6 la chua du: ai chay deploy-derp-vpn6.yml (workflow_dispatch)
    sau nay se dung LAI mot node trung hostname 'vpn6', tranh socket voi node native
    tren host va an IP ghim 100.64.0.7.
    """
    compose = ROOT / "derp-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    assert "tailscale" not in data.get("services", {}), (
        "derp-vpn6 KHONG duoc khai sidecar 'tailscale' nua — node vpn6 chay native tren host"
    )


def test_derp_vpn6_readme_huong_dan_sslh():
    """README phai mo ta rule sslh SNI -> derper noi bo (huong dan cutover mai)."""
    readme = ROOT / "derp-vpn6" / "README.md"
    assert readme.exists(), "derp-vpn6/README.md phai ton tai"
    txt = readme.read_text(encoding="utf-8").lower()
    assert "sslh" in txt and "sni" in txt, "README phai noi ve sslh + SNI"
    assert "8444" in txt, "README phai noi port noi bo derper 8444"


def test_deploy_derp_vpn6_workflow_dispatch_only():
    """Workflow deploy vpn6 CHI workflow_dispatch (box prod, khong auto-deploy)."""
    wf = ROOT / ".github" / "workflows" / "deploy-derp-vpn6.yml"
    assert wf.exists(), "deploy-derp-vpn6.yml phai ton tai"
    data = yaml.safe_load(wf.read_text())
    # YAML 1.1: key 'on' co the parse thanh True -> thu ca hai.
    on_block = data.get("on", data.get(True))
    assert on_block is not None, "workflow phai co block 'on'"
    assert "workflow_dispatch" in on_block, "phai co workflow_dispatch"
    assert "push" not in on_block, "KHONG duoc auto-deploy khi push"
    assert "schedule" not in on_block, "KHONG duoc auto-deploy theo schedule"


def test_relay_code_go_van_giu_khong_xoa():
    """Yeu cau nguoi dung (2026-09-05): KHONG xoa code relay tcp/udp khi them derper vpn6.

    Cap nhat 2026-09-11: nguoi dung DUYET go stack relay-vpn6 (compose + caddy +
    auto-deploy) vi no khong con nhan request nao va tu dung lai moi lan merge —
    xem test_relay_vpn6_da_go_va_khong_con_auto_deploy. Phan con giu la CODE Go
    goc cua relay (relay-vpn5/), dung lai duoc neu can dung lai.
    """
    assert (ROOT / "relay-vpn5" / "server.go").exists(), (
        "relay-vpn5/server.go (code mix tcp/udp) phai VAN con — khong duoc xoa"
    )
