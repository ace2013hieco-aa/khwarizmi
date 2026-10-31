"""OPS-5Z3 — a fetched page is not evidence until it is the source.

The fixtures are the real provider responses stored by the live runs, not
synthesised bodies:

* ``pubmed_cookie_wall_5590.html`` — the 5,590-byte "Cookies must be enabled"
  page served as **HTTP 203** to runs 18 and 31 (content hash
  ``e142eeae…`` / ``ebcd5b02…`` / ``705db439…``);
* ``openalex_work_33727.json`` — the 33,727-byte OpenAlex work record served as
  **HTTP 200** to run 19 (content hash ``05475c33…``).

The first must be refused before an artifact can be constructed; the second
must be accepted. The capability path is the live one, so the assertions run
through the real supply, the real fetch driver and the real artifact store.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from hermes.agents.runtime.assembly import evidence_envelope
from hermes.agents.runtime.types import MAX_PAYLOAD_BYTES
from hermes.artifacts.store import ArtifactStore
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
from hermes.research.capability_supply import (
    RESEARCH_EGRESS_TOOL_SET_ID,
    build_research_egress_supply,
)
from hermes.research.claims import (
    CLAIM_SCHEMA_VERSION,
    ExtractionDraft,
    ResearchClaimDraft,
    validate_extraction,
)
from hermes.research.live_fetch import ALLOWLIST_HOSTS, build_live_fetch_wiring
from hermes.tools.capabilities.content import read_content
from hermes.tools.capabilities.invoke import (
    CapabilityInvoker,
    InMemoryIdempotencyLedger,
)
from hermes.tools.capabilities.types import (
    InvokeRequest,
    Observation,
    RiskLevel,
    ToolGrant,
)
from hermes.tools.providers.base import TransportResponse
from hermes.tools.providers.content import fetch_content_refusal

CLOCK = "2026-10-29T18:00:00.000000+00:00"
PROJECT = "p-ops5z3"
PROFILE = "RESEARCHER"
OPENALEX_URL = "https://openalex.org/W3087879971"

FIXTURES = Path(__file__).parent / "fixtures" / "source_payloads"
COOKIE_WALL = FIXTURES / "pubmed_cookie_wall_5590.html"
OPENALEX_WORK = FIXTURES / "openalex_work_33727.json"


class Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 1000.0

    def sleep(self, delay: float) -> None:
        return None


def _public_resolve(host: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


@pytest.fixture
def conn():
    connection = connect(":memory:")
    migrate_to_latest(connection)
    ProjectRepository(connection, lambda: CLOCK).create(PROJECT, "OPS-5Z3")
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
    store: ArtifactStore
    invoker: CapabilityInvoker

    def fetch(self, url: str = OPENALEX_URL, key: str = "idem-ops5z3") -> Observation:
        result = self.invoker.invoke(InvokeRequest(
            capability_id="source_fetch",
            arguments={"provider": "openalex", "url": url},
            idempotency_key=key,
            lease_generation="lease-gen-ops5z3",
            profile=PROFILE,
            rationale="the stage needs a source, not just a 2xx",
            grant=ToolGrant(
                grant_id="grant.ops5z3",
                profile=PROFILE,
                tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID}),
                max_risk=RiskLevel.MEDIUM.value),
            deadline_seconds=30.0))
        assert isinstance(result, Observation), result
        return result


def _rig(conn, store, monkeypatch, *, status: int, body: bytes,
         content_type: str) -> Rig:
    wiring = build_live_fetch_wiring(
        conn, store, lambda: CLOCK, dns_resolve=_public_resolve)

    def scripted(spec):
        return TransportResponse(
            status=status, body=body, headers={}, content_type=content_type)

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
    return Rig(conn=conn, store=store, invoker=invoker)


def _payload(observation: Observation) -> dict[str, Any]:
    assert observation.payload is not None
    return json.loads(observation.payload.text)


def _artifact_count(conn) -> int:
    return int(conn.execute(
        "SELECT count(*) FROM artifacts WHERE artifact_type = 'source_payload'"
    ).fetchone()[0])


# ═══════════════ the pure check, on the stored bytes ═══════════════


def test_the_cookie_wall_is_refused_on_its_status_and_its_body() -> None:
    body = COOKIE_WALL.read_bytes()
    assert len(body) == 5590

    by_status = fetch_content_refusal(
        status=203, media_type="text/html", body=body)
    assert by_status is not None
    assert by_status.code == "NON_AUTHORITATIVE_RESPONSE"

    # The same bytes at 200 are still a consent interstitial, not a source.
    by_body = fetch_content_refusal(
        status=200, media_type="text/html", body=body)
    assert by_body is not None
    assert by_body.code == "NON_CONTENT_PAYLOAD"
    assert "cookie interstitial" in by_body.detail


def test_the_real_openalex_record_is_accepted() -> None:
    body = OPENALEX_WORK.read_bytes()
    assert len(body) == 33727
    assert fetch_content_refusal(
        status=200, media_type="application/json", body=body) is None


def test_the_check_reads_only_the_prefix_and_is_deterministic() -> None:
    body = b"<html><body>" + b"x" * 5000 + b"cookies must be enabled</body></html>"
    # The marker is outside the 4 KiB prefix: a real long article is not
    # refused by a phrase that appears deep in its body.
    assert fetch_content_refusal(
        status=200, media_type="text/html", body=body) is None
    assert fetch_content_refusal(
        status=200, media_type="text/html", body=COOKIE_WALL.read_bytes()) \
        == fetch_content_refusal(
            status=200, media_type="text/html", body=COOKIE_WALL.read_bytes())


# ═══════════════ the capability path — refused before storage ═══════════════


def test_the_203_cookie_wall_is_a_refusal_and_writes_no_artifact(
        conn, store, monkeypatch) -> None:
    rig = _rig(conn, store, monkeypatch, status=203,
               body=COOKIE_WALL.read_bytes(), content_type="text/html")

    observation = rig.fetch()

    assert observation.ok(), observation.detail
    assert observation.artifacts == ()
    payload = _payload(observation)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == "NON_AUTHORITATIVE_RESPONSE"
    assert _artifact_count(conn) == 0
    assert not any(path.is_file() for path in Path(store._root).rglob("*"))


def test_a_200_cookie_wall_is_a_refusal_and_writes_no_artifact(
        conn, store, monkeypatch) -> None:
    rig = _rig(conn, store, monkeypatch, status=200,
               body=COOKIE_WALL.read_bytes(), content_type="text/html")

    observation = rig.fetch()

    assert observation.ok(), observation.detail
    payload = _payload(observation)
    assert payload["status"] == "REFUSED"
    assert payload["code"] == "NON_CONTENT_PAYLOAD"
    assert _artifact_count(conn) == 0


def test_the_real_openalex_record_is_stored_and_citable(
        conn, store, monkeypatch) -> None:
    body = OPENALEX_WORK.read_bytes()
    rig = _rig(conn, store, monkeypatch, status=200,
               body=body, content_type="application/json")

    observation = rig.fetch()

    assert observation.ok(), observation.detail
    payload = _payload(observation)
    assert payload["status"] == "FETCHED"
    assert payload["size_bytes"] == 33727
    assert payload["artifact_id"] == payload["content_hash"]
    assert _artifact_count(conn) == 1
    assert rig.store.read_verified(payload["content_hash"]) == body
    assert payload["source_ref"] == f"source_payload:{payload['content_hash']}"


# ═══════════════ the evidence envelope — a bounded read, not an id ═══════════════


def test_the_envelope_carries_a_bounded_excerpt_of_the_real_record() -> None:
    body = OPENALEX_WORK.read_bytes()
    ref = "evidence:05475c339049a0388bc6a3bc21b1d0f7bffdaad1b8cad27ffba661dfd091ce3c"

    envelope = evidence_envelope(
        task_id="task-ops5z3:EVIDENCE", evidence_ref=ref, artifact_bytes=body,
        artifact_format="openalex")

    assert len(envelope.text.encode("utf-8")) <= MAX_PAYLOAD_BYTES
    document = json.loads(envelope.text)
    excerpt = document["excerpt"]
    assert excerpt["bytes"] == 33727
    # OPS-5Z3: the excerpt is the record's *content*, not its first N bytes.
    # The abstract of this record begins at byte 31,556, so a byte prefix gave
    # the stage a title and a list of author affiliations.
    assert excerpt["extracted"] is True
    # The selected content fits, so nothing was cut — but fields were dropped,
    # which ``extracted`` says and ``truncated`` alone would not.
    assert excerpt["truncated"] is False
    assert len(excerpt["text"].encode("utf-8")) < len(body) // 10
    # Provenance: the title is verbatim in the artifact, and the abstract's
    # words are the keys of its inverted index. The reconstructed prose is not a
    # contiguous byte range, so a substring check would be the wrong assertion.
    assert "Containment, Contact Tracing" in excerpt["text"]
    assert b"Containment, Contact Tracing" in body
    for word in excerpt["text"].split("\n\n")[-1].split()[:8]:
        assert word.encode("utf-8") in body
    # The envelope still names the fact it is evidence for.
    assert document["evidence_ref"] == ref
    assert document["artifact_id"] == ref.partition(":")[2]


def test_a_short_artifact_is_carried_whole_and_says_so() -> None:
    body = b"alpha reduces beta\n"
    envelope = evidence_envelope(
        task_id="t:EVIDENCE", evidence_ref="evidence:" + "a" * 64,
        artifact_bytes=body)
    excerpt = json.loads(envelope.text)["excerpt"]
    # Plain text is its own content, so nothing was selected and nothing cut.
    # OPS-5Z5 adds the read flag: a caller can tell a full read from a fallback
    # without inferring it from the absence of a field.
    assert excerpt == {"text": body.decode(), "truncated": False,
                       "extracted": False, "bytes": len(body),
                       "read": "content", "format": "text"}


def test_the_envelope_without_bytes_keeps_the_pinned_ops5l_shape() -> None:
    ref = "evidence:" + "a" * 64
    envelope = evidence_envelope(task_id="t:EVIDENCE", evidence_ref=ref)
    assert json.loads(envelope.text) == {"artifact_id": "a" * 64,
                                         "evidence_ref": ref}
    assert len(envelope.text.encode("utf-8")) <= MAX_PAYLOAD_BYTES


def test_an_excerpt_that_would_not_fit_is_trimmed_not_torn() -> None:
    # Quotes and backslashes expand under JSON escaping, so a byte budget is
    # not a document budget; the renderer must trim until the whole envelope
    # fits, and the text it returns must remain a clean prefix of the bytes.
    body = ('"' * 8000).encode("utf-8")
    envelope = evidence_envelope(
        task_id="t:EVIDENCE", evidence_ref="evidence:" + "b" * 64,
        artifact_bytes=body)
    assert len(envelope.text.encode("utf-8")) <= MAX_PAYLOAD_BYTES
    excerpt = json.loads(envelope.text)["excerpt"]
    assert excerpt["truncated"] is True
    assert excerpt["text"] == "" or set(excerpt["text"]) == {"\""}
    assert excerpt["text"].encode("utf-8") in body


# ═══════════════ the existing claim-ground gate can refuse a wrong figure ═══════════════


def _claim(statement: str, source_ref: str) -> ResearchClaimDraft:
    return ResearchClaimDraft(
        ref="c1", statement=statement, source_ref=source_ref,
        support_state="INFERRED", span_ref=None, claim_type="descriptive",
        context_tags={}, assumption_refs=(), related_claims=())


def _validate(statement: str) -> Any:
    source_ref = ("source_payload:"
                  "05475c339049a0388bc6a3bc21b1d0f7bffdaad1b8cad27ffba661dfd091ce3c")
    draft = ExtractionDraft(
        source_ref=source_ref, claims=(_claim(statement, source_ref),),
        assumptions=(), extracted_by="model_ref:ops5z3",
        schema_version=CLAIM_SCHEMA_VERSION)
    text = OPENALEX_WORK.read_text(encoding="utf-8")
    return validate_extraction(
        draft, text_resolver=lambda ref: text if ref == source_ref else None)


def test_a_quoted_figure_absent_from_the_bytes_is_refused() -> None:
    """G9 already exists; the excerpt is what lets the model avoid this."""
    result = _validate('The record reports "India 5,275,035 cases".')
    assert not result.admitted
    assert "statement_not_in_source" in {e.code for e in result.errors}


def test_a_quoted_title_present_in_the_bytes_is_admitted() -> None:
    result = _validate(
        'The record is titled "Containment, Contact Tracing and Asymptomatic '
        'Transmission of Novel Coronavirus Disease (COVID-19): A Modelling Study".')
    assert result.admitted, result.errors


def test_content_that_exceeds_the_bound_is_cut_and_says_so() -> None:
    """The other branch: ``extracted`` and ``truncated`` are independent.

    A record whose *content* alone exceeds the bound is both selected from and
    cut — the case the byte-prefix design could never distinguish.
    """
    words = " ".join(f"w{index}" for index in range(4000))
    record = json.dumps({
        "title": "A long record",
        "abstract_inverted_index": {word: [place]
                                    for place, word in enumerate(words.split())},
    }).encode("utf-8")

    excerpt = json.loads(evidence_envelope(
        task_id="t:EVIDENCE", evidence_ref="evidence:" + "b" * 64,
        artifact_bytes=record, artifact_format="openalex").text)["excerpt"]

    assert excerpt["extracted"] is True
    assert excerpt["truncated"] is True
    assert len(excerpt["text"].encode("utf-8")) <= MAX_PAYLOAD_BYTES
    assert excerpt["text"].startswith("A long record")


class TestTheMarkersDoNotRefuseRealArticles:
    """`captcha` and `access denied` are ordinary English.

    The first marker list applied them as bare substrings to the first 4 KiB, so
    an article titled "How CAPTCHA systems work" was refused as a challenge page
    and the run lost its source. A real interstitial is mostly markup; a real
    article is mostly prose. The broad markers now count only on a sparse page.
    """

    def test_an_article_about_captchas_is_accepted(self) -> None:
        body = (
            "<html><body><h1>How CAPTCHA systems work</h1><p>"
            + "A captcha is a challenge used to tell humans from bots. " * 40
            + "</p></body></html>").encode()
        assert fetch_content_refusal(
            status=200, media_type="text/html", body=body) is None

    def test_an_article_mentioning_access_denied_is_accepted(self) -> None:
        body = (
            "<html><body><h1>Debugging 403s</h1><p>"
            + "The server returned access denied, which usually means the token "
              "expired. " * 40
            + "</p></body></html>").encode()
        assert fetch_content_refusal(
            status=200, media_type="text/html", body=body) is None

    def test_a_sparse_page_with_those_words_is_still_refused(self) -> None:
        # The wall the markers exist for: almost no prose, so the words count.
        body = b"<html><body>Access denied. captcha</body></html>"
        refusal = fetch_content_refusal(
            status=200, media_type="text/html", body=body)
        assert refusal is not None and refusal.code == "NON_CONTENT_PAYLOAD"

    def test_the_strong_markers_apply_to_a_long_page_too(self) -> None:
        # "Cookies must be enabled" is not something an article opens with.
        body = (
            "<html><body>Cookies must be enabled to continue.<p>"
            + "filler prose " * 400 + "</p></body></html>").encode()
        refusal = fetch_content_refusal(
            status=200, media_type="text/html", body=body)
        assert refusal is not None and refusal.code == "NON_CONTENT_PAYLOAD"


class TestAMalformedIndexIsNotAnAbstract:
    """A reconstruction that invents a sentence is worse than none.

    Dropping a word with an unreadable position returned a *shorter* abstract —
    a different one the source never wrote, indistinguishable to the reader.
    Joining two words that claim one slot produced a sentence that never
    existed. Both now return no abstract at all.
    """

    def test_a_string_position_drops_the_abstract_not_a_word(self) -> None:
        record = json.dumps({
            "title": "T",
            "abstract_inverted_index": {"alpha": ["1"], "beta": [1]},
        }).encode()
        assert read_content(record, format="openalex").text == "T"

    def test_colliding_positions_do_not_become_a_sentence(self) -> None:
        record = json.dumps({
            "title": "T",
            "abstract_inverted_index": {"alpha": [1], "beta": [1]},
        }).encode()
        assert read_content(record, format="openalex").text == "T"

    def test_a_valid_index_still_reconstructs(self) -> None:
        record = json.dumps({
            "title": "T",
            "abstract_inverted_index": {"alpha": [0], "beta": [1]},
        }).encode()
        assert read_content(record, format="openalex").text == "T\n\nalpha beta"
