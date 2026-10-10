"""P-AUTO-3 live fetch wiring tests (OpenAlex + PubMed, D5).

Three layers, never conflated:

1. **Hermetic replay (always green, offline):** the recorded fixtures in
   ``tests/fixtures/p_auto_3_live/{openalex,pubmed}.json`` were captured
   from REAL live end-to-end runs (search → fetch per provider through
   the Controller). Replay mode serves them through a REFUSING inner
   transport — the live provider is never contacted, and the run
   reproduces the recorded bytes exactly (transport + evidence replay).

2. **Wiring unit tests (always green, offline):** the sanitized-egress
   allowlist refuses every scheme/host outside the two providers; the
   rate-limiter persistence decision is pinned (in-memory, resets on
   restart — ACCEPTABLE per the P-AUTO-3 charter, stated + tested); the
   OpenAlex fetch-URL rewrite targets the API host.

3. **Live tests (marked ``live_fetch``, skippable offline):** one real
   end-to-end search + fetch per provider through allowlist + envelope +
   journal — the roadmap gate (d). Skipped when the network is
   unreachable or ``HERMES_SKIP_LIVE_FETCH`` is set.

No credentials anywhere. No new dependencies.
"""
from __future__ import annotations

import dataclasses
import io
import json
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

import hermes.tools.providers.http as http_module
from hermes.artifacts.store import ArtifactStore
from hermes.config import SandboxPolicy
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
from hermes.persistence.source_outcomes import SourceOutcomeRepository
from hermes.research.controller import Controller
from hermes.research.gateway import apply_intent
from hermes.research.live_fetch import (
    ALLOWLIST_HOSTS,
    RATE_LIMITER_PERSISTENCE,
    allowlist_from_config,
    build_live_fetch_wiring,
)
from hermes.research.source_handlers import (
    DEFAULT_OVERALL_DEADLINE_SECONDS,
    SourcePolicy,
    UntrustedContent,
    UntrustedContentView,
)
from hermes.research.source_templates import (
    build_source_fetch_task_payload,
    build_source_search_task_payload,
)
from hermes.tools.providers.adapters.pubmed import PubmedAdapter
from hermes.tools.providers.base import (
    PageState,
    RateProfile,
    RequestSpec,
    WalkRequest,
)
from hermes.tools.providers.http import ProviderHTTPTransport
from hermes.tools.providers.normalize import RetrievalHints
from hermes.tools.providers.paginate import fetch_batch, walk
from hermes.tools.providers.ratelimit import ProviderRateLimiter
from hermes.tools.providers.replay import (
    RecordedTransport,
    ReplayUnavailableError,
    load_fixtures,
    provider_resolver_for,
)
from hermes.tools.research_sources import (
    FetchRequest,
    ProviderValidationError,
    RetryPolicy,
    SearchResult,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
TOPIC = "CRISPR"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "p_auto_3_live"
PROVIDERS = ("openalex", "pubmed")


# ═══════════════════ fakes / helpers ═══════════════════


class RefusingTransport:
    """Replay's inner transport — live contact is ALWAYS a failure."""

    def __init__(self) -> None:
        self.contacted = 0

    def request(self, spec):
        self.contacted += 1
        raise AssertionError(f"live provider contacted: {spec.url!r}")


class Clock:
    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, delay: float) -> None:
        return None


@pytest.fixture
def db(tmp_path):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create("p1", "Test")
    yield conn
    conn.close()


def _store(db, tmp_path):
    return ArtifactStore(
        str(tmp_path / "store"),
        ArtifactRepository(db, lambda: CLOCK),
        clock=lambda: CLOCK)


def _public_resolve(host: str) -> tuple[str, ...]:
    """Hermetic DNS stub: one public address, no real resolution."""
    return ("93.184.216.34",)


