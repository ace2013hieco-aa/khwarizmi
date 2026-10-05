# Hermes Final Ratification Gate

**Independent Pre-Ratification Verification, Reconciliation & Governance Closure**

**Date:** 2026-08-20
**Repository:** `ace2013hieco-aa/khwarizmi-research` @ `main`
**Role:** FINAL ARCHITECTURE RATIFICATION AGENT (governance + architectural-integrity gate)
**Standard of proof:** live source > live tests > git history > ratified docs > design gates > adversarial reviews > agent claims. No status claim was trusted from documentation alone; every load-bearing claim below was re-verified against the live tree at the HEAD recorded in §2.

---

## 1. Executive Verdict

> ## RATIFICATION READY WITH EXPLICIT DECISIONS

The current Hermes architecture — the ratified v6 baseline plus the Five-Fundamentals amendment package and its C1/C4/C5/C6 design gates — is **coherent, epistemically safe, deterministic, and governable enough to ratify**, provided the operator consciously rules on exactly **three** decisions (§13). There are **zero architectural blockers** (§12) and **zero defects requiring redesign** before ratification.

What this verdict is NOT: it is not "everything is implemented." Most of the Five-Fundamentals package is **DESIGNED, not IMPLEMENTED** (§3). Ratification here means *ratify the design and stop changing the architecture*, not *declare the mechanism built*. The implementation-state honesty of the repository is itself one of the strongest arguments for readiness: the package is explicit, everywhere, about what is deferred (§4, §10).

The three explicit decisions are minimal and genuine — none is invented:

1. **C5 priority position** — Option A (below-dimensions) vs Option B (literal Q-02 precedence, bounded). This is the one decision that touches a ratified contract (Q-02 §11.5) and carries a real risk trade-off.
2. **C1 slot-vocabulary scope** — ratify the FULL-HISTORY append-only reading explicitly (do not inherit it silently).
3. **Deferred-dependency acceptance/ordering** — accept the partial failure-localization state until S5/S7 land, or sequence them ahead; confirm the S5/S7/P4/ModelClient prerequisite chain.

If the operator rules on these three, the architecture-design loop should **STOP** and implementation should begin under the §17 sequence.

---

## 2. Repository State Verified

All facts below re-verified live on 2026-08-20 (not inherited from prior documents).

| Item | Verified value |
|---|---|
| HEAD | `e151a74eb6609749e3e97257be6bd209d32e42ec` |
| Branch | `main` |
| Divergence from `origin/main` | **0/0** — `git status -sb` shows `## main...origin/main` with no ahead/behind; `git rev-parse origin/main` == HEAD |
| Tracked-state cleanliness | Clean — `git status --short` shows **no** modified/staged tracked files |
| Untracked files (3) | `FRESH_REDTEAM_AUDIT.md`, `P-BAYESIAN-PROTOCOL-01_reconciliation_record.md`, `hermes_gr4_annealed_bridge_sampling_proposal.md` |
| Documents under review present at HEAD | Yes — all of `hermes_research_architecture_v6.md`, `hermes_five_fundamentals_blueprint.md`, `hermes_five_fundamentals_ratification_readiness.md`, `hermes_architecture_team_handoff.md`, and the four C-gate files exist in the working tree at HEAD |

**Note on HEAD drift:** the readiness package was written against `8f011a3`, the handoff against `3a1e890`, the blueprint against `ef2b9e4`. Current HEAD `e151a74` is **later** than all of these (it adds the Step-0 test gaps `bf5e67d` and the README cleanup `e151a74`). No document under review claims a HEAD that is *ahead* of the live tree; all cited commits are ancestors of `e151a74`. The documents' commit citations remain accurate as historical anchors.

**Verification gates executed for THIS document (live, 2026-08-20):**

| Gate | Result |
|---|---|
| `.venv/Scripts/python.exe scripts/run_tests.py` | **1525 passed** in 347.24s |
| `uvx pyright src/` | **0 errors, 0 warnings, 0 informations** |
| `uvx ruff check src/ tests/` | **All checks passed!** |
| `git status` | clean tracked tree; 3 deliberately-untracked files |

The suite count (1525) matches the readiness package's post-Step-0 expectation (1513 prior + 12 Step-0 tests). The 12 Step-0 tests are confirmed present: `TestEmptyArtifactNeverSatisfies` (`test_program_obligations.py:465`), `TestM3NamedInjectionFixtures` (`test_provider_orchestration.py:2230`), and three foreign-project tests in `test_hr07_decisive_refuted_contract.py` (lines 483/501/516).

**Relevant recent commits (ancestors of HEAD):**
`e151a74` (README cleanup) ← `bf5e67d` (Step-0 test gaps, tests-only) ← `7b7ccb8` (readiness package) ← `8f011a3` (handoff) ← `3a1e890` (C5 TTL remediation) ← `4554a27` (adversarial-review remediation) ← `e3091e8` (substrate cross-check fix) ← `9765ecf`/`4b3c2b4`/`486c5dc`/`7eab07b` (C6/C5/C4/C1 gates) ← `783831b` (blueprint).

---

## 3. State-Ladder Assessment

The repository's own ladder: **DESIGNED → IMPLEMENTED + TESTED → EXTERNALLY VERIFIED → RATIFIED** (v6 header, line 3). Each component classified independently below. "Verified" here means adversarially reviewed against live source (the four C-gates each passed an independent hostile review); it does NOT mean externally ratified.

| Component | State | Evidence (verified live) |
|---|---|---|
| **v6 baseline (approved slices: P2 ResearchProgram/ActionEvaluation, Step-5 trust boundary, P3 gateway/task-plan/walking-skeleton)** | **RATIFIED** | v6 header line 3: operator ratification IDR-023 after external closure gate at `979399e`/`55ad4c4`. Live source confirms the ratified carriers exist (`programs.py`, `evaluation.py`, `gateway.py`, `controller.py`) |
| **v6 deferred slices (GR1–GR9, P7+, §28.5 rows)** | **DEFERRED** (below RATIFIED by explicit design) | v6 header line 3: "later slices remain DEFERRED (§28.5)"; not ratified |
| **v6 CONTRA candidate amendment (§29)** | **DESIGNED** | v6 line 227: "no implementation, no verification, no ratification claim" |
| **v6 Scientific-Skills candidate amendment (§30)** | **DESIGNED** | v6 line 239: same explicit non-ratified status |
| **Five-Fundamentals blueprint** | **DESIGNED** (reviewed + corrected, NOT ratified) | Blueprint header: "NOT ratified Hermes architecture … modifies nothing". Adversarial audit A–R completed; corrected tally 5/10/3 at §27.2 (line 2182) |
| **C1 slot_ref** | **DESIGNED** (gate reviewed: HOLDS WITH CAVEATS, 4/4 confirmed) | No `slot_ref` anywhere in `src/` (grep: zero hits). Gate `7eab07b` + remediations |
| **C4 exploration floor** | **DESIGNED** (gate reviewed: HOLDS WITH CAVEATS, 11 confirmed / 1 contradicted+fixed) | No floor mechanism in `src/`; no `FloorGrantRecorded` in `events.py` (grep: zero hits). Gate `486c5dc` + remediations |
| **C5 Director priority** | **DESIGNED** (gate reviewed: HOLDS WITH CAVEATS, 2 confirmed / 2 contradicted+fixed; one open decision) | No `PROPOSE_DIRECTOR_PRIORITY` in `intents.py`; no `DirectorPriorityProposed` in `events.py`. Gate `4b3c2b4` + remediations |
| **C6 convergence diagnostic** | **DESIGNED** (gate reviewed: HOLDS WITH CAVEATS, 10/10 confirmed) | `RECONCILE_DIGEST_VERSION = "4"` still (`controller.py:87`); no `convergence` section in `reconcile_digest()`. Gate `9765ecf` + remediations |
| **S5 invalidation cascade** | **NOT IMPLEMENTED** (deferred by design) | `repositories.py:619–641`: "IDR-017: Non-cascade contract … Full cascade semantics … deferred to the reconcile loop (§8, P3)" — the deferral is an explicit ratified contract, not an omission |
| **S7 refuted-registry / resurrection screen** | **NOT IMPLEMENTED** (designed in v6 §10.2) | Zero resurrection/screen machinery in `src/` (grep) |
| **P4 agent runtime (Director/Researcher/Adversary/Implementer/Reconcile)** | **NOT IMPLEMENTED** (Phase-0 placeholders) | `src/hermes/agents/*.py` all 4-line stubs ("Not implemented until P4"); `reconcile.py` 6-line stub (verified `wc -l`) |
| **ModelClient record/replay** | **NOT IMPLEMENTED** | No ModelClient class in `src/` (blueprint §27 re-grade finding; confirmed absent) |
| **GR4 annealed-bridge proposal** | **PROPOSAL** (below DEFERRED in authority order) | Blueprint lines 19–22: "PROPOSAL status preserved verbatim; it has not passed the five-stage loop and does not alter the ratified baseline or any IDR". File remains untracked |
| **P-BAYESIAN-PROTOCOL-01 reconciliation record** | **PROTOCOL-LAYER governance artifact** (untracked; subordinate to v6 by its own §P1) | Self-declares: protocol-layer only, not architecture, not mechanism, no cross-layer override; ADR status "NONE AUTHORIZED". See §15 for disposition |

