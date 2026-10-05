"""Provider adapter contract and runtime protocols (Part 3 step 3).

The thin-adapter shape (blueprint §3): an adapter is a `ProviderContractCard`
(declaration) plus four hooks — `build_request`, `parse_page`, `extract_ids`,
`build_fetch_request` — and NOTHING else: no rate-limit logic, no retry logic,
no reconciliation logic, no logging, no redaction, no cursor bookkeeping. All
of that lives in the driver/limiter/recorder (only-entry-point invariant,
PS-03 — an adapter never holds the transport, the limiter, or the recorder).

The runtime protocols (`Clock`, `Transport`, `ProviderRateLimiter`,
`RequestRecorder`) are structural: steps 4–6 implement them (`ratelimit.py`,
`http.py`, `replay.py`); step-3 tests satisfy them with fakes. The walk driver
(`paginate.py`) depends only on these shapes.

Design anchors (contract §3/§4.4, blueprint §3/§5.1):
- `PageState` is the driver's per-page position (page_index + cursor or
  offset); `parse_page` returns the NEXT state, so the adapter owns pagination
  mechanics and the driver owns the guard (WS-03/06).
- `Page.records` are RAW provider rows — raw by construction (PS-12);
  canonicalization is `extract_ids`'s job, called by the driver once per row.
- `RequestSpec.headers_meta` carries header-auth credential metadata and is
  NEVER logged — the log and the `SearchResult`s store only
  `request_params_redacted` (the recorder-boundary redaction, contract §7).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeAlias

from hermes.tools.providers.normalize import RetrievalHints
from hermes.tools.research_sources import RequestLogRecord, RetryPolicy, SearchResult

__all__ = [
    # runtime protocols
    "Clock",
    "Page",
    "PageState",
    # contract types
    "PaginationKind",
    "ProviderAdapter",
    "ProviderContractCard",
    "ProviderRateLimiter",
    "RateProfile",
    "RawRecord",
    "RequestRecorder",
    "RequestSpec",
    "Transport",
    "TransportResponse",
    "WalkMode",
    "WalkRequest",
]

PaginationKind: TypeAlias = Literal["cursor", "offset", "none"]
# The driver's walk mode (WS-01): derived from the parsed hints — a pure
# identifier hint is a lookup; everything else is a query. `VALID_NEGATIVE`
# resolution applies only in lookup mode.
WalkMode: TypeAlias = Literal["lookup", "query"]


@dataclass(frozen=True)
class RateProfile:
    """Per-provider rate profile (contract §6.1) — the step-4 limiter's input."""

    rps: float
    burst: int
    concurrency: int
    daily_cap: int


@dataclass(frozen=True)
class ProviderContractCard:
    """One per-provider declaration (the §3 table row of the contract)."""

    provider_id: str
    base_url: str
    auth_policy: Literal["none", "query", "header"]  # credentials NEVER in logs (§7)
    hint_routes: dict[str, str]  # identifier_kind -> endpoint selector
    pagination: dict  # {kind: cursor|offset|none, start_param?, page_size_cap,
    #                   max_pages, loop_guard} — the spec's loop_guard is the
    #                   driver's trap threshold (WS-03)
    hazard_spec_version: str
    rate_profile: RateProfile
    retry_class_map: dict[str, str]  # failure class -> transient|permanent


@dataclass(frozen=True)
class PageState:
    """The driver's per-page position — cursor providers carry `cursor`,
    offset providers `offset`; the adapter advances it via `Page.next_state`."""

    page_index: int
    cursor: str | None = None
    offset: int | None = None


@dataclass(frozen=True)
class RequestSpec:
    """The request form `build_request` produces — passed through redaction at
    the recorder boundary before it may be logged; credentials are injected
    HERE and only here (the driver never sees raw credential material)."""

    url: str
    params: dict[str, str]
    headers_meta: dict[str, str]  # header-auth metadata — never logged


RawRecord: TypeAlias = dict[str, object]


@dataclass(frozen=True)
class Page:
    """One parsed page — RAW records (PS-12), the provider's total if any, and
    the NEXT position. `next_state=None` means the walk is exhausted."""

    records: tuple[RawRecord, ...] = ()
    total: int | None = None
    next_state: PageState | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class WalkRequest:
    """Per-task walk bounds (blueprint §5.1 — S11 scale classes).

    `size_cap_bytes` (RT-06/RT3-01, step 4) is the per-task completed-body
    cap — the driver carries it into HazardContext so the EVALUATOR applies
    it after the status verdicts (an oversized COMPLETE 2xx body →
    PARTIAL_CONTENT); the transport's own streaming abort is a separate,
    status-conditional hard cap.

    `deadline_monotonic` (D1, P-AUTO-3 redteam) is the dispatch's absolute
    overall wall-clock deadline (a ``Clock.monotonic`` reading; None =
    unbounded) — the driver checks it before every page and retry attempt."""

    max_results: int
    max_pages: int = 50
    page_size_cap: int = 100
    size_cap_bytes: int | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    deadline_monotonic: float | None = None


