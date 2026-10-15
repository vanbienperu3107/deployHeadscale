# AI Coworker Architecture & Deployment Plan v3.8



# Version 3.8 — Pi-Native Execution Harness + PostgresSaver Durable Control Plane

## 1. Architectural Decision

OpenCode is removed from the target architecture.

Pi becomes the only coding/agent execution harness.

```text
OpenCode
→ REMOVED FROM TARGET RUNTIME

Pi Coding Agent
→ execution harness

LangGraph
→ deterministic Coworker workflow control plane

PostgresSaver
→ durable LangGraph checkpoint persistence
```

Open WebUI remains the primary user-facing workspace.

```text
OPEN WEBUI-FIRST
PI-NATIVE EXECUTION
LANGGRAPH-CONTROLLED WORK
```

The system does NOT replace Open WebUI with Pi UI.

```text
Open WebUI owns user experience.
Pi executes agent work.
LangGraph owns workflow state.
PostgreSQL persists durable control state.
```

---

# 2. Why Pi Replaces OpenCode

## Current Findings

Measured on the same CLIProxy model and a small code-fix task:

```text
Pi
→ 19–31s
→ ~16K–43K tokens
→ 116–460 MB peak RAM

OpenCode
→ 130s
→ ~927K tokens
→ ~1 GB peak RAM
```

The raw token totals are not direct cost totals because cache reads cost less than fresh input.

However:

```text
Pi is materially lighter and faster.
```

Pi also exposes:

```text
RPC JSONL
extension hooks
tool_call blocking
user_bash interception
MCP native support
session JSONL persistence
compaction
interrupt-capable UI bridge
```

These capabilities make Pi suitable as a controlled executor under LangGraph.

---

# 3. v3.8 Core Principle

```text
PI DOES NOT OWN THE TASK LIFECYCLE.

LANGGRAPH DOES NOT OWN AGENT TRANSCRIPT MEMORY.

POSTGRESSAVER DOES NOT OWN SEMANTIC KNOWLEDGE.

EVIDENCE LEDGER DOES NOT REPLACE CHECKPOINTS.
```

Responsibility boundary:

```text
Pi
= What one agent sees and does in one execution session

LangGraph
= Where the Coworker workflow currently is

PostgresSaver
= Durable snapshots of LangGraph workflow state

Context Ledger
= What the system currently knows and trusts

Evidence Ledger
= What was actually verified for a requirement and revision

Open WebUI
= What the user sees and controls
```

---

# 4. v3.8 Final Architecture

```text
                         WINDOWS / MOBILE
                               │
                               ▼
                           OPEN WEBUI
                               │
      Native Chat / History / Notes / Memory / Knowledge / Files
                               │
                               ▼
                      Work Type Router
                 ┌─────────────┼─────────────┐
                 ▼             ▼             ▼
               HỎI         TÌM HIỂU       LÀM VIỆC
                 │             │             │
                 ▼             ▼             ▼
          Native Chat     Native Research    │
                                               ▼
                                  COWORKER HARNESS API
                                               │
                                               ▼
                                   LANGGRAPH CONTROL PLANE
                                               │
      ┌────────────────────────────────────────┼────────────────────────────────────────┐
      ▼                                        ▼                                        ▼
 Requirement Controller                    Context Layer                          Task/DAG Layer
      │                                        │                                        │
 Requirement Contract                  Context Ledger                       Complexity Controller
 Output Contract                       Context Compiler                     Decomposer / Reviewer
      │                                        │                                        │
      └────────────────────────────────────────┴─────────────────────┬──────────────────┘
                                                                      ▼
                                                               POSTGRESSAVER
                                                          workflow checkpoints
                                                                      │
                                                                      ▼
                                                              DAG SCHEDULER
                                                                      │
                                                       ┌──────────────┼──────────────┐
                                                       ▼              ▼              ▼
                                                  Pi Worker A    Pi Worker B    Pi Reviewer
                                                       │              │              │
                                              isolated worktree  research env    read-only env
                                                       │              │              │
                                              Pi session JSONL   Pi session JSONL  Pi session JSONL
                                                       └──────────────┼──────────────┘
                                                                      ▼
                                                        RESULT ACCEPTANCE GATE
                                                                      │
                                                                      ▼
                                                                 SYNTHESIS
                                                                      │
                                                              QUALITY GATE
                                                                      │
                                                                    FINAL
                                                                      │
                                                                  OPEN WEBUI

SERVER INTERNAL
├── PostgreSQL
│   ├── PostgresSaver checkpoints
│   ├── Coworker Evidence Ledger
│   ├── Requirement / Task / Context metadata
│   └── Strategy Memory
├── Pi Worker Runtime
├── Pi Extension Package
├── Pi Mobile Bridge / Tau (tailnet only)
├── CLIProxy
├── MCP / Research Tools
├── File / Object Storage
└── Workspace Manager / Git Worktrees
```

