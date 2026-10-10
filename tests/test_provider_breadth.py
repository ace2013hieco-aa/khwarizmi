"""IDR-046 O2-BUILD — commercial web-leg contract + hazard regression.

Covers the four new providers (brave/exa/tavily/searxng) and the additive
POST transport (D4):

- each shipped spec loads via `load_hazard_spec` with the D7 content
  (A3 second half);
- `walk` returns `NONE` for a golden success payload per vendor (A3);
- per vendor: `THROTTLED` on 429; `MALFORMED_200` when `required_fields`
  is missing; `EMPTY_RESULT` on an empty body; `NONE` on a zero-result
  body, which walks to `EMPTY` (never a `VALID_NEGATIVE` claim — A4/A9);
- the zero-delivered matrix rows hold per vendor: searched-zero →
  `EMPTY`, never-searched → `UNAVAILABLE` (A9);
- the shared adapter obligations (D8): `build_request` URL starts with
  `http`; `items_paths` includes `"items"`; no `extract_ids` override;
- credentials: no leg places a credential in `params`, `url`, or `body`;
  `headers_meta` is absent from every recorded interaction and fixture
  (A8);
- POST transport: `redact_body` edge policies; the redacted `"body"` key
  for POST specs only; two bodies differing anywhere produce two fixture
  ids; GET normalized form carries no body key (A7/A12(d));
- the HTTP POST wire path: `data=` + JSON `Content-Type`, params never
  sent; the closed method set refuses before I/O (D4/D6).
"""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

import hermes.tools.providers.http as http_module
from hermes.tools.providers.adapters import PROVIDER_REGISTRY
from hermes.tools.providers.base import (
    Page,
    PageState,
    RequestSpec,
    TransportResponse,
    WalkRequest,
)
from hermes.tools.providers.hazards import (
    HazardContext,
    HazardVerdict,
    ProviderHazardSpec,
    evaluate_hazards,
    load_hazard_spec,
)
from hermes.tools.providers.http import ProviderHTTPTransport
from hermes.tools.providers.normalize import (
    RetrievalHints,
    parse_query_hints,
)
from hermes.tools.providers.paginate import combine, walk
from hermes.tools.providers.redact import redact_body
from hermes.tools.providers.replay import (
    RecordedInteraction,
    RecordedTransport,
    fixture_id_of,
    interaction_to_fixture,
    normalized_request,
)
from hermes.tools.research_sources import (
    WEB_SEARCH_PROVIDERS,
    ProviderUnavailableError,
    ProviderValidationError,
    RedactionError,
    RequestLogRecord,
    RetrievalShortfallError,
)

SPEC_DIR = Path(__file__).resolve().parent.parent / "src" / "hermes" / "tools" / "providers" / "hazard_specs"

WEB_PROVIDERS = ["brave", "exa", "tavily", "searxng"]

GOLDEN: dict[str, dict] = {
    "brave": {"web": {"results": [
        {"title": "Epistemic compilers",
         "url": "https://example.com/epistemic",
         "description": "A study of epistemic compilers."}]}},
    "exa": {"results": [
        {"title": "Epistemic compilers",
         "url": "https://example.com/epistemic",
         "text": "A study of epistemic compilers."}]},
    "tavily": {"results": [
        {"title": "Epistemic compilers",
         "url": "https://example.com/epistemic",
         "content": "A study of epistemic compilers."}]},
    "searxng": {"results": [
        {"title": "Epistemic compilers",
         "url": "https://example.com/epistemic",
         "content": "A study of epistemic compilers."}],
        "number_of_results": 1},
}

ZERO_RESULT: dict[str, dict] = {
    "brave": {"web": {"results": []}},
    "exa": {"results": []},
    "tavily": {"results": []},
    "searxng": {"results": [], "number_of_results": 0},
}


# ── fakes (walk-test shape — self-contained per repo style) ──


class FakeTransport:
    """Serves a script of (status, payload) pages as JSON transport
    responses; records every spec for wire-form assertions."""

    def __init__(self, script: list[tuple[int, object]]) -> None:
        self._script = list(script)
        self.requests: list[RequestSpec] = []

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.requests.append(spec)
        status, payload = self._script.pop(0)
        if isinstance(payload, dict):
            raw = json.dumps(payload).encode("utf-8")
        elif isinstance(payload, str):
            raw = payload.encode("utf-8")
        else:
            raw = payload or b""
        return TransportResponse(status=status, body=raw, headers={},
                                 content_type="application/json")


