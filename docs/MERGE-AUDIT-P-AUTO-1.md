# MERGE-AUDIT-P-AUTO-1 — adversarial audit of `merge/p-auto-1@8fd6ef1`

Audit of the P-AUTO-1 planner/sequencer line for merge onto `main`.
Findings only. Counts and `file:line`. Executed in an isolated worktree;
the shared checkout and other agents' branches were never touched.

## Inputs receipt (all readable, no STOP)

| Input | Value | State |
| --- | --- | --- |
| `main` (local) | `c6076d5f978a4c4b49574d1af6f02cafd63750f5` | read |
| `main` (remote) | `c6076d5f978a4c4b49574d1af6f02cafd63750f5` | identical — unmoved |
| `merge-base main HEAD` | `c6076d5f978a4c4b49574d1af6f02cafd63750f5` | == `main` — FF valid |
| slice commit | `51293da` | read |
| MUST-FIX commit | `fdbcb4f` | read |
| GAP commit | `8fd6ef1045c7ee475a985c93ab0aca5484381296` | read — line tip |
| redteam audit | `audits/AUDIT-P-AUTO-1-REDTEAM.md` on `audit/p-auto-1-redteam@45816dc` | read (input only, not merged) |

STOP-topic scan over the full diff (`backtest_audit`, `SDA`, `TSE`,
`Optimize-my-strategy`): **0 hits**. No STOP condition on scope.

## Isolation and import proof

Isolated worktree `merge/p-auto-1@8fd6ef1`; baseline detached worktree at
`c6076d5` for A/B. Gates invoked with the shared venv interpreter, cwd =
worktree, `PYTHONPATH=<worktree>/src`. Import proof per probe:
`hermes.__file__` resolved to `<worktree>/src/hermes/__init__.py` and the
normalized-path assertion passed, so every measurement below is attributed to
the intended tree and not to the editable install.

## Verdict: FAIL — do not push

Two MUST-FIX findings are **regressions against closed/certified slices**
(Q-04 §3.4, C4 §2.4 AC-5), each reproduced A/B against baseline, and each
**masked rather than fixed** by this line's own test updates. Per AGENTS.md,
changes near certified surfaces require a design gate plus the owning
certification slice re-run; neither is present. All four gates are green
(§Gate integrity) — the suite does not detect M1 or M2, so green gates are
not evidence against them.

`main` was **not** fast-forwarded and **not** pushed.

The blocking set is **M1–M4**. M1 and M2 are the certified-slice regressions
and are each independently sufficient to fail the merge; M3 and M4 mean the
F3 remediation that this line landed does not reliably record faults, so F3
cannot be treated as closed.

## MUST-FIX (blocking)

### M1 — the inert seq row permanently suppresses the certified Q-04 §3.4 cone-blocked dispatch diagnostic

`_sequencer_pass` filters sequencer tasks out of its own view
(`controller.py:4286-4288`), but `_dispatch_pass` (`controller.py:4425`)
consumes the **unfiltered** `_discover_eligible()` (`controller.py:4428`).
The seq artifact is admitted `PENDING` and is never terminalized once real
work runs out: `_sequencer_pass` returns early at `controller.py:4289-4290`
when no non-sequencer task is eligible, so the supersede/cancel loop at
`controller.py:4358-4369` is unreachable. `if not tasks:` at
`controller.py:4440` is therefore permanently `False` for any project that
has ever completed one sequencer pass, and `_cone_blocked_dispatch_notes()`
(`controller.py:4015`) is never called again.

Measured, fixtures identical to
`tests/test_controller_q04.py::TestConeBlockedDispatchNote` plus a prior
sequencer pass (sequence real work → terminate it → then fail and classify an
ancestor so a dependent is cone-blocked):

| | baseline `c6076d5` | tip `8fd6ef1` |
| --- | --- | --- |
| `_cone_blocked_dispatch_notes` calls on the idle tick | 1 | **0** |
| note emitted | `Q-04: dispatch blocked by failure cone of task A (FAILED — REFUTED); blocked dependents: B` | **none** |
| eligible set at the idle tick | `[]` | `['seq-p1-8cb11210…']` (`PENDING`) |

The certified test still passes because it never exercises a prior sequencer
pass. This is a coverage gap, not a green gate.

### M2 — the seq row contaminates the Q-02 ordering observable and the C4 floor ranking

Same unfiltered consumption: the seq row is ranked by `_order_eligible`
(`controller.py:4430`) and fed to `_persist_floor_transitions`
(`controller.py:4439`).

Quiescence is lost — an idle tick with zero real work:

| | baseline | tip |
| --- | --- | --- |
| `ordering_policy_version` | `''` | `'task-eval-2026.1'` |
| `result.unhandled` | `[]` | `['seq-p1-69fe0ef2…']` |

