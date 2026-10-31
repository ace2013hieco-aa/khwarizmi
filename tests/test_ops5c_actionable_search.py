"""OPS-5C — a search is actionable without its rows entering the prompt.

What this file proves, against the REAL shipped chain (RecordedTransport ->
allowlist -> host pin -> a scripted HTTP edge; no network):

1. a successful search derives a content handle, states the delivered count,
   the omitted count and the handle in its bounded detail, and returns no
   artifact;
2. ``source_fetch(provider, search_handle, row_index)`` selects the snapshot
   row, runs the same fetch chain and writes the same ``source_payload`` row
   the OPS-5B writer writes — with the *choice* (handle, 0-based index, row
   hash) in its metadata — and ``EVIDENCE_REF`` accepts it;
3. the rendered feedback detail and envelope contain no title, URL, result id
   or row content hash (distinct sentinel strings);
4. ``(handle, i)`` resolves to the same row on every call, a repeated search
   derives the same handle, and a different index selects the corresponding
   row;
5. an out-of-range index, an expired/absent handle, a provider mismatch, an
   ambiguous target, a missing target and a malformed handle each return a
   benign REFUSED tool result with its named code: no dial, no artifact, no
   journal row;
6. the generated prompt note states the two target forms, the 0-based index,
   the provider's relevance order (row 0 is the top-ranked result) and the
   handle's transient status, and the note follows the registry declaration.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass, replace
from typing import Any, cast

import pytest

from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import TOOL_CALL_KEYS, AgentRuntime
from hermes.agents.runtime.types import RunLimits, TaskContext
from hermes.artifacts.store import ArtifactStore
from hermes.composition import (
    build_capability_tool_notes,
    plan_capability_plane,
)
from hermes.core.intents import Intent, IntentKind
from hermes.eval.loop_observations import RecordingCapabilityPort
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
)
from hermes.research.capability_supply import (
    FETCH_TARGET_AMBIGUOUS,
    FETCH_TARGET_MISSING,
    RESEARCH_EGRESS_TOOL_SET_ID,
    SEARCH_HANDLE_EXPIRED,
    SEARCH_HANDLE_INVALID,
    SEARCH_HANDLE_PREFIX,
    SEARCH_PROVIDER_MISMATCH,
    SEARCH_ROW_INDEX_OUT_OF_RANGE,
    SUPPLIED_CAPABILITY_IDS,
    SearchHandleCollision,
    SearchResultRegistry,
    SearchSelectionRefusal,
    build_research_egress_supply,
    search_handle_of,
    supplied_capability_risks,
)
from hermes.research.gateway import apply_intent
from hermes.research.live_fetch import (
    ALLOWLIST_HOSTS,
    build_live_fetch_wiring,
)
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.types import (
    IN_PROCESS_ENVIRONMENT,
    Capability,
    CapabilityKind,
    InputField,
    InvokeRequest,
    Observation,
    RiskLevel,
    Tool,
    ToolGrant,
    ToolSet,
)
from hermes.tools.models.router import ModelProposal
from hermes.tools.providers.base import TransportResponse

CLOCK = "2026-10-25T12:00:00.000000+00:00"
PROJECT = "p1"
PROFILE = "RESEARCHER"
TOPIC = "CRISPR delivery"

#: Distinctive row text. Every sentinel below must be absent from the prompt.
TITLES = (
    "OPS5C-SENTINEL-TITLE-ALPHA a distinctive first hit",
    "OPS5C-SENTINEL-TITLE-BRAVO a distinctive second hit",
    "OPS5C-SENTINEL-TITLE-CHARLIE a distinctive third hit",
)
URLS = (
    "https://openalex.org/W900000001",
    "https://openalex.org/W900000002",
    "https://openalex.org/W900000003",
)
DOIS = (
    "https://doi.org/10.5555/ops5c.alpha",
    "https://doi.org/10.5555/ops5c.bravo",
    "https://doi.org/10.5555/ops5c.charlie",
)
SEARCH_TOTAL = 41
FETCH_BODY = b"OPS5C-FETCHED-FULLTEXT - the fetched payload bytes\n"
FETCH_BODY_HASH = hashlib.sha256(FETCH_BODY).hexdigest()
EMPTY_TOPIC = "OPS5C-EMPTY-RESULT-TOPIC"


class Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 1000.0

    def sleep(self, delay: float) -> None:
        return None


def _public_resolve(host: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


def _search_body() -> bytes:
    document = {
        "total": SEARCH_TOTAL,
        "meta": {"count": SEARCH_TOTAL},
        "results": [
            {"id": url, "doi": doi, "title": title,
             "publication_year": 2020 + index}
            for index, (url, doi, title) in enumerate(
                zip(URLS, DOIS, TITLES, strict=True))
        ],
    }
    return json.dumps(document).encode("utf-8")


def _empty_body() -> bytes:
    return json.dumps({"total": 0, "meta": {"count": 0},
                       "results": []}).encode("utf-8")


SEARCH_BODY = _search_body()


@dataclass
class Rig:
    conn: Any
    store: ArtifactStore
    supply: Any
    invoker: CapabilityInvoker
    calls: list[Any]

    def call(self, capability_id: str, arguments: dict[str, Any],
             key: str) -> Observation:
        result = self.invoker.invoke(InvokeRequest(
            capability_id=capability_id,
            arguments=arguments,
            idempotency_key=key,
            lease_generation="lease-gen-7",
            profile=PROFILE,
            rationale="the brief asks for an admitted source",
            grant=ToolGrant(
                grant_id="grant.live.researcher",
                profile=PROFILE,
                tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID}),
                max_risk=RiskLevel.MEDIUM.value)))
        assert isinstance(result, Observation), result
        return result

    def search(self, key: str = "idem-search",
               topic: str = TOPIC) -> Observation:
        return self.call(
            "source_search",
            {"provider": "openalex", "topic": topic, "max_results": 3},
            key)

    def fetch(self, arguments: dict[str, Any],
              key: str = "idem-fetch") -> Observation:
        return self.call("source_fetch", arguments, key)


@pytest.fixture
def conn():
    connection = connect(":memory:")
    migrate_to_latest(connection)
    ProjectRepository(connection, lambda: CLOCK).create(PROJECT, "OPS-5C")
    yield connection
    connection.close()


@pytest.fixture
def store(conn, tmp_path):
    return ArtifactStore(
        str(tmp_path / "store"),
        ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)


@pytest.fixture
def rig(conn, store, monkeypatch):
    wiring = build_live_fetch_wiring(
        conn, store, lambda: CLOCK, dns_resolve=_public_resolve)
    calls: list[Any] = []

    def scripted(spec):
        calls.append(spec)
        path = urllib.parse.urlsplit(spec.url).path
        if path == "/works":
            if spec.params.get("search") == EMPTY_TOPIC:
                return TransportResponse(
                    status=200, body=_empty_body(), headers={},
                    content_type="application/json")
            return TransportResponse(
                status=200, body=SEARCH_BODY, headers={},
                content_type="application/json")
        return TransportResponse(
            status=200, body=FETCH_BODY, headers={},
            content_type="text/plain")

    monkeypatch.setattr(wiring.http_transport, "request", scripted)
    machinery = replace(wiring.machinery, clock=Clock())
    supply = build_research_egress_supply(
        conn=conn, store=store, clock=lambda: CLOCK, project_id=PROJECT,
        machinery=machinery, allowlist=ALLOWLIST_HOSTS,
        dns_resolve=_public_resolve)
    invoker = CapabilityInvoker(
        registry=supply.registry,
        implementations=supply.implementations,
        clock=Clock(),
        ledger=InMemoryIdempotencyLedger(),
        sandbox_enabled=False)
    return Rig(conn=conn, store=store, supply=supply, invoker=invoker,
               calls=calls)


def _detail(observation: Observation) -> str:
    assert observation.payload is not None
    return observation.detail


def _payload(observation: Observation) -> dict[str, Any]:
    assert observation.payload is not None
    return json.loads(observation.payload.text)


def _handle_from(detail: str) -> str:
    match = re.search(rf"{SEARCH_HANDLE_PREFIX}[0-9a-f]{{64}}", detail)
    assert match is not None, detail
    return match.group(0)


def _artifact_rows(conn, artifact_type: str = "source_payload"
                   ) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM artifacts WHERE artifact_type = ? AND project_id = ?",
        (artifact_type, PROJECT))]


def _journal_rows(conn) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM provider_interactions ORDER BY interaction_id")]


def _rows_of(rig: Rig, handle: str) -> tuple[Any, ...]:
    """Resolve 0..N-1 until the registry refuses; the delivered tuple."""
    registry: SearchResultRegistry = rig.supply.search_registry
    rows: list[Any] = []
    for index in range(25):
        try:
            rows.append(registry.resolve(handle, "openalex", index))
        except SearchSelectionRefusal:
            break
    return tuple(rows)


# ═══════════════ the search detail ═══════════════


def test_a_search_returns_a_handle_and_a_ranked_count_in_its_bounded_detail(
        rig) -> None:
    observation = rig.search()
    assert observation.ok(), observation.detail
    assert observation.artifacts == (), "a search is not an artifact (R7)"
    detail = _detail(observation)
    assert detail.startswith("search openalex: 3 source row(s) (COMPLETE)")
    assert "rows=3" in detail
    assert "omitted=38" in detail
    assert "omitted_is_estimate" not in detail
    handle = _handle_from(detail)
    assert handle.startswith(SEARCH_HANDLE_PREFIX)
    assert len(handle) == len(SEARCH_HANDLE_PREFIX) + 64
    # The preimage is the delivered rows, in the delivered order: pin it here
    # so a re-sort or a normalisation would fail this test. The encoding must
    # preserve list order — `programs.canonical_json` sorts lists of dicts
    # (fine for derived sets, wrong for a ranking), so it is not used.
    payload = _payload(observation)
    expected = SEARCH_HANDLE_PREFIX + hashlib.sha256(json.dumps({
        "provider": "openalex",
        "rows": [
            {
                "result_id": row["result_id"],
                "content_hash": row["content_hash"],
                "source_url": row["source_url"],
            }
            for row in payload["rows"]
        ],
    }, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert handle == expected
    assert [row["source_url"] for row in payload["rows"]] == list(URLS)
    # One journal row for the one recorded search request.
    assert len(rig.calls) == 1
    assert len(_journal_rows(rig.conn)) == 1
    assert _artifact_rows(rig.conn) == []


def test_an_empty_search_issues_no_handle(rig) -> None:
    observation = rig.search(key="idem-empty", topic=EMPTY_TOPIC)
    assert observation.ok(), observation.detail
    detail = _detail(observation)
    assert "search_handle=none" in detail
    assert "rows=0" in detail
    assert "omitted=unknown" in detail
    assert re.search(rf"{SEARCH_HANDLE_PREFIX}[0-9a-f]{{64}}", detail) is None
    assert len(rig.supply.search_registry) == 0


def test_the_handle_preimage_is_the_delivered_order_and_a_different_order_differs(
        rig) -> None:
    observation = rig.search()
    handle = _handle_from(_detail(observation))
    rows = _rows_of(rig, handle)
    assert search_handle_of("openalex", rows) == handle
    reversed_handle = search_handle_of("openalex", tuple(reversed(rows)))
    assert reversed_handle != handle
    assert search_handle_of("pubmed", rows) != handle


def test_the_estimate_marker_is_stated_only_with_a_reported_total(rig) -> None:
    from hermes.research.capability_supply import _search_result
    from hermes.tools.research_sources import SearchOutcome

    rows = _rows_of(rig, _handle_from(_detail(rig.search())))
    estimated = tuple(replace(row, total_count=100, total_is_estimate=True)
                      for row in rows)
    note = _search_result(
        "openalex",
        SearchOutcome(per_provider=estimated, aggregate="COMPLETE", notes=(),
                      request_log=None),
        SearchResultRegistry()).notes[0]
    assert "omitted=97" in note
    assert "omitted_is_estimate=true" in note
    unknown = tuple(replace(row, total_count=None, total_is_estimate=True)
                    for row in rows)
    unknown_note = _search_result(
        "openalex",
        SearchOutcome(per_provider=unknown, aggregate="COMPLETE", notes=(),
                      request_log=None),
        SearchResultRegistry()).notes[0]
    assert "omitted=unknown" in unknown_note
    assert "omitted_is_estimate" not in unknown_note


# ═══════════════ the actionable fetch ═══════════════


def test_fetch_by_handle0_writes_a_citable_artifact_with_the_choice_in_metadata(
        rig) -> None:
    search = rig.search()
    handle = _handle_from(_detail(search))
    rows = _rows_of(rig, handle)
    observation = rig.fetch(
        {"provider": "openalex", "search_handle": handle, "row_index": 0},
        key="idem-fetch-0")
    assert observation.ok(), observation.detail
    payload = _payload(observation)
    assert payload["status"] == "FETCHED"
    assert payload["url"] == rows[0].source_url
    assert payload["search_handle"] == handle
    assert payload["row_index"] == 0
    assert payload["search_result_hash"] == rows[0].content_hash
    assert payload["content_hash"] == FETCH_BODY_HASH
    assert observation.artifacts == (
        f"evidence/{FETCH_BODY_HASH}", f"source_payload/{FETCH_BODY_HASH}")
    # The dial was the row's own URL, host-rewritten to the provider's API
    # surface by the shipped adapter (path preserved).
    assert rig.calls[-1].url == "https://api.openalex.org/W900000001"
    artifacts = _artifact_rows(rig.conn)
    assert len(artifacts) == 1
    row = artifacts[0]
    assert row["artifact_id"] == FETCH_BODY_HASH
    assert row["content_hash"] == FETCH_BODY_HASH
    assert row["task_id"] is None
    metadata = json.loads(row["metadata_json"])
    assert metadata["search_handle"] == handle
    assert metadata["row_index"] == 0
    assert metadata["search_result_hash"] == rows[0].content_hash
    assert metadata["source_url_redacted"] == (
        "https://api.openalex.org/W900000001")
    assert metadata["provider"] == "openalex"
    assert rig.store.read_verified(FETCH_BODY_HASH) == FETCH_BODY
    # The fetched artifact is the citation; the search handle is not.
    result = apply_intent(rig.conn, Intent(
        kind=IntentKind.EVIDENCE_TRANSITION,
        proposed_by=PROFILE, project_id=PROJECT,
        payload={
            "evidence_artifact_ref": f"evidence:{payload['artifact_id']}",
            "from_state": "SUPPORTED",
            "to_state": "ROBUST",
            "rationale": "the provider's top-ranked hit supports the rung",
        }))
    assert result.entity_id
    assert rig.conn.execute(
        "SELECT 1 FROM events WHERE event_type = ?",
        ("EvidenceTransitionProposed",)).fetchone() is not None
    # The handle itself is not a citation form: EVIDENCE_REF refuses it.
    from hermes.research.gateway import GatewayRejection
    with pytest.raises(GatewayRejection) as rejected:
        apply_intent(rig.conn, Intent(
            kind=IntentKind.EVIDENCE_TRANSITION,
            proposed_by=PROFILE, project_id=PROJECT,
            payload={
                "evidence_artifact_ref": f"evidence:{handle}",
                "from_state": "SUPPORTED",
                "to_state": "ROBUST",
                "rationale": "the transient handle is not an artifact",
            }))
    assert rejected.value.code == "EVIDENCE_REF"


def test_the_index_selects_its_own_row_and_repeats_are_stable(rig) -> None:
    first = _handle_from(_detail(rig.search(key="idem-search-a")))
    second = _handle_from(_detail(rig.search(key="idem-search-b")))
    assert first == second, "an identical search must derive the same handle"
    assert len(rig.supply.search_registry) == 1
    rows = _rows_of(rig, first)
    assert len(rows) == 3
    one_a = rig.fetch(
        {"provider": "openalex", "search_handle": first, "row_index": 1},
        key="idem-row1-a")
    one_b = rig.fetch(
        {"provider": "openalex", "search_handle": first, "row_index": 1},
        key="idem-row1-b")
    payload_a = _payload(one_a)
    payload_b = _payload(one_b)
    assert payload_a["url"] == rows[1].source_url
    assert payload_a["search_result_hash"] == rows[1].content_hash
    assert payload_b["url"] == payload_a["url"]
    assert payload_b["search_result_hash"] == payload_a["search_result_hash"]
    assert payload_b["artifact_id"] == payload_a["artifact_id"]
    assert one_a.artifacts == one_b.artifacts
    assert len(_artifact_rows(rig.conn)) == 1, "the same bytes dedup"
    zero = rig.fetch(
        {"provider": "openalex", "search_handle": first, "row_index": 0},
        key="idem-row0")
    assert _payload(zero)["url"] == rows[0].source_url
    assert _payload(zero)["search_result_hash"] != rows[1].content_hash


# ═══════════════ the content-absence pin ═══════════════


class _SearchFetchCite:
    """Tick 1 searches; tick 2 fetches the top-ranked row; tick 3 cites it.

    The handle is read from the previous tick's rendered feedback envelope —
    exactly what the model was shown — not from the supply's registry.
    """

    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.search_detail = ""
        self.search_envelope: dict[str, Any] = {}
        self.fetch_envelope: dict[str, Any] = {}

    @staticmethod
    def _observations(request: Any) -> list[dict[str, Any]]:
        observed: list[dict[str, Any]] = []
        for part in request.prompt:
            if part.origin != "runtime.observation":
                continue
            try:
                document = json.loads(part.text)
            except ValueError:
                continue
            if isinstance(document, dict):
                observed.append(document)
        return observed

    def invoke(self, request: Any) -> ModelProposal:
        self.requests.append(request)
        if any(part.origin == "runtime.review" for part in request.prompt):
            return ModelProposal(
                provider_id="script", model_id="script", tier="m",
                profile=request.profile,
                lease_generation=request.lease_generation,
                structured={"rationale": "nothing to object to"})
        observed = self._observations(request)
        searched = [item for item in observed
                    if item.get("capability_id") == "source_search"]
        fetched = [item for item in observed
                   if item.get("capability_id") == "source_fetch"]
        if fetched:
            envelope = fetched[-1]
            self.fetch_envelope = envelope
            artifact = next(
                handle.split("/", 1)[1] for handle in envelope["artifacts"]
                if handle.startswith("evidence/"))
            structured: dict[str, Any] = {
                "kind": "EVIDENCE_TRANSITION",
                "rationale": "cite the row fetched last tick",
                "payload": {
                    "evidence_artifact_ref": f"evidence:{artifact}",
                    "from_state": "SUPPORTED",
                    "to_state": "ROBUST",
                    "rationale": "the provider's top-ranked hit supports it",
                },
            }
        elif searched:
            envelope = searched[-1]
            self.search_envelope = envelope
            self.search_detail = str(envelope.get("detail", ""))
            detail = self.search_detail
            handle = re.search(
                rf"{SEARCH_HANDLE_PREFIX}[0-9a-f]{{64}}", detail)
            assert handle is not None, detail
            structured = {"tool_calls": [{
                "capability_id": "source_fetch",
                "arguments": {
                    "provider": "openalex",
                    "search_handle": handle.group(0),
                    "row_index": 0,
                },
                "rationale": "fetch the provider's top-ranked result",
            }]}
        else:
            structured = {"tool_calls": [{
                "capability_id": "source_search",
                "arguments": {"provider": "openalex", "topic": TOPIC,
                              "max_results": 3},
                "rationale": "start from the provider's ranking",
            }]}
        return ModelProposal(
            provider_id="script", model_id="script", tier="m",
            profile=request.profile,
            lease_generation=request.lease_generation,
            structured=structured)


def test_the_live_shaped_run_never_puts_a_row_into_the_prompt(rig) -> None:
    plan = plan_capability_plane(
        load_profiles(), supplied=SUPPLIED_CAPABILITY_IDS,
        risks=supplied_capability_risks())
    model = _SearchFetchCite()
    capabilities = RecordingCapabilityPort(rig.invoker)
    runtime = AgentRuntime(
        model=model,
        orchestration=lambda intent: apply_intent(rig.conn, intent),
        capabilities=capabilities,
        profiles=plan.profiles,
        grants=plan.grants,
    )
    result = runtime.run("researcher", TaskContext(
        task_id="t1", project_id=PROJECT, lease_generation="gen",
        limits=RunLimits(max_ticks=4, max_tool_calls=2)))
    assert result.state == "SUCCEEDED", (
        result.state, result.termination,
        [refusal.detail for refusal in result.refusals])
    evidence = [proposal for proposal in result.proposals
                if proposal.intent.kind is IntentKind.EVIDENCE_TRANSITION]
    assert len(evidence) == 1
    assert evidence[0].admission == "ADMITTED"
    assert len(capabilities.calls) == 2
    # The model acted only from what it was shown.
    assert model.search_detail.startswith(
        "search openalex: 3 source row(s) (COMPLETE)")
    handle = _handle_from(model.search_detail)
    rows = _rows_of(rig, handle)
    assert len(rows) == 3
    # The rendered feedback carries the payload's size and digest, not its text.
    envelope = model.search_envelope
    digest = str(envelope["payload_digest"])
    assert re.fullmatch(r"[0-9a-f]{64}", digest) is not None
    assert int(envelope["payload_bytes"]) > 0
    assert envelope["artifacts"] == []
    # The sentinel pin: no row title, URL, result id or content hash appears
    # in any prompt this run built (detail, envelope, system guidance, all).
    prompt_text = "\n".join(part.text for request in model.requests
                            for part in request.prompt)
    for row in rows:
        assert row.title not in prompt_text
        assert row.source_url not in prompt_text
        assert row.result_id not in prompt_text
        assert row.content_hash not in prompt_text
    for sentinel in (*TITLES, *URLS):
        assert sentinel not in prompt_text
    assert "search_handle=" in prompt_text
    assert "rows=3" in prompt_text


# ═══════════════ the six named refusals ═══════════════


def test_an_expired_handle_refuses_and_selects_no_other_row(rig) -> None:
    handle = _handle_from(_detail(rig.search()))
    rows = _rows_of(rig, handle)
    journal_before = len(_journal_rows(rig.conn))
    calls_before = len(rig.calls)
    # Fill the bounded registry until the original snapshot is evicted
    # (capacity 32; each donor is a different row identity).
    registry = rig.supply.search_registry
    for index in range(32):
        donor = replace(rows[0], result_id=f"sr_{index:024x}")
        registry.register("openalex", (donor,))
    observation = rig.fetch(
        {"provider": "openalex", "search_handle": handle, "row_index": 0},
        key="idem-expired")
    assert observation.ok(), "a selection refusal is data, not TOOL_FAILED"
    payload = _payload(observation)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == SEARCH_HANDLE_EXPIRED
    assert observation.artifacts == ()
    assert len(rig.calls) == calls_before
    assert len(_journal_rows(rig.conn)) == journal_before
    assert _artifact_rows(rig.conn) == []


def test_a_malformed_handle_refuses(rig) -> None:
    observation = rig.fetch(
        {"provider": "openalex", "search_handle": "search_not-hex",
         "row_index": 0},
        key="idem-invalid")
    payload = _payload(observation)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == SEARCH_HANDLE_INVALID
    assert observation.artifacts == ()
    assert rig.calls == []


def test_a_provider_mismatch_refuses_without_a_dial(rig) -> None:
    handle = _handle_from(_detail(rig.search()))
    calls_before = len(rig.calls)
    journal_before = len(_journal_rows(rig.conn))
    observation = rig.fetch(
        {"provider": "pubmed", "search_handle": handle, "row_index": 0},
        key="idem-mismatch")
    payload = _payload(observation)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == SEARCH_PROVIDER_MISMATCH
    assert observation.artifacts == ()
    assert len(rig.calls) == calls_before
    assert len(_journal_rows(rig.conn)) == journal_before
    assert _artifact_rows(rig.conn) == []


def test_an_ambiguous_target_refuses_without_a_dial(rig) -> None:
    handle = _handle_from(_detail(rig.search()))
    calls_before = len(rig.calls)
    observation = rig.fetch(
        {"provider": "openalex", "url": URLS[0], "search_handle": handle,
         "row_index": 0},
        key="idem-ambiguous")
    payload = _payload(observation)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == FETCH_TARGET_AMBIGUOUS
    assert observation.artifacts == ()
    assert len(rig.calls) == calls_before
    assert _artifact_rows(rig.conn) == []


def test_a_missing_target_refuses_without_a_dial(rig) -> None:
    calls_before = len(rig.calls)
    observation = rig.fetch({"provider": "openalex"}, key="idem-missing")
    payload = _payload(observation)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == FETCH_TARGET_MISSING
    assert observation.artifacts == ()
    assert len(rig.calls) == calls_before


def test_a_half_named_handle_target_refuses_as_missing(rig) -> None:
    handle = _handle_from(_detail(rig.search()))
    calls_before = len(rig.calls)
    observation = rig.fetch(
        {"provider": "openalex", "search_handle": handle},
        key="idem-half")
    payload = _payload(observation)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == FETCH_TARGET_MISSING
    assert observation.artifacts == ()
    assert len(rig.calls) == calls_before


# ═══════════════ the registry's own invariant ═══════════════


def test_out_of_range_and_non_integer_indices_are_named(rig) -> None:
    handle = _handle_from(_detail(rig.search()))
    calls_before = len(rig.calls)
    journal_before = len(_journal_rows(rig.conn))
    for index in (3, -1, 99):
        observation = rig.fetch(
            {"provider": "openalex", "search_handle": handle,
             "row_index": index},
            key=f"idem-range-{index}")
        payload = _payload(observation)
        assert payload["status"] == "REFUSED"
        assert payload["code"] == SEARCH_ROW_INDEX_OUT_OF_RANGE
        assert observation.artifacts == ()
    assert len(rig.calls) == calls_before
    assert len(_journal_rows(rig.conn)) == journal_before
    assert _artifact_rows(rig.conn) == []
    registry = rig.supply.search_registry
    with pytest.raises(SearchSelectionRefusal) as refused:
        registry.resolve(handle, "openalex", True)
    assert refused.value.code == SEARCH_ROW_INDEX_OUT_OF_RANGE
    with pytest.raises(SearchSelectionRefusal) as refused_str:
        registry.resolve(handle, "openalex", cast(Any, "0"))
    assert refused_str.value.code == SEARCH_ROW_INDEX_OUT_OF_RANGE


def test_eviction_is_oldest_first_and_bounded(rig) -> None:
    handle = _handle_from(_detail(rig.search()))
    rows = _rows_of(rig, handle)
    registry = SearchResultRegistry(capacity=2)
    first = registry.register("openalex", (rows[0],))
    second = registry.register("openalex", (rows[1],))
    assert len(registry) == 2
    third = registry.register("openalex", (rows[2],))
    assert len(registry) == 2
    with pytest.raises(Exception) as expired:
        registry.resolve(first, "openalex", 0)
    assert getattr(expired.value, "code", "") == SEARCH_HANDLE_EXPIRED
    assert registry.resolve(second, "openalex", 0).source_url == rows[1].source_url
    assert registry.resolve(third, "openalex", 0).source_url == rows[2].source_url


def test_a_repeated_search_keeps_the_original_tuple(rig) -> None:
    handle = _handle_from(_detail(rig.search(key="idem-t1")))
    registry = rig.supply.search_registry
    original = registry.resolve(handle, "openalex", 0)
    # Same identity, later retrieval timestamp and page metadata: not a
    # collision, and the registered tuple is not replaced.
    retimed = tuple(replace(row, access_timestamp_utc="2026-10-26T00:00:00+00:00")
                    for row in _rows_of(rig, handle))
    assert registry.register("openalex", retimed) == handle
    assert registry.resolve(handle, "openalex", 0) is original


def test_a_handle_collision_is_refused_never_remapped(rig, monkeypatch) -> None:
    import hermes.research.capability_supply as supply_module
    real_handle = _handle_from(_detail(rig.search()))
    rows = _rows_of(rig, real_handle)
    registry = rig.supply.search_registry
    forced = "search_" + "0" * 64
    monkeypatch.setattr(
        supply_module, "search_handle_of",
        lambda provider, delivered: forced)
    assert registry.register("openalex", (rows[0],)) == forced
    with pytest.raises(SearchHandleCollision) as collision:
        registry.register("openalex", (rows[1],))
    assert collision.value.code == "SEARCH_HANDLE_COLLISION"
    # The original handle still names its own tuple; nothing was remapped.
    monkeypatch.undo()
    assert registry.resolve(real_handle, "openalex", 0).source_url == (
        rows[0].source_url)


# ═══════════════ the generated prompt note ═══════════════


def test_the_generated_note_states_the_ranked_order_and_the_two_forms(rig) -> None:
    plan = plan_capability_plane(
        load_profiles(), supplied=SUPPLIED_CAPABILITY_IDS,
        risks=supplied_capability_risks())
    note = build_capability_tool_notes(
        plan, rig.supply, item_keys=TOOL_CALL_KEYS)["researcher"]
    assert "source_fetch(provider: string, one of" in note
    assert "url?: string" in note
    assert "search_handle?: string" in note
    assert "row_index?: integer" in note
    assert "exactly one target form" in note
    assert "0-based" in note
    assert "provider's relevance order" in note
    assert "row_index 0 is the provider's top-ranked result" in note
    assert "transient locator" in note
    assert "never a citation" in note
    critic = build_capability_tool_notes(
        plan, rig.supply, item_keys=TOOL_CALL_KEYS)["critic"]
    assert "relevance order" not in critic


class _SupplyWith:
    def __init__(self, registry: Any) -> None:
        self.registry = registry


def _fake_fetch_registry(*, summary: str, fields: tuple[str, ...]
                         ) -> _SupplyWith:
    from hermes.tools.capabilities.registry import CapabilityRegistry

    registry = CapabilityRegistry(allowlist=frozenset({"source_fetch"}))
    inputs = [InputField(name="provider", type="string",
                         allowed_values=frozenset({"openalex", "pubmed"}))]
    for name in fields:
        inputs.append(InputField(
            name=name, type="integer" if name == "row_index" else "string",
            required=False))
    registry.register_tool(Tool(
        tool_id="source_fetch", summary=summary, inputs=tuple(inputs),
        risk=RiskLevel.MEDIUM, network=True, sandboxed=False,
        environment=IN_PROCESS_ENVIRONMENT))
    registry.register_capability(Capability(
        capability_id="source_fetch", tool_id="source_fetch",
        kind=CapabilityKind.TOOL, risk=RiskLevel.MEDIUM))
    registry.register_tool_set(ToolSet(
        set_id=RESEARCH_EGRESS_TOOL_SET_ID,
        capability_ids=("source_fetch",)))
    return _SupplyWith(registry)


def test_the_generated_note_follows_the_fetch_declaration() -> None:
    plan = plan_capability_plane(
        load_profiles(), supplied=("source_fetch",),
        risks={"source_fetch": "MEDIUM"})
    complete = build_capability_tool_notes(
        plan, _fake_fetch_registry(
            summary="FIRST FETCH SUMMARY",
            fields=("url", "search_handle", "row_index")),
        item_keys=TOOL_CALL_KEYS)["researcher"]
    changed = build_capability_tool_notes(
        plan, _fake_fetch_registry(
            summary="SECOND FETCH SUMMARY",
            fields=("url", "search_handle", "row_index")),
        item_keys=TOOL_CALL_KEYS)["researcher"]
    assert "FIRST FETCH SUMMARY" in complete
    assert "SECOND FETCH SUMMARY" not in complete
    assert "SECOND FETCH SUMMARY" in changed
    assert "relevance order" in complete
    # A declaration without the handle/index fields cannot honestly state
    # the rule: the note follows the schema instead of hand-typing it.
    partial = build_capability_tool_notes(
        plan, _fake_fetch_registry(summary="URL ONLY", fields=("url",)),
        item_keys=TOOL_CALL_KEYS)["researcher"]
    assert "url?: string" in partial
    assert "search_handle" not in partial
    assert "relevance order" not in partial
