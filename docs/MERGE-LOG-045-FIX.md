# MERGE-LOG-045-FIX — integration of `merge/fix-045` onto `main`

**Branch:** `merge/idr045-fix`, created from `main@c2c8fa990a56d2ca4b980fb62680dc058f294b94`.
**Local-only. Nothing pushed — not this branch, not `merge/fix-045`, not `main`.**
**Verdict: PASS — clean, conflict-free integration, all gates green.**

## Inputs

| Input | Hash | State |
|---|---|---|
| Baseline | `main@c2c8fa990a56d2ca4b980fb62680dc058f294b94` | read; `origin/main` is the same commit |
| Integrand | `merge/fix-045@87af69682131c208faae1dcd24a298e1299ab815` | read |
| Live tree | 13 worktrees, several checked out by other sessions | verify-only reads; none modified |

**Isolation.** All work was done in a dedicated throwaway `git worktree`
(`%LOCALAPPDATA%\Temp\opencode\audit045`) branched from `c2c8fa9`. The root
checkout `D:/New folder/research-agent` is on another session's
`catalyst/a2-wording@43de295` and `main` is checked out in
`.worktrees/b1-breakit`; neither was touched, and `main` was never checked out
or advanced by this task. No other session's branch, worktree, or checkout was
modified — the only refs written were `merge/idr045-fix` (new) and this file.

**Forbidden-topic scan** (`backtest_audit|SDA|TSE|Optimize-my-strategy`) over
`git log -p c2c8fa9..merge/fix-045`: no hits. Nothing to report.

## Merge hashes

| Field | Value |
|---|---|
| Merge commit | `beed3cf8a2402581f5594ef44fb422542b8fcaca` |
| Parents | `c2c8fa990a56d2ca4b980fb62680dc058f294b94` (baseline) + `87af69682131c208faae1dcd24a298e1299ab815` (integrand) |
| Merge tree | `c94a303f4b3866c6de78b81dc49ba04f3076d5bb` |
| Integrand tree | `c94a303f4b3866c6de78b81dc49ba04f3076d5bb` — **identical** |
| Baseline tree | `5428ab75482c6a4753f3fe2176a5d24c2f391112` |
| Strategy | `git merge --no-ff` → `ort` |

`git merge-base c2c8fa9 87af696` = `c2c8fa9` itself, so `main` had no commits
beyond the fork point.

## Line integrated (7 commits, `c2c8fa9..87af696`)

| Hash | Subject |
|---|---|
| `96c52e7` | feat(idr-045): plan admission pass + intent provenance (D1+D2, C1–C6 closed) |
| `7695c0c` | docs(idr-045): adversarial implement audit — PASS with evidence (C1-C6, V1, V4, DIRECTOR, program_from_dict, follow-ons) |
| `34dd717` | docs(roadmap): close out IDR-045 — ratified D1-A/D2-A, audits 96c52e7/7695c0c PASS, Catalyst B0/B1/A2 + open-decisions recorded |
| `779d25f` | Merge branch 'idr-045/closeout' into merge/idr045 |
| `e5d4fb1` | docs(merge-log): record IDR-045 closeout integration (MERGE/idr045-to-main) |
| `84665d2` | docs(merge/audit): independent adversarial audit of merge/idr045@e5d4fb1 — **FAIL** |
| `87af696` | fix(idr-045): close MERGE-AUDIT-045 blockers + correct the IDR-045 record |

## Conflicts and resolutions

**None. Zero textual conflicts, zero resolution choices, no hand-edits.**

Because the merge-base *is* `c2c8fa9`, the integrand is a strict descendant of
the baseline: there was no same-file contention to resolve and no semantic
question to adjudicate. Verified mechanically rather than taken on trust:

- `git diff --stat 87af696 beed3cf` → **empty** (merge tree byte-identical to the integrand tip)
- `git ls-files -u` → empty (no unmerged paths)
- conflict-marker scan (`<<<<<<< `, `=======`, `>>>>>>> ` at line start) over all 15 changed files → 0 hits
- `git status --porcelain` immediately after the merge → clean

**Changed-file list (resolutions only): _none_.** No file required a resolution,
so the "no new code beyond conflict resolution" constraint was satisfied
trivially: the merge introduced no code of its own. The 15 files below arrived
whole from `87af696`.

