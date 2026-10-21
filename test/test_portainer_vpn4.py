from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PORTAINER_COMPOSE = ROOT / "portainer-vpn4" / "docker-compose.yml"
INTEGRATION = ROOT / "test" / "portainer_vpn4_integration.sh"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-portainer-vpn4.yml"
ROLLBACK_WORKFLOW = ROOT / ".github" / "workflows" / "rollback-portainer-vpn4.yml"


def load_portainer_compose():
    """Load the Task 1 service contract from its Compose file."""
    assert PORTAINER_COMPOSE.exists(), "portainer-vpn4/docker-compose.yml phai ton tai"
    data = yaml.safe_load(PORTAINER_COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "Compose phai la mot YAML mapping"
    return data


def test_portainer_compose_exists_and_is_valid_yaml():
    compose = load_portainer_compose()
    assert isinstance(compose.get("services"), dict)
    assert set(compose["services"]) == {"portainer"}, (
        "Stack quan tri Docker nay chi duoc co service portainer; them service "
        "thu hai co the mo port/privileged mount hoac vuot security contract."
    )


def test_portainer_service_is_private_and_persistent():
    service = load_portainer_compose()["services"]["portainer"]

    assert service["image"] == "portainer/portainer-ce:lts"
    assert service["command"] == ["--http-enabled"]
    assert service["container_name"] == "portainer"
    assert service["restart"] == "unless-stopped"
    assert service["mem_limit"] == "256m"
    assert not service.get("ports")
    assert service["volumes"] == [
        "/var/run/docker.sock:/var/run/docker.sock",
        "portainer_data:/data",
    ]


def test_portainer_uses_only_the_external_edge_network():
    compose = load_portainer_compose()
    service = compose["services"]["portainer"]

    assert service["networks"] == ["edge"]
    assert compose["networks"] == {"edge": {"external": True, "name": "edge"}}


def test_portainer_declares_its_named_data_volume():
    compose = load_portainer_compose()
    assert compose["volumes"] == {"portainer_data": None}


def test_portainer_does_not_declare_an_unsupported_image_healthcheck():
    """Portainer LTS does not document an in-image HTTP probe utility.

    A `CMD-SHELL curl ...` or guessed Portainer CLI flag would report a false
    health state. Readiness is instead verified by the deploy workflow through
    the publicly terminated TLS route and Portainer's `/api/status` endpoint.
    """
    service = load_portainer_compose()["services"]["portainer"]
    assert "healthcheck" not in service


def test_portainer_uses_existing_json_log_rotation_convention():
    logging = load_portainer_compose()["services"]["portainer"]["logging"]
    assert logging == {
        "driver": "json-file",
        "options": {"max-size": "10m", "max-file": "3"},
    }


def test_integration_harness_generates_a_valid_unique_resource_suffix():
    """Bash parses `${$}` but fails it at runtime as a bad substitution.

    The harness creates disposable Docker resource names from this value. It
    must use Bash's process identifier `$$`, not invalid `${$}` or `$-`.
    """
    body = INTEGRATION.read_text(encoding="utf-8")
    assert 'SUFFIX="${$}-${RANDOM}"' not in body
    assert 'SUFFIX="$$-${RANDOM}"' in body


def test_integration_harness_does_not_leak_caddy_anonymous_volumes():
    """Caddy images declare /data and /config volumes by default.

    Removing the three disposable Caddy containers without `-v` would leave
    anonymous volumes on every local/CI integration run. The harness does not
    need persistence, so each Caddy stub must override both paths with tmpfs.
    """
    body = INTEGRATION.read_text(encoding="utf-8")
    assert body.count("--tmpfs /data:rw,noexec,nosuid,size=16m") == 3
    assert body.count("--tmpfs /config:rw,noexec,nosuid,size=16m") == 3


def load_deploy_workflow():
    """Load the Task 4 production deploy contract.

    A workflow that omits this file cannot accidentally be treated as a safe
    replacement for the explicit, manually approved deployment procedure.
    """
    assert DEPLOY_WORKFLOW.exists(), "deploy-portainer-vpn4.yml phai ton tai"
    data = yaml.safe_load(DEPLOY_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "deploy workflow phai la mot YAML mapping"
    return data


def deploy_body():
    load_deploy_workflow()
    return DEPLOY_WORKFLOW.read_text(encoding="utf-8")


def test_deploy_workflow_is_manual_and_serialized():
    workflow = load_deploy_workflow()
    # PyYAML 1.1 parses the YAML key `on` as True, while GitHub parses it as
    # the string key. Accept only the single GitHub trigger in either view.
    triggers = workflow.get("on", workflow.get(True))

    assert triggers == {"workflow_dispatch": None}
    assert workflow["concurrency"] == {
        "group": "deploy-vpn4-host",
        "cancel-in-progress": False,
    }


def test_deploy_preflight_validates_dns_secrets_and_candidate_configs_before_ssh_changes():
    workflow = load_deploy_workflow()
    body = deploy_body()
    steps = workflow["jobs"]["deploy"]["steps"]
    ssh_index = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("appleboy/ssh-action")
    )
    dns_index = next(
        index
        for index, step in enumerate(steps)
        if "DNS" in step["name"]
    )

    assert dns_index < ssh_index, "DNS phai duoc kiem tra truoc khi SSH vao vpn4"
    assert "portainer.hangocthanh.io.vn" in steps[dns_index]["run"]
    assert "SSH_HOST" in steps[dns_index]["run"]
    assert "SSH_HOST_VPN4" in body
    for secret in ("SSH_HOST_VPN4", "SSH_USER", "SSH_KEY", "DEPLOY_PATH"):
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in body
    assert "sudo -n" in body
    ssh_step = steps[ssh_index]
    assert ssh_step["env"] == {
        "DEPLOY_PATH": "${{ secrets.DEPLOY_PATH }}",
        "DEPLOY_REF": "${{ github.ref_name }}",
    }
    assert 'git fetch origin "$DEPLOY_REF:refs/remotes/origin/$DEPLOY_REF"' in body
    assert 'git reset --hard "origin/$DEPLOY_REF"' in body
    assert "OLD_SHA=" in body and "NEW_SHA=" in body
    assert "nginx:1.27-alpine nginx -t" in body
    assert "caddy:2.8-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile" in body
    assert "docker compose -f \"$DEPLOY_PATH/portainer-vpn4/docker-compose.yml\" config --quiet" in body


def test_deploy_only_recreates_the_two_affected_edge_services_and_preserves_data():
    body = deploy_body()
    caddy_recreate = (
        'docker compose -f "$DEPLOY_PATH/edge-vpn4/docker-compose.yml" '
        "up -d --force-recreate --no-deps caddy-edge"
    )
    nginx_recreate = (
        'docker compose -f "$DEPLOY_PATH/edge-vpn4/docker-compose.yml" '
        "up -d --force-recreate --no-deps nginx"
    )

    assert caddy_recreate in body
    assert nginx_recreate in body
    assert body.index(caddy_recreate) < body.index(nginx_recreate)
    assert body.index("nginx:1.27-alpine nginx -t") < body.index(nginx_recreate)
    assert "docker compose -f \"$DEPLOY_PATH/portainer-vpn4/docker-compose.yml\" pull portainer" in body
    assert "docker compose -f \"$DEPLOY_PATH/portainer-vpn4/docker-compose.yml\" up -d --remove-orphans portainer" in body
    assert "docker compose -f \"$DEPLOY_PATH/edge-vpn4/docker-compose.yml\" up -d --remove-orphans" not in body
    for forbidden in ("docker compose down -v", "docker volume rm", "docker system prune", "docker volume prune"):
        assert forbidden not in body
    assert "portainer_data" not in body
    for unrelated in ("derper", "cliproxy", "opencode", "fail2ban"):
        assert f"--no-deps {unrelated}" not in body


def test_deploy_snapshots_unrelated_containers_before_and_after_the_change():
    body = deploy_body()

    assert "SNAPSHOT_BEFORE=" in body
    assert "SNAPSHOT_AFTER=" in body
    assert "RestartCount" in body
    assert "StartedAt" in body
    assert '"$container" = "portainer"' in body
    assert "cmp -s \"$SNAPSHOT_BEFORE\" \"$SNAPSHOT_AFTER\"" in body
    assert "diff -u \"$SNAPSHOT_BEFORE\" \"$SNAPSHOT_AFTER\"" in body
    assert body.index("SNAPSHOT_BEFORE=") < body.index("pull portainer")
    assert body.index('snapshot_non_portainer | $SUDO tee "$SNAPSHOT_AFTER" >/dev/null') > body.index(
        "up -d --force-recreate --no-deps nginx"
    )


def test_deploy_verifies_public_tls_isolation_and_existing_routes_after_edge_activation():
    body = deploy_body()

    status_url = "https://portainer.hangocthanh.io.vn/api/status"
    assert status_url in body
    assert "-k" not in body
    assert '"$STATUS_CODE" != "200"' in body
    assert 'test -s "$STATUS_BODY"' in body
    assert body.index(status_url) > body.index("up -d --force-recreate --no-deps nginx")
    assert "8000|9000|9443" in body
    assert "HostConfig.PortBindings" in body
    assert "NetworkSettings.Networks.edge" in body
    assert "RepoDigests" in body
    assert "https://vpn4.hangocthanh.io.vn/derp/probe" in body
    assert "https://cliproxy.hangocthanh.io.vn/v1/models" in body
    assert "https://opencode.hangocthanh.io.vn/global/health" in body
    assert "Authorization:" not in body
    assert '"$DERP_CODE" != "200"' in body
    assert 'case "$CLIPROXY_CODE" in' in body
    assert '401|403) ;;' in body
    assert '*) echo "::error::CLIProxy authentication route regressed"; exit 1 ;;' in body
    assert '"$OPENCODE_CODE" != "401"' in body


def test_deploy_recovers_only_its_route_changes_and_never_prints_secret_values():
    workflow = load_deploy_workflow()
    body = deploy_body()
    stage_step = next(
        step
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name", "").startswith("Stage Portainer")
    )
    rollback_step = next(
        step
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name", "").startswith("Rollback transaction")
    )
    script = stage_step["with"]["script"]
    rollback_script = rollback_step["with"]["script"]

    assert "TRANSACTION_MARKER" in script
    assert "caddy-change-attempted" in rollback_script
    assert "nginx-change-attempted" in rollback_script
    assert "edge-vpn4/nginx.conf" in script
    assert "edge-vpn4/Caddyfile" in script
    assert "docker compose -f \"$DEPLOY_PATH/portainer-vpn4/docker-compose.yml\" down" in rollback_script
    assert "$SUDO rm -rf \"$TRANSACTION_DIR\"" in rollback_script
    assert "<<" not in script and "<<" not in rollback_script
    assert all(line.strip() != "else" for line in script.splitlines())
    assert all(line.strip() != "else" for line in rollback_script.splitlines())
    for secret in ("SSH_HOST", "SSH_USER", "SSH_KEY", "DEPLOY_PATH"):
        assert f'echo "${secret}"' not in body
        assert f'echo "${{{{ secrets.{secret}' not in body


def test_deploy_is_a_fail_closed_transaction_until_external_checks_commit_it():
    """Every failure after an ingress change must restore the old routes.

    The old route config is deliberately retained until the GitHub-runner
    public checks complete. A durable transaction marker lets a dedicated
    `if: failure()` SSH step cover both remote-command and public TLS/auth
    failures after the initial remote step has exited.
    """
    workflow = load_deploy_workflow()
    body = deploy_body()
    steps = workflow["jobs"]["deploy"]["steps"]
    deploy_ssh = next(
        step
        for step in steps
        if step.get("name", "").startswith("Stage Portainer")
    )
    script = deploy_ssh["with"]["script"]

    # drone-ssh injects an `exit` guard after EVERY physical line when
    # script_stop is true. That turns a legitimate false marker condition in
    # `if test -f ...; then` into an abort before rollback can continue.
    # The scripts themselves own failure semantics with set -euo pipefail.
    assert deploy_ssh["with"].get("script_stop") is False
    assert "set -euo pipefail" in script
    assert "TRANSACTION_DIR=" in script
    assert "TRANSACTION_MARKER=" in script
    assert "caddy-change-attempted" in script
    assert "nginx-change-attempted" in script
    assert "PORTAINER_STARTED=1" in script
    assert "PREVIOUS_NGINX" in script and "PREVIOUS_CADDY" in script

    external_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name", "").startswith("Verify public TLS")
    )
    rollback_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name", "").startswith("Rollback transaction")
    )
    assert external_index < rollback_index
    assert steps[rollback_index].get("if") == "failure()"
    rollback_script = steps[rollback_index]["with"]["script"]
    assert "edge-vpn4/Caddyfile" in rollback_script
    assert "edge-vpn4/nginx.conf" in rollback_script
    assert 'docker compose -f "$DEPLOY_PATH/portainer-vpn4/docker-compose.yml" down' in rollback_script
    assert any(
        step.get("name", "").startswith("Commit successful transaction")
        and step.get("if") == "success()"
        for step in steps
    )

    for step in steps:
        if not str(step.get("uses", "")).startswith("appleboy/ssh-action"):
            continue
        assert step["with"].get("script_stop") is False
        action_script = step["with"]["script"]
        assert "<<" not in action_script
        assert all(line.strip() != "else" for line in action_script.splitlines())


