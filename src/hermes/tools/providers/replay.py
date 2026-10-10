"""CHG-2 — provider record/replay (transport determinism layer).

Reproducible evidence acquisition means: given a recorded interaction,
replay reproduces the identical recorded bytes/metadata (transport
replay) and hence the identical parsed outcome (evidence replay) —
without contacting the live provider. It does NOT mean the external
world is reproducible (live fidelity), the source persists (source
permanence), or the underlying claim stays true (scientific validity).

Layers (never conflated):
  transport replay  — same fixture → same recorded bytes/metadata;
  evidence replay   — same bytes + same parser version → same outcome;
  research replay   — same artifacts → deterministic downstream state;
  scientific validity — explicitly NOT guaranteed (world may differ).

``RecordedTransport`` wraps any ``Transport``. In record mode it
delegates to the inner transport and reports each interaction to a
caller-supplied sink (persistence lives with the sink — the transport
holds no connection, preserving SD2-03). In replay mode it serves
fixtures by deterministic fixture id and never touches the network.
Redaction happens at the record boundary: only redacted request forms
ever reach the sink or a fixture file.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from hermes.tools.providers.base import (
    RequestSpec,
    Transport,
    TransportResponse,
)
from hermes.tools.providers.redact import (
    DEFAULT_POLICY,
    RedactionPolicy,
    redact_body,
    redact_params,
    redact_url,
)
from hermes.tools.research_sources import ProviderError, ProviderValidationError

__all__ = [
    "DEFAULT_MAX_BODY_BYTES",
    "REPLAY_UNAVAILABLE",
    "SOURCE_CHANGED",
    "FixtureRecord",
    "RecordTooLargeError",
    "RecordedInteraction",
    "RecordedTransport",
    "ReplayUnavailableError",
    "SinkCallable",
    "compare_recorded",
    "dump_fixtures",
    "fixture_id_of",
    "interaction_id_of",
    "interaction_to_fixture",
    "load_fixtures",
    "normalized_request",
    "provider_resolver_for",
]

# Failure-class strings (FetchFailure.failure_class vocabulary —
# plain strings by contract, no enum change required).
REPLAY_UNAVAILABLE = "REPLAY_UNAVAILABLE"
SOURCE_CHANGED = "SOURCE_CHANGED"

# Default cap for recorded response bodies (S11 scale class — the same
# bound the fetch path enforces; larger bodies are refused loudly,
# never silently dropped).
DEFAULT_MAX_BODY_BYTES = 16 * 1024 * 1024


class ReplayUnavailableError(ProviderError):
    """No usable fixture exists for a replay-mode request (missing,
    incompatible parser version, or corrupt fixture). A transport-level
    failure by contract — drivers map it to typed outcomes."""


def normalized_request(spec: RequestSpec,
                       policy: RedactionPolicy = DEFAULT_POLICY,
                       ) -> dict[str, Any]:
    """The canonical redacted request form: redacted URL + redacted
    params (sorted by serialization). ``headers_meta`` is NEVER
    included (never-logged by contract).

    IDR-046 D4 — fixture identity with bodies: POST specs gain a
    ``"body"`` key holding the *redacted* canonical body (a credential
    can never enter a fixture id or fixture file; two POSTs differing
    anywhere in body get distinct fixture ids — otherwise one would
    replay the other's bytes). GET specs carry no ``"body"`` key, so GET
    normalized forms and GET fixture ids are byte-identical to before."""
    if not isinstance(spec.url, str) or not spec.url:
        raise ProviderError("cannot normalize a request without a URL",
                            hazard_class="MALFORMED_REQUEST",
                            recordable=False)
    params = spec.params if isinstance(spec.params, dict) else {}
    out: dict[str, Any] = {
        "url": redact_url(spec.url, policy),
        "params": redact_params(
            {str(k): str(v) for k, v in params.items()}, policy),
    }
    method = getattr(spec, "method", "GET")
    if method not in ("GET", "POST"):
        raise ProviderValidationError(
            f"unknown request method {method!r} — refusing (closed "
            f"method set: GET | POST)")
    if method == "POST":
        out["body"] = redact_body(
            spec.body if isinstance(spec.body, bytes) else spec.body,
            policy)
    return out


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def fixture_id_of(provider_id: str,
                  normalized: Mapping[str, Any]) -> str:
    """Deterministic fixture identity over provider + normalized
    request. Adapter version is intentionally EXCLUDED (it is recorded
    provenance, not identity — the same normalized interaction
    replays across adapter upgrades); parser version gates replay
    compatibility instead (§17)."""
    if not provider_id:
        raise ProviderError("fixture identity requires provider_id",
                            hazard_class="MALFORMED_REQUEST",
                            recordable=False)
    raw = _canonical_bytes({"provider_id": provider_id,
                            "request": dict(normalized)})
    return "fx_" + hashlib.sha256(raw).hexdigest()[:24]


def interaction_id_of(fixture_id: str, *, status_class: str,
                      body_hash: str | None, failure_class: str | None,
                      task_id: str | None) -> str:
    """Deterministic interaction identity: one recorded (request,
    response, task) triple. Distinct from fixture identity (which keys
    the replay corpus by request alone): retries with different
    outcomes and different tasks each own their row, while byte-
    identical replays converge on one row (idempotent persist).
    Task linkage is part of identity so per-task reads
    (``list_for_task``) are exact — shared bytes still dedupe in the
    artifact store by content hash."""
    raw = _canonical_bytes({"fixture": fixture_id, "status": status_class,
                            "body": body_hash, "failure": failure_class,
                            "task": task_id})
    return "ix_" + hashlib.sha256(raw).hexdigest()[:24]


@dataclass(frozen=True)
class RecordedInteraction:
    """One recorded provider interaction (transport-level fact).

    ``response_body`` is transient (persisted to the artifact store by
    the sink, referenced by ``response_body_hash``); ``error`` is set
    only for raised transport failures (never both body and error).
    ``task_id``/``project_id`` are execution-context provenance bound
    by the caller (a task-bound view); they are excluded from fixture
    identity and fixture files.
    """

    interaction_id: str
    provider_id: str
    adapter_version: str
    parser_version: str
    normalized_request: dict[str, Any]
    request_hash: str
    status_class: str
    response_body_hash: str | None
    outcome_kind: str
    failure_class: str | None
    retrieved_at: str
    source_url_redacted: str
    redirects: tuple[str, ...] = ()
    content_type: str | None = None
    attempt: int = 1
    task_id: str | None = None
    project_id: str | None = None


@dataclass(frozen=True)
class FixtureRecord:
    """A serializable replay fixture (fixture-file corpus unit)."""

    fixture_id: str
    provider_id: str
    adapter_version: str
    parser_version: str
    normalized_request: dict[str, Any]
    status: int | None
    body_hex: str | None
    body_hash: str | None
    headers: dict[str, str]
    content_type: str | None
    error_type: str | None
    error_message: str | None
    error_hazard_class: str | None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "provider_id": self.provider_id,
            "adapter_version": self.adapter_version,
            "parser_version": self.parser_version,
            "normalized_request": self.normalized_request,
            "status": self.status,
            "body_hex": self.body_hex,
            "body_hash": self.body_hash,
            "headers": self.headers,
            "content_type": self.content_type,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "error_hazard_class": self.error_hazard_class,
        }

    @staticmethod
    def from_mapping(data: Mapping[str, Any]) -> "FixtureRecord":
        if not isinstance(data, dict):
            raise ReplayUnavailableError(
                "corrupt fixture: not a mapping",
                hazard_class="FIXTURE_CORRUPT", recordable=False)
        required = ("fixture_id", "provider_id", "adapter_version",
                    "parser_version", "normalized_request")
        for key in required:
            if not data.get(key):
                raise ReplayUnavailableError(
                    f"corrupt fixture: missing {key!r}",
                    hazard_class="FIXTURE_CORRUPT", recordable=False)
        body_hex = data.get("body_hex")
        body_hash = data.get("body_hash")
        if body_hex is not None:
            try:
                body = bytes.fromhex(body_hex)
            except ValueError:
                raise ReplayUnavailableError(
                    "corrupt fixture: body_hex is not hex",
                    hazard_class="FIXTURE_CORRUPT", recordable=False) from None
            if (body_hash is not None and
                    hashlib.sha256(body).hexdigest() != body_hash):
                raise ReplayUnavailableError(
                    "corrupt fixture: body hash mismatch",
                    hazard_class="FIXTURE_CORRUPT", recordable=False)
        return FixtureRecord(
            fixture_id=str(data["fixture_id"]),
            provider_id=str(data["provider_id"]),
            adapter_version=str(data["adapter_version"]),
            parser_version=str(data["parser_version"]),
            normalized_request=dict(data["normalized_request"]),
            status=data.get("status"),
            body_hex=body_hex,
            body_hash=body_hash,
            headers=dict(data.get("headers") or {}),
            content_type=data.get("content_type"),
            error_type=data.get("error_type"),
            error_message=data.get("error_message"),
            error_hazard_class=data.get("error_hazard_class"))


def load_fixtures(path: str) -> dict[str, FixtureRecord]:
    """Load a fixture corpus file ``{"fixtures": [...]}`` keyed by
    fixture id. Corrupt files fail loudly (never partial loads)."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(
            data.get("fixtures"), list):
        raise ReplayUnavailableError(
            f"corrupt fixture file {path!r}: expected "
            f'{{"fixtures": [...]}}',
            hazard_class="FIXTURE_CORRUPT", recordable=False)
    out: dict[str, FixtureRecord] = {}
    for raw in data["fixtures"]:
        record = FixtureRecord.from_mapping(raw)
        out[record.fixture_id] = record
    return out


