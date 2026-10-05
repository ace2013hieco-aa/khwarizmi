"""ProviderRateLimiter — the step-4 rate gate (blueprint §6.1, contract §6.1).

Step 4 of the Part 3 implementation (IDR-030, §27 item 55 RESOLVED).
Remediated per the three hostile design gates
(`hermes_researchsourceprovider_ratelimit_review{,2,3}.md` — RT-01…RT-10,
RT2-01…RT2-06, RT3-01…RT3-05, all FOLDED IN 2026-08-14) and the fourth
gate on the shipped code (`hermes_researchsourceprovider_ratelimit_audit.md`
— TR-01/CAP-01/RL-01, FOLDED IN 2026-08-14).

The limiter is a GATE in front of the transport at the driver call site
(RT-07): it never sees the transport and never wraps it. The driver
(`_fetch_page`) holds the RAW transport and calls acquire → request →
release; `transport.request` has exactly one call site (the driver) — the
only-entry-point invariant (PS-03) made structural. No component other than
the driver may call the limiter, and the limiter never touches the transport
(no double-limit risk, no bypass).

Contract (the three gates pinned these shapes):

- `acquire(provider) -> tuple[bool, str]` — the per-provider token bucket
  (rps, burst) + per-provider semaphore (concurrency) + global bounded
  concurrency, FIFO per provider. NEVER raises for a POLICY condition and
  NEVER blocks on a hard stop (RT-01: a raise would escape the driver's try
  and break `walk()`'s never-raises invariant; an unbounded block would
  hang the retry loop). An unknown provider raises `ValueError` — that is a
  programming error, never a policy condition (fail-closed: no provider
  runs un-throttled). The DECISION and the CAUSE return under one lock
  (RL-01, fourth gate): `(True, "")` on a grant,
  `(False, "daily_cap_exhausted")` | `(False, "admission_wait_expired")`
  on a denial — a caller can never read ANOTHER caller's denial through a
  separate accessor.
- **`False` is reserved for the daily cap** (RT-01/RT2-02/RT3-02): a hard
  stop, no retry — the cap will not clear within the retry window. The
  admission waits are bounded by construction (the bucket's wait is ≤ the
  burst-refill time; the semaphores are short because the driver releases
  per request — WK3-01) with a named `ADMISSION_WAIT_BOUND` (default 60s)
  safety net. On the pathological expiry `acquire` returns
  `(False, "admission_wait_expired")` — **the causes differ in RETRY
  semantics (RT3-02): `daily_cap_exhausted` is a hard stop (no retry);
  `admission_wait_expired` is TRANSIENT contention (the driver backs off
  and RETRIES the page — the next acquire may succeed).
- **The daily cap is a hard stop even under queued waiters (CAP-01, fourth
  gate):** the top-of-acquire check is the no-wait fast path, AND the wait
  loop RE-CHECKS the cap before the grant condition — a waiter that queued
  while `cap_used < cap` can never grant after other waiters exhausted the
  cap; it is removed from the FIFO queue and denied with the no-retry
  `daily_cap_exhausted` label (never `admission_wait_expired`, never a
  grant). The UTC day-window reset RE-RUNS inside the loop too (RT4-01,
  second gate) — a waiter queued across the midnight rollover sees the
  fresh window, never yesterday's exhausted count.
- `last_denial_reason(provider) -> str` (RT3-03) — `""` normally;
  `"daily_cap_exhausted"` | `"admission_wait_expired"` — kept as a
  DIAGNOSTIC-only accessor (the driver branches on the atomic tuple, never
  on this; a provider 429 is never mislabeled — the `note_throttled` path
  never touches it).
- `release(provider)` — returns the SEMAPHORE slot ONLY; a token is NEVER
  refunded (RT-03: a refund would hollow the rps/burst bucket under the
  driver's per-request acquire/release and a walk could loop at burst
  speed). A release without a matching acquire raises `RuntimeError`
  (fail-closed — an underflow would admit MORE than `concurrency`); the
  driver's before-the-try return check makes it structurally impossible
  (RT2-03).
- `note_throttled(provider, retry_after)` — shapes FUTURE acquires ONLY
  (RT-08): tokens drain to zero and a positive `Retry-After` delays refill
  past the cooldown; it NEVER sleeps the current caller (the driver's
  `_backoff` is the only caller-sleeping backoff — no double-delay).
- Daily cap — a hard stop for that provider for a fixed UTC window:
  midnight per `clock.now_utc`'s date (RT-10). Counts GRANTED acquires
  (every transport request, retries included — WK-05).
- Construction validation (RT-09) — fail-closed at `__init__`: non-positive
  `rps`/`burst`/`concurrency`/`daily_cap`, a non-positive
  `admission_wait_bound`, or a non-positive `global_concurrency` →
  `ValueError`. Operator-config validation remains at P7.
- Clock-injected (contract §6.1) — tests drive it with a mutable clock;
  determinism without sleeping.
"""
from __future__ import annotations

