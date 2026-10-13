# Tavily Key Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a small service that manages multiple Tavily API keys, detects exhausted/rate-limited keys, fails over to healthy keys, and exposes both a web dashboard and MCP-compatible tools.

**Architecture:** The system has a backend key router, a persistent key/usage store, a dashboard UI, and an MCP/API adapter. Requests go through a single router that chooses a healthy key, records usage/failures, and retries with the next eligible key on Tavily quota/rate/auth errors.

**Tech Stack:** Node.js 22, TypeScript, Fastify, SQLite, React/Vite, MCP SDK, Vitest, Playwright.

**Spec:** `docs/specs/tavily-key-router.md`

## Global Constraints

- Tavily API keys must never be returned unmasked by any API or UI.
- Rotation must treat HTTP `401`, `403`, `429`, `432`, and `433` as key-scoped failover candidates.
- Usage polling must respect Tavily usage endpoint limit: no more than 10 usage requests per 10 minutes per environment.
- Dashboard must show per-key status: `healthy`, `cooling_down`, `exhausted`, `invalid`, `unknown`.
- The service must support at least 10 configured keys.
- The first implementation must not include multi-user auth unless explicitly added later.
- The system must not claim to bypass Tavily free-tier limits; UI copy must describe failover and observability, not quota evasion.

## Review Focus

- Duplicate keys: adding the same key twice should be rejected without revealing the full key.
- All keys exhausted: search should return a clear `no_healthy_key` error, not loop forever.
- Tavily `Retry-After`: cooldown should honor the header when present.
- Usage endpoint throttling: dashboard should show stale usage with timestamp instead of over-polling.
- Concurrent requests: router should not send too many parallel requests through the same key when load-balance mode is enabled.

---

### Task 1: Domain Model And Key Store

**Files:**

- Create: `src/server/keys/key-store.ts`
- Create: `src/server/keys/key-store.test.ts`
- Create: `src/server/db/schema.sql`
- Modify: `src/server/db/index.ts`

**Interfaces:**

- Consumes: SQLite connection from `getDb(): Database`.
- Produces: `createKey(input: CreateKeyInput): Promise<StoredKey>`, `listKeys(): Promise<StoredKey[]>`, `updateKeyStatus(id: string, patch: KeyStatusPatch): Promise<StoredKey>`, `maskTavilyKey(key: string): string`.

```ts
type KeyStatus = "healthy" | "cooling_down" | "exhausted" | "invalid" | "unknown";

type CreateKeyInput = {
  label: string;
  apiKey: string;
  accountGroup?: string;
};

type StoredKey = {
  id: string;
  label: string;
  maskedKey: string;
  encryptedKeyRef: string;
  accountGroup: string | null;
  status: KeyStatus;
  cooldownUntil: string | null;
  lastErrorCode: number | null;
  lastCheckedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

type KeyStatusPatch = {
  status?: KeyStatus;
  cooldownUntil?: string | null;
  lastErrorCode?: number | null;
  lastCheckedAt?: string | null;
};
```

- [ ] **Step 1: Write the failing key masking and duplicate-key tests**

```ts
import { describe, expect, it } from "vitest";
import { createKey, listKeys, maskTavilyKey } from "./key-store";

describe("key store", () => {
  it("masks Tavily keys without exposing the secret", () => {
    expect(maskTavilyKey("tvly-abcdefghijklmnopqrstuvwxyz")).toBe("tvly-abc...xyz");
  });

  it("rejects duplicate API keys", async () => {
    await createKey({ label: "primary", apiKey: "tvly-duplicate" });
    await expect(createKey({ label: "copy", apiKey: "tvly-duplicate" })).rejects.toThrow("duplicate_key");
  });

  it("lists only masked keys", async () => {
    await createKey({ label: "primary", apiKey: "tvly-secret-123456" });
    const keys = await listKeys();
    expect(keys[0].maskedKey).toContain("...");
    expect(JSON.stringify(keys)).not.toContain("tvly-secret-123456");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm vitest src/server/keys/key-store.test.ts`

Expected: FAIL because `key-store.ts` does not exist.

- [ ] **Step 3: Create SQLite schema**

Create `src/server/db/schema.sql` with table `tavily_keys`, including `id`, `label`, `key_hash`, `encrypted_key_ref`, `account_group`, `status`, `cooldown_until`, `last_error_code`, `last_checked_at`, `created_at`, and `updated_at`.