def dump_fixtures(records: list[FixtureRecord], path: str) -> None:
    """Write a fixture corpus file (test/corpus utility; deterministic
    key order)."""
    ordered = sorted(records, key=lambda r: r.fixture_id)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"fixtures": [r.to_mapping() for r in ordered]},
                  handle, sort_keys=True, indent=2, ensure_ascii=False)
        handle.write("\n")


def compare_recorded(live: TransportResponse,
                     fixture: FixtureRecord) -> bool:
    """True iff a live response matches the recorded fixture (status +
    body hash). A mismatch surfaces ``SOURCE_CHANGED`` at the caller —
    live content is never silently substituted for recorded content."""
    if fixture.error_type is not None:
        return False
    if live.status != fixture.status:
        return False
    if fixture.body_hash is None:
        return True
    return hashlib.sha256(live.body).hexdigest() == fixture.body_hash


def _status_class(status: int | None, error: BaseException | None) -> str:
    if error is not None:
        hazard = getattr(error, "hazard_class", None)
        return f"ERROR_{hazard}" if hazard else "ERROR_UNKNOWN"
    return f"HTTP_{status}"


class RecordedTransport:
    """A ``Transport`` wrapper adding record/replay (CHG-2).

    Construction is single-provider (explicit ``provider_id`` plus
    adapter/parser versions) or resolver-driven (``resolve_provider``
    maps each ``RequestSpec`` to ``(provider_id, adapter_version,
    parser_version)`` — e.g. :func:`provider_resolver_for` — for the
    shared-transport case where one transport serves many providers).
    Exactly one of the two must identify the provider; an
    unidentifiable request fails closed (``ProviderValidationError``),
    never unattributed.

    Record mode: delegates to the inner transport, builds a
    ``RecordedInteraction`` per request, and reports
    ``(interaction, body_or_None)`` to ``sink``. Bodies larger than
    ``max_body_bytes`` raise ``RecordTooLargeError`` loudly (never
    silently dropped). Recording failures propagate — a silent
    provenance gap is worse than a loud task failure.

    Replay mode: serves fixtures by deterministic fixture id from the
    in-memory corpus (as loaded by ``load_fixtures``); parser-version
    mismatch, missing, or corrupt fixtures raise
    ``ReplayUnavailableError``. The live provider is never contacted
    (verified by tests using a refusing inner transport).

    ``bound(task_id, project_id)`` returns an immutable child view
    sharing inner transport, sink, and fixtures with execution-context
    provenance fixed — the handler choke point binds per-dispatch
    context without shared mutation. The transport holds no
    connection: persistence lives with the sink (SD2-03 preserved).
    """

    def __init__(
        self,
        inner: Transport,
        *,
        provider_id: str | None = None,
        adapter_version: str | None = None,
        parser_version: str | None = None,
        clock: Any,
        mode: str = "record",
        sink: Callable[
            [RecordedInteraction, bytes | None], None] | None = None,
        fixtures: Mapping[str, FixtureRecord] | None = None,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        redaction_policy: RedactionPolicy = DEFAULT_POLICY,
        resolve_provider: Callable[
            [RequestSpec], tuple[str, str, str] | None] | None = None,
    ) -> None:
        if mode not in ("record", "replay"):
            raise ProviderError(f"unknown RecordedTransport mode {mode!r}",
                                provider_id=provider_id or "",
                                hazard_class="MALFORMED_REQUEST",
                                recordable=False)
        self._inner = inner
        self._provider_id = provider_id
        self._adapter_version = adapter_version
        self._parser_version = parser_version
        self._clock = clock
        self._mode = mode
        self._sink = sink
        self._fixtures = dict(fixtures) if fixtures else {}
        self._max_body_bytes = max_body_bytes
        self._policy = redaction_policy
        self._resolve_provider = resolve_provider
        self._task_id: str | None = None
        self._project_id: str | None = None
        self._adapter: Any | None = None
        self._retain_body = True

    @property
    def mode(self) -> str:
        return self._mode

    def bound(self, *, task_id: str | None = None,
              project_id: str | None = None,
              adapter: Any | None = None,
              retain_body: bool = True) -> "RecordedTransport":
        """Immutable child view with execution-context provenance fixed
        (handler choke-point binding — no shared mutation). The
        optional adapter is the ACTING adapter for the bound execution
        (its provider/version identity is the most specific attribution
        available — required where request URLs do not name the API,
        e.g. per-source fetch URLs).

        ``retain_body`` controls whether recorded response bodies are
        handed to the sink for artifact-store persistence. Search keeps
        it True (listing bytes would otherwise be homeless — outcomes
        store derived records, never raw listings). Fetch sets it False
        (payload bytes land as ``source_payload`` artifacts through the
        outcome write path; a second row for identical bytes would
        trip the R02 same-hash-different-type refusal). Failure
        metadata is recorded either way — only body bytes are gated.
        """
        child = RecordedTransport(
            self._inner, provider_id=self._provider_id,
            adapter_version=self._adapter_version,
            parser_version=self._parser_version, clock=self._clock,
            mode=self._mode, sink=self._sink, fixtures=self._fixtures,
            max_body_bytes=self._max_body_bytes,
            redaction_policy=self._policy,
            resolve_provider=self._resolve_provider)
        child._task_id = task_id
        child._project_id = project_id
        child._adapter = adapter
        child._retain_body = retain_body
        return child

    def _identify(self, spec: RequestSpec) -> tuple[str, str, str]:
        """Resolve (provider_id, adapter_version, parser_version) for one
        request: bound acting adapter first (most specific), then
        construction-fixed identity, then the resolver; otherwise fail
        closed (never unattributed)."""
        if self._adapter is not None:
            adapter = self._adapter
            provider_id = getattr(adapter, "provider_id", "")
            adapter_version = getattr(adapter, "adapter_version", "")
            parser_version = getattr(adapter, "parser_version", "")
            if provider_id and adapter_version and parser_version:
                return (str(provider_id), str(adapter_version),
                        str(parser_version))
            raise ProviderValidationError(
                "bound adapter lacks provider/version identity — "
                "refusing unattributed recording")
        if (self._provider_id and self._adapter_version
                and self._parser_version):
            return (self._provider_id, self._adapter_version,
                    self._parser_version)
        if self._resolve_provider is not None:
            resolved = self._resolve_provider(spec)
            if resolved is not None:
                provider_id, adapter_version, parser_version = resolved
                if provider_id and adapter_version and parser_version:
                    return provider_id, adapter_version, parser_version
        raise ProviderValidationError(
            "RecordedTransport cannot identify the provider for this "
            "request - refusing unattributed recording")

    def _fixture_for(self, spec: RequestSpec,
                     normalized: dict[str, Any]) -> FixtureRecord:
        provider_id, _, parser_version = self._identify(spec)
        fid = fixture_id_of(provider_id, normalized)
        record = self._fixtures.get(fid)
        if record is None:
            raise ReplayUnavailableError(
                f"no fixture for {fid!r} (provider "
                f"{provider_id!r})",
                provider_id=provider_id,
                hazard_class="FIXTURE_MISSING", recordable=False)
        if record.parser_version != parser_version:
            raise ReplayUnavailableError(
                f"fixture {fid!r} pins parser {record.parser_version!r}, "
                f"replay requires {parser_version!r}",
                provider_id=provider_id,
                hazard_class="FIXTURE_INCOMPATIBLE", recordable=False)
        return record

    def request(self, spec: RequestSpec) -> TransportResponse:
        normalized = normalized_request(spec, self._policy)
        if self._mode == "replay":
            return self._replay(spec, normalized)
        return self._record(spec, normalized)

    def _replay(self, spec: RequestSpec,
               normalized: dict[str, Any]) -> TransportResponse:
        record = self._fixture_for(spec, normalized)
        provider_id, _, _ = self._identify(spec)
        if record.error_type is not None:
            raise ProviderError(
                record.error_message or "recorded provider failure",
                provider_id=provider_id,
                hazard_class=record.error_hazard_class or "UNKNOWN",
                recordable=True)
        body = bytes.fromhex(record.body_hex) if record.body_hex else b""
        return TransportResponse(
            status=record.status if record.status is not None else 200,
            body=body, headers=dict(record.headers),
            content_type=record.content_type)

    def _record(self, spec: RequestSpec,
               normalized: dict[str, Any]) -> TransportResponse:
        provider_id, adapter_version, parser_version = self._identify(spec)
        fid = fixture_id_of(provider_id, normalized)
        request_hash = hashlib.sha256(
            _canonical_bytes(normalized)).hexdigest()
        try:
            response = self._inner.request(spec)
        except Exception as exc:
            interaction = RecordedInteraction(
                interaction_id=interaction_id_of(
                    fid, status_class=_status_class(None, exc),
                    body_hash=None,
                    failure_class=type(exc).__name__,
                    task_id=self._task_id),
                provider_id=provider_id,
                adapter_version=adapter_version,
                parser_version=parser_version,
                normalized_request=normalized, request_hash=request_hash,
                status_class=_status_class(None, exc),
                response_body_hash=None, outcome_kind="RECORDED_FAILURE",
                failure_class=type(exc).__name__,
                retrieved_at=self._clock.now_utc(),
                source_url_redacted=normalized["url"],
                task_id=self._task_id, project_id=self._project_id)
            if self._sink is not None:
                self._sink(interaction, None)
            raise
        if len(response.body) > self._max_body_bytes:
            raise RecordTooLargeError(
                f"recorded body {len(response.body)} bytes exceeds cap "
                f"{self._max_body_bytes} — refused loudly, never silently "
                f"dropped",
                provider_id=provider_id)
        body_hash = hashlib.sha256(response.body).hexdigest()
        interaction = RecordedInteraction(
            interaction_id=interaction_id_of(
                fid, status_class=_status_class(response.status, None),
                body_hash=body_hash, failure_class=None,
                task_id=self._task_id),
            provider_id=provider_id,
            adapter_version=adapter_version,
            parser_version=parser_version,
            normalized_request=normalized, request_hash=request_hash,
            status_class=_status_class(response.status, None),
            response_body_hash=body_hash, outcome_kind="RECORDED_SUCCESS",
            failure_class=None,
            retrieved_at=self._clock.now_utc(),
            source_url_redacted=normalized["url"],
            content_type=response.content_type,
            task_id=self._task_id, project_id=self._project_id)
        if self._sink is not None:
            # retain_body=False (fetch path) withholds bytes from the
            # sink — the outcome write path owns payload persistence;
            # the hash still identifies the bytes for fixtures/audit.
            self._sink(interaction,
                       response.body if self._retain_body else None)
        return response


