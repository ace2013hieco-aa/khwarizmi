# MERGE-LOG-HR08-PIN-1 — structural pin: the only incoming edge into COMPLETED (GAP-1 D10-A)

## Provenance

| Item | Value |
| --- | --- |
| Task | HR08-PIN-1-MERGE (merge gate; local FF — the push is bundled with the sibling GAP-1 wave-1b slices under one human D9 pin) |
| Base (`main` before) | `487dc87` (FENCE-FUZZ-1 landing + its merge log) |
| Slice | `slice/hr08-pin-1@59f7077`; **restacked** as `slice/hr08-pin-1-restacked@785113a` (cherry-pick of `b722b97`; the slice's own re-stamp dropped and re-created for the combined count — no rebase, no merge commit) |
| Landed tip (FF'd to) | `785113a16687c3aa8871d6259828a08f7e049018` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the GAP-1 wave-1b fleet under one human D9 pin |

## Scope

```
tests/test_hr08_completed_edge_pin.py | +50      (new; 1 test)
docs/SUITE-COUNT.md                   |  +3 -3   (4860 -> 4861)
```

No `src/` change.

## What was certified

- The edge set is **derived at runtime** from `lifecycle._TRANSITIONS`
  (`src/hermes/research/lifecycle.py:83`; sole edge `REPORTING → COMPLETED`
  at `:114`) — never hand-copied. The pin asserts
  `{(src, dst) for (src, dst) in _TRANSITIONS if dst == "COMPLETED"} ==
  {("REPORTING", "COMPLETED")}`.
- The D10 interlock comment records the dependency on journal trigger stage S
  (TAMPER-1): trigger DDL `migrations.py:31`, created in `_migrate_20_to_21`
  (`:1256`), registered (`:1326`), and recreated in the rebuild path (`:364`);
  repositories choke points `transition_lifecycle` (`:206`, `:241`). The
  comment states the certification VOID if stage S (or its re-chain
  successor TAMPER-2) is ever removed — the structural pin alone never claims
  SQL-bypass protection.

## Fail-on-base (mutation)

Scratch-added a second incoming edge (`DRAFT → COMPLETED`) to
`lifecycle._TRANSITIONS`: **1 failed** —
`assert {'DRAFT', 'REPORTING'} == {'REPORTING'}`; restored: **1 passed**.
Logs: `hr08-pin-1-mutation-fail.txt` (831 B) /
`-fixed.txt` (untracked slice-worktree artifacts).

## Gates (raw)

Agent run: battery 104 passed; **FULL suite 4836 passed, 3 skipped, 0 failed**;
stamp 4839; census PASS; B4 24 passed; ruff pass; pyright 0/0/0;
NOT-list 0.

Director re-derivation at restacked tip `785113a`: battery
(pin + `test_hr08_completion_invariant.py` + `test_hr8_blind_window.py` +
`test_lifecycle.py`) **104 passed**; stamp `--check` OK **4861**
(4860 + 1); census PASS; B4 **24 passed**; ruff `All checks passed!`;
NOT-list scan of the restack range **0 hits** (word-boundary).

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| pin hardcodes the edge set instead of deriving it | **no** — read from `_TRANSITIONS` at runtime |
| D10 dependency honesty (stage S / TAMPER-2) | **recorded** in the test's interlock comment |
| census shift | **none** |
| B4 governed corpora | **PASS** — 24/24; no governed-doc edits |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `487dc87` |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies graph-structural coverage of the COMPLETED transition
edge. It makes no validity, reproducibility, or admissibility claim, and the
pin does not by itself certify tamper-evidence (that remains stage S +
TAMPER-2).

License: Apache-2.0 (LICENSE).
