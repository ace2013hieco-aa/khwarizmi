# HERMES STEP 6 — RECONCILE-LOOP INTEGRATION DESIGN GATE

**Status:** CLOSED — VERDICT B (targeted design/hardening required before implementation)
**Predecessor:** HERMES S5 Implementation Closure (`206b643`)
**Charter:** Design authorization requested — design gate only, NO production implementation
**Date:** 2026-08-22
**Architecture authority:** Ratified Hermes v6 contract; Step 4 S5/S7 decision gate; S5 closure report; IDR-040

---

## 1. Executive verdict

**VERDICT B — STEP 6 REQUIRES TARGETED DESIGN/HARDENING.**

The reconcile-loop architecture for `RETRACT_SOURCE` proposal ingestion is
substantially defined and the dominant substrate already exists — but one
production gap is disqualifying, and one authority decision is pre-ratified
as open and must be closed by the operator before any Step 6 code is written:

- **GAP-1 (disqualifying, production):** `HumanDecisionReceived` has **no
  production emitter**. The event exists in the ratified catalog
  (`events.py:32`) and the S5 gateway validator dereferences it fail-closed
  (`gateway.py:1066–1082`), but a repository-wide grep finds zero emitters in
  `src/` — only test fixtures emit it. Consequence: as of HEAD `206b643`,
  **no legitimate production path can ever satisfy the S5 human-decision
  precondition**. `RETRACT_SOURCE` is unreachable in production. This is not
  a Step 6 concern that can be deferred past this gate: Step 6's entire
  purpose is to build the A→D pipeline that terminates at E, and E's
  precondition has no producer.
