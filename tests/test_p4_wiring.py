"""P4 production wiring tests — real handlers through CHG-2 machinery.

Proves the principal P4 claim through the ACTUAL production provider
execution entry points (``_run_search`` / ``_run_fetch`` via
``make_source_*_handler`` + ``Controller.tick``), never synthetic
repository-only calls:

  production handler → existing transport boundary (RecordedTransport)
  → recording sink → ProviderInteractionRepository + bounded artifact
  → existing evidence/provenance linkage (outcome artifacts + edges)

and symmetrically for replay (fixtures → RecordedTransport →
adapter/parser → deterministic result, zero live contact).
"""
from __future__ import annotations

import hashlib
import json

import pytest

from hermes.artifacts.store import ArtifactStore
from hermes.core import frozen_clock
from hermes.core.intents import Intent, IntentKind
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.provider_interactions import (
    ProviderInteractionRepository,
)
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.research.controller import Controller
from hermes.research.gateway import apply_intent
from hermes.research.source_handlers import (
    ProviderMachinery,
    make_source_fetch_handler,
    make_source_search_handler,
)
from hermes.research.source_templates import (
    build_source_fetch_task_payload,
    build_source_search_task_payload,
)
from hermes.tools.providers.adapters.openalex import OpenalexAdapter
from hermes.tools.providers.base import TransportResponse
from hermes.tools.providers.replay import (
    RecordedTransport,
    interaction_to_fixture,
    provider_resolver_for,
)
from hermes.tools.research_sources import ProviderError

CLOCK = "2026-01-01T00:00:00.000000+00:00"
PROVIDER = "openalex"

OPENALEX_PAGE = {
    "meta": {"count": 1},
    "results": [{
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1234/abcdef",
        "title": "A study of things",
        "authorships": [{"author": {"display_name": "Ada L."}}],
        "publication_year": 2024,
        "primary_location": {"source": {"display_name": "J. Tests"}},
    }],
}

FULL_TEXT = b"Full text of the study, several kilobytes would live here."


# ═══════════════════════ fakes (transport-level only) ═══════════════════════


class FakeClock:
    def __init__(self, t=CLOCK):
        self.t = t

    def now_utc(self) -> str:
        return self.t

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, delay: float) -> None:
        return None


class ScriptedTransport:
    """Inner transport playing a script (responses or exceptions)."""

    def __init__(self, script):
        self._script = list(script)
        self.contacted = 0

    def request(self, spec):
        self.contacted += 1
        action = self._script.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action


class RefusingTransport:
    def __init__(self):
        self.contacted = 0

    def request(self, spec):
        self.contacted += 1
        raise AssertionError("live provider contacted")


class FakeLimiter:
    def acquire(self, provider):
        return True, ""

    def release(self, provider):
        pass

    def note_throttled(self, provider, retry_after=None):
        pass

    def last_denial_reason(self, provider):
        return ""


class FakeRecorder:
    def __init__(self):
        self.logs = []

    def record(self, log):
        self.logs.append(log)


@pytest.fixture
def db(tmp_path):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p2", "Other")
    yield conn
    conn.close()


def _store(db, tmp_path):
    repo = ArtifactRepository(db, frozen_clock(CLOCK))
    return ArtifactStore(str(tmp_path / "store"), repo,
                         clock=frozen_clock(CLOCK))


def _ok_bytes():
    return json.dumps(OPENALEX_PAGE).encode("utf-8")


def _ok_response(body=None):
    return TransportResponse(
        status=200, body=_ok_bytes() if body is None else body,
        headers={}, content_type="application/json")