def _wiring(db, store, *, mode="replay", fixtures=None, dns_resolve=None):
    """Build the production wiring; in replay mode swap the inner
    transport for a refusing one (zero live contact, byte-identical
    results). Unit (non-live) wiring uses a public-IP DNS stub so the
    P-AUTO-4 DNS guard stays hermetic offline (no real resolution).

    FIX-USERINFO: ``dns_resolve`` reaches the ``mode="live"`` wiring too.
    A unit test that drives the live gate must inject a stub, otherwise the
    gate resolves for real and the suite silently depends on DNS. The
    marked ``live_fetch`` end-to-end tests leave it None (real resolution
    is the point of those tests)."""
    if mode == "live":
        return build_live_fetch_wiring(db, store, lambda: CLOCK,
                                       dns_resolve=dns_resolve)
    import dataclasses

    live = build_live_fetch_wiring(db, store, lambda: CLOCK,
                                   dns_resolve=dns_resolve or _public_resolve)
    refusing = RefusingTransport()
    replay = RecordedTransport(
        refusing,
        resolve_provider=provider_resolver_for(live.adapters),
        clock=Clock(),
        mode="replay",
        fixtures=fixtures or {},
    )
    machinery = dataclasses.replace(live.machinery, transport=replay)
    handlers = dict(live.handlers)
    from hermes.research.source_handlers import (
        make_source_fetch_handler,
        make_source_search_handler,
    )

    handlers["source_search"] = make_source_search_handler(machinery)
    handlers["source_fetch"] = make_source_fetch_handler(machinery)
    return dataclasses.replace(
        live, transport=replay, machinery=machinery, handlers=handlers)


def _controller(db, wiring, store):
    return Controller(
        db, project_id="p1", task_handlers=wiring.handlers,
        artifact_store=store, clock=lambda: CLOCK)


def _admit_search(db, provider):
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload=build_source_search_task_payload(
            provider,
            {"identifiers": {}, "topic": TOPIC, "mode": "TOPIC",
             "unrecognized_hints": []},
            scope_ref="p1", page_size=5, max_pages=1)))
    return result.entity_id


def _refs_for(db, search_task_id):
    results = SourceOutcomeRepository(db).load_search_results(search_task_id)
    return ["source_result:" + r.content_hash for r in results[:2]]


def _admit_fetch(db, search_task_id, provider, refs):
    result = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload=build_source_fetch_task_payload(
            search_task_id, refs, provider=provider,
            max_sources=2, size_cap_bytes=1024 * 1024)))
    return result.entity_id


def _interactions(db, task_id):
    return ProviderInteractionRepository(db).list_for_task(task_id)


# ═══════════════════ 1. hermetic replay (offline, always) ═══════════════════


