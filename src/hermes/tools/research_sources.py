"""ResearchSourceProvider port — Protocol, deterministic types, and error taxonomy.

Phase: step 1 of the Part 3 implementation (IDR-030, §27 item 55 RESOLVED).
This module is the *what*: the ratified §15 `search`/`fetch`/`extract` signatures
preserved exactly, the reconciliation-carrying `SearchResult`, the fetch outcome
types (`FetchedSource`/`NoFullText`/`FetchFailure`/`FetchOutcome` — PS-01/PS2-01/
PS3-01..04), the request-log records (PS-01/PS2-07), and the §15 error taxonomy.

Pure and read-only by construction: no DB tables, no events, no intents, no
gateway changes (PA4 `READ_ONLY`, outbox-exempt). The provider machinery lives in
`hermes.tools.providers` (normalize/redact now; base/http/hazards/paginate/
ratelimit/replay + the 11 adapters in later steps). Nothing here does I/O.

Design anchors (contract `hermes_researchsourceprovider_contract.md` §2/§5.2,
blueprint `hermes_researchsourceprovider_implementation_design.md` §2):
- `SearchResult.reconciliation` is the per-provider verdict; the *aggregate* is on
  `SearchOutcome` (COMPLETE/PARTIAL/EMPTY/UNAVAILABLE — PS-13).
- `raw_retrieved_count` (reconciliation) vs `delivered_count` (consumer stream) are
  never the same number (PS2-05).
- `NoFullText` is a RESULT, never a failure (PS2-01); its kind is derived only from
  what the response evidences — never guessed (PS3-03).
- `FetchOutcome.aggregate` is a *resolution* signal; per-source outcomes are the
  evidence signal (PS3-04).
- `VALID_NEGATIVE` is unreachable at fetch scope (PS3-01) — enforced by the fetch
  driver (step 5a), not by these types.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Literal, Protocol, Sequence, cast

from hermes.research.programs import canonical_json, sha256_hex

__all__ = [
    # the ratified provider allowlist (IDR-030 decision point 1)
    "SOURCE_PROVIDER_ALLOWLIST",
    "WEB_SEARCH_PROVIDERS",
    "FetchFailure",
    "FetchLogEntry",
    "FetchOutcome",
    "FetchRequest",
    "FetchedSource",
    "NoFullText",
    "PermanentProviderError",
    # errors
    "ProviderError",
    "ProviderUnavailableError",
    "ProviderValidationError",
    "RedactionError",
    "RequestLogRecord",
    # protocol
    "ResearchSourceProvider",
    "RetrievalShortfallError",
    "RetryPolicy",
    "SearchOutcome",
    "SearchResult",
    # records
    "Source",
    "SourceArtifact",
    "TransientProviderError",
    "content_hash_of_search_result",
    # deterministic identity helpers
    "make_search_result_id",
    "observation_hash_of_search_result",
    "outcome_record_hash",
    "search_result_from_mapping",
    # lossless SearchResult round-trip (OQ-1(b) / OB-05)
    "search_result_to_mapping",
]

# The reconciliation verdict classes (contract §4.1 / blueprint §5.1).
ReconciliationVerdict = Literal["COMPLETE", "SHORTFALL", "UNKNOWN"]
# The search-level aggregates (contract §4.2 / blueprint §5.1 step 7, PS-13/PS2-03/PS3-06).
SearchAggregate = Literal["COMPLETE", "PARTIAL", "EMPTY", "UNAVAILABLE"]
# The fetch-level aggregates (blueprint §5.3).
FetchAggregate = Literal["COMPLETE", "PARTIAL", "FAILED"]
# The structured no-full-text kinds (PS3-03): the driver asserts ONLY what the
# response evidences — a 404 alone cannot distinguish NOT_OA from REMOVED_OR_RETRACTED.
NoFullTextKind = Literal["NOT_OA", "REMOVED_OR_RETRACTED", "NOT_FOUND"]


class ResearchSourceProvider(Protocol):
    """The ratified §15 port, signatures unchanged (IDR-030 decision point 1).

    `extract` returns the v6 §16.1 `Source` records; that record type is
    designed-but-unimplemented, so the return is a forward reference resolved
    when the record lands — extraction is deterministic parsing, never an LLM
    step (contract §2.3), and this port never writes.
    """

    def search(self, query: str, max_results: int) -> list["SearchResult"]: ...

    def fetch(self, source: "SearchResult") -> "SourceArtifact": ...

    def extract(self, artifact: "SourceArtifact") -> list["Source"]: ...


# ── deterministic identity (contract §2.2) ──


def make_search_result_id(
    provider: str,
    endpoint: str,
    query: str,
    page_index: int,
    cursor_key: str | None,
    identifiers: dict[str, str],
) -> str:
    """Content-addressed, deterministic `result_id` (contract §2.2).

    ``"sr_" + sha256(canonical_json(provider, endpoint, query, position_key,
    canonical_identifiers))[:24]`` — the same request-state discipline the
    fingerprint uses (PS-06), so a record's identity is derivable from what was
    actually sent, never from an LLM or a counter.
    """
    payload = canonical_json(
        {
            "provider": provider,
            "endpoint": endpoint,
            "query": query,
            "position_key": {"page_index": page_index, "cursor_key": cursor_key},
            "identifiers": dict(sorted(identifiers.items())),
        }
    )
    return "sr_" + sha256_hex(payload)[:24]


# The SEMANTIC identity preimage (step-6 P0 — the record's stable source
# identity). Observation/retrieval metadata is EXCLUDED so that repeated
# retrieval of the same canonical source does NOT create a new identity merely
# because the access time, request-log ref, reconciliation counts, or other
# run metadata changed — the crash-retry one-shot (the step-6 hash-SET
# comparison) must see identical semantic sources as identical.
_IDENTITY_FIELDS = (
    "provider",
    "identifiers",
    "title",
    "authors",
    "year",
    "venue",
    "abstract_sha256",
    "source_url",
    "valid_negative",
    "valid_negative_for",
)


def content_hash_of_search_result(result: "SearchResult") -> str:
    """SEMANTIC identity of the record (contract §2.2 — the record's stable
    source identity, ``sha256`` of the canonical identity preimage).

    The preimage is the bibliographic/source essence ONLY (provider,
    identifiers, title, authors, year, venue, abstract_sha256, source_url,
    valid_negative, valid_negative_for) — it EXCLUDES every observation/
    retrieval field: result_id, endpoint, query, request_params_redacted,
    access_timestamp_utc, page_index, cursor_key, raw_retrieved_count,
    delivered_count, total_count, total_is_estimate, reconciliation,
    provenance, and content_hash itself (ADV-01 — never
    ``H(record INCLUDING H(record))``).

    Repeated retrieval of the same canonical source MUST produce the same
    hash regardless of access time, request-log ref, counts, or other run
    metadata (step-6 P0 invariant — crash-retry idempotency, stable source
    references, and resolver stability all depend on it). Use
    ``observation_hash_of_search_result`` for full-record integrity.
    """
    data = dataclasses.asdict(result)
    data = {k: data[k] for k in _IDENTITY_FIELDS}
    data["identifiers"] = dict(sorted((data["identifiers"] or {}).items()))
    data["authors"] = list(data["authors"] or ())
    return sha256_hex(canonical_json(data))


def observation_hash_of_search_result(result: "SearchResult") -> str:
    """Full-record integrity hash (step-6 P0 companion) — ``sha256`` of the
    canonical record INCLUDING the observation metadata, EXCLUDING only the
    self-referential ``content_hash`` (ADV-01).

    ``content_hash_of_search_result`` is the stable identity;
    ``observation_hash`` is the tamper-evidence hash over the persisted form
    (a changed timestamp/count/log ref changes it, so the write path can
    detect a corrupted or forged persisted record).
    """
    data = dataclasses.asdict(result)
    data.pop("content_hash", None)
    return sha256_hex(canonical_json(data))


# The RATIFIED adapter allowlist (IDR-030 decision point 1, contract §3 —
# the 11 scholarly-retrieval providers — as amended by IDR-046 D1 with the
# four commercial web-search legs). The gateway enforces membership at
# INSERT_TASK admission (OQ-5); the handler machinery refuses anything
# else before any I/O. Web legs are barred from every evidence position
# (IDR-046 D2/D3) — the `WEB_SEARCH_PROVIDERS` predicate below is the
# single definition of "web-derived"; no other module may hardcode ids.
SOURCE_PROVIDER_ALLOWLIST = frozenset({
    "pubmed", "pmc", "europepmc", "arxiv", "biorxiv", "medrxiv",
    "openalex", "crossref", "semantic-scholar", "core", "unpaywall",
    "brave", "exa", "tavily", "searxng",
})

# The web-search provenance class (IDR-046 D1) — exactly the four
# commercial web legs. A row is web-derived iff its provider intersects
# this set (`src/hermes/tools/research_sources.py` is the single
# definition).
WEB_SEARCH_PROVIDERS = frozenset({"brave", "exa", "tavily", "searxng"})


def outcome_record_hash(outcome: object, outcome_kind: str) -> str:
    """The OUTCOME-LEVEL semantic hash (step-6 OB-01 — the one-shot SET's
    second member, alongside the per-result/per-payload content hashes).

    Preimage = canonical(outcome_kind, aggregate, notes, per-source semantic
    resolutions, request-log FACTS). Observation/retrieval metadata is
    EXCLUDED: access timestamps, the cursor chain's timing, the fetch
    ``FetchLogEntry`` stream (attempts/attempt_verdicts/timestamps), and the
    request log's ``timestamps`` tuple — so a crash-retry with identical
    semantic content but changed observation metadata produces the SAME
    outcome hash (IDEMPOTENT), while a changed aggregate, notes, or per-source
    resolution (COMPLETE→SHORTFALL; a fetch that now succeeds where it
    failed) produces a DIFFERENT hash (DIVERGENT → one-shot refusal).

    ``outcome_kind`` is ``"search"`` or ``"fetch"``; the per-source branch
    reads the outcome's own carrier types.
    """
    if outcome_kind == "search":
        _require(outcome, "SearchOutcome")
        return _search_outcome_hash(outcome)
    if outcome_kind == "fetch":
        _require(outcome, "FetchOutcome")
        return _fetch_outcome_hash(outcome)
    raise ValueError(
        f"outcome_kind must be 'search' or 'fetch', got {outcome_kind!r}")


def _require(value: object, name: str) -> object:
    if value is None:
        raise ValueError(f"outcome must be a {name}, got None")
    return value


def _search_outcome_hash(outcome: object) -> str:
    """The search branch of ``outcome_hash_of_search_result`` (typed)."""
    o = cast(SearchOutcome, outcome)
    per_source = [
        {
            "result_id": r.result_id,
            "content_hash": content_hash_of_search_result(r),
            "valid_negative": r.valid_negative,
            "valid_negative_for": r.valid_negative_for,
        }
        for r in o.per_provider
    ]
    log = o.request_log
    request_facts = None
    if log is not None:
        # the stable, redacted request facts — the timestamps tuple is
        # observation and deliberately excluded
        request_facts = {
            "provider": log.provider,
            "endpoint": log.endpoint,
            "query": log.query,
            "request_params_redacted": dict(
                sorted((log.request_params_redacted or {}).items())),
            "cursor_chain": list(log.cursor_chain or ()),
            "page_counts": [list(pc) for pc in (log.page_counts or ())],
            "reconciliation": log.reconciliation,
            "total_is_estimate": log.total_is_estimate,
            "hazard_verdicts": list(log.hazard_verdicts or ()),
            "provider_spec_version": log.provider_spec_version,
            "raw_artifact_hashes": list(log.raw_artifact_hashes or ()),
        }
    return sha256_hex(canonical_json({
        "kind": "search",
        "aggregate": o.aggregate,
        "notes": list(o.notes or ()),
        "per_source": per_source,
        "request_facts": request_facts,
    }))


def _fetch_outcome_hash(outcome: object) -> str:
    """The fetch branch of ``outcome_hash_of_search_result`` (typed)."""
    o = cast(FetchOutcome, outcome)
    per_source: list[dict[str, object]] = []
    for f in o.per_source:
        per_source.append({
            "resolution": "fetched",
            "content_hash": f.artifact.content_hash,
        })
    for n in o.no_full_text:
        per_source.append({
            "resolution": "no_full_text",
            "kind": n.no_full_text_kind,
            "content_hash": content_hash_of_search_result(n.source),
        })
    for fl in o.failed:
        per_source.append({
            "resolution": "failed",
            "failure_class": fl.failure_class,
            "reason": fl.reason,
        })
    # the FetchLogEntry stream is OBSERVATION — excluded
    return sha256_hex(canonical_json({
        "kind": "fetch",
        "aggregate": o.aggregate,
        "notes": list(o.notes or ()),
        "per_source": per_source,
        "request_facts": None,
    }))


# ── lossless SearchResult round-trip (OQ-1(b) / OB-05) ──

_SEARCH_RESULT_FIELDS = frozenset({
    "result_id", "provider", "endpoint", "query", "request_params_redacted",
    "identifiers", "title", "authors", "year", "venue", "abstract_sha256",
    "source_url", "access_timestamp_utc", "page_index", "cursor_key",
    "raw_retrieved_count", "delivered_count", "total_count",
    "total_is_estimate", "reconciliation", "content_hash", "provenance",
    "valid_negative", "valid_negative_for",
})


def search_result_to_mapping(result: "SearchResult") -> dict[str, object]:
    """The persisted form of a ``SearchResult`` (canonical, JSON-safe)."""
    return dataclasses.asdict(result)


def search_result_from_mapping(data: object) -> "SearchResult":
    """Lossless reconstruction (OQ-1(b)) — ``SearchResult' == SearchResult``
    on EVERY field, with the container types restored exactly (OB-05):
    ``authors`` coerced back to tuple, dicts preserved, ``None`` fields
    preserved. Fail-closed: unknown or missing keys are an error, never a
    silent drop.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"persisted SearchResult must be a mapping, got {type(data).__name__}")
    unknown = sorted(set(data) - _SEARCH_RESULT_FIELDS)
    if unknown:
        raise ValueError(
            f"persisted SearchResult carries unknown keys {unknown} — the "
            f"schema is closed (OB-05)")
    missing = sorted(_SEARCH_RESULT_FIELDS - set(data))
    if missing:
        raise ValueError(
            f"persisted SearchResult is missing keys {missing} — the record "
            f"is incomplete (OB-05)")
    kwargs: dict[str, object] = dict(data)
    authors = kwargs.get("authors")
    if authors is None:
        kwargs["authors"] = ()
    elif isinstance(authors, (list, tuple)):
        kwargs["authors"] = tuple(authors)
    else:
        raise ValueError(
            f"persisted SearchResult.authors must be a list/tuple, "
            f"got {type(authors).__name__}")
    for key in ("request_params_redacted", "identifiers", "provenance"):
        value = kwargs.get(key)
        if value is not None and not isinstance(value, dict):
            raise ValueError(
                f"persisted SearchResult.{key} must be a mapping, "
                f"got {type(value).__name__}")
    # The schema is CLOSED (keys validated above); the field types are
    # restored with explicit casts — ``typing.cast`` is a declaration, the
    # validation lives in the closed-key checks + the container checks above.
    return SearchResult(
        result_id=cast(str, kwargs["result_id"]),
        provider=cast(str, kwargs["provider"]),
        endpoint=cast(str, kwargs["endpoint"]),
        query=cast(str, kwargs["query"]),
        request_params_redacted=cast(
            dict[str, str], kwargs["request_params_redacted"] or {}),
        identifiers=cast(dict[str, str], kwargs["identifiers"] or {}),
        title=cast(str, kwargs["title"]),
        authors=cast(tuple[str, ...], kwargs["authors"]),
        year=cast(int | None, kwargs["year"]),
        venue=cast(str, kwargs["venue"]),
        abstract_sha256=cast(str | None, kwargs["abstract_sha256"]),
        source_url=cast(str, kwargs["source_url"]),
        access_timestamp_utc=cast(str, kwargs["access_timestamp_utc"]),
        page_index=cast(int, kwargs["page_index"]),
        cursor_key=cast(str | None, kwargs["cursor_key"]),
        raw_retrieved_count=cast(int, kwargs["raw_retrieved_count"]),
        delivered_count=cast(int, kwargs["delivered_count"]),
        total_count=cast(int | None, kwargs["total_count"]),
        total_is_estimate=cast(bool, kwargs["total_is_estimate"]),
        reconciliation=cast(
            ReconciliationVerdict, kwargs["reconciliation"]),
        content_hash=cast(str, kwargs["content_hash"]),
        provenance=cast(dict[str, str], kwargs["provenance"] or {}),
        valid_negative=cast(bool, kwargs["valid_negative"]),
        valid_negative_for=cast(str | None, kwargs["valid_negative_for"]),
    )