---

# 5. Work Type Router

User-facing work types remain:

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

Priority:

```text
USER_EXPLICIT
>
ACTIVE_TASK_CONTINUATION
>
AUTO_ROUTER
>
SYSTEM_DEFAULT
```

Routing uses only light control context:

```text
current_user_message
explicit_mode
active_task_metadata
conversation_mode_state
current_project
recent_message_summary
```

Do NOT retrieve:

```text
full Pi transcript
raw MCP outputs
all project notes
all research artifacts
all Context Ledger records
```

before routing.

---

# 6. Pi Execution Profiles

Pi is started through RPC only for Coworker work.

```text
pi --mode rpc
```

Every Pi run receives:

```yaml
pi_run:
  run_id: RUN-901
  task_id: TASK-100
  subtask_id: ST-104
  execution_profile: SECURITY_REVIEWER
  worktree_id: WT-104
  requirement_version: REQ-v7
  output_contract_version: OUT-ST104-v3
  context_version: CTX-ST104-v8
  pi_session_id: PI-SESSION-42
```

## Profiles

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

## Tool Exposure

```text
CODE_WORKER
→ read / bash / edit / write
→ scoped MCP tools
→ workspace allowlist

RESEARCHER
→ research MCP tools
→ request_context / get_artifact
→ no write/edit

REVIEWER
→ read / grep / find / ls
→ codegraph read access
→ no bash / edit / write / push

SYNTHESIS_AGENT
→ approved artifacts
→ Evidence Ledger query
→ no raw child transcript by default
```

No profile receives every tool.

---

# 7. Pi Extension Package

The Pi extension package is called:

```text
pi-workspace-kit
```

It ports required workspace behavior into Pi.

```text
Permission Policy
Memory Blocks
Google AI Search
Figma Token Refresh
Workspace Guard
Workflow Status
Evidence Reporter
```

## 7.1 Permission Policy

Pi default behavior is not sufficient.

Pi does NOT ask before every tool call by default.

Required rules:

```text
bash:
*                     → allow
rm *                  → deny
sudo *                → deny
systemctl *           → deny
docker *              → deny
kubectl *             → deny
git reset --hard*     → deny
git push*             → deny
gh pr merge*          → deny
git worktree add*     → deny
git checkout main     → deny
git checkout master   → deny

MCP:
mcp__github__*        → ask
```

Rule:

```text
HARNESS OWNS WORKTREE CREATION.
HARNESS OWNS PUSH / PR / MERGE.
PI NEVER OWNS THESE OPERATIONS.
```

For chained shell commands:

```text
echo ok && rm -rf x

→ DENY
```

Each command segment is evaluated.

```text
strictest_action_wins
```

If a tool requires approval and no interactive UI exists:

```text
ASK → BLOCK
```

## 7.2 Workspace Guard

Pi write/edit is allowed only inside an approved worktree.

```text
allowed_root
→ /worktrees/TASK-100/ST-104
```

All paths are normalized with:

```text
realpath()
```

Symlink escape example:

```text
/worktrees/TASK-100/ST-104/link
→ /home/node/.ssh

Result:
DENY
```

## 7.3 Memory Blocks

Existing memory block model remains:

