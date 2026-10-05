# Hermes Research — Current Epistemic Architecture Review

**Date:** 2026-08-15 (second full adversarial pass, post-Q-05/Q-02/Q-04/Evidence-Ladder/operator-loop integration)
**Reviewer:** architecture/verification agent (this report is **operator-scoped**, not an external independent review)
**Authority basis:** live repository code > migrations > tests > IDRs > git history > prior reviews (authority order per review instruction §2)

Every claim below carries an authority label:

- **REPOSITORY-VERIFIED** — read directly from current code/migrations
- **TEST-VERIFIED** — asserted by a currently passing test (1319 passed at this HEAD)
- **PROBE-VERIFIED** — reproduced live in a throwaway probe during this review
- **DOCUMENTED** — committed governance doc, not code
- **OPERATOR-CLAIMED** — claimed by operator, not independently verified
- **INFERRED** — derived judgment
- **UNVERIFIED** — not checked

---

## A. Baseline

| Item | Value | Authority |
|---|---|---|
| HEAD | `f96a566` (Audit F8/F9: bound the RefutedApplied payload and enforce one-verdict at the schema level) | REPOSITORY-VERIFIED |
| Working tree | clean | REPOSITORY-VERIFIED |
| Remote | `origin/main` = `438b493` (HEAD is 1 commit ahead, unpushed) | REPOSITORY-VERIFIED |
| Tests | **1319 passed** (43s) | TEST-VERIFIED |
| Pyright | 0 errors, 0 warnings (config: `src` only) | TEST-VERIFIED |
| Ruff | All checks passed (C3 gate rules) | TEST-VERIFIED |
| Schema version | 12 (`SUPPORTED_VERSION`, migration 11→12 adds the one-verdict index) | REPOSITORY-VERIFIED |
| Ix | smells rev 62 · 203 candidates (god_module 48, orphan_file 154, weak 1); `ix doctor` all checks passed | TEST-VERIFIED |
| Diagrams | six verified figures in `docs/diagrams/` (authority/trust boundary, one-verdict gate, Research OS loop, provider search/fetch/recovery, horizon cliff, ladder REFUTED drivers) with per-figure provenance manifests + PNG/PDF exports — projections, never authority | REPOSITORY-VERIFIED |

The review prompt's stated baseline `d5df6ba` is 5 commits behind this HEAD. The commits since `d5df6ba` (`9eb09fd`, `d5df6ba`, `e53632f`, `8771ca7`, `438b493`, `f96a566` — the Q-05-governance and Ix commits were earlier) are exactly the operator-loop P2 remediations, token hardening, and the F1–F9 audit closures; they are reviewed **as part of this report** (sections G, H, I).

**Authority status of this report:** this is an in-house verification pass. It does **not** upgrade any operator ratification to "independently verified". The only externally-reviewed slices remain IDR-036/037 (Q-05 substrate + persistence, review PASS with MEDIUM+LOW findings remediated at `5aef874`, recorded at `8e4afb8`).

---

## B. Since-last-review changes (committed, current HEAD)

1. `8e4afb8` — Q-05 independent review recorded: IDR-036/037 upgraded to INDEPENDENTLY REVIEWED (external party), README status corrected, current-state review added.
2. `7e49a1e` — Ix refresh at `dc84673`: 200 smell claims analyzed (rev 56), ranks/doctor archived.
3. `adc40ab` — Research Operating System loop note (conceptual roadmap; every EXISTS link grep-verified).
4. `9eb09fd` — P2 #2/#3: `resolve_human_gate` one-transaction verdict + INVALIDATED-dep escape hatch.
5. `d5df6ba` — parked-gate diagnostic note + heartbeat-horizon cliff documentation, with tests.
6. `e53632f` — P2 #1: salted PBKDF2-HMAC-SHA256 operator-token hashes, min token length 8.
7. `8771ca7` — audit F1: operational mode self-heals from gate state (was silently-suppressed mode writes).
8. `438b493` — audit F2 (constant-time unknown-operator verify), F3 (specific RATIONALE refusal), F6 (transactional one-verdict check on proposal decisions), F7 (operator credentials on the S16 scope-review surface).
9. `f96a566` — audit F8 (RefutedApplied payload bounded to the event cap — a many-rival falsification no longer crashes the tick) and F9 (schema-level one-verdict index, migration 11→12, refuse-not-repair).