# ── records ──


@dataclass(frozen=True)
class Source:
    """The v6 §16.1 `Source` artifact record — the write-path target this port's
    `SearchResult` + `SourceArtifact` materialize into (contract §2.3 / §8
    provenance continuity). Universal §16.1 fields (`id`, `created_at`,
    `created_by`, `provenance`, `content_hash`) + the retrieval-side identity.
    Immutable once committed — a change is a new version with a recorded
    supersession edge, never a mutation (X6 excluded for the same reason).
    """

    id: str  # content-addressed (§16.1 discipline)
    provider: str
    identifiers: dict[str, str]  # canonical identifiers (normalize.py)
    title: str
    authors: tuple[str, ...]
    year: int | None
    venue: str
    abstract_sha256: str | None
    source_url: str  # redacted form
    artifact_ref: str  # content-addressed SourceArtifact.artifact_id / raw_bytes_ref
    created_at: str
    created_by: str
    provenance: dict[str, str]  # request_log_ref / fetch_log_ref, provider_spec_version, …
    content_hash: str


@dataclass(frozen=True)
class SearchResult:
    """One delivered retrieval record — the reconciliation carrier (contract §2.2)."""

    result_id: str  # "sr_" + sha256(...)[:24] — content-addressed (make_search_result_id)
    provider: str
    endpoint: str
    query: str  # the exact normalized request sent (post hint-routing)
    request_params_redacted: dict[str, str]  # the ONLY form ever logged/stored/emitted
    identifiers: dict[str, str]  # {doi?, pmid?, pmcid?, arxiv?, core_id?, openalex_id?, …}
    title: str
    authors: tuple[str, ...]
    year: int | None
    venue: str
    abstract_sha256: str | None  # hash only; raw text lives in the SourceArtifact
    source_url: str  # redacted form
    access_timestamp_utc: str  # ISO-8601 UTC
    page_index: int
    cursor_key: str | None
    raw_retrieved_count: int  # PS2-05 — pre-dedup rows seen on this walk (reconciliation)
    delivered_count: int  # PS2-05 — post-dedup records delivered to the stream
    total_count: int | None
    total_is_estimate: bool
    reconciliation: ReconciliationVerdict
    content_hash: str
    provenance: dict[str, str]  # {request_log_ref, provider_spec_version, hazard_verdict}
    # PS-11 — a real "no" on an identifier lookup is a RESULT, never an EMPTY failure;
    # the marker carries the distinction and the identifier that resolved to "no".
    valid_negative: bool = False
    valid_negative_for: str | None = None


