# Portainer VPN4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Portainer CE LTS on vpn4 at `https://portainer.hangocthanh.io.vn` with trusted TLS, no exposed administrative ports, preserved data, and no regression to DERP, CLIProxy, or OpenCode.

**Architecture:** A standalone Portainer CE container joins only dedicated external network `portainer_proxy`, shared solely with `caddy-edge`; it exposes no host port. Nginx retains host 443 and forwards exact SNI `portainer.hangocthanh.io.vn` to a new private Caddy TLS listener on 8447; Caddy acquires TLS via ALPN and reverse-proxies to Portainer's explicitly enabled private HTTP port 9000. A manual deployment workflow stages Portainer first, then target-recreates only Caddy and Nginx after config preflight, snapshots unrelated containers, and verifies all existing routes.

**Tech Stack:** Docker Compose v5, Portainer CE LTS, Nginx stream/SNI routing, Caddy 2.8, GitHub Actions, `appleboy/ssh-action`, pytest/PyYAML, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-20-portainer-vpn4-design.md`

## Global Constraints

- vpn4 is standalone rootful Docker; do not introduce Swarm, Portainer Agent, or an external endpoint.
- Use image `portainer/portainer-ce:lts`, `container_name: portainer`, `restart: unless-stopped`, and `mem_limit: 256m`.
- Use command `--http-enabled`; no host publication of 8000, 9000, or 9443 is allowed.
- Mount `/var/run/docker.sock:/var/run/docker.sock` and `portainer_data:/data`; never delete `portainer_data` or use `docker compose down -v`.
- Portainer joins only external `portainer_proxy`; `caddy-edge` joins `edge` plus `portainer_proxy`; no other service joins `portainer_proxy`.
- Every Portainer Compose command uses `--project-name portainer-vpn4` so its data volume is predictably `portainer-vpn4_portainer_data` regardless of host environment.
- The only permitted edge changes are targeted Caddy/Nginx reload or recreation required to load the exact Portainer SNI route. Never recreate, stop, or alter DERP, CLIProxy, OpenCode, or fail2ban.
- Nginx's default SNI route must remain `derper:443`; derper retains host 80 and UDP 3478.
- Portainer Caddy site runs at `https://portainer.hangocthanh.io.vn:8447`, disables HTTP-01, proxies `portainer:9000`, and passes `X-Forwarded-Proto: https` plus original Host.
- Every vpn4 deploy or rollback workflow is `workflow_dispatch` only, uses concurrency group `deploy-vpn4-host`, and has `cancel-in-progress: false`.
- All remote commands use `sudo -n`; do not echo secrets, API keys, socket contents, or Portainer administrator credentials.
- DNS must resolve `portainer.hangocthanh.io.vn` to `SSH_HOST_VPN4` before any edge change.
- Browser evidence after production deploy must cover desktop and mobile at the Portainer public HTTPS URL, accessibility snapshot, screenshots, and browser-console errors.

## Review Focus

- **Portainer HTTP enablement:** Test service command includes `--http-enabled`, while Caddy is the only TLS termination point and 9000 remains unbound on the host.
- **Host-port isolation:** Test absent `ports:` definition and production check that listeners 8000/9000/9443 remain absent after deploy.
- **Proxy-network drift:** Before start, allow only empty, Caddy-only, or the existing trusted Caddy+Portainer pair; after activation require exactly Caddy+Portainer. A separate Docker-root actor can race these checks, which is a host authorization concern outside the workflow.
- **SNI default safety:** Test new exact Portainer mapping points to 8447 without changing default `derper:443` or OpenCode's 8446/PROXY-protocol path.
- **Persistent data safety:** Test deploy and rollback workflows never use `down -v`, `volume rm`, or destructive cleanup of `portainer_data`.
- **Unrelated service regression:** Test snapshot/check compares non-Portainer container restart count and `StartedAt`; production workflow additionally probes DERP, CLIProxy authentication, and OpenCode authentication.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `portainer-vpn4/docker-compose.yml` | Single Portainer CE service, private `portainer_proxy` connectivity, persistence, health, resource/log limits. |
| `edge-vpn4/nginx.conf` | Exact SNI stream route from public 443 to Caddy listener 8447. |
| `edge-vpn4/Caddyfile` | Private 8447 TLS site and reverse proxy to Portainer HTTP 9000. |
| `.github/workflows/deploy-portainer-vpn4.yml` | Manual guarded deployment, verification, targeted recovery. |
| `.github/workflows/rollback-portainer-vpn4.yml` | Manual targeted removal of Portainer and route rollback while preserving data. |
| `test/test_portainer_vpn4.py` | Static contracts for service, routes, deploy/rollback safety, and workflow order. |
| `test/portainer_vpn4_integration.sh` | Disposable compose/Nginx SNI integration verification. |
| `.github/workflows/ci.yml` | Adds the Portainer contract/integration checks to CI. |