def test_deploy_writes_root_owned_transaction_artifacts_via_sudo_tee():
    """Shell redirects run before sudo and cannot write a root-owned directory.

    The transaction directory deliberately belongs to root so a deployment user
    cannot tamper with backups. Snapshot and listener output must therefore be
    materialized by root through tee, and comparison must also run through sudo.
    """
    script = deploy_body()

    assert 'snapshot_non_portainer | $SUDO tee "$SNAPSHOT_BEFORE" >/dev/null' in script
    assert 'snapshot_non_portainer | $SUDO tee "$SNAPSHOT_AFTER" >/dev/null' in script
    assert '$SUDO ss -ltn | $SUDO tee "$LISTENERS" >/dev/null' in script
    assert '$SUDO grep -Eq' in script
    assert '$SUDO cmp -s "$SNAPSHOT_BEFORE" "$SNAPSHOT_AFTER"' in script
    assert '$SUDO diff -u "$SNAPSHOT_BEFORE" "$SNAPSHOT_AFTER"' in script
    assert 'snapshot_non_portainer > "$SNAPSHOT_BEFORE"' not in script
    assert 'snapshot_non_portainer > "$SNAPSHOT_AFTER"' not in script
    assert '$SUDO ss -ltn > "$LISTENERS"' not in script


