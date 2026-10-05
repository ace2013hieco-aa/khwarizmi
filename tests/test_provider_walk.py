"""Step-3 golden fixtures — the reconciliation walk driver (blueprint §5.1).

The fake adapter + fake transport serve a script of pages; the fake limiter/
recorder/clock make the driver deterministic without network or sleeping.
Every WS-01…WS-07 remediation is pinned here, plus the reconciliation verdicts
(COMPLETE/SHORTFALL/UNKNOWN) and the aggregate matrix (COMPLETE/PARTIAL/EMPTY/
UNAVAILABLE incl. the valid-negative mixes and the raises).
"""
from __future__ import annotations

import json

import pytest

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
from hermes.tools.providers.normalize import (
    IDENTIFIER_KINDS,
    RetrievalHints,
    parse_query_hints,
)
from hermes.tools.providers.paginate import combine, walk
from hermes.tools.research_sources import (
    PermanentProviderError,
    ProviderUnavailableError,
    RedactionError,
    RequestLogRecord,
    RetrievalShortfallError,
    SearchOutcome,
)

# ── fakes ──


class FakeTransport:
    """Serves a script of (status, body, headers) pages and exposes the LAST
    entry so the fake adapter can render `Page` from it. Each `request` pops
    one entry (retries pop one per attempt)."""

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
            # Default payload: the script entry itself (records/total/next_cursor)
            # — a NON-empty JSON shape, so the hazard evaluator sees a normal
            # page and parse_page renders it from `last`.
            body = {k: v for k, v in self.last.items()
                    if k not in ("status", "headers", "body")}
        if isinstance(body, dict):
            raw = json.dumps(body).encode()
        elif isinstance(body, str):
            raw = body.encode()
        else:
            raw = body or b""
        return TransportResponse(
            status=self.last.get("status", 200), body=raw,
            headers=self.last.get("headers", {}))


class FakeAdapter(ProviderAdapter):
    def __init__(self, transport: FakeTransport, provider_id: str = "fake",
                 pagination: dict | None = None) -> None:
        self.transport = transport
        self.requests: list[tuple[RetrievalHints, PageState, int]] = []
        self.contract = ProviderContractCard(
            provider_id=provider_id,
            base_url="https://fake.example/api",
            auth_policy="none",
            hint_routes={"doi": "lookup", "pmid": "lookup", "pmcid": "lookup",
                         "arxiv": "lookup", "url": "lookup"},
            pagination=pagination or {"kind": "cursor", "page_size_cap": 100,
                                      "max_pages": 50, "loop_guard": 100},
            hazard_spec_version="1.0.0",
            rate_profile=RateProfile(rps=1.0, burst=1, concurrency=1, daily_cap=1000),
            retry_class_map={},
        )

    def build_request(self, hints: RetrievalHints, state: PageState, page_size: int) -> RequestSpec:
        self.requests.append((hints, state, page_size))
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
        return Page(records=records, total=entry.get("total"), next_state=next_state,
                    notes=tuple(entry.get("notes", ())))

    def extract_ids(self, record: dict[str, object]) -> dict[str, str]:
        return {k: str(v) for k, v in record.items()
                if k in IDENTIFIER_KINDS and v}

    def build_fetch_request(self, source) -> RequestSpec:  # pragma: no cover
        return RequestSpec(url="https://fake.example/api/fulltext", params={}, headers_meta={})


class FakeLimiter:
    """Step-4 shape (RT-01…RL-01): acquire returns (bool, str) — the atomic
    decision+reason (RL-01) — and a scriptable `denials` dict makes a
    provider deny with a named reason; the walk fixtures pin the no-retry
    daily cap vs the retryable admission expiry."""

    def __init__(self, denials: dict[str, str] | None = None) -> None:
        self.acquired: list[str] = []
        self.throttled: list[tuple[str, float | None]] = []
        self.denials = dict(denials or {})
        self.acquire_calls = 0

    def acquire(self, provider: str) -> tuple[bool, str]:
        self.acquired.append(provider)
        self.acquire_calls += 1
        if provider in self.denials:
            return False, self.denials[provider]
        return True, ""

    def release(self, provider: str) -> None:
        pass

    def note_throttled(self, provider: str, retry_after: float | None) -> None:
        self.throttled.append((provider, retry_after))

    def last_denial_reason(self, provider: str) -> str:
        return self.denials.get(provider, "")


class FakeRecorder:
    def __init__(self) -> None:
        self.logs: list[RequestLogRecord] = []

    def record(self, log: RequestLogRecord) -> None:
        self.logs.append(log)