```text
global/persona
global/human
project/project
```

Pi extension tools:

```text
memory_list
memory_set
memory_replace
```

Memory file frontmatter stays compatible:

```yaml
description: ...
label: human
limit: 5000
read_only: false
```

Current explicit user instruction remains higher priority than memory.

## 7.4 Google Search Fallback

Policy remains:

```text
google_ai_search_plus
↓ automated access blocked
↓
SearXNG immediately
```

No repeated Google retry.

---

# 8. LangGraph Control Plane

LangGraph owns:

```text
current node
completed nodes
pending branches
interrupt state
retry state
subgraph state
fan-out / fan-in
resume position
workflow transition legality
```

LangGraph does NOT own:

```text
Pi transcript
raw semantic context
raw tool output
Open WebUI chat history
memory blocks
approved evidence content
```

## H1 Code Workflow

```text
START
  ↓
create_worktree
  ↓
codegraph_init_and_explore
  ↓
Pi CODE_WORKER
  ↓
deterministic_checks
  ├── test
  ├── lint/build when applicable
  ├── codegraph_sync
  └── browser verification when UI changed
  ↓
Pi NORMAL_REVIEWER
  ↓
Pi HIGH_REVIEWER
  ↓
Pi XHIGH_REVIEWER
  ↓
pre_push_guard
  ↓
interrupt(PUSH_APPROVAL)
  ↓
push_branch
  ↓
watch_ci
  ↓
FINAL
```

No Pi worker can skip directly from:

```text
EXECUTING
→ PUSH
```

Illegal.

---

# 9. PostgresSaver Durable Checkpoint Plane

## 9.1 Responsibility

PostgresSaver persists LangGraph checkpoint state.

```text
PostgresSaver
= Where the workflow currently is
```

It is NOT:

```text
Context Ledger
Evidence Ledger
Open WebUI history store
Pi session transcript store
Knowledge/RAG store
```

## 9.2 Setup

```typescript
import { PostgresSaver } from "@langchain/langgraph-checkpoint-postgres";

const checkpointer = PostgresSaver.fromConnString(
  process.env.LANGGRAPH_DATABASE_URL,
  { schema: "coworker" }
);

await checkpointer.setup();
```

`setup()` runs only through controlled migration/deploy process.

Never run schema setup from arbitrary Pi worker session.

## 9.3 Thread Identity

```text
thread_id = execution_run_id
```

Example:

```text
RUN-8b2f4d4b-73e4-4f7a-a20a-7ad8fb5c9d31
```

Rules:

```text
thread_id < 255 chars
immutable
not user-provided text
not a filesystem path
not an API key
```

## 9.4 Graph State Rule

PostgresSaver state contains references, not raw work context.

```typescript
CoworkerState = {
  execution_run_id,
  task_id,
  requirement_version,
  output_contract_version,
  complexity_level,
  task_dag_version,
  worktree_ids,
  pi_run_ids,
  context_snapshot_ids,
  dependency_result_versions,
  evidence_map_version,
  pending_interrupt,
  status
}
```

Never store:

```text
full prompt
full Pi messages
raw image bytes
full research page content
credential material
```

## 9.5 Interrupt Durability

```text
LangGraph node
  ↓
interrupt(PUSH_APPROVAL)
  ↓
PostgresSaver checkpoint
  ↓
Open WebUI / Mobile approval UI
  ↓
Command({ resume: value })
  ↓
same thread_id
  ↓
resume
```

If process dies while waiting:

```text
restart harness
↓
load thread_id
↓
inspect pending interrupt
↓
resume
```

## 9.6 PostgresSaver Tables

Expected package-owned tables:

```text
checkpoint_migrations
checkpoints
checkpoint_blobs
checkpoint_writes
```

Conceptual role:

```text
checkpoint_migrations
→ package schema version

checkpoints
→ graph state snapshots / parent lineage

checkpoint_blobs
→ complex versioned channel values

checkpoint_writes
→ completed node writes available for fault recovery
```

Do NOT manually update these tables.

## 9.7 Retention

