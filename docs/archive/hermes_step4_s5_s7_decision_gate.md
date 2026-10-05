# HERMES STEP 4 — S5/S7 Architectural & Implementation Decision Gate

**Status:** DECISION GATE COMPLETE — verdict recorded in §9.
**HEAD:** `872d04b` (branch `step-4`, fast-forwarded from `main`; C1 Step-3 adversarial closure + write-path fix included).
**Verification gates executed live:** 1667 passed (0 failed), pyright 0 errors (1 known baseline warning), ruff clean.
**Governance authority:** `hermes_architecture_ratification.md` §8 Step 4; `hermes_c1_step3_adversarial_closure.md` §22.

---

## 1. Purpose and Scope

This document is the Step 4 deliverable: the S5/S7 architectural and
implementation decision gate. It determines whether S5 (invalidation
cascade) and S7 (refuted-registry / resurrection screen) are
architecturally complete enough to implement, how they compose with C1,
what must precede P4, and what remains deferred.

**This is a decision gate, not an implementation.** No production code
is modified. No new architecture is created. The ratified contracts are
evaluated against the live source to produce an implementation-readiness
verdict.

---

## 2. Live Repository State (verified at HEAD `872d04b`)

| Check | Result |
|---|---|
| Branch | `step-4` (fast-forwarded from `main` @ `872d04b`) |
| Working tree | clean |
| Origin sync | `origin/main` = `2b0f52b` at gate time — 2 commits unpushed (`cb1f8e1`, `872d04b`); pushed with the Step 4 deliverable |
| C1 closure doc | present (`hermes_c1_step3_adversarial_closure.md`) |
| C1 write-path fix | present (`cb1f8e1`) |
| Suite | 1667 passed, 0 failed |
| pyright | 0 errors, 1 warning (baseline `test_research_program.py:141`) |
| ruff | All checks passed |

---

## 3. Authority Map

| Document | Authority | S5 relevance | S7 relevance |
|---|---|---|---|
| `hermes_architecture_ratification.md` | **RATIFIED** (operator, 2026-08-20) | §6.3 defers S5; §7 sunset; §8 Step 4 charter | §6.3 defers S7; §7 sunset; §8 Step 4 charter |
| `hermes_research_architecture_v6.md` | **RATIFIED** (IDR-023, reaffirmed) | §7/S5 full cascade design; §14 edge classes; §8 reconcile loop | §10.2/S7 advisory design; §16.6 curated registry |
| `hermes_five_fundamentals_blueprint.md` | **RATIFIED** (with corrections) | §3.4 preservation rule; §27 T1 finding | §4.6 resurrection; §27 T4 finding; §19 Q14 |
| `hermes_c1_slot_ref_design_gate.md` | **RATIFIED** (Decision 2) | — | §5.4 deferred consumer; §4.6 exclusions |
| `hermes_c1_step3_adversarial_closure.md` | **RATIFIED** (closure record) | — | §15 S7 compatibility PASS |
| `docs/idr/IDR-017.md` | **RATIFIED** (Phase 1 decision) | Non-cascade contract; cascade deferred to reconcile loop | — |
| `docs/idr/IDR-041.md` | **RATIFIED** (APPLY + handoff) | — | REFUTED terminality; resurrection = new hypothesis |
| `hermes_q04_failure_propagation_design_gate.md` | **DESIGN** (not ratified) | §3 cone derivations (implemented in `graph.py`) | — |
| `hermes_final_ratification_gate.md` | **RATIFIED** (gate record) | §10 S5 assessment; §17 Step 5 | §10 S7 assessment; §17 Step 5 |

**Conflict resolution rule:** RATIFIED > DESIGN > DEFERRED > EXPERIMENTAL
(ratification record §12). Where a DESIGN document conflicts with a
RATIFIED contract, the RATIFIED contract prevails.

---

## 4. S5 — Invalidation Cascade: Contract Reconstruction

### 4.1 What S5 means in Hermes

S5 is the **supersede-and-invalidate cascade**: when a source is
retracted (human-initiated), every downstream research object that
*depends on* that source is marked `INVALIDATED`. The cascade is:

- **NOT recursive deletion** — nothing is ever deleted (§16.1 preserved).
- **NOT a mutation** — it is a lifecycle transition on downstream objects.
- **NOT an observation** — it is an authoritative state transition
  (INVALIDATED is a terminal task status; `task_status.py:94`).