class FakeClock:
    def __init__(self) -> None:
        self.t = "2026-08-14T00:00:00Z"
        self.slept = 0.0

    def now_utc(self) -> str:
        return self.t

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, delay: float) -> None:
        self.slept += delay


# ── helpers ──


def fake_spec(provider_id: str = "fake", *, loop_guard: int = 100,
              count_semantics: str = "exact", counts_raw_rows: bool = False,
              valid_negative_statuses: list[int] | None = None,
              throttle_signature: list[dict] | None = None) -> ProviderHazardSpec:
    return load_hazard_spec(provider_id, {
        "schema": SPEC_SCHEMA,
        "provider_id": provider_id,
        "version": "1.0.0",
        "markers": [],
        "empty_body_rule": "treat-as-failure",
        "error_field": None,
        "count_semantics": count_semantics,
        "counts_raw_rows": counts_raw_rows,
        "required_fields": ["records"],  # a non-empty payload missing "records" → MALFORMED_200
        "cursor_rule": {"kind": "cursor", "loop_guard": loop_guard},
        "throttle_signature": throttle_signature or [],
        "rewrite_suspect": [],
        "fetch": None,
        "valid_negative_statuses": valid_negative_statuses or [404],
    })


def rec(doi: str, title: str = "A paper") -> dict[str, object]:
    return {"doi": doi, "title": title}


def page(*, records: list[dict] | None = None, total: int | None = None,
         next_cursor: str | None = None, status: int = 200, body: object | None = None,
         headers: dict[str, str] | None = None) -> dict:
    return {"status": status, "body": body, "records": records or [],
            "total": total, "next_cursor": next_cursor, "headers": headers or {}}


def run_walk(script: list[dict], hints: RetrievalHints,
             request: WalkRequest | None = None, spec: ProviderHazardSpec | None = None,
             pagination: dict | None = None):
    spec = spec or fake_spec()
    transport = FakeTransport(script)
    adapter = FakeAdapter(transport, pagination=pagination)
    limiter, recorder, clock = FakeLimiter(), FakeRecorder(), FakeClock()
    outcome = walk(adapter, hints, request or WalkRequest(max_results=50),
                   transport, limiter, recorder, clock, hazard_spec=spec)
    return outcome, adapter, transport, limiter, recorder, clock, spec


def lookup_hints() -> RetrievalHints:
    return parse_query_hints("doi:10.1000/abc123")


def topic_hints() -> RetrievalHints:
    return parse_query_hints("epistemic compilers")


# ── clean walks and bounds ──


def test_clean_walk_is_complete():
    out, _, _, _, recorder, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=2, next_cursor="c1"),
        page(records=[rec("10.1000/b")], total=2),
    ], topic_hints())
    assert out.aggregate == "COMPLETE"
    assert len(out.per_provider) == 2
    assert out.notes[0] == "COMPLETE(retrieved==total)"
    assert all(r.reconciliation == "COMPLETE" for r in out.per_provider)
    assert all(r.raw_retrieved_count == 2 for r in out.per_provider)
    assert all(r.delivered_count == 2 for r in out.per_provider)
    assert recorder.logs[0].cursor_chain == (None, "c1")
    assert recorder.logs[0].page_counts == ((1, 2), (1, 2))
    assert recorder.logs[0].reconciliation == "COMPLETE"


def test_bounded_by_max_results():
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a"), rec("10.1000/b"), rec("10.1000/c"),
                      rec("10.1000/d"), rec("10.1000/e")], total=20, next_cursor="c1"),
    ], topic_hints(), request=WalkRequest(max_results=3))
    assert out.aggregate == "COMPLETE"
    assert out.notes[0] == "COMPLETE(bounded-by-request(max_results))"
    assert len(out.per_provider) == 5  # page granularity


def test_bounded_by_max_pages_is_stopped_at_limit():
    # WS-03 — a REQUEST bound is STOPPED_AT_LIMIT (COMPLETE-with-note).
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=50, next_cursor="c1"),
        page(records=[rec("10.1000/b")], total=50, next_cursor="c2"),
    ], topic_hints(), request=WalkRequest(max_results=50, max_pages=2))
    assert out.notes[0] == "COMPLETE(bounded-by-request(STOPPED_AT_LIMIT))"
    assert any("STOPPED_AT_LIMIT" in n for n in out.notes)
    assert out.aggregate == "COMPLETE"