def _machinery(inner, *, db, store, clock=None, mode="record",
               fixtures=None, provider=PROVIDER, redaction_policy=None):
    """Production-shaped machinery: REAL openalex adapter behind a
    RecordedTransport. Record mode persists through the ratified
    repository boundary (make_persisting_sink); replay mode serves
    fixtures with a refusing inner transport available."""
    from hermes.persistence.provider_interactions import make_persisting_sink
    clock = clock or FakeClock()
    adapters = {provider: OpenalexAdapter()}
    transport_kw = {}
    if redaction_policy is not None:
        transport_kw["redaction_policy"] = redaction_policy
    if mode == "record":
        transport = RecordedTransport(
            inner, resolve_provider=provider_resolver_for(adapters),
            clock=clock, mode="record",
            sink=make_persisting_sink(db, store, clock), **transport_kw)
    else:
        transport = RecordedTransport(
            inner, resolve_provider=provider_resolver_for(adapters),
            clock=clock, mode="replay", fixtures=fixtures or {},
            **transport_kw)
    return ProviderMachinery(
        adapters=adapters, transport=transport, limiter=FakeLimiter(),
        recorder=FakeRecorder(), clock=clock)


def _controller(db, machinery, store, *, project_id="p1"):
    return Controller(
        db, project_id=project_id, owner="p4-test",
        clock=lambda: CLOCK, lease_seconds=60,
        task_handlers={
            "source_search": make_source_search_handler(machinery),
            "source_fetch": make_source_fetch_handler(machinery),
        },
        artifact_store=store)


def _admit_search(db, *, project_id="p1", topic="dark matter"):
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id=project_id,
        payload=build_source_search_task_payload(
            PROVIDER, {"identifiers": {}, "topic": topic, "mode": "TOPIC",
                       "unrecognized_hints": []},
            scope_ref=project_id)))
    return result.entity_id


def _interactions(db, task_id):
    return ProviderInteractionRepository(db).list_for_task(task_id)


# ═══════════════════════ recording through production handlers ═══════════════════════


