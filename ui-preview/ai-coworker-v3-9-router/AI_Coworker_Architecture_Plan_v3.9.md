# AI Coworker Architecture & Deployment Plan v3.9



# Version 3.9 — Deterministic Router + AI SDK / Zod Classification Plane

## 1. Architectural Decision

v3.9 preserves the Pi-native architecture from v3.8.

New decision:

```text
Execution classification
→ deterministic code first
→ AI SDK + Zod only for ambiguous messages
→ transition validation in code
→ LangGraph only after COWORKER is selected
```

Do NOT use LangGraph to classify every message.

Do NOT use a multi-agent workflow to choose between:

```text
HỎI
TÌM HIỂU
LÀM VIỆC
```

The router is a small control component.

```text
small state
small schema
short timeout
low-cost model profile
strict output
deterministic fallback
```

---

# 2. v3.9 Final Architecture

```text
                                  WINDOWS / MOBILE
                                        │
                                        ▼
                                    OPEN WEBUI
                                        │
        Native Chat / History / Notes / Memory / Knowledge / Files
                                        │
                                        ▼
                          COWORKER GATEWAY API
                                        │
                                        ▼
                           EXECUTION CLASSIFICATION PLANE
                                        │
                 ┌──────────────────────┼──────────────────────┐
                 ▼                      ▼                      ▼
          Explicit Selector       Active Task Rule       Deterministic Rules
                 │                      │                      │
                 └──────────────────────┴───────────┬──────────┘
                                                      ▼
                                               ambiguity?
                                               ┌────┴────┐
                                              NO         YES
                                              │           │
                                              ▼           ▼
                                      Authoritative   AI SDK + Zod
                                      Rule Result     Fast Router Model
                                              │           │
                                              └─────┬─────┘
                                                    ▼
                                         Transition Validator
                                                    │
                         ┌──────────────────────────┼──────────────────────────┐
                         ▼                          ▼                          ▼
                       HỎI                      TÌM HIỂU                    LÀM VIỆC
                       CHAT                     RESEARCH                    COWORKER
                         │                          │                          │
                         ▼                          ▼                          ▼
                   Pi Direct /                Native Research /        COWORKER HARNESS
                   Native Chat                 Pi Research Profile              │
                                                                              ▼
                                                             LANGGRAPH + POSTGRESSAVER
                                                                              │
                       ┌──────────────────────────────────────────────────────┼──────────────────────────────────────────────────────┐
                       ▼                                                      ▼                                                      ▼
             Requirement / Output Contract                            Context / Evidence                                 Task / DAG / Quality
                       │                                                      │                                                      │
                       └──────────────────────────────────────────────────────┴──────────────────────────────┬───────────────────────┘
                                                                                                               ▼
                                                                                                      Pi RPC Executor Adapter
                                                                                                               │
                                                                 ┌─────────────────────────────────────────────┼─────────────────────────────────────────────┐
                                                                 ▼                                             ▼                                             ▼
                                                          Pi Worker                                     Pi Researcher                                  Pi Reviewer
                                                          worktree                                      logical workspace                              read-only
                                                                 │                                             │                                             │
                                                                 └─────────────────────────────────────────────┴─────────────────────────────────────────────┘
                                                                                                               ▼
                                                                                                             FINAL
                                                                                                               │
                                                                                                           OPEN WEBUI
```

---

# 3. User-Facing Work Types

The user sees:

```text
HỎI
TÌM HIỂU
LÀM VIỆC
```

Backend mapping:

```text
HỎI       → CHAT
TÌM HIỂU  → RESEARCH
LÀM VIỆC  → COWORKER
```

## HỎI

```text
Goal:
Answer directly.

Typical execution:
Open WebUI / Pi Direct
→ CLIProxy
→ Answer

No task lifecycle.
No LangGraph.
No PostgresSaver.
```

## TÌM HIỂU

```text
Goal:
Find current or verified information.

Typical execution:
Native Search / Fetch
or Pi Research Profile
→ Evidence-aware answer

No full Coworker lifecycle by default.
```

## LÀM VIỆC

```text
Goal:
Complete a multi-step task.

Typical execution:
Coworker Harness
→ LangGraph
→ PostgresSaver
→ Requirement / Context / Task / Quality lifecycle
→ Final
```

---

# 4. Router Responsibility Boundary

Router answers:

```text
HOW should this message execute?
```

Router does NOT answer:

```text
What exact requirements does the user have?
What is the final task complexity?
What worktree should be created?
What tool should be called?
What permission should be granted?
```

Responsibility table:

| Component | Authoritative Question | Non-Responsibility |
|---|---|---|
| Execution Router | HỎI / TÌM HIỂU / LÀM VIỆC? | mutate requirements |
| Requirement Controller | What does user want? | select model/tool policy |
| Complexity Controller | How much Coworker orchestration? | override explicit work type silently |
| LangGraph | Which workflow node runs next? | own Pi transcript |
| Pi | What does one agent execute? | push / merge / create worktree |
| PostgresSaver | Where did graph pause? | semantic truth / evidence truth |
| Context Ledger | What is trusted context? | workflow transition |
| Evidence Ledger | What was verified for this revision? | raw agent memory |

---

# 5. Router Inputs

Router reads only light control context:

```yaml
router_input:
  message_id: MSG-501
  current_message: "phần security thì sao?"

  explicit_mode: AUTO | HỎI | TÌM HIỂU | LÀM VIỆC | null

  active_task:
    task_id: TASK-100 | null
    status: ACTIVE | WAITING_CLARIFICATION | null
    display_mode: LÀM VIỆC | null
    topic_fingerprint: "..." | null

  conversation_state:
    last_mode: CHAT | RESEARCH | COWORKER | null
    last_message_summary: "..." | null

  current_project:
    project_id: PROJECT-7 | null

  recent_message_summary:
    - "..."
```

Router must NOT load:

```text
full Open WebUI chat
Pi session transcript
raw Context Ledger records
all project notes
all research sources
all tool traces
full requirement contracts
```

before mode selection.

---

# 6. Classification Decision Policy

Priority:

```text
USER_EXPLICIT
>
ACTIVE_TASK_CONTINUATION
>
SIDE_QUERY_ISOLATION
>
DETERMINISTIC_RULE
>
AI_SDK_CLASSIFIER
>
SAFE_FALLBACK
```

## 6.1 Explicit Selection

```text
User selects HỎI
→ HỎI

User selects TÌM HIỂU
→ TÌM HIỂU

User selects LÀM VIỆC
→ LÀM VIỆC
```

No model may silently override explicit selection.

## 6.2 Active Task Continuation

```text
Active task: TASK-100 AI Coworker

User:
"phần security thì sao?"

Result:
display_mode = LÀM VIỆC
execution_mode = COWORKER
mode_source = ACTIVE_TASK_CONTINUATION
task_id = TASK-100
```

## 6.3 Side Query Isolation

```text
Active task: TASK-100

User:
"1 USD bằng bao nhiêu PEN?"

Result:
display_mode = HỎI
execution_mode = CHAT
side_query = true
parent_task_id = TASK-100
```

Side query must not enter Parent Context Ledger unless explicitly promoted.

## 6.4 Deterministic Rules

Examples:

```text
"tạo plan"
"triển khai"
"sửa code"
"review phương án"
"thiết kế architecture"
→ LÀM VIỆC

"tìm giá hiện tại"
"tìm hiểu phiên bản mới"
"so sánh hiện nay"
→ TÌM HIỂU

"SSE là gì?"
"dịch đoạn này"
"Kafka partition là gì?"
→ HỎI
```

Deterministic match must record:

```text
rule_id
rule_version
rule_result
```

## 6.5 AI Classification Only for Ambiguity

Examples:

```text
"xem giúp tôi cái này"
"bạn xử lý phần này được không"
"nên làm gì tiếp"
```

These may require context-sensitive classification.

Only then call:

```text
AI SDK + Zod
```

---

# 7. AI SDK + Zod Router

## 7.1 Selected Stack

```text
AI SDK
+
@ai-sdk/openai-compatible
+
Zod
+
CLIProxy
```

Why:

```text
existing CLIProxy is OpenAI-compatible
TypeScript-native
structured output schema
provider abstraction
usage telemetry
small router surface
no separate DSL or code generator
```

## 7.2 Router Output Contract