def test_spec_loop_guard_is_trap_threshold():
    # WS-03 — the SPEC guard is the trap threshold: live cursor at the guard →
    # SHORTFALL(CURSOR_TRAP), never a bare COMPLETE.
    spec = fake_spec(loop_guard=2)
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=50, next_cursor="c1"),
        page(records=[rec("10.1000/b")], total=50, next_cursor="c2"),
    ], topic_hints(), request=WalkRequest(max_results=50, max_pages=100), spec=spec)
    assert out.notes[0] == "SHORTFALL(cause=CURSOR_TRAP)"
    assert out.aggregate == "PARTIAL"
    assert len(out.per_provider) == 2


def test_repeating_cursor_traps_before_duplicate_request():
    # WS-06 — the trap fires BEFORE the duplicate request: 2 pages requested,
    # the third (duplicate cursor) is never issued.
    out, _, transport, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=5, next_cursor="c1"),
        page(records=[rec("10.1000/b")], total=5, next_cursor="c1"),
        page(records=[rec("10.1000/c")], total=5, next_cursor="c2"),
    ], topic_hints())
    assert out.notes[0] == "SHORTFALL(cause=CURSOR_TRAP)"
    assert transport.calls == 2  # the duplicate was never requested
    assert "CURSOR_TRAP" in out.request_log.hazard_verdicts  # injected (WS-06)


# ── exhaustion rules (WS-02) ──


def test_empty_page_with_live_cursor_continues():
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=2, next_cursor="c1"),
        page(records=[], total=2, next_cursor="c2"),  # empty WITH a cursor → continue
        page(records=[rec("10.1000/b")], total=2),
    ], topic_hints())
    assert out.notes[0] == "COMPLETE(retrieved==total)"
    assert len(out.per_provider) == 2


def test_empty_page_mid_walk_is_shortfall():
    # WS-02 — an empty page after a non-empty page is EMPTY_MID_WALK, never a
    # silent COMPLETE.
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=None, next_cursor="c1"),
        page(records=[], total=None),
    ], topic_hints())
    assert out.notes[0] == "SHORTFALL(cause=EMPTY_MID_WALK)"
    assert out.aggregate == "PARTIAL"
    assert len(out.per_provider) == 1  # retained, flagged


def test_first_page_empty_is_exhausted_complete():
    out, _, _, _, _, _, _ = run_walk([
        page(records=[], total=0),
    ], topic_hints())
    assert out.notes[0] == "COMPLETE(retrieved==total)"
    assert out.aggregate == "EMPTY"
    with pytest.raises(RetrievalShortfallError) as exc:
        combine([out])
    assert exc.value.aggregate == "EMPTY"


def test_zero_delivered_total_positive_is_shortfall():
    # §4.1 (d) — total > 0 with zero delivered.
    out, _, _, _, _, _, _ = run_walk([
        page(records=[], total=5),
    ], topic_hints())
    assert out.notes[0] == "SHORTFALL(cause=ZERO_DELIVERED_TOTAL_POSITIVE)"


def test_total_exceeds_retrieved_is_shortfall():
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a"), rec("10.1000/b")], total=10, next_cursor="c1"),
        page(records=[rec("10.1000/c"), rec("10.1000/d")], total=10),
    ], topic_hints())
    assert out.notes[0].startswith("SHORTFALL(cause=TOTAL_EXCEEDS_RETRIEVED")
    assert out.aggregate == "PARTIAL"


# ── counts / dedup (PS-04/PS2-05) ──


def test_counts_raw_rows_dedups_before_compare():
    # Crossref shape: total counts raw rows incl. repeats — dedup BEFORE the
    # comparison; a dedup-heavy walk is not a false SHORTFALL.
    spec = fake_spec(counts_raw_rows=True)
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a"), rec("10.1000/a"), rec("10.1000/b")], total=2),
    ], topic_hints(), spec=spec)
    assert out.notes[0] == "COMPLETE(retrieved==total)"  # 2 dedup'd == 2
    assert len(out.per_provider) == 2
    assert any("dedup" in n for n in out.notes)


def test_counts_raw_rows_false_compares_raw_rows():
    # All other providers: total is dedup-truthful — compare RAW rows, and the
    # delivered stream is still dedup'd for the consumer (PS2-05).
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a"), rec("10.1000/a"), rec("10.1000/b")], total=3),
    ], topic_hints())
    assert out.notes[0] == "COMPLETE(retrieved==total)"  # raw 3 == total 3
    assert len(out.per_provider) == 2  # stream dedup'd
    assert out.per_provider[0].raw_retrieved_count == 3
    assert out.per_provider[0].delivered_count == 2


