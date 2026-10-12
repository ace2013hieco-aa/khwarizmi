# WIRING_DESIGN — binding the five platform planes behind `apply_intent`

**Role:** designer. **Worktree:** `D:\New folder\research-agent\.worktrees\wiring`.
**Branch:** `wiring/w0-design` cut from `main` tip `a8f0180`
(`test(platform): allowlist eval hostile/import_gate as declared governance consumers`).
**Deliverable:** this file only. **Zero edits to anything else. No staging. No commits. No code.**

**Status:** design only. No implementation, no dependency added, no existing file
modified, no substrate adopted. Where this document names an existing surface it
cites the source at the baseline commit; where docs and code disagree,
**the code is quoted** (repo convention, `docs/ARCHITECTURE.md` preamble).

**Inputs read (not modified) at `a8f0180`:**

- `ARCHITECTURE_DELTA.md` (all 281 lines, the R1 three-planes-plus-spine delta).
- `docs/ARCHITECTURE.md` §§3.2–3.6 (layer map, primary write path, read path,
  research/provider boundary, authority boundary) plus §3.8–§3.10 for the
  identity/isolation/transaction census this design must not disturb.
- Controller tick/dispatch surfaces: `src/hermes/research/controller.py`
  `tick:934`, `run:1076`, `_task_handlers:716` (ctor arg `:694`, dispatch
  `:3048`/`:3073`, classification `:5108`/`:5173`), `resolve_human_gate:1764`,
  lease block (acquire/renew/release, `LOCK` on contention, `lock_lost` rollback).
- Gateway validators: `src/hermes/research/gateway.py` `apply_intent:4038`
  (delta cited `:3961`; drift noted — code wins), rejection-code block
  `:105–:120` (`ROLE`, `UNKNOWN_KIND`, `NOT_WIRED`, `PROJECT_NOT_FOUND`,
  `MALFORMED_PAYLOAD`, `SCOPE_NOT_GOVERNED`, `NOT_COMPILED`, `STALE`, `BUDGET`,
  `DEPENDENCY`, `IDEMPOTENCY_CONFLICT`, `PROVENANCE`, `CLASSIFICATION_REF`,
  `PROPOSAL`, `EVIDENCE_REF`, `OPERATOR`) plus the frozen spine vocabulary
  `LOCK` (controller lease contention / mid-tick loss) and `RATIONALE`
  (4 KiB / rationale bound, `persistence/event_validation.py`,
  `DEFAULT_PAYLOAD_MAX_BYTES = 4096`), and the 15 `_validate_*` validators.
- Task-handler registration: `Controller(task_handlers: dict[str, Callable])`
  (`controller.py:659`, `:694`, `:716`); per-template dispatch `:3048`/`:3073`;
  `unhandled` fail-closed `:5173`.
- The five platform planes as built (read-only; no edits anywhere):
  R2 model plane (`src/hermes/tools/models/router.py`, `ModelRouter.invoke:1398`,
  `replay_bytes:1434`, `invoke_stream:1416`, `RecordedModelProvider:1016`);
  R3 capability plane (`src/hermes/tools/capabilities/registry.py`,
  `invoke.py:CapabilityInvoker.invoke:356`, `envelope.py`, `types.py`);
  R4 agent runtime (`src/hermes/agents/runtime/run.py:AgentRuntime.run:326`,
  `run:1469`, `_emit_intent:770`, `_apply:802`, `delegate.py`, `supervisor.py`,
  `checkpoint.py`, `projection.py`);
  R5 governance plane (`src/hermes/governance/policy.py:resolve:646`,
  `authority.py:evaluate_authority:552`, `approvals.py:evaluate_approval`);
  R6 methodology plane (`src/hermes/methodology/workflows.py:run_methodology:509`,
  `parse_methodology:244`, `substrate.py` identity `node_id_of:295`,
  `edge_id_of:307`).
  R7 (`src/hermes/eval/*`: `matrix.py`, `ops.py`, `hostile.py`, `import_gate.py`,
  `extensions.py`, `platform_cli.py`, `EXTENSIONS.md` nine frozen points) is
  **not a sixth wired plane** in this design — it is the verification /
  adversarial harness and the production-surface manifest. Its files appear
  below only as test guards and as two already-declared governance consumers.

**Forbidden restated (binding on this document and on W1–W4):**
no code, no dependency adds, no new authorities / codes / kinds / events /
tables proposed (each such need is named as an **open gate item** instead),
no edits to any existing file in this slice, no staging, no commits.

---

## 0. The five binding questions (reconstruction)

The brief references "the five binding questions above". No such list exists in
this turn's context, so this design **reconstructs** the only five questions
consistent with the inputs: one per currently-unwired platform plane (R2–R6),
each asking how that plane binds behind `apply_intent` without creating a
second write path. A hostile reviewer can verify the reconstruction: R2/R3/R4
reports build one plane each as new-files-only; R5 reports
"complete, and deliberately unwired" with `test_the_plane_is_wired_to_nothing`;
R6 reports "complete, with one honest collision" and the same unwired posture
for the spine; R7 is the matrix/surface/manifest, not a plane seeking a write
binding. If the owning director meant a different five, this section fails
closed: every binding below is still traceable call-by-call, and §8 lists what
a sixth binding would need as a gate.

| ID | Binding question | Plane (as built) | Plane entry cited |
|---|---|---|---|
| BIND-1 | How does a capability call execute from a tick without becoming a writer? | R3 Capability | `CapabilityInvoker.invoke` (`invoke.py:356`), `invoke_from_mapping:406`, registry `register_tool:105` / `register_capability:151` / `register_tool_set:174` / `register_plugin:190` |
| BIND-2 | How does a model call produce only proposals that re-enter through intents? | R2 Model | `ModelRouter.invoke:1398`, `invoke_stream:1416`, `replay_bytes:1434`, `RecordedModelProvider.invoke:1092` |
| BIND-3 | How does an agent run/delegation produce only proposals with B-2 discipline? | R4 Runtime | `AgentRuntime.run:326`, `run:1469`, `_emit_intent:770`, `_apply:802`, `delegate.py:InMemoryDelegationStore`, `projection.py` |
| BIND-4 | How does the spine consult governance without giving it a write or an authority? | R5 Governance | `evaluate_authority:552`, `policy.resolve:646`, `approvals.evaluate_approval`, `emitted_refusal_codes` |
| BIND-5 | How does a methodology run orchestrate R4+R3+R2 and record only through existing boundaries? | R6 Methodology | `run_methodology:509`, `parse_methodology:244`, `substrate.node_id_of:295` / `edge_id_of:307` |

Design rule applied to all five (from `ARCHITECTURE_DELTA.md` §1–§3):
**no plane writes.** Every plane operation is read/derive or a bounded
proposal (≤4 KiB or artifact-ref overflow) that re-enters through the
Orchestration API and becomes durable **only** inside the existing
validator → repository-tx chain driven by `apply_intent`. No plane opens
SQLite or a transaction — ever. No plane participates in lease custody.

Notation below per binding: numbered call sequence
`caller → plane entry → spine check → write-or-refusal`; then three tables
(transaction/lease attribution per step; refusal code per failure; R5
`allowed_consumers` delta); then an invariant-by-invariant no-impact ledger.
`allowed_consumers` is the exact set asserted in
`tests/test_governance_plane.py:2141–2147`:
`{methodology/workflows.py, eval/hostile.py, eval/import_gate.py}`.
Each binding states its delta to that set (possibly empty).

---

## BIND-1 — Capability execution binding (R3 → spine via task handlers)

