# ResearchSourceProvider — External Independent Closure-Gate Package

**Assembled:** 2026-08-14 · **Pinned HEAD:** `55c35c2` · **Slice status:**
steps 1–6 of 7 **IMPLEMENTED + TESTED**; **NOT RATIFIED-AS-IMPLEMENTED**.
This package certifies the provider slice AT ITS EXACT HISTORICAL HEAD
`55c35c2` — NOT at any later commit (see §A1 scope pinning).

This package is the single entry point for the **external independent
closure gate** (the standing condition of §27 item 43). It assembles the
evidence bundle, the status matrix, the verification commands, and the
gate-reviewer prompt. Nothing here substitutes for the gate itself; all
RATIFIED / EXTERNALLY VERIFIED claims are **UNCLAIMED** until the external
verifier has run and recorded its own verdict.

---

## A. Gate identity and standing conditions

| Condition | State |
|---|---|
| Slice implementation | steps 1–6 of 7 IMPLEMENTED + TESTED (step 7 record/replay acceptance NOT STARTED) |
| Step-6 final independent review | **READY FOR STEP 7** (`hermes_researchsourceprovider_step6_final_review.md`) |
| External independent closure gate (§27 item 43) | **STANDING — this package is its input, not its verdict** |
| Step 6 RATIFIED-as-implemented | **UNCLAIMED** |
| Slice EXTERNALLY VERIFIED | **UNCLAIMED** |
| Evidence status terms | every claim below is IMPLEMENTED / TESTED / DEFERRED — never RATIFIED |

### A1. Scope pinning (post-`55c35c2` commits are OUTSIDE this certification)

The repository has moved beyond `55c35c2`:

- `2d6d851` — Closure-gate package + store-dedup audit.
- `d7931ec` — Q-05 surviving-ideas stage (failure classification ratified,
  persisted, consumed; IDR-036/037; Q-02 design gate).

**A verification recorded at `55c35c2` is NOT a verification of `d7931ec`
(or later).** The external gate, when it runs against this package, certifies
the ResearchSourceProvider Part-3 slice (steps 1–6 of 7) at `55c35c2` only.
The Q-05/Q-02 changes (new modules `src/hermes/research/failure_classification.py`,
`src/hermes/persistence/failure_classifications.py`, their tests, and the
IDR-036/037 records) are OUTSIDE this package's certification scope: they do
not touch the provider slice's sources, but their presence means the tree at
`d7931ec` is a different tree that no verdict from this package covers.

If the gate is rerun at a new HEAD, a NEW closure-gate package must be created
pinned to that HEAD (with the provider-slice attack battery re-run verbatim
against the new tree) — the old record is never upgraded retroactively.

## B. The gate-reviewer prompt (verbatim)

> # HERMES RESEARCH — RESEARCHSOURCEPROVIDER SLICE — EXTERNAL INDEPENDENT CLOSURE GATE
> ## Audit the ResearchSourceProvider Part-3 slice (steps 1–6 of 7) at HEAD 55c35c2
>
> ### ROLE
> You are the **independent external verifier** for the ResearchSourceProvider
> slice of Hermes Research.
> You have had NO role in: designing the slice; implementing steps 1–6;
> remediating R01–R04; writing the step-6 audits or the final review;
> approving any prior review.
> You must independently audit the repository at HEAD `55c35c2`.
>
> Your task is NOT to improve the code.
> Your task is to determine whether the current HEAD is trustworthy enough
> to move the slice from **IMPLEMENTED — TESTED** to **EXTERNALLY VERIFIED**,
> and to rule on step-6 RATIFIED-as-implemented.
>
> Do not trust previous reports. Do not trust previous test counts. Do not
> trust the implementation agent's conclusions.
> Use the repository, the current architecture, fresh runtime evidence,
> source inspection, and adversarial tests.
>
> ### Evidence bundle (for orientation only — verify, do not trust)
> - `hermes_researchsourceprovider_implementation_design.md` (blueprint)
> - `hermes_researchsourceprovider_closure_gate_package.md` (this package)
> - `docs/idr/step6_closure_candidate_evidence_map.md`
> - `docs/idr/IDR-030.md` (provider allowlist / §27 item 55 ratification)
> - `docs/idr/IDR-032.md` (step-6 implementation + S6 audits A–D)
> - `docs/idr/IDR-033.md` (P1/C1 remediation)
> - `docs/idr/IDR-034.md` (S6-R01…R04 remediation)
> - `docs/idr/IDR-035.md` (R01 resolver audit + final review)
> - `hermes_researchsourceprovider_step6_remediation_report.md` (R01–R04)
> - `hermes_researchsourceprovider_step6_final_review.md` (final review)
> - audit records: `*_step6_code_audit.md`, `*_step6_code_audit2/3/4.md`,
>   `*_step6_r01_resolver_audit.md`
> - Ix archives: `docs/ix/*_20260814_step6.txt`, `*_r01remediation.txt`,
>   `step6_structural_comparison_20260814.md`
>
> ### Mandatory fresh runtime evidence (record, do not cite prior counts)
> 1. `git status --short`, `git log --oneline -5`, `git rev-parse HEAD`.
> 2. Full suite: `.venv/Scripts/python.exe scripts/run_tests.py -v` —
>    record collected/passed/failed/errors/exit/runtime.
> 3. Pyright: `npx pyright src` — record errors/warnings.
> 4. Targeted slice suite: `tests/test_provider_orchestration.py` (+ the
>    provider unit files: research_sources, hazards, walk, ratelimit, fetch).
> 5. `ix map` + `ix smells` — diff vs the archived baselines; confirm zero
>    new write paths, zero cycles, single handler→repository boundary.
>
> ### Minimum attack battery (fresh probes against the CURRENT HEAD)
> - R01: cross-project lineage (direct and shared-artifact), forged
>   search_task_id, non-dependency citation, direct-repository bypass,
>   refs-ownership (refs from a different same-project search), execution
>   scope (partial refs).
> - R02: same-hash/different-type reuse in BOTH directions (result↔payload)
>   and against outcome/unrelated types; same-type idempotent reuse.
> - R03: over-bound / malformed bounds rejected at admission; persisted spec
>   authoritative at execution; no silent default substitution.
> - R04: absent/unknown/non-string provider rejected; fetch/search provider
>   mismatch rejected at the write path.
> - Cross-cutting: task-scoped write view (no cross-task citation), no
>   evidence/gate/task mutation through outcomes, crash-recovery idempotency.
>
> ### Verdict
> Conclude exactly one of: **EXTERNALLY VERIFIED** / **REMEDIATION REQUIRED**,
> each with the evidence you yourself ran. Record your verdict and model_ref
> (the §14.4 provider-diversity rule — the verifier must record which model
> family produced the judgment) in `docs/idr/` as the closure record.

