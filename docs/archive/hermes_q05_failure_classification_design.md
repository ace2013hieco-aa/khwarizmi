# HERMES Q-05 — FALSIFIED FAILURE CLASSIFICATION: DESIGN

**Agent:** Hermes Research architecture-design + implementation agent
**Date:** 2026-08-15
**Status:** DESIGNED → DESIGN GATE PASSED (hostile self-review clean) → IMPLEMENTED + TESTED (this document precedes implementation; the implementation record follows in the section "Implementation notes")
**Authority order honored:** repository + ratified architecture (v6 §10.2 REFUTED; §9.1 thesis verdicts; S16 ScopeBrief) > ratified IDRs > existing tests > `hermes_surviving_ideas_application_framework.md` (proposal only) > external-source concepts > inference.

---

## 1. Current problem

When a hypothesis fails in Hermes, the system has no structured answer to *why*. The ratified architecture's falsification terminus — **REFUTED** (v6 §10.1/§10.2, "any → REFUTED" on decisive falsification) — is **ratified design, not executable behavior**: `src/hermes/research/evidence.py` is a Phase 0 placeholder, there is no evidence table, no EvidenceRepository, no Evidence Validator (authority/evidence map, `docs/idr/hermes_v6_authority_evidence_map.md:149`). Consequently:

1. There is no record in which a failure class could be stored.
2. There is no deterministic mapping from "how it failed" to "what may be proposed next".
3. Every downstream decision (reject / patch / pivot / park) is either manual or would be ad hoc — the exact "silent pivot" risk the framework's Chain A prohibits.

The framework's premise that "FALSIFIED already exists as a terminus; extend it" is **falsified by the repository itself** (see `hermes_surviving_ideas_repo_reconciliation.md` §2.1): the terminus is REFUTED, the word FALSIFIED appears nowhere, and the ladder is unimplemented.

## 2. Current Hermes owner

- **Authoritative owner of falsification:** the Evidence Ladder (v6 §10) — a P2 roadmap deliverable, currently a placeholder. Q-05 does **not** implement the ladder and does **not** add ladder states.
- **Authorization path:** the Intent Gateway (`apply_intent`, `src/hermes/research/gateway.py`) — the single mutation path. Wired for `PROPOSE_RESEARCH_PROGRAM` (Director-only), `INSERT_TASK`, `ADMIT_TASK`. `EVIDENCE_TRANSITION`/`BRANCH`/`ABANDON` are declared but NOT_WIRED.
- **Existing substrate precedent:** `claims.py` (ClaimAssumptionValidator — pure, deterministic, injected resolver, no writes), `thesis.py` (AR-03 validator — pure, injected resolver, no writes), `programs.py` (ResearchProgramValidator — pure, deterministic). The repository's manual-proof-first rule (v6 §29.2 rule 7) requires pure substrate before persistence.

## 3. Verified gap

GAP CONFIRMED (design gate: **YES — Q-05 is a real Hermes gap**), with a corrected premise:

- **No failure-class taxonomy** — nothing in src or ratified docs defines a vocabulary of *why* a hypothesis failed.
- **No deterministic action mapping** — nothing maps a failure cause to Hermes-native permitted next actions.
- **No falsification record to attach to** — the substrate must define the record shape it consumes (the future REFUTED write path's shape), exactly as `thesis.py`/`claims.py` define shapes their future write paths will persist.

The gap is *not*: a new state machine (REFUTED/UNCERTAIN are already the ratified ladder states — unimplemented, not missing from the design), a new scheduler, a new write path, or a new authority.

## 4. Scope boundary (what Q-05 is and is not)

**Q-05 IS:** a pure, deterministic **failure-classification substrate** — validator + versioned taxonomy + deterministic action map. Zero persistence, zero authority, zero new tables/events/intents.

**Q-05 IS NOT:** the Evidence Ladder; a REFUTED transition engine; a new intent/gateway kind; a controller change; automatic hypothesis/task/scope/program creation; a second epistemic authority; a parallel hypothesis lifecycle; the budget ledger (RESOURCE_CONSTRAINT does not create one).

**Deferred (documented, not built):** persistence of classifications (attaches to the future REFUTED write path as a field + `provenance_edges` citation edges); consumption by the reconcile loop/controller; the refuted registry; Q-04 downstream-impact traversal (the action `REVIEW_DOWNSTREAM_IMPACT` is emitted as a *proposal category* only).

## 5. Failure taxonomy (revised from the framework's five)

The framework's five classes were challenged per the task (§5). Result: four kept, one renamed (no axiom concept exists in Hermes — grep: 0 hits), one added (UNKNOWN — the framework's own §12 demands the honest fallback).

