# GatePro VPN4/VPN6 Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the approved GatePro API/MCP service on vpn4, with tailnet-only access and a dedicated application database on vpn6.

**Architecture:** A manually dispatched GitHub Actions workflow provisions an isolated `gatepro` PostgreSQL role/database on vpn6 and lets the GatePro image apply its own idempotent schema. A separate, transactional vpn4 stage builds the pinned upstream revision, injects secrets only into host-owned files, publishes port 8080 only on the vpn4 Tailscale IPv4 address, and rolls back only GatePro resources if a check fails. A static contract test protects the deployment boundaries before the workflow can be dispatched.

**Tech Stack:** GitHub Actions, `appleboy/ssh-action`, Docker Compose, PostgreSQL 16, Python `pytest`/PyYAML, GatePro client 0.2.0.

**Spec:** `docs/superpowers/specs/2026-11-02-gatepro-vpn4-vpn6-deployment-design.md`

## Global Constraints

- Run only through `workflow_dispatch`; never trigger deployment on push.
- Serialize vpn4 mutations with `deploy-vpn4-host` and do not cancel in-progress operations.
- Create only the `gatepro` role and `gatepro` database; never query, modify, or grant access to `derp`, `headscale`, or `opencode_remote`.
- Initialize application tables only by running `gatepro db init` from the deployed image.
- Publish `8080` only as `<vpn4-tailscale-ip>:8080:8080`; do not add Caddy, nginx, DNS, UFW public, or `0.0.0.0` configuration.
- Store `db.env`, API credentials, and Fernet keys outside Git, with mode `0600`, and never print them.
- The initial deployment starts `gatepro-api serve` without `--with-monitor`.
- Preserve unrelated vpn4 containers' restart counts and start timestamps.

## Review Focus

- Existing `gatepro` role/database: provisioning must reject unexpected ownership or database state rather than reusing an untrusted resource.
- vpn6 host access: a restrictive `pg_hba.conf` rule must admit exactly vpn4's Tailscale IP and reject a non-Tailscale source.
- Empty application configuration: API startup must fail before it runs if the required GatePro base URL and identity have not been provided through protected deployment secrets.
- Listener exposure: Docker must bind exactly the discovered Tailnet address, even when the host also has public network interfaces.
- Partial failure after database creation: rollback removes only GatePro resources on vpn4 and retains the isolated database for diagnosis without damaging shared vpn6 workloads.

---

### Task 1: Add Deployment Contract Tests

**Files:**
- Create: `test/test_gatepro_vpn4.py`

**Interfaces:**
- Consumes: `.github/workflows/deploy-gatepro-vpn4.yml`, created in Task 2.
- Produces: static deployment safety contract for CI and local `pytest`.

- [ ] **Step 1: Write failing contract tests for the approved boundary**

```python
def test_workflow_is_manual_and_serialized():
    assert triggers == {"workflow_dispatch": None}
    assert workflow["concurrency"] == {"group": "deploy-vpn4-host", "cancel-in-progress": False}

def test_workflow_uses_vpn6_database_but_never_shared_databases():
    assert "SSH_HOST_VPN6" in body
    assert "CREATE ROLE gatepro" in body
    assert "CREATE DATABASE gatepro" in body
    assert "headscale" not in body
    assert "opencode_remote" not in body

def test_workflow_initializes_schema_from_the_image_and_binds_only_tailnet():
    assert "gatepro db init" in body
    assert '"$VPN4_TS_IP:8080:8080"' in body
    assert "0.0.0.0:8080" not in body
    assert "--with-monitor" not in body
```

- [ ] **Step 2: Run the contract test to verify it fails**

Run: `python -m pytest test/test_gatepro_vpn4.py -q`

Expected: FAIL because the deployment workflow is absent.

- [ ] **Step 3: Add assertions for secrets, rollback, and unrelated-workload snapshots**

```python
def test_workflow_never_echoes_secrets_and_has_scoped_rollback():
    assert "GATEPRO_DB_PASSWORD" in body
    assert "GATEPRO_API_PASSWORD" in body
    assert "echo \"$GATEPRO_DB_PASSWORD\"" not in body
    assert "docker compose --project-name gatepro-vpn4" in body
    assert "docker compose down -v" not in body
    assert "snapshot_unrelated_workloads" in body
```

- [ ] **Step 4: Run the contract test to verify it fails for the intended missing workflow behavior**

Run: `python -m pytest test/test_gatepro_vpn4.py -q`

Expected: FAIL only because Task 2 has not created the workflow.

### Task 2: Implement Guarded VPN6/VPN4 Deployment Workflow

**Files:**
- Create: `.github/workflows/deploy-gatepro-vpn4.yml`
- Modify: `test/test_gatepro_vpn4.py`

