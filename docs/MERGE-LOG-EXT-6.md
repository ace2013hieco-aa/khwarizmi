# MERGE-LOG-EXT-6 — EXT-6 OPEN-contradiction bound (R4) landed on `main`

Merge-gate record for the EXT-6 slice: an additive, fail-closed cumulative
ceiling on a project's OPEN contradiction set
(`slice/ext-6-openbound@e0afafd`, 3 files, +450/−0) plus its redteam-audit
SHOULD-FIX closure (`fix/ext-6-s1s2@4fad0a6`, 3 files, +103/−12), landed
on `main` by **local fast-forward only**. Follows the `MERGE-LOG-EXT-5` /
`MERGE-LOG-EXT-4` pattern.

**Outcome: EXT-6 landed on `main` — local fast-forward, no push.**
Redteam audit `audit/ext-6-redteam@2baf5d4` is **PASS-WITH-SHOULD-FIX**
(0 MUST-FIX, 2 SHOULD-FIX, 3 observations); both SHOULD-FIX items are
**closed** by `4fad0a6` on the landed tip — the false "can never trip it"
claim is replaced by the true arithmetic, and the shipped height (1000)
is now pinned in-suite. **`origin` and the public mirror are NOT advanced
and NOT pushed — D8/D9 require a human hash-pin.**

## Provenance