| FailureClass | Hermes-native meaning | Required citation (deterministic) | Permitted-action set |
|---|---|---|---|
| `DECLARED_CONSTRAINT_VIOLATION` (renamed from HARD_AXIOM_VIOLATION) | The falsifying evidence contradicts a **declared constraint**: the hypothesis's `falsification_condition`, a program `methodology_constraint`, or a ScopeBrief constraint. The claim is invalid *within this declared frame*. | `constraint_ref` resolving to a declared constraint of the cited program (or brief); `evidence_refs` ⊆ record evidence | `REJECT_BRANCH`, `REVIEW_DOWNSTREAM_IMPACT` |
| `IMPLEMENTATION_FAILURE` | The underlying claim may remain viable; the **tested mechanism failed**: failed BacktestResult/Replication/leakage Validation, `EXPLORATORY_DRIFT` (spec drift, §11.1), a validity bug in the pipeline (§10.2). | `failed_mechanism_ref` resolving to a **prediction/observable** of the program (mechanism level, never claim level); `evidence_refs` ⊆ record evidence | `PROPOSE_MECHANISM_SUBSTITUTION` |
| `ENVIRONMENT_MISMATCH` | The mechanism is not contradicted *simpliciter*; it fails in the tested **regime** and may hold in another declared regime (ICSS-v1 axis; `regime` context dimension, claims.py). | `regime_ref` resolving to a declared regime; `evidence_refs` ⊆ record evidence | `PROPOSE_SCOPE_NARROWING` |
| `RESOURCE_CONSTRAINT` | The evidence primarily demonstrates a **measured resource deficit** (compute/data/budget), not a scientific contradiction. | structured `resource_gap` with `observed < required` (numeric); `evidence_refs` ⊆ record evidence | `PARK_FOR_RESOURCE_REVIEW` |
| `FRAMING_ERROR` | The problem definition/question itself is wrong or malformed — the fault is in the **ScopeBrief**, not the mechanism. | `scope_brief_ref` + `scope_brief_field` resolving to a field of the frozen brief; `evidence_refs` ⊆ record evidence | `ROUTE_TO_SCOPE_REVIEW` |
| `UNKNOWN` | The evidence does not permit an honest single classification. | (none beyond schema; evidence refs optional) | `ESCALATE_TO_DIRECTOR` |

**Mutual exclusivity model (§12):** exactly-one `failure_class` (the primary) + optional `contributing_factors` (same enum, validated, disjoint from primary). `UNKNOWN` is first-class. `MULTI_FACTOR` is deliberately **not** a class — a catch-all class would hide the primary and break the deterministic action map; a multi-factor failure is a primary + contributors. Rationale: action routing keys on the primary; epistemic honesty is preserved by contributors and by `UNKNOWN`.

**Why the rename:** "axiom" has no Hermes carrier. The citation target is a *declared constraint*. The class semantics (claim conflicts with a declared invariant; consequence = reject / preserve history) are unchanged; the name now says what the citation must be.

## 6. Proposed data model (smallest extension — no new artifact family)

Two typed frozen dataclasses (the `claims.py`/`programs.py` pattern) + one result:

```python
@dataclass(frozen=True, slots=True)
class FalsificationRecord:          # the record being classified — the shape the future
    project_id: str                 # REFUTED write path will persist (substrate defines it now)
    hypothesis_ref: str             # the refuted claim (program hypothesis ref / claim id)
    program_ref: str                # the ResearchProgram id the hypothesis belongs to
    falsifying_evidence_refs: tuple[str, ...]   # the falsifying evidence artifacts

@dataclass(frozen=True, slots=True)
class FailureClassificationDraft:   # LLM-proposed; the validator decides
    fai
    evidence_refs: tuple[str, ...]  # citations — must be ⊆ record.falsifying_evidence_refs
    contributing_factors: tuple[str, ...] = ()
    constraint_ref: str | None = None      # DECLARED_CONSTRAINT_VIOLATION
    failed_mechanism_ref: str | None = None # IMPLEMENTATION_FAILURE (a prediction/observable ref)
    regime_ref: str | None = None          # ENVIRONMENT_MISMATCH
    resource_gap: ResourceGap | None = None # RESOURCE_CONSTRAINT (observed < required)
    scope_brief_ref: str | None = None     # FRAMING_ERROR
    scope_brief_field: str | None = None   # FRAMING_ERROR
    proposed_by: str = ""            # advisory provenance (AgentProfile value)
    classifier_version: str          # REQUIRED — part of identity (see §14)
```

