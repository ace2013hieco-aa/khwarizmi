"""Step-4 golden fixtures — the rate limiter + HTTP transport (blueprint
§6.1/§6.1a, contract §6).

Everything the three hostile design gates (RT-01…RT-10, RT2-01…RT2-06,
RT3-01…RT3-05 — `hermes_researchsourceprovider_ratelimit_review{,2,3}.md`,
all FOLDED IN 2026-08-14) pinned is proven here against the running code:

- `ProviderRateLimiter` — the daily-cap `False` sentinel (no-retry), the
  `ADMISSION_WAIT_BOUND` expiry (`admission_wait_expired`, retryable),
  `last_denial_reason`, release-no-refund, the FIFO + global concurrency,
  the Retry-After cooldown, fail-closed construction validation, the UTC
  daily-cap window.
- `ProviderHTTPTransport` — the exception class map (transport-level ONLY:
  TIMEOUT transient, the 2xx-only size abort → PARTIAL_CONTENT; NEVER on an
  HTTP status — urllib's HTTPError is returned as a response), the
  redaction-`from None` discipline, the normalized content_type passthrough.
- Driver integration — the daily-cap walk denial (no retry), the
  admission-expiry retry (bounded, then THROTTLED), recovery after the slot
  frees, the RT2-06 catch-all re-raise of a non-ProviderError transport bug,
  and the evaluator's pinned-slot size + content-type checks in a real walk.
"""
from __future__ import annotations

import http.client
import io
import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

import hermes.tools.providers.http as http_module
from hermes.tools.providers.base import (
    Page,
    PageState,
    ProviderAdapter,
    ProviderContractCard,
    RateProfile,
    RequestSpec,
    TransportResponse,
    WalkRequest,
)
from hermes.tools.providers.hazards import (
    SPEC_SCHEMA,
    ProviderHazardSpec,
    load_hazard_spec,
)
from hermes.tools.providers.http import ProviderHTTPTransport
from hermes.tools.providers.normalize import (
    IDENTIFIER_KINDS,
    RetrievalHints,
    parse_query_hints,
)
from hermes.tools.providers.paginate import combine, walk
from hermes.tools.providers.ratelimit import ProviderRateLimiter
from hermes.tools.research_sources import (
    PermanentProviderError,
    ProviderUnavailableError,
    RequestLogRecord,
    TransientProviderError,
)

# ── clocks ──