@pytest.mark.parametrize("provider", PROVIDERS)
class TestHermeticReplay:
    """The recorded live corpus replays deterministically with zero
    network contact — the P-AUTO-3 evidence replay layer."""

    def _fixtures(self, provider):
        if not FIXTURES.exists():
            pytest.skip("recorded live fixtures not present")
        corpus = load_fixtures(str(FIXTURES / f"{provider}.json"))
        assert corpus, "empty fixture corpus"
        return corpus

    def test_search_replays_without_live_contact(self, db, tmp_path,
                                                 provider):
        fixtures = self._fixtures(provider)
        store = _store(db, tmp_path)
        wiring = _wiring(db, store, mode="replay", fixtures=fixtures)
        ctrl = _controller(db, wiring, store)
        task_id = _admit_search(db, provider)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(task_id) is TaskStatus.SUCCEEDED
        inner = wiring.transport._inner
        assert inner.contacted == 0
        rows = _interactions(db, task_id)
        # Replay writes NO interaction rows (the pre-existing contract).
        assert rows == []
        # But the parsed outcome is real: source_result artifacts exist.
        arts = db.execute(
            "SELECT COUNT(*) c FROM artifacts "
            "WHERE artifact_type = 'source_result'").fetchone()["c"]
        assert arts >= 1

    def test_fetch_replays_without_live_contact(self, db, tmp_path,
                                                provider):
        fixtures = self._fixtures(provider)
        store = _store(db, tmp_path)
        wiring = _wiring(db, store, mode="replay", fixtures=fixtures)
        ctrl = _controller(db, wiring, store)
        search_id = _admit_search(db, provider)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(search_id) is TaskStatus.SUCCEEDED
        refs = _refs_for(db, search_id)
        fetch_id = _admit_fetch(db, search_id, provider, refs)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(fetch_id) is TaskStatus.SUCCEEDED
        inner = wiring.transport._inner
        assert inner.contacted == 0
        payloads = db.execute(
            "SELECT COUNT(*) c FROM artifacts "
            "WHERE artifact_type = 'source_payload'").fetchone()["c"]
        assert payloads >= 1

    def test_replay_is_deterministic(self, db, tmp_path, provider):
        """Two replay runs over the same fixtures produce identical
        source_result content hashes (evidence replay)."""
        fixtures = self._fixtures(provider)
        hashes = []
        for _ in range(2):
            conn = connect(":memory:")
            migrate_to_latest(conn)
            ProjectRepository(conn, lambda: CLOCK).create("p1", "Test")
            store = ArtifactStore(
                str(tmp_path / f"store-{len(hashes)}"),
                ArtifactRepository(conn, lambda: CLOCK),
                clock=lambda: CLOCK)
            wiring = _wiring(conn, store, mode="replay", fixtures=fixtures)
            ctrl = _controller(conn, wiring, store)
            task_id = _admit_search(conn, provider)
            ctrl.run(max_ticks=8)
            assert TaskRepository(conn).get_status(
                task_id) is TaskStatus.SUCCEEDED
            hashes.append(sorted(
                r["content_hash"] for r in conn.execute(
                    "SELECT content_hash FROM artifacts "
                    "WHERE artifact_type = 'source_result'").fetchall()))
            conn.close()
        assert hashes[0] == hashes[1]

    def test_fetched_payload_is_readable_only_via_envelope(
            self, db, tmp_path, provider):
        """(b) the fetch path's persisted payload crosses the context
        boundary ONLY as UntrustedContent: the view accessor envelopes it,
        and the envelope's string forms never leak the payload."""
        fixtures = self._fixtures(provider)
        store = _store(db, tmp_path)
        wiring = _wiring(db, store, mode="replay", fixtures=fixtures)
        ctrl = _controller(db, wiring, store)
        search_id = _admit_search(db, provider)
        ctrl.run(max_ticks=8)
        refs = _refs_for(db, search_id)
        fetch_id = _admit_fetch(db, search_id, provider, refs)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(fetch_id) is TaskStatus.SUCCEEDED
        repo = SourceOutcomeRepository(db, store, lambda: CLOCK)
        view = UntrustedContentView(
            _load_search_results=repo.load_search_results,
            _read_payload=repo.read_payload_bytes)
        # Search free text is enveloped too (title/venue/query).
        results = view.search_results(search_id)
        assert results and all(
            isinstance(r.title, UntrustedContent) for r in results)
        # The fetched payload resolves only through the envelope.
        row = db.execute(
            "SELECT content_hash FROM artifacts "
            "WHERE artifact_type = 'source_payload' LIMIT 1").fetchone()
        assert row is not None
        env = view.fetched_text("source_payload:" + row["content_hash"])
        assert env is not None and env.origin == "fetched"
        assert env.text, "payload bytes never resolved"
        assert str(env) == repr(env), "str() must be the marker form"
        assert env.text not in str(env), "payload leaked through str()"


# ═══════════════════ 2. wiring unit tests (offline, always) ═══════════════════


