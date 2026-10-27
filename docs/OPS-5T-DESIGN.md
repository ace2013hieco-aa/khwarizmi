# OPS-5T — design gate: the completion predicate must count what happened

| Item | Value |
| --- | --- |
| Slice | OPS-5T |
| Base | `main` at `8eac365` |
| Branch | `slice/ops-5t-completion-truth` |
| Date | 2026-10-27 |
| Census at base | 124 / 28 (19/5/4) / 1 / 15 / 0 — `scripts/check_census.py` PASS on this tree |

The question is: **when a run says it succeeded, what recorded fact is that
statement about?** The answer this slice enforces:

> A run may record `SUCCEEDED` only when a durable row appeared because of it,
> and a project may record `COMPLETED` only when every obligation of *its own
> current program* is covered by a fact that is still live.

Both halves of that sentence were false. The first because a refusal was counted
as a write; the second because the predicate that reads obligations joined them
to facts by project alone and never asked whether a fact had been withdrawn.

---

## 1. The two defects, checked against the tree

### 1.1 C3 — a refusal is counted as an admission

`src/hermes/agents/runtime/wiring.py:203-210` (at base):

```python
def __call__(self, intent: Intent) -> Any:
    if not self._fence.held:
        self.refusals += 1
        ...
        self._fence.require(intent)      # raises LeaseLostRejection (LOCK)
    self.writes += 1                     # ← before the apply
    return self._inner(intent)
```

`AgentRuntime._apply` (`run.py:1246-1262`) catches `IntentRejectedError` and
returns it as `(Admission.REFUSED, "CODE: detail", "")` — data, not an
exception. So the increment is never unwound: **every refused intent is counted
as a write.**

`methodology_driver.py:689-690` (at base) then reads that counter as evidence:

```python
applied = max(0, wired.spine_writes - applied_so_far)
applied_so_far = max(applied_so_far, wired.spine_writes)
```

and `task_handlers/__init__.py:350-362` fails S6-B2 only when `applied == 0`.

The consequence is the one the audit names: **a run whose every proposal was
refused passes S6-B2 and is recorded `SUCCEEDED`, with no durable effect.** The
measurement the programme is built on — "this stage admitted something" — was
reading a counter that says "this stage called the spine".

### 1.2 C4 — the predicate fails open, four ways

`_passed_gate_requirements` (`completion.py:186-213` at base) joined
`GatePassed` events to tasks **by project only**:

```sql
SELECT t.spec_json
  FROM events e JOIN tasks t ON t.task_id = e.task_id
 WHERE e.project_id = ? AND e.event_type = 'GatePassed'
```

Three facts are missing from that join, and each is a hole on its own:

1. **No program scope.** A gate passed under an older program satisfied the
   current one. The planner's own identity for a gate task digests
   `program_id` (`task_plan._identity`), so the older task was never the task
   the current contract names.
2. **No task type.** A `GatePassed` event attached to any task carrying
   `spec.gate_requirement` counted — including an `AGENT_TASK` that was never a
   gate.
3. **No terminal state.** `_commit_gate` (`controller.py:5654-5664`) appends the
   event and *then* transitions the task. A task that ended `FAILED` with a
   `GatePassed` row on the journal still satisfied the requirement (H4's
   read-side consequence).

And in `_verdict_covered_classes` (`completion.py:155-183`) the artifact
invalidation marker was **not read at all**. Retraction is a marker on the
artifact row (`gateway.py:1912-1914`), not a delete: the satisfaction link and
its PASS verdict survive, so a **retracted artifact's PASS still covered its
requirement**. `completion.py:292` reads the marker for *contradiction* parties
and `repositories.py:3133` has an invalidation-aware helper; the satisfaction
join used neither.

Two more, in the same function as the loop that reads obligations:

4. **A malformed obligation was skipped.** `if not isinstance(req, dict):
   continue` and `if not isinstance(gate, str) or not gate: continue` — the
   obligation vanishes from the verdict instead of denying it.
