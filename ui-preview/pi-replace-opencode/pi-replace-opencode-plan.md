# Pi thay thế OpenCode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay OpenCode 1.18.33 bằng Pi coding agent (`@earendil-works/pi-coding-agent` 1.1.x) làm harness agent chính của người dùng, giữ nguyên CLIProxy, 13 MCP, skills, memory, chính sách quyền và truy cập từ điện thoại; chạy song song có rollback cho tới khi cắt chuyển.

**Architecture:** `coworker-harness` (LangGraph JS + Pi RPC Adapter + Evidence Ledger) là control plane độc lập, giữ trạng thái workflow/gate/checkpoint; Pi chỉ là executor chạy trong Git worktree. Hành vi riêng của workspace (chặn quyền kiểu OpenCode, memory blocks, Google AI search, Figma token, workflow gate, giới hạn thư mục) được port thành **Pi extensions** trong package nội bộ `pi-workspace-kit`. `pi-server` (Pi + extensions + bridge pi-mobile) chỉ được chạy trên worker có đủ RAM hoặc theo staged takeover, không co-host song song một cách không an toàn với `opencode-server` trên vpn4; truy cập từ xa chỉ qua tailnet và rollback là bật lại OpenCode.

**Tech Stack:** Pi 1.1.x (Node ≥22.19), LangGraph JS 1.5.0 + `@langchain/langgraph-checkpoint-postgres` 1.1.0, TypeScript + vitest, pi-mobile bridge (Node 24, pnpm 10.33), pi-tau-web-server 1.1.x, PostgreSQL, Docker Compose, GitHub Actions (repo `TelegramAgent`, `deployHeadscale`), Python pytest cho test compose/policy hiện có.

**Spec:** Không có spec riêng. Plan này dựa trên các nguồn đã kiểm chứng trong phiên 2026-10-07 → 2026-10-13:
- Kiến trúc đích: `AI_Coworker_Architecture_Plan_v3.7.md` (người dùng đính kèm).
- Bằng chứng chạy thật trong `/tmp/pi-eval/` (Pi 1.1.0 + CLIProxy + 13 MCP + extension quyền + RPC + compaction + pi-web + Tau + pi-mobile bridge + H1 LangGraph/Pi worktree gate). Bảng kết quả ở Phụ lục A.
- Cấu hình OpenCode hiện tại: `/home/node/.config/opencode/opencode.json`, `AGENTS.md`, `.opencode/workflow-policy.md`, `feature-workflow.md`, `RESEARCH-MCP-POLICY.md`.
- Hạ tầng hiện tại: repo `vanbienperu3107/TelegramAgent` (`docker-compose.yml`, `docker/Dockerfile.opencode-server`, `.github/workflows/deploy.yml`, `tests/test_compose.py`).

## Global Constraints

- Pi phiên bản ghim chính xác `@earendil-works/pi-coding-agent@1.1.0` (không `latest`, không `^`). Nâng cấp là một PR riêng có chạy lại Task 12.
- Node runtime trong image Pi: `node:22-bookworm-slim` (≥22.19.0). Bridge pi-mobile cần Node `>=24` → chạy bằng binary Node 24 riêng trong cùng image, ghim `v24.21.0` kèm kiểm sha256.
- Model mặc định: `cliproxy/claude-opus-5`; provider `cliproxy` dùng `api: "openai-completions"`, `baseUrl: "http://cliproxy:8317/v1"`; khoá đọc bằng `"apiKey": "!tr -d '\\n' < /run/secrets/cliproxy-key"`. Không bao giờ ghi khoá literal vào file.
- Telemetry tắt: `PI_TELEMETRY=0`, settings `enableInstallTelemetry: false`, `enableAnalytics: false`.
- Container Pi **không** có `ports:`; mọi service có `mem_limit`, `oom_score_adj`, giới hạn log — giữ đúng các test trong `tests/test_compose.py`. Tổng `mem_limit` các service trên vpn4 ≤ 1856 MB (`test_tong_ngan_sach_ram_khong_vuot_1856mb`).
- **Không co-host full Pi và OpenCode trên vpn4 trong pha song song.** Ngân sách hiện hữu là `opencode-server 1536m + telegram-gateway 256m + pg-tunnel 64m = 1856m`, đã chạm trần. `coworker-harness`/`pi-server` phải dùng worker riêng có ít nhất 1.5 GB RAM rảnh theo preflight, hoặc takeover có kiểm soát sau khi stop OpenCode. H1 đo 316 MB đỉnh không MCP; không được suy ra đủ RAM cho Pi production có MCP.
- Thư mục skills: `/opt/skills` (ro) và `/workspace/.skills-global`. Memory: giữ file Markdown hiện có `/home/node/.config/opencode/memory/*.md` và `<project>/.opencode/memory/project.md` làm nguồn dữ liệu (không copy, không đổi định dạng frontmatter).
- Chính sách bash phải tương đương block `permission.bash` hiện tại: `*` allow; deny `rm *`, `sudo *`, `systemctl *`, `docker *`, `kubectl *`, `git reset --hard*`; `github_*` MCP = ask. Lệnh nối (`&&`, `||`, `;`, `|`, xuống dòng) đánh giá từng đoạn, nghiêm nhất thắng. `ask` không có UI ⇒ block.
- Bridge chỉ bind trong mạng Docker/tailnet, xác thực Bearer token, `bridge_set_cwd` chỉ chấp nhận thư mục trong allowlist `/workspace/Project` và `/workspace/opencode-sandbox` (sau `realpath`).
- Không push thẳng `main`; mỗi task một branch/PR; dùng `/workspace/.bin/gh`. Secrets chỉ qua GitHub Actions secrets hoặc `/run/secrets`.
- Ngôn ngữ thông báo người dùng trong extension: tiếng Việt có dấu.
- Reviewer Normal, High, XHigh chạy bằng **ba Pi process riêng** (`reviewer_run_id` khác nhau), profile chỉ đọc; không chấp nhận self-review của worker. Reviewer bị giới hạn 8 tool calls và output bắt buộc là JSON `GateVerdict` để tránh loop đọc lặp vô hạn.
- Mỗi Git worktree là một phạm vi CodeGraph độc lập: Harness phải chạy `codegraph init <worktree> --yes` trước discovery và `codegraph sync <worktree>` sau mọi source edit. Không dùng index của checkout gốc cho worktree.

## Review Focus

