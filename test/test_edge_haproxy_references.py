import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
SCANNED = [
    ".github/workflows/diag-opencode.yml",
    ".github/workflows/survey-docker-vpn4.yml",
    "test/mutation_survey_vpn4.py",
    "portainer-vpn4/docker-compose.yml",
    "edge-vpn4/README.md",
]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_live_reference_to_retired_nginx_container():
    for rel in SCANNED:
        body = read(rel)
        assert not re.search(r"edge-nginx|nginx -T", body), f"{rel} still references retired nginx edge"


def test_survey_reads_running_haproxy_config_not_nginx():
    body = read(".github/workflows/survey-docker-vpn4.yml")
    assert "edge-haproxy" in body
    assert "haproxy -v" in body