## C. Evidence bundle index (all records, with verdicts)

| Record | Date | Verdict / content |
|---|---|---|
| Blueprint `hermes_researchsourceprovider_implementation_design.md` | 2026-08-13/14 | 7-step Part-3 design; PS/PS2/PS3, HZ/HZ2/FS, WS, RT/RT2/RT3, SD/OB/HD folds |
| §27 item 55 ratification (`IDR-030`) | 2026-08-14 | allowlist + reconciliation + redaction + rate defaults + estimate-total RULED |
| Step 6 design gates (`*_design_audit*.md`, `*_design_remediation.md`) | 2026-08-14 | SD-01…05, SD2-01…05, OB/HD — all folded; ACCEPTED FOR IMPLEMENTATION |
| Step 6 implementation (`IDR-032`) | 2026-08-14 | source_templates/handlers/source_outcomes + controller/gateway wiring, 21 fixtures, 869 → 877 → 880 → 881 |
| Code audits S6-A/B/C/D (`*_step6_code_audit*.md`) | 2026-08-14 | 3 P1 / 2 P2 / 2 P3 + 2 P2 + 1 P2 + 1 P3 — all folded; no-escape reach-in |
| P1/C1 remediation (`IDR-033`) | 2026-08-14 | same-project lineage at both surfaces; provider required |
| S6-R01…R04 remediation (`IDR-034` + report) | 2026-08-14 | lineage dependency/refs-ownership, artifact-type reuse, bounds contract, provider agreement — 6 fixtures, 890 |
| R01 resolver audit + final review (`IDR-035`) | 2026-08-14 | B3 partial-refs scope fold; payload-write type guard; **20/20 probes; READY FOR STEP 7**; 892 |
| Store dedup audit (`hermes_researchsourceprovider_store_dedup_audit.md`) | 2026-08-14 | type-blind dedup confined to the source slice; both write surfaces guarded — NO gap elsewhere |
| Ix structural comparisons | 2026-08-14 | CLEAN at each gate (153 → 161, all documented orphan-class deltas) |
| Closure-candidate evidence map (`docs/idr/step6_closure_candidate_evidence_map.md`) | 2026-08-14 | capability → implementation → evidence, statuses labeled |

## D. Status matrix (labels exact)

| Capability | Status |
|---|---|
| Steps 1–6 of 7 (port types, normalize/redact, hazards + 4 specs, walk driver, ratelimit/http, fetch driver, task-side orchestration) | **IMPLEMENTED + TESTED** |
| Step 7 of 7 (record/replay acceptance run) | **DEFERRED** (next action) |
| Step 6 RATIFIED-as-implemented | **DEFERRED** to the external gate |
| Slice EXTERNALLY VERIFIED | **DEFERRED** to the external gate |
| Provider allowlist / slice design (§27 item 55) | RATIFIED (`IDR-030`) |

## E. Verification commands + expected baselines (as of the pinned HEAD 55c35c2)

| Command | Expected |
|---|---|
| `.venv/Scripts/python.exe scripts/run_tests.py` | **892 passed**, 0 failed, 0 errors |
| `npx pyright src` | **0 errors, 0 warnings** |
| `pytest tests/test_provider_orchestration.py` | **44 passed** |
| `ix map .` + `ix smells` | deltas only in the documented orphan class; zero new write paths/cycles |

## F. Explicit non-claims

- **NOT** RATIFIED-as-implemented (step 6).
- **NOT** EXTERNALLY VERIFIED (slice).
- **NOT** implemented: step 7; any ResearchSourceProvider capability beyond
  the current phase; any future Hermes phase the slice roadmap defers.
- The external verifier's own verdict, evidence, and `model_ref` are the only
  inputs that can change the status matrix above.
