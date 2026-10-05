# MERGE-LOG-P-AUTO-1 — integration of the P-AUTO-1 planner line onto `main`

Merge integrator record for the P-AUTO-1 deterministic planner/sequencer
line. Follows the `MERGE-LOG-045-FIXLINE` pattern.

**Outcome: the line was integrated and verified on `merge/p-auto-1`, but the
adversarial merge-audit returned FAIL. `main` was NOT fast-forwarded and NOT
pushed.** See `docs/MERGE-AUDIT-P-AUTO-1.md`.

## Inputs

| Input | Value |
| --- | --- |
| Repository | `D:\New folder\research-agent` (`ace2013hieco-aa/khwarizmi-research`) |
| `main` at task start (local) | `c6076d5f978a4c4b49574d1af6f02cafd63750f5` |
| `main` at task start (remote) | `c6076d5f978a4c4b49574d1af6f02cafd63750f5` |
| Redteam audit (input only) | `audits/AUDIT-P-AUTO-1-REDTEAM.md` on `audit/p-auto-1-redteam@45816dc` |
| Human approval banked | D9 — merge P-AUTO-1 line to `main`; verify-then-push standing |

`main` was verified unmoved (local == remote) before and after the merge, so
the "main moved under you" STOP condition did not fire.

## Merge hashes

| Ref | Hash |
| --- | --- |
| `merge-base main HEAD` | `c6076d5f978a4c4b49574d1af6f02cafd63750f5` (== `main`) |
| `merge/p-auto-1` tip (line tip, pre-docs) | `8fd6ef1045c7ee475a985c93ab0aca5484381296` |
| `main` old | `c6076d5f978a4c4b49574d1af6f02cafd63750f5` |
| `main` new | **unchanged** — `c6076d5f978a4c4b49574d1af6f02cafd63750f5` |

## Line integrated (3 commits, `c6076d5..8fd6ef1`)

| Commit | Subject |
| --- | --- |
| `51293da` | P-AUTO-1: deterministic planner/sequencer (DETERMINISTIC via ADMIT_TASK) |
| `fdbcb4f` | fix(p-auto-1): template-marker seq predicate plus starvation-note correction plus fallback tiebreak |
| `8fd6ef1` | fix(p-auto-1-gap): seq-row test accounting for 9 red assertions plus F3 fault recording |

Diffstat `c6076d5..8fd6ef1` — 7 files, 785 insertions, 26 deletions:

```
 src/hermes/research/controller.py                  | 200 ++++++++
 tests/test_controller.py                           |   3 +-
 tests/test_controller_c4.py                        |  15 +-
 tests/test_controller_q02.py                       |  34 +-
 tests/test_idr045_plan_admission_and_provenance.py |  37 +-
 tests/test_p_auto_1_sequencer.py                   | 519 +++++++++++++++++++++
 tests/test_provider_orchestration.py               |   3 +-
```

The single src file is **+200/−0** — a pure addition. P-AUTO-2, spikes and
intake docs were not integrated; the redteam audit stays on its own branch.

## Conflicts and resolutions

**Zero conflicts.** The merge base equals `main`, so the integration was a
clean fast-forward to `8fd6ef1` exactly as the task predicted. No conflict
repair was needed and **no src changes were made by the integrator**.

Disclosure: during the fast-forward, git reported
`failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4':
Permission denied` while pruning a **stale, pre-existing** worktree admin
directory unrelated to this line. `HEAD` was verified correct at `8fd6ef1`
immediately afterwards and the merge was unaffected. The stale directory was
left in place rather than force-removed.

## Gate results (on the merged tree, tip `8fd6ef1`; all re-run by this task)

Run in the isolated worktree with the shared venv interpreter, cwd =
worktree, `PYTHONPATH=<worktree>/src`.

| Gate | Command | Result |
| --- | --- | --- |
| Full suite | `scripts/run_tests.py -v` | `2318 passed in 446.18s (0:07:26)` — exit 0 |
| Lint (C3) | `uvx ruff check src tests` | `All checks passed!` — exit 0 |
| Types (src, strict) | `uvx pyright src` | `0 errors, 0 warnings, 0 informations` — exit 0 |
| Types (tests) | `uvx pyright --pythonpath <abs venv python> --project pyrightconfig.tests.json` | `0 errors, 1 warning, 0 informations` — exit 0 |

The single pyright warning is pre-existing and outside the diff
(`tests/test_research_program.py:144:23`, `reportSelfClsParameterName`).

`scripts/run_tests.py` cannot be run from a bare worktree — its `.venv` path
is `__file__`-relative and would scrub all non-own site-packages. The shared
`run_tests.py` was therefore invoked with the shared venv python from the
worktree cwd, with `PYTHONPATH` pointing at the worktree `src`. The editable
install is a plain `.pth` (no PEP-660 meta-path finder), so `PYTHONPATH`
takes precedence; the import was proven per run by asserting
`hermes.__file__` resolves inside the worktree.

