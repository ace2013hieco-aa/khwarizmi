# HR-07: the decisive REFUTED input contract — what may produce a decisive
# falsification

**Status:** CONTRACT PINNED + CURRENT PATH HARDENED + TESTED (2026-08-19).
The future falsification-experiment engine remains **DEFERRED**; this IDR
pins the exact epistemic inputs allowed to produce a decisive REFUTED
transition as a CURRENT SAFETY CONTRACT, because live code for decisive
falsification classification and Evidence Ladder REFUTED application already
exists.

**Date:** 2026-08-19
**Covers:** the ratified falsification predicate
`certifies_decisive_falsification` (`src/hermes/research/failure_classification.py:879`),
both REFUTED drivers of the Evidence Ladder APPLY pass
(`src/hermes/research/controller.py` `_apply_evidence_ladder_pass` —
Driver 1 proposal-ratified, Driver 3 bare-classification), the HR-07
head-binding hardening (`Controller._program_head_id` + the two driver
checks), and `tests/test_hr07_decisive_refuted_contract.py` (semantic safety
cases A–G + golden fixtures for every forbidden class + head binding).

---

## 1. The invariant

> The system MUST NOT treat a **declaration**, a **citation string**, an
> **explanation**, an **artifact type**, an **implementation failure**, a
> **resource failure**, an **environment mismatch**, or **UNKNOWN** as
> decisive scientific falsification by themselves.

A decisive REFUTED is the terminal evidence-state verdict that a hypothesis
has been falsified. It is reachable ONLY through the complete current
contract (§3), never through any single one of its inputs alone.

## 2. Reconciliation (the six questions, answered from current code)

1. **What can currently produce REFUTED?** Exactly two live drivers, both
   inside the Evidence Ladder APPLY pass (`_apply_evidence_ladder_pass`):
   - **PATH A — proposal-shaped:** an admitted
     `EvidenceTransitionProposed` (to_state=REFUTED) carrying a
     `ratification_ref` that re-verifies as an APPROVED `REJECT_BRANCH`
     classification-action proposal (Driver 1).
   - **PATH B — bare Q-05 classification:** a digest-valid,
     content-consistent `failure_classification` artifact whose class is
     `DECLARED_CONSTRAINT_VIOLATION` citing the hypothesis's OWN declared
     falsification condition (Driver 3, IDR-041 AC-2).
   Nothing else writes the REFUTED rung.
2. **What is deterministic?** The falsification predicate
   (`certifies_decisive_falsification`), the content-integrity re-derivation
   (F13), the digest-valid identity check, the target dereference, the
   deterministic transition ids, and the APPLY pass ordering. All derived,
   never stored (F2).
3. **What is merely advisory?** The `FailureClassification` record itself is
   advisory (D8): it is outside every citable evidence-type set and can
   never be falsifying evidence. It becomes decisive ONLY through the
   ratified predicate + the APPLY pass's re-verification.
4. **What is human-ratified?** PATH A's approval: the
   `ClassificationActionDecision` (APPROVED) on a `REJECT_BRANCH` proposal.
   `REJECT_BRANCH` is authority-shaped, so the proposal is admitted as
   PENDING_HUMAN_APPROVAL and cannot become executable without a ratified
   operator decision. PATH B needs no proposal — the ratified classification
   record IS the falsification fact (IDR-041 AC-2).
5. **What is executed evidence?** The classification's cited
   `evidence_refs` — typed artifact refs that must dereference in-project
   and be reachable from the producing falsification task via §14
   `derived_from` edges (D4). These are the falsifying-evidence artifacts.
6. **What is currently only a classification/citation assertion?** The
   decisive link itself: "the result contradicts the declared falsification
   condition." Today this is asserted by the classification's
   `constraint_ref` citation and certified by the ratified predicate — there
   is NO executed falsification-RESULT type yet (§9 honest gap).

## 3. The exact admissible chain (current contract)

```text
digest-valid, content-consistent Q-05 classification artifact
    class == DECLARED_CONSTRAINT_VIOLATION          (the one falsification-shaped class)
    constraint_ref == hypothesis:<H>:falsification_condition   (the hypothesis's OWN condition)
    program_ref dereferences to the project's CURRENT program HEAD   (HR-07 head binding)
    hypothesis <H> dereferences in that program
    content integrity: metadata re-derives the row's content hash    (F13)
    identity: classification_id == artifact identity                 (digest-valid)
        ↓
    decisive falsification
        ↓
    REFUTED  (terminal rung; PATH B also emits RefutedApplied)
```