import threading
from collections import deque

from hermes.tools.providers.base import Clock, RateProfile

__all__ = ["ProviderRateLimiter"]

# The named safety net (RT-02/RT2-02): the admission waits are bounded by
# construction — the bucket's wait is ≤ burst-refill, the semaphores are
# short because the driver releases per request — so this only fires on the
# pathological path (a holder stuck mid-request).
DEFAULT_ADMISSION_WAIT_BOUND = 60.0
# Shipped default for the GLOBAL bounded-concurrency cap (contract §6.1 —
# \"global bounded concurrency\"). Config, not code; operator-config at P7.
DEFAULT_GLOBAL_CONCURRENCY = 4


class ProviderRateLimiter:
    """The Tool-Runtime-owned rate gate (contract §6.1, three gates folded in).

    Thread-safe: the Tool Runtime permits concurrent walks; aggregation is
    serialized in the fixed §3 allowlist order (PS-05) — this limiter only
    bounds the transport request rate, it does not serialize walks.
    """

    ADMISSION_WAIT_BOUND = DEFAULT_ADMISSION_WAIT_BOUND

    def __init__(
        self,
        profiles: dict[str, RateProfile],
        clock: Clock,
        *,
        global_concurrency: int = DEFAULT_GLOBAL_CONCURRENCY,
        admission_wait_bound: float | None = None,
    ) -> None:
        """Validate fail-closed (RT-09) and build the per-provider state.

        `global_concurrency` is the shipped default — config, not code
        (operator-config at P7); `admission_wait_bound` overrides the
        `ADMISSION_WAIT_BOUND` safety net for tests.
        """
        if global_concurrency < 1:
            raise ValueError(
                f"ProviderRateLimiter: global_concurrency must be >= 1, got {global_concurrency!r}")
        bound = DEFAULT_ADMISSION_WAIT_BOUND if admission_wait_bound is None else admission_wait_bound
        # A zero bound is a legitimate strict policy (never wait for admission
        # — every non-grant is an immediate admission-wait expiry); only a
        # NEGATIVE bound is incoherent.
        if bound < 0:
            raise ValueError(
                f"ProviderRateLimiter: admission_wait_bound must be >= 0, got {bound!r}")
        for provider, prof in profiles.items():
            if prof.rps <= 0 or prof.burst < 1 or prof.concurrency < 1 or prof.daily_cap <= 0:
                raise ValueError(
                    f"ProviderRateLimiter: invalid rate profile for {provider!r}: "
                    f"rps={prof.rps} burst={prof.burst} concurrency={prof.concurrency} "
                    f"daily_cap={prof.daily_cap} — all must be positive (fail-closed, RT-09)")
        if not profiles:
            raise ValueError("ProviderRateLimiter: at least one rate profile is required")

        self._profiles = dict(profiles)
        self._clock = clock
        self._global_concurrency = global_concurrency
        self._bound = bound

        # token bucket state (monotonic-based)
        self._tokens: dict[str, float] = {
            p: float(prof.burst) for p, prof in self._profiles.items()}
        self._last_refill: dict[str, float] = dict.fromkeys(self._profiles, 0.0)
        self._cooldown_until: dict[str, float] = dict.fromkeys(self._profiles, 0.0)
        # concurrency state
        self._in_use: dict[str, int] = dict.fromkeys(self._profiles, 0)
        self._global_in_use = 0
        # daily-cap state (UTC-date window, RT-10)
        self._cap_day: dict[str, str] = {}
        self._cap_used: dict[str, int] = dict.fromkeys(self._profiles, 0)
        # the denial cause (RT3-03) — only written by acquire's False paths
        self._denial: dict[str, str] = dict.fromkeys(self._profiles, "")
        # FIFO waiter queues (per provider — the contract's FIFO)
        self._waiters: dict[str, deque[tuple[threading.Event, int]]] = {
            p: deque() for p in self._profiles}
        self._next_waiter_id = 0
        self._cond = threading.Condition(threading.Lock())

    # ── the public API (Protocol, base.py) ──

    def acquire(self, provider: str) -> tuple[bool, str]:
        """Grant or deny one transport request for `provider`.

        Returns `(True, "")` on grant (token consumed, semaphore + global
        slot held, daily cap incremented). Returns `(False, reason)` WITHOUT
        blocking on a hard policy stop (daily cap) or on the
        ADMISSION_WAIT_BOUND safety-net expiry — NEVER raises for a policy
        condition, NEVER hangs. The reason is ATOMIC with the decision
        (RL-01, fourth gate): a caller always reads ITS OWN denial.
        """
        prof = self._profiles.get(provider)
        if prof is None:
            raise ValueError(
                f"ProviderRateLimiter.acquire: no rate profile for {provider!r} "
                f"(fail-closed — no provider runs un-throttled)")
        with self._cond:
            # Daily cap FIRST — a hit returns False without any admission
            # wait (RT-01: False WITHOUT blocking on a hard stop).
            day = self._day()
            if self._cap_day.get(provider) != day:
                self._cap_day[provider] = day
                self._cap_used[provider] = 0
            if self._cap_used[provider] >= prof.daily_cap:
                self._denial[provider] = "daily_cap_exhausted"
                return False, "daily_cap_exhausted"

            waiter = threading.Event()
            waiter_id = self._next_waiter_id
            self._next_waiter_id += 1
            self._waiters[provider].append((waiter, waiter_id))
            deadline = self._clock.monotonic() + self._bound
            try:
                while True:
                    now = self._clock.monotonic()
                    self._refill(provider, prof, now)
                    # RT4-01 (second gate) — the UTC day-window reset re-runs
                    # HERE, not just at the top of acquire: a waiter queued
                    # across the midnight rollover must see the FRESH window
                    # (otherwise the CAP-01 re-check below denies it on
                    # yesterday's exhausted count, and a grant would be
                    # charged to the wrong day).
                    day = self._day()
                    if self._cap_day.get(provider) != day:
                        self._cap_day[provider] = day
                        self._cap_used[provider] = 0
                    # CAP-01 (fourth gate) — RE-CHECK the cap inside the wait
                    # loop, before the grant condition: a waiter queued while
                    # cap_used < cap would otherwise grant after other
                    # waiters exhausted the cap (the hard stop is soft under
                    # concurrency). The denial is the no-retry
                    # daily_cap_exhausted — NEVER the retryable expiry label —
                    # and removing self unblocks the FIFO queue.
                    if self._cap_used[provider] >= prof.daily_cap:
                        entry = (waiter, waiter_id)
                        if entry in self._waiters[provider]:
                            self._waiters[provider].remove(entry)
                        self._denial[provider] = "daily_cap_exhausted"
                        return False, "daily_cap_exhausted"
                    _head_waiter, head_id = self._waiters[provider][0]
                    if (head_id == waiter_id
                            and self._tokens[provider] >= 1.0
                            and self._in_use[provider] < prof.concurrency
                            and self._global_in_use < self._global_concurrency):
                        # grant — charge the token (never refunded, RT-03),
                        # hold the slots, count the request against the cap
                        self._tokens[provider] -= 1.0
                        self._in_use[provider] += 1
                        self._global_in_use += 1
                        self._cap_used[provider] += 1
                        self._waiters[provider].popleft()
                        self._denial[provider] = ""
                        # the next FIFO waiter may now be the head — wake it
                        self._cond.notify_all()
                        return True, ""
                    remaining = deadline - self._clock.monotonic()
                    if remaining <= 0:
                        # admission-wait expiry — TRANSIENT contention
                        # (RT2-02/RT3-02): the driver RETRIES the page; the
                        # daily cap stays the only no-retry False.
                        entry = (waiter, waiter_id)
                        if entry in self._waiters[provider]:
                            self._waiters[provider].remove(entry)
                        self._denial[provider] = "admission_wait_expired"
                        return False, "admission_wait_expired"
                    # wait the shorter of the token arrival and the bound
                    # remainder — never longer than the safety net; a 0-wait
                    # (token ready, slot held) yields briefly instead of
                    # busy-spinning until the deadline
                    wait = min(remaining, self._token_wait(provider, prof, now))
                    self._cond.wait(wait if wait > 0 else 0.01)
            finally:
                # A grant pops the head and an expiry removes it, so a
                # successful return leaves the queue consistent; this
                # defensive remove only fires on an exception path (lock
                # held, the membership check is stable) — the waiter must
                # never block the queue behind it.
                entry = (waiter, waiter_id)
                if entry in self._waiters[provider]:
                    self._waiters[provider].remove(entry)
                    self._denial[provider] = "admission_wait_expired"

    def release(self, provider: str) -> None:
        """Return the SEMAPHORE slot only — a token is NEVER refunded (RT-03).

        A release without a matching acquire is a bug (an underflow would
        admit MORE than `concurrency`) — raised loudly; the driver's
        before-the-try return check (RT2-03) makes it structurally
        impossible from `_fetch_page`.
        """
        with self._cond:
            if self._in_use.get(provider, 0) <= 0:
                raise RuntimeError(
                    f"ProviderRateLimiter.release: no slot held for {provider!r} "
                    f"(release without acquire — would underflow the semaphore)")
            self._in_use[provider] -= 1
            self._global_in_use -= 1
            self._cond.notify_all()

    def note_throttled(self, provider: str, retry_after: float | None) -> None:
        """Drain the bucket; a positive `retry_after` delays refill (RT-08).

        Shapes FUTURE acquires only — never sleeps the current caller (the
        driver's `_backoff` is the only caller-sleeping backoff). A provider
        429 is never mislabeled as a limiter denial — this never touches
        `last_denial_reason`.
        """
        with self._cond:
            if provider not in self._profiles:
                return
            self._tokens[provider] = 0.0
            if retry_after is not None and retry_after > 0:
                self._cooldown_until[provider] = self._clock.monotonic() + retry_after
            else:
                self._cooldown_until[provider] = 0.0
            self._cond.notify_all()

    def last_denial_reason(self, provider: str) -> str:
        """RT3-03 — \"\" | \"daily_cap_exhausted\" | \"admission_wait_expired\".

        Read AFTER a `False` from `acquire`; empty otherwise. The two causes
        differ in RETRY semantics — the driver branches on this.
        """
        with self._cond:
            return self._denial.get(provider, "")

    # ── internals ──

    def _day(self) -> str:
        """The fixed UTC daily-cap window: the date of `clock.now_utc` (RT-10)."""
        return self._clock.now_utc()[:10]

    def _refill(self, provider: str, prof: RateProfile, now: float) -> None:
        """Continuous refill at rps, bounded by burst; a Retry-After cooldown
        holds the bucket at zero until it passes (tokens stay 0 during the
        cooldown; refill resumes from the cooldown's end)."""
        if now < self._cooldown_until.get(provider, 0.0):
            self._tokens[provider] = 0.0
            if now > self._last_refill[provider]:
                self._last_refill[provider] = now
            return
        last = self._last_refill[provider]
        if now > last:
            self._tokens[provider] = min(
                float(prof.burst), self._tokens[provider] + (now - last) * prof.rps)
            self._last_refill[provider] = now

    def _token_wait(self, provider: str, prof: RateProfile, now: float) -> float:
        """Seconds until the next token, honoring a Retry-After cooldown —
        the bucket's wait is bounded by burst-refill (a token arrives within
        1/rps once the cooldown passes)."""
        cooldown = self._cooldown_until.get(provider, 0.0)
        if now < cooldown:
            return cooldown - now
        tokens = self._tokens[provider]
        if tokens >= 1.0:
            return 0.0
        return (1.0 - tokens) / prof.rps