5. **A non-string artifact class was dropped.**
   `{c for c in required if isinstance(c, str)}` turns `["x", 5]` into `{x}`:
   the requirement is silently *narrowed*, so a project that satisfies `x`
   completes a requirement that named two classes.

---

## 2. The change

### 2.1 C3 — count the admission records, not the calls

The charter prefers the second of its two options, and this slice takes it: the
**proposals' admission records are the evidence**, and the transport counter is
no longer read anywhere in the methodology path.

`_admission_tally` (new, `methodology_driver.py`) classifies each proposal by
the verdict `apply_intent` returned:

| verdict | counted as | why |
| --- | --- | --- |
| `ADMITTED` | `intents_applied` | the spine wrote a new row |
| `DUPLICATE` | `intents_duplicate` | the identity matched a row the spine already held — **this run added nothing** |
| `REFUSED` | `intents_refused` | nothing was written; the spine's code is kept |
| `PENDING` | `intents_proposed` only | not a verdict; reported as "never answered" if it ever appears |

`StageRecord` carries the four counts plus `refusal_codes`, so a zero-admission
stage can say *which* zero it is. `applied = max(0, spine_writes - …)` is gone,
and so is `applied_so_far`.

The counter itself is also corrected at the seam
(`wiring.py:FencedIntentApplier.__call__`): `writes` now increments **after**
the inner call returns, and a refused call increments `refusals` instead. The
driver no longer reads it, but a counter named `writes` may not count a call the
spine refused — the next reader would believe it. It keeps a precise meaning:
*the intents the spine answered without refusing* (an admitted row or an
idempotent duplicate), which with `refusals` partitions every call, so "no
partial rows after a loss" stays checkable.

### 2.2 C4 — close the four holes

**The gate join** now reads five facts instead of one:

```sql
WHERE e.project_id = ?
  AND e.event_type = 'GatePassed'
  AND t.project_id = e.project_id
  AND t.task_type IN ('GATE', 'HUMAN_GATE')
  AND t.status = 'SUCCEEDED'
```

and the spec is checked for `spec["program_id"] == program_id` before its
`gate_requirement` is read. A task that cannot name this program contributes
nothing (fail-closed), exactly as an unparseable spec already did.

**The satisfaction join** calls `artifact_is_active(conn, artifact_id)` — the
repository rule the contradiction party check uses, promoted from
`ContradictionRepository._party_active` to a module-level function in
`repositories.py` so there is one definition of "retracted" rather than two. A
linked artifact whose marker says `INVALIDATED` contributes no class.

**Malformed obligations deny.** `_read_evidence_requirement` returns
`(claim_ref, classes, defect)`; a non-object obligation, a non-string/empty
`claim_ref`, a non-list or empty `required_artifacts`, or a non-string element
is a `PROGRAM_CORRUPT` denial naming the exact position
(`evidence_requirements[0].required_artifacts[1]`). A non-list obligation
container denies once instead of iterating whatever it is. No new denial code is
introduced: `PROGRAM_CORRUPT` already means "the program row is not the contract
it claims to be".

---

## 3. The four answers

### 3.1 Which admission record is authoritative, and what does a duplicate count as?

**`Proposal.admission`**, written by `AgentRuntime._emit_intent` from the
verdict `_apply` got back from `apply_intent`, carried on the run's
`ProposalSet`. It is the only record that says what the spine *did* with a
specific proposal: `spine_writes` says a call happened, and the trace says a
call happened, but neither says what came back.

`applied` counts `ADMITTED` **only**. A `DUPLICATE` is a replay: the runtime
derives `task_id`/`idempotency_key` by rule (`_derive_payload`), so a duplicate
means the spine already held *this exact* intent — the durable effect exists,
but it is not this run's, and S6-B2 asks whether *this run* recorded anything. A
run made only of replays records nothing new and fails S6-B2. That is the strict
reading, and §4.4 says S6-B2 may only get stricter. The duplicate is not hidden:
it is counted, stored on the stage record and named in the refusal message, so
"the run replayed three intents" and "the run proposed nothing" are different
sentences an operator can tell apart.

### 3.2 Does scoping the gate join break a legitimate case?