For PATH A the chain additionally requires the ratified approval leg:

```text
EvidenceTransitionProposed (to_state=REFUTED, ratification_ref)
    ratification_ref re-verifies as APPROVED REJECT_BRANCH
    action is in the classification's permitted set (recomputed, F2)
    classification dereferences to a project hypothesis on the CURRENT head
        ↓
    REFUTED
```

### Trusted vs re-derived vs externally supplied

| Input | PATH A (proposal) | PATH B (bare classification) |
|---|---|---|
| **trusted** | nothing — every leg re-verified at APPLY | nothing |
| **re-derived** | ratification (APPROVED decision + permitted-action recomputation), target dereference, content integrity | class membership, predicate, content integrity (F13), identity, head binding, hypothesis dereference |
| **externally supplied** | the proposal + the operator decision + the classification record | the classification record (LLM-proposed, validator-admitted) |
| **evidence** | the classification's dereferenceable `evidence_refs` | same |
| **authorization** | the APPROVED `REJECT_BRANCH` decision (human-ratified) | the ratified classification record itself (IDR-041 AC-2) |
| **falsification** | the ratified predicate over class + citation | the ratified predicate over class + citation |

## 4. Prohibited inputs (never REFUTED)

The following MUST NOT directly produce REFUTED — each is pinned by a
golden-fixture test:

| Prohibited input | Class | Why it is not falsification | Permitted instead |
|---|---|---|---|
| implementation failure (experiment crashed) | `IMPLEMENTATION_FAILURE` | the mechanism failed, the claim may still hold | `PROPOSE_MECHANISM_SUBSTITUTION` |
| resource exhaustion (stopped early) | `RESOURCE_CONSTRAINT` | absence of a completed run is not evidence against | `PARK_FOR_RESOURCE_REVIEW` |
| environment mismatch (regime not applicable) | `ENVIRONMENT_MISMATCH` | not a valid test of the hypothesis | `PROPOSE_SCOPE_NARROWING` |
| framing error (scope/methodology problem) | `FRAMING_ERROR` | a process/scope issue, not a result | `ROUTE_TO_SCOPE_REVIEW` |
| unknown / untestable | `UNKNOWN` | honest fallback; cannot refute | `ESCALATE_TO_DIRECTOR` |
| methodology-constraint violation | (citation shape) | a process failure, never a falsification | — |
| declaration / citation string / explanation alone | — | assertion without the ratified predicate | — |
| artifact type alone | — | type is not a result | — |

The structural guarantee is the `ACTION_MAP`
(`failure_classification.py:115`): only `DECLARED_CONSTRAINT_VIOLATION`
maps to `REJECT_BRANCH`, and only `REJECT_BRANCH` feeds a REFUTED
transition. Every other class's action set is proposal/review/escalation —
never decisive.

## 5. The falsification predicate (exact)

```python
certifies_decisive_falsification(failure_class, hypothesis_ref, constraint_ref)
    ==  (failure_class is DECLARED_CONSTRAINT_VIOLATION
         and constraint_ref == f"hypothesis:{hypothesis_ref}:falsification_condition")
```

Verified exact (brief §6): wrong hypothesis, wrong condition, methodology
constraint, every forbidden class, arbitrary citation, and missing citation
all return False. The predicate is pure, derived from the ratified taxonomy,
never a stored flag (F2).

## 6. HR-07 hardening — head binding (the gap found and closed)

**Gap (probe-confirmed):** before this IDR, a digest-valid decisive
classification citing a **superseded** program applied REFUTED to that
superseded program's hypothesis. The brief's §6 attack list requires
superseded-program → no REFUTED.