def test_malformed_row_skipped_and_counted():
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a"), {"title": "no identifiers"}], total=2),
    ], topic_hints())
    assert out.notes[0] == "COMPLETE(retrieved==total)"
    assert any(n.startswith("MALFORMED_ROW") for n in out.notes)
    assert len(out.per_provider) == 1


def test_estimate_semantics_noted():
    # the PS2-09 matrix: an estimate total is never dedup-truthful
    spec = fake_spec(count_semantics="estimate", counts_raw_rows=True)
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=None, next_cursor="c1"),
        page(records=[rec("10.1000/b")], total=None),
    ], topic_hints(), spec=spec)
    assert out.notes[0] == "COMPLETE(total_not_reported(exhausted))"
    assert "total_is_estimate=true" in out.notes
    assert out.request_log.total_is_estimate is True


# ── page failures (WS-04) ──


def test_mid_walk_permanent_failure_shortfall_records_retained():
    # page 2 is a schema-drift MALFORMED_200 (a non-empty payload missing the
    # required "records" field) — the walk SHORTFALLs with page 1's records
    # retained-flagged.
    spec = fake_spec()
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=5, next_cursor="c1"),
        page(status=200, body={"oops": True}),  # drift → MALFORMED_200
    ], topic_hints(), spec=spec)
    assert out.notes[0] == "SHORTFALL(cause=MALFORMED_200)"
    assert out.aggregate == "PARTIAL"
    assert len(out.per_provider) == 1
    assert out.per_provider[0].reconciliation == "SHORTFALL"


def test_first_page_permanent_failure_searched_empty():
    out, _, _, _, _, _, _ = run_walk([
        page(status=200, body={"oops": True}),  # drift → MALFORMED_200
    ], topic_hints(), spec=fake_spec())
    assert out.notes[0] == "SHORTFALL(cause=MALFORMED_200)"
    assert out.aggregate == "EMPTY"  # searched (a response was classified)
    with pytest.raises(RetrievalShortfallError) as exc:
        combine([out])
    assert exc.value.aggregate == "EMPTY"


def test_throttle_retry_then_success():
    spec = fake_spec(throttle_signature=[{"status": 429, "body_pattern": None, "fields": []}])
    out, _, transport, limiter, _, clock, _ = run_walk([
        page(status=429, body={}, headers={"retry-after": "5"}),
        page(records=[rec("10.1000/a")], total=1),
    ], topic_hints(), spec=spec)
    assert out.notes[0] == "COMPLETE(retrieved==total)"
    assert limiter.throttled == [("fake", 5.0)]
    assert transport.calls == 2
    assert clock.slept > 0


def test_throttle_exhaustion_first_page_unavailable():
    # WS-07 — a provider whose first page throttles to exhaustion ran but never
    # searched → UNAVAILABLE, never EMPTY.
    spec = fake_spec(throttle_signature=[{"status": 429, "body_pattern": None, "fields": []}])
    out, _, _, _, _, _, _ = run_walk([
        page(status=429, body={}),
        page(status=429, body={}),
        page(status=429, body={}),
        page(status=429, body={}),
    ], topic_hints(), spec=spec)
    assert out.aggregate == "UNAVAILABLE"
    with pytest.raises(ProviderUnavailableError):
        combine([out])


def test_mid_walk_throttle_exhaustion_partial():
    spec = fake_spec(throttle_signature=[{"status": 429, "body_pattern": None, "fields": []}])
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=5, next_cursor="c1"),
        page(status=429, body={}),
        page(status=429, body={}),
        page(status=429, body={}),
        page(status=429, body={}),
    ], topic_hints(), spec=spec)
    assert out.notes[0] == "SHORTFALL(cause=THROTTLED)"
    assert out.aggregate == "PARTIAL"
    assert len(out.per_provider) == 1  # retained


# ── VALID_NEGATIVE and the mode gate (WS-01) ──


def test_valid_negative_lookup_is_complete():
    out, _, _, _, _, _, _ = run_walk([
        page(status=404, body={}),
    ], lookup_hints())
    assert out.notes[0] == "COMPLETE(answered-no)"
    assert out.aggregate == "COMPLETE"
    assert len(out.per_provider) == 1
    vn = out.per_provider[0]
    assert vn.valid_negative is True
    assert vn.valid_negative_for == "10.1000/abc123"
    # combine: answered-no → COMPLETE, never PARTIAL/EMPTY
    combined = combine([out])
    assert combined.aggregate == "COMPLETE"