1. **Lệnh nguy hiểm đi vòng qua codemode/MCP hoặc qua `user_bash` (`!cmd` trong TUI)** — người dùng mong chặn giống OpenCode bất kể đường gọi. Test thêm ở Task 2 (`blocks_user_bash_rm`, `blocks_mcp_github_inside_codemode`).
2. **Bridge nhận `cwd` là symlink trỏ ra ngoài allowlist** (`/workspace/Project/link -> /home/node/.ssh`) — phải bị từ chối sau `realpath`. Test ở Task 7 (`rejects_symlink_escape`).
3. **Hai thiết bị cùng điều khiển một session, máy trước rớt mạng** — máy sau phải giành quyền sau tối đa `BRIDGE_RECONNECT_GRACE_MS` (đặt 30000) chứ không treo vĩnh viễn. Test ở Task 7 (`second_device_takes_control_after_grace`).
4. **Container Pi bị OOM/restart giữa lượt chạy** — phiên phải resume được từ file JSONL, không mất lịch sử. Test ở Task 9 (`session_survives_container_restart`).
5. **Memory block vượt `limit` hoặc frontmatter hỏng** — tool phải từ chối ghi và báo lỗi, không cắt cụt hay ghi đè mất dữ liệu. Test ở Task 3 (`rejects_over_limit`, `rejects_corrupt_frontmatter_without_writing`).

---

## File Structure

### Ownership Boundary — dùng sẵn vs. tự phát triển

| Năng lực | Dùng sẵn | Chủ sở hữu state | Tự phát triển thêm |
|---|---|---|---|
| Agent loop, tools, session JSONL, compaction | Pi 1.1 RPC | Pi `SessionManager` | Pi RPC Adapter chỉ chuẩn hoá event thành `TaskEvent` |
| Model/MCP | CLIProxy + 13 MCP Pi-native | Provider/MCP server | Converter OpenCode → `mcp.json`, profile tool theo role |
| Quyền trong agent | Pi `tool_call`, `user_bash`, UI RPC | Pi extension runtime | `pi-workspace-kit` policy/guard/memory/gate |
| Worktree, SHA, evidence, gate, push/CI | Git/GitHub Actions | **Coworker Harness/Postgres** | `WorktreeManager`, `EvidenceLedger`, deterministic checks |
| Workflow dài, fan-out, retry, approval, resume | LangGraph JS | **LangGraph PostgresSaver** | graph nodes và API run/resume |
| Mobile/web agent terminal | pi-mobile bridge, Tau | Pi session/bridge | fork bridge để allowlist cwd/ẩn path |
| UI Coworker chính | Open WebUI | Open WebUI chat/history | Gateway tool/pipe gọi `coworker-harness` (H2, ngoài H1) |

**Quy tắc:** LangGraph checkpoint trả lời “workflow đang ở node nào”; Pi JSONL trả lời “agent đã thấy và làm gì”; ledger trả lời “claim/gate/check nào đáng tin cho SHA nào”. Không sao chép chat history, raw Pi transcript hoặc semantic context blob vào LangGraph state.

Repo mới **`vanbienperu3107/pi-workspace-kit`** (Pi package nội bộ, TypeScript):

```
pi-workspace-kit/
├── package.json                  # "pi": { "extensions": [...], "skills": [], "prompts": [...] }
├── tsconfig.json
├── vitest.config.ts
├── src/
│   ├── shared/test-harness.ts    # fake ExtensionAPI cho unit test
│   ├── permission/policy.ts      # glob + chain evaluation (thuần, không I/O)
│   ├── permission/index.ts       # đăng ký tool_call + user_bash handler
│   ├── memory/store.ts           # đọc/ghi block Markdown + frontmatter
│   ├── memory/index.ts           # tools memory_list/memory_set/memory_replace + inject vào system prompt
│   ├── google-search/index.ts    # tool google_ai_search_plus (port từ plugin OpenCode)
│   ├── figma-token/index.ts      # chạy figma-token-sync.py khi session_start
│   ├── workspace-guard/index.ts  # chặn write/edit/bash ngoài allowlist cwd
│   └── workflow-gate/index.ts    # chỉ status/commands; push luôn bị chặn
├── prompts/                      # analyze.md implement.md review.md verify.md
├── agents/                       # workflow-analyst.md workflow-implementer.md workflow-reviewer.md
└── test/                         # *.test.ts tương ứng từng module
```

Repo mới **`vanbienperu3107/coworker-harness`** (LangGraph control plane, TypeScript):

```
coworker-harness/
├── package.json
├── src/
│   ├── graph/state.ts              # Annotation state: IDs/versions, never raw context
│   ├── graph/h1-code-flow.ts       # create_worktree → Pi → checks → reviews → approval → push/CI
│   ├── pi/rpc-client.ts            # strict JSONL Pi RPC child-process adapter
│   ├── pi/executor.ts              # worker/reviewer profile + TaskEvent mapping
│   ├── workspace/worktree.ts       # only component allowed to git worktree add/remove
│   ├── evidence/ledger.ts          # Postgres task_event/check_run/gate_verdict writes
│   ├── api/run-service.ts          # invoke/resume/status API, no direct shell access
│   └── config.ts                   # model profiles, limits, worker endpoint
├── test/                           # graph, adapter, worktree, ledger integration tests
└── scripts/h1-acceptance.mjs       # AC-H1 flow with a disposable fixture repo
```

Repo **`vanbienperu3107/TelegramAgent`** (sửa sau H1):

```
docker/Dockerfile.pi-server       # tạo mới
docker/pi/models.json.template    # tạo mới
docker/pi/settings.json           # tạo mới
docker/pi/mcp.json.template       # tạo mới (13 server)
docker/pi/APPEND_SYSTEM.md        # tạo mới — gộp instructions
docker/pi/entrypoint.sh           # tạo mới — bridge + tau
docker-compose.pi-worker.yml      # tạo mới — deployment worker riêng, volume pi_data
scripts/pi/convert-opencode-config.py   # tạo mới
scripts/pi/verify-pi-config.cjs         # tạo mới
scripts/pi/smoke.sh                     # tạo mới
.github/workflows/build-images.yml      # thêm build pi-server
.github/workflows/deploy-pi-worker.yml  # tạo mới — preflight worker → deploy → smoke Pi
.github/workflows/pi-acceptance.yml     # tạo mới (Task 12)
tests/test_compose.py                   # thêm test cho pi-server
tests/test_pi_config.py                 # tạo mới
```

Fork **`vanbienperu3107/pi-mobile`** (từ `ayagmar/pi-mobile`), sửa `bridge/src/server.ts` + `bridge/src/config.ts` + test.