PostgresSaver does not replace retention policy.

```text
RUNNING / WAITING_APPROVAL / BLOCKED
→ retain

PASSED / DELIVERED
→ hot checkpoint 30 days

FAILED / CANCELLED / SUPERSEDED
→ hot checkpoint 14 days

development / test run
→ 24 hours
```

Retention job must:

```text
skip active thread
archive required audit artifact
delete complete thread through saver API
record deletion audit event
```

Never delete only `checkpoints` rows while leaving blobs/writes orphaned.

---

# 10. Evidence Ledger

PostgresSaver checkpoint tells workflow position.

Evidence Ledger tells verified truth.

```text
Evidence Ledger
├── execution_run
├── task_event
├── check_run
├── gate_verdict
├── artifact
├── tool_outcome
├── reviewer_run
└── final_result
```

Example:

```yaml
gate_verdict:
  id: GATE-31
  execution_run_id: RUN-901
  task_id: TASK-100
  level: HIGH
  verdict: PASS
  revision: e763ceb...
  reviewer_run_id: RUN-REVIEW-H-12
  evidence_ids:
    - CHECK-18
    - CG-22
  created_at: ...
```

Push eligibility:

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

Any revision change:

```text
old gate verdicts
→ STALE
```

---

# 11. Workspace Manager — Pi-Native

Workspace policy:

```text
Pure Chat / Research
→ logical workspace

Independent artifact output
→ logical workspace or optional worktree

Any source write
→ mandatory Git worktree

Concurrent source writes
→ one worktree per subtask
```

Only Coworker Harness can create worktrees.

```text
WorktreeManager.create()
```

Example:

```text
task/100-integration
task/100/code
task/100/security
task/100/tests

/worktrees/task-100/code
/worktrees/task-100/security
/worktrees/task-100/tests
```

Every worktree records:

```text
workspace_id
task_id
subtask_id
repository
base_commit
branch
worktree_path
codegraph_index_status
status
```

## CodeGraph Rule

CodeGraph index is worktree-scoped.

```text
base checkout index
≠
worktree index
```

Before source discovery in a worktree:

```text
codegraph init <worktree> --yes
codegraph explore <query>
```

After any source change:

```text
codegraph sync <worktree>
```

Pi source edit cannot settle as PASS without current CodeGraph evidence.

---

# 12. Context System v3.8

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

Pi session compaction is local execution compaction.

```text
Pi compaction
≠
Context Ledger compaction
```

Pi compaction preserves an agent session.

Context Ledger compaction preserves task semantic state.

Both must be observable.

## Context Layers

```text
CORE
├── Requirement Contract
├── critical constraints
└── active Output Contract

DURABLE
├── approved decisions
├── stable reflections
└── project principles

WORKING
├── current research
├── dependency results
├── approved evidence
└── current artifact refs

EPHEMERAL
├── Pi tool output
├── recent worker thought/result
└── temporary intermediate notes
```

Never automatically drop:

```text
current user request
Requirement Contract
Output Contract
critical constraints
approved decisions
current task goal
```

---

# 13. Pi Subtask Envelope

Master does NOT send whole parent context.

```yaml
subtask_envelope:
  subtask_id: ST-104
  parent_task_id: TASK-100
  execution_run_id: RUN-901

  requirement_version: REQ-v7
  output_contract_version: OUT-ST104-v3
  context_version: CTX-ST104-v8

  objective: Design public Internet security model

  assigned_requirements:
    - R5
    - R6
    - R9

  critical_constraints:
    - CLIProxy private
    - PostgreSQL private
    - no direct push or merge

  approved_decisions:
    - D4

  dependency_results:
    - ST101_RESULT-v2

  artifacts:
    - architecture-v5.md

  tool_profile: SECURITY_REVIEWER

  worktree:
    id: WT-104
    path: /worktrees/task-100/security
    base_commit: abc123

  context_policy:
    max_tokens: 32000
    recall_allowed: true
    parent_context_access: ON_DEMAND
```

Pi does NOT receive:

```text
all parent history
full sibling transcript
raw unrelated tool output
unapproved draft decisions
credential data
```

---

# 14. Pi Task Reporting Protocol

Pi RPC events are normalized by Pi Executor Adapter.

```text
Pi RPC event
   ↓
Pi Executor Adapter
   ↓
Tool Outcome / Task Event
   ↓
Evidence Ledger
   ↓
LangGraph State Update
```

Mandatory normalized events:

```text
TASK_PROGRESS
TASK_BLOCKER
TASK_RESULT
```

Optional:

```text
TASK_WARNING
TASK_CHECKPOINT
TOOL_OUTCOME
PI_COMPACTION
PI_UI_APPROVAL_REQUESTED
```

## Pi UI Approval

Pi extension can emit:

```text
extension_ui_request
```

Pi mobile bridge / Tau / Open WebUI adapter renders it.

Response:

```text
extension_ui_response
```

This is local tool approval.

High-impact workflow approval remains LangGraph interrupt:

```text
LangGraph interrupt(PUSH_APPROVAL)
```

These are different approval classes.

```text
Pi approval
= may this tool call execute?

LangGraph approval
= may the workflow enter this irreversible state?
```

---

# 15. Complexity Engine v3.8

Complexity remains separate from work type.

```text
Work Type
= HỎI / TÌM HIỂU / LÀM VIỆC

Processing Level
= NHẸ / VỪA / NẶNG / RẤT NẶNG
```

Mapping:

```text
LÀM VIỆC + NHẸ
→ one Pi run + deterministic checks when needed

LÀM VIỆC + VỪA
→ small LangGraph workflow + 2–3 Pi runs

LÀM VIỆC + NẶNG
→ Task DAG + Pi subgraphs + integration review

LÀM VIỆC + RẤT NẶNG
→ full DAG
→ independent reviewer profiles
→ PostgresSaver resume
→ mandatory human approval for defined transitions
→ adversarial review when risk requires
```

Hard overrides:

```text
data loss risk
security-critical decision
production deployment
large migration
direct public Internet exposure
independent review policy
```

Force:

```text
XHIGH
```

---

# 16. Quality Gate v3.8

## Source Change Gate

```text
Pi worker result
  ↓
CodeGraph evidence current for worktree?
  ↓
tests after last source edit?
  ↓
UI verification after last UI edit when applicable?
  ↓
git diff scoped to worktree?
  ↓
accept worker result
```

## Review Gate

```text
Worker Result
  ↓
NORMAL Reviewer
  ↓ PASS
HIGH Reviewer
  ↓ PASS
XHIGH Reviewer
  ↓ PASS
LangGraph Push Approval Interrupt
  ↓ APPROVED
Harness Push / PR
```

Reviewers are independent Pi runs.

```text
reviewer_run_id
must differ from worker_run_id
```

Reviewer profile:

```text
read
grep
find
ls
codegraph read query

max_tool_calls = 8
```

Reviewer output:

```json
{
  "level": "HIGH",
  "verdict": "PASS",
  "revision": "e763ceb...",
  "findings": [],
  "evidence_ids": ["CHECK-18", "CG-22"]
}
```

Any mandatory failure:

```text
REVISE
```

Any revision change:

```text
all old gates → STALE
```

---

# 17. Failure / Resume Policy

## Pi Process Failure

```text
Pi process dies
  ↓
Pi session JSONL remains
  ↓
LangGraph checkpoint remains in PostgresSaver
  ↓
Pi Executor Adapter classifies failure
  ↓
retryable?
  ├── YES → start replacement Pi run + switch/resume session
  └── NO  → TASK_BLOCKER / NEEDS_USER_DECISION
```

## Harness Process Failure

```text
Harness dies
  ↓
PostgresSaver checkpoint remains
  ↓
Harness restart
  ↓
load thread_id
  ↓
validate requirement / dependency / evidence versions
  ↓
resume or rebuild context
```

## Requirement Change

```text
REQ-vN
  ↓ user changes scope
REQ-vN+1
  ↓
Impact Analyzer
  ├── unaffected → continue
  ├── affected → pause + rebuild envelope
  └── obsolete → supersede/cancel
```

