# Portainer VPN4 Design

**Status:** Approved design, awaiting review of this written specification before implementation planning.

## Goal

Deploy a single Portainer Community Edition server to vpn4 so the operator can manage that host's existing standalone Docker environment at `https://portainer.hangocthanh.io.vn`, with a real TLS certificate and without exposing Portainer's administrative ports directly to the Internet.

## Confirmed Environment

The read-only survey ran successfully on vpn4 in GitHub Actions run `39467047869` on 2026-10-20. It established the following facts:

- Docker is standalone (`Swarm LocalNodeState: inactive`), rootful, with Docker Engine 29.6.0 and Compose 5.1.4.
- The Docker API socket is `/var/run/docker.sock`; it is usable by the deployment account through `sudo -n`.
- vpn4 has 3.8 GiB RAM, with 1.8 GiB available at the time of survey; 14 GiB disk space remains on `/`.
- `edge` is an external bridge network on `172.23.0.0/16` and contains `edge-nginx`, `caddy-edge`, `derper`, `cliproxy`, and `opencode-server`. It is shared ingress transport and is not a Portainer trust boundary.
- `edge-nginx` owns host TCP 443. `derper` owns host TCP 80 and UDP 3478. The Nginx SNI default must remain DERP.
- Host ports 8000, 9000, 9443, 8446, and 8447 were unbound during the survey.
- Existing Caddy listeners use 8444 for CLIProxyAPI and 8445 for OpenCode. Port 8447 is reserved for Portainer's internal TLS listener.
- DNS `portainer.hangocthanh.io.vn` resolves to vpn4, verified in survey run `39467047869`.
- The host deployment checkout was on `main` at `571736f` at survey time. Deployment must fetch the target branch/ref explicitly rather than assume its checkout is current.

## Scope

### In scope

- A `portainer-vpn4` Docker Compose stack with a Portainer CE LTS server.
- A private external `portainer_proxy` network shared only by Portainer and `caddy-edge`.
- SNI routing and Caddy TLS/reverse-proxy configuration for `portainer.hangocthanh.io.vn`.
- A manual GitHub Actions deploy workflow with DNS validation, deploy safeguards, and remote verification.
- Automated configuration/integration tests covering the new stack, routes, deploy policy, and rollback behavior.
- A narrowly scoped rollback workflow or documented rollback step that removes the Portainer container and routing, preserving Portainer data.

### Out of scope

- Docker Swarm, Portainer Agent, Portainer Edge Agent, Kubernetes, or management of another host.
- Publishing Portainer's 8000, 9000, or 9443 ports on the host.
- Changing Portainer's vendor UI or creating a new UI. The service uses Portainer's existing web UI.
- Recreating, stopping, or changing DERP, CLIProxyAPI, OpenCode, or fail2ban as part of a Portainer deploy. The only permitted edge changes are targeted Caddy/Nginx reload or recreation required to load the new exact SNI route.
- Backup transport or off-host backup automation. The persistent volume is identified and preserved; backup scheduling is a later task.

## Security Model

Portainer will mount `/var/run/docker.sock`. This grants it effective root-equivalent authority over Docker on vpn4: an authenticated Portainer administrator can create privileged containers, mount host paths, and affect all existing containers. The service is therefore treated as an administrative endpoint, not an ordinary application.

Controls:

- No Portainer administrative port is published to the host. The Compose service has no `ports:` section.
- The service is reachable only from `caddy-edge` over a dedicated private `portainer_proxy` network. It must not attach to the shared `edge` network, whose other members include DERP, CLIProxy, and OpenCode.
- Only the domain `portainer.hangocthanh.io.vn` maps through Nginx SNI to a dedicated Caddy listener.
- Caddy terminates TLS with Let's Encrypt via TLS-ALPN because derper owns host port 80; HTTP-01 must remain disabled for this domain.
- Every request passes Google SSO before Caddy proxies it to Portainer. `forward_auth` consults a dedicated `portainer-oauth2-proxy` and only `hangocthanh3107@gmail.com` is accepted, from the auditable allowlist `portainer-vpn4/allowed-emails.txt`.
- The Portainer administrator is created on first start from `--admin-password-file`, written on the host under `umask 077` from a GitHub secret. No credential is printed to workflow logs.
- `portainer_data` is a named volume and is never deleted in normal deploy or rollback paths.

### Incident that produced these two controls (2026-10-21)