def test_valid_negative_query_mode_is_shortfall():
    # WS-01 — a query-mode VALID_NEGATIVE page is an anomaly, never "answered".
    out, _, _, _, _, _, _ = run_walk([
        page(status=404, body={}),
    ], topic_hints())
    assert out.notes[0] == "SHORTFALL(cause=VALID_NEGATIVE_MID_WALK)"
    assert out.aggregate == "EMPTY"
    assert not any(r.valid_negative for r in out.per_provider)


def test_mixed_mode_is_query_fail_closed():
    # MIXED hints (identifier + topic) → query mode (fail-closed): a 404 is
    # never an "answered" lookup.
    hints = parse_query_hints("doi:10.1000/abc123 epistemic compilers")
    assert hints.mode == "MIXED"
    out, _, _, _, _, _, _ = run_walk([
        page(status=404, body={}),
    ], hints)
    assert out.notes[0] == "SHORTFALL(cause=VALID_NEGATIVE_MID_WALK)"


def test_valid_negative_mix_with_real_results_is_complete():
    # Matrix (d) — a lookup answered-no mixed with a delivering walk → COMPLETE.
    answered = run_walk([page(status=404, body={})], lookup_hints())[0]
    delivered = run_walk([
        page(records=[rec("10.1000/a")], total=1),
    ], topic_hints())[0]
    combined = combine([answered, delivered])
    assert combined.aggregate == "COMPLETE"
    assert len(combined.per_provider) == 2


def test_valid_negative_mix_with_empty_search_is_complete():
    # Matrix (d) — answered-no mixed with an empty topic search → COMPLETE.
    answered = run_walk([page(status=404, body={})], lookup_hints())[0]
    empty = run_walk([page(records=[], total=0)], topic_hints())[0]
    combined = combine([answered, empty])
    assert combined.aggregate == "COMPLETE"


# ── the aggregate matrix / combine (step 7) ──


def test_combine_partial_when_shortfall_with_delivery():
    clean = run_walk([page(records=[rec("10.1000/a")], total=1)], topic_hints())[0]
    short = run_walk([
        page(records=[rec("10.1000/b")], total=5),
    ], topic_hints())[0]
    combined = combine([clean, short])
    assert combined.aggregate == "PARTIAL"
    assert len(combined.per_provider) == 2


def test_combine_complete_when_empty_mixes_with_delivered():
    empty = run_walk([page(records=[], total=0)], topic_hints())[0]
    delivered = run_walk([page(records=[rec("10.1000/a")], total=1)], topic_hints())[0]
    combined = combine([empty, delivered])
    assert combined.aggregate == "COMPLETE"  # the empty provider walked cleanly
    assert any("COMPLETE" in n for n in combined.notes)


def test_combine_unavailable_never_reads_as_empty():
    unavail = run_walk([
        page(status=429, body={}), page(status=429, body={}),
        page(status=429, body={}), page(status=429, body={}),
    ], topic_hints(), spec=fake_spec(
        throttle_signature=[{"status": 429, "body_pattern": None, "fields": []}]))[0]
    with pytest.raises(ProviderUnavailableError):
        combine([unavail])


def test_combine_fixed_order():
    a = run_walk([page(records=[rec("10.1000/a")], total=1)], topic_hints())[0]
    b = run_walk([page(records=[rec("10.1000/b")], total=1)], topic_hints())[0]
    combined = combine([b, a], order=["fake_a", "fake_b"])
    # both walks share provider id "fake" — the order list is honored by key
    assert combined.aggregate == "COMPLETE"


def test_reading_rule_complete_is_resolution_signal():
    # WS-05 — COMPLETE-with-STOPPED_AT_LIMIT never claims full coverage; the
    # note is the coverage signal.
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=50, next_cursor="c1"),
    ], topic_hints(), request=WalkRequest(max_results=50, max_pages=1))
    assert out.aggregate == "COMPLETE"
    assert any("STOPPED_AT_LIMIT" in n for n in out.notes)
    assert out.request_log.reconciliation == "COMPLETE"


# ── shipped-driver audit fold-in (WK-01…WK-07) ──


