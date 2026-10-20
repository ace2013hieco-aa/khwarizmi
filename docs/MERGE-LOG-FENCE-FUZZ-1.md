# MERGE-LOG-FENCE-FUZZ-1 — seeded adversarial fuzz battery for the fence classifier (GAP-1 P2-6)

## Provenance

| Item | Value |
| --- | --- |
| Task | FENCE-FUZZ-1-MERGE (merge gate; local FF — the push is bundled with the sibling GAP-1 wave-1b slices under one human D9 pin) |
| Base (`main` before) | `909831e` (ASSERTS-1 landing + its merge log) |
| Slice | `slice/fence-fuzz-1@37a2c4c`; **restacked** as `slice/fence-fuzz-1-restacked@83df558` (cherry-pick of `122d6db`; the slice's own re-stamp dropped and re-created for the combined count — no rebase, no merge commit) |
| Landed tip (FF'd to) | `83df558e5a600d14ab0d8bf55125a8543bdf898a` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the GAP-1 wave-1b fleet under one human D9 pin |

## Scope

```
tests/test_fence_classifier_fuzz.py | +472      (new; 9 tests)
docs/SUITE-COUNT.md                 |  +3 -3    (4851 -> 4860)
```

No `src/` change: the scratch mutation used for fail-on-base was fully
reverted (`git diff -- src` empty at the tip).

## What was certified

- A deterministic, seeded fuzz battery (3 fixed seeds, **1,911 generated
  cases**: 930 write / 390 read / 240 malformed / 138 inert / 213 unlabelled)
  over the fence classifier: nested quotes, escapes, line/block comments
  (including unbalanced), semicolons in strings, unicode identifiers, case
  tricks, whitespace/newline shuffles, `WITH`/CTE wrappers.
- Four invariants: (i) totality (every input classifies, no raise);
  (ii) soundness (a forbidden active operation never classifies into a
  permissive class, using the classifier's own imported constants — never a
  hand-copied keyword list); (iii) determinism (same bytes → same class);
  (iv) agreement with a tiny oracle on the known shapes already pinned by
  `tests/test_fence_classifier.py`.
- No genuine counterexample found; all invariants hold on the clean
  classifier. If one had been found, the charter required STOP-and-report.

## Fail-on-base (mutation)

Scratch-widened `_READ_KEYWORDS` with `INSERT` (classifier weakness),
battery: **3 failed, 6 passed** — e.g.
`('COUNTEREXAMPLE', 'INSERT', b" -- \\xe8\\xa1\\xa8 ... insert INTO t
VALUES (...)", False)` and oracle cross-check
`(b'INSERT INTO t VALUES (1)', True, False)`; failures:
`test_fence_constants_drive_the_battery`,
`test_fuzz_soundness_forbidden_active_operation_is_never_permissive`,
`test_fuzz_agrees_with_the_known_shape_oracle`. Scratch reverted:
**9 passed**. Logs: `fence-fuzz-1-mutation-fail.txt` /
`-fixed.txt` (untracked slice-worktree artifacts).

## Gates (raw)

Agent run: battery 80 passed (fuzz + existing classifier files); **FULL suite
4844 passed, 3 skipped, 0 failed** (588.43s); stamp 4847; census PASS
(124 / 19 / 5 / 4 / 28 / 1 / 15 / 0 unchanged); B4 24 passed; ruff pass;
pyright tests project 0 errors + 1 pre-existing warning.

Director re-derivation at restacked tip `83df558`: battery
(`test_fence_classifier_fuzz.py` + `test_fence_classifier.py`)
**80 passed**; stamp `--check` OK **4860** (4851 + 9); census PASS;
B4 **24 passed**; ruff `All checks passed!`; NOT-list scan of the restack
range **0 hits** (word-boundary).

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| invariant counterexample | **none found**; mutation proves the battery bites |
| classifier weakened in the landed tree | **no** — scratch reverted; zero src diff |
| census shift | **none** |
| B4 governed corpora | **PASS** — 24/24; no governed-doc edits |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `909831e` |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies adversarial fuzz coverage of the fence classifier's
classification invariants. It makes no validity, reproducibility, or
admissibility claim.

License: Apache-2.0 (LICENSE).
