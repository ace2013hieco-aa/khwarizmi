"""CHG-2 provider record/replay tests (ratified CHG-2 contract).

Covers: success/failure/timeout/rate-limit recording; replay
success/failure/missing/corrupt/incompatible; adapter-version
compatibility matrix; deterministic fixture identity; provenance
linkage (interaction → artifact store body → evidence); redaction +
secret rejection; size caps; project isolation; SOURCE_CHANGED; the
code-owned registry (all 11 adapters, same contract); unsupported
providers; live-never-contacted replay; per-adapter contract tests.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from hermes.artifacts.store import ArtifactStore
from hermes.core import frozen_clock
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.provider_interactions import (
    ProviderInteractionRepository,
    persist_interaction,
)
from hermes.tools.providers.adapters import PROVIDER_REGISTRY, resolve_adapter
from hermes.tools.providers.base import (
    PageState,
    RequestSpec,
    TransportResponse,
)
from hermes.tools.providers.normalize import RetrievalHints
from hermes.tools.providers.replay import (
    REPLAY_UNAVAILABLE,
    SOURCE_CHANGED,
    FixtureRecord,
    RecordedInteraction,
    RecordedTransport,
    RecordTooLargeError,
    ReplayUnavailableError,
    compare_recorded,
    dump_fixtures,
    fixture_id_of,
    interaction_id_of,
    interaction_to_fixture,
    load_fixtures,
    normalized_request,
)
from hermes.tools.research_sources import (
    SOURCE_PROVIDER_ALLOWLIST,
    ProviderError,
    ProviderValidationError,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"


# ═══════════════════════ fakes ═══════════════════════


class FakeClock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 0.0


class FakeTransport:
    """Scripted inner transport (records contact for live-proof)."""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.contacted = 0

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.contacted += 1
        action = self._script.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action


class RefusingTransport:
    """Inner transport that must never be contacted (replay proof)."""

    def __init__(self) -> None:
        self.contacted = 0

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.contacted += 1
        raise AssertionError("live provider contacted during replay")


def _recorder(seen: list):
    """Sink factory binding the log list explicitly (no loop-variable
    capture)."""

    def _sink(interaction, body) -> None:
        seen.append((interaction, body))

    return _sink


def _spec(url="https://example.test/search", params=None):
    return RequestSpec(url=url, params=params or {"q": "x"},
                       headers_meta={"Authorization": "Bearer SECRET"})


def _norm(spec=None):
    return normalized_request(spec or _spec())


def _ok_response(body=b'{"items": [{"id": "1", "title": "T"}]}'):
    return TransportResponse(status=200, body=body,
                             headers={"Retry-After": "3"},
                             content_type="application/json")


def _rt(provider_id="openalex", *, sink=None, fixtures=None, mode="record",
        inner=None, **kw):
    return RecordedTransport(
        inner or FakeTransport([_ok_response()]),
        provider_id=provider_id, adapter_version="1", parser_version="1",
        clock=FakeClock(), mode=mode, sink=sink, fixtures=fixtures, **kw)


@pytest.fixture
def db(tmp_path):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    from hermes.persistence.repositories import ProjectRepository
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p2", "Other")
    yield conn
    conn.close()


def _store(conn, tmp_path):
    from hermes.persistence.repositories import ArtifactRepository
    repo = ArtifactRepository(conn, frozen_clock(CLOCK))
    return ArtifactStore(str(tmp_path / "store"), repo,
                         clock=frozen_clock(CLOCK))


def _insert_task(db, task_id, project="p1"):
    from hermes.core.node import NodeContract
    from hermes.persistence.repositories import TaskRepository
    repo = TaskRepository(db, frozen_clock(CLOCK))
    node = NodeContract(
        task_id=task_id, project_id=project, task_type="TOOL_TASK",
        idempotency_key=f"idem-{task_id}", dependencies=[])
    repo.create(node)


# ═══════════════════════ recording ═══════════════════════


class TestRecording:
    def test_record_success(self):
        seen: list = []
        rt = _rt(sink=lambda i, b: seen.append((i, b)))
        response = rt.request(_spec())
        assert response.status == 200
        assert len(seen) == 1
        interaction, body = seen[0]
        assert interaction.outcome_kind == "RECORDED_SUCCESS"
        assert interaction.status_class == "HTTP_200"
        assert interaction.failure_class is None
        assert body == _ok_response().body
        assert interaction.response_body_hash == hashlib.sha256(body).hexdigest()
        # Interaction identity binds request + response (+ task); the
        # fixture identity binds the request alone (see
        # test_adapter_version_compatible).
        assert interaction.interaction_id.startswith("ix_")
        assert interaction.interaction_id == interaction_id_of(
            fixture_id_of("openalex", interaction.normalized_request),
            status_class="HTTP_200",
            body_hash=hashlib.sha256(body).hexdigest(),
            failure_class=None, task_id=None)

    def test_record_failure(self):
        seen: list = []
        err = ProviderError("boom", provider_id="openalex",
                            hazard_class="TIMEOUT")
        rt = _rt(sink=lambda i, b: seen.append((i, b)),
                 inner=FakeTransport([err]))
        with pytest.raises(ProviderError):
            rt.request(_spec())
        assert len(seen) == 1
        interaction, body = seen[0]
        assert interaction.outcome_kind == "RECORDED_FAILURE"
        assert interaction.status_class == "ERROR_TIMEOUT"
        assert interaction.failure_class == "ProviderError"
        assert body is None
        assert interaction.response_body_hash is None

    def test_record_timeout_rate_limit(self):
        for hazard, status in (("TIMEOUT", 408), ("THROTTLED", 429)):
            seen: list = []
            rt = _rt(sink=_recorder(seen),
                     inner=FakeTransport([TransportResponse(
                         status=status, body=b"{}", headers={},
                         content_type="application/json")]))
            response = rt.request(_spec())
            assert response.status == status
            assert seen[0][0].status_class == f"HTTP_{status}"

    def test_record_oversized_body_refused_loudly(self):
        rt = _rt(inner=FakeTransport([TransportResponse(
            status=200, body=b"x" * 100, headers={},
            content_type="application/json")]),
            max_body_bytes=10)
        with pytest.raises(RecordTooLargeError):
            rt.request(_spec())

    def test_credentials_never_recorded(self):
        seen: list = []
        rt = _rt(sink=lambda i, b: seen.append((i, b)))
        rt.request(_spec(url="https://user:pass@example.test/s?q=1",
                         params={"api_key": "SECRET", "q": "x"}))
        normalized = seen[0][0].normalized_request
        blob = json.dumps(normalized)
        assert "SECRET" not in blob
        assert "pass" not in blob
        assert "api_key" not in blob or "<redacted" in blob


# ═══════════════════════ replay ═══════════════════════


def _fixture_for(provider_id="openalex", body=None, status=200,
                 error=None):
    from hermes.tools.providers.replay import fixture_id_of as _fid
    body = _ok_response().body if body is None and error is None else body
    normalized = _norm()
    interaction = RecordedInteraction(
        interaction_id=_fid(provider_id, normalized),
        provider_id=provider_id,
        adapter_version="1", parser_version="1",
        normalized_request=normalized,
        request_hash="h", status_class=f"HTTP_{status}",
        response_body_hash=(hashlib.sha256(body).hexdigest()
                            if body is not None else None),
        outcome_kind=("RECORDED_SUCCESS" if error is None
                      else "RECORDED_FAILURE"),
        failure_class=None, retrieved_at=CLOCK,
        source_url_redacted="https://example.test/search")
    return interaction_to_fixture(
        interaction, body, headers={"Retry-After": "3"},
        status=status,
        error_message=(str(error) if error else None))


class TestReplay:
    def test_replay_success_without_live_contact(self):
        fixture = _fixture_for()
        inner = RefusingTransport()
        rt = _rt(mode="replay", inner=inner,
                 fixtures={fixture.fixture_id: fixture})
        response = rt.request(_spec())
        assert response.status == 200
        assert response.body == _ok_response().body
        assert inner.contacted == 0

    def test_replay_failure_preserved(self):
        fixture = _fixture_for(
            error=ProviderError("recorded boom",
                                hazard_class="TIMEOUT"))
        inner = RefusingTransport()
        rt = _rt(mode="replay", inner=inner,
                 fixtures={fixture.fixture_id: fixture})
        with pytest.raises(ProviderError):
            rt.request(_spec())
        assert inner.contacted == 0

    def test_missing_fixture(self):
        inner = RefusingTransport()
        rt = _rt(mode="replay", inner=inner, fixtures={})
        with pytest.raises(ReplayUnavailableError):
            rt.request(_spec())

    def test_corrupt_fixture(self):
        with pytest.raises(ReplayUnavailableError):
            FixtureRecord.from_mapping({"not": "a fixture"})
        with pytest.raises(ReplayUnavailableError):
            FixtureRecord.from_mapping({
                "fixture_id": "fx-x", "provider_id": "p",
                "adapter_version": "1", "parser_version": "1",
                "normalized_request": {"url": "u", "params": {}},
                "body_hex": "zz", "body_hash": "00"})

    def test_body_hash_mismatch_refused(self):
        fixture = _fixture_for()
        bad = FixtureRecord(
            fixture_id=fixture.fixture_id, provider_id="openalex",
            adapter_version="1", parser_version="1",
            normalized_request=fixture.normalized_request,
            status=200, body_hex="abcd", body_hash="00" * 32,
            headers={}, content_type=None, error_type=None,
            error_message=None, error_hazard_class=None)
        with pytest.raises(ReplayUnavailableError):
            FixtureRecord.from_mapping(bad.to_mapping())

    def test_parser_incompatibility(self):
        fixture = _fixture_for()
        inner = RefusingTransport()
        rt = RecordedTransport(
            inner, provider_id="openalex", adapter_version="1",
            parser_version="2", clock=FakeClock(), mode="replay",
            fixtures={fixture.fixture_id: fixture})
        with pytest.raises(ReplayUnavailableError) as exc:
            rt.request(_spec())
        assert "parser" in str(exc.value).lower()

    def test_adapter_version_compatible(self):
        # Same parser version under a newer adapter replays fine: the
        # fixture id binds provider + normalized request (not adapter
        # version); the recorded adapter version is provenance, and the
        # replay transport carries the new one.
        fixture = _fixture_for()
        assert fixture.adapter_version == "1"
        inner = RefusingTransport()
        rt = RecordedTransport(
            inner, provider_id="openalex", adapter_version="2",
            parser_version="1", clock=FakeClock(), mode="replay",
            fixtures={fixture.fixture_id: fixture})
        response = rt.request(_spec())
        assert response.status == 200
        assert response.body == _ok_response().body
        assert inner.contacted == 0

    def test_fixture_loader_roundtrip(self, tmp_path):
        fixture = _fixture_for()
        path = str(tmp_path / "corpus.json")
        dump_fixtures([fixture], path)
        loaded = load_fixtures(path)
        assert set(loaded) == {fixture.fixture_id}
        assert loaded[fixture.fixture_id].body_hash == fixture.body_hash

    def test_fixture_identity_deterministic(self):
        normalized = {"url": "https://example.test/search",
                      "params": {"q": "x"}}
        assert (fixture_id_of("openalex", normalized)
                == fixture_id_of("openalex", normalized))
        assert (fixture_id_of("openalex", normalized)
                == fixture_id_of("openalex", dict(normalized)))
        assert (fixture_id_of("openalex", normalized)
                != fixture_id_of("arxiv", normalized))
        other = {"url": "https://example.test/search",
                 "params": {"q": "y"}}
        assert (fixture_id_of("openalex", normalized)
                != fixture_id_of("openalex", other))

    def test_source_changed(self):
        fixture = _fixture_for()
        assert compare_recorded(_ok_response(), fixture) is True
        assert compare_recorded(
            TransportResponse(status=200, body=b'{"other": true}',
                              headers={},
                              content_type="application/json"),
            fixture) is False
        assert SOURCE_CHANGED == "SOURCE_CHANGED"
        assert REPLAY_UNAVAILABLE == "REPLAY_UNAVAILABLE"


# ═══════════════════════ persistence / provenance / security ═══════════════════════


class TestPersistence:
    def test_persist_roundtrip(self, db, tmp_path):
        store = _store(db, tmp_path)
        _insert_task(db, "t-1")
        db.execute(
            """INSERT INTO artifacts
               (artifact_id, project_id, task_id, artifact_type,
                content_hash, size_bytes, storage_path, producer,
                metadata_json, created_at)
               VALUES ('art-ev1', 'p1', NULL, 'evidence', 'ch-ev1', 1,
                       'x', 't', NULL, ?)""", (CLOCK,))
        body = _ok_response().body
        interaction = RecordedInteraction(
            interaction_id="fx-1", provider_id="openalex",
            adapter_version="1", parser_version="1",
            normalized_request={"url": "https://example.test/search",
                                "params": {"q": "x"}},
            request_hash="h", status_class="HTTP_200",
            response_body_hash=hashlib.sha256(body).hexdigest(),
            outcome_kind="RECORDED_SUCCESS", failure_class=None,
            retrieved_at=CLOCK,
            source_url_redacted="https://example.test/search")
        repo = ProviderInteractionRepository(db)
        rid = persist_interaction(
            db, frozen_clock(CLOCK), store, interaction, body,
            project_id="p1", task_id="t-1",
            evidence_artifact_id="art-ev1")
        assert rid == "fx-1"
        row = repo.get("fx-1", "p1")
        assert row is not None
        assert row["provider_id"] == "openalex"
        assert row["task_id"] == "t-1"
        assert row["evidence_artifact_id"] == "art-ev1"
        assert len(repo.list_for_task("t-1")) == 1
        assert len(repo.list_for_evidence("art-ev1")) == 1
        assert repo.list_for_task("t-other") == []
        # Body bytes verifiable through the artifact store.
        body_hash = hashlib.sha256(body).hexdigest()
        assert store.read(body_hash) == body
        from hermes.persistence.repositories import ArtifactRepository
        art_repo = ArtifactRepository(db, frozen_clock(CLOCK))
        art_row = art_repo.get_by_hash(body_hash)
        assert art_row is not None
        assert store.verify_integrity(art_row["artifact_id"])

    def test_body_hash_mismatch_refused(self, db, tmp_path):
        store = _store(db, tmp_path)
        interaction = RecordedInteraction(
            interaction_id="fx-2", provider_id="openalex",
            adapter_version="1", parser_version="1",
            normalized_request={"url": "u", "params": {}},
            request_hash="h", status_class="HTTP_200",
            response_body_hash="00" * 32,
            outcome_kind="RECORDED_SUCCESS", failure_class=None,
            retrieved_at=CLOCK, source_url_redacted="u")
        with pytest.raises(ValueError):
            persist_interaction(
                db, frozen_clock(CLOCK), store, interaction, b"other",
                project_id="p1")

    def test_secret_request_refused(self, db):
        from hermes.persistence.event_validation import EventValidationError
        repo = ProviderInteractionRepository(db)
        with pytest.raises(EventValidationError):
            repo.record(
                interaction_id="fx-evil", project_id="p1", task_id=None,
                provider_id="openalex", adapter_version="1",
                parser_version="1", normalized_request_hash="h",
                request_json=json.dumps(
                    {"url": "u", "api_key": "SECRET-VALUE"}),
                response_status_class="HTTP_200",
                response_body_hash=None, outcome_kind="RECORDED_SUCCESS",
                failure_class=None, content_type=None,
                retrieved_at=CLOCK,
                source_url_redacted="u", evidence_artifact_id=None,
                created_at=CLOCK)

    def test_project_isolation(self, db):
        _insert_task(db, "t-1")
        repo = ProviderInteractionRepository(db)
        repo.record(
            interaction_id="fx-p1", project_id="p1", task_id="t-1",
            provider_id="openalex", adapter_version="1", parser_version="1",
            normalized_request_hash="h", request_json='{"url": "u"}',
            response_status_class="HTTP_200", response_body_hash=None,
            outcome_kind="RECORDED_SUCCESS", failure_class=None,
            content_type="application/json", retrieved_at=CLOCK,
            source_url_redacted="u",
            evidence_artifact_id=None, created_at=CLOCK)
        prow = repo.get("fx-p1", "p1")
        assert prow is not None
        assert prow["project_id"] == "p1"
        assert repo.get("fx-p1", "p2") is None
        assert repo.list_for_task("t-1") != []


# ═══════════════════════ registry + adapters ═══════════════════════


class TestRegistry:
    def test_allowlist_covered(self):
        assert set(PROVIDER_REGISTRY) == set(SOURCE_PROVIDER_ALLOWLIST)
        assert len(PROVIDER_REGISTRY) == 11

    def test_resolve_unknown_refused(self):
        with pytest.raises(ProviderValidationError):
            resolve_adapter("not-a-provider")

    def test_all_adapters_same_contract(self):
        hints = RetrievalHints(identifiers={}, topic="dark matter",
                               mode="TOPIC", unrecognized_hints=())
        state = PageState(page_index=0)
        for provider_id, cls in sorted(PROVIDER_REGISTRY.items()):
            adapter = cls()
            assert adapter.provider_id == provider_id
            assert adapter.adapter_version
            assert adapter.parser_version
            assert adapter.contract.provider_id == provider_id
            try:
                spec = adapter.build_request(hints, state, 10)
            except ProviderValidationError:
                continue  # id-only providers refuse topic queries
            assert spec.url.startswith("http")
            assert "Authorization" not in str(spec.params)
            page = adapter.parse_page(
                {"items": [{"id": "x1", "title": "T",
                            "doi": "10.1234/abcdef"}]}, state)
            assert page.records
            ids = adapter.extract_ids(
                {"doi": "10.1234/abcdef", "pmid": "123"})
            assert ids.get("doi") == "10.1234/abcdef"


class TestAdapters:
    def test_arxiv_atom(self):
        from hermes.tools.providers.adapters.arxiv import ArxivAdapter
        adapter = ArxivAdapter()
        xml = ('<feed xmlns="http://www.w3.org/2005/Atom">'
               '<entry><id>http://arxiv.org/abs/1234</id>'
               '<title>Some Title</title><summary>Abs.</summary>'
               '<author><name>Jane Doe</name></author>'
               '<published>2024-01-01</published></entry></feed>')
        page = adapter.parse_page(xml, PageState(page_index=0))
        assert len(page.records) == 1
        assert page.records[0]["title"] == "Some Title"

    def test_biorxiv_refuses_topic(self):
        from hermes.tools.providers.adapters.biorxiv import BiorxivAdapter
        adapter = BiorxivAdapter()
        hints = RetrievalHints(identifiers={}, topic="x", mode="TOPIC",
                               unrecognized_hints=())
        with pytest.raises(ProviderValidationError):
            adapter.build_request(hints, PageState(page_index=0), 10)

    def test_unpaywall_doi_only(self):
        from hermes.tools.providers.adapters.unpaywall import UnpaywallAdapter
        adapter = UnpaywallAdapter()
        hints = RetrievalHints(identifiers={}, topic="x", mode="TOPIC",
                               unrecognized_hints=())
        with pytest.raises(ProviderValidationError):
            adapter.build_request(hints, PageState(page_index=0), 10)
        hints = RetrievalHints(identifiers={"doi": "10.1/abc"}, topic="",
                               mode="IDENTIFIER", unrecognized_hints=())
        spec = adapter.build_request(hints, PageState(page_index=0), 10)
        assert "10.1/abc" in spec.url

    def test_fetch_request_needs_url(self):
        from types import SimpleNamespace

        from hermes.tools.providers.adapters.openalex import OpenalexAdapter
        adapter = OpenalexAdapter()
        with pytest.raises(ProviderValidationError):
            adapter.build_fetch_request(
                SimpleNamespace(source_url=""))
        spec = adapter.build_fetch_request(
            SimpleNamespace(source_url="https://example.test/fulltext"))
        assert spec.url == "https://example.test/fulltext"