class TestRecordPath:
    def test_search_records_interaction(self, db, tmp_path):
        store = _store(db, tmp_path)
        inner = ScriptedTransport([_ok_response()])
        machinery = _machinery(inner, db=db, store=store)
        ctrl = _controller(db, machinery, store)
        task_id = _admit_search(db)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(task_id) is TaskStatus.SUCCEEDED
        assert inner.contacted >= 1
        rows = _interactions(db, task_id)
        assert len(rows) >= 1
        row = rows[0]
        assert row["provider_id"] == PROVIDER
        assert row["project_id"] == "p1"
        assert row["task_id"] == task_id
        assert row["outcome_kind"] == "RECORDED_SUCCESS"
        assert row["adapter_version"] == "1"
        assert row["parser_version"] == "1"
        assert row["response_body_hash"] == hashlib.sha256(
            _ok_bytes()).hexdigest()
        # Bounded artifact persisted + verifiable through the store.
        assert store.read(row["response_body_hash"]) == _ok_bytes()
        # Existing evidence linkage intact: outcome artifacts exist.
        arts = db.execute(
            "SELECT COUNT(*) c FROM artifacts "
            "WHERE artifact_type = 'source_result'").fetchone()["c"]
        assert arts >= 1

    def test_non_recording_baseline_unchanged(self, db, tmp_path):
        store = _store(db, tmp_path)
        inner = ScriptedTransport([_ok_response()])
        machinery = ProviderMachinery(
            adapters={PROVIDER: OpenalexAdapter()}, transport=inner,
            limiter=FakeLimiter(), recorder=FakeRecorder(),
            clock=FakeClock())
        ctrl = _controller(db, machinery, store)
        task_id = _admit_search(db)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(task_id) is TaskStatus.SUCCEEDED
        assert _interactions(db, task_id) == []

    def test_failure_recorded_honestly(self, db, tmp_path):
        store = _store(db, tmp_path)
        err = ProviderError("timeout", provider_id=PROVIDER,
                            hazard_class="TIMEOUT")
        inner = ScriptedTransport([err, err, err, err, err, err])
        machinery = _machinery(inner, db=db, store=store)
        ctrl = _controller(db, machinery, store)
        task_id = _admit_search(db)
        ctrl.run(max_ticks=8)
        rows = _interactions(db, task_id)
        assert len(rows) >= 1
        assert all(r["outcome_kind"] == "RECORDED_FAILURE" for r in rows)
        assert rows[0]["failure_class"] == "ProviderError"
        # Failure is a failure: no successful empty outcome substituted.
        status = TaskRepository(db).get_status(task_id)
        assert status is not TaskStatus.SUCCEEDED

    def test_secret_bearing_query_redacted(self, db, tmp_path):
        store = _store(db, tmp_path)
        inner = ScriptedTransport([_ok_response()])
        machinery = _machinery(inner, db=db, store=store)
        ctrl = _controller(db, machinery, store)
        task_id = _admit_search(db, topic="token=SECRET-VALUE-XYZ")
        ctrl.run(max_ticks=8)
        rows = _interactions(db, task_id)
        assert len(rows) >= 1
        blob = json.dumps([r["request_json"] for r in rows])
        assert "SECRET-VALUE-XYZ" not in blob

    def test_oversize_fails_loudly(self, db, tmp_path):
        store = _store(db, tmp_path)
        inner = ScriptedTransport([TransportResponse(
            status=200, body=b"x" * 100, headers={},
            content_type="application/json")])
        machinery = _machinery(inner, db=db, store=store)
        # Shrink the recording cap below the body (live fetch caps are
        # separate — this is the recording boundary).
        machinery.transport._max_body_bytes = 10
        ctrl = _controller(db, machinery, store)
        task_id = _admit_search(db)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(task_id) is TaskStatus.FAILED
        assert _interactions(db, task_id) == []

    def test_retry_records_idempotently(self, db, tmp_path):
        store = _store(db, tmp_path)
        inner = ScriptedTransport([
            TransportResponse(status=429, body=b"{}", headers={},
                              content_type="application/json"),
            _ok_response(),
        ])
        machinery = _machinery(inner, db=db, store=store)
        ctrl = _controller(db, machinery, store)
        task_id = _admit_search(db)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(task_id) is TaskStatus.SUCCEEDED
        # The retried request produced two distinct outcomes (429 then
        # 200): both attempts are recorded honestly as separate rows.
        rows = _interactions(db, task_id)
        assert len(rows) == 2
        assert {r["response_status_class"] for r in rows} == {"HTTP_429", "HTTP_200"}
        # Byte-identical re-persist converges idempotently (no dup rows,
        # no crash) — the duplicate=True path for identical retries.
        from hermes.persistence.provider_interactions import persist_interaction
        from hermes.tools.providers.replay import RecordedInteraction
        first = [r for r in rows
                 if r["response_status_class"] == "HTTP_200"][0]
        repeat = RecordedInteraction(
            interaction_id=first["interaction_id"],
            provider_id=first["provider_id"],
            adapter_version=first["adapter_version"],
            parser_version=first["parser_version"],
            normalized_request=json.loads(first["request_json"]),
            request_hash=first["normalized_request_hash"],
            status_class=first["response_status_class"],
            response_body_hash=first["response_body_hash"],
            outcome_kind=first["outcome_kind"],
            failure_class=first["failure_class"],
            retrieved_at=first["retrieved_at"],
            source_url_redacted=first["source_url_redacted"],
            task_id=task_id, project_id="p1")
        rid = persist_interaction(
            db, FakeClock(), store, repeat, _ok_response().body,
            project_id="p1", task_id=task_id)
        assert rid == first["interaction_id"]
        assert len(_interactions(db, task_id)) == 2


# ═══════════════════════ replay through production handlers ═══════════════════════


def _record_corpus(db, tmp_path):
    """Drive one recording run; return fixtures built from persisted rows."""
    from hermes.tools.providers.replay import interaction_to_fixture
    store = _store(db, tmp_path)
    inner = ScriptedTransport([_ok_response()])
    machinery = _machinery(inner, db=db, store=store)
    ctrl = _controller(db, machinery, store)
    task_id = _admit_search(db)
    ctrl.tick()
    assert TaskRepository(db).get_status(task_id) is TaskStatus.SUCCEEDED
    fixtures = {}
    for row in ProviderInteractionRepository(db).list_for_task(task_id):
        body = store.read(row["response_body_hash"])
        fixture = interaction_to_fixture(
            _row_to_interaction(row), body, headers={}, status=200)
        fixtures[fixture.fixture_id] = fixture
    assert fixtures
    return fixtures