class ProviderAdapter(abc.ABC):
    """The four hooks the walk/fetch drivers call — the thin-adapter shape."""

    contract: ProviderContractCard

    @abc.abstractmethod
    def build_request(
        self, hints: RetrievalHints, state: PageState, page_size: int
    ) -> RequestSpec: ...

    @abc.abstractmethod
    def parse_page(self, payload: object, state: PageState) -> Page: ...
    #   payload is the DECODED canonical payload (dict/str) the driver produces
    #   from the raw bytes after hazard evaluation; records are RAW provider
    #   rows — canonicalization is extract_ids' job.

    @abc.abstractmethod
    def extract_ids(self, record: RawRecord) -> dict[str, str]: ...
    #   canonical identifiers via normalize_identifier (contract §3.1) — the
    #   ONLY place identifier canonicalization happens (PS-12), called once per
    #   row by the driver, never deferred.

    @abc.abstractmethod
    def build_fetch_request(self, source: SearchResult) -> RequestSpec: ...
    #   fetch-level hook (PS-01) — same RequestSpec/redaction contract.

    def validate_fetch(self, source: SearchResult, payload: object) -> None:
        # FD-01 (fetch-gate) — the FIFTH hook: content-validation on the
        # artifact verdicts (NONE / INJECTION_SUSPECT) BEFORE artifact
        # construction. Raises FetchContentRejected(reason) on non-full-text
        # shapes (junk HTML, <error>-rooted wrappers, HTML-when-PDF-promised);
        # the fetch driver maps a rejection to FetchFailure(EMPTY_RESULT,
        # reason=<message>) — never a FetchedSource. Concrete no-op default:
        # adapters with fetch content knowledge override it (the canonical
        # four will); the generic safety controls (empty-body rule, size cap,
        # content-type, transport handling) apply regardless of this hook.
        # The message must never embed the rejected payload (F12).
        return None


# ── runtime protocols (structural; steps 4–6 implement) ──


class Clock(Protocol):
    """Clock-injected time (contract §6.1) — tests drive it with frozen_clock."""

    def now_utc(self) -> str: ...  # ISO-8601 UTC

    def monotonic(self) -> float: ...  # backoff sleeps


@dataclass(frozen=True)
class TransportResponse:
    """The transport's response — status + raw bytes + headers (Retry-After).

    `content_type` (RT-05/RT2-04, step 4) is the normalized media type from
    the response's Content-Type header (``text/xml; charset=utf-8`` →
    ``text/xml``), or None when the header is absent — the hazard evaluator
    consults it against the per-provider allowlist; the transport NEVER
    classifies on it."""

    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str | None = None


class Transport(Protocol):
    """The ONLY way into the provider machinery (PS-03). Raises ProviderError
    subclasses with policy-redacted messages (contract §7 — the transport is
    constructed with the RedactionPolicy and is the only component that
    raises provider errors, `from None` at every hop, PS2-04/PS3-07).
    Raises ONLY for TRANSPORT-LEVEL failures (RT-02/RT2-01) — never on an
    HTTP status; all statuses flow to evaluate_hazards."""

    def request(self, spec: RequestSpec) -> TransportResponse: ...


class ProviderRateLimiter(Protocol):
    """Per-provider token bucket + concurrency + Retry-After backoff (step 4,
    blueprint §6.1 — the four hostile gates RT/RT2/RT3/TR pinned this shape).

    - `acquire(provider) -> tuple[bool, str]` (RT-01/RT2-02/RT3-02/RL-01):
      the DECISION and the CAUSE return under one lock — NEVER raises for a
      policy condition, NEVER blocks on a hard stop. `False` is reserved
      for the daily cap (no retry, cause "daily_cap_exhausted"); admission
      waits are bounded (the bucket's wait ≤ burst-refill; the semaphores
      are short because the driver releases per request — WK3-01) with the
      ADMISSION_WAIT_BOUND safety net, and the pathological expiry returns
      `(False, "admission_wait_expired")` too (TRANSIENT — the driver
      RETRIES, RT3-02). The atomic reason closes the TOCTOU where a caller
      could read ANOTHER caller's denial through a separate accessor
      (RL-01); `""` on a grant.
    - `last_denial_reason(provider) -> str` (RT3-03): "" |
      "daily_cap_exhausted" | "admission_wait_expired" — kept as a
      DIAGNOSTIC-only accessor (the driver branches on the atomic reason,
      never on this; a provider 429 is never mislabeled).
    - `release` returns the SEMAPHORE slot only — a token is NEVER refunded
      (RT-03).
    - `note_throttled` shapes FUTURE acquires only — never sleeps the caller
      (RT-08).
    """

    def acquire(self, provider: str) -> tuple[bool, str]: ...
    def release(self, provider: str) -> None: ...
    def note_throttled(self, provider: str, retry_after: float | None) -> None: ...
    def last_denial_reason(self, provider: str) -> str: ...


class RequestRecorder(Protocol):
    """The recorder-boundary sink — persists the redacted RequestLogRecord
    (contract §8); the driver builds the log, the recorder stores it."""

    def record(self, log: RequestLogRecord) -> None: ...