**Key observation:** the ladder is never collapsed in the repository's own documents. Every design gate carries a "Status: DESIGN — nothing here is ratified" header; the blueprint, handoff, and readiness package all state implementation is separately chartered. This discipline is verified, not assumed.

---

## 4. Five-Fundamentals Assessment

Independent audit of the package against the twelve required points. Evidence hierarchy honored throughout.

| # | Audit point | Finding | Class |
|---|---|---|---|
| 1 | Corrected adversarial audit tally | **VERIFIED.** Blueprint §27.2 (line 2182) records 5 outright (D,I,N,O,R) / 10 partial (B,C,E,F,G,H,J,K/L,M,Q) / 3 only-if-extensions (A + K/L residual). The retraction of the unverified 9/5/4 verdict is recorded (§26.1). The correction downgraded five attacks whose defenses were deferred subsystems — honest, transcript-verified | OK |
| 2 | Overclaim/retraction handling | **VERIFIED.** The original verdict was retracted explicitly, not silently edited; the correction names each downgraded attack and why | OK |
| 3 | No new mutation/write path | **VERIFIED.** All four gates route through the existing `apply_intent` gateway (`gateway.py:1537` — the single mutation path). C1 adds a field on an existing carrier; C4 amends the existing ordering policy; C5 is proposal-shaped admission; C6 is a read-only digest section. No gate creates a table, a write path, or an intent that executes | OK |
| 4 | Preservation of deterministic control | **VERIFIED.** C4's floor function is pure (no clock/random/SQL/LLM); C5 consumption is a pure derivation from append-only events; C6 is a pure derivation hashed into the digest. `_task_ordering_key` (`evaluation.py:573–581`) is untouched by all four designs | OK |
| 5 | Evidence-ladder integrity | **VERIFIED.** No gate touches ladder preconditions or transitions. C1 explicitly: "no ladder precondition" (§3); C5: "no ladder transition from priority" (§2.6 MUST-NOT) | OK |
| 6 | Confirmatory vs exploratory separation | **VERIFIED.** C4 IS the exploratory bound (one reserved slot for a non-leading trajectory); it never converts exploration into confirmatory authority — floor grants produce dispatches, which still must earn satisfaction links through the normal verdict path | OK |
| 7 | Reconcile-loop authority | **VERIFIED.** The controller tick is the current reconcile loop; `reconcile_digest()` is read-only ("nothing here can act", `controller.py:991–993` — verified verbatim). C6 extends the digest's posture, never replaces it | OK |
| 8 | Task-graph authority | **VERIFIED.** No gate modifies task-graph rules, dependencies, or admission. C4/C5 reorder the already-eligible set only | OK |
| 9 | Agent boundedness | **VERIFIED.** Director proposes (C1 assignment, C5 priority); validators check (E6 membership/format); the deterministic policy consumes. "The signal proposes; the deterministic machinery decides" (blueprint §17 closing line) | OK |
| 10 | Epistemic safety | **VERIFIED** — see §9 for the full independent recheck. All seven remediation areas CLOSED in live source with adversarial tests | OK |
| 11 | Provenance requirements | **VERIFIED.** C1 new-slot rationale rides the admission event payload (never canonical content); C5 rationale is admission-time; C4/C6 add no provenance-free surfaces | OK |
| 12 | Compatibility with ratified v6 invariants | **VERIFIED with one flagged refinement.** No-scalar (IDR-019/attack D): intact in all four gates. Single mutation path (failure mode R): intact. No stored priority (Q-02 §14): C5 threads it via the proposal-record distinction. **The one refinement:** C5 §2.2/§2.6 vs Q-02 §11.5 literal precedence — this is the §13 Decision 1 item, properly flagged, not silent | FLAGGED (Decision 1) |

**Hidden-authority scan** (the nine prohibited shapes):

| Prohibited shape | Scan result |
|---|---|
| Hidden scheduler | **None.** Dispatch remains the controller's internal function consuming one policy order; C4 is a clause in that policy, C5 an input to it |
| Hidden state | **None.** C4's F-C counter and C5's TTL are derived from append-only events (`FloorGrantRecorded` design / `TaskStatusChanged` claims); no mutable stored counters |
| Second mutation path | **None.** All admissions through `apply_intent` |
| Evidence bypass | **None.** Satisfaction still requires a dereferenceable PASS verdict (verified §9); no gate creates an alternate satisfaction route |
| Authority escalation | **None.** C6 is never-a-gate-input by construction + structural fixtures (AC-6/AC-7); C5 is eligibility-neutral by construction |
| Unbounded agent discretion | **None.** Closed enums (C5: 3 values), closed vocabularies (C1: format-checked), validator-checks-semantics-never |
| Implicit promotion path | **None.** C5's activation-boundary safeguard rejects silent auto-activation on policy upgrade (AC-12) |
| Graph-as-authority / memory-as-authority | **None.** No graph or memory surface is consulted by any gate; portfolio remains a derived projection |
| Undocumented state transition | **None.** Every transition (floor F-C states, priority TTL/revocation) has a named event or diagnostic |

**Verdict:** the Five-Fundamentals package introduces **no new admission path, no second authority, and no hidden state**. Its central claim survives independent inspection.

---

## 5. C1 Assessment — `slot_ref`

