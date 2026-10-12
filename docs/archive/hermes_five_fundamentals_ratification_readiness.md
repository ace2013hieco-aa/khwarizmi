# HERMES FIVE-FUNDAMENTALS — RATIFICATION READINESS + IMPLEMENTATION ROADMAP

**Date:** 2026-08-20
**Repo:** `ace2013hieco-aa/khwarizmi-research` @ `main` = `8f011a3` (verified:
`git rev-parse HEAD`, in sync with `origin/main`, 0/0 divergence)
**Charter:** pre-P4 architecture readiness + epistemic safety gate
(2026-08-20 brief). This document is the ratification-ready record the
brief §14 requires. **Nothing here implements the roadmap** — per the
brief's §17 stop condition, this task verifies, remediates at the design
level, resolves contradictions, and STOPs.

**Verification gates executed for this document (all live, 2026-08-20):**

| Gate | Result |
|---|---|
| `scripts/run_tests.py` | **1513 passed** in 357.12s |
| `uvx pyright src/` | **0 errors, 0 warnings** |
| `uvx ruff check src/ tests/` | **All checks passed** |
| `git status` | clean except 3 deliberately-untracked files (`.freebuff/`, `FRESH_REDTEAM_AUDIT.md`, `hermes_gr4_annealed_bridge_sampling_proposal.md`) |

---

## A. Blueprint status

`hermes_five_fundamentals_blueprint.md` (commit `783831b`): **reviewed,
corrected, UNRATIFIED.**

> **Ratification update (2026-08-20, additive):** the package was
> subsequently RATIFIED by operator ratification —
> `hermes_architecture_ratification.md` (architecture frozen; the §16
> roadmap's Step 0 is DONE at `bf5e67d`, Step 2 is the ratification
> record itself). The status line above is the historical pre-ratification
> record and is preserved unchanged. It completed a full adversarial audit (attacks
A–R), four independent review passes, and a transcript-verified re-grade
(§27) that retracted the unverified original verdict (§26.1 retraction).
Its §19 open questions Q2/Q3/Q4/Q6 are resolved by the four design gates
(C1/C4/C5/C6); Q1, Q5, Q7–Q14 remain open architecture questions (§J).

**Verified runtime state (not trusted from the handoff — re-checked live):**

- The Director/Researcher/Adversary/Implementer agent runtimes are ALL
  4-line Phase-0 placeholders (`src/hermes/agents/*.py`, each 4 lines,
  "Not implemented until P4"). `reconcile.py` is a 6-line Phase-0 stub.
  The controller's tick IS the current reconcile loop (blueprint F4).
- S5 invalidation cascade: **no implementation in `src/`** (grep: zero
  cascade/invalidation machinery).
- S7 refuted-registry screen: **no implementation in `src/`** (grep: zero
  resurrection/screen machinery).
- Contradiction machinery: `CONTRADICTION_DETECTED` exists only as an enum
  declaration (`events.py:59`) with **zero emitters**; `contradiction_reduction`
  is hardcoded NONE (`task_obligations.py:124`); `CONTRADICTION_RESOLUTION`
  is declared-but-deferred and NOT LLM-proposable (`intents.py:42–49`).

## B. Corrected audit tally

**5 solved outright / 10 solved partially / 3 solved only if candidate
extensions land** (blueprint §27.2, transcript-verified 2026-08-19):

- Outright (5): D, I, N, O, R.
- Partially (10): B, C, E, F, G, H, J, K/L, M, Q.
- Only-if-extensions (3): A + the K/L residual.

The correction downgraded five attacks whose cited defenses are DEFERRED
subsystems, not implemented ones: G (S5 cascade), E (budget ledger), Q
(ModelClient record/replay), F and M (S7 refuted-registry screen). The
central claim survives: **no attack exposes a conflict with a ratified
invariant; the five fundamentals introduce no new admission path.**

## C. C1 decision — `slot_ref` (gate `7eab07b`, HOLDS WITH CAVEATS)

**Ratification note: FULL HISTORY vs LIVE CHAIN** (brief §9).