@dataclass(frozen=True)
class SourceArtifact:
    """The raw fetched payload, content-addressed and immutable (contract §2.3)."""

    artifact_id: str  # "art_" + sha256(raw_bytes)[:24]
    content_hash: str
    media_type: str
    size_bytes: int
    retrieved_from: str
    access_timestamp_utc: str
    raw_bytes_ref: str  # content-addressed store ref (S12 manifest for large corpora)


@dataclass(frozen=True)
class SearchOutcome:
    """The walk's aggregate (contract §4.2 — the full matrix, PS-13/PS2-03/PS3-06)."""

    per_provider: tuple[SearchResult, ...]
    aggregate: SearchAggregate
    notes: tuple[str, ...]  # STOPPED_AT_LIMIT, dedup, MALFORMED_ROW, causes, …
    request_log: "RequestLogRecord | None"  # carried, then persisted by the task (PS-01)


@dataclass(frozen=True)
class FetchedSource:
    """A source successfully fetched to an artifact (blueprint §2.1, PS-01).

    A source-RESOLUTION record: it carries the descriptor only, never the raw
    payload — the transient `FetchedPayload` carrier (fetch-gate A1) holds the
    bytes on the outcome until the task write path persists them.
    """

    source: SearchResult
    artifact: SourceArtifact
    hazard_verdict: str  # NONE | INJECTION_SUSPECT (advisory) — real failures land in FetchFailure