def _down_outcome():
    """A provider that ran but never searched (throttle exhaustion) —
    aggregate UNAVAILABLE with a SHORTFALL(cause=THROTTLED) note."""
    return run_walk([
        page(status=429, body={}), page(status=429, body={}),
        page(status=429, body={}), page(status=429, body={}),
    ], topic_hints(), spec=fake_spec(
        throttle_signature=[{"status": 429, "body_pattern": None, "fields": []}]))[0]


def test_wk01_answered_lookup_does_not_mask_failed_leg():
    # WK-01 — the answered_no branch consults the shortfall signal: a lookup
    # answered-no + a searched-then-failed query leg is PARTIAL, never the
    # COMPLETE that hides the failed leg.
    answered = run_walk([page(status=404, body={})], lookup_hints())[0]
    failed_q = run_walk([
        page(status=200, body={"oops": True}),  # drift → MALFORMED_200
    ], topic_hints(), spec=fake_spec())[0]
    assert answered.aggregate == "COMPLETE"
    assert failed_q.aggregate == "EMPTY"
    assert failed_q.notes[0].startswith("SHORTFALL(cause=MALFORMED_200)")
    combined = combine([answered, failed_q])
    assert combined.aggregate == "PARTIAL"


def test_wk02_down_provider_never_partial_trigger():
    # WK-02 — the shortfall scan excludes UNAVAILABLE sub-outcomes: delivered
    # + down stays COMPLETE (matrix (a): down providers are recorded in
    # notes, never PARTIAL triggers).
    delivered = run_walk([page(records=[rec("10.1000/a")], total=1)], topic_hints())[0]
    down = _down_outcome()
    assert down.aggregate == "UNAVAILABLE"
    assert any(n.startswith("SHORTFALL(") for n in down.notes)
    combined = combine([delivered, down])
    assert combined.aggregate == "COMPLETE"
    assert any("SHORTFALL" in n for n in combined.notes)  # still recorded


def test_wk02_answered_lookup_with_down_provider_complete():
    # Matrix (c) — answered + down stays COMPLETE (never PARTIAL) now that the
    # scan excludes the UNAVAILABLE leg.
    answered = run_walk([page(status=404, body={})], lookup_hints())[0]
    combined = combine([answered, _down_outcome()])
    assert combined.aggregate == "COMPLETE"


def test_wk03_bounded_no_total_is_unknown():
    # WK-03 — bounded-by-request with NO total is the contract's UNKNOWN case,
    # not COMPLETE.
    out, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=None, next_cursor="c1"),
    ], topic_hints(), request=WalkRequest(max_results=1))
    assert out.notes[0] == "UNKNOWN(total_not_reported(bounded))"
    # A delivered + UNKNOWN reconciliation is PARTIAL at every level — the
    # single-provider restriction of matrix (a): coverage cannot be claimed.
    assert out.aggregate == "PARTIAL"
    combined = combine([out])
    assert combined.aggregate == "PARTIAL"


def test_wk04_zero_delivered_total_positive_when_bounded():
    # WK-04 — §4.1 (d) dominates the bound reasons: total 50, zero delivered,
    # page bound → SHORTFALL, never COMPLETE(STOPPED_AT_LIMIT).
    out, _, _, _, _, _, _ = run_walk([
        page(records=[], total=50, next_cursor="c1"),
        page(records=[], total=50, next_cursor="c2"),
    ], topic_hints(), request=WalkRequest(max_results=50, max_pages=2))
    assert out.notes[0] == "SHORTFALL(cause=ZERO_DELIVERED_TOTAL_POSITIVE)"
    assert out.aggregate == "EMPTY"  # searched, found nothing — the (d) signal
    with pytest.raises(RetrievalShortfallError) as exc:
        combine([out])
    assert exc.value.aggregate == "EMPTY"


def test_wk05_retries_acquire_per_attempt():
    # WK-05 — every transport request is a limiter acquire, retries included:
    # 2 requests for the retried page → 2 acquires (the budget ledger's cost
    # input under-accounting is closed).
    spec = fake_spec(throttle_signature=[{"status": 429, "body_pattern": None, "fields": []}])
    out, _, transport, limiter, _, _, _ = run_walk([
        page(status=429, body={}, headers={"retry-after": "5"}),
        page(records=[rec("10.1000/a")], total=1),
    ], topic_hints(), spec=spec)
    assert out.notes[0] == "COMPLETE(retrieved==total)"
    assert transport.calls == 2
    assert limiter.acquired == ["fake", "fake"]