- **Exact wording conflict.** Blueprint §21 F-B (lines 1806–1809): a
  `slot_ref` "must either already exist in the supersession chain or be
  declared new with rationale." C1 §4.3 rules the slot vocabulary is the
  union of `slot_ref` values over ALL program versions in the project's
  supersession history — **append-only, slots never retired.**
- **Attack demonstrating why LIVE CHAIN fails.** Under the live-chain-only
  reading, when a lineage is abandoned (a trajectory REFUTED or dropped),
  its slots retire. A later program that re-explores the same design
  concept must then "declare new" a label for a concept that already has
  one — minting a second label for one concept. This defeats mutation-
  identity (F2), trajectory labeling (F4), and — decisively — the
  blueprint's OWN stated payoff for C1: resurrection screening (F6,
  blueprint lines 1795–1798). A retired vocabulary makes legitimate
  resurrections undeclarable and illegitimate ones unrecognizable.
- **Chosen interpretation: FULL HISTORY (append-only).** Consistent with
  resurrection screening (the consumer needs retired slots), content
  identity (slot participates in `content_hash`; vocabulary decisions are
  pure functions of immutable rows), supersession semantics (rows are
  immutable and append-only — IDR-041 §4/F14 precedent), and historical
  determinism (replay-stable: the vocabulary at any point is a function of
  the rows that exist then).
- **Consequences.** "Declare new" is valid only for a label NOT in the
  full-history vocabulary; re-declaring an existing slot is rejected
  (`E6_SLOT_ALREADY_DECLARED`). The vocabulary grows monotonically per
  project.
- **Versioning implications.** None for existing programs (the field is
  optional; AC-1 pins that a naive None-addition would rehash the corpus —
  the mitigation emits `slot_ref` only when non-None). `PROGRAM_SCHEMA_VERSION`
  bumps at implementation.
- **Decision required:** ratify FULL HISTORY explicitly (do not inherit it
  silently). The gate flags this in §7.1 and permits overrule only together
  with an alternative resurrection-screening mechanism.

## D. C4 decision — exploration floor (gate `486c5dc` + remediations, HOLDS WITH CAVEATS)

**Recommendation: APPROVE for implementation (Step 3) after blueprint
ratification.** Verified properties: the ratified `_task_ordering_key` is
NOT modified (floor permutes its output under a versioned clause); no
scalar/weight/composite (attack D intact); never reads spent budget (attack
O intact); F-C decay/kill-switch is a derived counter over append-only
`FloorGrantRecorded` events + satisfaction links (no stored state); the
cross-check substrate defect (transient ranking cited as durable record)
was found and fixed (`e3091e8`). The joint C4×C5 test matrix (8 cells) is
now pinned in C4 §4.5. One open parameter: F-C mode choice (decay vs
kill-switch default) — C4 §7.3, team decision at implementation charter.

## E. C5 decision — Director priority (gate `4b3c2b4` + remediations, HOLDS WITH CAVEATS)