@dataclass(frozen=True)
class FetchedPayload:
    """The TRANSIENT payload carrier (fetch-gate A1, MODIFIED — the gate
    remediation `hermes_researchsourceprovider_fetch_gate_remediation.md`).

    Exactly the artifact-store entry the task write path will persist: the
    content-addressed descriptor + the raw bytes, carried on
    `FetchOutcome.payloads` in order-aligned pairs with `per_source` (one per
    FETCHED source, never per attempt, never for a failure). The consumer
    contract is dereference-by-`artifact_id` (GC-02), never by position. The
    bytes are immutable; no component other than the task write path retains
    them past the outcome.
    """

    artifact: SourceArtifact
    raw_bytes: bytes


@dataclass(frozen=True)
class NoFullText:
    """PS2-01/PS3-03 — a RESULT, never a failure: the source is citable but no
    accessible full text exists (europepmc's clean 404 — the contract's *preferred*
    answer). Carried in the outcome, counted as COMPLETE, never FAILED."""

    source: SearchResult
    no_full_text_kind: NoFullTextKind  # PS3-03 — derived ONLY from what the response
    #   evidences (status + spec-declared markers); a provider-declared retraction
    #   marker maps to REMOVED_OR_RETRACTED, never NOT_OA
    evidence_basis: dict[str, str]  # PS3-03 — {status_code, marker_path, provider_spec_version}