- [ ] **Step 4: Implement `key-store.ts`**

Use SHA-256 for `key_hash`. Store the raw key through the existing secret abstraction if available; otherwise store a local encrypted reference placeholder and keep the encryption implementation isolated behind `encryptedKeyRef`.

- [ ] **Step 5: Run tests to verify pass**

Run: `pnpm vitest src/server/keys/key-store.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/server/keys src/server/db
git commit -m "feat: add Tavily key store"
```

---

### Task 2: Key Router And Failover Policy

**Files:**

- Create: `src/server/tavily/key-router.ts`
- Create: `src/server/tavily/key-router.test.ts`
- Modify: `src/server/keys/key-store.ts`

**Interfaces:**

- Consumes: `listKeys(): Promise<StoredKey[]>`, `updateKeyStatus(id: string, patch: KeyStatusPatch): Promise<StoredKey>`.
- Produces: `selectKey(strategy: KeyStrategy): Promise<SelectedKey>`, `markTavilyFailure(input: TavilyFailureInput): Promise<void>`, `isFailoverStatus(status: number): boolean`.

```ts
type KeyStrategy = "round_robin" | "lowest_usage" | "load_balance";

type SelectedKey = {
  id: string;
  apiKey: string;
  maskedKey: string;
};

type TavilyFailureInput = {
  keyId: string;
  status: number;
  retryAfterSeconds?: number;
  now: Date;
};
```

- [ ] **Step 1: Write failing tests for failover status classification**

```ts
import { describe, expect, it } from "vitest";
import { isFailoverStatus } from "./key-router";

describe("isFailoverStatus", () => {
  it.each([401, 403, 429, 432, 433])("returns true for %s", (status) => {
    expect(isFailoverStatus(status)).toBe(true);
  });

  it.each([400, 404, 500, 502])("returns false for %s", (status) => {
    expect(isFailoverStatus(status)).toBe(false);
  });
});
```

- [ ] **Step 2: Write failing tests for cooldown behavior**

```ts
it("marks 429 key as cooling down using Retry-After", async () => {
  const key = await createKey({ label: "k1", apiKey: "tvly-k1" });

  await markTavilyFailure({
    keyId: key.id,
    status: 429,
    retryAfterSeconds: 60,
    now: new Date("2026-10-13T00:00:00.000Z"),
  });

  const keys = await listKeys();
  expect(keys[0].status).toBe("cooling_down");
  expect(keys[0].cooldownUntil).toBe("2026-10-13T00:01:00.000Z");
});
```

- [ ] **Step 3: Run tests to verify failure**

Run: `pnpm vitest src/server/tavily/key-router.test.ts`

Expected: FAIL because router does not exist.

- [ ] **Step 4: Implement `isFailoverStatus(status: number): boolean`**

Return `true` only for `401`, `403`, `429`, `432`, `433`.

- [ ] **Step 5: Implement `markTavilyFailure(input: TavilyFailureInput): Promise<void>`**

Behavior:

- `401` or `403`: mark key `invalid`.
- `429`: mark key `cooling_down`, using `Retry-After` when present; otherwise 60 seconds.
- `432` or `433`: mark key `exhausted`.
- Non-failover statuses: do not change key status.

- [ ] **Step 6: Implement `selectKey(strategy: KeyStrategy): Promise<SelectedKey>`**

Initial implementation supports `round_robin` only. It must skip `invalid`, `exhausted`, and `cooling_down` keys whose `cooldownUntil` is in the future. If no key is available, throw `no_healthy_key`.

- [ ] **Step 7: Run tests to verify pass**

Run: `pnpm vitest src/server/tavily/key-router.test.ts`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/server/tavily src/server/keys
git commit -m "feat: add Tavily key router failover"
```

---

### Task 3: Tavily Client Wrapper

**Files:**

- Create: `src/server/tavily/tavily-client.ts`
- Create: `src/server/tavily/tavily-client.test.ts`

**Interfaces:**

- Consumes: `selectKey(strategy: KeyStrategy): Promise<SelectedKey>`, `markTavilyFailure(input: TavilyFailureInput): Promise<void>`.
- Produces: `tavilySearch(input: TavilySearchInput): Promise<TavilySearchResult>`.

```ts
type TavilySearchInput = {
  query: string;
  searchDepth?: "basic" | "advanced";
  strategy?: KeyStrategy;
};