**Independent review against live source (not trusting the gate's own reconciliation table).**

Verified live facts:
- `HypothesisSpec` (`programs.py:188–200`) has exactly the fields the gate claims (`ref`, `ladder_target`, `falsification_condition`, `rival_of`, `rival_status`) and **no `slot_ref`** — the field is genuinely new.
- **The AC-1 identity hazard is REAL and independently reproduced.** Live probe: `canonical_json({"ref":"h1","ladder_target":"SUPPORTED"})` ≠ `canonical_json({... , "slot_ref": None})` — `canonical_json` serializes `None` values (`"slot_ref":null`), so a naive None-emission WOULD rehash the entire existing corpus. The gate's mitigation (emit `slot_ref` only when non-None in `_h_to_dict`) is correct and sufficient. `_h_to_dict` (`programs.py:1156`) currently emits exactly the five existing fields — confirmed it feeds both `canonical_content_dict` (:1220) and `program_to_dict` (:1269), so the non-None-only rule must cover both (the gate's dual-consumer note is accurate).
- Supersession context already reaches the compile layer (`gateway.py:240–246` resolves `superseded_program_ids` in-project) — E6 needs no new data access. Confirmed.
- E6 is free (E1–E5 allocated); `PROPOSE_RESEARCH_PROGRAM` payload carries optional keys (`ratification_ref` precedent). Confirmed.

**The key question — LIVE CHAIN vs FULL HISTORY:**

> Should the slot vocabulary be based on the LIVE supersession chain or FULL SUPERSECTION HISTORY?

**This review independently confirms FULL HISTORY is the correct interpretation.** The argument is decisive, and it is the architecture's own:

1. **The consumer needs retired slots.** C1's stated payoff (blueprint F6, resurrection screening per IDR-041) requires recognizing a slot AFTER its lineage was abandoned or REFUTED. A live-chain vocabulary retires slots exactly when the resurrection consumer needs them — the mechanism defeats its own purpose.
2. **Live-chain forces label duplication.** When a lineage dies, its slots retire; a later program re-exploring the same concept must "declare new" a label for a concept that already has one — minting two labels for one concept, breaking mutation-identity (F2).
3. **Full history is the replay-stable reading.** The vocabulary becomes a pure function of the project's immutable program rows (append-only, IDR-041 §4/F14 precedent) — identical rows ⇒ identical vocabulary, independent of admission order. Live-chain vocabulary depends on which lineage is currently alive — a derived, mutable posture, contrary to the repository's derived-state discipline.
4. **The blueprint's own wording is ambiguous, not contrary.** §21 F-B says a slot "must either already exist in the supersession chain or be declared new" — "the supersession chain" read as the project's full chain history is consistent with F-B's text; the live-chain-only reading is the narrower interpretation, and the gate transparently flags the refinement (§7.1) rather than hiding it.

**Classification:** FULL HISTORY requires **explicit operator ratification** (it refines blueprint wording), but NO architectural modification — the gate already designs it. Overruling to LIVE CHAIN is only coherent together with an alternative resurrection-screening mechanism (none exists).

**Rehash-safety verification:** the proposed implementation CANNOT silently rehash existing programs via `slot_ref=None` insertion — AC-1 pins Delta=0 with a pre/post compiler fixture, and the non-None-only emission rule is the mitigation (independently confirmed necessary by the live probe above). `PROGRAM_SCHEMA_VERSION` bumps at implementation; no migration needed (TEXT column).

**C1 verdict:** DESIGN sound; HOLDS WITH CAVEATS confirmed independently. One explicit decision required (vocabulary scope). No blocker.

---

## 6. C4 Assessment — Exploration Floor

**Independent review against live source.**

Verified live facts:
- The Q-02 ordering surface is exactly as the gate describes: `TASK_ORDERING_POLICY` string + version triple (`evaluation.py:433–447`), lexicographic key over six dimensions → cost → created_at → task_ref (`_task_ordering_key`, :573–581 — verified verbatim). The floor is a versioned clause amending this policy's OUTPUT, not the key itself.
- The per-tick call cap is real: `DEFAULT_MAX_CALLS_PER_TICK = 8` (`controller.py:248`), enforced at dispatch. The floor consumes capacity, never expands it (§2.2); `floor_slots` ≥ capacity is rejected at policy construction (fail-closed).
- The degenerate-to-baseline pattern exists (`DEGENERATE_TO_BASELINE`, `evaluation.py:452`) — C4 reuses the established fallback shape.
- **The substrate defect was real and is fixed.** The ranking is transient and never persisted (`evaluation.py:494–511`); no ranking event exists in `events.py`. The gate's remediation — a new append-only `FloorGrantRecorded` event as the durable floor-grant substrate — is verified as the correct fix; `FloorGrantRecorded` does not yet exist in `events.py` (correct: DESIGN status), and its addition is the one flagged catalog exception.
- **No scalar, no spent-budget read:** the floor is a structural reservation over the lexicographic order (attack D intact); the F-C stagnation counter reads NEW satisfaction links, never spent budget (attack O intact). Both verified against the gate text and the live ordering surface.

**C4↔C5 composition — verified resolved in BOTH directions:**
- C4 §4.5 (lines 316–355) mirrors C5 §5 (lines 404–424): identical four composition rules (priority reorders first; floor applies second to the priority-aware order; priority never exempts from F-C; no priority suppresses the floor). Confirmed by reading both sections — the text is mutually consistent and cross-cited.
- The 8-cell joint C4×C5 test matrix is pinned in C4 §4.5 (cells 6–8 are the adversarial core: F-C despite priority, zero-claim rounds, inert-priority non-consumption).
- The prior one-sidedness defect (found by deleg_a790ff80) is genuinely remediated — composition now lives in both gates.

**F-C mode (decay vs kill-switch) as implementation-time parameter:** ACCEPTABLE. Both modes are fully designed (§2.3) with acceptance criteria (AC-7/AC-8); the choice between them is a values judgment about patience with stagnant trajectories, not an architectural unknown. It is versioned (`floor_stagnation_mode`), so either default is replay-stable. This is a team parameter decision at the implementation charter, NOT a ratification decision — it does not change the contract's shape.

**C4 verdict:** DESIGN sound; HOLDS WITH CAVEATS confirmed independently. No open decision rises to ratification level (the F-C default and trajectory granularity are policy-version parameters). No blocker. Approved for implementation first (controller-only, no P4 dependency).

---

## 7. C5 Assessment — Director Priority (the critical governance decision)

**Independent review against live source.**

Verified live facts:
- Q-02 §11.5's exact wording (verified at `hermes_q02_epistemic_roi_design.md:249–252`): "Precedence: ratified Director priority > epistemic policy > created_at/task_id tie-break (§11). (The override mechanism is deferred; the precedence is asserted at design level.)"
- Q-02 §18.2 (verified at :496–510): the precedence line is "a documented contract, not an implementation … IF a ratified override mechanism is ever built, it ranks above the policy — and Q-02 itself must never introduce a priority field (no new mutation surface, no budget-adjacent authority)."
- Q-02 §14's rejection is specifically a **stored priority field on tasks** — C5's proposal-record shape is not that shape (verified: no priority column exists; C5 adds an append-only admission record, trajectory-keyed, closed enum).
- The proposal-shaped precedent exists: `PROPOSE_CLASSIFICATION_ACTION` is `director_only` (`intents.py:84–93` — verified the frozenset body), admitted proposal-only with the EFFECTIVE/PENDING_HUMAN_APPROVAL split.
- No `PROPOSE_DIRECTOR_PRIORITY` intent, no `DirectorPriorityProposed` event exists yet — correct for DESIGN status.

**The conflict, stated precisely:** Q-02 §11.5 asserts (design-level, mechanism deferred) that a ratified Director priority ranks ABOVE the epistemic policy. C5 §2.2 as originally designed places priority BELOW the six epistemic dimensions (tie-breaker only). The pre-P4 readiness brief then recorded an Option-B recommendation (bounded literal precedence) in C5 §2.6. Both options are fully designed and visible. The ratification must pick one.

