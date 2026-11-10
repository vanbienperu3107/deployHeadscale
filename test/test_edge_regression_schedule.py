import pathlib

import yaml

ROOT = pathlib.Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "edge-regression.yml"


def load():
    assert WORKFLOW.exists(), "edge-regression.yml must exist"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")), WORKFLOW.read_text(encoding="utf-8")


def test_runs_every_six_hours_and_on_demand():
    data, _ = load()
    triggers = data.get("on", data.get(True))
    crons = [item["cron"] for item in triggers["schedule"]]
    assert crons == ["17 */6 * * *"]
    assert "workflow_dispatch" in triggers


def test_is_read_only_and_serialized_with_host_jobs():
    data, _ = load()
    assert data["permissions"] == {"contents": "read", "issues": "write"}
    assert data["concurrency"]["group"] == "deploy-vpn4-host"
    assert data["concurrency"]["cancel-in-progress"] is False


def test_checks_every_public_route_without_ssh_or_secrets_in_output():
    _, body = load()
    for marker in (
        "https://vpn4.hangocthanh.io.vn/derp/probe",
        "https://cliproxy.hangocthanh.io.vn/v1/models",
        "https://opencode.hangocthanh.io.vn/global/health",
        "https://opencode2.hangocthanh.io.vn/api/info",
    ):
        assert marker in body, marker
    assert "appleboy/ssh-action" not in body
    # The key may enter via env only; it must never be echoed or put on argv as text.
    assert "echo" not in "".join(line for line in body.splitlines() if "CLIPROXY_PROBE_KEY" in line)
    assert "echo \"${CLIPROXY_PROBE_KEY}" not in body and "echo $CLIPROXY_PROBE_KEY" not in body
    assert "set -x" not in body


def test_failure_is_reported_as_an_issue_not_silently_ignored():
    _, body = load()
    assert "::error::" in body
    assert "gh issue create" in body