**Question:** how does a capability call execute from a tick without becoming
a writer?

**Answer:** capabilities execute **inside** a task-handler call owned by the
tick, return envelope-wrapped untrusted observations, and reach durability
**only** through the one source-outcome write boundary with content-hash
identity and task binding (`docs/ARCHITECTURE.md` §3.5). The handler never
writes; it returns a `HandlerResult`-shaped value the controller routes to the
ordinary write path (the `SOURCE_SEARCH`/`SOURCE_FETCH` precedent:
`source_handlers.py:326–359` discipline, without adding a new template here —
see §8 for the gate if a new template is ever wanted).

**Call sequence (traceable):**

1. `Controller.tick:934` → eligible-task scan → `template in self._task_handlers`
   (`:3048`) → `entry = self._task_handlers.get(template)` (`:3073`).
2. Handler entry (future W1 file, see §6) → `CapabilityInvoker.invoke(request)`
   (`invoke.py:356`) with closed schema (`capability id`, args vs declared
   schema, envelope context, lease-generation tag, hazard spec).
3. Inside invoke, in order: `_require_schema:423` → `_require_lease:440` →
   `_resolve_capability:447` → `_authorize:476` → `_declared_arguments:545` →
   `_require_credential_free_inputs` / `_require_secret_free_inputs` →
   `_replayed_or_conflict:646` → `_sandbox_gate:680` → `_hazard_gate:722` →
   `_rate_decision:758` → `_gated_execution:772` → `_execute:795` →
   `_observation:871` / `_failed:907` (envelope via `_envelope_for:921`).
4. Handler returns observation (untrusted, envelope-wrapped) to the tick;
   the tick proposes the ordinary admission intent for that outcome
   (existing kind only — no new kind; §8).
5. `apply_intent:4038` → role gate → project gate → payload schema →
   credential-exists → HumanDecision dereference (where the kind requires it)
   → domain validators (identity re-derivation, ref re-resolution in-tx) →
   repository write (`BEGIN IMMEDIATE` owned by that repository) →
   `_append_event_to_db` → COMMIT; or refusal-as-data.

**Transaction / lease attribution per step:**

| Step | Actor | Transaction owner | Lease role |
|---|---|---|---|
| 1 tick scan + dispatch | Controller | none (reads are advisory, re-resolved on every call; §3.4) | tick holds the scheduler-lease fence; contention elsewhere returns `LOCK`; mid-tick loss aborts to `lock_lost` with rollback |
| 2–3 capability invoke + gates | R3 plane | **none — forbidden by construction.** `CapabilityInvoker` owns no `BEGIN`; no plane-owned log | plane carries the lease-generation **tag** only (B-4 attribution); never custody |
| 4 handler return → intent proposal | Handler (spine-owned call site) | none yet (proposal carries no identity, ≤4 KiB or artifact ref) | generation tag propagated, not re-issued |
| 5 `apply_intent` → repository write | Gateway + repository | the **existing** repository owner for that boundary (one `BEGIN IMMEDIATE` per §3.10 census: persistence 18 / gateway 5 / controller 4; no 28th owner added) | controller lease held for the verdict/write duration where the surface is lease-held; `LOCK` on contention |

**Refusal code per failure (existing vocabulary only, meanings frozen):**

| Failure | Code | Emitted by |
|---|---|---|
| capability attempts to author state / mutating tool | `ROLE` | invoker `_authorize` / spine role gate |
| invoked outside held lease / mid-run loss | `LOCK` | `_require_lease:440` (tag check) then controller fence (`lock_lost`) |
| output treated as evidence without repository write | `PROPOSAL` | spine (no write without admission) |
| schema / unknown-key violation | `MALFORMED_PAYLOAD` | `_require_schema:423` then gateway schema gate |
| referenced artifact does not dereference in-project | `EVIDENCE_REF` | domain validator re-resolution in-tx |
| supersession / chain-head violation on referenced records | `STALE` | validator |
| oversized payload where cap applies | `RATIONALE` | `event_validation` before any write |
| project missing / cross-project citation | `PROJECT_NOT_FOUND` / resolver fail-closed (`EVIDENCE_DOES_NOT_RESOLVE` per §3.9) | project gate / resolver |
| idempotency-key reuse for a different task | `IDEMPOTENCY_CONFLICT` | `_replayed_or_conflict:646` then gateway |

**R5 `allowed_consumers` delta for BIND-1:** **∅ (empty).**
BIND-1 does not import `hermes.governance`. If a future capability needs a
governance preflight, that file must be added to the allowlist as its own
gated delta — not smuggled inside BIND-1.

**No-impact ledger for BIND-1 (invariant-by-invariant):**

- Sole-write-path (`gateway.py:4038`): no impact — handler returns observations;
  the only mutation is the pre-existing repository boundary via `apply_intent`.
- Append-only journal (table-scoped): no impact — `_append_event_to_db`
  remains the only writer; no second log.
- Lease fence: no impact — custody stays in the controller; plane takes a tag.
- Content-hash identity: no impact — plane supplies no ID; write boundary
  recomputes (`fx_` for fixtures where retained; evidence identity at
  `source_outcomes.py` with N9 predicate in-tx).
- Human-authority boundary (`intents.py:124`/`:144`): no impact — capability
  cannot propose `internal_only` kinds; verdict-shaped output without a bound
  `HumanDecisionReceived` refuses `PROPOSAL`.
- Project isolation (§3.9): no impact — every resolve is project-scoped;
  cross-project citation fails closed.
- 4 KiB cap: no impact — every plane crossing checked; overflow via
  `artifacts/store.py` content-hash-keyed ref.
- N1 (`contradictions.py:106`) / N9 (`source_outcomes.py:159`): no impact —
  frozen predicates untouched; no slot feeds them.
- Determinism (no model decides): no impact — BIND-1 involves no model.
- Minimal-core / no substrate / import bans (§3.1): no impact — new handler
  imports ports + core types only; never `persistence`/repositories/SQL;
  tools→research ban respected (single recorded exception `hazards.py:137`
  untouched; `research_sources.py:33` standing violation not extended).
- Archive-not-delete / head-only supersession / refusal-as-data: no impact —
  no DELETE; second supersede link still refused; rejections return data.

---

## BIND-2 — Model inference binding (R2 → spine as proposals/bytes only)

**Question:** how does a model call produce only proposals that re-enter
through intents?

**Answer:** the model plane exposes `invoke`/`describe`/`replay_bytes` behind
ports; all output crosses into Hermes as envelope-wrapped untrusted content
(`security/boundaries.py`) and becomes a mutation **only** if a validator
accepts a bounded proposal inside the repository write path. The router's
internal lease/contract/secret/known-options checks (`_require_lease:1456`,
`_require_contract:1470`, `_require_non_secret_options:1491`,
`_require_known_options:1517`) are **plane-local refusals**, not spine
authorities — the spine re-checks everything that matters inside the write
transaction.

**Call sequence:**

1. Task handler (or R4 `_model_phase:513`, see BIND-3) → `ModelRouter.invoke`
   (`router.py:1398`) with closed schema (model/profile id,
   envelope-wrapped context, explicit output contract, lease-generation tag;
   no free-form kwargs).
2. Router: `_require_lease` → `_require_contract` → `_require_non_secret_options`
   → `_require_known_options` → `_candidates:1533` → `_build_call:1650` →
   `_run_chain:1687` → `_attempt:1757` → `_shape_result:1798` →
   `ModelProposal` (bounded ≤4 KiB or `ModelArtifactOverflow:532`) or
   `ModelRefusal` (`as_dict:584`).