def provider_resolver_for(
    adapters: Mapping[str, Any],
) -> Callable[[RequestSpec], tuple[str, str, str] | None]:
    """Build a provider resolver over adapter base URLs (shared-transport
    wiring helper): first adapter (sorted provider ids, deterministic)
    whose base URL prefixes the request URL wins, yielding
    ``(provider_id, adapter_version, parser_version)``; no match yields
    None (the transport then fails closed)."""

    def _resolve(spec: RequestSpec) -> tuple[str, str, str] | None:
        url = spec.url if isinstance(spec.url, str) else ""
        for provider_id in sorted(adapters):
            adapter = adapters[provider_id]
            base_url = getattr(adapter, "base_url", "")
            if base_url and url.startswith(base_url):
                return (provider_id,
                        str(getattr(adapter, "adapter_version", "1")),
                        str(getattr(adapter, "parser_version", "1")))
        return None

    return _resolve


class RecordTooLargeError(ProviderError):
    """A recorded body exceeds the recording cap — refused loudly so no
    silent provenance gap can form."""


def interaction_to_fixture(
    interaction: RecordedInteraction, body: bytes | None,
    headers: dict[str, str] | None = None,
    status: int | None = None,
    error_message: str | None = None,
) -> FixtureRecord:
    """Build a replay fixture from a recorded interaction (corpus
    authoring helper; deterministic). The fixture id is recomputed
    from provider + normalized request (never copied from the
    interaction id, which additionally binds response and task)."""
    body_hex = body.hex() if body is not None else None
    return FixtureRecord(
        fixture_id=fixture_id_of(interaction.provider_id,
                                 interaction.normalized_request),
        provider_id=interaction.provider_id,
        adapter_version=interaction.adapter_version,
        parser_version=interaction.parser_version,
        normalized_request=dict(interaction.normalized_request),
        status=status, body_hex=body_hex,
        body_hash=interaction.response_body_hash,
        headers=dict(headers or {}),
        content_type=interaction.content_type,
        error_type=("RECORDED_FAILURE"
                    if interaction.outcome_kind == "RECORDED_FAILURE"
                    else None),
        error_message=error_message,
        error_hazard_class=None)


#: Sink signature: persists one interaction (+ optional body bytes).
SinkCallable = Callable[[RecordedInteraction, bytes | None], None]