class TestSanitizedEgress:
    def test_allowlist_covers_exactly_the_two_providers(self):
        # D5 — the two keyless APIs (+ each provider's own canonical
        # content host, the record source_url target). No third party.
        hosts = set(ALLOWLIST_HOSTS)
        assert hosts == {
            "api.openalex.org", "openalex.org",
            "eutils.ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov",
        }

    def test_non_allowlisted_host_refused_before_any_io(self, db, tmp_path):
        # The allowlist gate sits BETWEEN RecordedTransport and the HTTP
        # client in the live wiring — reached via transport._inner.
        store = _store(db, tmp_path)
        wiring = _wiring(db, store, mode="live", dns_resolve=_public_resolve)
        gate = wiring.transport._inner
        for url in ("http://api.openalex.org/works",        # wrong scheme
                    "https://evil.example.com/steal",       # unknown host
                    "https://api.crossref.org/works",       # another provider
                    # FIX-USERINFO — the audited userinfo bypass: the host
                    # is evil.example, not the allowlisted userinfo prefix
                    "https://api.openalex.org:foo@evil.example/works",
                    "https://api.openalex.org:8443/works",   # non-default port
                    ):
            with pytest.raises(ProviderValidationError):
                gate.request(RequestSpec(url=url, params={}, headers_meta={}))

    def test_allowlisted_request_passes_the_gate(self, db, tmp_path,
                                                 monkeypatch):
        from hermes.tools.providers.base import TransportResponse

        store = _store(db, tmp_path)
        # FIX-USERINFO: the gate resolves its host before dialing, so this
        # unit test injects the hermetic DNS stub (the marked live_fetch
        # tests are the only ones that touch real DNS).
        wiring = _wiring(db, store, mode="live",
                         dns_resolve=_public_resolve)
        gate = wiring.transport._inner
        seen = {}

        def fake_request(spec):
            seen["url"] = spec.url
            return TransportResponse(
                status=200, body=b"{}", headers={},
                content_type="application/json")

        monkeypatch.setattr(wiring.http_transport, "request", fake_request)
        resp = gate.request(RequestSpec(
            url="https://api.openalex.org/works", params={},
            headers_meta={}))
        assert resp.status == 200
        assert seen["url"] == "https://api.openalex.org/works"


class TestConfigAllowlistNarrowing:
    """``sandbox.network_egress_allowlist`` may only NARROW the code-owned
    D5 surface (config.py) — never widen it; empty config is the floor."""

    def test_absent_or_empty_config_is_the_code_owned_floor(self):
        assert allowlist_from_config(None) == ALLOWLIST_HOSTS
        assert allowlist_from_config(SandboxPolicy()) == ALLOWLIST_HOSTS
        assert allowlist_from_config(SandboxPolicy(
            network_egress_allowlist=[])) == ALLOWLIST_HOSTS

    def test_subset_narrows(self):
        narrowed = allowlist_from_config(SandboxPolicy(
            network_egress_allowlist=["api.openalex.org",
                                      "https://eutils.ncbi.nlm.nih.gov/"]))
        assert narrowed == ("api.openalex.org", "eutils.ncbi.nlm.nih.gov")

    def test_entry_outside_the_d5_surface_is_refused_loudly(self):
        with pytest.raises(ProviderValidationError):
            allowlist_from_config(SandboxPolicy(
                network_egress_allowlist=["evil.example.com"]))
        with pytest.raises(ProviderValidationError):
            allowlist_from_config(SandboxPolicy(
                network_egress_allowlist=["http://api.openalex.org"]))

    def test_narrowed_wiring_refuses_the_excluded_provider(
            self, db, tmp_path, monkeypatch):
        from hermes.tools.providers.base import TransportResponse

        store = _store(db, tmp_path)
        wiring = build_live_fetch_wiring(
            db, store, lambda: CLOCK,
            sandbox_policy=SandboxPolicy(
                network_egress_allowlist=["api.openalex.org"]),
            dns_resolve=lambda host: ("93.184.216.34",))

        def fake_request(spec):
            return TransportResponse(
                status=200, body=b"{}", headers={},
                content_type="application/json")

        monkeypatch.setattr(wiring.http_transport, "request", fake_request)
        gate = wiring.transport._inner
        resp = gate.request(RequestSpec(
            url="https://api.openalex.org/works", params={},
            headers_meta={}))
        assert resp.status == 200
        with pytest.raises(ProviderValidationError):
            gate.request(RequestSpec(
                url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={}, headers_meta={}))