### Option A — priority below the epistemic dimensions (C5 §2.2 original)

| Criterion | Evaluation |
|---|---|
| Architectural coherence | Highest. Priority is purely advisory tie-breaking; the epistemic ordering remains the sole authority over merit. "The signal proposes; the deterministic machinery decides" in its strongest form |
| Scheduler-authority risk | Minimal. Priority can never reorder an epistemic difference — no hidden scheduler is possible |
| Epistemic integrity | Maximal. Evidence-gap/contradiction/rival dimensions always dominate |
| Compatibility with Q-02 | **Inverts Q-02 §11.5's literal text.** Requires treating §11.5 as superseded-by-refinement — legitimate only as a controlled, explicitly-ratified refinement (Q-02 §18.2's deferral exists precisely to let the mechanism's design gate settle the position, which cuts in favor of the gate's authority to settle it) |
| Attack-C implications | Attack C is structurally impossible under A |
| Deterministic replay | Identical guarantees to B (both are versioned policy clauses) |
| Boundedness | Trivially bounded — priority cannot override anything |
| Abuse potential | Lowest. A malicious/compromised Director can only permute epistemically-equal tasks |
| Hidden scheduling authority? | No |
| Do existing C5 constraints contain the risk? | Yes — under A they are belt-and-braces |
| **Weakness** | The Director's urgency signal is weak: an ELEVATE cannot lift a LOW-gap task above a HIGH-gap one, so C5 may fail its own purpose (expressing trajectory urgency between human decisions) in exactly the cases where urgency matters |

### Option B — literal precedence, bounded (Q-02 §11.5 letter; C5 §2.6)

`Director priority > Q-02 epistemic ordering > cost > created_at > task_ref`, bounded to the already-eligible set, with seven MUST-NOT bounds (no eligibility change, no gate/dependency/budget bypass, no Evidence-Ladder change, no task creation, no program-state mutation) and two temporal safeguards (activation boundary AC-12; TTL-at-consumability AC-13).

| Criterion | Evaluation |
|---|---|
| Architectural coherence | Good, IF the bounds hold. Priority becomes a first-class ordering authority above merit — coherent with Q-02's text, but the epistemic ordering is no longer the final word on dispatch order |
| Scheduler-authority risk | **Real and accepted.** A priority above the dimensions IS a scheduler-shaped authority. The bounds confine it to ordering-within-eligible, but the Director can now force a LOW-merit trajectory's task ahead of a HIGH-merit one. This is the explicit attack-C risk acceptance Option B requires |
| Epistemic integrity | Reduced by design — merit can be overridden. Mitigated by: TTL decay, operator revocation, supersession, version-bound consumption, and the fact that dispatch still cannot bypass gates/dependencies/budgets/ladder |
| Compatibility with Q-02 | **Literal compliance** with §11.5 and §18.2's "ranks above the policy" carve-out |
| Attack-C implications | Attack C is no longer structurally impossible — it is CONTAINED by the seven bounds + temporal safeguards + AC-12/13/14 fixtures. "Advisory becomes obeyed" is prevented by TTL/revocation, but "obeyed within TTL" is the design |
| Deterministic replay | Same guarantees as A (pure derivation from append-only events + versioned clause) |
| Boundedness | The bounds are strong and fixture-pinned (AC-14), but they are CONSTRAINTS on a real authority, not the absence of one |
| Abuse potential | Higher than A: a compromised Director can starve a high-merit trajectory for the TTL window. Operator revocation is the backstop |
| Hidden scheduling authority? | Not hidden (versioned, logged, PRIORITY_APPLIED diagnostic, revocable) — but it IS scheduling authority |
| Do existing C5 constraints contain the risk? | Yes, provided AC-12/13/14 are implemented as structural fixtures, not conventions. The activation-boundary safeguard is the critical one: without it, a stale priority queue silently seizes authority when the mechanism turns on |

### Decision-record recommendation

**Recommendation: ratify OPTION B (bounded), per the readiness package §E / C5 §2.6.**

Reasoning, stated honestly:

1. **Q-02 §11.5 is ratified text.** Option A requires the ratification to consciously OVERRIDE a ratified design-level assertion. Option B requires the ratification to consciously ACCEPT a bounded risk. Both need an explicit operator act — but overriding ratified text is the heavier governance move, and Q-02 §18.2 explicitly pre-carved the "ratified override mechanism ranks above the policy" shape. The blueprint's five conditions (§17) were written to make exactly this shape safe.
2. **Option A risks making C5 pointless.** A priority that only breaks epistemic ties cannot express the urgency C5 exists for; the mechanism would be ratified but inert in the cases that motivated it. A useless-but-safe mechanism is not obviously better than a bounded useful one.
3. **The risk Option B accepts is bounded, observable, and revocable** — not eliminated. The acceptance must be recorded as: *"the operator knowingly admits a scheduler-shaped ordering authority above the epistemic dimensions, confined to the eligible set, decayed by TTL, revocable at any time, version-bound, with silent activation rejected (AC-12)."* If that sentence is unacceptable, Option A is the fallback and is fully designed.
4. **This constitutes a controlled refinement of Q-02 either way.** Option B implements Q-02's letter with bounds Q-02 did not specify (the seven MUST-NOTs); Option A refines Q-02's letter into tie-breaking. Neither is silent. The ratification record must name which refinement is adopted.

**Required before implementation (whichever option):** AC-12/13/14 as structural fixtures; the `REVOKE_DIRECTOR_PRIORITY` operator channel; TTL default fixed (tens of dispatch rounds, versioned); dispatch-round TTL semantics confirmed (§7.6 of the gate).

**C5 verdict:** DESIGN sound under either option; the option choice is the single most important operator decision in this package. Not a blocker — both options are fully designed — but ratification MUST pick one explicitly.

---

## 8. C6 Assessment — Convergence Diagnostic

**Independent review against live source.**

Verified live facts:
- `reconcile_digest()` (`controller.py:981–1015`) is genuinely read-only: "nothing here can act: never writes, never executes, never retracts" (verified verbatim at :991–993). It folds six deterministic sections and hashes the composite. C6 adds one section + version bump 4→5.
- `RECONCILE_DIGEST_VERSION = "4"` confirmed at `controller.py:87`; the six concrete `digest_version == "4"` test pins enumerated in C6 §7.5 are confirmed at the exact cited locations (`test_provider_orchestration.py:1874`, `test_q04_gate_replay.py:338`, `test_q04_review_candidates.py:528`, `test_q05_evidence_ladder.py:1050/1100/1122`).
- **NOT_DERIVABLE honesty is genuinely honest.** `CONTRADICTION_DETECTED` exists only as an enum declaration (`events.py:59`) with **zero emitters** in `src/` (grep verified — only the enum line and a comment in `intents.py`). `contradiction_reduction` is hardcoded NONE (`task_obligations.py:124`, "no stored source"). So S3 (open contradictions) emitting `NOT_DERIVABLE` is the truthful state — emitting zero would be a lie.
- S5 (floor exhaustion) correctly emits `NOT_DERIVABLE` until C4 lands (no `FloorGrantRecorded` events exist yet).
- Named-key-only consumption: both observe→act loops consume digest sections by explicit named key, so the new `convergence` section cannot flow into any consumer without new code (AC-6 structural fixture pins this, including the no-`digest.values()` iteration rule).
- `propose_refutation_actions()` (the one act-adjacent loop) does NOT consume the convergence section (AC-7).