3. Replay path where applicable: `replay_bytes:1434` over `RecordedTransport`
   (`replay.py:293`); replay mode refuses live contact
   (`ReplayUnavailableError` hierarchy unchanged).
4. Consumer wraps output as untrusted envelope → drafts an intent within the
   caller's allowlist (`llm_proposable:124`) with rationale.
5. `apply_intent:4038` → same gate chain as BIND-1 step 5 → rows+edges+journal
   COMMIT or refusal-as-data.

**Transaction / lease attribution per step:**

| Step | Actor | Transaction owner | Lease role |
|---|---|---|---|
| 1–2 router invoke + chain | R2 plane | none (accounting `_publish:1176` / fixture store are plane-local test/record artifacts, never the journal) | tag check only (`_require_lease`); no custody |
| 3 replay | R2 plane / `RecordedTransport` | none | same tag-only |
| 4 proposal wrap | Caller (handler or R4 phase) | none (proposal has no identity) | generation propagated |
| 5 `apply_intent` write | Gateway + repository | existing owner only; no new owner | lease-held where the surface requires; `LOCK`/`lock_lost` unchanged |

**Refusal code per failure:**

| Failure | Code | Emitted by |
|---|---|---|
| model output presented as decision (missing/unbound `HumanDecisionReceived`) | `PROPOSAL` | gateway HumanDecision dereference |
| model proposes kind outside `llm_proposable:124` | `ROLE` | role gate |
| oversized / absent rationale | `RATIONALE` | rationale bound then `event_validation` |
| invoked without held lease | `LOCK` | router tag check, then controller fence |
| schema / unknown-key violation | `MALFORMED_PAYLOAD` | `_require_contract` / gateway schema |
| replay mismatch / unavailable fixture | existing replay/provider error (`ReplayUnavailableError`), unchanged | `RecordedModelProvider._fixture_for:1128`, `_verify_response:1147` |

**R5 `allowed_consumers` delta for BIND-2:** **∅.**
BIND-2 does not import `hermes.governance`.

**No-impact ledger for BIND-2:** same as BIND-1, plus:

- Determinism: no impact — model plane is explicit "proposals/bytes only";
  `research/evaluation.py` stays deterministic-libraries-only with no write
  path; no model output decides a transition.
- Content-hash identity: no impact — model bytes are not identity-bearing;
  retained interactions (if any) get `fx_`-class identity recomputed at
  `persistence/provider_interactions.py`, never authored.
- Replay determinism: no impact — byte-identical replay only; never validity,
  never admissibility of retracted sources (N9).
- Import direction: no impact — model-plane code imports `hermes.tools.*` +
  stdlib only; never `research`/`core`/`persistence`; providers never see
  research state (§3.5).

---

## BIND-3 — Runtime delegation binding (R4 → spine, B-2 discipline)

**Question:** how does an agent run/delegation produce only proposals with
B-2 discipline?

**Answer:** `AgentRuntime` runs profiles (`planner`/`researcher`/`verifier`/
`synthesizer`/`experimenter`/`critic`) whose contract is "intent proposals
only" (`AgentProfile`, `core/node.py:32`). Delegation records are **derived
working state**, not a record of record: no private lock, no restart
re-dispatch/second scheduler, lease-generation attribution on every record,
payload ≤4 KiB or artifact-ref overflow, and the durable write still routes
through `apply_intent` (`repositories.py:92` the only journal writer,
`ARCHITECTURE_DELTA.md` §3.2.3). The runtime imports ports + core types only
— never `persistence`, never a repository, never SQL.

**Store implementations the wiring injects (binding, not a choice):**
production constructs the runtime with **`InMemoryDelegationStore` and
`InMemoryCheckpointStore` only** — the same defaults the module already
installs (`run.py:286–287`, `:293–295`), made explicit and pinned by the W2
shim and a wiring negative (§7). `FileCheckpointStore:130` and
`FileDelegationStore:123` are **test-harness-only**: they exist so
"kill the process mid-run and resume" is a testable property
(`checkpoint.py:13–20`), and they cannot appear in production wiring because
each `put` writes a durable per-run/per-delegation document outside any
`BEGIN IMMEDIATE`, outside the journal, and outside project scoping —
exactly the §3.2.3(e) durable-derived-record prohibition (their
single-writer precondition, `checkpoint.py:22–35`, is a test-harness
concern). A shim constructed with a file store fails the wiring test.

**Call sequence:**

1. Task handler → `AgentRuntime.run(profile, task_context)` (`run.py:326` /
   `:1469`) with bounded context (artifact-only where profile requires,
   e.g. adversary), untrusted envelopes, explicit budget/limits,
   lease-generation tag. Guards: `_validate_inputs:1130`, `_max_ticks:1146`,
   `_max_proposals:1149`.
2. Per tick: `_tick:441` → `_model_phase:513` (via `ModelPort:180`) →
   `_emit_drafts:585` → `_validate_drafts:628` (allowlist + schema) →
   `_derive_payload:736` → `_emit_intent:770` (Intent + rationale, ≤4 KiB) →
   `_apply:802` via injected `IntentApplier:194` (in production wiring, this
   is `apply_intent`; in planes-as-built tests it is a stub — the binding
   fixes the production injection without changing the runtime module).
3. Tool sub-phase where the draft calls for observation: `_tool_phase:822` →
   `_one_tool_call:863` via `CapabilityPort:187` (BIND-1's invoker behind the
   port; same refusals).
4. Delegation sub-phase where the draft calls for subagent work:
   `_delegation_phase:939` → `_delegate_one:961` → `delegate.py` store
   (`DelegationStore:90`) — **the wiring injects `InMemoryDelegationStore`
   and never a file store** — with B-2 constraints; checkpoint via
   `_write_checkpoint:1170` (`checkpoint.py`) — **`InMemoryCheckpointStore`
   only**; supervision via `supervisor.py`; derived projection via
   `projection.py` (B-5 purity: no `conn`, no `execute`, no writer/journal
   imports).
5. Each emitted intent → `apply_intent:4038` → gate chain → repository tx →
   journal → COMMIT or refusal-as-data. `resume:1232` / `recover:1394` are
   explicit, **within-process** operations over the in-memory store; they
   re-drive from checkpoints without re-dispatching completed work as new
   authority, and the wiring never depends on them for crash recovery (next
   paragraph).

**Crash recovery is journal re-drive, not checkpoint resume (named
sequence):** a mid-tick crash takes the in-memory checkpoints, delegations
and trace with it; nothing plane-local survives. Recovery is the controller's
existing durable path only, in this order:
`Controller.tick:934` → `_recovery_pass:2908` (stale `RUNNING` → `NO_SIGNAL`,
`:2942`; second conclusive miss → `FAILED` while ACTIVE, `:2951`) →
`_requeue_recovered:2970` (`FAILED → RETRYING → RUNNING`, bounded by
`max_retries`) → `_run_handler:3063` re-executes the handler.
- **Which journal rows drive it:** the durable `tasks` status/heartbeat/
  attempt rows (the ladder above) plus the admission rows and `events` rows
  already committed by `apply_intent`'s repository transaction
  (`_append_event_to_db`, `repositories.py:97`); no plane-local file or
  checkpoint is read.
- **What a mid-tick crash replays:** the crashed tick's uncommitted work is
  discarded (drafts, unapplied proposals, the in-memory checkpoint). On
  re-execution the runtime re-derives the same `run_id`
  (`TaskContext.resolved_run_id:270` → `run_id_of:184`) and the same
  idempotency keys (`_derive_payload:736–768`,
  `child_idempotency_key_of:202`), so intents the crashed attempt already
  committed answer `DUPLICATE` and only never-committed intents admit —
  replay is idempotent by rule, never a second row (A2-03: one-shot keyed on
  `producing_task_id`).