**No, and the reason is the planner's own rule, not a judgement about reuse.**
`task_plan._identity` hashes `{program_id, plan_role, ref, plan_version}` into a
gate task's idempotency key, and `_gate_task` writes `program_id` into the spec.
A gate task is a task *of one program*; the planner cannot express "v1's gate
serves v2", because a head move is a new content-addressed `program_id` and
therefore a new gate task.

So the case the charter asks about — "a gate passed before a program's head
moved might be correctly reused" — is not a legitimate reuse under the planner's
own contract: the moved head's contract names a *different* gate task, and the
older pass is a verdict about the older contract. Requiring the new task to pass
is the same rule the planner already applies when it mints it.

The scope distinguishes the two cases by **the program the task was planned
for**, never by "whatever is head now": a task whose spec names the current
program counts however old it is, and a task whose spec names another program
does not count however recently it passed. A gate task that names no program
contributes nothing — it cannot prove it belongs here, and completion is
fail-closed.

If the Director wants a gate verdict to survive a program version bump, that is
a **planner** change (make the gate task identity independent of program
content), argued against E9 ("a new version changes the contract"). It is not a
predicate change, and this slice does not make it.

### 3.3 Is a retracted artifact's requirement denied, or does it need re-satisfaction?

**Denied.** The requirement becomes unsatisfied — the same verdict as "no link
at all" — which is the fail-closed answer. It is not *re-satisfied by the same
link*: the link and its PASS verdict still exist and are simply not counted, so
satisfying the requirement again needs a new artifact (a new row, a new PASS
verdict, a new link). That is the correct cost: the artifact that was withdrawn
is not evidence, and the rows that name it cannot be re-used as if it were.

Does it also un-cover a claim already built on it? **Not in this slice.**
Completion is a *read*: the coverage is re-derived at read time, so the next
attempt to complete denies. It does not revisit a project that already reached
`COMPLETED`, and it does not retract a claim, classification or contradiction
row built on the artifact. Whether a retraction must retro-actively un-cover
downstream claims — and what happens to a claim already asserted on a withdrawn
source — is **N9's** territory (retraction fencing: `source_outcomes.py`,
`RETRACTED_CITATION`, admissibility of retracted sources), and this slice
deliberately does not enter it. What it establishes is narrower and prior: a
retracted artifact cannot *cover a completion requirement*, so completion cannot
be granted on one.

### 3.4 What does S6-B2 report now?

The verdict is unchanged (`applied == 0` fails the run); the **message carries
the tally**, because "0 admissions" is the verdict, not the diagnosis:

- nothing proposed —
  `PROPOSAL: methodology 'm' completed with 0 admissions via apply_intent — the run proposed nothing, so no intent ever reached the one write path; an effectless run is not a recorded outcome (S6-B2)`
- everything refused —
  `PROPOSAL: methodology 'm' completed with 0 admissions via apply_intent — all 2 proposal(s) the run made were refused by the spine (MALFORMED_PAYLOAD); a refusal is data, not an admission, so the run recorded nothing (S6-B2)`
- refused and replayed —
  `PROPOSAL: methodology 'm' completed with 0 admissions via apply_intent — 3 proposal(s) were made and none became a new row: 1 refused by the spine (MALFORMED_PAYLOAD), 2 duplicate(s) of rows it already held; an effectless run is not a recorded outcome (S6-B2)`

An operator reading the third line learns that the loop was working and the
spine said no — which is a different incident from a loop that said nothing, and
the two used to be the same line.

---

## 4. What does not change

1. No new event kind, write path or transaction. Census 124 / 28 (19/5/4) / 1 /
   15 / 0, re-derived by `scripts/check_census.py`.
2. The substrate's rules, the gateway's checks and the capability grants are
   untouched: no `gateway.py`, no `substrate.py`, no `intents.py` edit.
3. Drain-only byte-identical. B4 24. LOOP baseline unchanged (the LOOP corpus
   pins the *runtime* plane's digests; the wiring's counters are not in it).
   Governed docs untouched.
4. **S6-B2 and the HR-08 gate only get stricter.** No denial was removed, no
   count was relaxed, no code was added.
