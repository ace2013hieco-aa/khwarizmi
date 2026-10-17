# MERGE-LOG-GAP2-DOCS-1 — the GAP-2 rulings record and claim alignment

## Provenance

| Item | Value |
| --- | --- |
| Task | GAP2-DOCS-1-MERGE (merge gate; local FF — the push is bundled with HR8-1 under one human D9 pin) |
| Base (`main` before) | `e565cd8dce6219869599ee6a01529b1539af2218` |
| Slice | `slice/gap2-docs-1@83b892439d3049685983bdb604c1d46dc10bc892` |
| Slice commits | `e33afd0` (rulings record) + `33ca704` (verdict semantics) + `d129735` (lifecycle docstring) + `83b8924` (P2-15 docstring) |
| Landed tip (FF'd to) | `83b8924` — tree `377b0e424596eae644b4943130885628a6c40074` |
| Merge worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` (exit 0); single-parent chain; **no rebase**, no merge commit |
| Push | drafted, **NOT executed** — bundled with HR8-1 under one human D9 pin |

## Scope

5 files, **+141/−12** — **zero executable lines changed** (Director-verified by reading the full
`src` diff; docstrings + docs only):

```
docs/GAP2-RULINGS.md                              | 121 ++  (the design-gate record)
README.md                                         |   2 +-  ("resolves" -> "closes"; acknowledgment, not reconciliation)
src/hermes/core/lifecycle.py                      |  11 +-  (module docstring: real mutation path; no driver ships)
src/hermes/persistence/failure_classifications.py |  12 +-  (`_evidence_resolver` docstring, P2-15)
src/hermes/research/gateway.py                    |   7 +-  (`_validate_contradiction_resolution` docstring: closing semantics)
```

`docs/GAP2-RULINGS.md` records: the Q1-Q4 rulings (Q1 acknowledge; Q2 operational independence;
Q3 quiescence deliberately not consulted; Q4 per-project retraction intended, global propagation
rejected), all 18 item dispositions, the five approved fix slices (HR8-1, CHG-DEDUP-1, CX-OVERLAP-1,
CRES-DIGEST-1, RESOLVER-PARITY-1), the rejected/deferred alternatives with rationale, the executed
claim alignments, and the search proof.

**Governed-member note.** `docs/ARCHITECTURE.md` §3.7 was reviewed and deliberately left
**byte-identical**: it is a governed B4 corpus member (`CORPUS_REFS`), so any edit forces a
deliberate fixture regeneration — excluded by the gr3-b4-empty gate. An exploratory edit reproduced
the 9-fixture-name failure and was reverted; recorded in `GAP2-RULINGS.md` §5.

## Gates (raw)

Slice run (recorded, on the slice tip): stamp `--check` OK **4661**; ruff pass; census PASS
(121/27/1/15); B4 **24/24**; pyright src 0/0/0; pyright tests 0 errors + 1 pre-existing warning;
full suite `4658 passed, 3 skipped, 0 failed`.

Merge-gate re-derivation (Director, live, on the landed tip `83b8924`):

- `scripts/stamp_suite_count.py --check` → `OK: docs\SUITE-COUNT.md collected=4661 matches the live collect` (exit 0).
- `uvx ruff check src tests` → `All checks passed!` (exit 0).
- `pytest tests/test_b4_ref_graphs.py` → `24 passed`; `git diff e565cd8..83b8924 -- docs/gr3-b4/` empty.
- `uvx pyright --pythonpath <repo-venv> src` (house invocation, from the worktree) → `0 errors, 0 warnings, 0 informations`.
- NOT-list scan (range diff, tree, commit bodies) → **0 hits**.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| `main` moved before the FF | **PASS** — unmoved at `e565cd8` pre-FF |
| FF-ability | **PASS** — `merge-base(main, 83b8924)` == `main`; `--ff-only` exit 0; no merge commit |
| dirty main-bound worktree | **PASS** — clean pre-FF |
| `--check` drift | **PASS** — 4661 (no tests added; count correctly unchanged) |
| FAIL audit on the range | **PASS** — none exists |
| push without a human hash-pin | **none performed** |

## Dual push plan (bundled with HR8-1; drafted, NOT executed)

The push for this landing is bundled with HR8-1's under **one** human D9 pin, on the single final
tree: origin fast-forward `e565cd8 → <final tip>` (single refspec, no force, no tags); public mirror
orphan-sync with tree = `<final tip>^{tree}`, parent = live mirror HEAD `16995027`, exact-hash push,
**no force** (rule #5).

## Prohibited-claims discipline

This gate certifies a documentation merge (the design-gate rulings record and the claim
alignments). It makes no validity, reproducibility, or admissibility claim, and no claim about any
model or human verdict beyond what the recorded rulings state.

License: Apache-2.0 (LICENSE).
