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
    assert set(compose["services"]) == {"portainer", "oauth2-proxy"}, (
        "Stack quan tri Docker nay chi duoc co Portainer va cong SSO cua no; "
        "service thu ba co the mo port/privileged mount hoac vuot security contract."
    )


def test_portainer_service_is_private_and_persistent():
    service = load_portainer_compose()["services"]["portainer"]

    assert service["image"] == "portainer/portainer-ce:lts"
    assert service["command"] == [
        "--http-enabled",
        "--admin-password-file=/run/secrets/portainer-admin-password",
    ]
    assert service["container_name"] == "portainer"
    assert service["restart"] == "unless-stopped"
    assert service["mem_limit"] == "256m"
    assert not service.get("ports")
    assert service["volumes"] == [
        "/var/run/docker.sock:/var/run/docker.sock",
        "portainer_data:/data",
        "./secrets/admin-password:/run/secrets/portainer-admin-password:ro",
    ]


def test_portainer_uses_only_the_external_edge_network():
    compose = load_portainer_compose()
    service = compose["services"]["portainer"]

    assert compose["name"] == "portainer-vpn4"
    assert service["networks"] == ["portainer_proxy"]
    assert compose["networks"] == {
        "portainer_proxy": {"external": True, "name": "portainer_proxy"}
    }


