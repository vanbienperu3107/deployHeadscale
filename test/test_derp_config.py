"""Validate cau truc config/derp.yaml va failover setup - chay trong CI truoc deploy."""
import pathlib
import yaml
import pytest

ROOT = pathlib.Path(__file__).parent.parent
DERP_MAP = ROOT / "config" / "derp.yaml"
HS_CONFIG = ROOT / "config" / "config.yaml"


def load_derp():
    return yaml.safe_load(DERP_MAP.read_text())


def load_hs():
    return yaml.safe_load(HS_CONFIG.read_text())


# ---------- derp.yaml structure ----------

def test_derp_yaml_ton_tai():
    assert DERP_MAP.exists(), "config/derp.yaml phai ton tai"


def test_derp_yaml_co_regions():
    d = load_derp()
    assert "regions" in d, "derp.yaml phai co truong 'regions'"
    assert len(d["regions"]) >= 1, "phai co it nhat 1 region trong derp.yaml"


def test_moi_region_co_truong_bat_buoc():
    for rid, region in load_derp()["regions"].items():
        assert "regionid" in region, f"region {rid}: thieu 'regionid'"
        assert "regioncode" in region, f"region {rid}: thieu 'regioncode'"
        assert "regionname" in region, f"region {rid}: thieu 'regionname'"
        assert "nodes" in region and len(region["nodes"]) >= 1, f"region {rid}: phai co nodes"


def test_moi_node_co_hostname_va_port():
    for rid, region in load_derp()["regions"].items():
        for node in region["nodes"]:
            assert "hostname" in node, f"region {rid}: node thieu 'hostname'"
            assert node.get("derpport") == 443, f"region {rid}: derpport phai la 443 (TLS)"
            assert node.get("stunport") == 3478, f"region {rid}: stunport phai la 3478"


def test_vpn4_co_trong_derp_map():
    """Dam bao vpn4.hangocthanh.io.vn duoc dang ky lam DERP relay."""
    hostnames = [
        node["hostname"]
        for region in load_derp()["regions"].values()
        for node in region["nodes"]
    ]
    assert "vpn4.hangocthanh.io.vn" in hostnames, (
        "vpn4.hangocthanh.io.vn phai co trong config/derp.yaml"
    )


def test_vpn4_ip_dung():
    for region in load_derp()["regions"].values():
        for node in region["nodes"]:
            if node["hostname"] == "vpn4.hangocthanh.io.vn":
                assert node.get("ipv4") == "149.104.66.174", (
                    "ipv4 cua vpn4 phai la 149.104.66.174"
                )


# ---------- headscale config: failover setup ----------

def test_headscale_config_co_derp_paths():
    """config.yaml phai chi toi derp.yaml de headscale tai region vpn4/vpn5."""
    cfg = load_hs()
    paths = cfg.get("derp", {}).get("paths", [])
    assert len(paths) >= 1, (
        "config.yaml: derp.paths phai co it nhat 1 path (tro toi derp.yaml)"
    )


def test_headscale_co_2_region_de_failover():
    """
    Khi 1 region chet, client phai co region du phong.
    - Region 999 (embedded vpn2): tu dong them boi automatically_add_embedded_derp_region
    - Region 1001+ (vpn4/vpn5): tu config/derp.yaml qua derp.paths
    -> Tong >= 2 region -> failover tu dong (tailscale tu chuyen ~5-15s).
    """
    cfg = load_hs()
    derp_srv = cfg.get("derp", {}).get("server", {})
    auto_embedded = derp_srv.get("automatically_add_embedded_derp_region", False)
    paths = cfg.get("derp", {}).get("paths", [])

    has_embedded = auto_embedded and derp_srv.get("enabled", False)
    has_external = len(paths) >= 1

    assert has_embedded and has_external, (
        "Can 2 DERP region de failover: "
        f"embedded={'ON' if has_embedded else 'OFF'} (region 999, vpn2), "
        f"external={'ON' if has_external else 'OFF'} (vpn4/vpn5 qua derp.paths)"
    )


def test_headscale_khong_dung_derp_tailscale_com():
    """Full self-host: phai tat URLs cua Tailscale Inc."""
    cfg = load_hs()
    urls = cfg.get("derp", {}).get("urls", [])
    assert urls == [], f"derp.urls phai rong (full self-host). Hien tai: {urls}"


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


