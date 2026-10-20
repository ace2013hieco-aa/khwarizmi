# MERGE-LOG-RULINGS-GAP1-1 — GAP-1 rulings record + D5-A posture + deliberate B4 regen

## Provenance

| Item | Value |
| --- | --- |
| Task | RULINGS-GAP1-1-MERGE (merge gate; local FF — the push is bundled with the sibling GAP-1 wave-1b slices under one human D9 pin) |
| Base (`main` before) | `636bab5` (HR08-PIN-1 landing + its merge log) |
| Slice | `slice/rulings-gap1@e3ce5ef`; **restacked** as `slice/rulings-gap1-restacked@e3b1f8f` (docs-only cherry-picks `f052197` + `beccde8` + one landing-resolution commit refreshing the D10 status row — no rebase, no merge commit) |
| Landed tip (FF'd to) | `e3b1f8f1ac59715ea49b2cda2bb2cfc467411e87` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the GAP-1 wave-1b fleet under one human D9 pin |

## Scope

```
docs/GAP1-RULINGS.md                    | +123      (new; D1-D12 + status + wave-1 record + D5-A)
docs/STATE.md                           |  +21      (wave-1 hardening entry + D5-A posture)
docs/gr3-b4/b4-fixtures/README.md       |  +15 -3   (regen record)
docs/gr3-b4/b4-fixtures/*.json          | 3 renames (2 lines each)
docs/SUITE-COUNT.md                     | unchanged 4861 (docs-only landing)
```

## What was certified

- The GAP-1 rulings **D1–D12** are recorded verbatim with evidence and
  couplings (`docs/GAP1-RULINGS.md`); wave-1 execution record cites the
  pushed tip `ce41570` with the suite chain 4743 → 4838.
- The **D5-A document-and-accept** posture (human override of the recommended
  key-custody IDR) is in `docs/STATE.md` under intentional architecture,
  with the explicit "boundary acceptance only — not a validity,
  reproducibility, or admissibility claim" caveat. Model-API-key policy
  (human-held, env-only, never wired) unchanged.
- **Deliberate B4 regeneration** for the governed `docs/STATE.md` edit:
  `b4-c1` `1727860b… → 357b9ee3…`, `b4-c2` `0551a2a6… → 03127be4…`,
  `b4-c4` `be83b607… → b5b21189…`; `b4-c3` unchanged. Edge sets and source
  counts identical (5 / 19 / 10 / 5; 6 / 12 / 8 / 4); each affected
  `skipped` list gains exactly one token (`docs/GAP1-RULINGS.md`, cited from
  `docs/STATE.md`) — citation structure invariant, only pinned byte
  identities moved.
- Landing resolution (recorded here): the D10 row's execution status was
  refreshed from "in flight / not landed at this tip" to **LANDED**
  (HR08-PIN-1, `b722b97`; merge log `docs/MERGE-LOG-HR08-PIN-1.md`) because
  this record lands *after* the pin — the record's status table must be
  truthful about the tree it is the ruling for. No ruling text changed.

## Gates (raw)

Agent run at slice tip `e3ce5ef`: **FULL suite 4835 passed, 3 skipped,
0 failed**; B4 24; stamp check 4838; census PASS; NOT-list 0.

Director re-derivation at restacked tip `e3b1f8f`: stamp `--check` OK
**4861** (docs-only slice adds no tests); census PASS; **B4 24 passed**
(proves the landing-resolution edit to the non-governed `GAP1-RULINGS.md`
does not move governed fixture digests); ruff `All checks passed!`;
NOT-list scan of the restack range **0 hits** (word-boundary); diffstat
6 files, +162/−6.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| ruling text altered during landing | **no** — only the D10 execution-status row + its evidence cell |
| B4 digests moved by the resolution edit | **no** — 24/24 after the edit |
| governing docs claiming more than recorded | **no** — prohibited-claims caveat present in STATE entry |
| census shift | **none** |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `636bab5` |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate records decisions and posture; it certifies no behavior change.
It makes no validity, reproducibility, or admissibility claim.

License: Apache-2.0 (LICENSE).
