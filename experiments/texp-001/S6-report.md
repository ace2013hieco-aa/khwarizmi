# TEXP-001 S6 — Build Report (analysis + lock tooling)

**Branch:** `texp-001/s6` (from `texp-001/s5b@faf018d`). **Inputs:**
spec D5/D6/D7/D8/appendix + S5 line + C5/C7 proposal status + P2 plan
S6 slice + live tree. **Constraints honored:** nothing in `src/`;
stdlib-only (no scipy/numpy — bootstrap/Wilcoxon hand-rolled from
seeded `random`); analysis reads result FILES only, never generator
or sampler internals; no pushes; no PILOT/TUNE/EVAL/HOLD execution
(tooling + synthetic-input tests only).

## Built

- `experiments/texp-001/analysis.py` — `paired_bootstrap_ci`
  (percentile, spec defaults 10k/95%, seeded, fail-closed on empty/
  non-finite), `wilcoxon_signed_rank` (ties averaged, zeros dropped;
  no p-values anywhere), `methods_agree` (D7 disagreement →
  default-2 wired into `decide_outcome`), `decide_outcome` (D6 1/2/3
  as a pure function; HOLD bar supplied by caller under the recorded
  rule), `evaluate_guardrails` (G1–G5 over plain records, missing
  fails closed), `report_effect` (mean+CI+Wilcoxon, no p-value keys),
  `load_results` (shape-checked JSON), scope stamp on every output.
- `experiments/texp-001/lock.py` — appendix lock block with EVERY
  field FILL (including appendix-fixed strata constants, restored at
  P4 per the STOP rule) + `hold_bar`/`validator_agreement`/
  `validator_provenance` extension slots (P1-required record homes,
  FILL like the rest); `assert_all_fill` (STOP guard);
  order-invariant canonical serialization + sha256.
- `experiments/texp-001/test_analysis.py` — 11 tests: CI covers known
  truth, CI width shrinks with n, garbage rejected, Wilcoxon agreement
  on effect + null, all D6 branches incl. disagreement default,
  each guardrail trips, missing fails closed, scope on every output,
  tmp-file loading, all-FILL + stability + fill-detection.
  Result: **11 passed**.
- `docs/texp-001/ROADMAP.md` — S6 row DONE (amended).

## RANGES-SEEDS proposal (FOR DIRECTOR SIGN-OFF — not locked, not used)

Tuning ranges (cover each arm's hyperparameters per D3; justified by
the stipulated len-energy scale, ΔE ∈ {0,±1,±2,±3} at these lengths):
A1 T [0.1, 20.0] (greedy→diffusive crossover bracketed);
A2 T0 [1.0, 100.0] (locked→free start), α [0.80, 0.999] (perceptible
cooling without freezing or heating; α≥1 excluded), T_end [0.01, 1.0]
(near-greedy terminus, T>0 kernel requirement honored). Seed ranges,
disjoint with stated sizes: PILOT 1000–1199 (200: σ_d graphs + algo
seeds + fixtures + margin); TUNE 2000–2799 (800: 60 configs × ~10
seeds + margin); EVAL 3000–5999 (3000: N≈32+ graphs + 3 arms × N × 10
algo seeds + margin); HOLD 6000–8999 (3000, mirrors EVAL).

## C5/C7 proposal status + K-status + lock-blocked remainder

C5: HOLD aligned to the EVAL bar proposed (module docstring with
rationale); C7: transfer scope capped unknown + agreement in every
memo (proposed) — both pending sign-off with this report. K-S1a (hub
presence at scale), K-S1b (lock quotes flag at fill time), K-S2a
(hub fractions at pilot), K-S2b (bar — proposed above), K-S2c (S4 C5
check), K-S5a (ℓ stipulation; planting works per S5b, pilot ℓ≥3 needs
B4 scale), human blindness + B6 ratification deferred to lock.
Lock-blocked remainder: B4 real scale, production-validator
agreement, range/seed sign-off, C5/C7 sign-off, analyst + operator
ratification (D6/D8).
