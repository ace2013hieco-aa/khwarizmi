# MERGE-LOG-CX-OVERLAP-1 — fresh in-transaction overlap on the recorded row (P2-17)

## Provenance

| Item | Value |
| --- | --- |
| Task | CX-OVERLAP-1-MERGE (merge gate; local FF — the push is bundled with the sibling slices under one human D9 pin) |
| Base (`main` before) | `db76eb6` (CHG-DEDUP-1 landing tip) |
| Slice | `slice/cx-overlap-1@ff0b851`; **restacked** as `slice/cx-overlap-1-restacked@23433a3` (cherry-picks of `49f0310` + `233c997` + `9504ca0`; the slice's own re-stamp dropped and re-created for the combined count — **no rebase**, no merge commit) |
| Landed tip (FF'd to) | `23433a3` — tree `2fba732dbb240ffeb7dac1ba40715710f1e6a473` |
| Merge worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` (exit 0); single-parent chain |
| Push | drafted, **NOT executed** — bundled with the remaining fleet under one human D9 pin |

## Scope

```
src/hermes/research/gateway.py             |  10 +  1 -   (fix)
tests/test_cx_overlap_fresh_store.py       | 426 +  0 -   (7 pins + a readback guard, new)
docs/SUITE-COUNT.md                        |   3 +  3 -   (4678 -> 4685)
```

**The fix (P2-17).** The recorded `overlap` column now carries the **fresh in-transaction overlap**
(`sorted(set(fresh_a["evidence"]) & set(fresh_b["evidence"]))`, re-derived after the unchanged
empty-overlap refusal gate) instead of the pre-lock snapshot computed before `BEGIN IMMEDIATE`. A
resolution/retraction committing between the pre-lock pair rule and the lock can no longer be
recorded as admitted provenance. The event payload and intent result stay on the pre-lock snapshot
(byte-stable consumers); the duplicate fast-path is untouched (duplicates do not re-verify — the
recorded P2-18 semantics).

## The pins (`tests/test_cx_overlap_fresh_store.py`)

`test_recorded_row_carries_fresh_overlap_not_prelock_snapshot` ·
`test_normal_record_stores_the_recomputed_overlap` · `test_fresh_empty_overlap_refuses_with_unchanged_gate` ·
`test_real_retraction_in_prelock_window_refuses_in_transaction` · `test_retraction_before_submission_refuses_prelock` ·
`test_duplicate_does_not_recompute_and_does_not_rewrite` · `test_record_appends_exactly_two_events`.
The discriminating pin constructs a retraction in the pre-lock window so the two values differ
deterministically.

## Fail-on-base (agent-run, scratch at `2b0228d` + the new test file)

**1 failed, 6 passed** (exit 1): `test_recorded_row_carries_fresh_overlap_not_prelock_snapshot` —
stored `['art-ev1', 'art-ev2']` (pre-lock on base) vs the fresh `['art-ev2']`; exactly the defect.
Scratch worktree removed.

## Gates (raw)

Agent run (slice tip): targeted battery `100 passed`; full suite `4673 passed, 3 skipped` (exit 0);
stamp OK 4676 (own branch); census PASS; B4 24/24; ruff pass; pyright src 0/0/0; pyright tests
0 errors + 1 pre-existing warning.

Director restacked-tip re-derivation (live): stamp `--check` OK **4685**; census **PASS**;
B4 `24 passed`; battery (`cx_overlap` + `chg_dedup` + `n9_retraction` + `n9_resolve` + `hr08`)
`55 passed`; ruff `All checks passed!`; NOT-list scan (range diff) **0 hits**.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits in range/commits/src-tests (docs prose hits on base tree are clearance text, not the delta) |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `db76eb6` |
| dirty main-bound worktree | **PASS** — clean pre-FF and post-FF |
| `--check` drift | **PASS** — 4685 (4678 + 7) |
| census / B4 drift | **PASS** — unchanged (same transaction, no new calls) |
| N1/N9 semantics / duplicate fast-path | **PASS** — untouched; n9 + chg1 + hr8 pins green |
| push without a human hash-pin | **none performed** |

## Bundled push plan (drafted, NOT executed)

One human D9 pin covers the single final tree (CHG-DEDUP-1 + this landing + CRES-DIGEST-1 +
RESOLVER-PARITY-1 + all merge logs): origin fast-forward `2b0228d → <final tip>`; public mirror
orphan-sync with tree = `<final tip>^{tree}`, parent = live mirror HEAD, exact-hash push, no force
(rule #5).

## Prohibited-claims discipline

This gate certifies a provenance-store fix on the recorded contradiction row with pinned refusal
gates. It makes no validity, reproducibility, or admissibility claim.

License: Apache-2.0 (LICENSE).
