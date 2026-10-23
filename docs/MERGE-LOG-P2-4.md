# MERGE-LOG-P2-4 — fixture-anchoring design note, integrity wording corrections, and the withdrawn C record (GAP-1 P2-4)

## Provenance

| Item | Value |
| --- | --- |
| Task | P2-4 (GAP-1): fixture anchoring — manifest signature or journal anchor |
| Base (`main` before) | `67ba1e1` |
| Slice | `slice/p2-4-anchor@24daf18` — created at the base; landed by **fast-forward** |
| Landed tip | `24daf18` |
| Status | **Design note only; the ruling (A / B / C) is still pending.** No code, no test, no migration, no fixture change. |
| Push | included in the wave-3c push (this batch) |

## Scope

```
docs/idr/FIXTURE-ANCHORING.md        | 330 ++  (new: the design note)
src/hermes/research/ref_graphs.py    |   7 +-  (docstring only)
docs/gr3-b4/b4-fixtures/README.md    |   9 +-  (the same claim, corrected)
docs/gr3-b4/P2-b4fixtures.md         |   6 +-  (the strongest form of the claim, corrected)
```

## What landed

- **The design note.** It establishes, with file:line evidence, that the fixture
  binding is **corruption-evident** (the name is the sha256 of the bytes, so a damaged
  file is refused at read time) and **regeneration-evident** (the suite rebuilds every
  fixture from the governed corpus), and that it is **not tamper-evident** — a replaced
  file whose name was recomputed is self-consistent and is caught only by regeneration,
  which is itself code in this repository. It costs three options (A journal pin event,
  B signed manifest, C document-and-accept) and requests the ruling rather than taking it.
- **Three wording corrections**, true under any of A/B/C: the module docstring, the
  fixtures README, and `P2-b4fixtures.md`'s *"needs no signature to detect tampering"* —
  the strongest form of the false claim, which the note's own §4 correction list had
  initially omitted.

## The withdrawn record (disclosed)

`fb7f755` briefly recorded `Status: RULED C — document-and-accept (2026-10-23, human)`
and a §4 paragraph asserting the human had ruled C and that A and B were not adopted.
**No such ruling was given.** The Director withdrew it in `24daf18`: the status row is
back to *"Proposal; the ruling is requested in §4"*, the paragraph is gone, and §5 speaks
of the recommended option rather than a ruling. The three wording corrections were kept —
they describe what the binding does, not which option is chosen.

## The citation error (Director's, corrected)

The note initially cited `ci.yml:33` as the full-suite step. At `67ba1e1` the committed
workflow has `test:` at 13, the suite-count step at 33, and the full-suite step at **43**.
The implementing agent flagged the drift; the Director had supplied the wrong number. Both
occurrences now read `ci.yml:3-10,13,43`, verified against the committed blob.

## Gates (raw)

| Gate | Result |
| --- | --- |
| B4 ref graphs | **24 passed** |
| `stamp_suite_count.py --check` | `OK: docs\SUITE-COUNT.md collected=5058` |
| Full suite (slice tip) | **5050 passed / 3 skipped / 5 failed** — the five intermittent host failures |
| `ruff check src tests scripts` | `All checks passed!` |
| `pyright src` | **0 errors, 0 warnings, 0 informations** |
| Governed corpus touched | **none** (no B4 regeneration needed) |
| `ref_graphs.py` | docstring-only: one hunk, no executable line |

## Residuals

1. **The ruling is open.** The note recommends C; A and B remain available. If A is chosen,
   the note needs a ruling record and an implementation outline; if B, D5 must be reopened
   first.
2. The five environment-sensitive tests are **intermittent** (5 / 4 / 0 failures observed on
   consecutive runs); a clean run is not evidence of a code change.

## Prohibited-claims discipline

This gate lands a proposal and corrects a claim. It asserts nothing about the fixtures'
tamper-resistance: they are corruption-evident and regeneration-evident, and that is the
whole claim.

License: Apache-2.0 (LICENSE).