**Covert-scheduler / evidence-source check:** C6 is structurally unable to act — it exists only inside the hashed digest body; no gate, ordering policy, eligibility predicate, ladder derivation, budget, or dispatch path may read it (AC-6/AC-7 fixtures). It proposes nothing, emits no intent, and the convergence decision remains the human's (HR-08). **C6 does NOT become a covert scheduler or evidence source.** Verified.

**Contradiction-machinery instruction honored:** this review does NOT recommend implementing contradiction emitters to enrich C6. The `NOT_DERIVABLE` state IS the feature; the honesty discipline is preserved. When the contradiction machinery lands (agent-runtime scope, separate milestone), S3 flips to real under the same `signal_schema_version` — observable, never silent drift.

**C6 verdict:** DESIGN sound; HOLDS WITH CAVEATS confirmed independently (10/10 claims verified). Implementation is P4-gated (the Director runtime must exist to consume it meaningfully). No blocker, no open decision at ratification level (S3 sequencing and the optional C5-history advisory are implementation-charter parameters).

---

## 9. Epistemic Safety Assessment

Independent recheck of the seven remediation areas against live source and tests — not trusting the readiness package's CLOSED labels.

| Area | Live verification | Tests exercise the enforcement boundary? | Status |
|---|---|---|---|
| **M1/HR-02: satisfaction ≠ artifact class** | `program_obligations.py` rule 5: satisfaction requires a dereferenceable PASS validation verdict keyed to the artifact's content hash (verified header lines 15–34; `ValidationVerdictRepository` at :64+). Empty artifact + no verdict → NOT SATISFIED; empty artifact + FAIL verdict → NOT SATISFIED (Step-0 `TestEmptyArtifactNeverSatisfies`, `test_program_obligations.py:465`) | Yes — adversarial fixtures drive the actual satisfaction derivation, including forged links, tampered hashes, foreign artifacts | **CLOSED** (honest residual: the verdict substrate records PASS trusting the issuing validator; content non-emptiness is delegated to the future content validator — recorded in the test docstring, not papered over) |
| **M3: untrusted-content boundary** | `UntrustedContentView` envelops fetched/search text at the handler context (`controller.py:3178–3186`, verified verbatim); `security/boundaries.py` envelope semantics | Yes — Step-0 `TestM3NamedInjectionFixtures` (`test_provider_orchestration.py:2230`) drives five named injection shapes (instruction override, fake system message, fake tool call, fake evidence/approval, malicious metadata) end-to-end through search→fetch→EXTRACT dispatch, plus a compromised-model worst case; asserts no satisfaction/REFUTED/approvals/authority-surface contamination | **CLOSED** |
| **Claim admission (HR-05/M4)** | `claims.py:60–83` closed 6-state `SupportState` vocabulary (verified verbatim: DIRECT/PARTIAL/INFERRED/SPECULATIVE/CONTRADICTED/UNSUPPORTED); span-dereference protocol; no LLM judge | Yes — fabricated-span rejection, causal-DIRECT source-shape rules, unknown-state rejection | **CLOSED** |
| **HR-08: lifecycle completion invariant** | `completion.py` pure eligibility predicate (verified :198+); enforced inside `ProjectRepository.transition_lifecycle` (`repositories.py:201` — the single lifecycle write path) | Yes — all six brief-required cases (terminal/gates/budget/noREADY missing → deny; full satisfaction → permit; corrupt rows → deny) | **CLOSED** |
| **HR-07: decisive REFUTED contract** | `certifies_decisive_falsification` (`failure_classification.py:879`); head-binding at both REFUTED drivers; project-scoped discovery (`controller.py:2294–2298`); project-bound classification content hash (`evidence_ladder.py:151–186`); project-scoped D3 dereference (`failure_classifications.py:582–600`) | Yes — 21 tests incl. Step-0's three foreign-project layers (bare-path discovery scoping, derived-identity never re-deriving cross-project, proposal-path D3 rejection) | **CLOSED** |
| **HR-04: scholarly identifier preservation** | `normalize_identifier` choke point (`tools/providers/normalize.py:138`, :253 "the choke point"); one deterministic normalization path; provider-native preserved verbatim but not universal identity | Yes — 20 tests (DOI convergence, arXiv version stripping, post-admission identifier mutation refused) | **CLOSED** |
| **HR-03: contradiction surface honesty** | `CONTRADICTION_RESOLUTION` NOT in `llm_proposable()` (verified the frozenset body, `intents.py:76–82`); gateway refuses it NOT_WIRED even for the Director with a well-formed rationale | Yes — `test_gateway.py:437–455` regression: not proposable, refused NOT_WIRED, refusal audited | **CLOSED** |

**Specific attack-shape recheck (charter §11 list):**

| Attack shape | Finding |
|---|---|
| Forged references | Satisfaction link forgery rejected without a covering PASS verdict (M1 tests); forged classification content hash rejected (HR-07 tests) |
| Cross-project references | Three independent layers reject foreign-project REFUTED (Step-0 tests); satisfaction/project-scoping tests |
| Hash substitution | Tampered input-hash satisfaction rejected; content-hash identity chain makes substitution a different artifact |
| Identity substitution | Canonical normalization choke point refuses post-admission identifier mutation (HR-04) |
| Stale/superseded program admission | Gateway rejects unresolvable/stale `supersedes_ref` (STALE, `gateway.py:240–246`); superseded-program both-paths tests (HR-07) |
| Prompt injection through retrieved material | Five named fixtures + compromised-model worst case: payload remains `UntrustedContent`, lands as data, never authority |
| Fake system messages / tool-call-shaped content | Named fixtures drive both shapes end-to-end; envelope prevents coercion |
| Unsupported claim promotion | Closed SupportState vocabulary; UNSUPPORTED is fail-closed; no LLM judge |
| Invalid artifact satisfaction | Empty-artifact mandatory regression (no verdict → refused; FAIL verdict → refused; excluded from derivation) |
| Accidental evidence promotion through diagnostics | Diagnostics are transient/hashed/never-gate-inputs (Q-02 discipline); C6 pins never-a-gate-input structurally; ranking never persisted |

**Verdict:** all seven areas CLOSED in live source, and the tests exercise the actual enforcement boundaries (not just envelope semantics). The one honest residual (verdict-substrate trusts the issuing validator for content non-emptiness) is documented and delegated to the future content validator — it is NOT a ratification blocker because the satisfaction layer itself is fail-closed: no verdict or FAIL verdict ⇒ NOT SATISFIED.

---

## 10. Deferred Dependency Assessment

For each deferred item: what depends on it, what does not, whether ratification can precede it, and which claims remain prohibited until it exists.

### S5 — Invalidation cascade
- **Depends on it:** full Fundamental-#3 preserve-and-mutate failure localization; the Q-04 cone operating over real invalidation (Step 10); the P4 completeness claim.
- **Does NOT depend on it:** C4 (ordering-side only); C1's field contract; C5/C6 consumption; Q-05 classification + Q-04 cone as they exist today (both real and ratified).
- **Can the architecture be ratified before it exists?** YES. The deferral is an explicit ratified contract (IDR-017 non-cascade, `repositories.py:619–641`), not an omission. The architecture intentionally gates it.
- **Prohibited claims until it lands:** no claim of preserve-and-mutate COMPLETENESS; failure localization must be described as partial (Q-05 classification + Q-04 cone real; cascade absent).