Deploy run `39686831400` was reported as failed, but its rollback step never ran: the step forwarded `DEPLOY_PATH` through `envs:` without a matching `env:` block, so `DEPLOY_PATH` expanded to the empty string, the transaction marker was looked up under `/`, and the script exited 0 after 1.5 seconds while reporting success.

Portainer therefore stayed publicly reachable overnight with **no administrator account**. Portainer's own five-minute initialisation timeout was the only thing preventing takeover; anyone able to restart the container would have had a fresh window to claim the admin account. Two independent controls now close this:

1. The SSO gate means an unauthenticated request never reaches Portainer at all, initialised or not.
2. Bootstrapping the admin means no unclaimed window exists in the first place.

Additionally, the one-time setup token had been printed into that run's log. Diagnostics now redact it, and the exposed instance was removed.

## Architecture

```text
Browser
  |
  | TLS SNI: portainer.hangocthanh.io.vn:443
  v
edge-nginx (host 443, stream ssl_preread; does not decrypt TLS)
  |
  | SNI route to caddy-edge:8447 over network edge
  v
caddy-edge (TLS-ALPN certificate, Caddy listener 8447; member of edge + portainer_proxy)
  |
  | HTTP reverse_proxy portainer:9000 over private network portainer_proxy
  v
portainer (Portainer CE LTS; only member of portainer_proxy besides caddy-edge)
  |-- /var/run/docker.sock (Docker host authority)
  `-- portainer_data:/data (persistent configuration)
```

Nginx retains its current routes unchanged:

- `cliproxy.hangocthanh.io.vn` -> `caddy-edge:8444`
- `opencode.hangocthanh.io.vn` -> `127.0.0.1:8446` -> `caddy-edge:8445`
- default/unrecognized SNI -> `derper:443`

The new route is exact-match only:

- `portainer.hangocthanh.io.vn` -> `caddy-edge:8447`

The route must not use the existing OpenCode PROXY protocol path. Portainer does not use the OpenCode fail2ban policy and Caddy's 8447 listener must accept normal TLS directly from Nginx, like the existing 8444 CLIProxy listener.

## Service Definition

Create `portainer-vpn4/docker-compose.yml` with one service:

- Image: `portainer/portainer-ce:lts`.
- Container name: `portainer`.
- Restart policy: `unless-stopped`.
- Memory limit: `256m`.
- Command: `--http-enabled`. Current Portainer CE LTS serves HTTPS internally on 9443 by default; this explicitly enables private HTTP on 9000 for the existing Caddy TLS terminator. It does not publish 9000 to the host.
- No host port publication.
- Networks: the external network named `portainer_proxy`.
- Volumes:
  - `/var/run/docker.sock:/var/run/docker.sock`
  - `portainer_data:/data`
- No Compose `healthcheck`: Portainer CE LTS does not document an in-image HTTP probe tool or CLI health command, so declaring `curl`, `wget`, or a guessed flag would create a false health state. The deploy workflow verifies the live app through the TLS route with Portainer's public `GET /api/status` endpoint instead.
- JSON log rotation consistent with existing vpn4 Compose stacks: 10 MiB max file size, 3 retained files.

The stack must declare `portainer_proxy` as `external: true`, `name: portainer_proxy`. `caddy-edge` joins both `edge` and `portainer_proxy`; no other service may join the latter. The deploy workflow may create either external network only when it does not exist; normal Portainer deploy must not recreate either network.

`portainer_data` remains a named volume after a normal rollback. This protects the initial administrator configuration, endpoints, users, and stack metadata. The operator can intentionally remove it only in a separately reviewed destructive reset procedure.

## Edge Routing

Modify `edge-vpn4/nginx.conf`:

- Add `portainer.hangocthanh.io.vn caddy-edge:8447;` to the current SNI map.
- Preserve the default map value `derper:443` exactly.
- Do not alter the port-443 listener, proxy timeout, or OpenCode's second local listener.

Modify `edge-vpn4/Caddyfile`:

- Add an HTTPS site `https://portainer.hangocthanh.io.vn:8447`.
- Configure the ACME issuer with `disable_http_challenge`, matching the existing 8444 and 8445 sites.
- Reverse proxy to `portainer:9000`.
- Pass `X-Forwarded-Proto: https` and the original `Host` header so Portainer generates URLs for the browser-facing HTTPS origin.
- Keep Caddy admin disabled.
- Do not add a port listener or Docker host publication for Caddy.
- Add structured access logging to stdout only. Do not log authorization headers or Docker socket data.

