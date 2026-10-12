# Hermes Architecture Ratification

**Canonical governance record — the authority transition from architecture design to frozen, separately chartered implementation.**

---

## 1. Ratification Date

**2026-08-20** (operator ratification executed this date; repository HEAD at ratification time: `ccb685d`, branch `main`, in sync with `origin/main`, tracked tree clean).

## 2. Ratification Authority

**Operator ratification.** The operator of `ace2013hieco-aa/khwarizmi-research` formally ratifies the architecture via the Final Operator Ratification charter (2026-08-20), executed and recorded by the ratification agent against the live repository. This record is the operator's explicit ruling on the three decisions the Final Architecture Ratification Gate referred to the operator. No decision below was inherited silently; each is recorded verbatim in governance language in §6.

## 3. Governing Baseline

The **ratified v6 architecture** — `hermes_research_architecture_v6.md` — is the governing baseline. Its status (v6 header, line 3): **RATIFIED** on the state ladder (DESIGNED → IMPLEMENTED + TESTED → EXTERNALLY VERIFIED → RATIFIED) for the approved slices (P2 ResearchProgram/ActionEvaluation, Step-5 trust boundary, P3 gateway/task-plan/walking-skeleton), by operator ratification IDR-023 after the external independent closure gate (verdict EXTERNALLY VERIFIED WITH CONDITIONS at `979399e`; conditions V6-FINAL-01/02 closed at `55ad4c4`). The v6 deferred slices (§28.5: GR1–GR9, P7+) remain DEFERRED and are not ratified by this record. The v6 CONTRA (§29) and Scientific-Skills (§30) candidate amendments remain DESIGNED and are not ratified by this record.

This ratification AMENDS the governing baseline with the Five-Fundamentals package under the authority order the blueprint itself declares (live repository + ratified v6 > ratified IDRs > implemented+tested design records > DESIGNED packages > DEFERRED slices > proposals). Nothing in this record weakens or removes any ratified v6 mechanism.

## 4. Final Ratification Gate

This ratification rests on the independent pre-ratification verification:

- **Document:** `hermes_final_ratification_gate.md`
- **Commit:** `5fe6a5e`
- **Verdict:** RATIFICATION READY WITH EXPLICIT DECISIONS — 0 architectural blockers, 0 defects requiring redesign, source/document reconciliation with 0 material discrepancies, epistemic safety 7/7 CLOSED in live source, all four design gates independently verified.
- **Verification gates executed live for the gate document:** 1525 tests passed, pyright 0 errors, ruff clean.

The operator's three decisions below resolve the gate's §13 explicit-decision list exactly. No other decisions were required; the gate's determination that the list is minimal is accepted.

## 5. Ratified Components

The following are **RATIFIED as architecture** by this record (ratified as DESIGN CONTRACTS — implementation is separately chartered per §8 and is NOT authorized by this record):

1. **The v6 baseline** (approved slices) — already RATIFIED (IDR-023); reaffirmed as the governing baseline (§3).
2. **The Five Fundamentals** — `hermes_five_fundamentals_blueprint.md` (commit `783831b`), ratified with its corrected 5/10/3 adversarial audit tally (§27.2), its retraction of the unverified 9/5/4 verdict (§26.1), and its honest partial states (S5/S7 deferred; P4 runtime unbuilt). The five fundamentals introduce no new admission path; every entry remains a proposal through the existing gateway.
3. **C1 — the `slot_ref` design-concept identity contract** — `hermes_c1_slot_ref_design_gate.md` (commit `7eab07b` + remediations), ratified with the FULL-HISTORY slot-vocabulary reading (Decision 2, §6.2).
4. **C4 — the exploration-floor contract** — `hermes_c4_exploration_floor_design_gate.md` (commit `486c5dc` + remediations), ratified as designed, including the `FloorGrantRecorded` event as the one flagged catalog addition. Approved for implementation first (controller-only, no P4 dependency).
5. **C5 — the bounded Director-priority contract with OPTION B** — `hermes_c5_director_priority_design_gate.md` (commit `4b3c2b4` + remediations), ratified with OPTION B bounded precedence (Decision 1, §6.1). Implementation deferred to Step 7 (P4-gated).
6. **C6 — the convergence-diagnostic contract** — `hermes_c6_convergence_diagnostic_design_gate.md` (commit `9765ecf` + remediations), ratified as a read-only, never-a-gate-input advisory surface with the `NOT_DERIVABLE` honesty discipline. Implementation deferred to Step 8 (P4-gated).