The seq row is the ranked **leader** under a live advancing clock
(`wave2 ranked LEADER = ['seq-p1-a2f9d94c…']`, real tasks admitted at later
`created_at`), so the *ranking* contamination is production-reachable and not
a frozen-clock artifact. Limit of this evidence: in that live-clock run
`FloorGrantRecorded` was 0 on **both** trees, so a live-clock *grant*
differential was not demonstrated — the grant loss below is measured under
the frozen-clock fixture timing only. The ranking exposure is proven; whether
it reaches a lost grant in production depends on the floor's own trigger
conditions and is unproven either way.

Under the **original** `test_controller_c4.py` fixture timing the floor grant
is eliminated:

| | baseline | tip |
| --- | --- | --- |
| `FloorGrantRecorded` | 1 (`t-n`, `FLOOR_GRANTED`, `research_program:rp-B`) | **0** |
| dispatch order | `['t-l1','t-n']` (floor intervened) | `['t-l1','t-l2']` (pure policy) |
| ranked leader | `t-l2` (real) | `seq-p1-23b941b6…` (inert) |

This line's response was to **re-time the fixture**
(`test_controller_c4.py::_monopoly_setup`, `2026-01-01T01/02/03:00` →
`2025-12-31T23:00/23:30/23:45`) so the clock-created seq row ranks last.
That preserves AC-5 for the new timing but removes coverage of the
*seq-row-outranks-real-tasks* condition, which is reachable in production
per the live-clock measurement above. Owning slice: C4 §2.4 AC-5.

### M3 — F3's blanket handler records routine absence as a fault

`task_repo.get(seq_task_id)` (`controller.py:4374`) signals absence by
raising. On the **first** sequencer pass the row does not exist yet, so the
normal happy path emits
`sequencer: get fault: Task not found: seq-p1-69fe0ef2…`
(`controller.py:4377-4379`). Measured on the first pass of every probe run.
The channel F3 exists to protect is polluted on 100% of first passes, and a
genuine fault at that site is now indistinguishable from routine absence.

### M4 — constant `_note_once` keys make distinct faults silently replaceable

`_note_once` (`controller.py:491-515`) dedupes by `key` and **overwrites in
place** (`self._notes[existing] = message`). The three F3 sites use constant
keys: `"sequencer:cancel-fault"` (`controller.py:4368`),
`"sequencer:get-fault"` (`controller.py:4378`), `"sequencer:fault"`
(`controller.py:4419`). N distinct `task_id`s or distinct exception types
under one class collapse to a single note, last-writer-wins; earlier distinct
faults are erased. Contrast the documented convention at
`controller.py:501-503` (`"plan-admission:incomplete:<program_id>"`), which
embeds the identity in the key.

## SHOULD-FIX

### S1 — tautological assertions in the Q-02 test updates

`tests/test_controller_q02.py:821-827` and `:966-972` assert
`[t["task_id"] for t in ordered] == ["t-next"] + [t["task_id"] for t in ordered if t["task_id"].startswith("seq-")]`.
The seq portion is self-referential — it states that the seq rows present in
`ordered` are seq rows. It pins the real prefix but neither the seq count nor
its identity. `:671-682` converts `assert rederived() == ([], None)` to a
prefix-filtered form and flips `ordering_policy_version == ""` to
`== "task-eval-2026.1"`: the tests were retargeted to accept M2's
contamination rather than the contamination being fixed.

### S2 — commit-message count and claim drift

`51293da` states "Add new test file test_p_auto_1_sequencer.py with 11
tests"; the file carries **14** at the tip (`fdbcb4f` added 3 closure tests)
and the message was never corrected. `51293da` also states
"Starvation-freedom guaranteed by immutable DAG topology" — the exact claim
F2 retracted; the correction landed in `fdbcb4f` at
`controller.py:4262-4272` but the slice commit message still asserts the
retracted lemma.

### S3 — an assertion-free test is counted in the 14