| File | Δ | Origin |
|---|---|---|
| `ROADMAP.md` | +6/-2 | `34dd717` |
| `docs/IDR45-Q37-evidence.md` | +72 | **new** in `87af696` (from `e077898`) |
| `docs/IDR45-audit5.md` | +170 | **new** in `87af696` (from `92ba005`) |
| `docs/IDR45-impl-audit.md` | +117 | **new** in `7695c0c`, corrected in `87af696` |
| `docs/MERGE-AUDIT-045.md` | +599 | **new** in `84665d2` |
| `docs/MERGE-LOG-045.md` | +65 | **new** in `e5d4fb1` |
| `docs/idr/IDR-045.md` | +385 | **new** in `96c52e7`, corrected in `87af696` |
| `src/hermes/core/intents.py` | +54/-8 | `96c52e7` + `87af696` |
| `src/hermes/persistence/repositories.py` | +19 | `96c52e7` |
| `src/hermes/research/controller.py` | +175 | `96c52e7` + `87af696` |
| `src/hermes/research/gateway.py` | +91/-11 | `96c52e7` + `87af696` |
| `src/hermes/research/programs.py` | +91 | `96c52e7` + `87af696` |
| `src/hermes/research/task_plan.py` | +10/-2 | `96c52e7` + `87af696` |
| `tests/test_idr045_merge_audit_045.py` | +405 | **new** in `87af696` |
| `tests/test_idr045_plan_admission_and_provenance.py` | +693 | **new** in `96c52e7`, extended in `87af696` |

15 files, 2942 insertions(+), 10 deletions(-).

## Gate results (on the merged tree, tip `beed3cf`)

All gates re-run by this task, not inherited from `MERGE-LOG-045.md` or
`MERGE-AUDIT-045.md`. `PYTHONPATH` pinned to this worktree's `src` and verified
(`hermes.__file__` resolves inside the worktree) before each run.

### Full gates

| Gate | Raw output |
|---|---|
| `scripts/run_tests.py -v` (full suite) | `====================== 2267 passed in 373.20s (0:06:13) =======================` |
| `uvx ruff check src tests` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| `uvx pyright --pythonpath .venv\Scripts\python.exe --project pyrightconfig.tests.json` | `0 errors, 1 warning, 0 informations` |
| `scripts/check_census.py` | `PASS - every certified figure is reproduced exactly.` |

Census detail (the certified DG-5 / acquisition-owner oracle):

```
executed transaction-control calls              121 / 121  OK
acquisition owners (persistence)                 18 / 18   OK
acquisition owners (gateway)                      5 / 5    OK
acquisition owners (Controller)                   4 / 4    OK
acquisition owners (total)                       27 / 27   OK
rollback-only participants                        1 / 1    OK
persistence->research import statements          15 / 15   OK
control calls outside certified layers            0 / 0    OK
control calls by statement: BEGIN 28, COMMIT 27, ROLLBACK 66
```

The single tests-project warning is `tests/test_research_program.py:144:23
reportSelfClsParameterName` — line 144 is `def _canonicalize(value):`, an
instance method with no `self`. That file **is** inside the integrated set, so
"pre-existing" needs a real argument rather than the usual non-inclusion one, so
it was checked directly: `git diff c2c8fa9 87af696 -- tests/test_research_program.py`
is **empty** and line 144 is byte-identical in both revisions. The warning is
therefore inherited from `main@c2c8fa9` by construction, not merge-induced.
Reported, not fixed: changing that signature would be a non-mechanical edit,
outside this task's scope.

The same inheritance check was run for the one warning `pyright src` does *not*
report — none; `src` is clean at 0/0/0.

### Targeted re-runs (shared-surface slices)

| Suite | Result |
|---|---|
| `tests/test_idr045_merge_audit_045.py` | 20 passed in 0.31s |
| `tests/test_idr045_plan_admission_and_provenance.py` | 26 passed in 0.36s |
| `tests/test_task_plan.py` | 12 passed in 0.07s |
| `tests/test_gateway.py` | 41 passed in 0.80s |
| `tests/test_controller_q02.py` | 39 passed in 0.55s |
| `tests/test_research_program.py` | 81 passed in 0.40s |
| **Combined** | **219 passed in 2.00s, 0 failed** |

Both IDR-045 suites, plus the four surfaces the integrand actually modifies
(`task_plan`, `gateway`, `controller`, `programs`/`research_program`).