**Transaction / lease attribution per step:**

| Step | Actor | Transaction owner | Lease role |
|---|---|---|---|
| 1 run entry + guards | R4 plane | none | tag required; run outside lease refuses `LOCK`; mid-run loss aborts to `lock_lost` with rollback |
| 2 model phase + draft validate + emit | R4 plane | none (drafts have no identity) | tag propagated into every draft/proposal |
| 3 tool sub-phase | R4 via CapabilityPort | none (see BIND-1) | tag-only |
| 4 delegation/checkpoint/supervision/projection | R4 plane | **none** — delegation/checkpoint records are derived working state held in `InMemoryDelegationStore`/`InMemoryCheckpointStore` (the only stores the wiring injects); a durable write does not exist on this path | every derived record carries lease-generation attribution (B-4; never a settable ambient id); file stores' single-writer precondition is test-harness-only |
| 5 per-intent apply | Gateway + repository | existing owner only | lease-held where required |

**Refusal code per failure:**

| Failure | Code | Emitted by |
|---|---|---|
| profile proposes outside its allowlist / acts as authority | `ROLE` | `_validate_drafts:628` then gateway role gate |
| verdict-shaped output without bound `HumanDecisionReceived` | `PROPOSAL` | gateway |
| run outside lease / mid-run lease loss | `LOCK` | runtime guard then `lock_lost` abort |
| missing / oversized rationale | `RATIONALE` | `_emit_intent` bound then `event_validation` |
| acting on superseded chain heads | `STALE` | validator |
| delegation shape violates B-2 (private lock / re-dispatch / oversize without artifact ref / missing generation) | construction-time refusal in wiring tests (existing codes `ROLE`/`MALFORMED_PAYLOAD`/`RATIONALE` as applicable; **no new code**) | wiring fixture (see §7) |

**Refusal codes at the R4 seam (stated once; see BIND-4):** `_apply:802–814`
currently coerces any spine code outside `_PLANE_REFUSAL_CODES:175–176`
(`{PROPOSAL, ROLE, MALFORMED_PAYLOAD, STALE, LOCK, RATIONALE}`) to
`PROPOSAL`, keeping the original only parenthetically in `detail` — so a
spine `OPERATOR` would surface as `PROPOSAL`. W4's one-hunk fix extends the
set at `:175–176` with **exactly one member, `OPERATOR`**, so a spine
`OPERATOR` reaches the caller **verbatim**. That single addition is the whole
delta: at the shared constant's three call sites — `:808` (`_apply`), `:909`
(capability-refusal mapping), `:1464` (`_code_of`) — every other code is
coerced exactly as today (`:808`/`:1464` → `PROPOSAL`, `:909` →
`MALFORMED_PAYLOAD`), `_apply`'s logic is not edited, and no code is created.
The `types.py:363` invariant (`RuntimeRefusal.code` is always a member of
`RUNTIME_REFUSAL_CODES`, `types.py:62–68`) is otherwise unchanged: W4
declares no `types.py` file and no `RUNTIME_REFUSAL_CODES` delta, so the
runtime's own closed vocabulary stays exactly as pinned. The rejected
alternative — extending the set to the complete frozen vocabulary
(`gateway.py:105–120` plus `LOCK`/`RATIONALE`, 18 codes) — is a **future
R4-contract gate** requiring `types.py` + `tests/test_agent_runtime.py`
deltas (it flips the coercions the three existing R4 tests pin); it is **not
this design**. Pinned by the BIND-4 fixture in §7.

**R5 `allowed_consumers` delta for BIND-3:** **∅.**
BIND-3 does not import `hermes.governance`. (A stage that needs a governance
preflight goes through BIND-4's consult site, not through the runtime.)

**No-impact ledger for BIND-3:** same as BIND-1, plus:

- B-2 stated-delta honored: no impact — the source's counter-example shapes
  (private `_DB_LOCK`, `owner_pid`/`_recovered_results` re-dispatch,
  `task_transcripts` >4 KiB) are each refused by a named constraint above.
- B-4 attribution: no impact — generation from the lease, never
  `set_execution_uuid`-style settable ambient.
- B-5 purity (projection): no impact — mechanical purity test required
  (no `conn`/`execute`/writer imports); projection is recomputed, never a
  second durable log.
- Human-authority boundary: no impact — `internal_only:144` kinds stay
  unreachable to profiles; `IntentApplier` cannot bypass the gateway.
- Store injection (production): no impact — `InMemory*` only, pinned by the
  W2 shim and a §7 negative; `File*` stores are test-harness-only because
  their `put` is a durable derived-document write outside `apply_intent`,
  the journal and project scoping (§3.2.3(e)).
- Crash recovery: no impact — the named journal re-drive uses the existing
  `tasks` ladder and committed admissions; no plane file participates, no
  second log, no second scheduler.

---

## BIND-4 — Governance consult binding (R5 → spine, read-only)

**Question:** how does the spine consult governance without giving it a write
or an authority?

**Answer:** it doesn't "wire the plane as an enforcer". The spine calls the
**pure evaluators** (`evaluate_authority`, `resolve`, `evaluate_approval`)
as read-only preflights over already-recorded rows, inside existing
transactions or before them, and every denial still flows through the existing
gateway/controller refusal vocabulary. The plane gains **no writer, no lease
custody, no transaction, no new refusal meaning**. This is a Governance change
only in the narrow sense of *adding named readers* (allowlist deltas below);
any change to policy content, refusal meanings, or partitions remains a design
gate plus owning-slice re-run (`ARCHITECTURE_DELTA.md` §2.5 change rule).

**Call sequence (two consult sites, either/both as gated; neither bypasses
the gateway):**

- Site A (admission preflight, inside gateway validators): validator →
  `resolve(action)` (`policy.py:646`) for the governed-action mapping and/or
  `evaluate_authority(ActionRequest, EvidenceContext)` (`authority.py:552`)
  over caller-supplied snapshots of recorded rows → verdict
  (`ALLOWED` / `REFUSED` with requirement + `GovernanceRefusal`) →
  the validator surfaces the refusal code **natively, verbatim** (rule below)
  and either continues the existing chain or returns refusal-as-data.
- Site B (controller verdict-surface preflight): `resolve_human_gate:1764`
  (and siblings `record_failure_classification`, `record_contradiction_\
  resolution`, `record_source_retraction_decision` per `docs/API.md`) →
  `evaluate_approval` over `DecisionRow` snapshots + `evaluate_authority`
  over credential/evidence snapshots → the same verbatim surfacing.
- **One rule, stated once — always native.** Governance's refusal vocabulary
  is a mirror of the spine's frozen set by construction (`policy.py:130–145`:
  `GATEWAY_DEFINED_CODES` ⊂ `gateway.py:105–120`, `CONTROLLER_EMITTED_CODES =
  {RATIONALE}`), and both `_refuse` (`authority.py:490–492`) and
  `GovernanceRefusal.from_mapping` (`policy.py:364–367`) refuse any
  non-member. A governance code is therefore already the code the spine would
  emit, so **no wiring site translates, remaps or wraps it**: Site A, Site B
  and the methodology path (`_governance_outcome:498–506`, which returns
  `refusal.code` unchanged — kept as-is, no edit to `workflows.py`) all emit
  the same string for the same denial. The only code a wired site itself adds
  is the plane's own shape refusal `MALFORMED_PAYLOAD` — never a new code.
