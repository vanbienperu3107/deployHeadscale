# CPA Bundle Router Design

## Purpose

CPA Bundle Router is a native CLIProxyAPI v8 plugin that exposes exactly three
logical model aliases: `chat`, `research`, and `code`. Each alias routes to
administrator-configured physical models using quality tiers, capability
filtering, weighted selection, session affinity, bounded failover, cooldown,
and streaming-safe execution.

The plugin does not implement OAuth, credential refresh, provider HTTP
protocols, or a second credential scheduler. It delegates physical-model
execution to CLIProxyAPI through the verified host model callbacks.

## Compatibility Contract

The production target is the CLIProxyAPI v8 source revision
`ae662a51649e085f5890aa0e3a9bca0d85a4911e` and its native C ABI. The Go
module remains `github.com/router-for-me/CLIProxyAPI/v8`, while the plugin API
types currently reside under `github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi`.

The plugin exports the required native ABI entry point,
`cliproxy_plugin_init`, and implements these host capabilities:

- `model.register` to publish `chat`, `research`, and `code`.
- `model.route` to route those aliases to this plugin's executor.
- `executor.*` to delegate selected physical models through host callbacks.
- `usage.handle` to record usage supplied by the host.
- `management.*` for authenticated operational endpoints and dashboard assets.

The design is compatible with a host callback surface that offers
`host.model.execute`, `host.model.execute_stream`, `host.model.stream_read`,
and `host.model.stream_close`. Native load, protocol fidelity, and host
behavior must be verified against a disposable binary before declaring any
compatibility claim as verified.

## Plugin Boundary

`ModelRouter.RouteModel` handles only the aliases `chat`, `research`, and
`code`. It returns a `self` execution target for those aliases and returns
`Handled: false` for every physical model. This prevents recursive routing
when the executor calls host model callbacks.

`ProviderExecutor.Execute` and `ExecuteStream` own bundle resolution and
selection. For each selected target they call the host with the original
protocol, translated request body, headers, query values, stream flag, and an
optional forced provider. CLIProxyAPI then applies its normal provider,
credential, refresh, translation, transport, and provider-specific behavior.

This division is intentional: `model.route` executes before host provider and
credential selection, whereas executor callbacks can perform bounded retries
over physical models without reimplementing OAuth or upstream HTTP handling.

## Configuration

Plugin configuration has a versioned YAML schema. Physical model IDs are
administrator policy and are never baked into code.

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
            capabilities:
              openai_chat: verified-integration
              streaming: verified-provider-docs
              tool_calling: manually-configured
              structured_output: unknown
              reasoning: unknown
              context_window: 128000
      - name: fallback
        targets:
          - model: CHAT_MODEL_B
            weight: 1
  research: { tiers: [] }
  code: { tiers: [] }
