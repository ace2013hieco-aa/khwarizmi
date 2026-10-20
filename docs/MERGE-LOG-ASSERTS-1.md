# MERGE-LOG-ASSERTS-1 — bare runtime asserts replaced with typed raises (GAP-1 P2-11)

## Provenance

| Item | Value |
| --- | --- |
| Task | ASSERTS-1-MERGE (merge gate; local FF — the push is bundled with the sibling GAP-1 wave-1b slices under one human D9 pin) |
| Base (`main` before) | `ce41570` (GAP-1 wave-1 pushed tip) |
| Slice | `slice/asserts-1@6f41b60` |
| Landed tip (FF'd to) | `6f41b60` — tree `28ee9da29d08b1a345cd1660748ec6238c76db62` |
| Merge method | **fast-forward** — `git merge --ff-only` (exit 0); no restack needed |
| Push | drafted, **NOT executed** — bundled with the GAP-1 wave-1b fleet under one human D9 pin |

## Scope

All **13** triage P2-11 sites, live and unmoved at base:
`platform_cli.py:105/:176`, `substrate.py:936`, `programs.py:1111`,
`invoke.py:956/:957`, `router.py:1431`, `sidecar.py:125`,
`paginate.py:1026/:1027/:1035/:1041/:1205`.

```
src/hermes/eval/platform_cli.py            +8  -2   (explicit raises on the exactly-one outcome invariant)
src/hermes/methodology/substrate.py        +5  -4   (SubstrateFormatError)
src/hermes/research/programs.py            +16 -1   (_require_scope_content_hash, RuntimeError)
src/hermes/tools/capabilities/invoke.py    +23 -6   (_check_refusal_partition, ProviderValidationError)
src/hermes/tools/models/router.py          +5  -1   (ModelPlaneInvariantError)
src/hermes/tools/models/sidecar.py         +13 -1   (_check_refusal_subset, ModelPlaneInvariantError)
src/hermes/tools/providers/paginate.py     +25 -6   (ProviderValidationError on the GC-02 bindings)
7 owning test files                        +158      (13 pins)
docs/SUITE-COUNT.md                        +3  -3    (4838 -> 4851)
```

## What was certified

- **Zero bare `assert` statements remain in `src/`** — every runtime guard now
  raises explicitly and therefore survives `python -O` (bare asserts vanish
  under optimization; the guards used to disappear with them).
- Import-time invariant checks (capability refusal partition, sidecar refusal
  subset) are now callable helpers whose typed raise is pinnable; the
  programs type-narrowing guard is `_require_scope_content_hash`. Helper
  extraction is behavior-preserving: the checks run at the same points as
  before, only through named functions.
- The two `platform_cli` sites raise **explicit** `AssertionError` — the eval
  package's existing idiom (`eval/hostile.py` raises it at 10+ guard sites);
  an explicit `raise` is NOT stripped by `-O`, unlike the old bare assert.
- 13 pins across the 7 owning test files (extension of existing surfaces, no
  new standalone pin file needed): each triggers its guard and pins the
  exception type + a stable message fragment.

## Fail-on-base

Fix reverted (conversion commit `45dfaf1` reverted), pins present:
`13 failed, 795 deselected in 1.53s` — every pin fails with the named
assertion (e.g. `src\hermes\tools\providers\paginate.py:1205: AssertionError`).
Fix restored: `13 passed, 795 deselected in 0.88s`.
Raw logs: `asserts-1-fob-base.txt` (65 KB, 1068 lines) /
`asserts-1-fob-fixed.txt` (untracked working artifacts in the slice worktree).

## Gates (raw)

Agent run: battery 861 passed; **FULL suite 4848 passed, 3 skipped, 0 failed**
(567.79s); stamp 4851; census PASS (124 calls / 28 owners; unchanged);
B4 24 passed; ruff pass; pyright src 0/0/0; pyright tests 0 errors + 1
pre-existing warning (`test_research_program.py:144`, line preserved).

Director re-derivation at landed tip `6f41b60`: battery (the 7 owning test
files) **808 passed**; stamp `--check` OK **4851** (4838 + 13); census PASS;
B4 **24 passed**; ruff `All checks passed!`; NOT-list scan of the slice diff
**0 hits** (word-boundary).

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| behavior change beyond optimization-mode semantics | **none** — same guards, same firing points; explicit raises survive `-O` |
| census shift | **none** — 124 / 28 / 15 unchanged |
| B4 governed corpora | **PASS** — 24/24; no governed-doc edits |
| pins weakened | **none** — 13 new pins; existing assertions untouched |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `ce41570` |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies typed runtime guards replace optimization-strippable
asserts. It makes no validity, reproducibility, or admissibility claim.

License: Apache-2.0 (LICENSE).