---

### Task 1: Khởi tạo package `pi-workspace-kit` và test harness

**Files:**
- Create: `package.json`, `tsconfig.json`, `vitest.config.ts`, `src/shared/test-harness.ts`, `test/harness.test.ts`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces:
  - `createFakePi(): FakePi` với `FakePi.on(event, handler)`, `FakePi.emit<T>(event, payload, ctx?): Promise<T[]>`, `FakePi.tools: Map<string, ToolDef>`, `FakePi.commands: Map<string, CommandDef>`, `FakePi.registerTool`, `FakePi.registerCommand`.
  - `fakeCtx({ hasUI?: boolean, select?: (title, options) => Promise<string|undefined>, cwd?: string }): ExtensionContext`.
  - `package.json` field `"pi": { "extensions": ["./src/permission/index.ts", "./src/memory/index.ts", "./src/google-search/index.ts", "./src/figma-token/index.ts", "./src/workspace-guard/index.ts", "./src/workflow-gate/index.ts"], "prompts": ["./prompts"] }`.
  - devDependency `@earendil-works/pi-coding-agent@1.1.0` (chỉ để lấy type), `vitest`, `typescript`.

- [ ] **Step 1: Write the failing test** `test/harness.test.ts`

```ts
it("fake pi dispatches tool_call and returns handler results in order", async () => {
  const pi = createFakePi();
  pi.on("tool_call", async () => undefined);
  pi.on("tool_call", async () => ({ block: true, reason: "x" }));
  const r = await pi.emit("tool_call", { toolName: "bash", input: { command: "ls" } }, fakeCtx());
  expect(r).toEqual([undefined, { block: true, reason: "x" }]);
});
```

- [ ] **Step 2: Run** `npx vitest run test/harness.test.ts` — Expected: FAIL (`createFakePi` not defined)
- [ ] **Step 3: Implement `createFakePi()` và `fakeCtx()`** trong `src/shared/test-harness.ts` (Map handler theo event, gọi tuần tự, `await`).
- [ ] **Step 4: Run** `npx vitest run` — Expected: PASS; `npx tsc --noEmit` exit 0
- [ ] **Step 5: CI** `.github/workflows/ci.yml`: Node 22.19, `npm ci && npx tsc --noEmit && npx vitest run` trên push mọi branch.
- [ ] **Step 6: Commit** `git commit -m "chore: scaffold pi-workspace-kit with fake extension harness"`

### Task 2: Extension chặn quyền tương đương OpenCode

**Files:**
- Create: `src/permission/policy.ts`, `src/permission/index.ts`, `test/permission.policy.test.ts`, `test/permission.extension.test.ts`

**Interfaces:**
- Consumes: `createFakePi`, `fakeCtx` (Task 1).
- Produces:
  - `type Action = "allow" | "ask" | "deny"`
  - `interface PermissionRules { bash: Array<[glob: string, action: Action]>; tools: Array<[pattern: string, action: Action]> }`
  - `const DEFAULT_RULES: PermissionRules` — bash đúng Global Constraints; tools: `[["mcp__github__*", "ask"]]`.
  - `decideBash(command: string, rules: PermissionRules): Action` — last-match-wins mỗi đoạn, nghiêm nhất giữa các đoạn.
  - `decideTool(toolName: string, rules: PermissionRules): Action`
  - default export `(pi: ExtensionAPI) => void` đăng ký `tool_call` và `user_bash`.
  - Đọc override từ `<agent-dir>/permission.json` nếu có (cùng schema `PermissionRules`).

- [ ] **Step 1: Write failing policy tests**

```ts
it.each([
  ["ls -la", "allow"], ["rm -rf /tmp/x", "deny"], ["sudo id", "deny"],
  ["git reset --hard HEAD~1", "deny"], ["docker ps", "deny"],
  ["echo hi && rm -rf x", "deny"], ["echo a; sudo id", "deny"],
  ["cat f | kubectl apply -f -", "deny"], ["git status", "allow"],
])("decideBash(%s) = %s", (cmd, want) => expect(decideBash(cmd, DEFAULT_RULES)).toBe(want));
it("mcp github is ask", () => expect(decideTool("mcp__github__get_me", DEFAULT_RULES)).toBe("ask"));
it("other mcp allow", () => expect(decideTool("mcp__research_search__searxng_web_search", DEFAULT_RULES)).toBe("allow"));
```

- [ ] **Step 2: Write failing extension tests**

```ts
it("deny returns block with Vietnamese reason", async () => {
  const [r] = await emitToolCall("bash", { command: "rm -rf x" }, fakeCtx({ hasUI: true }));
  expect(r).toEqual({ block: true, reason: "Bị chặn bởi chính sách: rm -rf x" });
});
it("ask without UI blocks", async () => {
  const [r] = await emitToolCall("mcp__github__get_me", {}, fakeCtx({ hasUI: false }));
  expect(r?.block).toBe(true);
});
it("ask with UI 'Cho phép' allows", async () => {
  const [r] = await emitToolCall("mcp__github__get_me", {}, fakeCtx({ hasUI: true, select: async () => "Cho phép" }));
  expect(r).toBeUndefined();
});
it("blocks_user_bash_rm", async () => {
  const [r] = await pi.emit("user_bash", { command: "rm -rf x" }, fakeCtx({ hasUI: true }));
  expect(r).toMatchObject({ result: { exitCode: 1 } });
});
it("blocks_mcp_github_inside_codemode", async () => {
  // codemode phát tool_call riêng cho từng MCP tool — đã đo ở Phụ lục A dòng A9
  const [r] = await emitToolCall("mcp__github__get_me", {}, fakeCtx({ hasUI: false }));
  expect(r?.block).toBe(true);
});
```

- [ ] **Step 3: Run** `npx vitest run test/permission*` — Expected: FAIL
- [ ] **Step 4: Implement** `policy.ts` (glob → RegExp, `*` = `.*`, dotall; tách chuỗi bằng `/&&|\|\||;|\||\n/`) và `index.ts` (UI select với lựa chọn `["Cho phép", "Từ chối"]`; `user_bash` trả `{ result: { exitCode: 1, output: reason } }` khi deny).
- [ ] **Step 5: Run** `npx vitest run` — Expected: PASS
- [ ] **Step 6: Commit** `feat(permission): port OpenCode bash/MCP permission policy to Pi`

### Task 3: Extension memory blocks tương thích `opencode-agent-memory`

