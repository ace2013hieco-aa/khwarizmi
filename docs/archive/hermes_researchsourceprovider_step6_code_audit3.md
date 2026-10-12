# ResearchSourceProvider — Step 6 Third-Gate Hostile Code Audit
## S6-B folded surfaces + the provider-agreement rule × EMPTY outcomes

**Scope:** attack ONLY the S6-B folded surfaces (provider-less refusal,
structural completion check, required resolver type) plus the
provider-agreement rule's interaction with EMPTY outcomes — for the same
bypass and silent-failure classes.
**HEAD:** `dd33a48` + the uncommitted S6-C fold-in.
**Method:** source inspection + live probes against real SQLite through the
shipped drivers.
**Verdict:** **MERGE WITH REMEDIATION (third round)** — 1 P2 (the cross-task
citation, confirmed and structurally closed), 3 PASS pins on the folded
surfaces. No architecture violations.

## Findings

| ID | Sev | Surface | Finding | Probe result |
|---|---|---|---|---|
| S6-C1 | — | provider agreement × EMPTY | PASS pin — the rule handles EMPTY correctly: an EMPTY outcome with a matching log records (typed); a mismatched log is refused; an EMPTY outcome with NO log is refused (fail-closed, no provider evidence). | all three PASS |
| S6-C2 | **P2** | handler write surface | A handler could cite a DIFFERENT RUNNING source task (a crashed worker whose heartbeat is still within the lease window) — the A2-01/02 checks verify template/project/RUNNING, but nothing tied the outcome to the task the controller actually DISPATCHED. Reproduced: rows landed under the foreign task (fresh-heartbeat crash window). The scoping must live at the DISPATCH seam — a factory-built `SourceHandler` wrapper alone is bypassable by any custom handler object (its own `build_context`). | `U-rows=2` landed → blocked |
| S6-C3 | — | structural completion check | PASS pin — the S6-B2 check is type-specific and per-task; a cross-task handler cannot SUCCEED with zero rows of its own. | PASS |
| S6-C4 | — | required resolver type | PASS pin — all three call sites pass the type; the prefix parsing rejects odd forms. | PASS |

## Fold-in (S6-C2, minimal + structural)

The controller's dispatch seam now wraps the per-tick bundle in a
**`TaskScopedSourceRepos`** view per dispatched task: `record()` FORCES the
cited `task_id` to the dispatched task (any other citation raises
`SourceOutcomeBindingError`). The scoping lives in `Controller._run_handler`
(not the factory), so EVERY handler — factory-built or custom — receives the
scoped surface. The per-tick `SourceRepos` bundle itself is unchanged (the
controller's own structural checks still use it); the read surface
(`dereference`/`load_search_results`) passes through. No new authority, no
schema/event/migration change. A cross-task citation now exhausts the retry
policy to a FAILED terminal, never a misbind.

## Regression fixtures (3, in `tests/test_provider_orchestration.py`)

- `test_emtp_outcome_provider_agreement_matrix` — the C1 matrix (matching-log
  EMPTY records; mismatched-log refused; no-log refused).
- `test_outcome_cannot_bind_to_foreign_task` — end-to-end: a handler citing a
  foreign RUNNING task is refused (zero rows under the foreign task), the
  dispatcher task exhausts to FAILED, the foreign task stays RUNNING.
- `test_ctx_repos_task_scoped_view` — the view refuses a foreign task_id
  outright and passes the matching one through.

## Verification

- Full suite: **880 passed** (877 + 3), 0 failed, 0 errors
- Targeted orchestration suite: 32 passed
- Pyright (`npx pyright src`): **0 errors**
- Live probes re-ran: C1 matrix PASS; the cross-task write FAIL → blocked;
  recovery interplay (U's own crash-recovery re-execution) verified as
  legitimate — the scoped view allows a task's OWN record, refuses foreign
  citations.

## Remaining risks (standing, unchanged)

- The external closure gate remains the standing condition; step 7 untouched.
- The cross-task citation is now structurally impossible from the handler
  surface (the only write surface is the scoped view); the controller's own
  code paths (EXTRACT, gates) are controller-owned and out of the handler
  threat model.