@dataclass(frozen=True)
class FetchFailure:
    """PS-01 — a per-source fetch failure (never silent)."""

    source: SearchResult
    failure_class: str  # PARTIAL_CONTENT | MALFORMED_200 | EMPTY_RESULT | THROTTLED | TIMEOUT | …
    reason: str  # NO_FULL_TEXT is NOT a failure — it is NoFullText


@dataclass(frozen=True)
class FetchOutcome:
    """The fetch driver's aggregate (blueprint §5.3, PS-01/PS2-01/PS3-04)."""

    per_source: tuple[FetchedSource, ...]
    no_full_text: tuple[NoFullText, ...]  # PS2-01 — contributes to COMPLETE, never FAILED
    failed: tuple[FetchFailure, ...]
    aggregate: FetchAggregate
    # PS3-04 — the aggregate is a RESOLUTION signal ("every source resolved"), never
    # an evidence signal; fetched_count/no_full_text_count make the split structural.
    fetched_count: int
    no_full_text_count: int
    fetch_log: tuple["FetchLogEntry", ...]  # PS2-07 — fetch-shaped log
    # Fetch-gate A1 (MODIFIED) — the transient payload carrier: one
    # FetchedPayload per FETCHED source, order-aligned with `per_source`.
    # Read-only slice: these are in-memory bytes handed to the task write
    # path (the sole dereference point); nothing persists them here.
    payloads: tuple[FetchedPayload, ...] = ()
    # Fetch-gate FD-02 — the batch cause notes (the daily-cap stop names the
    # source index so the aggregate's cause is the CAP, never N independent
    # source failures).
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FetchRequest:
    """Per-task fetch bounds (blueprint §5.3 — S11 scale classes).

    `deadline_monotonic` (D1, P-AUTO-3 redteam) is the dispatch's absolute
    overall wall-clock deadline (a ``Clock.monotonic`` reading; None =
    unbounded) — the fetch driver checks it before every source and retry
    attempt."""

    max_sources: int
    size_cap_bytes: int
    retry_policy: "RetryPolicy"
    deadline_monotonic: float | None = None