```

The real example will provide complete valid `research` and `code` routes;
the abbreviated design snippet above only documents the shape. Every target
may carry an optional provider restriction, positive integer weight,
capabilities, provenance, context window, and pricing metadata. Pricing is
optional and unknown pricing is never shown as a value.

Validation rejects missing or extra bundle aliases, an empty tier, duplicate
physical model/provider pairs within one bundle, non-positive weights,
invalid cooldown or affinity bounds, malformed capability data, and targets
that point back to the logical aliases.

## Request Classification And Selection

The classifier is deterministic and parses only supported request metadata:
source protocol, stream flag, tool definitions, structured-output requests,
reasoning request hints, context/token estimate, client routing hints, and a
configured trusted session header. It does not infer capability from model
names or invoke another model.

Capability filtering happens before balancing. A target whose capability is
unknown cannot satisfy a strict requirement. Targets must support the inbound
protocol and streaming when requested; OpenAI Chat Completions is the baseline
protocol. OpenAI Responses and Anthropic Messages are included only after the
native host integration proves their input/output callback behavior.

Selection order is:

1. Resolve the requested alias and classify hard requirements.
2. Use a live valid session binding if it still meets requirements and is not
   in cooldown.
3. Traverse quality tiers from highest to lowest.
4. Filter each tier by capabilities, context capacity, cooldown, and targets
   already attempted by this request.
5. Choose using concurrency-safe smooth weighted round robin.
6. Descend only when the current tier has no eligible untried target.

Quality is declared by the administrator through tier ordering. The router
does not claim an automatic quality ranking.

## Affinity, Health, And Failover

Affinity is a bounded in-memory LRU keyed by a non-reversible hash of the
session ID and bundle. It stores the chosen target, expiry, and configuration
revision only. It never stores prompts or conversation content. Default TTL is
one hour; bindings expire, are invalidated on configuration reload when the
target disappears, and rebind after a failed target. Requests without stable
session identity receive normal balancing and no fabricated prompt hash.

Health state is target-level and in memory. Retryable failures are 429,
500, 502, 503, 504, classified transient network errors, and safe upstream
timeouts. Client validation failures, tool-schema errors, context impossibility,
plugin configuration failures, and authorization failures are terminal.
Credential-specific failures are attributed in metrics but do not globally
cool down the physical target.

Failures use bounded exponential cooldown with jitter and a half-open probe.
No request retries a target twice. Retry budget applies to every tier and
request. A recovered target re-enters eligibility only after its cooldown and
probe policy permit it.

## Streaming Safety

The executor starts each candidate with `host.model.execute_stream`. Before
the first payload reaches the caller, a classified retryable start/read failure
can select the next eligible candidate. Once any payload is emitted, the
selection is final: no candidate is retried, no streams are concatenated, and
the terminal error is propagated. Context cancellation or client disconnect
closes the host stream. This protects protocol framing, tool-call ordering,
and non-idempotent work from duplicate execution.

## Persistence And Observability

SQLite, with WAL where supported, stores configuration revisions, capability
registry data, aggregated usage, and operational health summaries. Hot routing
state and session affinity remain in memory. A database error is reported and
metered but cannot block inference. Migrations are transactional. Retention,
backup, restore, and revision rollback are documented and exposed through
authenticated management actions.

Metrics have only low-cardinality labels such as bundle, target, tier, and
error class. Required names are `bundle_requests_total`,
`bundle_fallback_total`, `bundle_errors_total`,
`bundle_model_selected_total`, `bundle_affinity_hits_total`,
`bundle_cooldown_total`, `bundle_request_duration_seconds`, and
`bundle_upstream_duration_seconds`. No prompt, credential, or session value is
ever a metric label.

The usage observer persists only host-supplied bundle/model/request aggregate
metadata and token counts. It does not persist prompt bodies. It distinguishes
logical alias usage from physical-model usage. Costs are omitted unless a
configured price source applies to the model and usage data is present.

## Management Dashboard

Management routes are authenticated by CLIProxyAPI's management middleware.
The design deliberately does not expose a `ResourceRoute`, because resource
routes are unauthenticated in the verified host SDK.

The dashboard comprises:

- Overview: bundle health, active selections, requests, latency, cooldowns,
  error and fallback rates.
- Configuration: edit, validate, apply, and rollback revisions of tiers,
  targets, weights, affinity, cooldown policy, and capabilities.
- Analytics: requests, token counts, latency distribution, selection mix,
  fallback frequency, and affinity hit rate.

Handlers validate every payload, escape untrusted fields in HTML, return no
credential data, and use atomic configuration swaps. The browser only calls
authenticated management endpoints.

## Testing And Evidence

Implementation uses test-driven development. Each production behavior begins
with a failing Go test, followed by minimal code and a full test run.

The mandatory test matrix T01-T30 is mapped to unit, mock-host integration,
native ABI load, management authorization, persistence/restart, direct-host
regression, protocol, and rollback tests. Test status is reported separately as
PASS, FAIL, BLOCKED, or NOT_RUN. Mock host tests do not substitute for native
host ABI integration or live-provider validation.

The required local checks are `go test ./... -count=1`,
`go test -race ./... -count=1`, and `go vet ./...`. Native build/load validation
also requires a C compiler; this development environment currently lacks
`gcc`, `cc`, and `clang`, so this must run in GitHub Actions and a disposable
Ubuntu staging system before Gate B or Gate D passes.

## Delivery And Operations

The repository ships MIT source, explicit upstream attribution, CI workflows,
per-architecture release archives and checksums, example CPA/OpenCode config,
Ubuntu systemd documentation, Grafana/Prometheus integration documentation,
and non-destructive `preflight.sh` plus `install.sh` supporting `--dry-run`,
`--install`, `--verify`, and `--rollback`.

Linux amd64 is the first native target. Linux arm64 is marked supported only
after a native arm64 build and ABI-load verification. No production install or
public release occurs without an explicit deployment/release authorization.

## Explicit Limitations

- Selecting `research` never grants Internet access. Tools/search remain a
  client- or host-provided capability.
- Provider authentication and credential choice stay in CLIProxyAPI. The
  plugin controls model-target policy, not OAuth state.
- Unknown strict capabilities are rejected rather than assumed.
- Protocol support is evidence-based: OpenAI Chat is the initial baseline;
  Responses and Anthropic support require native compatibility evidence.
- The host may change plugin API semantics independently of the v8 module
  major version; `docs/compatibility.md` must record exact tested commits and
  verified behavior.
