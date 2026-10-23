# MERGE-LOG-WIRE-6 — declared-but-unwired intent kinds pinned, with recorded couplings (GAP-1 P2-8 / ruling D6-A)

## Provenance

| Item | Value |
| --- | --- |
| Task | WIRE-6 (merge gate; local FF — the push is bundled with the wave-3a fleet under one human D9 pin) |
| Base (`main` before) | `afad218` (UNWRAP-AUDIT landing + its merge log) |
| Slice | `slice/wire-6@af130be`; **restacked** as `slice/wire-6-restacked@3df7dc8` (1 cherry-pick; the slice's re-stamp dropped and re-created for the combined count — no rebase, no merge commit) |
| Landed tip (FF'd to) | `3df7dc8e4e995fc6462903aaced9cad69bf97511` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the wave-3a fleet under one human D9 pin |

## Scope

```
tests/test_wire_6_pins.py | 462 ++  (new: 5 structural pins)
docs/SUITE-COUNT.md       |  +3 -3  (4945)
```

**Zero `src` changes.** D6-A pins the declared state; it does not wire
anything.

## What was certified

- **Coverage is derived, not restated.** The pin locates `apply_intent`'s
  if/elif chain by shape, resolves every positive kind comparison
  (`IntentKind.X`, `"X" == kind`, `kind == "X"`, `kind in (...)`, and `or`
  unions), and derives the covered set from the live AST. A shape it cannot
  read is an anomaly that fails the pin closed — it never guesses and never
  silently drops a branch.
- **The remainder is exactly the six D6-A kinds.**
  `llm_proposable − covered == {BRANCH, ABANDON, REQUEST_HUMAN,
  REQUEST_REPLICATION, REQUEST_ADDITIONAL_EXPERIMENT, PROPOSE_GATE_OVERRIDE}`,
  and the same identity holds against **every** declared `IntentKind` member,
  so a new unwired kind cannot appear unannounced.
- **No silent fall-through.** The chain must end in an `else` raising the
  frozen `NOT_WIRED` code; the six must stay LLM-proposable and stay outside
  the dispatch.
- **The coupling map is the ruling text.** `BRANCH` / `ABANDON` /
  `REQUEST_HUMAN` → R2 / P1-12; `REQUEST_ADDITIONAL_EXPERIMENT` → D2;
  `REQUEST_REPLICATION` / `PROPOSE_GATE_OVERRIDE` → own gates; and the map is
  asserted equal to the live uncovered set, so drift fails the suite.
- **Authority kinds are dispatched.** Every `director_only` and
  `internal_only` kind is covered by the dispatch — none falls to `NOT_WIRED`.

## Director adversarial probes (the pin must be able to fail)

Run against an isolated copy of the tree, then discarded:

| Probe | Expected | Observed |
| --- | --- | --- |
| Add `elif intent.kind is IntentKind.BRANCH: result = None` before the fallback | the pin refuses a silent wiring | **3 failed** (coverage, six-reach-only, coupling map) |
| Change the fallback code `NOT_WIRED` → `UNKNOWN_KIND` | the pin refuses a weakened fallback | **4 failed** (all four structural pins) |
| Unmodified tree | green | **5 passed** |

## Gates (raw, at restacked tip `3df7dc8`)

- `tests/test_wire_6_pins.py`: **5 passed**
- `stamp_suite_count.py --check`: `OK: docs\SUITE-COUNT.md collected=4945 matches the live collect` (4940 + 5)
- `ruff check src tests scripts`: `All checks passed!`
- Full suite: batch-end gate at the combined wave-3a tip (recorded in
  `docs/MERGE-LOG-WAVE-3A.md`).

## STOP-condition checks

| Condition | Result |
| --- | --- |
| `src` edit | **none** — expected zero, observed zero |
| derived-set mismatch | **none** — the live uncovered set is exactly the six |
| pin weakened to fit the code | **no** — the pin derives from the AST; the probes show it refuses both a wiring and a weakened fallback |
| census shift | **none** — no executable code touched |
| B4 digests moved | **no** — no governed doc touched |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies a structural fact about the gateway's dispatch table and a
recorded staging decision. It does not claim the six kinds are implemented,
safe, or reachable; they remain declared, LLM-proposable, and refused with
`NOT_WIRED` until their recorded couplings land.

License: Apache-2.0 (LICENSE).
