"""SOURCE_SEARCH / SOURCE_FETCH controller handlers (step 6 of 7).

The task-side orchestration layer (design record D1–D5 / §10, remediation §H):

- ``SourceTaskExecutionContext`` — the ONLY normative handler contract
  (HD-02): the typed capability bundle. It exposes the task (read-only
  snapshot), the project, the per-tick ``SourceRepos`` (built over the
  CURRENT fenced connection in ``Controller._refresh_fence``, HD-03), and the
  tick-independent provider machinery + policy. NO raw connection, NO
  gateway, NO Controller internals.
- ``make_source_search_handler`` / ``make_source_fetch_handler`` — the
  factories. They capture ONLY the tick-independent machinery (adapters,
  transport, limiter, recorder, clock, redaction); the controller supplies
  the per-tick pieces at dispatch (SD2-03: a raw ``conn`` is refused at
  wiring — the factories take no connection).
- The handlers call the SHIPPED read-only drivers (``walk``/``combine`` /
  ``fetch_batch``), then the ONE repository write method
  (``SourceOutcomeRepository.record`` over the fence). They NEVER write to
  the DB directly, never create tasks, never touch evidence/gates/status.

Failure semantics (§11): ``combine()`` raises are caught as TYPED outcomes
(EMPTY / UNAVAILABLE — recorded, never silent) and reported as
``failed_typed`` so the controller's retry policy decides; everything else
propagates loudly (FC-01) and the controller marks the task FAILED.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, cast

from hermes.persistence.source_outcomes import (
    SourceOutcomeBindingError,
    SourceRepos,
)
from hermes.research.source_templates import (
    DEFAULT_SOURCE_MAX_SOURCES,
    DEFAULT_SOURCE_SIZE_CAP_BYTES,
    SOURCE_FETCH_TEMPLATE,
    SOURCE_SEARCH_TEMPLATE,
)
from hermes.security.boundaries import UntrustedContent
from hermes.tools.providers.base import (
    ProviderAdapter,
    WalkRequest,
)
from hermes.tools.providers.hazards import ProviderHazardSpec
from hermes.tools.providers.normalize import RetrievalHints
from hermes.tools.providers.paginate import (
    combine,
    fetch_batch,
    walk,
)
from hermes.tools.providers.redact import DEFAULT_POLICY, RedactionPolicy
from hermes.tools.providers.replay import RecordedTransport
from hermes.tools.research_sources import (
    FetchRequest,
    ProviderUnavailableError,
    ProviderValidationError,
    RetrievalShortfallError,
    RetryPolicy,
    SearchOutcome,
    content_hash_of_search_result,
)

__all__ = [
    "HandlerResult",
    "ProviderMachinery",
    "SourceHandler",
    "SourcePolicy",
    "SourceTaskExecutionContext",
    "TaskScopedSourceRepos",
    "UntrustedContent",
    "UntrustedContentView",
    "UntrustedSearchResult",
    "make_source_fetch_handler",
    "make_source_search_handler",
]


# D1 (P-AUTO-3 redteam, SHOULD-FIX): the overall wall-clock budget for ONE
# source dispatch — every page of a search (retries included) and every
# source of a fetch batch must fit inside it, or the shipped drivers stop
# with a typed TRANSIENT verdict instead of holding a controller tick open.
# Config, not code (operator-config at P7); <= 0 disables the bound.
DEFAULT_OVERALL_DEADLINE_SECONDS = 300.0


@dataclass(frozen=True)
class SourcePolicy:
    """The policy carrier for the source slice (bounds/retry/cap policy).

    Carried into the typed bundle; the search/fetch handlers derive their
    per-task ``WalkRequest``/``FetchRequest`` from the task's OWN spec bounds
    (OQ-6 — the builders carry them; over-bound requests are rejected at
    admission, never at execution). ``overall_deadline_seconds`` (D1) is the
    dispatch's whole-operation wall-clock budget (all pages / all sources).
    """

    page_size_cap: int = 100
    max_pages_cap: int = 50
    max_sources_cap: int = 50
    size_cap_bytes_cap: int = 16 * 1024 * 1024
    default_max_sources: int = DEFAULT_SOURCE_MAX_SOURCES
    default_size_cap_bytes: int = DEFAULT_SOURCE_SIZE_CAP_BYTES
    overall_deadline_seconds: float = DEFAULT_OVERALL_DEADLINE_SECONDS


@dataclass(frozen=True)
class ProviderMachinery:
    """The tick-independent provider machinery the handler factories capture
    (SD2-03 — the ONLY thing they capture; no connection, no repos).

    ``adapters`` maps the IDR-030 provider id → its adapter; the accessor
    refuses anything outside the allowlist before any I/O.
    """

    adapters: Mapping[str, ProviderAdapter]
    transport: Any
    limiter: Any
    recorder: Any
    clock: Any
    redaction_policy: RedactionPolicy = DEFAULT_POLICY
    # optional per-provider hazard-spec overrides (default: the shipped
    # specs, ``hazard_specs/{provider}.json`` — the walk/fetch drivers load
    # them; the overrides let tests drive the deterministic walk)
    hazard_specs: Mapping[str, ProviderHazardSpec] = field(default_factory=dict)

    def adapter(self, provider: str) -> ProviderAdapter:
        a = self.adapters.get(provider)
        if a is None:
            raise ProviderValidationError(
                f"no adapter for provider {provider!r} — not in the "
                f"allowlist (IDR-030); nothing was issued")
        return a

    def spec(self, provider: str) -> ProviderHazardSpec:
        """The hazard spec for a provider: the machinery override if given,
        else the shipped ``hazard_specs/{provider}.json`` (the drivers' own
        loading contract)."""
        override = self.hazard_specs.get(provider)
        if override is not None:
            return override
        from hermes.tools.providers.paginate import _load_shipped_spec
        return _load_shipped_spec(provider)


@dataclass(frozen=True)
class TaskScopedSourceRepos:
    """The per-dispatch task-scoped write view (S6-C2).

    ``record()`` FORCES the cited ``task_id`` to the task the controller
    dispatched: a handler cannot misbind an outcome to ANOTHER task (the
    A2-01/02 checks verify the cited task is a RUNNING source task of the
    project — true for a crashed worker within the lease window — but only
    the dispatch binding ties the outcome to the task being executed). The
    handler's ONLY write surface is this view; there is no other connection
    or repository reachable from the context (HD-02).
    """

    _task_id: str
    _record_for_task: Callable[..., dict]
    _dereference_ref: Callable[[str, str], bool]
    _load_search_results: Callable[[str], list]
    _read_payload: Callable[[str], bytes | None] | None

    def __init__(self, repos: SourceRepos, task_id: str) -> None:
        # The raw bundle is deliberately NOT retained (S6-C2/D4): a handler
        # that reaches for ``repos._repos`` to escape the scoping now fails
        # loudly with AttributeError instead of silently reaching an
        # unscoped write path. Only the surface methods are bound;
        # ``record`` is reachable solely with the forced task id.
        # Deliberate introspection of the bound methods' internals remains
        # the documented HD-02 fail-loud boundary — Python has no privacy,
        # but there is no accidental path to an unscoped ``record``.
        object.__setattr__(self, "_task_id", task_id)
        object.__setattr__(self, "_record_for_task",
                           functools.partial(_record_scoped, repos, task_id))
        object.__setattr__(self, "_dereference_ref", repos.dereference)
        object.__setattr__(self, "_load_search_results",
                           repos.load_search_results)
        reader = getattr(repos, "read_payload", None)
        object.__setattr__(self, "_read_payload",
                           _payload_reader_of(reader))

    def record(
        self,
        project_id: str,
        task_id: str,
        outcome: object,
        *,
        outcome_kind: str,
        produced_by: str = "",
    ) -> dict:
        if task_id != self._task_id:
            raise SourceOutcomeBindingError(
                f"source outcome refused: task {task_id!r} is not the "
                f"dispatched task {self._task_id!r} — outcomes bind to the "
                f"task being executed, never a foreign task (S6-C2)")
        return self._record_for_task(
            project_id, outcome,
            outcome_kind=outcome_kind, produced_by=produced_by,
        )

    def dereference_ref(self, project_id: str, ref: str) -> bool:
        return self._dereference_ref(project_id, ref)

    def load_search_results(self, search_task_id: str) -> list:
        return self._load_search_results(search_task_id)

    def read_payload(self, ref: str) -> bytes | None:
        """The M3 payload reader (scoped delegate): resolves
        ``source_payload:`` / ``source_result:`` refs to stored payload
        bytes; the handler context envelopes them in ``UntrustedContent``
        before any judgment surface. None when the repos expose no reader
        (fail closed — never a raw fallback)."""
        if self._read_payload is None:
            return None
        return self._read_payload(ref)


def _payload_reader_of(
    reader: object,
) -> Callable[[str], bytes | None] | None:
    """Type-narrow the repos' optional ``read_payload`` (M3). A missing or
    non-callable reader is None — the context then fails closed (no raw
    fallback)."""
    if callable(reader):
        return reader  # type: ignore[return-value]  # narrowed by the contract
    return None


def _record_scoped(
    repos: SourceRepos,
    task_id: str,
    project_id: str,
    outcome: object,
    *,
    outcome_kind: str,
    produced_by: str = "",
) -> dict:
    """The task-scoped record delegate — the ONLY write surface a handler
    holds. ``task_id`` is bound at wrap time; a handler cannot pass a
    foreign task through it (S6-C2)."""
    return repos.record(
        project_id, task_id, outcome,
        outcome_kind=outcome_kind, produced_by=produced_by,
    )


@dataclass(frozen=True)
class UntrustedSearchResult:
    """The persisted search stream with free-text ENVELOPED (M3): the
    structural fields (id / url / content hash) stay trusted, while
    ``title`` / ``venue`` / ``query`` are ``UntrustedContent`` — never raw
    strings. This is the ONLY context surface for the search text.
    """

    result_id: str
    source_url: str
    content_hash: str
    title: UntrustedContent
    venue: UntrustedContent
    query: UntrustedContent


@dataclass(frozen=True)
class UntrustedContentView:
    """The ONLY context surface for reading untrusted source text (M3).

    Every accessor returns ``UntrustedContent`` — never a raw ``str`` — so
    no unenveloped fetched/search text can reach a judgment prompt, a log,
    or an error. ``search_results`` re-reads the persisted search stream
    (D2) with the free-text fields enveloped; ``fetched_text`` resolves
    ``source_payload:`` refs to payload bytes, decoded lossily and
    enveloped. A missing reader or ref returns None (fail closed — never a
    raw fallback).
    """

    _load_search_results: Callable[[str], list]
    _read_payload: Callable[[str], bytes | None] | None = None

    def search_results(self, search_task_id: str) -> tuple[UntrustedSearchResult, ...]:
        results = self._load_search_results(search_task_id)
        out = []
        for r in results:
            ref = "source_result:" + str(getattr(r, "content_hash", ""))
            out.append(UntrustedSearchResult(
                result_id=str(getattr(r, "result_id", "")),
                source_url=str(getattr(r, "source_url", "")),
                content_hash=str(getattr(r, "content_hash", "")),
                title=UntrustedContent(str(getattr(r, "title", "")),
                                       "search_result.title", ref),
                venue=UntrustedContent(str(getattr(r, "venue", "")),
                                       "search_result.venue", ref),
                query=UntrustedContent(str(getattr(r, "query", "")),
                                       "search_result.query", ref),
            ))
        return tuple(out)

    def fetched_text(self, ref: str) -> UntrustedContent | None:
        """The fetched payload text for ``source_payload:<hash>`` refs,
        ENVELOPED. None when the ref does not dereference or no reader is
        wired (fail closed)."""
        if self._read_payload is None or not isinstance(ref, str):
            return None
        raw = self._read_payload(ref)
        if raw is None:
            return None
        return UntrustedContent(
            raw.decode("utf-8", errors="replace"), "fetched", ref)


@dataclass(frozen=True)
class SourceTaskExecutionContext:
    """The typed capability bundle — the ONLY normative handler contract
    (HD-02). No raw connection. No gateway. No Controller internals. No
    unrelated repositories (remediation §H).

    M3 (trust boundary): ``untrusted`` is the ONLY surface for reading
    fetched/search text — every accessor returns ``UntrustedContent``, so
    no unenveloped source text can reach a judgment prompt.
    """

    task: dict          # the task row snapshot (taken at dispatch; the
                        #   handler never re-reads STATUS — HD-04)
    project_id: str
    repos: SourceRepos  # per-tick bundle over the CURRENT fenced connection
    providers: ProviderMachinery
    policy: SourcePolicy
    untrusted: UntrustedContentView


@dataclass(frozen=True)
class SourceHandler:
    """A registered template handler. ``build_context`` lets the GENERIC
    controller construct the typed bundle per dispatch (HD-02 — the dispatch
    surface is the bundle, never a bare ``(task, fenced, repos)`` tuple);
    ``__call__`` executes it.
    """

    providers: ProviderMachinery
    policy: SourcePolicy
    fn: Callable[[SourceTaskExecutionContext], Any]
    name: str = ""

    def build_context(
        self, task: dict, project_id: str, repos: SourceRepos,
    ) -> SourceTaskExecutionContext:
        # ``repos`` is already the controller's TASK-SCOPED view (S6-C2 — the
        # controller wraps the per-tick bundle at dispatch, so EVERY handler
        # — factory-built or custom — receives the scoped surface).
        reader = getattr(repos, "read_payload", None)
        return SourceTaskExecutionContext(
            task=task, project_id=project_id, repos=repos,
            providers=self.providers, policy=self.policy,
            untrusted=UntrustedContentView(
                _load_search_results=repos.load_search_results,
                _read_payload=_payload_reader_of(reader),
            ),
        )

    def __call__(self, ctx: SourceTaskExecutionContext) -> Any:
        return self.fn(ctx)


@dataclass(frozen=True)
class HandlerResult:
    """The handler's structured verdict for the controller.

    ``completed`` → the controller transitions SUCCEEDED — but ONLY after a
    STRUCTURAL check that the task's outcome rows were persisted (S6-B2: a
    zero-row "success" is FAILED, never a silent SUCCEEDED). ``failed_typed``
    → the work ran and its (possibly typed) outcome was RECORDED, but the
    aggregate says the execution failed (EMPTY / UNAVAILABLE) — the
    controller applies its retry policy (§11). Exceptions are NOT converted
    to HandlerResult — they propagate loudly (FC-01). ``outcome_recorded``
    is the handler's honest statement of the same fact the controller
    verifies structurally. ``provider_requests`` is the MEASURED transport
    request count for this dispatch (FIX-A1: the controller charges
    actuals, never estimates — an estimate that understates retries would
    let real egress exceed the token envelope unrefused).
    """

    status: str                       # "completed" | "failed_typed"
    reason: str = ""
    outcome_recorded: bool = False
    provider_requests: int = 0


class _CountingTransport:
    """FIX-A1 — transparent per-dispatch transport request counter.

    Wraps any Transport (bound or plain) and counts every ``request`` call
    — retries included — without altering bytes, statuses, or errors. The
    count is the MEASURED provider-request volume the controller charges
    against the token envelope; estimates remain advisory-only (pre-claim
    admission) and can no longer understate real egress.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.count = 0

    def request(self, spec: Any) -> Any:
        self.count += 1
        return self._inner.request(spec)


