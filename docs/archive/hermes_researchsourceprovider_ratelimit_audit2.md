# Adversarial Review — Step-4 limiter/transport, second gate (post-TR fold-in)

**Scope:** hostile attack on ONLY the three surfaces the TR fold-in fixed — (1) the read-phase exception class map (`http.py`, TR-01), (2) the wait-loop daily-cap re-check (`ratelimit.py`, CAP-01), (3) the atomic `(bool, str)` acquire (`ratelimit.py`/`paginate.py`, RL-01) — for the same bypass/silent-failure classes the first four gates found, INCLUDING the downstream consumers of the fixed surfaces (the verdict path a fixed surface feeds). Method: fresh re-read of the folded code, then every finding reproduced against the running code with a probe (`probe_ratelimit2.py` — Q1/Q2/Q3). The TR dispositions were treated as settled only where the folded code actually enforces them.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| RT4-02 | **P2** | TR-01 surface → the walk's `searched` flag | **A TIMEOUT exhaustion counts as "searched" — a provider that never returned a classified response concludes `EMPTY` ("search ran and found nothing"), the PS-13 class.** The TR-01 read-phase map now emits `TIMEOUT` transient into the walk; after the bounded retries, `_fetch_page` returns `("TIMEOUT", "TIMEOUT")` and `walk()`'s `searched` flag excludes only `("THROTTLED", "TRANSIENT")` — so the timeout-exhausted page marks the provider SEARCHED, the zero-delivery single-provider aggregate is `EMPTY`, and `combine` raises `RetrievalShortfallError(aggregate="EMPTY")`. Reproduced: a transport that raises `TransientProviderError(TIMEOUT)` every attempt → walk aggregate `EMPTY`, `combine` raises `EMPTY` — "no literature exists" concluded from "the provider timed out" |
| RT4-01 | **P3** | CAP-01 surface | **The loop cap re-check never re-runs the UTC day-window reset — a waiter queued across the UTC midnight boundary is denied (or its grant is counted) against the STALE day.** The reset (`_cap_day`/`_cap_used`) runs only at the top of `acquire`; the CAP-01 re-check reads yesterday's count. Reproduced: cap=2, A grants (day 1), B and C queue past the top check, MIDNIGHT passes while they wait, A releases → B grants (day-1 count → 2), C's re-check denies `daily_cap_exhausted` — on the fresh day-2 window that should have granted C |

## Detail

**RT4-02 — The read-phase map's `TIMEOUT` verdict feeds a `searched` flag that mislabels exhaustion as "found nothing". (P2)**

TR-01's promise: mid-body failures → `TransientProviderError(TIMEOUT)`, retryable per §6.3. The downstream consumer: `_fetch_page`'s exhaustion return `(None, "TIMEOUT", "TIMEOUT")` → `walk()`'s WS-07 flag — `searched = failure_class is None or failure_class not in ("THROTTLED", "TRANSIENT")`. `TIMEOUT` is NOT in the exclusion set, so a provider whose every attempt timed out (the evaluator NEVER ran — no page was ever classified) is marked **searched**. The zero-delivery matrix then reads `EMPTY` ("searched, found nothing") at the single-provider level, and `combine` raises `RetrievalShortfallError(aggregate="EMPTY")` — the exact conclusion PS-13 forbids ("no literature exists" must never be derived from "providers were down"). The TR-01 fix was correct at the transport; it routed more traffic into a walk flag that mislabels the class it emits.

Reproduced (Q2): `TimeoutTransport` (raises `TransientProviderError(hazard_class="TIMEOUT")` on every attempt) → walk aggregate `'EMPTY'`, notes `[SHORTFALL(cause=TIMEOUT)]` → `combine` **raises `RetrievalShortfallError(aggregate='EMPTY')`**.

**Fix:** a transport failure never CLASSIFIED a response — add `TIMEOUT` to the not-searched set: `searched = failure_class is None or failure_class not in ("THROTTLED", "TRANSIENT", "TIMEOUT")`. A first-page timeout exhaustion then aggregates `UNAVAILABLE` (could not search — `ProviderUnavailableError`, the PS-13-correct side), while a MID-walk timeout keeps `SHORTFALL(cause=TIMEOUT)` + retained records (`PARTIAL` — the searched flag only shapes the zero-delivery case; WS-04 is untouched). Regression fixtures: a timeout-exhausted first page → `UNAVAILABLE` (never `EMPTY`); a mid-walk timeout → `PARTIAL` with the retained records.

**RT4-01 — The CAP-01 re-check reads a stale day's count across the UTC midnight rollover. (P3)**