class FakeLimiter:
    def acquire(self, provider: str) -> tuple[bool, str]:
        return True, ""

    def release(self, provider: str) -> None:
        pass

    def note_throttled(self, provider: str, retry_after: float | None) -> None:
        pass

    def last_denial_reason(self, provider: str) -> str:
        return ""


class FakeRecorder:
    def __init__(self) -> None:
        self.logs: list[RequestLogRecord] = []

    def record(self, log: RequestLogRecord) -> None:
        self.logs.append(log)


class FakeClock:
    def now_utc(self) -> str:
        return "2026-10-07T00:00:00Z"

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, delay: float) -> None:
        pass


def load_shipped(provider_id: str) -> ProviderHazardSpec:
    path = SPEC_DIR / f"{provider_id}.json"
    return load_hazard_spec(provider_id, json.loads(path.read_text(encoding="utf-8")))


def run_vendor_walk(provider_id: str, script: list[tuple[int, object]]):
    adapter = PROVIDER_REGISTRY[provider_id]()
    transport = FakeTransport(script)
    outcome = walk(adapter, parse_query_hints("epistemic compilers"),
                   WalkRequest(max_results=50), transport,
                   FakeLimiter(), FakeRecorder(), FakeClock())
    return outcome, adapter, transport


def evaluate(spec: ProviderHazardSpec, payload: object,
             status: int = 200) -> HazardVerdict:
    return evaluate_hazards(
        spec.provider_id, spec, payload,
        HazardContext(scope="SEARCH", status_code=status,  # type: ignore[arg-type]
                      request_params={}))


# ── A3: shipped specs load + walk returns NONE for a golden payload ──


@pytest.mark.parametrize("provider", WEB_PROVIDERS)
def test_shipped_spec_loads_with_d7_content(provider: str) -> None:
    spec = load_shipped(provider)
    assert spec.provider_id == provider
    assert provider in WEB_SEARCH_PROVIDERS
    # D7 required content: the drift sentinel per vendor shape.
    expected_required = {"brave": ("web", "web.results")}.get(
        provider, ("results",))
    assert tuple(spec.required_fields) == expected_required
    # 429 throttle declared for all four.
    assert any(sig.status == 429 for sig in spec.throttle_signature)
    # count-semantics matrix.
    if provider == "searxng":
        assert spec.count_semantics == "estimate"
        assert spec.counts_raw_rows is True
    else:
        assert spec.count_semantics == "absent"
        assert spec.counts_raw_rows is False
    # cursor rules.
    assert spec.cursor_rule.kind == (
        "offset" if provider in ("brave", "searxng") else "none")
    assert 1 <= spec.cursor_rule.loop_guard <= 1000
    # fetch null (no provider-declared full-text structure for web HTML).
    assert spec.fetch is None
    assert tuple(spec.valid_negative_statuses) == (404,)
    assert tuple(spec.content_types) == ("application/json",)
    assert list(spec.rewrite_suspect) == []


@pytest.mark.parametrize("provider", WEB_PROVIDERS)
def test_walk_golden_returns_none(provider: str) -> None:
    outcome, _adapter, _transport = run_vendor_walk(
        provider, [(200, GOLDEN[provider])])
    assert outcome.request_log is not None
    assert outcome.request_log.provider == provider
    assert outcome.request_log.hazard_verdicts == ("NONE",)


# ── A4: the hazard matrix per vendor ──


@pytest.mark.parametrize("provider", WEB_PROVIDERS)
def test_429_is_throttled(provider: str) -> None:
    assert evaluate(load_shipped(provider), GOLDEN[provider],
                    status=429).hazard_class == "THROTTLED"


@pytest.mark.parametrize("provider", WEB_PROVIDERS)
def test_missing_required_fields_is_malformed(provider: str) -> None:
    assert evaluate(load_shipped(provider), {"unrelated": 1},
                    status=200).hazard_class == "MALFORMED_200"


@pytest.mark.parametrize("provider", WEB_PROVIDERS)
def test_empty_body_is_empty_result(provider: str) -> None:
    assert evaluate(load_shipped(provider), b"",
                    status=200).hazard_class == "EMPTY_RESULT"