### S7 — Refuted-registry / resurrection screen
- **Depends on it:** C1's §5.4 resurrection-screening consumer (the payoff); the slot-axis screening.
- **Does NOT depend on it:** C1's field contract, E6 check, and slot vocabulary (all implementable without S7).
- **Can the architecture be ratified before it exists?** YES — but S7 MUST precede any claim that resurrection screening works. C1's §5.4 is explicitly a deferred consumer, not a blocker for the field.
- **Prohibited claims until it lands:** no claim that resurrections are screened; the slot axis is designed-but-inert.

### P4 — Director/Researcher/Reconcile runtime
- **Depends on it:** C5/C6 activation (their consumption surfaces are Director-facing; the Director is a 4-line stub); the reconcile loop becoming real (today the controller tick IS the reconcile loop).
- **Does NOT depend on it:** C4 (implementable against the controller alone); C1's field; every ratified v6 slice.
- **Can the architecture be ratified before it exists?** YES. The stubs are honest Phase-0 placeholders; the gates are designed against the ratified Director CONTRACT (v6 §13), not the stub.
- **Prohibited claims until it lands:** no claim that C5/C6 are operational; no claim that the Director proposes anything (it cannot yet).

### ModelClient — record/replay + untrusted-content inheritance
- **Depends on it:** P4's model-call safety (attack Q); the guarantee that the future ModelClient path inherits the M3 envelope.
- **Does NOT depend on it:** the M3 boundary as enforced TODAY at the handler context (verified §9); all current safety contracts.
- **Can the architecture be ratified before it exists?** YES — but it MUST precede P4 wiring (Step 6 is the adversarial gate before any LLM wiring).
- **Prohibited claims until it lands:** no claim that model output is record/replay-verifiable; no claim that the M3 boundary covers a ModelClient path that does not exist.

**Assessment:** all four are legitimately deferred, not concealed blockers. Each deferral is explicit in the documents, each has a named prerequisite position in the roadmap (Steps 5–7), and each carries a prohibited-claims discipline. None of them is a prerequisite for the RATIFIED CONTRACT to function — the ratified v6 slices operate today without any of them. **No deferred dependency blocks ratification.** The operator decision is acceptance/ordering only (Decision 3).

---

## 11. Source-vs-Contract Reconciliation

| Contract | Document Says | Source Does | Tests Prove | Status |
|---|---|---|---|---|
| Mutation gateway | Single path via `apply_intent`; proposals admitted, never executed here | `apply_intent` (`gateway.py:1537`) is the one mutation path; NOT_WIRED refusals audited | Gateway rejection suite; HR-03 NOT_WIRED regression | **MATCH** |
| Lifecycle machine | HR-08 completion invariant guards the single lifecycle write path | `transition_lifecycle` (`repositories.py:201`) consults the pure predicate | 13 tests, all six brief cases | **MATCH** |
| Task graph | Dependencies/gates precede ordering; ordering never admits | Eligibility decided before `_order_eligible` (`controller.py:1914–1932`) | Q-02 boundary tests 2–4 | **MATCH** |
| Evidence ladder | IDR-041 transitions, head-bound, APPLY pass | Ladder APPLY pass + `evidence_ladder_state` rows | IDR-041 AC-1..5 suite | **MATCH** |
| Program identity | Content-derived `program_id`; supersession append-only | `content_hash_of`/`canonical_content_dict` (`programs.py:1209–1240`); immutable rows | Identity + supersession tests | **MATCH** |
| slot_ref (C1) | DESIGN: field on HypothesisSpec, E6, full-history vocabulary | **ABSENT** (no `slot_ref` in `src/`) — correct for DESIGN status | None yet (AC-1..8 pinned for implementation) | **MATCH (design-only, honestly absent)** |
| Exploration floor (C4) | DESIGN: versioned clause, FloorGrantRecorded substrate | **ABSENT** (no floor, no event) — correct for DESIGN status | None yet (AC-1..10 + 8-cell matrix pinned) | **MATCH (design-only, honestly absent)** |
| Director priority (C5) | DESIGN: proposal record, closed enum, option A/B open | **ABSENT** (no intent, no event) — correct for DESIGN status | None yet (AC-1..14 pinned) | **MATCH (design-only, honestly absent)** |
| Convergence diagnostic (C6) | DESIGN: read-only digest section v5, NOT_DERIVABLE | Digest is v4, read-only, no convergence section — correct for DESIGN status | 6 `digest_version=="4"` pins (will bump atomically) | **MATCH (design-only, honestly absent)** |
| Invalidation (S5) | DEFERRED to reconcile loop (IDR-017) | Non-cascade contract live (`repositories.py:619–641`) | Single-task invalidation tests | **MATCH (deferral explicit)** |
| Refutation (HR-07) | Decisive-falsification contract, head-bound, project-scoped | `certifies_decisive_falsification` + three project-scoped layers | 21 tests incl. foreign-project | **MATCH** |
| Untrusted content (M3) | Envelope at handler context; five injection fixtures | `UntrustedContentView` at `controller.py:3178–3186` | 6 envelope + 6 injection tests | **MATCH** |
| Claim admission (HR-05) | Closed 6-state vocabulary, span dereference | `SupportState` enum + admission rules (`claims.py:60–83`) | Fabricated-span/unknown-state rejection | **MATCH** |
| Provenance | Estimator identity + basis_refs on heuristic inputs; rationale in admission payloads | Q-02 §13.7 contract by construction (v1 has no heuristics) | Labeling contract tested when present | **MATCH** |

**Discrepancies flagged:** ZERO material discrepancies. Every "absent" row is a design-gate contract whose absence is the correct, honest, documented state. No document claims implementation where source shows none; no source behavior contradicts a ratified contract.

---

## 12. Ratification Blockers

Applying the blocker test to every unresolved issue: *"If we ratify today, does this create a contradiction, unsafe authority path, impossible implementation contract, or governance ambiguity that could materially damage Hermes?"*

### BLOCKERS

**None.**

Every candidate issue was tested and failed to qualify:

| Candidate issue | Blocker test result |
|---|---|
| C5 Option A vs B unresolved | NO — both options are fully designed with ACs; ratifying with the decision pending-but-explicit creates no unsafe path because NOTHING is implemented until the option is chosen. The decision is a ratification input, not a blocker |
| C1 vocabulary scope | NO — FULL HISTORY is designed and recommended; silent inheritance is prevented by requiring explicit ratification wording. No contradiction arises from ratifying the recommended reading |
| S5/S7/P4/ModelClient absent | NO — the ratified v6 contract functions without them; their deferral is explicit with prohibited-claims discipline. Missing implementation ≠ architectural defect (§20 principle) |
| Verdict substrate trusts issuing validator (M1 residual) | NO — the satisfaction layer is fail-closed (no/FAIL verdict ⇒ NOT SATISFIED); the residual is documented and delegated to the future content validator. It cannot create unearned satisfaction today |
| Contradiction machinery absent (C6 S3) | NO — NOT_DERIVABLE honesty makes the absence visible, never silent. No unsafe path |
| GR4 proposal untracked/unratified | NO — it is below DEFERRED in the authority order, alters nothing, and is cited only as a design input |
| P-BAYESIAN record untracked | NO — self-declares protocol-layer, subordinate to v6, no mechanism, no cross-layer override. Documentation-hygiene item (§15) |
| F-C mode default open (C4) | NO — versioned policy parameter, both modes designed |

---

## 13. Explicit Operator Decisions

The minimal decision list. Each genuinely requires a conscious ruling; none is invented.