CAP-01's fix re-checks `self._cap_used[provider] >= prof.daily_cap` inside the wait loop — correct for the overrun class it closed — but the WINDOW reset (`if self._cap_day.get(provider) != day: reset`) still runs only at the TOP of `acquire`. A waiter that queued before midnight holds the old day's `_cap_day`, and every loop iteration compares against the old window: either its grant increments yesterday's count (the new day under-counts one request) or — the worse leg — the re-check denies it `daily_cap_exhausted` on yesterday's exhausted count when the fresh day's window has grants to give.

Reproduced (Q1): `cap=2`, `concurrency=1`; A grants (day 1, `cap_used=1`) and holds; B and C queue past the top check (day 1, `cap_used=1 < 2`); the probe advances the UTC date while they wait; A releases → B grants (`cap_used=2`, still day 1's window) → B releases → C's re-check: `cap_used=2 >= cap=2` → **`(False, "daily_cap_exhausted")` on the fresh day-2 window that should have granted C**. The denial is temporary (the next `acquire`'s top check resets the window) but the queued walk ends THROTTLED no-retry for a cap that did not bind.

**Fix:** re-run the day-window reset inside the loop before the CAP-01 re-check (the same two lines as the top of `acquire`) — a queued waiter then sees the fresh window. Regression fixture: the Q1 rollover — after midnight, the queued waiter GRANTS (and its grant counts against the new day), never a stale-day denial.

## What survives — probed, not assumed

| Surface | Probe | Result |
|---|---|---|
| TR-01 read-phase map, end-to-end | a transport that times out mid-body once then serves a clean page | `transport.calls=2`, walk aggregate `COMPLETE(retrieved==total)` — the mid-body timeout was RETRIED and recovered (the fold-in's promise held at the walk level, not just the transport unit) |
| CAP-01 queued-waiter denial | the fold-in fixture (`test_daily_cap_no_overrun_under_queued_waiters`) | green — exactly cap grants, the queued waiter `(False, "daily_cap_exhausted")` |
| RL-01 atomic reason | the fold-in fixture (`test_acquire_returns_reason_atomically`) | green — the expiry-denied caller reads ITS OWN reason under the interleave |
| Read-phase map unit | the 4 TR-01 fixtures (mid-body timeout / `IncompleteRead` / error-page abort / size-abort passthrough) | green — the map holds on both paths, the size abort passes through |

## Overall verdict: **MERGE WITH REMEDIATION (second gate).**

**RT4-02** is the P2: the TR-01 surface's own output is mislabeled by the walk's `searched` flag — "no literature" concluded from timeouts, the PS-13 class, loud (`EMPTY` raise) but wrong-conclusion-bearing. **RT4-01** is a P3 midnight-edge the CAP-01 re-check left open (stale-day accounting). Both are small fixes with regression fixtures — no redesign, no new components. The fold-in is the standing condition before step 5.

## Disposition — FOLDED IN (2026-08-14)

| ID | Decision | Landed where | Regression fixture |
|---|---|---|---|
| RT4-02 | `TIMEOUT` joins the not-searched set — a transport failure never CLASSIFIED a response; a first-page timeout exhaustion aggregates `UNAVAILABLE` (PS-13-correct), mid-walk stays `SHORTFALL(cause=TIMEOUT)` + retained records | `paginate.py` `walk()` searched flag (the not-searched set is now `THROTTLED`, `TRANSIENT`, `TIMEOUT`); contract §4.1/§4.2 ran-vs-searched text; blueprint walk-module bullet | `test_walk_timeout_exhaustion_is_unavailable_never_empty` + `test_walk_mid_walk_timeout_partial_records_retained` |
| RT4-01 | the UTC day-window reset re-runs inside the wait loop before the CAP-01 cap re-check — a queued waiter sees the fresh window | `ratelimit.py` `acquire` wait loop (reset before the cap re-check, CAP-01 block); contract §6.1; blueprint limiter bullet | `test_daily_cap_window_reset_reapplies_inside_wait_loop` |

**Status: FOLDED IN (2026-08-14).** RT4-01 and RT4-02 reproduced against the running code (probes Q1/Q2 confirmed; Q3 confirmed the TR-01 surface works end-to-end through the driver), then folded into `ratelimit.py` (the in-loop UTC day-window reset, RT4-01) and `paginate.py` (TIMEOUT joins the not-searched set, RT4-02), with regression fixtures for both probes (see the per-finding landing table). Full suite: **770 passed** (767 + 3 regression fixtures), `uvx pyright src` **0 errors**.