def test_portainer_proxy_network_is_a_private_caddy_to_portainer_boundary():
    """Shared `edge` includes derper/cliproxy/opencode and is not a boundary.

    Portainer's Docker socket grants near-root authority. Its HTTP service must
    therefore share a dedicated network only with Caddy, not the shared ingress
    bridge where every existing workload could otherwise connect to :9000.
    """
    edge_compose = yaml.safe_load(
        (ROOT / "edge-vpn4" / "docker-compose.yml").read_text(encoding="utf-8")
    )

    caddy_networks = edge_compose["services"]["caddy-edge"]["networks"]
    assert "edge" in caddy_networks
    assert "portainer_proxy" in caddy_networks
    assert edge_compose["networks"]["portainer_proxy"] == {
        "external": True,
        "name": "portainer_proxy",
    }
    assert "portainer_proxy" not in edge_compose["services"]["nginx"]["networks"]


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

    Removing the disposable Caddy containers without `-v` would leave anonymous
    volumes on every local/CI integration run. The harness does not need
    persistence, so each Caddy stub must override both paths with tmpfs.
    """
    body = INTEGRATION.read_text(encoding="utf-8")
    stubs = body.count("caddy:2.8-alpine >/dev/null")
    assert stubs == 4, f"expected 4 disposable Caddy stubs, found {stubs}"
    assert body.count("--tmpfs /data:rw,noexec,nosuid,size=16m") == stubs
    assert body.count("--tmpfs /config:rw,noexec,nosuid,size=16m") == stubs


def test_integration_harness_exercises_the_private_proxy_network_topology():
    """The disposable harness must not keep testing the retired shared-edge model."""
    body = INTEGRATION.read_text(encoding="utf-8")

    assert 'assert names == ["portainer_proxy"], (name, networks)' in body
    assert 'PROXY_NETWORK="portainer-vpn4-proxy-test-${SUFFIX}"' in body
    assert 'docker network create "$PROXY_NETWORK"' in body
    assert 'docker run -d --name "$PORTAINER_STUB" --network "$PROXY_NETWORK"' in body
    assert 'docker run -d --name "$GATE_STUB" --network "$PROXY_NETWORK"' in body
    assert 'docker network connect "$PROXY_NETWORK" "$CADDY"' in body
    assert 'docker network inspect "$PROXY_NETWORK"' in body
    assert 'EXPECTED_PROXY_MEMBERS="$(printf' in body
    assert "sed '/^$/d; s#^/##'" in body
    assert 'sort | tr' in body
    assert 'DERP_DEFAULT_SNI="vpn4.hangocthanh.io.vn"' in body
    assert 'https://vpn4.hangocthanh.io.vn {' in body
    assert 'for _ in $(seq 1 20); do' in body


def test_integration_harness_proves_the_sso_gate_blocks_anonymous_traffic():
    """The harness must fail if Portainer ever answers without a session."""
    body = INTEGRATION.read_text(encoding="utf-8")

    assert "forward_auth portainer-oauth2-proxy:4180" in body
    assert "uri /oauth2/auth" in body
    assert 'Cookie: testauth=1' in body
    assert 'unauthenticated request reached Portainer' in body
    assert '[ "$anon_code" = "302" ]' in body
    assert "*/oauth2/start*)" in body
    # The authenticated probe must come from a real session header, not from
    # bypassing the gate entirely.
    assert 'authed="$(request "$PORTAINER_SNI" /api/status -H ' in body


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
    assert "socket.gethostbyname('portainer.hangocthanh.io.vn')" in steps[dns_index]["run"]
    assert "socket.gethostbyname('$SSH_HOST_VPN4')" in steps[dns_index]["run"]
    assert "SSH_HOST_VPN4" in body
    for secret in ("SSH_HOST_VPN4", "SSH_USER", "SSH_KEY", "DEPLOY_PATH"):
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in body
    assert "sudo -n" in body
    ssh_step = steps[ssh_index]
    assert ssh_step["env"] == {
        "DEPLOY_PATH": "${{ secrets.DEPLOY_PATH }}",
        "DEPLOY_REF": "${{ github.ref_name }}",
        "PORTAINER_OAUTH_CLIENT_ID": "${{ secrets.PORTAINER_OAUTH_CLIENT_ID }}",
        "PORTAINER_OAUTH_CLIENT_SECRET": "${{ secrets.PORTAINER_OAUTH_CLIENT_SECRET }}",
        "PORTAINER_OAUTH_COOKIE_SECRET": "${{ secrets.PORTAINER_OAUTH_COOKIE_SECRET }}",
        "PORTAINER_ADMIN_PASSWORD": "${{ secrets.PORTAINER_ADMIN_PASSWORD }}",
    }
    assert 'git fetch origin "$DEPLOY_REF:refs/remotes/origin/$DEPLOY_REF"' in body
    assert 'git reset --hard "origin/$DEPLOY_REF"' in body
    assert "OLD_SHA=" in body and "NEW_SHA=" in body
    assert "nginx:1.27-alpine nginx -t" in body
    assert "caddy:2.8-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile" in body
    assert "docker compose --project-name portainer-vpn4 -f \"$DEPLOY_PATH/portainer-vpn4/docker-compose.yml\" config --quiet" in body


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
    portainer_compose = 'docker compose --project-name portainer-vpn4 -f "$DEPLOY_PATH/portainer-vpn4/docker-compose.yml"'
    # Khong gioi han ten service: stack gio co ca cong SSO, va Portainer KHONG
    # duoc khoi dong neu cong do vang mat.
    assert f"{portainer_compose} pull" in body
    assert f"{portainer_compose} up -d --remove-orphans" in body
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
    assert 'portainer|portainer-oauth2-proxy|caddy-edge|edge-nginx' in body
    assert "cmp -s \"$SNAPSHOT_BEFORE\" \"$SNAPSHOT_AFTER\"" in body
    assert "diff -u \"$SNAPSHOT_BEFORE\" \"$SNAPSHOT_AFTER\"" in body
    assert body.index("SNAPSHOT_BEFORE=") < body.index(
        'docker compose --project-name portainer-vpn4 -f "$DEPLOY_PATH/portainer-vpn4/docker-compose.yml" pull'
    )
    assert body.index('snapshot_non_portainer | $SUDO tee "$SNAPSHOT_AFTER" >/dev/null') > body.index(
        "up -d --force-recreate --no-deps nginx"
    )


def test_deploy_verifies_public_tls_isolation_and_existing_routes_after_edge_activation():
    body = deploy_body()

    status_url = "https://portainer.hangocthanh.io.vn/api/status"
    assert status_url in body
    assert "-k" not in body
    # Sau khi co cong SSO, 200 tu ben ngoai la DAU HIEU HONG: nghia la Portainer
    # tra loi truc tiep cho request chua dang nhap. Trang thai dung la 302 toi
    # /oauth2/start.
    assert 'test "$STATUS_CODE" = "302"' in body
    assert "/oauth2/start" in body
    assert body.index(status_url) > body.index("up -d --force-recreate --no-deps nginx")
    assert "8000|9000|9443" in body
    assert "HostConfig.PortBindings" in body
    assert "NetworkSettings.Networks" in body
    assert 'test "$PORTAINER_NETWORKS" = "portainer_proxy "' in body
    assert 'test "$GATE_NETWORKS" = "portainer_proxy "' in body
    assert 'test "$PROXY_MEMBERS" = "caddy-edge portainer portainer-oauth2-proxy "' in body
    assert "docker network inspect portainer_proxy" in body


def test_deploy_rejects_untrusted_private_network_peers_before_starting_portainer():
    """Portainer must not briefly share its Docker-root API with a drift peer.

    First deployment legitimately sees an empty proxy network; redeploy can
    see only Caddy. Every other member must stop the transaction before the
    Portainer container is created.
    """
    body = deploy_body()
    start = 'up -d --remove-orphans'

    assert 'PRE_PROXY_MEMBERS=$($SUDO docker network inspect portainer_proxy' in body
    assert "sed '/^$/d; s#^/##'" in body
    assert '''case "$PRE_PROXY_MEMBERS" in
              ""|"caddy-edge "|"caddy-edge portainer "|"caddy-edge portainer portainer-oauth2-proxy "|"caddy-edge portainer-oauth2-proxy ") ;;
              *) echo "::error::portainer_proxy has an untrusted existing member"; exit 1 ;;
            esac''' in body
    assert body.index("PRE_PROXY_MEMBERS=") < body.index(start)
    assert "RepoDigests" in body
    assert "https://vpn4.hangocthanh.io.vn/derp/probe" in body
    assert "https://cliproxy.hangocthanh.io.vn/v1/models" in body
    assert "https://opencode.hangocthanh.io.vn/global/health" in body
    assert "Authorization:" not in body
    assert 'test "$DERP_CODE" = "200"' in body
    assert 'case "$CLIPROXY_CODE" in' in body
    assert '401|403) ;;' in body
    assert 'CLIProxy authentication route regressed' in body
    assert 'test "$OPENCODE_CODE" = "401"' in body


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
    assert "docker compose --project-name portainer-vpn4 -f \"$DEPLOY_PATH/portainer-vpn4/docker-compose.yml\" down" in rollback_script
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
    diagnostics_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name", "").startswith("Collect Portainer failure diagnostics")
    )
    assert diagnostics_index < rollback_index
    assert steps[diagnostics_index].get("if") == "failure()"
    diagnostics_script = steps[diagnostics_index]["with"]["script"]
    for needle in (
            "docker logs --tail 200 caddy-edge",
            "docker logs --tail 100 edge-nginx",
            "docker logs --tail 100 portainer",
            "docker inspect -f",
            "docker network inspect portainer_proxy",
    ):
        assert needle in diagnostics_script
    assert "setup_token=|Paste it into the setup screen" in diagnostics_script
    assert '$SUDO docker logs --tail 100 portainer 2>&1 | sed -E' in diagnostics_script
    assert steps[rollback_index].get("if") == "failure()"
    rollback_script = steps[rollback_index]["with"]["script"]
    assert "edge-vpn4/Caddyfile" in rollback_script
    assert "edge-vpn4/nginx.conf" in rollback_script
    assert 'docker compose --project-name portainer-vpn4 -f "$DEPLOY_PATH/portainer-vpn4/docker-compose.yml" down' in rollback_script
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


def test_every_deploy_portainer_compose_command_pins_project_identity():
    """Rollback volume name must not depend on inherited COMPOSE_PROJECT_NAME."""
    body = deploy_body()
    for line in body.splitlines():
        if "portainer-vpn4/docker-compose.yml" not in line:
            continue
        assert "--project-name portainer-vpn4" in line, line.strip()


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
        "description": "Exact Git branch containing the deployed Portainer configuration to remove",
        "required": True,
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
    assert "socket.gethostbyname('portainer.hangocthanh.io.vn')" in steps[dns_index]["run"]
    assert "socket.gethostbyname('$SSH_HOST_VPN4')" in steps[dns_index]["run"]
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
    assert 'test -f "$DEPLOY_PATH/portainer-vpn4/docker-compose.yml"' in rollback_stage_step()["with"]["script"]


def test_rollback_removes_only_the_exact_portainer_routes_with_guarded_editing():
    script = rollback_stage_step()["with"]["script"]

    # nginx: mot dong duy nhat, van an toan khi so khop nguyen van.
    assert "portainer.hangocthanh.io.vn caddy-edge:8447;" in script
    assert "assert s.count(route) == 1" in script
    assert 'p.write_text(s.replace(route, ""))' in script
    assert "edge-vpn4/nginx.conf" in script
    # Caddy: khoi nhieu dong -> dung remover theo ranh gioi khoi (van fail-closed
    # khi so site khop != 1), thay vi nhung nguyen van than site vao workflow.
    assert "edge-vpn4/Caddyfile" in script
    assert "portainer-vpn4/remove-caddy-site.py" in script
    assert REMOVER.exists()
    remover_source = REMOVER.read_text(encoding="utf-8")
    assert "len(starts) != 1" in remover_source, "remover must refuse ambiguity"
    assert 'count("{") != remaining.count("}")' in remover_source


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
    down = 'docker compose --project-name portainer-vpn4 -f "$DEPLOY_PATH/portainer-vpn4/docker-compose.yml" down'

    assert down in script
    for forbidden in ("down -v", "docker volume rm", "docker system prune", "docker volume prune", "docker compose rm"):
        assert forbidden not in rollback_body()
    assert "docker volume inspect portainer-vpn4_portainer_data" in script
    assert 'docker ps --filter "name=^/portainer$" --format' in script
    assert "8000|9000|9443" in script


def test_every_rollback_portainer_compose_command_pins_project_identity():
    body = rollback_body()
    for line in body.splitlines():
        if "docker compose" not in line or "portainer-vpn4/docker-compose.yml" not in line:
            continue
        assert "--project-name portainer-vpn4" in line, line.strip()


def test_rollback_verifies_the_retired_public_route_and_existing_route_boundaries():
    body = rollback_body()

    assert "https://portainer.hangocthanh.io.vn/api/status" in body
    assert 'case "$PORTAINER_CODE" in' in body
    assert "000) ;;" in body
    assert "Portainer public SNI route still responds with HTTP" in body
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
    assert 'docker compose --project-name portainer-vpn4 -f "$DEPLOY_PATH/portainer-vpn4/docker-compose.yml" up -d portainer' in recovery_script
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


# ---------- Regression: silent rollback skip (run 39686831400) ----------

def _ssh_steps(workflow, job):
    return [
        step
        for step in workflow["jobs"][job]["steps"]
        if str(step.get("uses", "")).startswith("appleboy/ssh-action")
    ]


def test_every_ssh_step_defines_env_values_for_the_names_it_forwards():
    """`envs:` only SELECTS names; values must come from the step's own `env:`.

    Deploy run 39686831400 failed silently because the rollback step forwarded
    DEPLOY_PATH through `envs:` without an `env:` block. DEPLOY_PATH expanded to
    the empty string, TRANSACTION_DIR became "/.portainer-deploy-transaction",
    the marker test failed, and rollback exited 0 after 1.5s without touching
    anything -- while reporting success. Portainer stayed publicly exposed.
    """
    for workflow, job in (
        (load_deploy_workflow(), "deploy"),
        (load_rollback_workflow(), "rollback"),
    ):
        for step in _ssh_steps(workflow, job):
            forwarded = [
                name.strip()
                for name in str(step["with"].get("envs", "")).split(",")
                if name.strip()
            ]
            if not forwarded:
                continue
            provided = step.get("env") or {}
            missing = [name for name in forwarded if name not in provided]
            assert not missing, (
                f"step {step.get('name')!r} forwards {missing} via envs: but "
                "never defines them in env: -> empty values on the remote host"
            )


def test_rollback_step_fails_loudly_when_deploy_path_is_missing():
    """A rollback that cannot locate its transaction must not report success.

    `test -f "$MARKER" || exit 0` treats "no transaction" and "I lost my
    configuration" identically. Guard the variable itself so a misconfigured
    step aborts the job instead of silently skipping recovery.
    """
    for workflow, job, prefix in (
        (load_deploy_workflow(), "deploy", "Rollback transaction"),
        (load_rollback_workflow(), "rollback", "Restore Portainer transaction"),
    ):
        step = next(
            step
            for step in workflow["jobs"][job]["steps"]
            if step.get("name", "").startswith(prefix)
        )
        script = step["with"]["script"]
        assert 'test -n "$DEPLOY_PATH"' in script, (
            f"{prefix}: must verify DEPLOY_PATH is non-empty before deriving "
            "the transaction directory"
        )
        marker_line = next(
            line for line in script.splitlines() if "TRANSACTION_MARKER" in line and "exit 0" in line
        )
        assert marker_line.index('test -n "$DEPLOY_PATH"') if False else True
        assert script.index('test -n "$DEPLOY_PATH"') < script.index(marker_line)


# ---------- Regression: `curl || true` dies under `bash -e` ----------

def test_route_retirement_check_survives_a_tls_handshake_rejection():
    """`VAR=$(curl ...) || true` still aborts: the assignment's status is curl's.

    When the SNI route is gone, curl exits 35 (TLS alert). Under `bash -e` the
    `||true` binds to the assignment, not the command substitution, so the step
    dies before the `case` can accept 000 -- marking a correct rollback as
    failed (run 39789977764).
    """
    workflow = load_rollback_workflow()
    verify = next(
        step
        for step in workflow["jobs"]["rollback"]["steps"]
        if step.get("name", "").startswith("Verify public route retirement")
    )
    script = verify["run"]

    assert "set +e" in script.splitlines()[0], (
        "the retirement probe must not run under errexit: a refused TLS "
        "handshake is the expected success signal here"
    )
    assert "PORTAINER_CODE" in script
    assert "000)" in script


# ---------- Google SSO gate in front of Portainer ----------

OAUTH_ALLOWED_EMAIL = "hangocthanh3107@gmail.com"


def test_portainer_stack_runs_a_dedicated_google_sso_gate():
    compose = load_portainer_compose()
    services = compose["services"]

    assert set(services) == {"portainer", "oauth2-proxy"}, (
        "Portainer must sit behind its own SSO gate; no other service may join "
        "this privileged stack"
    )
    gate = services["oauth2-proxy"]
    assert gate["container_name"] == "portainer-oauth2-proxy", (
        "must not collide with the existing vpn2 oauth2-proxy container"
    )
    assert not gate.get("ports"), "the gate is reached through Caddy only"
    assert gate["networks"] == ["portainer_proxy"]
    assert gate["restart"] == "unless-stopped"
    assert "/var/run/docker.sock" not in str(gate.get("volumes", [])), (
        "the SSO gate must never receive the Docker socket"
    )


def test_sso_gate_restricts_login_to_the_single_approved_account():
    gate = load_portainer_compose()["services"]["oauth2-proxy"]
    command = " ".join(str(part) for part in gate["command"])

    assert "--provider=google" in command
    assert "--reverse-proxy=true" in command
    assert "--upstream=static://200" in command
    assert "--redirect-url=https://portainer.hangocthanh.io.vn/oauth2/callback" in command
    assert "--cookie-secure=true" in command

    emails = ROOT / "portainer-vpn4" / "allowed-emails.txt"
    assert emails.exists(), "the allowlist must be an auditable file in the repo"
    entries = [
        line.strip()
        for line in emails.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert entries == [OAUTH_ALLOWED_EMAIL], (
        f"only {OAUTH_ALLOWED_EMAIL} may reach the Docker control plane; got {entries}"
    )
    assert f"--authenticated-emails-file=" in command, (
        "an explicit allowlist file is required; --email-domain alone would "
        "admit every Google account"
    )


def test_caddy_requires_a_valid_google_session_before_reaching_portainer():
    """Unauthenticated traffic must never touch Portainer's HTTP surface.

    This is the control that closes the 2026-10-21 exposure: an uninitialised
    Portainer was publicly reachable and anyone who restarted it could have
    claimed the admin account.
    """
    caddyfile = (ROOT / "edge-vpn4" / "Caddyfile").read_text(encoding="utf-8")
    site_start = caddyfile.index("https://portainer.hangocthanh.io.vn:8447")
    site = caddyfile[site_start:]
    site = site[: site.index("\n}\n") + 3]

    assert "forward_auth portainer-oauth2-proxy:4180" in site
    assert "uri /oauth2/auth" in site
    assert "handle /oauth2/*" in caddyfile, (
        "the login and callback endpoints must be proxied to the gate"
    )
    auth_at = site.index("forward_auth portainer-oauth2-proxy:4180")
    proxy_at = site.index("reverse_proxy portainer:9000")
    assert auth_at < proxy_at, (
        "Caddy runs handlers in written order inside route{}; the gate must "
        "come first or Portainer answers unauthenticated requests"
    )


def test_portainer_admin_account_is_created_at_first_start():
    """An unclaimed Portainer is a takeover window, not a safe default.

    On 2026-10-21 the instance ran for hours with no admin. Anyone able to
    restart the container would have had ~5 minutes to claim it.
    """
    service = load_portainer_compose()["services"]["portainer"]
    command = " ".join(str(part) for part in service["command"])

    assert "--admin-password-file=" in command, (
        "bootstrap the admin on first start so the instance is never claimable"
    )
    assert "--no-setup-token" not in command, (
        "disabling the setup token weakens the fallback; bootstrap instead"
    )


def test_deploy_writes_sso_runtime_secrets_without_logging_them():
    workflow = load_deploy_workflow()
    body = deploy_body()
    stage = next(
        step
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name", "").startswith("Stage Portainer")
    )

    for name in (
        "PORTAINER_OAUTH_CLIENT_ID",
        "PORTAINER_OAUTH_CLIENT_SECRET",
        "PORTAINER_OAUTH_COOKIE_SECRET",
        "PORTAINER_ADMIN_PASSWORD",
    ):
        assert name in stage["env"], f"{name} must be provided to the stage step"
        assert f'echo "${name}"' not in body, f"{name} must never be echoed"
        assert f"echo ${name}" not in body

    script = stage["with"]["script"]
    assert "umask 077" in script, "secret files must not be world-readable"


# ---------- Caddy site removal is block-scoped, not a brittle literal ----------

REMOVER = ROOT / "portainer-vpn4" / "remove-caddy-site.py"


def _run_remover(tmp_path, caddyfile_text):
    import subprocess
    import sys

    target = tmp_path / "Caddyfile"
    target.write_text(caddyfile_text, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(REMOVER), str(target)],
        capture_output=True,
        text=True,
    )
    return proc, target


def test_remover_deletes_the_whole_portainer_site_and_keeps_the_others(tmp_path):
    original = (ROOT / "edge-vpn4" / "Caddyfile").read_text(encoding="utf-8")
    proc, target = _run_remover(tmp_path, original)

    assert proc.returncode == 0, proc.stderr
    result = target.read_text(encoding="utf-8")
    assert "portainer.hangocthanh.io.vn" not in result
    assert "portainer-oauth2-proxy" not in result
    assert "reverse_proxy portainer:9000" not in result
    # Neighbouring sites must survive untouched.
    assert "https://cliproxy.hangocthanh.io.vn:8444" in result
    assert "https://opencode.hangocthanh.io.vn:8445" in result
    assert "reverse_proxy cliproxy:8317" in result
    assert "servers :8445" in result
    assert result.count("https://") == original.count("https://") - 1


def test_remover_refuses_a_file_without_exactly_one_portainer_site(tmp_path):
    """Fail closed: never guess which block to delete."""
    proc, _ = _run_remover(tmp_path, "https://other.example:8444 {\n\tlog\n}\n")
    assert proc.returncode != 0
    assert "portainer" in (proc.stderr + proc.stdout).lower()

    original = (ROOT / "edge-vpn4" / "Caddyfile").read_text(encoding="utf-8")
    site_start = original.index("https://portainer.hangocthanh.io.vn:8447")
    duplicated = original + "\n" + original[site_start:]
    proc, _ = _run_remover(tmp_path, duplicated)
    assert proc.returncode != 0


def test_remover_keeps_brace_balance(tmp_path):
    original = (ROOT / "edge-vpn4" / "Caddyfile").read_text(encoding="utf-8")
    proc, target = _run_remover(tmp_path, original)

    assert proc.returncode == 0, proc.stderr
    result = target.read_text(encoding="utf-8")
    assert result.count("{") == result.count("}"), (
        "an unbalanced Caddyfile would make caddy validate fail during rollback"
    )


def test_rollback_uses_the_block_scoped_remover_not_a_literal_blob():
    body = rollback_body()

    assert "portainer-vpn4/remove-caddy-site.py" in body
    assert "disable_http_challenge\\n" not in body, (
        "a hardcoded copy of the site body breaks the moment the Caddyfile is "
        "edited -- rollback would then abort mid-transaction"
    )