- In both sites the evaluators are **total** (never raise for shape;
  malformed input answers `MALFORMED_PAYLOAD` as data) and **pure**
  (no clock, no store, no I/O, no model; same rows in any order → same
  verdict + same `digest()`).

**Transaction / lease attribution per step:**

| Step | Actor | Transaction owner | Lease role |
|---|---|---|---|
| snapshot recorded rows (credentials, decisions, evidence) | Spine (gateway validator / controller surface) | the **existing** surrounding transaction if already inside one (re-derivation pre-`BEGIN` per Model-D pattern where applicable); otherwise a read (advisory) | reads carry the current generation for attribution; no new lock |
| pure evaluate (`evaluate_authority` / `resolve` / `evaluate_approval`) | R5 plane | **none** — evaluators open no transaction, hold no connection | none (deterministic function of snapshots) |
| surface verdict code (native) → continue or refuse | Spine | the existing owner continues (repository `BEGIN IMMEDIATE` / gateway decision append / controller lease-held write) | unchanged fence |

**Refusal table (the complete consult/evaluation outcome set; every row is
one frozen code surfaced natively — see the rule above):**

| Consult / evaluation outcome | Code (native, verbatim) | Where the code is produced |
|---|---|---|
| request/context shape the evaluator cannot read | `MALFORMED_PAYLOAD` | `authority.py:519–522`, `:660–673` |
| action governed by no row (deny by default) | `ROLE` | `authority.py:677–682` |
| policy row effect `DENY` | `row.refusal_code` (shipped rows: `ROLE`, `policy.py:678–680`) | `authority.py:686–695` |
| required operator identity absent | `row.refusal_code` (`ROLE`) | `authority.py:701–708` |
| credential missing / not ratified for the actor | `row.credential_refusal_code` or `OPERATOR` (shipped rows declare `OPERATOR`, `policy.py:690`, `:704`) | `authority.py:710–723` |
| approval lifecycle not `APPROVED` (`MISSING`/`PENDING`/`DENIED`/`EXPIRED`) | `PROPOSAL` (state→code map, `approvals.py:130–135`) | `authority.py:782–792` |
| unreadable decision/approval row, or unapproved state without a refusal | `MALFORMED_PAYLOAD` | `authority.py:784–787` |
| decider is the requester (independence) | `ROLE` | `authority.py:804–812` |
| recorded decision binds no `command_hash` | `row.binding_refusal_code` or `STALE` (shipped rows: `PROPOSAL`, `policy.py:692`, `:706`) | `authority.py:814–824` |
| recorded decision binds a different chain head | `row.head_refusal_code` or `STALE` (shipped rows: `STALE`, `policy.py:707`) | `authority.py:826–838` |
| `RESTRICTED` target not bound | `row.binding_refusal_code` or `STALE` (shipped rows: `PROPOSAL`) | `authority.py:840–850` |
| required record but no rationale | `row.record_refusal_code` or `ROLE` (shipped: `PROPOSAL` REVIEWER/HUMAN, `RATIONALE` AGENT+RECORD; `policy.py:691`, `:705`, `:726`) | `authority.py:852–860` |
| substituted policy document at the public `resolve` | `MALFORMED_PAYLOAD` + `POLICY_SUBSTITUTION_DETAIL` | `policy.py:646–672` |
| allowed verdict | — (proceed; no refusal code) | `authority.py` ALLOWED branch |

Every code above is a member of `GOVERNANCE_REFUSAL_CODES`
(`policy.py:144–145`) — i.e. already frozen spine vocabulary. `OPERATOR` is
never coerced to `PROPOSAL`: the W4 `_PLANE_REFUSAL_CODES` hunk (BIND-3 note)
makes the R4 seam pass it through **verbatim**.

**R5 `allowed_consumers` delta for BIND-4:** the **only** binding that grows
the set, and only with the consult shim(s) created in W4:

- Baseline: `{methodology/workflows.py, eval/hostile.py, eval/import_gate.py}`.
- BIND-4 gain: **at most two** spine-adjacent readers, named exactly when W4
  lands (intended: one gateway-side consult module + one controller-side
  consult call-site file, e.g. `research/gateway_governance_consult.py` and
  the existing `research/controller.py` + `research/gateway.py` entries —
  final names fixed in W4; the test asserts exact membership, and
  `test_every_declared_consumer_is_actually_a_consumer` fails if an entry
  goes stale).
- BIND-1/2/3/5 gain: ∅ (stated per binding so a reviewer can check the sum).

The gate still protects what it always did: **no plane file reaches the
spine's write path**, and the consumer set is an explicit reviewable list
rather than something discovered by grep. The eval plane's two entries stay
as the declared second consumer (R7-FIX2); the methodology driver stays as
the first (R6).

**No-impact ledger for BIND-4:**

- Sole-write-path: no impact — consults are reads; mutations still only via
  `apply_intent`.
- Append-only journal: no impact — evaluators cannot append; writer unchanged.
- Lease fence: no impact — no custody; fence logic untouched.
- Content-hash identity: no impact — evaluators derive no IDs; digests are
  content digests of verdict mappings, never row identities.
- Human-authority boundary: no impact — the boundary is **consulted**, not
  moved; `internal_only` reachability unchanged; model verdicts still refused
  (B-1 provenance rule: verdict must bind a recorded `HumanDecisionReceived`
  row; stamping `decided_by='op-1'` fails too).
- Project isolation: no impact — contexts are project-scoped snapshots.
- 4 KiB cap: no impact — requests/contexts bounded; overflow via artifact ref.
- N1/N9: no impact — predicates not fed by evaluators.
- Determinism: no impact — evaluators are pure/deterministic; no model in path.
- Minimal-core / import bans: no impact — consult direction is
  spine-owns-call into a pure module; no `persistence`→`research` addition,
  no tools→research addition, no substrate, no new core dep.
- Governance change rule: **acknowledged, not impacted** — policy content,
  refusal meanings, and partitions are untouched; adding readers is the
  wired-test allowlist mechanism the R5 suite already governs.

---

## BIND-5 — Methodology orchestration binding (R6 → spine via R4+R3+R2)

**Question:** how does a methodology run orchestrate R4+R3+R2 and record only
through existing boundaries?

**Answer:** `run_methodology` is a **driver over already-bound planes**,
not a new writer. It parses a versioned methodology document (fail-closed),
runs each stage on the R4 runtime (which itself uses BIND-2/BIND-1 behind
ports), performs the per-stage governance preflight (BIND-4 consult, already
the one declared consumer `methodology/workflows.py`), and records substrate
nodes/edges as **derived working state in the run's own in-memory
`SubstrateStore`** (`substrate.py:522`) — never as intents and never as
journal rows. Corrected against the tree: there is **no substrate table**
(`migrations.py` creates no `substrate_*`/`mnode_` table), **no substrate
intent kind**, and **no gateway validator** among the 15
(`gateway.py:289–3959`) that takes a `SubstrateNode` or imports
`node_id_of`; `write_node:1092–1140` mutates the in-memory store
(`store.nodes[node_id] = node:1139`). Durability of substrate rows is
therefore an explicit **§8 gate (item 9)**, not a claim this binding may
make: until that gate passes, a wired methodology run may claim its stage
execution, stage outcomes/digests, and the durable admissions its proposals
made through `apply_intent` — it may **not** claim durable substrate
research state, a durable chain, or any `mnode_`/`medge_` ref readable after
the process ends. Substrate identity (`node_id_of:295`, `edge_id_of:307`,
`node_contradiction_id_of:319`) is recomputed by rule at the plane's own
write boundary (`write_node:1112`), never authored; `parse_methodology`
refuses unknown stages/keys as data.