No blind replay of old Pi transcript.

---

# 18. Mobile / Remote Access

## Default User Workspace

```text
Windows / Mobile
→ Open WebUI PWA
```

## Pi Operator / Developer Surface

```text
Pi Mobile Android
→ pi-mobile bridge
→ Pi RPC

Tau PWA
→ Pi RPC
```

Both are:

```text
tailnet only
Bearer token required
no public Internet exposure
cwd allowlist required
```

Bridge security:

```text
BRIDGE_HOST = tailnet or loopback
BRIDGE_ALLOWED_CWDS = approved roots
BRIDGE_AUTH_TOKEN = secret
BRIDGE_ENABLE_HEALTH_ENDPOINT = explicit
```

The bridge must reject:

```text
outside allowed cwd
symlink escape
token in query string
malformed envelope
concurrent control lock conflict
```

---

# 19. Data Model v3.8

## Open WebUI-Owned

```text
users
chats
messages
notes
memory
files
knowledge
native tasks
```

## PostgresSaver-Owned

```text
checkpoint_migrations
checkpoints
checkpoint_blobs
checkpoint_writes
```

## Coworker-Owned

```text
execution_run
coworker_task
task_dependency
task_requirement_map
task_workspace
task_artifact
task_run
task_event

requirement_contract
requirement_item
output_contract
deliverable_item

context_observation
context_reflection
context_snapshot

research_run
research_source
research_claim
claim_evidence

check_run
gate_verdict
reviewer_run

pi_run
pi_session_ref
pi_compaction_event
pi_ui_approval

draft
final_result
```

Every relevant Coworker object references:

```text
task_id
execution_run_id
requirement_version
output_contract_version
version
status
created_at
created_by
superseded_by
```

---

# 20. Postgres Schema Boundary

Recommended schemas:

```text
openwebui
→ Open WebUI owned data

coworker
→ PostgresSaver + Coworker control/evidence data
```

Do NOT use:

```text
public
```

for new Coworker tables.

Postgres role separation:

```text
coworker_runtime
→ read/write coworker schema only

coworker_migrator
→ schema migration only

readonly_inspector
→ inspector queries only
```

Pi worker does NOT receive direct PostgreSQL credentials.

```text
Pi Worker
→ Harness API
→ Evidence Ledger / PostgresSaver
```

not:

```text
Pi Worker
→ PostgreSQL direct
```

---

# 21. Execution Learning v3.8

v3.7 learning rules remain.

Additional Pi/Harness metrics:

```text
pi_run_success_rate
pi_rpc_restart_rate
pi_session_resume_success_rate
pi_tool_policy_block_rate
reviewer_tool_call_count
reviewer_token_budget_exceeded_rate
worktree_creation_failure_rate
codegraph_worktree_init_rate
stale_gate_rejection_rate
push_before_approval_block_rate
checkpoint_resume_success_rate
checkpoint_storage_bytes_per_run
checkpoint_retention_delete_success_rate
```

Execution path signature adds:

```text
pi_version
pi_extension_version
pi_profile
pi_session_id
worktree_base_commit
postgressaver_schema_version
checkpoint_count
interrupt_count
```

Strategy promotion remains forbidden from changing:

```text
production graph topology
system prompt
tool permission policy
security policy
retention policy
```

without versioned change and rollback.

---

# 22. Test Matrix v3.8

## Pi Harness

```text
- Pi RPC prompt / abort / steer / follow-up
- Pi UI approval round-trip
- Pi process crash and session resume
- malformed RPC record rejected
- stdout drained continuously
- stderr never parsed as protocol
```

## Worktree / CodeGraph

```text
- base checkout unchanged
- one source-writing subtask = one worktree
- base_commit recorded
- CodeGraph init inside each worktree
- CodeGraph sync after every source edit
- stale CodeGraph evidence rejected
- no direct merge to main
```

## PostgresSaver