**Files:**
- Create: `src/memory/store.ts`, `src/memory/index.ts`, `test/memory.store.test.ts`, `test/memory.extension.test.ts`, `test/fixtures/memory/human.md`

**Interfaces:**
- Produces:
  - `interface MemoryBlock { label: string; scope: "global" | "project"; description: string; limit: number; readOnly: boolean; value: string; path: string }`
  - `listBlocks(opts: { globalDir: string; projectDir?: string }): Promise<MemoryBlock[]>`
  - `setBlock(opts, input: { label: string; scope: "global"|"project"; value: string; description?: string; limit?: number }): Promise<MemoryBlock>`
  - `replaceInBlock(opts, input: { label: string; scope?: "global"|"project"; oldText: string; newText: string }): Promise<MemoryBlock>`
  - Tools đăng ký: `memory_list`, `memory_set`, `memory_replace` (schema giống OpenCode tool cùng tên).
  - `before_agent_start` thêm section `<memory_blocks>` chứa mọi block (label, description, chars_current/chars_limit, value).
  - Thư mục: `globalDir = process.env.PI_MEMORY_GLOBAL_DIR ?? "/home/node/.config/opencode/memory"`, `projectDir = <cwd>/.opencode/memory`.

- [ ] **Step 1: Write failing store tests** — fixture `human.md` copy định dạng hiện có (frontmatter `description`, `label`, `limit: 5000`, `read_only: false`).

```ts
it("lists global and project blocks with sizes", async () => {
  const blocks = await listBlocks({ globalDir: G, projectDir: P });
  expect(blocks.map(b => `${b.scope}:${b.label}`)).toEqual(["global:human", "global:persona", "project:project"]);
});
it("replaceInBlock keeps frontmatter byte-identical", async () => { /* đọc file trước/sau, so frontmatter */ });
it("rejects_over_limit", async () => {
  await expect(setBlock(o, { label: "human", scope: "global", value: "x".repeat(5001) })).rejects.toThrow("vượt giới hạn 5000");
});
it("rejects_corrupt_frontmatter_without_writing", async () => { /* file thiếu '---' đóng → throw, mtime không đổi */ });
it("replace with missing oldText throws and does not write", async () => {});
it("read_only block cannot be written", async () => {});
```

- [ ] **Step 2: Run** — Expected: FAIL
- [ ] **Step 3: Implement** store (parse frontmatter bằng `yaml` đã có trong deps của Pi; ghi atomic: file tạm cùng thư mục + `rename`).
- [ ] **Step 4: Write failing extension test**: sau `before_agent_start`, prompt chứa `<memory_blocks>` và `label: human`.
- [ ] **Step 5: Implement** `index.ts`; **Run** `npx vitest run` — PASS
- [ ] **Step 6: Commit** `feat(memory): memory blocks compatible with opencode-agent-memory files`

### Task 4: Port `google_ai_search_plus` và Figma token refresh

**Files:**
- Create: `src/google-search/index.ts`, `src/figma-token/index.ts`, `test/google-search.test.ts`, `test/figma-token.test.ts`

**Interfaces:**
- Consumes: logic từ `/workspace/.tools/google-ai-search-plugin/src/index.ts` (giữ nguyên `GoogleAIModeManager`, đường dẫn Chromium `/workspace/.browser/ms-playwright/chromium-1244/chrome-linux64/chrome`).
- Produces:
  - Tool `google_ai_search_plus` với params `{ query: string; timeout?: number (5–120, mặc định 30); followUp?: boolean }`, trả text Markdown.
  - Khi trang trả "Google is blocking automated access" → kết quả text bắt đầu bằng `BLOCKED:` để model chuyển ngay sang `mcp__research_search__searxng_web_search` (theo memory người dùng).
  - `figma-token`: trên `session_start` chạy `python3 /home/node/.config/opencode/figma-token-sync.py` qua `execFile`, timeout 20 s, chỉ log lỗi, không chặn session.

- [ ] **Step 1: Failing tests**: tool đăng ký đúng tên + schema; khi `GoogleAIModeManager.search` ném lỗi chứa "blocking automated access" thì kết quả bắt đầu `BLOCKED:`; figma: `execFile` được gọi đúng 1 lần với đúng argv, lỗi không làm `session_start` throw.
- [ ] **Step 2: Run** — FAIL
- [ ] **Step 3: Implement** (inject `searchImpl` và `execFileImpl` để test thay được).
- [ ] **Step 4: Run** `npx vitest run` — PASS
- [ ] **Step 5: Commit** `feat: port google_ai_search_plus and figma token refresh to Pi`

### Task 5: Workspace guard (giới hạn thư mục ghi)

**Files:**
- Create: `src/workspace-guard/index.ts`, `test/workspace-guard.test.ts`

**Interfaces:**
- Produces:
  - `isInsideAllowed(target: string, allow: string[]): Promise<boolean>` — so sánh sau `fs.realpath` (đường dẫn chưa tồn tại: realpath thư mục cha gần nhất).
  - Allowlist từ env `PI_WRITE_ALLOW` (phân cách `:`), mặc định `/workspace:/tmp`.
  - Chặn `write`/`edit` có `path` ngoài allowlist; chặn `bash` có `cd`/redirect `>`/`>>` tới đường dẫn tuyệt đối ngoài allowlist (heuristic, ghi rõ trong README là không thay sandbox).

- [ ] **Step 1: Failing tests**: `/workspace/Project/a.txt` allow; `/home/node/.ssh/id` deny; symlink `/workspace/x -> /etc` deny; `echo k > /etc/passwd` deny.
- [ ] **Step 2–4:** Run FAIL → implement → PASS
- [ ] **Step 5: Commit** `feat(guard): restrict write targets to allowlisted directories`

### Task 6: Pi Workflow Lite extensions (không cấp quyền push)

**Files:**
- Create: `src/workflow-gate/index.ts`, `prompts/analyze.md`, `prompts/implement.md`, `prompts/review.md`, `prompts/verify.md`, `agents/*.md`, `test/workflow-gate.test.ts`