# ── hints reconstruction (deterministic — mirrors normalize's derivation) ──


def _hints_from_spec(spec: dict) -> RetrievalHints:
    raw = spec.get("hints")
    if not isinstance(raw, dict):
        raise ProviderValidationError(
            "SOURCE_SEARCH spec.hints must be a mapping — a hand-built "
            "payload cannot skip the hint contract (D2)")
    identifiers = raw.get("identifiers") or {}
    if not isinstance(identifiers, dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in identifiers.items()):
        raise ProviderValidationError(
            "SOURCE_SEARCH spec.hints.identifiers must be a mapping of "
            "string → string")
    topic = raw.get("topic") or ""
    if not isinstance(topic, str):
        raise ProviderValidationError(
            "SOURCE_SEARCH spec.hints.topic must be a string")
    unrecognized = tuple(raw.get("unrecognized_hints") or ())
    if not all(isinstance(u, str) for u in unrecognized):
        raise ProviderValidationError(
            "SOURCE_SEARCH spec.hints.unrecognized_hints must be a list of "
            "strings")
    if identifiers and topic:
        mode: str = "MIXED"
    elif identifiers:
        mode = "IDENTIFIER"
    else:
        mode = "TOPIC"
    return RetrievalHints(
        identifiers=dict(identifiers), topic=topic, mode=mode,  # type: ignore[arg-type]
        unrecognized_hints=unrecognized,  # type: ignore[arg-type]
    )