@dataclass(frozen=True)
class RetryPolicy:
    """Transient-retry policy (contract §6.3) — jittered exponential backoff."""

    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter: bool = True


@dataclass(frozen=True)
class FetchLogEntry:
    """PS2-07 — one fetch-shaped request-log entry per source (the walk-shaped
    `RequestLogRecord` — cursor_chain/page_counts/reconciliation — does not fit a
    batch of fetches).

    Fetch-gate F6 — `attempts` + `attempt_verdicts` enrich the entry so the
    logical fetch and its network attempts are reconstructable ("attempt 1 →
    TIMEOUT, attempt 2 → SUCCESS"); bounded by `retry_policy.max_retries + 1`.
    """

    source_ref: str  # the SearchResult.result_id
    status: Literal["FETCHED", "NO_FULL_TEXT", "FAILED"]
    failure_class: str | None
    hazard_verdict: str
    size_bytes: int | None
    content_hash: str | None
    access_timestamp_utc: str
    attempts: int = 1  # F6 — transport attempts (a never-attempted cap-stop entry is 0)
    attempt_verdicts: tuple[str, ...] = ()  # F6 — per-attempt hazard class / TRANSIENT


@dataclass(frozen=True)
class RequestLogRecord:
    """The walk's redacted request log (contract §8 / blueprint §5.2) — re-runnable,
    deterministic, the future budget ledger's cost input (contract §6.4)."""

    provider: str
    endpoint: str
    query: str
    request_params_redacted: dict[str, str]
    timestamps: tuple[str, str]  # first request, last response (UTC)
    cursor_chain: tuple[str | None, ...]  # per-page cursor_key
    page_counts: tuple[tuple[int, int | None], ...]  # (retrieved_on_page, total_reported)
    reconciliation: str
    total_is_estimate: bool
    hazard_verdicts: tuple[str, ...]
    provider_spec_version: str
    raw_artifact_hashes: tuple[str, ...]