**Interfaces:**
- Consumes: nội dung `.opencode/commands/*.md`, `.opencode/agents/*.md`, `.opencode/workflow-policy.md` (copy, chỉ đổi cú pháp frontmatter nếu Pi cần).
- Produces:
  - Commands `/analyze`, `/implement`, `/review`, `/verify` (prompt templates).
  - Tool `workflow_status` chỉ hiển thị Task ID, SHA và evidence ID do harness inject vào context; Pi không là nguồn sự thật của gate.
  - `tool_call` handler **luôn** chặn `bash` khớp `git push*`, `gh pr merge*`, `git worktree add*`, `git checkout main`, `git checkout master`; lý do: "Lệnh này chỉ do Coworker Harness thực hiện".
  - Khi có source edit, `agent_before_settle` trả `continue: true` một lần nếu run chưa nhận evidence `CODEGRAPH_SYNC` và `CHECK_AFTER_EDIT`; nếu UI source edit thì cần thêm `PLAYWRIGHT_AFTER_EDIT`. Extension chỉ yêu cầu evidence, Harness mới xác minh/gắn evidence.

- [ ] **Step 1: Failing tests**: push/merge/worktree/main checkout luôn bị chặn bất kể prompt; edit source thiếu evidence thì settle yêu cầu tiếp tục; evidence đủ thì settle không nối thêm turn.
- [ ] **Step 2–4:** FAIL → implement → PASS
- [ ] **Step 5: Commit** `feat(workflow): expose workflow commands and reserve git control for harness`

### Task 6b: `coworker-harness` H1 — workflow state, Pi RPC và hard gates

**Files (repo mới `coworker-harness`):**
- Create: `package.json`, `src/graph/state.ts`, `src/graph/h1-code-flow.ts`, `src/pi/rpc-client.ts`, `src/pi/executor.ts`, `src/workspace/worktree.ts`, `src/evidence/ledger.ts`, `scripts/h1-acceptance.mjs`
- Test: `test/h1-code-flow.test.ts`, `test/rpc-client.test.ts`, `test/worktree.test.ts`, `test/ledger.test.ts`

**Interfaces:**
- Consumes: Pi 1.1 RPC JSONL, `pi-workspace-kit` (Task 1–6), CodeGraph CLI, Git, `@langchain/langgraph@1.5.0`, `@langchain/langgraph-checkpoint-postgres@1.1.0`.
- Produces:
  - `PiExecutor.start(envelope: SubtaskEnvelope): Promise<RunHandle>`; `events`, `abort`, `steer`, `answerUi`, `result` như đề xuất harness. Child Pi chạy với `cwd = worktree`, session dir riêng theo `run_id`, worker profile hoặc reviewer read-only profile.
  - `WorktreeManager.create({ taskId, repository, baseSha }): Promise<{ path, branch, baseSha }>` là API duy nhất được phép chạy `git worktree add`; `remove` chỉ sau khi ledger đánh dấu task terminal.
  - `EvidenceLedger.recordCheck`, `recordGate`, `latestForSha`; production dùng Postgres, test dùng in-memory adapter. `gate_verdict` bắt buộc gồm `sha`, `level`, `verdict`, `reviewer_run_id`, `evidence_ids`.
  - H1 graph: `create_worktree → codegraph_preflight → worker → deterministic_checks → review_normal → review_high → review_xhigh → pre_push_guard → interrupt(push approval) → push_branch → watch_ci → final`.
  - LangGraph graph state chỉ chứa ID/version/path/SHA; requirement/raw context/tool output chỉ đi qua artifact/evidence IDs.

- [ ] **Step 1: Write failing unit tests**

```ts
it("creates an isolated worktree at the pinned base SHA and never writes the base checkout", async () => {});
it("initializes CodeGraph inside the new worktree before the worker runs", async () => {});
it("records test exit code and post-edit CodeGraph sync against the worker commit SHA", async () => {});
it("requires normal, high, xhigh PASS verdicts from distinct reviewer run IDs for the exact SHA", async () => {});
it("stops at PUSH_APPROVAL interrupt and remote branch does not exist before Command resume", async () => {});
it("pushes only after Command({ resume: true }) and complete gate evidence", async () => {});
it("rejects stale verdicts after worker creates a new SHA", async () => {});
```

- [ ] **Step 2: Run** `npm test -- h1-code-flow` — Expected: FAIL
- [ ] **Step 3: Implement `rpc-client.ts`**: strict LF-delimited JSON parser, continuously drain stdout, timeout + child cleanup, classify `tool_execution_*`, `extension_ui_request`, `agent_settled`; no stderr parsing as protocol.
- [ ] **Step 4: Implement `worktree.ts` and `ledger.ts`**: call `git worktree add -b task/<taskId> <path> <baseSha>`; call `codegraph init <path> --yes` for every worktree (H1 evidence: index from base checkout is not reusable); use `PostgresSaver.fromConnString()` only in production composition, MemorySaver only in tests.
- [ ] **Step 5: Implement graph and reviewer profiles**: worker has `read,bash,edit,write`; reviewer has `read,grep,find,ls` only. Cap reviewer tool calls at 8 and ask it for a strict JSON `GateVerdict`; H1 observed unrestricted normal review made 17 calls and consumed 104K token.
- [ ] **Step 6: Run disposable acceptance fixture** `node scripts/h1-acceptance.mjs` — Expected: fixes a seeded parser bug; test PASS; 3 gates PASS; remote branch absent before approval; `Command({resume:true})` pushes branch; base checkout remains unchanged.
- [ ] **Step 7: Run** `npm test && npm run typecheck` — PASS. Start a local Postgres test container in CI only; run persistence/restart test: new process loads same `thread_id`, resumes pending interrupt.
- [ ] **Step 8: Commit** `feat(harness): add LangGraph Pi RPC code workflow with hard gates`

### Task 7: Fork pi-mobile bridge — allowlist cwd và ẩn đường dẫn

**Files (repo fork `pi-mobile`):**
- Modify: `bridge/src/config.ts` (thêm `BRIDGE_ALLOWED_CWDS`), `bridge/src/server.ts:983-1015` (nhánh `bridge_set_cwd`), nhánh `bridge_list_sessions`
- Test: `bridge/test/server.test.ts`, `bridge/test/config.test.ts`

**Interfaces:**
- Produces:
  - Env `BRIDGE_ALLOWED_CWDS` (phân cách `:`), bắt buộc khác rỗng khi `BRIDGE_HOST` không phải loopback.
  - `bridge_set_cwd` ngoài allowlist → `bridge_error` code `cwd_not_allowed`.
  - `bridge_sessions` thay đường dẫn tuyệt đối bằng đường dẫn tương đối so với root allowlist chứa nó.

- [ ] **Step 1: Failing tests**

