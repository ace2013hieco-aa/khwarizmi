# ResearchSourceProvider — Step 6 Second-Gate Hostile Code Audit
## S6-fixed surfaces only (typed resolver, provider agreement, HandlerResult contract, edge-based fetch input)

**Scope:** attack ONLY the surfaces folded in by the S6-A1…A5 audit — the typed
resolver (`_source_artifact_resolves`), the provider-agreement rule, the
HandlerResult return contract (+ the new completion check), and the edge-based
`load_search_results` — for the same bypass and silent-failure classes.
**HEAD:** `44cced5` (step-6 package, S6 fold-in) + the uncommitted S6-B fold-in.
**Method:** source inspection + three live probes against real SQLite through
the shipped drivers.
**Verdict:** **MERGE WITH REMEDIATION (second round)** — 2 P2s, 1 P3 pin, all
confirmed by reproduction, all folded in. No architecture violations.

## Findings

| ID | Sev | Surface | Finding | Probe result |
|---|---|---|---|---|
| S6-B1 | **P2** | provider agreement | `result_providers.discard(None)` SILENTLY dropped results that declare no provider — a provider-less result passed the agreement check when the rest agreed, and was recorded under a provider-bound task. Every delivered result's semantic identity REQUIRES its provider. | `RECORDED` → refused (`declares no provider`) |
| S6-B2 | **P2** | HandlerResult contract | A handler returning `HandlerResult(status="completed")` WITHOUT recording anything made the controller SUCCEED the task — completion was the handler's word, no structural verification (the EXTRACT precedent verifies rows before SUCCEEDED). | `status=SUCCEEDED` → `FAILED` |
| S6-B3 | **P3** | typed resolver | `_source_artifact_resolves(..., artifact_type="")` had an UNFILTERED default — dead in all shipping call sites, but a latent footgun (a future caller omitting the type would bypass the S6-A1 filter). | `untyped=True` → TypeError (required) |

**What survives (probed, not assumed):** the typed resolver holds (payload
hash cited as `source_result` refuses; cross-type refs never resolve), the
agreement rule holds for the mix case and the single-contradiction case, the
edge-based `load_search_results` agrees with `dereference_ref` on reused
(cross-project) rows, and the completed-branch structural check passes for
the honest handlers (end-to-end fixtures green).

## Fold-in (minimal)

1. **S6-B1** — the search binding now REFUSES any per-provider result whose
   `provider` is `None` (`declares no provider`, S6-B1) instead of dropping it
   from the agreement set.
2. **S6-B2** — `_run_handler`'s completed branch STRUCTURALLY verifies the
   task's outcome rows exist (`artifacts WHERE task_id … source_search /
   source_fetch_outcome`) before SUCCEEDED; a zero-row "success" is FAILED
   loudly. The shipped handlers now set `outcome_recorded=True` honestly; the
   controller does not trust it.
3. **S6-B3** — `artifact_type` is a REQUIRED parameter of
   `_source_artifact_resolves` (no unfiltered default); all three call sites
   (dereference_ref, the repositories resolver, the gateway admission) pass
   it.

## Regression fixtures (3, in `tests/test_provider_orchestration.py`)

- `test_none_provider_result_refused_at_binding` — a provider-less result is
  refused; zero artifacts land.
- `test_completed_handler_must_have_recorded_outcome` — a completed-claiming
  handler with no output FAILS the task; nothing lands.
- `test_resolver_type_required_no_unfiltered_bypass` — omitting the type is a
  TypeError; the typed call still refuses the payload-as-source_result.

## Verification

- Full suite: **877 passed** (874 + 3), 0 failed, 0 errors
- Targeted orchestration suite: 29 passed
- Pyright (`npx pyright src`): **0 errors**
- Live probes re-run: B1/B2 FAIL → PASS; B3 confirmed by TypeError

## Remaining risks (standing, unchanged)

- §26 Ix structural comparison: **CLEAN** (`docs/ix/step6_structural_comparison_20260814.md` —
  zero new write paths, zero cycles, single handler→repository boundary).
- The external closure gate remains the standing condition; step 7 untouched.
