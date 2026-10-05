# TEXP-001 S4 — Build Report (arms + tuning harness)

**Branch:** `texp-001/s4` (from `texp-001/s3@c338581`). **Inputs:** spec
v1.2 D1/D3 + S3 kernel + seam sketch + S3 audit incl. K-S3a + P2 plan S4
slice + live tree. **Constraints honored:** nothing in `src/`;
stdlib-only; deterministic given seed; `kernel.py` UNMODIFIED (mounted
via seam only — verified by `git diff` emptiness at commit, see below);
energies in-memory only; no pushes; no TUNE execution (harness
mechanics only — tuning runs at P4).

## Built

- `experiments/texp-001/arms.py` — `ArmSpec` (arm_id, per-segment
  temperatures, shared energy/validator callables, restart_prob,
  l_max, budget, steps_per_segment); `flat_energy` (constant-zero:
  the formalization of A0 "no energy" inside shared-kernel mechanics —
  equal candidates always accept, temperature provably irrelevant);
  `make_a0/make_a1/make_a2` (A1 temperatures constant by construction;
  A2 `T_k = max(t_end, t0·alpha**k)` with `0<alpha<1`, positive bounds
  enforced); `run_arm` (chained fixed-T segments over one shared
  counter — the S4-side schedule mounting; piecewise-constant
  disclosed, not hidden).
- `experiments/texp-001/tuning.py` — `sample_configs` (seeded uniform
  over caller-declared ranges; ranges REQUIRED input, never defaulted
  here), `select_best` (max primary metric, ties keep first),
  `robustness_fraction` (strict float `<=` margin — pinned by a
  boundary fixture: 0.9−0.85 exceeds 0.05 in float arithmetic),
  `N_TUNE_DEFAULT = 60`, `ROBUSTNESS_MARGIN = 0.05`. Imports nothing
  runnable (pinned by test) — TUNE cannot execute from this harness.
- `experiments/texp-001/test_arms.py` — 9 tests: single-variable
  (A1/A2 field-equal modulo temperatures + arm_id; A1 temps constant);
  A0 T-irrelevance (normalized equality); A0 `metro_rejects == 0`;
  identical budget counting across arms; end-to-end linkage;
  tuning determinism/selection/margins/errors; no-runner imports;
  import hygiene. Result: **9 passed**.
- `docs/texp-001/ROADMAP.md` — S4 row DONE (amended).

## K-S3a closure (maximal without violating the kernel STOP rule)

Completed here (inventory, documented): restart = reset-to-initial at
1 unit; L_max by truncation; initial = random admissible singleton;
proposal = prefix-keep/regrow with bounded retries (8/×4/2×L_max);
validator-before-energy ordering (validator rejects free of budget);
T>0 scope exclusion; `max_steps` default; truncation semantics;
`_dst_of` fallback; ties-keep-first best-tracking; validator
double-invocation (propose filter + re-check; counter fires only under
validator nondeterminism). **Carried to a kernel-track commit (STOP
forbids `kernel.py` edits on this track):** (i) "caught internally"
docstring overclaim (budget=0 initial-eval propagates instead of
setting `truncated`) — fix text: "mid-run overrun sets `truncated`;
initial-eval overrun propagates `BudgetOverrun`"; (ii) drop unused
`field` import. Exact patch spec above; one edit, zero behavior change.
`kernel.py` verified byte-unmodified on this branch (`git diff`
emptiness, see verification).

## K-status + TUNE-blocked remainder

K-S1a/K-S1b/K-S2a/b/c unaffected (S5/S6/pilot-owned, still open). No new
K-items opened by S4. TUNE remains blocked on: S1–S5 gates (F6, F2,
blindness review), declared ranges + seeds at lock (D3/D8), and the
C5/C7 pre-lock decisions. Production-agreement open item carried (no
production arms exist to agree with).