```typescript
const RouterResultSchema = z.object({
  displayMode: z.enum(["HỎI", "TÌM HIỂU", "LÀM VIỆC"]),

  executionMode: z.enum(["CHAT", "RESEARCH", "COWORKER"]),

  confidence: z.enum(["HIGH", "MEDIUM", "LOW"]),

  complexityHint: z.enum([
    "SIMPLE",
    "MEDIUM",
    "COMPLEX",
    "XHIGH",
  ]),

  continuation: z.boolean(),
  sideQuery: z.boolean(),
  needsEscalationProposal: z.boolean(),

  reasons: z.array(z.enum([
    "DIRECT_ANSWER",
    "CURRENT_OR_VERIFIED_INFORMATION",
    "EXTERNAL_RESEARCH",
    "ACTIVE_TASK_CONTINUATION",
    "PERSISTENT_TASK_STATE",
    "MULTIPLE_DELIVERABLES",
    "ARCHITECTURE_OR_DECISION",
    "IMPLEMENTATION_OR_EXECUTION",
    "QUALITY_REVIEW_REQUIRED",
    "SIDE_QUERY",
    "USER_EXPLICIT",
  ])).min(1).max(5),
});
```

The classifier may emit:

```text
complexityHint
```

The classifier may NOT emit:

```text
authoritative complexity level
task state transition
tool selection
permission decision
worktree path
SQL query
free-form execution mode
```

## 7.3 Router Call

```typescript
const result = await generateObject({
  model: cliproxy.chatModel("FAST_ROUTER_MODEL"),
  schema: RouterResultSchema,
  temperature: 0,
  prompt: routerPrompt(lightRouterInput),
});
```

Rules:

```text
timeout = 5 seconds
max retry = 1
temperature = 0
small model profile
no tools
no browsing
no MCP
```

## 7.4 Transition Validator

AI output is advisory until code validates it.

```text
AI SDK + Zod Result
        ↓
Transition Validator
        ├── explicit selection respected?
        ├── active task continuation respected?
        ├── side query isolated?
        ├── valid display/execution mapping?
        ├── research escalation only proposed?
        └── complexity remains hint only?
        ↓
Authoritative Route Result
```

Invalid model result:

```text
INVALID_ROUTER_OUTPUT
→ SAFE_FALLBACK
```

## 7.5 Safe Fallback

If classifier timeout, provider error, schema error or validation error:

```text
active task continuation
→ COWORKER

explicit selection
→ explicit selection

high-risk deterministic rule
→ COWORKER

otherwise
→ CHAT
  confidence = LOW
  mode_source = SAFE_FALLBACK
```

Safe fallback does NOT silently initiate expensive Coworker workflow.

---

# 8. Component Selection Record

## 8.1 Small Router Framework Options

| Option | Strength | Weakness | Fit for v3.9 | Decision |
|---|---|---|---|---|
| Deterministic TypeScript only | zero model cost, lowest latency, explainable | cannot resolve semantic ambiguity | mandatory first layer | USE |
| AI SDK + Zod | existing CLIProxy compatibility, TS-native, structured result, usage | adds AI SDK package/runtime | best ambiguity layer | SELECT |
| TypeChat | lightweight, MIT, schema repair | npm release old, separate model abstraction, less aligned with existing CLIProxy adapter | acceptable fallback candidate | NOT SELECTED NOW |
| BAML | typed prompt DSL, retry/fallback, function tests | separate DSL/generator; v0/v1 documentation transition; too much for three-mode router | possible future prompt platform | DEFER |
| LangGraph | durable workflows, interrupt, retry | excessive for per-message classification | COWORKER only | REJECT FOR ROUTER |
| Embedding / classifier model | low marginal cost at high scale | needs labeled dataset, drift maintenance, weak context understanding | later if volume justifies | DEFER |

## 8.2 Decision Rule

```text
M0 / M1
→ Deterministic TypeScript + AI SDK + Zod

If router prompt/schema becomes a large managed prompt library
→ evaluate BAML

If ≥ 10,000 labeled routes and latency/cost dominates
→ evaluate trained classifier / embedding layer

Never use LangGraph solely to route a message.
```

## 8.3 Structured Output Options

| Option | Validation | Retry / Repair | Provider Coupling | Decision |
|---|---|---|---|---|
| AI SDK + Zod | Zod schema | application-owned | OpenAI-compatible adapter | SELECT for router |
| TypeChat | TypeScript schema | built-in repair interaction | model adapter required | fallback candidate |
| BAML | BAML types | declarative retry/fallback | broad provider support | defer |
| raw JSON.parse | none | manual | none | REJECT |
| free-form text | none | prompt-only | none | REJECT |