```python
@dataclass(frozen=True, slots=True)
class FailureClassification:        # ADMITTED output — advisory, never a decision
    classification_id: str          # "fc_" + sha256(canonical content)[:24]
    schema_version: str             # FAILURE_CLASS_SCHEMA_VERSION
    classifier_version: str
    project_id: str
    hypothesis_ref: str
    program_ref: str
    failure_class: FailureClass
    contributing_factors: tuple[FailureClass, ...]
    evidence_refs: tuple[str, ...]
    constraint_ref / failed_mechanism_ref / regime_ref / resource_gap /
    scope_brief_ref / scope_brief_field   # the validated citations
    explanation: str
    proposed_by: str
    permitted_actions: tuple[str, ...]    # deterministic lookup result
    requires_human_confirmation: bool     # True iff failure_class == FRAMING_ERROR
    content_hash: str
```

**Persistence statement (not built):** when the Evidence Ladder lands (P2), the classification attaches to the REFUTED record as a metadata field (`failure_class`, `classifier_version`, `classification_id`) with `provenance_edges` citation edges to the falsifying evidence — the framework's "existing record + field" target, made possible because the substrate defines the exact field shape now. No new artifact family (`FailureAnalysis`/`FailureModeArtifact`/`HypothesisFailureObject`/`FailureState` are rejected — see §16).

## 7. Deterministic action mapping (the only mapping; never executed)

Hermes-native **proposal categories** (the vocabulary does not contain creation/mutation actions — those remain exclusively on the existing gateway paths):

| Action | Meaning (Hermes-native route) |
|---|---|
| `REJECT_BRANCH` | May propose branch termination via the existing `ABANDON` intent / `EVIDENCE_TRANSITION` (REFUTED finalization) — human-gated for pre-registered hypotheses (v6 §9.2) |
| `REVIEW_DOWNSTREAM_IMPACT` | May propose a downstream-impact check over existing `provenance_edges` (Q-04 surface, future) |
| `PROPOSE_MECHANISM_SUBSTITUTION` | May propose a patched candidate — through the existing Director `PROPOSE_RESEARCH_PROGRAM` path (new program version). **Never auto-created.** |
| `PROPOSE_SCOPE_NARROWING` | May propose a scope/regime edit — a new ScopeBrief version (S16 amendment, human/Director) |
| `PARK_FOR_RESOURCE_REVIEW` | No automatic action. May propose re-evaluation only if resources materially change. Director review. (No "park" state exists; this is a proposal category, not a state.) |
| `ROUTE_TO_SCOPE_REVIEW` | May route the framing question to ScopeBrief revision authority (S16; human). **No agent rewrites scope.** |
| `ESCALATE_TO_DIRECTOR` | May propose Director review only. |

Mapping (deterministic lookup, `failure_class → frozenset[action]`):

```
DECLARED_CONSTRAINT_VIOLATION → {REJECT_BRANCH, REVIEW_DOWNSTREAM_IMPACT}
IMPLEMENTATION_FAILURE        → {PROPOSE_MECHANISM_SUBSTITUTION}
ENVIRONMENT_MISMATCH          → {PROPOSE_SCOPE_NARROWING}
RESOURCE_CONSTRAINT           → {PARK_FOR_RESOURCE_REVIEW}
FRAMING_ERROR                 → {ROUTE_TO_SCOPE_REVIEW}
UNKNOWN                       → {ESCALATE_TO_DIRECTOR}
```

Rules: the set is the **closed** permission. Anything not in it is prohibited. No class ever yields creation/task/budget/scope-mutation actions. The mapping **computes** the permitted set; it never executes it. Proposing a substitution still requires the Director + gateway; retracting a branch still requires the existing authority; narrowing scope still requires the S16 human amendment path.