- **A dependency-propagation** — it walks dependency-class edges only.

### 4.2 The v6 design (RATIFIED, §7/S5)

The full cascade is a 5-step deterministic sequence:

1. Emit `SourceRetracted` event (catalog member, already exists).
2. Write a new `Validation`(FAIL)/`Critique`/`ResearchDecision` artifact
   with a `supersedes` edge to the source.
3. Mark every downstream artifact reachable via dependency-class edges
   (`supports`, `cites`, `entails`, `derived_from`, `used_as_input`)
   `INVALIDATED` (archived, never deleted).
4. Add the source to the inadmissible-source screen (§16.6).
5. Regenerate the derived vault projection (§21 single writer).

**Trigger:** `RETRACT_SOURCE {source_ref, reason, human_decision_ref}` —
human-initiated, gateway-validated, requires cited reason + recorded
`HumanDecision`.

**Edge-class constraint (R1):** the cascade walks dependency-class edges
ONLY. A `contradicts` edge NEVER triggers invalidation (retracting a
contradicting source removes counter-evidence; the claim's
`open_contradictions` is re-evaluated but the claim is never invalidated
by it).

### 4.3 Invalidation targets (live source audit)

| Object | Can become invalid? | Cause | Resulting state | Reversible? |
|---|---|---|---|---|
| Task (SUCCEEDED) | YES | `invalidate()` single-task | `INVALIDATED` (terminal) | NO (`task_status.py:94`) |
| Task (non-SUCCEEDED) | NO | — | — | — |
| Artifact | YES (designed) | S5 cascade step 3 | `INVALIDATED` marker | NO (archived) |
| Evidence ladder rung | NO | — | REFUTED is terminal; no invalidation path | — |
| Research program | NO | — | SUPERSEDED (head-advance); no invalidation | — |
| Claim | NO (designed as flag) | S5 cascade marks downstream | flagged, not deleted | — |

### 4.4 Authority boundary (who triggers invalidation)

| Candidate | May trigger? | Evidence |
|---|---|---|
| Operator (human) | **YES** — the ONLY trigger | v6 §7/S5: "human-initiated per §9.2 override discipline" |
| Controller | Executes the cascade (deterministic) | v6 §7/S5: "controller-computed, deterministic" |
| Reconcile loop | Triggers the controller pass | IDR-017: "reconcile loop … would compute cascade" |
| Research agent | NO | Never triggers invalidation |
| Evidence admission | NO | Ladder transitions only |
| Refutation (REFUTED) | NO — separate path | IDR-041: REFUTED is ladder-terminal, not invalidation |
| Mutation gateway | Validates the intent | Single-gateway invariant preserved |

**S5 does NOT create a new mutation path.** `RETRACT_SOURCE` is a new
`IntentKind` admitted through the existing `apply_intent` gateway —
the single authoritative mutation path is preserved. The cascade is a
deterministic controller computation triggered by the admitted intent,
not a second write path.

### 4.5 Cascade dependency graph (live substrate)

```text
Source artifact (retracted)
   | provenance_edges (cites, derived_from, used_as_input)
   v
Downstream artifacts
   | task_dependencies (scheduling layer)
   v
Downstream tasks -> INVALIDATED
   | program supersession chain
   v
Program versions (NOT invalidated -- superseded versions are historical)
```

**Live edge vocabulary** (`migrations.py:260-262`):
`cites`, `derived_from`, `supersedes`, `used_as_input`, `justifies`.

**v6 dependency-class** (§14/GR3): `supports`, `cites`, `entails`,
`derived_from`, `used_as_input`.

**Gap:** `supports` and `entails` are GR3 additions (DEFERRED, v6 §28.5).
The live schema carries 3 of the 5 dependency-class edge types. The
cascade can walk the existing 3 types; the remaining 2 land with GR3.

### 4.6 Existing substrate (implemented, verified)

