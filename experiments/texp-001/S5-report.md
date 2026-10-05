# TEXP-001 S5 — Build Report (generator + fixtures)

**Branch:** `texp-001/s5` (from `texp-001/s3@c338581`). **Inputs:** spec
v1.2 D2/D4-fixtures + S1 validator + S4 arms + S4 audit (K-S4a) + P2
plan S5 slice + live tree. **Constraints honored:** nothing in `src/`;
stdlib-only; deterministic given seed; generator secrecy by object
boundary (not convention); K-S2a/K-S2b WIRED as pilot acceptance (bar
is a required parameter, hub fractions recorded); no PILOT execution
(micro-scale self-tests only); no pushes.

## Built

- `experiments/texp-001/generator.py` — DCSBM-lite (θ-weighted,
  in/cross densities, seeded single `Random`): planted bridge (ordinary
  -degree endpoints/intermediates, admissible sequence, cross-community),
  hub decoys (top-degree nodes, truth-only), explicit type-violating
  cross edges (`warp`, unknown type), near-miss (admissible prefix +
  inadmissible tail). Stored graph = node ids + edge triples ONLY (no
  mappings, no labels); truth = tuples/strs/numbers only (no shared
  references possible); `as_adjacency` builds fresh dicts per call.
  Fail-closed: ℓ with no table sequence raises `PlantingError`.
- `experiments/texp-001/fixtures.py` — F1 (byte-identity), F2 (null
  sanity), F3 (label-shuffle, graph-unchanged asserted), F4 (equal
  counters + overrun raises), F5 (direct deref False + write-path
  refusal on `texp001:` claim source), F6 (decoys refused, planted
  kept), F7 (K1-amended same-budget degraded-policy cripple),
  `pilot_gate` (F2 + required `bar` + recorded hub fractions),
  `collect_k_paths` (evaluated-set harness composition — see below),
  `hub_fraction`, metric units.
- `experiments/texp-001/test_generator.py` — 16 tests: decoy presence
  per class, strata recorded (micro-scale, not executed at scale),
  fail-closed planting (ℓ=3 raises), secrecy (observable-surface scan
  + id-disjointness + planted⊆edges positional check), metric units,
  F1/F3/F4/F5/F6 green, F2/F7 mechanics + determinism, pilot-gate
  wiring. Result: **16 passed**.
- Vendored `arms.py` byte-identical to `texp-001/s4` (needed: fixtures
  compose arms; `main` line has no experiments/). Pending track merge;
  no divergence permitted.
- `docs/texp-001/ROADMAP.md` — S5 row DONE (amended).

## Calibration findings (built, not hidden)

1. **ℓ≥3 unplantable under the S1 table** (max length 2) — generator
   raises instead of poisoning recall. Pilot ℓ∈{3,4} strata REQUIRE a
   sequences-table extension first (S1 follow-on).
2. **Best-per-segment K-collection is structurally blind** under
   monotone energy (bests are always shortest) — replaced with
   evaluated-set collection (energy runs post-admissibility, so every
   logged path passed the validator). Production K-output discipline
   remains a future arms refinement.
3. **No seed-hunting:** F2/F7 directional inequalities are asserted
   for mechanics/determinism only. Pinning a lucky micro-seed as
   "proof" would be Goodhart-on-fixture; direction is pilot-scale
   under B-calibration.
4. Key-scan lesson: `bridge_len` collides with a "bridge" token ban —
   the scan covers the sampler-observable surface (node ids + edge
   values), with the collision documented, not silently dropped.

## K-status + TUNE-blocked remainder

K-S3a inventory carried (kernel.py byte-unmodified on this branch —
verified at commit); K-S4a relabel noted for the S4 track (A0
uniformity wording lives there, untouched here). K-S1a (hub presence)
partially served: hubs generated + recorded + fraction helper wired;
presence-in-corpora asserts at pilot scale. K-S1b/K-S2a/b/c carried
(pilot/lock/S4-owned). Production-agreement open item carried (no
production graph/arms exist). TUNE blocked on: S1–S5 gates at scale,
declared ranges + seeds at lock (D3/D8), C5/C7 pre-lock decisions,
table extension for ℓ≥3 strata.
