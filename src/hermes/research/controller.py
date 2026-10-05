"""IDR-029 P7 controller — the deterministic C-tier execution surface.

The controller is the v6 Reconcile loop's execution slice (v6 §8
responsibilities 5–7): it claims READY work, executes it through the
existing write path, and recovers stalled work — without becoming a
scheduler, a second authority, a new event, or a new intent.

No new tables, no new events, no new intents. Every transition uses the
existing atomic ``transition_status`` (IDR-013); every acceptance goes
through ``accept_extraction_output`` → ``record_extraction`` (V6-P7-A2,
the self-bound write path); the ``scheduler_lock`` single-row table (v4
§8, migration 1) provides the advisory single-writer discipline.

Design record: IDR-029 (decision 1–5, IDR29-01..06 remediations).
Status: DESIGNED → IMPLEMENTED + TESTED by this module and
``tests/test_controller.py`` (the 10 golden fixtures).

ADV-02 (fencing): the scheduler lease is generation-fenced — a controller
captures the lock row's ``generation`` at acquisition, and every authoritative
write it performs re-validates ``owner + generation`` INSIDE the write
transaction (``_FencedConnection``). A live controller whose tick outlasts the
lease cannot keep writing after a second controller reclaimed the stale lock:
its write raises ``LockLostError`` and rolls back (fail closed). The lock
operations themselves run on the raw connection, unfenced.
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from hermes.core import utc_now
from hermes.core.graph import (
    GRAPH_QUERY_VERSION,
    ArtifactBlastEntry,
    artifact_blast_radius,
    blocked_roots,
    change_blast_radius,
    failure_cone,
    graph_result_hash,
    re_review_candidates,
)
from hermes.core.modes import OperationalMode
from hermes.core.task_status import (
    TaskStatus,
    TaskTransitionError,
    validate_task_transition,
)
from hermes.persistence.failure_classifications import (
    FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
    FAILURE_CLASSIFICATION_REF_PREFIX,
    FailureClassificationRepository,
    classifications_digest,
)
from hermes.persistence.program_obligations import (
    ProgramRequirementSatisfactionRepository,
    RequirementSatisfactionError,
)
from hermes.persistence.repositories import (
    ArtifactRepository,
    ExtractionTaskBindingError,
    ProjectRepository,
    TaskRepository,
    _append_event_to_db,
    _research_program_row_to_dict,
)
from hermes.persistence.source_outcomes import (
    SourceOutcomeBindingError,
    SourceOutcomeConflictError,
    SourceOutcomeRepository,
    SourceRepos,
)
from hermes.research.autonomy_caps import (
    BUDGET_PER_RUN_STEPS_EXCEEDED,
    BUDGET_PER_RUN_TOKENS_EXCEEDED,
    BUDGET_PER_TASK_STEPS_EXCEEDED,
    BUDGET_PER_TASK_TOKENS_EXCEEDED,
    BUDGET_PER_TICK_STEPS_EXCEEDED,
    BUDGET_PER_TICK_TOKENS_EXCEEDED,
    DEFAULT_PER_TICK_STEPS,
    LOOP_PATTERN_QUARANTINED,
    WALLCLOCK_RUN_DEADLINE_EXCEEDED,
    WALLCLOCK_TICK_DEADLINE_EXCEEDED,
    BudgetTracker,
    LoopDetector,
    build_envelope,
    build_loop_threshold,
    build_wallclock,
    is_explicit_knob,
    reimport_quarantine,
)
from hermes.research.extraction import (
    EXTRACT_TEMPLATE,
    ExtractionNotBoundToTask,
    ExtractionOutputRejected,
    accept_extraction_output,
)
from hermes.research.source_handlers import (
    HandlerResult,
    TaskScopedSourceRepos,
    UntrustedContentView,
)
from hermes.research.verdict_decisions import record_human_decision_once
from hermes.tools.providers.docling_provider import (
    DoclingDocument,
)
from hermes.tools.providers.docling_provider import (
    resolver_for_store_key as docling_store_key_resolver,
)

RECONCILE_DIGEST_VERSION = "4"  # Director-facing digest: v1 sections + the
                              # pending-proposals replay (IDR-040 §3 — the
                              # propose-observe loop: undecided proposals are
                              # replayed into the next digest run) + the
                              # applied Evidence Ladder transitions
                              # (IDR-041 AC-1..5 — rung advances are visible
                              # in the daily digest, read-only) + the
                              # bare-classification falsifications and the
                              # refutation re-review candidates (the Q-04
                              # blast radius seeded by applied REFUTED
                              # transitions — IDR-041 AC-2)


class LockLostError(RuntimeError):
    """ADV-02 — the controller's captured lease generation no longer matches
    the ``scheduler_lock`` row (another controller reclaimed the stale lease).
    Raised by the fenced connection when a stale controller attempts an
    authoritative write; the write rolls back — a stale controller fails
    closed, never silently lands a mutation.
    """


class SourceRetractionError(ValueError):
    """The retraction record was refused: the named artifact does not exist
    in the project or is not a source-type artifact. Nothing is written —
    recording a retraction FACT for a non-source is a false assertion."""


class _FencedConnection:
    """ADV-02 — wraps the authoritative connection so every WRITE statement
    is attributed to the controller's current lease generation.

    The check runs inside the caller's transaction (repositories open
    ``BEGIN IMMEDIATE`` before writing), so a reclaim committed by another
    controller is visible to the check and no writer can interleave between
    the check and the write. A stale controller's write raises
    ``LockLostError`` and the repository rolls back — the mutation never
    lands. The declared surface is exactly ``execute`` / ``executemany``
    (SQL, fenced per statement) and ``in_transaction`` (read-only status);
    every other attribute is refused — never delegated.

    Statement classification is hardened against the ADV-02 audit bypass
    classes (F1–F3): leading SQL comments are stripped before the first-token
    check (F1), ``WITH``-prefixed CTE writes are detected via paren-depth
    token scan (F2), and ``executescript`` is REJECTED loudly rather than
    silently delegating to the raw connection (F3 — the fence's contract is
    per-statement attribution; an unfenced multi-statement runner would be a
    silent hole). HD-01 closes the DELEGATION surface too: ``cursor`` is
    REJECTED loudly (a cursor would carry the raw connection and never run the
    generation check) and ``commit``/``rollback`` are REJECTED loudly (the
    repositories own transactions via SQL inside their write methods — an
    external method call would flush or discard a repository's open
    mid-write transaction).

    C-FIX-2 (C-F-03; owning gate DG-4 §14, PROTECTED by DG-6 §3): the open
    ``__getattr__`` delegation is REPLACED by a fail-closed explicit
    surface. The 11 raw-connection methods that could mutate or exfiltrate
    outside per-statement attribution are REJECTED loudly
    (``_REFUSED_DELEGATIONS``: load_extension, enable_load_extension,
    create_function, create_aggregate, backup, serialize, deserialize,
    set_authorizer, set_progress_handler, set_trace_callback, interrupt);
    every other undeclared attribute raises ``AttributeError`` instead of
    silently reaching the raw connection. A new passthrough requires an
    explicit allowlist entry with a reason — ``__getattr__`` never
    delegates again.

    FIX-FENCE-CLASSIFIER (IMPROVE-B B-F-01/B-F-02; owning gate DG-4 §14,
    PROTECTED by DG-6 §3): the scan is now literal/comment-AWARE (parens
    inside ``'...'`` / ``"..."`` / backtick / ``[...]`` / ``--`` / ``/* */``
    never count — the pre-fix naive tokeniser desynced on
    ``WITH t AS (SELECT ')') INSERT ...`` and skipped the statement keyword)
    and the classification is FAIL CLOSED: only the read allowlist
    (SELECT / VALUES / EXPLAIN — a ``WITH`` statement is read iff its
    top-level statement keyword is SELECT / VALUES) and the
    transaction-control carve-out (BEGIN / COMMIT / ROLLBACK / SAVEPOINT /
    RELEASE / END — the repositories' own rollback must always be able to
    discard an open transaction) pass unfenced. Every other first keyword —
    DML, DDL (CREATE / DROP / ALTER), PRAGMA, ATTACH / DETACH, VACUUM,
    REINDEX, ANALYZE — and any unknown or unparseable statement runs the
    generation check. Note: a ``PRAGMA name = value`` write cannot be told
    from a read by text alone, so PRAGMA is uniformly fenced; the shipped
    PRAGMA calls (``_configure_pragmas`` / ``integrity_check`` /
    ``foreign_key_check``) run on the raw connection at open/check time,
    never through the fence.
    """

    # Fail-closed classification: anything NOT in these two tuples is a
    # write. _READ_KEYWORDS is the read allowlist (a WITH statement is read
    # iff its top-level statement keyword is one of these);
    # _CONTROL_KEYWORDS is the transaction-control carve-out (deliberate:
    # fencing COMMIT/ROLLBACK would break every repository's own
    # transaction ownership — the method-form refusals above are what
    # close the external delegation surface).
    _READ_KEYWORDS = ("SELECT", "VALUES", "EXPLAIN")
    _CONTROL_KEYWORDS = ("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT",
                         "RELEASE", "END")

    def __init__(self, conn: Any, check: Callable[[], None]) -> None:
        self._conn = conn
        self._check = check

    @staticmethod
    def _scan_statement(sql: str) -> tuple[str, str]:
        """Literal/comment-aware first-keyword scan (B-F-01).

        Walks the statement once, left to right, and returns
        ``(kind, first_keyword)``:

        - ``kind == "empty"`` — nothing but whitespace / comments; never a
          write.
        - ``kind == "malformed"`` — an unterminated literal or block
          comment; fail closed (the caller fences it).
        - ``kind == "ok"`` — ``first_keyword`` is the first unquoted word.

        Inert regions never contribute to the word scan: string literals
        ``'...'`` (with ``''`` escapes), quoted identifiers ``"..."`` /
        backticks / ``[...]``, line comments ``--`` and block comments
        ``/* */``. This is the fix for the paren-desync bypass: the pre-fix
        code counted parens per whitespace token, so one ``)`` inside a
        literal or comment desynced the depth and the real keyword was
        skipped as "not depth 0".
        """
        n = len(sql)
        i = 0
        while True:
            while i < n and sql[i].isspace():
                i += 1
            if i >= n:
                return ("empty", "")
            ch = sql[i]
            if ch == "-" and sql.startswith("--", i):
                nl = sql.find("\n", i + 2)
                if nl < 0:
                    return ("empty", "")
                i = nl + 1
                continue
            if ch == "/" and sql.startswith("/*", i):
                end = sql.find("*/", i + 2)
                if end < 0:
                    return ("malformed", "")
                i = end + 2
                continue
            break
        start = i
        while i < n:
            ch = sql[i]
            if ch.isspace():
                break
            if ch == "(" or ch == ")" or ch == "," or ch == ";":
                break
            if ch == "'":
                i += 1
                while i < n:
                    if sql[i] == "'":
                        if i + 1 < n and sql[i + 1] == "'":
                            i += 2
                            continue
                        i += 1
                        break
                    i += 1
                else:
                    return ("malformed", "")
                continue
            if ch == '"' or ch == "`":
                quote = ch
                i += 1
                while i < n and sql[i] != quote:
                    i += 1
                if i >= n:
                    return ("malformed", "")
                i += 1
                continue
            if ch == "[":
                end = sql.find("]", i + 1)
                if end < 0:
                    return ("malformed", "")
                i = end + 1
                continue
            if ch == "-" and sql.startswith("--", i):
                break
            if ch == "/" and sql.startswith("/*", i):
                break
            i += 1
        return ("ok", sql[start:i])

    # The statement keywords a ``WITH`` prefix may continue into (SQLite's
    # grammar: WITH may precede exactly one SELECT / VALUES / INSERT /
    # UPDATE / DELETE / REPLACE). Anything else at depth zero after the CTE
    # declarations — including no match at all — is NOT recognized, and the
    # caller fails closed.
    _WITH_STATEMENT_KEYWORDS = ("SELECT", "VALUES", "INSERT", "UPDATE",
                                "DELETE", "REPLACE")

    @staticmethod
    def _cte_statement_keyword(sql: str) -> str | None:
        """The top-level statement keyword of a ``WITH`` statement.

        Inert-aware like ``_scan_statement``: literals / quoted identifiers /
        comments never contribute, and parens inside them never count. Scans
        for the first word token at paren depth zero whose upper-cased form
        is one of the WITH-continuation statement keywords; the CTE
        declarations (``[RECURSIVE] name [(cols)] AS (...)``) and their
        bodies sit either at depth > 0 or are non-keyword words, so they are
        skipped. Returns ``None`` when no continuation keyword is found —
        malformed, truncated, or a statement shape this scan does not
        recognize; the caller fails closed (fences it).
        """
        n = len(sql)
        i = 0
        depth = 0
        while True:
            while i < n and sql[i].isspace():
                i += 1
            if i >= n:
                return None
            ch = sql[i]
            if ch == "-" and sql.startswith("--", i):
                nl = sql.find("\n", i + 2)
                if nl < 0:
                    return None
                i = nl + 1
                continue
            if ch == "/" and sql.startswith("/*", i):
                end = sql.find("*/", i + 2)
                if end < 0:
                    return None
                i = end + 2
                continue
            break
        while i < n:
            ch = sql[i]
            if ch.isspace() or ch == ";":
                i += 1
                continue
            if ch == "(":
                depth += 1
                i += 1
                continue
            if ch == ")":
                depth -= 1
                if depth < 0:
                    return None
                i += 1
                continue
            if ch == ",":
                i += 1
                continue
            if ch == "'":
                i += 1
                while i < n:
                    if sql[i] == "'":
                        if i + 1 < n and sql[i + 1] == "'":
                            i += 2
                            continue
                        i += 1
                        break
                    i += 1
                else:
                    return None
                continue
            if ch == '"' or ch == "`":
                quote = ch
                i += 1
                while i < n and sql[i] != quote:
                    i += 1
                if i >= n:
                    return None
                i += 1
                continue
            if ch == "[":
                end = sql.find("]", i + 1)
                if end < 0:
                    return None
                i = end + 1
                continue
            if ch == "-" and sql.startswith("--", i):
                nl = sql.find("\n", i + 2)
                if nl < 0:
                    return None
                i = nl + 1
                continue
            if ch == "/" and sql.startswith("/*", i):
                end = sql.find("*/", i + 2)
                if end < 0:
                    return None
                i = end + 2
                continue
            start = i
            while i < n:
                c = sql[i]
                if (c.isspace() or c in "(),;'\"`["
                        or (c == "-" and sql.startswith("--", i))
                        or (c == "/" and sql.startswith("/*", i))):
                    break
                i += 1
            if depth == 0 and sql[start:i].upper() in \
                    _FencedConnection._WITH_STATEMENT_KEYWORDS:
                return sql[start:i].upper()
        return None

    @staticmethod
    def _is_write(sql: str) -> bool:
        """Fail-closed classifier over SQLite's dialect (B-F-01/B-F-02).

        A statement is a write unless it is a read (first keyword in the
        read allowlist, or a ``WITH`` statement whose top-level statement
        keyword is one) or transaction control (the repositories' own
        BEGIN/COMMIT/ROLLBACK/SAVEPOINT/RELEASE — see the carve-out note in
        the class docstring).        Anything else — DML, DDL, PRAGMA, ATTACH,
        VACUUM, unknown verbs — is fenced, and a malformed statement (an
        unterminated literal or block comment) is fenced (fail closed).
        """
        kind, first = _FencedConnection._scan_statement(sql)
        if kind == "empty":
            return False  # whitespace/comment-only never needs a check
        if kind == "malformed":
            return True   # unterminated literal/comment — fail closed
        if first.upper() in _FencedConnection._READ_KEYWORDS:
            return False
        if first.upper() in _FencedConnection._CONTROL_KEYWORDS:
            return False
        if first.upper() == "WITH":
            keyword = _FencedConnection._cte_statement_keyword(sql)
            return keyword not in _FencedConnection._READ_KEYWORDS
        return True

    def execute(self, sql: str, parameters=()):
        if self._is_write(sql):
            self._check()
        return self._conn.execute(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters):
        if self._is_write(sql):
            self._check()
        return self._conn.executemany(sql, seq_of_parameters)

    def executescript(self, sql_script: str):
        # F3 — the fence attributes EVERY write to the lease generation;
        # a multi-statement script defeats per-statement attribution. Fail
        # closed: reject loudly instead of silently delegating to the raw
        # connection (no current write path uses executescript).
        raise TypeError(
            "executescript is not supported on the fenced connection: "
            "multi-statement scripts cannot be attributed to the lease "
            "generation (ADV-02 audit F3) — use per-statement execute()")

    def cursor(self):
        # HD-01 — a cursor would carry the RAW connection and defeat
        # per-statement generation attribution: cursor().execute() never
        # runs the generation check, so a stale controller could mutate
        # the DB through it without ever tripping the fence. Fail closed:
        # reject loudly, like executescript (no shipped write path uses a
        # cursor — the repositories call execute()/executemany() only).
        raise TypeError(
            "cursor() is not supported on the fenced connection: a cursor "
            "would bypass per-statement lease-generation attribution "
            "(HD-01) — use execute()/executemany()")

    def commit(self):
        # HD-01 — the repositories OWN transactions (BEGIN IMMEDIATE ...
        # COMMIT/ROLLBACK via execute(), never a method call). An external
        # commit() would flush a repository's open transaction mid-write —
        # rows committed, edges not: the two-transaction atomicity broken.
        raise TypeError(
            "commit() is not supported on the fenced connection: the "
            "repositories own transactions and commit via SQL inside their "
            "own write methods (HD-01)")

    def rollback(self):
        # HD-01 — same ownership: an external rollback() would silently
        # discard a repository's uncommitted work mid-transaction.
        raise TypeError(
            "rollback() is not supported on the fenced connection: the "
            "repositories own transactions and roll back via SQL inside "
            "their own write methods (HD-01)")

    # C-FIX-2 (C-F-03) — the fail-closed delegation verdict table. Every
    # name below exists on the raw ``sqlite3.Connection`` and would bypass
    # the per-statement lease-generation attribution the fence guarantees;
    # all 11 are REFUSED. What MAY pass is deliberately tiny: the
    # ``in_transaction`` read-only status property below (the repositories
    # and the gateway read it before deciding to ROLLBACK — it cannot
    # mutate state) plus the SQL entry points ``execute``/``executemany``
    # defined above (their BEGIN/COMMIT/ROLLBACK statements ride the
    # ``_CONTROL_KEYWORDS`` carve-out). Nothing else delegates.
    _REFUSED_DELEGATIONS = (
        "load_extension",         # native code loading — arbitrary execution
        "enable_load_extension",  # arms load_extension
        "create_function",        # registers executable callbacks (UDF)
        "create_aggregate",       # registers executable callbacks (UDA)
        "backup",                 # writes a full DB image to another DB
        "serialize",              # exfiltrates the whole DB as bytes
        "deserialize",            # replaces DB content from raw bytes
        "set_authorizer",         # mutates the connection's SQL policy
        "set_progress_handler",   # installs executable callbacks
        "set_trace_callback",     # installs executable callbacks
        "interrupt",              # cancels in-flight statements
    )

    @property
    def in_transaction(self) -> bool:
        """The ONE passthrough (C-FIX-2): read-only transaction status.

        Repositories and the gateway read ``in_transaction`` before issuing
        a ROLLBACK; it cannot mutate state, so it passes unfenced. Declared
        as a property so the surface is explicit (pyright-visible, never
        looked up through ``__getattr__``).
        """
        return self._conn.in_transaction

    def __getattr__(self, name: str) -> Any:
        """Fail closed (C-FIX-2): no silent delegation to the raw connection.

        The refused table is loud (``TypeError``) for the 11 known
        bypass-capable methods, mirroring the F3/HD-01 method refusals;
        anything else raises ``AttributeError`` naming the attribute — so a
        new delegation is an explicit, reviewable allowlist entry with a
        reason, never an accident.
        """
        if name in _FencedConnection._REFUSED_DELEGATIONS:
            raise TypeError(
                f"{name} is not supported on the fenced connection: it would "
                f"bypass per-statement lease-generation attribution "
                f"(C-F-03/C-FIX-2, DG-4 §14 / DG-6 §3) — delegation is "
                f"fail-closed; add an explicit allowlist entry with a reason "
                f"if a legitimate path needs it")
        raise AttributeError(
            f"fenced connection refuses undeclared attribute {name!r}: the "
            f"delegation surface is fail-closed (C-FIX-2, C-F-03) — declared "
            f"surface is execute()/executemany()/in_transaction")


# Default hard per-tick model-call cap (liveness floor — IDR-029 Decision 5).
DEFAULT_MAX_CALLS_PER_TICK = 8
# Default lease: a RUNNING task whose last_heartbeat is older than this is
# stale and enters the NO_SIGNAL ladder (v4 §19; IDR-029 Decision 4).
DEFAULT_LEASE_SECONDS = 60
# C2 — mid-execution heartbeat refresh interval (seconds): the RUNNING
# task's liveness floor while a long handler/model call executes. 30s <
# the 60s lease, so a fresh refresh always precedes lease expiry.
DEFAULT_HEARTBEAT_REFRESH = 30.0
# F15 — the refresh horizon (seconds): mid-execution refreshes stop after
# this much CONTINUOUS refreshing, so a genuinely HUNG execution (model call
# never returns) goes stale after `horizon + lease_seconds` and enters the
# NO_SIGNAL ladder — the fence makes the re-execution safe. A long-but-live
# execution shorter than the horizon is protected end to end. THE CLIFF: the
# refresher exits PERMANENTLY once the horizon is exhausted (or on any failed
# refresh), so a handler running LONGER than the horizon is discard-and-
# re-execute territory — its lease goes stale, a second controller reclaims
# and re-executes, and the late-returning handler's own writes fail the
# fence (exactly-once via the recovery ladder, never a second claim).
# Tune per deployment (the operator owns the hang-vs-slow tradeoff).
DEFAULT_HEARTBEAT_REFRESH_HORIZON = 300.0


@dataclass
class TickResult:
    """One tick's outcome. ``idle`` is empty when work was dispatched."""

    idle: str = ""                     # "", "no_eligible", "mode", "lock_held"
    dispatched: list[str] = field(default_factory=list)
    succeeded: list[str] = field(default_factory=list)
    retried: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    waiting_human: list[str] = field(default_factory=list)
    unhandled: list[str] = field(default_factory=list)
    recovery: list[str] = field(default_factory=list)   # tasks the recovery pass touched
    model_calls: int = 0
    ordering_policy_version: str = ""   # Q-02 §9: the applied task-ordering policy


class _HeartbeatRefresher:
    """Refresh a RUNNING task's ``last_heartbeat`` every ``interval`` seconds
    while the worker executes it (red-team C2): a long execution can no
    longer be NO_SIGNAL-reclaimed by a second controller mid-run. Daemon
    thread sharing the lease holder's fenced connection (the ONLY writer),
    so a lost lease fails the write (LockLostError) instead of the tick —
    the loop exits on the first failed refresh; the fence owns the truth.
    EXITS ARE PERMANENT: once the bounded horizon is exhausted (or a
    refresh fails), the refresher never restarts — a handler that outlives
    ``heartbeat_refresh_horizon`` is discard-and-re-execute territory (the
    stale lease is reclaimed and the task re-executes exactly once via the
    recovery ladder; the late handler's writes fail the fence).
    Cooperative stop: the tick sets the event and never waits on the
    thread beyond the current sleep."""

    def __init__(self, refresh: Callable[[], None], interval: float,
                 max_refreshes: int | None = None):
        self._refresh = refresh
        self._interval = max(interval, 0.01)
        # F15 — the bounded horizon: after max_refreshes, refreshes stop so a
        # genuinely hung execution goes stale and becomes reclaimable.
        self._max_refreshes = max_refreshes
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name="hermes-heartbeat-refresher",
            daemon=True)
        self._count = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._refresh()
                with self._lock:
                    self._count += 1
                    if (self._max_refreshes is not None
                            and self._count >= self._max_refreshes):
                        return
            except Exception:  # noqa: BLE001 — the write failed (lease lost);
                return      # further refreshes are futile, never a crash


