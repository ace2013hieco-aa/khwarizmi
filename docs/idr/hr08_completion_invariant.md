# HR-08: the research-completion invariant — operational termination is not
# epistemic completion

**Status:** IMPLEMENTED + TESTED — invariant pinned as a pure eligibility
contract and enforced at the single lifecycle write path (2026-08-18).
The future production lifecycle driver remains **DEFERRED**; this IDR pins
the completion precondition NOW so that no future driver can accidentally
implement `all tasks terminal + gates passed → COMPLETED` without checking
epistemic/research sufficiency.

**Date:** 2026-08-18
**Covers:** `src/hermes/research/completion.py` (the pure predicate
`can_complete_research` + the structured `CompletionEligibility` /
`CompletionDenial` verdicts), the HR-08 guard in
`src/hermes/persistence/repositories.py` (`ProjectRepository.transition_lifecycle`,
the single `REPORTING → COMPLETED` write path), and
`tests/test_hr08_completion_invariant.py` (negative cases A–G + the
positive path + the write-path guard).

---

## 1. The invariant

> A research project MUST NOT transition to `COMPLETED` merely because its
> tasks are terminal and its mandatory gates have passed. `COMPLETED`
> requires the valid satisfaction of every mandatory research obligation
> the project's current compiled program declares.
>
> **Operational termination is not epistemic completion.**

The following operational conditions are, each and together, **insufficient**
to establish research completion, and the contract deliberately does not
consult them:

| Operational condition | Why it is not completion |
|---|---|
| all tasks terminal | tasks are execution structure (v4 §7); a graph can finish with obligations unmet (evidence never produced, gates never passed) |
| mandatory gates passed | gates are necessary preconditions of transitions, not evidence that the §10.2 obligations were satisfied |
| budget exhausted | exhaustion is a resource fact about the run, not an epistemic verdict about the research |
| no READY tasks remain | absence of schedulable work is a scheduler state; work can be absent because it was never created |

## 2. Reconciliation (the five questions, answered from current code)

