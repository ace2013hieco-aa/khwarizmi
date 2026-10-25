"""OPS-5A — the two research-egress capabilities and their journal path.

This module supplies exactly the two capability ids a live run can honestly
execute at this base:

- ``source_search`` — one bounded walk over one allowlisted provider
  (OpenAlex or PubMed) through the shipped adapter and driver. Its delivered
  rows are registered in a per-composed-run, in-memory snapshot map and the
  success detail carries a content-derived ``search_handle``, the row count
  and the omitted count — never a title, URL, identifier or row hash;
- ``source_fetch`` — one bounded fetch of either a model-named URL or one row
  of a prior search (``search_handle`` + 0-based ``row_index``), pre-vetted
  against the code-owned D5 surface before any dial. Both forms run the same
  fetch chain and write the same ``source_payload`` artifact; the handle form
  adds the choice (handle, index, row hash) to that row's metadata.

The search snapshot is transient: no table, no artifact, no checkpoint and no
journal row. The handle is a locator, not a citation; only the fetched
``source_payload`` artifact can satisfy ``EVIDENCE_REF``.

Both are ``TOOL``-kind capabilities over in-process tools
(``network=True``, ``sandboxed=False``). Under OPS-5 R5 that is legal: the
tool runs in the controller's process, and the declaration records that fact
as ``IN_PROCESS_ENVIRONMENT`` — the plane never claims an isolation it did
not apply. The barriers are the closed request schema, the pre-dial allowlist,
the host pin and the transport timeout (in that order).

Egress journaling (R1)
----------------------
A network act that is not journaled is unobservable. Successful interactions
ride the shipped ``RecordedTransport`` → ``make_persisting_sink`` path (the
same owner the task-side source handlers use); the executor binds the project
and ``retain_body=False``, so the row carries identity, redacted request
forms and a response **digest** — never the fetched body, never a response
excerpt. A pre-dial refusal never reaches the transport, so this module writes
the refusal through the same sink as an ``EGRESS_REFUSED`` interaction row:
the redacted URL (host) and the rule's **named code** as ``failure_class``,
with ``response_body_hash = NULL``. No new table, no new transaction, no new
event kind.

Task linkage
------------
``provider_interactions.task_id`` is an FK into ``tasks`` and is nullable.
``ToolCallContext`` carries no task id, and the only run-derived value
available here (the plane's idempotency key) is not a task row, so the
executor binds ``project_id`` and leaves ``task_id`` NULL rather than writing
an FK-invalid link. The call's idempotency key rides the invocation envelope
(recorded by the orchestration side), which is the plane's own linkage.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import urllib.parse
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hermes.persistence.provider_interactions import make_persisting_sink
from hermes.research.live_fetch import (
    EgressRefusal,
    allowlist_from_config,
    build_live_fetch_wiring,
    preflight_egress,
)
from hermes.research.source_handlers import ProviderMachinery
from hermes.tools.capabilities.registry import CapabilityRegistry
from hermes.tools.capabilities.types import (
    IN_PROCESS_ENVIRONMENT,
    Capability,
    CapabilityKind,
    InputField,
    RiskLevel,
    Tool,
    ToolCallContext,
    ToolResult,
    ToolSet,
)
from hermes.tools.providers.base import WalkRequest
from hermes.tools.providers.normalize import (
    RetrievalHints,
    canonicalize_identifiers,
)
from hermes.tools.providers.paginate import combine, fetch_batch, walk
from hermes.tools.providers.redact import DEFAULT_POLICY, redact_url
from hermes.tools.providers.replay import (
    RecordedInteraction,
    RecordedTransport,
    fixture_id_of,
    interaction_id_of,
)
from hermes.tools.research_sources import (
    FetchRequest,
    ProviderUnavailableError,
    ProviderValidationError,
    RetrievalShortfallError,
    RetryPolicy,
    SearchOutcome,
    SearchResult,
    content_hash_of_search_result,
    make_search_result_id,
    search_result_from_mapping,
    sha256_hex,
)

__all__ = [
    "DEFAULT_SEARCH_MAX_RESULTS",
    "EVIDENCE_HANDLE_PREFIX",
    "FETCH_ROW_INDEX_FIELD",
    "FETCH_SEARCH_HANDLE_FIELD",
    "FETCH_TARGET_AMBIGUOUS",
    "FETCH_TARGET_MISSING",
    "FETCH_URL_FIELD",
    "HANDLE_SEPARATOR",
    "MAX_SEARCH_RESULTS",
    "PROVIDER_HOSTS",
    "REFUSAL_OUTCOME_KIND",
    "RESEARCH_EGRESS_TOOL_SET_ID",
    "SEARCH_HANDLE_COLLISION",
    "SEARCH_HANDLE_EXPIRED",
    "SEARCH_HANDLE_FIELD_MAX_BYTES",
    "SEARCH_HANDLE_INVALID",
    "SEARCH_HANDLE_PREFIX",
    "SEARCH_PROVIDER_MISMATCH",
    "SEARCH_REGISTRY_CAPACITY",
    "SEARCH_ROW_INDEX_OUT_OF_RANGE",
    "SOURCE_FETCH_SIZE_CAP_BYTES",
    "SOURCE_PAYLOAD_ARTIFACT_TYPE",
    "SOURCE_PAYLOAD_HANDLE_PREFIX",
    "SOURCE_REF_SEPARATOR",
    "SOURCE_SEARCH_SIZE_CAP_BYTES",
    "SUPPLIED_CAPABILITY_IDS",
    "ResearchEgressSupply",
    "SearchHandleCollision",
    "SearchResultRegistry",
    "SearchSelectionRefusal",
    "artifact_handles",
    "build_research_egress_supply",
    "research_egress_declarations",
    "search_handle_of",
    "source_payload_ref",
]

#: The supplied set — deliberately exactly the two ids `researcher` declares.
SUPPLIED_CAPABILITY_IDS: tuple[str, ...] = ("source_fetch", "source_search")

#: The one named composition the run's grants open (OPS-5B derives grants from
#: `agent_profile` over this set; 5A only declares it).
RESEARCH_EGRESS_TOOL_SET_ID = "set.research_egress"

#: Closed provider set. `source_fetch` additionally checks that the actual
#: request host belongs to the selected provider's own surface.
PROVIDER_HOSTS: dict[str, frozenset[str]] = {
    "openalex": frozenset({"api.openalex.org", "openalex.org"}),
    "pubmed": frozenset({"eutils.ncbi.nlm.nih.gov",
                         "pubmed.ncbi.nlm.nih.gov"}),
}

DEFAULT_SEARCH_MAX_RESULTS = 10
MAX_SEARCH_RESULTS = 25
SOURCE_SEARCH_SIZE_CAP_BYTES = 1024 * 1024
SOURCE_FETCH_SIZE_CAP_BYTES = 256 * 1024

#: The `outcome_kind` of a refusal row written by this module. It is a
#: provider-interaction row (the existing journal surface), not an event kind.
REFUSAL_OUTCOME_KIND = "EGRESS_REFUSED"

#: The artifact handle/ref forms the model is told to cite. The handle is
#: ``<kind>/<id>`` (the plane's HANDLE_PATTERN); the evidence/source ref is
#: ``<kind>:<id>`` (EVIDENCE_TRANSITION / source_payload). Both come from this
#: one pair of constants, so the tool and the contract note cannot drift.
EVIDENCE_HANDLE_PREFIX = "evidence"
SOURCE_PAYLOAD_HANDLE_PREFIX = "source_payload"
HANDLE_SEPARATOR = "/"
SOURCE_REF_SEPARATOR = ":"

#: The one artifact type a capability-written payload row may carry.
SOURCE_PAYLOAD_ARTIFACT_TYPE = "source_payload"

#: OPS-5C — the transient search-snapshot handle. The handle names the
#: delivered rows and their provider order; it is not an artifact, not a
#: citation and never durable. The full 64-hex digest is used (no alias).
SEARCH_HANDLE_PREFIX = "search_"
SEARCH_HANDLE_HEX_LENGTH = 64
#: The `source_fetch.search_handle` field bound (the 71-byte handle fits).
SEARCH_HANDLE_FIELD_MAX_BYTES = 96
#: At most 32 snapshots per composed run; the oldest is evicted on insert.
SEARCH_REGISTRY_CAPACITY = 32

#: One spelling for the two target forms, shared by the declaration and the
#: generated prompt sentence so a rename cannot leave the note stale.
FETCH_URL_FIELD = "url"
FETCH_SEARCH_HANDLE_FIELD = "search_handle"
FETCH_ROW_INDEX_FIELD = "row_index"

#: The pre-dial selection refusals. They are tool-result codes, not plane or
#: gateway codes: the call was allowed, the model's target was wrong.
SEARCH_HANDLE_INVALID = "SEARCH_HANDLE_INVALID"
SEARCH_HANDLE_EXPIRED = "SEARCH_HANDLE_EXPIRED"
SEARCH_PROVIDER_MISMATCH = "SEARCH_PROVIDER_MISMATCH"
SEARCH_ROW_INDEX_OUT_OF_RANGE = "SEARCH_ROW_INDEX_OUT_OF_RANGE"
SEARCH_HANDLE_COLLISION = "SEARCH_HANDLE_COLLISION"
FETCH_TARGET_AMBIGUOUS = "FETCH_TARGET_AMBIGUOUS"
FETCH_TARGET_MISSING = "FETCH_TARGET_MISSING"

_SEARCH_HANDLE_RE = re.compile(
    rf"{re.escape(SEARCH_HANDLE_PREFIX)}[0-9a-f]{{{SEARCH_HANDLE_HEX_LENGTH}}}\Z")

#: One bounded retry for a transient fetch; deterministic, no jitter.
FETCH_RETRY_POLICY = RetryPolicy(
    max_retries=1, base_delay_seconds=0.0, max_delay_seconds=0.0,
    jitter=False)


# ── declarations ──


def research_egress_declarations(
) -> tuple[tuple[Tool, ...], tuple[Capability, ...], ToolSet]:
    """The code-owned declaration table for the two capabilities.

    Build it once and register every member: the registry's allowlist, the
    tools, the capabilities and the tool set are all derived from this literal,
    so registry membership equals allowlist membership by construction.
    """
    provider_field = InputField(
        name="provider", type="string",
        allowed_values=frozenset(PROVIDER_HOSTS))
    search = Tool(
        tool_id="source_search",
        summary=("Search one allowlisted provider (OpenAlex or PubMed) for "
                 "source rows. Runs in-process (no sandbox)."),
        inputs=(
            provider_field,
            InputField(name="topic", type="string", required=False,
                       max_bytes=512),
            InputField(name="doi", type="string", required=False,
                       max_bytes=256),
            InputField(name="pmid", type="string", required=False,
                       max_bytes=32),
            InputField(name="max_results", type="integer", required=False,
                       max_bytes=3),
        ),
        risk=RiskLevel.MEDIUM,
        network=True,
        sandboxed=False,
        environment=IN_PROCESS_ENVIRONMENT,
        timeout_seconds=60.0,
    )
    fetch = Tool(
        tool_id="source_fetch",
        summary=("Fetch one source by allowlisted URL, or one row of a prior "
                 "search by its transient handle and 0-based index. Runs "
                 "in-process (no sandbox)."),
        inputs=(
            provider_field,
            InputField(name=FETCH_URL_FIELD, type="string", required=False,
                       max_bytes=2048),
            InputField(name=FETCH_SEARCH_HANDLE_FIELD, type="string",
                       required=False,
                       max_bytes=SEARCH_HANDLE_FIELD_MAX_BYTES),
            InputField(name=FETCH_ROW_INDEX_FIELD, type="integer",
                       required=False, max_bytes=3),
        ),
        risk=RiskLevel.MEDIUM,
        network=True,
        sandboxed=False,
        environment=IN_PROCESS_ENVIRONMENT,
        timeout_seconds=60.0,
    )
    capabilities = (
        Capability(
            capability_id="source_fetch", tool_id="source_fetch",
            summary="Fetch one allowlisted source URL.",
            kind=CapabilityKind.TOOL, risk=RiskLevel.MEDIUM),
        Capability(
            capability_id="source_search", tool_id="source_search",
            summary="Search one allowlisted provider.",
            kind=CapabilityKind.TOOL, risk=RiskLevel.MEDIUM),
    )
    tool_set = ToolSet(
        set_id=RESEARCH_EGRESS_TOOL_SET_ID,
        capability_ids=SUPPLIED_CAPABILITY_IDS,
        summary="the research egress surface (source_search, source_fetch)")
    return ((search, fetch), capabilities, tool_set)


# ── the egress journal (the existing provider-interaction sink) ──


class _EgressJournal:
    """Writes the metadata-only refusal row through the existing sink.

    A refusal is an interaction-shaped fact: who was addressed, what the rule
    said, and nothing else. No body, no response excerpt — the row's
    `response_body_hash` is NULL and its request form is the redacted URL.
    """

    def __init__(self, conn: Any, store: Any, clock: Any) -> None:
        self._sink = make_persisting_sink(conn, store, clock)
        self._clock = clock

    def refusal(
        self,
        *,
        project_id: str,
        provider: str,
        url: str,
        code: str,
        detail: str,
        adapter: Any,
    ) -> None:
        redacted = redact_url(url, DEFAULT_POLICY)
        normalized = {"url": redacted, "params": {}}
        request_hash = hashlib.sha256(json.dumps(
            normalized, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")).hexdigest()
        provider_id = provider if provider in PROVIDER_HOSTS else "unknown"
        interaction = RecordedInteraction(
            interaction_id=interaction_id_of(
                fixture_id_of(provider_id, normalized),
                status_class="REFUSED",
                body_hash=None,
                failure_class=code,
                task_id=None),
            provider_id=provider_id,
            adapter_version=str(getattr(adapter, "adapter_version", "1")),
            parser_version=str(getattr(adapter, "parser_version", "1")),
            normalized_request=normalized,
            request_hash=request_hash,
            status_class="REFUSED",
            response_body_hash=None,
            outcome_kind=REFUSAL_OUTCOME_KIND,
            failure_class=code,
            retrieved_at=_now_utc(self._clock),
            source_url_redacted=redacted,
            project_id=project_id,
        )
        # `persist_interaction` validates the request form's size and secret
        # content, then writes the row; the sink gets no body at all.
        self._sink(interaction, None)


# ── the transient search snapshot (OPS-5C) ──


def _row_identity(row: SearchResult) -> tuple[str, str, str]:
    """The handle preimage for one delivered row: identity, hash and URL.

    Deliberately excludes the retrieval metadata (`access_timestamp_utc`,
    request log, counts), so the same provider rows re-derive the same
    handle; the delivered order is the caller's and is never re-sorted.
    """
    return (row.result_id, row.content_hash, row.source_url)


def search_handle_of(provider: str, rows: Sequence[SearchResult]) -> str:
    """The content-derived ``search_<64 hex>`` handle for one delivered set.

    The preimage is ``{provider, rows:[{result_id, content_hash, source_url}]}``
    in the **delivered (relevance) order**. Order is part of the meaning: the
    provider ranks its hits, so reordering the rows is a different search
    result and derives a different handle. A repeated identical search derives
    the same handle.

    The encoding is key-sorted but **list-preserving**. The repository's
    ``canonical_json`` sorts a list of dicts by canonical JSON by design (it
    exists for order-independent derived sets), which would silently erase the
    rank; it is deliberately not used here.
    """
    preimage = {
        "provider": provider,
        "rows": [
            {
                "result_id": row.result_id,
                "content_hash": row.content_hash,
                "source_url": row.source_url,
            }
            for row in rows
        ],
    }
    encoded = json.dumps(
        preimage, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return SEARCH_HANDLE_PREFIX + sha256_hex(encoded)


@dataclass(frozen=True, slots=True)
class _SearchSnapshot:
    provider: str
    rows: tuple[SearchResult, ...]

    def identities(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(_row_identity(row) for row in self.rows)


class SearchSelectionRefusal(Exception):
    """A pre-dial target-selection refusal (data for the model, not a crash).

    The call was authorized and invoked; the *target* the model named cannot
    be resolved. The executor turns this into an OK observation whose payload
    is ``status="REFUSED"``: no dial, no artifact, no journal row, and the run
    continues so the model can correct.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class SearchHandleCollision(ProviderValidationError):
    """Two different row sets derived the same handle — never overwritten.

    A SHA-256 collision is not the concern; a registry bug or a handle
    derivation change is. Failing closed keeps a handle from silently naming
    a row set it was not derived from.
    """

    code = SEARCH_HANDLE_COLLISION