- **OPEN-DECISION-1 (operator ratification required):** whether retraction
  proposals may originate from the Director (v6 §9.3 table + §27 items
  13/25: "human-only vs. a `DIRECTOR_REVIEW` proposal subject to human
  approval"). This gate maps both branches onto the same architecture and
  identifies where they diverge; it does NOT decide the question.

Everything else the charter asks for is either READY or NEEDS HARDENING with
a named precedent. The recommended next step is the smallest possible gate:
**Step 6a — operator-decision ingestion surface for source retraction**
(closing GAP-1), followed by ratification of OPEN-DECISION-1, after which
the reconcile-loop slice is implementable against existing substrate.

---

## 2. Repository baseline (verified live, this session)

| Item | Value |
|---|---|
| HEAD | `206b643adbf4483ae81ffad33164a7aebe070629` |
| Branch | `main`, tracking origin/main, **0 ahead / 0 behind** (verified post-fetch) |
| Working tree | clean except untracked `.freebuff/` (app state, unchanged) |
| Worktrees | main @ `206b643`; `step-4` @ `45c5bb7`; two stale worktrees (`Development`, `Research-agent`) @ initial commit `854ee35` |
| Test baseline | full suite executed live this session: **1701 passed, exit 0** (`scripts/run_tests.py tests/ -q`, log `s6_baseline.log`) |

The repository matches the S5 closure record exactly. No drift to explain.

---

## 3. Current architecture map (evidence-first)

### 3.1 What "the reconcile loop" actually is today

The charter's §3 item 11 ("existing reconciliation/controller abstractions")
resolves to three distinct layers, all verified live:

| Layer | Location | State |
|---|---|---|
| Nominal module | `src/hermes/research/reconcile.py` | **Phase 0 placeholder** — 6 lines, docstring only ("Phase 0: placeholder"), zero code |
| Execution loop | `Controller.tick()` / `Controller.run()` (`controller.py:481/587`) | IMPLEMENTED — lease-fenced tick: acquire lock → recovery → mode check → requeue → discover → claim → execute → commit |
| Director advisory/action loop | IDR-040 §3 surfaces (`controller.py:880/997/1033/1391`) | IMPLEMENTED — `reconcile_digest()` (read-only composite) → `propose_review_actions()` (Director-only intents through the gateway) → `pending_classification_proposals()` replay → `record_operator_decision()` (lease-held verdict ingestion) |

The v6 text confirms the loop's posture: *"The loop never … directly mutates
state … Judgment … remains a `DIRECTOR_REVIEW` task whose *proposal* is an
intent"* (§8, line ~479); the `AuditView` freshness scan is *"proposal only,
never auto-execution"* (§14, §10.2). The architecture's answer to "who
proposes" is always: **a deterministic advisory surface proposes through the
single intent gateway; a human decides anything irreversible.**

### 3.2 The A–E chain for classification actions (the working precedent)

IDR-040 (RATIFIED/CLOSED 2026-08-15) built exactly the A–E pipeline the
charter describes, for classification-action proposals:

```text
A Observation   blast radius ∩ outstanding classifications (pure read,
                GRAPH_QUERY_VERSION-bound, content-hashed)
B Decision      ClassificationActionProposed audit event (append-only;
                PENDING_HUMAN_APPROVAL gate state RECOMPUTED from class, F2)
C Proposal      PROPOSE_CLASSIFICATION_ACTION intent (DIRECTOR role)
D Validation    apply_intent gateway: D3 dereference, permitted-action
                member, candidate existence, idempotent deterministic id
E Application   RESOLVE_CLASSIFICATION_PROPOSAL intent ingests the operator
                verdict (DETERMINISTIC, lease-held, one-verdict rule,
                contradictory refused)
```

This is the structural template Step 6 must reuse — not because it is
convenient, but because it is the *only* ratified in-repo instance of the
observe→propose→decide→apply shape, and v6 §9.3's open item explicitly
anticipates extending it to retraction.

### 3.3 The S5 mutation layer (E — complete)

Verified live at HEAD `206b643`: `_validate_retract_source`
(`gateway.py:1030+`) enforces payload shape, fail-closed
`HumanDecisionReceived` dereference, source resolution (artifact-id or
`<type>:<hash>` SD-05 form), full-command sha256 idempotency, STALE guard,
and one atomic `BEGIN IMMEDIATE` cascade (event → ResearchDecision artifact
with `supersedes` edge → dependency-class cone invalidation → terminal task
transitions). 34 focused tests + 14 adversarial probes green. **S5 owns E and
is not touched by this gate.**

### 3.4 Substrate inventory relevant to A–D

| Component | Location | Status for Step 6 |
|---|---|---|
| `SourceRetracted` seed events (observation) | `source_outcomes.py:735–764` auto-emit on HZ-02 provider marker; `controller.record_source_retraction` audit append | READY — the advisory already seeds candidate surfaces from recorded retractions (fail-closed, project-scoped) |
| Blast-radius / cone reads | `graph.py:157/240/276`; `controller.artifact_blast_radius`, `.re_review_candidates`, `.retracted_source_review_candidates` | READY — pure, versioned, content-hashed, no-write (fixture-pinned) |
| Digest composition | `controller.reconcile_digest()` v2 (`RECONCILE_DIGEST_VERSION="2"`, content-hash bound) | READY — new sections fold in with a version bump |
| Proposal-shaped intents | `PROPOSE_CLASSIFICATION_ACTION` (DIRECTOR-only, gateway-admitted, append-only audit event = the record) | READY as pattern; a retraction analog needs its own ratified kind (see §8) |
| Pending-proposal replay | `pending_classification_proposals()` → digest fold | READY pattern |
| Operator credential verification | `OperatorCredentialRepository.verify` (`repositories.py:1112`, constant-time, fail-closed) | READY |
| Lease/fencing | `scheduler_lock` + generation fencing (ADV-02, PA7); `record_operator_decision` acquires the lock for the write | READY |
| **HumanDecisionReceived emitter** | — | **ABSENT (GAP-1)** |
| Retraction-proposal intent kind | — | **NEEDS DESIGN** if Director-proposals are ratified (OPEN-DECISION-1) |
| Vault `_inbox/` intake | v6 §21 (renderer owns `journal/`, human owns `_inbox/`) | DESIGNED in v6, NOT implemented — out of scope for Step 6 slices 1–3 |

### 3.5 The production gap, precisely

```
$ grep -rn "HUMAN_DECISION_RECEIVED" src/ --include=*.py
src/hermes/core/events.py:32        # catalog declaration
src/hermes/research/gateway.py:1075 # S5 validator SELECT (read-side)
```

No `src/` file appends `HumanDecisionReceived`. Every other human-authority
surface in the codebase pairs its event with an ingestion path:
`resolve_human_gate` → `HumanGateResolved` (red-team A2),
`record_operator_decision` → `ClassificationActionDecision` (IDR-040 §3).
S5's authority evidence is the one orphaned half of this pairing — declared,
read, never written. Until an emitter exists, the S5 cascade is dead code in
production (fully verified in tests via fixture-appended decisions).

---

## 4. Decision / authority model (§13 matrix resolved)

Terminology resolution first: v6 uses "internal-only" in two distinct
senses — **proposer class** (never LLM-proposable) vs. **caller identity**
(the scheduler/deterministic layer calls `apply_intent`). `RETRACT_SOURCE`
is internal-only in the proposer sense (the human cannot literally emit an
intent; the deterministic layer ingests the human's recorded decision), which
is exactly how `RESOLVE_CLASSIFICATION_PROPOSAL` already works. No ambiguity
survives once the two senses are kept apart.

| Actor/component | Observe | Record decision | Propose intent | Apply intent | Mutate S5 |
|---|---|---|---|---|---|
| Operator (ratified credential) | YES (digest/CLI/vault views) | **YES — sole authority** (records the retract verdict; becomes the `HumanDecisionReceived` row) | Indirectly — their recorded decision is what authorizes the deterministic ingestion | NO (never calls `apply_intent` directly) | NO (indirect, only via D+E) |
| Reconciler / Director loop | YES (read-only digest surfaces) | NO | YES — proposal intents only, per branch below | NO | NO (hard invariant) |
| Gateway (`apply_intent`) | reads persisted state | NO | — | validates & applies admitted intents | performs the cascade (sole writer) |
| S5 mutation layer | — | — | — | — | executes the ratified cascade inside the gateway transaction |
| LLM agents | bounded judgment inputs only | NO | only via ratified LLM-proposable kinds — retraction is NOT one (v6 §8) | NO | NO |

Every cell traces to: v6 §8 (intent classes), §9.3 (retraction = always
requires human), IDR-040 §2 (advisory CANNOT mutate), ADV-02/PA7 (fencing).
The single cell marked by design decision rather than pure trace is
Reconciler/Propose under OPEN-DECISION-1 (below).

---

## 5. The core design question answered (A–D ownership)

### Branch H — human-only (v6 recommended default, §27 item 13)

```text
A  observation surfaces (existing, read-only): digest shows retracted-source
   candidates / blast radius / fetch-hazard records
B  DECISION: the OPERATOR records the retract verdict
   → NEW: Controller.record_source_retraction_decision(...) — the GAP-1 fix:
     verifies operator credential (_verify_operator), acquires the scheduler
     lease (LOCK refusal on contention — the record_operator_decision
     pattern), builds an INTERNAL ingestion that appends the append-only
     HumanDecisionReceived event (correlation_id = operator-chosen decision
     ref; payload carries {decision, reason_digest, target_hint})
C/D/E  the SAME controller method (or a thin follow-on call) builds the
   RETRACT_SOURCE intent citing that decision ref and admits it through
   apply_intent — the gateway re-validates everything independently
```

Note the shape: B and C are fused in one lease-held operation exactly as
`record_operator_decision` fuses "ingest verdict" with "admit intent." There
is **no separate reconciler-proposal object** in this branch — the smallest
abstraction that satisfies the architecture is the existing
decision+intent fusion, not a new intermediate.

### Branch D — Director-proposed, human-approved (open item 13's alternative)

```text
A  reconcile_digest() gains a retraction_candidates section (seeded from
   fetch-hazard SourceRetracted records / mis-citation review findings)
B  propose_retractions(): emits RETRACT_SOURCE_PROPOSAL-style intents
   (NEW kind, DIRECTOR role) → append-only audit event, PENDING state
C  pending replay into the digest (the propose-observe loop)
D  operator records the verdict → HumanDecisionReceived (GAP-1 fix again)
E  deterministic ingestion admits RETRACT_SOURCE citing the decision
```

Branch D strictly contains Branch H plus one proposal kind and a replay
section. Both branches share: the same decision record, the same gateway
validation, the same S5 application, the same idempotency keys.

### Recommendation (not a ratification)

Implement **Branch H now**; it is the minimum that closes GAP-1 and honors
"always requires human." Branch D remains available later without rework —
its additions are purely additive (one intent kind, one digest section) and
touch nothing Branch H builds. Ratifying Branch D later would then be an
extension, not a migration. This ordering makes OPEN-DECISION-1 non-blocking
for the hardening work while leaving the operator's choice fully open.

---

## 6. Single-writer / single-gateway invariant (§5)

Preserved verbatim in both branches:

- No reconcile-loop component writes S5 state. The Director loop's write
  surface is limited to admitting intents through `apply_intent` (IDR-040 §2
  "CANNOT" list extends unchanged) plus the two append-only audit records
  (decision record; proposal record under Branch D) — neither mutates state.
- No second emission of `SourceRetracted`: the event is emitted only inside
  the gateway's cascade transaction (and by the pre-existing IDR-040
  fetch-outcome auto-emit, which records an observation hazard, not an S5
  cascade — distinct semantic facts, distinct producers; unchanged).
- Where the boundary could look ambiguous and why it is not:
  `record_source_retraction` (audit append) vs. `RETRACT_SOURCE` (mutation)
  share the word "retraction" but live on opposite sides of it — the audit
  record is the OBSERVATION (IDR-040 §2), the intent is the MUTATION. Step 6
  documentation must keep the distinction explicit; the names stay as-is
  (renaming public contracts is prohibited drift).

## 7. Determinism boundary (§7)

Same persisted state ⇒ same proposed/derived outputs, given the established
version discipline: digest sections carry `*_VERSION` constants and a
content hash (`RECONCILE_DIGEST_VERSION` precedent); candidate surfaces are
deterministic `sorted(set(...))` compositions over insert-only tables; the
gateway is deterministic by construction. The only nondeterminism entering
the pipeline is operator input timing — which is authority, not mechanism.

## 8. `RETRACT_SOURCE` proposal semantics (§9)

Mapped to the ratified contract, not invented:

| Requirement | Source | Step 6 mapping |
|---|---|---|
| Required evidence | v6 §7/S5: cited reason + recorded `HumanDecision` | decision row (GAP-1 emitter) + free-text reason carried in the intent payload |
| Source identity | S5 impl: artifact-id or `<type>:<hash>` | unchanged; proposal surfaces cite the same forms |
| Operator authority | v6 §9.3: always requires human | credential check precedes any write (OPERATOR refusal otherwise) |
| Correlation / idempotency identity | S5 impl: sha256(source_ref, reason, human_decision_ref) | unchanged; the decision ref is the natural dedup key upstream |
| Temporal semantics / staleness | S5 impl: STALE guard on already-retracted sources | unchanged; a stale proposal surfaces as data (`rejected: true, code: STALE`), never raised through the loop |
| Proposal repeatability | IDR-040: repeat digest runs duplicate nothing | holds for both branches |
| Proposal invalid before application | covered by gateway re-validation at admission time | a proposal whose decision was refused/superseded simply fails admission — no proposal-expiry machinery needed |

Where v6 is silent — e.g., whether one decision may authorize retracting
multiple sources (S5 currently permits it; adversarially probed at closure) —
this gate records it as an open item for the Step 6a implementation charter,
not as silently chosen semantics.

## 9. Idempotency model (§10)

Layer-by-layer, distinguishing semantic effects from audit multiplicity:

| Stage | Semantic idempotency | Audit/event multiplicity |
|---|---|---|
| Decision recording | same (operator, decision-ref) re-record → `duplicate=True`, nothing changes | none beyond the uniform IntentApplied audit (established pattern) |
| Digest/cycle rerun | pure recomputation; identical inputs → identical hashed output | zero |
| Proposal (Branch D) | deterministic proposal id; repeats return the existing record | each admission attempt logs its own audit row (legitimate, established) |
| Application | full-command key; identical repeat → duplicate=True with zero cascade effects; differing command → STALE | IntentApplied per attempt |
| Crash windows | see §11 — every boundary is transactional or append-only | — |

## 10. Concurrency model (§11)

No new primitive required. The existing stack is demonstrably sufficient:

- Single-writer: `BEGIN IMMEDIATE` on the one-row `scheduler_lock`; a second
  live controller fails acquisition and returns `idle="lock_held"` — two
  reconciliation workers cannot both be inside a tick.
- Verdict ingestion is lease-held end-to-end (`record_operator_decision`
  precedent): concurrent verdict → fail-closed `LOCK`, nothing written,
  lease released after.
- Race (decision recording ↔ reconciliation): harmless — reconciliation only
  reads committed state; an undecided decision is invisible until commit.
- Race (two operators, same source): serialized by the lease; second verdict
  hits the gateway's duplicate/STALE logic. Conflicting decisions on the same
  source: the FIRST applied retraction wins; later ones refuse STALE. This is
  the S5-closure-tested behavior and needs no extension.
- Minimum locking boundary: the existing lease around each ingestion call.
  Compare-and-swap machinery would be speculative abstraction — rejected.

## 11. Failure and recovery model (§12)

Boundary-by-boundary against the existing journal/WAL architecture:

| Boundary | Failure behavior | Recovery |
|---|---|---|
| decision persistence | lease-held single transaction; crash rolls back | retry re-records; idempotent |
| reconciliation reads | read-only; crash costs nothing | next cycle recomputes |
| proposal creation (Branch D) | gateway transaction; crash rolls back | repeat cycle re-proposes; deterministic ids prevent duplication |
| gateway validation | rejection = data, no write | surfaced in digest; fixable by operator |
| intent persistence + S5 application | ONE atomic `BEGIN IMMEDIATE` (F9-class, S5-verified); sabotage of the final write persists nothing | replay-safe via correlation key |
| process restart | WAL recovery restores last committed state; orphaned nothing — every stage is either fully committed or absent | deterministic recomputation from the journal |
| journaled / not journaled | every accepted mutation and audit record journals (append-only triggers, F-16); rejected attempts leave only the IntentRejected signal row per §8 | nothing must be suppressed |

Event-journal redesign: explicitly out of scope; the existing append-only +
trigger-guarded journal satisfies every requirement above.

## 12. Event / audit model (§14)

| Pipeline stage | Event | Status |
|---|---|---|
| operator decision recorded | `HumanDecisionReceived` | EXISTS in catalog; **emitter = GAP-1 deliverable** |
| observation (fetch hazard) | `SourceRetracted` (observation-class, IDR-040 auto-emit) | EXISTS — distinct producer, distinct semantic fact |
| proposal (Branch D only) | new append-only proposal event (ClassificationActionProposed analog) | NEEDS DESIGN, contingent on OPEN-DECISION-1 |
| intent admission | `IntentApplied` / `IntentRejected` | EXISTS |
| S5 mutation | `SourceRetracted` (cascade) + `TaskInvalidated` | EXISTS, S5-owned |

No duplicate semantic events introduced. Replay safety: replay consumers
recompute derived views from committed rows; a recorded decision replays as
history, never as a new mutation, because mutations exist only inside gateway
transactions keyed by content hashes — the same property that makes S5
replay-deterministic (closure probe 9).

## 13. ResearchDecision integration (§15)

- The `ResearchDecision` artifact with `supersedes` edge is an **output** of
  S5 (written inside the cascade), and an **input** to advisory reads only.
- It does NOT represent operator authority — authority lives in the
  `HumanDecisionReceived` journal row; the artifact represents the research
  fact "this source is superseded." Keeping these separate is what lets the
  gateway treat them differently (authority is dereferenced fail-closed;
  artifacts are graph nodes).
- Supersession affects reconciliation only as lineage: newer decisions
  supersede older ones along `supersedes` edges; historical decisions remain
  auditable forever (archived-not-deleted). No redesign.
- Source identity resolution stays SD-05 (artifact-id or `<type>:<hash>`),
  already dual-form-supported by the S5 resolver.

## 14. Post-retraction artifact analysis (§17)

The S5 closure finding stands and is CLASSIFIED here:

- **Artifacts created after a retraction are not retro-invalidated — correct
  behavior, belongs in S5, no change.** An artifact that did not exist when
  the source died cannot have inherited validity from it; conversely,
  admitting it is a *screening* question, not a mutation question.
- Whether new downstream work may cite an already-retracted source is the
  §16.6 inadmissible-source screen — i.e., **cascade step 4**, explicitly
  deferred with §16.6. Not fixable in Step 6 without inventing the deferred
  substrate; the boundary stays clean.
- Future decisions referencing retracted sources: the decision record is
  advisory; the gateway's STALE guard blocks re-mutation. Any deeper
  screening is S7 territory.
- Responsibility assignment: **validity at decision time = operator +
  observation surfaces (Step 6 reads); validity at application time = S5
  gateway (done); future citations = deferred §16.6/S7.** Nothing moves.

## 15. S7 compatibility analysis (§16)

The proposed architecture creates no assumption that conflicts with the S7
substrate:

- Authority flows through recorded decision events, not through any registry
  structure — §16.6's curated registry can attach later as another consumer
  of the same events.
- The dependency-cone walk uses the live 3-of-5 edge vocabulary with the
  relation isolated behind named constants (`_S5_DEPENDENCY_EDGE_TYPES`);
  S7's admission screening composes over the same cones without altering
  them.
- Branch D's optional proposal kind is orthogonal to FeatureBinding/
  curation-invariant admission (which govern knowledge admission, not
  retraction proposals).
- Nothing in Step 6 writes to, assumes, or reserves §16.6 structures.
  Future compatibility demonstrated by construction: every extension point
  is an event consumer or an advisory read, both additive by nature.

## 16. Adversarial design review (§18 — 20 attacks)

| # | Attack | Violated invariant? | Handled today? | Design response | Implement now? |
|---|---|---|---|---|---|
| 1 | duplicate reconciliation cycles | determinism/idempotency | YES — pure reads, hashed digests | none needed | — |
| 2 | concurrent workers | single-writer | YES — lease refuses second tick | none | — |
| 3 | stale decisions | authority freshness | PARTIAL — gateway re-validates at admission; a decision older than intervening state changes still passes if the exact command is legal | acceptable: authority is the human's, not the clock's; STALE covers re-mutation | no |
| 4 | superseded decisions | one-truth | YES — supersedes lineage is append-only; old decisions remain historical facts, gateway validates current state | none | — |
| 5 | operator decision replay | idempotency | YES — decision-ref dedup + full-command key downstream | none | — |
| 6 | retraction between observation and application | TOCTOU | YES — admission-time validation is authoritative; digest staleness is cosmetic | none | — |
| 7 | proposal replay (Branch D) | idempotency | YES by design — deterministic proposal ids (pattern proven) | n/a until Branch D ratified | — |
| 8 | gateway rejection after proposal | audit completeness | YES — rejection is data (`IntentRejected`), proposal remains visible | none | — |
| 9 | crash between proposal and application | atomicity | YES — proposal is an append-only record; application is separately atomic | none | — |
| 10 | crash after application | durability | YES — single committed transaction; WAL | none | — |
| 11 | duplicate intents | idempotency | YES — correlation-key dedup (S5-closure tested) | none | — |
| 12 | conflicting operator decisions | single authority per act | YES — lease serializes; first-applied wins; later refuse STALE/duplicate | none | — |
| 13 | two operators, same source | same as 12 | YES | none | — |
| 14 | malicious/incorrect proposal construction | authority integrity | YES — credential check + gateway re-validation of everything; the reconciler cannot fabricate authority (GAP-1 fix keeps decision fabrication impossible: emitter requires ratified credential) | keep credential check inside the lease | yes (slice 1) |
| 15 | direct mutation bypass | single-gateway | YES — no public retraction API besides intent path (S5-closure probe A2) | regression-test pins it | yes (test slice) |
| 16 | event replay | replay purity | YES — mutations only inside gateway transactions; replay recomputes views | none | — |
| 17 | database rollback | atomicity | YES — F9-class single transaction (S5-closure probe) | none | — |
| 18 | WAL recovery | durability | YES — SQLite WAL; restart resumes from committed state | none | — |
| 19 | artifacts created after retraction | screening boundary | YES (by deferral) — classified §14 above; screen is deferred §16.6 | document boundary | no (deferred) |
| 20 | future S7 admission vs Step 6 assumptions | compatibility | YES — §15 analysis; all extension points additive | keep edge-vocabulary constants named/isolated | no |

No attack survives. Two require implementation-time test coverage (14, 15).

## 17. Implementation-readiness matrix (§19)

| Component | Class | Detail |
|---|---|---|
| Observation surfaces (candidates, radius, digest) | **READY** | shipped, versioned, no-write pinned |
| Operator credential verification | **READY** | constant-time, fail-closed |
| Lease/fenced write | **READY** | ADV-02/PA7 + record_operator_decision pattern |
| Decision event + ingestion surface | **NEEDS HARDENING (GAP-1)** | catalog event exists; add the sanctioned emitter method + its validator-grade checks |
| `RETRACT_SOURCE` admission (E) | **READY** | S5, closed at `206b643` |
| Director retraction-proposal kind (Branch D) | **NEEDS DESIGN + RATIFICATION** | blocked on OPEN-DECISION-1; additive later |
| Vault `_inbox/` intake channel | **NEEDS DESIGN** | v6 §21 Phase 0 contract, unimplemented — explicitly NOT part of Step 6 slices below |
| §16.6 inadmissible-source screen (cascade step 4) | **BLOCKED** | on §16.6 substrate (Step 4 deferral, unchanged) |
| S7 admission screening | **BLOCKED** | on S7 substrate (unchanged) |

Required for Step 6a (Branch H): one controller method (+ its lease/credential
plumbing), zero schema changes, zero migrations, one new event-emitter test
suite, docs. No dependencies on S7 or any future step.

## 18. Proposed implementation sequence (§20 — NOT executed here)

**Slice 1 — operator-decision ingestion for source retraction (closes GAP-1).**
Objective: the sanctioned B-stage surface.
Modules: `controller.py` (new method beside `record_operator_decision`),
possibly a small gateway-adjacent helper; no gateway changes.
Contract: verify credential → acquire lease → append `HumanDecisionReceived`
(correlation_id = decision_ref, payload `{decision, reason_digest,
target_hint}`) → optionally fuse the `RETRACT_SOURCE` admission (same lease)
→ release lease. Refusals surfaced as data (OPERATOR / LOCK / duplicate).
Invariants: no second emission path for the event outside the lease; no
state machine touched by the decision record itself.
Tests: credential failures, LOCK contention, duplicate refs, malformed
payloads, event-row shape, lease release, fusion success/failure paths.
Rollback boundary: revert the single method + tests; nothing else touches.
Closure criteria: full suite green; a production (non-fixture) end-to-end
test drives decision → `apply_intent` → verified cascade.

**Slice 2 — digest integration.** Objective: observation visibility.
Modules: `controller.reconcile_digest()` — fold decision/proposal state into
a versioned section (`RECONCILE_DIGEST_VERSION="3"`).
Tests: hash binding, determinism, decided-vs-pending folding.
Rollback boundary: revert section + version bump.

**Slice 3 — (contingent on OPEN-DECISION-1 ratifying Branch D) proposal
kind + replay.** Objective: Director-proposed retraction under human
approval. Modules: new intent kind + validator + digest replay section.
Tests: mirror the PROPOSE_CLASSIFICATION_ACTION suite shape.

Each slice is independently shippable; 1 and 2 do not depend on 3.

## 19. Test strategy (§21 — designed, not written)

Unit: decision ingestion (happy/refusals/duplicates); digest sections;
deterministic ordering; stale detection. Integration: decision → gateway →
cascade end-to-end (the first non-fixture path); persistence/reopen;
journal integrity. Concurrency: competing ingestion calls (LOCK);
simultaneous operators. Crash/recovery: kill points at each §11 boundary
(transactional probes, the S5-closure sabotage pattern). Replay:
identical-ledger determinism across rebuilt DBs. Adversarial: bypass scan
(no public API besides intent path), fabricated decision without credential,
stale proposal admission, conflicting verdicts, supersession race.

## 20. Explicit non-goals

No production code in this gate. No S5 semantic change. No gateway redesign.
No S7/§16.6/FeatureBinding work. No vault `_inbox/` implementation. No new
concurrency primitives. No migrations. Branch D is designed but not built
absent ratification.

## 21. Open architectural decisions

1. **OPEN-DECISION-1 (operator):** Branch H vs Branch D — v6 §27 items
   13/25. Recommended: H now, D additive later. Must be answered before
   Slice 3, not before Slice 1.
2. Multi-source decisions: one decision authorizing several retractions is
   currently S5-permitted; ratify or restrict at Step 6a.
3. Decision-record payload schema (`reason_digest` vs full reason) — settle
   in the Step 6a charter (bounded payloads, S6 posture).
4. Vault inbox as a future decision-intake channel — deferred with §21's
   renderer phase; noted so nobody mistakes it for missing Step 6 scope.

## 22. Final verdict

**VERDICT B — STEP 6 REQUIRES TARGETED DESIGN/HARDENING** before
implementation readiness: close GAP-1 (the missing
`HumanDecisionReceived` production emitter — Slice 1) and resolve
OPEN-DECISION-1 (operator ratification of proposer authority). With those,
every remaining component is READY against existing substrate.

## 23. Recommended next charter

**STEP 6a — Operator-Decision Ingestion Surface (implementation charter):**
authorize Slice 1 (+ optionally Slice 2) exactly as specified in §18, with
the multi-source-decision and payload-schema questions settled in its body.
Sequencing rule preserved: S5 CLOSED → **Step 6 design gate (this document)**
→ Step 6a implementation (separate charter) → [optional Branch-D extension]
→ S7 substrate design gate → S7 implementation. No stage collapsed.

---

## SHA-256 manifest

| Artifact | SHA-256 |
|---|---|
| `hermes_step6_reconcile_design_gate.md` (content as committed) | `94f1e0ea79a7ccc222ba2fe39a18c7904b06b3e909d680dc6394d93b494daaa9` |

Note: the hash above covers this document up to and including the manifest
table row itself (the Step-4 convention). Any later edit invalidates it and
requires re-hashing per governance.