Together with: **all explicitly ratified invariants and safety constraints** — the no-scalar invariant (IDR-019/attack D), the single-mutation-path invariant (failure mode R; `apply_intent` gateway), the no-stored-priority discipline (Q-02 §14, threaded by C5's proposal-record distinction), eligibility-before-ordering, head-binding (HR-07), satisfaction-requires-PASS-verdict (M1/HR-02), the untrusted-content boundary (M3), the closed claim-support vocabulary (HR-05/M4), the completion invariant (HR-08), scholarly identifier preservation (HR-04), contradiction-surface honesty (HR-03), and the dependency boundaries recorded in §7.

## 6. Explicit Decisions

The operator's three decisions, recorded in concise governance language.

### 6.1 Decision 1 — C5 Director Priority: OPTION B (BOUNDED) RATIFIED

**RATIFIED: Option B — bounded Director priority.** Director priority follows the literal Q-02 §11.5 precedence:

```
Director priority > Q-02 epistemic ordering > cost > created_at > task_ref
```

This authority is **explicitly bounded**. The ratified C5 mechanism MUST preserve all existing safety boundaries. Director priority MUST NOT:

- create tasks
- create eligibility
- bypass task readiness
- bypass dependencies
- bypass budget constraints
- bypass evidence-ladder requirements
- alter evidence classification
- mutate program state
- modify the task graph
- create an alternative mutation path
- silently activate stale priorities
- bypass lifecycle guards
- override terminal-state invariants

It may **only** affect ordering among tasks that are ALREADY eligible for dispatch.

**Ratified C5 safeguards (all of them):** trajectory-keyed priority; closed strength enum (ELEVATE/SUSTAIN/DEPRIORITIZE — three values, never a scalar); policy-version binding; supersession by the Director; operator revocation (`REVOKE_DIRECTOR_PRIORITY`); TTL; bounded eligible-set operation; explicit activation boundary (only priorities admitted under a consuming policy version are consumable); no silent activation after policy-version changes (AC-12); dispatch-round TTL semantics with TTL starting at consumability (AC-13).

**Explicit attack-C risk acceptance (on record):**

> Director priority is intentionally granted scheduler-shaped authority above the epistemic dimensions, but that authority is bounded to the already-eligible set and cannot create eligibility or bypass any epistemic, lifecycle, dependency, budget, or evidence gate.

This is an intentional architectural decision. Q-02 is NOT silently rewritten: Q-02 §11.5's literal precedence is implemented as ratified text, with the bounds above recorded as the ratified refinement of the mechanism Q-02 §18.2 pre-carved ("IF a ratified override mechanism is ever built, it ranks above the policy"). The ratification of a consuming `policy_version` at Step 7 is the ratification surface for the mechanism's activation; until then, admitted priorities are inert audit records and the mechanism is off by default.

### 6.2 Decision 2 — C1 Slot Vocabulary: FULL-HISTORY RATIFIED

**RATIFIED: the FULL-HISTORY slot vocabulary.** The `slot_ref` vocabulary is the union of slot references appearing across the project's complete supersession history. The vocabulary is:

- **append-only**
- **never implicitly retired**
- **project-scoped**
- **historically deterministic** (a pure function of the project's immutable program rows; replay-stable)
- **used for mutation identity** (F2: same slot, new mechanism is recognizable)
- **compatible with resurrection screening** (the S7 consumer needs retired slots)

**The LIVE-CHAIN interpretation is explicitly REJECTED.** Rationale (on record):

> A live-chain-only vocabulary would allow a previously abandoned research concept to disappear from the vocabulary. A later legitimate re-exploration would then require a new label for the same conceptual slot, undermining mutation identity and weakening resurrection screening. Therefore: **slot identity is historical, not merely live-chain scoped.**

**The C1 serialization rule is formally preserved:** `slot_ref` MUST NOT be serialized as `null` merely because the optional field is absent. The implementation must preserve the existing corpus hash (AC-1 Delta=0): the field is emitted only when non-None, per the C1 design §4.2.3. (The hazard was independently reproduced at the final gate: `canonical_json` serializes `None` values, so a naive emission would rehash the entire corpus.)

No implementation is performed by this ratification record.

### 6.3 Decision 3 — Deferred Dependencies: ACCEPTED

The operator formally accepts the following dependency state (full assessment: final gate §10):

- **S5 — invalidation cascade: DEFERRED.** S5 does not block ratification of the architecture. However, Fundamental #3 MUST NOT claim complete preserve-and-mutate operational behavior until S5 is implemented and verified.
- **S7 — refuted-registry / resurrection screen: DEFERRED.** C1's field contract and vocabulary may proceed independently. The resurrection-screening consumer MUST NOT be claimed operationally complete until S7 exists and is verified.
- **ModelClient / record-replay: PREREQUISITE FOR P4.** The future ModelClient path MUST inherit the existing untrusted-content boundary (M3) and epistemic safety rules. No implementation now.
- **P4 agent runtime: DEFERRED / IMPLEMENTATION-GATED.** Director/Researcher/Reconcile runtime remains unimplemented until the P4 prerequisites are satisfied. C5/C6 consumption MUST remain P4-gated.

Prohibited-claims discipline: until the relevant dependency lands, no document, agent, or report may claim the capability it gates. Absence is not retirement; deferral is not completion.

## 7. Accepted Deferred Dependencies

Recorded as accepted by Decision 3 (§6.3), with their sunset conditions:

| Dependency | Status | Boundary (what it gates) |
|---|---|---|
| **S5 invalidation cascade** | DEFERRED | Fundamental #3's preserve-and-mutate completeness claim; mature Q-04 (Step 10). IDR-017's ratified non-cascade contract remains in force until then |
| **S7 refuted-registry / resurrection screen** | DEFERRED | C1's §5.4 resurrection-screening consumer; any operational resurrection-screening claim |
| **ModelClient record/replay** | PREREQUISITE FOR P4 | Any LLM wiring in P4; must inherit the M3 untrusted-content boundary and epistemic safety rules (Step 5 adversarial gate) |
| **P4 agent runtime** | DEFERRED / IMPLEMENTATION-GATED | C5/C6 activation (Steps 7–8); the reconcile loop becoming real |

Also accepted as deferred (final gate §14): the budget ledger (attack E — ordering never reads spent budget), the real contradiction machinery (Step 11; C6 S3 emits `NOT_DERIVABLE` until it lands), blueprint §19 Q1/Q7–Q13 open questions, and the v6 CONTRA/Scientific-Skills candidate amendments.

## 8. Implementation Dependency Order

**FROZEN sequence** (ratified by the operator; each step remains separately chartered — ratification does NOT constitute permission to implement all steps automatically; do not reorder dependencies for convenience). The sequence uses the exact dependency logic established in `hermes_final_ratification_gate.md` §17 (Step 0 is already DONE — committed `bf5e67d`, 12 tests, suite 1513→1525 — and Step 2 of the gate's roadmap, the ratification record, is THIS document):

| Step | Deliverable |
|---|---|
| **STEP 1** | Provider/source closure (HR-04 normalization choke point confirmed across every provider adapter; per-adapter identifier-preservation tests; mutated-identifier-after-admission refusal) |
| **STEP 2** | C4 implementation (floor clause + `FloorGrantRecorded` event + diagnostics; `_task_ordering_key` UNCHANGED; AC-1..10 + joint C4×C5 matrix cells 1–2, 7) |
| **STEP 3** | C1 implementation (`HypothesisSpec.slot_ref` + E6 + vocabulary projection + schema-version bump; AC-1 Delta=0 corpus-rehash check is the gate) |
| **STEP 4** | S5/S7 architectural/implementation decision gate (implement now or record the accepted partial state with sunset conditions; S7 before the C1-§5.4 consumer, S5 before the P4 completeness claim) |
| **STEP 5** | P4 prerequisites including the ModelClient boundary (record/replay contract + M3 boundary-inheritance fixtures; Director/Researcher runtime CONTRACTS pinned against v6 §13) |
| **STEP 6** | P4 runtime implementation (replace Phase-0 stubs; reconcile loop real; all proposals still gateway-only; no-new-admission-path invariant re-verified against the live runtime) |
| **STEP 7** | C5 implementation (under ratified OPTION B: `PROPOSE_DIRECTOR_PRIORITY` + bounded consumption + `REVOKE_DIRECTOR_PRIORITY`; AC-1..14 incl. AC-12/13/14 structural fixtures; joint matrix cells 3–8) |
| **STEP 8** | C6 implementation (convergence digest section, `RECONCILE_DIGEST_VERSION` 4→5 with the six fixture pins updated atomically; AC-1..10) |
| **STEP 9** | Falsification execution (minimum execution substrate for decisive REFUTED; HR-07 full matrix against real executed results) |
| **STEP 10** | Mature Q-04 (cone over real invalidation; assumption-seeded cone walk; cone never invents impact beyond declared edge classes) |
| **STEP 11** | Advanced Research OS (real contradiction subsystem, portfolio projection, cross-domain generation, effort-normalization closure — each with its own design gate first) |

Every step: separately chartered, prerequisites enforced, adversarial gate + independent review per the final gate §17.

## 9. Architecture Freeze Rule

**HERMES ARCHITECTURE IS FROZEN** as of this ratification.

The ratified architecture consists of: the existing ratified v6 baseline; the Five Fundamentals; the C1 `slot_ref` contract; the C4 exploration-floor contract; the C5 bounded Director-priority contract (Option B); the C6 convergence-diagnostic contract; all explicitly ratified invariants and safety constraints (§5); and the dependency boundaries recorded above (§7–§8).

The architecture is now **the authority against which implementation must be evaluated**.

Future agents MUST NOT modify the architecture merely because:

- another design seems cleaner
- another mechanism seems interesting
- a speculative improvement is possible
- an optimization is attractive
- a new research idea appears
- implementation becomes inconvenient

**Architecture changes require a NEW explicit architecture amendment / ratification process.** Design iteration on the frozen surface is closed; effort now belongs to separately chartered implementation under the frozen contracts.

## 10. Falsification Exception

Architecture freeze does NOT mean architectural dogma. Future implementation or testing MAY demonstrate:

- an invariant is impossible
- a contract is internally contradictory
- an implementation exposes a prohibited authority path
- deterministic replay fails
- epistemic safety fails
- a hidden admission path exists
- a design assumption is empirically falsified
- a deferred dependency reveals an architectural contradiction

If that happens: **STOP implementation at the affected boundary. Open a new architecture amendment. Do NOT silently modify the ratified contract.** The falsification evidence path is the only legitimate route back to architecture change.

## 11. Non-Ratified Artifacts

Explicitly **NOT ratified** by this record (presence in the repository ≠ authority):

| Artifact | Governance status |
|---|---|
| `hermes_gr4_annealed_bridge_sampling_proposal.md` (GR4 annealed-bridge proposal) | **EXPERIMENTAL / PROPOSAL — NON-AUTHORITY.** Not incorporated into the frozen Five-Fundamentals architecture merely because the file exists. No GR4 implementation, no GR4 ratification, no scope expansion. It must independently complete the five-stage design/ratification loop before any architecture claim. Committed only as a cited design input (blueprint lines 19–22) |
| `P-BAYESIAN-PROTOCOL-01_reconciliation_record.md` (Bayesian Protocol-01) | **NON-AUTHORITY / SUBORDINATE — protocol-layer governance artifact.** It self-declares subordinate to v6 (protocol-layer only; not mechanism; not ADR finalization; no cross-layer override; ADR status NONE AUTHORIZED). This record confirms that disposition: it does NOT alter the Five-Fundamentals ratification and is not part of the ratified architecture. If it is ever intended to become permanent Hermes architecture, it requires a separate amendment/ratification decision — it is NOT silently ratified here |
| `FRESH_REDTEAM_AUDIT.md` | **HISTORICAL RECORD — NON-AUTHORITY.** Independent red-team audit (2026-08-15, target HEAD `f78bedd`); its findings are verified resolved in live source; retained as audit trail |
| v6 CONTRA candidate amendment (v6 §29) | **DESIGNED — not ratified.** Its own five-stage loop required |
| v6 Scientific-Skills candidate amendment (v6 §30) | **DESIGNED — not ratified.** Its own five-stage loop required |
| Blueprint §19 Q1, Q7–Q13 open questions | **OPEN — not resolved by this ratification.** Each needs its own design gate if pursued |
| C2, C3, GR4-reheat design experiments | **EXPERIMENTAL — not gated, not ratified** (blueprint §21, handoff §7) |
| Diagram Reference Pack | **BRAINSTORMING INPUT — NON-AUTHORITY** |

## 12. Governance Interpretation

The five governance states, distinguished canonically:

| State | Meaning | Applies to |
|---|---|---|
| **RATIFIED** | Formally approved as architecture authority by operator ratification; changes require a new amendment process (§9) | v6 approved slices (IDR-023); the Five-Fundamentals package + C1/C4/C5(Option B)/C6 contracts (THIS record); ratified IDRs; ratified invariants |
| **DESIGN** | Designed and reviewed but not ratified; not authority | v6 CONTRA (§29); v6 Scientific-Skills (§30); blueprint §19 open questions |
| **IMPLEMENTED** | Built and tested in `src/` — a state of execution, orthogonal to ratification: ratified contracts may be unimplemented (C1/C4/C5/C6 today), and implemented slices rest on ratified authority (v6 P2/P3) | v6 approved slices (RATIFIED + IMPLEMENTED); C1/C4/C5/C6 (RATIFIED, NOT YET IMPLEMENTED — implementation is Steps 2–8) |
| **DEFERRED** | Intentionally not built; explicitly gated with sunset conditions and prohibited-claims discipline (§7) | S5, S7, P4 runtime, ModelClient, budget ledger, contradiction machinery, v6 §28.5 slices |
| **EXPERIMENTAL** | Proposal/design-experiment status; below DEFERRED in authority order; must pass the five-stage loop before any claim | GR4 proposal, C2/C3/GR4-reheat, diagram pack |

**Reading rule for future agents:** a document's self-declared status + this record govern. Ratified contracts bind implementation; DESIGN documents propose; DEFERRED items gate claims, not architecture; EXPERIMENTAL artifacts confer no authority. Where any future document conflicts with this record, this record prevails until amended via §9/§10.

---

*End of Hermes Architecture Ratification. Recorded at `main` = `ccb685d` (pre-commit), 2026-08-20, by operator ratification. The architecture-design loop is CLOSED: RATIFY → RECORD → FREEZE → VERIFY → STOP.*
