"""P-AUTO-4 autonomy envelopes + safety caps (deterministic, no model calls).

The hard blocker for live loops (D6): every live-loop budget is a
deterministic envelope whose breach refuses fail-closed with a named code
(refusal-as-data). No LLM/model judgment sits in any breach path — the
checks below are pure integer/float/clock comparisons plus an in-memory
pattern counter. Values proposed here are RATIFIED AT THE GATE (D6); the
table is the ratification surface.

Proposed values table (gate ratification; carries existing defaults where
they exist — nothing is loosened):

================ ============================== =============================
Scope            Cap                            Proposed value (carry?)
================ ============================== =============================
budget/steps     per_task_steps (max controller  5 (new; > task max_retries 3
                 executions of one task,          so normal retries never hit
                 incl retries/recovery)           it)
budget/steps     per_tick_steps (max dispatches  8 (carry
                 per tick)                        DEFAULT_MAX_CALLS_PER_TICK)
budget/steps     per_run_steps (max dispatches   1000 (carry run max_ticks)
                 per run)
budget/tokens    per_task_tokens (max provider   250 (new; > 50 pages x
                 requests per task, retries       (retries+1) worst case)
                 included)
budget/tokens    per_tick_tokens (max provider   1000 (new; 8 tasks x 125
                 requests per tick)               avg, under per_task x tick)
budget/tokens    per_run_tokens (max provider    10000 (new; 1000 ticks x 10
                 requests per run)                avg, bounded)
wall-clock       overall_dispatch_deadline_s     300.0 (carry
                 (one SOURCE dispatch)            DEFAULT_OVERALL_DEADLINE_SECONDS)
wall-clock       per_tick_wall_s (one tick)      600.0 (new; 2x dispatch)
wall-clock       per_run_wall_s (one run)        3600.0 (new; 1h operator day
                                                  slice)
retry/backoff    max_retries (per page/source)   3 (carry
                                                  DEFAULT_SOURCE_RETRY_POLICY)
retry/backoff    base_delay_s                    1.0 (carry)
retry/backoff    max_delay_s                     30.0 (carry)
retry/backoff    jitter                          True (carry; deterministic
                                                  tests use jitter=False)
retry/hard-stop  daily_cap_exhausted             hard stop, no retry (carry
                                                  RT-01/RT2-02/RT3-02)
loop/poison      repeat_threshold (same task +   3 (new; matches max_retries
                 same failure signature           so exhaustion => review)
                 consecutive hits => quarantine)
rate (D5)        openalex rps/burst/daily_cap    5.0 / 5 / 1000 (carry live
                                                  wiring)
rate (D5)        pubmed rps/burst/daily_cap      3.0 / 3 / 1000 (carry live
                                                  wiring)
rate/admission   admission_wait_bound_s          60.0 (carry
                                                  DEFAULT_ADMISSION_WAIT_BOUND)
dns/egress       resolve allowlisted hosts;      refuse (new; S2 pin
                 refuse private/loopback/         mechanics, D5 scope only)
                 link-local/multicast/
                 unspecified/reserved/not-global/
                 ipv4-mapped/site-local/6bone
proxy            guarded fetches ignore          no-proxy opener (new;
                 HTTPS_PROXY (never bypass the    ProxyHandler({}))
                 allowlist)
================ ============================== =============================

Starvation / deadlock review (g): the envelopes above cannot starve or
deadlock a live loop — (1) every cap is a STOP, never a wait: a breach
returns a named refusal and the controller parks the task / ends the
tick / ends the run instead of blocking on a grant that will never
arrive; (2) the only waiting primitive (the limiter admission queue) is
already bounded by ADMISSION_WAIT_BOUND with a named expiry that RETRIES
transiently, while the daily cap is the sole no-retry hard stop — caps
never convert a hard stop into a wait; (3) quarantine never silently
retries: a quarantined task stays FAILED with a human-visible note and is
excluded from requeue/re-execution, so the recovery ladder cannot livelock
on a poison task; (4) wall-clock deadlines are checked BEFORE each
page/source and each retry attempt (never after), so a hung provider stops
the dispatch instead of holding the tick; (5) per-tick/per-run step caps
are checked before claim, so a capped task is never stranded RUNNING.
No new locks, no new threads, no new schema — the trackers below are
in-memory counters owned by the tick/run scope.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Callable

__all__ = [
    "ADMISSION_WAIT_BOUND_S",
    "BUDGET_PER_RUN_STEPS_EXCEEDED",
    "BUDGET_PER_RUN_TOKENS_EXCEEDED",
    "BUDGET_PER_TASK_STEPS_EXCEEDED",
    "BUDGET_PER_TASK_TOKENS_EXCEEDED",
    "BUDGET_PER_TICK_STEPS_EXCEEDED",
    "BUDGET_PER_TICK_TOKENS_EXCEEDED",
    "DAILY_CAP_HARD_STOP",
    "DEFAULT_LOOP_REPEAT_THRESHOLD",
    "DEFAULT_OVERALL_DISPATCH_DEADLINE_S",
    "DEFAULT_PER_RUN_STEPS",
    "DEFAULT_PER_RUN_TOKENS",
    "DEFAULT_PER_RUN_WALL_S",
    "DEFAULT_PER_TASK_STEPS",
    "DEFAULT_PER_TASK_TOKENS",
    "DEFAULT_PER_TICK_STEPS",
    "DEFAULT_PER_TICK_TOKENS",
    "DEFAULT_PER_TICK_WALL_S",
    "DEFAULT_RETRY_BASE_DELAY_S",
    "DEFAULT_RETRY_MAX_DELAY_S",
    "DEFAULT_RETRY_MAX_RETRIES",
    "DNS_REBINDING_REFUSED",
    "LOOP_PATTERN_QUARANTINED",
    "POISON_TASK_QUARANTINED",
    "P_AUTO_4_PROPOSED_VALUES",
    "RETRY_ATTEMPTS_EXHAUSTED",
    "STARVATION_DEADLOCK_REVIEW",
    "WALLCLOCK_DISPATCH_DEADLINE_EXCEEDED",
    "WALLCLOCK_RUN_DEADLINE_EXCEEDED",
    "WALLCLOCK_TICK_DEADLINE_EXCEEDED",
    "BudgetEnvelope",
    "BudgetTracker",
    "LoopDetector",
    "RetryCaps",
    "WallClockCaps",
    "build_envelope",
    "build_loop_threshold",
    "build_rate_profiles",
    "build_retry_caps",
    "build_wallclock",
    "classify_failure_signature",
    "deterministic_backoff_delay",
    "is_explicit_knob",
    "narrow_float",
    "narrow_int",
    "refuse_non_public_addresses",
    "reimport_quarantine",
    "resolve_and_vet_host",
]

# ── refusal codes (refusal-as-data; stable for tests/audit) ──

BUDGET_PER_TASK_STEPS_EXCEEDED = "BUDGET_PER_TASK_STEPS_EXCEEDED"
BUDGET_PER_TICK_STEPS_EXCEEDED = "BUDGET_PER_TICK_STEPS_EXCEEDED"
BUDGET_PER_RUN_STEPS_EXCEEDED = "BUDGET_PER_RUN_STEPS_EXCEEDED"
BUDGET_PER_TASK_TOKENS_EXCEEDED = "BUDGET_PER_TASK_TOKENS_EXCEEDED"
BUDGET_PER_TICK_TOKENS_EXCEEDED = "BUDGET_PER_TICK_TOKENS_EXCEEDED"
BUDGET_PER_RUN_TOKENS_EXCEEDED = "BUDGET_PER_RUN_TOKENS_EXCEEDED"
WALLCLOCK_DISPATCH_DEADLINE_EXCEEDED = "WALLCLOCK_DISPATCH_DEADLINE_EXCEEDED"
WALLCLOCK_TICK_DEADLINE_EXCEEDED = "WALLCLOCK_TICK_DEADLINE_EXCEEDED"
WALLCLOCK_RUN_DEADLINE_EXCEEDED = "WALLCLOCK_RUN_DEADLINE_EXCEEDED"
RETRY_ATTEMPTS_EXHAUSTED = "RETRY_ATTEMPTS_EXHAUSTED"
DAILY_CAP_HARD_STOP = "daily_cap_exhausted"
LOOP_PATTERN_QUARANTINED = "LOOP_PATTERN_QUARANTINED"
POISON_TASK_QUARANTINED = "POISON_TASK_QUARANTINED"
DNS_REBINDING_REFUSED = "DNS_REBINDING_REFUSED"

# ── proposed defaults (the values table, machine-readable) ──

DEFAULT_PER_TASK_STEPS = 5
DEFAULT_PER_TICK_STEPS = 8
DEFAULT_PER_RUN_STEPS = 1000
DEFAULT_PER_TASK_TOKENS = 250
DEFAULT_PER_TICK_TOKENS = 1000
DEFAULT_PER_RUN_TOKENS = 10000
DEFAULT_OVERALL_DISPATCH_DEADLINE_S = 300.0
DEFAULT_PER_TICK_WALL_S = 600.0
DEFAULT_PER_RUN_WALL_S = 3600.0
DEFAULT_RETRY_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY_S = 1.0
DEFAULT_RETRY_MAX_DELAY_S = 30.0
DEFAULT_LOOP_REPEAT_THRESHOLD = 3
ADMISSION_WAIT_BOUND_S = 60.0

P_AUTO_4_PROPOSED_VALUES: dict[str, object] = {
    "per_task_steps": DEFAULT_PER_TASK_STEPS,
    "per_tick_steps": DEFAULT_PER_TICK_STEPS,
    "per_run_steps": DEFAULT_PER_RUN_STEPS,
    "per_task_tokens": DEFAULT_PER_TASK_TOKENS,
    "per_tick_tokens": DEFAULT_PER_TICK_TOKENS,
    "per_run_tokens": DEFAULT_PER_RUN_TOKENS,
    "overall_dispatch_deadline_s": DEFAULT_OVERALL_DISPATCH_DEADLINE_S,
    "per_tick_wall_s": DEFAULT_PER_TICK_WALL_S,
    "per_run_wall_s": DEFAULT_PER_RUN_WALL_S,
    "retry_max_retries": DEFAULT_RETRY_MAX_RETRIES,
    "retry_base_delay_s": DEFAULT_RETRY_BASE_DELAY_S,
    "retry_max_delay_s": DEFAULT_RETRY_MAX_DELAY_S,
    "retry_jitter": True,
    "daily_cap_hard_stop": DAILY_CAP_HARD_STOP,
    "loop_repeat_threshold": DEFAULT_LOOP_REPEAT_THRESHOLD,
    "openalex_rps": 5.0,
    "openalex_burst": 5,
    "openalex_daily_cap": 1000,
    "pubmed_rps": 3.0,
    "pubmed_burst": 3,
    "pubmed_daily_cap": 1000,
    "admission_wait_bound_s": ADMISSION_WAIT_BOUND_S,
}

STARVATION_DEADLOCK_REVIEW = (
    "P-AUTO-4 starvation/deadlock review: every cap is a STOP, never a wait "
    "(breach => named refusal + park/end, never block); the limiter admission "
    "queue stays bounded by ADMISSION_WAIT_BOUND with transient retry, the "
    "daily cap stays the sole no-retry hard stop; quarantine excludes poison "
    "tasks from requeue/re-execution with a human-visible note so recovery "
    "cannot livelock; wall-clock deadlines are checked BEFORE each page/source "
    "and retry attempt; step caps are checked before claim so capped tasks are "
    "never stranded RUNNING. No new locks/threads/schema."
)


# ── envelopes (frozen carriers; the trackers below enforce them) ──


@dataclass(frozen=True, slots=True)
class BudgetEnvelope:
    """Per-task / per-tick / per-run step + token budgets (D6 proposed)."""

    per_task_steps: int = DEFAULT_PER_TASK_STEPS
    per_tick_steps: int = DEFAULT_PER_TICK_STEPS
    per_run_steps: int = DEFAULT_PER_RUN_STEPS
    per_task_tokens: int = DEFAULT_PER_TASK_TOKENS
    per_tick_tokens: int = DEFAULT_PER_TICK_TOKENS
    per_run_tokens: int = DEFAULT_PER_RUN_TOKENS


@dataclass(frozen=True, slots=True)
class RetryCaps:
    """Retry-with-backoff params (proposed values, capped attempts)."""

    max_retries: int = DEFAULT_RETRY_MAX_RETRIES
    base_delay_s: float = DEFAULT_RETRY_BASE_DELAY_S
    max_delay_s: float = DEFAULT_RETRY_MAX_DELAY_S
    jitter: bool = True


@dataclass(frozen=True, slots=True)
class WallClockCaps:
    """Wall-clock budgets (seconds; <= 0 disables that bound)."""

    dispatch_deadline_s: float = DEFAULT_OVERALL_DISPATCH_DEADLINE_S
    per_tick_wall_s: float = DEFAULT_PER_TICK_WALL_S
    per_run_wall_s: float = DEFAULT_PER_RUN_WALL_S


# ── narrow-only operator knobs (config may tighten, never widen) ──


def narrow_int(operator: int | None, code_default: int, name: str) -> int:
    """Narrow-only int knob: absent => default; tighter => accepted.

    A looser-than-default operator value is refused LOUDLY (never silently
    clamped) — the code-owned surface is the ceiling, mirroring
    ``allowlist_from_config`` (config may narrow, never widen).
    """
    if operator is None:
        return code_default
    if not isinstance(operator, int) or isinstance(operator, bool):
        raise ValueError(f"P-AUTO-4 {name} must be an int, got {operator!r}")
    if operator <= 0:
        raise ValueError(f"P-AUTO-4 {name} must be > 0, got {operator!r}")
    if operator > code_default:
        raise ValueError(
            f"P-AUTO-4 {name}={operator!r} widens the code-owned ceiling "
            f"{code_default!r} — operator config may only narrow, never widen")
    return operator


def narrow_float(operator: float | int | None, code_default: float, name: str) -> float:
    """Narrow-only float knob: absent => default; tighter => accepted."""
    if operator is None:
        return code_default
    if not isinstance(operator, (int, float)) or isinstance(operator, bool):
        raise ValueError(f"P-AUTO-4 {name} must be a number, got {operator!r}")
    value = float(operator)
    if value <= 0:
        raise ValueError(f"P-AUTO-4 {name} must be > 0, got {operator!r}")
    if value > code_default:
        raise ValueError(
            f"P-AUTO-4 {name}={value!r} widens the code-owned ceiling "
            f"{code_default!r} — operator config may only narrow, never widen")
    return value


def deterministic_backoff_delay(attempt: int, base: float, max_delay: float) -> float:
    """Pure exponential backoff delay (no sleep, no jitter, no randomness).

    ``attempt`` is 0-based. Deterministic so cap-breach tests pin the exact
    bound; production jitter (if enabled) only SHRINKS toward this ceiling
    via ``uniform(0.5, 1.0)`` — this value is the per-attempt worst case.
    """
    if attempt < 0:
        raise ValueError(f"attempt must be >= 0, got {attempt!r}")
    if base <= 0 or max_delay <= 0:
        raise ValueError("base and max_delay must be > 0")
    return min(max_delay, base * (2.0 ** attempt))


# ── in-memory trackers (tick/run scope; no schema, no journal writes) ──


@dataclass
class BudgetTracker:
    """In-memory step/token counters for one controller run.

    ``check_*`` returns "" on grant or the named refusal code on breach —
    the caller parks/ends with the code (refusal-as-data, never an
    exception for a policy condition, never silent success).
    """

    envelope: BudgetEnvelope = field(default_factory=BudgetEnvelope)
    run_steps: int = 0
    run_tokens: int = 0
    tick_steps: int = 0
    tick_tokens: int = 0
    task_steps: dict[str, int] = field(default_factory=dict)
    task_tokens: dict[str, int] = field(default_factory=dict)

    def begin_tick(self) -> None:
        self.tick_steps = 0
        self.tick_tokens = 0

    def check_step(self, task_id: str) -> str:
        """Grant one dispatch step for ``task_id`` or refuse with a code."""
        per_task = self.task_steps.get(task_id, 0) + 1
        if per_task > self.envelope.per_task_steps:
            return BUDGET_PER_TASK_STEPS_EXCEEDED
        if self.tick_steps + 1 > self.envelope.per_tick_steps:
            return BUDGET_PER_TICK_STEPS_EXCEEDED
        if self.run_steps + 1 > self.envelope.per_run_steps:
            return BUDGET_PER_RUN_STEPS_EXCEEDED
        return ""

    def consume_step(self, task_id: str) -> str:
        """Check then count one dispatch step; returns "" or the code."""
        code = self.check_step(task_id)
        if code:
            return code
        self.task_steps[task_id] = self.task_steps.get(task_id, 0) + 1
        self.tick_steps += 1
        self.run_steps += 1
        return ""

    def check_task_step(self, task_id: str) -> str:
        """Per-task step check only (recovery path, FIX-A2).

        Recovery re-execution is liveness work: it is counted against the
        task's own envelope (poison visibility, alongside the max_retries
        attempt bound) but never against the tick/run dispatch capacity —
        the F15 cadence contract (`needed == ceil(n/cap)`) owns that
        capacity, and starving recovery on a full tick would strand dead
        workers instead of recovering them.
        """
        if self.task_steps.get(task_id, 0) + 1 > self.envelope.per_task_steps:
            return BUDGET_PER_TASK_STEPS_EXCEEDED
        return ""

    def record_task_step(self, task_id: str) -> None:
        """Count one recovery execution against the task envelope only."""
        self.task_steps[task_id] = self.task_steps.get(task_id, 0) + 1

    def check_tokens(self, task_id: str, amount: int) -> str:
        """Grant ``amount`` provider-request tokens or refuse with a code."""
        if amount < 0:
            raise ValueError(f"token amount must be >= 0, got {amount!r}")
        if self.task_tokens.get(task_id, 0) + amount > self.envelope.per_task_tokens:
            return BUDGET_PER_TASK_TOKENS_EXCEEDED
        if self.tick_tokens + amount > self.envelope.per_tick_tokens:
            return BUDGET_PER_TICK_TOKENS_EXCEEDED
        if self.run_tokens + amount > self.envelope.per_run_tokens:
            return BUDGET_PER_RUN_TOKENS_EXCEEDED
        return ""

    def consume_tokens(self, task_id: str, amount: int) -> str:
        code = self.check_tokens(task_id, amount)
        if code:
            return code
        self.task_tokens[task_id] = self.task_tokens.get(task_id, 0) + amount
        self.tick_tokens += amount
        self.run_tokens += amount
        return ""

    def record_tokens(self, task_id: str, amount: int) -> str:
        """FIX-A1 — record SPENT provider requests unconditionally.

        Post-execution accounting: the requests already left the host, so
        refusing to count them would re-open the undercount bypass (the
        ledger would understate the wire). Always records; returns the
        first breached cap code ("" when within envelope) so the caller
        can note the overrun — subsequent admissions refuse on the
        recorded totals via ``check_tokens``.
        """
        if amount < 0:
            raise ValueError(f"token amount must be >= 0, got {amount!r}")
        self.task_tokens[task_id] = self.task_tokens.get(task_id, 0) + amount
        self.tick_tokens += amount
        self.run_tokens += amount
        if self.task_tokens[task_id] > self.envelope.per_task_tokens:
            return BUDGET_PER_TASK_TOKENS_EXCEEDED
        if self.tick_tokens > self.envelope.per_tick_tokens:
            return BUDGET_PER_TICK_TOKENS_EXCEEDED
        if self.run_tokens > self.envelope.per_run_tokens:
            return BUDGET_PER_RUN_TOKENS_EXCEEDED
        return ""


@dataclass
class LoopDetector:
    """Pattern counter + poison-task quarantine (beyond admission cycles).

    Tracks consecutive (task_id, failure-CLASS) hits — the class comes
    from ``classify_failure_signature`` (FIX-B2: free-text reasons cannot
    evade the threshold by varying incident detail; blank reasons count as
    ``UNKNOWN``). At ``repeat_threshold`` the task is QUARANTINED: parked
    FAILED with a human-visible reason, never auto-retried, excluded from
    requeue. The quarantine set is the primitive the controller consults
    before any retry/requeue decision — a quarantined task can only leave
    via an operator action (new intent), never silently. The terminal
    quarantine state is journaled (the FAILED transition reason carries the
    marker codes) and re-imported on boot via ``reimport_quarantine``
    (FIX-B1: memory-only is what failed the audit).
    """

    repeat_threshold: int = DEFAULT_LOOP_REPEAT_THRESHOLD
    _counts: dict[tuple[str, str], int] = field(default_factory=dict)
    _quarantined: dict[str, str] = field(default_factory=dict)

    def observe_failure(self, task_id: str, signature: str) -> str:
        """Record one failure; returns "" or a quarantine code."""
        failure_class = classify_failure_signature(signature)
        key = (task_id, failure_class)
        # A different class for the same task resets every other streak.
        for other in [k for k in self._counts if k[0] == task_id and k != key]:
            del self._counts[other]
        streak = self._counts.get(key, 0) + 1
        self._counts[key] = streak
        if streak >= self.repeat_threshold:
            raw = (signature or "")[:120]
            reason = (
                f"loop quarantined: task {task_id!r} failed {streak}x "
                f"with failure class {failure_class!r} (last: {raw!r}) "
                f"({LOOP_PATTERN_QUARANTINED}/{POISON_TASK_QUARANTINED})")
            self._quarantined[task_id] = reason
            return LOOP_PATTERN_QUARANTINED
        return ""

    def observe_success(self, task_id: str) -> None:
        for k in [k for k in self._counts if k[0] == task_id]:
            del self._counts[k]

    def is_quarantined(self, task_id: str) -> bool:
        return task_id in self._quarantined

    def reason_for(self, task_id: str) -> str:
        return self._quarantined.get(task_id, "")

    def quarantined_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._quarantined))

    def seed_quarantined(self, reasons: dict[str, str]) -> None:
        """FIX-B1 — re-import journaled terminal quarantine (boot path).

        ``reasons`` maps task_id → the journaled quarantine reason. Seeded
        entries behave exactly like live ones (dispatch/requeue refuse with
        the same human-visible reason). Never overwrites a live entry.
        """
        for task_id, reason in reasons.items():
            if task_id and task_id not in self._quarantined:
                self._quarantined[task_id] = reason

    def seed_streak(self, task_id: str, failure_class: str, count: int) -> None:
        """FIX-B1 — re-import a consecutive-failure streak (boot path).

        ``count`` is the trailing same-class run re-derived from the
        journal; capped below the threshold (seeding never quarantines by
        itself — the next live failure trips it honestly).
        """
        if not task_id or count <= 0:
            return
        capped = min(count, max(self.repeat_threshold - 1, 0))
        if capped <= 0:
            return
        key = (task_id, failure_class)
        if self._counts.get(key, 0) < capped:
            self._counts[key] = capped


# FIX-B2 — closed failure-class map for quarantine streaks (deterministic,
# no model judgment). The TRANSIENT family merges every retryable
# transport/provider condition so a flapping provider cannot evade the
# threshold by alternating incident detail; EMPTY (typed negative) and
# OTHER stay distinct; blank/unknown reasons count as UNKNOWN (never a
# free pass). Coarse by design: quarantine is the early park, the
# task-level max_retries chain remains the hard backstop.
_TRANSIENT_FAMILY_MARKERS: tuple[str, ...] = (
    "transient", "timeout", "timed out", "throttl", "429", "unavailable",
    "could not search", "connection", "dns", "refused", "reset",
    "5xx", "500", "502", "503", "504", "retry",
)
_EMPTY_MARKERS: tuple[str, ...] = ("empty", "nothing found", "no literature")


def classify_failure_signature(signature: str) -> str:
    """Map a free-text failure reason to a closed streak class."""
    lowered = (signature or "").casefold()
    if not lowered.strip():
        return "UNKNOWN"
    if any(marker in lowered for marker in _TRANSIENT_FAMILY_MARKERS):
        return "TRANSIENT"
    if any(marker in lowered for marker in _EMPTY_MARKERS):
        return "EMPTY"
    return "OTHER"


def is_explicit_knob(operator: object | None, name: str, default: object) -> bool:
    """True iff ``operator`` explicitly carries a non-default ``name`` value.

    FIX-C2 support: distinguishes an operator-authored tightening (which
    must never be silently overridden) from an absent knob (where the
    liveness floor may fill in). Dicts are explicit by key presence;
    objects by deviation from the code-owned default.
    """
    if operator is None:
        return False
    if isinstance(operator, dict):
        return name in operator
    return getattr(operator, name, default) != default


def reimport_quarantine(conn: object, project_id: str) -> tuple[dict[str, str], dict[str, tuple[str, int]]]:
    """FIX-B1 — reload journaled quarantine state (read-only, no schema).

    Returns ``(quarantined, streaks)``: tasks whose latest terminal FAILED
    journal row still stands (currently FAILED) and carries the quarantine
    marker, plus trailing same-class failure runs for currently-live tasks
    (re-derived from consecutive FAILED-transition reasons, newest first).
    Pure SELECTs over the existing ``events``/``tasks`` tables — no writes,
    no new tables, no new event types. Empty maps on any query failure
    (e.g. pre-migration database) — boot never breaks on re-import.
    """
    quarantined: dict[str, str] = {}
    streaks: dict[str, tuple[str, int]] = {}
    try:
        execute = conn.execute  # type: ignore[attr-defined,union-attr]
        marker = f"%{LOOP_PATTERN_QUARANTINED}%"
        rows = execute(
            "SELECT e.task_id AS task_id, e.reason AS reason "
            "FROM events e JOIN tasks t "
            "ON t.task_id = e.task_id AND t.project_id = e.project_id "
            "WHERE e.project_id = ? AND e.event_type = 'TaskStatusChanged' "
            "AND e.to_state = 'FAILED' AND e.reason LIKE ? "
            "AND t.status = 'FAILED' "
            "ORDER BY e.event_id DESC",
            (project_id, marker),
        ).fetchall()
        for row in rows:
            task_id = row["task_id"]
            if task_id and task_id not in quarantined:
                quarantined[task_id] = str(row["reason"] or "")
        live = execute(
            "SELECT task_id FROM tasks WHERE project_id = ? "
            "AND status IN ('PENDING', 'READY', 'RETRYING', 'RUNNING')",
            (project_id,),
        ).fetchall()
        for live_row in live:
            task_id = live_row["task_id"]
            if not task_id or task_id in quarantined:
                continue
            history = execute(
                "SELECT reason FROM events "
                "WHERE project_id = ? AND task_id = ? "
                "AND event_type = 'TaskStatusChanged' "
                "AND to_state = 'FAILED' "
                "ORDER BY event_id DESC LIMIT 32",
                (project_id, task_id),
            ).fetchall()
            run_class = ""
            run_count = 0
            for event_row in history:
                failure_class = classify_failure_signature(
                    str(event_row["reason"] or ""))
                if run_count == 0:
                    run_class, run_count = failure_class, 1
                elif failure_class == run_class:
                    run_count += 1
                else:
                    break
            if run_count > 0:
                streaks[task_id] = (run_class, run_count)
    except Exception:  # noqa: BLE001 — pre-migration DB: boot with empty maps
        return {}, {}
    return quarantined, streaks


# ── DNS-rebinding guard (S2 pin mechanics, D5 scope) ──

_NON_GLOBAL_V6_NETS: tuple[str, ...] = ("fec0::/10", "3ffe::/16")


def _blocked_reason(address: str) -> str:
    """Named reason ``address`` may not be dialed, or "" when public."""
    try:
        ip = ipaddress.ip_address(address.partition("%")[0])
    except ValueError:
        return "non-address"
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _blocked_reason(str(mapped))
    if isinstance(ip, ipaddress.IPv6Address):
        for net in _NON_GLOBAL_V6_NETS:
            if ip in ipaddress.IPv6Network(net):
                return f"non-global v6 ({net})"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_multicast:
        return "multicast"
    if ip.is_reserved:
        return "reserved"
    if ip.is_private:
        return "private (RFC1918/ULA)"
    if not ip.is_global:
        return "not globally routable"
    return ""


def refuse_non_public_addresses(host: str, addresses: tuple[str, ...] | list[str]) -> None:
    """Refuse when ANY resolved address is non-public (fail-closed).

    Raises ``ValueError`` with the ``DNS_REBINDING_REFUSED`` code embedded —
    the live-fetch gate maps it to the typed refusal. A mixed
    public/private answer set is refused as a whole (S2 rule); an empty set
    is refused (nothing vetted to dial).
    """
    if not addresses:
        raise ValueError(
            f"{DNS_REBINDING_REFUSED}: host {host!r} resolved to no addresses")
    for address in sorted(set(addresses)):
        reason = _blocked_reason(address)
        if reason:
            raise ValueError(
                f"{DNS_REBINDING_REFUSED}: host {host!r} resolved to "
                f"non-public address {address} ({reason})")


def resolve_and_vet_host(
    host: str,
    resolve: Callable[[str], tuple[str, ...] | list[str]],
) -> tuple[str, ...]:
    """Resolve ``host`` and vet every address; return sorted addresses.

    ``resolve`` is injectable so tests drive it deterministically; production
    passes ``socket.getaddrinfo``-backed resolution. Refuses with
    ``DNS_REBINDING_REFUSED`` on any non-public address (fail-closed).
    """
    addresses = tuple(resolve(host))
    refuse_non_public_addresses(host, addresses)
    return tuple(sorted(set(addresses)))


# ── operator-config builders (narrow-only; duck-typed, no config import) ──


def _op_get(operator: object | None, name: str) -> object | None:
    if operator is None:
        return None
    if isinstance(operator, dict):
        return operator.get(name)
    return getattr(operator, name, None)


def build_envelope(operator: object | None = None) -> BudgetEnvelope:
    """Build the step/token envelope from operator knobs (narrow-only)."""
    return BudgetEnvelope(
        per_task_steps=narrow_int(
            _op_get(operator, "per_task_steps"),  # type: ignore[arg-type]
            DEFAULT_PER_TASK_STEPS, "per_task_steps"),
        per_tick_steps=narrow_int(
            _op_get(operator, "per_tick_steps"),  # type: ignore[arg-type]
            DEFAULT_PER_TICK_STEPS, "per_tick_steps"),
        per_run_steps=narrow_int(
            _op_get(operator, "per_run_steps"),  # type: ignore[arg-type]
            DEFAULT_PER_RUN_STEPS, "per_run_steps"),
        per_task_tokens=narrow_int(
            _op_get(operator, "per_task_tokens"),  # type: ignore[arg-type]
            DEFAULT_PER_TASK_TOKENS, "per_task_tokens"),
        per_tick_tokens=narrow_int(
            _op_get(operator, "per_tick_tokens"),  # type: ignore[arg-type]
            DEFAULT_PER_TICK_TOKENS, "per_tick_tokens"),
        per_run_tokens=narrow_int(
            _op_get(operator, "per_run_tokens"),  # type: ignore[arg-type]
            DEFAULT_PER_RUN_TOKENS, "per_run_tokens"),
    )


def build_wallclock(operator: object | None = None) -> WallClockCaps:
    """Build wall-clock caps; ``overall_deadline_seconds`` is the legacy key."""
    dispatch_raw = _op_get(operator, "overall_deadline_seconds")
    if dispatch_raw is None:
        dispatch_raw = _op_get(operator, "overall_dispatch_deadline_s")
    return WallClockCaps(
        dispatch_deadline_s=narrow_float(
            dispatch_raw,  # type: ignore[arg-type]
            DEFAULT_OVERALL_DISPATCH_DEADLINE_S,
            "overall_deadline_seconds"),
        per_tick_wall_s=narrow_float(
            _op_get(operator, "per_tick_wall_seconds"),  # type: ignore[arg-type]
            DEFAULT_PER_TICK_WALL_S, "per_tick_wall_seconds"),
        per_run_wall_s=narrow_float(
            _op_get(operator, "per_run_wall_seconds"),  # type: ignore[arg-type]
            DEFAULT_PER_RUN_WALL_S, "per_run_wall_seconds"),
    )


def build_retry_caps(operator: object | None = None) -> RetryCaps:
    """Build retry caps; accepts both autonomy and legacy retry key shapes."""
    max_retries_raw = _op_get(operator, "retry_max_retries")
    if max_retries_raw is None:
        max_retries_raw = _op_get(operator, "max_retries")
    base_raw = _op_get(operator, "retry_base_delay_seconds")
    if base_raw is None:
        base_raw = _op_get(operator, "base_delay_seconds")
    max_raw = _op_get(operator, "retry_max_delay_seconds")
    if max_raw is None:
        max_raw = _op_get(operator, "max_delay_seconds")
    caps = RetryCaps(
        max_retries=narrow_int(
            max_retries_raw,  # type: ignore[arg-type]
            DEFAULT_RETRY_MAX_RETRIES, "retry_max_retries"),
        base_delay_s=narrow_float(
            base_raw,  # type: ignore[arg-type]
            DEFAULT_RETRY_BASE_DELAY_S, "retry_base_delay_seconds"),
        max_delay_s=narrow_float(
            max_raw,  # type: ignore[arg-type]
            DEFAULT_RETRY_MAX_DELAY_S, "retry_max_delay_seconds"),
    )
    if caps.max_delay_s < caps.base_delay_s:
        raise ValueError(
            "P-AUTO-4 retry_max_delay_seconds must be >= "
            "retry_base_delay_seconds")
    return caps


def build_loop_threshold(operator: object | None = None) -> int:
    """Build the loop/quarantine repeat threshold (narrow-only)."""
    return narrow_int(
        _op_get(operator, "loop_repeat_threshold"),  # type: ignore[arg-type]
        DEFAULT_LOOP_REPEAT_THRESHOLD, "loop_repeat_threshold")


def build_rate_profiles(
    operator: object | None = None,
) -> dict[str, dict[str, object]]:
    """Build D5 rate profiles from operator knobs (narrow-only).

    Returns plain mappings (no tools import — the caller builds
    ``RateProfile``); a wider-than-code operator value is refused loudly.
    """
    openalex_rps = narrow_float(
        _op_get(operator, "openalex_rps"),  # type: ignore[arg-type]
        5.0, "openalex_rps")
    pubmed_rps = narrow_float(
        _op_get(operator, "pubmed_rps"),  # type: ignore[arg-type]
        3.0, "pubmed_rps")
    openalex_burst = narrow_int(
        _op_get(operator, "openalex_burst"),  # type: ignore[arg-type]
        5, "openalex_burst")
    pubmed_burst = narrow_int(
        _op_get(operator, "pubmed_burst"),  # type: ignore[arg-type]
        3, "pubmed_burst")
    openalex_cap = narrow_int(
        _op_get(operator, "openalex_daily_cap"),  # type: ignore[arg-type]
        1000, "openalex_daily_cap")
    pubmed_cap = narrow_int(
        _op_get(operator, "pubmed_daily_cap"),  # type: ignore[arg-type]
        1000, "pubmed_daily_cap")
    return {
        "openalex": {
            "rps": openalex_rps, "burst": openalex_burst,
            "concurrency": 2, "daily_cap": openalex_cap},
        "pubmed": {
            "rps": pubmed_rps, "burst": pubmed_burst,
            "concurrency": 1, "daily_cap": pubmed_cap},
    }