---

# 9. Router Component Diagram

```text
┌───────────────────────────────────────────────────────────────────────────┐
│                            COWORKER GATEWAY API                            │
│                                                                           │
│  POST /route                                                              │
│  { message_id, current_message, explicit_mode, active_task, ... }        │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                         ROUTER INPUT NORMALIZER                            │
│                                                                           │
│  - trim / size limit                                                       │
│  - active task metadata only                                               │
│  - recent message summary only                                             │
│  - no raw transcript retrieval                                             │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                         DETERMINISTIC RULE ENGINE                          │
│                                                                           │
│  USER_EXPLICIT                                                            │
│  ACTIVE_TASK_CONTINUATION                                                  │
│  SIDE_QUERY_ISOLATION                                                      │
│  HIGH_RISK_WORK                                                            │
│  OBVIOUS_WORK / RESEARCH / CHAT                                            │
└───────────────┬───────────────────────────────────────────┬───────────────┘
                │ decisive                                  │ ambiguous
                ▼                                            ▼
┌───────────────────────────────────────┐       ┌────────────────────────────┐
│ AUTHORITATIVE RULE RESULT              │       │ AI SDK CLASSIFIER          │
│                                       │       │                            │
│ source = DETERMINISTIC_RULE           │       │ FAST_ROUTER_MODEL          │
│ confidence = HIGH                     │       │ temperature = 0            │
└───────────────────┬───────────────────┘       │ Zod RouterResultSchema      │
                    │                           │ timeout = 5s               │
                    │                           └──────────────┬─────────────┘
                    │                                          │
                    └─────────────────────┬────────────────────┘
                                          ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                           TRANSITION VALIDATOR                             │
│                                                                           │
│  - displayMode ↔ executionMode mapping                                   │
│  - explicit selection precedence                                          │
│  - side query isolation                                                   │
│  - COWORKER continuation lineage                                          │
│  - complexityHint is advisory                                             │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                            ROUTE RECORD WRITER                            │
│                                                                           │
│  execution_run                                                            │
│  router_input_snapshot (redacted/light)                                   │
│  router_output                                                            │
│  rules_triggered                                                          │
│  model/profile/version                                                    │
│  latency / usage / fallback                                               │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │
                 ┌───────────────────┼────────────────────┐
                 ▼                   ▼                    ▼
              CHAT                RESEARCH             COWORKER
             direct              research             LangGraph
```

---

# 10. Router Output Contract

```json
{
  "run_id": "RUN-501",
  "message_id": "MSG-501",
  "task_id": null,

  "display_mode": "TÌM HIỂU",
  "execution_mode": "RESEARCH",

  "mode_source": "AI_SDK_CLASSIFIER",
  "confidence": "MEDIUM",
  "complexity_hint": "SIMPLE",

  "continuation": false,
  "side_query": false,
  "needs_escalation_proposal": false,

  "reasons": [
    "CURRENT_OR_VERIFIED_INFORMATION",
    "EXTERNAL_RESEARCH"
  ],

  "rules_triggered": [],
  "router_version": "ROUTER-v1",
  "schema_version": "ROUTE-SCHEMA-v1",
  "model_profile": "FAST_ROUTER_MODEL",
  "latency_ms": 412,
  "created_at": "..."
}
```

`complexity_hint` remains advisory.

```text
Router = hint
Complexity Controller = authority
```

---

# 11. Route Transition Matrix

| From | To | Allowed | Authority | Rule |
|---|---|---:|---|---|
| CHAT | RESEARCH | yes | router / user | current verification emerged |
| RESEARCH | COWORKER | yes | user approval or non-explicit escalation | work-shaped deliverables emerged |
| COWORKER | CHAT side query | yes | deterministic isolation | unrelated short question |
| CHAT side query | COWORKER | yes | active task continuation | answer complete, return to parent |
| COWORKER | CHAT | no direct downgrade | user/task closure | must preserve task lineage |
| any | explicit user mode | yes | user | explicit selection wins |

Every transition persists:

```text
old_mode
new_mode
source
reason
user_override
task_id
parent_run_id
timestamp
```

---

# 12. Complexity Controller

Router returns only a hint.

Complexity Controller runs after Requirement Contract and Output Contract.