class Controller:
    """Deterministic single-tick loop over the existing task graph.

    Parameters
    ----------
    conn : the authoritative SQLite connection.
    project_id : the project this controller drives.
    extract_fn : Callable[[dict, UntrustedContentView], ExtractionDraft] —
        the SINGLE injection point for the deferred C-tier model call
        (IDR-028 Decision 5). The contract: ``(task, untrusted)`` → an
        ``ExtractionDraft`` whose ``source_ref`` equals
        ``task.spec.source_ref`` (the binding enforces it, V6-P7-A2-01).
        M3 (trust boundary): the task's SOURCE CONTENT is read only via
        the ``untrusted`` view (``UntrustedContentView``) — a judgment
        callable never receives an unenveloped ``str`` of source text; the
        envelope's string forms never carry the payload. ``None`` disables
        EXTRACT dispatch (fail-closed).
    gate_verdict_fn : Callable[[dict], bool] — deterministic verdict for
        GATE tasks (IDR29-06: only gates whose verdict is closed over state
        the controller can read). ``None`` disables GATE dispatch
        (fail-closed — the controller never auto-passes a gate).
    task_handlers : dict[str, Callable] — per-spec-template handlers for
        non-EXTRACT AGENT_TASKs (the P3 evidence-task slices populate
        these). HD-02: every entry must expose ``build_context(task,
        project_id, repos)`` (the ``SourceHandler`` shape) — the controller
        dispatches ONLY the typed capability bundle, never a bare
        ``(task, fenced, repos)`` tuple; a handler without a builder fails
        closed. An AGENT_TASK with no handler is left READY with a
        diagnostic, never silently SUCCEEDED.

    M3 — the untrusted-input wrapper requirement at ALL THREE injection
    points (extract_fn / gate_verdict_fn / task_handlers), mandatory
    before any LLM wiring: fetched/search source text is read ONLY via
    ``UntrustedContent`` (the handler context's ``untrusted`` view) — a
    judgment callable never receives an unenveloped ``str`` of source
    content, and the envelope's string forms never carry the payload, so
    a prompt-injection payload cannot reach a model call, a log, or an
    error message accidentally. The typed envelope is defined in
    ``hermes.security.boundaries``.
    artifact_store : the filesystem artifact store for FETCH payload bytes
        (the source-slice repository persists payloads with the outcome,
        IDR-013). None is valid for search-only wiring; a fetch outcome
        with no store fails closed.
    owner : the controller's lock identity (defaults to a fresh uuid).
    clock : injectable clock (deterministic tests).
    lease_seconds : stale-heartbeat threshold (v4 §19).
    max_calls_per_tick : hard per-tick model-call cap (liveness floor).
    """

    def __init__(
        self,
        conn: Any,
        *,
        project_id: str,
        extract_fn: Callable[[dict, UntrustedContentView], Any] | None = None,
        gate_verdict_fn: Callable[[dict], bool] | None = None,
        task_handlers: dict[str, Callable[[dict], Any]] | None = None,
        owner: str | None = None,
        clock: Callable[[], str] | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_calls_per_tick: int = DEFAULT_MAX_CALLS_PER_TICK,
        artifact_store: Any = None,
        enable_epistemic_ordering: bool = True,
        enable_exploration_floor: bool = False,
        floor_policy: Any = None,
        heartbeat_refresh_interval: float = DEFAULT_HEARTBEAT_REFRESH,
        heartbeat_refresh_horizon: float = DEFAULT_HEARTBEAT_REFRESH_HORIZON,
        autonomy_operator: Any | None = None,
        budget_tracker: BudgetTracker | None = None,
        loop_detector: LoopDetector | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        import uuid

        self._conn = conn  # RAW — used only for the lock operations themselves
        self._project_id = project_id
        self._extract_fn = extract_fn
        self._gate_verdict_fn = gate_verdict_fn
        self._task_handlers = task_handlers or {}
        self._owner = owner or f"controller-{uuid.uuid4().hex[:12]}"
        self._clock = clock or utc_now
        self._lease_seconds = lease_seconds
        self._max_calls_per_tick = max_calls_per_tick
        # P-AUTO-4 envelopes (deterministic, no model judgment in breach path):
        # narrow-only operator knobs build the step/token envelope, the
        # wall-clock caps, and the loop/quarantine threshold — a wider-than-
        # code operator value is refused loudly at construction (never
        # silently clamped). Injected tracker/detector let tests drive exact
        # breach sequences; production owns one per controller lifetime.
        import time as _time

        self._monotonic: Callable[[], float] = monotonic or _time.monotonic
        self._wallclock = build_wallclock(autonomy_operator)
        if budget_tracker is not None:
            # Test-only seam (audit NOTE): injected trackers bypass the
            # narrow-only builders — production always builds via
            # build_envelope so operator values are ceiling-checked.
            self._budget = budget_tracker
        else:
            envelope = build_envelope(autonomy_operator)
            # FIX-C2 — the per-tick floor is applied, never silently:
            # an EXPLICIT operator tightening below max_calls_per_tick is
            # refused loudly (an operator cap must never be widened behind
            # its back); an absent knob inherits the liveness floor so the
            # F15 cap-sweep keeps needed == ceil(n/cap) at every cap.
            if envelope.per_tick_steps < max_calls_per_tick:
                if is_explicit_knob(autonomy_operator, "per_tick_steps",
                                    DEFAULT_PER_TICK_STEPS):
                    raise ValueError(
                        f"P-AUTO-4 per_tick_steps={envelope.per_tick_steps!r} "
                        f"undercuts max_calls_per_tick={max_calls_per_tick!r} "
                        f"— tighten both knobs together (refuse-or-record, "
                        f"never silent override)")
                import dataclasses as _dc

                envelope = _dc.replace(
                    envelope, per_tick_steps=max_calls_per_tick)
            self._budget = BudgetTracker(envelope=envelope)
        if loop_detector is not None:
            self._loops = loop_detector
        else:
            self._loops = LoopDetector(
                repeat_threshold=build_loop_threshold(autonomy_operator))
        self._run_start: float | None = None
        self._tick_start: float | None = None
        # C2 — mid-execution liveness: refresh the RUNNING task's heartbeat
        # while a long handler/model call executes, so a second controller
        # can never NO_SIGNAL-reclaim it (the lease expiry reclaim window).
        self._heartbeat_refresh_interval = heartbeat_refresh_interval
        # F15 — refresh stops after this many CONTINUOUS seconds so a hung
        # execution becomes reclaimable; a live execution is protected for
        # the whole horizon (operator-owned hang-vs-slow tradeoff).
        self._heartbeat_refresh_horizon = heartbeat_refresh_horizon
        self._heartbeat_refreshes = 0
        # Q-02 Model B: the ratified deterministic ordering policy applies at
        # dispatch. False restores the baseline created_at order (removal test).
        self._enable_epistemic_ordering = enable_epistemic_ordering
        # C4 exploration floor (ratified design gate §2–§5): a versioned
        # RESERVATION clause in the Q-02 ordering policy — it permutes the
        # pure-policy output, never admits/gates/budgets/expands the cap.
        # OFF by default (Delta=0): enabling amends the policy string and
        # bumps the policy version (the ``-floor.1`` suffix), so the
        # dispatch record shows exactly which ordering policy ran (Q-02 §9).
        # AC-3 fail-closed: a floor_slots >= max_calls_per_tick
        # configuration is REJECTED at construction, never clamped.
        from hermes.research.evaluation import FloorPolicy
        self._floor_policy = floor_policy or FloorPolicy()
        self._enable_exploration_floor = bool(
            enable_exploration_floor and enable_epistemic_ordering)
        if self._enable_exploration_floor:
            self._floor_policy.validate_capacity(max_calls_per_tick)
        self._lock_generation: int | None = None
        # Any (not `_FencedConnection | None`) for pyright: the repos' `conn`
        # params are typed sqlite3.Connection and the fenced wrapper is
        # structural — consistent with this module's `conn: Any` convention.
        self._fenced: Any = None
        # Placeholders — rebuilt FENCED on every successful acquisition
        # (generation is only known then; see _refresh_fence).
        self._project_repo = ProjectRepository(conn, self._clock)
        self._task_repo = TaskRepository(conn, self._clock)
        self._artifact_store = artifact_store
        # Source-slice repos — rebuilt FENCED on every acquisition (SD2-03 /
        # HD-03: the per-tick SourceRepos bundle is the only repos a handler
        # sees; `repos._conn IS fenced` is fixture-asserted).
        self._artifacts_repo = ArtifactRepository(conn, self._clock)
        self._source_repo = SourceOutcomeRepository(
            conn, artifact_store, self._clock)
        self._repos = SourceRepos(
            artifacts=self._artifacts_repo, source=self._source_repo)
        # Q-05 read-only consumption (D8): rebuilt FENCED on every lock
        # acquisition; the digest never writes, so it is never an authority.
        self._failure_classification_repo = FailureClassificationRepository(
            conn, self._clock)
        # Q-02 IDR-038 §3.1: per-requirement satisfaction links (read-only at
        # dispatch; rebuilt FENCED on every acquisition).
        self._satisfaction_repo = ProgramRequirementSatisfactionRepository(
            conn, self._clock)
        self._notes: list[str] = []
        # MERGE-AUDIT-045-FIX C4 — condition -> index into self._notes, so
        # _note_once bounds growth by distinct condition rather than by tick
        # count. self._notes is never cleared, so an unbounded list would grow
        # for the controller's whole lifetime.
        self._note_index: dict[str, int] = {}
        # B3: in-memory set of proposal_ids that have been noted as refused
        # for EMIT_PARALLEL_REGIME_PROGRAM — notes at most once per controller
        # lifetime to avoid log spam across retry ticks.
        self._b3_refused_proposals: set[str] = set()
        # FIX-B1 — reload journaled quarantine state (read-only SELECTs, no
        # schema): the terminal quarantine marker + trailing failure streaks
        # survive restarts via the append-only journal. Seeded streaks are
        # capped below the threshold — only a live failure quarantines.
        quarantined, streaks = reimport_quarantine(conn, project_id)
        self._loops.seed_quarantined(quarantined)
        for seed_task_id, (seed_class, seed_count) in streaks.items():
            self._loops.seed_streak(seed_task_id, seed_class, seed_count)
        if quarantined:
            self._note_once(
                f"quarantine re-imported for {len(quarantined)} task(s) "
                f"from the journal: {sorted(quarantined)}",
                key="p-auto-4:quarantine-reimported")

    # ── public API ──

    @property
    def notes(self) -> list[str]:
        """Diagnostics surfaced during the last run — fail-closed refusals,
        tamper signals, undereferenceable refs. Read-only; the CLI and the
        digest consume it, nothing writes through it."""
        return list(self._notes)

    def quarantined_tasks(self) -> tuple[str, ...]:
        """P-AUTO-4 poison-task quarantine (human-visible, never silent).

        Tasks the loop detector parked after ``repeat_threshold`` consecutive
        same-signature failures — they stay FAILED, are excluded from
        requeue/re-execution, and leave only via an operator action.
        """
        return self._loops.quarantined_ids()

    def _estimate_tokens(self, task: dict) -> int:
        """Pre-claim admission estimate for one dispatch (P-AUTO-4).

        SOURCE_SEARCH => max_pages, SOURCE_FETCH => max_sources (spec bounds,
        fail-closed over-estimate); anything else => 1. Advisory-only: the
        post-execution charge uses MEASURED transport requests
        (HandlerResult.provider_requests); the estimate only gates admission
        so an undersized guess can never hide real egress.
        """
        spec = task.get("spec") or {}
        try:
            if isinstance(spec.get("max_pages"), int) and spec.get("max_pages", 0) > 0:
                return int(spec["max_pages"])
            if isinstance(spec.get("max_sources"), int) and spec.get("max_sources", 0) > 0:
                return int(spec["max_sources"])
        except (TypeError, ValueError):
            return 1
        return 1

    def _record_spent_tokens(self, task_id: str, amount: int) -> None:
        """FIX-A1 — record spent provider requests + note any overrun.

        Post-execution spends are facts, not grants: they record
        unconditionally (refusing would understate the wire) and any cap
        breach is noted human-visibly here while subsequent admissions
        refuse on the recorded totals.
        """
        code = self._budget.record_tokens(task_id, amount)
        if code:
            self._note_once(
                f"provider token budget overrun for {task_id}: {code} "
                f"(spent {amount}; further dispatches refuse)",
                key=f"p-auto-4:token-overrun:{task_id}")

    def _run_wall_exceeded(self) -> bool:
        if self._run_start is None:
            return False
        bound = self._wallclock.per_run_wall_s
        if bound <= 0:
            return False
        return self._monotonic() - self._run_start >= bound

    def _tick_wall_exceeded(self) -> bool:
        if self._tick_start is None:
            return False
        bound = self._wallclock.per_tick_wall_s
        if bound <= 0:
            return False
        return self._monotonic() - self._tick_start >= bound

    def _note_once(self, message: str, *, key: str | None = None) -> None:
        """Record a diagnostic once per **condition**, not once per wording.

        MERGE-AUDIT-045-FIX C4: the previous version suppressed repeats by
        comparing the whole rendered message, so a persistent fault whose text
        varies per tick defeated it — CPython embeds object addresses in many
        exception messages (``TypeError: ... <obj at 0x...>``), and with
        ``self._notes`` never cleared that grew the list without bound (200
        ticks of one fault -> 200 notes).

        ``key`` names the *condition* (a stable identity such as
        ``"plan-admission:incomplete:<program_id>"``), so the list is bounded by
        the number of distinct conditions rather than by the number of ticks.
        When the same condition re-reports with different wording the existing
        entry is refreshed in place rather than appended, which keeps the
        diagnostic current without growing the list. ``key`` defaults to the
        message, preserving the old message-identity behaviour for callers that
        pass no key.
        """
        k = message if key is None else key
        existing = self._note_index.get(k)
        if existing is not None:
            self._notes[existing] = message
            return
        self._note_index[k] = len(self._notes)
        self._notes.append(message)

    def tick(self) -> TickResult:
        """One pass: acquire lock → recovery → mode check → requeue+re-
        execute → discover → claim → execute → commit. Returns a structured
        outcome.

        A second live controller fails the lock and returns
        ``idle="lock_held"`` without dispatching anything.
        """
        if not self._acquire_lock():
            return TickResult(idle="lock_held")
        # P-AUTO-4 tick scope: wall-clock start + per-tick budget reset.
        self._tick_start = self._monotonic()
        self._budget.begin_tick()

        try:
            mode = self._project_repo.get_mode(self._project_id)
            # Recovery marks dead workers through the NO_SIGNAL ladder. This
            # runs in every mode (liveness is safety). The second-miss
            # NO_SIGNAL -> FAILED hop is mode-gated (F15-audit): the requeue
            # leg of Decision 4 only exists in ACTIVE ticks, so a worker
            # that dies while the wave is parked at a human gate (or
            # stopped) must stay NO_SIGNAL - FAILING it early strands the
            # task at FAILED forever (the same-pass requeue is skipped) and
            # the operator's later verdict never restarts it. The conclusive
            # second miss becomes conclusive once ACTIVE, where the chain
            # completes in the same pass.
            touched, recovery_failed = self._recovery_pass(mode)
            # P2 #3 diagnostic: while the wave is parked (AWAITING_HUMAN),
            # surface why on the notes channel if a parked gate's dep was
            # INVALIDATED after parking — the operator sees the escape
            # hatch exists. Diagnostic only; never a gate.
            # FIX-NOTES-DEDUP: routed through _note_once (keyed by gate) —
            # a parked wave reports the same condition every tick, and
            # _notes is never cleared.
            for key, line in self._parked_gate_invalidated_dep_notes():
                self._note_once(line, key=key)
            if mode is OperationalMode.AWAITING_HUMAN:
                # AUDIT self-heal: the mode is DERIVED from gate state — if
                # no gate is actually waiting, AWAITING_HUMAN is stale (e.g.
                # the final verdict's ACTIVE write failed and was surfaced,
                # or a crash window); re-derive ACTIVE and resume dispatch.
                waiting = self._fenced.execute(
                    "SELECT 1 FROM tasks "
                    "WHERE project_id = ? AND status = 'WAITING_HUMAN' "
                    "LIMIT 1", (self._project_id,)).fetchone()
                if waiting is None:
                    try:
                        self._project_repo.transition_mode(
                            self._project_id, OperationalMode.ACTIVE,
                            caused_by="controller",
                            reason="no gate waiting — stale AWAITING_HUMAN "
                                   "self-healed (audit)")
                        mode = OperationalMode.ACTIVE
                    except Exception as exc:  # noqa: BLE001 — fail-closed
                        self._note_once(
                            f"mode self-heal to ACTIVE refused: {exc}",
                            key="mode:self-heal:active")
            elif mode is OperationalMode.ACTIVE:
                # AUDIT self-heal (reverse): a gate is waiting but the mode
                # says ACTIVE — the park's AWAITING_HUMAN write failed (or
                # tampered state). Re-derive AWAITING_HUMAN so the wave
                # STOPS at the gate instead of dispatching past it.
                waiting = self._fenced.execute(
                    "SELECT 1 FROM tasks "
                    "WHERE project_id = ? AND status = 'WAITING_HUMAN' "
                    "LIMIT 1", (self._project_id,)).fetchone()
                if waiting is not None:
                    try:
                        self._project_repo.transition_mode(
                            self._project_id, OperationalMode.AWAITING_HUMAN,
                            caused_by="controller",
                            reason="gate waiting — stale ACTIVE mode "
                                   "self-healed (audit)")
                    except Exception as exc:  # noqa: BLE001 — fail-closed
                        self._note_once(
                            f"mode self-heal to AWAITING_HUMAN refused: "
                            f"{exc}",
                            key="mode:self-heal:awaiting-human")
                    return TickResult(
                        idle="waiting_human",
                        recovery=sorted(set(touched)),
                    )
            if mode is not OperationalMode.ACTIVE:
                return TickResult(
                    idle=f"mode:{mode.value}",
                    recovery=sorted(set(touched)),
                )

            # IDR-045 D1 — plan-admission pass (ACTIVE-only, pre-dispatch,
            # filtered head MAX(version) WHERE parent_program_id IS NULL — C1).
            # Eligibility: ACTIVE mode (above) + compiled primary head exists
            # and is parseable (uncompiled → no-op, not a tick failure).
            # Admission order is plan.ordered (C6: per-payload apply_intent
            # loop, NO bulk transaction — crash-resume k-of-n is observable).
            # Supersession: leave-in-place + admit-new-DAG + observable no-op
            # (C2 — old rows remain, new disjoint task_ids via _identity).
            self._plan_admission_pass()

            # Evidence Ladder APPLY (IDR-041 AC-1..5) — the deterministic
            # transition executor runs every ACTIVE tick with dispatch, so
            # ratified obligation/terminus facts advance ladder state.
            self._apply_evidence_ladder_pass()

            # ADR-041 B3: consume APPROVED PROPOSE_PARALLEL_REGIME_TEST
            # proposals — each approval emits a parallel-regime-test program.
            self._consume_approved_parallel_regime_proposals()

            # CHG-1 contradiction detection runs every ACTIVE tick on the
            # already-held lease / fence (lock-less core, mirroring the
            # ladder pass). A found conflict records a RECORD_CONTRADICTION
            # through the gateway; resolution stays operator-gated. Detector
            # failure is refusal-as-data (zero writes). Runs BEFORE
            # requeue/dispatch so newly-falsified classifications can mark
            # affected tasks invalid within the same tick.
            self._detect_contradictions_pass()

            # P-AUTO-1 — deterministic sequencer pass (ACTIVE-only, pre-dispatch).
            # Reads READY tasks + dependencies + terminal states + ladder/failure
            # signals; emits ADMIT_TASK/DETERMINISTIC for sequencing.
            self._sequencer_pass()

            # Requeue + re-execute is dispatch, so it only happens while the
            # project is ACTIVE (IDR-029 Decision 4).
            requeued = self._requeue_recovered(recovery_failed)
            reexecuted = self._re_execute_requeued(requeued)

            result = self._dispatch_pass()
            result.recovery = sorted(set(touched + requeued))
            result.succeeded.extend(reexecuted.succeeded)
            result.retried.extend(reexecuted.retried)
            result.failed.extend(reexecuted.failed)
            result.model_calls += reexecuted.model_calls
            return result
        except LockLostError:
            # ADV-02 — the lease was reclaimed mid-tick (a second controller
            # took the stale lock while this controller was live). Every
            # authoritative write this controller attempted failed closed and
            # rolled back; dispatch stops. B remains authoritative.
            return TickResult(idle="lock_lost")
        finally:
            self._release_lock()

    def run(self, max_ticks: int = 1000) -> list[TickResult]:
        """Tick until no eligible work remains or ``max_ticks`` is reached.

        Idempotent on re-run: a second ``run()`` over the same db finds no
        eligible work (criterion 10). P-AUTO-4 run scope: the per-run wall
        clock starts here and the run step/token counters reset (task-level
        counters persist — a poison task stays counted across runs).
        """
        outcomes: list[TickResult] = []
        self._run_start = self._monotonic()
        self._budget.run_steps = 0
        self._budget.run_tokens = 0
        for _ in range(max_ticks):
            if self._run_wall_exceeded():
                self._note_once(
                    f"run wall-clock exceeded "
                    f"({WALLCLOCK_RUN_DEADLINE_EXCEEDED}) — run stops, "
                    f"never a silent hang",
                    key="p-auto-4:run-wall-exceeded")
                outcomes.append(
                    TickResult(idle=WALLCLOCK_RUN_DEADLINE_EXCEEDED))
                break
            if self._budget.run_steps >= self._budget.envelope.per_run_steps:
                self._note_once(
                    f"run step budget exceeded "
                    f"({BUDGET_PER_RUN_STEPS_EXCEEDED}) — run stops",
                    key="p-auto-4:run-steps-exceeded")
                outcomes.append(TickResult(idle=BUDGET_PER_RUN_STEPS_EXCEEDED))
                break
            if self._budget.run_tokens >= self._budget.envelope.per_run_tokens:
                self._note_once(
                    f"run token budget exceeded "
                    f"({BUDGET_PER_RUN_TOKENS_EXCEEDED}) — run stops",
                    key="p-auto-4:run-tokens-exceeded")
                outcomes.append(
                    TickResult(idle=BUDGET_PER_RUN_TOKENS_EXCEEDED))
                break
            out = self.tick()
            outcomes.append(out)
            # Keep going while the tick did meaningful work: a dispatched
            # task, OR a recovery pass that touched a dead worker — the
            # NO_SIGNAL ladder's first pass (RUNNING → NO_SIGNAL) dispatches
            # nothing and NEEDS a second pass to FAILED → requeue →
            # re-execute (IDR-029 Decision 4).
            if out.idle or (not out.dispatched and not out.recovery):
                break
        return outcomes

    def note(self, message: str) -> None:
        """Record an audit note (used by the IDR29-02 lease-race branch)."""
        self._notes.append(message)

    def classification_proposals(self) -> dict:
        """READ-ONLY advisory digest of recorded failure classifications (D8).

        The reconcile/controller loop's consumption surface: feeds the
        repository read query through the pure ``classifications_digest`` so
        the Director can surface permitted-action proposals from recorded
        FALSIFIED/REFUTED classifications. Never writes, never executes,
        never creates — the ActionEvaluation posture (``evaluation.py``); the
        classification stays advisory metadata, unreachable as evidence.
        """
        rows = self._failure_classification_repo.classifications_for_project(
            self._project_id)
        return classifications_digest(rows)

    # ── Q-04: derived failure-propagation graph (read-only advisory) ──

    def _load_task_graph_state(
        self,
    ) -> tuple[dict[str, list[str]], dict[str, str], dict[str, str]]:
        """One read-only load of the project's task-graph state (Q-04 §3.1):
        the outgoing ``task_dependencies`` edges (project-scoped), task
        statuses, and Q-05 failure-classification labels. All ratified
        sources — nothing is written, nothing stored is derived (F2)."""
        deps = self._conn.execute(
            """SELECT d.task_id, d.depends_on_task_id
               FROM task_dependencies d
               JOIN tasks t ON t.task_id = d.task_id
               WHERE t.project_id = ?""",
            (self._project_id,),
        ).fetchall()
        dependents: dict[str, list[str]] = {}
        for r in deps:
            # task_dependencies(task_id, depends_on_task_id): the TASK depends
            # on the upstream — so the upstream's dependents include the task.
            dependents.setdefault(r["depends_on_task_id"], []).append(
                r["task_id"])
        statuses = {
            r["task_id"]: r["status"] for r in self._conn.execute(
                "SELECT task_id, status FROM tasks WHERE project_id = ?",
                (self._project_id,)).fetchall()}
        labels = {
            row["task_id"]: row["metadata"].get("failure_class")
            for row in self._failure_classification_repo
            .classifications_for_project(self._project_id)
            if row.get("task_id") and row["metadata"].get("failure_class")}
        return dependents, statuses, labels

    def failure_cone(self, seed_task_ids: list[str]) -> dict:
        """READ-ONLY advisory (Q-04 §3.4): the transitive dependents blocked
        by seed tasks that are not SUCCEEDED, each labeled with the FIRST
        blocking ancestor + status + its Q-05 classification label. Version-
        bound, hashed, never persisted — the classifications_digest pattern.
        The controller's eligibility logic is untouched: this is the
        TRANSITIVE view of the same predicate, never a scheduler input."""
        dependents, statuses, labels = self._load_task_graph_state()
        cone = failure_cone(seed_task_ids, dependents, statuses, labels)
        payload = [{
            "task_id": e.task_id,
            "blocking_ancestor": e.blocking_ancestor,
            "blocking_status": e.blocking_status,
            "classification_label": e.classification_label,
        } for e in cone]
        return {
            "version": GRAPH_QUERY_VERSION,
            "items": payload,
            "content_hash": graph_result_hash("failure_cone", payload),
        }

    def blocked_roots(self) -> dict:
        """READ-ONLY advisory (Q-04 §3.2): tasks whose dependency closure
        contains a TERMINAL FAILED ancestor — permanently blocked until the
        failure is resolved by IDR-029 or a new iteration."""
        dependents, statuses, _ = self._load_task_graph_state()
        roots = blocked_roots(dependents, statuses)
        payload = list(roots)
        return {
            "version": GRAPH_QUERY_VERSION,
            "items": payload,
            "content_hash": graph_result_hash("blocked_roots", payload),
        }

    def change_blast_radius(self, seed_task_ids: list[str]) -> dict:
        """READ-ONLY advisory (Q-04 §3.2): the full transitive dependent
        closure of the seeds — "what would this change affect" regardless
        of current status."""
        dependents, _, _ = self._load_task_graph_state()
        radius = change_blast_radius(seed_task_ids, dependents)
        payload = list(radius)
        return {
            "version": GRAPH_QUERY_VERSION,
            "items": payload,
            "content_hash": graph_result_hash("blast_radius", payload),
        }

    # ── lock (advisory single-writer, v4 §8; lease-based — IDR29-03;
    #    generation-fenced — ADV-02) ──
    def artifact_blast_radius(self, seed_artifact_ids: list[str]) -> dict:
        """READ-ONLY advisory (Q-04 §5 extension): the transitive downstream
        closure over ``provenance_edges`` — every artifact that cites,
        derives from, uses as input, supersedes, or is justified by a seed
        artifact (transitively), so a retracted/superseded source artifact
        surfaces every downstream artifact needing re-review. Project-
        scoped, version-bound, hashed, never persisted, never writes —
        the Q-04 graph advisory posture (§4: CANNOT retract, invalidate,
        or modify anything)."""
        downstream: dict[str, list[tuple[str, str]]] = {}
        rows = self._conn.execute(
            """SELECT e.upstream_id, e.artifact_id, e.edge_type
               FROM provenance_edges e
               JOIN artifacts a ON a.artifact_id = e.artifact_id
               WHERE a.project_id = ?""",
            (self._project_id,),
        ).fetchall()
        for r in rows:
            downstream.setdefault(r["upstream_id"], []).append(
                (r["artifact_id"], r["edge_type"]))
        radius = artifact_blast_radius(seed_artifact_ids, downstream)
        payload = [{
            "artifact_id": e.artifact_id,
            "reached_via": e.reached_via,
            "edge_type": e.edge_type,
        } for e in radius]
        return {
            "version": GRAPH_QUERY_VERSION,
            "items": payload,
            "content_hash": graph_result_hash("artifact_blast_radius", payload),
        }

    def re_review_candidates(self, seed_artifact_ids: list[str]) -> dict:
        """READ-ONLY advisory: the artifact blast radius joined with
        OUTSTANDING Q-05 classifications (D8-valid, unflagged digest items)
        — the concrete re-review candidate set for a retracted/superseded
        source: every downstream artifact that carries a recorded
        classification. Consumes the ratified artifact_blast_radius +
        classifications_digest; never writes, never retracts, never
        executes — the Q-04 §4 advisory posture (names what needs
        re-review, changes nothing)."""
        radius = self.artifact_blast_radius(seed_artifact_ids)["items"]
        payload: list[dict] = []
        if radius:
            digest = self.classification_proposals()
            by_class_artifact = {
                i["classification_id"]: i for i in digest["items"]
                if not i["integrity_flags"]}
            rows = self._conn.execute(
                """SELECT e.upstream_id AS evidence_ref, e.artifact_id
                   FROM provenance_edges e
                   JOIN artifacts a ON a.artifact_id = e.artifact_id
                   WHERE a.project_id = ? AND e.edge_type = 'cites'""",
                (self._project_id,),
            ).fetchall()
            cite_map: dict[str, list[dict]] = {}
            for r in rows:
                item = by_class_artifact.get(r["artifact_id"])
                if item is not None:
                    cite_map.setdefault(r["evidence_ref"], []).append(item)
            entries = tuple(ArtifactBlastEntry(
                artifact_id=i["artifact_id"], reached_via=i["reached_via"],
                edge_type=i["edge_type"]) for i in radius)
            for c in re_review_candidates(entries, cite_map):
                payload.append({
                    "artifact_id": c.artifact_id,
                    "reached_via": c.reached_via,
                    "edge_type": c.edge_type,
                    "classification_refs": list(c.classification_refs),
                    "failure_classes": list(c.failure_classes),
                    "requires_human_confirmation":
                        c.requires_human_confirmation,
                })
        # CHG-1 contradiction seeds (advisory-only): OPEN contradiction
        # parties carrying outstanding classifications join the candidate
        # set with reached_via "contradiction". Appended after the
        # existing path without altering it — unrelated candidates keep
        # identical entries and relative order; the merged list is
        # re-sorted by artifact_id for determinism. Never mutates state.
        present = {p["artifact_id"] for p in payload}
        by_classification_id = {
            i["classification_id"]: i for i in (
                self.classification_proposals().get("items", [])
                if radius else [])
            if isinstance(i, dict) and not i.get("integrity_flags")}
        for party in self._open_contradiction_parties():
            if party in present:
                continue
            item = by_classification_id.get(party)
            if item is None or not item.get("failure_class_ref"):
                continue
            payload.append({
                "artifact_id": party,
                "reached_via": "contradiction",
                "edge_type": "contradiction",
                "classification_refs": [item["failure_class_ref"]],
                "failure_classes": [item.get("failure_class") or ""],
                "requires_human_confirmation": bool(
                    item.get("requires_human_confirmation")),
            })
            present.add(party)
        payload.sort(key=lambda p: p["artifact_id"])
        return {
            "version": GRAPH_QUERY_VERSION,
            "items": payload,
            "content_hash": graph_result_hash(
                "re_review_candidates", payload),
        }

    def _open_contradiction_parties(self) -> list[str]:
        """Sorted party artifact IDs of operationally active OPEN
        contradictions (delegates to the S-1 internal seam)."""
        from hermes.research.contradiction_candidates import (
            open_contradiction_parties,
        )
        return open_contradiction_parties(self._conn, self._project_id)

    def record_source_retraction(
        self, artifact_id: str, *, caused_by: str, reason: str,
    ) -> None:
        """Record the FACT of a source retraction — an audit event ONLY
        (append-only; nothing is retracted, invalidated, or modified here
        — the retraction authority stays where it already lives, Q-04 §4).
        Validated at admission: the artifact must exist in this project and
        be a source-type artifact (source_result / source_payload /
        source_search); otherwise the record is refused and nothing is
        written. The event type is the ratified v4 §8.1 catalog member
        SourceRetracted (ADV-05 — validated at the persistence boundary)."""
        row = self._conn.execute(
            "SELECT artifact_type FROM artifacts "
            "WHERE artifact_id = ? AND project_id = ?",
            (artifact_id, self._project_id),
        ).fetchone()
        if row is None:
            raise SourceRetractionError(
                f"refused source retraction: artifact {artifact_id!r} "
                f"does not exist in project {self._project_id!r}")
        if row["artifact_type"] not in ("source_result", "source_payload",
                                        "source_search"):
            raise SourceRetractionError(
                f"refused source retraction: artifact {artifact_id!r} "
                f"has type {row['artifact_type']!r}, not a source artifact")
        # Inside a tick the write is fenced (attributed to the lease); a
        # Director-side record outside a tick appends directly — an
        # append-only audit event touches no state machine, so the unfenced
        # append carries no lease-race hazard.
        conn = self._fenced if self._fenced is not None else self._conn
        _append_event_to_db(
            conn, self._clock, "SourceRetracted",
            self._project_id, caused_by=caused_by, reason=reason,
            artifact_ids=[artifact_id],
            payload={"artifact_id": artifact_id},
        )

    def retracted_source_review_candidates(self) -> dict:
        """READ-ONLY advisory: the re-review candidate set seeded by the
        RECORDED SourceRetracted events — exactly the downstream artifacts
        of retracted sources that carry an outstanding Q-05 classification.
        Fail-closed: an event whose artifact_ids_json is corrupt, or whose
        artifact no longer exists in the project, is skipped with an
        observable note — never a crash, never a silent seed."""
        rows = self._conn.execute(
            "SELECT * FROM events "
            "WHERE project_id = ? AND event_type = ?",
            (self._project_id, "SourceRetracted"),
        ).fetchall()
        seeds: list[str] = []
        for r in rows:
            raw = r["artifact_ids_json"] or []
            import json as _json
            try:
                ids = _json.loads(raw) if isinstance(raw, str) else (raw or [])
            except ValueError:
                self._note_once(
                    f"corrupt SourceRetracted event {r['event_id']!r} — "
                    f"artifact_ids_json is not JSON; no retraction seed",
                    key=f"read:corrupt-sourceretracted-notjson:"
                        f"{r['event_id']}")
                continue
            if not isinstance(ids, list) or not all(
                    isinstance(i, str) for i in ids):
                self._note_once(
                    f"corrupt SourceRetracted event {r['event_id']!r} — "
                    f"artifact_ids is not a string list; no retraction seed",
                    key=f"read:corrupt-sourceretracted-shape:"
                        f"{r['event_id']}")
                continue
            for aid in ids:
                exists = self._conn.execute(
                    "SELECT 1 FROM artifacts "
                    "WHERE artifact_id = ? AND project_id = ?",
                    (aid, self._project_id),
                ).fetchone()
                if exists:
                    seeds.append(aid)
                    continue
                # Ref-form seed ("source_result:<hash>" — the ratified
                # dereference identity, SD-05): resolve by content hash in
                # this project; the type prefix must match the row.
                prefix, sep, h = aid.partition(":")
                if sep:
                    row = self._conn.execute(
                        "SELECT artifact_id, artifact_type FROM artifacts "
                        "WHERE project_id = ? AND content_hash = ? "
                        "ORDER BY created_at LIMIT 1",
                        (self._project_id, h),
                    ).fetchone()
                    if row is not None and row["artifact_type"] == prefix:
                        seeds.append(row["artifact_id"])
                        continue
                self._note_once(
                    f"SourceRetracted event {r['event_id']!r} names "
                    f"artifact {aid!r} — not resolvable in project; skipped",
                    key=f"read:unresolvable-artifact:{r['event_id']}:{aid}")
        return self.re_review_candidates(sorted(set(seeds)))

    def pending_classification_proposals(self) -> list[dict]:
        """READ-ONLY replay of the propose-observe loop (IDR-040 §3): every
        admitted ClassificationActionProposed event whose gate state is
        PENDING_HUMAN_APPROVAL and which has NO ratified
        ClassificationActionDecision yet — the undecided set the Director
        replays into its next digest run. Deterministic (event_id order),
        fail-closed (a corrupt proposal payload is skipped with an
        observable note — never a crash, never a false pending item), and
        pure read: decisions are recorded through the gateway, never here."""
        rows = self._conn.execute(
            "SELECT event_id, correlation_id, payload_json, created_at "
            "FROM events "
            "WHERE project_id = ? AND event_type = ? "
            "ORDER BY event_id",
            (self._project_id, "ClassificationActionProposed"),
        ).fetchall()
        import json as _json
        pending: list[dict] = []
        for r in rows:
            try:
                payload = _json.loads(r["payload_json"] or "{}")
            except ValueError:
                self._note_once(
                    f"corrupt ClassificationActionProposed event "
                    f"{r['event_id']!r} — payload is not JSON; not replayed",
                    key=f"read:corrupt-proposal:{r['event_id']}")
                continue
            # F2 — the gate is RECOMPUTED from the classification's class,
            # never trusted from the stored admission state: a proposal
            # replays as pending iff its class actually requires human
            # confirmation. A stored state that contradicts the recomputed
            # gate is a tamper signal — noted, and the class wins.
            gate = self._classification_gate(payload.get(
                "classification_ref"), payload.get("action"))
            if gate is None:
                self._note_once(
                    f"proposal {r['correlation_id']!r} cites a "
                    f"classification that does not dereference — not "
                    f"replayed",
                    key="read:proposal-undereferenceable:"
                        f"{r['correlation_id']}")
                continue
            if not gate:
                if payload.get("state") == "PENDING_HUMAN_APPROVAL":
                    self._note_once(
                        f"proposal {r['correlation_id']!r} claims "
                        f"PENDING_HUMAN_APPROVAL but its class does not "
                        f"require human confirmation — tamper signal, "
                        f"not replayed",
                        key=f"read:proposal-tamper:{r['correlation_id']}")
                continue
            decided = self._conn.execute(
                "SELECT 1 FROM events "
                "WHERE event_type = ? AND correlation_id = ?",
                ("ClassificationActionDecision", r["correlation_id"]),
            ).fetchone()
            if decided is not None:
                continue
            pending.append({
                "proposal_id": r["correlation_id"],
                "classification_ref": payload.get("classification_ref"),
                "action": payload.get("action"),
                "candidate_artifact_ref": payload.get(
                    "candidate_artifact_ref"),
                "rationale": payload.get("rationale", ""),
                "proposed_at": r["created_at"],
            })
        return pending


    def _classification_gate(
        self, classification_ref: object, action: object,
    ) -> bool | None:
        """F2 recompute of the PROPOSAL gate (IDR-041 decision): a proposal
        needs human confirmation iff its CLASS requires it (FRAMING_ERROR)
        OR its ACTION is authority-shaped (REJECT_BRANCH /
        ROUTE_TO_SCOPE_REVIEW / PROPOSE_SCOPE_NARROWING). Both branches
        derive from the dereferenced classification metadata and the
        payload's action — never from any stored gate/state field. Returns
        None when the ref cannot be dereferenced or the metadata is corrupt
        (fail-closed: a missing or corrupt classification can never yield a
        false gate)."""
        if not isinstance(classification_ref, str) or not (
                classification_ref.startswith(
                    FAILURE_CLASSIFICATION_REF_PREFIX)):
            return None
        import json as _json

        from hermes.research.failure_classification import (
            FailureClass,
            PermittedAction,
            parse_contributing_factors,
            proposal_requires_human_confirmation,
        )
        row = self._conn.execute(
            "SELECT metadata_json FROM artifacts "
            "WHERE project_id = ? AND artifact_type = ? AND content_hash = ?",
            (self._project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
             classification_ref[len(FAILURE_CLASSIFICATION_REF_PREFIX):]),
        ).fetchone()
        if row is None:
            return None
        try:
            meta = _json.loads(row["metadata_json"] or "{}")
        except ValueError:
            return None
        try:
            failure_class = FailureClass(meta.get("failure_class"))
        except ValueError:
            return None
        try:
            action_member = (PermittedAction(action)
                             if isinstance(action, str) else None)
        except ValueError:
            return None
        if action_member is None:
            return None
        return proposal_requires_human_confirmation(
            failure_class, action_member,
            parse_contributing_factors(meta.get("contributing_factors")))

    def reconcile_digest(self) -> dict:
        """READ-ONLY Director-facing daily digest — the reconcile/controller
        loop's one-call surface: the Q-05 classification proposals, the
        Q-04 §5 re-review candidates seeded by recorded SourceRetracted
        events, the undecided PENDING_HUMAN_APPROVAL proposals replayed
        from the audit (the propose-observe loop), the applied Evidence
        Ladder transitions (IDR-041 AC-1..5), the bare-classification
        falsifications (IDR-041 AC-2 — the falsification FACTS), and the
        refutation re-review candidates (the Q-04 blast radius seeded by
        applied REFUTED transitions), version-bound and content-hashed as
        a composite. Everything the Director needs to ACT
        is here, and nothing here can act: never writes, never executes,
        never retracts — the classification/graph advisory posture.
        Deterministic (all sections are)."""
        import hashlib
        import json as _json
        proposals = self.classification_proposals()
        candidates = self.retracted_source_review_candidates()
        pending = self.pending_classification_proposals()
        ladder = self.evidence_ladder_transitions()
        falsifications = self.bare_classification_falsifications()
        refutations = self.refutation_review_candidates()
        body = {
            "digest_version": RECONCILE_DIGEST_VERSION,
            "classification_proposals": proposals,
            "re_review_candidates": candidates,
            "pending_proposals": pending,
            "ladder_transitions": ladder,
            "falsifications": falsifications,
            "refutation_review_candidates": refutations,
        }
        content_hash = hashlib.sha256(_json.dumps(
            body, sort_keys=True, separators=(",", ":"),
            default=str).encode("utf-8")).hexdigest()
        return {**body, "content_hash": content_hash}

    def propose_review_actions(
        self, *, candidate_artifact_ids: list[str] | None = None,
    ) -> dict:
        """The Director's permitted-action intents THROUGH the gateway
        (IDR-040 §2 — proposal-only, never executed). Consumes
        ``reconcile_digest()``; for each re-review candidate, emits one
        ``PROPOSE_CLASSIFICATION_ACTION`` intent per permitted action cited
        by its classifications, admitted by ``apply_intent`` (D3
        dereference + ratified action member + candidate existence are
        validated at the gateway). Idempotent: repeat digest runs duplicate
        nothing. The ACTION itself still requires its existing authority
        (ABANDON / EVIDENCE_TRANSITION / PROPOSE_RESEARCH_PROGRAM / S16) —
        this loop only PROPOSES."""
        from hermes.core.intents import Intent, IntentKind
        from hermes.research.gateway import GatewayRejection, apply_intent

        digest = self.reconcile_digest()
        candidates = digest["re_review_candidates"]["items"]
        if candidate_artifact_ids is not None:
            wanted = set(candidate_artifact_ids)
            candidates = [c for c in candidates
                          if c["artifact_id"] in wanted]
        by_ref = {i["failure_class_ref"]: i
                  for i in digest["classification_proposals"]["items"]
                  if i.get("failure_class_ref")}
        proposed: list[str] = []
        duplicates: list[str] = []
        rejected: list[dict] = []
        conn = self._fenced if self._fenced is not None else self._conn
        for c in candidates:
            for ref in c["classification_refs"]:
                item = by_ref.get(ref)
                if item is None:
                    continue
                for action in item["permitted_actions"]:
                    intent = Intent(
                        kind=IntentKind.PROPOSE_CLASSIFICATION_ACTION,
                        proposed_by="DIRECTOR",
                        origin_kind="deterministic",
                        origin_ref="propose_review_actions",
                        project_id=self._project_id,
                        justification=(
                            f"re-review candidate {c['artifact_id']} "
                            f"cited by {ref}"),
                        payload={
                            "classification_ref": ref,
                            "action": action,
                            "candidate_artifact_ref": c["artifact_id"],
                            "rationale": (
                                f"blast-radius downstream of a retracted "
                                f"source (via {c['edge_type']})"),
                        },
                    )
                    try:
                        result = apply_intent(conn, intent,
                                              clock=self._clock)
                        (duplicates if result.duplicate else proposed).append(
                            result.entity_id)
                    except GatewayRejection as exc:
                        rejected.append({
                            "candidate": c["artifact_id"],
                            "action": action,
                            "code": exc.code,
                            "detail": str(exc),
                        })
        return {"proposed": proposed, "duplicates": duplicates,
                "rejected": rejected}

    def propose_refutation_actions(self) -> dict:
        """The Director's re-review action intents THROUGH the gateway
        (IDR-041 AC-2 — proposal-only, never executed): for every surfaced
        REFUTATION review candidate (the Q-04 blast radius seeded by an
        applied REFUTED transition), emits one ``PROPOSE_CLASSIFICATION_ACTION``
        intent per DOWNSTREAM artifact — the REVIEW_DOWNSTREAM_IMPACT
        review obligation (advisory-shaped, EFFECTIVE — no human gate)
        cited against the falsification's own classification. Consumes
        ``reconcile_digest()``; the gateway re-validates the classification
        ref D3-dereference + candidate existence + action membership.
        Idempotent: repeat digest runs duplicate nothing (the same
        (classification_ref, action, candidate) returns the existing
        proposal). The ACTION itself still requires its existing authority
        — this loop only PROPOSES, closing the observe→act loop the digest
        v4 fold opened. Fail-closed per row: an unresolvable
        classification ref or an empty candidate set contributes nothing,
        never a crash."""
        from hermes.core.intents import Intent, IntentKind
        from hermes.research.gateway import GatewayRejection, apply_intent

        digest = self.reconcile_digest()
        fals = {i["transition_id"]: i
                for i in digest["falsifications"]["items"]
                if i.get("classification_ref")}
        proposed: list[str] = []
        duplicates: list[str] = []
        rejected: list[dict] = []
        conn = self._fenced if self._fenced is not None else self._conn
        for item in digest["refutation_review_candidates"]["items"]:
            classification_ref = fals.get(
                item["transition_id"], {}).get("classification_ref")
            if not classification_ref:
                continue  # falsification fact not resolvable — fail closed
            for d in item["downstream_artifacts"]:
                intent = Intent(
                    kind=IntentKind.PROPOSE_CLASSIFICATION_ACTION,
                    proposed_by="DIRECTOR",
                    origin_kind="deterministic",
                    origin_ref="propose_refutation_actions",
                    project_id=self._project_id,
                    justification=(
                        f"refutation downstream {d['artifact_id']} of "
                        f"{item['program_id']}:{item['hypothesis_ref']}"),
                    payload={
                        "classification_ref": classification_ref,
                        "action": "REVIEW_DOWNSTREAM_IMPACT",
                        "candidate_artifact_ref": d["artifact_id"],
                        "rationale": (
                            f"downstream of the falsified hypothesis "
                            f"{item['hypothesis_ref']!r} "
                            f"(via {d['edge_type']})"),
                    },
                )
                try:
                    result = apply_intent(conn, intent, clock=self._clock)
                    (duplicates if result.duplicate else proposed).append(
                        result.entity_id)
                except GatewayRejection as exc:
                    rejected.append({
                        "candidate": d["artifact_id"],
                        "action": "REVIEW_DOWNSTREAM_IMPACT",
                        "code": exc.code,
                        "detail": str(exc),
                    })
        return {"proposed": proposed, "duplicates": duplicates,
                "rejected": rejected}

    def register_operator(
        self, *, operator_id: str, token: str, name: str = "",
    ) -> dict:
        """The BOOTSTRAP surface for the ratified operator credential
        (red-team A4): an operator registers ONCE with a plaintext token —
        only its salted PBKDF2-HMAC-SHA256 hash is persisted (minimum token
        length enforced at register). From then on, every operator
        verdict (``resolve_human_gate`` / ``record_operator_decision``)
        must present the operator_id + the matching token; a verdict
        without a ratified credential is refused fail-closed with code
        ``OPERATOR``. Registering the same id with a different token is
        refused (the credential is ratifiable, never overwriteable).
        Never raises through the loop: refusals are surfaced as data."""
        from hermes.persistence.repositories import OperatorCredentialRepository
        conn = self._fenced if self._fenced is not None else self._conn
        try:
            row = OperatorCredentialRepository(conn, self._clock).register(
                operator_id, token, name)
        except ValueError as exc:
            return {"operator_id": operator_id, "rejected": True,
                    "code": "OPERATOR", "detail": str(exc)}
        return {"operator_id": operator_id, "name": row["name"],
                "created_at": row["created_at"], "rejected": False}

    def _verify_operator(self, operator_id: str, token: str) -> bool:
        """True iff (operator_id, token) matches a ratified credential —
        the proof-of-humanity gate every verdict surface enforces
        (red-team A4). Fail-closed: unknown operator or wrong token."""
        from hermes.persistence.repositories import OperatorCredentialRepository
        return OperatorCredentialRepository(self._conn).verify(
            operator_id, token)

    def resolve_human_gate(
        self, *, task_id: str, verdict: str, rationale: str = "",
        operator_id: str, operator_token: str,
    ) -> dict:
        """The FIRST-CLASS human-gate resolution surface (red-team A2):
        a ratified operator verdict on a PARKED HUMAN_GATE task — the
        missing leg that makes the three mandatory gates passable in
        shipped code (previously only hand-built `transition_status` +
        GatePassed event rows could pass them). Validated fail-closed at
        admission: the task exists in this project, is a HUMAN_GATE, and
        is WAITING_HUMAN (the one-verdict rule — a resolved gate cannot
        be re-resolved); the verdict is APPROVED or REJECTED. APPROVED
        re-dispatches the wave: WAITING_HUMAN -> RUNNING (the ratified
        edge) then the gate outcome -> SUCCEEDED, with GatePassed +
        HumanGateResolved audit events; REJECTED -> FAILED with
        GateFailed + HumanGateResolved. The project returns to ACTIVE
        when no gate remains waiting; a held scheduler lease refuses the
        verdict fail-closed with code ``LOCK`` (lease-held write, the
        record_operator_decision precedent). Never raises through the
        loop: every refusal is surfaced as data."""
        if verdict not in ("APPROVED", "REJECTED"):
            return {"task_id": task_id, "verdict": verdict,
                    "rejected": True, "code": "VERDICT",
                    "detail": "verdict must be APPROVED or REJECTED"}
        # F3 (audit): pre-validate the audit payload BEFORE any work or
        # write — an oversized rationale would otherwise fail the whole
        # verdict at the event boundary with a generic TRANSITION refusal.
        from hermes.persistence.event_validation import (
            DEFAULT_PAYLOAD_MAX_BYTES,
            EventValidationError,
            validate_payload_size,
        )
        try:
            validate_payload_size(
                {"verdict": verdict, "rationale": rationale,
                 "operator_id": operator_id},
                max_bytes=DEFAULT_PAYLOAD_MAX_BYTES)
        except EventValidationError as exc:
            return {"task_id": task_id, "verdict": verdict,
                    "rejected": True, "code": "RATIONALE",
                    "detail": f"rationale too large for the audit event: "
                              f"{exc}"}
        if not self._verify_operator(operator_id, operator_token):
            return {"task_id": task_id, "verdict": verdict,
                    "rejected": True, "code": "OPERATOR",
                    "detail": "no ratified operator credential for "
                              f"operator {operator_id!r} — verdict refused"}
        if not self._acquire_lock():
            return {"task_id": task_id, "verdict": verdict,
                    "rejected": True, "code": "LOCK",
                    "detail": "scheduler lease held by another controller "
                              "— verdict not recorded"}
        try:
            row = self._fenced.execute(
                "SELECT project_id, task_type, status FROM tasks "
                "WHERE task_id = ?", (task_id,)).fetchone()
            if row is None or row["project_id"] != self._project_id:
                return {"task_id": task_id, "verdict": verdict,
                        "rejected": True, "code": "NOT_FOUND",
                        "detail": f"task {task_id!r} is not in project "
                                  f"{self._project_id!r}"}
            if row["task_type"] != "HUMAN_GATE":
                return {"task_id": task_id, "verdict": verdict,
                        "rejected": True, "code": "NOT_HUMAN_GATE",
                        "detail": f"task {task_id!r} is not a HUMAN_GATE"}
            if row["status"] != TaskStatus.WAITING_HUMAN.value:
                # the one-verdict rule — a resolved gate is terminal
                return {"task_id": task_id, "verdict": verdict,
                        "rejected": True, "code": "NOT_WAITING",
                        "detail": f"task {task_id!r} is "
                                  f"{row['status']}, not WAITING_HUMAN "
                                  f"— already resolved"}
            # F14 (audit): the one-verdict rule ALSO consults the append-only
            # journal — a status TAMPERED back to WAITING_HUMAN after a
            # legit resolve must never permit a second verdict. The journal
            # has no UPDATE/DELETE path (it is the tamper-resistant truth);
            # the mutable status column is never the sole authority.
            already = self._fenced.execute(
                "SELECT 1 FROM events WHERE task_id = ? "
                "  AND event_type = 'HumanGateResolved' LIMIT 1",
                (task_id,)).fetchone()
            if already is not None:
                return {"task_id": task_id, "verdict": verdict,
                        "rejected": True, "code": "ALREADY_RESOLVED",
                        "detail": f"gate {task_id!r} already has a ratified "
                                  f"verdict on the audit — one verdict per "
                                  f"gate, terminal"}
            # P2 #3 diagnostic: the operator is resolving a parked gate —
            # surface WHY it is parked (an INVALIDATED dep) on the notes
            # channel right at the verdict surface. FIX-NOTES-DEDUP: the
            # same condition may already be noted from the tick surface;
            # keyed _note_once refreshes that entry instead of appending
            # a byte-identical second one.
            for key, line in self._parked_gate_invalidated_dep_notes():
                self._note_once(line, key=key)
            passed = verdict == "APPROVED"
            # Independent operator-loop verdict (red-team P2) — two fixes:
            # (1) ATOMICITY — the ENTIRE verdict lands in ONE fenced
            # transaction: WAITING_HUMAN -> RUNNING -> SUCCEEDED/FAILED +
            # GatePassed/GateFailed + HumanGateResolved commit or roll back
            # together, so a mid-resolve crash can never leave a stale
            # GatePassed (or half-transition) on the journal.
            # (2) ESCAPE HATCH — the F-10 READY->RUNNING dependency rule is
            # deliberately NOT applied to this hop: the gate parked only
            # after its deps SUCCEEDED, so a post-park INVALIDATION must not
            # strand the wave forever (permanent park with no escape). The
            # terminal operator verdict is the escape; dependency discipline
            # still holds downstream at each task's own claim
            # (_discover_eligible / transition_status F-10).
            import uuid as _uuid
            terminal = (TaskStatus.SUCCEEDED if passed
                        else TaskStatus.FAILED)
            conn = self._fenced
            conn.execute("BEGIN")
            try:
                validate_task_transition(TaskStatus.WAITING_HUMAN,
                                         TaskStatus.RUNNING)
                validate_task_transition(TaskStatus.RUNNING, terminal)
                ts = self._clock()
                conn.execute(
                    "UPDATE tasks SET status = ? WHERE task_id = ?",
                    (TaskStatus.RUNNING.value, task_id))
                conn.execute(
                    "UPDATE tasks SET started_at = ? WHERE task_id = ? "
                    "AND started_at IS NULL", (ts, task_id))
                _append_event_to_db(
                    conn, self._clock, "TaskStatusChanged",
                    project_id=self._project_id, task_id=task_id,
                    from_state=TaskStatus.WAITING_HUMAN.value,
                    to_state=TaskStatus.RUNNING.value,
                    correlation_id=str(_uuid.uuid4()),
                    caused_by="operator",
                    reason=f"human gate resolved: {verdict}")
                _append_event_to_db(
                    conn, self._clock,
                    "GatePassed" if passed else "GateFailed",
                    project_id=self._project_id, task_id=task_id,
                    caused_by="operator",
                    reason=f"human verdict {verdict}")
                conn.execute(
                    "UPDATE tasks SET status = ? WHERE task_id = ?",
                    (terminal.value, task_id))
                conn.execute(
                    "UPDATE tasks SET completed_at = ? WHERE task_id = ?",
                    (ts, task_id))
                _append_event_to_db(
                    conn, self._clock, "TaskStatusChanged",
                    project_id=self._project_id, task_id=task_id,
                    from_state=TaskStatus.RUNNING.value,
                    to_state=terminal.value,
                    correlation_id=str(_uuid.uuid4()),
                    caused_by="operator",
                    reason=("gate approved (human verdict)"
                            if passed else "gate rejected (human verdict)"))
                _append_event_to_db(
                    conn, self._clock, "HumanGateResolved",
                    project_id=self._project_id, task_id=task_id,
                    caused_by="operator",
                    reason=f"human gate {task_id} resolved: {verdict}",
                    payload={"verdict": verdict, "rationale": rationale,
                             "operator_id": operator_id},
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            remaining = self._fenced.execute(
                "SELECT 1 FROM tasks "
                "WHERE project_id = ? AND status = 'WAITING_HUMAN' "
                "  AND task_id != ? LIMIT 1",
                (self._project_id, task_id),
            ).fetchone()
            if remaining is None:
                # AUDIT: the mode write is NOT silently swallowed — a
                # failure is surfaced on the notes channel and the next
                # tick re-derives the mode from gate state (self-heal), so
                # a failed write can never strand the wave at
                # AWAITING_HUMAN with no gate left to resolve.
                try:
                    self._project_repo.transition_mode(
                        self._project_id, OperationalMode.ACTIVE,
                        caused_by="operator",
                        reason=f"human gate {task_id} resolved — wave "
                               f"may resume")
                except Exception as exc:  # noqa: BLE001 — audit, never silent
                    self._note_once(
                        f"mode transition to ACTIVE failed after gate "
                        f"{task_id} resolved: {exc} — the next tick will "
                        f"self-heal (audit)",
                        key=f"gate:mode-active-failed:{task_id}")
            return {"task_id": task_id, "verdict": verdict,
                    "rejected": False}
        except Exception as exc:  # noqa: BLE001 — fail-closed operator-verdict boundary
            return {"task_id": task_id, "verdict": verdict,
                    "rejected": True, "code": "TRANSITION",
                    "detail": str(exc)}
        finally:
            self._release_lock()

    def record_operator_decision(
        self, *, proposal_id: str, decision: str,
        rationale: str = "", operator_id: str, operator_token: str,
    ) -> dict:
        """The FIRST-CLASS operator-verdict ingestion surface (IDR-040 §3):
        records a ratified HUMAN decision on a pending classification-action
        proposal THROUGH the gateway — the RESOLVE_CLASSIFICATION_PROPOSAL
        intent built here (DETERMINISTIC, the internal role: the human has
        no agent profile, the deterministic layer ingests the operator
        verdict) and admitted by ``apply_intent``. The write is LEASE-HELD:
        the scheduler lock is acquired for the verdict's duration (an
        authoritative event-write must not interleave with a concurrent
        controller's lease; if another controller holds the lease the
        verdict is refused fail-closed with code ``LOCK`` and nothing is
        written). The gateway validates the proposal exists AND is
        PENDING_HUMAN_APPROVAL, the decision is APPROVED/REJECTED, and the
        one-verdict rule. Rejections are surfaced as data (never raised
        through the loop): a repeat of the same decision returns
        ``duplicate=True``; a contradictory verdict, a non-pending proposal,
        or a held lease returns ``{"rejected": True, ...}`` with the gateway
        code — nothing is written on a refusal. This is the only sanctioned
        path for the operator verdict; hand-built intents remain possible
        but are not the loop's contract."""
        from hermes.core.intents import Intent, IntentKind
        from hermes.research.gateway import GatewayRejection, apply_intent

        if not self._verify_operator(operator_id, operator_token):
            return {
                "proposal_id": proposal_id,
                "decision": decision,
                "rejected": True,
                "code": "OPERATOR",
                "detail": "no ratified operator credential for "
                          f"operator {operator_id!r} — verdict refused",
            }

        intent = Intent(
            kind=IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL,
            proposed_by="DETERMINISTIC",
            project_id=self._project_id,
            justification=(
                f"operator verdict {decision} on proposal {proposal_id}"),
            payload={
                "proposal_id": proposal_id,
                "decision": decision,
                "rationale": rationale,
                "operator_id": operator_id,
            },
        )
        if not self._acquire_lock():
            return {
                "proposal_id": proposal_id,
                "decision": decision,
                "rejected": True,
                "code": "LOCK",
                "detail": "scheduler lease held by another controller — "
                          "verdict not recorded",
            }
        try:
            result = apply_intent(self._fenced, intent, clock=self._clock)
            return {
                "proposal_id": proposal_id,
                "decision": decision,
                "duplicate": result.duplicate,
                "rejected": False,
            }
        except GatewayRejection as exc:
            return {
                "proposal_id": proposal_id,
                "decision": decision,
                "rejected": True,
                "code": exc.code,
                "detail": str(exc),
            }
        finally:
            self._release_lock()

    def record_scope_review_decision(
        self, *, proposal_id: str, scope_decision: str,
        rationale: str = "",
        operator_id: str, operator_token: str,
    ) -> dict:
        """The S16 scope-review intake (IDR-041 §4): records the human's
        scope verdict on an APPROVED ROUTE_TO_SCOPE_REVIEW /
        PROPOSE_SCOPE_NARROWING classification-action proposal — the first
        ratification-ref consumer. Builds the RECORD_SCOPE_REVIEW_DECISION
        intent (DETERMINISTIC, internal role) and admits it through the
        gateway: the proposal_id must be an APPROVED S16-routed approval
        whose action is in the classification's permitted set (recomputed,
        F2); the scope_decision must be a ratified ScopeReviewDecision; ONE
        SCOPE DECISION PER APPROVAL. The write is LEASE-HELD like the
        operator verdict (a concurrent controller's lease refuses the
        record fail-closed with code LOCK; the lease is released after).
        Rejections are surfaced as data, never raised through the loop.
        A4 parity (audit F7): like the other human-verdict surfaces, the
        scope verdict requires a RATIFIED operator credential — verified
        here, and re-verified at the gateway — an unratified call is
        refused with code OPERATOR and nothing is written. The record is
        evidence-of-ratification for the S16 authority's separate brief
        amendment — nothing here amends a brief."""
        from hermes.core.intents import Intent, IntentKind
        from hermes.research.gateway import GatewayRejection, apply_intent

        if not self._verify_operator(operator_id, operator_token):
            return {
                "proposal_id": proposal_id,
                "scope_decision": scope_decision,
                "rejected": True,
                "code": "OPERATOR",
                "detail": "no ratified operator credential for "
                          f"operator {operator_id!r} — scope decision "
                          f"refused",
            }

        intent = Intent(
            kind=IntentKind.RECORD_SCOPE_REVIEW_DECISION,
            proposed_by="DETERMINISTIC",
            project_id=self._project_id,
            justification=(
                f"scope review decision {scope_decision} on approval "
                f"{proposal_id}"),
            payload={
                "proposal_id": proposal_id,
                "scope_decision": scope_decision,
                "rationale": rationale,
                "operator_id": operator_id,
            },
        )
        if not self._acquire_lock():
            return {
                "proposal_id": proposal_id,
                "scope_decision": scope_decision,
                "rejected": True,
                "code": "LOCK",
                "detail": "scheduler lease held by another controller — "
                          "scope decision not recorded",
            }
        try:
            result = apply_intent(self._fenced, intent, clock=self._clock)
            return {
                "proposal_id": proposal_id,
                "scope_decision": scope_decision,
                "duplicate": result.duplicate,
                "rejected": False,
            }
        except GatewayRejection as exc:
            return {
                "proposal_id": proposal_id,
                "scope_decision": scope_decision,
                "rejected": True,
                "code": exc.code,
                "detail": str(exc),
            }
        finally:
            self._release_lock()

    # ── Step 7 (v6 §16.6): curated-knowledge surfaces ──

    def record_curation_decision(
        self, *, operation: str, program_ref: str, hypothesis_ref: str,
        source_binding_ref: str, source_decision_event_ref: str,
        signature_json: str, supersedes_ref: str = "",
        rationale: str = "",
        operator_id: str, operator_token: str,
    ) -> dict:
        """The FIRST-CLASS curation-verdict ingestion surface (Step 7,
        v6 §16.6): records a ratified operator decision to ADMIT (or
        SUPERSEDE) a REFUTED_PATTERN curated entry THROUGH the gateway —
        the CURATE_KNOWLEDGE intent built here (DETERMINISTIC, the internal
        role: the human has no agent profile, the deterministic layer
        ingests the ratified verdict — the record_operator_decision
        precedent, IDR-040 §3) and admitted by ``apply_intent``.

        The surface FIRST records the operator's ratified HumanDecision
        (a ``HumanDecisionReceived`` event whose payload binds the
        full-command ``curation_id`` hash — the gateway re-verifies the
        binding fail-closed), THEN submits the command. The decision record
        is idempotent per command hash (a replay never double-records).
        The write is LEASE-HELD: the scheduler lock is acquired for the
        verdict's duration (a concurrent controller's lease refuses the
        record fail-closed with code ``LOCK``; nothing is written).

        The operator selects WHICH binding and ratifies the command — the
        operator NEVER authors axes: the gateway recomputes the signature
        from the persisted FeatureBinding and refuses any drift. Rejections
        are surfaced as data (never raised through the loop): a repeat of
        the same command returns ``duplicate=True``; any gateway refusal
        returns ``{"rejected": True, "code": ..., "detail": ...}`` —
        nothing is written on a refusal."""
        from hermes.core.intents import Intent, IntentKind
        from hermes.persistence.event_validation import (
            DEFAULT_PAYLOAD_MAX_BYTES,
            EventValidationError,
            validate_payload_size,
        )
        from hermes.research.feature_binding import curation_command_hash
        from hermes.research.gateway import GatewayRejection, apply_intent

        command_payload = {
            "operation": operation,
            "kind": "REFUTED_PATTERN",
            "program_ref": program_ref,
            "hypothesis_ref": hypothesis_ref,
            "source_binding_ref": source_binding_ref,
            "source_decision_event_ref": source_decision_event_ref,
            "signature_json": signature_json,
            "supersedes_ref": supersedes_ref,
        }
        echo = {**command_payload}
        try:
            command_hash = curation_command_hash(command_payload)
        except (TypeError, ValueError) as exc:  # fail-closed, never raised
            return {**echo, "rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": f"the curation command is not hashable: {exc}"}

        if not self._verify_operator(operator_id, operator_token):
            return {**echo, "rejected": True, "code": "OPERATOR",
                    "detail": "no ratified operator credential for "
                              f"operator {operator_id!r} — curation "
                              f"decision refused"}

        decision_ref = f"curate-decision-{command_hash}"
        decision_payload = {
            "decision": "CURATE_KNOWLEDGE",
            "curation_id": command_hash,
            "operator_id": operator_id,
            "rationale": rationale,
        }
        # F3 (audit): pre-validate the decision payload BEFORE any work —
        # an oversized rationale would otherwise fail at the event boundary.
        try:
            validate_payload_size(decision_payload,
                                  max_bytes=DEFAULT_PAYLOAD_MAX_BYTES)
        except EventValidationError as exc:
            return {**echo, "rejected": True, "code": "RATIONALE",
                    "detail": f"rationale too large for the decision "
                              f"event: {exc}"}

        if not self._acquire_lock():
            return {**echo, "rejected": True, "code": "LOCK",
                    "detail": "scheduler lease held by another controller — "
                              "curation decision not recorded"}
        try:
            # 1. The ratified HumanDecision (idempotent per command hash —
            #    a replay never double-records the decision event).
            record_human_decision_once(
                conn=self._fenced, clock=self._clock,
                project_id=self._project_id, correlation_id=decision_ref,
                caused_by="operator",
                reason=f"operator curation verdict ({operation})",
                payload=decision_payload)
            # 2. The CURATE_KNOWLEDGE command (gateway validates fail-closed:
            #    decision binding, REFUTED head, FeatureBinding integrity,
            #    evidence basis, signature recompute, curated_id recompute).
            intent = Intent(
                kind=IntentKind.CURATE_KNOWLEDGE,
                proposed_by="DETERMINISTIC",
                project_id=self._project_id,
                justification=(
                    f"operator curation verdict {operation} on hypothesis "
                    f"{hypothesis_ref!r} (curation_id {command_hash})"),
                payload={**command_payload,
                         "human_decision_ref": decision_ref,
                         "operator_id": operator_id},
            )
            result = apply_intent(self._fenced, intent, clock=self._clock)
            return {**echo,
                    "curated_id": result.entity_id,
                    "curation_id": command_hash,
                    "duplicate": result.duplicate,
                    "rejected": False}
        except GatewayRejection as exc:
            return {**echo, "rejected": True, "code": exc.code,
                    "detail": str(exc)}
        finally:
            self._release_lock()

    def record_source_retraction_decision(
        self, *, source_ref: str, reason: str, rationale: str = "",
        operator_id: str, operator_token: str,
    ) -> dict:
        """The FIRST-CLASS source-retraction ingestion surface (Step 8
        Slice 1, closes GAP-1; v6 §7/S5; Step 6 gate §18): records a
        ratified operator decision to retract a source THROUGH the gateway —
        the RETRACT_SOURCE intent built here (DETERMINISTIC, the internal
        role: the human has no agent profile, the deterministic layer
        ingests the ratified verdict — the record_operator_decision
        precedent, IDR-040 §3; the record_curation_decision shape, Step 7)
        and admitted by ``apply_intent``.

        The surface FIRST records the operator's ratified HumanDecision
        (a ``HumanDecisionReceived`` event whose payload binds the
        deterministic ``retraction_id`` — the gateway re-verifies the
        binding fail-closed), THEN submits the command. The decision record
        is idempotent per retraction id (a replay never double-records).
        The write is LEASE-HELD: the scheduler lock is acquired for the
        verdict's duration (a concurrent controller's lease refuses the
        record fail-closed with code ``LOCK``; nothing is written).

        One decision authorizes exactly ONE source retraction (Step 8
        multi-source RESTRICT — no arrays, no batching). The decision event
        carries the bounded ``reason_digest`` (Step 8 payload lock); the
        full cited reason travels in the RETRACT_SOURCE intent and lands in
        the superseding ResearchDecision artifact — it is never duplicated
        into the journal payload. ``rationale`` is accepted for API symmetry
        with the sibling verdict surfaces and boundedness-checked, but is
        not persisted (neither locked payload shape carries it). Rejections
        are surfaced as data (never raised through the loop): a repeat of
        the same decision returns ``duplicate=True``; any gateway refusal
        returns ``{"rejected": True, "code": ..., "detail": ...}`` —
        nothing is written on a refusal.

        Known limitation (S5 L2, intentionally out of scope — Step 7
        charter lock, carried by Step 8): the downstream cone traversal
        operates on bare artifact IDs while some production dependency
        edges use prefixed/task-ID reference forms, so downstream cone
        propagation — and therefore the curated-invalidation predicate
        that consumes the same cone — may be incomplete. This method does
        not alter edge storage, edge creation, graph traversal, or S5 cone
        logic in any way.
        """
        import hashlib as _hashlib

        from hermes.core.intents import Intent, IntentKind
        from hermes.persistence.event_validation import (
            DEFAULT_PAYLOAD_MAX_BYTES,
            EventValidationError,
            validate_payload_size,
        )
        from hermes.research.gateway import GatewayRejection, apply_intent

        echo = {"source_ref": source_ref}
        # 1. Input shape (fail-closed, before any work — mirrors the
        #    RETRACT_SOURCE gateway contract: non-empty source_ref,
        #    non-blank cited reason).
        if not isinstance(source_ref, str) or not source_ref:
            return {**echo, "rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": "source_ref must be a non-empty string"}
        if not isinstance(reason, str) or not reason.strip():
            return {**echo, "rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": "reason must be a non-empty cited reason "
                              "(v6 §7/S5)"}
        if not isinstance(rationale, str):
            return {**echo, "rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": "rationale must be a string"}
        # F3 (audit): pre-validate boundedness BEFORE any work — an
        # oversized reason would otherwise fail at the event boundary.
        try:
            validate_payload_size(
                {"source_ref": source_ref, "reason": reason,
                 "rationale": rationale},
                max_bytes=DEFAULT_PAYLOAD_MAX_BYTES)
        except EventValidationError as exc:
            return {**echo, "rejected": True, "code": "RATIONALE",
                    "detail": f"reason too large for the decision path: "
                              f"{exc}"}

        if not self._verify_operator(operator_id, operator_token):
            return {**echo, "rejected": True, "code": "OPERATOR",
                    "detail": "no ratified operator credential for "
                              f"operator {operator_id!r} — source-"
                              f"retraction decision refused"}

        # 2. Deterministic decision identity (Step 8 charter §7): the
        #    digest binds the exact cited reason; the id binds one
        #    decision to exactly one source (multi-source RESTRICT).
        reason_digest = _hashlib.sha256(
            reason.encode("utf-8")).hexdigest()
        retraction_id = _hashlib.sha256(
            (source_ref + reason_digest).encode("utf-8")).hexdigest()
        decision_ref = f"retract-decision-{retraction_id}"
        decision_payload = {
            "decision": "RETRACT_SOURCE",
            "retraction_id": retraction_id,
            "source_ref": source_ref,
            "reason_digest": reason_digest,
            "operator_id": operator_id,
        }

        if not self._acquire_lock():
            return {**echo, "rejected": True, "code": "LOCK",
                    "detail": "scheduler lease held by another controller — "
                              "source-retraction decision not recorded"}
        try:
            # 3. The ratified HumanDecision (idempotent per retraction id —
            #    a replay never double-records the decision event).
            record_human_decision_once(
                conn=self._fenced, clock=self._clock,
                project_id=self._project_id, correlation_id=decision_ref,
                caused_by="operator",
                reason="operator source-retraction verdict",
                payload=decision_payload)
            # 4. The RETRACT_SOURCE command (gateway validates fail-closed:
            #    decision dereference, source resolution, S5 cascade).
            intent = Intent(
                kind=IntentKind.RETRACT_SOURCE,
                proposed_by="DETERMINISTIC",
                project_id=self._project_id,
                justification=(
                    f"operator source-retraction verdict on {source_ref!r} "
                    f"(retraction_id {retraction_id})"),
                payload={"source_ref": source_ref, "reason": reason,
                         "human_decision_ref": decision_ref},
            )
            result = apply_intent(self._fenced, intent, clock=self._clock)
            return {**echo,
                    "retraction_id": retraction_id,
                    "decision_ref": decision_ref,
                    "entity_id": result.entity_id,
                    "duplicate": result.duplicate,
                    "rejected": False}
        except GatewayRejection as exc:
            return {**echo, "rejected": True, "code": exc.code,
                    "detail": str(exc)}
        finally:
            self._release_lock()

    def detect_contradictions(self) -> dict:
        """Run the deterministic CLASSIFICATION_CONFLICT detector (CHG-1)
        and record each finding through the gateway — the standalone path.

        Acquires and releases the scheduler lease (for an external /
        scheduler-driven caller); the in-tick caller must use
        ``_detect_contradictions_pass`` instead so it runs on the
        already-held fence without deleting the tick's own lease.

        Machine-derived derived-state admission: NO operator credential
        is involved (there is no human verdict here — the lease alone
        serializes the write, like tick-held writes). The detector is
        the pure ``detect_classification_conflicts`` pass over
        digest-valid classifications; the gateway re-verifies every
        pair rule fail-closed at admission. Detector failure returns
        refusal-as-data (code ``DETECTOR``) with zero writes — a failed
        detector run asserts nothing, and absence of a record is never
        evidence of absence. Rejections are surfaced as data (never
        raised through the loop).
        """
        if not self._acquire_lock():
            return {"rejected": True, "code": "LOCK",
                    "detail": "scheduler lease held by another controller — "
                              "contradiction detection not run"}
        try:
            return self._detect_contradictions_pass()
        finally:
            self._release_lock()

    def _detect_contradictions_pass(self) -> dict:
        """Lock-less core of contradiction detection.

        Runs on the caller's already-acquired scheduler lease / fence
        (the same pattern as ``_apply_evidence_ladder_pass``). The
        public ``detect_contradictions`` wraps this with lock
        acquire/release for standalone callers; ``tick()`` invokes this
        directly so the in-flight lease is not deleted mid-tick.

        Same semantics as the wrapper: machine-derived admission, no
        operator credential, fail-closed ``DETECTOR`` refusal with zero
        writes on detector failure, rejections surfaced as data.
        """
        from hermes.core.intents import Intent, IntentKind
        from hermes.research.contradictions import (
            CONTRADICTION_DETECTOR_VERSION,
            detect_classification_conflicts,
        )
        from hermes.research.gateway import GatewayRejection, apply_intent

        try:
            rows = self._detector_candidate_rows()
            found = detect_classification_conflicts(rows)
        except Exception as exc:  # noqa: BLE001 — detector failure
            # asserts nothing; the loop observes the refusal as data.
            self._note_once(
                f"contradiction detector failed: {exc} (DETECTOR)",
                key="contradiction:detector-failed")
            return {"rejected": True, "code": "DETECTOR",
                    "detail": f"contradiction detector failed: {exc}"}
        recorded: list[str] = []
        duplicates = 0
        refused: list[dict] = []
        for candidate in found:
            intent = Intent(
                kind=IntentKind.RECORD_CONTRADICTION,
                proposed_by="DETERMINISTIC",
                project_id=self._project_id,
                justification=(
                    "deterministic classification-conflict detection "
                    f"({candidate['contradiction_id']})"),
                payload={
                    "party_a": candidate["party_a"],
                    "party_b": candidate["party_b"],
                    "detector_version":
                        CONTRADICTION_DETECTOR_VERSION,
                    "supersedes_ref": "",
                },
            )
            try:
                result = apply_intent(
                    self._fenced, intent, clock=self._clock)
            except GatewayRejection as exc:
                refused.append(
                    {"contradiction_id": candidate["contradiction_id"],
                     "code": exc.code, "detail": str(exc)})
                continue
            if result.duplicate:
                duplicates += 1
            else:
                recorded.append(candidate["contradiction_id"])
        # FIX-NOTES-DEDUP: one condition per controller — the counts are
        # refreshed in place across ticks (keyed), never appended per tick.
        self._note_once(
            f"contradiction detection: {len(recorded)} recorded, "
            f"{duplicates} duplicates, {len(refused)} refused",
            key="contradiction-detection")
        return {"rejected": False, "recorded": recorded,
                "duplicates": duplicates, "refused": refused}

    def _detector_candidate_rows(self) -> list[dict]:
        """Digest-valid classification rows for the detector pass
        (delegates to the S-1 internal seam)."""
        from hermes.research.contradiction_candidates import (
            detector_candidate_rows,
        )
        return detector_candidate_rows(
            self._conn, self._project_id,
            self.classification_proposals().get("items", []))

    def _detector_resolve_ref(self, ref: object) -> str | None:
        """Resolve one evidence ref to a bare artifact ID
        (delegates to the S-1 internal seam)."""
        from hermes.research.contradiction_candidates import (
            detector_resolve_ref,
        )
        return detector_resolve_ref(self._conn, self._project_id, ref)

    def record_contradiction_resolution(
        self, *, contradiction_id: str, rationale: str = "",
        operator_id: str, operator_token: str,
    ) -> dict:
        """The FIRST-CLASS contradiction-verdict ingestion surface (CHG-1):
        records a ratified operator decision resolving an OPEN
        contradiction THROUGH the gateway — the CONTRADICTION_RESOLUTION
        intent built here (DETERMINISTIC, the internal role: the human
        has no agent profile, the deterministic layer ingests the
        ratified verdict — the record_operator_decision precedent,
        IDR-040 §3) and admitted by ``apply_intent``.

        The surface FIRST records the operator's ratified HumanDecision
        (a ``HumanDecisionReceived`` event whose payload binds the
        deterministic ``resolution_id`` — the gateway re-verifies the
        binding fail-closed), THEN submits the command. The write is
        LEASE-HELD; rejections are surfaced as data (never raised
        through the loop): a repeat returns ``duplicate=True``; any
        gateway refusal returns ``{"rejected": True, ...}``.
        """
        from hermes.core.intents import Intent, IntentKind
        from hermes.persistence.event_validation import (
            DEFAULT_PAYLOAD_MAX_BYTES,
            EventValidationError,
            validate_payload_size,
        )
        from hermes.research.gateway import (
            GatewayRejection,
            _contradiction_resolution_id,
            apply_intent,
        )

        echo = {"contradiction_id": contradiction_id}
        if not isinstance(contradiction_id, str) or not contradiction_id:
            return {**echo, "rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": "contradiction_id must be a non-empty string"}
        if not isinstance(rationale, str):
            return {**echo, "rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": "rationale must be a string"}
        try:
            resolution_id = _contradiction_resolution_id(contradiction_id)
        except (TypeError, ValueError) as exc:  # fail-closed, never raised
            return {**echo, "rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": f"the resolution command is not hashable: {exc}"}

        if not self._verify_operator(operator_id, operator_token):
            return {**echo, "rejected": True, "code": "OPERATOR",
                    "detail": "no ratified operator credential for "
                              f"operator {operator_id!r} — contradiction "
                              f"resolution refused"}

        decision_ref = f"contradiction-decision-{resolution_id}"
        decision_payload = {
            "decision": "CONTRADICTION_RESOLUTION",
            "resolution_id": resolution_id,
            "contradiction_id": contradiction_id,
            "operator_id": operator_id,
            "rationale": rationale,
        }
        # F3 (audit): pre-validate the decision payload BEFORE any work.
        try:
            validate_payload_size(decision_payload,
                                  max_bytes=DEFAULT_PAYLOAD_MAX_BYTES)
        except EventValidationError as exc:
            return {**echo, "rejected": True, "code": "RATIONALE",
                    "detail": f"rationale too large for the decision "
                              f"event: {exc}"}

        if not self._acquire_lock():
            return {**echo, "rejected": True, "code": "LOCK",
                    "detail": "scheduler lease held by another controller — "
                              "contradiction resolution not recorded"}
        try:
            record_human_decision_once(
                conn=self._fenced, clock=self._clock,
                project_id=self._project_id, correlation_id=decision_ref,
                caused_by="operator",
                reason="operator contradiction-resolution verdict",
                payload=decision_payload)
            intent = Intent(
                kind=IntentKind.CONTRADICTION_RESOLUTION,
                proposed_by="DETERMINISTIC",
                project_id=self._project_id,
                justification=(
                    f"operator contradiction verdict resolving "
                    f"{contradiction_id!r} (resolution_id {resolution_id})"),
                payload={"contradiction_id": contradiction_id,
                         "human_decision_ref": decision_ref,
                         "operator_id": operator_id},
            )
            result = apply_intent(self._fenced, intent, clock=self._clock)
            return {**echo,
                    "resolution_id": resolution_id,
                    "decision_ref": decision_ref,
                    "entity_id": result.entity_id,
                    "duplicate": result.duplicate,
                    "rejected": False}
        except GatewayRejection as exc:
            return {**echo, "rejected": True, "code": exc.code,
                    "detail": str(exc)}
        finally:
            self._release_lock()

    def record_failure_classification(
        self, *, program_ref: str, hypothesis_ref: str, failure_class: str,
        evidence_refs: list, falsifying_evidence_refs: list,
        explanation: str, classifier_version: str,
        constraint_ref: str | None = None,
        failed_mechanism_ref: str | None = None,
        regime_ref: str | None = None,
        resource_gap: dict | None = None,
        scope_brief_ref: str | None = None,
        scope_brief_field: str | None = None,
        contributing_factors: list | None = None,
        proposed_by: str = "", producing_task_id: str,
        rationale: str = "",
        operator_id: str, operator_token: str,
    ) -> dict:
        """The FIRST-CLASS failure-classification ingestion surface (P6):
        records an operator-asserted failure classification THROUGH the
        gateway — the RECORD_CLASSIFICATION intent built here
        (DETERMINISTIC, the internal role: the human has no agent
        profile, the deterministic layer ingests the ratified verdict —
        the record_operator_decision precedent, IDR-040 §3) and admitted
        by ``apply_intent``.

        Judgment authorship is the operator's (which evidence
        constitutes which failure class of which hypothesis); EVERYTHING
        checkable is re-verified fail-closed — the substrate re-runs
        validation with the real resolvers, re-derives identity, and
        enforces task binding, evidence ownership, and content-hash
        idempotency. An LLM must never call this surface (it is not
        reachable through any proposable intent).

        The surface FIRST records the operator's ratified HumanDecision
        (a ``HumanDecisionReceived`` event whose payload binds the
        deterministic command hash — the gateway re-verifies the
        binding fail-closed), THEN submits the command. The write is
        LEASE-HELD; rejections are surfaced as data (never raised
        through the loop): a repeat returns ``duplicate=True``; any
        gateway refusal returns ``{"rejected": True, ...}``.
        """
        from hermes.core.intents import Intent, IntentKind
        from hermes.persistence.event_validation import (
            DEFAULT_PAYLOAD_MAX_BYTES,
            EventValidationError,
            validate_payload_size,
        )
        from hermes.research.failure_classification import (
            classification_command_hash,
        )
        from hermes.research.gateway import GatewayRejection, apply_intent

        echo = {"program_ref": program_ref, "hypothesis_ref": hypothesis_ref}
        if not isinstance(rationale, str):
            return {**echo, "rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": "rationale must be a string"}
        if contributing_factors is None:
            contributing_factors = []
        if resource_gap is not None and not isinstance(resource_gap, dict):
            return {**echo, "rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": "resource_gap must be a mapping or absent"}
        command = {
            "program_ref": program_ref,
            "hypothesis_ref": hypothesis_ref,
            "failure_class": failure_class,
            "evidence_refs": evidence_refs,
            "falsifying_evidence_refs": falsifying_evidence_refs,
            "explanation": explanation,
            "classifier_version": classifier_version,
            "constraint_ref": constraint_ref,
            "failed_mechanism_ref": failed_mechanism_ref,
            "regime_ref": regime_ref,
            "resource_gap": resource_gap,
            "scope_brief_ref": scope_brief_ref,
            "scope_brief_field": scope_brief_field,
            "contributing_factors": contributing_factors,
            "proposed_by": proposed_by,
            "producing_task_id": producing_task_id,
        }
        try:
            command_hash = classification_command_hash(command)
        except (TypeError, ValueError) as exc:  # fail-closed, never raised
            return {**echo, "rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": f"the classification command is not hashable: "
                              f"{exc}"}

        if not self._verify_operator(operator_id, operator_token):
            return {**echo, "rejected": True, "code": "OPERATOR",
                    "detail": "no ratified operator credential for "
                              f"operator {operator_id!r} — failure "
                              f"classification refused"}

        decision_ref = f"classification-decision-{command_hash}"
        decision_payload = {
            "decision": "RECORD_CLASSIFICATION",
            "classification_hash": command_hash,
            "operator_id": operator_id,
            "rationale": rationale,
        }
        # F3 (audit): pre-validate the decision payload BEFORE any work.
        try:
            validate_payload_size(decision_payload,
                                  max_bytes=DEFAULT_PAYLOAD_MAX_BYTES)
        except EventValidationError as exc:
            return {**echo, "rejected": True, "code": "RATIONALE",
                    "detail": f"rationale too large for the decision "
                              f"event: {exc}"}

        if not self._acquire_lock():
            return {**echo, "rejected": True, "code": "LOCK",
                    "detail": "scheduler lease held by another controller — "
                              "failure classification not recorded"}
        try:
            record_human_decision_once(
                conn=self._fenced, clock=self._clock,
                project_id=self._project_id, correlation_id=decision_ref,
                caused_by="operator",
                reason="operator classification verdict",
                payload=decision_payload)
            intent = Intent(
                kind=IntentKind.RECORD_CLASSIFICATION,
                proposed_by="DETERMINISTIC",
                project_id=self._project_id,
                justification=(
                    f"operator classification verdict "
                    f"{failure_class!r} on hypothesis "
                    f"{hypothesis_ref!r} (command {command_hash})"),
                payload={**command,
                         "human_decision_ref": decision_ref,
                         "operator_id": operator_id},
            )
            result = apply_intent(self._fenced, intent, clock=self._clock)
            return {**echo,
                    "classification_hash": command_hash,
                    "decision_ref": decision_ref,
                    "entity_id": result.entity_id,
                    "duplicate": result.duplicate,
                    "rejected": False}
        except GatewayRejection as exc:
            return {**echo, "rejected": True, "code": exc.code,
                    "detail": str(exc)}
        finally:
            self._release_lock()

    def screen_near_miss_refutations(self, *, signature_json: str) -> dict:
        """The S7 near-miss screen (Step 7, v6 §16.6, charter §15) —
        READ-ONLY, advisory-only (D8): screens a candidate signature against
        the project's ACTIVE curated REFUTED_PATTERN entries (exact
        signature equality — no fuzzy/semantic matching). The active set
        excludes SUPERSEDED and INVALIDATED entries. The result shape omits
        source_project_id, the binding's artifact content, and
        admission_event_ref (no unrelated project/artifact/admission-event
        data leaks through the screen). Deterministic ordering
        (curated_id ASC). Never mutates state — the S7 consumer/UI is a
        deferred surface; this is the advisory read only."""
        import json as _json

        from hermes.persistence.repositories import CuratedKnowledgeRepository
        from hermes.research.feature_binding import (
            FeatureBindingError,
            signature_from_axes,
        )

        if not isinstance(signature_json, str) or not signature_json:
            return {"rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": "signature_json must be a non-empty string"}
        # Fail-closed shape check: only a CANONICAL signature (what
        # signature_from_binding produces) is screened — anything else is
        # refused, never silently matched against nothing.
        try:
            parsed = _json.loads(signature_json)
        except ValueError:
            return {"rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": "signature_json is not valid JSON"}
        if (not isinstance(parsed, dict)
                or parsed.get("schema_version") != 1
                or not isinstance(parsed.get("axes"), dict)):
            return {"rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": "signature_json must be "
                              "{\"schema_version\":1,\"axes\":{...}}"}
        try:
            canonical = signature_from_axes(parsed["axes"])
        except FeatureBindingError as exc:
            return {"rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": f"signature_json axes are not canonical: {exc}"}
        if canonical != signature_json:
            return {"rejected": True, "code": "MALFORMED_PAYLOAD",
                    "detail": "signature_json is not in canonical compact "
                              "form — recompute it via "
                              "signature_from_binding"}

        repo = CuratedKnowledgeRepository(self._conn)
        matches = repo.screen_matches(self._project_id, signature_json)
        return {"signature_json": signature_json,
                "matches": matches,
                "count": len(matches),
                "rejected": False}

    def audit_curated_registry(self) -> dict:
        """The curated-registry audit surface (Step 7, v6 §16.6,
        charter §15) — READ-ONLY, project-scoped: every curated entry of
        this project regardless of status (full provenance shape: source
        project/binding/decision refs, admission refs, invalidation ref),
        each with its immutable evidence basis (sorted bare artifact_ids)
        and its supersession link (when this entry superseded another).
        Deterministic ordering (curated_id ASC). Never mutates state."""
        from hermes.persistence.repositories import CuratedKnowledgeRepository

        repo = CuratedKnowledgeRepository(self._conn)
        entries = []
        active = 0
        for entry in repo.all_entries(self._project_id):
            entry = dict(entry)
            entry["evidence_basis"] = repo.basis(
                self._project_id, entry["curated_id"])
            entry["supersession"] = repo.supersession(
                self._project_id, entry["curated_id"])
            if entry["status"] == "ADMITTED":
                active += 1
            entries.append(entry)
        return {"entries": entries,
                "count": len(entries),
                "active_count": active,
                "rejected": False}

    def _refresh_fence(self) -> None:
        """Rebuild the fenced connection + repos with the CURRENT captured
        generation (called on every successful acquisition). The source-slice
        repos join this rebuild over ``self._fenced`` (SD2-03 / HD-03)."""
        self._fenced = _FencedConnection(self._conn, self._assert_lock_valid)
        self._project_repo = ProjectRepository(self._fenced, self._clock)
        self._task_repo = TaskRepository(self._fenced, self._clock)
        self._artifacts_repo = ArtifactRepository(self._fenced, self._clock)
        self._source_repo = SourceOutcomeRepository(
            self._fenced, self._artifact_store, self._clock)
        self._repos = SourceRepos(
            artifacts=self._artifacts_repo, source=self._source_repo)
        self._failure_classification_repo = FailureClassificationRepository(
            self._fenced, self._clock)
        self._satisfaction_repo = ProgramRequirementSatisfactionRepository(
            self._fenced, self._clock)

    def _assert_lock_valid(self) -> None:
        """ADV-02 — the fencing check: the lock row must still be OURS at the
        generation we captured. Runs inside the write transaction (the fenced
        connection calls it before the first write statement), so no other
        writer can interleave between check and write (SQLite serializes
        writers; the reclaim's commit is visible to our transaction)."""
        row = self._conn.execute(
            "SELECT owner, generation FROM scheduler_lock WHERE id = 0"
        ).fetchone()
        owner = row["owner"] if row else None
        generation = row["generation"] if row else None
        if row is None or owner != self._owner or generation != self._lock_generation:
            raise LockLostError(
                f"scheduler lease lost: lock is owner={owner!r} "
                f"generation={generation!r}, controller {self._owner!r} holds "
                f"generation={self._lock_generation!r} — failing closed")

    def _acquire_lock(self) -> bool:
        now = self._clock()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT owner, locked_at, generation FROM scheduler_lock "
                "WHERE id = 0"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO scheduler_lock (id, owner, locked_at, generation) "
                    "VALUES (0, ?, ?, 0)",
                    (self._owner, now),
                )
                self._lock_generation = 0
            elif row["owner"] == self._owner:
                # refresh our own lease — SAME generation stays valid
                self._conn.execute(
                    "UPDATE scheduler_lock SET locked_at = ? WHERE id = 0",
                    (now,),
                )
                self._lock_generation = row["generation"]
            elif self._is_stale_ts(row["locked_at"], now):
                # ADV-02 — reclaim by lease expiry (IDR-029 Decision 4), now
                # generation-FENCED: the generation increments on the ownership
                # change, so any write the OLD holder attempts after this point
                # fails the fence (it captured the pre-reclaim generation).
                self._conn.execute(
                    "UPDATE scheduler_lock SET owner = ?, locked_at = ?, "
                    "generation = generation + 1 WHERE id = 0",
                    (self._owner, now),
                )
                self._lock_generation = row["generation"] + 1
            else:
                self._conn.execute("ROLLBACK")
                return False
            self._conn.execute("COMMIT")
            self._refresh_fence()
            return True
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def _release_lock(self) -> None:
        self._conn.execute(
            "DELETE FROM scheduler_lock WHERE id = 0 AND owner = ?",
            (self._owner,),
        )

    # ── recovery (v4 §19 NO_SIGNAL ladder; IDR-029 Decision 4) ──

    def _recovery_pass(self, mode: OperationalMode) -> tuple[list[str], list[str]]:
        """Mark dead workers: stale RUNNING → NO_SIGNAL (first miss);
        NO_SIGNAL that is STILL stale → FAILED (second conclusive miss);
        NO_SIGNAL with a fresh heartbeat → RUNNING (revert).

        The second-miss NO_SIGNAL → FAILED hop only fires while the project
        is ACTIVE (F15-audit): the requeue leg of Decision 4 (FAILED →
        RETRYING → RUNNING → re-execute) exists only in ACTIVE ticks, so a
        conclusive FAILED hop while AWAITING_HUMAN/PAUSED would strand the
        task at FAILED with attempts remaining — the same-pass requeue is
        skipped and the operator's later verdict never restarts it. While
        stopped, the task stays NO_SIGNAL; the second miss becomes
        conclusive on the first ACTIVE tick, where the chain completes in
        the same pass. The liveness REVERT (fresh heartbeat → RUNNING) is
        mode-independent (a live worker may return to RUNNING even while
        parked; the mode gate already prevents dispatch).

        Returns ``(touched, recovery_failed)`` — the second list is the
        tasks this pass FAILED via the ladder (the only FAILED tasks the
        controller may auto-requeue)."""
        touched: list[str] = []
        recovery_failed: list[str] = []
        now = datetime.fromisoformat(self._clock())

        rows = self._fenced.execute(
            "SELECT * FROM tasks WHERE project_id = ? AND status IN "
            "('RUNNING', 'NO_SIGNAL')",
            (self._project_id,),
        ).fetchall()
        for row in rows:
            task_id = row["task_id"]
            status = TaskStatus(row["status"])
            if status is TaskStatus.RUNNING:
                if self._is_stale(row["last_heartbeat"], now):
                    self._task_repo.transition_status(
                        task_id, TaskStatus.NO_SIGNAL,
                        caused_by="controller",
                        reason="lease expired: no heartbeat (first miss, v4 §19)",
                    )
                    touched.append(task_id)
            else:  # NO_SIGNAL
                if self._is_stale(row["last_heartbeat"], now):
                    if mode is OperationalMode.ACTIVE:
                        self._task_repo.transition_status(
                            task_id, TaskStatus.FAILED,
                            caused_by="controller",
                            reason="second conclusive miss: no heartbeat (v4 §19)",
                        )
                        touched.append(task_id)
                        recovery_failed.append(task_id)
                    # else: parked/stopped — keep NO_SIGNAL; the requeue
                    # chain can only complete on an ACTIVE tick
                else:
                    # fresh heartbeat before the second check → revert
                    self._task_repo.transition_status(
                        task_id, TaskStatus.RUNNING,
                        caused_by="controller",
                        reason="fresh heartbeat before second check (v4 §19)",
                    )
                    touched.append(task_id)
        return touched, recovery_failed

    def _requeue_recovered(self, recovery_failed: list[str]) -> list[str]:
        """Requeue only the tasks this controller FAILED via the recovery
        ladder (IDR-029 Decision 4): FAILED → RETRYING → RUNNING, bounded by
        ``max_retries``. Each RETRYING→RUNNING transition increments
        ``attempt`` (the retry-policy primitive) — A2-03 one-shot is keyed
        on ``producing_task_id``, never on attempt, so idempotency survives.

        Output-rejected tasks with attempts remaining never land FAILED
        (Decision 2 sends them to RETRYING directly), so this pass cannot
        resurrect a task the acceptance path deliberately retired.
        """
        requeued: list[str] = []
        for task_id in recovery_failed:
            if self._loops.is_quarantined(task_id):
                self._note_once(
                    f"requeue refused for {task_id}: "
                    f"{self._loops.reason_for(task_id)}",
                    key=f"p-auto-4:quarantined:{task_id}")
                continue
            # FIX-A2 — recovery re-execution is execution: it passes the
            # per-TASK step budget (poison visibility, alongside the
            # max_retries attempt bound below). Tick/run dispatch capacity
            # is untouched by design: the F15 cadence contract owns it, and
            # starving recovery on a full tick would strand dead workers.
            step_code = self._budget.check_task_step(task_id)
            if step_code:
                self._note_once(
                    f"requeue refused for {task_id}: {step_code}",
                    key=f"p-auto-4:{step_code}:{task_id}")
                continue
            row = self._task_repo.get(task_id)
            if row["attempt"] >= row["max_retries"]:
                continue
            self._task_repo.transition_status(
                task_id, TaskStatus.RETRYING,
                caused_by="controller", reason="recovery requeue (v4 §19)",
            )
            self._task_repo.transition_status(
                task_id, TaskStatus.RUNNING,
                caused_by="controller", reason="recovery re-claim (v4 §19)",
            )
            self._budget.record_task_step(task_id)
            requeued.append(task_id)
        return requeued

    def _re_execute_requeued(self, requeued: list[str]) -> TickResult:
        """Re-execute recovery-requeued tasks (now RUNNING) — TEMPLATE-GENERIC
        (SD-02 / SD2-05): each requeued task is re-dispatched through the SAME
        execute-ONLY per-template path as its own kind (EXTRACT →
        ``_execute_extract``; handler-backed → ``_run_handler``; unknown →
        left with a diagnostic, never reinterpreted as another kind). The
        one-shot (A2-03/OB-01) makes an identical re-acceptance idempotent
        and a divergent one a FAILED terminal — no duplicate rows, no
        double-success (criterion 3/5)."""
        out = TickResult()
        for task_id in requeued:
            # FIX-A2 — belt-and-braces: a task quarantined between requeue
            # and re-execution is never re-executed silently.
            if self._loops.is_quarantined(task_id):
                self._note_once(
                    f"re-execution refused for {task_id}: "
                    f"{self._loops.reason_for(task_id)}",
                    key=f"p-auto-4:quarantined:{task_id}")
                continue
            try:
                task = self._task_repo.get(task_id)
            except Exception:  # noqa: BLE001 — task vanished mid-recovery
                self.note(f"requeued task {task_id} no longer exists — skipped")
                continue
            spec = task.get("spec") or {}
            template = (spec.get("template") or "").strip().casefold()
            if template == EXTRACT_TEMPLATE:
                # FIX-A1/A2 — the re-execution spends provider estimate
                # tokens like a dispatch (handler re-executions charge
                # measured actuals inside _run_handler).
                self._record_spent_tokens(
                    task_id, self._estimate_tokens(task))
                out2 = self._execute_extract(task_id)
            elif template in self._task_handlers:
                out2 = self._run_handler(task_id, template)
            else:
                self.note(
                    f"requeued task {task_id} has no executor for template "
                    f"{template!r} — left for diagnostics")
                out2 = TickResult()
                out2.unhandled.append(task_id)
            out.succeeded.extend(out2.succeeded)
            out.retried.extend(out2.retried)
            out.failed.extend(out2.failed)
            out.unhandled.extend(out2.unhandled)
            out.model_calls += out2.model_calls
        return out

    def _run_handler(self, task_id: str, template: str) -> TickResult:
        """Execute a handler-backed AGENT_TASK — execute-ONLY (the task is
        already RUNNING: claimed by dispatch, or re-claimed by the recovery
        requeue — SD2-05, never a re-claim). The typed bundle is the ONLY
        handler contract (HD-02). Handles the structured ``HandlerResult``
        and the source-slice error split: one-shot divergence → FAILED
        terminal (a retry would diverge again); a binding error while the
        task is still RUNNING without prior output → retry policy (IDR29-02)."""
        out = TickResult()
        task = self._task_repo.get(task_id)
        entry = self._task_handlers.get(template)
        if entry is None:
            self.note(
                f"handler-backed task {task_id} has no handler for template "
                f"{template!r} — left for diagnostics")
            out.unhandled.append(task_id)
            return out
        builder = getattr(entry, "build_context", None)
        if builder is None:
            # HD-02 — the typed bundle is the ONLY dispatch contract; a bare
            # callable cannot be dispatched (fail closed, never a guess).
            self._task_repo.transition_status(
                task_id, TaskStatus.FAILED, caused_by="controller",
                reason=f"handler '{template}' has no build_context — the "
                       f"typed SourceTaskExecutionContext is the only "
                       f"dispatch contract (HD-02)")
            out.failed.append(task_id)
            return out
        # S6-C2 — the handler's write surface is the TASK-SCOPED view of the
        # per-tick bundle: record() forces the cited task to the dispatched
        # task. The scoping lives at the DISPATCH seam so every handler
        # (factory-built or custom) receives it — no handler can misbind an
        # outcome to another task.
        ctx = builder(task, self._project_id,
                      TaskScopedSourceRepos(self._repos, task["task_id"]))
        try:
            # C2 — the handler is the long execution; keep the task alive.
            result = self._run_with_heartbeat_refresh(
                task_id, lambda: entry(ctx))
            if not isinstance(result, HandlerResult):
                # S6-A3 — the structured return type is the contract: a
                # handler returning anything else (None, a dict, a str) is a
                # contract violation, NOT a success — fail closed, never a
                # silent SUCCEEDED (HD-02 "wrong result type → fail closed").
                # FIX-A1 — no measured count exists; charge the estimate so
                # the execution is still counted.
                self._record_spent_tokens(
                    task_id, self._estimate_tokens(task))
                self._task_repo.transition_status(
                    task_id, TaskStatus.FAILED, caused_by="controller",
                    reason=f"handler '{template}' returned "
                           f"{type(result).__name__}, not a HandlerResult — "
                           f"the structured verdict is the only return "
                           f"contract (S6-A3)")
                out.failed.append(task_id)
                return out
            # FIX-A1 — charge the MEASURED transport requests for this
            # dispatch (retries included); estimates stay advisory-only at
            # pre-claim admission and can no longer understate real egress.
            self._record_spent_tokens(
                task_id, max(0, result.provider_requests))
            status = result.status
            if status == "completed":
                # S6-B2 — completion is STRUCTURALLY verified, never the
                # handler's word: a SOURCE_SEARCH/SOURCE_FETCH handler that
                # claims completed must have persisted its outcome (the
                # EXTRACT precedent: acceptance writes rows before the
                # SUCCEEDED transition). A zero-row "success" is a contract
                # violation → FAILED, never a silent SUCCEEDED.
                has_outcome = self._fenced.execute(
                    "SELECT 1 FROM artifacts WHERE task_id = ? "
                    "AND artifact_type IN ("
                    "'source_search','source_fetch_outcome') LIMIT 1",
                    (task_id,),
                ).fetchone()
                if has_outcome is None:
                    self._task_repo.transition_status(
                        task_id, TaskStatus.FAILED, caused_by="controller",
                        reason=f"handler '{template}' claimed completion but "
                               f"recorded no source outcome — zero-row "
                               f"success is not success (S6-B2)")
                    out.failed.append(task_id)
                    return out
                # IDR-038 §3.1: a completed evidence-producing task records
                # its per-requirement satisfaction links BEFORE the SUCCEEDED
                # transition — a SUCCEEDED evidence task always carries its
                # links (or an explicit note); idempotent, so recovery is safe.
                self._record_requirement_satisfactions(task)
                self._task_repo.transition_status(
                    task_id, TaskStatus.SUCCEEDED, caused_by="controller",
                    reason=f"handler '{template}' completed")
                self._loops.observe_success(task_id)
                out.succeeded.append(task_id)
            else:
                # failed_typed — the work ran and its typed outcome was
                # RECORDED (EMPTY / UNAVAILABLE, §11); the retry policy
                # decides, never an unbounded loop.
                reason = getattr(result, "reason", "") or (
                    f"handler '{template}' reported a typed failure")
                disposition = self._retry_or_fail(task_id, reason)
                if disposition == "retried":
                    out.retried.append(task_id)
                else:
                    out.failed.append(task_id)
        except SourceOutcomeConflictError as exc:
            # one-shot divergence — a retry would diverge again (A2-03/OB-01).
            # FIX-A1 — the handler ran (unknown request volume); charge the
            # estimate so the execution is counted, never silent.
            self._record_spent_tokens(
                task_id, self._estimate_tokens(task))
            self._task_repo.transition_status(
                task_id, TaskStatus.FAILED, caused_by="controller",
                reason=f"handler '{template}': one-shot refusal — the task "
                       f"already produced a divergent outcome: {exc}")
            out.failed.append(task_id)
        except SourceOutcomeBindingError as exc:
            # IDR29-02 split (the source-slice analogue): never transition
            # blindly — the task may already have left RUNNING.
            current = self._task_repo.get_status(task_id)
            if current is not TaskStatus.RUNNING:
                self.note(
                    f"source acceptance refused for {task_id}: task already "
                    f"{current.value}; recovery owns it ({exc})")
            else:
                # FIX-A1 — the handler executed while RUNNING (measured
                # figure lost in the binding failure); charge the estimate.
                self._record_spent_tokens(
                    task_id, self._estimate_tokens(task))
                has_prior = self._fenced.execute(
                    "SELECT 1 FROM artifacts WHERE task_id = ? LIMIT 1",
                    (task_id,),
                ).fetchone()
                if has_prior is not None:
                    self._task_repo.transition_status(
                        task_id, TaskStatus.FAILED, caused_by="controller",
                        reason=f"acceptance refused: task already produced "
                               f"output (one-shot); divergent re-execution "
                               f"is not a second output: {exc}")
                    out.failed.append(task_id)
                else:
                    disposition = self._retry_or_fail(
                        task_id, f"acceptance refused: {exc}")
                    if disposition == "retried":
                        out.retried.append(task_id)
                    else:
                        out.failed.append(task_id)
        except Exception as exc:  # noqa: BLE001 — fail-closed, never silent
            # FIX-A1 — same estimate fallback: the execution happened, so it
            # is counted even though no measured figure exists.
            self._record_spent_tokens(
                task_id, self._estimate_tokens(task))
            self._task_repo.transition_status(
                task_id, TaskStatus.FAILED, caused_by="controller",
                reason=f"handler '{template}' failed: {exc}")
            out.failed.append(task_id)
        return out

    # ── discovery + dispatch (Decision 1–3) ──

    def _discover_eligible(self) -> list[dict]:
        """READY (or PENDING) tasks whose dependencies are all SUCCEEDED.

        Discovery is a cheap pre-filter, never the authority:
        ``transition_status`` re-validates the v4 §7 rule 1 atomically
        (F-10) at claim time.

        Sequencer artifacts (``spec.template == "sequencer"``, P-AUTO-1) are
        excluded: they are recorded-only and never claimable, so an inert one
        must not occupy the eligible set. Excluded here rather than at a
        consumer because the Q-02 ranking is also re-derived straight from
        this method — a dispatch-only filter would leave the ranking, the
        C4 floor input and the Q-04 §3.4 idle predicate still contaminated.
        """
        rows = self._fenced.execute(
            """
            SELECT t.* FROM tasks t
            WHERE t.project_id = ? AND t.status IN
                  ('PENDING', 'READY', 'RETRYING')
              AND NOT EXISTS (
                  SELECT 1 FROM task_dependencies d
                  JOIN tasks dep ON dep.task_id = d.depends_on_task_id
                  WHERE d.task_id = t.task_id
                    AND dep.status != 'SUCCEEDED'
              )
            ORDER BY t.created_at, t.task_id
            """,
            (self._project_id,),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            d["spec"] = d.pop("spec_json") or {}
            if isinstance(d["spec"], str):
                import json as _json
                try:
                    d["spec"] = _json.loads(d["spec"])
                except ValueError:
                    d["spec"] = {}
            if self._is_sequencer_task(d):
                continue
            out.append(d)
        return out

    # ── Q-02 epistemic ordering (Model B: deterministic controller policy) ──

    def _order_eligible(
        self, tasks: list[dict], *, capacity: int | None = None,
    ) -> tuple[list[dict], Any | None]:
        """Apply the ratified Q-02 ordering policy to the eligible set.

        Computed at discovery time from stored task state and the
        gateway-validated ``research_program:`` provenance refs — never
        persisted, re-derived on every tick (Q-02 §9–§10, §12). Returns
        (tasks-in-policy-order, ranking) or (tasks, None) when empty.

        When the C4 exploration floor is enabled, the floor-aware wrapper
        permutes the pure-policy output under the versioned reservation
        rule (C4 §4.2); ``capacity`` is the round's remaining call-cap
        slot count (defaults to the full per-tick cap at discovery time).
        """
        from hermes.research.evaluation import evaluate_eligible_tasks

        if not tasks:
            return tasks, None
        program_rows, satisfactions = self._load_obligation_context()
        inputs = [
            self._eligible_task_input(t, program_rows=program_rows,
                                      satisfactions=satisfactions)
            for t in tasks]
        if self._enable_exploration_floor:
            from hermes.research.evaluation import (
                evaluate_eligible_tasks_with_floor,
            )
            cap = (self._max_calls_per_tick if capacity is None
                   else capacity)
            ranking = evaluate_eligible_tasks_with_floor(
                inputs,
                capacity=cap,
                floor_policy=self._floor_policy,
                event_records=self._load_floor_event_records(),
                satisfaction_counts=self._load_floor_satisfaction_counts(),
            )
        else:
            ranking = evaluate_eligible_tasks(inputs)
        by_ref = {t["task_id"]: t for t in tasks}
        return [by_ref[e.task_ref] for e in ranking.comparison], ranking

    def _load_floor_event_records(self) -> tuple:
        """The project's append-only ``FloorGrantRecorded`` history,
        projected into pure ``FloorEventRecord`` facts for the F-C
        derivation (C4 §4.3). Event_id order is the durable round
        vocabulary — no wall-clock reads. Corrupt payloads are skipped
        fail-closed (never a crash, never a silent skip)."""
        import json as _json

        from hermes.research.evaluation import (
            FloorEventRecord,
            TaskDiagnosticKind,
        )
        rows = self._fenced.execute(
            "SELECT event_id, payload_json, created_at FROM events "
            "WHERE project_id = ? AND event_type = 'FloorGrantRecorded' "
            "ORDER BY event_id",
            (self._project_id,),
        ).fetchall()
        records: list[FloorEventRecord] = []
        for r in rows:
            try:
                p = _json.loads(r["payload_json"] or "{}")
                kind = TaskDiagnosticKind(p.get("kind", ""))
                records.append(FloorEventRecord(
                    kind=kind,
                    trajectory=str(p.get("trajectory", "")),
                    round_index=int(p.get("round_index", 0)),
                    created_at=str(r["created_at"] or ""),
                    task_ref=p.get("task_ref"),
                    satisfaction_count=int(p.get("satisfaction_count", 0)),
                    outstanding_obligations=tuple(
                        p.get("outstanding_obligations") or ()),
                ))
            except (ValueError, KeyError, TypeError):
                self._note_once(
                    "corrupt FloorGrantRecorded payload skipped by the "
                    "C4 F-C derivation (fail-closed)",
                    key=f"floor:corrupt-payload:{r['event_id']}")
        return tuple(records)

    def _load_floor_satisfaction_counts(self) -> dict[str, int]:
        """Per-trajectory (program) satisfaction-link ROW counts — the
        monotone productivity witness for the F-C counter (C4 §2.3).
        Append-only + idempotent links over immutable artifacts ⇒ the
        count never decreases; a round is productive iff it grew."""
        rows = self._fenced.execute(
            "SELECT program_id, COUNT(*) AS n "
            "FROM program_requirement_satisfactions "
            "WHERE project_id = ? GROUP BY program_id",
            (self._project_id,),
        ).fetchall()
        return {r["program_id"]: int(r["n"]) for r in rows}

    def _persist_floor_transitions(self, ranking: Any) -> None:
        """Append each floor grant / F-C transition as a
        ``FloorGrantRecorded`` event (C4 §4.3 — the durable substrate).

        The ranking itself is transient (never persisted), so the floor's
        audit history rides these append-only events; the F-C stagnation
        counter is re-derived from them + the satisfaction links, never
        stored. The round's transitions are appended atomically (one
        transaction), event_id order = the durable round vocabulary.
        Inert / degenerate / stagnant diagnostics are advisory observables
        on the ranking only — they are NOT durable facts (the counter is a
        pure derivation), so they are not persisted here.
        """
        transitions = getattr(ranking, "floor_transitions", ()) or ()
        if not transitions:
            return
        conn = self._fenced if self._fenced is not None else self._conn
        conn.execute("BEGIN")
        try:
            for t in transitions:
                payload = {
                    "kind": t.kind.value,
                    "trajectory": t.trajectory,
                    "round_index": t.round_index,
                    "task_ref": t.task_ref,
                    "slot": t.slot,
                    "counter_after": t.counter_after,
                    "satisfaction_count": t.satisfaction_count,
                    "outstanding_obligations": list(
                        t.outstanding_obligations),
                }
                _append_event_to_db(
                    conn, self._clock, "FloorGrantRecorded",
                    project_id=self._project_id,
                    task_id=t.task_ref,
                    correlation_id=ranking.ranking_id,
                    caused_by="controller",
                    reason=t.detail,
                    payload=payload,
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def _load_obligation_context(
        self,
    ) -> tuple[list[dict], dict[str, dict[str, frozenset[str]]]]:
        """One read per tick: the project's immutable program rows (parsed)
        and the per-requirement satisfaction links (IDR-038 §3.1). Both are
        read-only stored facts — the derivation never writes (Q-02 §8)."""
        rows = self._fenced.execute(
            "SELECT * FROM research_programs WHERE project_id = ?",
            (self._project_id,),
        ).fetchall()
        programs: list[dict] = []
        for r in rows:
            try:
                programs.append(_research_program_row_to_dict(r))
            except ValueError:
                # Corrupt program row — fail closed: never a fact source,
                # never a crash. Observable via the notes channel (the
                # corruption degrades to baseline, never disappears silently).
                self._note_once(
                    f"corrupt research_program row {r['program_id']!r} "
                    f"skipped by the Q-02 obligation derivation "
                    f"(fail-closed to baseline)",
                    key=f"obligation:corrupt-program:{r['program_id']}")
        satisfactions = self._satisfaction_repo.satisfaction_types_by_requirement(
            self._project_id)
        return programs, satisfactions

    @staticmethod
    def _program_head_id(programs: list[dict]) -> str | None:
        """The program_id of the project's current epistemic-contract head —
        the max-version program row (the supersession-chain head, the same
        selection ``ResearchProgramRepository.current`` uses). Deterministic
        tie-break on program_id. HR-07: a decisive REFUTED must bind to the
        CURRENT contract — a classification citing a superseded program is a
        historical record, never a live falsification."""
        head: dict | None = None
        for p in programs:
            if head is None or (
                    int(p.get("version") or 0),
                    str(p.get("program_id") or "")) > (
                    int(head.get("version") or 0),
                    str(head.get("program_id") or "")):
                head = p
        if head is None:
            return None
        return str(head.get("program_id") or "") or None

    def _eligible_task_input(
        self, task: dict, *,
        program_rows: list[dict] | None = None,
        satisfactions: dict[str, dict[str, frozenset[str]]] | None = None,
    ) -> Any:
        """Build the pure EligibleTask input from stored state — deterministic,
        code-derived (Q-02 §8: no LLM-supplied estimate can enter).

        cost_class: the stored column mapped onto the ratified CostTier
        vocabulary — anything outside LOW/MEDIUM/HIGH is UNKNOWN (AC-08:
        unknown never treated as a value).
        dimensions: v1.2 derives the epistemic facts from the compiled
        programs named in the task's gateway-validated ``research_program:``
        provenance refs (Q-02 §7 option C) + the per-requirement satisfaction
        links (IDR-038 §3.1). A task whose obligation facts cannot be
        resolved — no link, missing/corrupt program row — gets all-NONE
        dimensions and degenerates to the created_at/task_id baseline
        (Q-02 §18.4). ``program_rows``/``satisfactions`` are the per-tick
        read-only context (``_load_obligation_context``).
        """
        from hermes.research.evaluation import CostTier, EligibleTask
        from hermes.research.task_obligations import (
            program_obligation_dimensions,
        )

        raw = (task.get("cost_class") or "").strip().upper()
        try:
            cost = CostTier(raw)
        except ValueError:
            cost = CostTier.UNKNOWN
        spec = task.get("spec") or {}

        dims: dict = {}
        basis: tuple[str, ...] = ()
        program_ids = [
            p[len("research_program:"):] for p in
            self._program_refs_from_provenance(task)]
        if program_ids and program_rows is not None:
            linked = [
                row for row in program_rows if row.get("program_id") in program_ids]
            dims, basis = program_obligation_dimensions(
                linked, satisfactions=satisfactions)

        return EligibleTask(
            task_ref=task["task_id"],
            template=(spec.get("template") or "").strip().casefold(),
            cost_class=cost,
            dimensions=dims,
            basis_refs=basis,
            created_at=task.get("created_at") or "",
            # C4 §2.1: the trajectory-label input — the task's own
            # gateway-validated ``research_program:`` refs (the same refs
            # the obligation derivation keys on). Floor-only: never an
            # ordering-key input, never hashed into the pure-path identity.
            program_refs=self._program_refs_from_provenance(task),
        )

    @staticmethod
    def _prov_refs(task: dict, prefix: str) -> tuple[str, ...]:
        """Sorted ``prefix:<id>`` refs from a task's provenance, accepting
        both the raw row shape (``provenance_json`` string, ``_discover_eligible``)
        and the parsed repository shape (``provenance`` list,
        ``TaskRepository.get``). Anything non-list or non-str is skipped —
        never trusted as an ordering or satisfaction input (fail-closed)."""
        prov = task.get("provenance_json")
        if isinstance(prov, str):  # raw row shape — parse, fail closed
            import json as _json
            try:
                prov = _json.loads(prov)
            except ValueError:
                return ()
        if not isinstance(prov, list):
            prov = task.get("provenance")  # parsed repository shape
        if not isinstance(prov, list):
            return ()
        return tuple(sorted(
            e for e in prov
            if isinstance(e, str) and e.startswith(prefix)
            and len(e) > len(prefix)))

    @classmethod
    def _program_refs_from_provenance(cls, task: dict) -> tuple[str, ...]:
        """The reserved, admission-checked ``research_program:`` ref class
        (gateway.py V6-FINAL-02) — the only deterministic task→program link
        the schema records today (Q-02 derivation input)."""
        return cls._prov_refs(task, "research_program:")

    @classmethod
    def _requirement_refs_from_provenance(cls, task: dict) -> tuple[str, ...]:
        """The plan-generated ``evidence_requirement:<claim_ref>`` ref class
        (task_plan.py emits it next to the program ref for every evidence
        task). NOT gateway-enforced (derived/context-dependent per the
        gateway docstring) — the satisfaction write path re-validates every
        ref against the linked program's evidence requirements before any
        link is recorded, so a forged ref can never fabricate a satisfaction."""
        return cls._prov_refs(task, "evidence_requirement:")

    def _record_requirement_satisfactions(self, task: dict) -> None:
        """IDR-038 §3.1 write path: record per-requirement satisfaction
        links for a COMPLETED evidence-producing task.

        The task→requirement binding is PLAN-GENERATED provenance
        (``evidence_requirement:<claim_ref>`` next to the gateway-validated
        ``research_program:<id>`` ref), never an LLM decision and never a
        spec field. For each (program, claim_ref) pair, each artifact the
        task produced whose class the requirement actually requires is
        linked via the validated repository write (rules 1–4: governance,
        dereference, project, class). Fail-closed per link: a ref that does
        not dereference, or an artifact of the wrong class, produces a note
        and NO link — never a crash, never a false satisfaction, never a
        task failure (the work is done; the LINK is what refuses). The
        repository is idempotent, so recovery re-execution re-records
        safely. Runs BEFORE the SUCCEEDED transition: a SUCCEEDED evidence
        task always carries its links (or an explicit note).
        """
        program_ids = [
            p[len("research_program:"):] for p in
            self._program_refs_from_provenance(task)]
        claim_refs = [
            c[len("evidence_requirement:"):] for c in
            self._requirement_refs_from_provenance(task)]
        if not program_ids or not claim_refs:
            return
        produced = self._fenced.execute(
            "SELECT artifact_id, artifact_type FROM artifacts "
            "WHERE task_id = ?", (task["task_id"],)).fetchall()
        if not produced:
            return
        # One read-only context parse (the same F5-defensive read the
        # ordering uses); the repository remains the admission authority.
        program_rows = self._load_obligation_context()[0]
        by_pid = {r.get("program_id"): r for r in program_rows}
        for pid in program_ids:
            program = by_pid.get(pid)
            if program is None:
                self.note(
                    f"satisfaction link skipped: research_program:{pid!r} is "
                    f"not resolvable in the obligation context — no link "
                    f"(fail-closed)")
                continue
            reqs = {
                r.get("claim_ref"): r for r in
                (program.get("evidence_requirements") or [])
                if isinstance(r, dict) and r.get("claim_ref")}
            for claim_ref in claim_refs:
                req = reqs.get(claim_ref)
                if req is None:
                    self.note(
                        f"satisfaction link refused: evidence_requirement:"
                        f"{claim_ref!r} does not dereference to an evidence "
                        f"requirement of research_program:{pid!r} — no link "
                        f"(IDR-038 §3.1 rule 2)")
                    continue
                required = set(req.get("required_artifacts") or [])
                for art in produced:
                    if art["artifact_type"] not in required:
                        continue  # not this requirement's class — no link
                    try:
                        self._satisfaction_repo.record(
                            project_id=self._project_id,
                            program_id=pid,
                            requirement_ref=claim_ref,
                            artifact_id=art["artifact_id"],
                        )
                    except RequirementSatisfactionError as exc:
                        self.note(
                            f"satisfaction link refused for artifact "
                            f"{art['artifact_id']!r}: {exc}")

    # ── Evidence Ladder APPLY (IDR-041 AC-1..5) ──

    def _apply_evidence_ladder_pass(self) -> list[str]:
        """The Evidence Ladder's ONE deterministic write path (the APPLIED
        side, design AC-1..5): consumes ratified facts and writes rung
        transitions atomically (an ``evidence_ladder_state`` row + the
        ``EvidenceTransitionApplied`` audit event in ONE transaction) —
        never a bare agent claim (AC-5).

        Two drivers, in deterministic order (first-visit-wins per
        (program, hypothesis)):

          1. ratified REFUTED — admitted ``EVIDENCE_TRANSITION_PROPOSED``
             records whose AC-4 ratification RE-VERIFIES at apply time
             (the shared ``_resolve_ratified_proposal``: APPROVED
             REJECT_BRANCH decision, action in the class's permitted set
             recomputed F2). The terminal fact wins the pass.
          2. obligation climbs — the highest rung whose artifact
             obligation set is satisfied by the recorded satisfaction
             links (IDR-038 §3.1); completed obligations ARE the
             ratification, no agent intent.

        Every write is its own transaction (row + event commit or roll
        back together), so a mid-apply crash leaves no half-state (AC-4);
        every transition id is deterministic (AC-1). The current rung is
        derived from ratified sources — the stored row is only ever
        COMPARED (a disagreement is a forward advance or a tamper
        signal), never trusted as the desired rung (F2). Fail-closed:
        a forged/stale ratification, a corrupt classification, an
        unresolvable target, or a tampered cache produces an observable
        note and writes nothing (AC-2). Returns the applied transition
        ids (the event correlations).
        """
        import json as _json

        from hermes.research.evidence_ladder import (
            classification_content_matches,
            classification_transition_id,
            derive_obligation_rung,
            obligation_transition_id,
            ratification_transition_id,
            repair_state_transition_id,
            rung_above,
        )
        from hermes.research.failure_classification import (
            FailureClass,
            PermittedAction,
            certifies_decisive_falsification,
        )
        from hermes.research.gateway import _resolve_ratified_proposal

        applied: list[str] = []
        written: set[tuple[str, str]] = set()
        programs, satisfactions = self._load_obligation_context()

        # Driver 1 — ratified REFUTED (deterministic event_id order).
        rows = self._fenced.execute(
            "SELECT event_id, correlation_id, payload_json FROM events "
            "WHERE project_id = ? AND event_type = ? ORDER BY event_id",
            (self._project_id, "EvidenceTransitionProposed"),
        ).fetchall()
        for r in rows:
            try:
                payload = _json.loads(r["payload_json"] or "{}")
            except ValueError:
                continue  # corrupt admission — never a ratified input
            if not isinstance(payload, dict) or (
                    payload.get("to_state") != "REFUTED"):
                continue
            ratification_ref = payload.get("ratification_ref")
            if not isinstance(ratification_ref, str) or not ratification_ref:
                # Declared but never ratified: the admission audit keeps the
                # record; the APPLY has no ratified input to act on (AC-5).
                continue
            ratified = _resolve_ratified_proposal(
                self._fenced, self._project_id, ratification_ref,
                frozenset({PermittedAction.REJECT_BRANCH}))
            if ratified is None:
                self.note(
                    f"Evidence Ladder: transition proposal "
                    f"{r['correlation_id']!r} cites ratification_ref "
                    f"{ratification_ref!r} that does not re-verify as an "
                    f"APPROVED REJECT_BRANCH proposal — nothing applied "
                    f"(AC-2 fail-closed)")
                continue
            target = self._ladder_refuted_target(ratified, programs)
            if target is None:
                self.note(
                    f"Evidence Ladder: transition proposal "
                    f"{r['correlation_id']!r}'s ratified classification "
                    f"does not resolve to a project hypothesis — nothing "
                    f"applied (AC-2 fail-closed)")
                continue
            pid, h_ref = target
            if (pid, h_ref) in written:
                continue
            current = self._ladder_current_rung(pid, h_ref)
            if current == "REFUTED":
                continue  # terminal — already applied (idempotent)
            tid = ratification_transition_id(str(r["correlation_id"]))
            if self._ladder_transition_applied(tid):
                # The transition IS on the audit but the cache head does not
                # reflect it — a downward tamper after apply (the normal
                # already-applied case is caught by ``current == REFUTED``
                # above). Heal the cache to the derived rung; never silent.
                self.note(
                    f"Evidence Ladder: transition {tid!r} for "
                    f"research_program:{pid} hypothesis {h_ref!r} is "
                    f"applied but the cache does not reflect REFUTED — "
                    f"healing the cache (tamper signal)")
                self._write_ladder_transition(
                    program_id=pid, hypothesis_ref=h_ref, transition_id=tid,
                    from_rung=current, to_rung="REFUTED",
                    driver="ratification",
                    proposal_id=str(r["correlation_id"]),
                    classification_ref=str(
                        ratified.get("classification_ref") or ""),
                    evidence_artifact_ref=str(
                        payload.get("evidence_artifact_ref") or ""),
                    ratification_ref=ratification_ref,
                    ratified_by="proposal",
                    emit_event=False,
                )
                continue
            self._write_ladder_transition(
                program_id=pid, hypothesis_ref=h_ref, transition_id=tid,
                from_rung=current, to_rung="REFUTED",
                driver="ratification",
                proposal_id=str(r["correlation_id"]),
                classification_ref=str(ratified.get("classification_ref") or ""),
                evidence_artifact_ref=str(
                    payload.get("evidence_artifact_ref") or ""),
                ratification_ref=ratification_ref,
                ratified_by="proposal",
            )
            written.add((pid, h_ref))
            applied.append(tid)

        # Driver 3 — bare-classification REFUTED (IDR-041 AC-2 deferred
        # branch, ratified): a digest-valid Q-05 classification ALONE
        # certifies a decisive falsification — the class is
        # DECLARED_CONSTRAINT_VIOLATION and the cited constraint is the
        # hypothesis's OWN declared falsification condition
        # (``hypothesis:<H>:falsification_condition``, via the ratified
        # predicate — never a stored flag). No transition proposal and no
        # agent intent needed: the ratified classification record IS the
        # falsification fact. Fail-closed per row: a forged identity, a
        # corrupt metadata, a non-ratified class, a non-falsification
        # citation, or an unresolvable target applies nothing (and is never
        # a crash). Deterministic (sorted by classification row).
        cls_rows = self._fenced.execute(
            "SELECT artifact_id, content_hash, metadata_json FROM artifacts "
            "WHERE project_id = ? AND artifact_type = ? ORDER BY artifact_id",
            (self._project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE),
        ).fetchall()
        for r in cls_rows:
            try:
                meta = _json.loads(r["metadata_json"] or "{}")
            except ValueError:
                continue  # corrupt metadata — never a falsification fact
            if not isinstance(meta, dict):
                continue
            # digest-valid identity (the classifications_digest discipline)
            if meta.get("classification_id") != r["artifact_id"]:
                continue  # forged identity — never a falsification fact
            # F13 — content integrity (ratified EC-V6 identity discipline):
            # the stored metadata must RE-DERIVE the row's authoritative
            # content hash. A metadata rewrite — class, constraint
            # citation, hypothesis target — changes the derived hash and
            # is refused as forged; the classification_id check alone is
            # not enough (a rewrite can preserve it).
            if not classification_content_matches(
                    meta, self._project_id, str(r["content_hash"] or "")):
                continue  # content does not re-derive the identity
            raw_class = meta.get("failure_class")
            try:
                failure_class = (FailureClass(raw_class)
                                 if isinstance(raw_class, str) else None)
            except ValueError:
                failure_class = None
            if failure_class is None:
                continue  # non-ratified class — never decisive
            h_ref = meta.get("hypothesis_ref")
            program_ref = meta.get("program_ref")
            if not isinstance(h_ref, str) or not h_ref:
                continue
            if not isinstance(program_ref, str) or not program_ref:
                continue
            if not certifies_decisive_falsification(
                    failure_class, h_ref, meta.get("constraint_ref")):
                continue  # not a decisive falsification citation
            prog_id = program_ref
            if program_ref.startswith("research_program:"):
                prog_id = program_ref[len("research_program:"):]
            program = next(
                (p for p in programs
                 if str(p.get("program_id") or "") == prog_id
                 or str(p.get("content_hash") or "") == prog_id),
                None)
            if program is None:
                continue  # foreign program — nothing applies
            # HR-07 — head binding: a decisive falsification must cite the
            # project's CURRENT epistemic contract (the supersession-chain
            # head). A classification against a superseded program is a
            # historical record, never a live REFUTED (fail-closed, noted).
            if str(program.get("program_id") or "") != (
                    self._program_head_id(programs)):
                self.note(
                    f"Evidence Ladder: classification {r['artifact_id']!r} "
                    f"cites superseded research_program:{prog_id!r} — a "
                    "decisive REFUTED must bind to the current program head "
                    "(HR-07); nothing applied")
                continue
            hyps = program.get("hypotheses") or []
            if not any(isinstance(h, dict) and h.get("ref") == h_ref
                       for h in hyps):
                continue  # foreign hypothesis — nothing applies
            pid = str(program.get("program_id") or "")
            if (pid, h_ref) in written:
                continue
            current = self._ladder_current_rung(pid, h_ref)
            if current == "REFUTED":
                continue  # terminal — already applied (idempotent)
            cls_ref = FAILURE_CLASSIFICATION_REF_PREFIX + str(
                r["content_hash"] or "")
            tid = classification_transition_id(cls_ref)
            if self._ladder_transition_applied(tid):
                # F12 — the applied transition is hidden by a downward
                # cache tamper; heal, never silent.
                self.note(
                    f"Evidence Ladder: transition {tid!r} for "
                    f"research_program:{pid} hypothesis {h_ref!r} is "
                    f"applied but the cache does not reflect REFUTED — "
                    f"healing the cache (tamper signal)")
                self._write_ladder_transition(
                    program_id=pid, hypothesis_ref=h_ref, transition_id=tid,
                    from_rung=current, to_rung="REFUTED",
                    driver="ratification",
                    classification_ref=cls_ref,
                    ratified_by="classification",
                    constraint_ref=str(meta.get("constraint_ref") or ""),
                    emit_event=False,
                )
                continue
            self._write_ladder_transition(
                program_id=pid, hypothesis_ref=h_ref, transition_id=tid,
                from_rung=current, to_rung="REFUTED",
                driver="ratification",
                classification_ref=cls_ref,
                ratified_by="classification",
                constraint_ref=str(meta.get("constraint_ref") or ""),
            )
            written.add((pid, h_ref))
            applied.append(tid)

        # Driver 2 — obligation climbs (sorted programs, sorted hypotheses).
        for program in sorted(
                programs, key=lambda p: str(p.get("program_id") or "")):
            pid = program.get("program_id")
            if not pid:
                continue
            hypotheses = sorted(
                (h for h in (program.get("hypotheses") or [])
                 if isinstance(h, dict) and h.get("ref")),
                key=lambda h: str(h.get("ref")))
            for hyp in hypotheses:
                h_ref = str(hyp.get("ref"))
                if (pid, h_ref) in written:
                    continue
                satisfied = ((satisfactions.get(pid) or {}).get(h_ref)
                             or frozenset())
                desired = derive_obligation_rung(program, hyp, satisfied)
                if desired is None:
                    continue
                current = self._ladder_current_rung(pid, h_ref)
                if current == desired:
                    continue
                if rung_above(current, desired):
                    # The cache claims a higher rung than the ratified
                    # sources derive — a tamper signal, never silent. A
                    # terminal REFUTED is NEVER reverted (AC-3 safety
                    # wins over self-healing); a lower non-terminal
                    # tamper is repaired to the true derived rung (the
                    # design's self-healing, observable via the note).
                    if current == "REFUTED":
                        self.note(
                            f"Evidence Ladder: ladder cache for "
                            f"research_program:{pid} hypothesis {h_ref!r} "
                            f"shows REFUTED but no ratified input "
                            f"re-verifies it — REFUTED is terminal, "
                            f"nothing written (tamper signal)")
                        continue
                    self.note(
                        f"Evidence Ladder: ladder cache for "
                        f"research_program:{pid} hypothesis {h_ref!r} "
                        f"claims rung {current} but the ratified sources "
                        f"derive {desired} — correcting the cache "
                        f"(tamper signal)")
                    self._write_ladder_transition(
                        program_id=pid, hypothesis_ref=h_ref,
                        transition_id=repair_state_transition_id(
                            pid, h_ref, desired),
                        from_rung=current, to_rung=desired,
                        driver="obligations",
                        satisfied_classes=sorted(satisfied),
                        emit_event=False,
                    )
                    continue
                tid = obligation_transition_id(pid, h_ref, desired)
                if self._ladder_transition_applied(tid):
                    # Applied but the cache head does not reflect the derived
                    # rung — a downward tamper after apply (the normal
                    # already-applied case is caught by ``current ==
                    # desired`` above). Heal the cache; never silent.
                    self.note(
                        f"Evidence Ladder: transition {tid!r} for "
                        f"research_program:{pid} hypothesis {h_ref!r} is "
                        f"applied but the cache does not reflect "
                        f"{desired} — healing the cache (tamper signal)")
                    self._write_ladder_transition(
                        program_id=pid, hypothesis_ref=h_ref,
                        transition_id=tid, from_rung=current,
                        to_rung=desired, driver="obligations",
                        satisfied_classes=sorted(satisfied),
                        emit_event=False,
                    )
                    continue
                self._write_ladder_transition(
                    program_id=pid, hypothesis_ref=h_ref, transition_id=tid,
                    from_rung=current, to_rung=desired,
                    driver="obligations",
                    satisfied_classes=sorted(satisfied),
                )
                written.add((pid, h_ref))
                applied.append(tid)
        return applied

    def _already_emitted_parallel_regime_child(
        self, parent_program_id: str, target_regime: str,
    ) -> bool:
        """True iff a child program with this (parent_program_id,
        target_regime) pair already exists — so a tick never re-emits the
        same proposal (B3 pre-check skip)."""
        row = self._conn.execute(
            "SELECT 1 FROM research_programs "
            "WHERE parent_program_id = ? AND target_regime = ?",
            (parent_program_id, target_regime),
        ).fetchone()
        return row is not None

    def _consume_approved_parallel_regime_proposals(self) -> list[str]:
        """B3 (ADR-041 AC-7): consume APPROVED ``PROPOSE_CLASSIFICATION_ACTION``
        proposals whose action is ``PROPOSE_PARALLEL_REGIME_TEST``.

        The controller (DETERMINISTIC) emits a single ``EMIT_PARALLEL_REGIME_PROGRAM``
        intent per approval. The gateway clones parent substance, validates
        the triggering classification, compiles, and records — producing a
        child program with ``parent_program_id``/``parent_hypothesis_ref``/
        ``target_regime`` linkage and ``produced_by='DETERMINISTIC'``.

        Idempotency: a pre-check skips proposals whose child already exists;
        gateway-level PA4 catches any race. Refusals are noted at most once
        per controller lifetime via ``_b3_refused_proposals``."""
        from hermes.core.intents import Intent, IntentKind
        from hermes.research.gateway import GatewayRejection, apply_intent
        # B3: the controller holds the lease-fenced connection from the tick.
        conn = self._fenced if self._fenced is not None else self._conn
        rows = conn.execute(
            "SELECT event_id, correlation_id, payload_json "
            "FROM events "
            "WHERE project_id = ? AND event_type = 'ClassificationActionProposed' "
            "ORDER BY event_id",
            (self._project_id,),
        ).fetchall()
        import json as _json

        from hermes.research.failure_classification import PermittedAction
        consumed: list[str] = []
        for r in rows:
            try:
                payload = _json.loads(r["payload_json"] or "{}")
            except ValueError:
                self.note(
                    f"B3: corrupt ClassificationActionProposed event "
                    f"{r['event_id']!r} — payload is not JSON; not consumed")
                continue
            if payload.get("action") != PermittedAction.PROPOSE_PARALLEL_REGIME_TEST.value:
                continue
            proposal_id = r["correlation_id"]
            # Skip if already emitted (pre-check).
            parent_program_id = payload.get("candidate_artifact_ref")
            target_regime = payload.get("target_regime", "")
            if not parent_program_id or not target_regime:
                self.note(
                    f"B3: proposal {proposal_id!r} missing parent_program_id or "
                    f"target_regime — not consumed")
                continue
            if proposal_id in self._b3_refused_proposals:
                continue
            if self._already_emitted_parallel_regime_child(
                    parent_program_id, target_regime):
                continue
            # Check for an APPROVED decision.
            decision = conn.execute(
                "SELECT payload_json FROM events "
                "WHERE event_type = 'ClassificationActionDecision' "
                "AND correlation_id = ? ORDER BY event_id LIMIT 1",
                (proposal_id,),
            ).fetchone()
            if decision is None:
                continue  # not yet decided — still pending
            try:
                d_payload = _json.loads(decision["payload_json"] or "{}")
            except ValueError:
                self.note(
                    f"B3: corrupt ClassificationActionDecision for proposal "
                    f"{proposal_id!r} — not consumed")
                continue
            if d_payload.get("decision") != "APPROVED":
                continue  # REJECTED or otherwise not approved
            # Resolve parent_hypothesis_ref from the classification artifact's
            # metadata (the proposal event does not carry it).
            cls_ref = payload.get("classification_ref", "")
            if cls_ref.startswith("failure_classification:"):
                cls_ref = cls_ref[len("failure_classification:"):]
            cls_meta = conn.execute(
                "SELECT metadata_json FROM artifacts "
                "WHERE project_id = ? AND artifact_type = ? "
                "AND (artifact_id = ? OR content_hash = ?)",
                (self._project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
                 cls_ref, cls_ref),
            ).fetchone()
            if cls_meta is None:
                self.note(
                    f"B3: proposal {proposal_id!r} references classification "
                    f"{cls_ref!r} that does not resolve — not consumed")
                continue
            try:
                meta = _json.loads(cls_meta["metadata_json"] or "{}")
                parent_hypothesis_ref = meta.get("hypothesis_ref", "")
            except ValueError:
                self.note(
                    f"B3: proposal {proposal_id!r} has corrupt classification "
                    f"metadata — not consumed")
                continue
            # Emit the EMIT_PARALLEL_REGIME_PROGRAM intent.
            intent = Intent(
                kind=IntentKind.EMIT_PARALLEL_REGIME_PROGRAM,
                proposed_by="DETERMINISTIC",
                project_id=self._project_id,
                payload={
                    "parent_program_id": parent_program_id,
                    "parent_hypothesis_ref": parent_hypothesis_ref,
                    "target_regime": target_regime,
                    "triggering_classification_id": cls_ref,
                },
                justification="ADR-041 B3: consume APPROVED "
                "PROPOSE_PARALLEL_REGIME_TEST proposal",
            )
            try:
                result = apply_intent(conn, intent, clock=self._clock)
                if result.duplicate:
                    # Gateway found an existing child with the same
                    # content_hash — already emitted, mark consumed.
                    consumed.append(proposal_id)
                else:
                    consumed.append(proposal_id)
            except GatewayRejection as exc:
                self.note(
                    f"B3: EMIT_PARALLEL_REGIME_PROGRAM for proposal "
                    f"{proposal_id!r} refused ({exc.code}): {exc}")
                self._b3_refused_proposals.add(proposal_id)
            except Exception as exc:  # noqa: BLE001 — audit, never silent
                self.note(
                    f"B3: EMIT_PARALLEL_REGIME_PROGRAM for proposal "
                    f"{proposal_id!r} failed: {exc}")
                self._b3_refused_proposals.add(proposal_id)
        return consumed

    def _ladder_current_rung(
        self, program_id: str, hypothesis_ref: str,
    ) -> str | None:
        """The head rung of the ladder cache for one (program, hypothesis)
        — the pass's own last output, COMPARED against (never trusted as)
        the derived rung."""
        row = self._fenced.execute(
            "SELECT rung FROM evidence_ladder_state "
            "WHERE project_id = ? AND program_id = ? AND hypothesis_ref = ? "
            "ORDER BY version DESC LIMIT 1",
            (self._project_id, program_id, hypothesis_ref),
        ).fetchone()
        return row["rung"] if row is not None else None

    def _ladder_transition_applied(self, transition_id: str) -> bool:
        """True iff the deterministic transition id is already on the audit
        (the idempotency guard — the same ratified facts can never apply a
        second transition)."""
        row = self._fenced.execute(
            "SELECT 1 FROM events "
            "WHERE event_type = ? AND correlation_id = ?",
            ("EvidenceTransitionApplied", transition_id),
        ).fetchone()
        return row is not None

    def _ladder_refuted_target(
        self, ratified: dict, programs: list[dict],
    ) -> tuple[str, str] | None:
        """The (program_id, hypothesis_ref) a ratified REJECT_BRANCH
        proposal targets — from its classification's ``program_ref`` +
        ``hypothesis_ref``, dereferenced against the loaded program context
        with the digest-valid identity discipline (classification_id must
        equal the artifact identity; the program must resolve in-project;
        the hypothesis must exist in it). None on ANY failure (fail-closed
        — a forged/corrupt classification never selects a target)."""
        cls_ref = ratified.get("classification_ref")
        if (not isinstance(cls_ref, str)
                or not cls_ref.startswith(FAILURE_CLASSIFICATION_REF_PREFIX)):
            return None
        content_hash = cls_ref[len(FAILURE_CLASSIFICATION_REF_PREFIX):]
        if not content_hash:
            return None
        import json as _json
        row = self._fenced.execute(
            "SELECT artifact_id, metadata_json FROM artifacts "
            "WHERE project_id = ? AND artifact_type = ? AND content_hash = ?",
            (self._project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
             content_hash),
        ).fetchone()
        if row is None:
            return None
        try:
            meta = _json.loads(row["metadata_json"] or "{}")
        except ValueError:
            return None
        if not isinstance(meta, dict):
            return None
        # digest-valid identity + the metadata the ratified write path
        # always stores (the classifications_digest discipline).
        if meta.get("classification_id") != row["artifact_id"]:
            return None
        h_ref = meta.get("hypothesis_ref")
        program_ref = meta.get("program_ref")
        if not isinstance(h_ref, str) or not h_ref:
            return None
        if not isinstance(program_ref, str) or not program_ref:
            return None
        prog_id = program_ref
        if program_ref.startswith("research_program:"):
            prog_id = program_ref[len("research_program:"):]
        program = next(
            (p for p in programs
             if str(p.get("program_id") or "") == prog_id
             or str(p.get("content_hash") or "") == prog_id),
            None)
        if program is None:
            return None
        # HR-07 — head binding: a ratified REFUTED must target the project's
        # CURRENT epistemic contract (the supersession-chain head); a
        # classification against a superseded program never selects a target.
        if str(program.get("program_id") or "") != (
                self._program_head_id(programs)):
            return None
        hyps = program.get("hypotheses") or []
        if not any(isinstance(h, dict) and h.get("ref") == h_ref
                   for h in hyps):
            return None
        return str(program.get("program_id") or ""), h_ref

    def _dependent_hypothesis_set(
        self, program_id: str, hypothesis_ref: str,
    ) -> list[dict[str, str]]:
        """The rival hypotheses of a falsified one (``rival_of == ref``)
        with their current ladder rung — the SAME dependent set the
        refutation advisory computes, folded into the ``RefutedApplied``
        event so event-catalog consumers see rival fallout without joining
        ladder state. Fail-closed per row: a corrupt program row or a
        hypothesis without a ref contributes nothing, never a crash."""
        programs: list[dict] = []
        for r in self._fenced.execute(
                "SELECT * FROM research_programs WHERE project_id = ?",
                (self._project_id,)).fetchall():
            try:
                programs.append(_research_program_row_to_dict(r))
            except ValueError:
                continue  # corrupt program row — never a fact source
        program = next(
            (p for p in programs
             if str(p.get("program_id") or "") == program_id), None)
        if program is None:
            return []
        dependents: list[dict[str, str]] = []
        for h in program.get("hypotheses") or []:
            if (isinstance(h, dict) and h.get("rival_of") == hypothesis_ref
                    and h.get("ref")):
                dependents.append({
                    "ref": str(h["ref"]),
                    "rung": self._ladder_current_rung(
                        program_id, str(h["ref"])) or "",
                })
        return sorted(dependents, key=lambda d: d["ref"])

    def _write_ladder_transition(
        self, *, program_id: str, hypothesis_ref: str, transition_id: str,
        from_rung: str | None, to_rung: str, driver: str,
        satisfied_classes: list[str] | None = None,
        proposal_id: str = "", classification_ref: str = "",
        evidence_artifact_ref: str = "", ratification_ref: str = "",
        constraint_ref: str = "", ratified_by: str = "",
        emit_event: bool = True,
    ) -> None:
        """One atomic ladder write: the ``evidence_ladder_state`` row
        (version = head + 1, content-derived state id) + the
        ``EvidenceTransitionApplied`` audit event in the SAME transaction
        — committed or rolled back together, so a mid-apply crash never
        leaves a half-state (AC-4). ``emit_event=False`` marks the
        cache-REPAIR write (a tampered cache corrected to the true derived
        rung): observable via the note, never presented as an applied
        transition."""
        from hermes.research.evidence_ladder import ladder_state_id
        conn = self._fenced
        conn.execute("BEGIN")
        try:
            head = conn.execute(
                "SELECT version FROM evidence_ladder_state "
                "WHERE project_id = ? AND program_id = ? "
                "  AND hypothesis_ref = ? "
                "ORDER BY version DESC LIMIT 1",
                (self._project_id, program_id, hypothesis_ref),
            ).fetchone()
            version = (int(head["version"]) + 1) if head is not None else 1
            conn.execute(
                "INSERT INTO evidence_ladder_state "
                "(state_id, project_id, program_id, hypothesis_ref, "
                " version, rung, transition_id, derived_from, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ladder_state_id(program_id, hypothesis_ref, version),
                 self._project_id, program_id, hypothesis_ref, version,
                 to_rung, transition_id, driver, self._clock()),
            )
            if emit_event:
                payload: dict[str, Any] = {
                    "program_id": program_id,
                    "hypothesis_ref": hypothesis_ref,
                    "from_rung": from_rung or "",
                    "to_rung": to_rung,
                    "driver": driver,
                }
                if driver == "ratification":
                    payload["ratified_by"] = ratified_by
                    if proposal_id:
                        payload["proposal_id"] = proposal_id
                    if classification_ref:
                        payload["classification_ref"] = classification_ref
                    if evidence_artifact_ref:
                        payload["evidence_artifact_ref"] = evidence_artifact_ref
                    if ratification_ref:
                        payload["ratification_ref"] = ratification_ref
                    if constraint_ref:
                        payload["constraint_ref"] = constraint_ref
                else:
                    payload["requirement_ref"] = hypothesis_ref
                    payload["satisfied_artifact_classes"] = sorted(
                        satisfied_classes or [])
                _append_event_to_db(
                    conn, self._clock, "EvidenceTransitionApplied",
                    project_id=self._project_id, correlation_id=transition_id,
                    from_state=from_rung, to_state=to_rung,
                    caused_by="controller",
                    reason=(f"evidence ladder {driver} transition: "
                            f"{from_rung or '(none)'} -> {to_rung}"),
                    payload=payload,
                )
                # RefutedApplied — the first-class FALSIFICATION fact: when
                # the bare-classification driver (AC-2 driver 3, ratified_by
                # == "classification") applies the terminal rung, the same
                # atomic write ALSO records the falsification as its own
                # event-catalog member, so consumers subscribe to the fact
                # directly (no ladder-row reads, no payload filtering).
                # Same correlation_id (the transition id) — the two records
                # join cleanly. Proposal-ratified REFUTED and obligation
                # climbs never emit it.
                if (to_rung == "REFUTED" and ratified_by == "classification"):
                    # F8 (audit): the dependent-hypothesis fallout is
                    # bounded to the event cap. A program with many rivals
                    # used to blow past 4096 bytes, the append raised, the
                    # write rolled back and RE-RAISED through tick() — a
                    # legitimate falsification CRASHED the controller loop
                    # (probe-confirmed with 200 rivals). Now the SORTED
                    # dependent list is truncated deterministically to fit;
                    # the full count is recorded on the payload and the
                    # truncation is surfaced as a note (never silent).
                    deps = self._dependent_hypothesis_set(
                        program_id, hypothesis_ref)
                    payload = {
                        "program_id": program_id,
                        "hypothesis_ref": hypothesis_ref,
                        "classification_ref": classification_ref,
                        "constraint_ref": constraint_ref,
                        "dependent_hypotheses": deps,
                        "dependent_count": len(deps),
                    }
                    from hermes.persistence.event_validation import (
                        DEFAULT_PAYLOAD_MAX_BYTES,
                        EventValidationError,
                        validate_payload_size,
                    )
                    while deps:
                        try:
                            validate_payload_size(
                                payload, max_bytes=DEFAULT_PAYLOAD_MAX_BYTES)
                            break
                        except EventValidationError:
                            deps = deps[:-1]
                            payload["dependent_hypotheses"] = deps
                    if len(deps) < payload["dependent_count"]:
                        self.note(
                            f"Evidence Ladder: RefutedApplied payload "
                            f"bounded — {payload['dependent_count']} "
                            f"dependent hypotheses truncated to "
                            f"{len(deps)} for the event cap (F8 audit); "
                            f"the full count is recorded")
                    _append_event_to_db(
                        conn, self._clock, "RefutedApplied",
                        project_id=self._project_id,
                        correlation_id=transition_id,
                        from_state=from_rung, to_state=to_rung,
                        caused_by="controller",
                        reason=("evidence ladder falsification: a "
                                "digest-valid Q-05 classification certified "
                                "a decisive falsification"),
                        payload=payload,
                    )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def evidence_ladder_transitions(self) -> dict:
        """READ-ONLY advisory: the applied evidence-ladder transitions (the
        audit events), deterministic event_id order. The APPLY pass's
        observable output — never writes, never a scheduler input."""
        import json as _json
        rows = self._conn.execute(
            "SELECT correlation_id, from_state, to_state, payload_json, "
            "       created_at FROM events "
            "WHERE project_id = ? AND event_type = ? ORDER BY event_id",
            (self._project_id, "EvidenceTransitionApplied"),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for r in rows:
            try:
                payload = _json.loads(r["payload_json"] or "{}")
            except ValueError:
                payload = {}
            items.append({
                "transition_id": r["correlation_id"],
                "from_rung": r["from_state"],
                "to_rung": r["to_state"],
                "payload": (payload if isinstance(payload, dict) else {}),
                "created_at": r["created_at"],
            })
        return {"items": items}

    def bare_classification_falsifications(self) -> dict:
        """READ-ONLY advisory: the applied BARE-CLASSIFICATION REFUTED
        facts (IDR-041 AC-2 deferred branch) — the ``RefutedApplied`` audit
        events: falsifications certified by a digest-valid Q-05
        classification ALONE, no transition proposal, no ladder-row reads.
        Deterministic (event_id order), read-only — the falsification
        FACTS, distinct from ``refutation_review_candidates`` (the
        re-review SET those facts demand). Fail-closed: a corrupt payload
        contributes nothing, never a crash."""
        import json as _json
        items: list[dict[str, Any]] = []
        for r in self._conn.execute(
                "SELECT correlation_id, from_state, to_state, payload_json, "
                "       created_at FROM events "
                "WHERE project_id = ? "
                "  AND event_type = 'RefutedApplied' "
                "ORDER BY event_id",
                (self._project_id,),
        ).fetchall():
            try:
                payload = _json.loads(r["payload_json"] or "{}")
            except ValueError:
                payload = {}
            if not isinstance(payload, dict):
                continue
            deps = payload.get("dependent_hypotheses")
            items.append({
                "transition_id": r["correlation_id"],
                "program_id": str(payload.get("program_id") or ""),
                "hypothesis_ref": str(payload.get("hypothesis_ref") or ""),
                "classification_ref": str(
                    payload.get("classification_ref") or ""),
                "constraint_ref": str(payload.get("constraint_ref") or ""),
                "dependent_hypotheses": (
                    deps if isinstance(deps, list) else []),
                "created_at": r["created_at"],
            })
        return {"items": items}

    def refutation_review_candidates(self) -> dict:
        """READ-ONLY advisory (the Q-04 blast radius x the Evidence Ladder):
        for every APPLIED REFUTED transition (the terminal rung — ratified
        by proposal or by bare classification), the concrete re-review set
        the falsification demands: the falsified hypothesis's evidence base
        (its satisfaction-linked artifacts + the falsification
        classification's cited evidence, when resolvable), every DOWNSTREAM
        artifact over ``provenance_edges`` (the artifact blast radius), and
        the DEPENDENT hypotheses — the program's hypotheses that rival the
        falsified one (``rival_of == hypothesis_ref``), with their current
        ladder rung. Fail-closed per row: a corrupt payload or an
        unresolvable classification contributes nothing and is never a
        crash; deterministic (sorted ladder rows, sorted seeds). Never
        writes — names what needs re-review after a falsification, changes
        nothing."""
        import json as _json
        rows = self._conn.execute(
            "SELECT program_id, hypothesis_ref, transition_id "
            "FROM evidence_ladder_state "
            "WHERE project_id = ? AND rung = 'REFUTED' "
            "ORDER BY program_id, hypothesis_ref",
            (self._project_id,),
        ).fetchall()
        prov = self._conn.execute(
            """SELECT e.upstream_id, e.artifact_id, e.edge_type
               FROM provenance_edges e
               JOIN artifacts a ON a.artifact_id = e.artifact_id
               WHERE a.project_id = ?""",
            (self._project_id,),
        ).fetchall()
        downstream: dict[str, list[tuple[str, str]]] = {}
        cites: dict[str, list[str]] = {}
        for r in prov:
            downstream.setdefault(r["upstream_id"], []).append(
                (r["artifact_id"], r["edge_type"]))
            if r["edge_type"] == "cites":
                cites.setdefault(r["artifact_id"], []).append(
                    r["upstream_id"])
        satisfaction_ids: dict[tuple[str, str], list[str]] = {}
        for r in self._conn.execute(
                "SELECT program_id, requirement_ref, artifact_id "
                "FROM program_requirement_satisfactions"):
            satisfaction_ids.setdefault(
                (r["program_id"], r["requirement_ref"]), []).append(
                    r["artifact_id"])
        payload_by_tid: dict[str, dict] = {}
        for r in self._conn.execute(
                "SELECT correlation_id, payload_json FROM events "
                "WHERE project_id = ? "
                "  AND event_type = 'EvidenceTransitionApplied'",
                (self._project_id,),
        ).fetchall():
            try:
                payload = _json.loads(r["payload_json"] or "{}")
            except ValueError:
                payload = {}
            if isinstance(payload, dict):
                payload_by_tid[r["correlation_id"]] = payload
        by_hash: dict[str, str] = {}
        for r in self._conn.execute(
                "SELECT artifact_id, content_hash FROM artifacts "
                "WHERE project_id = ?", (self._project_id,)).fetchall():
            by_hash.setdefault(r["content_hash"], r["artifact_id"])
        programs: list[dict] = []
        for pr in self._conn.execute(
                "SELECT * FROM research_programs WHERE project_id = ?",
                (self._project_id,)).fetchall():
            try:
                programs.append(_research_program_row_to_dict(pr))
            except ValueError:
                continue  # corrupt program row — never a fact source
        items: list[dict[str, Any]] = []
        for r in rows:
            pid, h_ref, tid = (r["program_id"], r["hypothesis_ref"],
                               r["transition_id"])
            program = next(
                (p for p in programs
                 if str(p.get("program_id") or "") == pid), None)
            if program is None:
                continue  # foreign program — nothing to surface
            hyps = program.get("hypotheses") or []
            if not any(isinstance(h, dict) and h.get("ref") == h_ref
                       for h in hyps):
                continue  # foreign hypothesis — nothing to surface
            # evidence base: the satisfaction-linked artifacts of the
            # falsified hypothesis + the classification's cited evidence
            seeds = list(satisfaction_ids.get((pid, h_ref), ()))
            payload = payload_by_tid.get(tid, {})
            cls_ref = payload.get("classification_ref")
            if isinstance(cls_ref, str) and cls_ref:
                prefix, sep, h = cls_ref.partition(":")
                if sep and prefix == "failure_classification":
                    cls_aid = by_hash.get(h)
                    if cls_aid is not None:
                        seeds.extend(cites.get(cls_aid, ()))
            seeds = sorted(set(seeds))
            radius = artifact_blast_radius(seeds, downstream)
            dependents = sorted(
                str(h.get("ref")) for h in hyps
                if isinstance(h, dict) and h.get("rival_of") == h_ref
                and h.get("ref"))
            items.append({
                "program_id": pid,
                "hypothesis_ref": h_ref,
                "transition_id": tid,
                "evidence_base": seeds,
                "downstream_artifacts": [{
                    "artifact_id": e.artifact_id,
                    "reached_via": e.reached_via,
                    "edge_type": e.edge_type,
                } for e in radius],
                "dependent_hypotheses": [{
                    "ref": dref,
                    "rung": self._ladder_current_rung(pid, dref) or "",
                } for dref in dependents],
            })
        return {
            "version": GRAPH_QUERY_VERSION,
            "items": items,
            "content_hash": graph_result_hash(
                "refutation_review_candidates", items),
        }

    def _cone_blocked_dispatch_notes(self) -> list[tuple[str, str]]:
        """Q-04 §3.4: when a dispatch pass finds nothing eligible, surface a
        diagnostic note when the idle dispatch is blocked by a failure cone
        whose blocking ancestor carries a Q-05 classification ("blocked by
        research_program:...: task FAILED — IMPLEMENTATION_FAILURE") —
        diagnostic only; the eligibility logic is untouched (this is the
        TRANSITIVE view of the same predicate, never a second gate). Empty
        when nothing is blocked by a classified ancestor. FIX-NOTES-DEDUP:
        each entry is ``(condition_key, message)`` — the key is stable per
        blocking ancestor, so the caller can dedupe across ticks."""
        dependents, statuses, labels = self._load_task_graph_state()
        classified = sorted(
            t for t, s in statuses.items()
            if s != TaskStatus.SUCCEEDED.value and labels.get(t))
        if not classified:
            return []
        cone = failure_cone(classified, dependents, statuses, labels)
        blocked_by: dict[str, list[str]] = {}
        for e in cone:
            # F10: the note is a DISPATCH diagnostic — a SUCCEEDED cone
            # member already ran and is not blocked (only reachable via
            # tampered state; the ladder forbids it). Never claim one is.
            if (labels.get(e.blocking_ancestor)
                    and statuses.get(e.task_id, "")
                    != TaskStatus.SUCCEEDED.value):
                blocked_by.setdefault(e.blocking_ancestor, []).append(
                    e.task_id)
        return [
            (f"cone-blocked:{ancestor}",
             "Q-04: dispatch blocked by failure cone of task "
             f"{ancestor} ({statuses.get(ancestor, '?')} — "
             f"{labels[ancestor]}); blocked dependents: "
             + ", ".join(sorted(blocked_by[ancestor])))
            for ancestor in sorted(blocked_by)
        ]

    def _parked_gate_invalidated_dep_notes(self) -> list[tuple[str, str]]:
        """P2 #3 diagnostic: surface on the notes channel when a parked
        HUMAN_GATE sits at WAITING_HUMAN while one of its dependencies was
        INVALIDATED AFTER the gate parked — so the operator sees WHY the
        wave is parked (the dep that once SUCCEEDED no longer does) and that
        the operator verdict is the escape hatch. Diagnostic only: this is
        never a gate, never a veto, and the eligibility logic is untouched —
        the verdict itself (``resolve_human_gate``) is the escape. Empty
        when no parked gate has an INVALIDATED dependency. FIX-NOTES-DEDUP:
        each entry is ``(condition_key, message)`` — the key is stable per
        gate, so the caller can dedupe across ticks."""
        rows = self._fenced.execute(
            "SELECT task_id FROM tasks "
            "WHERE project_id = ? AND task_type = 'HUMAN_GATE' "
            "  AND status = 'WAITING_HUMAN'",
            (self._project_id,)).fetchall()
        notes: list[tuple[str, str]] = []
        for row in rows:
            gate_id = row["task_id"]
            invalidated = sorted(
                dep_id for dep_id in self._task_repo.get_dependencies(gate_id)
                if self._task_repo.get_status(dep_id) is TaskStatus.INVALIDATED)
            if invalidated:
                notes.append(
                    (f"parked-gate-invalidated:{gate_id}",
                     (f"gate {gate_id} is parked at WAITING_HUMAN and its "
                      f"dependency {invalidated[0]} was INVALIDATED after "
                      f"the gate parked — the operator verdict is the "
                      f"escape hatch "
                      f"(resolve_human_gate APPROVED/REJECTED)")))
        return notes

    def _plan_admission_pass(self) -> list[str]:
        """IDR-045 D1 — plan-admission pass (ACTIVE-only, pre-dispatch).

        Eligibility: the ACTIVE-filtered head (MAX(version) WHERE
        parent_program_id IS NULL — C1, never unfiltered current()). When the
        filtered head exists and is parseable, project its plan (build_task_plan
        + plan_to_payloads) and admit every payload through apply_intent as
        Intent(kind=ADMIT_TASK, proposed_by=DETERMINISTIC) with
        origin_kind=deterministic / origin_ref=plan_admission_pass (D2).
        Per-payload apply_intent loop, NO bulk transaction (C6) — a crash
        after k-of-n leaves k committed rows and re-tick completes to n via
        idempotent ADMIT_TASK. ADMIT_TASK/DETERMINISTIC only (P4 is structural
        — the gateway ROLE gate rejects any other pairing).
        Supersession: leave-in-place + admit-new-DAG (C2 — old rows remain; a
        new head yields disjoint task_ids via _identity). A tick where every
        plan task already exists adds no rows and emits no note: that is the
        C2 no-op, and it is distinguishable from a failure because a failure
        always records a note.

        Runs every ACTIVE tick before the evidence-ladder / dispatch passes, so
        plan tasks are committed as PENDING before dispatch scans for eligible
        work. It is not gated on a "readiness" computation: ``tick()`` has none
        (the ordering argument is the dispatch scan, not a readiness pass).

        Failure discipline (MERGE-AUDIT-045 §2.3): **no outcome is swallowed.**
        An unreadable head, an unparseable program, a non-compiler-derived
        program, an uncompilable program, a gateway refusal, and an unexpected
        exception from the gateway each record a note via ``_note_once`` and
        are visible on ``Controller.notes``. A tick that ends with any refusal
        records the partial-DAG shortfall explicitly, so a permanently partial
        task graph can never be mistaken for a healthy wave parked at a gate.

        Returns the newly admitted task_ids. The return is a convenience for
        direct callers; operator visibility comes from ``Controller.notes``.
        """
        from hermes.core.intents import Intent, IntentKind
        from hermes.research.gateway import GatewayRejection, apply_intent
        from hermes.research.programs import program_from_dict
        from hermes.research.task_plan import build_task_plan, plan_to_payloads

        conn = self._fenced if self._fenced is not None else self._conn
        # Filtered head (C1) — never unfiltered current() / _program_head_id.
        row = conn.execute(
            "SELECT * FROM research_programs WHERE project_id = ? "
            "AND parent_program_id IS NULL ORDER BY version DESC LIMIT 1",
            (self._project_id,),
        ).fetchone()
        if row is None:
            # No compiled program yet — the normal cold-start case, not a failure.
            return []
        head = str(row["program_id"])
        # Parse the stored row via the persistence mapper.
        try:
            from hermes.persistence.repositories import _research_program_row_to_dict
            d = _research_program_row_to_dict(row)
        except Exception as exc:  # noqa: BLE001 — recorded, never silent
            self._note_once(
                f"plan admission skipped: primary head {head} could not be read "
                f"as a program row ({type(exc).__name__}: {exc}) — no plan task "
                f"was admitted and nothing else reports this",
                key=f"plan-admission:unreadable-head:{head}",
            )
            return []
        try:
            program = program_from_dict(d)
        except Exception as exc:  # noqa: BLE001 — recorded, never silent
            self._note_once(
                f"plan admission skipped: primary head {head} does not parse as "
                f"a compiled program ({type(exc).__name__}: {exc}) — the plan is "
                f"unavailable until the head is repaired",
                key=f"plan-admission:unparseable-head:{head}",
            )
            return []
        # Compiled-program validity (prevents synthetic q02 fixtures from stealing
        # plan admission: a row whose obligations do not re-derive from its own
        # hypotheses is not a compiler output).
        try:
            from hermes.research.programs import derive_program_obligations
            # `_expected_gates` is deliberately unused: MERGE-AUDIT-045 F3
            # records that this fence compares evidence_requirements only,
            # while build_task_plan selects gates from gate_requirements.
            # Closing that gap is an eligibility change, tracked in
            # docs/idr/IDR-045.md D1.2, not a merge-blocker fix.
            expected_ev, _expected_gates = derive_program_obligations(
                program.hypotheses)
        except Exception as exc:  # noqa: BLE001 — recorded, never silent
            self._note_once(
                f"plan admission skipped: obligation derivation failed for "
                f"program {head} ({type(exc).__name__}: {exc})",
                key=f"plan-admission:derive-failed:{head}",
            )
            return []
        if tuple(program.evidence_requirements) != tuple(expected_ev):
            self._note_once(
                f"plan admission skipped: program {head} evidence_requirements "
                f"do not re-derive from its hypotheses — not a compiler output, "
                f"so no plan is admitted for it",
                key=f"plan-admission:not-compiler-derived:{head}",
            )
            return []
        try:
            plan = build_task_plan(program)
        except ValueError as exc:
            self._note_once(
                f"plan admission skipped: program {head} is uncompiled "
                f"({exc}) — build_task_plan refused, no plan task admitted",
                key=f"plan-admission:uncompiled:{head}",
            )
            return []
        payloads = plan_to_payloads(plan, self._project_id)
        admitted: list[str] = []
        refusals: list[str] = []
        for payload in payloads:
            intent = Intent(
                kind=IntentKind.ADMIT_TASK,
                proposed_by="DETERMINISTIC",
                project_id=self._project_id,
                payload=payload,
                justification=f"IDR-045 plan admission for program {program.program_id}",
                origin_kind="deterministic",
                origin_ref="plan_admission_pass",
            )
            task_id = str(payload.get("task_id", ""))
            try:
                result = apply_intent(conn, intent, clock=self._clock)
                if not result.duplicate:
                    admitted.append(result.entity_id)
            except GatewayRejection as exc:
                # Recorded with its stable code, never discarded. A missing
                # dependency is a P2-violation that a later apply_intent in
                # ordered sequence may resolve (prefix-closed); a refusal that
                # persists across ticks is a real blockage and this note is how
                # the operator learns about it. apply_intent has already
                # journalled its own IntentRejected row.
                refusals.append(f"{task_id} -> {exc.code}: {exc}")
            except Exception as exc:  # noqa: BLE001 — recorded, never silent
                # An unexpected exception from the gateway is not a refusal; it
                # is a fault. It is recorded distinctly so "refused" can never
                # be mistaken for "crashed".
                refusals.append(f"{task_id} -> FAULT {type(exc).__name__}: {exc}")
        if refusals:
            shown = "; ".join(refusals[:3])
            if len(refusals) > 3:
                shown += f"; (+{len(refusals) - 3} more)"
            self._note_once(
                f"plan admission INCOMPLETE for program {head}: "
                f"{len(admitted)} of {len(payloads)} plan task(s) newly admitted, "
                f"{len(refusals)} refused [{shown}] — the task DAG is permanently "
                f"partial until the refusal cause is fixed; the outward tick "
                f"result does not carry this",
                key=f"plan-admission:incomplete:{head}",
            )
        return admitted

    @staticmethod
    def _is_sequencer_task(task: dict) -> bool:
        """True iff the row is a sequencer artifact (F1 predicate).

        Predicate is the recorded ``spec.template == "sequencer"`` marker
        plus project scope (callers only pass same-project rows) — never
        the ``seq-`` ID prefix, which any admitted task_id may forge
        (gateway honors arbitrary non-empty task_ids). Accepts decoded
        task dicts (``spec`` mapping) and raw rows (``spec_json`` text).
        """
        import json as _json

        spec = task.get("spec", task.get("spec_json", {}))
        if isinstance(spec, str):
            try:
                spec = _json.loads(spec)
            except ValueError:
                return False
        template = spec.get("template") if isinstance(spec, dict) else None
        return (
            isinstance(template, str)
            and template.strip().casefold() == "sequencer"
        )

    def _sequencer_pass(self) -> list[str]:
        """P-AUTO-1 — deterministic sequencer pass.

        Reads READY tasks + dependencies + terminal states + ladder/failure
        signals via existing repository methods only. Emits ADMIT_TASK with
        proposed_by=DETERMINISTIC through apply_intent only. Dependency-respect
        ordering (topological sort). No-op when nothing ready.

        Starvation-freedom: every READY task is included in the sequence
        on every tick it is READY, in a deterministic order derived from
        the dependency DAG (content-addressed task_ids, fixed dependency
        edges, lexicographic tie-break) — never from arrival time or
        priority. Positions may shift as the ready set changes, but no
        READY task can be permanently displaced: the order for a fixed
        ready set is stable, and a later-ready task takes precedence only
        through a dependency edge or a smaller task_id, neither of which
        arrival order controls.
        """
        import hashlib

        from hermes.core.intents import Intent, IntentKind
        from hermes.core.task_status import TaskStatus
        from hermes.persistence.repositories import (
            NotFoundError,
            TaskRepository,
        )
        from hermes.research.gateway import GatewayRejection, apply_intent

        task_repo = TaskRepository(self._fenced, self._clock)

        # Discover READY tasks (PENDING/READY/RETRYING with all deps SUCCEEDED)
        ready_tasks = self._discover_eligible()
        # Filter out sequencer tasks (they are internal sequencing artifacts).
        # F1: the predicate is the spec.template marker, not the seq- ID
        # prefix — a user task_id starting with seq- is sequenced normally.
        ready_tasks = [
            t for t in ready_tasks if not self._is_sequencer_task(t)
        ]
        if not ready_tasks:
            return []

        # Build dependency graph for topological sort
        task_map = {t["task_id"]: t for t in ready_tasks}
        task_ids = list(task_map.keys())

        # Get all dependencies for each ready task (including deps not in ready set)
        all_deps: dict[str, list[str]] = {}
        for task_id in task_ids:
            deps = task_repo.get_dependencies(task_id)
            all_deps[task_id] = deps

        # Topological sort (Kahn's algorithm) — deterministic via sorted task_ids
        # for tie-breaking, ensuring reproducibility.
        in_degree: dict[str, int] = dict.fromkeys(task_ids, 0)
        adj: dict[str, list[str]] = dict.fromkeys(task_ids, [])
        # dict.fromkeys shares the same list; create separate lists
        for tid in task_ids:
            adj[tid] = []
        for tid in task_ids:
            for dep in all_deps[tid]:
                if dep in task_ids:
                    adj[dep].append(tid)
                    in_degree[tid] += 1

        # Deterministic queue: always process lexicographically smallest first
        queue = sorted([tid for tid in task_ids if in_degree[tid] == 0])
        ordered: list[str] = []
        while queue:
            tid = queue.pop(0)
            ordered.append(tid)
            for succ in sorted(adj[tid]):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)
            queue.sort()

        # Cycle detection (should not happen in a valid DAG)
        if len(ordered) != len(task_ids):
            self._note_once(
                "sequencer: cycle detected in ready task subgraph; "
                "falling back to created_at order",
                key="sequencer:cycle-detected",
            )
            ordered = sorted(
                task_ids,
                key=lambda tid: (task_map[tid].get("created_at", ""), tid),
            )

        # Emit ADMIT_TASK for sequencing — each sequencer task is a TOOL_TASK
        # with template="sequencer" that records the determined order.
        # The idempotency_key is derived from the ordered sequence, so
        # re-running the pass produces the same task_id (no duplicates).
        # Check if sequencer task already exists to avoid duplicate IntentApplied events.
        # Invalidate any existing sequencer tasks for this project (only one active).
        seq_idempotency = hashlib.sha256(
            str(sorted(ordered)).encode()
        ).hexdigest()[:32]
        seq_task_id = f"seq-{self._project_id}-{seq_idempotency}"

        # Cancel any existing sequencer tasks for this project (PENDING/READY only)
        # to ensure only the latest sequencer is active. The LIKE pre-filter
        # narrows (defense-in-depth); the template predicate decides (F1).
        existing_seq_rows = self._fenced.execute(
            "SELECT task_id, spec_json FROM tasks WHERE project_id = ? AND task_id LIKE ? "
            "AND status IN ('PENDING', 'READY')",
            (self._project_id, "seq-%"),
        ).fetchall()
        for row in existing_seq_rows:
            old_seq_id = row["task_id"]
            if old_seq_id != seq_task_id and self._is_sequencer_task(dict(row)):
                try:
                    task_repo.transition_status(
                        old_seq_id, TaskStatus.CANCELLED, caused_by="sequencer",
                        reason="superseded by new sequencer pass")
                except LockLostError:
                    raise
                except Exception as exc:  # noqa: BLE001 — recorded, never silent
                    self._note_once(f"sequencer: cancel fault: {exc}",
                                    key=f"sequencer:cancel-fault:{old_seq_id}")

        # Check if current sequencer task already exists (idempotency guard)
        existing_seq = None
        try:
            existing_seq = task_repo.get(seq_task_id)
        except LockLostError:
            raise
        except NotFoundError:
            pass  # routine first pass for this ready set — not a fault
        except Exception as exc:  # noqa: BLE001 — recorded, never silent
            self._note_once(f"sequencer: get fault: {exc}",
                            key=f"sequencer:get-fault:{seq_task_id}")

        admitted: list[str] = []
        if existing_seq is None:
            intent = Intent(
                kind=IntentKind.ADMIT_TASK,
                proposed_by="DETERMINISTIC",
                project_id=self._project_id,
                payload={
                    "task_id": seq_task_id,
                    "task_type": "TOOL_TASK",
                    "profile": None,
                    "idempotency_key": seq_idempotency,
                    "iteration": 1,
                    "spec": {
                        "template": "sequencer",
                        "sequence": ordered,
                        "sequencer_version": 1,
                    },
                    "inputs": [],
                    "outputs": ["sequencer:order"],
                    "dependencies": [],
                    "provenance": [f"sequencer_pass:{self._project_id}"],
                    "cost_class": "LOW",
                },
                justification=f"P-AUTO-1 deterministic sequencer for {len(ordered)} ready tasks",
                origin_kind="deterministic",
                origin_ref="sequencer_pass",
            )
            try:
                result = apply_intent(self._fenced, intent, clock=self._clock)
                if not result.duplicate:
                    admitted.append(result.entity_id)
            except GatewayRejection as exc:
                self._note_once(
                    f"sequencer: ADMIT_TASK refused ({exc.code}): {exc}",
                    key=f"sequencer:refused:{exc.code}",
                )
            except Exception as exc:  # noqa: BLE001 — recorded, never silent
                self._note_once(
                    f"sequencer: FAULT {type(exc).__name__}: {exc}",
                    key=f"sequencer:fault:{seq_task_id}",
                )

        return admitted

    def _dispatch_pass(self) -> TickResult:
        result = TickResult()
        calls = 0
        # FIX-F — first cap-skip code seen this tick: when caps skip every
        # task, the tick still emits a named idle code (never a silent
        # empty tick that reads as clean completion).
        skipped_code = ""
        tasks = self._discover_eligible()
        if self._enable_epistemic_ordering:
            tasks, ranking = self._order_eligible(tasks)
            if ranking is not None:
                # Q-02 §9: every dispatch records the applied policy version,
                # so execution is auditable against the exact ordering policy.
                result.ordering_policy_version = ranking.policy_version
                # C4 §4.3: the floor's durable substrate — every floor grant
                # / F-C transition is appended as a FloorGrantRecorded event
                # (the ranking itself is transient). The F-C counter is
                # re-derived from these events + the satisfaction links.
                self._persist_floor_transitions(ranking)
        if not tasks:
            # Q-04 §3.4: diagnostic-only note when the dispatch attempt is
            # idle and blocked by a classified failure cone — the eligibility
            # logic is untouched; the note is advice on the channel only.
            # FIX-NOTES-DEDUP: routed through _note_once (keyed by blocking
            # ancestor) — an idle dispatch re-reports the same cone every
            # tick, and _notes is never cleared.
            for key, line in self._cone_blocked_dispatch_notes():
                self._note_once(line, key=key)
        for task in tasks:
            spec = task.get("spec") or {}
            template = (spec.get("template") or "").strip().casefold()
            task_id = task["task_id"]

            # Fail-closed: never dispatch a task the controller cannot
            # execute (criterion 9 — never a silent SUCCEEDED).
            kind = self._classify(task, template)
            if kind == "unhandled":
                result.unhandled.append(task_id)
                continue

            # P-AUTO-4 envelopes (checked BEFORE claiming — a capped task is
            # never stranded RUNNING; every breach is a named refusal on the
            # notes channel, never silent success, never a model judgment).
            # Budget precedes the liveness floor so an explicit tight budget
            # reports its own code (the floor still bounds via the
            # max(per_tick, max_calls) construction default).
            if self._loops.is_quarantined(task_id):
                self._note_once(
                    f"dispatch refused for {task_id}: "
                    f"{self._loops.reason_for(task_id)}",
                    key=f"p-auto-4:quarantined:{task_id}")
                if not skipped_code:
                    skipped_code = LOOP_PATTERN_QUARANTINED
                continue
            if self._tick_wall_exceeded():
                self._note_once(
                    f"tick wall-clock exceeded "
                    f"({WALLCLOCK_TICK_DEADLINE_EXCEEDED}) — tick stops",
                    key="p-auto-4:tick-wall-exceeded")
                result.idle = WALLCLOCK_TICK_DEADLINE_EXCEEDED
                break
            if self._run_wall_exceeded():
                self._note_once(
                    f"run wall-clock exceeded "
                    f"({WALLCLOCK_RUN_DEADLINE_EXCEEDED}) — run stops",
                    key="p-auto-4:run-wall-exceeded")
                result.idle = WALLCLOCK_RUN_DEADLINE_EXCEEDED
                break
            tokens = self._estimate_tokens(task)
            step_code = self._budget.check_step(task_id)
            if step_code in (BUDGET_PER_TICK_STEPS_EXCEEDED,
                             BUDGET_PER_RUN_STEPS_EXCEEDED):
                self._note_once(
                    f"dispatch refused: {step_code} — tick/run stops",
                    key=f"p-auto-4:{step_code}")
                result.idle = step_code
                break
            if step_code == BUDGET_PER_TASK_STEPS_EXCEEDED:
                self._note_once(
                    f"dispatch refused for {task_id}: {step_code}",
                    key=f"p-auto-4:{step_code}:{task_id}")
                if not skipped_code:
                    skipped_code = step_code
                continue
            token_code = self._budget.check_tokens(task_id, tokens)
            if token_code in (BUDGET_PER_TICK_TOKENS_EXCEEDED,
                              BUDGET_PER_RUN_TOKENS_EXCEEDED):
                self._note_once(
                    f"dispatch refused: {token_code} — tick/run stops",
                    key=f"p-auto-4:{token_code}")
                result.idle = token_code
                break
            if token_code == BUDGET_PER_TASK_TOKENS_EXCEEDED:
                self._note_once(
                    f"dispatch refused for {task_id}: {token_code}",
                    key=f"p-auto-4:{token_code}:{task_id}")
                if not skipped_code:
                    skipped_code = token_code
                continue

            # Liveness floor (IDR-029 Decision 5): the cap is checked BEFORE
            # claiming, so a capped task is never stranded RUNNING.
            if kind == "extract" and calls >= self._max_calls_per_tick:
                result.idle = "max_calls_per_tick"
                break

            # Claim: READY → RUNNING (atomic; PENDING → READY first). The
            # claim is the dispatch — heartbeat it (the controller is the
            # worker for the tasks it claims).
            try:
                if TaskStatus(task["status"]) is TaskStatus.PENDING:
                    self._task_repo.transition_status(
                        task_id, TaskStatus.READY, caused_by="controller")
                self._task_repo.transition_status(
                    task_id, TaskStatus.RUNNING, caused_by="controller")
            except TaskTransitionError:
                # F15-audit: a STALE controller (or a racing one) may reach
                # an eligibility snapshot whose statuses have moved — e.g.
                # a late-returning handler after the lease was reclaimed, or
                # a task already completed/resolved by the current owner.
                # The claim validates the transition BEFORE any write, so
                # the fence never fires; fail closed here (IDR29-02 case a:
                # do NOT transition, log, and let recovery re-examine) —
                # never an unhandled crash out of the tick loop.
                self.note(
                    f"claim refused for {task_id}: status moved since "
                    f"discovery — recovery owns it; skipped")
                continue
            self._task_repo.heartbeat(task_id)
            result.dispatched.append(task_id)
            # Count the claimed dispatch against the P-AUTO-4 envelope (the
            # pre-claim checks above guarantee these consume cleanly).
            # FIX-A1 — steps here for every dispatch; tokens split by kind:
            # handler-backed dispatches charge MEASURED transport requests
            # inside _run_handler, every other kind charges its (exact,
            # non-provider) estimate here so nothing runs uncounted.
            self._budget.consume_step(task_id)
            if kind not in self._task_handlers:
                self._budget.consume_tokens(task_id, tokens)

            if kind == "extract":
                calls += 1
                outcome = self._execute_extract(task_id)
                result.model_calls += outcome.model_calls
                result.succeeded.extend(outcome.succeeded)
                result.retried.extend(outcome.retried)
                result.failed.extend(outcome.failed)
            elif kind == "human_gate":
                outcome = self._park_human_gate(task_id)
                result.waiting_human.extend(outcome)
                result.idle = "waiting_human"   # the wave stops here
                break
            elif kind == "gate":
                if self._gate_verdict_fn is None:
                    # should be unreachable (classify handles None) — safety
                    result.unhandled.append(task_id)
                    continue
                verdict = self._gate_verdict_fn(task)
                self._commit_gate(task_id, verdict)
                if verdict:
                    self._loops.observe_success(task_id)
                    result.succeeded.append(task_id)
                else:
                    result.failed.append(task_id)
            else:  # handler-backed AGENT_TASK — typed bundle only (HD-02)
                out2 = self._run_handler(task_id, template)
                result.succeeded.extend(out2.succeeded)
                result.retried.extend(out2.retried)
                result.failed.extend(out2.failed)
                result.unhandled.extend(out2.unhandled)
            # FIX-A3 — post-execution wall check: a long execution may have
            # spent the tick budget mid-dispatch. The tick stops here with a
            # named code instead of dispatching further work into an expired
            # budget (a single terminal hang remains owned by the heartbeat
            # horizon — preemption is out of scope by design).
            if not result.idle and self._tick_wall_exceeded():
                self._note_once(
                    f"tick wall-clock exceeded after {task_id} "
                    f"({WALLCLOCK_TICK_DEADLINE_EXCEEDED}) — tick stops",
                    key="p-auto-4:tick-wall-exceeded-post")
                result.idle = WALLCLOCK_TICK_DEADLINE_EXCEEDED
                break
        # FIX-F — caps skipped every task: emit the first skip code as the
        # tick idle (notes carry the per-task detail). An empty dispatch
        # with zero eligible work keeps idle="" (nothing to bound — firing
        # there would be noise, recorded as intentional).
        if not result.dispatched and not result.idle and skipped_code:
            result.idle = skipped_code
        return result

    def _classify(self, task: dict, template: str) -> str:
        """Classify a task for dispatch (IDR29-06: the enumeration lives in
        the template authority — task_plan.py; the controller dispatches what
        the plan says, fail-closed on anything else)."""
        task_type = task.get("task_type")
        if task_type == "HUMAN_GATE":
            return "human_gate"
        if task_type == "GATE":
            return "gate" if self._gate_verdict_fn is not None else "unhandled"
        if template == EXTRACT_TEMPLATE:
            return "extract" if self._extract_fn is not None else "unhandled"
        if task_type == "AGENT_TASK":
            return template if template in self._task_handlers else "unhandled"
        return "unhandled"

    # ── EXTRACT execution (Decision 2; IDR29-02 error split) ──

    def _retry_or_fail(self, task_id: str, reason: str) -> str:
        """Apply the retry policy: attempts remain → FAILED then RETRYING
        (the ratified state machine has no RUNNING→RETRYING edge — the chain
        is RUNNING → FAILED → RETRYING); exhausted → FAILED.

        P-AUTO-4 poison-task quarantine sits in front: an already-quarantined
        task stays FAILED (never RETRYING, never silent), and a fresh
        ``repeat_threshold`` streak quarantines here — the task parks FAILED
        with a human-visible note even when attempts remain.

        Returns "retried" or "failed".
        """
        if self._loops.is_quarantined(task_id):
            self._task_repo.transition_status(
                task_id, TaskStatus.FAILED, caused_by="controller",
                reason=f"{reason} ({self._loops.reason_for(task_id)})")
            self._note_once(
                f"retry refused for {task_id}: "
                f"{self._loops.reason_for(task_id)}",
                key=f"p-auto-4:quarantined:{task_id}")
            return "failed"
        quarantine_code = self._loops.observe_failure(task_id, reason or "")
        if quarantine_code:
            self._task_repo.transition_status(
                task_id, TaskStatus.FAILED, caused_by="controller",
                reason=f"{reason} ({self._loops.reason_for(task_id)})")
            self._note_once(
                f"poison task quarantined: {self._loops.reason_for(task_id)}",
                key=f"p-auto-4:quarantined:{task_id}")
            return "failed"
        row = self._task_repo.get(task_id)
        if row["attempt"] < row["max_retries"]:
            self._task_repo.transition_status(
                task_id, TaskStatus.FAILED, caused_by="controller",
                reason=reason)
            self._task_repo.transition_status(
                task_id, TaskStatus.RETRYING, caused_by="controller",
                reason="retry scheduled")
            return "retried"
        self._task_repo.transition_status(
            task_id, TaskStatus.FAILED, caused_by="controller",
            reason=f"{reason} (attempts exhausted)")
        return "failed"

    def _run_with_heartbeat_refresh(
        self, task_id: str, fn: Callable[[], Any],
    ) -> Any:
        """Run one task execution with a mid-execution heartbeat refresher
        (C2): while ``fn`` runs, a daemon refresher keeps the task's
        ``last_heartbeat`` fresh every ``heartbeat_refresh_interval``
        seconds, so a long execution is never NO_SIGNAL-reclaimed by a
        second controller. The refresher shares this lease holder's fenced
        connection; on a lost lease its write fails and the loop exits —
        the tick is never crashed by the refresher. CLIFF: the refresher
        is bounded by ``heartbeat_refresh_horizon`` (default 300s) and
        exits PERMANENTLY when the horizon is exhausted — a handler that
        outlives it becomes reclaimable; the task is then re-executed by
        the next controller (at-least-once) and the late handler's writes
        fail the fence. Handlers longer than the horizon are
        discard-and-re-execute by design."""
        horizon = max(self._heartbeat_refresh_horizon,
                      self._heartbeat_refresh_interval)
        max_refreshes = max(1, math.ceil(
            horizon / max(self._heartbeat_refresh_interval, 0.01)))
        refresher = _HeartbeatRefresher(
            lambda: self._refresh_liveness(task_id),
            self._heartbeat_refresh_interval,
            max_refreshes=max_refreshes)
        refresher.start()
        try:
            return fn()
        finally:
            refresher.stop()
            self._heartbeat_refreshes += refresher.count

    def _refresh_liveness(self, task_id: str) -> None:
        """F15 — refresh BOTH the scheduler lease and the task heartbeat
        while the worker executes. The lease refresh is owner-guarded on the
        raw connection (the lease mechanism is unfenced by design): a lease
        B already reclaimed (owner changed) updates 0 rows and raises, so
        the refresher stops and the stale task becomes reclaimable. Without
        this the C2 protection was illusory in a two-controller deployment —
        B reclaimed the never-refreshed ``locked_at``, the fence killed the
        refresher, and B re-executed a LIVE worker's task."""
        now = self._clock()
        cur = self._conn.execute(
            "UPDATE scheduler_lock SET locked_at = ? WHERE id = 0 AND owner = ?",
            (now, self._owner),
        )
        if cur.rowcount != 1:
            raise LockLostError(
                f"scheduler lease lost during execution: lease refresh "
                f"refused for controller {self._owner!r} — failing closed")
        self._task_repo.heartbeat(task_id)

    def _execute_extract(self, task_id: str) -> TickResult:
        out = TickResult()
        if self._extract_fn is None:
            # Unreachable via dispatch (classify gates on it), but fail
            # closed if invoked directly with no model call wired.
            self._task_repo.transition_status(
                task_id, TaskStatus.FAILED, caused_by="controller",
                reason="no extract_fn wired — EXTRACT task cannot execute")
            out.failed.append(task_id)
            return out
        task = self._task_repo.get(task_id)
        extract_fn = self._extract_fn  # narrowed: the None branch returned
        # M3 (trust boundary): the model call reads the task's source
        # content ONLY through the untrusted view — fetched/search text is
        # enveloped (UntrustedContent), never handed to the judgment
        # callable as a raw str. Built over the fenced SourceRepos.
        untrusted = UntrustedContentView(
            _load_search_results=self._repos.load_search_results,
            _read_payload=self._repos.read_payload,
        )
        # HR-05 (span dereference): a claim's span_ref must resolve within
        # the cited source's stored full text. Only text-bearing
        # ``source_payload`` sources carry readable content; for every other
        # carrier the span is form-checked only. Built over the same fenced
        # payload reader as the untrusted view, so a fabricated span_ref
        # pointing at a nonexistent section is rejected deterministically at
        # admission (audit PROBE P4 / T-CAUSAL-OVERCLAIM).
        repos = self._repos

        def _span_resolve(source_ref: str, span_ref: str) -> bool:
            if not isinstance(source_ref, str) or ":" not in source_ref:
                return True
            if source_ref.partition(":")[0] != "source_payload":
                return True  # no readable full text for this carrier
            raw = repos.read_payload(source_ref)
            if raw is None:
                # The cited content is unreadable — the span cannot be
                # verified, so it is dangling (fail closed).
                return False
            # A docling record resolves through its digest-anchored span
            # tokens (AUDIT-S1 A1). FETCH-FIX-M1: the citation ref here is
            # the content-addressed store key that yielded these bytes
            # (repos.read_payload enforced exactly that); the record's inner
            # ref is author-declared metadata and can never equal the hash
            # of its own bytes, so admission is the store-key identity plus
            # the record's own ref/digest chain — see resolver_for_store_key.
            try:
                record = json.loads(raw.decode("utf-8"))
                record_version = record.get("record_version", "")
                if (isinstance(record_version, str)
                        and record_version.startswith("s1-docling/")):
                    doc = DoclingDocument.from_record(record)
                    docling_resolver = docling_store_key_resolver(doc)
                    return docling_resolver(source_ref, span_ref)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                # Not a docling record or failed to parse — fall through to substring check
                pass
            # Fallback: simple substring check for other source_payload types
            text = raw.decode("utf-8", errors="replace")
            return isinstance(span_ref, str) and span_ref in text

        # C2 — the INJECTED model call is the long execution; keep the task
        # alive on the lease while it runs.
        draft = self._run_with_heartbeat_refresh(
            task_id, lambda: extract_fn(task, untrusted))
        try:
            outcome = accept_extraction_output(
                self._fenced, self._project_id, task_id, draft,
                extracted_by=f"controller:{self._owner}",
                reason=f"extract task {task_id} output",
                span_resolver=_span_resolve,
            )
            del outcome  # audit is rows + events; nothing else to do
            self._task_repo.transition_status(
                task_id, TaskStatus.SUCCEEDED,
                caused_by="controller",
                reason="extraction output accepted")
            self._loops.observe_success(task_id)
            out.succeeded.append(task_id)
        except ExtractionOutputRejected as exc:
            # Retryable: deterministic validation rejected the output, 0 rows
            # written (S6). RETRYING (via FAILED→RETRYING, the ratified
            # chain) while attempts remain, else FAILED.
            outcome = self._retry_or_fail(
                task_id, f"extraction output rejected: {exc}")
            if outcome == "retried":
                out.retried.append(task_id)
            else:
                out.failed.append(task_id)
        except (ExtractionNotBoundToTask, ExtractionTaskBindingError) as exc:
            # IDR29-02: the binding error is TWO cases with DIFFERENT status
            # preconditions — never transition blindly.
            current = self._task_repo.get_status(task_id)
            if current is not TaskStatus.RUNNING:
                # (a) LEASE RACE: the task already left RUNNING (that is why
                # the binding fired). Recovery owns it — do not transition.
                self.note(
                    f"acceptance refused for {task_id}: task already "
                    f"{current.value}; recovery owns it ({exc})")
            else:
                # (b) task still RUNNING. Two sub-cases:
                #  (b1) ONE-SHOT DIVERGENCE (A2-03): the task already
                #  produced output (rows persisted) and this re-execution
                #  diverged. One execution, one output — a retry would just
                #  diverge again. FAILED is the honest terminal.
                #  (b2) SOURCE/SPEC MISMATCH with no prior output: a genuine
                #  controller-side failure — RETRYING/FAILED by retry policy.
                has_prior = self._fenced.execute(
                    "SELECT 1 FROM research_claims WHERE producing_task_id = ? "
                    "LIMIT 1",
                    (task_id,),
                ).fetchone()
                if has_prior is not None:
                    self._task_repo.transition_status(
                        task_id, TaskStatus.FAILED,
                        caused_by="controller",
                        reason=f"acceptance refused: task already produced "
                               f"output (A2-03 one-shot); divergent re-"
                               f"execution is not a second output: {exc}")
                    out.failed.append(task_id)
                else:
                    outcome = self._retry_or_fail(
                        task_id, f"acceptance refused: {exc}")
                    if outcome == "retried":
                        out.retried.append(task_id)
                    else:
                        out.failed.append(task_id)
        return out

    # ── HUMAN_GATE (Decision 3; the wave-stop mechanism) ──

    def _park_human_gate(self, task_id: str) -> list[str]:
        """Park a HUMAN_GATE at WAITING_HUMAN and put the project in
        AWAITING_HUMAN mode. The next tick's mode check dispatches nothing
        until a human decision returns the mode to ACTIVE (IDR29-05)."""
        self._task_repo.transition_status(
            task_id, TaskStatus.WAITING_HUMAN,
            caused_by="controller",
            reason="human gate reached — awaiting approval")
        _append_event_to_db(
            self._fenced, self._clock, "HumanApprovalRequested",
            self._project_id, task_id, caused_by="controller",
            reason="human gate reached")
        # (The mode may already be AWAITING_HUMAN — the
        # transition is idempotent-by-mode); a second park is a no-op.
        # AUDIT: a failure is surfaced (never silent) — a gate waiting
        # under ACTIVE mode would let the next tick dispatch PAST the
        # unapproved gate; the tick self-heal re-derives AWAITING_HUMAN.
        try:
            self._project_repo.transition_mode(
                self._project_id, OperationalMode.AWAITING_HUMAN,
                caused_by="controller",
                reason=f"human gate {task_id} awaiting decision")
        except Exception as exc:  # noqa: BLE001 — audit, never silent
            self._note_once(
                f"mode transition to AWAITING_HUMAN failed while parking "
                f"gate {task_id}: {exc} — the next tick will self-heal "
                f"(audit)",
                key=f"gate:park-mode-failed:{task_id}")
        return [task_id]

    def _commit_gate(self, task_id: str, verdict: bool) -> None:
        """Deterministic GATE verdict: GatePassed/GateFailed + transition."""
        _append_event_to_db(
            self._fenced, self._clock,
            "GatePassed" if verdict else "GateFailed",
            self._project_id, task_id, caused_by="controller")
        self._task_repo.transition_status(
            task_id, TaskStatus.SUCCEEDED if verdict else TaskStatus.FAILED,
            caused_by="controller",
            reason="gate passed (deterministic)" if verdict
            else "gate failed (deterministic)")

    # ── staleness helpers ──

    def _is_stale(self, last_heartbeat: str | None, now: datetime) -> bool:
        """A NULL or unparseable heartbeat is stale (fail-closed)."""
        if last_heartbeat is None:
            return True
        try:
            ts = datetime.fromisoformat(last_heartbeat)
        except ValueError:
            return True
        return (now - ts).total_seconds() > self._lease_seconds

    def _is_stale_ts(self, ts: str, now: str) -> bool:
        try:
            return (datetime.fromisoformat(now)
                    - datetime.fromisoformat(ts)).total_seconds() \
                > self._lease_seconds
        except ValueError:
            return True
