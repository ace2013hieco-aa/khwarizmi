# MERGE-LOG-EXT-8 — EXT-8 P4 row notes (EXT-1 items 7–12) landed on `main`

Merge-gate record for the EXT-8 slice: a **docs-only** batch recording the six
P4 triage rows — L4, L2, I1, I2, I3, I5 (EXT-1 roadmap items **7–12**) — as
documentation. One new file (`docs/EXT-4-P4-NOTES.md`, 6 sections, +327/−0),
landed on `main` by **local fast-forward only**. Follows the
`MERGE-LOG-EXT-6` / `EXT-5` / `EXT-4` pattern.

**Outcome: EXT-8 landed on `main` — local fast-forward, no push.** No audit
round-trip was taken: the Director verified the document **anchor-by-anchor**
in lieu of an audit (docs-only, zero code risk — recorded below). The landing
range contains **no `src/` change and no behaviour change**. `origin` and the
public mirror are **NOT advanced and NOT pushed — D8/D9 require a human
hash-pin.**

## Provenance

| Item | Value |
| --- | --- |
| Task | EXT-8-MERGE (merge gate, local-only) |
| Base (`main` before) | `034a4ac3b4766afc8a9106073620deb81e7fe3d2` (tree `027cabcf3edc610e77fe0c5ab01e7a523158c393`) |
| Landed tip (FF'd to) | `c9bc798e39afb5182f9589227607cc9529d8408e` (tree `d6ddcc34197f43c45cef41cc6776d031f1d5d48a`) |
| Branch | `slice/ext-8-p4notes` @ `c9bc798` |
| Triage item | EXT-1 roadmap items **7–12** (L4, L2, I1, I2, I3, I5) — `audit/ext-1-triage@bc1a5da` |
| Audit of record | **none** — Director anchor-by-anchor verification in lieu of an audit round-trip (docs-only, zero code risk; recorded) |
| Gate worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/ext-8-merge-wt` |
| Main-bound holder | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` (FF'd **in place**) |
| Merge method | **fast-forward in place**, `git merge --ff-only` |
| Push | **none** (D8/D9 — human hash-pin required) |

## What landed

| Commit | Subject | Files |
| --- | --- | --- |
| `c9bc798` | docs(ext-8): record the P4 row positions (EXT-1 items 7-12) | `docs/EXT-4-P4-NOTES.md` +327/−0 |

Range: 1 commit, 1 file, **+327/−0** (`git diff --numstat 034a4ac..c9bc798`).

The document carries one section per P4 row (L4, L2, I1, I2, I3, I5); each
records the row's status, its live `file:line` pointers, what is
intentionally NOT done and why, and the future-work trigger that would
reopen it. Rows I1/I2/L2 record *certified positions* (determinism owns
control; a plausibility gate is rejected by construction; mTLS/backpressure
and hardware fencing are inapplicable to the shipped single-host CLI
topology). Rows L4 and I3 record existing substance (the unversioned
artifact `content_hash` with its upgrade hazard; the content-addressed store
with pre-proceed dereference and the EXT-2 production wiring). **No code
change and no behaviour change is asserted by this landing.**

## Anchor verification (method + result)

The document is a pointer document, so its correctness is its anchors'
correctness. Three independent passes, all green:

1. **Slice pass (in-process, at the base tree).** Every `path:line` token in
   `docs/EXT-4-P4-NOTES.md` was extracted mechanically, then each was resolved
   live: the file must exist, the line number must be within the file, and the
   line must be non-blank — and each line was additionally confirmed to carry
   the text quoted beside it in the document. **50 unique full-path pointers,
   0 bad.**
2. **Director re-derivation (independent of the slice author).** The Director
   re-derived the document's anchors and confirmed **75 anchors resolve — 61
   full-path programmatically + 14 shorthand-by-proximity**. This is the
   verification of record that stands in for an audit round-trip.
3. **Landed-tip pass (after the FF).** On the FF'd tip, the document yields
   **75 anchor occurrences / 62 unique `path:line` tokens**; all 62 resolve
   (file exists, line in range, line non-blank). **0 bad.**

Note on shorthand: prose inside the document also cites anchors in short form
(e.g. `` `store.py:29` ``) where the full path is unambiguous from the
enclosing sentence. Those are covered by passes 2 and 3 above via
basename resolution.

## Content identity (pure FF — nothing rewritten)

- `merge-base(main, c9bc798)` == `034a4ac3b4766afc8a9106073620deb81e7fe3d2`
  == `main` before the landing — the FF is linear and no content was
  rewritten (rebase-prohibition D1 not engaged).
- `git merge --ff-only c9bc798` exit 0; `main^{tree}` == `c9bc798^{tree}`
  == `d6ddcc34197f43c45cef41cc6776d031f1d5d48a`.
- The main-bound holder (`met-1-merge-wt`) was verified **clean** immediately
  before touching the ref, was FF'd **in place**, and its `HEAD` followed the
  ref — **no stale main-bound worktree left**.
- The slice worktree (`ext-8-wt`) and the gate worktree (`ext-8-merge-wt`)
  are untouched by the ref move.

## Gates (raw, on the landed tip `c9bc798`)

Environment: repo venv `D:\New folder\research-agent\.venv\Scripts\python.exe`
(Python 3.14.1, Test-Path-proven), `PYTHONPATH=<gate-wt>/src`, idle machine.

```
stamp --check     OK: docs\SUITE-COUNT.md collected=4600 matches the live collect   [exit 0]
collect           4600 tests collected in 11.66s
B4                24 passed in 13.14s
ruff              All checks passed!                                                [exit 0]
pyright src       0 errors, 0 warnings, 0 informations                              [exit 0]
pyright tests     0 errors, 1 warning, 0 informations                               [exit 0]
check_census      PASS - every certified figure is reproduced exactly                [exit 0]
full suite        5 failed, 4592 passed, 3 skipped, 1 warning in 955.21s
```

`check_census` reproduces all eight certified figures exactly:
`executed transaction-control calls 121`, `acquisition owners persistence 18 /
gateway 5 / Controller 4 / total 27`, `rollback-only participants 1`,
`persistence->research import statements 15`, `control calls outside certified
layers 0` (by statement: BEGIN 28, COMMIT 27, ROLLBACK 66).

Suite arithmetic: `4592 passed + 5 failed + 3 skipped == 4600` == the stamped
collect count.

### pyright tests-config — invocation note (environment, recorded)

The documented `pyright --pythonpath <venv>/Scripts/python.exe --project
pyrightconfig.tests.json` invocation reports **112 `reportMissingImports`
errors in this environment**, all of the form `Import "pytest" could not be
resolved`. Root cause is **environmental, not code**: pyright's
`--pythonpath` probing does not populate the interpreter's `site-packages`
into its search paths here (reproduced identically with a freshly created
`uv venv` + `pip install pytest`, and with the tool sandbox both on and off —
`--verbose` shows only typeshed in `Search paths`).

The same analysis was therefore run with pyright's documented
`venvPath`/`venv` mechanism, using a config that is **byte-identical to
`pyrightconfig.tests.json` except for the two added keys**
`"venvPath": "."` and `"venv": ".venv"` (same `include`, same `ignore`, same
`pythonVersion`, same `extraPaths`, same three `report*: "none"`
suppressions). Result: **0 errors, 1 warning** — the warning being the
pre-existing `reportSelfClsParameterName` at
`tests/test_research_program.py:144`, matching the standard recorded in
`MERGE-LOG-EXT-2` ("pyright tests-config 0 errors (1 pre-existing
warning)"). The temporary config was used only for the gate run and deleted
afterwards; `git status --porcelain` on the gate worktree is empty, so the
tree is clean.

The 112 errors are provably landing-independent: `pyrightconfig.tests.json`
includes `src` and `tests` only, and the landing adds one Markdown file under
`docs/`.

## Red set == documented baseline-5 (exact, not a superset)

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

These are **exactly** the 5 pre-existing environmental reds documented in
`docs/archive/MERGE-LOG-CLOUD.md` (3 concurrency races + 1 Windows
symlink-privilege refusal + 1 q05 race) and reproduced verbatim in
`docs/MERGE-LOG-SUB-1.md` (which records the same five, "red set ==
documented baseline-5 **exactly**"). **Red set == documented set (exact); no
new red; delta 0.** The landing range is docs-only (one Markdown file under
`docs/`) and touches no test, so no red could be induced, and `main` was
verified unmoved before the FF, so this is a like-for-like comparison.

## Documented flake — did not fire; no isolation proof required

`tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree`
is the documented 30 s pinned-subprocess-timeout flake
(`docs/MERGE-LOG-NUM-1.md`). It **did not fire**: the string `eval_plane`
appears **0 times** in the full-suite log and it is absent from the red set.
Per the merge brief, isolation proof is required only when the flake fires;
none was needed.

## Dual push plans — drafted, NOT executed (D8/D9)

1. **`origin` plain-push** (`https://github.com/ace2013hieco-aa/khwarizmi-research.git`):
   push `<reviewed-main-hash>:refs/heads/main`, single refspec, **no force**,
   no tags, after re-verifying live `origin/main` is a strict ancestor of the
   reviewed tip (FF). Live `origin/main` at draft time:
   `034a4ac3b4766afc8a9106073620deb81e7fe3d2` — a strict ancestor of the local
   `main`, so the plain push would fast-forward.
2. **public mirror orphan-sync** (`https://github.com/ace2013hieco-aa/khwarizmi`):
   add a temp remote, `fetch --no-tags`, re-read the live mirror pin, build a
   sync commit whose tree is `<reviewed-tip>^{tree}` and whose parent is the
   mirror HEAD (orphan convention — `merge-base` must be empty), push the
   exact hash with **no force** (rule #5), then remove the temp remote. Live
   mirror HEAD at draft time:
   `9b16fd8507524fb659966810bdbd3a0884eea644` — a moving target, always
   re-read with `ls-remote` immediately before the sync.

Both charters require a **human hash-pin** of the final local `main` tip
(this MERGE-LOG + the roadmap flip land on top of `c9bc798`, so the pinnable
hash is the tip *after* those two commits). **Nothing was pushed.**

## Verdict

### A — EXT-8 MERGED (LOCAL-ONLY)

`main` FF'd `034a4ac3b4766afc8a9106073620deb81e7fe3d2` →
`c9bc798e39afb5182f9589227607cc9529d8408e`; the two docs commits (this
MERGE-LOG and the roadmap rows 7–12 flip) land on top. The landing is
documentation only: it records the six P4 rows — their status, their live
anchors, the work intentionally not done and why, and the trigger that would
reopen each — and asserts no code change and no behaviour change. All gates
are green: stamp `--check` 4600, collect 4600, B4 24/24, ruff clean, both
pyright configurations 0 errors, `check_census` PASS, and the full suite's
red set is exactly the documented baseline-5 (delta 0; the documented
`eval_plane` flake did not fire). **No push executed.**

License: Apache-2.0 (LICENSE).
