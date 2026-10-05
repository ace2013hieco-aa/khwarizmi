# TEXP-001 ROADMAP — Annealed Bridge Sampling (GR4)

| Phase | Scope | Status |
|---|---|---|
| P0 | Grounding: sampler/action-evaluator existence, F5 hook, Ix, baselines | DONE (`texp-001/p0@998292b`: `P0-grounding.md`) |
| P0-supplement | Spec-v1.2 grounding: B-disposition, sufficiency re-grade, Case B verdict, stipulated energy + draft signature | DONE (`texp-001/p0@0867c64`: `P0-supplement.md`; B3/B4/B5 BLOCKED, B1/B2 CLOSED, B6 PROPOSED per correction) |
| P1 | Adversarial spec review | DONE (`texp-001/p1@f7d2559`: `P1-spec-review.md`, conditional accept C1–C8) |
| P2 | Twin implementation plan (IDR-042) | DONE (`texp-001/p2@48e4ce9`: `P2-implementation-plan.md`, plan only) |
| S1 | Reference validator + tests + sources + report | DONE (`texp-001/s1`: 18 tests green; sequences stipulated, K1 recorded, K2 seeded) |
| S2 | Reference energy + tests + report | DONE (`texp-001/s2`: 7 tests green; form stipulated minimal, blindness demonstrated, human sign-off deferred to lock) |
| S3 | Shared Metropolis kernel + tests + report | DONE (`texp-001/s3`: 11 tests green; S1/S2 vendored byte-identical pending merge; fixed-T only, schedule is S4's seam) |
| S4 | Arms A0/A1/A2 + tuning harness + tests + report | DONE (`texp-001/s4`: 9 tests green; single-variable pinned, budget-identical, TUNE not executed; K-S3a inventory closed, docstring/import micro-items carried to kernel track) |
| S5 | Generator + fixtures F1–F7 + tests + report | DONE (`texp-001/s5`: 16 tests green; arms vendored byte-identical pending merge; ℓ≥3 fail-closed pending table extension; F2/F7 directional green deferred to pilot) |
| S5-unify | Merge s4+s5 + K-S3a patch + K-S4a relabel + ℓ3/ℓ4 extension + criteria tests | DONE (`texp-001/s5-unify`: 73 tests green; K-S3a/K-S4a CLOSED, K-S5a OPENED; single line, no rebase) |
| S5b | Multi-midpoint planting | DONE (`texp-001/s5b`: ℓ2/ℓ3/ℓ4 plant green, ℓ≥5 fail-closed green; K-S5a CLOSED with evidence) |
| S6 | Analysis + lock tooling + tests + report (this branch) | DONE (`texp-001/s6`: 11 tests green; bootstrap/Wilcoxon/guards/lock all-FILL; ranges+seeds PROPOSED for sign-off, not locked) |