def test_rollback_keeps_transaction_artifacts_when_restore_fails():
    """Rollback failure must stay visible and leave the only route backups intact."""
    workflow = load_deploy_workflow()
    rollback_script = next(
        step["with"]["script"]
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name", "").startswith("Rollback transaction")
    )

    assert "ROLLBACK_FAILED=0" in rollback_script
    assert "rollback_run()" in rollback_script
    assert "ROLLBACK_FAILED=1" in rollback_script
    assert 'test "$ROLLBACK_FAILED" = "0" && $SUDO rm -rf "$TRANSACTION_DIR"' in rollback_script
    assert 'test "$ROLLBACK_FAILED" = "0" || exit 1' in rollback_script


def test_rollback_restores_checkout_revision_as_well_as_runtime_route_files():
    """A route backup alone is insufficient after `git reset --hard`.

    A failure after the candidate checkout is reset but before edge markers are
    written would otherwise leave disk at the candidate revision while Nginx
    and Caddy still run the old configuration. The next deployment would then
    treat the wrong files as its rollback baseline.
    """
    workflow = load_deploy_workflow()
    stage_script = next(
        step["with"]["script"]
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name", "").startswith("Stage Portainer")
    )
    rollback_script = next(
        step["with"]["script"]
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name", "").startswith("Rollback transaction")
    )

    assert 'OLD_SHA=$(git rev-parse HEAD)' in stage_script
    assert 'old-sha' in stage_script
    assert 'tee "$TRANSACTION_DIR/old-sha"' in stage_script
    assert 'OLD_SHA=$($SUDO cat "$TRANSACTION_DIR/old-sha")' in rollback_script
    assert 'rollback_run git reset --hard "$OLD_SHA"' in rollback_script