## 8. Authority boundary

MAY (all within this substrate): propose a class; cite evidence/constraint/mechanism/regime/resource-gap/scope-field; deterministically validate citations; deterministically map to the permitted-action set; derive `requires_human_confirmation` (FRAMING_ERROR); surface the result for review.

MUST NOT (structural, enforced by construction — no code path exists): create a hypothesis; create a program; create a task; retract a branch; revise ScopeBrief; change ladder/evidence state; bypass a gate; alter budgets; change scheduler priority; override the Director; bypass the Intent Gateway. The substrate has no SQL, no repository imports, no gateway imports, no event writes, no filesystem/network access. An ADMITTED classification is advisory metadata; every downstream action still passes the existing authorized pathway (or is simply a proposal category).

## 9. Model boundary

**LLM/model-assisted:** propose `failure_class`, `explanation`, `evidence_refs`, the class-specific citations (`constraint_ref`, `failed_mechanism_ref`, `regime_ref`, `resource_gap`, `scope_brief_ref/field`), `contributing_factors`, `proposed_by`, `classifier_version`.

**Deterministic (code, final):** closed enum values; schema/types; required-citation-per-class; citation resolution (injected resolvers, project-scoped); `evidence_refs ⊆ record.falsifying_evidence_refs`; `resource_gap.observed < required`; contributing-factor disjointness; the action map; permission checks (`requires_human_confirmation`); identity (`classification_id`) and versioning; serialization; replay determinism.

The LLM is never the authority on whether a permitted action occurs — this substrate doesn't even *take* an action; it emits proposal categories.

## 10. Provenance

Every ADMITTED classification carries, in order: `project_id` → `hypothesis_ref` → `program_ref` → the falsifying `evidence_refs` (must be a non-empty subset of the record's evidence) → class-specific citation (`constraint_ref` / `failed_mechanism_ref` / `regime_ref` / `resource_gap` / `scope_brief_ref+field`). Each citation is **validated to resolve** (injected resolver; a missing resolver for a required citation is fail-closed, mirroring `thesis.py`'s `NONE_FOUND_UNDEREFERENCEABLE`). `proposed_by` + `classifier_version` are advisory provenance. Reuses the repository's `artifact_type:ref` citation form; reuses the `provenance_edges` mechanism at persistence time (not built). No redundant provenance mechanism is introduced.

## 11. Determinism

- Pure function: no clock, no random, no SQL, no IO. Same (record, draft, resolver-behavior) ⇒ identical structured output.
- `canonical_json` + `sha256_hex` reused from `programs.py` (single derivation, never two).
- `classification_id` = `fc_` + sha256(canonical content incl. `schema_version` + `classifier_version`)[:24] — replay-stable and **version-bound** (see §14).
- Identity never authored by the caller.

## 12. Security

No credentials, no network, no filesystem, no process boundary. The only external surface is the injected resolver protocol; resolvers are project-scoped and supplied by the write path (substrate fixtures use stubs). Fail-closed: any missing required citation, unresolvable ref, unknown enum value, or type violation ⇒ REJECTED with structured errors.

## 13. Phase

P2-adjacent substrate, Phase-1 of the Q-sequence. Manual-proof-first (v6 §29.2 rule 7): pure validator + golden fixtures now; persistence when the Evidence Ladder lands. **Roadmap correction (IDR-036/037, 2026-08-15):** the Evidence Ladder remains deferred, but Q-05 advisory persistence was implemented EARLY through the existing artifact store as preparatory infrastructure (`hermes_q05_persistence_slice_design.md`, IDR-037) — the architecture is not structurally expanded (no new tables/authorities), but the implementation SEQUENCE changed; recorded honestly. Governance: IMPLEMENTED + TESTED, **RATIFIED / CLOSED** (2026-08-15 — the operator accepted the §10 adversarial audit as the Q-05 closure gate; reviewer provenance: implementation agent at operator instruction, not a claim of external independence).

## 14. Failure-class versioning

The taxonomy is versioned: `FAILURE_CLASS_SCHEMA_VERSION = "1"` (the enum + action map) and `classifier_version` (required on every draft — the classifier/mapping policy version, like `compiler_version` on `ResearchProgramDraft`). Both enter the content identity. Consequences:

- Same falsification record + new `classifier_version` ⇒ a **new** derived classification (new `classification_id`), coexisting with the historical one. Historical truth is never mutated — Hermes' supersession convention (`supersedes_ref`, content-addressed immutable artifacts) applies to *new* records, and the substrate supports it by identity, not by rewriting.
- Replay after a changed classifier version is a deterministic new derivation, never an in-place edit (attacks §14.12).

## 15. Acceptance tests (golden fixtures)

Designed before implementation; implemented in `tests/test_failure_classification.py`:

- **A. DECLARED_CONSTRAINT_VIOLATION:** (A1) valid constraint citation → ADMITTED, actions = {REJECT_BRANCH, REVIEW_DOWNSTREAM_IMPACT}; (A2) missing constraint citation → REJECTED; (A3) citation points at an unresolvable constraint → REJECTED.
- **B. IMPLEMENTATION_FAILURE:** (B1) mechanism-level citation (failed_mechanism_ref = a prediction in the program) → ADMITTED, actions = {PROPOSE_MECHANISM_SUBSTITUTION}; (B2) evidence contradicts only the top-level claim (no mechanism ref) → REJECTED.
- **C. ENVIRONMENT_MISMATCH:** (C1) regime ref resolves → ADMITTED, actions = {PROPOSE_SCOPE_NARROWING}; (C2) no regime ref → REJECTED.
- **D. RESOURCE_CONSTRAINT:** (D1) measurable deficit (observed < required) + evidence → ADMITTED, actions = {PARK_FOR_RESOURCE_REVIEW}; (D2) action set contains no retry/budget-expansion action (asserted exactly); (D3) observed >= required → REJECTED.
- **E. FRAMING_ERROR:** (E1) brief ref + field resolve → ADMITTED, actions = {ROUTE_TO_SCOPE_REVIEW}, requires_human_confirmation=True; (E2) missing brief/field → REJECTED; (E3) no silent scope mutation — the module exposes no write surface (structural assertion on the API).
- **F. Authority attacks (fail closed):** classification cannot create hypothesis/task, change ladder state, bypass gateway, or mutate scope — structural assertions + per-attack fixture.
- **G. Replay:** identical inputs ⇒ identical output (deep-equal + identical classification_id).
- **H. Provenance:** every ADMITTED classification's refs trace to the record's evidence and the class-required citation; the stub resolvers are project-scoped.

## 16. Rejected alternatives

1. **New artifact family** (`FailureAnalysis`, `FailureModeArtifact`, `HypothesisFailureObject`, `FailureState`): rejected — the repository proves the concept fits a validator result; no persistence exists to attach to, and a new artifact family would need a table + write path + authority surface, all forbidden by the manual-proof-first rule.
2. **Persisted field on `thesis_evidence`:** rejected — thesis tables are literature verdicts (gate inputs), not falsification records; nothing reads them yet.
3. **Extending `evidence.py` / implementing the REFUTED transition:** rejected — that is the Evidence Ladder (P2 roadmap), explicitly out of scope; Q-05 must not duplicate or pre-empt it.
4. **New intent kind (`CLASSIFY_FAILURE`):** rejected — the gateway wires three kinds; a new intent would be a new mutation path and would make the LLM a proposer of state changes. The classification is advisory substrate, not an intent.
5. **Persisting now (new `failure_classifications` table):** rejected — no write path exists to bind it to (no evidence table), and IDR precedent (CONTRA P7) requires substrate-first.
6. **`MULTI_FACTOR` as a class:** rejected — hides the primary; breaks deterministic action routing. Primary + contributors + UNKNOWN is the smallest honest model.
7. **Keeping `HARD_AXIOM_VIOLATION`:** rejected — "axiom" has no Hermes carrier; the citation would be undefined. Renamed to `DECLARED_CONSTRAINT_VIOLATION`.
8. **Classification with no citation discipline (free-form "why" text):** rejected — the framework's own acceptance tests demand a required-citation rule; a naked label is exactly the "no provenance" failure mode.

## 17. Unresolved questions (recorded, non-blocking)

