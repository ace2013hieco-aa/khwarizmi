# MERGE-LOG-EXT-3 — L3 N9 predicate state-drift (pin + census)

## Provenance

| Item | Value |
| --- | --- |
| Task | EXT-3-MERGE (merge gate only — no push) |
| Base (`main` before) | `6cce97c029dce670be8b57e33f62467131ffc036` |
| Slice (FF'd to) | `1a42183662feb9702b69520430b2efd49511a5dd` |
| Slice commits | `9fec4b1` (pin + restamp) + `1a42183` (census doc) |
| Branch | `slice/ext-3-n9pin` |
| Merge worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/ext-3-merge-wt` |
| Merge method | **fast-forward in place**, `git merge --ff-only` in the main-bound worktree |
| FF evidence | `merge-base(main, slice)` == `main`; `main..slice` = 2, `slice..main` = 0 |
| Rebase / merge commit / force | **none** — FF only, tip has exactly one parent |

## Scope

3 files, +535/−3, **zero `src/` changes** (`git diff main..1a42183 -- src/` is empty):

```
docs/EXT-3-N9-RESOLVE-CENSUS.md  | 149 +++++++++++++++  (new)
docs/SUITE-COUNT.md              |   6 +-             (restamp 4447 -> 4452)
tests/test_n9_resolve_path_pin.py | 383 ++++++++++++++++  (new, 5 tests)
```

The slice adds a **source-scanning pin** and the recorded census it enforces. It
lands **no production code**, so there is no `apply_intent` change, no new write
path, and no alteration of the certified N9 surface.

## The pin — how a future developer cannot silently drift

`tests/test_n9_resolve_path_pin.py` re-derives the census by AST over
`src/hermes/**/*.py` and requires every function that calls
`_source_artifact_resolves` to appear in **exactly one** of three tables:

1. `N9_FENCED_RESOLVE_SITES` — certified evidence positions. The function must
   contain `source_artifact_retracted`, **ordered after** the resolve call (the
   resolved artifact is re-checked before use).
2. `N9_NON_EVIDENCE_ALLOWLIST` — resolve paths that are deliberately *not* N9
   positions, each with a recorded reason.
3. `N9_FROZEN_GAP_REGISTER` — paths that **are** decision-affecting evidence
   positions but sit on certified writers/validators, so the fence may not be
   added without the owning gate re-run. Recorded so the gap is explicit,
   exactly bounded, and unable to grow silently.

The certified predicate set is pinned to exactly its four sites
(`N9_CERTIFIED_PREDICATE_SITES`). Four assertions:
`test_every_resolve_site_is_classified`,
`test_fenced_resolve_sites_carry_the_predicate_after_the_resolve`,
`test_certified_predicate_sites_are_exactly_the_certified_four`,
`test_frozen_gap_register_is_exact`, plus the scanner self-test
`test_scanner_detects_a_planted_bypass`.

A new resolve path therefore cannot land silently: it appears in the scan and in
no table, and `test_every_resolve_site_is_classified` fails naming it.

## Census (8 resolve sites / 4 predicate sites at `main@1a42183`)

| Resolve site | Enclosing function | Verdict |
| --- | --- | --- |
| `persistence/failure_classifications.py:361` | `FailureClassificationRepository._verify_evidence_owned` | FENCED (predicate `:378`) |
| `persistence/failure_classifications.py:401` | `FailureClassificationRepository._evidence_resolver` | FENCED (predicate `:411`) |
| `persistence/graph_edges.py:338` | `GraphEdgeRepository._resolve_endpoint` | non-evidence |
| `persistence/repositories.py:2002` | `ClaimAssumptionRepository._dereference_artifact_ref` | **frozen gap** |
| `persistence/source_outcomes.py:474` | `SourceOutcomeRepository.dereference_ref` | non-evidence |
| `persistence/source_outcomes.py:719` | `SourceOutcomeRepository._validate_task_binding` | non-evidence |
| `research/gateway.py:2386` | `_validate_curate_knowledge` | **frozen gap** |
| `research/gateway.py:3953` | `_validate_source_spec` | non-evidence |

Predicate sites: `failure_classifications.py:378`, `:411`,
`research/contradiction_candidates.py:65`, `research/gateway.py:2712`.

## Frozen-gap register — the two gate-blocked sites (pointer)

Recorded, not wired. Both need a design gate plus the owning certification
re-run before the fence may be added:

- **`research/gateway.py:2386` in `_validate_curate_knowledge`** — resolves the
  classification's `falsifying_evidence_refs` into the `evidence_basis` that
  justifies the retraction. A genuine admissibility position, but a certified
  gateway validator (one of the 27 acquisition owners, P7 governance lifecycle)
  adjacent to the N9-certified gateway site.
- **`persistence/repositories.py:2002` in
  `ClaimAssumptionRepository._dereference_artifact_ref`** — the extraction/claim
  `source_ref` dereference. A genuine evidence position, but the helper's
  contract is *dereference* under a closed vocabulary, so the fence belongs at
  the certified writer `record_extraction`, not in the shared helper.

Full reasoning: `docs/EXT-3-N9-RESOLVE-CENSUS.md`.

## HARD RULE — audit duty (pin re-verification, first-pass)

No FAIL-level audit existed on this range, so the merge gate performed one:
the pin's AST enumeration was re-derived from live source **independently** of
the pin's own tables (a separate script, not the pin) and compared.

| Check | Result |
| --- | --- |
| resolve sites (independent scan) | **8** |
| predicate sites (independent scan) | **4** |
| over-count / under-count | **none** — matches the pin's tables exactly |
| fenced site 1 `_verify_evidence_owned` | resolve `[361]`, predicate `[378]` — ordered correctly |
| fenced site 2 `_evidence_resolver` | resolve `[401]`, predicate `[411]` — ordered correctly |
| allowlist × 4 | each has a resolve call and **no** predicate in its function |
| register entry `_validate_curate_knowledge` | resolve `[2386]`, predicate `[]` — gap real |
| register entry `_dereference_artifact_ref` | resolve `[2002]`, predicate `[]` — gap real |
| pin scanner vs tables | `unclassified = []`, `stale = []`, predicate set == certified four |
| **FAIL-level findings** | **none** — no missed resolve path, no wrong gap entry |

## Gates (raw, on the landed tip `1a42183`, offline, `PYTHONPATH=<wt>/src`, no extra `-q`)

Interpreter for every gate below:
`D:/New folder/research-agent/.venv/Scripts/python.exe`
(**Test-Path: True**, Python 3.14.1, pyright 1.1.414, ruff 0.16.10).

- **Pin** (`scripts/run_tests.py tests/test_n9_resolve_path_pin.py -v`) ->
  `5 passed in 4.67s` (exit 0).
- **Stamp `--check`** (`scripts/stamp_suite_count.py --check`) ->
  `OK: docs\SUITE-COUNT.md collected=4452 matches the live collect` (exit 0).
- **Collect** (`scripts/run_tests.py --collect-only`) ->
  `4452 tests collected in 6.54s` (== 4452).
- **B4** (`scripts/run_tests.py tests/test_b4_ref_graphs.py`) ->
  `24 passed in 102.11s (0:01:42)` = **24/24**. B4 fixtures byte-identical
  (`git diff -- docs/gr3-b4/` empty).
- **Census** (`scripts/check_census.py`) ->
  `PASS - every certified figure is reproduced exactly`
  (121 calls; owners 18/5/4 = 27; rollback-only 1; persistence->research
  imports 15; outside 0).
- **Ruff** (`python -m ruff check src tests`) -> `All checks passed!` (exit 0).
- **Pyright src** (`python -m pyright src --pythonpath "<venv python>"`) ->
  `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests-config**, two recordings:
  1. (a) `python -m pyright --pythonpath "<venv python>" --project pyrightconfig.tests.json` ->
     `108 errors, 1 warning, 0 informations` (exit 1). The 108-env baseline:
     every one is `reportMissingImports` on `Import "pytest"`, spread over 103
     pre-existing test files; **0** touch `tests/test_n9_resolve_path_pin.py`;
     the single warning is the pre-existing
     `tests/test_research_program.py:144 reportSelfClsParameterName`.
     `--pythonpath` does not resolve `pytest` in this environment.
  2. (b) with the venv made discoverable to pyright (`venvPath`/`venv`, via a
     `.venv` junction to the repo venv — junction removed after the run; the
     probe config was not committed) ->
     `0 errors, 1 warning, 0 informations` (exit 0), the only warning being the
     same pre-existing `test_research_program.py:144`.
  (b) is the recorded standard: **0 errors** on the tests project.
- **Full suite** (`scripts/run_tests.py tests --tb=short -rf`) ->
  `5 failed, 4444 passed, 3 skipped, 1 warning in 565.12s (0:09:25)`.
  Pass + skip + failed = 4444 + 3 + 5 = **4452** == collect.

## Red set: EXACTLY baseline-5 (not a superset)

```
tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

Environmental races / Windows symlink privilege — flaky by nature, unchanged
from the documented baseline. **Delta = 0.**

The documented flake
(`tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree`,
30s pinned-subprocess timeout, `docs/MERGE-LOG-NUM-1.md`) **did not fire** on the
landed tip, so no isolation proof was required. For the record, during the
EXT-3 slice run it fired twice under full-suite load and then passed twice —
once with the change absent (50.8s) and once with it present (38.2s), plus a
full-file isolation run of `tests/test_eval_plane.py` at **205 passed** — so it
is a timing flake, independent of this change.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`) | **PASS** — 0 word-boundary mentions in subjects, bodies or the range diff. One *case-insensitive substring* false positive (`tse` inside "itself", `tests/test_n9_resolve_path_pin.py` docstring) — not a mention; reported for the record. |
| `main` moved before the FF | **PASS** — re-verified unmoved at `6cce97c` (local == `origin/main` == `ls-remote`) immediately pre-FF |
| FF-ability | **PASS** — `merge-base` == `main`; +2/−0; `--ff-only` used, exit 0 |
| dirty main-bound worktree | **PASS** — `met-1-merge-wt` clean pre-FF, and FF'd **in place** so it is clean post-FF at `1a42183 [main]` |
| pin miscount | **PASS** — 8/4 independently re-derived; no over/under-count |
| FAIL-level audit finding | **PASS** — none; both register entries verified real |
| red set superset of baseline-5 | **PASS** — delta 0 |
| `--check` drift | **PASS** — collected 4452 == stamp |
| roadmap diff beyond the status cell | **PASS** — numstat `1 1`, word-diff shows only `QUEUED` -> `LANDED-PIN (1a42183) / wiring GATE-BLOCKED` |
| stale main-bound worktree left behind | **PASS** — `met-1-merge-wt` clean at the final tip |
| push without a human hash-pin | **none performed** |