class SearchResultRegistry:
    """The per-composed-run, bounded, in-memory search snapshot map.

    The registry holds the delivered ``SearchResult`` objects (titles
    included) only in memory: no table, no artifact, no checkpoint, no
    journal row. A handle names an immutable delivered tuple; a repeated
    identical search refreshes its recency but never replaces the tuple. The
    oldest snapshot is evicted when the bound is exceeded; there is no TTL.
    """

    def __init__(self, capacity: int = SEARCH_REGISTRY_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("a search registry needs a positive capacity")
        self._capacity = capacity
        self._snapshots: OrderedDict[str, _SearchSnapshot] = OrderedDict()

    def __len__(self) -> int:
        return len(self._snapshots)

    def register(self, provider: str, rows: Sequence[SearchResult]) -> str:
        """Register one delivered set and return its derived handle.

        A handle already present with the same row identities keeps its
        original tuple (the rows are retrieval-equivalent; the timestamp and
        request log are not identity) and moves to the newest end. A handle
        present with different identities raises: a collision is never a
        remap.
        """
        delivered = tuple(rows)
        handle = search_handle_of(provider, delivered)
        existing = self._snapshots.get(handle)
        if existing is not None:
            identities = tuple(_row_identity(row) for row in delivered)
            if (existing.provider != provider
                    or existing.identities() != identities):
                raise SearchHandleCollision(
                    "search handle collision: a different row set derived an "
                    "existing handle — refusing to remap it")
            self._snapshots.move_to_end(handle)
            return handle
        self._snapshots[handle] = _SearchSnapshot(provider, delivered)
        while len(self._snapshots) > self._capacity:
            self._snapshots.popitem(last=False)
        return handle

    def resolve(self, handle: str, provider: str, row_index: int
                ) -> SearchResult:
        """Resolve ``(handle, provider, 0-based row_index)`` or refuse.

        Checks are ordered so each refusal is the most specific true one:
        the handle must be well formed, then present, then owned by the
        named provider, then in range. Nothing here dials.
        """
        if not isinstance(handle, str) or _SEARCH_HANDLE_RE.fullmatch(
                handle) is None:
            raise SearchSelectionRefusal(
                SEARCH_HANDLE_INVALID,
                f"{handle!r} is not a {SEARCH_HANDLE_PREFIX}<64 hex> handle")
        snapshot = self._snapshots.get(handle)
        if snapshot is None:
            raise SearchSelectionRefusal(
                SEARCH_HANDLE_EXPIRED,
                "no search snapshot is registered for this handle in this "
                "composed run (expired, evicted or a new process) — search "
                "again")
        if snapshot.provider != provider:
            raise SearchSelectionRefusal(
                SEARCH_PROVIDER_MISMATCH,
                f"the handle belongs to provider {snapshot.provider!r}, not "
                f"{provider!r}")
        if (isinstance(row_index, bool) or not isinstance(row_index, int)
                or not 0 <= row_index < len(snapshot.rows)):
            raise SearchSelectionRefusal(
                SEARCH_ROW_INDEX_OUT_OF_RANGE,
                f"row_index {row_index!r} is outside 0.."
                f"{max(0, len(snapshot.rows) - 1)} for this search ("
                f"{len(snapshot.rows)} row(s))")
        return snapshot.rows[row_index]


# ── executors ──


class _SupplyBase:
    def __init__(
        self,
        *,
        machinery: ProviderMachinery,
        project_id: str,
        allowlist: tuple[str, ...],
        journal: _EgressJournal,
        resolve: Callable[[str], tuple[str, ...]] | None,
        store: Any,
        search_registry: SearchResultRegistry,
    ) -> None:
        self._machinery = machinery
        self._project_id = project_id
        self._allowlist = allowlist
        self._journal = journal
        self._resolve = resolve
        self._store = store
        self._search_registry = search_registry

    def _adapter(self, arguments: Mapping[str, Any]) -> Any:
        provider = str(arguments.get("provider") or "")
        return self._machinery.adapter(provider)

    def _bound_transport(self, adapter: Any) -> Any:
        transport = self._machinery.transport
        if isinstance(transport, RecordedTransport):
            # R1 — the interaction row is metadata plus digests; no body bytes
            # reach the sink. task_id stays NULL (see the module docstring).
            return transport.bound(project_id=self._project_id,
                                   adapter=adapter, retain_body=False)
        return transport


class SourceSearchExecutor(_SupplyBase):
    """One provider walk → one bounded JSON observation of source rows."""

    def __call__(self, arguments: Mapping[str, Any],
                 context: ToolCallContext) -> ToolResult:
        provider = str(arguments.get("provider") or "")
        adapter = self._adapter(arguments)
        hints = _search_hints(arguments)
        maximum = _search_max_results(arguments)
        request = WalkRequest(
            max_results=maximum,
            max_pages=1,
            page_size_cap=maximum,
            size_cap_bytes=SOURCE_SEARCH_SIZE_CAP_BYTES,
            deadline_monotonic=context.deadline_monotonic,
        )
        # The provider id is echoed from the closed allowed_values set; the
        # adapter accessor above already refused anything outside it, before
        # any I/O.
        outcome = walk(
            adapter, hints, request,
            transport=self._bound_transport(adapter),
            limiter=self._machinery.limiter,
            recorder=self._machinery.recorder,
            clock=self._machinery.clock,
            hazard_spec=self._machinery.spec(provider),
            redaction_policy=self._machinery.redaction_policy,
        )
        try:
            combined = combine([outcome], order=[provider])
        except RetrievalShortfallError as exc:
            # Searched, found nothing: an EMPTY result is an observation, not
            # a failure. The rows are empty and the note says why.
            empty = SearchOutcome(
                per_provider=outcome.per_provider,
                aggregate="EMPTY",
                notes=outcome.notes + tuple(exc.notes),
                request_log=outcome.request_log)
            return _search_result(provider, empty, self._search_registry)
        except ProviderUnavailableError:
            # Could not search is NOT "no literature" (PS-13): fail the call.
            raise
        return _search_result(provider, combined, self._search_registry)


class SourceFetchExecutor(_SupplyBase):
    """One fetch target → the vetted provider fetch, journaled on both paths.

    Two target forms are accepted, never both and never neither: the OPS-5B
    ``url`` form, and the OPS-5C ``(search_handle, row_index)`` form which
    selects one row of a prior search snapshot. The selection is a pre-dial,
    data-shaped refusal; the fetch chain below it is the same chain.
    """

    def __call__(self, arguments: Mapping[str, Any],
                 context: ToolCallContext) -> ToolResult:
        provider = str(arguments.get("provider") or "")
        adapter = self._adapter(arguments)
        try:
            target = _select_fetch_target(
                arguments, provider=provider,
                now=_now_utc(self._machinery.clock),
                registry=self._search_registry)
        except SearchSelectionRefusal as exc:
            # A caller's bad target is data: no dial, no artifact, no journal
            # row, and the run continues (R3). A real fetch failure below keeps
            # the OPS-5A fatal path.
            return _refused_result("source_fetch", exc.code, exc.detail)
        source = target.source
        try:
            spec = adapter.build_fetch_request(source)
        except ProviderValidationError:
            # A missing/empty URL is a schema-shaped refusal, not an egress
            # attempt; there is no host to journal.
            raise
        # The code-owned allowlist is the FIRST barrier: an out-of-surface
        # host refuses (and journals) before the provider-consistency check
        # below, so the named rule code is the egress layer's, not a
        # downstream inference.
        try:
            preflight_egress(spec.url, allowlist=self._allowlist,
                             resolve=self._resolve)
        except EgressRefusal as exc:
            self._journal.refusal(
                project_id=self._project_id, provider=provider,
                url=spec.url, code=exc.code, detail=exc.detail, adapter=adapter)
            raise
        self._require_provider_host(provider, spec.url, adapter)
        outcome = fetch_batch(
            adapter, [source],
            FetchRequest(
                max_sources=1,
                size_cap_bytes=SOURCE_FETCH_SIZE_CAP_BYTES,
                retry_policy=FETCH_RETRY_POLICY,
                deadline_monotonic=context.deadline_monotonic),
            transport=self._bound_transport(adapter),
            limiter=self._machinery.limiter,
            recorder=self._machinery.recorder,
            clock=self._machinery.clock,
            hazard_spec=self._machinery.spec(provider),
            redaction_policy=self._machinery.redaction_policy,
        )
        if outcome.per_source and outcome.payloads:
            payload = outcome.payloads[0]
            row = self._record_payload(
                payload, provider=provider, url=spec.url, context=context,
                search_handle=target.search_handle,
                row_index=target.row_index,
                search_result_hash=target.search_result_hash)
            handles = artifact_handles(row)
            document: dict[str, Any] = {
                "capability": "source_fetch",
                "provider": provider,
                "url": source.source_url,
                "status": "FETCHED",
                "artifact_id": row["artifact_id"],
                "content_hash": row["content_hash"],
                "source_ref": source_payload_ref(row),
                "media_type": row.get("metadata", {}).get(
                    "media_type", payload.artifact.media_type),
                "size_bytes": row["size_bytes"],
                "retrieved_at": row["created_at"],
            }
            if target.search_handle:
                # The observation names the choice as well as the bytes; the
                # artifact metadata below carries the same three fields.
                document["search_handle"] = target.search_handle
                document["row_index"] = target.row_index
                document["search_result_hash"] = target.search_result_hash
            return ToolResult(
                payload=json.dumps(document, sort_keys=True,
                                   ensure_ascii=False),
                artifacts=handles,
                notes=(
                    (f"fetched {provider}: {row['size_bytes']} bytes; cite "
                     f"{handles[0]} or {source_payload_ref(row)}"),
                ))
        if outcome.no_full_text:
            record = outcome.no_full_text[0]
            return ToolResult(
                payload=json.dumps({
                    "capability": "source_fetch",
                    "provider": provider,
                    "url": source.source_url,
                    "status": "NO_FULL_TEXT",
                    "kind": record.no_full_text_kind,
                    "evidence": dict(record.evidence_basis),
                }, sort_keys=True, ensure_ascii=False),
                notes=(f"no full text ({record.no_full_text_kind})",))
        failure = outcome.failed[0] if outcome.failed else None
        if failure is None:
            raise ProviderValidationError(
                "source_fetch: the fetch driver returned no resolution — "
                "refusing to report a success")
        raise SourceFetchFailed(failure.failure_class, failure.reason)

    def _record_payload(
        self,
        payload: Any,
        *,
        provider: str,
        url: str,
        context: ToolCallContext,
        search_handle: str = "",
        row_index: int | None = None,
        search_result_hash: str = "",
    ) -> dict[str, Any]:
        """Record the fetched bytes as one content-addressed source artifact.

        R1 — recording, not authoring: the bytes are the provider's response,
        the type is fixed here, the identity is the store's content hash, the
        project is the composition's, and the destination is the store's
        content-addressed root. The model cannot name any of them; it only
        chose to fetch. The row carries enough attribution (provider, host,
        digest, redacted URL, call key) that it is traceable to the fetch.

        OPS-5C adds the *choice* to the same metadata when the fetch addressed
        a search row: the handle, the 0-based delivered index and that row's
        semantic hash. No second writer, type, table or transaction.
        """
        if self._store is None:
            raise SourceArtifactUnavailable(
                "source_fetch: no artifact store is wired — the fetched bytes "
                "cannot be recorded, so the call fails closed rather than "
                "returning an uncitable handle")
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        redacted = redact_url(url, DEFAULT_POLICY)
        metadata: dict[str, Any] = {
            "capability_id": "source_fetch",
            "provider": provider,
            "host": host,
            "content_digest": payload.artifact.content_hash,
            "source_url_redacted": redacted,
            "media_type": payload.artifact.media_type,
            "retrieved_at": _now_utc(self._machinery.clock),
            "idempotency_key": context.idempotency_key,
            "lease_generation": context.lease_generation,
            "profile": context.profile,
        }
        if search_handle:
            metadata["search_handle"] = search_handle
            metadata["row_index"] = row_index
            metadata["search_result_hash"] = search_result_hash
        row = self._store.write(
            payload.raw_bytes,
            artifact_type=SOURCE_PAYLOAD_ARTIFACT_TYPE,
            producer=(f"capability:source_fetch:{provider}:"
                      f"{context.profile}:{context.idempotency_key}"),
            project_id=self._project_id,
            task_id=None,
            metadata=metadata,
            artifact_id=payload.artifact.content_hash,
        )
        if not isinstance(row, dict):
            raise SourceArtifactConflict(
                "source_fetch: the artifact store returned a non-row — "
                "refusing to cite it")
        if row.get("artifact_type") != SOURCE_PAYLOAD_ARTIFACT_TYPE:
            raise SourceArtifactConflict(
                "source_fetch: the content already exists as artifact type "
                f"{row.get('artifact_type')!r}, not "
                f"{SOURCE_PAYLOAD_ARTIFACT_TYPE!r} — a same-hash different-type "
                "row is never reused as a source (R02)")
        if row.get("content_hash") != payload.artifact.content_hash:
            raise SourceArtifactConflict(
                "source_fetch: the artifact store returned content hash "
                f"{row.get('content_hash')!r}, not "
                f"{payload.artifact.content_hash!r}")
        if row.get("project_id") != self._project_id:
            raise SourceArtifactConflict(
                "source_fetch: the content already exists in another project — "
                "refusing to hand back a row this project cannot dereference "
                "(R5)")
        return row

    def _require_provider_host(self, provider: str, url: str,
                               adapter: Any) -> None:
        """A URL must belong to the provider it names.

        The allowlist admits four hosts across two providers; fetching a
        PubMed URL under the OpenAlex hazard spec would classify the response
        with the wrong rules. This is a pre-dial refusal, journaled with the
        same metadata-only shape as an allowlist refusal.
        """
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        allowed = PROVIDER_HOSTS.get(provider, frozenset())
        if host in allowed:
            return
        detail = (f"host {host or '<no host>'!r} is not a {provider!r} "
                  f"surface ({sorted(allowed)})")
        self._journal.refusal(
            project_id=self._project_id, provider=provider, url=url,
            code="PROVIDER_HOST_MISMATCH", detail=detail, adapter=adapter)
        raise EgressRefusal("PROVIDER_HOST_MISMATCH", host, detail)


class SourceFetchFailed(ProviderValidationError):
    """The fetch resolved to a failure (a typed fetch verdict, not a crash)."""

    def __init__(self, failure_class: str, detail: str) -> None:
        super().__init__(f"source fetch failed [{failure_class}]: {detail}")
        self.failure_class = failure_class


class SourceArtifactUnavailable(ProviderValidationError):
    """The fetch succeeded but no artifact store is wired for the bytes."""


class SourceArtifactConflict(ProviderValidationError):
    """The store returned a row this capability may not cite.

    A same-content row of a different type, a wrong content hash, or a row
    owned by another project all fail closed: an uncitable handle is worse
    than a typed refusal.
    """


# ── supply ──


@dataclass(frozen=True)
class ResearchEgressSupply:
    """Declarations plus implementations, ready for a composition to wire."""

    tools: tuple[Tool, ...]
    capabilities: tuple[Capability, ...]
    tool_set: ToolSet
    registry: CapabilityRegistry
    implementations: Mapping[str, Any]
    machinery: ProviderMachinery
    allowlist: tuple[str, ...]
    #: OPS-5C — the one transient snapshot map both executors share for this
    #: composed run. In memory only; not an artifact, not a citation.
    search_registry: SearchResultRegistry


def build_research_egress_supply(
    *,
    conn: Any,
    store: Any,
    clock: Any,
    project_id: str,
    machinery: ProviderMachinery | None = None,
    sandbox_policy: Any | None = None,
    autonomy_caps: Any | None = None,
    allowlist: tuple[str, ...] | None = None,
    dns_resolve: Callable[[str], tuple[str, ...]] | None = None,
) -> ResearchEgressSupply:
    """Build the two capabilities over the shipped adapters and allowlist.

    ``machinery`` is an injection seam for tests (a scripted or recorded
    transport); when absent the production live-fetch wiring is built, which
    is the same path the task-side source handlers use. ``allowlist`` defaults
    to the code-owned surface narrowed by ``sandbox_policy`` — config may only
    narrow it (``allowlist_from_config``). ``autonomy_caps`` is the P-AUTO-4
    operator surface: it must be threaded through the wiring or a tightened
    rate/deadline knob is silently ignored (FIX-C1 class).
    """
    if machinery is None:
        wiring = build_live_fetch_wiring(
            conn, store, clock, sandbox_policy=sandbox_policy,
            autonomy_caps=autonomy_caps, dns_resolve=dns_resolve)
        active_machinery: ProviderMachinery = wiring.machinery
    else:
        active_machinery = machinery
    resolved_allowlist = (tuple(allowlist) if allowlist is not None
                          else allowlist_from_config(sandbox_policy))
    if not resolved_allowlist:
        raise ProviderValidationError(
            "research capability supply: an empty egress allowlist would make "
            "every call unusable — refusing to build")
    tools, capabilities, tool_set = research_egress_declarations()
    registry = CapabilityRegistry(
        allowlist=frozenset(capability.capability_id
                            for capability in capabilities))
    for tool in tools:
        registry.register_tool(tool)
    for capability in capabilities:
        registry.register_capability(capability)
    registry.register_tool_set(tool_set)
    journal = _EgressJournal(conn, store, clock)
    search_registry = SearchResultRegistry()
    shared: dict[str, Any] = {
        "machinery": active_machinery,
        "project_id": project_id,
        "allowlist": resolved_allowlist,
        "journal": journal,
        "resolve": dns_resolve,
        "store": store,
        "search_registry": search_registry,
    }
    implementations: dict[str, Any] = {
        "source_search": SourceSearchExecutor(**shared),
        "source_fetch": SourceFetchExecutor(**shared),
    }
    return ResearchEgressSupply(
        tools=tools, capabilities=capabilities, tool_set=tool_set,
        registry=registry, implementations=implementations,
        machinery=active_machinery, allowlist=resolved_allowlist,
        search_registry=search_registry)


# ── helpers ──


def _now_utc(clock: Any) -> str:
    """The provider-clock convention, plus the bare-callable core clock."""
    now = getattr(clock, "now_utc", None)
    if callable(now):
        value = now()
        return str(value() if callable(value) else value)
    return str(clock())


def artifact_handles(row: Mapping[str, Any]) -> tuple[str, str]:
    """The two plane-legal handles for one persisted source row.

    ``evidence/<artifact_id>`` is the handle EVIDENCE_TRANSITION cites (as
    ``evidence:<artifact_id>``); ``source_payload/<content_hash>`` is the
    handle a source/claim ref cites. Both match the plane's HANDLE_PATTERN.
    """
    return (
        f"{EVIDENCE_HANDLE_PREFIX}{HANDLE_SEPARATOR}{row['artifact_id']}",
        (f"{SOURCE_PAYLOAD_HANDLE_PREFIX}{HANDLE_SEPARATOR}"
         f"{row['content_hash']}"),
    )


def source_payload_ref(row: Mapping[str, Any]) -> str:
    """The ``source_payload:<content_hash>`` ref for one persisted row."""
    return (f"{SOURCE_PAYLOAD_HANDLE_PREFIX}{SOURCE_REF_SEPARATOR}"
            f"{row['content_hash']}")


def _search_hints(arguments: Mapping[str, Any]) -> RetrievalHints:
    identifiers: dict[str, str] = {}
    for kind in ("doi", "pmid"):
        raw = str(arguments.get(kind) or "").strip()
        if raw:
            identifiers[kind] = raw
    topic = str(arguments.get("topic") or "").strip()
    if not identifiers and not topic:
        raise ProviderValidationError(
            "source_search requires one of topic, doi or pmid — an empty "
            "search is a caller mistake, not an observation")
    if identifiers and topic:
        mode = "MIXED"
    elif identifiers:
        mode = "IDENTIFIER"
    else:
        mode = "TOPIC"
    return RetrievalHints(identifiers=identifiers, topic=topic, mode=mode)


def _search_max_results(arguments: Mapping[str, Any]) -> int:
    raw = arguments.get("max_results", DEFAULT_SEARCH_MAX_RESULTS)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ProviderValidationError("source_search.max_results must be an integer")
    if not 1 <= raw <= MAX_SEARCH_RESULTS:
        raise ProviderValidationError(
            f"source_search.max_results must be between 1 and "
            f"{MAX_SEARCH_RESULTS}, got {raw}")
    return raw


def _search_result(provider: str, outcome: SearchOutcome,
                   registry: SearchResultRegistry) -> ToolResult:
    """The bounded search observation plus its transient handle.

    The detail discloses the delivered count, the omitted count and a derived
    handle — never a title, URL, identifier, result id or row hash. The rows
    themselves stay in the observation payload (which the prompt never
    carries) and in the in-memory snapshot the handle names.
    """
    delivered = tuple(outcome.per_provider)
    rows = [{
        "result_id": result.result_id,
        "provider": result.provider,
        "title": result.title,
        "year": result.year,
        "venue": result.venue,
        "identifiers": dict(result.identifiers),
        "source_url": result.source_url,
        "content_hash": result.content_hash,
        "page_index": result.page_index,
        "valid_negative": result.valid_negative,
    } for result in delivered]
    handle = registry.register(provider, delivered) if delivered else None
    total = delivered[0].total_count if delivered else None
    if total is None:
        omitted, estimate = "unknown", False
    else:
        omitted = str(max(0, total - len(delivered)))
        estimate = bool(delivered[0].total_is_estimate)
    note = (f"search {provider}: {len(rows)} source row(s) "
            f"({outcome.aggregate}); search_handle={handle or 'none'}; "
            f"rows={len(rows)}; omitted={omitted}")
    if estimate:
        note += "; omitted_is_estimate=true"
    return ToolResult(
        payload=json.dumps({
            "capability": "source_search",
            "provider": provider,
            "aggregate": outcome.aggregate,
            "rows": rows,
            "notes": list(outcome.notes),
        }, sort_keys=True, ensure_ascii=False),
        notes=(note,))


@dataclass(frozen=True, slots=True)
class _FetchTarget:
    """One selected fetch target: a URL carrier or a search-snapshot row."""

    source: SearchResult
    search_handle: str = ""
    row_index: int | None = None
    search_result_hash: str = ""


def _select_fetch_target(
    arguments: Mapping[str, Any],
    *,
    provider: str,
    now: str,
    registry: SearchResultRegistry,
) -> _FetchTarget:
    """Enforce exactly one target form and resolve it before any dial.

    ``url`` alone is the OPS-5B form. ``search_handle`` + ``row_index`` alone
    is the OPS-5C form. Both, neither, or an incomplete handle form is a
    named pre-dial refusal; an index/expiry/provider problem comes from the
    registry with its own named code.
    """
    url = arguments.get("url")
    handle = arguments.get("search_handle")
    row_index = arguments.get("row_index")
    has_url = isinstance(url, str) and bool(url.strip())
    has_handle = isinstance(handle, str) and bool(handle.strip())
    has_index = row_index is not None
    if has_url and (has_handle or has_index):
        raise SearchSelectionRefusal(
            FETCH_TARGET_AMBIGUOUS,
            "source_fetch takes exactly one target form: url, or "
            "search_handle + row_index — not both")
    if has_url:
        return _FetchTarget(_synthetic_source(provider, str(url), now))
    if not (has_handle and has_index):
        raise SearchSelectionRefusal(
            FETCH_TARGET_MISSING,
            "source_fetch needs either url or both search_handle and "
            "row_index — no target was named")
    row = registry.resolve(str(handle), provider, row_index)
    return _FetchTarget(
        row, search_handle=str(handle), row_index=row_index,
        search_result_hash=row.content_hash)


def _refused_result(capability: str, code: str, detail: str) -> ToolResult:
    """A benign, pre-dial REFUSED tool result (no artifact, no dial, no row).

    It is an OK observation carrying a REFUSED payload: the run continues and
    the model sees the named code in the next tick's bounded detail. It is
    deliberately not `TOOL_FAILED` — the C4 terminal rule is unchanged.
    """
    return ToolResult(
        payload=json.dumps({
            "capability": capability,
            "status": "REFUSED",
            "code": code,
            "detail": detail,
        }, sort_keys=True, ensure_ascii=False),
        artifacts=(),
        notes=(f"{capability} refused: {code}; {detail}",))


def _synthetic_source(provider: str, url: str, now: str) -> SearchResult:
    """A one-source fetch carrier for a model-named URL.

    The fetch driver consumes a `SearchResult` (provider, URL, identity); the
    capability supplies exactly that shape and no bibliographic claims beyond
    the URL and any identifier the URL itself names.

    HR-04 choke-point discipline: this is NOT a fourth direct SearchResult
    construction site. Identifiers pass `canonicalize_identifiers` (the single
    identity/normalization path) and the carrier is assembled through the
    audited closed-schema constructor (`search_result_from_mapping`), so the
    certified inventory of construction sites is unchanged. The content hash is
    then computed from the record, never supplied.
    """
    identifiers = canonicalize_identifiers(
        _identifiers_from_url(provider, url))
    endpoint = "capability.source_fetch"
    result_id = make_search_result_id(
        provider, endpoint, "", 0, None, identifiers)
    carrier = search_result_from_mapping({
        "result_id": result_id,
        "provider": provider,
        "endpoint": endpoint,
        "query": "",
        "request_params_redacted": {},
        "identifiers": identifiers,
        "title": "",
        "authors": (),
        "year": None,
        "venue": "",
        "abstract_sha256": None,
        "source_url": url,
        "access_timestamp_utc": now,
        "page_index": 0,
        "cursor_key": None,
        "raw_retrieved_count": 0,
        "delivered_count": 1,
        "total_count": None,
        "total_is_estimate": False,
        "reconciliation": "UNKNOWN",
        "content_hash": "",
        "provenance": {},
        "valid_negative": False,
        "valid_negative_for": None,
    })
    return dataclasses.replace(
        carrier, content_hash=content_hash_of_search_result(carrier))


def _identifiers_from_url(provider: str, url: str) -> dict[str, str]:
    path = urllib.parse.urlsplit(url).path.strip("/")
    if provider == "openalex":
        token = path.rsplit("/", 1)[-1] if path else ""
        if re.fullmatch(r"W\d+", token):
            return {"openalex_id": token}
    if provider == "pubmed":
        digits = re.sub(r"[^0-9]", "", path)
        if digits:
            return {"pmid": digits}
    return {}
