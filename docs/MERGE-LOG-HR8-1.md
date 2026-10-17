# MERGE-LOG-HR8-1 — completion-conflict recompute at read time (P1-10)

## Provenance

| Item | Value |
| --- | --- |
| Task | HR8-1-MERGE (merge gate; local FF — the push is bundled with GAP2-DOCS-1 under one human D9 pin) |
| Base (`main` before) | `6232b90` (docs landing tip: `slice/gap2-docs-1` FF + its merge log) |
| Slice | `slice/hr8-1@e3af8b9`; **restacked** as `slice/hr8-1-restacked@f7d10d1` after the docs landing moved `main` |
| Slice commits (restacked) | `44b840d` (fix) + `1a65ed8` (8 pins) + `f7d10d1` (re-stamp) — cherry-picks of `c39b538` + `e6dc2a8` + `e3af8b9`; **no rebase**, no merge commit |
| Landed tip (FF'd to) | `f7d10d1` — tree `fc6e0f8d6548883844a610fd92294c4f4503cd6c` |
| Merge worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` (exit 0); single-parent chain |
| Push | drafted, **NOT executed** — bundled with GAP2-DOCS-1 under one human D9 pin |

## Scope (slice range `6232b90..f7d10d1`)

```
src/hermes/research/completion.py   |  69 +  10 -
tests/test_hr8_blind_window.py      | 369 +   0 -   (new)
docs/SUITE-COUNT.md                 |   3 +   3 -   (4661 -> 4669)
```

**The fix (P1-10).** `_open_program_contradictions` (completion.py) no longer trusts stored `OPEN`
rows alone: it re-derives conflicts at read time over the current classification rows — stored OPEN
rows **merged with** fresh pairs (`classifications_digest` → `detector_candidate_rows` →
`detect_classification_conflicts`), deduplicated by stored contradiction id, deterministic sort,
read-only in the same transaction. This closes the blind window where a conflict became
N1-eligible between ticks while the stored row set stayed empty. Liveness/touch semantics are
unchanged; no new transaction or write path (census unchanged).

**Derivation parity (Director-verified line-level).** The read-time derivation is 1:1 with the
tick path: `classification_proposals` (`controller.py:1139-1147`) and `_detector_candidate_rows`
(`controller.py:2500-2506`) consume the same `classifications_for_project` → `classifications_digest`
→ `detector_candidate_rows(conn, project_id, items)` chain the predicate now uses.

**Carried observation (recorded, not a must-fix).** The predicate's recompute raises on a detector
failure where the tick path treats a detector failure as data (`DETECTOR` note). Accepted for this
landing — no lifecycle driver ships (ruling Q2), so the predicate is only reachable via
`can_complete_research` / the write-path guard; the divergence folds into the WP9 driver design
cluster (ruling R12 / P3-16).

## The 8 pins (`tests/test_hr8_blind_window.py`, +369)

`test_fresh_conflict_denies_completion` · `test_fresh_conflict_denies_the_write_path` ·
`test_resolved_pair_does_not_reblock` · `test_superseded_pair_does_not_reblock` ·
`test_invalidated_party_excluded_from_fresh_set` · `test_stored_open_row_blocks_exactly_once` ·
`test_fresh_conflict_foreign_to_head_program_unaffected` ·
`test_repeated_checks_identical_side_effect_free_verdict`.

The resolved/superseded pins first assert the pair is still N1-eligible over the current rows (the
naive-recompute trap — verified non-vacuous), then assert `eligible is True`; the write-path pin
asserts `TransitionError` with `HR-08`/`OPEN_CONTRADICTION`, lifecycle unchanged, and zero new
events.

## Fail-on-base (Director-independent reproduction)

Scratch detached worktree at base `e565cd8` + the new test file copied in (equal to the slice's
base code): **3 failed, 5 passed** in 2.08s — `test_fresh_conflict_denies_completion`
(`eligible=True` on a fresh conflict), `test_fresh_conflict_denies_the_write_path` (no
`TransitionError` — the window's write path completes), and
`test_repeated_checks_identical_side_effect_free_verdict`. Exact reproduction of the slice report:
the blind window is real and the pins are load-bearing. Scratch worktree removed after the check.

## Gates (raw, combined tip `f7d10d1`)

| Gate | Result |
| --- | --- |
| Full suite (`scripts/run_tests.py -v`, under the heavy-gate lock) | **4663 passed, 6 skipped, 0 failed** (522.22s, exit 0) |
| Skip variance (documented) | 3 standing (`s1_docling_provider.py:341` — pinned docling not in the main venv; same on `main`) + 3 transient `live_fetch` (network probe offline during the run; the same file re-run immediately after: **33 passed, 0 skipped**; skip is the designed offline path, `HERMES_SKIP_LIVE_FETCH` unset/unused by the runner). No failure anywhere. |
| stamp `--check` | OK **4669** (= 4661 + 8; the slice adds 8 tests) |
| census | **PASS** — every certified figure reproduced (read-only derivation; no write path added) |
| B4 | **24/24** byte-identical |
| ruff | `All checks passed!` |
| pyright src | 0 errors, 0 warnings, 0 informations |
| pyright tests | 0 errors, 1 warning (pre-existing `test_research_program.py:144`), 0 informations |
| New battery + owning suites | 8 + 149 = **157 passed** (`test_hr8_blind_window`, `test_hr08_completion_invariant`, `test_chg1_contradictions`, `test_lifecycle`) |
| NOT-list scan (range diff, tree, commit bodies) | **0 hits** |

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits (both ranges, tree and history) |
| `main` moved before the FF | **PASS** — restacked onto `6232b90` after the docs landing; FF exit 0 |
| FF-ability | **PASS** — descendant chain `6232b90 → 44b840d → 1a65ed8 → f7d10d1`; no merge commit |
| dirty main-bound worktree | **PASS** — clean pre-FF and post-FF |
| `--check` drift | **PASS** — 4669 exactly matches the live collect |
| FAIL audit on the range | **PASS** — none exists |
| push without a human hash-pin | **none performed** |

## Dual push plan (bundled with GAP2-DOCS-1; drafted, NOT executed)

One human D9 pin covers the single final tree (docs landing + this landing + both merge logs):
origin fast-forward `e565cd8 → <final tip>` (single refspec, no force, no tags); public mirror
orphan-sync with tree = `<final tip>^{tree}`, parent = live mirror HEAD `16995027`, exact-hash
push, **no force** (rule #5).

## Prohibited-claims discipline

This gate certifies a deterministic predicate fix and its pins: completion now denies on
N1-eligible conflicts whether stored or freshly derivable. It makes no validity,
reproducibility, or admissibility claim.

License: Apache-2.0 (LICENSE).