## What this merge brings in

Two adversarial audits and their closure, in order:

- `84665d2` audited `merge/idr045@e5d4fb1` and returned **FAIL** — merge fidelity
  was clean, but the payload had a post-commit refusal hole in the single
  mutation path (F2) and a plan-admission pass that swallowed every outcome.
- `87af696` closed both blockers and corrected eight record defects, adding
  `tests/test_idr045_merge_audit_045.py` (20 tests) as the executed proof.

The integrated result is self-describing: the FAIL verdict, its evidence, the
closure commit message, and the IDR's own audit-response section
(`docs/idr/IDR-045.md:350-371`, headed "MERGE-AUDIT-045 response") all ship
together, so a reader of the merged tree can audit the audit.

## Carry-forward: F3 and F4 remain OPEN (not absorbed by this merge)

`docs/MERGE-AUDIT-045.md` §6 listed 8 conditions; `87af696` closed 6 and left
two open by design, because both change eligibility semantics rather than
correcting a defect. They are recorded in-tree, not merely in this log:

- **F3 — the compiler-derived fence compares only `evidence_requirements`.**
  `derive_program_obligations` returns `gate_requirements` as well, and
  `task_plan.build_task_plan` selects the plan's gates from
  `program.gate_requirements` (`task_plan.py:130-131`). A row whose
  `gate_requirements` diverged from its hypotheses would produce a different
  admitted DAG without detection. Repository writes validate both
  (`repositories.py:1376-1379`), so only hand-written rows — precisely what the
  fence exists to guard — are exposed. One clause closes it
  (`or program.gate_requirements != expected_gates`).
  Recorded at `docs/idr/IDR-045.md:97` ("Known gap, not closed here (F3)") and
  cross-referenced from `controller.py:_plan_admission_pass`, where
  `_expected_gates` is left unused with a comment saying so.
- **F4 — `current_primary` is cited as the production mechanism but has no
  production caller.** The production eligibility query is the inline filtered
  `SELECT … WHERE project_id=? AND parent_program_id IS NULL ORDER BY version
  DESC LIMIT 1` in `controller._plan_admission_pass`; the repository method at
  `repositories.py:1711` is exercised only by the IDR-045 suite. The record was
  corrected to name the inline query as the production path; routing through the
  repository method is a de-duplication, not a behaviour change, and was left
  open. Recorded at `docs/idr/IDR-045.md:80` and in `ROADMAP.md`'s open-decisions
  bullet.

Neither blocks this integration: C1/Q7 filtered-head semantics hold either way,
and both items are documentation-vs-duplication cleanups, not correctness bugs.
Neither was silently closed.

Also acknowledged in-tree and **not** closed by the IDR-045 line: the
post-commit 4 KiB `validate_payload_size` hazard class, which pre-dates IDR-045
(`event_validation.py:150` is reached only from the post-commit audit append).
`87af696` removed the C5 guard from that position so IDR-045 no longer *adds* to
it, but the pre-existing class remains. Stated at
`docs/idr/IDR-045.md` D2.2.

## Post-merge integrity checks

| Check | Result |
|---|---|
| Merge tree == integrand tree | identical (`c94a303…`) — no hand-edit |
| Unmerged paths | none |
| Conflict markers in the 15 changed files | 0 |
| `main` after the merge | `c2c8fa9`, unchanged (never checked out here) |
| `origin/main` | `c2c8fa9`, unchanged |
| `merge/fix-045` | `87af696`, unchanged |
| `git ls-remote origin merge/idr045-fix merge/fix-045 merge/audit-045` | empty — nothing pushed |
| Other sessions' worktrees/branches | untouched; read-only |

## Verdict

**PASS.** Single integration branch `merge/idr045-fix` at `beed3cf`, forked from
`main@c2c8fa9`, integrating `merge/fix-045@87af696`. The merge was conflict-free
and byte-identical to the integrand (zero resolutions, zero hand-edits, no code
introduced by the merge itself). Full suite 2267 passed / 0 failed, ruff clean,
pyright `src` 0/0/0, pyright tests 0 errors + 1 pre-existing warning, census
oracle PASS, and 219 passed across the six targeted shared-surface suites. F3
and F4 carry forward as open and are recorded in-tree. `main` untouched, nothing
pushed anywhere, no other session disturbed.