```ts
it("rejects cwd outside allowlist", /* /home/node/.ssh → cwd_not_allowed */);
it("rejects_symlink_escape", /* <allow>/link -> /etc → cwd_not_allowed */);
it("accepts nested dir inside allowlist", /* <allow>/a/b → bridge_cwd_set */);
it("config refuses non-loopback host without allowlist", /* parse throws */);
it("sessions payload contains no absolute allowlisted root", /* JSON không chứa '/workspace/Project/' */);
```

- [ ] **Step 2: Run** `(cd bridge && pnpm vitest run test/server.test.ts)` — FAIL
- [ ] **Step 3: Implement** (dùng `fs.promises.realpath`, so `path.relative` không bắt đầu `..`).
- [ ] **Step 4: Run** `(cd bridge && pnpm run check)` — Expected: lint, typecheck, toàn bộ test PASS (baseline 87 + 5 mới).
- [ ] **Step 5: Commit + PR trong fork**; mở PR ngược lên `ayagmar/pi-mobile` (không chờ merge).

### Task 8: Image `pi-server` worker và cấu hình chuyển đổi

**Files (repo `TelegramAgent`):**
- Create: `docker/Dockerfile.pi-server`, `docker/pi/models.json.template`, `docker/pi/settings.json`, `docker/pi/mcp.json.template`, `docker/pi/APPEND_SYSTEM.md`, `docker/pi/entrypoint.sh`, `scripts/pi/convert-opencode-config.py`, `scripts/pi/verify-pi-config.cjs`, `tests/test_pi_config.py`
- Modify: `.github/workflows/build-images.yml`

**Interfaces:**
- Consumes: package `pi-workspace-kit` (Task 1–6, cài bằng `pi install git:github.com/vanbienperu3107/pi-workspace-kit@<tag>`), fork bridge (Task 7, ghim commit SHA).
- Produces:
  - Image `ghcr.io/vanbienperu3107/pi-server:<git-sha>`; user `node`; `PI_CODING_AGENT_DIR=/home/node/.pi/agent`; `PI_TELEMETRY=0`; tini làm PID 1; cùng gói apt với `Dockerfile.opencode-server` (git, openssh-client, ripgrep, ca-certificates, curl, tini, python3, graphviz).
  - `convert-opencode-config.py <opencode.json> <out-dir>` sinh `mcp.json` theo bảng chuyển đổi chính thức của Pi: `local` → `command`+`args`; `environment` → `env`; `{env:X}` → `${X}`; `{file:P}` → `"!cat P"`; `remote` → `url`+`headers`; khoá Tavily chuyển từ query `tavilyApiKey=` sang header `Authorization: Bearer ${TAVILY_API_KEY}`; `enabled:false` giữ nguyên; `codegraph` và `research_search` đặt `"exposure": "direct"` (đo ở A4: codemode gọi sai tên và bỏ sót caller), các server còn lại giữ `codemode`.
  - `APPEND_SYSTEM.md` = nối `AGENTS.md` + `feature-workflow.md` + `RESEARCH-MCP-POLICY.md` (sinh lúc build, có header nguồn + sha256 từng file).
  - `entrypoint.sh`: chạy bridge (`BRIDGE_HOST=0.0.0.0` trong mạng Docker, `BRIDGE_PORT=8787`, `BRIDGE_ALLOWED_CWDS=/workspace/Project:/workspace/opencode-sandbox`, `BRIDGE_PI_COMMAND=pi`) và `pi-tau-web-server --host 0.0.0.0 --port 3001` với `TAU_USER/TAU_PASS` từ secret; thoát khi một trong hai chết. Worker chỉ nhận subtask từ `coworker-harness`, không có đường push/merge trực tiếp.
  - `verify-pi-config.cjs`: exit≠0 nếu thiếu model mặc định trong `models.json`, nếu có khoá literal, nếu thiếu bất kỳ server nào đang `enabled` trong `opencode.json`.

- [ ] **Step 1: Failing tests** `tests/test_pi_config.py`

```python
def test_convert_maps_all_13_servers(tmp_path): ...  # tên server trùng 1-1, enabled giữ nguyên
def test_convert_moves_tavily_key_to_header(tmp_path): ...  # url không còn "tavilyApiKey="
def test_codegraph_and_research_search_direct(tmp_path): ...  # exposure == "direct"
def test_convert_file_refs_become_command(tmp_path): ...    # "{file:/x}" -> "!cat /x"
def test_no_literal_secret_in_outputs(tmp_path): ...        # regex tvly-|ghp_|figd_|sk- không xuất hiện
def test_models_template_uses_secret_file(): ...            # apiKey bắt đầu bằng "!"
def test_settings_telemetry_off(): ...
def test_dockerfile_pins_pi_and_node24_sha(): ...           # "@earendil-works/pi-coding-agent@1.1.0" và sha256 node v24.21.0
```

- [ ] **Step 2: Run** `pytest tests/test_pi_config.py -q` — FAIL
- [ ] **Step 3: Implement** script/template/Dockerfile.
- [ ] **Step 4: Run** `pytest -q` (toàn repo) — PASS; `docker build -f docker/Dockerfile.pi-server .` chạy trong CI `build-images.yml` — PASS.
- [ ] **Step 5: Commit** `feat(pi): pi-server image and OpenCode→Pi config converter`

### Task 9: Deploy `pi-server` trên worker riêng hoặc staged takeover

**Files:**
- Create: `docker-compose.pi-worker.yml`, `.github/workflows/deploy-pi-worker.yml`, `scripts/pi/preflight-worker.sh`
- Modify: `tests/test_compose.py`
- Create: `scripts/pi/smoke.sh`

**Interfaces:**
- Consumes: image Task 8, `coworker-harness` H1 (Task 6b).
- Produces:
  - Service `pi-server`: `mem_limit: 768m`, `memswap_limit: 1280m`, `oom_score_adj: 800`, `pids_limit: 512`, `security_opt: ["no-new-privileges:true"]`, `cap_drop: [ALL]`, `env_file: .env.pi`, không `ports:`, `working_dir: ${DEFAULT_PROJECT_PATH:?...}`, volumes: `./workspace:/workspace`, `pi_data:/home/node/.pi/agent/sessions`, `./skill_new:/opt/skills:ro`, `./workspace/opencode-mcp-research/image-data:/research-images:ro`, secret file `cliproxy-key`; healthcheck `curl -sS -o /dev/null --max-time 5 http://127.0.0.1:8787/health` (bridge chạy `BRIDGE_ENABLE_HEALTH_ENDPOINT=true`).
  - `preflight-worker.sh` từ chối deploy nếu worker không có ít nhất 1536 MB `MemAvailable` trước khi khởi động Pi, hoặc nếu không truy cập được CLIProxy/MCP network.
  - Không đổi `opencode-server.mem_limit` ở giai đoạn canary. Nếu không có worker thứ hai, staged takeover phải stop OpenCode trước khi start Pi và giữ rollback dưới 60 s.
  - `smoke.sh` (chạy trong container `pi-server`): `pi --version` = 1.1.0; `pi mcp list` có ≥10 `connected`; `pi --no-session -p "Reply with exactly: PONG"` in `PONG`; RPC `get_state` qua bridge trả `provider=cliproxy`.

