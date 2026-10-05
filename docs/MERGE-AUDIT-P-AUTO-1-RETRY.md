# MERGE-AUDIT-P-AUTO-1-RETRY — delta re-audit of `merge/p-auto-1@3174a3d`

Delta audit of the `fix/p-auto-1-fix2` remediation line as integrated into
`merge/p-auto-1`, scored against the blocking set of
`docs/MERGE-AUDIT-P-AUTO-1.md` (M1–M4) and its carry-forward (S1–S3,
O1–O2). Findings only. Counts and `file:line`. Executed in an isolated
worktree; the shared checkout and the `fix2` / `fix2-before` trees were
opened read-only and never written.

This document supersedes nothing. `MERGE-AUDIT-P-AUTO-1.md` remains the
record of the `8fd6ef1` audit and of its verdict FAIL; this is the delta.

The audited integration tip is `3174a3d`. Committing this file moved the
branch to `5f0a121`, and the gate addendum below moved it once more; the
final tip is the addendum commit. All three share one `src`+`tests` tree,
byte-identical to `fix/p-auto-1-fix2@59ad5bf` (INV7–INV11 plus the proof
reported with the addendum commit), so every finding below holds unchanged at
the final tip.

## Inputs receipt (all readable, no STOP)

| Input | Value | State |
| --- | --- | --- |
| `main` (local) | `c6076d5f978a4c4b49574d1af6f02cafd63750f5` | read, never touched |
| `main` (remote, `git ls-remote origin refs/heads/main`) | `c6076d5f978a4c4b49574d1af6f02cafd63750f5` | identical — unmoved before **and** after |
| `merge/p-auto-1` on entry | `af14bbbd47f9b0c433a65222db5685473582caad` | read |
| `fix/p-auto-1-fix2` tip | `59ad5bf481496131561ecccd89436a02844eb393` | read-only |
| — commit 1 | `5b9e937` M1+M2 producer filter | read |
| — commit 2 | `8efb3b3` M3+M4 fault notes | read |
| — commit 3 | `59ad5bf` S3 assertion | read |
| merge base of the two legs | `8fd6ef1045c7ee475a985c93ab0aca5484381296` | == the previously audited tip |
| `merge/p-auto-1` after integration | `3174a3dd92550da862f793629961af84f2a7baf8` | new, **local, unpushed** |
| `merge/p-auto-1` on the remote | **absent** (`git ls-remote origin 'refs/heads/merge/*'` lists 11 branches, none of them this one) | never pushed |