**Call sequence:**

1. Spine or operator driver → `parse_methodology(data)` (`workflows.py:244`)
   → `MethodologyConfig` (stages → profiles, toolset, termination, governance
   actions) or `MethodologyRefusal` (`MALFORMED_PAYLOAD`).
2. `run_methodology(config, inputs)` (`:509`) → per stage:
   `_governance_outcome(stage, inputs)` (`:487`, the declared
   `evaluate_authority` consumer) → R4 `run(profile, task_context)` (BIND-3)
   → stage `StageOutcome` / `MethodologyRun` (`:426`) with `digest:441`.
3. Substrate recording (derived working state — no write path): the stage's
   node is recorded into the run's in-memory store via
   `write_node(store, node)` (`workflows.py:599–602`,
   `substrate.py:1092`): shape/kind/ref/provenance/support checks, the
   `mnode_` id recomputed at `:1112` → `node_id_of:295`, returned as the id
   or refusal-as-data. No `apply_intent`, no repository, no `BEGIN`, no
   journal row — nothing about a node/edge becomes durable. The stage's
   ordinary proposals (R4 drafts) still route through `apply_intent` per
   BIND-3; those are the run's durable footprint. `chain_inputs` /
   `swap_test.py` `run_swap_probe` prove a second document runs on the same
   runtime instances without a second scheduler.
4. Reconstruction is derived: `MethodologyRun.reconstruction:437` →
   `ChainReconstruction` (pure recomputation, B-5 discipline).

**Transaction / lease attribution per step:**

| Step | Actor | Transaction owner | Lease role |
|---|---|---|---|
| 1 parse | R6 plane | none (config is a value object; `methodology_identity:628` is a digest, not a row id) | none |
| 2 per-stage preflight + R4 run | R6 driver → BIND-4 consult (read) → BIND-3 run → BIND-2/BIND-1 behind ports | none new (each inner plane step per its binding) | generation tag threaded through every stage; no private lock; no re-dispatch |
| 3 substrate recording | R6 plane | **none** — nodes/edges are derived working state in the run's in-memory `SubstrateStore`; no durable substrate record exists to own | none — run-local derived state (nothing journal-attributed to hold) |
| 4 reconstruction | R6 plane | none (derived view) | none |

**Refusal code per failure:**

| Failure | Code | Emitted by |
|---|---|---|
| workflow missing required key / unknown stage | `MALFORMED_PAYLOAD` | `parse_methodology` then gateway schema |
| stage governance preflight denies | the governance code **verbatim** — always-native rule in BIND-4 (e.g. `OPERATOR` stays `OPERATOR`) | `_governance_outcome:498–506`; R4 seam preserves it per the BIND-3 note |
| inner model/capability/runtime refusal | that binding's code (see BIND-1–3) | inner plane + gateway |
| node shape/kind/ref/provenance/support refusal (derived state) | the plane's closed set `SUBSTRATE_REFUSAL_CODES` (`substrate.py:203–217`) surfaced as `MethodologyRefusal(code=…)` — four repo codes (`MALFORMED_PAYLOAD`, `RATIONALE`, `PROVENANCE`, `EVIDENCE_DOES_NOT_RESOLVE`) plus the plane-local `UNSUPPORTED_CLAIM`/`PREMATURE_CONCLUSION`/`CIRCULAR_REASONING`/`RETRACTED_CITATION` | `write_node` as data (`workflows.py:600–602`); these never enter the journal vocabulary because no substrate row is admitted |
| oversize stage payload | `RATIONALE` (or artifact-ref overflow) | bound then `event_validation` |

**R5 `allowed_consumers` delta for BIND-5:** **∅ beyond baseline.**
`methodology/workflows.py` is **already** the declared first consumer; BIND-5
adds no new importer — it exercises the existing preflight path. (If W-slices
split the driver, the split files must either not import governance or each be
added as an explicit allowlist delta in W4 — no silent additions.)

**No-impact ledger for BIND-5:** same as BIND-1, plus:

- No second scheduler: no impact — `run_methodology` drives the **existing**
  R4 runtime instances; `swap_test` proves one runtime serves two documents.
- No new tables/kinds/events: **acknowledged, gated — not "no impact."**
  Substrate nodes/edges are derived working state in the run's in-memory
  store; they use no boundary because none exists (no table, no kind, no
  validator — the Answer above). Durability of substrate rows is §8 item 9;
  until it passes, the run can claim only the durable admissions its
  proposals made through `apply_intent`, never durable substrate state (the
  Answer states the full can/cannot list).
- B-6 (scoped memory): no impact — still BLOCKED; methodology recall (if any)
  is advisory only, per-project partitioned when ever unblocked, never a gate
  input granting authority.
- Methodology-as-config: no impact — documents are data; the driver is
  deterministic; same config + same inputs → same digests.

---

## 6. Slice plan (W1–W4 order, file sets per slice, disjointness argument)

**Ordering principle:** additive planes first, single wiring last — the same
pattern that built R2–R7 as new-files-only deliberately-unwired planes.
W1–W3 create **new files only** (no existing-file edits, so the unwired gates
stay green). W4 is the **only** slice that edits existing spine/test files
(the wiring commit). Review order is W1 → W2 → W3 → W4; no slice lands unless
the full suite is green (docs-only rule: full suite proves no behavior change
until W4, which then proves the intended behavior change with new fixtures).
W4 additionally re-runs the certified slice owning each touched surface
(the ordered list after the table below) — full-suite green alone is not
sufficient for W4.

| Slice | Binds | File set (exact; no other files touched) | Existing-file edits? |
|---|---|---|---|
| **W1** — Capability execution shim | BIND-1 | NEW `src/hermes/research/task_handlers/__init__.py` (creates the package: docstring + import discipline per §3.1; **owned by W1 only — W2/W3 add modules and never touch it**); NEW `src/hermes/research/task_handlers/capability_handler.py` (thin handler: template → `CapabilityInvoker.invoke` → observation → ordinary intent proposal; imports ports + core types only); NEW `tests/test_wiring_capability.py` (fixtures per §7) | **none** |
| **W2** — Model + Runtime proposal shims | BIND-2 + BIND-3 | NEW `src/hermes/research/task_handlers/model_proposal.py` (closed-schema `ModelRouter.invoke` wrapper → proposal; no ID); NEW `src/hermes/research/task_handlers/runtime_proposals.py` (R4 `run`/`delegate` driver with B-2 guards, constructs the runtime with `InMemoryCheckpointStore`/`InMemoryDelegationStore` **only**, + `IntentApplier=apply_intent` injection point documented, not yet connected); NEW `tests/test_wiring_model_runtime.py` | **none** |
| **W3** — Methodology driver shim | BIND-5 | NEW `src/hermes/research/task_handlers/methodology_driver.py` (`parse_methodology` → per-stage BIND-4 preflight shape → R4 run → ordinary-intent proposals; substrate nodes/edges recorded as derived working state via `write_node`, never proposed as intents — §8 item 9 is the durability gate; reconstruction as derived view); NEW `tests/test_wiring_methodology.py` | **none** |
| **W4** — Spine wiring + governance consult | BIND-4 (+ connects W1–W3) | NEW `src/hermes/research/governance_consult.py` (the at-most-two Site-A/Site-B pure-consult functions); EDIT `src/hermes/research/controller.py` (registration of W1–W3 templates in `_task_handlers` + Site-B preflight call, one hunk); EDIT `src/hermes/research/gateway.py` (Site-A preflight call inside existing validators, surfacing the native code, one hunk); EDIT `src/hermes/agents/runtime/run.py` (one hunk: `_PLANE_REFUSAL_CODES:175–176` extended with exactly one member, `OPERATOR`, so `_apply:802–814` preserves a spine `OPERATOR` verbatim; the `:909`/`:1464` shared-constant behaviors and the `types.py:363` invariant are otherwise unchanged — no new code, no other behavior change; the full-vocabulary pass-through is a future R4-contract gate, not this design); EDIT `tests/test_governance_plane.py` (allowlist deltas for BIND-4 only, plus staleness pin); NEW `tests/test_wiring_governance.py` | **yes — only here** |