| Component | Location | Status |
|---|---|---|
| `invalidate()` single-task | `repositories.py:626` | IMPLEMENTED, 0 production callers |
| `SourceRetracted` event | `events.py:73` | IMPLEMENTED (enum member) |
| Auto-emit on retraction fetch | `source_outcomes.py:735-764` | IMPLEMENTED |
| `record_source_retraction()` | `controller.py:786` | IMPLEMENTED |
| `retracted_source_review_candidates()` | `controller.py:823` | IMPLEMENTED (digest) |
| `failure_cone()` | `graph.py:157` | IMPLEMENTED (Q-04 pure derivation) |
| `artifact_blast_radius()` | `graph.py:276` | IMPLEMENTED (Q-04 pure derivation) |
| `change_blast_radius()` | `graph.py:240` | IMPLEMENTED (Q-04 pure derivation) |
| `reconcile.py` | 6-line placeholder | NOT IMPLEMENTED |
| `RETRACT_SOURCE` intent | — | NOT IMPLEMENTED |
| Recursive CTE / cascade traversal | — | NOT IMPLEMENTED |
| Inadmissible-source screen | — | NOT IMPLEMENTED (requires §16.6 store) |
| Vault projection regeneration | — | NOT IMPLEMENTED (requires §21 renderer) |

---

## 5. S7 — Refuted-Registry / Resurrection Screen: Contract Reconstruction

### 5.1 What S7 means in Hermes

S7 is the **near-miss refuted-registry advisory**: when a new hypothesis
is proposed, the controller computes signature similarity against the
**curated refuted registry** and surfaces a `NearMissRefutation` advisory.
S7 is:

- **Advisory only** — never blocking, never a gate input (v6 §10.2/S7).
- **NOT an admission authority** — it never admits, rejects, or
  transitions anything by itself (C1 gate §4.6).
- **NOT a resurrection authority** — resurrection is always a NEW
  hypothesis with new content identity (IDR-041 terminality).
- **A screening surface** — it surfaces prior-refutation context to the
  human gate so the operator can judge "same concept, new conditions"
  vs "identical re-attempt".

### 5.2 The v6 design (RATIFIED, §10.2/S7)

On hypothesis proposal, the controller computes signature similarity
against the curated refuted registry using the screen axes:

- **instrument** (the measurement/execution instrument)
- **feature-binding signature** (the feature set the hypothesis binds)
- **strategy family** (the claim-type / approach family)
- **[PA6] reward_hack_family** (metric-gaming, gate-bypass,
  environment-exploit, evidence-fabrication)

Output: `NearMissRefutation {hypothesis_ref, matched_refuted_ids,
similarity_axes}` — surfaced to the `DIRECTOR_REVIEW` proposal and the
§9.1 gate pack. Never blocking.

**Curation invariant (§16.6):** the screen queries the curated registry
only, never archived project data. Nothing auto-promotes from one
project's research memory into long-term knowledge.

### 5.3 The C1 slot_ref axis (RATIFIED, deferred consumer)

C1 adds a `slot_ref` axis to the S7 screen (design gate §5.4):

- A resurrection candidate's slot is compared against its predecessor's.
- **Equal slot + distinct content lineage** = recognizable resurrection
  attempt (legitimate re-exploration under changed conditions).
- **Equal content-hash lineage** = NOT a resurrection (IDR-041
  terminality — identical content is a re-attempt, not new research).
- Advisory, human-gated.

This consumer is **designed but NOT implementable until S7 exists** —
it is a deferred consumer of the S7 screen, recorded in the C1 gate §5.4
and reaffirmed in the closure doc §15.

### 5.4 Resurrection semantics (RATIFIED, IDR-041 + blueprint §4.6)

Resurrection is governed by the REFUTED-terminal model:

- The original REFUTED record is **never reverted** — it remains a
  permanent registry asset with its condition citations.
- Resurrection is a **new hypothesis** (new content identity) that:
  1. cites the original REFUTED record via provenance,
  2. declares the **changed condition** (new regime / new constraint
     resolution) as part of its falsification frame,
  3. passes the refuted-registry screen (the S7 advisory).
- The screen distinguishes "same concept, new conditions" (legitimate)
  from "same content-hash lineage" (not a resurrection).

### 5.5 Existing substrate (implemented, verified)

| Component | Location | Status |
|---|---|---|
| REFUTED terminal rung | `migrations.py:682-697` (CHECK) | IMPLEMENTED |
| REFUTED never-reverted (AC-3) | `evidence_ladder.py` (IDR-041) | IMPLEMENTED |
| `RefutedApplied` event | `events.py:57` | IMPLEMENTED |
| `bare_classification_falsifications()` | `controller.py` (digest) | IMPLEMENTED |
| `refutation_review_candidates()` | `controller.py` (digest) | IMPLEMENTED |
| Completion refutation guard (HR-08) | `completion.py:177-254` | IMPLEMENTED |
| `slot_vocabulary()` (C1) | `repositories.py:1668` | IMPLEMENTED |
| Curated refuted registry (§16.6 store) | — | NOT IMPLEMENTED |
| Near-miss similarity computation | — | NOT IMPLEMENTED |
| `NearMissRefutation` advisory | — | NOT IMPLEMENTED |
| Screen axes (instrument/feature/family) | — | NOT IMPLEMENTED |
| FeatureBinding signature | — | NOT IMPLEMENTED (no `FeatureBinding` in src/) |