STOP-topic scan (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`),
delta-scoped: **0 hits** over `8fd6ef1..59ad5bf`. See §Forbidden-topic scan
for the two hits on the docs leg and why they are reported, not triggered.

## Deviation from the charter's stated topology — a FF was impossible

The charter expected "clean FF from `8fd6ef1`". That is not reachable.
`af14bbb` and `59ad5bf` are **divergent siblings**, not an ancestor pair:

```
$ git merge-base af14bbb 59ad5bf
8fd6ef1045c7ee475a985c93ab0aca5484381296
$ git merge-base --is-ancestor af14bbb 59ad5bf   →  NOT an ancestor
$ git merge-base --is-ancestor 59ad5bf af14bbb   →  NOT an ancestor
```

`af14bbb` is a docs-only line built on `8fd6ef1`; `59ad5bf` is a code line
built on the same commit. Neither contains the other, so no fast-forward
exists in either direction. Both shortcuts were rejected on charter grounds:

- `git reset --hard 59ad5bf` would **delete** the four prior docs commits
  (`008b678`, `852a64f`, `6838429`, `af14bbb`) — including the MERGE-LOG and
  the very MERGE-AUDIT this delta is scored against, which the charter
  requires carried forward.
- `git rebase` would **rewrite** `af14bbb` and its ancestors, changing hashes
  the charter cites by name.

Chosen: `git merge --no-ff 59ad5bf481496131561ecccd89436a02844eb393` →
merge commit `3174a3d`, "Merge made by the 'ort' strategy", 5 files changed,
259 insertions(+), 41 deletions(-), **zero conflicts**. Both lines and every
referenced hash survive. Resulting topology:

```
*   3174a3d merge(p-auto-1): integrate fix/p-auto-1-fix2 tip 59ad5bf into merge/p-auto-1@af14bbb
|\
| * 59ad5bf test(p-auto-1-fix2): S3 - starvation-freedom test stops asserting nothing (local-only)
| * 8efb3b3 fix(p-auto-1-fix2): M3+M4 - sequencer notes report faults, one entry per faulted row (local-only)
| * 5b9e937 fix(p-auto-1-fix2): M1+M2 - exclude the recorded-only seq artifact from discovery (local-only)
* | af14bbb docs(merge-audit-p-auto-1): downgrade the assertion-free-test finding to SHOULD-FIX S3
* | 6838429 docs(merge-audit-p-auto-1): state the evidence limit on the M2 live-clock floor claim
* | 852a64f docs(merge-p-auto-1): MERGE-LOG-P-AUTO-1 for the P-AUTO-1 planner line (not merged)
* | 008b678 docs(merge-audit-p-auto-1): adversarial audit of merge/p-auto-1@8fd6ef1 - FAIL
|/
* 8fd6ef1 fix(p-auto-1-gap): seq-row test accounting for 9 red assertions plus F3 fault recording (local-only)
```

`git rev-list --parents -n 1 3174a3d` →
`3174a3dd… af14bbbd… 59ad5bf4…`: first parent the docs line, second parent
the fix tip. This is a **documented deviation** from the charter's stated
expectation, not a STOP condition — the deliverable "advance to `59ad5bf`"
is met in content and proven byte-exact below.

## Merge integrity — six invariants

| # | Claim | Command | Result |
| --- | --- | --- | --- |
| INV1 | the merge authors **no** src change | `git diff --exit-code 59ad5bf 3174a3d -- src` | exit 0 — IDENTICAL |
| INV2 | the merge authors **no** tests change | `git diff --exit-code 59ad5bf 3174a3d -- tests` | exit 0 — IDENTICAL |
| INV3 | prior docs preserved byte-exact | `git diff --exit-code af14bbb 3174a3d -- docs` | exit 0 — IDENTICAL |
| INV4 | the only delta vs the fix tip is the carried docs | `git diff 59ad5bf 3174a3d --stat` | 2 files, 440 insertions (`MERGE-AUDIT-P-AUTO-1.md` 268, `MERGE-LOG-P-AUTO-1.md` 172), 0 deletions |
| INV5 | the only delta vs the docs tip is the fix | `git diff af14bbb 3174a3d --stat` | 5 files, 259 insertions, 41 deletions |
| INV6 | `main` unmoved | local vs `ls-remote` | `c6076d5f978a4c4b49574d1af6f02cafd63750f5` both |

The resulting tree is exactly `59ad5bf`'s `src/`+`tests/` ∪ `af14bbb`'s
`docs/`. The charter constraint "No src/ changes whatsoever on the merge
branch" holds: the merge commit's own contribution to `src/` is nil (INV1),
and the src text at `3174a3d` is the src text of `59ad5bf`, which was
authored on the fix branch, not here.

## Isolation and import proof

Isolated worktree `merge/p-auto-1@3174a3d` at
`C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/mergepauto1`. Gates invoked
with cwd = worktree, the shared venv interpreter reached through a gitignored
`.venv` junction, and `PYTHONPATH=<worktree>/src` on every invocation
(`core.autocrlf=true`, so worktree text is uniform CRLF; all content
comparisons here are by git object id / `--numstat` / md5, never by eye).

A/B attribution is proven at the git-object level rather than by trusting the
harness — the seq filter's presence in `_discover_eligible` across the three
relevant trees:

| Tree | `if self._is_sequencer_task(d):` occurrences in `controller.py` |
| --- | --- |
| `8fd6ef1` (BEFORE leg src) | **0** |
| `59ad5bf` (fix tip) | **1** |
| `3174a3d` (AFTER leg / merge tip) | **1** |

and the four test files are blob-identical between `59ad5bf` and `3174a3d`
(`d878a7f28099`, `7fd7f0d4d264`, `216a3b487e31`, `b693c54176f7`), md5 at the
merge tip `fab28b47fb0a2e34e00e41cd24af3738`,
`bb4291c1ca3c6d3935fd66fe50ec24a3`, `f3ef7b519d7409ae223766c71002d9ba`,
`944123f01518ad11d71269da51b56b16`. Both A/B legs therefore ran
**byte-identical tests** and differed in **one** thing: the src tree.

## Verdict: PASS — cleared for a fresh D9 push decision

M1, M2, M3 and M4 are all **CLOSED**, each with a fail-before/pass-after
regression test whose red leg is reproduced here against `8fd6ef1` src. S1
and S3 are **CLOSED**. All four gates are green on the new tip, full suite
**2325 passed**. No new MUST-FIX and no new SHOULD-FIX arises from the delta.

`main` was **not** advanced and **not** pushed; `merge/p-auto-1` was **not**
pushed. D9 push approval lapsed with the prior FAIL and this charter does not
restore it — the push decision is the director's, on a fresh D9.

Residual, all non-blocking and all pre-existing: **S2 open** (commit-message
drift, unfixable without a history rewrite), **O1**, **O2** unchanged, plus
one new observation **O3** (a now-redundant second filter). See
§Carry-forward.

## MUST-FIX closure

### M1 — CLOSED: the inert seq row no longer suppresses the Q-04 §3.4 diagnostic

The prior audit's mechanism was that `_dispatch_pass` consumed the
**unfiltered** `_discover_eligible()`, so an inert PENDING seq artifact made
`if not tasks:` permanently `False` and `_cone_blocked_dispatch_notes()`
unreachable for the rest of the project's life.

The fix moves the exclusion to the **producer**:
`src/hermes/research/controller.py:2738-2739`

```python
            if self._is_sequencer_task(d):
                continue
```

inside `_discover_eligible` (`controller.py:2699`), with the rationale recorded
in its docstring at `controller.py:2706-2711` — explicitly noting that a
dispatch-only filter would leave the Q-02 ranking, the C4 floor input and the
Q-04 §3.4 idle predicate still contaminated. The predicate reused is the
existing `spec.template` marker `_is_sequencer_task` (`controller.py:4240`),
not the `seq-` prefix, so the prior audit's F1 closure is preserved.

Every consumer is now clean at once, with no consumer-side edit:
`_sequencer_pass`'s own view (`controller.py:4294`), `_dispatch_pass`
(`controller.py:4439`) via `tasks = self._discover_eligible()`
(`controller.py:4442`), `_order_eligible` (`controller.py:4444`),
`_persist_floor_transitions` (`controller.py:4453`) and the idle predicate
`if not tasks:` (`controller.py:4454`).

**Regression test** — `tests/test_controller_q04.py:160`
`TestConeBlockedDispatchNote::test_note_still_fires_after_a_prior_sequencer_pass`
(+26 lines, pure append). It sequences real work, asserts the artifact exists
and `A` is still PENDING and no cone note has fired, then fails and classifies
`A` `REFUTED` and re-ticks so `B` is genuinely cone-blocked with only the seq
row otherwise eligible.

Red on `8fd6ef1` src:

```
>       assert any(
            "Q-04: dispatch blocked by failure cone of task A" in n
            and "FAILED" in n and "REFUTED" in n and "B" in n
            for n in ctrl._notes)
E       assert False
E        +  where False = any(<generator object TestConeBlockedDispatchNote.test_note_still_fires_after_a_prior_sequencer_pass.<locals>.<genexpr> …>)
```

This is the prior audit's measured table (`_cone_blocked_dispatch_notes` calls
1 → 0, note emitted → none) converted into a permanent gate.

**Second M1 test** — `tests/test_p_auto_1_sequencer.py:608`
`test_inert_artifact_leaves_the_eligible_set_empty` states the invariant
directly. Red on `8fd6ef1` src:

```
>       assert ctrl._discover_eligible() == []
E       AssertionError: assert [{'task_id': …': None, …}] == []
E         Left contains one more item: {'task_id': 'seq-p1-7328ca305c8160391de5a9189f4630ea', 'project_id': 'p1', 'task_type': 'TOOL_TASK', 'profile': None, …}
```

### M2 — CLOSED: the seq artifact is out of the Q-02 observable and the C4 floor ranking

Same producer-side exclusion; no separate code. Closure is proven on three
surfaces.

**(a) Q-02 quiescence restored.** `tests/test_controller_q02.py` is back to
its pre-line assertions — see §S1. Red on `8fd6ef1` src, three tests:

```
>       assert t2.ordering_policy_version == ""  # no unclaimed eligible task
E       AssertionError: assert 'task-eval-2026.1' == ''
E         + task-eval-2026.1

>       assert [t["task_id"] for t in ordered] == ["t-next"]
E       AssertionError: assert ['t-next', 's…41e4585fb3eb'] == ['t-next']
E         Left contains one more item: 'seq-p1-d115c40199f1692e5ead41e4585fb3eb'

>       assert order1 == ["t-linked"]
E       AssertionError: assert ['t-linked', …19293c38302c'] == ['t-linked']
E         Left contains one more item: 'seq-p1-f456d8308910ef5fa03c19293c38302c'
```

The first is the exact inverse of the prior audit's quiescence table
(`ordering_policy_version` `''` → `'task-eval-2026.1'`): the retargeted value
is now red and the certified value green.

**(b) C4 floor ranking clean.** `tests/test_controller_c4.py:276`
`TestSequencerArtifactNotAnOrderingParticipant` (2 tests, +47 lines appended).
Red on `8fd6ef1` src:

```
>       assert seq_id not in result.unhandled
E       AssertionError: assert 'seq-p1-23b941b645dd331b658500f18d7206df' not in ['seq-p1-23b941b645dd331b658500f18d7206df']
E        +  where […] = TickResult(idle='max_calls_per_tick', dispatched=['t-l1', 't-l2'], succeeded=['t-l1', 't-l2'], …, ordering_policy_version='task-eval-2026.1-floor.1').unhandled

>       assert seq_id not in [t["task_id"] for t in eligible]
E       AssertionError: assert 'seq-p1-23b941b645dd331b658500f18d7206df' not in ['seq-p1-23b941b645dd331b658500f18d7206df', 't-l1', 't-l2', 't-n']
```

**(c) The certified slice C4 §2.4 AC-5 regression is gone — and it is now
reproduced under the ORIGINAL fixture timing, which the prior audit could only
measure with a hand-built probe.** Four pre-existing C4 tests went red on
`8fd6ef1` src once `_monopoly_setup` was un-re-timed:

```
>       assert order == ["t-l1", "t-n"]
E       AssertionError: assert ['t-l1', 't-l2'] == ['t-l1', 't-n']
E         At index 1 diff: 't-l2' != 't-n'

>       assert "FLOOR_ENTITLEMENT_WITHDRAWN" in kinds
E       AssertionError: assert 'FLOOR_ENTITLEMENT_WITHDRAWN' in ['FLOOR_GRANTED', 'FLOOR_GRANTED']

>       assert "FLOOR_SUSPENDED" in kinds
E       AssertionError: assert 'FLOOR_SUSPENDED' in ['FLOOR_GRANTED', 'FLOOR_GRANTED']

>       assert events                                            (test_controller_c4.py:265)
E       assert []
```

The dispatch-order row is the prior audit's M2 table verbatim
(`['t-l1','t-n']` → `['t-l1','t-l2']`, leader real → inert). The last is
stronger than anything the prior audit measured: with the artifact as
pure-policy leader the leading trajectory is empty, the monopoly is never
seen, and the floor emits **zero** events.

Evidence limit carried forward honestly: the prior audit's live-clock run had
`FloorGrantRecorded` = 0 on **both** trees, so a live-clock *grant*
differential was never demonstrated. That limit still stands — the grant loss
above is measured under the frozen-clock C4 fixture. What is now proven, and
was only argued before, is that the *ranking* contamination is real and that
it reaches the floor's own observables.

### M3 — CLOSED: routine first-pass absence is no longer recorded as a fault

`src/hermes/research/controller.py:4285-4288` imports `NotFoundError`
alongside `TaskRepository`; `controller.py:4389-4390` catches it ahead of the
blanket handler:

```python
        except NotFoundError:
            pass  # routine first pass for this ready set — not a fault
```

`LockLostError` still re-raises first (`controller.py:4387-4388`), so the
lease fence is not swallowed, and the blanket `except Exception` recorder
survives at `controller.py:4391-4393` — a genuine fault at that site is still
recorded, and is now *distinguishable* from routine absence, which was the
prior finding.

**Regression test** — `tests/test_p_auto_1_sequencer.py:632`
`test_first_pass_records_no_get_fault_note`. Red on `8fd6ef1` src:

```
>       assert not [n for n in ctrl.notes if "get fault" in n]
E       AssertionError: assert not ['sequencer: get fault: Task not found: seq-p1-07f6f1ef86fb7bb2bf42aa1f1e199e6e']
```

The prior audit measured this note on 100% of first passes; it is now red.

### M4 — CLOSED: `_note_once` keys carry the faulting row's identity

All three sites the prior audit cited are scoped, following the documented
`<surface>:<condition>:<identity>` convention at `controller.py:501-503`:

| Site | Key at `3174a3d` | Was at `af14bbb` |
| --- | --- | --- |
| cancel fault | `key=f"sequencer:cancel-fault:{old_seq_id}"` — `controller.py:4381` | `"sequencer:cancel-fault"` |
| get fault | `key=f"sequencer:get-fault:{seq_task_id}"` — `controller.py:4393` | `"sequencer:get-fault"` |
| admission fault | `key=f"sequencer:fault:{seq_task_id}"` — `controller.py:4434` | `"sequencer:fault"` |

The two remaining sequencer keys are **not** M4 instances and were checked
rather than assumed:

- `key="sequencer:cycle-detected"` (`controller.py:4344`) — constant, but its
  *message* is also constant (one cycle condition per project per pass), so
  there are no distinct facts to collapse. Last-writer-wins is a no-op.
- `key=f"sequencer:refused:{exc.code}"` (`controller.py:4429`) — already
  scoped, pre-existing, untouched by this delta.

**Regression test** — `tests/test_p_auto_1_sequencer.py:645`
`test_distinct_cancel_faults_keep_distinct_notes`: two stale artifacts with
distinct content-addressed ids, `transition_status` monkeypatched to refuse
both. Red on `8fd6ef1` src:

```
>       assert len(faults) == 2
E       AssertionError: assert 1 == 2
E        +  where 1 = len(['sequencer: cancel fault: cancel refused for seq-p1-stale000000000000000000000b'])
```

`…0a` had been erased by `…0b` — the exact last-writer-wins mechanism the
prior audit described from reading `_note_once`
(`controller.py:491-516`; the in-place overwrite is `controller.py:513`,
`self._notes[existing] = message`), now demonstrated behaviourally.

## SHOULD-FIX dispositions

### S1 — CLOSED (not chartered; closed anyway)

The prior finding was that the line **retargeted certified assertions to
accept M2's contamination** instead of fixing it, in two files. Both are
restored.

**`tests/test_controller_q02.py`** — every `startswith("seq-")` filter and
every `seq-` reference is gone from the file at `3174a3d` (grep count 0). The
restorations, each verified present verbatim at the pre-line baseline
`c6076d5`:

- `assert t2.ordering_policy_version == ""  # no unclaimed eligible task`
- `assert rederived() == ([], None)  # deterministic end state`
- `assert order1 == ["t-linked"]`
- `assert rederived() == ([], None, {})`

The **only** residual delta against pre-line `c6076d5` is one
admission-accounting hunk, `+5/−2` at `tests/test_controller_q02.py:320-325`:

```python
        # transitions and the extract outcomes. P-AUTO-1: the sequencer pass
        # admits its seq row through the gateway, emitting IntentApplied (the
        # same admission event any task emits) — accounted for here.
        assert after_events - before_events <= {
            "TaskStatusChanged", "IntentApplied"}
```

This is a **true** widening, not a retarget: the sequencer admits through
`apply_intent`, so `IntentApplied` is genuinely a new event type on this path,
and the assertion still forbids every other event type. It is the minimum
honest accommodation of the feature and it does not weaken a certified
property. Accepted.

**`tests/test_controller_c4.py`** — the fixture re-timing is **reverted**.
`git diff c6076d5 3174a3d --numstat` → `47  0  tests/test_controller_c4.py`:
a **pure append with zero deletions**, so `_monopoly_setup` is byte-identical
to pre-line. Confirmed by direct comparison: `created_at` values at
`tests/test_controller_c4.py:90/93/96` are `2026-01-01T01:00` / `T02:00` /
`T03:00`, and `2025-12-31T23` appears **nowhere** in the file. The re-timing
rationale docstring is removed with it.

The appended class states the corrected principle in its own docstring
(`tests/test_controller_c4.py:277-284`), closing with: "The artifact is
excluded at discovery; the fix is the exclusion, never a re-timing of these
fixtures." That is the right disposition — the prior audit's objection was
precisely that re-timing preserved AC-5 for the new timing while deleting
coverage of the production-reachable condition. Coverage is now added instead
of subtracted, and §M2(c) shows the original timing is restored **and** red
without the fix.

### S2 — STILL OPEN (recommend discharge by record)

`51293da`'s commit message still states (line 11) "Add new test file
`test_p_auto_1_sequencer.py` with **11** tests"; the file carries **18** test
functions at `3174a3d` (14 at `8fd6ef1`, +4 from this delta:
`test_artifact_is_absent_from_the_eligible_set_and_the_ranking`,
`test_inert_artifact_leaves_the_eligible_set_empty`,
`test_first_pass_records_no_get_fault_note`,
`test_distinct_cancel_faults_keep_distinct_notes`). It also still states
(line 8) "Starvation-freedom guaranteed by immutable DAG topology" — the
lemma F2 retracted.

The drift has **widened** numerically (11 → 14 → 18) because the file grew.
It cannot be fixed on this branch: correcting a commit message means rewriting
history, which AGENTS.md's append-only discipline and this charter's "hashes
the charter cites by name" both forbid. It is bookkeeping about a message, not
a defect in the tree, and no gate reads it.

**Recommended disposition:** discharge S2 by record — this section *is* the
correction. Any future reader reconciling `51293da`'s message against the tree
should treat the count as 18 and the starvation-freedom lemma as retracted
(the correction lives at `controller.py:4271-4279` and is now asserted at
`tests/test_p_auto_1_sequencer.py:303`). Not a push blocker.

### S3 — CLOSED

`tests/test_p_auto_1_sequencer.py:286`
`test_starvation_freedom_documented` no longer has a body of one comment plus
`pass`. It now exercises property 2 of its own docstring — inclusion is total
over the ready set, cost class is an ordering input and never an admission
one — and asserts at `tests/test_p_auto_1_sequencer.py:303`:

```python
        assert set(_latest_sequence(conn)) == {extract_id, "t-high", "t-low"}
```

with a `HIGH`-cost and a `LOW`-cost dependency-free task admitted at `LATER`
alongside the extract task. The test now fails if the sequencer ever drops a
ready task on cost grounds, which the `pass` stub could not. The docstring at
`:287-295` is unchanged, so the F2 correction it records survives. The prior
audit's bookkeeping objection — a documentation-only stub inflating the F2
closure count — is resolved by giving it an assertion, the first of the two
options that audit offered.

## Observations

- **O1 — dead store, STILL PRESENT, unchanged.**
  `controller.py:4316-4317`
  `in_degree`/`adj` `dict.fromkeys(task_ids, …)`; `adj` is immediately
  rebuilt by `:4319-4320`. The aliasing comment at `:4318` is correct; the
  initialization is dead. Non-blocking, untouched by this delta.
- **O2 — terminalization outside the gateway, STILL PRESENT, unchanged.**
  `controller.py:4374-4376`
  `task_repo.transition_status(old_seq_id, TaskStatus.CANCELLED, caused_by="sequencer", …)`.
  Still within the existing envelope (the Controller is one of the 4 certified
  acquisition owners, and the write is journalled). Its "unreachable in the
  idle case" characterization from the prior audit **still holds**: M1 was
  fixed in `_discover_eligible`, not in `_sequencer_pass`'s own early return
  at `controller.py:4301-4302`, so the cancel sweep at `:4370-4381` remains
  unreachable when no real work is eligible. Non-blocking.
- **O3 — NEW, non-blocking: a now-redundant second filter.**
  `controller.py:4298-4300` re-filters `ready_tasks` through
  `_is_sequencer_task` immediately after `ready_tasks = self._discover_eligible()`
  at `:4294`, which already excludes them at `:2738`. Harmless and idempotent
  — a list comprehension over an already-clean list — but it is now dead work
  and its comment ("Filter out sequencer tasks (they are internal sequencing
  artifacts)") no longer describes a live necessity. Left alone deliberately:
  removing it would be a src change on the merge branch, which this charter
  forbids. Worth one line in a future cleanup pass.

## Scope-creep re-scan of `8fd6ef1..59ad5bf`

| Check | Result |
| --- | --- |
| `git diff --name-status` | exactly **5** files, all `M`: `src/hermes/research/controller.py`, `tests/test_controller_c4.py`, `tests/test_controller_q02.py`, `tests/test_controller_q04.py`, `tests/test_p_auto_1_sequencer.py` |
| `git diff --stat` | 5 files changed, **259 insertions(+), 41 deletions(-)** |
| src only | `src/hermes/research/controller.py \| 22 ++++++++++++++++++----` → **1 file, +18/−4** |
| files outside `src/`+`tests/` | **0** |
| `src/hermes/core/`, `src/hermes/persistence/` | **untouched** (empty name-only diff) — `intents.py` and the repositories are unmodified |
| `DELETE` added to src | **0** matches — append-only preserved |
| added src lines mentioning `IntentKind`, `proposed_by`, `internal_only`, `apply_intent` | **0** — no authority surface touched; the human-authority fail-closed boundary and the LLM-proposable kind list are unmodified |
| new files, `or*.json` sprawl, fixtures | **none** |

The entire src delta is the four hunks quoted above: a docstring (+7), the
two-line producer filter (+2), the `NotFoundError` import (+3 net) and its
catch (+2), and three `key=` f-string scopings (+0 net). No existing behavior
was textually removed from src; the only src deletions are the three constant
key literals and the one-line import they replace. Determinism-owns-control is
untouched — the fix *narrows* what reaches ranking and dispatch, and adds no
model routing.

## A/B regression harness — fail-before / pass-after

Both legs ran the identical selection
(`tests/test_p_auto_1_sequencer.py tests/test_controller_q02.py
tests/test_controller_q04.py tests/test_controller_c4.py`, `-q
-p no:cacheprovider`) against byte-identical test files (md5 above). Only the
src tree differed: BEFORE = `8fd6ef1` src in a purpose-built detached
worktree, AFTER = merge tip `3174a3d`. `PYTHONPATH=<tree>/src` on both, so the
editable install could not skew imports.

**BEFORE — `8fd6ef1` src + merge-tip tests: exit=1, 81 tests, 14 FAILED**

```
..............FFFF............................F..F......F......F.......F [ 88%]
...FF.FFF                                                                [100%]
BEFORE(8fd6ef1 src + merge-tip tests) exit=1
```

```
FAILED tests/test_p_auto_1_sequencer.py::TestSequencerArtifactOutOfDispatchOrdering::test_artifact_is_absent_from_the_eligible_set_and_the_ranking
FAILED tests/test_p_auto_1_sequencer.py::TestSequencerArtifactOutOfDispatchOrdering::test_inert_artifact_leaves_the_eligible_set_empty
FAILED tests/test_p_auto_1_sequencer.py::TestSequencerFaultNotes::test_first_pass_records_no_get_fault_note
FAILED tests/test_p_auto_1_sequencer.py::TestSequencerFaultNotes::test_distinct_cancel_faults_keep_distinct_notes
FAILED tests/test_controller_q02.py::TestRecoveryDeterminism::test_ordering_survives_crash_recovery_unperturbed
FAILED tests/test_controller_q02.py::TestSatisfactionWritePath::test_links_flow_into_the_ordering_derivation
FAILED tests/test_controller_q02.py::TestMultiTickRecoveryDeterminism::test_ordering_deterministic_as_satisfactions_grow_across_ticks
FAILED tests/test_controller_q04.py::TestConeBlockedDispatchNote::test_note_still_fires_after_a_prior_sequencer_pass
FAILED tests/test_controller_c4.py::TestMonopolyFire::test_floor_promotes_non_leader_and_records_event
FAILED tests/test_controller_c4.py::TestFCDecay::test_stagnant_grant_triggers_withdrawal_event
FAILED tests/test_controller_c4.py::TestFCKillSwitch::test_stagnant_grant_triggers_suspension_event
FAILED tests/test_controller_c4.py::TestEventPayload::test_payload_is_validated_and_bounded
FAILED tests/test_controller_c4.py::TestSequencerArtifactNotAnOrderingParticipant::test_floor_observables_are_clean_of_the_seq_artifact
FAILED tests/test_controller_c4.py::TestSequencerArtifactNotAnOrderingParticipant::test_ranking_is_the_real_eligible_set_only
```

Attribution of the 14: **6** are this delta's new regression tests (2 M1/M2
sequencer + 2 M3/M4 + 2 C4 artifact) proving the findings they name; **8** are
pre-existing tests that the fix *un-broke* — 3 Q-02 (S1 restorations) and 5 C4
(4 certified-slice casualties of the contamination plus the appended class's
own 2 counted above). No test fails for an unrelated reason.

**AFTER — merge tip `3174a3d`: exit=0, 81 tests, 0 FAILED**

```
........................................................................ [ 88%]
.........                                                                [100%]
AFTER(merge tip 3174a3d) exit=0
```

14 → 0. The BEFORE worktree was created for this run only, restored clean and
removed (`git worktree remove --force`, exit 0, directory verified GONE);
`git worktree list` is back to **35** entries, the count on entry.

## Gate integrity — re-run on the new tip `3174a3d`

All four gates green, cwd = the isolated worktree, `PYTHONPATH=<worktree>/src`
on every invocation.

| Gate | Command | Result |
| --- | --- | --- |
| full suite | `PYTHONPATH=<wt>/src ./.venv/Scripts/python.exe scripts/run_tests.py -v` | `collected 2325 items` → **`2325 passed in 400.37s (0:06:40)`** — `run_tests exit=0` |
| lint (C3) | `uvx ruff check src tests` | `All checks passed!` — exit 0 |
| strict types | `PYTHONPATH=<wt>/src uvx pyright src` | `0 errors, 0 warnings, 0 informations` — exit 0 |
| tests types | `PYTHONPATH=<wt>/src uvx pyright --pythonpath <abs wt venv python> --project pyrightconfig.tests.json` | `0 errors, 1 warning, 0 informations` — exit 0 |

Suite header, verbatim: `platform win32 -- Python 3.14.1, pytest-9.1.1,
pluggy-1.6.0`; `rootdir: C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\mergepauto1`.

The single pyright warning is pre-existing and outside the delta
(`tests/test_research_program.py:144:23`, `reportSelfClsParameterName`) —
identical to the warning recorded at `8fd6ef1`, so the delta added none.

Count lineage, independently re-derived:

| Figure | Derivation |
| --- | --- |
| 2304 | baseline `c6076d5` collected total |
| 2318 | `8fd6ef1` = 2304 + 14 (`test_p_auto_1_sequencer.py` at `8fd6ef1`) — the prior audit's figure, reproduced |
| **2325** | `3174a3d` = 2304 + **21** |
| +4 | `test_p_auto_1_sequencer.py` 14 → 18 (`TestSequencerArtifactOutOfDispatchOrdering` 2, `TestSequencerFaultNotes` 2) |
| +1 | `test_controller_q04.py` `test_note_still_fires_after_a_prior_sequencer_pass` |
| +2 | `test_controller_c4.py` `TestSequencerArtifactNotAnOrderingParticipant` |
| 21 | 14 + 4 + 1 + 2 — reconciles 2318 → 2325 exactly, **+7** |

No test was deleted or skipped to reach green: `tests/test_controller_c4.py`
and `tests/test_controller_q04.py` are pure appends (`47 0`, `26 0`), and
`tests/test_controller_q02.py`'s `+5/−2` removes only the retargeted
assertion *text*, restoring four stronger originals in its place.

## Addendum — gates re-run on the final tip `5f0a121`

The table above is at `3174a3d`. Committing this document moved the tip to
`5f0a121`, and per AGENTS.md a docs-only change still requires the full
suite green, so all four gates were re-run at the new tip. INV7–INV11 prove
the doc commit changed no `src/` or `tests/` byte, which makes the re-run a
formality; it is recorded anyway.

| Gate | Result at `5f0a121` |
| --- | --- |
| full suite | `collected 2325 items` → **`2325 passed in 436.83s (0:07:16)`** — `run_tests exit=0` |
| lint (C3) | `All checks passed!` — exit 0 |
| strict types | `0 errors, 0 warnings, 0 informations` — exit 0 |
| tests types | `0 errors, 1 warning, 0 informations` — exit 0 (same pre-existing `tests/test_research_program.py:144:23`) |

### Disclosed flake — one contended suite run, then green twice

A **first** suite run at `5f0a121` reported `1 failed, 2324 passed in
431.15s (0:07:11)`, exit 1:

```
FAILED tests/test_controller.py::test_12_f2_operator_round_trip_latency_documented
>       assert resolve >= refusal * 0.7
E       assert 0.09779410000192001 >= (0.14158540000062203 * 0.7)
tests\test_controller.py:2355: AssertionError
```

That assertion is a **wall-clock latency probe**, not a logic predicate: the
test times a single-KDF budget, a wrong-token gate refusal and a full
APPROVED gate resolve, then asserts the resolve is never much cheaper than
the refusal. The bound was missed by **1.3%** (`0.09779` vs `0.09911`). The
run was contended — `ruff` and both `pyright` invocations were executing
concurrently with it.

Attribution, in order of strength:

| Evidence | Result |
| --- | --- |
| `git diff --exit-code 8fd6ef1 5f0a121 -- tests/test_controller.py` | **IDENTICAL** — the FIX2 delta never touched the file |
| `git diff --numstat c6076d5 8fd6ef1 -- tests/test_controller.py` | `2 1` — one hunk, at `:825`, from `51293da` |
| the `:825` hunk | `count_rows(db, "tasks") == 1` → `== 2` in `test_10_rerun_idempotent_no_duplicates`, 1530 lines from the flake, no timing content |
| the flaky test re-run **alone**, nothing else on the box | **pass**, exit 0 |
| full suite re-run **alone** at `5f0a121` | **`2325 passed`**, exit 0, zero `FAILED` lines |
| full suite at `3174a3d` (identical `src`+`tests`) | **`2325 passed`**, exit 0 |

So the probe is pre-existing, is not in this line's delta, and is not
sensitive to anything the line changed — it is sensitive to CPU load, which
was self-inflicted by the auditor. It does not bear on the verdict.

The `:825` hunk is worth stating explicitly because it is the same *class* of
edit as S1 (an expectation widened to accommodate the seq artifact), and it
remains **correct** after the FIX2 filter: the filter excludes the artifact
from `_discover_eligible`, not from the `tasks` table, so the row genuinely
exists and the count genuinely is 2. Verified green in every run above.

**Lesson carried: never run a static gate concurrently with the full suite on
this box.** All figures in the two gate tables above are from uncontended
runs except the discarded one, whose raw output is quoted verbatim here
rather than deleted.

## Forbidden-topic scan

Delta-scoped over `git diff 8fd6ef1 59ad5bf`
(`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`, word-boundary
matched): **0 hits**.

Over the docs leg `git diff 8fd6ef1 af14bbb`: **2 hits**, both on adjacent
lines of the added `MERGE-AUDIT-P-AUTO-1.md`:

```
25:+STOP-topic scan over the full diff (`backtest_audit`, `SDA`, `TSE`,
26:+`Optimize-my-strategy`): **0 hits**. No STOP condition on scope.
```

That is the prior audit **reporting its own scan pattern** — the charter's
vocabulary quoted in order to record a nil result, not the topics being
worked on. **Reported, not triggered**, matching this repo's established
precedent for exactly this situation. A hard halt here would make the charter
unexecutable: the base `main@c6076d5` the director declared immovable itself
carries the prose at `docs/ARCHITECTURE.md:19` ("run external engines in-repo
(`backtest_audit`, feature/statistical …"), a file untouched by both lines,
and six further pre-existing docs contain the same scan boilerplate. No
STOP condition on scope is asserted.

## Post-audit integrity checks

- `git rev-parse HEAD` in the worktree when the audit body was written:
  `3174a3dd92550da862f793629961af84f2a7baf8`; after the two docs commits on
  this file, `5f0a121` and then the addendum. `git symbolic-ref --short HEAD`
  → `merge/p-auto-1` throughout.
- `git status --porcelain` before this doc was written: **empty** — no stray
  tracked modification, no src change made by this audit. The only untracked
  entry is the gitignored `.venv` junction, never staged.
- `main` local == `main` remote == `c6076d5f978a4c4b49574d1af6f02cafd63750f5`,
  checked **before the merge, immediately after the merge, and again at the
  close of this audit**. `main` was never checked out, reset, rebased,
  committed to or pushed. Not advanced.
- **No `git push` of any ref was performed.** `git ls-remote origin
  'refs/heads/merge/*'` returns 11 branches and `merge/p-auto-1` is not among
  them: `3174a3d`, `af14bbb`, `59ad5bf`, `8efb3b3`, `5b9e937`, `5f0a121` and
  the addendum commit exist only in the local object store. D9 lapsed with the
  prior FAIL and this charter covers merge + re-audit only; **stopped before
  push** as instructed.
- Read-only trees respected: `fix2` (`fix/p-auto-1-fix2@59ad5bf`) and
  `fix2-before` (`8fd6ef1` detached) were read via `git show` / `git diff` and
  never written, checked out over, or pruned. The shared checkout
  `D:/New folder/research-agent` stayed on `fix/p-auto-1-gap@8fd6ef1`,
  unmodified.
- The BEFORE worktree was self-built (not `fix2-before`), used for one run,
  restored clean and removed; `git worktree list` count is back to **35**.
- All gate and A/B logs were written to `/tmp/…`, outside every worktree tree.
- Probes were read-only (in-memory databases); no repository writes outside
  the single merge commit and the docs commits on this file (`5f0a121`, then
  the gate addendum). `5f0a121` is pinned docs-only by INV7–INV11; the
  addendum commit is pinned the same way and the `git diff --exit-code … -- src
  tests` proof is reported with the charter deliverable, since a commit cannot
  cite its own hash from inside itself.
- **Disclosure (repeat of the prior audit's, still unresolved and deliberately
  untouched):** during the merge, git reported
  `error: failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4': Permission denied`
  while pruning a **stale, pre-existing** worktree admin directory unrelated
  to this line. The merge landed correctly — `3174a3d` with the two expected
  parents, clean status, correct tree per INV1–INV5 — and HEAD was verified
  immediately after. The stale directory was **left in place, not
  force-removed**, per "do not touch … other agents' branches/worktrees". It
  should be cleaned up by whoever owns it.

## Carry-forward for a fresh D9

Blocking: **none**. M1–M4 closed with red-then-green proof; S1 and S3 closed;
scope clean; four gates green at 2325 on `3174a3d` **and** on the final tip
(addendum). One contended suite run flaked on a pre-existing wall-clock probe
outside this line's delta; disclosed, attributed, and green on both
uncontended re-runs.

Non-blocking, for a future cleanup pass — none of it a push blocker, and none
of it fixable on this branch without a src change the charter forbids:

1. **S2** — `51293da`'s message says 11 tests (now 18) and asserts the
   retracted starvation-freedom lemma. Discharged by record in §S2; a history
   rewrite is the only other route and is forbidden.
2. **O1** — dead `adj` initialization, `controller.py:4316-4317`.
3. **O2** — terminalization through the fenced repository rather than
   `apply_intent`, `controller.py:4374-4376`; unreachable in the idle case.
4. **O3** — redundant second `_is_sequencer_task` filter,
   `controller.py:4298-4300`, dead since `:2738` took over the job.
5. The stale `.git/worktrees/step-4` admin entry, by its owner.