class TestRateLimiterPersistenceDecision:
    def test_decision_is_recorded_in_memory_acceptable(self):
        # (c) the charter decision: in-memory, resets on restart —
        # ACCEPTABLE for this slice, stated as a module constant and
        # pinned here so the decision cannot silently change.
        assert "in-memory" in RATE_LIMITER_PERSISTENCE
        assert "restart" in RATE_LIMITER_PERSISTENCE

    def test_limiter_state_resets_on_restart(self, db, tmp_path):
        # Two wirings (== two process lifetimes) share nothing: a fresh
        # limiter starts with a full token bucket and a zeroed daily cap.
        # E2 (P-AUTO-3 redteam): the OLD test drained the production
        # daily_cap=1000 at 5 rps against wall-clock time (~200s of
        # admission waits) and hung. The restart boundary is a
        # per-instance fact — pin it with a small-cap profile and the
        # frozen clock (burst == cap): the drain completes in two grants,
        # no wall-clock waits, no real-time drain.
        store = _store(db, tmp_path)
        first = build_live_fetch_wiring(
            db, store, lambda: CLOCK,
            dns_resolve=lambda host: ("93.184.216.34",))
        second = build_live_fetch_wiring(
            db, store, lambda: CLOCK,
            dns_resolve=lambda host: ("93.184.216.34",))
        assert first.limiter is not second.limiter

        profiles = {"openalex": RateProfile(
            rps=1000.0, burst=2, concurrency=1, daily_cap=2)}
        drained = ProviderRateLimiter(profiles, Clock())
        for _ in range(2):
            granted, reason = drained.acquire("openalex")
            assert granted and reason == ""
            drained.release("openalex")
        granted, reason = drained.acquire("openalex")
        assert not granted, "expected the small daily cap to be drained"
        assert reason == "daily_cap_exhausted"

        fresh = ProviderRateLimiter(profiles, Clock())
        granted, reason = fresh.acquire("openalex")
        assert granted and reason == ""
        fresh.release("openalex")


class TestOpenAlexFetchRewrite:
    def test_canonical_record_url_rewrites_to_api_host(self, db, tmp_path):
        from types import SimpleNamespace

        store = _store(db, tmp_path)
        wiring = _wiring(db, store)
        adapter = wiring.adapters["openalex"]
        spec = adapter.build_fetch_request(SimpleNamespace(
            source_url="https://openalex.org/W2060313932"))
        assert spec.url == "https://api.openalex.org/W2060313932"

    def test_missing_url_refused(self, db, tmp_path):
        from types import SimpleNamespace

        store = _store(db, tmp_path)
        wiring = _wiring(db, store)
        with pytest.raises(ProviderValidationError):
            wiring.adapters["openalex"].build_fetch_request(
                SimpleNamespace(source_url=""))


# ═══════════════════ 2b. redirect refusal (A1 regression) ═══════════════════


def _fake_source(result_id: str, *, source_url: str | None = None):
    """A minimal SearchResult for the driver-level deadline tests."""
    return SearchResult(
        result_id=result_id,
        provider="fake",
        endpoint="fulltext",
        query="",
        request_params_redacted={},
        identifiers={},
        title="A paper",
        authors=(),
        year=None,
        venue="",
        abstract_sha256=None,
        source_url=source_url or f"https://provider/{result_id}",
        access_timestamp_utc=CLOCK,
        page_index=0,
        cursor_key=None,
        raw_retrieved_count=1,
        delivered_count=1,
        total_count=1,
        total_is_estimate=False,
        reconciliation="COMPLETE",
        content_hash="",
        provenance={},
    )


class _ExpiredClock:
    """A clock whose every monotonic reading is past a test deadline."""

    def now_utc(self) -> str:
        return CLOCK

    def monotonic(self) -> float:
        return 1_000_000.0

    def sleep(self, delay: float) -> None:
        return None


def _message(headers: dict[str, str]) -> Message:
    msg = Message()
    for key, value in headers.items():
        msg[key] = value
    return msg


class _ScriptedResponse:
    """A minimal urllib-shaped response for the opener chain (no sockets)."""

    def __init__(self, url: str, status: int,
                 headers: dict[str, str], body: bytes) -> None:
        self.url = url
        self.code = status
        self.status = status
        self.msg = ""
        self.headers = _message(headers)
        self._stream = io.BytesIO(body)

    def read(self, amount: int = -1) -> bytes:
        return self._stream.read(amount)

    def info(self) -> Message:
        return self.headers

    def geturl(self) -> str:
        return self.url

    def close(self) -> None:
        self._stream.close()