```text
Requirement Contract
      +
Output Contract
      +
Deterministic dimensions
      +
Semantic assessment
      +
Hard risk overrides
      ↓
Authoritative Processing Level
```

User-facing:

```text
NHẸ
VỪA
NẶNG
RẤT NẶNG
```

Backend:

```text
SIMPLE
MEDIUM
COMPLEX
XHIGH
```

---

# 13. Pi-Native Execution Harness

Pi remains the only agent execution harness.

```text
Pi
→ agent loop
→ MCP client
→ tools
→ session JSONL
→ local compaction
→ extension hooks
→ RPC transport
```

Pi does NOT own:

```text
task state transitions
worktree creation
push
merge
evidence truth
workflow checkpoint
```

Pi profiles:

```text
FAST_ROUTER
REQUIREMENT_ANALYST
RESEARCHER
CODE_WORKER
STANDARD_REVIEWER
INDEPENDENT_REVIEWER
ADVERSARIAL_REVIEWER
SYNTHESIS_AGENT
```

---

# 14. LangGraph + PostgresSaver Plane

LangGraph activates only for:

```text
LÀM VIỆC
```

LangGraph owns:

```text
current node
pending branches
retry
interrupt
fan-out / fan-in
resume position
workflow transition legality
```

PostgresSaver owns:

```text
durable graph checkpoint
```

PostgresSaver does NOT own:

```text
Pi transcript
semantic context
verified evidence
Open WebUI chat history
```

```text
PostgresSaver
= where did workflow pause?

Context Ledger
= what does system know and trust?

Evidence Ledger
= what did system verify for this revision?
```

---

# 15. Persistence Component Selection Record

| Component | Scope | Durable Across Restart | Use in v3.9 | Do Not Use For |
|---|---|---:|---|---|
| Pi session JSONL | one Pi session | yes | transcript / local compaction / Pi resume | workflow authority |
| PostgresSaver | one LangGraph thread | yes | workflow checkpoints / interrupts / time travel | semantic context |
| PostgresStore | cross-thread app data | yes | future long-term strategy/preference store | checkpoint state |
| Context Ledger | task/project semantic state | yes | requirement, decisions, evidence context | graph node position |
| Evidence Ledger | verified run/revision facts | yes | tests, gate verdicts, artifacts | raw transcript |
| Redis queue | job transport | depends | later concurrency only | source of truth |
| MemorySaver | process memory | no | unit test / local spike only | production |
| SQLiteSaver | local file | yes | local developer environment | multi-instance production |

Decision:

```text
Production workflow checkpoint
→ PostgresSaver

Development / unit test
→ MemorySaver

Long-term cross-thread strategy memory
→ PostgresStore or dedicated strategy tables
```

---

# 16. PostgresSaver Detailed Rules

## 16.1 Setup

```typescript
const checkpointer = PostgresSaver.fromConnString(
  process.env.LANGGRAPH_DATABASE_URL,
  { schema: "coworker" }
);

await checkpointer.setup();
```

`setup()` runs only in controlled migration/deploy.

Never from Pi worker.

## 16.2 Thread Identity

```text
thread_id = execution_run_id
```

Rules:

```text
immutable
UUID / generated ID
< 255 characters
not user text
not workspace path
not credential
```

## 16.3 State Rule

Checkpoint state stores only reference-sized data:

```typescript
CoworkerState = {
  execution_run_id,
  task_id,
  requirement_version,
  output_contract_version,
  task_dag_version,
  complexity_level,
  worktree_ids,
  pi_run_ids,
  evidence_map_version,
  pending_interrupt,
  status
}
```

Never store:

```text
full prompt
full Pi messages
raw tool output
research page content
image bytes
credentials
```

## 16.4 Interrupt

```text
LangGraph node
  ↓
interrupt(PUSH_APPROVAL)
  ↓
PostgresSaver checkpoint
  ↓
Open WebUI / mobile answer
  ↓
Command({ resume: value })
  ↓
same thread_id
  ↓
resume
```

## 16.5 Retention

```text
RUNNING / WAITING_APPROVAL / BLOCKED
→ retain

PASSED / DELIVERED
→ hot checkpoint 30 days

FAILED / CANCELLED / SUPERSEDED
→ hot checkpoint 14 days

development / test
→ 24 hours
```

Retention job must:

```text
skip active thread
archive audit artifact if required
delete complete thread through supported saver API
record audit event
```