**Fix:** a decisive REFUTED must bind to the project's CURRENT epistemic
contract — the supersession-chain head (max-version program row, the same
selection `ResearchProgramRepository.current` uses). Both REFUTED drivers
now check `program.program_id == Controller._program_head_id(programs)`;
a superseded citation is a historical record, never a live falsification
(fail-closed, noted on PATH B; silent-None on PATH A's target resolution).
The head program still refutes (no over-restriction).

## 7. Future execution-result contract (DEFERRED — pinned, not built)

The future P4/P5 falsification-experiment engine MUST produce a validated
falsification-result record that the decisive predicate can consume. The
smallest future-proof contract, using existing identity discipline:

```text
FalsificationTestResult
    test_id                        # the executed falsification test
    hypothesis_ref                 # binds to the program hypothesis
    falsification_condition_ref    # hypothesis:<H>:falsification_condition
    program_ref                    # MUST be the current head at apply time
    execution_id                   # the run that produced the result
    result_class                   # closed vocabulary (below)
    result_payload_hash            # content hash of the executed result
    policy_version                 # validator/policy that judged it
    produced_artifact_refs         # the executed-evidence artifacts
    deterministic identity         # content-derived id (EC-V6)
    provenance                     # §14 edges to the producing task
```

Result-state vocabulary (the decisive distinction is **VIOLATED ≠ task
FAILED** — a failed experiment is not automatically a false hypothesis):

| State | Meaning | Decisive? |
|---|---|---|
| `VIOLATED` | the executed result contradicts the declared condition | the only decisive state |
| `MET` | the result satisfies the condition | never refutes |
| `UNTESTABLE` | missing data / invalid methodology | never refutes (→ UNKNOWN/escalate) |
| `INCONCLUSIVE` | the run did not decide | never refutes |

Integration note: when this substrate lands, PATH B's decisive input should
require a dereferenceable `VIOLATED` `FalsificationTestResult` covering the
cited falsification condition (the M1/HR-02 verdict-coverage pattern —
content validation gates the decisive fact, never a bare citation). Until
then, the current contract (§3) is the binding safety boundary.

## 8. Identity, provenance, versioning, replay

- **Identity:** classification `classification_id = fc_<content_hash[:24]>`
  (derived, never authored — EC-V6); transition ids are deterministic
  (`classification_transition_id` / `ratification_transition_id`), so the
  APPLY is idempotent across crashes and replays (AC-1/AC-4).
- **Provenance:** §14 `cites` edges to the falsifying evidence + a
  `derived_from` edge to the producing falsification task (D4); the ladder
  row records `classification_ref` / `proposal_id` / `ratification_ref`.
- **Versioning:** `classifier_version` enters the classification identity —
  a reclassification under a new version is a NEW record, never a mutation.
- **Replay:** the APPLY pass re-derives everything from the journal + rows;
  a replayed pass re-derives the same transition ids and writes nothing new.
- **Stale-result behavior:** a classification against a superseded program
  is stale by construction — head binding (§6) refuses it. A tampered
  cache hiding an applied REFUTED is healed with a note (F12), never silent.
- **Cross-project binding:** classifications are project-scoped (D1); the
  target dereference is in-project only — a foreign program/hypothesis
  applies nothing.

## 9. The honest gap (brief §9)

> The current REFUTED path is architecturally constrained but still
> dependent on a future validated falsification-result substrate.

The current system has **no executed falsification-result type**. The
decisive input today is a ratified classification record — constrained by
class + citation + content integrity + head binding + dereference, but the
"result contradicts the declared condition" link is asserted by the
classification, not yet witnessed by an executed, validated test result.
This IDR does NOT pretend the Q-05 classification is equivalent to an
executed experiment; §7 pins the contract the future engine must satisfy.

## 10. Adversarial / semantic safety tests
(`tests/test_hr07_decisive_refuted_contract.py`)

- **Predicate exactness** — only the exact class + own-condition citation
  is decisive; every forbidden class, methodology constraint, wrong
  hypothesis, arbitrary/missing citation is non-decisive.
- **Golden fixtures** — one per forbidden class
  (IMPLEMENTATION_FAILURE / ENVIRONMENT_MISMATCH / RESOURCE_CONSTRAINT /
  FRAMING_ERROR / UNKNOWN), each carrying a falsification-condition
  citation, each asserting NO REFUTED.
- **A** implementation failure (crashed experiment) → NOT REFUTED.
- **B** resource exhaustion (stopped early) → NOT REFUTED.
- **C** environment mismatch (regime not applicable) → NOT REFUTED.
- **D** valid decisive falsification → REFUTED (positive path,
  ratified_by=classification).
- **E** condition satisfied (no violation citation) → NOT REFUTED.
- **F** untestable/UNKNOWN and FRAMING_ERROR → NOT REFUTED.
- **G** forged result (content-hash mismatch) and forged identity → NOT
  REFUTED.
- **Head binding** — superseded program via PATH B → NOT REFUTED; via the
  fully ratified PATH A chain → NOT REFUTED; current head → still REFUTED.

## 11. No experiment engine

This IDR pins the epistemic contract. It does NOT implement browser
experimentation, a Python experiment runner, a backtest engine, a
statistical executor, or a model-based falsification engine. Those systems,
when built, MUST obey §3 (current) and §7 (future result substrate).