class _ScriptedHTTPSHandler(urllib.request.HTTPSHandler):
    """Serves scripted responses by full URL — the TLS leg is faked.

    Subclassing HTTPSHandler makes ``build_opener`` drop its default one, so
    the transport's real opener never opens a socket in these tests.
    """

    def __init__(self, script: dict[str, tuple[int, dict[str, str], bytes]]) -> None:
        super().__init__()
        self.script = dict(script)
        self.requested: list[str] = []

    def https_open(self, req: urllib.request.Request) -> Any:
        self.requested.append(req.full_url)
        entry = self.script.get(req.full_url)
        if entry is None:
            raise AssertionError(
                f"unscripted request issued: {req.full_url!r}")
        status, headers, body = entry
        return _ScriptedResponse(req.full_url, status, headers, body)


class TestRedirectRefusal:
    """A1 (MUST-FIX) regression — every 3xx hop is re-vetted against the
    request's own https origin; anything else is refused by returning the
    3xx status (never chased, never a second connection)."""

    def _script(self, monkeypatch, script):
        handler = _ScriptedHTTPSHandler(script)
        monkeypatch.setattr(
            http_module, "_OPENER", http_module._build_opener(handler))
        return handler

    def test_redirect_to_evil_fixture_is_refused(self, monkeypatch):
        fixture = json.loads(
            (FIXTURES / "redirect_evil.json").read_text(encoding="utf-8"))
        initial = fixture["initial_url"]
        evil = fixture["evil_location"]
        assert "evil.example.com" in evil
        handler = self._script(monkeypatch, {
            initial: (302, {"Location": evil}, b""),
            evil: (200, {"Content-Type": "text/html"}, b"stolen"),
        })
        resp = ProviderHTTPTransport().request(RequestSpec(
            url=initial, params={}, headers_meta={}))
        assert resp.status == 302, (
            "a refused redirect must surface its 3xx status for the evaluator")
        assert resp.headers.get("Location") == evil
        assert handler.requested == [initial], (
            f"the off-origin hop was contacted: {handler.requested}")

    def test_same_origin_https_hop_is_followed(self, monkeypatch):
        initial = "https://api.openalex.org/works"
        final = "https://api.openalex.org/works/next"
        handler = self._script(monkeypatch, {
            initial: (302, {"Location": final}, b""),
            final: (200, {"Content-Type": "application/json"}, b'{"ok":true}'),
        })
        resp = ProviderHTTPTransport().request(RequestSpec(
            url=initial, params={}, headers_meta={}))
        assert resp.status == 200
        assert resp.body == b'{"ok":true}'
        assert handler.requested == [initial, final]

    def test_downgrade_and_foreign_port_are_refused(self, monkeypatch):
        initial = "https://api.openalex.org/works"
        for location in ("http://api.openalex.org/works",
                         "https://api.openalex.org:8443/works"):
            handler = self._script(monkeypatch, {
                initial: (302, {"Location": location}, b""),
                location: (200, {"Content-Type": "text/html"}, b"stolen"),
            })
            resp = ProviderHTTPTransport().request(RequestSpec(
                url=initial, params={}, headers_meta={}))
            assert resp.status == 302, location
            assert handler.requested == [initial], location

    def test_production_opener_installs_the_guard(self):
        # The module-level opener (the production path) must carry the
        # same-origin handler — a plain HTTPRedirectHandler would silently
        # re-open the A1 bypass.
        assert any(
            isinstance(h, http_module._SameOriginRedirectHandler)
            for h in http_module._OPENER.handlers)


# ═══════════════════ 2c. PubMed parser versioning (C1) ═══════════════════