---

# 17. Evidence Ledger

```text
execution_run
route_record
requirement_contract
output_contract
task_event
check_run
gate_verdict
pi_run
tool_outcome
artifact
final_result
```

Gate validity:

```text
same revision
+
NORMAL PASS
+
HIGH PASS
+
XHIGH PASS
+
explicit user approval
=
PUSH ALLOWED
```

Any source revision change:

```text
old gate verdicts
→ STALE
```

---

# 18. Workspace / Pi / CodeGraph Flow

```text
LÀM VIỆC task includes source write
  ↓
Coworker Harness
  ↓
WorktreeManager.create()
  ↓
task/<task-id>/<subtask-id>
  ↓
codegraph init <worktree> --yes
  ↓
codegraph explore
  ↓
Pi CODE_WORKER RPC
  ↓
source edit
  ↓
test / build / browser verification
  ↓
codegraph sync <worktree>
  ↓
independent Pi reviewers
  ↓
LangGraph approval interrupt
  ↓
Harness push / PR
```

Rule:

```text
BASE CHECKOUT INDEX
≠
WORKTREE INDEX
```

Every source-writing worktree needs independent CodeGraph lifecycle.

---

# 19. Context System

Context Ledger remains semantic authority.

```text
Event Stream
   ↓
Observer
   ↓
Context Ledger
   ↓
Reflector
   ↓
Dropper
   ↓
Deterministic Compiler
   ↓
Context Validator
   ↓
Context Package
```

Router context remains light.

Pi context remains local to Pi session.

LangGraph state remains reference-sized.

```text
Router context
≠
Pi session context
≠
LangGraph checkpoint
≠
Context Ledger package
```

---

# 20. Tool Architecture

## Router

```text
no tools
no MCP
no browser
no search
```

## CHAT

```text
memory when relevant
optional safe direct tools
```

## RESEARCH

```text
search_web
fetch_url
knowledge
video search
image search
```

## COWORKER Master

```text
task APIs
artifact APIs
context APIs
spawn subtask
get subtask result
```

## Pi Worker

```text
read
bash
edit
write
scoped MCP
workspace allowlist
```

## Pi Reviewer

```text
read
find
ls
codegraph read query

max_tool_calls = 8
```

---

# 21. Component Upgrade Triggers

This section is an explicit future decision record.

## Router

```text
Current:
Deterministic TypeScript + AI SDK + Zod
```

Evaluate BAML when:

```text
router prompts become a large versioned prompt library
many route schemas need independent prompt tests
declarative provider fallback becomes essential
```

Evaluate trained classifier / embeddings when:

```text
≥ 10,000 reviewed route labels
router latency/cost dominates at scale
mode taxonomy is stable
offline precision/recall exceeds LLM router baseline
```

## Checkpointer

```text
Current:
PostgresSaver
```

Evaluate alternate checkpointer when:

```text
PostgreSQL checkpoint writes become bottleneck
retention purge cannot meet operations target
cross-region low-latency execution is required
```

Do NOT replace PostgresSaver merely because Redis exists.

## Pi

```text
Current:
Pi RPC executor
```

Evaluate Pi Durable when:

```text
Pi RPC process model cannot meet multi-tenant durability requirement
agent execution needs a shared durable runtime beyond LangGraph adapter
ownership boundary can remain unambiguous
```

Do NOT introduce Pi Durable while LangGraph and Pi Durable would both own task workflow state.

## Mobile Operator Surface

```text
Current:
Open WebUI PWA for user
Pi Mobile / Tau for operator
```

Evaluate native custom mobile app when:

```text
operator workflow needs offline queue
push approval SLA cannot be met with PWA
device-native credential storage is required
```

---

# 22. Observability

Router Inspector:

```text
Mode: LÀM VIỆC
Execution: COWORKER
Source: DETERMINISTIC_RULE
Confidence: HIGH

Why:
✓ implementation requested
✓ persistent task state required
✓ review required

Classifier:
not called
```

When AI SDK is used:

```text
Classifier:
FAST_ROUTER_MODEL
Schema: ROUTE-SCHEMA-v1
Latency: 412ms
Usage: ...
Validation: PASS
```

Coworker Inspector tabs:

```text
[Route]
[Requirements]
[Output]
[Context]
[Tasks]
[Pi Runs]
[Tools]
[Checkpoints]
[Evidence]
[Quality]
[Cost]
[Lineage]
[Learned Strategy]
```

---

# 23. Router Metrics

Track:

```text
route_total
route_by_source
deterministic_route_rate
ai_classifier_route_rate
safe_fallback_rate
router_timeout_rate
schema_validation_failure_rate
transition_validation_rejection_rate
mode_precision
mode_recall
coworker_false_positive_rate
coworker_false_negative_rate
continuation_accuracy
side_query_isolation_accuracy
router_latency_p50
router_latency_p95
router_token_cost
```

Calibration dataset:

```text
ROUTE-001 → HỎI
ROUTE-010 → TÌM HIỂU
ROUTE-020 → LÀM VIỆC
ROUTE-030 → active task continuation
ROUTE-040 → side query
ROUTE-050 → explicit override
ROUTE-060 → classifier timeout fallback
ROUTE-070 → high-risk override
```

---

# 24. Test Matrix v3.9

## Router

```text
- explicit mode wins
- active task continuation wins
- side query does not mutate parent ledger
- deterministic implementation rule routes Coworker
- deterministic freshness rule routes Research
- ambiguous input invokes AI SDK exactly once
- Zod-invalid output uses safe fallback
- classifier timeout uses safe fallback
- high-risk rule survives classifier failure
- complexity hint cannot become authoritative complexity
- RouteRecord has redacted light input only
```

## AI SDK / Zod

```text
- accepted enum mapping
- invalid display/execution pair rejected
- reasons list bounded
- no free-form tool/permission field accepted
- timeout = 5 seconds
- retry ≤ 1
- temperature = 0
```

## LangGraph / PostgresSaver

```text
- HỎI and TÌM HIỂU do not create checkpoint by default
- LÀM VIỆC creates execution thread
- interrupt checkpoint survives harness restart
- same thread_id resumes exactly once
- retention skips active run
- state stores IDs not raw Pi transcript
```

## Pi / Worktree / Quality

```text
- worker cannot push/merge/create worktree
- source edit requires worktree-local CodeGraph init/sync
- reviewer is separate read-only run
- reviewer call budget enforced
- stale evidence/gates rejected
- UI edit requires browser verification evidence
```

---

# 25. Deployment Roadmap v3.9

## M0 — Router Foundation

```text
deterministic rules
AI SDK + Zod classifier
Transition Validator
RouteRecord
offline route dataset
```

## M1 — Pi Workspace Kit

```text
permission policy
workspace guard
memory compatibility
Google → SearXNG fallback
Figma token refresh
```

## M2 — Coworker Harness H1

```text
Pi RPC Adapter
Worktree Manager
CodeGraph lifecycle
deterministic checks
independent reviewers
Evidence Ledger
```

## M3 — PostgresSaver Production

```text
separate schema
controlled setup migration
interrupt restart test
retention job
checkpoint inspector
```

## M4 — Requirement / Output / Context

```text
Requirement Contract
Output Contract
Context Ledger
Context Validator
Recall
```

## M5 — Complexity / DAG / Multi-Agent

```text
Complexity Controller
Task Decomposer
Decomposition Reviewer
Pi subtask envelopes
artifact-mediated communication
```

## M6 — Cross-device

```text
Open WebUI PWA
Pi Mobile bridge fork
Tau operator surface
tailnet-only access
```

## M7 — Execution Learning

```text
effectiveness metrics
strategy candidate
offline evaluation
promotion gate
```

---

# 26. v3.9 Final Execution Chain

```text
USER
 ↓
OPEN WEBUI
 ↓
EXECUTION CLASSIFICATION PLANE
 ├── USER_EXPLICIT
 ├── ACTIVE_TASK_CONTINUATION
 ├── SIDE_QUERY_ISOLATION
 ├── DETERMINISTIC_RULE
 └── AI SDK + ZOD IF AMBIGUOUS
 ↓
TRANSITION VALIDATOR
 ├── HỎI
 │     ↓
 │   CHAT
 │
 ├── TÌM HIỂU
 │     ↓
 │   RESEARCH
 │
 └── LÀM VIỆC
       ↓
   COWORKER HARNESS
       ↓
   LANGGRAPH + POSTGRESSAVER
       ↓
   REQUIREMENT CONTRACT
       ↓
   OUTPUT CONTRACT
       ↓
   COMPLEXITY CONTROLLER
       ↓
   TASK DAG
       ↓
   WORKTREE MANAGER
       ↓
   PI EXECUTION PROFILES
       ↓
   CHECK / REVIEW / EVIDENCE GATES
       ↓
   INTERRUPT APPROVAL WHEN REQUIRED
       ↓
   FINAL
       ↓
   OPEN WEBUI
       ↓
   USER
```