Also refreshed this review: Ix reports re-run at `f96a566` (rev 62) and archived under `docs/ix/`; `docs/ix/README.md` updated.

---

## C. Q-05

### C.1 Advisory role (unchanged, re-verified)

- The action map is **inert proposal categories**, never executable commands: `PermittedAction` names (`REJECT_BRANCH`, `REVIEW_DOWNSTREAM_IMPACT`, `PROPOSE_MECHANISM_SUBSTITUTION`, `PROPOSE_SCOPE_NARROWING`, `ROUTE_TO_SCOPE_REVIEW`, `PARK_FOR_RESOURCE_REVIEW`, `ESCALATE_TO_DIRECTOR`) are proposal shapes; the only execution path is the ratified-proposal handoff into the two existing authority consumers (S16 scope intake, EVIDENCE_TRANSITION) and the ladder drivers. REPOSITORY-VERIFIED (gateway proposal admission + `_resolve_ratified_proposal` + controller APPLY).
- Taxonomy remains the ratified six classes; no `HARD_AXIOM_VIOLATION`/`MULTI_FACTOR` creep. REPOSITORY-VERIFIED (`FailureClass` enum).

### C.2 Falsification-fact role (the NEW authority boundary, §4/§5/§6 — audited fresh)

`certifies_decisive_falsification(failure_class, hypothesis_ref, constraint_ref)` is a pure function: `DECLARED_CONSTRAINT_VIOLATION AND constraint_ref == "hypothesis:<H>:falsification_condition"`. REPOSITORY-VERIFIED (`failure_classification.py`).

