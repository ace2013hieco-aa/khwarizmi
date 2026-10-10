"""Supervisor — cancel, retry, timeout, trace, recovery (§2.3, §4 B-4).

Four jobs, one owner
--------------------
A run needs to be *stoppable* (cooperative cancel), *bounded in time*
(deadline), *bounded in attempts* (retry budget), and *observable* (a streaming
execution trace). It also owns the classification half of crash recovery. All
four are process-local and derived: nothing here is durable, nothing is
scheduled, and nothing takes a lock — the plane is not a scheduler and holds no
lease custody (§3.2.4).

Cooperative cancel, deliberately
--------------------------------
`RunCancelToken` is a flag another part of the process may set — no thread, no
signal handler, no `asyncio` cancellation. A plane that could not be stopped by
its caller would be an authority over its own lifetime, and a plane that spawned
its own killer thread would be a second scheduler.

The trace is derived, and deliberately not durable
--------------------------------------------------
`emit()` appends to an in-memory per-run list; `stream()` yields a snapshot.
B-5 forbids the runtime a second durable log, so nothing here is persisted, and
a resumed run starts a fresh trace while the checkpoint's digests carry the
lineage. The `at` stamp comes from the injected clock and the sequence number is
per-run, so a trace is deterministic given a deterministic clock.

Timeout, checked and never enforced by force
--------------------------------------------
`check()` answers "cancelled", "timed out" or "go". A port call that overruns its
deadline is *recorded and its result discarded* by the caller — killing arbitrary
Python needs the sandbox, which is a capability this plane does not have (the
same honest limit R3 records for a runaway tool).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from hermes.agents.runtime.checkpoint import apply_recovery, classify_recovery
from hermes.agents.runtime.types import (
    Checkpoint,
    RecoveryVerdict,
    TraceEvent,
    digest_of,
)
from hermes.core import Clock, utc_now

Monotonic = Callable[[], float]

#: Default horizon after which a run's heartbeat is a conclusive miss.
DEFAULT_HEARTBEAT_HORIZON_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class RetryBudget:
    """A bounded, deterministic retry schedule (no jitter, no ambient state).

    Deterministic on purpose: a run whose retries depended on wall-clock jitter
    could not claim "the same terminal state" after a resume.
    """

    max_retries: int = 2
    base_delay_seconds: float = 0.5

    def delays(self) -> tuple[float, ...]:
        """The delay before each retry, doubling: base, 2×base, 4×base, …"""
        return tuple(self.base_delay_seconds * (2 ** index)
                     for index in range(self.max_retries))

    def allows(self, attempt: int) -> bool:
        """True when another attempt is permitted after `attempt` (1-based)."""
        return attempt <= self.max_retries


class RunCancelToken:
    """A cooperative cancel flag. Satisfies the capability plane's `CancelToken`."""

    def __init__(self, reason: str = "") -> None:
        self._cancelled = False
        self._reason = reason

    def cancel(self, reason: str = "") -> None:
        self._cancelled = True
        if reason:
            self._reason = reason

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason

    def is_cancelled(self) -> bool:
        """The protocol method the capability plane expects."""
        return self._cancelled


