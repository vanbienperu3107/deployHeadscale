# GatePro VPN4/VPN6 Deployment Design

**Goal:** Deploy GatePro API and MCP on vpn4 for tailnet-only access, backed by a dedicated PostgreSQL database on vpn6, without disturbing existing vpn4 or vpn6 workloads.

**Approved scope:**

- Build the `vanbienperu3107/gatepro-client` revision `075d520` on vpn4.
- Run the API and renewal monitor on vpn4.
- Create an isolated PostgreSQL login role and database named `gatepro` on vpn6.
- Use the application-owned schema initialization command, `gatepro db init`.
- Expose port 8080 only on vpn4's Tailscale IPv4 address.
- Do not add a public hostname, Caddy/nginx route, public firewall rule, or Internet listener.

## Architecture

The deployment workflow runs manually from this repository and serializes vpn4 changes with the existing `deploy-vpn4-host` concurrency group. It first performs bounded, read-only preflight checks on both hosts. On vpn6 it creates the dedicated `gatepro` login role and database only when absent, configures PostgreSQL host access for vpn4's Tailscale address, and creates no application tables directly.

On vpn4 the workflow checks out the requested GatePro client revision into a dedicated deployment directory, builds an image locally, writes `/srv/gatepro/db.env` with a database DSN and Fernet encryption key under owner-only permissions, and mounts a separate configuration volume. It invokes `gatepro db init` from that image to apply the bundled `gatepro_client/schema.sql` idempotently, then starts `gatepro-api serve --with-monitor`.

The service publishes `vpn4-tailscale-ip:8080:8080`, never `0.0.0.0:8080` or a public host address. The API's GatePro identity is configured independently in `gatepro_config`: it must use vpn4's real egress address visible to GatePro, never its Tailnet address. This maintains the intended firewall-policy source identity while restricting API clients to the Tailnet.

## Data Boundaries

- `gatepro` PostgreSQL role owns only the `gatepro` database.
- Existing vpn6 databases and roles, including `derp`, `headscale`, and `opencode_remote`, are not modified or queried.
- `gatepro db init` is the sole schema-management operation. No workflow SQL creates, alters, or drops application tables.
- The Fernet key remains only in `/srv/gatepro/db.env` on vpn4. It is never committed, printed, or passed to an image build.
- The database password remains in the same private file; workflow logs must mask or avoid values derived from it.

## Runtime Boundaries

- The GatePro container receives a dedicated Docker volume for `api.env`, session cache, and service-account cache.
- The API requires its dedicated database and does not fall back to file-only state when the DSN is misconfigured.
- Existing DERP, CLIProxyAPI, edge proxy, and unrelated containers on vpn4 are snapshotted before and after deployment. A changed snapshot is a failed deployment.
- The workflow uses `--project-name gatepro-vpn4` and addresses only its own container, volume, deploy directory, database, and PostgreSQL access rule.

## Failure Handling And Rollback

Before starting the new service, the workflow records its transaction marker and any old GatePro container/image metadata. If image build, schema init, identity validation, startup, health check, Tailnet listener assertion, or unrelated-workload snapshot fails, it stops and removes only the new GatePro compose project and restores any pre-existing GatePro project state.

Database and role creation are intentionally retained on failure because they are isolated, reusable infrastructure and must not be dropped automatically while a failure is being investigated. Existing database data is never dropped. A separate manual teardown workflow may be designed later if removal is required.

## Acceptance Criteria

1. `gatepro` role can log in to its dedicated `gatepro` database, while access to existing vpn6 application databases is denied.
2. Application schema is initialized by `gatepro db init`, not handwritten deployment SQL.
3. vpn4 service reaches PostgreSQL only through vpn6's Tailnet address.
4. The API listens on vpn4's Tailnet address at port 8080 and is absent from public/all-interface listeners.
5. `GET /healthz` returns HTTP 200; protected endpoints return HTTP 401 without a bearer token.
6. The API account and Fernet key are not written into Git, build layers, or logs.
7. Existing vpn4 workloads retain their container start timestamp and restart count after success or automatic rollback.
8. Failure leaves no GatePro listener or running GatePro container on vpn4 unless it existed before this deployment.

## Test Matrix

| ID | Preconditions | Steps | Expected Result | Evidence |
| --- | --- | --- | --- | --- |
| TC-01 | PostgreSQL on vpn6 reachable over Tailnet | Provision role/database; attempt permitted and forbidden database connections | `gatepro` connection succeeds; existing application database connection is rejected | Redacted `psql` exit status and role/database query |
| TC-02 | Fresh dedicated database | Run containerized `gatepro db init` twice | Both runs succeed and required tables exist | Command status and table-name-only query |
| TC-03 | vpn4 Tailnet IP and vpn6 Tailnet IP discovered | Start service with DSN using vpn6 Tailnet address | API starts and database-backed `/connections` response succeeds | Redacted compose state and HTTP response fields |
| TC-04 | Service started | Inspect published ports and host listeners | Only `vpn4-tailscale-ip:8080` is bound | `docker inspect` and `ss -ltn` output |
| TC-05 | Service started | Call `/healthz`; call `/status` without token | 200 then 401 | HTTP status codes |
| TC-06 | vpn4 pre-deploy snapshot | Build and deploy, then compare unrelated snapshot | No unrelated workload timestamp or restart-count change | Before/after snapshot diff |
| TC-07 | Deliberately invalid non-secret configuration in a test run | Invoke deployment validation before start | Deployment aborts and removes only GatePro project resources | Transaction log and post-failure project state |

## Operational Decisions

- Database/role provisioning is idempotent and guarded by exact names; it never enumerates or alters other schemas.
- The workflow discovers Tailnet addresses on each target rather than embedding addresses in repository files.
- The first deployment creates the API account interactively through a protected GitHub secret. The workflow cannot invent this password.
- Starting the renewal monitor requires an enabled GatePro account and mailbox configuration. The deployment must leave the monitor disabled until those encrypted credentials and explicit identity are configured, or it risks repeated OTP attempts. The initial service launch therefore uses `serve` without `--with-monitor`; a subsequent guarded enablement change can add the monitor after live credentials are validated.

## Out Of Scope

- Public API exposure, DNS, TLS, Caddy, nginx, or Internet firewall changes.
- Creation of GatePro operator/mail credentials or automatic login to GatePro.
- Migration, backup, restoration, or modification of existing vpn6 databases.
- A destructive teardown workflow.
