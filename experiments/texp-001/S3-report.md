# TEXP-001 S3 — Build Report (shared proposal kernel)

**Branch:** `texp-001/s3` (from `main@c0b5777`). **Inputs:** spec v1.2
D1/D3 + S1 validator + S2 energy + P2 plan S3 slice + live tree.
**Constraints honored:** nothing in `src/`; stdlib-only
(`__future__`/`dataclasses`/`hashlib`/`math`/`typing` + local `random`
import inside `make_rng_stream`); deterministic given seed; no model
calls; no pushes; no schedule mechanism anywhere in the kernel.

## Built

- `experiments/texp-001/kernel.py` — fixed-T Metropolis chain:
  `make_rng_stream` (sha256-derived streams per graph/seed/purpose, no
  module-level generator — cross-stream sharing constructionally
  impossible), `BudgetCounter` (`evaluate` counts every energy call
  incl. Metropolis rejects; `spend` prices restarts at 1 unit,
  stipulated; overrun raises `BudgetOverrun`), `initial_path`,
  `propose` (prefix-keep + random-walk regrow, truncated to `l_max`,
  bounded retries, validator-verdict-only filtering), `run_chain`
  (fixed `temperature` parameter validated > 0; restart resets to
  initial; overrun caught internally as `truncated=True`;
  `ChainResult` carries in-memory floats only).
- `experiments/texp-001/test_kernel.py` — 11 tests: end-to-end vs S1+S2,
  exact restart/budget accounting (3 steps/3 restarts/7 used), overrun
  raises, seed-identity, stream divergence + independence, no
  validator-internals, no-schedule tokens, T>0 enforcement, L_max +
  metro-reject counting, float-only energies + import allowlist.
  Result: **11 passed**.
- Vendored dependencies (branch is self-contained; `main` has no
  experiments/): `validator.py` byte-identical to `texp-001/s1`
  (sha256 `f672ec2d…`, 112 lines), `energy.py` byte-identical to
  `texp-001/s2` (`0379c33d…`, 66 lines). Pending track merge; no
  divergence permitted (re-verify hashes on merge).
- `docs/texp-001/ROADMAP.md` — created (absent on `main`): prior-phase
  pointers (P0 `texp-001/p0@998292b` + supplement `0867c64`; P1
  `texp-001/p1@f7d2559`; P2 `texp-001/p2@48e4ce9`; S1 `texp-001/s1`;
  S2 `texp-001/s2`) + S3 row DONE.

## Pre-test fix (self-caught, documented)

First draft double-evaluated energy per candidate (a stray block
evaluating `current` before `cand`, double-spending budget) — removed
before any test ran; the exact-accounting test (3/3/7) pins the
corrected single-evaluation semantics.

## Seam surface for S4 (C6)

S4 passes `temperature` per arm (fixed for A1, schedule for A2 —
schedule code lives in S4, never here), `validator`/`energy` callables
(S1/S2 functions shared by object identity), `graph` adjacency,
`context`, and one `BudgetCounter` per run. `ChainConfig` carries no
schedule fields; token scan (`anneal|cooling|schedule|alpha|T_end`)
is a pinned test. K-S2c pre-satisfied by construction (floats only,
no writes — pinned by import-allowlist + float-assertion tests).

## Stipulations in S3 (minimal, labeled)

Restart = reset-to-initial at 1 budget unit; L_max by truncation;
initial = random admissible singleton; proposal = prefix-keep/regrow
with bounded retries. Production-agreement open item carried (no
production kernel exists to agree with).
