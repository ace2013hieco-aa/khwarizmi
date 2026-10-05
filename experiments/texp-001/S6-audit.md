# TEXP-001 S6 — Audit (adversarial)

## IDENTITY

**Role:** Adversary, fresh session. **Branch:** `texp-001/s6-audit`
(from `texp-001/s6@3ac9c4d`). **Inputs:** (1) S6 file list at pin
(analysis/lock/test/S6-report/ROADMAP, +481/−1); spec D5/D6/D7/D8 +
appendix recovered verbatim from the hash-pinned blob (`9433022`,
sha256 `94b19e9d…`); (3) director rulings inline (asymmetric C5
stands; C7 scope-cap; signed ranges/seeds). No prior reasoning relied
upon. Stop screen: nothing in this session's materials refers to the
four excluded projects as in-scope content; no `src/` edits; no pushes.

## ATTACKS (falsify-don't-confirm; failed attacks reported)

1. **Statistical correctness** — independent reimplementation
   (different draw calls) reproduces CIs exactly ([0.094, 0.106] both,
   both cover 0.10); Wilcoxon hand-checks match incl. ties
   ([1,1,−2]→3.0/3.0) and zero-dropping ([0,1,−1]→1.5/1.5/n2);
   seed determinism holds; index math 250/9750 confirmed. **FAILED.**
2. **D6/D7 fidelity** — `decide_outcome` branches match spec D6
   (methods-flag→2; LB>δ+guards+hold→1; UB<−δ→3; else 2, covering the
   within-band case); disagreement default wired; p-value machinery
   absent (the token occurs only in two denial docstrings,
   `analysis.py:87/:172`). **FAILED.**
3. **C5 compliance** — the module docstring (`analysis.py:11-21`,
   echoed at `:127-133`) proposes aligning HOLD to the EVAL bar,
   **contrary to the binding asymmetric ruling**. Code path is
   bar-agnostic (proven: `hold_confirmed` is a bool input; no HOLD-bar
   constant exists; `delta_min=0.05` default is the EVAL bar) — so no
   behavioral risk today. **CONFIRMED → K-S6a** (docstring correction
   to the asymmetric ruling + conjunction rationale, closing at lock).
4. **Lock completeness** — every appendix leaf present except the five
   structural list elements (`bridge_len[0..2]`, `noise[0..1]`),
   intentionally FILL per the STOP rule with P4-restore note in
   `lock.py` docstring; template extras (`hold_bar`,
   `validator_agreement`, `validator_provenance`) documented.
   Nested FILL-trip works (`arms.A1`); clean template trips empty;
   nested reorder + rehash stable. **FAILED.**
5. **Scope-cap enforcement** — `report_effect`/`evaluate_guardrails`
   stamp unconditionally; `load_results` is input plumbing (not an
   output). **Gap found:** `decide_outcome` returns bare ints with no
   stamp, contradicting the "every output" claim → **K-S6b** (stamp
   decision outputs or document the vocabulary exception before lock).
6. **Ranges/seeds sanity** — signed ranges cover exactly the
   `make_a1`/`make_a2` hyperparameters (`temperature` / `t0, alpha,
   t_end`); dynamics span free→frozen (exp(−3/100)≈0.97,
   exp(−3/0.01)≈0); α excludes heating; all four seed ranges pairwise
   disjoint with stated sizes; EVAL/HOLD supply (3000) covers N≈32
   demand (≈992), TUNE (800) covers 600. **FAILED.**

## FINDINGS

- **CONDITION K-S6a (given)** — correct the C5-alignment paragraph to
  the asymmetric ruling; closes at lock. No behavior change (proven
  bar-agnostic above).
- **CONDITION K-S6b (new)** — scope-stamp `decide_outcome` outputs or
  record the vocabulary exception before lock.
- S6 tests re-run green (11/11). No BLOCKERs.

## VERDICT: PASS WITH CONDITIONS K-S6a, K-S6b

S6 tooling is correct, deterministic, and honestly scoped; both
conditions are lock-time documentation, no code rework required.
