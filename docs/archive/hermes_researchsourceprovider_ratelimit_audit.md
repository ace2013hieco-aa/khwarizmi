# Adversarial Review — Step-4 limiter/transport, shipped-code audit (post-RT3 fold-in)

**Scope:** hostile attack on the SHIPPED step-4 code (`ratelimit.py` + `http.py` + the `_fetch_page` integration), attacking ONLY the four surfaces the three design gates pinned — (1) the daily-cap `False` sentinel, (2) the retryable admission expiry, (3) the HTTPError-as-response status deferral, (4) the 2xx-only size abort — for the same bypass/silent-failure classes the RT/RT2/RT3 gates found, PLUS the class map's coverage boundary (the RT-02/RT2-06 promise: "a bare client-library exception is NEVER propagated"). Method: fresh re-read of the shipped code, then every finding reproduced against the running code with a probe (`probe_step4_audit.py` — P1/P2/P3/P4 + the mid-body read probe). The RT/RT2/RT3 dispositions were treated as settled only where the shipped code actually enforces them.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| TR-01 | **P1** | `http.py` exception class map | **The map covers only the `urlopen` phase — a transport-level failure during the BODY-READ phase escapes bare.** `_read_body` calls `resp.read()` with no exception handling: a mid-download read timeout / connection reset / `IncompleteRead` propagates out of `request()` as a raw `TimeoutError`/`OSError`, the driver's RT2-06 catch-all RE-RAISES it (it is not a `ProviderError`), and `walk()` CRASHES — never a verdict, never the transient retry §6.3 promises. Reproduced: a read-timeout mid-body escapes as bare `TimeoutError`. This is the RT-02/RT2-06 class, unclosed at the read boundary |
| CAP-01 | **P2** | daily-cap hard stop | **The daily cap is not a hard stop under queued waiters — the cap check runs only at the top of `acquire`, and the wait loop's grant condition never re-checks it.** A waiter that passed the check while `cap_used < cap` can GRANT after other waiters exhausted the cap: reproduced deterministically, **3 grants for a `daily_cap` of 2** (A holds, B and C queue past the check, B grants, C grants — overrun=1). The cap is a "hard stop, no retry" by contract; it overruns by up to `concurrency` under concurrent walks (the Tool Runtime explicitly permits them) |
| RL-01 | **P2** | `last_denial_reason` accessor | **The reason accessor is a TOCTOU — a caller can read ANOTHER caller's denial.** `acquire` returns `False` and releases the lock; the driver then calls `last_denial_reason` in a separate locked step. Reproduced with the event-driven interleave: a caller whose OWN denial was `admission_wait_expired` (transient, retryable) read `daily_cap_exhausted` after a concurrent grant exhausted the cap — **the driver takes the NO-RETRY branch on a transient condition, the RT3-02 class the third gate closed, reopened by the API shape** |

## Detail

**TR-01 — The exception class map stops at `urlopen`; the body-read phase is uncovered. (P1)**

§6.1a: "http.py raises ONLY `ProviderError` subclasses with a named `hazard_class` FOR TRANSPORT-LEVEL failures (timeout/connection → `TransientProviderError(hazard_class="TIMEOUT")`…); a bare `socket.timeout`/HTTP-client exception is NEVER propagated." The shipped `request()` wraps `urlopen` in the class map, but the response-body read (`_read_body` → `resp.read(65536)`) runs OUTSIDE any transport-level handler: a read-phase `TimeoutError` (the socket timing out mid-download), `ConnectionResetError`, or `http.client.IncompleteRead` propagates out of `request()` raw. The driver's RT2-06 catch-all (`except Exception: raise`) was built for BUGS — it re-raises the bare exception, and `walk()` — whose contract is "never raises for a verdict" — raises. **A transient condition (retryable per §6.3) crashes the walk instead of producing `SHORTFALL(cause=TIMEOUT)` after the bounded retries.**

Reproduced: a response whose `read()` returns one chunk then raises `TimeoutError("read timed out mid-body")` → `transport.request(...)` **RAISED bare `TimeoutError`** (not `TransientProviderError`).