`tests/test_p_auto_1_sequencer.py:247`
`test_starvation_freedom_documented` has a body of one comment plus `pass`:
it asserts nothing, always passes, and is one of the 14 counted new tests.
Graded SHOULD-FIX, not MUST-FIX, because the body states its own intent
("This is a documentation test — the property is verified by
`TestSequencerDependencyRespect` and `TestSequencerOrderingDeterminism`") and
the substantive F2 assertion did land at
`tests/test_p_auto_1_sequencer.py:261`
(`assert seq_2 == sorted([extract_id_1, extract_id_2])`). The residual issue
is bookkeeping: a documentation-only stub inflates the closure count for F2,
whose remediation is otherwise only the reworded note at
`controller.py:4262-4272`. Give it an assertion or drop it from the count.

## Observations (non-blocking)

- **O1 — dead store.** `controller.py:4305`
  `adj: dict[str, list[str]] = dict.fromkeys(task_ids, [])` is immediately
  overwritten by `:4307-4308`. The aliasing comment at `:4306` is correct;
  the initialization itself is dead.
- **O2 — terminalization outside the gateway.** `controller.py:4362`
  `task_repo.transition_status(old_seq_id, CANCELLED, caused_by="sequencer", …)`
  writes durable state through the Controller's fenced repository path rather
  than `apply_intent`, and introduces a new `caused_by` actor string. It
  mirrors the certified recovery-ladder pattern (Controller is one of the 4
  certified acquisition owners) and is journalled, so it is within the
  existing envelope — but it is the line's only terminalization site and it is
  unreachable in the idle case (M1).

## Verified clean (no finding)

- **Scope.** Exactly 1 src file changed: `src/hermes/research/controller.py`,
  **+200/−0** — a pure addition; no existing behavior textually removed.
  `git diff --stat c6076d5 8fd6ef1`: 7 files, 785 insertions, 26 deletions.
- **Authority.** No new intent kinds, no `internal_only` change, no LLM/model
  routing. The only intent emitted is `IntentKind.ADMIT_TASK` with
  `proposed_by="DETERMINISTIC"`, `origin_kind="deterministic"`
  (`controller.py:4384-4406`). Determinism-owns-control preserved.
- **Append-only.** No `DELETE` introduced.
- **F1 blast radius capped.** The seq artifact is recorded-only: `_classify`
  returns `"unhandled"` (`controller.py:4453-4456`) and dispatch never reads
  `spec.sequence`. Prefix/template forgery reaches ranking and observables,
  not execution.
- **F1 closed.** The predicate is the `spec.template` marker
  (`_is_sequencer_task`, `controller.py:4231-4252`), not the `seq-` prefix;
  pinned by `tests/test_p_auto_1_sequencer.py:392` (a `seq-trap` user task
  survives and is sequenced) and `:419`.
- **F4 closed.** Explicit `(created_at, task_id)` tie-break at
  `controller.py:4334-4337`, pinned by
  `tests/test_p_auto_1_sequencer.py:451`.
- **Project isolation.** The raw sweep at `controller.py:4353-4357` is
  project-scoped and read-only; the `LIKE 'seq-%'` pre-filter narrows while
  the template predicate decides.
- **Payload discipline.** The seq spec carries `template`, `sequence`,
  `sequencer_version` only; no oversized-verdict path added.

## Gate integrity — re-run in the isolated tree

All four gates green on tip `8fd6ef1`. Recorded because the verdict is FAIL
*despite* them: M1 and M2 are invisible to the suite.

| Gate | Result |
| --- | --- |
| `.venv/Scripts/python.exe scripts/run_tests.py -v` | `2318 passed in 446.18s (0:07:26)` — exit 0 |
| `uvx ruff check src tests` | `All checks passed!` — exit 0 |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` — exit 0 |
| `uvx pyright --pythonpath <abs venv python> --project pyrightconfig.tests.json` | `0 errors, 1 warning, 0 informations` — exit 0 |

The single pyright warning is pre-existing and outside the diff
(`tests/test_research_program.py:144:23`, `reportSelfClsParameterName`).

Count lineage, independently re-derived:

| Figure | Derivation |
| --- | --- |
| 2304 | baseline `c6076d5` collected total |
| 146 | `51293da` focused selection: `test_controller.py` 109 + `test_idr045_plan_admission_and_provenance.py` 26 + `test_p_auto_1_sequencer.py` 11 |
| 14 | `test_p_auto_1_sequencer.py` at tip (`fdbcb4f` added 3 closure tests, 11 → 14) |
| 117 | `8fd6ef1` focused selection: `test_controller_q02.py` 39 + `test_controller_c4.py` 10 + `test_provider_orchestration.py` 68 |
| 2318 | full suite at tip = 2304 + 14 |

## Redteam dispositions

| Item | Claimed | Audit finding |
| --- | --- | --- |
| F1 | closed | **Agreed** — template predicate, pinned by 2 tests |
| F2 | closed | **Disputed** — note reworded, but the counted closure test is assertion-free (S3) |
| F3 | closed in GAP | **Disputed** — M3 and M4: the recording is present but unreliable |
| F4 | closed | **Agreed** — explicit tie-break, pinned by 1 test |
| admission-reserve | parked by director decision | Noted; out of scope for this audit |

## Post-audit integrity checks

- `git status --porcelain --untracked-files=no` in the worktree: empty before
  the docs were written — no stray tracked modifications, no src changes
  made by this audit.
- `main` local == `main` remote == `c6076d5f978a4c4b49574d1af6f02cafd63750f5`
  at the close of the audit: **not advanced**.
- No `git push` of any ref was performed.
- Probes were read-only (in-memory databases); no repository writes.
- Gate logs and probe scripts were kept outside the worktree tree except the
  suite log, which remains untracked and was never staged.
- Disclosure: during the earlier FF of `merge/p-auto-1`, git reported
  `failed to delete '.git/worktrees/step-4': Permission denied` while pruning
  a **stale, pre-existing** worktree admin directory unrelated to this line.
  HEAD was verified correct at `8fd6ef1` immediately after; the merge was
  unaffected. The stale directory was left in place, not force-removed.