---

# 27. v3.9 Final Rules

```text
ROUTE BY CODE FIRST.

CALL A MODEL ONLY FOR AMBIGUITY.

VALIDATE ALL MODEL ROUTES.

ROUTER DOES NOT OWN REQUIREMENTS.

ROUTER DOES NOT OWN COMPLEXITY.

LANGGRAPH DOES NOT RUN FOR EVERY MESSAGE.

PI EXECUTES.

LANGGRAPH TRANSITIONS.

POSTGRESSAVER CHECKPOINTS.

CONTEXT LEDGER TRUSTS.

EVIDENCE LEDGER VERIFIES.

WORKTREE MANAGER ISOLATES.
```

---

# Version 3.9 — Four-Level Review

## LOW — 9.5/10

PASS.

Strengths:

```text
- avoids expensive orchestration for simple questions;
- makes routing observable and testable;
- uses existing CLIProxy-compatible TypeScript stack;
- keeps LangGraph in its correct workflow role;
- preserves v3.8 authority boundaries.
```

## NORMAL — 9.2/10

Required implementation rules:

```text
1. Explicit selection and active-task continuation bypass AI classifier.

2. Classifier receives only light router context.

3. Zod output is validated again by transition code.

4. Fallback never silently starts expensive Coworker work.

5. Router output remains traceable by version and source.
```

Status:

```text
PASS WITH IMPLEMENTATION RULES
```

## HIGH — 8.9/10

Required improvements:

### H1 Router Evaluation

```text
offline labeled dataset
mode precision / recall
false positive / negative analysis
continuation and side-query accuracy
```

### H2 Prompt / Schema Versioning

```text
router version
schema version
model profile version
deterministic rule version
```

### H3 Provider Failure Policy

```text
timeout 5s
retry once
safe fallback
no infinite retry
```

### H4 Upgrade Discipline

```text
AI SDK / Zod update
→ rerun route dataset

model profile change
→ rerun route dataset

rule change
→ rerun route dataset
```

Status:

```text
PASS AFTER H1-H4
```

## XHIGH — 8.6/10 before production calibration; ~9.5/10 after corrections

### X1 Deterministic Authority

```text
LLM may classify ambiguity.

Code owns precedence.
Code owns mapping validation.
Code owns fallback.
Code owns state transition.
```

### X2 Cost Containment

```text
No model call for obvious route.
No LangGraph for HỎI.
No PostgresSaver checkpoint for ordinary HỎI / TÌM HIỂU.
No tool exposure for router.
```

### X3 Unsafe Escalation Prevention

```text
Classifier failure
≠
permission to start COWORKER.

Only explicit selection,
active continuation,
or deterministic high-risk rule
may force COWORKER under classifier failure.
```

### X4 Long-Term Decision Record

```text
component comparison
upgrade trigger
current choice
reason
measurement needed to revisit
```

must stay with architecture document.

## XHIGH Final Assessment

After X1-X4 and offline route calibration:

```text
Architecture readiness ≈ 9.5 / 10
```

Remaining risks:

```text
1. Router labeled dataset may not represent future user language.
2. FAST_ROUTER_MODEL quality may drift after CLIProxy model change.
3. Ambiguous boundary between Research and Work needs continuous calibration.
4. User-facing override UX must remain clear.
5. AI SDK structured-output behavior must be retested on provider upgrades.
```

---

# v3.9 Core Rule

```text
THE SYSTEM DOES NOT ASK A LARGE MODEL
TO DECIDE WHAT CODE ALREADY KNOWS.

THE SYSTEM USES A SMALL STRUCTURED MODEL CALL
ONLY WHEN THE MESSAGE IS GENUINELY AMBIGUOUS.

THE SYSTEM NEVER TRUSTS THE CLASSIFIER
MORE THAN EXPLICIT USER INTENT,
ACTIVE TASK CONTINUITY,
OR DETERMINISTIC SAFETY POLICY.
```