### Decision 1 — C5 priority position (MOST IMPORTANT)
**Ratify Option A (below-dimensions tie-breaker) OR Option B (literal Q-02 precedence, bounded per C5 §2.6).**
- This review recommends **Option B bounded** (§7), with the explicit attack-C risk acceptance recorded: a scheduler-shaped ordering authority above the epistemic dimensions, confined to the eligible set, TTL-decayed, operator-revocable, version-bound, silent activation rejected (AC-12).
- If Option A is chosen instead, the ratification must record it as a controlled refinement of Q-02 §11.5 (superseding the literal precedence assertion).
- Either way: the choice must be explicit in the ratification record. Silent inheritance in either direction is prohibited.

### Decision 2 — C1 slot-vocabulary scope
**Ratify the FULL-HISTORY append-only slot vocabulary explicitly** (over blueprint §21 F-B's ambiguous "supersession chain" wording).
- This review confirms FULL HISTORY is the architecturally correct reading (§5): the live-chain reading defeats the resurrection-screening payoff, forces label duplication, and breaks replay stability.
- Overruling to LIVE CHAIN is only coherent together with an alternative resurrection-screening mechanism (none exists or is designed).

### Decision 3 — Deferred-dependency acceptance and ordering
**Accept the partial failure-localization state until S5/S7 land, OR sequence S5/S7 ahead of the portfolio layer; and confirm the prerequisite chain** (S7 before C1-§5.4 consumer; S5 before P4 completeness claim; ModelClient before P4 wiring; C4 first, then C1, then C5/C6 P4-gated).
- This is an acceptance/ordering ruling, not a design question — both paths are designed and costed in the roadmap (Steps 3–8).

**Determination that all three genuinely require operator decisions:**
- Decision 1 touches a ratified contract (Q-02 §11.5) and accepts or refuses a real risk — no agent may rule on it alone.
- Decision 2 refines blueprint wording with identity-chain consequences — the gate explicitly routes it back (§7.1).
- Decision 3 allocates implementation sequencing with claim-prohibition consequences — an operator/resource judgment.

**Explicitly NOT decisions (resolved or sub-ratification):** C4 F-C mode default (versioned parameter); C4 trajectory granularity (policy-version choice); C5 TTL default (tens of dispatch rounds, versioned — confirm at implementation charter); C5 SUSTAIN necessity (enum member, droppable without contract change); C6 S3 sequencing and optional C5-history advisory (implementation-charter parameters). These are implementation-charter items, kept off the minimal list deliberately.

---

## 14. Accepted Deferred Work

Intentionally deferred, non-blocking, with their sunset conditions:

| Item | Deferral basis | Sunset condition (when it must land) |
|---|---|---|
| S5 invalidation cascade | IDR-017 ratified non-cascade contract | Before the P4 completeness claim; before mature Q-04 (Step 10) |
| S7 refuted-registry screen | v6 §10.2 designed, unimplemented | Before C1's §5.4 resurrection consumer is claimed operational |
| P4 agent runtime | Phase-0 placeholders by design | Before C5/C6 activation (Step 8) |
| ModelClient record/replay | Attack Q defense, Step 6 | Before any LLM wiring in P4 |
| Budget ledger (attack E) | Ordering never reads spent budget (attack O invariant) | Future audit surface; no gate prerequisite |
| Contradiction machinery (real emitters + resolution routing) | Declared-but-deferred (`intents.py:42–49`); Step 11 | Before C6 S3 flips from NOT_DERIVABLE; explicitly NOT chartered by any current gate |
| Blueprint §19 Q1, Q7–Q13 open questions | Unchanged, still open | Each needs its own design gate if/when pursued |
| GR4 annealed-bridge proposal | PROPOSAL status; has not passed the five-stage loop | Must pass the five-stage loop before any architecture claim |
| v6 CONTRA (§29) and Scientific-Skills (§30) candidate amendments | DESIGNED, not ratified | Their own five-stage loops |

---

## 15. Required Documentation Corrections

Non-architectural fixes. None of these is a ratification blocker; all are hygiene.

1. **Governance-distinction clarity (charter §4 check).** The repository DOES make the v6-ratified vs Five-Fundamentals-unratified distinction explicit: v6 header line 3 carries the RATIFIED status with the state ladder; the blueprint header carries "NOT ratified Hermes architecture"; every C-gate carries "Status: DESIGN — nothing here is ratified"; the handoff says "NOT RATIFIED" in its package status. **Verdict: no governance defect exists.** A future agent reading v6 §28 (ratified amendment text) cannot reasonably conclude the Five-Fundamentals package is ratified, because the package lives in separate documents that each self-declare DESIGN status, and the blueprint's authority-order block (lines 27–30) ranks ratified v6 above itself. **Recommended hygiene only:** when the ratification record is written (Step 2), it should state the distinction once, canonically: "v6 approved slices: RATIFIED. Five-Fundamentals package: ratified as DESIGN by this record; implementation separately chartered." No production-architecture change required.
2. **Untracked-file disposition (3 files).** `FRESH_REDTEAM_AUDIT.md` (historical audit; findings verified resolved §9-era), `hermes_gr4_annealed_bridge_sampling_proposal.md` (cited by committed docs as a design input — deleting it dangles references), and `P-BAYESIAN-PROTOCOL-01_reconciliation_record.md` (protocol-layer governance record from a separate session; self-declares subordinate, no mechanism). **Recommendation:** commit all three as-is (audit trail + cited design input + protocol record), or explicitly delete with the dangling-reference consequence accepted. This is an operator disposition decision, recorded here for completeness — it does not gate ratification.
3. **Readiness-package HEAD citation.** `hermes_five_fundamentals_ratification_readiness.md` line 4 cites `main = 8f011a3`; current HEAD is `e151a74` (later). The citation was accurate at writing and remains a valid historical anchor; no correction required, but the ratification record should cite the HEAD at ratification time.
4. **C5 §7 open-question numbering.** The gate's §7 list is misnumbered after remediations (items appear as 1, 2, 3, 6, 4, 5 — line 501–518). Cosmetic only; does not affect any contract. Fix at next touch of that file.

---

## 16. Final Ratification Verdict

### Final Ratification Matrix

| Area | Verdict | Severity | Required Before Ratification? | Required Before Implementation? |
|---|---|---|---|---|
| v6 baseline (approved slices) | RATIFIED — stable | — | n/a (already ratified) | n/a |
| Five-Fundamentals blueprint | Sound; honest partial states | ACCEPTABLE | No (ratify as-is with corrected tally) | Ratification is the prerequisite |
| C1 slot_ref | Sound; FULL-HISTORY reading | MINOR (decision) | **Decision 2** (explicit ruling) | Yes — AC-1..8, esp. AC-1 Delta=0 |
| C4 exploration floor | Sound; composition bidirectional | NONE | No | Yes — AC-1..10 + joint matrix cells 1–2, 7 |
| C5 Director priority | Sound under either option | **MAJOR (decision)** | **Decision 1** (Option A vs B) | Yes — AC-1..14 incl. AC-12/13/14 fixtures |
| C6 convergence diagnostic | Sound; NOT_DERIVABLE honest | NONE | No | Yes — AC-1..10; atomic v4→v5 bump (6 pins) |
| S5 invalidation cascade | Legitimately deferred | ACCEPTABLE DEFERMENT | **Decision 3** (accept/sequence) | Before P4 completeness claim |
| S7 refuted-registry screen | Legitimately deferred | ACCEPTABLE DEFERMENT | **Decision 3** (accept/sequence) | Before C1-§5.4 consumer |
| P4 agent runtime | Legitimately deferred | ACCEPTABLE DEFERMENT | No | Before C5/C6 activation |
| ModelClient record/replay | Legitimately deferred | ACCEPTABLE DEFERMENT | No | Before P4 wiring (Step 6 gate) |
| Epistemic safety (7 areas) | All CLOSED in live source | NONE (1 documented residual) | No | Residual → future content validator |
| Governance distinction (v6 vs package) | Explicit, no defect | DOCUMENTATION ONLY | No (hygiene note §15.1) | No |
| Untracked files (3) | Disposition open | DOCUMENTATION ONLY | No (operator call §15.2) | No |
| GR4 proposal | PROPOSAL, not merged | ACCEPTABLE DEFERMENT | No | Five-stage loop before any claim |

### BLOCKERS
None (§12).

### EXPLICIT DECISIONS REQUIRED
1. C5 Option A vs Option B (recommended: **B bounded**, with recorded attack-C risk acceptance).
2. C1 FULL-HISTORY slot vocabulary (recommended: **ratify explicitly**).
3. S5/S7/P4/ModelClient deferral acceptance + implementation ordering (recommended: **accept partial state; C4 → C1 → S5/S7 decision → P4 prerequisites → P4 → C5/C6**).

### ACCEPTED DEFERMENTS
S5, S7, P4 runtime, ModelClient, budget ledger, contradiction machinery, blueprint §19 Q1/Q7–Q13, GR4 proposal, v6 CONTRA/Scientific-Skills amendments (§14).

### POST-RATIFICATION WORK
The entire implementation roadmap (Steps 0–11 of the readiness package), of which Step 0 is already DONE (committed `bf5e67d`: 12 tests, suite 1513→1525). Remaining: Steps 1–11, each separately chartered (§17).

### DOCUMENTATION CLEANUP
§15 items 1–4 (canonical ratification-distinction statement; untracked-file disposition; HEAD citation at ratification time; C5 §7 numbering).

---

## THE VERDICT

> ## RATIFICATION READY WITH EXPLICIT DECISIONS

**Why:**

1. **Architectural coherence.** The package is a portfolio-governance layer OVER the ratified control plane — it replaces nothing, adds no second authority, and every mechanism is a derived projection, a versioned policy parameter, or a proposal-only surface. Verified against live source for all four gates.
2. **Invariant preservation.** No-scalar, single-mutation-path, no-stored-priority, eligibility-before-ordering, head-binding, and the no-new-admission-path invariant all survive independent inspection (§4 hidden-authority scan: zero prohibited shapes found).
3. **Epistemic safety.** All seven remediation areas CLOSED in live source with adversarial tests that exercise the actual enforcement boundaries; the five named injection shapes, foreign-project REFUTED, and empty-artifact satisfaction are all pinned (§9). The one residual is documented, fail-closed, and delegated — not hidden.
4. **Governance consistency.** The v6-ratified vs package-unratified distinction is explicit everywhere it matters; no document invites the "everything is ratified" misreading (§15.1). The one genuine governance question (C5 vs Q-02 §11.5) is flagged, designed both ways, and routed to the operator — exactly the correct handling.
5. **Design completeness.** Every gate has decidable contracts, acceptance criteria, implementation surfaces, authority boundaries, and open-question lists. Three hostile review passes found real defects; all were fixed and the fixes verified (§4, §6, §7).
6. **Implementation-state honesty.** The repository never collapses DESIGNED into IMPLEMENTED: stubs are stubs, deferrals are contracts, NOT_DERIVABLE is emitted where sources are absent. This is the discipline that makes ratification safe.
7. **Compatibility with ratified v6.** No gate weakens a ratified slice; the only interaction with ratified text (Q-02 §11.5) is the explicit Decision 1, and Q-02 §18.2 pre-carved the override-mechanism shape.
8. **No unresolved issue requires architectural redesign.** Every open item is either an explicit operator decision (3), a versioned implementation parameter, or an accepted deferment. The blocker test (§12) found zero genuine blockers.

**The standard of §20 is met:** Hermes has reached a sufficiently coherent, safe, deterministic, and governable architectural state that the design should now be RATIFIED and the architecture-design loop STOPPED, unless a future implementation or falsification result demonstrates a real defect. The three decisions are the last architecture-level rulings needed; everything after them is implementation.

**If the operator rules on Decisions 1–3, the architecture is frozen.** Further changes require the implementation-falsification evidence path, not further design iteration.

---

## 17. Post-Ratification Implementation Sequence

The next implementation sequence AFTER ratification (this document implements nothing — charter §17 stop condition honored; no production code touched, no mechanism introduced, no design loop started):

1. **Step 1 — Provider/source identity closure.** Confirm HR-04's normalization choke point covers every provider adapter; per-adapter identifier-preservation tests; mutated-identifier-after-admission refusal. Independent review recommended.
2. **Step 2 — Ratification record.** Record the operator's Decisions 1–3 as an IDR or ratification record per repo convention; state the v6/package distinction canonically (§15.1); cite the HEAD at ratification time. Independent review REQUIRED (authority transfer).
3. **Step 3 — C4 exploration floor** (first implementation: controller-only, no P4 dependency). Floor clause + `FloorGrantRecorded` event + diagnostics; `_task_ordering_key` UNCHANGED; AC-1..10 + joint matrix cells 1–2, 7. Independent review REQUIRED.
4. **Step 4 — C1 slot_ref field contract.** Field + E6 + vocabulary projection + schema-version bump; AC-1 Delta=0 is the gate (corpus-wide rehash check). Independent review REQUIRED.
5. **Step 5 — S5/S7 sequencing decision** (Decision 3 execution): implement now or record the accepted partial state with sunset conditions. S7 before C1-§5.4 consumer; S5 before P4 completeness claim.
6. **Step 6 — P4 prerequisites.** ModelClient record/replay contract + M3 boundary-inheritance fixtures; Director/Researcher runtime CONTRACTS pinned against v6 §13. Independent review REQUIRED (security boundary before LLM wiring).
7. **Step 7 — P4 research runtime.** Replace Phase-0 stubs; reconcile loop real; all proposals still gateway-only; no-new-admission-path invariant re-verified against the live runtime.
8. **Step 8 — C5/C6 activation.** Under the ratified option: `PROPOSE_DIRECTOR_PRIORITY` + consumption + `REVOKE_DIRECTOR_PRIORITY`; convergence digest section v4→v5 (6 fixture pins updated atomically); AC-1..14 / AC-1..10 + joint matrix cells 3–8. Independent review REQUIRED (highest attack-C surface).
9. **Step 9 — Falsification execution.** The minimum execution substrate for decisive REFUTED (declared condition + executed/validated result + identity + hash + provenance). HR-07 full matrix against real results.
10. **Step 10 — Mature Q-04 impact loop.** Cone over real invalidation (S5); assumption-seeded cone walk; cone never invents impact beyond declared edge classes.
11. **Step 11 — Advanced Research OS.** Real contradiction subsystem, portfolio projection, cross-domain generation, effort-normalization closure — each with its own design gate first.

Every step: separately chartered, prerequisites enforced, adversarial gate + independent review per the readiness package §16. **This sequence is the plan after ratification — it is not started by this document.**

---

*End of Hermes Final Ratification Gate. Prepared from executed repository evidence at `main` = `e151a74`. Every load-bearing claim was verified against live source, live tests, or git history on 2026-08-20; no verdict was inherited from a prior document or subagent self-report without independent re-verification. Verification gates: 1525 passed, pyright 0 errors, ruff clean.*