# ── error taxonomy (contract §5.2 / blueprint §2.2) ──


class ProviderError(Exception):
    """Base provider error. Carries provider_id + hazard_class + recordable so the
    caller (and `search_accounting`) can classify without inspecting messages."""

    def __init__(
        self,
        message: str,
        provider_id: str = "",
        hazard_class: str = "UNKNOWN",
        recordable: bool = True,
    ) -> None:
        super().__init__(message)
        self.provider_id = provider_id
        self.hazard_class = hazard_class
        self.recordable = recordable


class TransientProviderError(ProviderError):
    """429/THROTTLED/5xx/timeouts → retryable (contract §6.3 transient)."""


class PermanentProviderError(ProviderError):
    """MALFORMED_200/REWRITE_SUSPECT/CURSOR_TRAP/PARTIAL_CONTENT → no retry."""


class RetrievalShortfallError(PermanentProviderError):
    """The walk terminated prematurely or the search ran and found nothing.

    `aggregate` distinguishes SHORTFALL-ish terminations from the EMPTY case:
    EMPTY strictly means "searched, found nothing" — never "could not search"
    (PS-13); that is `ProviderUnavailableError`.
    """

    def __init__(
        self,
        message: str,
        provider_id: str = "",
        expected: int | None = None,
        got: int = 0,
        cause_class: str = "",
        aggregate: str = "SHORTFALL",
        recordable: bool = True,
        notes: Sequence[str] = (),
    ) -> None:
        super().__init__(message, provider_id=provider_id,
                         hazard_class=cause_class or "SHORTFALL", recordable=recordable)
        self.expected = expected
        self.got = got
        self.cause_class = cause_class
        self.aggregate = aggregate
        # WK-06 — the aggregate raise carries the merged per-provider notes so
        # the typed error alone tells WHICH provider shortfalled and why (the
        # "never silent" detail), not just that one did.
        self.notes = tuple(notes)


class ProviderUnavailableError(ProviderError):
    """aggregate=UNAVAILABLE — could not search (every routed provider
    throttled/errored/unreachable, or no adapter was routeable). Deliberately
    distinct from EMPTY so "no literature exists" can never be concluded from
    "providers were down" (PS-13/PS3-06)."""

    def __init__(
        self,
        message: str,
        provider_id: str = "",
        hazard_class: str = "UNKNOWN",
        recordable: bool = True,
        notes: Sequence[str] = (),
    ) -> None:
        super().__init__(message, provider_id=provider_id,
                         hazard_class=hazard_class, recordable=recordable)
        # WK-06 — same contract as RetrievalShortfallError: which providers
        # were down and why, carried on the raise.
        self.notes = tuple(notes)


class ProviderValidationError(PermanentProviderError):
    """Bad hint / bad identifier / allowlist rejection — before any I/O."""


class RedactionError(ProviderError):
    """Fail-closed: redaction could not run → no request is issued.

    PS3-07: the message names the offending parameter, NEVER its value — it is
    raised while raw credentials are in scope.
    """


class FetchContentRejected(PermanentProviderError):
    """FD-01 — the adapter's `validate_fetch` hook rejected a fetch response
    body as not-full-text (junk HTML, `<error>`-rooted wrapper, HTML-when-PDF-
    promised). A per-source rejection: the fetch driver maps it to
    `FetchFailure(EMPTY_RESULT, reason=<message>)` — never a `FetchedSource`.
    The message must never embed the rejected payload (F12 — no body data in
    failure objects)."""
