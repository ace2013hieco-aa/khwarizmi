# MERGE-LOG — merge/gr3b4-step4 (GR3-B4 + Step 4 integration)

**Branch:** `merge/gr3b4-step4`, from `main@c0b5777dffc1993a87cd58f296964775a6cf6a6b`; local-only, no pushes, `main` untouched.
**Inputs:** `main@c0b5777` + `gr3-b4/closeout@f4d2be0` + `step-4/closeout@d614c1f`.
**Merge order (per task spec):** gr3-b4/closeout first, then step-4/closeout.

## Merge hashes

| # | Merge commit | Parents | Line merged |
|---|---|---|---|
| 1 | `945a6e8a5f547a7f327c2327fd54eefc4ef2fcef` | `c0b5777` + `f4d2be0` (`gr3-b4/closeout`) | B4 corpus/ref-graph substrate + texp-001 line |
| 2 | `c91ceb4a5aad93353e083d86476d6df07e53150c` | `945a6e8` + `d614c1f` (`step-4/closeout`) | Regime-axis substrate + wiring + closeout docs |

## Conflicts and resolutions

**None. Zero textual conflicts, zero semantic conflicts.**

Pre-merge survey showed the two lines touch disjoint file sets:

- gr3-b4/closeout adds only new files (`src/hermes/persistence/corpus.py`, `src/hermes/persistence/graph_edges.py`, `src/hermes/research/corpus.py`, `src/hermes/research/graph_edges.py`, `src/hermes/research/ref_graphs.py`, `tests/test_b4_ref_graphs.py`, `tests/test_corpus_admission.py`, `tests/test_gr3_edges.py`, `tests/texp_p3_*.py`, `experiments/texp-001/*`, `docs/gr3-b4/*`, `docs/texp-001/ROADMAP.md`, `scripts/p1b_audit2_probes.py`, `.gitattributes`) — 55 files, 10545 insertions, 0 deletions, 0 modifications of existing files.
- step-4/closeout adds `ROADMAP.md` (a NEW file — `main@c0b5777` has no root `ROADMAP.md`; blob `74b8768`), `docs/idr/IDR-044.md`, `docs/idr/IDR-SKELETON.md`, `docs/idr/step4_s_r2_adversarial_audit.md`, `src/hermes/research/regimes.py` (new) and `tests/test_regimes.py`; it modifies `docs/idr/*`, `src/hermes/persistence/failure_classifications.py`, `src/hermes/persistence/repositories.py`, `src/hermes/research/programs.py`, and step-4 test files — 14 files, 1496 insertions(+), 56 deletions(-), no path overlap with the gr3-b4 line.

No same-line-different-intent edits, no test-expectation collisions (test files disjoint), no migration-number collisions (neither line adds migrations). Both merges were clean `--no-ff` merges by the `ort` strategy; no resolution choices were made, so none are recorded.

## Gate results (on the merged tree, tip `c91ceb4`)

| Gate | Result |
|---|---|
| `scripts/run_tests.py` (full suite) | **PASS — 2209 passed** in 361.52s (0 failures, 0 errors) |
| `uvx ruff check src tests` | **PASS — All checks passed!** |
| `uvx pyright src` | **PASS — 0 errors, 0 warnings, 0 informations** |
| `uvx pyright --pythonpath .venv\Scripts\python.exe --project pyrightconfig.tests.json` | **RED — 12 errors, 1 warning (PRE-EXISTING, not merge-induced — see below)** |

### Tests-pyright red: pre-existing on the source branch (documented, not fixed)

The 12 errors are unresolved imports (`import "arms"` / `"energy"` / `"fixtures"` / `"generator"` / `"kernel"` / `"validator"`) in `tests/texp_p3_audit_checks.py` and `tests/texp_p3_reconcile_probe.py`, which arrived via the gr3-b4/closeout merge. Both files do a runtime `sys.path.insert(0, experiments/texp-001)` (`tests/texp_p3_audit_checks.py:40`, `tests/texp_p3_reconcile_probe.py:43`) so the imports resolve at test runtime (both files pass in the full suite), but `pyrightconfig.tests.json`'s `extraPaths` only lists `src`, so pyright cannot resolve them statically.