The bare-classification REFUTED driver (controller Driver 3) gates on, in order: project scoping → digest-valid identity (`classification_id == artifact_id`) → **F13 content integrity** (stored metadata must re-derive the row's content hash — a class/constraint/hypothesis rewrite changes the derived hash and is refused) → class parse (any failure → skip) → non-empty refs → the falsification predicate → program resolves in the *current* program set → hypothesis exists → terminal-REFUTED idempotency → F12 applied-transition tamper check. Every gate is a `continue` (fail-closed per row, never a crash). REPOSITORY-VERIFIED.

Attack-list coverage (§6, 29 attacks) — all TEST-VERIFIED in `tests/test_q05_evidence_ladder.py`:

| # | Attack | Test |
|---|---|---|
| 1 | forged classification_id | `test_forged_identity_never_refutes` |
| 2 | forged content_hash | `test_content_identity_verifier`, `test_metadata_rewrite_forging_falsification_is_refused` |
| 3 | forged failure_class | `test_non_falsification_class_never_refutes`, rewrite test |
| 4 | forged project_id | SQL project scoping + `test_fail_closed_foreign_classification_ref` |
| 5–6 | forged program/hypothesis ref | `test_foreign_target_never_refutes`, `test_target_hypothesis_must_exist_in_program` |
| 7–9 | forged/wrong/methodology constraint | `test_metadata_rewrite_…`, `test_methodology_constraint_violation_never_refutes` |
| 10–14 | every non-falsification class | `test_non_falsification_class_never_refutes` |
| 15 | foreign project | scoping + `test_fail_closed_foreign_classification_ref` |
| 16 | superseded/unknown program | `test_foreign_target_never_refutes` (resolution against current program set) |
| 17 | unknown hypothesis | `test_target_hypothesis_must_exist_in_program` |
| 18 | malformed metadata | `test_corrupt_metadata_never_crashes_the_tick` |
| 19 | malformed contributing factors | digest `MALFORMED_CONTRIBUTING_FACTORS` flag (digest-level; the driver never reads contributors) |
| 20 | stale classification | no supersession model for classifications; stale *program* refs fail resolution — see C.4 |
| 21 | duplicated classification | idempotency tests (single event, single transition) |
| 22 | already-REFUTED hypothesis | `test_refuted_is_terminal` + driver idempotent skip |
| 23 | forged ladder state | `test_tampered_cache_upward_is_repaired_to_derived`, `test_tampered_refuted_cache_never_reverted` |
| 24 | forged prior transition | `test_downward_tamper_of_applied_refuted_is_healed` (F12) |
| 25 | corrupt EvidenceTransitionProposed | corrupt admission skipped with note (driver 1) |
| 26 | missing ratification | `test_refuted_without_ratification_applies_nothing` |
| 27 | rejected ratification | `test_rejected_decision_applies_nothing` |
| 28 | wrong-action ratification | `_resolve_ratified_proposal(…, {REJECT_BRANCH})` — an APPROVED non-REJECT_BRANCH proposal never resolves |
| 29 | stale/foreign ratification | `test_forged_ratification_ref_applies_nothing` + `_resolve_ratified_proposal` re-verification |

**Verdict: no unauthorized REFUTED path found.**

**Verdict: no unauthorized REFUTED path found.** The three drivers (ratified REJECT_BRANCH proposal; obligation climbs; bare-classification decisive falsification) are the only writes to REFUTED, each fully derived. The §4 question — "can anything other than a genuine declared falsification condition cause REFUTED?" — is answered **no**, with the explicit caveat that this is operator-scope verification, not the required external attack on this surface (see K).

### C.3 FRAMING_ERROR contributing-factor rule (§8) — verified everywhere

`requires_human_confirmation_for` = `class is FRAMING_ERROR OR FRAMING_ERROR in contributing_factors` — a pure function, **never a stored trust**. REPOSITORY-VERIFIED. Recomputed at every surface:

- construction (`failure_classification.py:794`)
- digest recomputation (`failure_classifications.py:751`); stored-vs-derived mismatch → `STORED_CONFIRMATION_MISMATCH` flag, `DEGRADED`
- proposal admission (`gateway.py:424`)
- decision validator (`gateway.py:648`) — a verdict on a non-gated proposal is refused
- controller proposal surface (`controller.py:953`)

The §8 attack (`primary=IMPLEMENTATION_FAILURE, contributing=FRAMING_ERROR`) was **PROBE-VERIFIED live** during this review: `requires_human_confirmation == True`, proposal gate fires even on a non-authority action, control (no contributor) is False. Tests: `test_contributing_framing_error_gates_human_confirmation`, `test_digest_gates_contributing_framing_error` (tampered stored False flagged), `test_digest_recomputes_both_derived_fields`.

### C.4 Digest corruption semantics (§10) and immutability (§11)

- `classifications_digest` returns `items/errors/integrity_status` with `OK|FLAGGED|DEGRADED`; corrupt rows are surfaced as explicit diagnostics (`MALFORMED_METADATA`, `WRONG_ARTIFACT_TYPE`, `MISSING_CLASSIFICATION_ID`, `MISSING_CLASS`, `STORED_ACTIONS_MISMATCH`, `STORED_CONFIRMATION_MISMATCH`, …), never silently dropped. TEST-VERIFIED (`test_q05_persistence.py`: DEGRADED mixed states, FLAGGED stored-mismatch states, valid rows still visible alongside diagnostics).
- **Immutability:** no `UPDATE`/`DELETE` on `research_programs` or `scope_briefs` anywhere in `src` (grep-verified at this HEAD); supersession = new row; old versions remain readable and valid; stale/foreign refs fail resolution. TEST-VERIFIED (supersession tests in `test_research_program.py`, stale-ref tests). The pre-transaction TOCTOU concern is closed by **alternative A (structural immutability)** — citation targets cannot change after publish, so resolution outside a transaction is safe. REPOSITORY-VERIFIED.

---

## D. Q-02

### D.1 Precedence (§14) — the real competition is tested

The shipped precedence (from controller + evaluation code, confirmed by tests): **hard eligibility → dependency/gate/call-cap budget → Director priority (mechanism deferred — tested as absent) → Q-02 deterministic policy (lexicographic dimensions, cost tiebreak, UNKNOWN last) → created_at → task_id**.

The eligible-vs-eligible golden case exists and is exact: `test_low_cost_eligible_task_dispatches_first` — both tasks eligible, the later-created LOW-cost task dispatches before the earlier-created HIGH-cost one, asserting the policy beats `created_at`. TEST-VERIFIED. Boundaries all hold: dependency-blocked task never ordered/dispatched (`test_dependency_blocked_task_is_never_ordered_or_dispatched`), call cap (`test_ordering_cannot_squeeze_past_the_call_cap`), failed-gate task (`test_task_awaiting_a_failed_gate_is_never_ordered`), no Director-priority mechanism exists (`test_no_priority_mechanism_exists`).

### D.2 Authority boundary (§13)

Q-02 orders **already-eligible** tasks only; it cannot admit, create, bypass dependencies/gates/budgets/human approval, mutate ladder state or scope, modify Director authority, ingest LLM information gain, or alter lifecycle authority. TEST-VERIFIED across `tests/test_controller_q02.py` (dependency/budget/gate boundaries; `test_evaluation_never_imports_the_controller`; `test_dispatch_never_writes_beyond_the_ordinary_flow`).

### D.3 Deterministic proxies (§15) and metadata injection

Unavailable dimensions surface as `NONE` — no fabricated values. `test_llm_supplied_spec_fields_cannot_enter_the_ordering` (free-form `information_gain`/`roi_score` from task specs are never ordering inputs), `test_forged_or_malformed_provenance_is_never_an_ordering_input`, `test_unknown_cost_class_sorts_last` (UNKNOWN never treated as a value). TEST-VERIFIED.

### D.4 Versioning (§16) and recovery (§17)

`EligibleTask` carries the version triple (`evaluator_version`, `policy_version`, `schema_version`; `EVALUATION_SCHEMA_VERSION = "1"`); the dispatch result records `ordering_policy_version` (`task-eval-2026.1` asserted in tests). REPOSITORY-VERIFIED + TEST-VERIFIED. Recovery is **deterministic recomputation from current ratified facts** (`test_ordering_survives_crash_recovery_unperturbed`, `test_ordering_deterministic_as_satisfactions_grow_across_ticks`) — no retained ordering context, consistent with the §17 preference.

---

## E. Q-04

- **Cone:** forward reachability through non-SUCCEEDED source nodes; a SUCCEEDED intermediate breaks propagation. The §18 attack (A FAILED → B SUCCEEDED → C READY: C neither in cone nor blocked; B in cone only) is exactly `test_succeeded_intermediate_breaks_the_blocking_chain`. TEST-VERIFIED. Cycles/sorted traversal/duplicate edges/missing nodes covered by the cone suite (`tests/test_q04_failure_cone.py`).
- **Blast radius:** traverses the existing ratified `provenance_edges` set (`cites`, `derived_from`, `supersedes`, `used_as_input`, `justifies`) read-only; surfaces never write. TEST-VERIFIED (`test_blast_radius_regardless_of_status`, `test_surfaces_never_write`).
- **No automatic invalidation (§20):** blast radius and `SourceRetracted` produce observations + re-review candidates only; no automatic state mutation, no automatic evidence retraction. TEST-VERIFIED (`test_surfaces_never_write`, re-review candidate tests).
- **Future requirement recorded (not built, per §42):** the five edge types currently share one propagation semantics; an edge-propagation policy version is future work.

---

## F. Proposal lifecycle

- **Gate recomputation (§23):** the gate is derived from class + contributing factors + action shape at admission, replay, and decision time — stored gate state is never trusted. `test_gate_recomputed_never_trusted_from_storage`, `test_tampered_pending_on_no_gate_proposal_not_replayed`, `test_tampered_effective_on_gated_proposal_still_replayed`, `test_gate_recomputed_from_action_never_stored`. TEST-VERIFIED.
- **One proposal → one verdict:** now enforced twice — transactionally (F6: prior-read + append in one `BEGIN IMMEDIATE`, race-probe-confirmed closed) and at the schema level (F9: partial unique index on `events(event_type, correlation_id)` for the one-verdict types; migration refuses existing duplicates rather than repairing). Regression tests `test_f6_one_verdict_race_closed`, `test_migration_registers_version_12`, `test_migration_12_refuses_existing_duplicates`. TEST-VERIFIED.
- Contradictory verdict refused; identical verdict idempotent; unknown proposal / unknown payload key / corrupt payload / undereferenceable classification all refused or surfaced with notes; cross-project proposals refused at the gateway (`in_project` check). TEST-VERIFIED (`tests/test_q04_gate_replay.py`, ~30 tests).
- Proposals never execute; only the two ratified consumers apply (S16 scope review, EVIDENCE_TRANSITION) plus the ladder drivers, each re-verifying the ratification (`_resolve_ratified_proposal`). REPOSITORY-VERIFIED.

---

## G. Evidence Ladder (APPLY authority)

- **Principle (§28):** stored ladder state is a **cache, never the source of truth**. The APPLY pass derives desired state from ratified facts (satisfaction links, ratified REJECT_BRANCH proposals, digest-valid decisive falsifications) and only *compares* the cache: upward tamper repaired to derived (`test_tampered_cache_upward_is_repaired_to_derived`), downward tamper of an applied transition healed with a note, never re-created (`test_downward_tamper_of_applied_refuted_is_healed`, F12); REFUTED is terminal and never downgraded (`test_refuted_is_terminal`, `test_tampered_refuted_cache_never_reverted`). TEST-VERIFIED.
- **F8 (this review's probe):** a falsification with 200 rivals produced a 9444-byte `RefutedApplied` payload > the 4096-byte event cap; the append raised and **re-raised through `tick()`, crashing the loop on legitimate input** (probe-confirmed). Fixed in `f96a566`: dependent list truncated deterministically (sorted-prefix) to fit, full `dependent_count` recorded, truncation surfaced as a note. Regression: `test_many_rivals_never_crash_tick_payload_bounded`. TEST-VERIFIED.
- **F9 (schema):** migration 12's unique index is the schema-level backstop for one-verdict/one-transition; the transition admission's check-then-append race was closed transactionally in the same commit (the index alone would have turned the race into an unhandled `IntegrityError`). TEST-VERIFIED.
- Every ladder write is its own transaction (row + event); crash mid-chain recovers to the same ladder (`test_crash_mid_chain_recovers_to_same_ladder`); identical facts → identical ladder across tick schedules (`test_identical_facts_identical_ladder_across_tick_schedules`). TEST-VERIFIED.

---

## H. Operator loop (human gate / recovery / heartbeat)

All five prior independent-review P2 residuals are closed or consciously accepted (governance record: `hermes_p2_residuals_governance.md`):

- **P2 #1 token hashing — REMEDIATED** (`e53632f`): salted per-credential PBKDF2-HMAC-SHA256, self-describing format, min token length 8; legacy bare-hex fallback.
- **P2 #2 gate atomicity — REMEDIATED** (`9eb09fd`): the APPROVED/REJECTED verdict (RUNNING → event → terminal → `HumanGateResolved`) is one fenced transaction; crash-injection test proves zero half-state (`test_11_resolve_verdict_lands_in_one_transaction`).
- **P2 #3 REJECTED permanent-park — REMEDIATED** (`9eb09fd` + `d5df6ba`): a parked HUMAN_GATE whose dep is INVALIDATED after parking resolves via the operator verdict (escape hatch), with a diagnostic note at both the tick surface and the verdict surface; F-10 remains a claim-time guard. Tests: `test_11_escape_hatch_invalidated_dep_after_parking_still_resolvable`, `test_11_parked_gate_invalidated_dep_diagnostic_note`.
- **P2 #4 horizon cliff — DOCUMENTED + TESTED** (accepted design): refresher exits permanently on horizon exhaustion; lease goes stale; recovery reclaims and re-executes exactly once; the late handler's writes are discarded by the IDR29-02 binding guard (fired before the generation fence — the real order, asserted by `test_15_f15_horizon_cliff_late_handler_discarded`). At-most-one active lease + at-least-once completion + binding-protected idempotent persistence. TEST-VERIFIED.
- **F1 (in-house audit):** park/final-verdict mode writes were `contextlib.suppress`-wrapped — a failed write left a permanent-park or, worse, a **gate-bypass** state (gate waiting under ACTIVE → next tick dispatches past it). Fixed in `8771ca7`: mode now self-heals from gate state every tick; failures surface on the notes channel. Two self-heal tests.
- **F2:** constant-work unknown-operator verify (no timing oracle); **F3:** specific `RATIONALE` refusal for oversized verdict rationale; **F7:** S16 scope-review surface now requires operator credentials (was the only human-verdict surface without one). All TEST-VERIFIED in `438b493`.

Diagnostics are separated from authority throughout (notes channel never gates, never vets).

---

## I. Provenance and artifacts

- **SourceRetracted (§21):** emitted only from provider-declared `REMOVED_OR_RETRACTED` markers (HZ-02), in the same transaction as the outcome record, `NEW`-only (idempotent); `NOT_OA` never emits; a bare HTTP 404 is `MALFORMED_200`/`NOT_OA`, never a retraction. REPOSITORY-VERIFIED (`source_outcomes.py`, `hazards.py`). Tests: `test_retraction_hazard_emits_the_event_atomically`, `test_identical_retry_does_not_duplicate_the_event`, `test_fetch_without_retraction_hazard_emits_no_event`, end-to-end advisory test. TEST-VERIFIED.
- **Ratified-by distinction (§7):** the ladder and `RefutedApplied` carry `ratified_by="classification"` (deterministically admitted digest-valid record) vs `ratified_by="proposal"` (human-approved verdict) — the taxonomy the review instruction demands already exists in the data. REPOSITORY-VERIFIED.
- **Derived-artifact taxonomy (§31):** the generic artifact store carries OBSERVATION/DERIVED_ANALYSIS/PROPOSAL/DECISION/EXECUTION semantics implicitly (artifact types + event types). No immediate misclassification risk found in the *execution* paths (every consumption point re-derives); a formal taxonomy is **future architecture work** — not built, per §42.

---

## J. Authority model

The architecture matches the §44 principle end to end:

```
OBSERVE → CLASSIFY → ANALYZE IMPACT → PROPOSE → HUMAN-RATIFY (where required)
→ APPLY existing authority → RECOMPUTE derived state → PRIORITIZE next eligible
work → EXECUTE → OBSERVE
```

Every derived-to-authoritative step is an explicit, deterministic, re-verifiable contract: ladder rungs re-derive from ratified facts; verdicts re-verify against the journal; ordering recomputes from current ratified facts; gate state is recomputed, never stored-trusted; content identity re-derives from metadata. No "stored row says so", no "LLM said so", no "proposal was previously effective" paths were found. The one historical violation of this discipline (the suppressed mode writes, F1) was found by this review's own failure injection and fixed.

Stage distinction (§30): Observation (`SourceRetracted`), Analysis (Q-05 classification), Proposal (action proposal), Ratification (human verdict), Evidence fact (decisive falsification predicate), Execution (ladder drivers / ratified consumers) are distinct types with distinct consumption rules. REPOSITORY-VERIFIED.

**Vocabulary (§32):** the report recommends (not built) consistently labeling: Q-05 = **advisory / falsification-fact input depending on path**; Q-02 = **deterministic control policy**; Q-04 = **descriptive/review advisory**; Evidence Ladder APPLY = **authoritative execution path for evidence state**. The code already encodes most of this in docstrings and the `ratified_by` field; a formal vocabulary pass is future work.

---

## K. Independent-verification status

| Slice | Status | External verification |
|---|---|---|
| Q-05 substrate + persistence (IDR-036/037) | IMPLEMENTED + TESTED / CLOSED | **YES** — external independent review, PASS, MEDIUM+LOW findings remediated at `5aef874`, recorded at `8e4afb8` |
| Q-05 → Evidence Ladder REFUTED authority | IMPLEMENTED + TESTED | **NO** — operator-ratified; not covered by the substrate review |
| Q-02 (IDR-038) | IMPLEMENTED + TESTED / RATIFIED / CLOSED | **NO** |
| Q-04 task cone (IDR-039) | IMPLEMENTED + TESTED / RATIFIED / CLOSED | **NO** |
| Q-04 artifact radius + SourceRetracted (IDR-040) | IMPLEMENTED + TESTED / RATIFIED / CLOSED | **NO** |
| Proposal lifecycle + ladder APPLY (IDR-041) | IMPLEMENTED + TESTED / RATIFIED / CLOSED | **NO** |
| Operator loop additions (F15/F16/B4, P2s, F1–F9) | IMPLEMENTED + TESTED | **NO** |

DOCUMENTED + REPOSITORY-VERIFIED. The recommendation from §35 stands and is reinforced: the external closure should attack **one coherent package** — Q-02 + Q-04 + IDR-040/041 + the Evidence-Ladder REFUTED authority + the operator-loop additions — rather than re-running only the old Q-05 substrate review. This is the highest-value next step; nothing in this report substitutes for it.

---

## L. Research OS loop

From `hermes_research_operating_system_loop.md` (verified against code during its writing; every EXISTS link grep-verified):

```
ResearchProgram ──EXISTS──▶ Task graph ──EXISTS──▶ Controller execution
      ▲                                                  │
      │                                                  ▼
      │                                               Evidence
      │                                                  │
      │                                                  ▼
      │                                       SUPPORT / REFUTED (ladder)
      │                                                  │
      │                                                  ▼
      │                                               Q-05 "WHY?"
      │                                                  │
      │                                                  ▼
      │                                        Q-04 "WHAT ELSE IS AFFECTED?"
      │                                                  │
      │                                                  ▼
      │                                             ActionEvaluation
      │                                                  │
      │                                                  ▼
      │                                           Q-02 "WHAT NEXT?"
      │                                                  │
      └────────────────────────────── Controller dispatch ◀┘
```

Visualization: `docs/diagrams/research_os_loop.html` (Loop figure: 8 stations + one hub; PNG/PDF in `docs/diagrams/exports/`) — a projection with its own provenance manifest, never authority.

All ten arrows **EXISTS** (task-graph creation, execution, evidence ingestion, ladder promotion, Q-05 classification, Q-04 impact/re-review advisory, proposal lifecycle, Q-02 ordering, dispatch, task-graph feedback). PLANNED/MISSING: none were invented — the loop is genuinely closed as a *feedback* loop; what is deliberately absent is a loop *driver* (no second scheduler, no auto-pivot engine, no hidden LLM scheduler — documented as "what the loop is NOT"). DOCUMENTED + REPOSITORY-VERIFIED.

---

## M. Remaining defects (classified)

| ID | Finding | Class | Status |
|---|---|---|---|
| F4 | Stored-iteration DoS: PBKDF2 iteration count read from stored credential (attacker-controlled) — informational; iteration counts come from the store, bounded by a sane-range check | OBSERVATION (P3) | open, recorded in audit doc |
| F5 | `--token` on argv + unsalted-at-rest local config | OBSERVATION | accepted for lab tool, recorded |
| — | Edge-propagation policy version (all five edge types share one semantics) | FUTURE DESIGN | recorded, not built (§19/§42) |
| — | Derived-artifact taxonomy (OBSERVATION/DERIVED_ANALYSIS/PROPOSAL/DECISION/EXECUTION as a first-class type) | FUTURE DESIGN | recorded, not built (§31/§42) |
| — | Task-class runtime policy: expected duration / max runtime / heartbeat horizon / recovery policy | FUTURE DESIGN | recorded, not built (§27) — the 300s default is consciously NOT universally safe |
| — | Authority vocabulary formalization | FUTURE DESIGN | recorded, not built (§32) |
| — | Global Ix map ingest (ArangoDB 409/1210 on patch commit — environmental) | OBSERVATION | scoped pipeline unaffected; documented in `docs/ix/README.md` |
| — | `resolve_human_gate` REJECTED-through-RUNNING interim state | OBSERVATION | escape hatch fixed the permanent-park; the interim RUNNING blip remains, verdict atomicity prevents any half-state |

**No BLOCKER, no MUST FIX** found at this HEAD. All earlier MUST-FIX-grade findings (F1 mode-suppression, F6 one-verdict race, F8 tick crash) were remediated in this session's commits and regression-locked.

---

## N. Improvements

**Immediate (in this report's scope — done):** F8/F9 closed and regression-locked (`f96a566`); Ix reports re-run and archived at `f96a566`.

**Before external closure (recommended, NOT yet done):**
1. Assemble the §35 package (Q-02, Q-04, IDR-040/041, ladder REFUTED authority, operator-loop additions) for one independent external adversarial review.
2. Fix F4 (bounded iteration range on stored credentials) if the external review flags it — currently P3/informational.
3. Add the explicit IMPLEMENTATION_FAILURE+FRAMING_ERROR contributing-factor variant to the test suite (rule is class-agnostic and PROBE-VERIFIED this review, but the exact primary is only covered by equivalence via RESOURCE_CONSTRAINT).

**Future (recorded, deliberately not built):** edge-propagation policy version; derived-artifact taxonomy; task-class runtime policy; authority vocabulary pass; richer re-review candidate explanations; horizon policy per task class.

---

## O. Final verdict

**READY FOR INDEPENDENT EPISTEMIC CLOSURE.**

Reasoning: (1) the central question — has Hermes become a coherent Research OS loop without hidden second authorities / false promotion paths / duplicate state machines / unverifiable derived truth — is answered **no violations found** across every surface examined (the one genuine violation found, F1's silently-suppressed mode writes, was probe-confirmed and fixed this session); (2) every prior P2 residual and every in-house audit finding F1–F9 is closed and regression-locked; (3) 1319 tests pass with pyright 0 / ruff clean; (4) the architecture discipline (derive → verify → authorize → apply → audit) holds at every checked boundary, and Ix shows no new authority nodes or scheduler loops.

The verdict is **conditional on the external closure pass**: the Q-05→REFUTED authority, IDR-040/041, Q-02, and Q-04 remain operator-ratified only. Until the §35 package is independently attacked, treat the "READY" as *ready to be audited*, not *audited*. Per §45, no new Research OS capability (Q-09/Q-07/CV-01/TRIZ/Obsidian) should be started before that closure.
