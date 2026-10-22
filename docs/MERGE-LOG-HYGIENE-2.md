# MERGE-LOG-HYGIENE-2 — structural hygiene: validator stages, refusal-code census, dead-lock decision (GAP-1 P3-4/6/8)

## Provenance

| Item | Value |
| --- | --- |
| Task | HYGIENE-2-MERGE (merge gate; local FF — the push is bundled with the GAP-1 wave-2 fleet under one human D9 pin) |
| Base (`main` before) | `6e76fee` (GAP-1 wave-1b pushed tip) |
| Slice | `slice/hygiene-2@c8692e2` |
| Landed tip (FF'd to) | `c8692e2` — tree recomputed at FF |
| Merge method | **fast-forward** — `git merge --ff-only` (no restack) |
| Push | drafted, **NOT executed** — bundled with the wave-2 fleet under one human D9 pin |

## Scope

```
src/hermes/research/gateway.py        | +760 -313  (P3-8 validator stages)
src/hermes/persistence/database.py    |  +11       (P3-4 dormancy note; owner-count correction)
tests/test_hygiene_structural.py      | +169       (5 tests)
docs/SUITE-COUNT.md                   |  +3 -3     (4861 -> 4866)
```

## What was certified

- **P3-8** — `_validate_retract_source` (487 lines) split into 8 named private
  stage helpers inside gateway.py: `_retract_source_command`,
  `_retract_source_binding`, `_retract_source_id`,
  `_retract_source_record_decision`, `_retract_source_invalidate_cone`,
  `_retract_source_invalidate_curated`,
  `_retract_source_supersede_contradictions`,
  `_retract_source_emit_retracted_event`. Behavior-neutral by construction
  (same order, same refusal codes/messages, same return values); proven by
  the unchanged full suite (4863 passed + 3 designed skips).
- **P3-6** — refusal-code census pinned by AST/source scans
  (`test_gateway_refusal_code_census_is_exact`,
  `test_proposal_refusal_code_count_is_deterministic`,
  `test_refusal_code_symbols_are_stable_module_constants`) with counts
  derived live from the code at this tip (never copied from the triage);
  `test_no_spine_code_token_in_src` pins the absence claim. No governed-doc
  edits (no B4 regen needed).
- **P3-4** — `acquire_writer_lock` is RETAINED (not deleted), documented as
  deprecated for new orchestration callers: it has ZERO `src/` callers, but
  the certified Phase-1 acceptance surface imports and exercises it directly
  (`tests/test_phase1_acceptance.py:17,20,122-194,774-776`) — deletion would
  break a certified surface. Dormancy note corrected from "27 owners" to
  **28 owners / 124 calls** (CRED-1 added the 19th persistence owner).
  Transaction boundaries themselves untouched (D12 territory).

## Gates (Director re-derivation at the landed tip)

| Gate | Result |
| --- | --- |
| FULL suite | **4863 passed, 3 skipped, 0 failed** (703.49s) |
| stamp `--check` | OK — collected **4866** (4861 + 5) |
| census | PASS — 124 calls / 28 owners (19/5/4) / 1 rollback-only / 15 imports |
| B4 | **24 passed** |
| ruff | `All checks passed!` |
| pyright src | 0 errors, 0 warnings, 0 informations |
| pyright tests | 0 errors, 1 pre-existing warning (`test_research_program.py:144`) |
| NOT-list | **0 hits** (word-boundary) |

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| behavior change in the validator split | **none** — identical refusal semantics; full suite unchanged |
| transaction boundaries / census altered | **none** — 124 / 28 unchanged |
| deleting a certified surface (`acquire_writer_lock`) | **avoided** — retained with a deprecation note; phase-1 import proven live |
| B4 governed corpora | **PASS** — 24/24; no governed-doc edits |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `6e76fee` |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies a behavior-neutral extraction, a source-derived refusal
census, and a dead-code decision. It makes no validity, reproducibility, or
admissibility claim.

License: Apache-2.0 (LICENSE).