**Fix:** wrap the body-read phase in the same class map — `except (TimeoutError, ConnectionError, OSError, http.client.HTTPException)` around `_read_body` → `TransientProviderError(hazard_class="TIMEOUT")` `from None`, letting the size-abort's `PermanentProviderError` (a `ProviderError`) pass through untouched. Applied to BOTH the success path and the HTTPError branch (`exc.read` has the same hole). Regression fixtures: mid-body read timeout → `TIMEOUT` transient; mid-body `IncompleteRead` → `TIMEOUT`; the size abort still raises `PARTIAL_CONTENT`.

**CAP-01 — The daily cap overruns under queued waiters. (P2)**

§6.1: "**`False` is reserved for the daily cap** (a hard stop — the cap will not clear within the retry window, so **no retry**)." The shipped `acquire` checks `cap_used >= daily_cap` ONCE at the top (before queueing), and the wait loop's grant condition checks only `head == us AND tokens >= 1 AND in_use < concurrency AND global < global_concurrency` — **no cap re-check**. A waiter that queued while `cap_used < cap` can grant after other waiters exhausted the cap: the hard stop is soft under concurrency, and the overrun rides the FIFO queue exactly (deterministic).

Reproduced: `daily_cap=2`, `concurrency=1`; A grants and holds; B and C queue (both pass the top check at `cap_used=1`); A releases → B grants (`cap_used=2`) → B releases → **C grants (`cap_used=3`)**. **3 grants for a cap of 2 — overrun=1, deterministic** (a bare `time.sleep(0.2)` guarantees both are queued before A's release; FIFO fixes the order).

**Fix:** re-check the cap inside the wait loop, before the grant condition — `if cap_used >= daily_cap: remove self; denial="daily_cap_exhausted"; return False` (the hard-stop no-retry label, and the removal unblocks the FIFO queue for the remaining waiters). The top-of-acquire check stays as the immediate no-wait fast path. Regression fixtures: the queued-waiter overrun (3-thread barrier, cap 2 → exactly 2 grants); a queued waiter hitting the cap gets `daily_cap_exhausted`, never `admission_wait_expired`.

**RL-01 — `last_denial_reason` is a TOCTOU; a caller can read another caller's denial. (P2)**

RT3-03 pinned "keep `-> bool`, add `limiter.last_denial_reason(provider)` — read AFTER a `False`". The shipped shape: `acquire` decides AND returns, releasing the lock; the driver's `last_denial_reason` re-takes the lock in a SEPARATE step. The reason slot is per-provider single-value — any intervening denial (another walk on the same provider) overwrites it before the owner reads. The harmful direction: an expiry-denied caller (transient contention — must retry) reads `daily_cap_exhausted` → **the driver's `if reason == "daily_cap_exhausted": return … THROTTLED …` takes the no-retry branch on a transient condition** — exactly the RT3-02 class the third gate closed, reopened by the API shape.

Reproduced with the event-driven interleave: caller1's own denial was `admission_wait_expired` (slot held, bound 0); while caller1 paused before its read, the holder released, a queued waiter granted (cap exhausted), a later caller hit the cap; caller1's read returned **`"daily_cap_exhausted"`**.

**Fix decision (fold-in):** close it structurally — `acquire` returns the reason atomically: `acquire(provider) -> tuple[bool, str]` (the decision AND the cause under one lock; `""` on grant, the two denial literals on `False`). This changes the `base.py` Protocol, the driver's call site, the fakes, and the RT3-03 text — a contract amendment justified by a reproduced race, and step 5 (the fetch driver "inherits the contract") has NOT shipped yet, so this is the last cheap moment. Alternative (rejected as weaker): thread-local the reason — preserves `-> bool` but couples the contract to the caller's thread and silently breaks an async driver. The audit recommends the tuple.

## What survives — probed, not assumed

| Surface | Probe | Result |
|---|---|---|
| Status deferral, HTTPError with a real `fp` | `HTTPError(…, fp=BytesIO(b"no body?"))` | returned `status=404 body=b"no body?"` — the status is deferred, never raised (RT2-01 holds) |
| Status deferral, HTTPError with `fp=None` | `HTTPError(…, {}, None)` | returned `status=404 body=b""` — the stdlib's `addinfourl.read` guards `fp=None`; no crash (a corner the audit expected to break; it does not) |
| Retryable admission expiry | holder releases the slot at 0.3s; bound 0.05s | attempts 0/1 expire, attempt 2 grants — the expiry retried until the slot freed (RT3-02's fix WORKS in the positive case; RL-01 is the residual race, not a broken mechanism) |
| 2xx-only size abort | oversized 429 vs oversized 200 | 200 → `PARTIAL_CONTENT` raise; 429 → response (status preserved) — the split holds (RT3-01 (a)) |
| `release`-no-refund, before-the-try check, catch-all re-raise | shipped code reading + the existing 29 fixtures | unchanged and green — no regression from the three gates |

## Overall verdict: **MERGE WITH REMEDIATION (fourth gate).**

**TR-01** is gate-blocking for the transport contract as written: the RT-02 promise ("a bare client-library exception is NEVER propagated") is false at the read boundary, and a transient mid-download failure crashes the walk. **CAP-01** and **RL-01** are P2s: the cap is not the hard stop the contract names, and the reason accessor reopens the RT3-02 no-retry-on-transient class. All three are small structural fixes (read-phase wrapping; the loop cap re-check; the `(bool, str)` acquire) with regression fixtures — no redesign, no new components. The fold-in is the standing condition before step 5 (the fetch driver) builds on this contract.

## Disposition — FOLDED IN (2026-08-14)

| ID | Decision | Where it lands |
|---|---|---|
| TR-01 | the body-read phase is wrapped in the class map: timeout/connection/`IncompleteRead` (mid-download, on BOTH the success and the HTTPError paths) → `TransientProviderError(hazard_class="TIMEOUT")` `from None`; the size-abort `PermanentProviderError` passes through untouched | `http.py` — the `_read_body` call sites; contract §6.3; 4 regression fixtures (mid-body timeout / `IncompleteRead` / error-page read-abort / size-abort passthrough) |
| CAP-01 | the wait loop RE-CHECKS the daily cap before the grant condition — a queued waiter hitting the cap gets the no-retry `daily_cap_exhausted` denial (never `admission_wait_expired`) and is removed from the FIFO queue (unblocks the remaining waiters) | `ratelimit.py` `acquire`; contract §6.1; 1 regression fixture (the 3-waiter barrier: exactly cap grants, the queued waiter denied with the hard-stop label) |
| RL-01 | `acquire -> tuple[bool, str]` — the decision AND the cause return under one lock; the driver branches on the returned reason; `last_denial_reason` stays as a DIAGNOSTIC-only accessor | `base.py` Protocol, `ratelimit.py`, `paginate.py` (`_fetch_page` unpack), fakes (`FakeLimiter`/`LeaseLimiter`), RT3-03 text; contract §6.1; 1 regression fixture (the event-driven interleave: the expiry-denied caller reads ITS OWN reason) |

## Re-check (all probes re-verified against the fixed code)

| Probe | Before | After |
|---|---|---|
| TR-01 mid-body read timeout | bare `TimeoutError` escaped `request()` (walk crash) | `TransientProviderError(TIMEOUT)`; the size abort still raises `PARTIAL_CONTENT` |
| CAP-01 queued-waiter overrun | 3 grants for a cap of 2 | exactly 2 grants; the queued waiter denied `(False, "daily_cap_exhausted")` |
| RL-01 reason interleave | expiry-denied caller read `"daily_cap_exhausted"` (no-retry branch on a transient) | the caller's acquire returned `(False, "admission_wait_expired")` — its OWN reason |

**Status: FOLDED IN (2026-08-14).** All three dispositions verified against the running code (6 regression fixtures in `tests/test_provider_ratelimit.py`, **767 passed suite-wide, pyright 0 errors**). The step-4 contract is remediated — step 5 (the fetch driver) may build on the audited limiter/transport.