def test_rollback_reads_every_root_owned_transaction_marker_via_sudo():
    """Rollback must work even if the transaction directory is mode 0700 root."""
    workflow = load_deploy_workflow()
    rollback_script = next(
        step["with"]["script"]
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name", "").startswith("Rollback transaction")
    )

    for marker in (
        '"$TRANSACTION_MARKER"',
        '"$TRANSACTION_DIR/caddy-change-attempted"',
        '"$TRANSACTION_DIR/nginx-change-attempted"',
        '"$TRANSACTION_DIR/portainer-attempted"',
    ):
        assert f"$SUDO test -f {marker}" in rollback_script


def load_rollback_workflow():
    """Load the Task 5 manual, data-preserving removal workflow."""
    assert ROLLBACK_WORKFLOW.exists(), "rollback-portainer-vpn4.yml phai ton tai"
    data = yaml.safe_load(ROLLBACK_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "rollback workflow phai la mot YAML mapping"
    return data


def rollback_body():
    load_rollback_workflow()
    return ROLLBACK_WORKFLOW.read_text(encoding="utf-8")


def rollback_stage_step():
    return next(
        step
        for step in load_rollback_workflow()["jobs"]["rollback"]["steps"]
        if step.get("name", "").startswith("Remove only Portainer")
    )


def test_rollback_workflow_is_manual_serialized_and_uses_an_explicit_target_ref():
    workflow = load_rollback_workflow()
    triggers = workflow.get("on", workflow.get(True))

    assert isinstance(triggers, dict)
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["target_ref"] == {
        "description": "Git branch containing the Portainer configuration to remove",
        "required": True,
        "default": "main",
        "type": "string",
    }
    assert workflow["concurrency"] == {
        "group": "deploy-vpn4-host",
        "cancel-in-progress": False,
    }
    assert workflow["jobs"]["rollback"]["steps"]


def test_rollback_preflight_checks_secrets_and_the_exact_portainer_dns_before_ssh():
    workflow = load_rollback_workflow()
    body = rollback_body()
    steps = workflow["jobs"]["rollback"]["steps"]
    ssh_index = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("appleboy/ssh-action")
    )
    dns_index = next(index for index, step in enumerate(steps) if "DNS" in step["name"])

    assert dns_index < ssh_index
    assert "portainer.hangocthanh.io.vn" in steps[dns_index]["run"]
    assert '"$RESOLVED" != "$SSH_HOST_VPN4"' in steps[dns_index]["run"]
    for secret in ("SSH_HOST_VPN4", "SSH_USER", "SSH_KEY", "DEPLOY_PATH"):
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in body
        assert f'echo "${secret}"' not in body
    assert rollback_stage_step()["env"] == {
        "DEPLOY_PATH": "${{ secrets.DEPLOY_PATH }}",
        "DEPLOY_REF": "${{ inputs.target_ref }}",
    }
    assert 'git fetch origin "$DEPLOY_REF:refs/remotes/origin/$DEPLOY_REF"' in body
    assert 'git reset --hard "origin/$DEPLOY_REF"' in body
    assert "git check-ref-format --branch \"$DEPLOY_REF\"" in body