**W4 certification re-runs (ordered; each is red-stops-the-change,
`AGENTS.md:98–101`).** W4 touches tick dispatch (`controller.py:3048`/`:3073`),
lease-held verdict surfaces (`:1764`), the validated gateway surfaces
(`gateway.py`), and the R4 runtime's refusal seam (`run.py:175–176`). On the
final W4 tree, after the full suite is green, re-run the owning certified
slices in this order:
1. **P6 — production classification writer** (`ff79bb6`; guard
   `tests/test_p6_classification.py`).
2. **N9 — retraction-aware evidence admission** (`02cb976`; guard
   `tests/test_n9_retraction_admission.py`).
3. **P7 — contradiction/governance lifecycle** (guard
   `tests/test_chg1_contradictions.py`).
4. **Post-P6 tick-loop detector wiring** (`633cff1`+`2328399`; guards
   `tests/test_p_auto_6_loop.py`, `tests/test_failure_injection.py`).
5. **R5 governance independence** — the allowlist-exactness pair
   (`tests/test_governance_plane.py`).
6. **R4 runtime** — `tests/test_agent_runtime.py` for the `run.py` hunk.

**Green means:** that slice's named guard suite passes with 0 failures,
0 errors and no new skips on the W4 tree (collection == pass count where the
holding certification defines it), and the closing CONTROL set —
`scripts/run_tests.py` full suite, `ruff check src tests`, `pyright src` +
the tests project — is green at the same commit. A red gate stops the change;
the P6 → N9 → P7 → tick-loop order follows the certification lineage (N9
lifted P7; the tick-loop detector sits post-P6).

**Disjointness argument (checkable with `git diff --stat` per slice):**

- `task_handlers/` ownership: W1 creates the package (`__init__.py`,
  docstring, import discipline per §3.1) and is its only owner; W2/W3 add
  modules under it and never create or edit `__init__.py`; the order
  W1 → W2 → W3 guarantees the package exists before its first dependent.
- W1 ∩ W2 = ∅: distinct new paths (`capability_handler.py` + the
  `task_handlers/__init__.py` W1 owns vs `model_proposal.py` +
  `runtime_proposals.py` + `test_wiring_model_runtime.py`); W2 adds no
  `__init__.py` edit and does not exist before W1 lands.
- W1 ∩ W3 = ∅, W2 ∩ W3 = ∅: same — distinct new paths.
- W4 ∩ (W1 ∪ W2 ∪ W3) = ∅ on edits: W1–W3 touch **zero** existing files, so
  no existing-file hunk can collide with W4's four edited files; W4's one new
  file (`governance_consult.py`) and one new test (`test_wiring_governance.py`)
  are names reserved here and forbidden to W1–W3.
- Within W4, the four edited files are disjoint hunks by construction
  (registration hunk vs validator-call hunk vs `run.py` refusal-set hunk vs
  allowlist hunk); a reviewer
  verifies with `git diff --stat` that each slice shows exactly its table's
  files and nothing else.
- Import-disjointness: only W4's `governance_consult.py` (plus the two
  edited spine files' consult call sites) may name `hermes.governance`;
  W1–W3 must pass the unwired grep for their paths (their tests assert it).

If a slice needs a file outside its table, it stops and re-gates — the table
is the contract, not a suggestion.

---

## 7. Test strategy per binding (which existing suite guards it, which new fixtures prove it)

General rule: existing suites guard **no-regression** (they stay green through
W1–W3 and pin the new behavior in W4); new wiring fixtures prove **the
binding** (one negative per refusal path, one positive round-trip per happy
path). Canonical commands per `AGENTS.md`: full suite via
`scripts/run_tests.py`, `ruff check src tests`, `pyright src` (+ tests config).

**BIND-1 (Capability):**

- Existing guards: `tests/test_capability_plane.py` (registry/invoke/envelope
  matrix, mutating-tool `ROLE`, schema/secret/hazard/rate gates);
  controller tick/dispatch suites; gateway validator suites;
  `test_provider_orchestration`-family golden fixtures (handler-result
  discipline precedent).
- New fixtures (`tests/test_wiring_capability.py`): handler factory handed a
  raw `conn` fails the wiring test (never runs — SD2-03 precedent);
  unhandled template returns `unhandled` fail-closed (`:5173`); observation →
  ordinary-intent round-trip admits one row; re-emit is idempotent
  (`IDEMPOTENCY_CONFLICT` or duplicate-same-row per boundary); oversize
  observation takes artifact-ref overflow, else `RATIONALE`; cross-project
  observation refuses (`EVIDENCE_REF` / `PROJECT_NOT_FOUND`).

**BIND-2 (Model):**

- Existing guards: `tests/test_model_plane.py` (router/policy/accounting/
  replay/refusal matrix); `RecordedTransport` replay suites (byte-identical,
  refusing inner transport).
- New fixtures (`tests/test_wiring_model_runtime.py`, model half): closed-schema
  violation refuses `MALFORMED_PAYLOAD` (unknown key); lease-less invoke
  refuses `LOCK`; decision-shaped output without bound `HumanDecisionReceived`
  refuses `PROPOSAL` at the gateway (not merely at the router); oversize
  proposal takes `ModelArtifactOverflow` path or refuses `RATIONALE`; replay
  bytes equal record bytes fixture-for-fixture.

**BIND-3 (Runtime):**

- Existing guards: `tests/test_agent_runtime.py` (run/delegate/checkpoint/
  supervisor/projection matrix, allowlist refusals, `TestRealSpineIntegration`
  precedent: admitted task lands, re-emit is `DUPLICATE`, unwired kind surfaces
  `NOT_WIRED` as data).
- New fixtures (runtime half): profile proposing outside allowlist refuses
  `ROLE` at `_validate_drafts` and at the gateway; `internal_only` kind from
  any profile refuses `ROLE`; mid-run lease loss aborts to `lock_lost` with
  rollback (no partial rows); delegation store with a private lock /
  re-dispatch shape fails construction (B-2 negative); oversize draft takes
  artifact ref; `resume`/`recover` never double-admit.
- File-store negative: constructing the W2 shim with `FileCheckpointStore` /
  `FileDelegationStore` fails the wiring test (test-harness-only stores);
  crash-recovery fixture: kill mid-tick, restart, and the journal re-drive
  (task status ladder + committed admissions) re-executes and admits only
  never-committed intents — committed ones answer `DUPLICATE`, with no second
  row and no plane file consulted.

**BIND-4 (Governance consult):**

- Existing guards: `tests/test_governance_plane.py` (144+ tests: matrix-as-data,
  49-scenario coverage, `evaluate_authority` totality/purity/determinism,
  `test_the_plane_is_wired_to_nothing`, `test_every_declared_consumer_is_\
  actually_a_consumer`, `test_the_package_exports_nothing_eagerly`);
  gateway `OPERATOR`/`PROPOSAL` suites; controller human-gate suites.