- [ ] **Step 1: Failing tests** thêm vào `tests/test_compose.py`

```python
def test_pi_worker_compose_khong_publish_cong(services): assert "ports" not in services["pi-server"]
def test_pi_server_khong_publish_cong(services): assert "ports" not in services["pi-server"]
def test_pi_server_khong_o_db_net(services): assert "db_net" not in services["pi-server"]["networks"]
def test_pi_sessions_giu_qua_deploy(services, compose): assert "pi_data" in compose["volumes"]
# compose vpn4 gốc giữ nguyên test_tong_ngan_sach_ram_khong_vuot_1856mb
```

- [ ] **Step 2: Run** `pytest tests/test_compose.py -q` — FAIL
- [ ] **Step 3: Implement** worker compose + preflight + deploy bước "verify-pi-config" và "smoke pi"; nếu smoke fail → stop `pi-server`, job FAIL và OpenCode không bị động tới.
- [ ] **Step 4: Run** `pytest -q` — PASS; dispatch `deploy-pi-worker.yml`; Expected: preflight PASS, smoke in `PONG` và `provider=cliproxy`.
- [ ] **Step 5: Test restart** — `session_survives_container_restart`: trong deploy job, tạo session qua bridge với code word, restart `pi-server`, `switch_session` cùng file, hỏi lại code word → khớp.
- [ ] **Step 6: Commit** `feat(deploy): add isolated Pi worker deployment with capacity preflight`

### Task 10: Truy cập từ điện thoại (bridge + Tau qua tailnet)

**Files:**
- Modify: `edge-vpn4/Caddyfile` trong `deployHeadscale` **chỉ** nếu người dùng duyệt route; mặc định không đổi Caddy.
- Create: `docs/pi-remote-access.md` (repo `TelegramAgent`)

**Interfaces:**
- Consumes: service `pi-server` (Task 9), fork pi-mobile (Task 7).
- Produces:
  - Truy cập mặc định: `tailscale serve` trên vpn4 → `https://vpn4.<tailnet>.ts.net:8787` (bridge) và `:3001` (Tau), chỉ trong tailnet; không mở Internet công cộng.
  - APK pi-mobile build từ fork qua CI fork (job Android có sẵn); sửa lỗi detekt `SessionsScreen` complexity 17 > 15 bằng tách composable con.

- [ ] **Step 1: Failing check**: từ runner CI tham gia tailnet (khoá ephemeral), `curl -H "Authorization: Bearer $TOKEN" https://vpn4.../health` — FAIL (chưa có serve).
- [ ] **Step 2: Implement** `tailscale serve` cấu hình lưu bền (`tailscale serve --bg --https=8787 http://pi-server:8787` qua container sidecar trong mạng `edge`, hoặc trên host — chọn host vì đã có tailscaled).
- [ ] **Step 3: Run** check lại — PASS 200; không token → 401.
- [ ] **Step 4: Android emulator E2E** trong fork pi-mobile: dùng `reactivecircus/android-emulator-runner@v2` (API 34, x86_64) giống `adroidClient/.github/workflows/android-emulator.yml`; bridge thật trong job (Pi 1.1 + CLIProxy secret); Espresso/UiAutomator: thêm host, gửi prompt, nhận câu trả lời, duyệt quyền "Cho phép". Expected: PASS + ảnh chụp artifact.
- [ ] **Step 5: Commit** `docs(pi): remote access via tailnet for bridge and Tau`

### Task 11: Chuyển Telegram gateway sang Pi (tùy chọn theo cờ)

**Files (repo `TelegramAgent`):**
- Create: `src/services/pi-client.ts`, `tests/pi-client.test.ts`
- Modify: `src/services/task-runner.ts`, `src/config.ts`

**Interfaces:**
- Consumes: bridge WebSocket (Task 7/9).
- Produces:
  - `interface AgentBackend { taoSession(tuaDe?: string): Promise<{ id: string }>; guiPrompt(a: { sessionID: string; text: string }): Promise<void>; huy(sessionID: string): Promise<void>; traLoiQuyen(sessionID: string, requestID: string, traLoi: "once"|"reject"): Promise<void>; suKien(sessionID: string): AsyncIterable<SuKienChung> }`
  - `OpenCodeClient` hiện có được bọc thành `OpenCodeBackend implements AgentBackend`; `PiBridgeBackend implements AgentBackend` mới.
  - Env `AGENT_BACKEND=opencode|pi` (mặc định `opencode`).
  - Ánh xạ: `prompt_async` → RPC `prompt`; `abort` → `abort`; `permission.asked` ↔ `extension_ui_request(select)`; trả lời `once` → `"Cho phép"`, `reject` → `"Từ chối"`; `always` không hỗ trợ ở Pi → coi như `once` và báo người dùng.

- [ ] **Step 1: Failing tests** với fake WebSocket server: prompt → nhận `agent_settled` → `vanTraLoiCuoi` đúng text; duyệt quyền round-trip; huỷ trong 1 s.
- [ ] **Step 2–4:** FAIL → implement → `npm test` PASS (toàn bộ test cũ vẫn PASS với `AGENT_BACKEND=opencode`).
- [ ] **Step 5: Commit** `feat(gateway): pluggable agent backend with Pi bridge implementation`

### Task 12: Bộ nghiệm thu, cắt chuyển và rollback

**Files:**
- Create: `.github/workflows/pi-acceptance.yml`, `docs/pi-cutover-runbook.md`, `scripts/pi/acceptance/*.sh`

**Interfaces:**
- Consumes: mọi task trước.
- Produces: workflow dispatch chạy trên **Pi worker** (ssh-action như `deploy.yml`) các ca A1–A13 (Phụ lục B), xuất `acceptance-<sha>.md` làm artifact; runbook cắt chuyển 3 bước và rollback.