def test_rollback_removes_only_the_exact_portainer_routes_with_guarded_editing():
    script = rollback_stage_step()["with"]["script"]

    assert "portainer.hangocthanh.io.vn caddy-edge:8447;" in script
    assert "https://portainer.hangocthanh.io.vn:8447 {" in script
    assert "assert s.count(route) == 1" in script
    assert "assert s.count(site) == 1" in script
    assert "edge-vpn4/nginx.conf" in script
    assert "edge-vpn4/Caddyfile" in script
    assert 'p.write_text(s.replace(route, ""))' in script
    assert 'p.write_text(s.replace(site, ""))' in script


def test_rollback_validates_route_free_candidate_before_target_edge_recreates():
    script = rollback_stage_step()["with"]["script"]
    caddy_recreate = (
        'docker compose -f "$DEPLOY_PATH/edge-vpn4/docker-compose.yml" '
        "up -d --force-recreate --no-deps caddy-edge"
    )
    nginx_recreate = (
        'docker compose -f "$DEPLOY_PATH/edge-vpn4/docker-compose.yml" '
        "up -d --force-recreate --no-deps nginx"
    )

    assert "nginx:1.27-alpine nginx -t" in script
    assert "caddy:2.8-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile" in script
    assert script.index("nginx:1.27-alpine nginx -t") < script.index(caddy_recreate)
    assert script.index("caddy:2.8-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile") < script.index(caddy_recreate)
    assert script.index(caddy_recreate) < script.index(nginx_recreate)
    assert 'docker compose -f "$DEPLOY_PATH/edge-vpn4/docker-compose.yml" up -d --remove-orphans' not in script
    for unrelated in ("--no-deps derper", "--no-deps cliproxy", "--no-deps opencode", "--no-deps fail2ban"):
        assert unrelated not in script