## Task 1: Portainer Service Contract

**Files:**
- Create: `portainer-vpn4/docker-compose.yml`
- Create: `test/test_portainer_vpn4.py`

**Interfaces:**
- Consumes: Dedicated external Docker network `portainer_proxy` and host socket `/var/run/docker.sock`.
- Produces: Compose project `portainer-vpn4`, service `portainer`, named volume `portainer_data`.

- [ ] **Step 1: Write failing Compose contract tests**

```python
def test_portainer_service_is_private_and_persistent():
    service = load(PORTAINER_COMPOSE)["services"]["portainer"]
    assert service["image"] == "portainer/portainer-ce:lts"
    assert service["command"] == ["--http-enabled"]
    assert service["container_name"] == "portainer"
    assert service["restart"] == "unless-stopped"
    assert service["mem_limit"] == "256m"
    assert not service.get("ports")
    assert "/var/run/docker.sock:/var/run/docker.sock" in service["volumes"]
    assert "portainer_data:/data" in service["volumes"]
```

Add assertions for: top-level project name `portainer-vpn4`; external network named `portainer_proxy`; Portainer only joins that network; `caddy-edge` is its only peer; `portainer_data` exists; no unsupported `healthcheck` is declared; and json-file log rotation uses `10m` / `3`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q test/test_portainer_vpn4.py`

Expected: FAIL because `portainer-vpn4/docker-compose.yml` does not exist.

- [ ] **Step 3: Create `portainer-vpn4/docker-compose.yml`**

Implement the single service and declarations fixed by Global Constraints. Use Compose syntax and logging conventions from `edge-vpn4/docker-compose.yml`. Do not add a healthcheck: the Portainer LTS image has no documented in-image HTTP probe tool, and Task 4 verifies `/api/status` through the real TLS ingress.

- [ ] **Step 4: Validate the rendered Compose config and unit test**

Run:

```bash
docker compose --project-name portainer-vpn4 -f portainer-vpn4/docker-compose.yml config --quiet
python -m pytest -q test/test_portainer_vpn4.py
```

Expected: Both PASS.

- [ ] **Step 5: Commit**

```bash
git add portainer-vpn4/docker-compose.yml test/test_portainer_vpn4.py
git commit -m "feat(portainer): add private vpn4 service stack"
```

## Task 2: Edge SNI and TLS Routing

**Files:**
- Modify: `edge-vpn4/nginx.conf`
- Modify: `edge-vpn4/Caddyfile`
- Modify: `test/test_edge_vpn4.py`
- Modify: `test/test_portainer_vpn4.py`

**Interfaces:**
- Consumes: Service name `portainer`, private HTTP port `9000`, public domain `portainer.hangocthanh.io.vn`.
- Produces: Exact Nginx SNI map entry to `caddy-edge:8447`, Caddy HTTPS listener `:8447`.

- [ ] **Step 1: Add failing route tests**

```python
def test_portainer_sni_route_is_exact_and_derp_stays_default():
    nginx = NGINX_CONF.read_text(encoding="utf-8")
    assert "portainer.hangocthanh.io.vn  caddy-edge:8447;" in nginx
    assert re.search(r"default\s+derper:443;", nginx)

