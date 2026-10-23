# MERGE-LOG-PROVIDER-1 — hazard-spec fail-closed path and gateway-wide payload shape bounds (GAP-1 P2-3 / P2-10)

## Provenance

| Item | Value |
| --- | --- |
| Task | PROVIDER-1 (merge gate; local FF — the push is bundled with the wave-3a fleet under one human D9 pin) |
| Base (`main` before) | `ec5af26` (WIRE-6 landing + its merge log) |
| Slice | `slice/provider-1@4b239da`; **restacked** as `slice/provider-1-restacked@29c8b8c` (3 cherry-picks; the slice's re-stamp dropped and re-created for the combined count — no rebase, no merge commit) |
| Landed tip (FF'd to) | `29c8b8cf0cd864d9dad826bd4fcf013d2f22e0f7` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the wave-3a fleet under one human D9 pin |

## Scope

```
src/hermes/research/gateway.py               |  54 +-  (P2-10 bound + pre-dispatch call)
src/hermes/tools/providers/paginate.py       |   7 +-  (P2-3 typed refusal)
tests/test_gateway.py                        | 184 ++   (23 shape-bound pins)
tests/test_provider_walk.py                  |  65 ++   (registry census + refusal + override)
tests/test_provider_fetch.py                 |  21 ++   (fetch driver refusal)
tests/test_hr04_source_identifier_capture.py |  13 +-  (typed-error alignment)
tests/test_hygiene_structural.py             |   4 +-  (refusal census: +1 site)
docs/SUITE-COUNT.md                          |  +3 -3  (4972)
```

## What was certified

### P2-3 — spec-less providers refuse before any I/O

- `_load_shipped_spec` now raises `SpecValidationError`
  (`hazards.py:247`, a `PermanentProviderError`) carrying
  `provider_id` and `hazard_class="SPEC_INVALID"` instead of a bare
  `ValueError`. This is the hazard boundary's existing typed error, not a new
  class and not a new hazard class.
- **The no-spec set is 7 of 15 registered providers, not 8.** The triage list
  named `base`, but `base` is the adapter base module
  (`src/hermes/tools/providers/base.py`), not a provider id; `PROVIDER_REGISTRY`
  holds 15 ids, 8 with shipped specs and 7 without. The new census test walks
  the registry and pins both sets, so a provider added without a spec (or a
  spec shipped for an unregistered id) fails the suite.
  - Shipped (8): `arxiv`, `brave`, `europepmc`, `exa`, `openalex`, `pmc`,
    `searxng`, `tavily`.
  - Refused (7): `biorxiv`, `core`, `crossref`, `medrxiv`, `pubmed`,
    `semantic-scholar`, `unpaywall`.
- Refusal happens **before any request**: the walk and fetch pins assert
  `transport.calls == 0`, no limiter acquisition, and no adapter request. The
  typed error propagates; it is not swallowed into a verdict.
- **No invented allowlist host, regex, or spec.** No file under
  `hazard_specs/` and no allowlist was touched. Filling the seven gaps by
  guessing endpoints is explicitly not what this slice does.
- An explicit `hazard_spec=` override still admits a spec-less provider (pinned).

### P2-10 — gateway-wide payload shape bound, applied pre-write

- `INTENT_PAYLOAD_MAX_DEPTH = 16`, `INTENT_PAYLOAD_MAX_CONTAINERS = 4096`.
  The root payload is depth 1; every dict/list/tuple node counts toward the
  container bound; a reference cycle is refused (it would otherwise defeat the
  walk). Refusal code is the existing `MALFORMED_PAYLOAD`, refusal-as-data.
- Applied in `apply_intent` after role/project/provenance and **before the
  budget/governance hooks and every per-kind validator**, so no validator can
  commit a row first. The pin parametrizes all 15 wired kinds and asserts one
  `IntentRejected`, no `IntentApplied`, and no task row.
- Boundary pins: depth 16 admitted / 17 refused; 4096 containers admitted /
  4097 refused; 10 000-deep nesting refuses without a `RecursionError`;
  a self-referential dict refuses.
- **Rationale** (pinned in the test docstring): the deepest shipped proposal
  draft is depth 3, so 16 keeps >5× headroom while staying an order of
  magnitude below the interpreter's recursion budget; 4096 containers is far
  past the 4 KiB journal event cap, which is **unchanged**.
- **W4 residual pinned, not tightened:** non-source `spec` *values* stay
  free-form (the program-id field is not even type-checked), so the bound
  constrains structure only. Tightening values would reject currently-admitted
  traffic; `test_non_source_spec_value_shape_stays_admitted_w4` records that
  decision.

## Refusal-census refresh (ruled change, inline reason)

The payload bound adds exactly one `MALFORMED_PAYLOAD` refusal site:
`MALFORMED_PAYLOAD 122 → 123`, total `267 → 268`, with the inline comment
`# COND-TYPE +1 site; GAP-1 P2-10 +1 site`. Structure is unchanged; only the
count moved, and only for this ruled change.

## Gates (raw, at restacked tip `29c8b8c`)

- Battery (`test_gateway`, `test_provider_walk`, `test_provider_fetch`,
  `test_hygiene_structural`, `test_hr04_source_identifier_capture`):
  **235 passed**
- `check_census.py`: **PASS** — 124 transaction-control calls / 28 owners
  (persistence 19, gateway 5, Controller 4) / 1 rollback-only / 15 imports /
  0 outside certified layers — **unchanged**
- `stamp_suite_count.py --check`: `OK: docs\SUITE-COUNT.md collected=4972 matches the live collect` (4945 + 27)
- `uvx pyright src`: **0 errors, 0 warnings, 0 informations**
- `ruff check src tests scripts`: `All checks passed!`
- Full suite: batch-end gate at the combined wave-3a tip (recorded in
  `docs/MERGE-LOG-WAVE-3A.md`).

## STOP-condition checks

| Condition | Result |
| --- | --- |
| invented allowlist host / regex / spec | **none** — no spec or allowlist file touched; the seven gaps are refused, not guessed |
| new transaction-control call | **none** — census identical (124 / 28 / 19 / 15) |
| 4 KiB event cap changed | **no** — `event_validation.py` untouched |
| valid traffic newly refused | **none observed** — full suite green at the batch tip; the free-form `spec` W4 case is explicitly pinned as still admitted |
| refusal-census drift without reason | **no** — one site, inline reason, structure unchanged |
| B4 digests moved | **no** — no governed doc touched |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies a fail-closed refusal path for spec-less providers and a
structural payload bound. It does not claim the seven providers are supported,
that their future specs are known, or that a bounded payload is a safe payload:
the bound limits shape, not content, and the 4 KiB journal cap remains the
separate content-size authority.

License: Apache-2.0 (LICENSE).