@pytest.mark.parametrize("provider", WEB_PROVIDERS)
def test_zero_result_body_is_none_never_valid_negative(provider: str) -> None:
    assert evaluate(load_shipped(provider), ZERO_RESULT[provider],
                    status=200).hazard_class == "NONE"
    outcome, _adapter, _transport = run_vendor_walk(
        provider, [(200, ZERO_RESULT[provider])])
    assert outcome.aggregate == "EMPTY"  # searched, found nothing
    assert all(not r.valid_negative for r in outcome.per_provider)
    with pytest.raises(RetrievalShortfallError) as exc:
        combine([outcome])
    assert exc.value.aggregate == "EMPTY"


# ── A9: the zero-delivered matrix rows per vendor ──


@pytest.mark.parametrize("provider", WEB_PROVIDERS)
def test_unsearched_zero_delivery_is_unavailable(provider: str) -> None:
    # Four 500s exhaust the default retry policy (3 retries + attempt 1):
    # TRANSIENT is never a classified response, so the leg never searched.
    outcome, _adapter, _transport = run_vendor_walk(
        provider, [(500, {"error": "boom"})] * 4)
    assert outcome.aggregate == "UNAVAILABLE"  # could not search
    with pytest.raises(ProviderUnavailableError):
        combine([outcome])


# ── D8: shared adapter obligations per vendor ──


@pytest.mark.parametrize("provider", WEB_PROVIDERS)
def test_adapter_contract_tables(provider: str) -> None:
    cls = PROVIDER_REGISTRY[provider]
    adapter = cls()
    assert adapter.provider_id == provider
    assert adapter.contract.provider_id == provider
    # No per-provider extract_ids override — the shared choke point owns it.
    assert "extract_ids" not in cls.__dict__
    hints: RetrievalHints = parse_query_hints("epistemic compilers")
    spec = adapter.build_request(hints, PageState(page_index=0), 10)
    assert spec.url.startswith("http")
    assert "Authorization" not in str(spec.params)
    # The shared-shape fallback parses on every leg.
    page = adapter.parse_page(
        {"items": [{"id": "x1", "title": "T",
                    "doi": "10.1234/abcdef"}]},
        PageState(page_index=0))
    assert page.records
    assert "items" in adapter.items_paths


@pytest.mark.parametrize("provider", WEB_PROVIDERS)
def test_no_credential_in_wire_forms(provider: str) -> None:
    # A8 — credentials appear only in headers_meta (deployment-injected),
    # never in params, url, or body; headers_meta never reaches a record.
    adapter = PROVIDER_REGISTRY[provider]()
    spec = adapter.build_request(parse_query_hints("epistemic compilers"),
                                 PageState(page_index=0), 10)
    assert spec.headers_meta == {}
    assert "api_key" not in spec.params and "token" not in spec.params
    body_text = bytes(spec.body).decode("utf-8") if spec.body else ""
    for secret_word in ("api_key", "apikey", "token", "secret", "auth"):
        assert secret_word not in body_text
        assert secret_word not in spec.url
    normalized = normalized_request(spec)
    assert "headers_meta" not in normalized
    assert "SECRET" not in json.dumps(normalized)


# ── D4 transport: redact_body edge policies ──


def test_redact_body_keeps_known_fields_and_scrubs_unknown_keys() -> None:
    # P1-4 — the vendor-declared fields keep their values (fixture identity
    # must distinguish same-shaped searches); an unknown key keeps the
    # frozen default-deny scrub.
    out = redact_body(
        b'{"query": "dark matter", "numResults": 10, "mystery": "x"}')
    assert out == {"query": "dark matter", "numResults": 10,
                   "mystery": "<redacted>"}


def test_redact_body_credential_and_polite_keys() -> None:
    out = redact_body(b'{"x-api-key": "SECRET", "email": "a@b.c"}')
    assert out == {"x-api-key": "<redacted>",
                   "email": "<redacted:email>"}
    assert "SECRET" not in json.dumps(out)


def test_redact_body_nested_and_list_values() -> None:
    out = redact_body(b'{"filter": {"token": "SECRET", "q": "x"}, '
                      b'"items": [{"key": "SECRET2"}]}')
    assert out == {"filter": "<redacted>", "items": "<redacted>"}
    assert "SECRET" not in json.dumps(out)


def test_redact_body_refuses_undecodable_never_hashes() -> None:
    for bad in (b"\x00\x01\x02 binary", b"{not json",
                b'{"unclosed": true', "not-bytes"):  # type: ignore[list-item]
        with pytest.raises(RedactionError) as exc:
            redact_body(bad)  # type: ignore[arg-type]
        assert "body" in str(exc.value)  # names the parameter …
        assert str(bad) not in str(exc.value)  # … never its value