class MutableClock:
    """Deterministic clock for the limiter — monotonic + the UTC date advance
    by hand (contract §6.1 clock-injected; the wait bound makes every denial
    path immediate, so no real sleeping is needed)."""

    def __init__(self, now_utc: str = "2026-08-14T00:00:00Z", mono: float = 0.0) -> None:
        self.t = now_utc
        self.mono = mono

    def now_utc(self) -> str:
        return self.t

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.mono += seconds

    def advance_day(self) -> None:
        dt = datetime.fromisoformat(self.t.replace("Z", "+00:00")) + timedelta(days=1)
        self.t = dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class RealClock:
    """Real-time clock for the one threaded FIFO fixture."""

    def now_utc(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def monotonic(self) -> float:
        return time.monotonic()


class HybridClock(RealClock):
    """Real monotonic + a mutable UTC date — the midnight-rollover fixture
    (RT4-01) advances the window while a waiter is queued."""

    def __init__(self) -> None:
        self.t = "2026-08-14T00:00:00Z"

    def now_utc(self) -> str:
        return self.t

    def advance_day(self) -> None:
        dt = datetime.fromisoformat(self.t.replace("Z", "+00:00")) + timedelta(days=1)
        self.t = dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_limiter(profiles: dict[str, tuple[float, int, int, int]],
                 clock: MutableClock | None = None,
                 **kwargs) -> ProviderRateLimiter:
    clock = clock or MutableClock()
    return ProviderRateLimiter(
        {p: RateProfile(rps=r, burst=b, concurrency=c, daily_cap=d)
         for p, (r, b, c, d) in profiles.items()},
        clock, **kwargs)


# ── ProviderRateLimiter ──


def test_construction_validation_fail_closed():
    # RT-09 — non-positive profile axes are a config error, never a silent
    # default; the empty profile set and bad bounds too.
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            make_limiter({"p": (bad, 1, 1, 100)})
    for bad in (0, -1):
        with pytest.raises(ValueError):
            make_limiter({"p": (1.0, bad, 1, 100)})
        with pytest.raises(ValueError):
            make_limiter({"p": (1.0, 1, bad, 100)})
        with pytest.raises(ValueError):
            make_limiter({"p": (1.0, 1, 1, bad)})
    with pytest.raises(ValueError):
        make_limiter({})
    with pytest.raises(ValueError):
        make_limiter({"p": (1.0, 1, 1, 100)}, global_concurrency=0)
    # a zero admission bound is a legitimate strict policy (never wait);
    # only a NEGATIVE bound is incoherent
    with pytest.raises(ValueError):
        make_limiter({"p": (1.0, 1, 1, 100)}, admission_wait_bound=-0.1)
    make_limiter({"p": (1.0, 1, 1, 100)}, admission_wait_bound=0.0)


def test_unknown_provider_fail_closed():
    # No provider runs un-throttled: an unknown provider is a programming
    # error, never a policy condition — raised, never granted.
    limiter = make_limiter({"p": (1.0, 1, 1, 100)})
    with pytest.raises(ValueError):
        limiter.acquire("nope")


def test_daily_cap_false_sentinel_no_block_no_retry_signal():
    # RT-01/RT2-02/RT3-02 — the daily cap returns False WITHOUT blocking;
    # `last_denial_reason` names the cause (the driver's no-retry branch).
    # concurrency is generous: the cap is the signal under test, never slot
    # contention (and the frozen clock's bound can't expire — the deny path
    # is what is deterministic).
    limiter = make_limiter({"p": (10.0, 10, 10, 2)})
    assert limiter.acquire("p") == (True, "")
    assert limiter.acquire("p") == (True, "")
    assert limiter.acquire("p") == (False, "daily_cap_exhausted")
    assert limiter.last_denial_reason("p") == "daily_cap_exhausted"  # diagnostic
    # a grant clears the denial
    limiter = make_limiter({"p": (10.0, 10, 10, 100)})
    assert limiter.acquire("p") == (True, "")
    assert limiter.last_denial_reason("p") == ""


def test_daily_cap_window_is_fixed_utc_date():
    # RT-10 — the cap resets at UTC midnight per clock.now_utc's date.
    clock = MutableClock()
    limiter = make_limiter({"p": (10.0, 10, 10, 1)}, clock)
    assert limiter.acquire("p") == (True, "")
    assert limiter.acquire("p") == (False, "daily_cap_exhausted")
    clock.advance_day()
    assert limiter.acquire("p") == (True, "")  # new window


def test_admission_wait_expiry_is_transient_signal():
    # RT2-02/RT3-02 — the ADMISSION_WAIT_BOUND expiry is a DISTINCT cause
    # from the daily cap (the driver's retryable branch).
    limiter = make_limiter({"p": (10.0, 10, 1, 100)}, admission_wait_bound=0.0)
    assert limiter.acquire("p") == (True, "")  # slot held
    assert limiter.acquire("p") == (False, "admission_wait_expired")  # not a cap
    assert limiter.last_denial_reason("p") == "admission_wait_expired"  # diagnostic


def test_release_returns_slot_and_expiry_clears():
    # after release the slot is free — the next acquire grants again
    limiter = make_limiter({"p": (10.0, 10, 1, 100)}, admission_wait_bound=0.0)
    assert limiter.acquire("p") == (True, "")
    limiter.release("p")
    assert limiter.acquire("p") == (True, "")
    limiter.release("p")


def test_release_never_refunds_token():
    # RT-03 — release returns the SEMAPHORE slot only: after acquire+release
    # with no time passed, the bucket is still empty, so the next acquire is
    # DENIED (a refunding limiter would grant — this pins no-refund).
    clock = MutableClock()
    limiter = make_limiter({"p": (1.0, 1, 1, 100)}, clock, admission_wait_bound=0.0)
    assert limiter.acquire("p") == (True, "")  # tokens 1 → 0
    limiter.release("p")  # slot back; token NOT refunded
    assert limiter.acquire("p") == (False, "admission_wait_expired")
    assert limiter.last_denial_reason("p") == "admission_wait_expired"


def test_bucket_refills_at_rps():
    # the bucket drains, refills continuously at rps, and the wait is bounded
    # by burst-refill — with a frozen clock, denial until the refill passes
    clock = MutableClock()
    limiter = make_limiter({"p": (1.0, 1, 1, 100)}, clock, admission_wait_bound=0.0)
    assert limiter.acquire("p") == (True, "")  # burst 1 spent
    limiter.release("p")  # the slot is not the signal under test
    assert limiter.acquire("p") == (False, "admission_wait_expired")  # no refill
    clock.advance(1.1)  # > 1/rps — one token refilled
    assert limiter.acquire("p") == (True, "")
    limiter.release("p")


def test_release_without_acquire_raises():
    # RT2-03 — releasing an un-acquired slot would underflow the semaphore
    # and admit MORE than concurrency: loud, never silent.
    limiter = make_limiter({"p": (10.0, 10, 1, 100)})
    with pytest.raises(RuntimeError):
        limiter.release("p")


def test_note_throttled_retry_after_cooldown_shapes_future_acquires():
    # RT-08 — note_throttled drains the bucket and a positive Retry-After
    # delays refill past the cooldown; it never sleeps the caller.
    clock = MutableClock()
    limiter = make_limiter({"p": (1.0, 1, 1, 100)}, clock, admission_wait_bound=0.0)
    assert limiter.acquire("p") == (True, "")
    limiter.release("p")
    limiter.note_throttled("p", retry_after=5.0)
    clock.advance(2.0)
    assert limiter.acquire("p") == (False, "admission_wait_expired")
    clock.advance(4.0)  # total 6 > 5 — refill resumes
    assert limiter.acquire("p") == (True, "")
    limiter.release("p")


def test_note_throttled_without_retry_after_drains_then_refills():
    clock = MutableClock()
    limiter = make_limiter({"p": (1.0, 1, 1, 100)}, clock, admission_wait_bound=0.0)
    assert limiter.acquire("p") == (True, "")
    limiter.release("p")
    limiter.note_throttled("p", None)
    clock.advance(1.1)
    assert limiter.acquire("p") == (True, "")  # refilled at rps
    limiter.release("p")


def test_global_concurrency_bounds_across_providers():
    # contract §6.1 \"global bounded concurrency\" — a busy provider holds a
    # global slot; a second provider's acquire waits (and expires under the
    # bound) instead of running un-throttled.
    clock = MutableClock()
    limiter = make_limiter({"a": (10.0, 10, 1, 100), "b": (10.0, 10, 1, 100)},
                           clock, global_concurrency=1, admission_wait_bound=0.0)
    assert limiter.acquire("a") == (True, "")
    assert limiter.acquire("b") == (False, "admission_wait_expired")
    assert limiter.last_denial_reason("b") == "admission_wait_expired"
    limiter.release("a")
    assert limiter.acquire("b") == (True, "")
    limiter.release("b")


def test_fifo_concurrency_second_waiter_served_after_release():
    # contract §6.1 FIFO — with concurrency=1, the second waiter is NOT
    # granted while the first holds the slot; it is served on release.
    limiter = make_limiter({"p": (100.0, 100, 1, 1000)}, RealClock(),
                           admission_wait_bound=5.0)
    order: list[str] = []
    holder_entered = threading.Event()
    release_holder = threading.Event()

    def worker(name: str, hold: bool) -> None:
        ok, _ = limiter.acquire("p")
        order.append(f"{name}:{ok}")
        if hold:
            holder_entered.set()
            release_holder.wait(2.0)
        limiter.release("p")

    t1 = threading.Thread(target=worker, args=("a", True))
    t2 = threading.Thread(target=worker, args=("b", False))
    t1.start()
    assert holder_entered.wait(2.0)
    t2.start()
    time.sleep(0.05)
    assert order == ["a:True"]  # b is queued, not granted
    release_holder.set()
    t1.join(2.0)
    t2.join(2.0)
    assert not t1.is_alive() and not t2.is_alive()
    assert order == ["a:True", "b:True"]  # FIFO — b served after a released


# ── ProviderHTTPTransport ──


class FakeResp:
    """A urllib-style response: .status, .headers, .read(amt), .close()."""

    def __init__(self, body: bytes, status: int = 200,
                 headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}
        self._pos = 0
        self.closed = False

    def read(self, amt: int = -1) -> bytes:
        if self._pos >= len(self.body):
            return b""
        n = len(self.body) - self._pos if amt < 0 else min(amt, len(self.body) - self._pos)
        chunk = self.body[self._pos:self._pos + n]
        self._pos += n
        return chunk

    def close(self) -> None:
        self.closed = True


def fake_open(status: int, body: bytes, headers: dict[str, str] | None = None):
    return lambda req, timeout: FakeResp(body, status=status, headers=headers)


def test_http_status_never_raises(monkeypatch):
    # RT2-01 — urllib surfaces non-2xx as HTTPError; the transport RETURNS it
    # as a response so evaluate_hazards classifies the status (a 404 keeps
    # its answered-lookup VALID_NEGATIVE; a 429 keeps its THROTTLED path).
    monkeypatch.setattr(
        http_module, "_open_request",
        lambda req, timeout: (_ for _ in ()).throw(
            urllib.error.HTTPError(req.full_url, 404, "Not Found", {},
                                   io.BytesIO(b""))))
    transport = ProviderHTTPTransport()
    resp = transport.request(RequestSpec(
        url="https://api.example/search", params={}, headers_meta={}))
    assert resp.status == 404
    assert resp.body == b""


def test_http_429_returned_not_raised(monkeypatch):
    monkeypatch.setattr(http_module, "_open_request", fake_open(429, b"{}", {
        "Retry-After": "5"}))
    transport = ProviderHTTPTransport()
    resp = transport.request(RequestSpec(
        url="https://api.example/search", params={}, headers_meta={}))
    assert resp.status == 429
    assert resp.headers.get("Retry-After") == "5"


def test_http_timeout_maps_transient_timeout(monkeypatch):
    # RT-02 — a bare timeout is NEVER propagated; it is a typed transient
    # with a named hazard_class (retryable per §6.3).
    def boom(req, timeout):
        raise TimeoutError("timed out")
    monkeypatch.setattr(http_module, "_open_request", boom)
    transport = ProviderHTTPTransport()
    with pytest.raises(TransientProviderError) as exc:
        transport.request(RequestSpec(
            url="https://api.example/search", params={}, headers_meta={}))
    assert exc.value.hazard_class == "TIMEOUT"


def test_http_urlerror_timeout_reason_maps_transient(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.URLError(TimeoutError("timed out"))
    monkeypatch.setattr(http_module, "_open_request", boom)
    transport = ProviderHTTPTransport()
    with pytest.raises(TransientProviderError) as exc:
        transport.request(RequestSpec(
            url="https://api.example/search", params={}, headers_meta={}))
    assert exc.value.hazard_class == "TIMEOUT"


def test_http_connection_error_maps_transient(monkeypatch):
    def boom(req, timeout):
        raise ConnectionResetError("connection reset")
    monkeypatch.setattr(http_module, "_open_request", boom)
    transport = ProviderHTTPTransport()
    with pytest.raises(TransientProviderError) as exc:
        transport.request(RequestSpec(
            url="https://api.example/search", params={}, headers_meta={}))
    assert exc.value.hazard_class == "TIMEOUT"


def test_http_size_abort_fires_only_on_2xx(monkeypatch):
    # RT3-01 (a) — the streaming abort is status-conditional: an oversized
    # 2xx body is a permanent PARTIAL_CONTENT; an oversized 429 keeps its
    # status (THROTTLED verdict — status evidence dominates).
    monkeypatch.setattr(http_module, "_open_request",
                        fake_open(200, b"x" * 1000))
    transport = ProviderHTTPTransport(size_cap_bytes=100)
    with pytest.raises(PermanentProviderError) as exc:
        transport.request(RequestSpec(
            url="https://api.example/search", params={}, headers_meta={}))
    assert exc.value.hazard_class == "PARTIAL_CONTENT"

    monkeypatch.setattr(http_module, "_open_request",
                        fake_open(429, b"x" * 1000))
    resp = transport.request(RequestSpec(
        url="https://api.example/search", params={}, headers_meta={}))
    assert resp.status == 429  # never PARTIAL_CONTENT, never a raise


def test_http_error_messages_redact_credentials(monkeypatch):
    # PS-02/PS2-04/PS3-07 — every message is built from the policy-redacted
    # request form and raised `from None`: a timeout cannot leak a
    # query-auth credential.
    def boom(req, timeout):
        raise TimeoutError("timed out")
    monkeypatch.setattr(http_module, "_open_request", boom)
    transport = ProviderHTTPTransport()
    with pytest.raises(TransientProviderError) as exc:
        transport.request(RequestSpec(
            url="https://api.example/search?api_key=supersecret&q=epistemic",
            params={}, headers_meta={}))
    message = str(exc.value)
    assert "supersecret" not in message
    # the redacted placeholder (URL-encoded by redact_url's query re-encode)
    assert "redacted" in message
    assert exc.value.__cause__ is None  # the from-None discipline


def test_http_content_type_normalized(monkeypatch):
    # RT-05 — the transport surfaces the normalized media type only; the
    # allowlist check lives in the evaluator.
    monkeypatch.setattr(http_module, "_open_request",
                        fake_open(200, b"{}", {"Content-Type":
                                               "application/atom+xml; charset=utf-8"}))
    transport = ProviderHTTPTransport()
    resp = transport.request(RequestSpec(
        url="https://api.example/search", params={}, headers_meta={}))
    assert resp.content_type == "application/atom+xml"
    assert resp.body == b"{}"


def test_http_builds_url_with_merged_params(monkeypatch):
    captured: dict[str, object] = {}

    def capture(req, timeout):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        return FakeResp(b"{}")

    monkeypatch.setattr(http_module, "_open_request", capture)
    transport = ProviderHTTPTransport(timeout=12.0)
    resp = transport.request(RequestSpec(
        url="https://api.example/search?rows=10",
        params={"q": "epistemic", "api_key": "s3cr3t"}, headers_meta={}))
    assert resp.status == 200
    assert captured["url"] == \
        "https://api.example/search?rows=10&api_key=s3cr3t&q=epistemic"
    assert captured["timeout"] == 12.0


# ── driver integration (walk + real limiter + FakeTransport) ──


class FakeTransport:
    """Serves a script of pages; each request pops one entry. `content_type`
    rides the response so the evaluator's label check can fire."""

    def __init__(self, script: list[dict]) -> None:
        self._script = list(script)
        self.last: dict | None = None
        self.calls = 0

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.calls += 1
        self.last = self._script.pop(0) if self._script else None
        if self.last is None:
            raise PermanentProviderError("no scripted response", hazard_class="MALFORMED_200")
        body = self.last.get("body")
        if body is None:
            body = {k: v for k, v in self.last.items()
                    if k not in ("status", "headers", "body", "content_type")}
        if isinstance(body, dict):
            raw = json.dumps(body).encode()
        elif isinstance(body, str):
            raw = body.encode()
        else:
            raw = body or b""
        return TransportResponse(
            status=self.last.get("status", 200), body=raw,
            headers=self.last.get("headers", {}),
            content_type=self.last.get("content_type"))


class FakeAdapter(ProviderAdapter):
    def __init__(self, transport: FakeTransport, provider_id: str = "fake") -> None:
        self.transport = transport
        self.contract = ProviderContractCard(
            provider_id=provider_id,
            base_url="https://fake.example/api",
            auth_policy="none",
            hint_routes={"doi": "lookup", "pmid": "lookup", "pmcid": "lookup",
                         "arxiv": "lookup", "url": "lookup"},
            pagination={"kind": "cursor", "page_size_cap": 100,
                        "max_pages": 50, "loop_guard": 100},
            hazard_spec_version="1.0.0",
            rate_profile=RateProfile(rps=1.0, burst=1, concurrency=1, daily_cap=1000),
            retry_class_map={},
        )

    def build_request(self, hints: RetrievalHints, state: PageState, page_size: int) -> RequestSpec:
        return RequestSpec(
            url="https://fake.example/api/search",
            params={"q": hints.topic or next(iter(hints.identifiers.values()), ""),
                    "cursor": state.cursor or "", "rows": str(page_size)},
            headers_meta={})

    def parse_page(self, payload: object, state: PageState) -> Page:
        entry = self.transport.last or {}
        records = tuple(entry.get("records", []))
        next_cursor = entry.get("next_cursor")
        next_state = (PageState(state.page_index + 1, cursor=next_cursor)
                      if next_cursor is not None else None)
        return Page(records=records, total=entry.get("total"), next_state=next_state)

    def extract_ids(self, record: dict[str, object]) -> dict[str, str]:
        return {k: str(v) for k, v in record.items()
                if k in IDENTIFIER_KINDS and v}

    def build_fetch_request(self, source) -> RequestSpec:  # pragma: no cover
        return RequestSpec(url="https://fake.example/api/fulltext", params={}, headers_meta={})


class FakeRecorder:
    def __init__(self) -> None:
        self.logs: list[RequestLogRecord] = []

    def record(self, log: RequestLogRecord) -> None:
        self.logs.append(log)


class WalkClock:
    """The driver's clock — now_utc + sleep accumulation (no real sleeping)."""

    def __init__(self) -> None:
        self.t = "2026-08-14T00:00:00Z"
        self.slept = 0.0

    def now_utc(self) -> str:
        return self.t

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, delay: float) -> None:
        self.slept += delay


def fake_spec(content_types: list[str] | None = None,
              throttle_signature: list[dict] | None = None) -> ProviderHazardSpec:
    return load_hazard_spec("fake", {
        "schema": SPEC_SCHEMA,
        "provider_id": "fake",
        "version": "1.0.0",
        "markers": [],
        "empty_body_rule": "treat-as-failure",
        "error_field": None,
        "count_semantics": "exact",
        "counts_raw_rows": False,
        "required_fields": ["records"],
        "cursor_rule": {"kind": "cursor", "loop_guard": 100},
        "throttle_signature": throttle_signature or [],
        "rewrite_suspect": [],
        "fetch": None,
        "valid_negative_statuses": [404],
        "content_types": content_types or [],
    })


def rec(doi: str) -> dict[str, object]:
    return {"doi": doi, "title": "A paper"}


def page(*, records: list[dict] | None = None, total: int | None = None,
         next_cursor: str | None = None, content_type: str | None = None) -> dict:
    return {"status": 200, "records": records or [], "total": total,
            "next_cursor": next_cursor, "content_type": content_type}


def topic_hints() -> RetrievalHints:
    return parse_query_hints("epistemic compilers")


def run_walk(script: list[dict], limiter: ProviderRateLimiter, spec: ProviderHazardSpec,
             request: WalkRequest | None = None):
    transport = FakeTransport(script)
    adapter = FakeAdapter(transport)
    outcome = walk(adapter, topic_hints(), request or WalkRequest(max_results=50),
                   transport, limiter, FakeRecorder(), WalkClock(), hazard_spec=spec)
    return outcome, transport


def test_walk_daily_cap_denial_is_no_retry():
    # RT-01/RT3-02 — the daily cap is a hard stop: page 2's acquire returns
    # False and the driver returns THROTTLED with NO retry (one request
    # total), carrying the cause note.
    limiter = make_limiter({"fake": (10.0, 10, 1, 1)})
    spec = fake_spec()
    outcome, transport = run_walk([
        page(records=[rec("10.1000/a")], total=2, next_cursor="c1"),
        page(records=[rec("10.1000/b")], total=2),
    ], limiter, spec)
    assert outcome.notes[0] == "SHORTFALL(cause=THROTTLED)"
    assert "daily_cap_exhausted=true" in outcome.notes
    assert transport.calls == 1  # the denied page was never requested
    assert outcome.aggregate == "PARTIAL"  # page 1 records retained-flagged


def test_walk_admission_expiry_retries_then_throttled():
    # RT3-02/03 — the admission-wait expiry is TRANSIENT: the driver backs
    # off and RETRIES (acquire per attempt) before exhausting — never the
    # daily cap's single-shot no-retry.
    clock = MutableClock()
    limiter = make_limiter({"fake": (10.0, 10, 1, 1000)}, clock,
                           admission_wait_bound=0.0)
    assert limiter.acquire("fake") == (True, "")  # a concurrent tenant holds the slot
    spec = fake_spec()
    outcome, transport = run_walk([
        page(records=[rec("10.1000/a")], total=1),
    ], limiter, spec)
    assert outcome.notes[0] == "SHORTFALL(cause=THROTTLED)"
    assert "admission_wait_expired=true" in outcome.notes
    assert transport.calls == 0  # every attempt was denied before the request
    # the waiter queue drained — once the holder releases, a fresh acquire
    # grants immediately (no leaked waiter blocking the slot)
    limiter.release("fake")
    assert limiter.acquire("fake") == (True, "")


def test_walk_recovers_after_slot_release():
    # the expiry is contention — once the holder releases, the same limiter
    # admits a fresh walk normally (COMPLETE).
    clock = MutableClock()
    limiter = make_limiter({"fake": (10.0, 10, 1, 1000)}, clock,
                           admission_wait_bound=0.0)
    assert limiter.acquire("fake") == (True, "")
    outcome, _ = run_walk([page(records=[rec("10.1000/a")], total=1)],
                          limiter, fake_spec())
    assert outcome.notes[0] == "SHORTFALL(cause=THROTTLED)"
    assert "admission_wait_expired=true" in outcome.notes
    limiter.release("fake")
    outcome2, transport2 = run_walk([page(records=[rec("10.1000/a")], total=1)],
                                    limiter, fake_spec())
    assert outcome2.notes[0] == "COMPLETE(retrieved==total)"
    assert transport2.calls == 1


def test_walk_non_provider_error_transport_bug_is_loud():
    # RT2-06 — a NON-ProviderError escaping the transport is a bug: the
    # catch-all RE-RAISES it (never a MALFORMED_200 schema verdict).
    class BuggyTransport:
        def request(self, spec: RequestSpec) -> TransportResponse:
            raise ValueError("transport bug")

    limiter = make_limiter({"fake": (10.0, 10, 1, 1000)})
    adapter = FakeAdapter(BuggyTransport())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        walk(adapter, topic_hints(), WalkRequest(max_results=50),
             BuggyTransport(), limiter, FakeRecorder(), WalkClock(),
             hazard_spec=fake_spec())


def test_walk_oversized_page_is_partial_content():
    # RT3-01 (b)/RT-06 — the evaluator's completed-body check: an oversized
    # COMPLETE 2xx page → PARTIAL_CONTENT (permanent), never silent
    # truncation and never a bare COMPLETE.
    limiter = make_limiter({"fake": (10.0, 10, 1, 1000)})
    outcome, transport = run_walk([
        page(records=[rec("10.1000/a")], total=1),
    ], limiter, fake_spec(), request=WalkRequest(max_results=50, size_cap_bytes=10))
    assert outcome.notes[0] == "SHORTFALL(cause=PARTIAL_CONTENT)"
    assert transport.calls == 1  # failed permanently — no retry


def test_walk_content_type_mismatch_is_malformed():
    # RT-05/RT2-04/RT3-04 — the evaluator's label check at the pinned slot:
    # a declared allowlist + a concrete mismatch → MALFORMED_200 (permanent);
    # status evidence still dominates (a 429 with a mismatched label stays
    # THROTTLED — covered by the status deferral fixtures).
    spec = fake_spec(content_types=["application/json"])
    limiter = make_limiter({"fake": (10.0, 10, 1, 1000)})
    outcome, _ = run_walk([
        page(records=[rec("10.1000/a")], total=1, content_type="text/plain"),
    ], limiter, spec)
    assert outcome.notes[0] == "SHORTFALL(cause=MALFORMED_200)"
    # matching label passes
    outcome2, _ = run_walk([
        page(records=[rec("10.1000/a")], total=1, content_type="application/json"),
    ], limiter, spec)
    assert outcome2.notes[0] == "COMPLETE(retrieved==total)"


def test_walk_throttled_429_passes_limiter_and_retries():
    # the 429 path still flows through the real limiter: note_throttled
    # drains the bucket, the driver backs off, and the retry re-acquires —
    # then succeeds once the second page is served.
    # no Retry-After header: note_throttled drains the bucket, the driver
    # backs off, and the retry re-acquires after the (tiny) rps refill wait —
    # the real limiter is exercised end-to-end. The limiter's clock is the
    # REAL monotonic clock (a frozen one would never refill the drained
    # bucket), the driver's clock stays fake.
    spec = fake_spec(throttle_signature=[
        {"status": 429, "body_pattern": None, "fields": []}])
    limiter = make_limiter({"fake": (1000.0, 10, 1, 1000)}, RealClock())
    transport = FakeTransport([
        {"status": 429, "body": {}, "headers": {}},
        page(records=[rec("10.1000/a")], total=1),
    ])
    adapter = FakeAdapter(transport)
    outcome = walk(adapter, topic_hints(), WalkRequest(max_results=50),
                   transport, limiter, FakeRecorder(), WalkClock(),
                   hazard_spec=spec)
    assert outcome.notes[0] == "COMPLETE(retrieved==total)"
    assert transport.calls == 2
    assert "daily_cap_exhausted" not in outcome.notes  # a 429 is never a denial


# ── fourth-gate fold-in (TR-01/CAP-01/RL-01, 2026-08-14) ──


class MidReadFailResp:
    """A response whose read() succeeds once, then raises — a mid-download
    transport failure (TR-01's probe shape)."""

    status = 200
    headers: dict[str, str] = {}

    def __init__(self, exc: BaseException, first: bytes = b"x" * 100) -> None:
        self._exc = exc
        self._first = first
        self._calls = 0

    def read(self, amt: int = -1) -> bytes:
        self._calls += 1
        if self._calls == 1:
            return self._first
        raise self._exc

    def close(self) -> None:
        pass


def test_http_mid_body_timeout_maps_transient(monkeypatch):
    # TR-01 — the exception class map covers the BODY-READ phase: a read
    # timeout mid-download is a transport-level transient (TIMEOUT), never a
    # bare exception that would crash the walk.
    monkeypatch.setattr(http_module, "_open_request",
                        lambda req, timeout: MidReadFailResp(TimeoutError("read timed out")))
    transport = ProviderHTTPTransport()
    with pytest.raises(TransientProviderError) as exc:
        transport.request(RequestSpec(
            url="https://api.example/search", params={}, headers_meta={}))
    assert exc.value.hazard_class == "TIMEOUT"


def test_http_mid_body_incomplete_read_maps_transient(monkeypatch):
    # the same hole for http.client.IncompleteRead (server closed early)
    monkeypatch.setattr(http_module, "_open_request",
                        lambda req, timeout: MidReadFailResp(http.client.IncompleteRead(b"x")))
    transport = ProviderHTTPTransport()
    with pytest.raises(TransientProviderError) as exc:
        transport.request(RequestSpec(
            url="https://api.example/search", params={}, headers_meta={}))
    assert exc.value.hazard_class == "TIMEOUT"


def test_http_mid_body_failure_on_error_page_maps_transient(monkeypatch):
    # the HTTPError branch has the same hole — closed by the same map: an
    # error page whose read aborts mid-body is still a transient.
    def open_err(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 429, "Too Many Requests", {},
            MidReadFailResp(TimeoutError("read timed out")))
    monkeypatch.setattr(http_module, "_open_request", open_err)
    transport = ProviderHTTPTransport()
    with pytest.raises(TransientProviderError) as exc:
        transport.request(RequestSpec(
            url="https://api.example/search", params={}, headers_meta={}))
    assert exc.value.hazard_class == "TIMEOUT"


def test_http_mid_body_size_abort_still_passes_through(monkeypatch):
    # TR-01 — the read-phase wrapper must NOT swallow the size abort: an
    # oversized COMPLETE 2xx body still raises PARTIAL_CONTENT (permanent).
    monkeypatch.setattr(http_module, "_open_request", fake_open(200, b"x" * 1000))
    transport = ProviderHTTPTransport(size_cap_bytes=100)
    with pytest.raises(PermanentProviderError) as exc:
        transport.request(RequestSpec(
            url="https://api.example/search", params={}, headers_meta={}))
    assert exc.value.hazard_class == "PARTIAL_CONTENT"


def test_daily_cap_no_overrun_under_queued_waiters():
    # CAP-01 — the daily cap is a hard stop even under queued waiters: a
    # waiter that queued past the top-of-acquire check (cap_used < cap) is
    # RE-CHECKED inside the wait loop and denied with the no-retry
    # daily_cap_exhausted label (never admission_wait_expired, never a
    # grant). The pre-fix code granted 3 for a cap of 2 — this pins exactly 2.
    limiter = make_limiter({"fake": (100.0, 100, 1, 2)}, RealClock(),
                           admission_wait_bound=5.0)
    assert limiter.acquire("fake") == (True, "")  # A — cap=1, slot held
    results: dict[str, tuple[bool, str]] = {}

    def worker(name: str) -> None:
        granted, reason = limiter.acquire("fake")
        results[name] = (granted, reason)
        if granted:
            limiter.release("fake")

    t1 = threading.Thread(target=worker, args=("b",))
    t2 = threading.Thread(target=worker, args=("c",))
    t1.start()
    t2.start()
    time.sleep(0.2)  # B and C are queued past the top check (cap_used=1 < 2)
    limiter.release("fake")  # A done — B grants (cap=2); C is re-checked
    t1.join(3.0)
    t2.join(3.0)
    assert not t1.is_alive() and not t2.is_alive()
    grants = [k for k, v in results.items() if v[0] is True]
    denials = [k for k, v in results.items() if v[0] is False]
    assert len(grants) == 1  # B only — total grants == daily_cap, no overrun
    assert len(denials) == 1  # C is denied
    assert results[denials[0]] == (False, "daily_cap_exhausted")  # hard-stop label


def test_acquire_returns_reason_atomically():
    # RL-01 — the decision AND the cause return under one lock: a caller
    # whose OWN denial is the admission expiry can never read another
    # caller's cap denial through the interleave that reproduced the TOCTOU.
    limiter = make_limiter({"fake": (100.0, 100, 1, 2)}, RealClock(),
                           admission_wait_bound=0.0)
    assert limiter.acquire("fake") == (True, "")  # holder — cap=1, slot held
    own: dict[str, tuple[bool, str]] = {}
    paused = threading.Event()
    proceed = threading.Event()

    def caller1() -> None:
        own["result"] = limiter.acquire("fake")  # expiry False — atomic reason
        paused.set()
        proceed.wait(2.0)

    th = threading.Thread(target=caller1)
    th.start()
    paused.wait(2.0)
    # while caller1 is paused, the cap exhausts behind it:
    limiter.release("fake")
    assert limiter.acquire("fake") == (True, "")  # queued waiter grants (cap=2)
    limiter.release("fake")
    assert limiter.acquire("fake") == (False, "daily_cap_exhausted")  # cap hit
    proceed.set()
    th.join(2.0)
    assert own["result"] == (False, "admission_wait_expired")  # ITS OWN reason


# ── second-gate fold-in (RT4-01/RT4-02, 2026-08-14) ──


class TimeoutTransport:
    """Raises the transient TIMEOUT class on every attempt — the transport
    failure the TR-01 read-phase map emits (RT4-02's probe shape)."""

    def __init__(self) -> None:
        self.calls = 0
        self.last: dict | None = None

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.calls += 1
        raise TransientProviderError("request timed out", hazard_class="TIMEOUT")


def test_walk_timeout_exhaustion_is_unavailable_never_empty():
    # RT4-02 — a provider whose every attempt TIMED OUT never CLASSIFIED a
    # response: the single-provider aggregate is UNAVAILABLE (could not
    # search), NEVER EMPTY ("no literature" — the PS-13 class). Pre-fix, the
    # timeout exhaustion counted as "searched" and combine raised EMPTY.
    limiter = make_limiter({"fake": (10.0, 10, 1, 1000)})
    transport = TimeoutTransport()
    adapter = FakeAdapter(transport)
    outcome = walk(adapter, topic_hints(), WalkRequest(max_results=50),
                   transport, limiter, FakeRecorder(), WalkClock(),
                   hazard_spec=fake_spec())
    assert outcome.notes[0] == "SHORTFALL(cause=TIMEOUT)"
    assert outcome.aggregate == "UNAVAILABLE"
    with pytest.raises(ProviderUnavailableError):
        combine([outcome])
    assert transport.calls == 4  # the bounded retry ran before the verdict


def test_walk_mid_walk_timeout_partial_records_retained():
    # RT4-02 — a MID-walk TIMEOUT (after a delivered page) stays
    # SHORTFALL(cause=TIMEOUT) with the records retained-flagged → PARTIAL;
    # the searched-flag fix only shapes the zero-delivery case (WS-04 is
    # untouched).
    class TimeoutAfterFirst:
        def __init__(self) -> None:
            self.calls = 0
            self.last: dict | None = None

        def request(self, spec: RequestSpec) -> TransportResponse:
            self.calls += 1
            if self.calls == 1:
                self.last = {"records": [{"doi": "10.1000/a", "title": "A"}],
                             "total": 2, "next_cursor": "c1"}
                return TransportResponse(status=200, body=json.dumps(self.last).encode(),
                                         headers={})
            raise TransientProviderError("request timed out", hazard_class="TIMEOUT")

    limiter = make_limiter({"fake": (10.0, 10, 1, 1000)})
    transport = TimeoutAfterFirst()
    adapter = FakeAdapter(transport)
    outcome = walk(adapter, topic_hints(), WalkRequest(max_results=50),
                   transport, limiter, FakeRecorder(), WalkClock(),
                   hazard_spec=fake_spec())
    assert outcome.notes[0] == "SHORTFALL(cause=TIMEOUT)"
    assert outcome.aggregate == "PARTIAL"
    assert len(outcome.per_provider) == 1  # page 1 records retained-flagged


def test_daily_cap_window_reset_reapplies_inside_wait_loop():
    # RT4-01 — the CAP-01 loop re-check must see the FRESH UTC day: a waiter
    # queued before midnight is granted on the new window, never denied
    # daily_cap_exhausted on yesterday's exhausted count. Pre-fix, C was
    # denied (stale day-1 count); with the in-loop reset, B and C both grant
    # on the fresh day-2 window.
    clock = HybridClock()
    limiter = make_limiter({"fake": (100.0, 100, 1, 2)}, clock,
                           admission_wait_bound=5.0)
    assert limiter.acquire("fake") == (True, "")  # A — day1 grant, cap_used=1
    results: dict[str, tuple[bool, str]] = {}

    def worker(name: str) -> None:
        granted, reason = limiter.acquire("fake")
        results[name] = (granted, reason)
        if granted:
            limiter.release("fake")

    t1 = threading.Thread(target=worker, args=("b",))
    t2 = threading.Thread(target=worker, args=("c",))
    t1.start()
    t2.start()
    time.sleep(0.2)  # B and C queued past the top check (day1, cap_used=1)
    clock.advance_day()  # midnight while they wait
    limiter.release("fake")  # A done — the in-loop reset re-applies first
    t1.join(3.0)
    t2.join(3.0)
    assert not t1.is_alive() and not t2.is_alive()
    assert results["b"] == (True, "")  # fresh window has grants
    assert results["c"] == (True, "")
    # and the fresh window is still capped: a fourth acquire is denied
    assert limiter.acquire("fake") == (False, "daily_cap_exhausted")