**Recommendation: ratify OPTION B (bounded), per the pre-P4 brief §10.**
Recorded in the gate as §2.6 (this task's design-level remediation):

```
Director priority > Q-02 epistemic ordering > cost > created_at > task_ref
```

**bounded to the already-eligible set**, with seven MUST-NOT bounds (no
eligibility change, no gate bypass, no dependency bypass, no budget bypass,
no Evidence-Ladder change, no task creation, no program-state mutation) and
two temporal safeguards:

1. **Policy activation boundary:** priorities admitted under a non-consuming
   policy version stay inert after a policy upgrade; only priorities
   admitted under a consuming version are consumable (re-proposal activates).
   Silent auto-activation is rejected as attack C by another path.
2. **TTL activation semantics:** TTL starts when the priority becomes
   consumable (first admission under a consuming version), not at inert
   proposal admission. Counting remains dispatch-round semantics (C5 §2.5;
   zero-claim rounds don't advance it).

New acceptance criteria pinned: **AC-12** (activation boundary), **AC-13**
(TTL activation), **AC-14** (bounded override structural fixtures).

**Honest record of the conflict:** the gate's original §2.2 recommended
Option A (below-dimensions) on attack-C grounds; the brief recommends
Option B-with-bounds as the ratified Q-02 §11.5 precedence. Both are fully
designed and visible. **The team must pick one explicitly at ratification —
this document recommends B-with-bounds.** The core distinction (admitted
proposal record, NOT a stored field on tasks) holds under either option and
threads Q-02 §14/§18.2.

## F. C6 decision — convergence diagnostic (gate `9765ecf` + remediations, HOLDS WITH CAVEATS)

**Recommendation: APPROVE the design; implementation is P4-gated.** C6 is a
read-only `convergence` section of `reconcile_digest` (v4→v5). Verified:
the digest's read-only posture is real (`controller.py:991–993` "nothing
here can act"); both observe→act loops consume digest sections by explicit
named key only, so a new section cannot flow in without new code; AC-6/AC-7
structural fixtures pin never-a-gate-input; the `NOT_DERIVABLE` for open
contradictions is genuinely honest (zero emitters exist). **Do not
implement contradiction emitters to make C6 appear richer** — the honesty
discipline IS the feature. The 4→5 version bump touches 6 concrete
`digest_version == "4"` pins in 4 test files (enumerated in C6 §7.5).

## G. Deferred dependencies (classified, NOT auto-implemented — brief §13)

| Dependency | Classification | Rationale |
|---|---|---|
| **S5 invalidation cascade** | **MUST PRECEDE full Fundamental-#3 operation; CAN REMAIN DEFERRED for C1/C4 implementation** | Q-05 classification + Q-04 cone are real today; the cascade is the missing failure-localization half. C4 (ordering-side) doesn't need it. C5/C6 consumption doesn't need it either, but the research runtime (P4) cannot claim preserve-and-mutate completeness without it. |
| **S7 refuted-registry screen** | **MUST PRECEDE C1's §5.4 resurrection consumer; CAN REMAIN DEFERRED for C1's field contract** | C1's field + E6 check + vocabulary are implementable without S7; the screen axis (§5.4) is an explicitly deferred consumer. S7 must land before the resurrection-screening payoff is claimed. |
| **P4 agent runtime** (director/researcher/reconcile) | **MUST PRECEDE C5/C6 activation (Step 8)** | C5/C6 consumption surfaces are Director-facing; the Director runtime is a 4-line stub. C4 is implementable against the controller alone (Step 3). |
| **Budget ledger (attack E)** | **CAN REMAIN DEFERRED** | Ordering never reads spent budget (attack O invariant); the ledger is a future audit surface, not a gate prerequisite. |
| **ModelClient record/replay (attack Q)** | **MUST PRECEDE P4 (Step 6 prerequisite)** | The untrusted-content boundary (M3) is enforced at the handler context today; the future ModelClient path must inherit it (Step 6 adversarial gate). |

**Dependency graph (implementation order, acyclic):**

```
Step 0 (safety test completion) ─┐
Step 1 (provider/source closure) ─┼→ Step 2 (RATIFICATION) ─→ Step 3 (C4) ─→ Step 4 (C1 field)
                                  │                                │
                                  │                                ├→ Step 5 (S5/S7 decision) ─→ S7 before C1-§5.4 consumer
                                  │                                │                            └→ S5 before P4 completeness claim
                                  └→ Step 6 (P4 prerequisites: ModelClient boundary, M3 inheritance)
                                       └→ Step 7 (P4 runtime) ─→ Step 8 (C5/C6 activation)
                                            └→ Step 9 (falsification execution) ─→ Step 10 (mature Q-04) ─→ Step 11 (advanced Research OS)
```

## H. Immediate safety remediations (brief §2–§8 — verified status)

All seven items were verified against live source (not trusted from commit
messages). **All seven are CLOSED in source with adversarial tests.** Three
precise test-coverage gaps remain and are assigned to Step 0.

| Item | Status (verified live) | Evidence | Gap |
|---|---|---|---|
| **M1/HR-02** satisfaction ≠ artifact class | **CLOSED** (`54c5c56`) | `persistence/program_obligations.py`: satisfaction link requires a dereferenceable PASS validation verdict covering the artifact's content hash; 22 adversarial tests (forged requirement ref, foreign artifact, wrong class, foreign program, forged link w/o verdict, tampered input hash, project-scoping, corrupt program row, append-only) | **empty-artifact test missing** (brief §2 list item 1) |
| **HR-03** surface honesty | **CLOSED** (`7847b71`) | `intents.py`: `CONTRADICTION_RESOLUTION` NOT in `llm_proposable()` (verified the frozenset body); regression test `test_gateway.py:437–455` | none |
| **M3** untrusted-content boundary | **CLOSED** (`aea1cbe`, `7783ec0`) | `security/boundaries.py` `UntrustedContent` envelope; controller envelops fetched/search text before the handler context (`controller.py:3181–3183`); `test_boundaries.py` (6 tests: no payload in str/repr, interpolation yields marker, no silent coercion, explicit unwrap only) | **the five named injection fixtures missing** (prompt injection in source text, malicious metadata, instructions in retrieved doc, fake system message, tool-call-like payload) — envelope semantics tested, payload-level fixtures not yet |
| **HR-05/M4** claim admission | **CLOSED** (`7783ec0`) | `claims.py:60–83` closed 6-state vocabulary (DIRECT/PARTIAL/INFERRED/SPECULATIVE/CONTRADICTED/UNSUPPORTED); span-dereference protocol (`claims.py:293+`); `test_claims.py` (missing/unknown support_state rejected, causal-DIRECT requires experiment source, fabricated span rejected, resolving span admits) | none material |
| **HR-08** completion invariant | **CLOSED** (`a983623`) | `completion.py` pure eligibility predicate; enforced inside `ProjectRepository.transition_lifecycle` (the single lifecycle write path); 13 tests covering ALL six brief-required cases (terminal+missing, gates+missing, budget+missing, noREADY+missing, full-satisfaction permit, corrupt program/ladder denial) | none |
| **HR-07** decisive REFUTED contract | **CLOSED** (`f3603b9`) | `failure_classification.py:879` `certifies_decisive_falsification`; head-binding enforced at BOTH REFUTED drivers (`controller.py:2345`, `:2558`); 14 tests (IMPLEMENTATION_FAILURE/RESOURCE/ENVIRONMENT/FRAMING/UNKNOWN all not-REFUTED, forged content hash, forged identity, superseded-program both paths) | **foreign-project rejection test missing** (brief §7 list item 10) |
| **HR-04** scholarly identifier preservation | **CLOSED** (`ef2b9e4`) | `tools/providers/normalize.py` canonical normalization choke point at walk admission; `docs/idr/hr04_source_identifier_capture.md`; 20 tests (DOI variants converge, arXiv version stripped, provider-native preserved verbatim but NOT universal identity, missing identifiers still admissible, identifier mutation after admission refused) | none |

**Step 0 = close the three gaps** (empty-artifact test; five M3 injection
fixtures; HR-07 foreign-project test). These are test-only additions — no
production-code change expected unless a fixture exposes a real hole (which
would then be chartered explicitly).

## I. Exact implementation sequence

See §16 roadmap below (Steps 0–11). Summary: **Step 0 safety tests →
Step 1 provider closure → Step 2 RATIFICATION → Step 3 C4 → Step 4 C1 →
Step 5 S5/S7 decision → Step 6 P4 prerequisites → Step 7 P4 runtime →
Step 8 C5/C6 → Step 9 falsification execution → Step 10 mature Q-04 →
Step 11 advanced Research OS.**

## J. Remaining unresolved architecture questions

1. **C5 §2.2 Option A vs Option B** — this document recommends B-with-bounds
   (§E); ratification must pick explicitly. (C5 §7.1, §2.6)
2. **C1 vocabulary scope** — FULL HISTORY recommended (§C); ratify explicitly.
   (C1 §7.1)
3. **C5 TTL default** (`priority_ttl_rounds`) — open; propose tens of
   dispatch rounds, versioned. (C5 §7.3)
4. **C5 TTL calendar-round alternative** — dispatch-round semantics pinned;
   calendar-round decay would need a new per-round marker event. (C5 §7.6)
5. **SUSTAIN necessity** — 3-value vs 2-value enum. (C5 §7.4)
6. **C4 F-C mode default** — decay vs kill-switch. (C4 §7.3)
7. **Active-trajectory bound (§19 Q5)** — admission-side cap; interacts with
   C5 (priority must not imply admission). (C5 §7.5)
8. **S5/S7 sequencing** — accept partial failure-localization until they
   land, or sequence them ahead of the portfolio layer. (§G, blueprint §19 Q14)
9. **Blueprint §19 Q1** (portfolio carrier P1-a vs P1-b), **Q7–Q13** —
   unchanged, still open.
10. **Per-instance ratification fallback for C5** — EFFECTIVE-on-admission
    chosen; fallback is per-instance PENDING_HUMAN_APPROVAL. (C5 §7.2)

## K. Proposed ratification wording

> **RATIFICATION — Five-Fundamentals package (pending architecture-team
> approval):**
>
> 1. The five-fundamentals blueprint (`783831b`) is ratified with its
>    corrected 5/10/3 audit tally (§27) and its honest partial states
>    (S5/S7 deferred; P4 runtime unbuilt).
> 2. C1 (`slot_ref`) is ratified with the **FULL-HISTORY append-only slot
>    vocabulary** reading (over blueprint §21 F-B's ambiguous "supersession
>    chain" wording), per the C1 gate §4.3/§7.1.
> 3. C4 (exploration floor) is ratified as designed, including the
>    `FloorGrantRecorded` event as the one flagged catalog addition, and
>    approved for implementation (Step 3).
> 4. C5 (Director priority) is ratified with **OPTION B bounded precedence**
>    (priority > epistemic ordering > cost > created_at > task_ref, within
>    the already-eligible set), the seven MUST-NOT bounds, and the two
>    temporal safeguards (activation boundary + TTL-at-consumability), per
>    C5 §2.6. Implementation deferred to Step 8 (P4-gated).
> 5. C6 (convergence diagnostic) is ratified as a read-only, never-a-gate-
>    input advisory surface with the `NOT_DERIVABLE` honesty discipline.
>    Implementation deferred to Step 8 (P4-gated).
> 6. The three Step-0 test gaps (§H) are closed before any gate
>    implementation begins.
> 7. No production code is changed by this ratification; each step of the
>    roadmap requires its own implementation charter.

---

## 16. IMPLEMENTATION ROADMAP (Steps 0–11)

Every step: prerequisites / deliverable / tests / adversarial gate /
independent-review requirement. **This roadmap is NOT chartered by this
task — it awaits the architecture team's review (§17).**

### Step 0 — Immediate epistemic safety test completion
- **Prerequisites:** none (main is green: 1513 passed, pyright/ruff clean).
- **Deliverable:** the three §H gaps closed — (a) M1 empty-artifact
  adversarial test; (b) the five M3 injection fixtures (prompt injection in
  source text, malicious metadata, instructions embedded in retrieved doc,
  fake system message, tool-call-like payload inside evidence) proving they
  remain data, not authority; (c) HR-07 foreign-project rejection test.
- **Tests:** the additions themselves; full suite stays green.
- **Adversarial gate:** each injection fixture must reach a judgment surface
  and be shown to produce NO satisfaction/evidence/REFUTED/task-mutation/
  gate-approval effect.
- **Independent review:** not required (test-only, bounded).

### Step 1 — Provider/source identity closure
- **Prerequisites:** Step 0.
- **Deliverable:** confirm HR-04's canonical normalization choke point
  covers every provider adapter before historical provider closure; no new
  lineage graph, no DOI resolver, no embeddings (HR-04 pinned constraints).
- **Tests:** per-adapter identifier-preservation tests (DOI/PMID/PMCID/
  arXiv/OpenAlex/provider-native); missing-identifier-still-valid.
- **Adversarial gate:** a provider returning a mutated identifier after
  admission must be refused (`test_j` pattern extended per adapter).
- **Independent review:** recommended (last chance before provider closure).

### Step 2 — Five-Fundamentals ratification
- **Prerequisites:** Steps 0–1; this readiness document reviewed.
- **Deliverable:** the §K ratification wording decided (ratify/reject each
  of blueprint, C1-reading, C4, C5-option, C6); decisions recorded as an
  IDR or ratification record per repo convention.
- **Tests:** n/a (governance step).
- **Adversarial gate:** every §J open question has an explicit disposition
  (decided or explicitly deferred) — no silent inheritance.
- **Independent review:** REQUIRED (this is the authority transfer).

### Step 3 — C4 exploration floor
- **Prerequisites:** Step 2 ratification (C4 approved); C4 gate ACs 1–10.
- **Deliverable:** the floor clause in/around `evaluate_eligible_tasks`;
  `FloorGrantRecorded` event; `FLOOR_INERT`/`FLOOR_GRANTED` diagnostics;
  floor parameters in the policy version triple. `_task_ordering_key`
  UNCHANGED.
- **Tests:** C4 AC-1..AC-10; joint C4×C5 matrix cells 1–2, 7 (no-priority
  cells).
- **Adversarial gate:** structural fixtures — ordering key unchanged, no
  scalar, no spent-budget read, no eligibility change, cap never expanded.
- **Independent review:** REQUIRED (first ordering-policy mutation since Q-02).

### Step 4 — C1 `slot_ref` field contract
- **Prerequisites:** Step 2 ratification (C1 FULL-HISTORY reading); C1 gate
  ACs 1–8.
- **Deliverable:** `HypothesisSpec.slot_ref` (optional, non-None-only in
  `_h_to_dict`); `_draft_from_payload` parsing; E6 check; slot-vocabulary
  projection; `PROGRAM_SCHEMA_VERSION` bump. No migration (TEXT column).
- **Tests:** C1 AC-1..AC-8 — AC-1 (Delta=0: no existing program rehashes)
  is the gate.
- **Adversarial gate:** corpus-wide rehash check on the existing program
  rows; dual-consumer deserializer tolerance (pre-C1 rows missing the key).
- **Independent review:** REQUIRED (identity-chain mutation).

### Step 5 — S5/S7 prerequisite decision
- **Prerequisites:** Steps 3–4 landed or chartered.
- **Deliverable:** explicit sequencing decision — S5 (invalidation cascade)
  and S7 (refuted-registry screen): implement now, or accept the partial
  failure-localization state with a recorded sunset condition. S7 MUST
  precede C1's §5.4 resurrection consumer; S5 MUST precede the P4
  completeness claim.
- **Tests:** n/a (decision step) — but if implemented, each gets its own
  gate with ACs.
- **Adversarial gate:** the decision must name what is NOT true until S5/S7
  land (no overclaiming preserve-and-mutate completeness).
- **Independent review:** REQUIRED if implemented; recommended for the
  deferral decision.

### Step 6 — P4 runtime prerequisites
- **Prerequisites:** Step 5 decision; M3 boundary verified.
- **Deliverable:** the ModelClient record/replay contract (attack Q) and
  the guarantee that the future ModelClient path inherits the M3
  untrusted-content envelope; the Director/Researcher runtime CONTRACTS
  (not implementations) pinned against v6 §13.
- **Tests:** boundary-inheritance fixtures for the ModelClient path.
- **Adversarial gate:** no model output can become satisfaction/evidence/
  REFUTED/task-mutation/gate-approval without the deterministic contracts.
- **Independent review:** REQUIRED (security boundary before LLM wiring).

### Step 7 — P4 research runtime
- **Prerequisites:** Step 6; separately chartered (NOT by this task).
- **Deliverable:** the Director/Researcher agent runtimes replacing the
  Phase-0 stubs; the reconcile loop real; all proposals still gateway-only.
- **Tests:** runtime integration suite; gateway admission unchanged.
- **Adversarial gate:** the five fundamentals' no-new-admission-path
  invariant re-verified against the live runtime.
- **Independent review:** REQUIRED.

### Step 8 — C5/C6 activation
- **Prerequisites:** Step 7 (Director runtime live); Step 2 ratification
  (C5 option decided, C6 approved); C5 ACs 1–14, C6 ACs 1–10.
- **Deliverable:** `PROPOSE_DIRECTOR_PRIORITY` intent + consumption under
  the ratified option; the `convergence` digest section (v4→v5, 6 fixture
  pins updated); `REVOKE_DIRECTOR_PRIORITY` operator channel.
- **Tests:** C5 AC-1..AC-14 (incl. AC-12/13/14 temporal safeguards);
  C6 AC-1..AC-10; joint C4×C5 matrix cells 3–8.
- **Adversarial gate:** activation-boundary test (inert priority survives a
  policy upgrade unconsumed); bounded-override fixtures (all seven MUST-NOTs);
  convergence never-a-gate-input structural fixtures.
- **Independent review:** REQUIRED (priority is the highest attack-C surface).

### Step 9 — Falsification execution
- **Prerequisites:** Step 8; HR-07 contract live.
- **Deliverable:** the experiment-execution path that produces the validated
  test results HR-07's decisive-falsification contract consumes (declared
  falsification condition + executed/validated result + result identity +
  content hash + provenance + policy/version). NOT an experiment engine —
  the minimum execution substrate for decisive REFUTED.
- **Tests:** HR-07's full matrix against real executed results (forged
  hash/identity/condition/project all rejected).
- **Adversarial gate:** no non-falsification class can reach REFUTED
  through the new path.
- **Independent review:** REQUIRED.

### Step 10 — Mature Q-04 impact loop
- **Prerequisites:** Step 9; S5 decision from Step 5 landed.
- **Deliverable:** the Q-04 falsification-impact cone operating over real
  invalidation (S5) — assumption-seeded cone walk (§19 Q8 resolved).
- **Tests:** cone-walk determinism; impact localization on real REFUTED.
- **Adversarial gate:** the cone never invents impact beyond the declared
  edge classes.
- **Independent review:** REQUIRED.

### Step 11 — Advanced Research OS capabilities
- **Prerequisites:** Steps 9–10 stable; separately chartered.
- **Deliverable:** the deferred advanced surfaces (contradiction subsystem —
  the REAL one, with emitters and resolution routing; portfolio projection;
  cross-domain generation GX3; effort-normalization decision closure).
- **Tests:** per-subsystem gates (each gets its own design gate first —
  the contradiction subsystem is explicitly NOT chartered by this task).
- **Adversarial gate:** each new surface passes the no-unearned-epistemic-
  authority test: no artifact/claim/classification/proposal/priority/
  diagnostic becomes authority without its deterministic contract.
- **Independent review:** REQUIRED per subsystem.

---

## 17. STOP CONDITION — MET

This task STOPs here. Produced: this ratification-readiness package
(§A–§K) and the implementation roadmap (§16). Design-level remediations
made: C5 §2.6 (Option-B recommendation + bounds + temporal safeguards +
AC-12/13/14) and C4 §4.5 joint test matrix. **No roadmap step was
implemented.** The architecture team reviews M1, HR-03, M3, HR-05, HR-08,
HR-07, HR-04, C1, C4, C5, C6, and the S5/S7 dependencies, then separately
charters implementation.

**Final principle honored:** the goal of this package was not to make
Hermes more capable — it was to make Hermes safe enough that adding the
research engine cannot accidentally turn artifacts, claims, classifications,
proposals, priorities, or diagnostics into unearned epistemic authority.
All seven safety items are verified closed in source; three bounded test
gaps are enumerated for Step 0; only after that gate should Hermes enter P4.