def test_redact_body_refuses_empty() -> None:
    with pytest.raises(RedactionError):
        redact_body(b"")


# ── D4 transport: fixture identity with bodies (A7) ──


def _post_spec(body: bytes, url: str = "https://api.exa.ai/search",
               params: dict | None = None) -> RequestSpec:
    return RequestSpec(url=url, params=params or {}, headers_meta={},
                       method="POST", body=body)


def test_post_bodies_differing_anywhere_produce_two_fixture_ids() -> None:
    fid_a = fixture_id_of(
        "exa", normalized_request(_post_spec(b'{"query": "x"}')))
    fid_b = fixture_id_of(
        "exa", normalized_request(
            _post_spec(b'{"query": "x", "extra": "y"}')))
    assert fid_a != fid_b
    # Value-only variation (same keys, different values) -- the D4 failure
    # mode that was live pre-fix: every key that was not a credential alias
    # or polite identifier scrubbed to "<redacted>", so any two same-shaped
    # searches collapsed onto ONE fixture id (one recorded fixture would
    # have replayed the other search's bytes).
    fid_c = fixture_id_of(
        "exa", normalized_request(
            _post_spec(b'{"query": "x", "numResults": 5}')))
    fid_d = fixture_id_of(
        "exa", normalized_request(
            _post_spec(b'{"query": "y", "numResults": 5}')))
    assert fid_c != fid_d
    # ... and the tavily reviewed shape (max_results) under the same rule.
    fid_e = fixture_id_of(
        "tavily", normalized_request(
            _post_spec(b'{"query": "x", "max_results": 5}',
                       url="https://api.tavily.com/search")))
    fid_f = fixture_id_of(
        "tavily", normalized_request(
            _post_spec(b'{"query": "y", "max_results": 5}',
                       url="https://api.tavily.com/search")))
    assert fid_e != fid_f
    # determinism: the same body replays to the same id.
    assert fid_a == fixture_id_of(
        "exa", normalized_request(_post_spec(b'{"query": "x"}')))
    assert fid_c == fixture_id_of(
        "exa", normalized_request(
            _post_spec(b'{"query": "x", "numResults": 5}')))


def test_redacted_body_reaches_no_fixture() -> None:
    normalized = normalized_request(
        _post_spec(b'{"api_key": "SECRET-XYZ", "query": "q"}'))
    assert "body" in normalized
    assert "SECRET-XYZ" not in json.dumps(normalized)


def test_unknown_body_key_is_scrubbed_in_fixture_identity() -> None:
    # P1-4 — the unknown-key default-deny scrub survives into the recorded
    # normalized form (only the declared vendor fields pass through).
    normalized = normalized_request(_post_spec(b'{"mystery": "x"}'))
    assert normalized["body"] == {"mystery": "<redacted>"}


def test_credential_body_value_reaches_neither_sink_nor_fixture() -> None:
    # A7/P1-4 — a credential-valued body key is scrubbed before any record:
    # neither the sink interaction nor the fixture built from it carries
    # the value.
    seen: list[RecordedInteraction] = []

    def sink(interaction: RecordedInteraction, body: bytes | None) -> None:
        seen.append(interaction)

    transport = RecordedTransport(
        FakeTransport([(200, {"results": []})]),
        provider_id="exa", adapter_version="1", parser_version="1",
        clock=FakeClock(), mode="record", sink=sink)
    transport.request(
        _post_spec(b'{"api_key": "SECRET-XYZ", "query": "epistemic"}'))
    assert len(seen) == 1
    interaction = seen[0]
    normalized = interaction.normalized_request
    assert normalized["body"] == {"api_key": "<redacted>",
                                  "query": "epistemic"}
    fixture = interaction_to_fixture(interaction, b'{"results": []}')
    dumped = json.dumps(fixture.to_mapping())
    assert "SECRET-XYZ" not in json.dumps(normalized)
    assert "SECRET-XYZ" not in dumped
    assert fixture.fixture_id.startswith("fx_")


def test_get_normalized_form_has_no_body_key() -> None:
    # A7/A12(d) — GET fixture ids are unchanged: the key is absent.
    normalized = normalized_request(
        RequestSpec(url="https://example.test/search",
                    params={"q": "x"}, headers_meta={}))
    assert set(normalized) == {"url", "params"}