5. The act-key, `proposable_kinds`, `max_ticks` and objectives are untouched.
6. No key material.

## 5. Falsifiers, and where each is pinned

| # | Falsifier | Test |
| --- | --- | --- |
| 1 | a methodology whose every proposal is refused **fails** S6-B2 | `test_a_methodology_whose_every_proposal_is_refused_fails_s6b2` |
| 2 | a methodology with one genuine admission still passes | `test_a_methodology_with_one_genuine_admission_still_passes` |
| 3 | a `GatePassed` from another program does not satisfy | `test_a_gate_passed_by_another_program_does_not_satisfy` |
| 4 | a `GatePassed` on a task that ended `FAILED` does not satisfy | `test_a_gate_passed_on_a_failed_task_does_not_satisfy` |
| 5 | a retracted artifact does not cover its requirement | `test_a_retracted_artifact_does_not_cover_its_requirement` |
| 6 | a malformed requirement or a non-string artifact class denies | `test_a_malformed_evidence_requirement_denies`, `test_a_non_string_artifact_class_is_not_narrowed_to_the_strings`, `test_a_malformed_gate_requirement_denies`, `test_an_obligation_container_that_is_not_a_list_denies` |
| 7 | baseline and census unchanged | `test_the_baseline_program_is_eligible`, `scripts/check_census.py`, `test_census_check` |

Every falsifier above was run against the base tree with the source changes
stashed and **failed there**, then passed with them restored — the tests are
evidence, not decoration. The controls that must not move
(`test_a_gate_passed_on_an_integrity_gate_task_satisfies`,
`test_a_retraction_marker_that_is_not_the_marker_is_ignored`,
`test_the_baseline_program_is_eligible`,
`test_a_methodology_with_one_genuine_admission_still_passes`) pass on both.

## 6. Gates

1. Targeted: `test_ops5t_completion_truth`, `test_ops5m_truncated_chain`,
   `test_hr08_completion_invariant`, `test_ops5q_program_ref`,
   `test_methodology_plane`, `test_loop_baseline`, `test_b4_ref_graphs`,
   `test_census_check`.
2. `scripts/run_tests.py` (full).
3. `scripts/stamp_suite_count.py`, then `--check`.
4. `scripts/check_census.py` — unchanged.
5. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright tests project.

## 7. What this slice decides not to take

- **H2** (`TICK_LIMIT` / `NO_PROPOSALS` recorded `SUCCEEDED`). Adjacent to C3,
  and deliberately **not** folded in. C3's defect is a *count*: a call that
  wrote nothing was counted as an effect. H2 is a *state*: a stage that stopped
  because it had nothing to propose is recorded `SUCCEEDED`, and OPS-5M's
  constant already argues why that is the correct stage-level reading — a
  succeeded stage's own termination never reaches `METHODOLOGY_COMPLETE`, and a
  stage that stops on `NO_PROPOSALS` after doing its work must not fail the
  chain. Changing it changes stage semantics, not the completion predicate, and
  no falsifier in this charter asks for it. Recorded for a later slice with its
  own argument.
- **H4** (`_commit_gate` is two writes). The **read-side** consequence is closed
  here: falsifier 4 makes a `GatePassed` that outlived a failed task worthless
  to the predicate, which is H4's only consumer. The **write-side** atomicity is
  not touched, and must not be here: making the event and the transition one
  transaction is a change to a write path, which §4.1 forbids.
- **H7** (planning and completion disagree about the program head). The gate
  scope removes *one* instance of the disagreement — completion now reads gates
  by the same program id the planner planned them under — but `_current_program`
  still takes the max version regardless of `parent_program_id`, and that is not
  this slice.
- **C1, C2, H1, H3, H5, H6, H8**: not taken (charter appendix).
- **A new denial code** for a malformed obligation: refused. `PROGRAM_CORRUPT`
  already says "this row is not the contract it claims to be", and the closed
  vocabulary is part of what the predicate promises.
- **A second invalidation check** in `completion.py`: refused. The repository's
  rule is imported and called, so "retracted" has one definition.