### 5.6 The critical S7 substrate gap

The v6 S7 design screens against the **curated refuted registry** — a
long-term-knowledge store (§16.6) that does not exist in `src/`. The
screen axes reference `FeatureBinding` signatures, which also do not
exist in `src/` (verified: 0 matches for `FeatureBinding`/
`feature_binding`).

This means S7 is **not implementable against the current substrate**
without first building:

1. The long-term-knowledge store (§16.6) — the curated registry itself.
2. The `FeatureBinding` artifact type (v6 §10.1) — the signature carrier.
3. The curation-invariant admission path (how a REFUTED hypothesis
   enters the curated registry from a project's research memory).

These are **prerequisite substrates**, not S7 itself. They are part of
the v6 P2 slice (§28.5) and are DEFERRED.

---

## 6. Composition Analysis: S5/S7 with C1 and the Single-Gateway Invariant

### 6.1 S5 composes cleanly with the ratified architecture

- `RETRACT_SOURCE` is a new `IntentKind` → admitted through `apply_intent`
  (single-gateway invariant preserved).
- The cascade is a deterministic controller computation → no second
  write path.
- `SourceRetracted` already exists in the event catalog → no new event
  type needed for step 1.
- `invalidate()` already exists (single-task) → the cascade extends it
  to downstream dependents via graph traversal.
- The Q-04 cone derivations (`failure_cone`, `artifact_blast_radius`,
  `change_blast_radius`) are already implemented as pure functions →
  the cascade traversal can reuse them.

**S5's composition is architecturally sound.** The missing pieces are
the reconcile loop (the cascade's home) and the §16.6/§21 substrates
(steps 4-5 of the cascade).

### 6.2 S7 composes with C1 but requires prerequisite substrates

- C1's `slot_vocabulary()` is implemented and provides the slot axis.
- The REFUTED-terminal model (IDR-041) is implemented and provides the
  resurrection semantics.
- BUT the curated registry (§16.6) and FeatureBinding signatures are
  NOT implemented — S7 cannot screen against a registry that doesn't
  exist.

**S7's composition with C1 is designed but substrate-blocked.** The
slot axis is ready; the registry it screens against is not.

### 6.3 Single-gateway invariant check

| Mechanism | New mutation path? | Evidence |
|---|---|---|
| S5 `RETRACT_SOURCE` | NO — new IntentKind through `apply_intent` | v6 §7/S5: "gateway-validated" |
| S5 cascade execution | NO — deterministic controller computation | v6 §7/S5: "controller-computed" |
| S7 near-miss screen | NO — read-only advisory, never writes | v6 §10.2/S7: "advisory only" |
| S7 registry population | Requires curation path (§16.6) | v6 §16.6: "curated import only" |

**The single-gateway invariant is preserved by both S5 and S7.** Neither
creates a second write path. S7's registry population is a curated
import (human-gated), not an agent write.

---

## 7. What Must Be Implemented Before P4

Per the ratification record §7 and the final gate §17:

| Dependency | Gates | Must precede |
|---|---|---|
| S5 invalidation cascade | Fundamental #3 preserve-and-mutate completeness; mature Q-04 (Step 10) | P4 completeness claim |
| S7 refuted-registry screen | C1 §5.4 resurrection consumer; any operational resurrection-screening claim | C1-§5.4 consumer claim |
| ModelClient record/replay | Any LLM wiring in P4 | P4 runtime (Step 6) |
| P4 agent runtime | C5/C6 activation (Steps 7-8) | C5/C6 consumption |

**S5 must land before the P4 completeness claim.** The preserve-and-mutate
loop (Fundamental #3) leans on the S5 cascade; until it lands, failure
localization is partial (blueprint §19 Q14).

**S7 must land before the C1-§5.4 resurrection consumer is claimed
operational.** Until S7 exists, the resurrection-screening consumer MUST
NOT be claimed complete (prohibited-claims discipline, ratification §6.3).

---

## 8. What Remains Explicitly Deferred

| Item | Status | Rationale |
|---|---|---|
| S5 cascade steps 4-5 (inadmissible-source screen, vault projection) | DEFERRED | Require §16.6 store + §21 renderer (P2/P3 substrates) |
| S7 curated registry (§16.6) | DEFERRED | Long-term-knowledge store is a P2 slice |
| S7 FeatureBinding signatures | DEFERRED | FeatureBinding is a v6 §10.1 artifact, not yet implemented |
| GR3 edge types (`supports`, `entails`) | DEFERRED | v6 §28.5 GR-slices; cascade walks existing 3 types until GR3 lands |
| C1 §5.4 resurrection consumer | DEFERRED | Implementable only after S7 |
| Reconcile loop (real) | DEFERRED | P4 runtime (Step 6); S5 cascade's home |

---

## 9. Verdict

### Verdict: **B — S5 READY / S7 REQUIRES FURTHER DESIGN**

This is the strongest readiness state the evidence supports. It is not
A (both ready) because S7 is substrate-blocked. It is not C/D/E because
S5's design is ratified and its core cascade is implementable against
the current substrate.

### 9.1 Why S5 is READY

S5's design is **RATIFIED** (v6 §7/S5) and fully specified:

- The trigger (`RETRACT_SOURCE`, human-initiated, gateway-validated) is
  a new `IntentKind` through the existing `apply_intent` gateway — the
  single-gateway invariant is preserved.
- The cascade is a deterministic controller computation — no second
  write path.
- The core cascade (steps 1-3) is implementable against the **current
  substrate**:
  - Step 1 (`SourceRetracted` event) — already exists (`events.py:73`).
  - Step 2 (write `Validation`/`supersedes` artifact) — `artifacts` +
    `provenance_edges` (with `supersedes` in the edge vocab) exist.
  - Step 3 (mark downstream `INVALIDATED`) — task-level invalidation
    exists (`invalidate()`, `task_status.py:94`); the Q-04 cone
    derivations (`failure_cone`, `artifact_blast_radius`) are already
    implemented as pure functions and provide the traversal.
- The edge-class constraint (R1: dependency-class edges only) is
  specified and the live schema carries 3 of the 5 dependency-class
  edge types (`cites`, `derived_from`, `used_as_input`).

**S5 is implementable as a separately-chartered step.** The
implementation must include a migration for the artifact-level
invalidation marker (the `artifacts` table has no status column today),
but that is a schema addition within the implementation step's scope,
not a change to the ratified contract.

**Deferred sub-steps (explicit):** cascade steps 4-5 (inadmissible-source
screen, vault projection regeneration) require the §16.6 store and §21
renderer, which are DEFERRED P2/P3 substrates. These are recorded as
deferred, not blockers.

**Reconcile-loop integration:** IDR-017 names the reconcile loop as the
cascade's natural home, but the cascade does NOT require the full P4
reconcile loop — it can be implemented as a controller method triggered
by the admitted `RETRACT_SOURCE` intent. The reconcile-loop integration
lands with Step 6 (P4 runtime).

### 9.2 Why S7 REQUIRES FURTHER DESIGN

S7's design is **RATIFIED** (v6 §10.2/S7) at the contract level, but it
is **substrate-blocked**:

- The screen queries the **curated refuted registry** (§16.6 long-term-
  knowledge store) — this store does **not exist** in `src/` (verified:
  0 matches for `refuted_registry`, `near_miss`, `curated`).
- The screen axes reference **`FeatureBinding` signatures** — this
  artifact type does **not exist** in `src/` (verified: 0 matches for
  `FeatureBinding`/`feature_binding`).
- The **curation-invariant admission path** (how a REFUTED hypothesis
  enters the curated registry from a project's research memory) is not
  specified at implementation detail.

These are **prerequisite substrates**, not S7 itself. They are part of
the v6 P2 slice (§28.5) and are DEFERRED. S7 cannot be implemented
against the current substrate without first building:

1. The long-term-knowledge store (§16.6).
2. The `FeatureBinding` artifact type (v6 §10.1).
3. The curation-invariant admission path.

**S7 requires further design** to specify these substrates at
implementation detail before it can be built. The C1 `slot_ref` axis is
ready (implemented), but the registry it screens against is not.

### 9.3 What this verdict authorizes

- **S5:** authorized to proceed to a separately-chartered implementation
  step (per the frozen sequence — ratification is NOT permission to
  implement; a separate charter is required).
- **S7:** NOT authorized for implementation. Requires a further design
  gate specifying the §16.6 registry substrate, the FeatureBinding
  signature carrier, and the curation-invariant admission path.
- **C1 §5.4 resurrection consumer:** remains DEFERRED until S7 lands.
  The prohibited-claims discipline holds: no operational resurrection-
  screening claim until S7 exists and is verified.

---

## 10. Decision Record

**Decision:** Verdict B recorded. S5 READY for a separately-chartered
implementation step; S7 REQUIRES FURTHER DESIGN (substrate-blocked on
§16.6 registry + FeatureBinding + curation path).

**Governance compliance:**

- No ratified contract was altered. The v6 S5/S7 designs are evaluated
  as-is against the live source.
- No production code was modified. This is a docs-only decision gate.
- No new architecture was created. The verdict records readiness, not
  design.
- The single-gateway invariant is confirmed preserved by both S5 and S7.
- The prohibited-claims discipline is reaffirmed for S7 and the C1 §5.4
  consumer.

**Sunset conditions (from ratification §7, reaffirmed):**

| Dependency | Gates | Sunset |
|---|---|---|
| S5 cascade | Fundamental #3 completeness; mature Q-04 | Before P4 completeness claim |
| S7 screen | C1 §5.4 consumer; resurrection-screening claim | Before C1-§5.4 consumer claim |

**Open items carried forward:**

1. S5 implementation charter (separately chartered step; not authorized
   by this gate).
2. S7 further-design gate (specify §16.6 registry, FeatureBinding,
   curation path).
3. GR3 edge types (`supports`, `entails`) — cascade walks existing 3
   types until GR3 lands (v6 §28.5).
4. Reconcile-loop integration of the S5 cascade (Step 6, P4 runtime).

---

## 11. Verification Evidence (executed live at HEAD `872d04b`)

| Gate | Command | Result |
|---|---|---|
| Test suite | `pytest -q` (env-scrubbed, project venv) | **1667 passed, 0 failed** |
| Type check | `uvx pyright --project pyrightconfig.tests.json` | **0 errors, 1 warning** (baseline `test_research_program.py:141`) |
| Lint | `uvx ruff check src tests` | **All checks passed** |
| Working tree | `git status` | clean |
| Origin sync | `git rev-list --left-right --count origin/main...step-4` | 0 / 2 at gate time (`cb1f8e1`, `872d04b` unpushed); all pushed with the Step 4 deliverable |

**Substrate audit (grep-verified against `src/`):**

| Substrate | Matches | Conclusion |
|---|---|---|
| `RETRACT_SOURCE` | 0 | NOT IMPLEMENTED |
| `near_miss` / `refuted_registry` / `curated` | 0 | NOT IMPLEMENTED |
| `FeatureBinding` / `feature_binding` | 0 | NOT IMPLEMENTED |
| `WITH RECURSIVE` / recursive CTE | 0 | NOT IMPLEMENTED |
| `inadmissible` source screen | 0 | NOT IMPLEMENTED |
| `invalidate()` production callers | 0 | implemented, unused in src/ |
| `provenance_edges` edge vocab | 5 types | cites/derived_from/supersedes/used_as_input/justifies |
| `reconcile.py` | 6 lines | placeholder |

---

## 12. Continuity Statement

**STEP 4 — S5/S7 DECISION GATE COMPLETE.**

**Verdict: B — S5 READY / S7 REQUIRES FURTHER DESIGN.**

S5 (invalidation cascade) is architecturally complete and implementable
against the current substrate; it is authorized to proceed to a
separately-chartered implementation step. S7 (refuted-registry /
resurrection screen) is substrate-blocked on the §16.6 curated registry,
the FeatureBinding signature carrier, and the curation-invariant
admission path; it requires a further design gate before implementation.
The C1 §5.4 resurrection consumer remains DEFERRED until S7 lands.

The next step in the frozen sequence is **Step 5** (P4 prerequisites
including the ModelClient boundary), unless the operator charters the
S5 implementation step first. This gate does NOT authorize implementation
of either S5 or S7 — ratification is not permission to implement; each
step remains separately chartered.

*End of Step 4 decision gate. Recorded at `step-4` = `872d04b`,
docs-only, no production-code changes.*