- New fixtures (`tests/test_wiring_governance.py`): consult purity
  (no `conn`/`execute`/writer/journal imports — mechanical grep);
  substituted-policy call answers `MALFORMED_PAYLOAD` with
  `POLICY_SUBSTITUTION_DETAIL`; model-stamped `decided_by='op-1'` without a
  recorded `HumanDecisionReceived` row refuses `PROPOSAL`; non-operator denial
  refuses `OPERATOR`/`PROPOSAL`/`ROLE` per path (never a protocol control);
  spine `OPERATOR` (unratified credential) reaches the runtime caller as
  `OPERATOR` **verbatim** through `_apply` after the W4 `_PLANE_REFUSAL_CODES` hunk — never
  coerced to `PROPOSAL` (pins `run.py:175–176`/`:802–814`); the same fixture
  asserts the coercions unchanged — `SCOPE_NOT_GOVERNED` → `PROPOSAL`,
  `NOT_WIRED` → `PROPOSAL` through `_apply`/`_code_of`, `EVIDENCE_REF` →
  `MALFORMED_PAYLOAD` at the capability site — citing the existing R4
  tests that already pin each one (green unchanged; gate-#6 guardians):
  `TestProposalAuthority::test_the_spine_refusal_is_recorded_as_data`
  (`tests/test_agent_runtime.py:1192–1199`),
  `TestToolHandling::test_a_capability_refusal_is_recorded_with_its_provenance`
  (`:1287–1293`),
  `TestRealSpineIntegration::test_an_unwired_kind_surfaces_the_spine_refusal_as_data`
  (`:2581–2592`);
  allowlist-exactness (every declared consumer names the plane; every namer is
  declared — the two tests above extended, not weakened).

**BIND-5 (Methodology):**

- Existing guards: `tests/test_methodology_plane.py` (90 tests: substrate
  ontology/identity/edges/N9/contradiction/chain, `parse_methodology`
  fail-closed, `run_methodology` driver, `swap_test` second-document probe);
  R4 + R3 + R2 suites (inner bindings).
- New fixtures (`tests/test_wiring_methodology.py`): unknown stage/key
  refuses `MALFORMED_PAYLOAD`; second document runs on same runtime instances
  (no second scheduler — instance-identity assertion); per-stage governance
  preflight denial surfaces the governance code verbatim (always-native rule;
  no new code); substrate node with foreign task binding / cross-project ref
  refuses as data at `write_node` (in memory — no journal effect);
  reconstruction is recomputed (mutate-then-rerun yields same digest from
  same inputs); durability negative: after a wired run the DB/journal holds
  no substrate row and no `mnode_`/`medge_` ref (the §8 item 9 gate is the
  only path that could change this).

R7 harness role: `tests/test_eval_plane.py` (matrix/ops/hostile/import-gate/
extensions suites, redaction affix rules, `unevaluable` fail-closed) guards
that no wiring introduces an evaluable-but-unresolved dynamic import or a
secret-bearing payload; the import gate owns the single crossing the eval
plane uses and reports it whatever the spelling.

---

## 8. Open gate items (explicitly NOT proposed here)

Per the forbidden clause, this design proposes **no** new authority, code,
kind, event, or table. Each need that would require one is recorded here as a
gate, not a decision:

1. **New task templates** (e.g. dedicated `MODEL_INVOKE` / `CAPABILITY_CALL` /
   `METHODOLOGY_STAGE` templates): gate — needs template-key decision + handler
   contract + `unhandled`-until-wired proof. W1–W4 reuse existing templates and
   the ordinary admission kinds only.
2. **New intent kinds**: gate — `docs/ARCHITECTURE.md` §3.11 (merely possible,
   requires design gate). None proposed; any slot needing one (per
   `ARCHITECTURE_DELTA.md` §3.2.3/§4 `:214`) stops.
3. **New events / journal rows**: gate — same §3.11. None proposed; journaling
   via task events + rows + §14 edges only.
4. **New tables / stores**: gate — delegation/checkpoint records stay
   in-process derived working state (production wiring injects `InMemory*`
   stores only; `FileCheckpointStore`/`FileDelegationStore` are
   test-harness-only — BIND-3); any genuinely-durable new record needs the
   five §3.2.3 conditions plus a table gate. None proposed.
5. **New refusal codes**: gate — frozen vocabulary only
   (`ROLE`/`OPERATOR`/`LOCK`/`PROPOSAL`/`STALE`/`RATIONALE` + refinements);
   "no new code without the specified behavior + tests" (`docs/API.md`).
   None proposed.
6. **New authorities / policy rows with new meanings**: governance design gate
   + owning certification slice re-run. None proposed; BIND-4 consults the
   canonical policy only.
7. **Recall / memory unblock (B-6)**: stays BLOCKED pending per-project store
   partition + accepted native dependency. Not proposed.
8. **Line-number drift**: `AGENTS.md` cites `gateway.py:3961` (actual `:4038`
   at this baseline) and `controller.py:486/597` (actual tick `:934` / run
   `:1076`); `ARCHITECTURE_DELTA.md` §6 lists further doc drifts. Docs-only
   correction, not this design's to edit.
9. **Durable substrate rows (BIND-5)**: gate — a substrate table (e.g.
   `substrate_nodes`/`substrate_edges`, or an artifacts-row carrier on the
   Q-05 precedent: `artifact_type` open column + `ArtifactRepository.record`,
   `repositories.py:847`, with provenance edges in `provenance_edges`) + an
   intent kind + a gateway validator that re-derives `node_id_of`/`edge_id_of`
   inside its transaction + project scoping + N9/retraction proof for cited
   refs. Until this gate passes, wired methodology runs keep nodes/edges as
   derived working state and claim no durable substrate state (BIND-5 Answer
   states the can/cannot list); no W1–W4 file may persist them.

---

## 9. Acceptance (what the hostile reviewer checks)

- Every binding traces call-by-call (§§BIND-1–5 step numbers cite file:line at
  `a8f0180`; code wins on drift).
- Every invariant maps to a no-impact statement in each binding's ledger
  (sole-write-path, journal table-scope, lease fence, content-hash identity,
  human-authority boundary, project isolation, 4 KiB cap, N1/N9 frozen,
  determinism, minimal-core/import bans, archive-not-delete/head-only,
  refusal-as-data).
- Every failure of a **durable write** maps to an existing frozen code, and
  every governance refusal is surfaced natively and verbatim (BIND-4 rule;
  `OPERATOR` never coerced to `PROPOSAL`); derived substrate refusals are the
  R6 plane's own closed set (`substrate.py:203–217`) consumed as data inside
  the run, with §8 item 9 recording the gate that would make them durable —
  no new codes proposed.
- Substrate durability is not claimed: BIND-5 states the derived-only posture
  and the can/cannot list, and §8 item 9 records the table gate; no wiring
  file persists a node/edge.
- Every binding states its R5 `allowed_consumers` delta (BIND-4 grows by at
  most two named readers in W4; BIND-1/2/3/5 gain ∅; baseline triple unchanged
  otherwise).
- Slice plan shows W1–W4 order, exact file sets, `task_handlers/` ownership,
  the disjointness argument, and the W4 certification re-runs with their green
  definition (§6); `git diff --stat` per slice matches its table.
- Test strategy names the existing guard suite and the new proving fixtures
  per binding (§7); R7 eval plane stays the harness, not a sixth binding.
- `git status --short` in this worktree shows **exactly one new file**:
  `WIRING_DESIGN.md` (this file). No existing file edited, nothing staged,
  nothing committed.