## Worktree hygiene

`met-1-merge-wt` (house arrangement preserved): bound to `main@6cce97c` and
clean → FF'd **in place** to `1a42183` → this log commits on top → ends bound to
`main` at the final tip, clean. `ext-3-merge-wt` used for the gate runs (detached
at `1a42183`); `ext-3-wt` left on `slice/ext-3-n9pin` per the slice convention.

## Dual push plans — drafted, NOT executed (D8/D9)

No push was performed by this gate. Both plans require a human hash-pin.

1. **`origin` plain-push** (`https://github.com/ace2013hieco-aa/khwarizmi-research`):
   push `<merge-gate-tip>:refs/heads/main`, single refspec, no force, no tags,
   after re-verifying live `origin/main` is a strict ancestor of the tip (FF).
2. **public mirror orphan-sync** (`https://github.com/ace2013hieco-aa/khwarizmi`):
   add a temp remote, `fetch --no-tags`, re-read the live mirror pin, build a
   sync commit whose tree is `<tip>^{tree}` and whose parent is the mirror HEAD
   (orphan convention — `merge-base` must be empty), push exact-hash with **no
   force** (rule #5), then remove the temp remote. Mirror HEAD is a moving
   target: always re-run `ls-remote` immediately before the sync.

## Verdict

### A — EXT-3 MERGED (LOCAL-ONLY)

`main` FF'd `6cce97c029dce670be8b57e33f62467131ffc036` ->
`1a42183662feb9702b69520430b2efd49511a5dd`. L3 is closed as a **recorded census
plus an enforcing pin**; the two decision-affecting but certified-surface sites
are recorded as gate-blocked rather than wired. No push executed.

License: Apache-2.0 (LICENSE).