Verified pre-existing: the identical command on `gr3-b4/closeout@f4d2be0` itself (checked out in a temporary worktree) reports the **identical 12 errors, 1 warning**. The merge neither introduced nor worsened this. Per the task's stop condition ("any gate red — report, don't fix by redesigning"), it is reported here and left untouched: amending `pyrightconfig.tests.json` (`extraPaths += ["experiments/texp-001"]`) or the two files would be a behavior-adjacent change beyond mechanical conflict resolution, which the task forbids. The 1 warning (`test_research_program.py:143 reportSelfClsParameterName`) is likewise present on the source branch.

### Out-of-band gate: the TEXP-001 twin suite (not in the canonical gate set)

`experiments/texp-001` holds the pinned, shelved twin's own suite — and the only pin of the twin's
duplicate B4 agreement constants (`experiments/texp-001/test_b4_source.py`) — but the canonical runner's
`testpaths = ["tests"]` (`pyproject.toml:35`) does not collect it, so the full-suite gate above is blind
to it. Per `docs/MERGE-AUDIT.md` C3 (director ruling: record it out-of-band — no gate rewiring for
shelved code), the gate is run and recorded here:

| Out-of-band gate | Command | Result |
|---|---|---|
| TEXP-001 twin suite (97 tests, shelved code) | `.venv/Scripts/python.exe scripts/run_tests.py experiments/texp-001` | **PASS — 97 passed** |

## Shared-file slice suites (explicit re-runs on the merged tree)

| Suite | Result |
|---|---|
| `tests/test_research_program.py` | 80 passed |
| `tests/test_gateway.py` | 41 passed |
| `tests/test_claims_write_path.py` | 52 passed |
| `tests/test_q05_persistence.py` | 57 passed |
| `tests/test_regimes.py` | 25 passed |
| `tests/test_gr3_edges.py` | 28 passed |
| `tests/test_corpus_admission.py` | 23 passed |
| `tests/test_b4_ref_graphs.py` | 24 passed |
| **Total** | **330 passed, 0 failed** |

## Verdict

Integration branch complete: both lines merged cleanly, full suite + lint + `pyright src` green, all 8 slice suites green. One gate (`pyright` tests project) is red **pre-existing from the gr3-b4 line** (static import resolution of runtime `sys.path`-based experiment imports) — reported, not fixed, per task constraints. `main` untouched; nothing pushed.

## Post-audit reconciliation (`merge/conditions`, closes `docs/MERGE-AUDIT.md` C1–C4)

| Condition | Closure | Where |
|---|---|---|
| C1 — stale certified census | persistence acquisition owners 16 → 18 (27 total), transaction-control calls 113 → 121, `persistence→research` import statements 13 → 15; the `hermes.research.regimes` dereference classified under the DG-5 Model-D precedent (director ruling: INTENTIONAL, no DG-6 re-run); drifted §3.10 line citations re-pinned | `AGENTS.md`, `docs/ARCHITECTURE.md` §3.10 (+ the §2 layer-table row) |
| C1 (derived) — B4 fixture re-derivation | `AGENTS.md` and `docs/ARCHITECTURE.md` are governed corpus members, so re-censusing them moved their bytes and invalidated the content-addressed B4 fixtures: 3 of 4 regenerated deliberately (README §Regenerating, director ruling MERGE/conditions) — `749bf192… → ffbdf93c…` (c1), `82ea9ec8… → 8d2c74fa…` (c2), `2249067c… → 4bc5dc28…` (c4); `eef41946…` (c3, IDR-only stratum) unchanged. Edge sets identical (5/19/10/5); each affected `skipped` list gains exactly the new `IDR-044` token. No `src/` change, no twin edit (the twin resolves fixtures by directory and re-verifies name⇔digest) | `docs/gr3-b4/b4-fixtures/` (3 added, 3 removed, README table + note) |
| C2 — dropped identity-uniqueness coverage | `target_regime` distinct-registered-tag identity test restored via a synthetic two-entry registry fixture; the partial-fields/unresolvable-parent/hypothesis tests de-entangled from the free-string `"regime-A"` filler (that refusal now asserted where it belongs) | `tests/test_research_program.py` |
| C3 — twin suite out of band | command + result recorded above (no gate rewiring) | this file |
| C4 — wording + supersession | `ROADMAP.md` add/modify wording corrected above; IDR-036 D5 / IDR-037 D5 DEFERRED stances recorded as superseded by IDR-044 A6/A7 (their text untouched) | this file, `docs/idr/IDR-044.md` addendum |