```text
- setup migration idempotent
- thread_id length < 255
- checkpoint written on interrupt
- process restart resumes same pending interrupt
- parallel branch partial completion persists
- retention skips active thread
- retention deletes complete thread safely
- package version upgrade tested against snapshot DB
```

## Gates

```text
- worker cannot push
- worker cannot create worktree
- reviewer cannot write/edit/bash
- all three reviewer run IDs differ
- stale revision gate rejected
- push blocked before user approval
- push allowed only after exact approval + exact SHA gates
```

## Pi Mobile Bridge

```text
- Bearer token required
- query-string token rejected
- cwd outside allowlist rejected
- symlink escape rejected
- reconnect preserves control only within grace
- second client denied while lock valid
- second client succeeds after grace
```

---

# 23. Deployment Roadmap v3.8

## M0 — Pi + CLIProxy Certification

```text
chat
streaming
tool calls
multi-round tools
MCP conversion
Pi RPC
permission extension
```

## M1 — Pi Workspace Kit

```text
permission policy
workspace guard
memory compatibility
Google → SearXNG fallback
Figma token refresh
workflow status commands
```

## M2 — Coworker Harness H1

```text
LangGraph graph
Pi RPC Adapter
Worktree Manager
CodeGraph evidence
deterministic checks
Normal / High / XHigh reviewers
LangGraph push approval interrupt
Evidence Ledger
```

## M3 — PostgresSaver Production Persistence

```text
separate coworker schema
controlled setup migration
process restart resume
retention job
checkpoint observability
```

## M4 — Requirement + Output Contracts

```text
requirement resolver
requirement reviewer
immutable REQ versions
output contracts
deliverable mapping
```

## M5 — Context Infrastructure

```text
ledger
observer
reflector
dropper
compiler
validator
recall
inspector
```

## M6 — Complexity + DAG

```text
complexity engine
decomposer
decomposition reviewer
Pi subtask envelopes
artifact-mediated dependency flow
```

## M7 — Multi-Agent Pi Execution

```text
parallel Pi workers
max parallelism
dependency-aware resume
conflict resolution
synthesis
integration review
```

## M8 — Cross-device

```text
Open WebUI PWA
Pi Mobile bridge fork
Tau operator surface
tailnet-only remote access
```

## M9 — Effectiveness + Strategy Memory

```text
run evaluator
baseline comparison
strategy candidate
offline evaluation
promotion gate
```

---

# 24. v3.8 Final Execution Chain

```text
USER
 ↓
OPEN WEBUI
 ↓
WORK TYPE ROUTER
 ├── HỎI
 │     ↓
 │   NATIVE CHAT / PI DIRECT
 │
 ├── TÌM HIỂU
 │     ↓
 │   NATIVE RESEARCH / PI RESEARCH PROFILE
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
   COMPLEXITY ENGINE
       ↓
   TASK DAG
       ↓
   WORKTREE MANAGER
       ↓
   PI SUBTASK ENVELOPES
       ↓
   PI WORKERS / PI REVIEWERS
       ↓
   TASK RESULT ACCEPTANCE
       ↓
   EVIDENCE LEDGER
       ↓
   SYNTHESIS
       ↓
   INTEGRATION QUALITY GATE
       ↓
   LANGGRAPH APPROVAL INTERRUPT
       ↓
   FINAL
       ↓
   OPEN WEBUI
       ↓
   USER
```

---

# 25. v3.8 Final Rules

```text
OPEN WEBUI OWNS THE USER EXPERIENCE.

PI OWNS INDIVIDUAL AGENT EXECUTION.

LANGGRAPH OWNS WORKFLOW STATE TRANSITIONS.

POSTGRESSAVER OWNS DURABLE WORKFLOW CHECKPOINTS.

CONTEXT LEDGER OWNS SEMANTIC CONTEXT.

EVIDENCE LEDGER OWNS VERIFIED EXECUTION FACTS.

WORKTREE MANAGER OWNS SOURCE-WRITE ISOLATION.

PI NEVER PUSHES.

PI NEVER MERGES.

PI NEVER CREATES A WORKTREE.

CHECKPOINT IS NOT CONTEXT.

CHECKPOINT IS NOT EVIDENCE.

RAW AGENT HISTORY REMAINS RECALLABLE.
```

