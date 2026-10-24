"""OPS-5A — the two research-egress capabilities and their journal discipline.

What this file proves, against the REAL shipped chain (RecordedTransport →
allowlist gate → host pin → a scripted HTTP transport; no live network):

1. `source_search` returns admitted source rows parsed from recorded provider
   bytes, through one bounded walk;
2. `source_fetch` fetches an allowlisted URL through the same chain, with the
   adapter's canonical-URL rewrite applied before the dial;
3. a host outside the code-owned allowlist refuses BEFORE a dial and is
   journaled with the host and the rule's named code — no body, no secret
   query value;
4. the journal row (the existing `provider_interactions` sink) carries refs
   and digests only — never the fetched body — for success and refusal alike;
5. the supplied declarations are coherent: exactly `source_search` and
   `source_fetch`, TOOL kind, in-process (`sandboxed=False` +
   `IN_PROCESS_ENVIRONMENT`), every registered tool has an executor, and the
   registry's allowlist drift is empty.

The provider bytes are the recorded P-AUTO-3 OpenAlex fixture (a real captured
response), served by a scripted inner transport. No test here contacts the
network.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from hermes.artifacts.store import ArtifactStore
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
from hermes.research.capability_supply import (
    REFUSAL_OUTCOME_KIND,
    RESEARCH_EGRESS_TOOL_SET_ID,
    SUPPLIED_CAPABILITY_IDS,
    build_research_egress_supply,
)
from hermes.research.live_fetch import ALLOWLIST_HOSTS, build_live_fetch_wiring
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.types import (
    IN_PROCESS_ENVIRONMENT,
    CapabilityKind,
    FailureKind,
    InvokeRequest,
    Observation,
    RiskLevel,
    ToolGrant,
)
from hermes.tools.providers.base import TransportResponse

CLOCK = "2026-10-24T12:00:00.000000+00:00"
PROJECT = "p1"
PROFILE = "RESEARCHER"
FIXTURE = (Path(__file__).resolve().parent / "fixtures" / "p_auto_3_live"
           / "openalex.json")

SEARCH_BODY_MARKER = "OPS5A-SEARCH-BODY-MARKER"
FETCH_BODY_MARKER = "OPS5A-FETCH-BODY-MARKER"
SECRET_QUERY_VALUE = "OPS5A-SECRET-QUERY-VALUE"

FETCH_BODY = (b"Curated full text about CRISPR systems.\n"
              + FETCH_BODY_MARKER.encode("ascii"))


class Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 1000.0

    def sleep(self, delay: float) -> None:
        return None


def _public_resolve(host: str) -> tuple[str, ...]:
    """Hermetic DNS stub: one public address, no real resolution."""
    return ("93.184.216.34",)


def _load_search_body() -> bytes:
    """The recorded OpenAlex search response, with a body-only marker.

    The marker exists so the journal assertion can prove the response BODY is
    absent from the row: it appears nowhere else in the request/row.
    """
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = json.loads(bytes.fromhex(
        document["fixtures"][0]["body_hex"]).decode("utf-8"))
    payload["ops5a_marker"] = SEARCH_BODY_MARKER
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


SEARCH_BODY = _load_search_body()


@pytest.fixture
def conn():
    connection = connect(":memory:")
    migrate_to_latest(connection)
    ProjectRepository(connection, lambda: CLOCK).create(PROJECT, "OPS-5A")
    yield connection
    connection.close()


@pytest.fixture
def store(conn, tmp_path):
    return ArtifactStore(
        str(tmp_path / "store"),
        ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)


@dataclass
class Rig:
    conn: Any
    supply: Any
    invoker: CapabilityInvoker
    calls: list[Any]

    def call(self, capability_id: str,
             arguments: dict[str, Any]) -> Observation:
        result = self.invoker.invoke(InvokeRequest(
            capability_id=capability_id,
            arguments=arguments,
            idempotency_key=f"idem-{capability_id}",
            lease_generation="lease-gen-7",
            profile=PROFILE,
            rationale="the brief asks for an admitted source",
            grant=ToolGrant(
                grant_id="grant.researcher",
                profile=PROFILE,
                tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID}),
                max_risk=RiskLevel.MEDIUM.value),
        ))
        assert isinstance(result, Observation), result
        return result


@pytest.fixture
def rig(conn, store, monkeypatch):
    """The production chain with only the HTTP dial replaced.

    `build_live_fetch_wiring` builds the real RecordedTransport → allowlist
    gate → pin → ProviderHTTPTransport chain; the innermost `request` is
    scripted. The supply is then built over that machinery.
    """
    wiring = build_live_fetch_wiring(
        conn, store, lambda: CLOCK, dns_resolve=_public_resolve)
    calls: list[Any] = []

    def scripted(spec):
        calls.append(spec)
        path = urllib.parse.urlsplit(spec.url).path
        if path == "/works":
            return TransportResponse(
                status=200, body=SEARCH_BODY, headers={},
                content_type="application/json")
        return TransportResponse(
            status=200, body=FETCH_BODY, headers={},
            content_type="text/plain")

    monkeypatch.setattr(wiring.http_transport, "request", scripted)
    # The driver compares `deadline_monotonic` against the provider clock's
    # monotonic. The production wiring adapts a core clock to REAL
    # time.monotonic; this test's plane clock is the frozen one, so the
    # machinery clock is replaced to keep both sides on the same base (the
    # transport keeps its own clock for timestamping).
    machinery = dataclasses.replace(wiring.machinery, clock=Clock())
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
    return Rig(conn=conn, supply=supply, invoker=invoker, calls=calls)


def _journal_rows(conn) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM provider_interactions ORDER BY interaction_id")]


def _provider_response_artifacts(conn) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM artifacts "
        "WHERE artifact_type = 'provider_response'").fetchone()
    return int(row["c"])


# ═══════════════ the supplied set ═══════════════


def test_the_supplied_set_is_exactly_the_two_research_egress_capabilities(
        rig) -> None:
    supply = rig.supply
    assert SUPPLIED_CAPABILITY_IDS == ("source_fetch", "source_search")
    assert supply.tool_set.set_id == RESEARCH_EGRESS_TOOL_SET_ID
    assert supply.tool_set.capability_ids == SUPPLIED_CAPABILITY_IDS
    assert supply.registry.capability_ids() == SUPPLIED_CAPABILITY_IDS
    assert supply.registry.drift_report() == ()
    assert set(supply.implementations) == {
        tool.tool_id for tool in supply.tools}
    assert set(supply.implementations) == set(SUPPLIED_CAPABILITY_IDS)
    for tool in supply.tools:
        assert tool.network is True
        assert tool.sandboxed is False
        assert tool.environment == IN_PROCESS_ENVIRONMENT
    for capability in supply.capabilities:
        assert capability.kind is CapabilityKind.TOOL


# ═══════════════ search ═══════════════


def test_source_search_returns_admitted_source_rows(rig) -> None:
    observation = rig.call(
        "source_search",
        {"provider": "openalex", "topic": "CRISPR", "max_results": 5})
    assert observation.ok(), observation.detail
    assert observation.envelope is not None
    assert observation.envelope.environment == IN_PROCESS_ENVIRONMENT
    payload = json.loads(observation.payload.text)
    assert payload["capability"] == "source_search"
    assert payload["provider"] == "openalex"
    # One bounded page with no reported total is an honest PARTIAL/UNKNOWN;
    # the observation must carry the rows and the note, not invent COMPLETE.
    assert payload["aggregate"] in {"COMPLETE", "PARTIAL"}
    assert payload["notes"], "a bounded one-page walk must carry its note"
    assert len(payload["rows"]) == 5, "the recorded search delivered no rows"
    for row in payload["rows"]:
        assert row["result_id"].startswith("sr_")
        assert row["provider"] == "openalex"
        assert row["source_url"].startswith("https://")
        assert len(row["content_hash"]) == 64
    # One recorded interaction for one transport request.
    assert len(rig.calls) == 1
    rows = _journal_rows(rig.conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["project_id"] == PROJECT
    assert row["task_id"] is None
    assert row["provider_id"] == "openalex"
    assert row["outcome_kind"] == "RECORDED_SUCCESS"
    assert row["response_body_hash"] == hashlib.sha256(SEARCH_BODY).hexdigest()
    assert row["source_url_redacted"].startswith(
        "https://api.openalex.org/works")
    # The journal row carries refs/digests only — never the fetched body —
    # and respects the existing 4 KiB event-payload bound.
    serialized = json.dumps(row, default=str)
    assert SEARCH_BODY_MARKER not in serialized
    assert len(row["request_json"].encode("utf-8")) <= 4096
    assert _provider_response_artifacts(rig.conn) == 0


# ═══════════════ fetch ═══════════════


def test_source_fetch_succeeds_against_the_allowlisted_provider(rig) -> None:
    observation = rig.call(
        "source_fetch",
        {"provider": "openalex", "url": "https://openalex.org/W2060313932"})
    assert observation.ok(), observation.detail
    payload = json.loads(observation.payload.text)
    assert payload["capability"] == "source_fetch"
    assert payload["status"] == "FETCHED"
    assert payload["url"] == "https://openalex.org/W2060313932"
    assert payload["content_hash"] == hashlib.sha256(FETCH_BODY).hexdigest()
    assert payload["size_bytes"] == len(FETCH_BODY)
    assert FETCH_BODY_MARKER in payload["text"]
    # The adapter rewrite happened BEFORE the dial, and the vetted host is the
    # API host that the scripted transport saw.
    assert len(rig.calls) == 1
    assert rig.calls[0].url == "https://api.openalex.org/W2060313932"
    rows = _journal_rows(rig.conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["outcome_kind"] == "RECORDED_SUCCESS"
    assert row["response_body_hash"] == hashlib.sha256(FETCH_BODY).hexdigest()
    assert row["source_url_redacted"] == (
        "https://api.openalex.org/W2060313932")
    assert row["task_id"] is None
    serialized = json.dumps(row, default=str)
    assert FETCH_BODY_MARKER not in serialized
    assert _provider_response_artifacts(rig.conn) == 0


@pytest.mark.parametrize(
    ("url", "code"),
    (
        (f"https://evil.example/steal?token={SECRET_QUERY_VALUE}",
         "ORIGIN_NOT_ALLOWLISTED"),
        # The code-owned surface is https-only: plain http is a different
        # origin, not a scheme the rule layer accepts at the allowlist.
        ("http://api.openalex.org/works", "ORIGIN_NOT_ALLOWLISTED"),
        ("ftp://api.openalex.org/works", "SCHEME_NOT_ALLOWED"),
        ("https://api.openalex.org:8443/works", "ORIGIN_NOT_ALLOWLISTED"),
        ("https://api.openalex.org:foo@evil.example/works",
         "CREDENTIALS_IN_URL"),
    ),
    ids=("unknown-host", "http-origin", "wrong-scheme", "non-default-port",
         "userinfo"),
)
def test_an_out_of_allowlist_url_refuses_before_a_dial_and_journals(
        rig, url: str, code: str) -> None:
    observation = rig.call(
        "source_fetch", {"provider": "openalex", "url": url})
    assert observation.ok() is False
    assert observation.failure is FailureKind.TOOL_ERROR
    # Pre-dial: the scripted HTTP transport was never touched.
    assert rig.calls == []
    rows = _journal_rows(rig.conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["outcome_kind"] == REFUSAL_OUTCOME_KIND
    assert row["failure_class"] == code
    assert row["response_body_hash"] is None
    assert row["task_id"] is None
    serialized = json.dumps(row, default=str)
    assert SECRET_QUERY_VALUE not in serialized, (
        "a credential-class query value reached the journal row")
    assert FETCH_BODY_MARKER not in serialized
    assert len(row["request_json"].encode("utf-8")) <= 4096
    assert _provider_response_artifacts(rig.conn) == 0


def test_a_host_from_the_other_provider_surface_refuses_pre_dial(rig) -> None:
    observation = rig.call(
        "source_fetch",
        {"provider": "openalex",
         "url": "https://pubmed.ncbi.nlm.nih.gov/42818749/"})
    assert observation.ok() is False
    assert rig.calls == []
    row = _journal_rows(rig.conn)[0]
    assert row["outcome_kind"] == REFUSAL_OUTCOME_KIND
    assert row["failure_class"] == "PROVIDER_HOST_MISMATCH"
    assert "pubmed.ncbi.nlm.nih.gov" in row["source_url_redacted"]
    assert row["response_body_hash"] is None
