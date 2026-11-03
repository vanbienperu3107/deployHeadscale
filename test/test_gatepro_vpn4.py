"""Contract cho workflow deploy GatePro (API vpn4, DB rieng tren vpn6, tailnet-only)."""

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-gatepro-vpn4.yml"


def load():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def ssh_steps():
    return [s for s in load()["jobs"]["deploy"]["steps"] if "ssh-action" in str(s.get("uses", ""))]


def script_for(host_secret):
    found = [s for s in ssh_steps() if host_secret in s["with"]["host"]]
    assert len(found) == 1
    return found[0]


def test_manual_and_serialized_with_vpn4_host():
    wf = load()
    assert set(wf.get("on", wf.get(True))) == {"workflow_dispatch"}
    assert wf["concurrency"] == {"group": "deploy-vpn4-host", "cancel-in-progress": False}


def test_vpn6_only_creates_isolated_role_and_database():
    s = script_for("SSH_HOST_VPN6")["with"]["script"]
    assert "CREATE ROLE gatepro LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE" in s
    assert "CREATE DATABASE gatepro OWNER gatepro" in s
    assert "truefalsefalsefalse" in s, "phai tu choi role gatepro co quyen bat thuong"
    assert 'test "$OWNER" = "gatepro"' in s
    assert not re.search(r"(?i)\b(DROP|GRANT)\s+(DATABASE|ALL|CONNECT|USAGE|SELECT|INSERT|UPDATE|DELETE)\b", s)
    for shared in ("derp", "headscale", "opencode_remote"):
        assert not re.search(rf"(?i)(ALTER|CREATE)\s+DATABASE\s+{shared}\b", s)


def test_schema_only_from_image_and_no_monitor():
    s = script_for("SSH_HOST_VPN4")["with"]["script"]
    assert "gatepro db init" in s
    assert '"serve", "--with-monitor"' in s
    assert "[monitor\\\\] started" in s or "monitor started" in s
    assert "CREATE TABLE" not in s


def test_api_binds_only_tailnet_and_is_verified():
    s = script_for("SSH_HOST_VPN4")["with"]["script"]
    assert "VPN4_TS_IP=$(tailscale ip -4" in s
    assert "docker exec ts-vpn4 tailscale ip -4" in s
    assert '$VPN4_TS_IP:8080:8080' in s
    assert '$VPN4_TS_IP:5433:5432' in s
    assert not re.search(r'["\[ ](0\.0\.0\.0:)?8080:8080', s.replace("$VPN4_TS_IP:8080:8080", ""))
    assert 'test "$BIND" = "$VPN4_TS_IP:8080 "' in s
    assert 'test "$LISTEN" = "$VPN4_TS_IP:8080 "' in s
    assert 'test "$NOAUTH" = "401"' in s
    for public in ("ufw allow", "Caddyfile", "nginx", "iptables -A", "iptables -I", "nft add"):
        assert public not in s


def test_secrets_via_env_never_printed_or_baked():
    body = WORKFLOW.read_text(encoding="utf-8")
    for step in ssh_steps():
        assert "${{ secrets." not in step["with"]["script"]
        assert "set -x" not in step["with"]["script"]
    s = script_for("SSH_HOST_VPN4")["with"]["script"]
    for secret in ("GATEPRO_DB_PASSWORD", "GATEPRO_DB_SECRET_KEY", "GATEPRO_API_PASSWORD"):
        assert secret in script_for("SSH_HOST_VPN4")["with"]["envs"]
        assert f'echo "${secret}"' not in body
        assert not re.search(rf"--build-arg[^\n]*{secret}", s)
    assert "umask 077" in s and "chmod 600 db.env" in s


def test_rollback_is_scoped_and_keeps_data():
    s = script_for("SSH_HOST_VPN4")["with"]["script"]
    assert "--project-name gatepro-vpn4" in s
    assert "trap " in s and "cleanup_gatepro_failure" in s
    assert not re.search(r"down[^\n]*(-v\b|--volumes)", s)
    assert "volume rm" not in s and "system prune" not in s
    assert "snapshot_unrelated_workloads > before.snap" in s
    assert "cmp -s before.snap after.snap" in s