def _row_to_interaction(row):
    from hermes.tools.providers.replay import RecordedInteraction
    return RecordedInteraction(
        interaction_id=row["interaction_id"],
        provider_id=row["provider_id"],
        adapter_version=row["adapter_version"],
        parser_version=row["parser_version"],
        normalized_request=json.loads(row["request_json"]),
        request_hash=row["normalized_request_hash"],
        status_class=row["response_status_class"],
        response_body_hash=row["response_body_hash"],
        outcome_kind=row["outcome_kind"],
        failure_class=row["failure_class"],
        retrieved_at=row["retrieved_at"],
        source_url_redacted=row["source_url_redacted"])


class TestReplayPath:
    def test_replay_deterministic_no_live_contact(self, db, tmp_path):
        fixtures = _record_corpus(db, tmp_path)
        # Fresh project/task replays the recorded corpus.
        store = _store(db, tmp_path)
        inner = RefusingTransport()
        machinery = _machinery(inner, db=db, store=store, mode="replay",
                               fixtures=fixtures)
        ctrl = _controller(db, machinery, store)
        task_id = _admit_search(db)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(task_id) is TaskStatus.SUCCEEDED
        assert inner.contacted == 0
        arts = db.execute(
            "SELECT artifact_id, content_hash FROM artifacts "
            "WHERE artifact_type = 'source_result' "
            "ORDER BY artifact_id ASC").fetchall()
        assert len(arts) >= 1

    def test_replay_matches_recorded_artifacts(self, db, tmp_path):
        fixtures = _record_corpus(db, tmp_path)
        before = sorted(
            r["content_hash"] for r in db.execute(
                "SELECT content_hash FROM artifacts "
                "WHERE artifact_type = 'source_result'").fetchall())
        store = _store(db, tmp_path)
        inner = RefusingTransport()
        machinery = _machinery(inner, db=db, store=store, mode="replay",
                               fixtures=fixtures)
        ctrl = _controller(db, machinery, store)
        task_id = _admit_search(db)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(task_id) is TaskStatus.SUCCEEDED
        assert inner.contacted == 0
        after = sorted(
            r["content_hash"] for r in db.execute(
                "SELECT content_hash FROM artifacts "
                "WHERE artifact_type = 'source_result'").fetchall())
        # Content-addressed dedup: replay reproduces identical artifacts.
        assert set(after) == set(before)

    def test_replay_missing_fixture_fails_closed(self, db, tmp_path):
        store = _store(db, tmp_path)
        inner = RefusingTransport()
        machinery = _machinery(inner, db=db, store=store, mode="replay",
                               fixtures={})
        ctrl = _controller(db, machinery, store)
        task_id = _admit_search(db)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(task_id) is not TaskStatus.SUCCEEDED
        assert inner.contacted == 0


# ═══════════════════════ isolation / linkage / drift ═══════════════════════


