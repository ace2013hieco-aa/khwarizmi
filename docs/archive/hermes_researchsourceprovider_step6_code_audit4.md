# ResearchSourceProvider — Step 6 Code Audit 4 (S6-D1…D4)

**Date:** 2026-08-14 · **Auditor:** independent hostile pass (no role in the
step-6 implementation) · **HEAD at audit start:** `06dc7b6` · **Scope:** the
S6-C2 task-scoped write view — dispatch-seam wrapping, recovery
re-execution interplay, read-surface passthrough, and the reach-in surface.

## Verdict

**CLEAN — one P3 hardened in place (D4).** The task-scoped write view holds
under hostile probing: recovery re-execution records under its own task, the
foreign-citation refusal is airtight through the controller's dispatch seam,
and the read surfaces pass through unchanged. The single residual surface is
the classic Python-no-privacy reach-in (a handler reaching into private
attributes for an unscoped write); that path was cheaply removed by no
longer retaining the raw bundle.

## Findings

| ID | Sev | Finding | Probe | Disposition |
|---|---|---|---|---|
| S6-D1 | — | Recovery re-execution records under ITS OWN task through the scoped seam (stale task → NO_SIGNAL → requeue → handler re-runs → rows under own task) | live controller run, 8 ticks | **PASS** — no change |
| S6-D2 | — | The view refuses a foreign task citation and passes the own-task record | live | **PASS** — no change |
| S6-D3 | — | Read passthrough (`dereference_ref`, `load_search_results`) is intact and project-edge-scoped | live | **PASS** — no change |
| S6-D4 | P3 | The scoped view retained `_repos` (the raw `SourceRepos` bundle) as a plain attribute — `ctx.repos._repos.source.record("p1", "foreign", …)` was an *accidental* reach-in that re-opened the C2 cross-task hole | live reach-in | **HARDENED** — the view no longer retains the bundle at all; the accidental path now raises `AttributeError` (fail loud). Deliberate introspection of bound-method internals remains the documented HD-02 fail-loud boundary (programmer-error class, indistinguishable from writing raw SQL) |

## Fold-in (minimal, architecture-preserving)

- `TaskScopedSourceRepos` (in `src/hermes/research/source_handlers.py`) now
  binds only the three surface methods (`_record_scoped` partial with the
  task forced, `repos.dereference`, `repos.load_search_results`) and retains
  **no reference to the raw bundle**. `record()` is reachable solely with
  the forced task id; there is no `_repos` attribute to reach into.
- Regression fixture `test_ctx_repos_no_raw_bundle_reach_in` proves the
  accidental reach-in raises `AttributeError` while the legitimate scoped
  surface (record / dereference / load) still works end-to-end.

## Verification

- Probe suite: **D1–D4 all PASS** (fail-loud reach-in confirmed).
- Orchestration suite: **33 passed** (32 + 1 new fixture).
- Full suite: **881 passed** (880 + 1), 0 failed, 0 errors.
- Pyright (`npx pyright src`): **0 errors, 0 warnings**.

## Status

The task-scoped write view is now hardened against both the accidental
cross-task citation (S6-C2) and the accidental escape hatch (S6-D4). Step 6
remains **IMPLEMENTED — TESTED**, **NOT RATIFIED-AS-IMPLEMENTED**; the §26 Ix
structural comparison (clean at `06dc7b6`, re-verified) and the external
closure gate remain the standing conditions.