type TavilySearchResult = {
  answer?: string;
  results: Array<{
    title: string;
    url: string;
    content: string;
  }>;
  keyId: string;
  maskedKey: string;
};
```

- [ ] **Step 1: Write failing test for retrying with next key**

```ts
it("retries with the next healthy key after a Tavily quota response", async () => {
  const first = await createKey({ label: "k1", apiKey: "tvly-k1" });
  const second = await createKey({ label: "k2", apiKey: "tvly-k2" });

  mockTavily.forKey("tvly-k1").responds(432, { detail: "plan limit reached" });
  mockTavily.forKey("tvly-k2").responds(200, {
    answer: "ok",
    results: [{ title: "A", url: "https://example.com", content: "content" }],
  });

  const result = await tavilySearch({ query: "test" });

  expect(result.keyId).toBe(second.id);
  expect(result.answer).toBe("ok");

  const keys = await listKeys();
  expect(keys.find((key) => key.id === first.id)?.status).toBe("exhausted");
});
```

- [ ] **Step 2: Write failing test for all keys exhausted**

```ts
it("throws no_healthy_key when every key is exhausted", async () => {
  await createKey({ label: "k1", apiKey: "tvly-k1" });
  await createKey({ label: "k2", apiKey: "tvly-k2" });

  mockTavily.forAnyKey().responds(432, { detail: "plan limit reached" });

  await expect(tavilySearch({ query: "test" })).rejects.toThrow("no_healthy_key");
});
```

- [ ] **Step 3: Run tests to verify failure**

Run: `pnpm vitest src/server/tavily/tavily-client.test.ts`

Expected: FAIL because `tavily-client.ts` does not exist.

- [ ] **Step 4: Implement `tavilySearch(input: TavilySearchInput): Promise<TavilySearchResult>`**

Use Tavily `/search`. On failover status, call `markTavilyFailure`, select next key, and retry. Each key may be tried at most once per request.

- [ ] **Step 5: Run tests**

Run: `pnpm vitest src/server/tavily/tavily-client.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/server/tavily
git commit -m "feat: wrap Tavily search with key failover"
```

---

### Task 4: Usage Poller And Dashboard API

**Files:**

- Create: `src/server/tavily/usage-poller.ts`
- Create: `src/server/tavily/usage-poller.test.ts`
- Create: `src/server/routes/keys.ts`
- Create: `src/server/routes/keys.test.ts`

**Interfaces:**

- Consumes: `listKeys(): Promise<StoredKey[]>`, `updateKeyStatus(id: string, patch: KeyStatusPatch): Promise<StoredKey>`.
- Produces: `refreshUsage(now: Date): Promise<UsageRefreshResult>`, `GET /api/keys`, `POST /api/keys`, `POST /api/keys/:id/refresh-usage`.

```ts
type UsageRefreshResult = {
  refreshed: number;
  skipped: number;
  nextAllowedAt: string;
};