def test_wk06_raises_carry_notes():
    # WK-06 — the EMPTY/UNAVAILABLE raises carry the merged notes: WHICH
    # provider shortfalled and why, not just that one did.
    empty = run_walk([page(records=[], total=0)], topic_hints())[0]
    with pytest.raises(RetrievalShortfallError) as exc:
        combine([empty])
    assert exc.value.notes and exc.value.notes[0] == "COMPLETE(retrieved==total)"
    with pytest.raises(ProviderUnavailableError) as exc:
        combine([_down_outcome()])
    assert exc.value.notes and any(n.startswith("SHORTFALL(") for n in exc.value.notes)


def test_wk07_max_results_bound_reads_raw_retrieved():
    # WK-07 — the max_results bound reads RAW rows: 3 raw rows reach the bound
    # on page 1 (the old dedup'd-count bound would have issued a second
    # request), and the dedup reduction below the bound is noted.
    out, _, transport, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a"), rec("10.1000/a"), rec("10.1000/a")],
             total=5, next_cursor="c1"),
        page(records=[rec("10.1000/b")], total=5),
    ], topic_hints(), request=WalkRequest(max_results=3))
    assert out.notes[0] == "COMPLETE(bounded-by-request(max_results))"
    assert any("dedup_reduced_below_bound" in n for n in out.notes)
    assert transport.calls == 1  # the second page was never requested
    assert len(out.per_provider) == 1
    assert out.per_provider[0].raw_retrieved_count == 3


# ── third-gate fold-in (WK3-01…WK3-03) ──


def test_wk301_lease_limiter_releases_per_request():
    # WK3-01 — every acquire is released: a concurrency-1 LEASE limiter (the
    # Protocol's `release` + RateProfile.concurrency anticipate exactly this)
    # neither blocks the retry path nor leaks a slot at walk end — the
    # acquire/release contract is pinned by behavior, not by docstring.
    class LeaseLimiter:
        def __init__(self) -> None:
            self.held = 0
            self.acquires = 0
            self.releases = 0

        def acquire(self, provider: str) -> tuple[bool, str]:
            assert self.held < 1, "slot exhausted (previous acquire never released)"
            self.held += 1
            self.acquires += 1
            return True, ""

        def release(self, provider: str) -> None:
            self.held -= 1
            self.releases += 1

        def note_throttled(self, provider: str, retry_after: float | None) -> None:
            pass

        def last_denial_reason(self, provider: str) -> str:
            return ""

    spec = fake_spec(throttle_signature=[{"status": 429, "body_pattern": None, "fields": []}])
    transport = FakeTransport([
        page(status=429, body={}, headers={"retry-after": "5"}),
        page(records=[rec("10.1000/a")], total=1),
    ])
    adapter = FakeAdapter(transport)
    limiter = LeaseLimiter()
    outcome = walk(adapter, topic_hints(), WalkRequest(max_results=50),
                   transport, limiter, FakeRecorder(), FakeClock(), hazard_spec=spec)
    assert outcome.notes[0] == "COMPLETE(retrieved==total)"
    assert limiter.acquires == 2 and limiter.releases == 2  # retry accounted + released
    assert limiter.held == 0  # no leaked slot


def test_wk302_note_scan_is_single_source_of_truth():
    # WK3-02 — the scan keys ONLY on the SHORTFALL/UNKNOWN notes: a hand-built
    # outcome carrying aggregate="PARTIAL" with no note is NOT a trigger
    # (every driver-produced PARTIAL outcome carries a prefix note — this is
    # the unexplainable-PARTIAL class, closed).
    clean = run_walk([page(records=[rec("10.1000/a")], total=1)], topic_hints())[0]
    hand_built = SearchOutcome(
        per_provider=(), aggregate="PARTIAL", notes=(), request_log=None)
    combined = combine([clean, hand_built])
    assert combined.aggregate == "COMPLETE"
    # and a driver-produced PARTIAL (with its note) still triggers:
    short = run_walk([
        page(records=[rec("10.1000/b")], total=5),
    ], topic_hints())[0]
    assert combine([clean, short]).aggregate == "PARTIAL"