def _dispatch_deadline(ctx: SourceTaskExecutionContext) -> float | None:
    """The dispatch's absolute overall deadline (D1) — a ``monotonic``
    reading, or None when the policy disables the bound (<= 0)."""
    seconds = ctx.policy.overall_deadline_seconds
    if seconds <= 0:
        return None
    return ctx.providers.clock.monotonic() + seconds


# ── the SOURCE_SEARCH handler ──


def _run_search(ctx: SourceTaskExecutionContext) -> HandlerResult:
    spec = ctx.task.get("spec") or {}
    provider = spec.get("provider")
    if not isinstance(provider, str):
        raise ProviderValidationError(
            "SOURCE_SEARCH spec.provider missing (admission should have "
            "rejected this payload)")
    hints = _hints_from_spec(spec)
    adapter = ctx.providers.adapter(provider)

    page_size = spec.get("page_size")
    max_pages = spec.get("max_pages")
    size_cap_bytes = spec.get("size_cap_bytes")
    if not all(isinstance(v, int) and v > 0 for v in (page_size, max_pages)):
        raise ProviderValidationError(
            "SOURCE_SEARCH spec bounds must be positive integers "
            "(admission should have rejected this payload)")

    request = WalkRequest(
        max_results=int(cast(int, page_size)),
        max_pages=int(cast(int, max_pages)),
        page_size_cap=ctx.policy.page_size_cap,
        size_cap_bytes=int(size_cap_bytes)
        if isinstance(size_cap_bytes, int) else ctx.policy.size_cap_bytes_cap,
        # D1 — the dispatch's overall deadline, checked before every page
        # and retry attempt by the shipped walk driver.
        deadline_monotonic=_dispatch_deadline(ctx),
    )
    # P4 recording boundary (the existing transport choke point): when
    # the machinery carries a RecordedTransport, bind this dispatch's
    # task/project plus the acting adapter so interactions persist with
    # execution linkage and exact provider/version identity (fetch URLs
    # do not name the API — the adapter object does). Plain transports
    # pass through untouched — non-recording live behavior is
    # byte-identical.
    transport = ctx.providers.transport
    if isinstance(transport, RecordedTransport):
        transport = transport.bound(task_id=ctx.task["task_id"],
                                    project_id=ctx.project_id,
                                    adapter=adapter,
                                    retain_body=True)
    # FIX-A1 — count the MEASURED transport requests for this dispatch
    # (retries included); the controller charges this count, never the
    # max_pages estimate.
    counted = _CountingTransport(transport)
    outcome = walk(
        adapter, hints, request,
        transport=counted,
        limiter=ctx.providers.limiter,
        recorder=ctx.providers.recorder,
        clock=ctx.providers.clock,
        hazard_spec=ctx.providers.spec(provider),
        redaction_policy=ctx.providers.redaction_policy,
    )
    try:
        combined = combine([outcome], order=[provider])
    except RetrievalShortfallError as exc:  # aggregate == EMPTY (searched, found nothing)
        combined = SearchOutcome(
            per_provider=outcome.per_provider,
            aggregate="EMPTY",
            notes=outcome.notes + tuple(exc.notes),
            request_log=outcome.request_log,
        )
        ctx.repos.record(
            ctx.project_id, ctx.task["task_id"], combined,
            outcome_kind="search",
            produced_by=f"controller-handler:{SOURCE_SEARCH_TEMPLATE}",
        )
        return HandlerResult(
            status="failed_typed",
            reason=f"search EMPTY (searched, found nothing): {combined.notes}",
            outcome_recorded=True,
            provider_requests=counted.count,
        )
    except ProviderUnavailableError as exc:  # could not search
        combined = SearchOutcome(
            per_provider=(),
            aggregate="UNAVAILABLE",
            notes=tuple(exc.notes),
            request_log=outcome.request_log,
        )
        ctx.repos.record(
            ctx.project_id, ctx.task["task_id"], combined,
            outcome_kind="search",
            produced_by=f"controller-handler:{SOURCE_SEARCH_TEMPLATE}",
        )
        return HandlerResult(
            status="failed_typed",
            reason=f"search UNAVAILABLE (could not search): {combined.notes}",
            outcome_recorded=True,
            provider_requests=counted.count,
        )
    ctx.repos.record(
        ctx.project_id, ctx.task["task_id"], combined,
        outcome_kind="search",
        produced_by=f"controller-handler:{SOURCE_SEARCH_TEMPLATE}",
    )
    return HandlerResult(status="completed", outcome_recorded=True,
                         provider_requests=counted.count)