def test_unknown_method_refuses_before_io() -> None:
    with pytest.raises(ProviderValidationError):
        normalized_request(
            RequestSpec(url="https://example.test/search", params={},
                        headers_meta={}, method="DELETE", body=b""))


# ── D4 transport: the HTTP POST wire path ──


class FakeResp:
    """A urllib-style response: .status, .headers, .read(amt), .close()."""

    def __init__(self, body: bytes, status: int = 200,
                 headers: dict | None = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}
        self._pos = 0

    def read(self, amt: int = -1) -> bytes:
        if self._pos >= len(self.body):
            return b""
        n = (len(self.body) - self._pos if amt < 0
             else min(amt, len(self.body) - self._pos))
        chunk = self.body[self._pos:self._pos + n]
        self._pos += n
        return chunk

    def close(self) -> None:
        pass


def test_http_post_sends_body_never_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def capture(req: object, timeout: float) -> FakeResp:
        assert isinstance(req, urllib.request.Request)
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["content_type"] = req.get_header("Content-type")
        return FakeResp(b'{"results": []}')

    monkeypatch.setattr(http_module, "_open_request", capture)
    body = b'{"max_results":10,"query":"epistemic"}'
    resp = ProviderHTTPTransport().request(
        RequestSpec(url="https://api.tavily.com/search",
                    params={"q": "epistemic"}, headers_meta={},
                    method="POST", body=body))
    assert resp.status == 200
    assert captured["data"] == body
    assert captured["content_type"] == "application/json"
    # D4 rule 3 — the query string is built from the URL alone.
    assert captured["url"] == "https://api.tavily.com/search"


def test_http_get_path_is_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def capture(req: object, timeout: float) -> FakeResp:
        assert isinstance(req, urllib.request.Request)
        captured["url"] = req.full_url
        captured["data"] = req.data
        assert req.get_header("Content-type") is None
        return FakeResp(b"{}")

    monkeypatch.setattr(http_module, "_open_request", capture)
    resp = ProviderHTTPTransport().request(
        RequestSpec(url="https://api.example/search?rows=10",
                    params={"q": "epistemic"}, headers_meta={}))
    assert resp.status == 200
    assert captured["data"] is None
    assert captured["url"] == \
        "https://api.example/search?rows=10&q=epistemic"


def test_http_unknown_method_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(req: object, timeout: float) -> FakeResp:
        raise AssertionError("no I/O on a refused method")

    monkeypatch.setattr(http_module, "_open_request", boom)
    with pytest.raises(ProviderValidationError):
        ProviderHTTPTransport().request(
            RequestSpec(url="https://api.example/search", params={},
                        headers_meta={}, method="DELETE", body=b""))


def test_http_empty_post_body_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(req: object, timeout: float) -> FakeResp:
        raise AssertionError("no I/O on a refused body")

    monkeypatch.setattr(http_module, "_open_request", boom)
    with pytest.raises(ProviderValidationError):
        ProviderHTTPTransport().request(
            RequestSpec(url="https://api.example/search", params={},
                        headers_meta={}, method="POST", body=b""))


def test_http_status_never_raises_on_post(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        http_module, "_open_request",
        lambda req, timeout: (_ for _ in ()).throw(
            urllib.error.HTTPError(req.full_url, 429, "Too Many Requests",
                                   {}, io.BytesIO(b""))))
    resp = ProviderHTTPTransport().request(
        _post_spec(b'{"query": "x"}'))
    assert resp.status == 429


# ── P2 behavioral pins (O2-fix): throttle scoping + cursor traps ──

# The distinctive hostile rules the HZ/FS/WK precedent calls out. Each pin
# below is behavioral, not content-only: it fails when its rule is
# neutralized (the O2 fix report quotes the neutralize-and-restore runs) —
# emptying a fields-scoped throttle rule, changing a leg's cursor kind, or
# lowering a shipped loop_guard.

THROTTLE_FIELD = {"tavily": "detail", "searxng": "error"}


@pytest.mark.parametrize("provider", ["tavily", "searxng"])
def test_throttle_pattern_is_fields_scoped(provider: str) -> None:
    """A 200 carrying the throttle phrase in the DECLARED field is
    THROTTLED; the same phrase in an undeclared key is not — the rule is
    fields-scoped, never a free-text body scan (HZ2-01)."""
    spec = load_shipped(provider)
    field = THROTTLE_FIELD[provider]
    assert evaluate(spec, {"results": [], field: "rate limit exceeded"},
                    200).hazard_class == "THROTTLED"
    assert evaluate(spec, {"results": [], "note": "rate limit exceeded"},
                    200).hazard_class == "NONE"