def test_portainer_caddy_site_terminates_tls_and_proxies_private_http():
    caddy = CADDYFILE.read_text(encoding="utf-8")
    assert "https://portainer.hangocthanh.io.vn:8447" in caddy
    assert "disable_http_challenge" in caddy
    assert "reverse_proxy portainer:9000" in caddy
    assert "X-Forwarded-Proto https" in caddy
```

Add negative assertions that 8447 does not acquire OpenCode PROXY protocol wrapping and no existing Cliproxy/OpenCode/DERP mapping is changed.

- [ ] **Step 2: Run route tests to verify they fail**

Run: `python -m pytest -q test/test_edge_vpn4.py test/test_portainer_vpn4.py`

Expected: FAIL because neither Portainer route exists yet.

- [ ] **Step 3: Add exact Nginx and Caddy routes**

Add only the exact SNI map entry and Caddy site required by the spec. Use the 8444 site as the normal-TLS listener template. Explicitly set reverse-proxy headers required by Portainer, retaining the browser host and HTTPS scheme.

- [ ] **Step 4: Validate Nginx/Caddy syntax and route unit tests**

Run:

```bash
docker run --rm -v "$PWD/edge-vpn4/nginx.conf:/etc/nginx/nginx.conf:ro" nginx:1.27-alpine nginx -t
docker run --rm -v "$PWD/edge-vpn4/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.8-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
python -m pytest -q test/test_edge_vpn4.py test/test_portainer_vpn4.py
```

Expected: Both config validations and tests PASS.

- [ ] **Step 5: Commit**

```bash
git add edge-vpn4/nginx.conf edge-vpn4/Caddyfile test/test_edge_vpn4.py test/test_portainer_vpn4.py
git commit -m "feat(edge): route Portainer through vpn4 TLS ingress"
```

## Task 3: Local SNI Integration Test

**Files:**
- Create: `test/portainer_vpn4_integration.sh`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Portainer Compose, `edge-vpn4/nginx.conf`, `edge-vpn4/Caddyfile` route definitions.
- Produces: CI check `portainer-vpn4` proving exact SNI routing and service isolation in a disposable Docker network/project.

- [ ] **Step 1: Write a failing integration test script**

The script must create an isolated Docker network and use a disposable TLS-capable Caddy/Portainer-compatible HTTP backend. It must assert:

```bash
# Exact Portainer SNI reaches a 200/redirect-compatible backend.
# Unknown SNI reaches the DERP stub, not the Portainer backend.
# No host mapping exists for 8000, 9000, or 9443 in the Portainer Compose config.
```

Do not target vpn4 or any production hostname/IP.

- [ ] **Step 2: Run it to verify RED**

Run: `bash test/portainer_vpn4_integration.sh`

Expected: FAIL before the corresponding temporary test configuration/route support exists.

- [ ] **Step 3: Complete the disposable integration harness**

Keep the harness self-cleaning and distinct from production resources. It may use a test-only local certificate / `curl --resolve` / `-k`; production certificate validation belongs to Task 5.

- [ ] **Step 4: Add CI job and verify GREEN**

Add a `portainer-vpn4` job after checkout that validates Compose YAML, runs `test/test_portainer_vpn4.py`, runs the edge regression tests, and executes the new integration script.

Run:

```bash
python -m pytest -q test/test_portainer_vpn4.py test/test_edge_vpn4.py
bash test/portainer_vpn4_integration.sh
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add test/portainer_vpn4_integration.sh test/test_portainer_vpn4.py test/test_edge_vpn4.py .github/workflows/ci.yml
git commit -m "test(portainer): cover vpn4 ingress and isolation"
```

## Task 4: Guarded Production Deployment Workflow

**Files:**
- Create: `.github/workflows/deploy-portainer-vpn4.yml`
- Modify: `test/test_portainer_vpn4.py`

**Interfaces:**
- Consumes: GitHub secrets `SSH_HOST_VPN4`, `SSH_USER`, `SSH_KEY`, `SSH_PORT`, `DEPLOY_PATH`; target ref `github.ref_name`; stack/edge configs from Tasks 1-2.
- Produces: manual production deploy with remote verification; no action on unrelated services.

- [ ] **Step 1: Write failing workflow-policy tests**

Add assertions for all of these explicit requirements:

```python
def test_deploy_workflow_is_manual_and_serialized():
    assert triggers == {"workflow_dispatch"}
    assert workflow["concurrency"] == {
        "group": "deploy-vpn4-host",
        "cancel-in-progress": False,
    }