class TestIsolationLinkage:
    def test_cross_project_row_isolation(self, db, tmp_path):
        store = _store(db, tmp_path)
        inner = ScriptedTransport([_ok_response()])
        machinery = _machinery(inner, db=db, store=store)
        ctrl = _controller(db, machinery, store)
        task_id = _admit_search(db, project_id="p1")
        ctrl.run(max_ticks=8)
        repo = ProviderInteractionRepository(db)
        assert len(repo.list_for_task(task_id)) == 1
        # p2 tasks see nothing; p2-scoped reads of p1 rows miss.
        assert repo.list_for_task("t-p2-ghost") == []
        for row in repo.list_for_task(task_id):
            assert repo.get(row["interaction_id"], "p2") is None
            own = repo.get(row["interaction_id"], "p1")
            assert own is not None
            assert own["project_id"] == "p1"

    def test_replay_across_projects_links_locally(self, db, tmp_path):
        fixtures = _record_corpus(db, tmp_path)
        n_before = db.execute(
            "SELECT COUNT(*) c FROM provider_interactions").fetchone()["c"]
        store = _store(db, tmp_path)
        inner = RefusingTransport()
        machinery = _machinery(inner, db=db, store=store, mode="replay",
                               fixtures=fixtures)
        ctrl = _controller(db, machinery, store, project_id="p2")
        # A different query replays nothing (fixture miss is honest):
        # use the SAME query so the recorded bytes apply.
        task_id = _admit_search(db, project_id="p2")
        ctrl.run(max_ticks=8)
        # Byte-identical cross-project reuse hits the pre-existing
        # S6-B2 task-binding rule (identical outcome rows are shared
        # globally, never re-bound to the new task) — live execution
        # behaves identically (see test_identical_bytes_parity below),
        # so replay has parity with live: the FAILED status below is
        # the S6-B2 rule firing, and no live contact occurred.
        assert TaskRepository(db).get_status(task_id) is TaskStatus.FAILED
        assert inner.contacted == 0
        # Replay writes no interaction rows and touches no p1 state.
        assert db.execute(
            "SELECT COUNT(*) c FROM provider_interactions").fetchone()["c"] \
            == n_before

    def test_query_discriminating_replay_with_preserving_policy(
            self, db, tmp_path):
        # Default-deny redaction collapses query values (pre-existing
        # security posture — fixtures are then topic-blind). With an
        # explicitly query-preserving policy (credentials still
        # redacted by name), distinct topics replay distinctly: this
        # pins the policy/fidelity trade-off, not a default behavior.
        from hermes.tools.providers.redact import (
            DEFAULT_POLICY,
            RedactionPolicy,
        )
        policy = RedactionPolicy(
            credential_aliases=DEFAULT_POLICY.credential_aliases,
            polite_identifiers=DEFAULT_POLICY.polite_identifiers,
            default_deny=False)

        def _body(title):
            import copy
            page = copy.deepcopy(OPENALEX_PAGE)
            page["results"][0]["title"] = title
            return json.dumps(page).encode()

        store = _store(db, tmp_path)
        inner = ScriptedTransport([
            TransportResponse(status=200, body=_body("Alpha"), headers={},
                              content_type="application/json"),
            TransportResponse(status=200, body=_body("Beta"), headers={},
                              content_type="application/json"),
        ])
        machinery = _machinery(inner, db=db, store=store,
                               redaction_policy=policy)
        ctrl = _controller(db, machinery, store)
        ta = _admit_search(db, topic="alpha")
        tb = _admit_search(db, topic="beta")
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(ta) is TaskStatus.SUCCEEDED
        assert TaskRepository(db).get_status(tb) is TaskStatus.SUCCEEDED
        # Normalized forms preserve the distinct queries.
        norms = {
            r["interaction_id"]: json.loads(r["request_json"])
            for r in ProviderInteractionRepository(db).list_for_task(ta)}
        norms.update({
            r["interaction_id"]: json.loads(r["request_json"])
            for r in ProviderInteractionRepository(db).list_for_task(tb)})
        queries = {json.dumps(n["params"], sort_keys=True) for n in
                   norms.values()}
        assert len(queries) == 2
        # Replay beta's fixture under p2: new bytes, p2-owned rows,
        # zero live contact, p1 untouched.
        beta_rows = ProviderInteractionRepository(db).list_for_task(tb)
        fixtures = {}
        for row in beta_rows:
            body = store.read(row["response_body_hash"])
            fixture = interaction_to_fixture(
                _row_to_interaction(row), body, headers={}, status=200)
            fixtures[fixture.fixture_id] = fixture
        arts_before = db.execute(
            "SELECT COUNT(*) c FROM artifacts").fetchone()["c"]
        store2 = _store(db, tmp_path)
        refusing = RefusingTransport()
        machinery2 = _machinery(refusing, db=db, store=store2,
                                mode="replay", fixtures=fixtures,
                                redaction_policy=policy)
        ctrl2 = _controller(db, machinery2, store2, project_id="p2")
        t2 = _admit_search(db, project_id="p2", topic="beta")
        ctrl2.run(max_ticks=8)
        # Identical bytes replayed cross-project hit the shared outcome
        # rows (S6-B2, pre-existing) — the fixture HIT (zero live
        # contact proves it); only new bytes would bind new rows.
        assert TaskRepository(db).get_status(t2) is TaskStatus.FAILED
        assert refusing.contacted == 0
        reasons = " ".join(
            r["reason"] for r in db.execute(
                "SELECT reason FROM events WHERE event_type = ? "
                "ORDER BY event_id DESC LIMIT 4",
                ("TaskStatusChanged",)).fetchall())
        assert "zero-row" in reasons
        assert db.execute(
            "SELECT COUNT(*) c FROM artifacts").fetchone()["c"] \
            == arts_before

    def test_identical_bytes_parity_live_vs_replay(self, db, tmp_path):
        # Pre-existing S6-B2 × content-dedup interaction (NOT P4
        # behavior): byte-identical cross-project outcomes are shared
        # globally and never re-bound, so the second project fails
        # S6-B2 — identically for live and replayed execution. This
        # test pins the parity (replay must behave EXACTLY like live).
        store = _store(db, tmp_path)
        inner = ScriptedTransport([_ok_response(), _ok_response()])
        machinery = ProviderMachinery(
            adapters={PROVIDER: OpenalexAdapter()}, transport=inner,
            limiter=FakeLimiter(), recorder=FakeRecorder(),
            clock=FakeClock())
        ctrl = _controller(db, machinery, store)
        t1 = _admit_search(db, project_id="p1")
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(t1) is TaskStatus.SUCCEEDED
        ctrl2 = _controller(db, machinery, store, project_id="p2")
        t2 = _admit_search(db, project_id="p2")
        ctrl2.run(max_ticks=8)
        live_status = TaskRepository(db).get_status(t2)
        # Replay path, same bytes, fresh project/task:
        fixtures = {}
        for row in ProviderInteractionRepository(db).list_for_task(t1):
            body = store.read(row["response_body_hash"])
            fixture = interaction_to_fixture(
                _row_to_interaction(row), body, headers={}, status=200)
            fixtures[fixture.fixture_id] = fixture
        store2 = _store(db, tmp_path)
        refusing = RefusingTransport()
        machinery2 = _machinery(refusing, db=db, store=store2,
                                mode="replay", fixtures=fixtures)
        ctrl3 = _controller(db, machinery2, store2, project_id="p2")
        t3 = _admit_search(db, project_id="p2")
        ctrl3.run(max_ticks=8)
        assert TaskRepository(db).get_status(t3) is live_status
        assert refusing.contacted == 0

    def test_task_linkage_bound_at_dispatch(self, db, tmp_path):
        store = _store(db, tmp_path)
        inner = ScriptedTransport([_ok_response(), _ok_response()])
        machinery = _machinery(inner, db=db, store=store)
        ctrl = _controller(db, machinery, store)
        t1 = _admit_search(db, topic="alpha")
        t2 = _admit_search(db, topic="beta")
        ctrl.run(max_ticks=8)
        ctrl.run(max_ticks=8)
        rows1 = _interactions(db, t1)
        rows2 = _interactions(db, t2)
        assert rows1 and all(r["task_id"] == t1 for r in rows1)
        # t2 may or may not have dispatched yet; whatever it recorded
        # is bound to t2 alone.
        assert all(r["task_id"] == t2 for r in rows2)
        assert {r["interaction_id"] for r in rows1}.isdisjoint(
            {r["interaction_id"] for r in rows2})