class TestPubMedParserVersioning:
    """C1 (SHOULD-FIX) — the PubMed parse path is versioned, so a pre-bump
    fixture can never silently replay under the new parser."""

    def test_adapter_parser_version_bumped(self):
        assert PubmedAdapter.parser_version == "2"
        assert PubmedAdapter.adapter_version == "1"

    def test_recorded_corpus_pins_the_versioned_parser(self):
        corpus = load_fixtures(str(FIXTURES / "pubmed.json"))
        assert corpus
        assert {f.parser_version for f in corpus.values()} == {
            PubmedAdapter.parser_version}

    def test_v1_pinned_fixture_refused_not_silently_replayed(self):
        corpus = load_fixtures(str(FIXTURES / "pubmed.json"))
        fid = sorted(corpus)[0]
        stale = dataclasses.replace(corpus[fid], parser_version="1")
        transport = RecordedTransport(
            RefusingTransport(),
            resolve_provider=provider_resolver_for({"pubmed": PubmedAdapter()}),
            clock=Clock(), mode="replay", fixtures={fid: stale})
        adapter = PubmedAdapter()
        spec = adapter.build_request(
            RetrievalHints(identifiers={}, topic=TOPIC, mode="TOPIC",
                           unrecognized_hints=()),
            PageState(page_index=0), 5)
        with pytest.raises(ReplayUnavailableError) as exc:
            transport.request(spec)
        assert exc.value.hazard_class == "FIXTURE_INCOMPATIBLE"
        assert transport._inner.contacted == 0


# ═══════════════════ 2d. overall deadline (D1) ═══════════════════


class TestOverallDeadline:
    """D1 (SHOULD-FIX) — one dispatch (every search page / every fetch
    source) is bounded by an overall wall-clock deadline; an expired budget
    stops with a typed TRANSIENT verdict and issues no further request."""

    def test_policy_and_live_wiring_pin_the_bound(self, db, tmp_path):
        assert DEFAULT_OVERALL_DEADLINE_SECONDS > 0
        assert (SourcePolicy().overall_deadline_seconds
                == DEFAULT_OVERALL_DEADLINE_SECONDS)
        store = _store(db, tmp_path)
        wiring = _wiring(db, store)
        for name in ("source_search", "source_fetch"):
            policy = wiring.handlers[name].policy
            assert (policy.overall_deadline_seconds
                    == DEFAULT_OVERALL_DEADLINE_SECONDS)

    def test_expired_deadline_search_aborts_before_any_request(
            self, db, tmp_path):
        store = _store(db, tmp_path)
        live = build_live_fetch_wiring(db, store, lambda: CLOCK)
        refusing = RefusingTransport()
        outcome = walk(
            live.adapters["openalex"],
            RetrievalHints(identifiers={}, topic=TOPIC, mode="TOPIC",
                           unrecognized_hints=()),
            WalkRequest(max_results=5, max_pages=1, page_size_cap=100,
                        deadline_monotonic=999_999.0),
            transport=refusing,
            limiter=live.limiter,
            recorder=live.machinery.recorder,
            clock=_ExpiredClock(),
            hazard_spec=live.hazard_specs["openalex"],
        )
        assert refusing.contacted == 0, "a request was issued after the deadline"
        assert outcome.aggregate == "UNAVAILABLE"
        assert any("deadline_exhausted=true" in n for n in outcome.notes)

    def test_expired_deadline_fetch_fails_all_sources_without_requests(
            self, db, tmp_path):
        store = _store(db, tmp_path)
        live = build_live_fetch_wiring(db, store, lambda: CLOCK)
        refusing = RefusingTransport()
        outcome = fetch_batch(
            live.adapters["openalex"],
            [_fake_source("sr_deadline_a"), _fake_source("sr_deadline_b")],
            FetchRequest(max_sources=2, size_cap_bytes=1024,
                         retry_policy=RetryPolicy(max_retries=0),
                         deadline_monotonic=999_999.0),
            transport=refusing,
            limiter=live.limiter,
            recorder=live.machinery.recorder,
            clock=_ExpiredClock(),
            hazard_spec=live.hazard_specs["openalex"],
        )
        assert refusing.contacted == 0, "a request was issued after the deadline"
        assert outcome.aggregate == "FAILED"
        assert len(outcome.failed) == 2
        assert all(f.failure_class == "TRANSIENT" for f in outcome.failed)
        assert any("deadline exhausted" in n for n in outcome.notes)