---

# Version 3.8 — Four-Level Review

## LOW — 9.4/10

PASS.

Strengths:

```text
- removes dual harness ambiguity;
- keeps Open WebUI-first product strategy;
- makes Pi a lightweight replaceable executor;
- makes workflow state durable through PostgresSaver;
- separates checkpoint, semantic context and verified evidence;
- prevents Pi worker from direct push/merge/worktree authority.
```

## NORMAL — 9.1/10

Required implementation rules:

```text
1. PostgresSaver state contains IDs/references, not raw agent context.

2. Every source-writing Pi run starts inside a Harness-created worktree.

3. Every worktree has its own CodeGraph init/sync lifecycle.

4. Reviewers are separate read-only Pi runs.

5. LangGraph interrupt owns high-impact approval; Pi UI owns local tool approval.

6. HỎI/TÌM HIỂU do not enter expensive Coworker graph by default.
```

Status:

```text
PASS WITH IMPLEMENTATION RULES
```

## HIGH — 8.8/10

Required improvements:

### H1 PostgresSaver Retention

```text
checkpoint growth must be bounded;
active thread must never be pruned;
deletion must use supported saver/thread lifecycle;
retention audit is mandatory.
```

### H2 Idempotent Side Effects

```text
no push / external mutation before interrupt approval;
worktree creation keyed by task/subtask id;
retry must not duplicate artifact or external action.
```

### H3 Runtime Capacity

```text
Pi worker and OpenCode cannot be assumed safe on same constrained vpn4 host.
Worker capacity preflight is mandatory.
```

### H4 Reviewer Budget

```text
max_tool_calls = 8
strict JSON verdict
independent reviewer run ids
```

Status:

```text
PASS AFTER H1-H4
```

## XHIGH — 8.5/10 before runtime certification; ~9.5/10 after corrections

### X1 Control Authority

```text
Pi may execute.
Pi may report.
Pi may request approval.

Pi may not transition authoritative task state.
Pi may not push.
Pi may not merge.
Pi may not create worktrees.
```

### X2 Triple Persistence Boundary

```text
PostgresSaver
→ workflow position

Context Ledger
→ semantic trust

Evidence Ledger
→ verified facts
```

No layer replaces another.

### X3 Crash / Resume Certification

Must prove:

```text
pending LangGraph interrupt
↓ harness killed
↓ harness restarted
↓ same thread_id loaded
↓ resume accepted
↓ no duplicate push / worktree / tool side effect
```

### X4 Security Boundary

```text
Pi extension policy
is NOT the security boundary.

Container / OS / network isolation
is the security boundary.
```

### X5 Evidence Integrity

```text
gate verdict valid only for exact revision;
reviewer identity must differ from worker;
check evidence must be later than last source edit;
approval must be lineage-linked to exact run and revision.
```

## XHIGH Final Assessment

After X1-X5 and production PostgresSaver restart/retention certification:

```text
Architecture readiness ≈ 9.5 / 10
```

Remaining engineering risks:

```text
1. CLIProxy native tool-call and streaming compatibility across all Pi profiles.
2. Pi extension package supply-chain and upgrade discipline.
3. PostgresSaver checkpoint storage growth and migration compatibility.
4. Semantic Context Ledger selection quality.
5. Evidence reviewer false-negative rate.
6. Capacity sizing for Pi workers with full MCP/browser workloads.
7. Open WebUI integration UX complexity.
```

---

# v3.8 Core Rule

```text
THE SYSTEM DOES NOT TRUST:
"THE AGENT SAID IT IS DONE."

THE SYSTEM TRUSTS:
WORKTREE ISOLATION
+
CURRENT CODEGRAPH EVIDENCE
+
POST-EDIT CHECKS
+
INDEPENDENT REVIEW GATES
+
LINEAGE-LINKED HUMAN APPROVAL
+
DURABLE CHECKPOINT / RESUME
```