# ═══════════════════════ fetch path through production handlers ═══════════════════════


def _admit_fetch(db, search_task_id, *, project_id="p1"):
    refs = [
        "source_result:" + r["content_hash"] for r in db.execute(
            "SELECT content_hash FROM artifacts "
            "WHERE artifact_type = 'source_result' "
            "ORDER BY content_hash ASC").fetchall()]
    assert refs, "search must have persisted source_result rows first"
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id=project_id,
        payload=build_source_fetch_task_payload(
            search_task_id, refs, provider=PROVIDER)))
    return result.entity_id


class TestFetchPath:
    def test_fetch_records_interaction(self, db, tmp_path):
        store = _store(db, tmp_path)
        inner = ScriptedTransport([
            _ok_response(),
            TransportResponse(status=200, body=FULL_TEXT,
                              headers={},
                              content_type="text/plain"),
        ])
        machinery = _machinery(inner, db=db, store=store)
        ctrl = _controller(db, machinery, store)
        search_id = _admit_search(db)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(search_id) is TaskStatus.SUCCEEDED
        fetch_id = _admit_fetch(db, search_id)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(fetch_id) is TaskStatus.SUCCEEDED
        rows = _interactions(db, fetch_id)
        assert len(rows) >= 1
        assert all(r["task_id"] == fetch_id for r in rows)
        assert all(r["outcome_kind"] == "RECORDED_SUCCESS" for r in rows)
        # Fetch payload artifacts persisted through the existing path.
        payloads = db.execute(
            "SELECT COUNT(*) c FROM artifacts "
            "WHERE artifact_type = 'source_payload'").fetchone()["c"]
        assert payloads >= 1

    def test_fetch_replay_deterministic_no_live_contact(self, db, tmp_path):
        store = _store(db, tmp_path)
        inner = ScriptedTransport([
            _ok_response(),
            TransportResponse(status=200, body=FULL_TEXT,
                              headers={},
                              content_type="text/plain"),
        ])
        machinery = _machinery(inner, db=db, store=store)
        ctrl = _controller(db, machinery, store)
        search_id = _admit_search(db)
        ctrl.run(max_ticks=8)
        fetch_id = _admit_fetch(db, search_id)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(fetch_id) is TaskStatus.SUCCEEDED
        payload_hashes = sorted(
            r["content_hash"] for r in db.execute(
                "SELECT content_hash FROM artifacts "
                "WHERE artifact_type = 'source_payload'").fetchall())
        assert payload_hashes
        # Fresh database replays both fixtures deterministically.
        conn2 = connect(":memory:")
        migrate_to_latest(conn2)
        ProjectRepository(conn2, frozen_clock(CLOCK)).create("p1", "Test")
        store2 = _store(conn2, tmp_path)
        fixtures = {}
        for row in ProviderInteractionRepository(db).list_for_task(fetch_id):
            body = store.read(row["response_body_hash"])
            fixture = interaction_to_fixture(
                _row_to_interaction(row), body, headers={}, status=200)
            fixtures[fixture.fixture_id] = fixture
        search_rows = ProviderInteractionRepository(db).list_for_task(
            search_id)
        for row in search_rows:
            body = store.read(row["response_body_hash"])
            fixture = interaction_to_fixture(
                _row_to_interaction(row), body, headers={}, status=200)
            fixtures[fixture.fixture_id] = fixture
        refusing = RefusingTransport()
        machinery2 = _machinery(refusing, db=conn2, store=store2,
                                mode="replay", fixtures=fixtures)
        ctrl2 = _controller(conn2, machinery2, store2)
        search2 = _admit_search(conn2)
        ctrl2.run(max_ticks=8)
        assert TaskRepository(conn2).get_status(search2) is TaskStatus.SUCCEEDED
        # The replayed search reproduces identical source refs, so the
        # fetch task binds identically and replays its own fixture.
        fetch2 = _admit_fetch(conn2, search2)
        ctrl2.run(max_ticks=8)
        assert TaskRepository(conn2).get_status(fetch2) is TaskStatus.SUCCEEDED
        assert refusing.contacted == 0
        replayed_hashes = sorted(
            r["content_hash"] for r in conn2.execute(
                "SELECT content_hash FROM artifacts "
                "WHERE artifact_type = 'source_payload'").fetchall())
        assert replayed_hashes == payload_hashes
        conn2.close()