# ═══════════════════ 3. live tests (marked, skippable offline) ═══════════════════


def _live_available() -> bool:
    import os
    import urllib.request

    if os.environ.get("HERMES_SKIP_LIVE_FETCH"):
        return False
    try:
        urllib.request.urlopen(
            "https://api.openalex.org/works?per-page=1", timeout=5)
        return True
    except Exception:  # noqa: BLE001 — any network failure skips live
        return False


@pytest.mark.live_fetch
class TestLiveEndToEnd:
    """(d) the gate: one REAL end-to-end fetch per provider through
    allowlist + envelope + journal. Skipped offline (network probe) or
    with HERMES_SKIP_LIVE_FETCH=1 — the hermetic layer above carries the
    same evidence deterministically."""

    @pytest.mark.parametrize("provider", PROVIDERS)
    def test_live_search_then_fetch_per_provider(self, db, tmp_path,
                                                 provider):
        if not _live_available():
            pytest.skip("live network unavailable (or skipped by env)")
        store = _store(db, tmp_path)
        wiring = _wiring(db, store, mode="live")
        ctrl = _controller(db, wiring, store)

        # SEARCH (live) — journaled interaction, UntrustedContent-envelope
        # surface downstream, sanitized egress allowlist enforced.
        search_id = _admit_search(db, provider)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(search_id) is TaskStatus.SUCCEEDED
        rows = _interactions(db, search_id)
        assert rows, "search interaction not journaled"
        assert all(r["provider_id"] == provider for r in rows)
        assert all(r["outcome_kind"] == "RECORDED_SUCCESS" for r in rows)
        assert all(r["task_id"] == search_id for r in rows)
        # The journal's request forms are redacted (never-logged params).
        for r in rows:
            assert "CRISPR" not in r["request_json"]

        # FETCH (live) — one real payload per provider through the same
        # allowlist + journal; payload bytes land as source_payload.
        refs = _refs_for(db, search_id)
        fetch_id = _admit_fetch(db, search_id, provider, refs)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(fetch_id) is TaskStatus.SUCCEEDED
        fetch_rows = _interactions(db, fetch_id)
        assert fetch_rows, "fetch interaction not journaled"
        assert all(r["task_id"] == fetch_id for r in fetch_rows)
        payloads = db.execute(
            "SELECT COUNT(*) c FROM artifacts "
            "WHERE artifact_type = 'source_payload'").fetchone()["c"]
        assert payloads >= 1

    @pytest.mark.parametrize("provider", PROVIDERS)
    def test_live_run_records_replay_fixtures(self, db, tmp_path,
                                              provider):
        """The live run's interactions convert to replay fixtures that
        load_fixtures accepts (the corpus layer stays regenerable)."""
        if not _live_available():
            pytest.skip("live network unavailable (or skipped by env)")
        store = _store(db, tmp_path)
        wiring = _wiring(db, store, mode="live")
        ctrl = _controller(db, wiring, store)
        search_id = _admit_search(db, provider)
        ctrl.run(max_ticks=8)
        assert TaskRepository(db).get_status(search_id) is TaskStatus.SUCCEEDED
        from hermes.tools.providers.replay import interaction_to_fixture

        fixtures = {}
        for row in _interactions(db, search_id):
            body = store.read(row["response_body_hash"])
            if body is None:
                continue
            from hermes.tools.providers.replay import RecordedInteraction

            interaction = RecordedInteraction(
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
                source_url_redacted=row["source_url_redacted"],
                content_type=row["content_type"],
                task_id=search_id, project_id="p1")
            fx = interaction_to_fixture(
                interaction, body, headers={}, status=200)
            fixtures[fx.fixture_id] = fx
        assert fixtures
        # Round-trip through the fixture loader (corrupt-free, hash-true).
        from hermes.tools.providers.replay import dump_fixtures

        path = tmp_path / f"{provider}-roundtrip.json"
        dump_fixtures(list(fixtures.values()), str(path))
        reloaded = load_fixtures(str(path))
        assert set(reloaded) == set(fixtures)