def test_wk303_total_decline_is_named():
    # WK3-03 — a cross-page total decline is named in the notes, never
    # silently accepted as a provider revising its count.
    out, _, _, _, _, _, _ = run_walk([
        page(records=[], total=50, next_cursor="c1"),
        page(records=[], total=0),
    ], topic_hints())
    assert out.notes[0] == "SHORTFALL(cause=EMPTY_MID_WALK)"  # the anomaly still fires
    assert any(n.startswith("total_declined: 50 -> 0") for n in out.notes)

    # with delivery — the decline note rides alongside the verdict:
    out2, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/a")], total=50, next_cursor="c1"),
        page(records=[rec("10.1000/b")], total=0),
    ], topic_hints())
    assert any(n.startswith("total_declined: 50 -> 0") for n in out2.notes)

    # a rise or equality is NOT a decline:
    out3, _, _, _, _, _, _ = run_walk([
        page(records=[rec("10.1000/c")], total=0, next_cursor="c1"),
        page(records=[rec("10.1000/d")], total=50),
    ], topic_hints())
    assert not any(n.startswith("total_declined") for n in out3.notes)


# ── ADV-08: fail-closed / exception boundaries ──
# The objective: expected provider hazards → deterministic verdicts; contract/
# programming failures → LOUD, never silently converted into a search result.
# The driver's "never raises" guarantee is scoped to hazard verdicts — the
# walks below pin the boundary on both sides.

class BrokenParseAdapter(FakeAdapter):
    """Adapter contract violation: parse_page raises a programming error."""

    def parse_page(self, payload: object, state: PageState) -> Page:
        raise RuntimeError("adapter bug: cannot parse page")


class FailingRecorder:
    """Recorder (audit-trail) persistence failure."""

    def record(self, log: RequestLogRecord) -> None:
        raise OSError("audit store unavailable")


class RedactionFailureTransport:
    """A RedactionError escaping the transport — a config/programming failure,
    never a provider page hazard."""

    def request(self, spec: RequestSpec) -> TransportResponse:
        raise RedactionError("policy gap: param 'api_key' has no redaction rule")


def test_adv08_adapter_contract_violation_is_loud(db_unused=None):
    # An adapter that raises is a Hermes-side programming error — it must
    # PROPAGATE loudly, never become a MALFORMED_200 search verdict or a
    # silent empty result.
    script = [page(records=[rec("10.1000/a")], total=1)]
    spec = fake_spec()
    transport = FakeTransport(script)
    adapter = BrokenParseAdapter(transport)
    limiter, recorder, clock = FakeLimiter(), FakeRecorder(), FakeClock()
    with pytest.raises(RuntimeError, match="adapter bug"):
        walk(adapter, topic_hints(), WalkRequest(max_results=50),
             transport, limiter, recorder, clock, hazard_spec=spec)


def test_adv08_recorder_failure_is_loud():
    # A recorder (request-log persistence) failure must NOT be swallowed: the
    # audit record is authoritative; losing it silently would hide the walk.
    script = [page(records=[rec("10.1000/a")], total=1)]
    spec = fake_spec()
    transport = FakeTransport(script)
    adapter = FakeAdapter(transport)
    limiter, clock = FakeLimiter(), FakeClock()
    with pytest.raises(OSError, match="audit store unavailable"):
        walk(adapter, topic_hints(), WalkRequest(max_results=50),
             transport, limiter, FailingRecorder(), clock, hazard_spec=spec)


def test_adv08_redaction_error_from_transport_is_loud_never_malformed():
    # ADV-08 — a NON-permanent ProviderError (RedactionError) escaping the
    # transport is a contract/programming failure: re-raise loudly. Pre-fix,
    # the broad `except ProviderError` converted it into a MALFORMED_200 page
    # verdict — a misleading search result from a config bug.
    spec = fake_spec()
    limiter, recorder, clock = FakeLimiter(), FakeRecorder(), FakeClock()
    with pytest.raises(RedactionError):
        walk(FakeAdapter(RedactionFailureTransport()), topic_hints(),
             WalkRequest(max_results=50), RedactionFailureTransport(),
             limiter, recorder, clock, hazard_spec=spec)


def test_adv08_permanent_transport_failure_stays_a_verdict():
    # Positive control: a REAL permanent transport hazard (PARTIAL_CONTENT)
    # still resolves to a deterministic verdict — never a raise.
    class SizeAbortTransport:
        def request(self, spec: RequestSpec) -> TransportResponse:
            raise PermanentProviderError(
                "body exceeds cap", hazard_class="PARTIAL_CONTENT")

    spec = fake_spec()
    limiter, recorder, clock = FakeLimiter(), FakeRecorder(), FakeClock()
    outcome = walk(FakeAdapter(SizeAbortTransport()), topic_hints(),
                   WalkRequest(max_results=50), SizeAbortTransport(),
                   limiter, recorder, clock, hazard_spec=spec)
    assert outcome.notes[0] == "SHORTFALL(cause=PARTIAL_CONTENT)"