class Supervisor:
    """Cancel / retry / timeout / trace / recovery for one runtime instance."""

    def __init__(
        self,
        *,
        clock: Clock = utc_now,
        monotonic: Monotonic | None = None,
        sleep: Callable[[float], None] | None = None,
        heartbeat_horizon_seconds: float = DEFAULT_HEARTBEAT_HORIZON_SECONDS,
        retry: RetryBudget | None = None,
        on_event: Callable[[TraceEvent], None] | None = None,
    ) -> None:
        self._clock = clock
        self._monotonic = monotonic if monotonic is not None else time.monotonic
        self._sleep = sleep if sleep is not None else time.sleep
        self._horizon = heartbeat_horizon_seconds
        self._retry = retry if retry is not None else RetryBudget()
        self._on_event = on_event
        self._traces: dict[str, list[TraceEvent]] = {}

    # ── time ──

    def now(self) -> str:
        return self._clock()

    def deadline(self, seconds: float | None) -> float | None:
        """Turn a relative deadline into a monotonic instant (or `None`)."""
        if seconds is None:
            return None
        return self._monotonic() + float(seconds)

    def elapsed(self, deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return self._monotonic() - deadline

    def expired(self, deadline: float | None) -> bool:
        return deadline is not None and self._monotonic() >= deadline

    def check(self, token: RunCancelToken | None,
              deadline: float | None) -> str:
        """`"` (go), `"CANCELLED"` or `"TIMEOUT"` — checked, never enforced."""
        if token is not None and token.cancelled:
            return "CANCELLED"
        if self.expired(deadline):
            return "TIMEOUT"
        return ""

    def sleep(self, seconds: float) -> None:
        self._sleep(seconds)

    # ── retry ──

    @property
    def retry(self) -> RetryBudget:
        return self._retry

    def attempt(
        self,
        action: Callable[[int], Any],
        *,
        retryable: Callable[[Any], bool],
        budget: RetryBudget | None = None,
    ) -> tuple[Any, tuple[int, ...]]:
        """Call `action(attempt)` until it is not retryable or the budget ends.

        Returns the last result and every attempt number made, so a run can
        record *how many* attempts a proposal cost without the supervisor
        keeping state of its own.
        """
        plan = budget if budget is not None else self._retry
        result: Any = None
        attempts: list[int] = []
        for attempt in range(1, plan.max_retries + 2):
            attempts.append(attempt)
            result = action(attempt)
            if not retryable(result) or not plan.allows(attempt):
                break
            self.sleep(plan.delays()[attempt - 1])
        return result, tuple(attempts)

    # ── the trace ──

    def emit(self, *, kind: str, run_id: str, tick: int, lease_generation: str,
             detail: dict[str, Any] | None = None) -> TraceEvent:
        """Append one trace event; in-memory only (never a durable log, B-5)."""
        events = self._traces.setdefault(run_id, [])
        event = TraceEvent(
            sequence=len(events) + 1,
            kind=kind,
            run_id=run_id,
            tick=tick,
            lease_generation=lease_generation,
            at=self._clock(),
            detail=dict(detail or {}),
        )
        events.append(event)
        if self._on_event is not None:
            self._on_event(event)
        return event

    def events(self, run_id: str) -> tuple[TraceEvent, ...]:
        return tuple(self._traces.get(run_id, ()))

    def stream(self, run_id: str) -> Iterator[TraceEvent]:
        """A snapshot stream: the events this run has emitted so far, in order."""
        return iter(self.events(run_id))

    def trace_digest(self, run_id: str) -> str:
        return digest_of([{**event.detail, "kind": event.kind,
                           "seq": event.sequence}
                          for event in self.events(run_id)])

    def forget(self, run_id: str) -> None:
        """Drop a run's trace (its lineage lives in the checkpoint's digests)."""
        self._traces.pop(run_id, None)

    # ── crash recovery ──

    def heartbeat_age_seconds(self, last_heartbeat: str,
                             *, now: str | None = None) -> float | None:
        """Seconds since the last heartbeat, or `None` when there was never one."""
        if not last_heartbeat:
            return None
        stamp = now if now is not None else self._clock()
        try:
            then = datetime.fromisoformat(last_heartbeat)
            current = datetime.fromisoformat(stamp)
        except ValueError:
            return None
        return (current - then).total_seconds()

    def stale(self, last_heartbeat: str, *, now: str | None = None) -> bool:
        """A missing heartbeat is a conclusive miss: there is nothing to trust."""
        age = self.heartbeat_age_seconds(last_heartbeat, now=now)
        if age is None:
            return True
        return age >= self._horizon

    def recover(self, checkpoint: Checkpoint, *,
                now: str | None = None) -> tuple[RecoveryVerdict, Checkpoint]:
        """Classify an interrupted run and fold the verdict back in.

        Classification only: `RecoveryVerdict.may_dispatch` is `False` on every
        branch, so recovery can never become a second scheduler. Continuing a run
        is a separate, explicit act.
        """
        stamp = now if now is not None else self._clock()
        verdict = classify_recovery(
            checkpoint, stale=self.stale(checkpoint.last_heartbeat, now=stamp))
        updated = apply_recovery(checkpoint, verdict, at=stamp)
        self.emit(kind="RECOVERY_CLASSIFIED", run_id=checkpoint.run_id,
                  tick=checkpoint.tick,
                  lease_generation=checkpoint.lease_generation,
                  detail={"verdict": verdict.kind, "misses": verdict.misses,
                          "may_resume": verdict.may_resume,
                          "may_dispatch": verdict.may_dispatch})
        return verdict, updated
