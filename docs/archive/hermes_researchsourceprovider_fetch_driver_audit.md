# Step 5a — Fetch Driver — Shipped-Code Hostile Audit

**Scope:** protest-stage attack on the SHIPPED `fetch_batch` driver
(`paginate.py`) at the four pinned surfaces the gate-remediated design carries —
**GC-02** (the payload↔`per_source` artifact_id binding), **GC-01** (the `_verdict`
scope-closure guard), **FD-02** (the batch-cap stop), **F6** (the attempt
accounting) — plus the cross-surface candidates the fresh code reading surfaced.
All findings reproduced against the running code with probes (`probe_fetch_audit.py`,
removed after the audit). Verdict **MERGE WITH REMEDIATION**: one P2 + two P3s; the
four pinned surfaces are otherwise verified sound.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| FC-01 | **P2** | `_fetch_one` | `build_fetch_request`/`redact_params` sit INSIDE the transport exception map — an adapter hook raising a transport `ProviderError` is retried as a network transient, burning the attempt budget and masking the adapter bug |
| FC-02 | **P3** | F6/`fetch_batch` | The cap-hit log entry is the only one where `attempts != len(attempt_verdicts)` — the acquire denial is never recorded, unlike the walk's `hazard_verdicts` discipline |
| FC-03 | **P3** | FD-02/`_fetch_one` | An UNKNOWN limiter denial reason is treated as retryable admission-wait — a future policy reason burns the retry budget and surfaces as a generic `THROTTLED` instead of failing loudly |

## Detail

### FC-01 (P2) — the adapter/redaction phase sits inside the transport exception map

`_fetch_one` wraps `build_fetch_request` + `redact_params` + `transport.request` in
ONE try whose handlers are the transport map (`TransientProviderError` → backoff +
retry, `PermanentProviderError` → typed failure). An ADAPTER bug that raises a
transport-class `ProviderError` from `build_fetch_request` is therefore
indistinguishable from a network failure. **Reproduced:** an adapter raising
`TransientProviderError(hazard_class="TIMEOUT")` from the hook → the driver retried
3 times (`attempt_verdicts = ("TIMEOUT", "TIMEOUT", "TIMEOUT")`) and surfaced
`FetchFailure(TIMEOUT, "transient failures exhausted after 3 attempts")` — the
adapter bug masked as network degradation, the retry budget burned.

The walk's audited precedent builds + redacts OUTSIDE `_fetch_page` (the request is a
parameter); only `transport.request` sits in the exception map. The fetch driver
deviates. A `RedactionError` (plain `ProviderError`) is caught by the loud re-raise
today, so the shipped adapters are safe — but a future adapter whose hook raises a
transport class reopens the misclassification. **Fix:** move `build_fetch_request` +
`redact_params` out of the transport map (loud propagation), keeping the
acquire→release pairing (a hook error between acquire and release still releases).

### FC-02 (P3) — the cap-hit entry breaks the attempts↔verdicts reconstruction invariant

Every other entry type satisfies `attempts == len(attempt_verdicts)` (a FETCHED
entry from a 2-attempt source: `attempts=2, ("TIMEOUT", "NONE")`; an exhausted
entry: `attempts=3, ("TIMEOUT",) * 3`; a permanent entry: `attempts=1, ("MALFORMED_200",)`).
The cap-hit entry does not: **reproduced** — a first-attempt `daily_cap_exhausted`
denial produces `attempts=1, attempt_verdicts=()` (the denial is never recorded).
The walk's `hazard_verdicts` records `"THROTTLED"` for a cap-denied page
(`_fetch_page` returns `THROTTLED` + the denial reason); the fetch driver's
admission-wait branch DOES append `"THROTTLED"`, but the cap branch returns before
appending. A consumer reconstructing "attempt 1 → ?" from the cap entry cannot tell
what attempt 1 was (the `reason="daily_cap_exhausted"` disambiguates only if read).
**Fix:** append `"THROTTLED"` to `attempt_verdicts` before the CAP return (or
document the asymmetry).

### FC-03 (P3) — unknown limiter denial reasons are retried as admission-wait

`_fetch_one`'s denial branch checks `reason == "daily_cap_exhausted"` (CAP stop) and
treats EVERYTHING ELSE as retryable admission-wait contention. The limiter contract
today has exactly two reasons (RL-01), so the shipped code is correct — but an
unknown/future policy reason (e.g., `"policy_denied"`, `"budget_exhausted"`) would
silently inherit the retryable branch. **Reproduced:** a limiter denying every
attempt with `"policy_denied"` → the driver backed off and retried all 3 attempts,
then surfaced `FetchFailure(THROTTLED, "transient failures exhausted after 3
attempts")` — a hard policy stop masked as transient contention, the AR-02 class.
**Fix (the stricter option):** reject an unknown denial reason loudly
(`ProviderValidationError` — a limiter/driver contract violation), or map it
explicitly; never default an unknown reason into the retryable branch.