- [ ] **Step 1: Viết ca nghiệm thu dạng script** (mỗi ca exit 0/1, in `PASS`/`FAIL` + bằng chứng).
- [ ] **Step 2: Dispatch** `pi-acceptance.yml` — Expected: 13/13 PASS cho commit đang deploy.
- [ ] **Step 3: Cắt chuyển bề mặt 1 — người dùng hằng ngày**: Tau/pi-mobile qua tailnet làm bề mặt chính 7 ngày; OpenCode vẫn chạy. Ghi lại lỗi vào issue.
- [ ] **Step 4: Cắt chuyển bề mặt 2 — Telegram**: đặt `AGENT_BACKEND=pi`, deploy, chạy A11 trên Telegram thật.
- [ ] **Step 5: Cắt chuyển bề mặt 3 — stop OpenCode sau 7 ngày ổn định**: bỏ route/worker OpenCode, giữ image + volume `opencode_data` 30 ngày. Pi worker không đổi `mem_limit` chỉ vì cắt chuyển; tăng capacity phải qua benchmark/PR riêng.
- [ ] **Step 6: Rollback (thử thật một lần trước bước 5)**: đặt `AGENT_BACKEND=opencode`, khôi phục route/worker OpenCode với `mem_limit` 1536m, deploy image/version đã ghi trong runbook; Expected: `/global/health` 200 trong 60 s và phiên OpenCode cũ còn nguyên.
- [ ] **Step 7: Commit** `docs(pi): acceptance suite, cutover and rollback runbook`

---

## Phụ lục A — Bằng chứng đã đo (2026-10-09 → 2026-10-13, container 1,5 GB)

| # | Hạng mục | Kết quả |
|---|---|---|
| A1 | Pi 1.1.0 + CLIProxy (openai-completions, anthropic-messages) | PASS, 3–4 s |
| A2 | 13 MCP qua `mcp.json` | 10 connected, 3 disabled có chủ ý; wiki 502 do backend |
| A3 | Transport MCP remote | 6/7 streamable HTTP; không server nào SSE cũ |
| A4 | MCP gọi thật (research_search, codegraph) | PASS; codemode gọi sai tên lần đầu, codegraph bỏ sót 2/7 caller |
| A5 | Pi mặc định | không chặn lệnh nào |
| A6 | Extension quyền (deny / ask không UI / chuỗi lệnh / MCP github) | PASS |
| A7 | Duyệt quyền qua RPC, Tau (trình duyệt mobile), pi-mobile bridge | PASS cả ba |
| A8 | Abort / steer / reconnect / lock | 0,02 s / PASS / resumed / control_lock_denied |
| A9 | Compaction | 17,3K token → tóm tắt có cấu trúc; nhớ đúng dữ kiện sau nén |
| A10 | Bài sửa bug (cùng model) | Pi 19–31 s, ~16–43K token, 116–460 MB; OpenCode 130 s, ~927K token, ~1 GB |
| A11 | Tuân thủ quy trình | Pi bỏ qua worktree; OpenCode tuân thủ ⇒ Task 6 bắt buộc |
| A12 | pi-mobile bridge `pnpm run check` | 87/87; lỗ hổng cwd tùy ý + lộ đường dẫn ⇒ Task 7 |
| A13 | App Android pi-mobile | BLOCKED (không KVM) ⇒ Task 10 Step 4 |
| A14 | H1 LangGraph + Pi RPC hard-gate spike (2026-10-15) | PASS: `MemorySaver`, disposable worktree, CodeGraph init+explore+sync, worker + 3 reviewer read-only, `interrupt()` duyệt push; remote branch **không tồn tại** trước approval, push sau `Command({resume:true})`; lần cuối 96,59 s, 324 MB peak, 95.828 token. Một run trước reviewer Normal gọi 17 tool/104K token; run cuối reviewer XHigh gọi 9 tool ⇒ Task 6b giới hạn 8 call/reviewer là bắt buộc. |

## Phụ lục B — Ca nghiệm thu (Task 12)

| ID | Ca | Kỳ vọng |
|---|---|---|
| AC1 | `pi -p` với model mặc định | trả lời, exit 0 |
| AC2 | `pi mcp list` | ≥10 connected, đúng danh sách enabled |
| AC3 | `rm -rf`, `sudo`, `git reset --hard` qua tool, qua chuỗi lệnh, qua `!cmd` | đều bị chặn |
| AC4 | `mcp__github__*` không UI | bị chặn; có UI → hỏi |
| AC5 | memory_list/set/replace trên file thật | đọc/ghi đúng, frontmatter giữ nguyên |
| AC6 | `git push` khi thiếu gate | bị chặn với lý do tiếng Việt |
| AC7 | Ghi file ngoài `/workspace`, `/tmp` | bị chặn |
| AC8 | Bridge: cwd ngoài allowlist, symlink thoát | `cwd_not_allowed` |
| AC9 | Hai thiết bị, máy đầu rớt mạng | máy sau giành quyền ≤ 30 s |
| AC10 | Restart container giữa phiên | resume được, dữ kiện còn |
| AC11 | Telegram với `AGENT_BACKEND=pi` | prompt, duyệt quyền, huỷ hoạt động |
| AC12 | Rollback | OpenCode health 200 ≤ 60 s, phiên cũ còn |
| AC13 | H1 hard-gate | base checkout không đổi; worktree có SHA mới; CodeGraph init/sync trong worktree; 3 reviewer run ID khác nhau PASS đúng SHA; remote branch vắng trước approval và xuất hiện sau resume |

## Phụ lục C — Rủi ro còn lại

- Pi không có sandbox; ranh giới thật là container (`cap_drop: [ALL]`, `no-new-privileges`, không Docker socket).
- Extension bên thứ ba thực thi trong tiến trình Pi; chỉ cài package ghim theo commit/tag sau khi review.
- pi-mobile mới cam kết Pi 0.80; fork phải tự chạy ca nghiệm thu khi nâng Pi.
- Codemode làm chất lượng gọi tool kém hơn; codegraph khai báo `exposure: "direct"` trong `mcp.json`.
- `always` (cho phép vĩnh viễn) của OpenCode không có tương đương trực tiếp; Task 11 hạ về `once`.
- H1 dùng `MemorySaver` để thử graph. Production bắt buộc `PostgresSaver`; không promotion khi chưa có test resume pending `interrupt()` qua process restart và Postgres thật.
- H1 không tải 13 MCP và không chạy UI test; 316 MB chỉ là lower bound, không phải capacity chứng minh cho Pi worker production.