| Item | Value |
| --- | --- |
| Task | EXT-6-MERGE (merge gate, local-only) |
| Base (`main` before) | `bec22431cfbabed32a25e973bd49bf67d27a0ebf` |
| Landed tip (FF'd to) | `4fad0a616450abec0fd52f9e09afd91aab0d67ee` |
| Branch | `slice/ext-6-openbound` @ `e0afafd` → `fix/ext-6-s1s2` @ `4fad0a6` |
| Triage item | R4 (`audit/ext-1-triage@bc1a5da`) |
| Audit of record | `audit/ext-6-redteam@2baf5d4` — PASS-WITH-SHOULD-FIX |
| Gate worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/ext-6-merge-wt` |
| Main-bound holder | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` (FF'd **in place**) |
| Merge method | **fast-forward in place**, `git merge --ff-only` |
| Push | **none** (D8/D9 — human hash-pin required) |

## What landed

| Commit | Subject | Files |
| --- | --- | --- |
| `5a46ecb` | fix(ext-6): cumulative OPEN-contradiction bound with fail-closed refusal (R4) | `contradictions.py` +28, `gateway.py` +40, `tests/test_ext6_open_bound.py` +382 |
| `e0afafd` | docs(ext-6): re-stamp SUITE-COUNT.md (4587 → 4599) | `docs/SUITE-COUNT.md` 3/3 |
| `4fad0a6` | docs(ext-6): correct the ceiling arithmetic + pin the shipped height (audit S1/S2) | `contradictions.py` +22/−6, `tests/test_ext6_open_bound.py` +78/−3, `docs/SUITE-COUNT.md` 3/3 |

Range: 3 commits, 4 files, **+544/−3** (`git diff --numstat bec2243..4fad0a6`).

The bound: `MAX_OPEN_CONTRADICTIONS = 1000`, project-scoped, enforced
**inside** the existing `BEGIN IMMEDIATE` in
`gateway.py::_validate_record_contradiction` — a NET-NEW admission refuses
fail-closed with the new named code `CONTRADICTION_BACKLOG`
(refusal-as-data + operator guidance), nothing is inserted on refusal, and
existing OPEN rows are untouched. NOT gated: resolution (the only drain),
head-only supersession (net-zero), idempotent replay (zero effects). No
certified invariant is altered (N1 pair rule, N9 retraction fencing,
identity re-derivation and the resolution verdict path are untouched) and
no transaction-control call is added (the certified census stays 121).

## Content identity (pure FF — nothing rewritten)

- `merge-base(main, e0afafd)` == `bec22431cfbabed32a25e973bd49bf67d27a0ebf`
  == `main`; likewise `merge-base(main, 4fad0a6)` — the FF is linear and
  no content was rewritten.
- `git merge --ff-only 4fad0a6` exit 0; `main^{tree}` == `4fad0a6^{tree}`
  == `f3228311c76715596e86d7010a1dcfb23d8e5284`.
- The audit worktree (`ext-6-audit-wt`) and both slice worktrees
  (`ext-6-wt`, `ext-6-fix-wt`) are untouched.

## Audit SHOULD-FIX closures (both on the landed tip)

**S1 — false invariant claim.** The comment claimed a maximal detector
pass "can never trip" the 2× ceiling. False unless the OPEN set is already
≤ 500. Restated to the true arithmetic (K = OPEN rows at pass start,
C = 500): one maximal pass admits `min(C, CEILING − K)` and refuses the
remainder, so it trips the ceiling **iff K > 500** —
`K=0→500/0, K=500→500/0, K=501→499/1, K=600→400/100, K=999→1/499,
K=1000→0/500`. The corrected text states explicitly that refusing the
remainder is **correct fail-closed behaviour**, not a defect: the backlog
is already at the ceiling, each refusal is surfaced as
`CONTRADICTION_BACKLOG` data (never a silent drop), and the drain stays
open.

**S2 — no pin at the shipped height.** Every behavioural pin drove a
monkeypatched ceiling (1–5), so the constant's own height was never
exercised in-suite. Added ONE production-height integration pin
(`TestShippedHeight::test_shipped_height_fill_refuse_drain_readmit`) that
drives `MAX_OPEN_CONTRADICTIONS` itself end-to-end through the single
mutation path: fill a project to 1000 OPEN → the 1001st net-new admission
refuses with data (nothing written, transaction rolled back) → the drain
resolves → the freed slot re-admits. Wall-time was measured FIRST
(~1.1 s total, ~0.66 ms/record) — inside the 120 s budget, so the in-suite
test was chosen over the documented-methodology fallback.

## Gates (raw, on the landed tip `4fad0a6`, `PYTHONPATH=<wt>/src`, no extra `-q`)

Interpreter: `D:/New folder/research-agent/.venv/Scripts/python.exe`
(Test-Path **True**, Python 3.14.1, pytest 9.1.1; ruff 0.17.0; pyright
1.1.414 via `uvx`).

```
######## COLLECT ########
4600 tests collected in 14.16s
COLLECT_EXIT=0

######## STAMP --check ########
OK: docs\SUITE-COUNT.md collected=4600 matches the live collect
STAMP_EXIT=0

######## CHECK_CENSUS ########
executed transaction-control calls                 121       121  OK
acquisition owners (persistence)                    18        18  OK
acquisition owners (gateway)                         5         5  OK
acquisition owners (Controller)                      4         4  OK
acquisition owners (total)                          27        27  OK
rollback-only participants                           1         1  OK
persistence->research import statements             15        15  OK
control calls outside certified layers               0         0  OK
PASS - every certified figure is reproduced exactly.
CENSUS_EXIT=0

######## RUFF ########
All checks passed!
RUFF_EXIT=0

######## B4 24 ########
24 passed in 186.74s (0:03:06)
B4_EXIT=0

######## BOUND 13 ########
13 passed in 3.99s
BOUND_EXIT=0

######## PYRIGHT SRC ########
0 errors, 0 warnings, 0 informations
PYRIGHT_SRC_EXIT=0

######## PYRIGHT TESTS (absolute --pythonpath <venv>, pyrightconfig.tests.json) ########
112 errors, 1 warning, 0 informations
  -- every error is Import "pytest" could not be resolved (reportMissingImports);
     non-pytest-import errors: 0. This is the documented environment baseline
     (pyright's interpreter search-path probe returns typeshed-only here), unchanged
     at 112 because the new test was added to a file that already imports pytest.
PYRIGHT_TESTS_CANON_EXIT=1

######## PYRIGHT TESTS (venvPath/venv route) ########
0 errors, 1 warning, 0 informations
  -- the single warning is the pre-existing tests/test_research_program.py:144
     (identical on main since before EXT-4)
PYRIGHT_TESTS_EXIT=0

######## FULL SUITE (scripts/run_tests.py tests --tb=short -rf) ########
4 failed, 4593 passed, 3 skipped, 1 warning in 946.05s (0:15:46)
FULLSUITE_EXIT=1
```

`4593 + 3 + 4 = 4600` == collect.

## Red set: SUBSET of baseline-5 (4 of 5; delta −1)

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

All four are the pre-existing environmental reds (3 concurrency races + 1
Windows symlink-privilege refusal) documented in
`docs/archive/MERGE-LOG-CLOUD.md` and reproduced through `MERGE-LOG-NUM-1`
/ `-FRONT-1` / `-EXT-2` / `-EXT-3` / `-EXT-4` / `-EXT-5`. The fifth
baseline red
(`test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds`)
did not fire this run, so the red set is a **strict subset** of
baseline-5. No new red. The documented `tests/test_eval_plane.py` timing
flake did not fire (`test_eval_plane` mentions in the run: 0), so no
isolation proof was required.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list functional coupling (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`) | **PASS** — 0 case-sensitive hits in the range commit subjects/bodies and in the range diff; the loose case-insensitive sweep surfaces only the substring `sDa` inside `TestRefusalSurfacesAsData` (a word-boundary artifact, not a mention) |
| `main` moved before the FF | **PASS** — verified unmoved at `bec2243` immediately pre-FF (local == `origin/main` == `ls-remote`) |
| Dirty main-bound worktree | **PASS** — `met-1-merge-wt` clean (empty `status --porcelain`) before the ref was touched |
| FF-ability fails | **PASS** — `merge-base(main, 4fad0a6)` == `main`; `git merge --ff-only` exit 0 |
| Red set superset of baseline-5 | **PASS** — red set is a strict SUBSET (4 of 5), delta −1 |
| `--check` drift | **PASS** — `collected=4600` == live collect 4600 |
| Roadmap diff beyond the status cell | **PASS** — numstat `1 1`; word-diff shows only `QUEUED` → `LANDED (4fad0a6)` |
| Stale main-bound worktree left behind | **PASS** — `met-1-merge-wt` clean and bound to `main` at the final tip |
| FAIL audit on the range | **PASS (did not fire)** — the only audit covering the range is PASS-WITH-SHOULD-FIX; both items closed by `4fad0a6` |
| Push without a human hash-pin | **none performed** |

Ignored by charter: a `git` housekeeping step emitted
`error: failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4': Permission denied`
while the worktree operations pruned a stale admin entry. It concerns an
unrelated, already dead entry and has no effect on the landing; recorded,
not acted on (constraint: "prune step-4 error ignored").

## Worktree hygiene

- Main-bound holder `met-1-merge-wt`: FF'd **in place**, clean, bound to
  `main` at the final tip.
- Gate worktree `ext-6-merge-wt`: detached at the landed tip, clean (the
  `.venv` junction is gitignored; the temporary pyright diagnostic config
  was removed before the full suite ran).
- Slice worktrees `ext-6-wt` / `ext-6-fix-wt` and the audit worktree
  `ext-6-audit-wt` are untouched.
- The shared checkout `D:\New folder\research-agent` was never used for
  any gate (its own checkout is on an unrelated branch).

## Dual push plans — drafted, NOT executed (D8/D9)

1. **`origin` plain-push** (`https://github.com/ace2013hieco-aa/khwarizmi-research.git`):
   push `<reviewed-main-hash>:refs/heads/main`, single refspec, no force,
   no tags, after re-verifying live `origin/main` is a strict ancestor of
   the reviewed tip (FF). Live `origin/main` at draft time:
   `bec22431cfbabed32a25e973bd49bf67d27a0ebf` — a strict ancestor of the
   local `main`, so the plain push would fast-forward.
2. **public mirror orphan-sync** (`https://github.com/ace2013hieco-aa/khwarizmi`):
   add a temp remote, `fetch --no-tags`, re-read the live mirror pin,
   build a sync commit whose tree is `<tip>^{tree}` and whose parent is
   the mirror HEAD (orphan convention — `merge-base` must be empty), push
   the exact hash with **no force** (rule #5), then remove the temp
   remote. Live mirror HEAD at draft time:
   `7ab0cdb0db3ff439df2820c19a77c36e441455e0` — a moving target, always
   re-read with `ls-remote` immediately before the sync.

## Verdict

### A — EXT-6 MERGED (LOCAL-ONLY)

`main` FF'd `bec22431cfbabed32a25e973bd49bf67d27a0ebf` →
`4fad0a616450abec0fd52f9e09afd91aab0d67ee`; the two docs commits (this
MERGE-LOG and the roadmap row-5 flip) land on top. The cumulative
OPEN-contradiction ceiling lands additive-only inside the certified single
mutation path: a net-new admission refuses fail-closed with the named
code `CONTRADICTION_BACKLOG` (refusal-as-data, never a silent drop),
existing OPEN rows are untouched, and the human verdict — the only drain —
is never blocked. The shipped height is now pinned in-suite and the
ceiling comment states the true arithmetic. Suite count re-stamped 4600;
audit S1/S2 closed on the landed tip. No push executed.

License: Apache-2.0 (LICENSE).