1. **Does a production `REPORTING → COMPLETED` driver currently exist?**
   No. `ProjectRepository.transition_lifecycle`
   (`src/hermes/persistence/repositories.py:197`) is the only lifecycle write
   path and has **zero production callers** — only tests invoke it.
   `src/hermes/research/reconcile.py` (the future driver's home) is a Phase-0
   placeholder.
2. **Which function owns that decision today?**
   Structurally, `transition_lifecycle` + `validate_transition`
   (`src/hermes/core/lifecycle.py`). Before this IDR the structural table
   check (`REPORTING → COMPLETED` ∈ `VALID_TRANSITIONS`,
   `lifecycle.py:113`) was the **only** precondition — zero epistemic checks.
3. **Does any current path already enforce an epistemic completion
   condition?** No. Nothing between `validate_transition` and the state
   UPDATE consulted programs, obligations, satisfaction links, gates, or
   refutation state.
4. **Is `COMPLETED` currently reachable in executable code?** Yes — any
   caller able to reach `transition_lifecycle` from `REPORTING` could write
   `COMPLETED` unconditionally (tests demonstrate the call shape, e.g.
   `tests/test_phase1_acceptance.py:83`, though those attempts are
   structurally invalid from `CREATED`).
5. **Which future component is expected to own the final decision?**
   The future production lifecycle driver (the reconcile loop / controller
   lifecycle pass) will decide **when** to attempt the transition. It remains
   deferred. This IDR pins **what must hold** whenever that attempt is made,
   at the single choke point every attempt must traverse.

## 3. Satisfaction semantics (existing contracts only — no new framework)

"satisfied" is defined exclusively by the ratified Hermes contracts:

- **`ResearchProgram.evidence_requirements`** — the DERIVED §10.2
  obligations of the project's **current** (supersession-chain head)
  compiled program (`research/programs.py`, IDR-018). No program ⇒ nothing
  to have completed ⇒ denial (`NO_PROGRAM`).
- **Satisfaction links** (IDR-038 §3.1,
  `persistence/program_obligations.py`) — and **only** links whose artifact
  carries a dereferenceable **PASS validation verdict** whose `input_hash`
  still covers the artifact's content hash (M1 / HR-02). Coverage is
  re-derived at read time; nothing stored is trusted. A bare artifact class —
  or a structurally-present but verdict-less link — can never satisfy a
  requirement.
- **Mandatory gate requirements** — the program's `gate_requirements`
  (the three mandatory human gates + integrity gates, `programs.py:151`),
  evidenced by `GatePassed` audit events on the gate tasks that carry the
  requirement in `spec.gate_requirement` (`research/task_plan.py:148`).
  Gate passage is **necessary but never sufficient**.
- **Refutation state** — a confirmatory hypothesis whose
  `evidence_ladder_state` record is the ratified `REFUTED` terminus
  (IDR-041, written only by the ladder APPLY pass from re-verified ratified
  input) has **not** been satisfied; refutation routes to revision (§6.1),
  never to completion (`HYPOTHESIS_REFUTED`).
- **Q-05 / proposal-ratification** — consumed indirectly: the REFUTED
  ladder record IS the ratified falsification fact; the predicate reads the
  recorded fact, never re-decides it.
- **Contradiction state** — no first-class contradiction table exists on this
  baseline; the refutation record is the available contradiction signal. If a
  contradiction registry lands, it becomes an additional denial source here.

Explicitly **forbidden** as satisfaction (audit HR-08):

- raw artifact existence;
- artifact class alone (the pre-M1 ladder flaw, HR-02);
- cached ladder state (F2: the stored rung row is a pass's own output, never
  a trusted input — the predicate reads only the REFUTED terminus, which is
  an append-only applied record, not a cached climb rung).

## 4. The contract

```python
can_complete_research(conn, project_id) -> CompletionEligibility
```

- **Pure & side-effect-free:** read-only queries against the project's own
  rows; no clock, no randomness, no writes, no LLM.
- **Project-scoped:** every query is keyed by `project_id`.
- **Deterministic:** identical DB state ⇒ identical verdict and identical
  denial list (denial subjects iterate program order / sorted missing
  classes).
- **Fail-closed:** a missing program, a corrupt program row, an unparseable
  gate spec, or an unverifiable link is a **denial**, never a silent pass.
- **Explainable:** every refusal carries structured `CompletionDenial`s —
  `code` (closed vocabulary: `NO_PROGRAM`, `PROGRAM_CORRUPT`,
  `HYPOTHESIS_REFUTED`, `REQUIREMENT_UNSATISFIED`, `GATE_NOT_PASSED`),
  `subject`, `requirement`, `explanation`, `suggested_next_action` — the
  `CompilationError` style (Part 2 §12).

## 5. Enforcement point (the choke point)

The guard lives in `ProjectRepository.transition_lifecycle`, inside the
`BEGIN IMMEDIATE` fence, immediately after `validate_transition` and before
the state UPDATE:

```python
if to_state == LifecycleState.COMPLETED:
    eligibility = can_complete_research(self._conn, project_id)
    if not eligibility.eligible:
        raise TransitionError(from_state, to_state,
            reason=f"HR-08 completion invariant not met — {codes}")
```

Properties:

- **Single choke point:** `transition_lifecycle` is the ONLY writer of
  `projects.lifecycle_state` (verified by grep — one `UPDATE projects SET
  lifecycle_state` in the codebase). No driver, current or future, can reach
  `COMPLETED` without traversing the guard.
- **Atomic:** the predicate runs while holding the write lock; a denial
  raises inside the transaction, the `except` path ROLLBACKs, and neither
  state nor event is written (the existing F-01 kill-resume contract).
- **Structural check preserved:** the v4 §6.1 table check still runs first;
  the invariant is an additional precondition, never a relaxation.
- **Non-COMPLETED transitions untouched:** FAILED / ABANDONED remain
  reachable unconditionally — operational termination of an unsuccessful
  project is legitimate; only the *success* terminus carries the epistemic
  precondition.

## 6. Failure semantics

A denied transition raises `TransitionError` whose `reason` enumerates every
denial code (`HR-08 completion invariant not met — REQUIREMENT_UNSATISFIED:h1;
GATE_NOT_PASSED:pre_live`). The DB is unchanged (ROLLBACK), no
`LifecycleTransition` event is appended, and the structured denials tell the
caller exactly which obligations to discharge. The predicate itself never
raises on bad data — it converts corruption into denials (`PROGRAM_CORRUPT`),
so the write path always fails with the domain error, never a raw parse
traceback.

## 7. Provenance requirements

Completion evidence must be journal- and row-verifiable:

- satisfaction: `program_requirement_satisfactions` rows (append-only,
  content-derived ids) joined to `artifacts` and `validation_verdicts`
  (PASS, input-hash covering content hash);
- gates: `GatePassed` events joined to the gate task whose `spec_json`
  carries the `gate_requirement`;
- refutation: the `evidence_ladder_state` REFUTED row (append-only, written
  only by the ratified APPLY pass);
- the transition itself: the `LifecycleTransition` event records
  `from_state=REPORTING`, `to_state=COMPLETED`, `caused_by`, `reason`.

## 8. Future-driver integration point

The future production lifecycle driver (deferred) MUST:

1. call `can_complete_research(conn, project_id)` before attempting
   `transition_lifecycle(..., LifecycleState.COMPLETED)`;
2. treat `eligible=False` as "remain in REPORTING" and surface the denials
   (never retry-loop blindly);
3. **never** substitute an operational condition (task terminality, gate
   passage, budget exhaustion, READY absence) for the predicate.

The driver does not need to exist for the invariant to hold: the write-path
guard makes the invariant true regardless of who calls.

## 9. Rejected alternatives

- **A — invariant already enforced:** false. Recon found no epistemic
  precondition anywhere on the `REPORTING → COMPLETED` path (§2).
- **C — document-only + test harness, no code:** rejected because the
  building blocks for a narrow pure predicate already exist (programs,
  satisfaction links, verdicts, gate events, ladder records). A pure
  predicate + write-path guard pins the invariant mechanically, which a
  document alone cannot.
- **Enforcing in the future driver instead of the write path:** rejected —
  it would leave the invariant unenforced until the driver lands and would
  let any interim caller write `COMPLETED`. The choke point is the only
  location that is driver-independent.
- **A new evidence framework / completion artifact:** rejected by the brief;
  satisfaction is defined by existing contracts only (§3).
- **Trusting cached ladder rungs or stored satisfaction fields:** rejected
  (F2) — coverage is re-derived at read time.

## 10. Acceptance tests (`tests/test_hr08_completion_invariant.py`)

Negative cases (each must deny `COMPLETED`):

- **A** — all tasks terminal, mandatory evidence requirement unsatisfied →
  `REQUIREMENT_UNSATISFIED`; write path refuses, DB unchanged, no event.
- **B** — all tasks terminal, all three mandatory human gates passed
  (`GatePassed` events), obligation still missing → denied. Gate passage is
  not completion.
- **C** — budget exhausted (no schedulable headroom; all tasks terminal) →
  denied unless the completion contract is independently satisfied. The
  predicate never consults budget.
- **D** — no READY tasks remain → denied unless the completion criteria are
  satisfied. The predicate never consults task state.
- **E** — all required satisfaction links exist **structurally** but their
  artifacts carry no PASS validation verdict (pre-M1 shape) → denied. A bare
  artifact class / verdict-less link can never satisfy a requirement.
- **F** — obligations covered but the hypothesis carries a ratified REFUTED
  ladder record → `HYPOTHESIS_REFUTED`.
- **G** — no compiled program governs the project → `NO_PROGRAM` (and a
  corrupt head row → `PROGRAM_CORRUPT`).

Positive case:

- every evidence requirement satisfied by verdict-covered links, every
  mandatory gate evidenced by `GatePassed`, no refutation → `eligible=True`
  and `transition_lifecycle` carries `REPORTING → COMPLETED` with exactly
  one `LifecycleTransition` event.

Guard properties:

- a denied transition leaves `lifecycle_state` unchanged and appends no
  event (ROLLBACK);
- the predicate is deterministic (two calls, identical verdicts) and
  side-effect-free (row counts unchanged after a call).
