# Operator-Loop Independent-Review P2 Residuals — Governance Record

**Recorded:** 2026-08-15
**Source:** Independent operator-loop verdict (46/46 live probes, no P0/P1)
**Status:** 3 of 4 residuals REMEDIATED; 1 DOCUMENTED + TESTED (accepted design)

## Context

The independent review of the shipped operator loop found no P0/P1 defects
and recommended tracking four P2 hardening residuals. This record tracks
them to closure. It supersedes the ad-hoc status spread across commit
messages and test banners.

> Attribution note: the verdict is labeled "HEAD 58104b4", but its sharp
> probe describes `_refresh_liveness` (F15), which landed at `62a9a9d`
> AFTER `58104b4`. The findings therefore describe the post-F15 operator
> loop — the loop that exists today — and each remediation is verified
> against the current code, not the labeled HEAD.

## Status map

| # | Finding | Status | Remediation | Verified by |
|---|---------|--------|-------------|-------------|
| P2 #1 | `--token` on argv; unsalted SHA-256 token hash; no minimum token length at register | **REMEDIATED** | `e53632f` — salted PBKDF2-HMAC-SHA256 (210k iterations, fresh 128-bit random salt per credential, self-describing stored value `pbkdf2$sha256$<iter>$<salt>$<hash>`); minimum token length 8 enforced at register; legacy bare-hex rows still verify | `test_12_salted_token_hash_format_and_legacy_fallback`, `test_12_register_operator_bootstrap_and_refusal` (min-length refusal + idempotency) |
| P2 #2 | `resolve_human_gate` APPROVED = 4 separate commits; a crash between them leaves a stale `GatePassed` on the journal | **REMEDIATED** | `9eb09fd` — the entire verdict (WAITING_HUMAN→RUNNING→SUCCEEDED/FAILED, GatePassed/GateFailed, HumanGateResolved, both TaskStatusChanged events) lands in ONE fenced transaction; commit or roll back together | `test_11_resolve_verdict_lands_in_one_transaction` (crash-injection: zero rows land, gate stays resolvable) |
| P2 #3 | REJECTED routes through RUNNING; a dep INVALIDATED after parking makes both verdicts refuse → permanent park, no escape | **REMEDIATED** | `9eb09fd` — the terminal operator verdict is the escape hatch (F-10 remains a claim-time guard at each task's own dispatch); `d5df6ba` — diagnostic note surfaces WHY the gate is parked (INVALIDATED dep) on the tick channel and at the verdict surface | `test_11_escape_hatch_invalidated_dep_after_parking_still_resolvable` (APPROVED + REJECTED), `test_11_parked_gate_invalidated_dep_diagnostic_note` |
| P2 #4 | Protection window capped at `heartbeat_refresh_horizon` = 300s; refresher exits permanently on any exception — a >5-min handler is discard-and-re-execute territory | **DOCUMENTED + TESTED** (accepted design, not a bug) | `d5df6ba` — the cliff is explicit at the constant, the refresher class, and the run-with-refresh docstring; the discard side is regression-tested | `test_15_f15_horizon_cliff_late_handler_discarded` — B recovers + re-executes (attempt 2, one output); A's late-returning handler is discarded by the IDR29-02 binding guard with no second claim/output |

## Remaining accepted exposure (by design)

- **`--token` on argv** remains the only CLI credential transport; on a
  shared host the process list could expose a token. Accepted for a
  single-operator lab tool and documented in the CLI help. A future
  hardening could accept the token via environment variable or prompt, or
  move to short-lived challenges.
- **`hermes run` returns 0 with "0 dispatched" on an empty wave** — fine,
  but scripters must read the summary line.

## Verification summary

- 1313 tests pass; pyright 0 errors; ruff clean (C3 gate).
- Every remediation is exercised by a regression test that attacks the
  exact failure mode, not by a report.
- Follow-up audit F1 (silent mode-transition failure) was found while
  closing out this record — see `hermes_redteam_operator_loop_audit.md`.