### Gate lineage `146 → 14 → 117 → 2318` (independently re-derived)

| Figure | Derivation |
| --- | --- |
| 2304 | baseline `c6076d5` collected total (reference point) |
| **146** | `51293da` focused selection — `test_controller.py` 109 + `test_idr045_plan_admission_and_provenance.py` 26 + `test_p_auto_1_sequencer.py` 11 |
| **14** | `test_p_auto_1_sequencer.py` at tip — `fdbcb4f` added 3 closure tests, 11 → 14 |
| **117** | `8fd6ef1` focused selection — `test_controller_q02.py` 39 + `test_controller_c4.py` 10 + `test_provider_orchestration.py` 68 |
| **2318** | full suite at tip = 2304 baseline + 14 new |

The director's `2318` was reproduced exactly, not merely accepted.

## Audit dispositions

Redteam items as dispositioned by the merge-audit (full findings, with A/B
measurements, in `docs/MERGE-AUDIT-P-AUTO-1.md`):

| Item | Line claim | Audit |
| --- | --- | --- |
| F1 — forgeable `seq-` prefix | closed | **Agreed** — `spec.template` predicate at `controller.py:4231-4252`, pinned by 2 tests |
| F2 — false starvation-freedom lemma | closed | **Disputed** — note reworded at `controller.py:4262-4272`, but the counted closure test at `tests/test_p_auto_1_sequencer.py:247` is assertion-free (S3) |
| F3 — silent `contextlib.suppress` sites | closed in GAP | **Disputed** — recording is present but unreliable: routine absence is logged as a fault (M3) and constant dedupe keys erase distinct faults (M4) |
| F4 — implicit cycle-fallback tie-break | closed | **Agreed** — explicit `(created_at, task_id)` key at `controller.py:4334-4337`, pinned by 1 test |
| admission-reserve | parked by director decision | Noted; out of scope |

Two new blocking findings were raised by this audit and are **not** in the
redteam list:

- **M1** — the never-terminalized `PENDING` seq row permanently defeats
  `if not tasks:` at `controller.py:4440`, suppressing the certified Q-04
  §3.4 cone-blocked dispatch diagnostic. Reproduced A/B: baseline emits the
  note, tip emits nothing (0 diagnostic calls on the idle tick).
- **M2** — the same row is ranked by `_order_eligible`
  (`controller.py:4430`) and fed to `_persist_floor_transitions`
  (`controller.py:4439`): `ordering_policy_version` never returns to
  quiescent `''`, the seq row is the ranked leader under a live clock, and
  under the original c4 fixture timing `FloorGrantRecorded` drops 1 → 0 with
  dispatch degenerating to pure-policy order (C4 §2.4 AC-5). The line
  re-timed `_monopoly_setup` rather than fixing the behavior.

M1 and M2 regress two closed/certified slices, which per AGENTS.md require a
design gate plus the owning certification slice re-run. Neither is present.
The full suite does not detect either, so the green gates are not evidence
against them.

## Carry-forward: what the next line must do

1. Terminalize or filter the seq artifact so it cannot occupy the eligible
   set indefinitely — either filter sequencer tasks in `_dispatch_pass`
   (`controller.py:4428`) as `_sequencer_pass` already does
   (`controller.py:4286-4288`), or supersede the stale row on the idle path
   that currently returns early at `controller.py:4289-4290`.
2. Re-run the owning certification slices (Q-04 §3.4, C4 §2.4 AC-5) and add
   coverage for the *prior-sequencer-pass* sequence the existing tests never
   exercise.
3. Distinguish routine absence from fault at `controller.py:4374` (M3) and
   put identity in the `_note_once` keys (M4).
4. Give `test_starvation_freedom_documented` a real assertion or drop it
   from the counted closures (S3).

## Post-merge integrity checks

- `main` local == `main` remote == `c6076d5f978a4c4b49574d1af6f02cafd63750f5`
  at the close of the task — **not advanced**.
- No `git push` of any ref was performed; D9 was not exercised because its
  precondition (audit PASS) was not met.
- All work confined to the isolated worktree; the shared checkout and other
  agents' branches were never touched.
- `git status --porcelain --untracked-files=no` clean apart from the two docs
  committed here; the suite log stayed untracked and was never staged.
- Only the two deliverable docs were added — one concern per commit, no src
  changes, no unrelated files.

## Verdict

**Integrated and verified; NOT merged.** `merge/p-auto-1` carries the line at
`8fd6ef1` plus these two docs. `main` remains at `c6076d5`. The merge is
blocked on the merge-audit FAIL (MUST-FIX M1–M4); the STOP condition
"merge-audit FAIL — fix, do not push" was honored. Because every MUST-FIX
requires a src change in `controller.py` and this task is constrained to
"no src/ changes except conflict repair", the fixes were **not** applied here
and the MUST-FIX list is handed back for a follow-up line.