def test_rollback_stops_only_portainer_and_preserves_its_named_volume_without_public_admin_ports():
    script = rollback_stage_step()["with"]["script"]
    down = 'docker compose -f "$DEPLOY_PATH/portainer-vpn4/docker-compose.yml" down'

    assert down in script
    assert "portainer-vpn4/docker-compose.yml" not in script.replace(down, "")
    for forbidden in ("down -v", "docker volume rm", "docker system prune", "docker volume prune", "docker compose rm"):
        assert forbidden not in rollback_body()
    assert "docker volume inspect portainer-vpn4_portainer_data" in script
    assert 'docker ps --filter "name=^/portainer$" --format' in script
    assert "8000|9000|9443" in script


def test_rollback_verifies_the_retired_public_route_and_existing_route_boundaries():
    body = rollback_body()

    assert "https://portainer.hangocthanh.io.vn/api/status" in body
    assert '''case "$PORTAINER_CODE" in
            000) ;;
            *) echo "::error::Portainer public SNI route still responds with HTTP"; exit 1 ;;
          esac''' in body
    assert "https://vpn4.hangocthanh.io.vn/derp/probe" in body
    assert 'test "$DERP_CODE" = "200"' in body
    assert "https://cliproxy.hangocthanh.io.vn/v1/models" in body
    assert '401|403) ;;' in body
    assert "https://opencode.hangocthanh.io.vn/global/health" in body
    assert 'test "$OPENCODE_CODE" = "401"' in body
    assert "Authorization:" not in body
    assert "-k" not in body


def test_rollback_recovers_original_routes_and_portainer_if_the_transaction_fails():
    workflow = load_rollback_workflow()
    steps = workflow["jobs"]["rollback"]["steps"]
    stage_script = rollback_stage_step()["with"]["script"]
    recovery_step = next(
        step
        for step in steps
        if step.get("name", "").startswith("Restore Portainer transaction")
    )
    recovery_script = recovery_step["with"]["script"]

    assert "TRANSACTION_MARKER" in stage_script
    assert "PREVIOUS_NGINX" in stage_script and "PREVIOUS_CADDY" in stage_script
    assert "caddy-change-attempted" in stage_script
    assert "nginx-change-attempted" in stage_script
    assert "portainer-down-attempted" in stage_script
    assert recovery_step["if"] == "failure()"
    assert 'cp "$TRANSACTION_DIR/Caddyfile.previous" "$DEPLOY_PATH/edge-vpn4/Caddyfile"' in recovery_script
    assert 'cp "$TRANSACTION_DIR/nginx.conf.previous" "$DEPLOY_PATH/edge-vpn4/nginx.conf"' in recovery_script
    assert 'caddy:2.8-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile' in recovery_script
    assert recovery_script.index("caddy validate") < recovery_script.index(
        "up -d --force-recreate --no-deps caddy-edge"
    )
    assert recovery_script.index("nginx:1.27-alpine nginx -t") < recovery_script.index(
        "up -d --force-recreate --no-deps nginx"
    )
    assert 'docker compose -f "$DEPLOY_PATH/edge-vpn4/docker-compose.yml" up -d --force-recreate --no-deps caddy-edge' in recovery_script
    assert 'docker compose -f "$DEPLOY_PATH/edge-vpn4/docker-compose.yml" up -d --force-recreate --no-deps nginx' in recovery_script
    assert 'docker compose -f "$DEPLOY_PATH/portainer-vpn4/docker-compose.yml" up -d portainer' in recovery_script
    assert 'git reset --hard "$OLD_SHA"' in recovery_script
    assert "ROLLBACK_FAILED=0" in recovery_script
    assert 'test "$ROLLBACK_FAILED" = "0" || exit 1' in recovery_script
    assert all("portainer_data" not in line for line in recovery_script.splitlines() if "rm" in line)


def test_rollback_ssh_scripts_do_not_use_heredocs_bare_else_or_script_stop_true():
    workflow = load_rollback_workflow()

    for step in workflow["jobs"]["rollback"]["steps"]:
        if not str(step.get("uses", "")).startswith("appleboy/ssh-action"):
            continue
        assert step["with"].get("script_stop") is False
        script = step["with"]["script"]
        assert "<<" not in script
        assert all(line.strip() != "else" for line in script.splitlines())
