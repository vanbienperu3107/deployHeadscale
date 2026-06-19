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


def test_vpn3_co_trong_derp_map():
    """Dam bao vpn3.hangocthanh.io.vn duoc dang ky lam DERP relay (preferred region)."""
    hostnames = [
        node["hostname"]
        for region in load_derp()["regions"].values()
        for node in region["nodes"]
    ]
    assert "vpn3.hangocthanh.io.vn" in hostnames, (
        "vpn3.hangocthanh.io.vn phai co trong config/derp.yaml"
    )


def test_vpn3_ip_dung():
    for region in load_derp()["regions"].values():
        for node in region["nodes"]:
            if node["hostname"] == "vpn3.hangocthanh.io.vn":
                assert node.get("ipv4") == "149.104.66.159", (
                    "ipv4 cua vpn3 phai la 149.104.66.159"
                )


# ---------- headscale config: failover setup ----------

def test_headscale_config_co_derp_paths():
    """config.yaml phai chi toi derp.yaml de headscale tai region vpn3."""
    cfg = load_hs()
    paths = cfg.get("derp", {}).get("paths", [])
    assert len(paths) >= 1, (
        "config.yaml: derp.paths phai co it nhat 1 path (tro toi derp.yaml)"
    )


def test_headscale_co_2_region_de_failover():
    """
    Khi 1 region chet, client phai co region du phong.
    Ca 2 region (vpn3 preferred + vpn2 backup) phai co trong derp.yaml.
    automatically_add_embedded_derp_region phai False (vpn2 da them thu cong).
    """
    d = load_derp()
    assert len(d["regions"]) >= 2, (
        f"derp.yaml phai co >= 2 region de failover (hien co {len(d['regions'])})"
    )
    cfg = load_hs()
    auto = cfg.get("derp", {}).get("server", {}).get("automatically_add_embedded_derp_region", True)
    assert not auto, (
        "automatically_add_embedded_derp_region phai False (vpn2 da trong derp.yaml, tranh them 2 lan)"
    )


def test_vpn3_la_preferred_vpn2_la_backup():
    """vpn3 phai la preferred (avoid=False), vpn2 phai la backup (avoid=True)."""
    d = load_derp()
    vpn3_region = next(
        (r for r in d["regions"].values()
         if any("vpn3" in n["hostname"] for n in r["nodes"])), None)
    vpn2_region = next(
        (r for r in d["regions"].values()
         if any("vpn2" in n["hostname"] for n in r["nodes"])), None)

    assert vpn3_region is not None, "Khong tim thay region chua vpn3.hangocthanh.io.vn"
    assert vpn2_region is not None, "Khong tim thay region chua vpn2.hangocthanh.io.vn"
    assert not vpn3_region.get("avoid", False), (
        "vpn3 phai la preferred (avoid phai False hoac bo trong)"
    )
    assert vpn2_region.get("avoid") is True, (
        "vpn2 phai la backup (avoid phai True)"
    )


def test_headscale_khong_dung_derp_tailscale_com():
    """Full self-host: phai tat URLs cua Tailscale Inc."""
    cfg = load_hs()
    urls = cfg.get("derp", {}).get("urls", [])
    assert urls == [], f"derp.urls phai rong (full self-host). Hien tai: {urls}"


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