def _repeating_position_adapter(base: type) -> type:
    """A subclass of a shipped adapter whose parse_page keeps handing back
    the SAME live position — the shape the seen-position trap exists for."""

    class Repeating(base):  # type: ignore[misc, valid-type]
        def parse_page(self, payload: object, state: PageState) -> Page:
            page = super().parse_page(payload, state)
            return Page(records=page.records, total=page.total,
                        next_state=PageState(
                            page_index=state.page_index + 1,
                            cursor="same-position",
                            offset=(state.offset if state.offset is not None
                                    else 0)),
                        notes=page.notes)

    return Repeating


def _advancing_position_adapter(base: type) -> type:
    """A subclass of a shipped adapter whose parse_page hands back a FRESH
    position on every page — a provider that always reports a next page."""

    class Advancing(base):  # type: ignore[misc, valid-type]
        def parse_page(self, payload: object, state: PageState) -> Page:
            page = super().parse_page(payload, state)
            return Page(records=page.records, total=page.total,
                        next_state=PageState(
                            page_index=state.page_index + 1,
                            cursor=f"c{state.page_index + 1}",
                            offset=state.page_index + 1),
                        notes=page.notes)

    return Advancing


@pytest.mark.parametrize("provider", ["brave", "searxng"])
def test_duplicate_cursor_traps_before_the_duplicate_request(
        provider: str) -> None:
    # WS-06 behavioral pin for the offset legs: a provider that keeps
    # handing back the same position is trapped BEFORE the duplicate
    # request is issued.
    adapter = _repeating_position_adapter(PROVIDER_REGISTRY[provider])()
    transport = FakeTransport([(200, GOLDEN[provider])] * 105)
    outcome = walk(adapter, parse_query_hints("epistemic compilers"),
                   WalkRequest(max_results=10 ** 6, max_pages=10 ** 6),
                   transport, FakeLimiter(), FakeRecorder(), FakeClock())
    assert any("repeating position" in note for note in outcome.notes)
    assert len(transport.requests) == 2  # the duplicate was never issued
    assert outcome.notes[0] == "SHORTFALL(cause=CURSOR_TRAP)"
    assert "CURSOR_TRAP" in outcome.request_log.hazard_verdicts
    assert adapter.contract.pagination["kind"] == "offset"


@pytest.mark.parametrize("provider", WEB_PROVIDERS)
def test_shipped_loop_guard_is_the_trap_bound(provider: str) -> None:
    # WS-03 behavioral pin: a provider that always reports a next page is
    # walked only to the spec's declared loop_guard (100 in all four
    # shipped specs) and the guard-hit is a CURSOR_TRAP — never an
    # unbounded walk.
    adapter = _advancing_position_adapter(PROVIDER_REGISTRY[provider])()
    transport = FakeTransport([(200, GOLDEN[provider])] * 105)
    outcome = walk(adapter, parse_query_hints("epistemic compilers"),
                   WalkRequest(max_results=10 ** 6, max_pages=10 ** 6),
                   transport, FakeLimiter(), FakeRecorder(), FakeClock())
    assert outcome.notes[0] == "SHORTFALL(cause=CURSOR_TRAP)"
    assert len(transport.requests) == 100  # the shipped loop_guard


@pytest.mark.parametrize("provider", ["exa", "tavily"])
def test_none_cursor_kind_does_not_invent_a_position_trap(
        provider: str) -> None:
    # The none-kind legs declare no cursor: a provider handing back a
    # cursor is still bounded by the shipped guard, and the driver does
    # NOT invent a seen-position trap from a position it does not track.
    adapter = _repeating_position_adapter(PROVIDER_REGISTRY[provider])()
    transport = FakeTransport([(200, GOLDEN[provider])] * 105)
    outcome = walk(adapter, parse_query_hints("epistemic compilers"),
                   WalkRequest(max_results=10 ** 6, max_pages=10 ** 6),
                   transport, FakeLimiter(), FakeRecorder(), FakeClock())
    assert len(transport.requests) == 100
    assert not any("repeating position" in note for note in outcome.notes)
    assert outcome.notes[0] == "SHORTFALL(cause=CURSOR_TRAP)"
    assert adapter.contract.pagination["kind"] == "none"