def test_ping_reporter_vpn4_trong_netns_tailscale():
    """
    ping-reporter PHAI chay trong netns cua tailscale (network_mode: service:tailscale).
    Neu khong co, TCP connect toi collector_ip:8090 qua WireGuard se fail voi
    OSError(113, 'No route to host') - da xac nhan qua diag run 27821574015.
    """
    compose = ROOT / "derp-vpn4" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    pr = data["services"].get("ping-reporter", {})
    network_mode = pr.get("network_mode", "")
    assert "tailscale" in network_mode, (
        "ping-reporter trong derp-vpn4/docker-compose.yml PHAI co "
        "network_mode: 'service:tailscale' de reach collector:8090 qua WireGuard. "
        "Khong co -> POST metrics/report fail OSError(113, 'No route to host')."
    )


def test_derp_co_2_region_total():
    """3 DERP regions (999 embedded + 1001 vpn4 + 1002 vpn5) -> failover tot."""
    d = load_derp()
    assert len(d["regions"]) >= 2, (
        "config/derp.yaml phai co it nhat 2 region ngoai (+ embedded 999 = 3 tong)"
    )


# ---------- region 1002 (vpn5 hybrid relay) ----------

def test_vpn5_co_trong_derp_map():
    """Dam bao vpn5.hangocthanh.io.vn (hybrid relay) duoc dang ky."""
    hostnames = [
        node["hostname"]
        for region in load_derp()["regions"].values()
        for node in region["nodes"]
    ]
    assert "vpn5.hangocthanh.io.vn" in hostnames, (
        "vpn5.hangocthanh.io.vn phai co trong config/derp.yaml (region 1002)"
    )


def test_vpn5_ip_va_port_dung():
    for region in load_derp()["regions"].values():
        for node in region["nodes"]:
            if node["hostname"] == "vpn5.hangocthanh.io.vn":
                assert node.get("ipv4") == "204.199.161.89", (
                    "ipv4 cua vpn5 phai la 204.199.161.89"
                )
                assert node.get("derpport") == 443, "vpn5 derpport phai la 443"


def test_vpn5_region_id_la_1002():
    d = load_derp()
    assert 1002 in d["regions"], "region 1002 phai ton tai (vpn5)"
    assert d["regions"][1002]["regionid"] == 1002


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


# ---------- relay-vpn4 compose (hybrid relay thay the derp-vpn4) ----------

def test_relay_vpn4_compose_ton_tai():
    compose = ROOT / "relay-vpn4" / "docker-compose.yml"
    assert compose.exists(), "relay-vpn4/docker-compose.yml phai ton tai"


def test_relay_vpn4_compose_co_relay_va_tailscale():
    compose = ROOT / "relay-vpn4" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    svcs = data.get("services", {})
    assert "relay" in svcs, "relay-vpn4 compose phai co service 'relay'"
    assert "tailscale" in svcs, "relay-vpn4 compose phai co service 'tailscale' (sidecar)"


def test_relay_vpn4_expose_udp_41641():
    compose = ROOT / "relay-vpn4" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    ports = data["services"]["relay"].get("ports", [])
    ports_str = " ".join(str(p) for p in ports)
    assert "41641" in ports_str, "relay-vpn4 phai expose UDP 41641 (WireGuard outbound)"


def test_relay_vpn4_co_caddy_tls():
    """vpn4 khong co Pangolin — dung Caddy tu xu ly TLS thay Traefik."""
    compose = ROOT / "relay-vpn4" / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text())
    svcs = data.get("services", {})
    assert "caddy" in svcs, (
        "relay-vpn4 compose phai co service 'caddy' (TLS termination, thay the Traefik)"
    )
    ports = svcs["caddy"].get("ports", [])
    ports_str = " ".join(str(p) for p in ports)
    assert "443" in ports_str, "caddy phai expose port 443"


def test_relay_vpn4_dockerfile_ton_tai():
    assert (ROOT / "relay-vpn4" / "Dockerfile").exists(), (
        "relay-vpn4/Dockerfile phai ton tai"
    )


def test_relay_vpn4_go_mod_ton_tai():
    assert (ROOT / "relay-vpn4" / "go.mod").exists(), (
        "relay-vpn4/go.mod phai ton tai"
    )