**Interfaces:**
- Consumes: GitHub secrets `SSH_HOST_VPN4`, `SSH_HOST_VPN6`, `SSH_USER`, `SSH_KEY`, `SSH_PORT`, `DEPLOY_PATH`, `GATEPRO_DB_PASSWORD`, `GATEPRO_DB_SECRET_KEY`, `GATEPRO_API_PASSWORD`, `GATEPRO_BASE_URL`, `GATEPRO_IP_CLIENT`, `GATEPRO_HOST_ADDRESS`, `GATEPRO_HOST_NAME`.
- Produces: manual deployment/rollback flow that runs `gatepro db init`, then publishes a tailnet-only API on vpn4.

- [ ] **Step 1: Implement preflight and vpn6 provisioning stage**

Add manual workflow dispatch and `deploy-vpn4-host` concurrency. Validate non-empty required secrets without displaying their values. In the vpn6 SSH step, discover `tailscale ip -4` for vpn4 as a supplied environment value, connect to the existing PostgreSQL container through its configured local administration path, and idempotently create only role/database `gatepro`. Add a narrowly scoped host-access rule for vpn4's exact Tailnet `/32`, reload PostgreSQL, and assert the new role cannot connect to `derp`, `headscale`, or `opencode_remote`.

- [ ] **Step 2: Implement vpn4 transactional build and schema-init stage**

Check out `vanbienperu3107/gatepro-client` at pinned revision `075d520` into `$DEPLOY_PATH/gatepro-vpn4`. Discover `VPN4_TS_IP` with `tailscale ip -4`. Write `/srv/gatepro/db.env` from the database DSN and `GATEPRO_DB_SECRET_KEY` under `umask 077`; keep API account material in the dedicated GatePro config volume. Build image locally, use it to run `gatepro db init`, and insert required non-secret GatePro configuration through `gatepro db config-set`.

- [ ] **Step 3: Implement tailnet-only runtime and acceptance probes**

Start `gatepro-api serve` without the monitor using a dedicated compose project. Set the compose port mapping from `$VPN4_TS_IP:8080` only. Assert the container is running, `/healthz` returns 200, an unauthenticated protected endpoint returns 401, `/connections` is database-backed after API account issuance, and host listener output contains the exact Tailnet address with no wildcard/public `:8080` listener.

- [ ] **Step 4: Implement scoped rollback and workload preservation checks**

Snapshot unrelated vpn4 containers before mutation and compare after. On failure, stop/remove only the `gatepro-vpn4` compose project, remove only GatePro transaction files, restore a prior GatePro project state if one was recorded, and retain the new dedicated database/role. Do not use `docker compose down -v`, `git clean`, wildcard deletes, or changes to edge/DERP/CLIProxy resources.

- [ ] **Step 5: Update the contract test until it asserts the concrete workflow requirements**

Add assertions that secrets are received via `envs`, Tailnet IP discovery occurs before port mapping, schema initialization precedes API startup, monitor is not enabled, and rollback is constrained to `gatepro-vpn4`.

- [ ] **Step 6: Run the focused contract tests**

Run: `python -m pytest test/test_gatepro_vpn4.py -q`

Expected: PASS.

### Task 3: Validate Repository Checks And Deployment Inputs

**Files:**
- Modify: `.github/workflows/deploy-gatepro-vpn4.yml` only if checks expose a defect.
- Test: `test/test_gatepro_vpn4.py`

**Interfaces:**
- Consumes: completed workflow and static contract tests.
- Produces: validated, dispatch-ready workflow without a production deployment yet.

- [ ] **Step 1: Run the focused deployment contract test**

Run: `python -m pytest test/test_gatepro_vpn4.py -q`

Expected: PASS.

- [ ] **Step 2: Run the repository test suite**

Run: `python -m pytest -q`

Expected: PASS; report any unrelated failures rather than masking them.

- [ ] **Step 3: Validate workflow syntax and inspect the final diff**

Run: `python -c "import pathlib,yaml; yaml.safe_load(pathlib.Path('.github/workflows/deploy-gatepro-vpn4.yml').read_text())"`

Expected: exits 0.

Run: `git diff --check && git diff -- .github/workflows/deploy-gatepro-vpn4.yml test/test_gatepro_vpn4.py`

Expected: no whitespace errors; only intended workflow/test changes.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy-gatepro-vpn4.yml test/test_gatepro_vpn4.py docs/superpowers/specs/2026-11-02-gatepro-vpn4-vpn6-deployment-design.md docs/superpowers/plans/2026-11-02-gatepro-vpn4-vpn6-deployment.md
git commit -m "feat: add guarded GatePro vpn4 deployment"
```

## Self-Review

- Spec coverage: Tasks 1-3 cover all approved scope, runtime boundaries, rollback, and every Test Matrix item; public exposure and shared database modification remain excluded.
- Type consistency: workflow accepts exactly the named GitHub secrets and static tests inspect the workflow path created by Task 2.
- Review focus coverage: role/database reuse, Tailnet host access, missing GatePro configuration, listener exposure, and partial failure are protected by explicit workflow checks and static contract assertions.
- Proportion: the plan specifies interfaces and checks without embedding the implementation script.