def make_source_search_handler(
    providers: ProviderMachinery,
    policy: SourcePolicy | None = None,
) -> SourceHandler:
    """Factory — captures ONLY the tick-independent machinery (SD2-03)."""
    return SourceHandler(
        providers=providers,
        policy=policy or SourcePolicy(),
        fn=_run_search,
        name=SOURCE_SEARCH_TEMPLATE,
    )


# ── the SOURCE_FETCH handler ──


def _run_fetch(ctx: SourceTaskExecutionContext) -> HandlerResult:
    spec = ctx.task.get("spec") or {}
    search_task_id = spec.get("search_task_id")
    if not isinstance(search_task_id, str):
        raise ProviderValidationError(
            "SOURCE_FETCH spec.search_task_id missing (admission should have "
            "rejected this payload)")
    provider = spec.get("provider")
    if not isinstance(provider, str):
        # the fetch task spec carries the provider for the adapter routing
        raise ProviderValidationError(
            "SOURCE_FETCH spec.provider missing (admission should have "
            "rejected this payload)")
    adapter = ctx.providers.adapter(provider)

    # D2 — the fetch input resolves from the PERSISTED outcome, never a
    # hand-authored list (the spec refs are the binding, not the input).
    sources = ctx.repos.load_search_results(search_task_id)
    if not sources:
        raise ProviderValidationError(
            f"SOURCE_FETCH input: search task {search_task_id!r} has no "
            f"persisted source_result records — nothing to fetch (D2)")
    # R01-audit (B3) — the spec refs define the fetch SCOPE: the persisted
    # stream is filtered to exactly the cited refs' results, so a
    # planner-tightened (partial-refs) fetch fetches ONLY its cited subset
    # and records cleanly — never a silent over-fetch that would fail the
    # A2-01 write check late, after wasted execution. Ref hashes not in the
    # stream are impossible (admission requires refs-ownership), so the
    # filter is lossless for honest payloads.
    ref_hashes = {
        ref[len("source_result:"):]
        for ref in spec.get("source_refs") or []
        if isinstance(ref, str) and ref.startswith("source_result:")
    }
    if ref_hashes:
        sources = [s for s in sources
                   if content_hash_of_search_result(s) in ref_hashes]
    if not sources:
        raise ProviderValidationError(
            f"SOURCE_FETCH input: search task {search_task_id!r} has no "
            f"persisted source_result records matching the spec refs — "
            f"nothing to fetch (D2)")

    # R03 — the runtime FetchRequest is built from the task's PERSISTED
    # spec bounds (admission validated them; the spec is authoritative after
    # admission). A malformed/missing bound on a forged row FAILS LOUDLY —
    # the execution never silently substitutes the global defaults.
    max_sources = spec.get("max_sources")
    size_cap_bytes = spec.get("size_cap_bytes")
    retry = spec.get("retry_policy")
    if not isinstance(max_sources, int) or isinstance(max_sources, bool) \
            or max_sources < 1:
        raise ProviderValidationError(
            "SOURCE_FETCH spec.max_sources missing/malformed (admission "
            "should have rejected this payload; the runtime never silently "
            "substitutes defaults — R03)")
    if not isinstance(size_cap_bytes, int) or isinstance(size_cap_bytes, bool) \
            or size_cap_bytes < 1:
        raise ProviderValidationError(
            "SOURCE_FETCH spec.size_cap_bytes missing/malformed (admission "
            "should have rejected this payload; R03)")
    if not isinstance(retry, dict):
        raise ProviderValidationError(
            "SOURCE_FETCH spec.retry_policy missing/malformed (admission "
            "should have rejected this payload; R03)")
    try:
        retry_policy = RetryPolicy(**retry)
    except (TypeError, ValueError) as exc:
        raise ProviderValidationError(
            f"SOURCE_FETCH spec.retry_policy malformed: {exc} (R03)") from exc
    request = FetchRequest(
        max_sources=max_sources,
        size_cap_bytes=size_cap_bytes,
        retry_policy=retry_policy,
        # D1 — the dispatch's overall deadline, checked before every source
        # and retry attempt by the shipped fetch driver.
        deadline_monotonic=_dispatch_deadline(ctx),
    )
    # P4 recording boundary (same choke point as search): bind this
    # dispatch's task/project plus the acting adapter when the
    # machinery carries a RecordedTransport; retain_body=False because
    # payload bytes land as source_payload artifacts through the
    # outcome write path (a second row for identical bytes would trip
    # the R02 same-hash-different-type refusal). Plain transports pass
    # through untouched.
    transport = ctx.providers.transport
    if isinstance(transport, RecordedTransport):
        transport = transport.bound(task_id=ctx.task["task_id"],
                                    project_id=ctx.project_id,
                                    adapter=adapter,
                                    retain_body=False)
    # FIX-A1 — same measured-count discipline as search.
    counted = _CountingTransport(transport)
    outcome = fetch_batch(
        adapter, sources, request,
        transport=counted,
        limiter=ctx.providers.limiter,
        recorder=ctx.providers.recorder,
        clock=ctx.providers.clock,
        hazard_spec=ctx.providers.spec(provider),
        redaction_policy=ctx.providers.redaction_policy,
    )
    ctx.repos.record(
        ctx.project_id, ctx.task["task_id"], outcome,
        outcome_kind="fetch",
        produced_by=f"controller-handler:{SOURCE_FETCH_TEMPLATE}",
    )
    return HandlerResult(status="completed", outcome_recorded=True,
                         provider_requests=counted.count)
def make_source_fetch_handler(
    providers: ProviderMachinery,
    policy: SourcePolicy | None = None,
) -> SourceHandler:
    """Factory — captures ONLY the tick-independent machinery (SD2-03)."""
    return SourceHandler(
        providers=providers,
        policy=policy or SourcePolicy(),
        fn=_run_fetch,
        name=SOURCE_FETCH_TEMPLATE,
    )
