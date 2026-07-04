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


def test_headscale_co_2_region_de_failover():
    """
    Khi 1 region chet, client phai co region du phong.
    - Region 999 (embedded vpn2): tu dong them boi automatically_add_embedded_derp_region
    - Cac region DONG (1000+): tu derp-backend (DB Postgres) qua derp.urls
    -> Tong >= 2 region -> failover tu dong (tailscale tu chuyen ~5-15s).
    """
    cfg = load_hs()
    derp = cfg.get("derp", {})
    derp_srv = derp.get("server", {})
    auto_embedded = derp_srv.get("automatically_add_embedded_derp_region", False)
    urls = derp.get("urls", [])

    has_embedded = auto_embedded and derp_srv.get("enabled", False)
    has_external = any("derpmap.json" in u for u in urls)

    assert has_embedded and has_external, (
        "Can 2 nguon DERP de failover: "
        f"embedded={'ON' if has_embedded else 'OFF'} (region 999, vpn2), "
        f"external={'ON' if has_external else 'OFF'} (region dong qua derp-backend/derp.urls)"
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


def test_derp_vpn4_expose_port_443_va_3478():
    compose = ROOT / "derp-vpn4" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    ports = data["services"]["derper"].get("ports", [])
    ports_str = " ".join(str(p) for p in ports)
    assert "443" in ports_str, "derp-vpn4 phai expose port 443 (DERP/HTTPS)"
    assert "3478" in ports_str, "derp-vpn4 phai expose port 3478/udp (STUN)"


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


def test_derp_vpn4_reporter_dung_netns_sidecar():
    """ping-reporter vpn4 phai chung netns voi sidecar de POST toi collector qua WireGuard."""
    compose = ROOT / "derp-vpn4" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    nm = data["services"]["ping-reporter"].get("network_mode")
    assert nm == "service:tailscale", (
        "ping-reporter vpn4 phai co network_mode: service:tailscale "
        "(neu khong se khong route duoc toi collector 100.64.0.1:8090 -> POST timeout)"
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

def test_relay_vpn6_compose_ton_tai():
    compose = ROOT / "relay-vpn6" / "docker-compose.yml"
    assert compose.exists(), "relay-vpn6/docker-compose.yml phai ton tai"


def test_relay_vpn6_compose_co_relay_va_tailscale():
    compose = ROOT / "relay-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    svcs = data.get("services", {})
    assert "relay" in svcs, "relay-vpn6 compose phai co service 'relay'"
    assert "tailscale" in svcs, "relay-vpn6 compose phai co service 'tailscale' (sidecar)"


def test_relay_vpn6_build_tu_relay_vpn5():
    """relay-vpn6 tai dung code Go cua relay-vpn5 (build context ../relay-vpn5)."""
    compose = ROOT / "relay-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    ctx = data["services"]["relay"].get("build", {}).get("context", "")
    assert "relay-vpn5" in ctx, "relay-vpn6 phai build tu ../relay-vpn5 (tai dung code Go)"


def test_relay_vpn6_expose_udp_41641():
    compose = ROOT / "relay-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    ports = data["services"]["relay"].get("ports", [])
    ports_str = " ".join(str(p) for p in ports)
    assert "41641" in ports_str, "relay-vpn6 phai expose UDP 41641 (WireGuard)"


def test_relay_vpn6_join_memnet_external():
    """relay-vpn6 phai join network memory-stack_memnet (de Caddy goi duoc)."""
    compose = ROOT / "relay-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    nets = data.get("networks", {})
    assert "memnet" in nets, "relay-vpn6 phai khai bao network 'memnet'"
    assert nets["memnet"].get("external") is True, "memnet phai la external"
    assert nets["memnet"].get("name") == "memory-stack_memnet", (
        "memnet phai tro toi network memory-stack_memnet (cua memory-caddy)"
    )


def test_relay_vpn6_reporter_dung_netns_sidecar():
    """ping-reporter vpn6 phai chung netns sidecar de POST toi collector qua WireGuard."""
    compose = ROOT / "relay-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    nm = data["services"]["ping-reporter"].get("network_mode")
    assert nm == "service:tailscale", (
        "ping-reporter vpn6 phai co network_mode: service:tailscale"
    )


def test_relay_vpn6_caddy_snippet_ton_tai():
    """Snippet Caddy cho vpn6 phai ton tai va tro toi relay-vpn6:8080."""
    snippet = ROOT / "relay-vpn6" / "caddy-vpn6.caddy"
    assert snippet.exists(), "relay-vpn6/caddy-vpn6.caddy phai ton tai"
    txt = snippet.read_text()
    assert "vpn6.hangocthanh.io.vn" in txt, "snippet phai co domain vpn6"
    assert "relay-vpn6:8080" in txt, "snippet phai reverse_proxy toi relay-vpn6:8080"


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
    """derper vpn6 nghe :8444 va CHI bind localhost (8443 = Caddy; sslh route SNI vao)."""
    compose = ROOT / "derp-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    cmd_str = " ".join(str(c) for c in data["services"]["derper"].get("command", []))
    assert "--a=:8444" in cmd_str, "derper vpn6 phai nghe :8444 (8443 da la Caddy)"
    ports_str = " ".join(str(p) for p in data["services"]["derper"].get("ports", []))
    assert "127.0.0.1:8444:8444" in ports_str, (
        "derper vpn6 phai bind 127.0.0.1:8444 (chi sslh tren host goi toi)"
    )
    assert "443:443" not in ports_str, (
        "derper vpn6 KHONG duoc chiem cong 443 (sslh dang giu)"
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


def test_derp_vpn6_reporter_netns_sidecar():
    compose = ROOT / "derp-vpn6" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    nm = data["services"]["ping-reporter"].get("network_mode")
    assert nm == "service:tailscale", (
        "ping-reporter vpn6 phai co network_mode: service:tailscale"
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


def test_relay_vpn6_code_van_giu_khong_xoa():
    """Yeu cau nguoi dung: KHONG xoa code relay tcp/udp khi them derper vpn6."""
    assert (ROOT / "relay-vpn5" / "server.go").exists(), (
        "relay-vpn5/server.go (code mix tcp/udp) phai VAN con — khong duoc xoa"
    )
    assert (ROOT / "relay-vpn6" / "docker-compose.yml").exists(), (
        "relay-vpn6/docker-compose.yml phai VAN con — khong duoc xoa"
    )