The Caddy service already connects to `edge`; no compose-network change is needed for it. `caddy-edge` must be force-recreated only when the Caddyfile changes, because bind-mounted config is read during process startup.

## Deployment Workflow

Add `.github/workflows/deploy-portainer-vpn4.yml`, manually triggered only.

It shares `concurrency.group: deploy-vpn4-host` and sets `cancel-in-progress: false` so it does not race with deploys or emergency rollback of DERP/edge/CLIProxy.

### Pre-deploy checks

1. Resolve `portainer.hangocthanh.io.vn`; it must equal the resolved IP of `SSH_HOST_VPN4`.
2. Confirm all required GitHub secrets exist without printing them: `SSH_HOST_VPN4`, `SSH_USER`, `SSH_KEY`, `DEPLOY_PATH`.
3. SSH to vpn4 with the established `sudo -n` convention.
4. Fetch the requested ref and reset the deployment checkout to its `origin/<ref>` revision. This is necessary because the survey observed a stale checkout on vpn4.
5. Require `edge` to exist or create it only when absent.
6. Validate the candidate Nginx config in a disposable `nginx:1.27-alpine` container before changing running edge services.
7. Validate the Portainer Compose file with `docker compose config --quiet` without rendering environment secrets.
8. Capture a snapshot of all running containers excluding Portainer, recording name, restart count, and started-at time.

### Deploy sequence

1. Pull the pinned Portainer image.
2. Start or update only the `portainer-vpn4` stack with `docker compose --project-name portainer-vpn4 up -d --remove-orphans`. Every Portainer Compose command pins this project name so the persistent Docker volume is deterministically `portainer-vpn4_portainer_data`, independent of host `COMPOSE_PROJECT_NAME`.
3. Wait for Portainer to start, then verify Portainer's `GET /api/status` through the newly configured public TLS route. This is the application readiness check; no unsupported Compose healthcheck is declared.
4. Recreate only `caddy-edge` using the existing `edge-vpn4` Compose project and `--force-recreate`; do not run `docker compose up` for the entire edge project if it would recreate Nginx or fail2ban.
5. Reload or recreate only `edge-nginx` after a syntax preflight. This change is unavoidable because Nginx reads its SNI map at startup. It must be a targeted change and must be followed by an immediate DERP probe.
6. Verify that every pre-existing container except the three intentional deployment targets (`portainer`, `caddy-edge`, and `edge-nginx`) has the same restart count and started-at value as its pre-deploy snapshot. The two edge components are expected to recreate to load bind-mounted route changes. If any other container differs, fail the workflow and print the diff.

### Remote verification

1. Poll `https://portainer.hangocthanh.io.vn/` for an HTTP response indicating the Portainer UI is reachable through valid TLS. Redirects are acceptable; a connection/TLS failure is not.
2. Verify from vpn4 that no host listener exists on 8000, 9000, or 9443 after deployment.
3. Verify the Portainer service has no Compose `ports` mapping and is attached only to `portainer_proxy`.
4. Verify DERP remains reachable at `https://vpn4.hangocthanh.io.vn/derp/probe` with HTTP 200.
5. Verify the existing CLIProxy path `https://cliproxy.hangocthanh.io.vn/v1/models` retains its expected authentication behavior, without printing API keys.
6. Verify the existing OpenCode route still returns an authenticated response (401 without credentials is acceptable and expected).
7. Log the deployed source revision and the Portainer image digest/tag.

## Failure Handling and Rollback

The workflow must stop on an explicit deployment failure after collecting enough diagnostics to distinguish Portainer failure from edge routing failure.

Automatic recovery applies only to changes made by the workflow:

- If Portainer does not start, bring down only `portainer-vpn4`; preserve `portainer_data`.
- If the edge reload/recreate prevents DERP from returning HTTP 200, restore the previous Nginx and Caddy configuration from the deployment checkout's prior revision and target-recreate the affected edge component. Do not remove or recreate derper.
- If post-deploy snapshot detects an unrelated container restart, fail the workflow and do not automatically remove unrelated containers.

Provide a manual workflow or documented operational command to remove the Portainer container plus SNI/Caddy routes while preserving the named volume. Destruction of `portainer_data` is explicitly excluded.

## Acceptance Criteria