1. **Where the classification is *consumed*:** the reconcile loop and the controller are the future consumers; consumption design waits for the Evidence Ladder write path (P2). The action categories are proposal categories precisely so consumption can route them without new intents.
2. **`contributing_factors` citation discipline:** contributors are validated for enum membership/disjointness but do not carry per-factor citations. If the ladder write path later needs per-factor provenance, extend the draft — the identity includes them, so old records remain stable.
3. **Staleness enforcement:** "stale classification against superseded evidence" is resolved at the substrate by the injected resolver (the write path's resolver checks head-status) and by identity (a reclassification under new evidence/version is a new record). A dedicated `supersedes_ref` chain for classifications awaits the persistence slice.
4. **FRAMING_ERROR proposer restriction:** the substrate derives `requires_human_confirmation=True` but does not itself reject a non-Director proposer — the Director-confirmation rule is enforced by whoever consumes the classification (future), matching the framework's "confirmed by Director" semantics without inventing authority in the substrate.

---

## 18. Design gate — hostile self-review (run before implementation)

> **Is Q-05 a real Hermes gap after inspecting the current repository?**
> YES (reconciliation §8): no failure taxonomy, no action mapping, no falsification record — and the ladder terminus is unimplemented. The corrected premise (substrate-first, record shape defined now) is repo-consistent.

> **Could this classification mechanism accidentally become a second epistemic authority?**
> No. Pure function; no state, no persistence, no write path, no imports of repositories/gateway/events. It cannot transition, promote, create, or retract anything. An ADMITTED result is advisory metadata; the action set is a *permission* computation, not a decision.

> **Could it create a silent pivot?**
> No. The action vocabulary contains no creation/mutation actions (`PROPOSE_MECHANISM_SUBSTITUTION` is a *proposal category* routed through the existing Director path; nothing in the module calls `apply_intent`). Attack tests F1/F2/F5 assert this structurally.

> **Could it mutate ScopeBrief?**
> No. No SQL/IO/write surface exists. FRAMING_ERROR is explicitly limited to `ROUTE_TO_SCOPE_REVIEW` and derives `requires_human_confirmation=True`. Tests E3/F6 assert the module exposes no mutation capability.

> **Could it create a parallel state machine?**
> No. The taxonomy is a classification vocabulary over a falsification record; it has no states, no transitions, no lifecycle. The record it consumes is the future REFUTED write path's shape — the substrate is upstream of, and subordinate to, the ladder.

> **Could an LLM-produced classification bypass deterministic validation?**
> No. Every draft field is type/enum/schema-checked; every citation must resolve (project-scoped resolvers, fail-closed when missing); `evidence_refs` must be a subset of the record's falsifying evidence; `resource_gap` must satisfy observed < required; identity is derived, never authored.

> **Could historical falsification records be rewritten?**
> No. The substrate writes nothing. Versioning (§14) makes reclassification a new derived record; identity binds every classification to its (schema, classifier, content).

**GATE RESULT: PASSED — no remediation required before implementation.**

---

## 19. Implementation notes (appended after implementation)

- **Module:** `src/hermes/research/failure_classification.py` (new — a sibling of `claims.py`/`thesis.py`/`programs.py`; the Evidence Ladder placeholder `evidence.py` is untouched).
- **Tests:** `tests/test_failure_classification.py` — fixtures A–H + the §14 adversarial-attack matrix.
- **Wiring:** none — no migration, no new tables/events/intents, no gateway/controller changes. The module is importable substrate only.
- **Baseline vs result:** 892 passed / pyright 0 errors before; final suite + pyright numbers recorded in the implementation report.

### 19.1 Implementation record (post-implementation, verified)

- **Module:** `src/hermes/research/failure_classification.py` (818 lines) — pure substrate; imports ONLY `math`, `dataclasses`, `enum`, `typing`, and `canonical_json`/`sha256_hex` from `hermes.research.programs`. No cycle (programs.py does not import it), no repository/gateway/event/evidence imports, no SQL, no IO, no clock.
- **Tests:** `tests/test_failure_classification.py` — **41 golden fixtures** (A–H acceptance matrix + the 12-attack adversarial matrix + UNKNOWN/human-confirmation/summarizer/versioning edge cases), all green.
- **Wiring:** none by design — no migration, no tables, no events, no intents, no gateway/controller changes (manual-proof-first, v6 §29.2 rule 7). The classification attaches to the future REFUTED write path as a metadata field + `provenance_edges` citation edges.
- **Final numbers:**
  - Full suite: **933 passed, 0 failed, 0 errors** (was 892 at baseline; +41 Q-05) — 9.18s runtime, exit code 0.
  - Targeted Q-05 suite: 41 passed.
  - pyright (`uvx pyright src`): **0 errors, 0 warnings, 0 informations**.
  - Baseline HEAD: `2d6d851`. No tracked files modified; new files: module, test file, and the two required documents (this one + the reconciliation).
- **Ix (§22):** the ix backend was not reachable (`ix docker start` required — not run, heavy side effect); the structural comparison was performed manually and is recorded below.

### 19.2 Structural comparison vs. the pre-Q05 baseline (§22)

| Check | Result |
|---|---|
| New scheduler? | NO — no scheduling vocabulary, no task-status logic, no `ADMIT_TASK` |
| New write path? | NO — no SQL/repository/gateway/event imports (asserted by test F1 token scan + AST import audit) |
| New state machine? | NO — the taxonomy is a classification vocabulary; no states/transitions/lifecycle |
| Unexpected dependency cycle? | NO — imports only stdlib + `programs.py` (one-directional) |
| New authority component? | NO — pure function; result is advisory metadata |
| Direct ScopeBrief mutation? | NO — no scope table access; FRAMING_ERROR → {ROUTE_TO_SCOPE_REVIEW} + requires_human_confirmation |
| Evidence-promotion path? | NO — no ladder vocabulary, no promotion logic |
| Alternate task-creation path? | NO — no task/intent vocabulary |

### 19.3 Post-implementation hostile audit (§23) — verdict

The audit probes (forged class/constraint/scope-field, no-evidence, auto-replacement, scope rewrite, budget bypass, class-mismatch, cross-project, stale evidence, duplicate, classifier-version replay, ordering idempotency, int/float gaps, empty-string citations, resolver-free UNKNOWN) all **fail closed deterministically**. The module improves Hermes' ability to learn from falsification (structured, versioned, provenance-bearing WHY + permitted-proposal categories) without becoming a second decision authority: it holds no state, executes nothing, and every downstream action still requires the existing authorized pathway.

**Final status: READY FOR INDEPENDENT REVIEW** — then **RATIFIED by the operator (2026-08-15) as IDR-036**: the six-class taxonomy and the deterministic action map are now architecture future phases consume (the independent review remains standing; IDR-036 records that it does not substitute for it).

### 19.4 Independent adversarial review (2026-08-15) — closure verdict

Fresh-eyes audit of the FULL Q-05 package (substrate + persistence slice + controller consumption),
reading the code, not the docs. Result: **2 findings, both remediated, regression-tested, re-verified.**

| # | Severity | Finding | Fix | Verified |
|---|---|---|---|---|
| F1 | HIGH | The CONTRA/claims write path's generic artifact dereference (`_dereference_artifact_ref`) form-checked deferred types, so a `ResearchClaim` could nominally cite `failure_classification:<hash>` as its `source_ref` — a D8 advisory-boundary leak (classification as evidence/source). | Fix A: `_dereference_artifact_ref` now returns `False` for `artifact_type == "failure_classification"`; the write path refuses with "must dereference". | `test_claim_cannot_cite_classification_as_source`; original attack re-run → refused |
| F2 | MEDIUM | The read-only digest trusted the row's stored `permitted_actions` metadata; a tampered row could surface actions the ratified taxonomy does not permit. | Fix B: `classifications_digest` recomputes `permitted_actions` from the ratified `ACTION_MAP` via `permitted_actions_for`; corrupt `failure_class` rows are skipped, never fail open. | `test_digest_recomputes_permitted_actions` (tampered REJECT_BRANCH → ESCALATE_TO_DIRECTOR) |

Six-question authority audit: no new scheduler, no new write path, no new state machine, no
dependency cycle, no new authority component, no ScopeBrief mutation; Fix A closes an
evidence-promotion path; no alternate task-creation path.

Verification: full suite **971 passed** (0 failed, 9.41s; 892 baseline + 79 Q-05), pyright
**0 errors / 0 warnings**. Source delta for remediation: +23 lines in 2 files (+2 regression tests).

**Closure verdict: READY FOR INDEPENDENT REVIEW.** The review does not substitute for or close
the standing independent review; Q-02/Q-04/Q-07/Q-09/CV-01 remain unstarted. Not committed
(workflow).
