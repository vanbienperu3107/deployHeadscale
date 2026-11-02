# CPA Bundle Router Design

## Purpose

CPA Bundle Router is a native CLIProxyAPI v8 plugin that exposes exactly three logical model aliases: `chat`, `research`, and `code`. Each alias routes to administrator-configured physical models using quality tiers, capability filtering, weighted selection, session affinity, bounded failover, cooldown, and streaming-safe execution.

The plugin does not implement OAuth, credential refresh, provider HTTP protocols, or a second credential scheduler. It delegates physical-model execution to CLIProxyAPI through verified host model callbacks.

## Compatibility Contract

The production target is the CLIProxyAPI v8 source revision `ae662a51649e085f5890aa0e3a9bca0d85a4911e` and its native C ABI. The Go module remains `github.com/router-for-me/CLIProxyAPI/v8`, while plugin API types currently reside under `github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi`.

The plugin exports `cliproxy_plugin_init` and implements:

- `model.register` to publish `chat`, `research`, and `code`.
- `model.route` to route those aliases to its executor.
- `executor.*` to delegate selected physical models through host callbacks.
- `usage.handle` to record host-supplied usage.
- `management.*` for authenticated operational API and dashboard assets.

Host callbacks required by the design are `host.model.execute`, `host.model.execute_stream`, `host.model.stream_read`, and `host.model.stream_close`. Native load, protocol fidelity, and host behavior must be verified with a disposable binary before compatibility is declared verified.

## Plugin Boundary

`ModelRouter.RouteModel` handles only `chat`, `research`, and `code`, returns a `self` target for those aliases, and returns `Handled: false` for all physical models. This prevents recursion when the executor calls host model callbacks.

`ProviderExecutor.Execute` and `ExecuteStream` own bundle resolution. Each selected target is executed through the host with original protocol, body, headers, query, stream flag and optional provider constraint. CLIProxyAPI keeps provider, credential, refresh, translation, transport and provider-specific behavior.

## Configuration

The plugin owns a versioned YAML schema. Physical model IDs are administrator policy and never hard-coded.

```yaml
schema_version: 1
storage:
  path: /var/lib/cli-proxy-api/bundle-router.sqlite
  retention_days: 90
bundles:
  chat:
    session_affinity:
      ttl: 1h
      max_entries: 10000
      trusted_session_header: X-Session-ID
    retry:
      max_attempts: 4
      initial_cooldown: 30s
      max_cooldown: 15m
    tiers:
      - name: premium
        targets:
          - model: CHAT_MODEL_A
            provider: optional-provider-key
            weight: 3
```

Each target can define provider, positive weight, capabilities/provenance, context window and optional pricing. Validation rejects missing or extra bundle aliases, empty tiers, duplicate model/provider pairs, non-positive weight, invalid affinity/cooldown limits, invalid capability data and logical alias recursion.

## Request Classification And Selection

Classification is deterministic: source protocol, stream flag, tools, structured output, reasoning hints, context estimate, client hints and trusted session header. It uses no LLM classifier and no model-name capability assumptions.

Unknown capabilities do not satisfy strict requirements. OpenAI Chat Completions is the baseline protocol. OpenAI Responses and Anthropic Messages require native host integration evidence before support can be claimed.

Selection order:

1. Resolve alias and hard requirements.
2. Use a valid session binding if it remains eligible.
3. Traverse tiers from highest quality downward.
4. Filter by capability, context, cooldown and prior attempts.
5. Select with concurrent smooth weighted round robin.
6. Descend only after the active tier has no eligible untried target.

## Affinity, Health And Failover

Affinity is bounded in-memory LRU keyed by a non-reversible hash of session ID plus bundle. It stores target, expiry and configuration revision only. Default TTL is one hour. Missing stable session identity means normal balancing, never a fabricated prompt hash.

Retryable failures are 429, 500, 502, 503, 504, classified transient network failures and safe upstream timeouts. Invalid client input, tool-schema errors, unsatisfiable context, configuration failure and auth failures are terminal. Credential-specific failures do not globally cool down a physical target.

Cooldown uses bounded exponential backoff with jitter and a half-open probe. A request never retries the same target.

## Streaming Safety

The executor starts candidates with `host.model.execute_stream`. Retry is allowed only before the first payload reaches the client. Once payload has been emitted, that stream is final, no fallback occurs, and terminal error is propagated. Context cancellation closes the host stream.

## Persistence And Observability

SQLite WAL stores configuration revisions, capability registry, aggregated usage and health summaries. Affinity, cooldown and scheduling stay in memory. Database failures never block inference.

Required low-cardinality metrics are `bundle_requests_total`, `bundle_fallback_total`, `bundle_errors_total`, `bundle_model_selected_total`, `bundle_affinity_hits_total`, `bundle_cooldown_total`, `bundle_request_duration_seconds`, and `bundle_upstream_duration_seconds`. Raw prompt, credential and session values never become metric labels.

Usage tracking separates logical alias from physical model. Costs are absent when no reliable pricing or usage exists.

## Management Dashboard

All dashboard routes use authenticated CLIProxyAPI management routes. Resource routes are intentionally excluded because the verified SDK marks them unauthenticated.

The dashboard covers overview, configuration revisions and rollback, and analytics. It validates all mutations, escapes untrusted data and never returns credential values.

## Testing And Evidence

Implementation follows TDD. T01-T30 map to unit, mock host, native ABI load, management authorization, persistence/restart, direct host regression, protocol and rollback tests. Mock evidence does not replace native ABI or live-provider evidence.

Required checks are `go test ./... -count=1`, `go test -race ./... -count=1` and `go vet ./...`. The current local environment lacks `gcc`, `cc` and `clang`, so native shared-library validation must run in GitHub Actions and disposable Ubuntu staging before Gate B or Gate D can pass.

## Delivery And Explicit Limitations

The repository ships MIT source, upstream attribution, CI, artifact checksums, example CPA/OpenCode configuration, Ubuntu systemd guidance, Grafana/Prometheus documentation, `preflight.sh`, and `install.sh` supporting dry-run, install, verify and rollback.

- `research` does not grant Internet access; tools remain client/host-provided.
- CLIProxyAPI retains OAuth and credential choice.
- Unknown strict capabilities are rejected.
- Linux arm64 is supported only after native arm64 build and ABI-load proof.
- No production installation or public release occurs without an explicit deployment/release authorization.