1. `https://portainer.hangocthanh.io.vn` serves Portainer through a valid publicly trusted TLS certificate.
2. Portainer manages the local standalone Docker endpoint through `/var/run/docker.sock`.
3. No host listener or published Compose port exists for 8000, 9000, or 9443.
4. The Portainer container is only connected to `portainer_proxy`; that network has exactly `portainer` and `caddy-edge`; and the service definition has a 256 MiB memory limit.
5. `portainer_data` persists Portainer state across an ordinary deploy/recreate and is preserved by rollback.
6. Existing DERP, CLIProxy, and OpenCode routes remain healthy after deployment.
7. Nginx's SNI default remains `derper:443`.
8. The deploy workflow performs DNS, syntax, snapshot, TLS, isolation, and regression checks, and uses the shared vpn4 concurrency group.
9. Rollback removes Portainer reachability without deleting its data volume or disturbing unrelated services.

## Test Strategy

### Static/unit tests

- Parse Portainer Compose and assert: LTS image, no `ports`, external `portainer_proxy`, socket/data mounts, `mem_limit: 256m`, restart policy, no unsupported image healthcheck, and log rotation.
- Parse Nginx/Caddy and assert: exact Portainer domain route to 8447, TLS-ALPN-compatible issuer, proxy to `portainer:9000`, no new default route, and no change to the DERP default.
- Parse deploy workflow and assert: dispatch-only, shared concurrency, DNS before edge changes, targeted component operations, no `down -v`, no data-volume deletion, no API-key echo, required verification commands, and snapshot comparison.
- Extend edge tests so new SNI/Caddy route is included alongside the existing cliproxy/OpenCode invariants.

### Integration

- Use a disposable local Compose project with an Nginx stream configuration and a backend stub/Portainer-compatible endpoint to assert SNI routing reaches the 8447 listener without changing the default DERP route.
- Validate Portainer Compose with `docker compose config --quiet`.

### Production CI verification

- The manual deploy workflow is the production integration test. It is PASS only after the remote verification list completes against the same target revision.
- Browser verification is required after deployment: load `https://portainer.hangocthanh.io.vn` in Playwright, capture an accessibility snapshot and desktop/mobile screenshots, confirm no new browser-console error, and confirm the login UI is readable and not clipped.

## Risks and Decisions

| Risk | Decision |
| --- | --- |
| Portainer controls Docker with root-equivalent authority | Expose only behind the dedicated HTTPS hostname; no direct admin ports; `portainer_proxy` limits private HTTP reachability to Caddy; Google SSO gate rejects every account except the single allowlisted address; admin bootstrapped at first start so no unclaimed window exists. |
| A rollback step silently does nothing and still reports success | Every SSH step that forwards a name through `envs:` must define it in `env:`; rollback aborts loudly when `DEPLOY_PATH` is empty rather than treating it as "no transaction to undo". Covered by `test_every_ssh_step_defines_env_values_for_the_names_it_forwards`. |
| A correct rollback is reported as failed | Route-retirement probes run under `set +e`: once the SNI route is gone, curl exits 35 and `VAR=$(curl ...) || true` would still abort under `bash -e`. |
| Docker network TOCTOU | The deploy workflow checks exact proxy-network membership before Portainer start and after Caddy/Nginx activation, then rolls back detected drift. Docker users able to attach a peer between checks already hold host-level Docker authority; absolute prevention requires host-level Docker authorization policy outside this scope. |
| vpn4 memory is constrained and other containers have no memory cap | Cap Portainer at 256 MiB; deployment checks actual memory and preserves existing workloads. |
| Nginx owns 443 and DERP must remain default SNI | Add only exact SNI mapping; verify DERP probe immediately after edge change. |
| Port 80 belongs to DERP | Use Caddy TLS-ALPN with HTTP-01 disabled. |
| Bind-mounted edge config is not reloaded automatically | Target-recreate only Caddy/Nginx after syntax validation; do not touch DERP/CLIProxy. |
| vpn4 checkout can be stale | Fetch and reset the requested ref before deployment, record deployed SHA. |
| Portainer data loss | Never use `down -v`, never remove `portainer_data` in deploy or rollback. |

## Open Items Resolved

- DNS was initially absent but was verified correct by survey run `39467047869`.
- The host is standalone Docker, so Portainer Agent and Swarm deployment are not part of this design.
- The approved service budget is 256 MiB, based on the survey's 1.8 GiB available memory.