## What survives — verified against the running code, not assumed

- **GC-01 (P1 probe):** a SEARCH marker declaring `failure_class="NO_FULL_TEXT"`
  (legal in `_MARKER_CLASSES` — result classes are allowed marker targets) is now
  **rejected at SEARCH scope with `SpecValidationError`** by the `_verdict` guard —
  the guard's concrete value: before GC-01, `_fetch_page` would have treated that
  page as a NORMAL page (`NO_FULL_TEXT` ∉ its retry/permanent sets → falls to
  parse). No return path escapes (all 22 `_v` sites thread the scope).
- **GC-02 (P4 probe):** a mixed batch (FETCHED + NO_FULL_TEXT + FAIL) → exactly one
  payload per `FetchedSource`, `payloads[i].artifact.artifact_id ==
  per_source[i].artifact.artifact_id` (aligned=True) — the driver builds the
  artifact once and shares it between the semantic record and the carrier; the
  driver-side assert + the fixture pin the binding.
- **FD-02 (P5 probe):** a 5-source batch with the cap exhausting at source 2 →
  fetched=2, 3 marked `FetchFailure(THROTTLED, daily_cap_exhausted)` (never
  fetched, never dropped), the outcome note `"daily cap exhausted at source 2 of 5"`,
  transport called exactly 2×, zero payloads for the marked sources, and the
  never-attempted entries carry `attempts=0, attempt_verdicts=()`.
- **F6 (retry/exhaustion/permanent/success paths):** `attempts ==
  len(attempt_verdicts)` on every path except the FC-02 corner; the exhausted
  failure's reason is the generic driver message (never the transport exception
  text — F12 holds even under repeated wrapping).

## Interaction with prior gates

| Prior surface | Status after this audit |
|---|---|
| GC-02 binding | Holds (P4); the assert + fixtures are the pin |
| GC-01 closure | Holds AND has demonstrable value (P1 — the search-marker `NO_FULL_TEXT` escape is now rejected, where the walk previously mis-handled it) |
| FD-02 stop | Holds (P5); FC-03 is the unknown-reason corner of the same mechanism |
| F6 accounting | Holds except the cap-hit asymmetry (FC-02) |
| F8 (`fetch: null`) | Unaffected — not re-attacked here |

## Overall verdict

**MERGE WITH REMEDIATION.** The four pinned surfaces survive their hostile pass
(GC-01, GC-02, FD-02 verified; F6 holds except one corner). The three findings are
edge-condition fixes, not design rework: FC-01 restores the walk's loud-adapter-error
discipline, FC-02 restores the attempts↔verdicts reconstruction invariant, FC-03
fail-closes unknown limiter reasons. All three are P2/P3 — no P1, no gate-blocking —
but the fold-in (with a regression fixture per probe) is the standing condition
before the step-5a commit gate.

## Disposition — FOLDED IN (2026-08-14)

| ID | Decision | Where it landed | Regression fixture |
|---|---|---|---|
| FC-01 | **FIXED** — `build_fetch_request` + `redact_params` moved OUT of the transport exception map in `_fetch_one`; only `transport.request` sits in the map (the walk's audited precedent). A hook `ProviderError` propagates loudly through the outer `finally` (the acquire→release pairing preserved — the slot is released before the raise escapes). | `paginate.py` `_fetch_one` | `test_fc01_adapter_hook_transport_error_propagates_loudly_never_retries` (loud on the first attempt, acquire/release balanced, transport never called) + `test_fc01_transport_transient_still_retries_positive_control` (the map is intact for the transport itself — a genuine transient still retries) |
| FC-02 | **FIXED** — `"THROTTLED"` appended to `attempt_verdicts` before the CAP return; the cap-hit entry now satisfies `attempts == len(attempt_verdicts)` like every other path. | `paginate.py` `_fetch_one` denial branch | `test_fc02_cap_hit_entry_satisfies_attempts_verdicts_invariant` (`attempts=1, attempt_verdicts=("THROTTLED",)`, transport never called) |
| FC-03 | **FIXED** — an UNKNOWN denial reason (anything other than `daily_cap_exhausted`/`admission_wait_expired`, the limiter contract's exact two) raises `ProviderValidationError` loudly; the retryable branch is unreachable for unknown reasons. | `paginate.py` `_fetch_one` denial branch | `test_fc03_unknown_limiter_denial_reason_fails_loudly` (`policy_denied` → `ProviderValidationError`, transport never called) |

All three probes re-verified against the folded code via the fixtures above; the
positive control proves the transport map was narrowed, not removed. Suite:
**837 passed (833 baseline + 4 regression fixtures), `uvx pyright src` 0 errors.**
The step-5a commit gate is now clear.

---

**Probe evidence:** `probe_fetch_audit.py` — P1–P6 against the running driver +
evaluator; removed after the audit per house convention.