def test_deploy_preserves_data_and_unrelated_services():
    assert "docker compose down -v" not in body
    assert "volume rm" not in body
    assert "portainer_data" not in destructive_commands
    assert "docker compose up -d" not in edge_project_wide_commands
```

Also test ordering: DNS before SSH edge work; Nginx syntax before Nginx target recreate; Portainer health before edge change; snapshot before deployment and comparison after; DERP/CLIProxy/OpenCode/public-TLS/port-isolation verification after deployment.

- [ ] **Step 2: Run workflow-policy tests to verify RED**

Run: `python -m pytest -q test/test_portainer_vpn4.py`

Expected: FAIL because `deploy-portainer-vpn4.yml` is absent.

- [ ] **Step 3: Implement deployment workflow**

Implement exactly this sequence:

1. Resolve domain and `SSH_HOST_VPN4` to IP; require equality.
2. Ensure secrets are non-empty without logging them.
3. SSH using `sudo -n`; fetch `origin/<ref>` and reset `$DEPLOY_PATH` to it, recording old and new SHA.
4. Create `edge` only if absent; validate the Nginx file in a disposable container and validate Portainer Compose.
5. Snapshot all running containers other than the intentional deployment targets `portainer`, `caddy-edge`, and `edge-nginx`, using `Name RestartCount StartedAt`.
6. Pull and start only `portainer-vpn4` with `docker compose up -d --remove-orphans`; wait for the container to be running. After the targeted edge change, verify app readiness via HTTPS `GET /api/status`.
7. Target-recreate Caddy then Nginx only. Do not start/recreate the complete edge project and do not reference DERP/CLIProxy commands except read-only verification.
8. If Caddy/Nginx change fails or DERP probe fails, restore the prior edge config/ref and target-recreate only the component the workflow changed; retain Portainer data.
9. Run the exact verification list from the spec and compare snapshots.

Do not use heredocs or bare `else` in `appleboy/ssh-action` script if its invocation uses `script_stop: true`; follow the established workflow convention and its corresponding regression tests.

- [ ] **Step 4: Run static checks and workflow-policy tests**

Run:

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-portainer-vpn4.yml')); print('YAML OK')"
python -m pytest -q test/test_portainer_vpn4.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy-portainer-vpn4.yml test/test_portainer_vpn4.py
git commit -m "feat(portainer): add guarded vpn4 deployment workflow"
```

## Task 5: Non-destructive Rollback Workflow

**Files:**
- Create: `.github/workflows/rollback-portainer-vpn4.yml`
- Modify: `test/test_portainer_vpn4.py`
- Modify: `docs/superpowers/specs/2026-10-20-portainer-vpn4-design.md` only if implementation discovers a necessary correction to the approved spec.

**Interfaces:**
- Consumes: Portainer Compose project and edge routing files.
- Produces: manual rollback that removes reachability/container without deleting `portainer_data`.

- [ ] **Step 1: Write failing rollback-safety tests**

```python
def test_rollback_is_manual_serialized_and_preserves_portainer_data():
    assert triggers == {"workflow_dispatch"}
    assert concurrency_group == "deploy-vpn4-host"
    assert "down -v" not in body
    assert "volume rm" not in body
    assert "portainer_data" not in destructive_commands
```

Assert it restores/removes only the exact Portainer Nginx/Caddy route, target-recreates edge components only when route config changes, verifies DERP remains 200, and confirms Portainer public domain no longer routes after rollback.

- [ ] **Step 2: Run rollback tests to verify RED**

Run: `python -m pytest -q test/test_portainer_vpn4.py`

Expected: FAIL because rollback workflow is absent.

- [ ] **Step 3: Implement manual rollback workflow**

