# TEXP-001 S5-unify — Merge + Extension Report

**Branch:** `texp-001/s5-unify` (from `texp-001/s5@a339e06`; merge
`texp-001/s4`, no rebase). **Scope:** single line containing
validator+energy+kernel(+patch)+arms+tuning+generator+fixtures.

## Merge choices (recorded)

- Merge commit (no-ff, topology preserved): s4 brought `tuning.py`,
  `test_arms.py`, `S4-report.md`; `arms.py` arrived identical on both
  sides (s5 vendored it byte-identical from s4) — merged to ONE copy,
  no conflict, no divergence permitted.
- Single conflict (`docs/texp-001/ROADMAP.md`): resolved textually by
  union — kept s4-side's richer S4 row ("carried to kernel track"),
  dropped both stale "(this branch)" markers, kept s5's S5 row.
- Vendored onto the line (byte-identical, recorded, pending track
  merge): `SOURCES.md` (`fb5a191c…` ex s1, for amendment below),
  `test_validator.py` (`45de957b…`), `test_energy.py` (`7512f928…`).

## K-S3a: FULLY CLOSED (verbatim patch)

Applied exactly the carried spec, nothing more (`git diff` on
`kernel.py` shows only these two hunks): (i) run_chain docstring —
"Budget overrun is caught internally and reported via ``truncated``…"
→ "mid-run overrun sets `truncated`; initial-eval overrun propagates
`BudgetOverrun`…" (fix text verbatim incl. lowercase start and single
backticks; true parenthetical retained); (ii) `from dataclasses
import dataclass, field` → `from dataclasses import dataclass`.
S3 (11) + S4 (9) suites re-run green against the patched kernel.

## K-S4a: CLOSED (relabel in `arms.py` + cumulative note)

"Uniform walk" → "flat-energy kernel walk (proposal-concentrated, NOT
uniform)"; per-segment `budget_used` documented as cumulative
shared-counter reading.

## ℓ3/ℓ4 extension + K-S5a (OPENED)

Two entries added, each labeled
`# STIPULATED (S5-unify: D2 ℓ3/ℓ4 strata need)` — the bound of
"minimal and labeled" (a third entry fails `test_f6_complete`'s
count pin of 10). SOURCES.md amended with matching rows. **Scope
correction (found during verification):** the extension unblocks
VALIDATION at ℓ3/ℓ4, but generator planting logic remains
len-2-specific (single midpoint) — ℓ≥3 planting raises
`PlantingError("unreachable")`, ℓ≥5 raises the table message
(pinned: `test_planting_fails_closed_two_bounds`). Multi-midpoint
planting is an explicit generator follow-on, folded into K-S5a. Rationale:
D2 strata require ℓ∈{2,3,4}; the S1 table capped at 2, making ℓ≥3
unplantable (fail-closed `PlantingError` proved it). **K-S5a (open):**
the two entries are stipulated-minimal; richer typing or longer
sequences need table review; pilot ℓ≥3 strata additionally need B4
scale. Generator needed no change (reads the table dynamically).

## Suite + K-status

Full `experiments/` suite: 73 collected (validator 20 incl. 2 new
table-driven parametrizations, energy 7, kernel 11, arms 9, generator
16, fixtures 10) — all green. K-S3a/K-S4a CLOSED; K-S5a OPENED;
K-S1a (hub presence at scale), K-S1b/K-S2a/b/c (lock/pilot/S4),
production-agreement item carried. No `src/` edits (verified by diff);
no pushes; no TUNE/PILOT execution (micro self-tests only).

## S5b note — multi-midpoint planting (K-S5a CLOSED)

Generator planting generalized: ℓ−1 distinct intermediates sampled per
(a, b) attempt under the unchanged ordinary-degree + endpoint-community
rule (single midpoint was the ℓ=2 special case). This supersedes the
"Generator needed no change" sentence above for *planting* (table
reading was and remains dynamic). Verified: ℓ2/ℓ3/ℓ4 plant green
(distinct vertices, validator-accepted, near-miss tracks planted
prefix); ℓ≥5 still fail-closed via the table message (pinned:
`test_planting_fails_closed_two_bounds` +
`test_planting_multi_midpoint_l3_l4`). Secrecy construction untouched
(same triple/tuple separation; secrecy tests green unmodified).
**K-S5a CLOSED with evidence.** Remaining: pilot ℓ≥3 strata need B4
scale (unchanged); richer typing/longer sequences need table review
(unchanged).