type KeyUsageView = {
  id: string;
  label: string;
  maskedKey: string;
  status: KeyStatus;
  usage: {
    usedCredits: number | null;
    totalCredits: number | null;
    lastCheckedAt: string | null;
    stale: boolean;
  };
};
```

- [ ] **Step 1: Write failing test for usage throttling**

```ts
it("does not refresh usage more than 10 times per 10 minutes", async () => {
  await createKey({ label: "k1", apiKey: "tvly-k1" });

  for (let i = 0; i < 10; i++) {
    await refreshUsage(new Date(`2026-10-13T00:0${i}:00.000Z`));
  }

  const result = await refreshUsage(new Date("2026-10-13T00:09:30.000Z"));

  expect(result.refreshed).toBe(0);
  expect(result.skipped).toBe(1);
  expect(result.nextAllowedAt).toBe("2026-10-13T00:10:00.000Z");
});
```

- [ ] **Step 2: Write failing API test for masked key list**

```ts
it("GET /api/keys returns masked key views", async () => {
  await createKey({ label: "primary", apiKey: "tvly-secret-123456" });

  const response = await app.inject({ method: "GET", url: "/api/keys" });

  expect(response.statusCode).toBe(200);
  expect(response.body).not.toContain("tvly-secret-123456");
  expect(response.json()[0].maskedKey).toContain("...");
});
```

- [ ] **Step 3: Run tests to verify failure**

Run: `pnpm vitest src/server/tavily/usage-poller.test.ts src/server/routes/keys.test.ts`

Expected: FAIL because files do not exist.

- [ ] **Step 4: Implement `refreshUsage(now: Date): Promise<UsageRefreshResult>`**

Call Tavily usage endpoint only when under the throttle window. Store usage snapshot with timestamp. If throttled, keep previous usage and mark it stale in API view.

- [ ] **Step 5: Implement key routes**

Routes:

- `GET /api/keys`: list masked keys plus usage view.
- `POST /api/keys`: add key with `label`, `apiKey`, optional `accountGroup`.
- `POST /api/keys/:id/refresh-usage`: refresh only one key if throttle permits.

- [ ] **Step 6: Run tests**

Run: `pnpm vitest src/server/tavily/usage-poller.test.ts src/server/routes/keys.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/server/tavily src/server/routes
git commit -m "feat: add Tavily usage API"
```

---

### Task 5: Dashboard UI

**Files:**

- Create: `src/web/pages/KeysDashboard.tsx`
- Create: `src/web/pages/KeysDashboard.test.tsx`
- Create: `src/web/api/keys.ts`
- Modify: `src/web/App.tsx`
- Test: `tests/e2e/keys-dashboard.spec.ts`

**Interfaces:**

- Consumes: `GET /api/keys`, `POST /api/keys`, `POST /api/keys/:id/refresh-usage`.
- Produces: dashboard route `/keys` and UI for key list, status, usage, add key, manual refresh.

- [ ] **Step 1: Write component test for key status rendering**

```tsx
it("renders key usage and status without exposing raw keys", async () => {
  mockApiKeys([
    {
      id: "key_1",
      label: "Primary",
      maskedKey: "tvly-abc...xyz",
      status: "healthy",
      usage: {
        usedCredits: 250,
        totalCredits: 1000,
        lastCheckedAt: "2026-10-13T00:00:00.000Z",
        stale: false,
      },
    },
  ]);

  render(<KeysDashboard />);

  expect(await screen.findByText("Primary")).toBeInTheDocument();
  expect(screen.getByText("tvly-abc...xyz")).toBeInTheDocument();
  expect(screen.getByText("250 / 1000")).toBeInTheDocument();
  expect(screen.queryByText(/tvly-secret/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run component test to verify failure**

Run: `pnpm vitest src/web/pages/KeysDashboard.test.tsx`

Expected: FAIL because dashboard does not exist.

- [ ] **Step 3: Implement `src/web/api/keys.ts`**

Export `fetchKeys`, `createKey`, and `refreshKeyUsage`.

- [ ] **Step 4: Implement `KeysDashboard.tsx`**

Show total keys, count per status, table with label, masked key, status, usage, last checked, refresh button, and add-key form.

- [ ] **Step 5: Add route `/keys` in `App.tsx`**

Wire the page into the app router.

- [ ] **Step 6: Run component test**

Run: `pnpm vitest src/web/pages/KeysDashboard.test.tsx`

Expected: PASS.

- [ ] **Step 7: Write E2E test**

```ts
test("operator can add a Tavily key and see masked status", async ({ page }) => {
  await page.goto("/keys");
  await page.getByLabel("Label").fill("Primary");
  await page.getByLabel("API key").fill("tvly-secret-123456");
  await page.getByRole("button", { name: "Add key" }).click();

  await expect(page.getByText("Primary")).toBeVisible();
  await expect(page.getByText(/tvly-.*\.\.\./)).toBeVisible();
  await expect(page.getByText("tvly-secret-123456")).not.toBeVisible();
});
```

- [ ] **Step 8: Run E2E browser test**

Run: `pnpm playwright test tests/e2e/keys-dashboard.spec.ts`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/web tests/e2e
git commit -m "feat: add Tavily key dashboard"
```

---

### Task 6: MCP Tools

**Files:**

- Create: `src/server/mcp/tavily-tools.ts`
- Create: `src/server/mcp/tavily-tools.test.ts`
- Modify: `src/server/mcp/index.ts`

**Interfaces:**

- Consumes: `tavilySearch(input: TavilySearchInput): Promise<TavilySearchResult>`, `listKeys(): Promise<StoredKey[]>`.
- Produces MCP tools: `tavily_search`, `tavily_key_status`.

- [ ] **Step 1: Write failing test for `tavily_key_status` tool**

```ts
it("returns masked key status through MCP", async () => {
  await createKey({ label: "Primary", apiKey: "tvly-secret-123456" });

  const result = await callMcpTool("tavily_key_status", {});

  expect(JSON.stringify(result)).toContain("Primary");
  expect(JSON.stringify(result)).toContain("...");
  expect(JSON.stringify(result)).not.toContain("tvly-secret-123456");
});
```

- [ ] **Step 2: Write failing test for `tavily_search` tool**

```ts
it("routes Tavily MCP search through the key router", async () => {
  await createKey({ label: "Primary", apiKey: "tvly-k1" });
  mockTavily.forKey("tvly-k1").responds(200, {
    answer: "ok",
    results: [{ title: "A", url: "https://example.com", content: "content" }],
  });

  const result = await callMcpTool("tavily_search", { query: "test" });

  expect(JSON.stringify(result)).toContain("ok");
  expect(JSON.stringify(result)).toContain("tvly-");
  expect(JSON.stringify(result)).not.toContain("tvly-k1");
});
```

- [ ] **Step 3: Run tests to verify failure**

Run: `pnpm vitest src/server/mcp/tavily-tools.test.ts`

Expected: FAIL because MCP tools do not exist.

- [ ] **Step 4: Implement MCP tool `tavily_key_status`**

Return list of keys with label, masked key, status, usage, and last checked timestamp.

- [ ] **Step 5: Implement MCP tool `tavily_search`**

Input: `{ query: string; searchDepth?: "basic" | "advanced" }`. Call `tavilySearch` and return answer/results plus masked key metadata.

- [ ] **Step 6: Register tools in `src/server/mcp/index.ts`**

Register both tools under the existing MCP server bootstrap.

- [ ] **Step 7: Run tests**

Run: `pnpm vitest src/server/mcp/tavily-tools.test.ts`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/server/mcp
git commit -m "feat: expose Tavily router through MCP"
```

---

### Task 7: End-To-End Verification And Documentation

**Files:**

- Create: `docs/tavily-key-router.md`
- Create: `docs/runbooks/tavily-quota-failover.md`
- Modify: `README.md`

**Interfaces:**

- Consumes all previous tasks.
- Produces operator documentation and final verification evidence.

- [ ] **Step 1: Write documentation**

Document how to add keys, how status transitions work, what `401`, `403`, `429`, `432`, `433` mean, how cooldown works, how to configure MCP client, and why this is failover/observability rather than quota evasion.

- [ ] **Step 2: Run unit tests**

Run: `pnpm vitest`

Expected: PASS.

- [ ] **Step 3: Run typecheck**

Run: `pnpm typecheck`

Expected: PASS.

- [ ] **Step 4: Run lint**

Run: `pnpm lint`

Expected: PASS.

- [ ] **Step 5: Run browser verification**

Run: `pnpm dev`, then visit `/keys` with Playwright.

Expected: dashboard loads, add-key form is visible, key table uses masked key only, and console has no errors.

- [ ] **Step 6: Run MCP smoke test**

Run MCP client against local server and call `tavily_key_status` and `tavily_search`.

Expected: both return masked key metadata and no raw API key.

- [ ] **Step 7: Commit**

```bash
git add docs README.md
git commit -m "docs: document Tavily key router operations"
```

---

## Self-Review

**Spec coverage:** Covered key storage, failover, usage polling, dashboard, MCP tools, docs, and verification.

**Step scan:** Each task has a failing test, implementation step, verification command, and commit step. No task requires the implementer to infer public interfaces.

**Type consistency:** `StoredKey`, `KeyStatus`, `KeyStrategy`, `TavilySearchInput`, and `KeyUsageView` are defined once and reused consistently.

**Review Focus coverage:** Duplicate keys are tested in Task 1. All keys exhausted and failover statuses are tested in Task 2 and Task 3. Usage throttling is tested in Task 4. Concurrent load-balance is listed as focus but deferred from initial implementation; if load-balance is required for v1, add a dedicated Task 8 before implementation.

**Proportion:** Plan is longer than the spec because it fixes interfaces and tests, but does not include implementation bodies beyond schemas and exact test assertions.