Require explicit `workflow_dispatch`. The remote script removes only the Portainer Compose container/project and exact Portainer SNI/Caddy site from the target revision/configuration, then target-recreates Caddy/Nginx. It must retain the named volume and not run a global prune or touch unrelated stacks.

- [ ] **Step 4: Verify rollback workflow policy**

Run:

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/rollback-portainer-vpn4.yml')); print('YAML OK')"
python -m pytest -q test/test_portainer_vpn4.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/rollback-portainer-vpn4.yml test/test_portainer_vpn4.py
git commit -m "feat(portainer): add data-preserving rollback workflow"
```

## Task 6: Full Branch Verification and Production Release

**Files:**
- Modify only if verification exposes a defect in Tasks 1-5.

**Interfaces:**
- Consumes: complete implementation and GitHub branch ref.
- Produces: deployment evidence tied to the branch commit and browser evidence for the production UI.

- [ ] **Step 1: Run full local regression suite relevant to changed systems**

Run:

```bash
docker compose --project-name portainer-vpn4 -f portainer-vpn4/docker-compose.yml config --quiet
python -m pytest -q test/test_portainer_vpn4.py test/test_edge_vpn4.py test/test_derp_config.py
bash test/portainer_vpn4_integration.sh
```

Expected: PASS. Record exact commit SHA.

- [ ] **Step 2: Review final diff at Normal, High, and XHigh depth**

Normal: approved scope and acceptance criteria. High: edge/DERP/CLIProxy/OpenCode interactions and CI ordering. XHigh: Docker socket authority, data deletion paths, stale host checkout, TLS certificate failure, concurrent deploy, and rollback behavior.

Expected: PASS at all three levels before production dispatch.

- [ ] **Step 3: Push branch and wait for CI of the same head SHA**

Run the repository CI and require the new `portainer-vpn4` job plus existing edge/DERP regressions to PASS. Do not use a green run for another revision as evidence.

- [ ] **Step 4: Dispatch `deploy-portainer-vpn4.yml` and monitor to completion**

Record run ID, URL, target ref/SHA, DNS result, no-public-port check, snapshot comparison, DERP probe, CLIProxy/OpenCode checks, and Caddy certificate evidence.

- [ ] **Step 5: Browser verification at desktop and mobile**

Use Playwright at `https://portainer.hangocthanh.io.vn`:

```text
1. Navigate and capture accessibility snapshot.
2. Capture desktop screenshot and inspect rendered text/control geometry.
3. Resize to mobile, capture snapshot and screenshot, inspect overflow/overlap/clipping.
4. Check browser console for new errors.
```

Expected: Portainer login screen is served through TLS, readable on both viewports, no public-port workaround is required, and no new browser console error exists.

- [ ] **Step 6: Commit any verification-driven fix separately, then rerun affected checks**

Do not amend a failed/previous commit. If no code changes arise, do not create an empty commit.

## Plan Self-Review

- **Spec coverage:** Tasks 1-5 map all service, route, deploy, rollback, persistence, isolation, and test requirements. Task 6 maps CI, production and browser evidence.
- **Step scan:** Every task starts with a failing test, has a RED verification, minimal implementation step, GREEN verification, and scoped commit.
- **Type/interface consistency:** `portainer` service, `portainer_data`, `edge`, 8447, and domain names are fixed consistently across all tasks.
- **Review focus:** Each listed failure mode has an owning contract test in Tasks 1, 2, 4, or 5 and production confirmation in Task 6.
- **Proportion:** The plan specifies decisions and commands but leaves implementation bodies to the executor; no production configuration is copied wholesale into the plan.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-20-portainer-vpn4-implementation.md`. Please review the plan and choose an execution approach:

- **Subagent-driven:** A fresh agent implements and a fresh reviewer checks each task. This is the safer option because the work changes a Docker-root-equivalent administrative endpoint and shared DERP ingress.
- **Native:** I implement all tasks in this session, then run an independent whole-branch review. This is faster but has fewer intermediate independent checks.

I recommend **Subagent-driven** because a mistake can expose host Docker authority or interrupt the shared DERP route. Does the plan capture what you want, and which approach should we use?
