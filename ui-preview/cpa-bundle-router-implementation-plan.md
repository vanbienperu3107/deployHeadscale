# CPA Bundle Router Implementation Plan

**Goal:** Deliver a native CLIProxyAPI plugin exposing `chat`, `research`, and `code` with quality-tier routing, safe fallback, persistence, authenticated operations, native artifacts and verified compatibility.

**Architecture:** Native C ABI adapter exposes model registration, routing, executor, usage and authenticated management. The Go routing core independently validates policy, classifies requests, applies affinity/capability/tier/weight selection, records cooldown, and delegates physical model execution to CLIProxyAPI host callbacks. SQLite holds revision and aggregate telemetry; fast state stays in memory.

**Spec:** [CPA Bundle Router Design](./cpa-bundle-router-design.md)

## Global Constraints

- ID is `bundle-router`; logical aliases are only `chat`, `research`, `code`.
- No second OAuth, credential store, provider HTTP client or credential scheduler.
- Model IDs and providers are configuration only.
- Strict unknown capability means unsupported.
- No prompt, credential, raw session ID or OAuth data in DB/logs/metrics.
- No candidate retried twice; no streaming fallback after first payload.
- Management mutations are authenticated; no public `ResourceRoute` dashboard.
- Arm64 support needs a native arm64 build and ABI load proof.

## Task Sequence

1. **Foundation and test harness:** initialize Go module/Makefile/license, manual clock, scripted mock host, test matrix and attribution.
2. **Native ABI and aliases:** C ABI bridge, schema negotiation, `cliproxy_plugin_init`, three aliases, recursion guard, compatibility documentation.
3. **Policy and capabilities:** versioned YAML validation, strict capability provenance and placeholder-only examples.
4. **Tier routing:** smooth weighted round robin, highest-tier traversal and no duplicate candidate attempts.
5. **Affinity:** TTL LRU, session hash only, bounded memory, expiry/rebind/reload invalidation.
6. **Health:** retry classification, bounded exponential cooldown, half-open recovery and credential-specific 401 handling.
7. **Non-stream execution:** host callback delegation, same-tier 429/503 fallback, next-tier fallback only after exhaustion.
8. **Streaming execution:** retry before first output, terminal partial stream failure, cancellation propagation.
9. **Persistence and metrics:** SQLite WAL migrations/revisions/usage aggregates, bounded metrics and telemetry degradation safety.
10. **Management and dashboard:** authenticated overview/configuration/rollback/analytics endpoints, escaped embedded dashboard.
11. **Operations:** read-only preflight, guarded install/dry-run/verify/rollback scripts, systemd/OpenCode/backup/observability docs.
12. **CI and native evidence:** format, vet, unit/race/mock tests, vulnerability scan, native artifact checksums, disposable host ABI test and arm64 policy.

## Mandatory Evidence

- T01-T30 are mapped to unit, mock host, native ABI, persistence, browser management, direct host and rollback evidence.
- Every behavior starts with a failing test, followed by minimal code and full suite.
- Required Go checks: `go test ./... -count=1`, `go test -race ./... -count=1` and `go vet ./...`.
- Native `.so` load, staging, rollback and arm64 evidence must run on an appropriate toolchain/native environment. They cannot inherit PASS from mock tests or cross-compilation.

## Review Focus

- Reject unsupported host ABI schema before load.
- Never derive session identity from prompts.
- Credential-specific 401 must not cool down an otherwise healthy target.
- A stream that emitted bytes must terminate rather than fallback.
- SQLite telemetry failure must not block successful inference.

The full task-by-task plan with files, interfaces, RED/GREEN tests, commands and commit milestones is available in the repository version of this file and is intended for approval before code implementation.
