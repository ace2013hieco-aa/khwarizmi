"""The reconciliation walk driver (blueprint §5.1, remediated WS-01…WS-07).

Step 3 of the Part 3 implementation (IDR-030, §27 item 55 RESOLVED). Two
entry points:

- `walk(...)` — ONE provider's walk (blueprint steps 1–6): routing/mode,
  the page loop with limiter/redaction/hazard/parse, the cursor guard, the
  bounds (``min(spec.loop_guard, request.max_pages)``), canonicalize + dedup,
  and the per-provider reconciliation verdict. **Never raises for a verdict** —
  the outcome carries everything (records, the verdict note, causes, notes).
- `combine(...)` — the aggregate matrix (blueprint step 7, contract §4.2):
  the full COMPLETE/PARTIAL/EMPTY/UNAVAILABLE rules incl. the valid-negative
  mixes and the ran-vs-searched terms. **This is the raising point**: a final
  `EMPTY` raises `RetrievalShortfallError(aggregate="EMPTY")`, a final
  `UNAVAILABLE` raises `ProviderUnavailableError(aggregate="UNAVAILABLE")`.

Remediated behaviors folded in (the walk review, WS-01…WS-07):

- WS-01 — the driver derives a `lookup`/`query` mode from the parsed hints
  (a pure identifier hint → lookup; TOPIC/MIXED → query — fail-closed).
  `VALID_NEGATIVE` resolution applies ONLY in lookup mode; a query-mode
  `VALID_NEGATIVE` page is `SHORTFALL(cause=VALID_NEGATIVE_MID_WALK)`.
- WS-02 — the exhaustion rule is cursor-aware AND position-aware: an empty
  page WITH a live next cursor CONTINUES; an empty page after ≥ 1 non-empty
  page is `SHORTFALL(cause=EMPTY_MID_WALK)`; "exhausted" means
  (empty ∧ no cursor ∧ first page) ∨ (no cursor after a non-empty page).
- WS-03 — the driver enforces `min(spec.cursor_rule.loop_guard,
  request.max_pages)`; hitting the SPEC guard with a live cursor is
  `SHORTFALL(cause=CURSOR_TRAP)`; hitting a REQUEST bound is
  `STOPPED_AT_LIMIT` (`COMPLETE`-with-note).
- WS-04 — any page failure after ≥ 1 successful page (transient-after-retries
  OR permanent-immediate) converts to the provider's `SHORTFALL(cause=<class>)`
  with the accumulated records retained-flagged; only a FIRST-page failure
  with zero delivery feeds the zero-delivered matrix.
- WS-05 — `COMPLETE` is a resolution signal, never a coverage claim — the
  reading rule is stated on `combine`.
- WS-06 — the trap fires BEFORE the duplicate request (seen-chain check), and
  the driver-injected `CURSOR_TRAP` verdict enters `RequestLogRecord`.
- WS-07 — "searched" = ≥ 1 response classified (a verdict other than pure
  throttle/transient exhaustion); "ran" = the transport was called.

Shipped-driver audit fold-in (WK-01…WK-07):

- WK-01 — `combine`'s `answered_no` branch consults the shortfall signal: an
  answered lookup + a searched-then-failed leg is `PARTIAL` (the failure is
  real), + down/unrun providers stays `COMPLETE` (matrix (c)).
- WK-02 — the shortfall scan EXCLUDES `UNAVAILABLE` sub-outcomes: a provider
  that could not run is recorded in notes, never a PARTIAL trigger.
- WK-03 — bounded-by-request with NO total is `UNKNOWN(total_not_reported
  (bounded))`; with a total it is `COMPLETE(bounded-by-request(max_results))`.
- WK-04 — §4.1 (d) (`total > 0`, zero delivered) runs BEFORE the bound
  branches — a declared total dominates the bound reasons.
- WK-05 — `limiter.acquire` is per transport request (inside the attempt
  loop), retries included — the budget ledger's cost input under-accounting
  is closed.
- WK-06 — the `EMPTY`/`UNAVAILABLE` raises carry the merged notes.
- WK-07 — the bounds read `raw_retrieved`, never the dedup'd stream, with a
  `dedup_reduced_below_bound` note when dedup cut the delivered stream.

Second-gate review of the TR-folded limiter/transport (RT4-01/RT4-02,
`hermes_researchsourceprovider_ratelimit_audit2.md`, FOLDED IN 2026-08-14):

- RT4-02 — `TIMEOUT` joins the not-searched set: a transport failure never
  CLASSIFIED a response, so a timeout-exhausted provider aggregates
  `UNAVAILABLE` (could not search — the PS-13-correct side), never `EMPTY`
  ("no literature"); mid-walk timeouts keep `SHORTFALL(cause=TIMEOUT)` +
  retained records (`PARTIAL`).

Third-gate audit fold-in (WK3-01…WK3-03):

- WK3-01 — every `limiter.acquire` is paired with `limiter.release` (per
  request, via try/finally in `_fetch_page`): correct under lease semantics
  (the Protocol's `release` + `RateProfile.concurrency`) and a no-op under
  charge-only — the driver holds no slot past the request.
- WK3-02 — `combine`'s shortfall scan keys SOLELY on the SHORTFALL/UNKNOWN
  notes (every driver-produced PARTIAL outcome carries one); a bare
  `aggregate="PARTIAL"` is not a trigger.
- WK3-03 — a cross-page total decline is named in the notes
  (`total_declined: <prev> -> <new>`); the (d) check still reads the
  last-reported total.

Step-4 limiter/transport integration (RT-01…RT3-05 folded in, 2026-08-14):

- RT2-03/RT3-02/03/RL-01 — `_fetch_page` checks the `acquire` return BEFORE
  the try: a `False` never reaches `release`; the reason is ATOMIC with the
  decision (`acquire -> (bool, str)`, RL-01 — the driver branches on ITS
  OWN denial, never another caller's); `daily_cap_exhausted` is a no-retry
  hard stop, `admission_wait_expired` is transient — backoff + retry the
  page; the denial reason returns with the verdict and the walk loop
  appends the cause note.
- RT2-06 — the catch-all re-raises a NON-`ProviderError` from the transport
  (a bug, loud); only `ProviderError` subclasses map to hazard classes.
- RT2-04/RT3-01/04 — the driver carries `content_type`/`body_size`/
  `size_cap_bytes` into `HazardContext` for the evaluator's pinned-slot
  label + completed-body-size checks.

The reconciliation reads `raw_retrieved_count` (PS-04/PS2-05) — never the
dedup'd stream; `counts_raw_rows: true` specs dedup by identifier BEFORE the
total comparison, per spec content, never a driver guess.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import random
from typing import Sequence

from hermes.tools.providers.base import (
    PageState,
    ProviderAdapter,
    RequestSpec,
    TransportResponse,
    WalkMode,
    WalkRequest,
)
from hermes.tools.providers.hazards import (
    HazardContext,
    ProviderHazardSpec,
    evaluate_hazards,
)
from hermes.tools.providers.normalize import (
    RetrievalHints,
    canonicalize_identifiers,
    dedup_key,
)
from hermes.tools.providers.redact import DEFAULT_POLICY, RedactionPolicy, redact_params
from hermes.tools.research_sources import (
    FetchContentRejected,
    FetchedPayload,
    FetchedSource,
    FetchFailure,
    FetchLogEntry,
    FetchOutcome,
    FetchRequest,
    NoFullText,
    PermanentProviderError,
    ProviderError,
    ProviderUnavailableError,
    ProviderValidationError,
    RequestLogRecord,
    RetrievalShortfallError,
    SearchAggregate,
    SearchOutcome,
    SearchResult,
    SourceArtifact,
    TransientProviderError,
    content_hash_of_search_result,
    make_search_result_id,
)

__all__ = ["combine", "fetch_batch", "walk"]

# Permanent classes fail the page immediately (contract §6.3) — a mid-walk
# permanent converts to SHORTFALL(cause=<class>) per WS-04. EMPTY_RESULT is
# excluded: it drives the page-shape exhaustion rules, not a page failure.
_PERMANENT_CLASSES = frozenset({
    "MALFORMED_200", "REWRITE_SUSPECT", "CURSOR_TRAP", "PARTIAL_CONTENT",
})

# Fetch-scope permanent classes (D2 — the fetch driver's closed mapping): a
# fetch response that is malformed/empty/degraded is a typed per-source
# failure, never a FetchedSource. THROTTLED/TRANSIENT/TIMEOUT retry;
# NO_FULL_TEXT/INJECTION_SUSPECT/NONE are results/advisory (the driver maps
# them explicitly).
_FETCH_PERMANENT_CLASSES = frozenset({
    "MALFORMED_200", "EMPTY_RESULT", "PARTIAL_CONTENT",
})

# The verdict-note convention — the FIRST note on every walk outcome; combine()
# keys on the prefixes. Formats: "COMPLETE(...)", "SHORTFALL(cause=...)",
# "UNKNOWN(...)".
_SHORTFALL_PREFIX = "SHORTFALL("
_UNKNOWN_PREFIX = "UNKNOWN("


def _verdict_note(verdict: str, detail: str) -> str:
    return f"{verdict}({detail})"


def _deadline_expired(deadline: float | None, clock: object) -> bool:
    """True when the dispatch's overall wall-clock budget is spent (D1).

    `deadline` is an absolute ``Clock.monotonic`` reading (None = no bound).
    Checked BEFORE each page/source and each retry attempt, so a slow or
    hung provider stops the dispatch with a typed TRANSIENT verdict instead
    of holding a controller tick open indefinitely.
    """
    if deadline is None:
        return False
    return clock.monotonic() >= deadline  # type: ignore[attr-defined]


# ── the single-provider walk (steps 1–6) ──


def walk(
    adapter: ProviderAdapter,
    hints: RetrievalHints,
    request: WalkRequest,
    transport: object,
    limiter: object,
    recorder: object,
    clock: object,
    hazard_spec: ProviderHazardSpec | None = None,
    redaction_policy: RedactionPolicy = DEFAULT_POLICY,
) -> SearchOutcome:
    """Walk ONE provider (blueprint §5.1 steps 1–6). Never raises for a
    verdict — see `combine` for the aggregate and the raising point.

    `transport`/`limiter`/`recorder`/`clock` are the runtime protocols
    (base.py); `hazard_spec` defaults to the shipped spec for the provider id.
    """
    provider = adapter.contract.provider_id
    spec = hazard_spec or _load_shipped_spec(provider)
    mode: WalkMode = "lookup" if hints.mode == "IDENTIFIER" else "query"

    pagination = adapter.contract.pagination
    kind = pagination.get("kind", "cursor")
    spec_guard = spec.cursor_rule.loop_guard
    max_pages = min(spec_guard, request.max_pages)  # WS-03
    page_size = min(request.page_size_cap, request.max_results)

    endpoint = _endpoint_of(adapter, hints)
    query = _query_of(hints)
    started = _now(clock)

    state = PageState(page_index=0)
    seen_positions: set[str] = set()
    delivered: list[SearchResult] = []
    dedup_seen: set[str] = set()
    notes: list[str] = []
    page_counts: list[tuple[int, int | None]] = []
    cursor_chain: list[str | None] = []
    hazard_verdicts: list[str] = []
    raw_retrieved = 0
    total: int | None = None
    pages_done = 0
    searched = False
    redacted_params: dict[str, str] = {}
    verdict = "COMPLETE"
    verdict_detail = "exhausted"
    reached_max_results = False
    hit_page_bound = False

    while raw_retrieved < request.max_results and pages_done < max_pages:
        if _deadline_expired(request.deadline_monotonic, clock):
            # D1 (P-AUTO-3 redteam) — the overall budget is spent: stop
            # BEFORE the next request (never after). TRANSIENT keeps the
            # not-searched discipline (RT4-02): a first page never issued
            # aggregates UNAVAILABLE ("could not search"); a mid-walk stop
            # keeps the records delivered so far under
            # SHORTFALL(cause=TRANSIENT).
            verdict, verdict_detail = "SHORTFALL", "cause=TRANSIENT"
            notes.append(_verdict_note(verdict, verdict_detail))
            notes.append("deadline_exhausted=true")
            hazard_verdicts.append("TRANSIENT")
            break
        # WS-06 — the trap fires BEFORE the duplicate request.
        pos = _position_of(state, kind)
        if pos is not None:
            if pos in seen_positions:
                # WS-06 — the trap fires BEFORE the duplicate request.
                verdict, verdict_detail = "SHORTFALL", "cause=CURSOR_TRAP"
                notes.append(_verdict_note(verdict, verdict_detail))
                notes.append(f"cursor_trap: repeating position {pos!r} (request not issued)")
                hazard_verdicts.append("CURSOR_TRAP")  # WS-06 — driver-injected
                break
            seen_positions.add(pos)

        req = adapter.build_request(hints, state, page_size)
        redacted_params = redact_params(req.params, redaction_policy)

        payload, hazard_class, failure_class, denial_reason = _fetch_page(
            adapter, spec, req, state, redacted_params, transport, limiter,
            request, clock,  # type: ignore[arg-type]
        )
        pages_done += 1
        cursor_chain.append(pos)
        hazard_verdicts.append(hazard_class)
        # WS-07 — "searched" = a response was CLASSIFIED. A permanent-class
        # page (MALFORMED_200…) is a classified response; only pure
        # throttle/transient exhaustion leaves the provider un-searched.
        # RT4-02 (second gate) — a TRANSPORT failure (TIMEOUT) is never a
        # classified response either: the not-searched set covers it, so a
        # provider that timed out to exhaustion aggregates UNAVAILABLE (could
        # not search), NEVER EMPTY ("no literature" — the PS-13 class).
        if failure_class is None or failure_class not in (
                "THROTTLED", "TRANSIENT", "TIMEOUT"):
            searched = True

        if failure_class is not None:
            # WS-04 — a page failure converts to the provider's SHORTFALL with
            # the cause; the records accumulated so far are retained-flagged.
            verdict, verdict_detail = "SHORTFALL", f"cause={failure_class}"
            notes.append(_verdict_note(verdict, verdict_detail))
            if denial_reason:
                # RT3-03 — the limiter-denial cause rides the notes: the
                # daily cap is a no-retry hard stop, the admission-wait
                # expiry is transient contention — the note names WHICH.
                notes.append(f"{denial_reason}=true")
            break

        # WS-01 — VALID_NEGATIVE resolution only in lookup mode.
        if hazard_class == "VALID_NEGATIVE":
            if mode == "lookup":
                delivered.append(_valid_negative_result(
                    adapter, hints, redacted_params, state, spec, clock))
                verdict, verdict_detail = "COMPLETE", "answered-no"
                notes.append(_verdict_note(verdict, verdict_detail))
            else:
                verdict, verdict_detail = "SHORTFALL", "cause=VALID_NEGATIVE_MID_WALK"
                notes.append(_verdict_note(verdict, verdict_detail))
            break

        page = adapter.parse_page(payload, state)
        page_counts.append((len(page.records), page.total))
        if page.total is not None:
            # WK3-03 — a cross-page total DECLINE is named, never silently
            # accepted as the provider revising its count: the (d) check reads
            # the last-reported total, so an inconsistent provider's decline is
            # visible in the notes (a fidelity pin — the anomaly itself is
            # already flagged by EMPTY_MID_WALK / TOTAL_EXCEEDS_RETRIEVED).
            if total is not None and page.total < total:
                notes.append(f"total_declined: {total} -> {page.total}")
            total = page.total
        raw_retrieved += len(page.records)
        for record in page.records:
            ids = canonicalize_identifiers(adapter.extract_ids(record))
            if not ids:
                notes.append(f"MALFORMED_ROW(page={state.page_index}): no identifiers")
                continue
            key = dedup_key(ids)
            if key is None:
                # Identifiers exist but none carries a cross-provider dedup
                # kind (doi/pmid/pmcid/arxiv — e.g. url-only) — the record is
                # still delivered; it simply participates in no dedup set.
                delivered.append(_make_result(
                    adapter, hints, redacted_params, ids, record, state, spec, clock))
                continue
            if key in dedup_seen:
                notes.append(f"dedup: {key!r} (first-seen wins)")
                continue
            dedup_seen.add(key)
            delivered.append(_make_result(
                adapter, hints, redacted_params, ids, record, state, spec, clock))

        if page.next_state is not None:
            state = page.next_state
            # WS-02 — an empty page WITH a live cursor continues the walk.
        else:
            # WS-02 — an empty page after ≥ 1 non-empty page is an anomaly,
            # never a silent "exhausted"; a first-page empty (no cursor) is a
            # legitimate "found nothing".
            if len(page.records) == 0 and (raw_retrieved > 0 or pages_done > 1):
                verdict, verdict_detail = "SHORTFALL", "cause=EMPTY_MID_WALK"
                notes.append(_verdict_note(verdict, verdict_detail))
            break

    # ── why did the loop end? (for the verdict, WS-03/WK-07) ──
    # WK-07 — the bounds read RAW rows, never the dedup'd stream: a
    # dedup-heavy walk must not over-run the resource cap, and a dedup
    # reduction below the bound is noted, never silently dropped.
    reached_max_results = raw_retrieved >= request.max_results
    hit_page_bound = pages_done >= max_pages
    if reached_max_results and len(delivered) < raw_retrieved:
        notes.append(
            f"dedup_reduced_below_bound: raw={raw_retrieved} delivered={len(delivered)}")

    # ── reconciliation verdict (contract §4.1, WS-02/03/06, WK-03/04) ──
    if verdict == "SHORTFALL":
        pass  # trap / mid-walk failure / VN-mid-walk / EMPTY_MID_WALK already set
    elif pages_done == 0:
        # Never searched — every attempt was throttle/transient exhaustion.
        # The single-provider aggregate will be UNAVAILABLE (WS-07).
        verdict, verdict_detail = "SHORTFALL", "cause=NEVER_SEARCHED"
        notes.append(_verdict_note(verdict, verdict_detail))
    elif len(delivered) == 0 and total is not None and total > 0:
        # §4.1 (d) — WK-04: a declared total > 0 with zero delivery dominates
        # the bound reasons (the provider demonstrably HAS results). Fires
        # before reached_max_results / hit_page_bound so a bounded walk cannot
        # mask it as COMPLETE(STOPPED_AT_LIMIT).
        verdict, verdict_detail = "SHORTFALL", "cause=ZERO_DELIVERED_TOTAL_POSITIVE"
        notes.append(_verdict_note(verdict, verdict_detail))
    elif reached_max_results:
        # §4.1 (b) — WK-03: bounded-by-request is COMPLETE WITH a total; the
        # no-total bounded walk is the contract's UNKNOWN case.
        if total is None:
            verdict, verdict_detail = "UNKNOWN", "total_not_reported(bounded)"
            notes.append(_verdict_note(verdict, verdict_detail))
        else:
            verdict, verdict_detail = "COMPLETE", "bounded-by-request(max_results)"
    elif hit_page_bound:
        # WS-03 — the SPEC guard is the trap threshold; a REQUEST bound is
        # STOPPED_AT_LIMIT (bounded, COMPLETE-with-note / UNKNOWN no-total).
        if pages_done >= spec_guard:
            verdict, verdict_detail = "SHORTFALL", "cause=CURSOR_TRAP"
            notes.append(_verdict_note(verdict, verdict_detail))
        else:
            notes.append("STOPPED_AT_LIMIT: more pages remained at request bounds")
            if total is None:
                verdict, verdict_detail = "UNKNOWN", "total_not_reported(bounded)"
            else:
                verdict, verdict_detail = "COMPLETE", "bounded-by-request(STOPPED_AT_LIMIT)"
    else:
        # Exhausted naturally (no next cursor).
        if total is None:
            verdict, verdict_detail = "COMPLETE", "total_not_reported(exhausted)"
        else:
            effective = _effective_retrieved(spec, dedup_seen, raw_retrieved)
            if effective == total:
                verdict, verdict_detail = "COMPLETE", "retrieved==total"
            else:
                verdict, verdict_detail = "SHORTFALL", "cause=TOTAL_EXCEEDS_RETRIEVED"

    notes = _ensure_verdict_first(notes, verdict, verdict_detail)
    if spec.count_semantics == "estimate":
        notes.append("total_is_estimate=true")

    log = RequestLogRecord(
        provider=provider,
        endpoint=endpoint,
        query=query,
        request_params_redacted=redacted_params,
        timestamps=(started, _now(clock)),
        cursor_chain=tuple(cursor_chain),
        page_counts=tuple(page_counts),
        reconciliation=verdict,
        total_is_estimate=spec.count_semantics == "estimate",
        hazard_verdicts=tuple(hazard_verdicts),
        provider_spec_version=spec.version,
        raw_artifact_hashes=(),
    )
    recorder.record(log)  # type: ignore[attr-defined]

    _patch_delivered(delivered, verdict, raw_retrieved, total, spec)

    aggregate: SearchAggregate = _single_provider_aggregate(delivered, searched, notes)
    return SearchOutcome(
        per_provider=tuple(delivered),
        aggregate=aggregate,
        notes=tuple(notes),
        request_log=log,
    )


# ── the aggregate matrix (step 7, contract §4.2) ──


def combine(
    outcomes: Sequence[SearchOutcome],
    order: Sequence[str] | None = None,
) -> SearchOutcome:
    """The aggregate matrix (contract §4.2) over per-provider walk outcomes,
    serialized in the fixed allowlist order (PS-05) when `order` is given.
    Raises `RetrievalShortfallError(aggregate="EMPTY")` for a final
    zero-delivery searched aggregate, `ProviderUnavailableError` for
    UNAVAILABLE.

    Reading rule (WS-05): the returned aggregate is a RESOLUTION signal, never
    a coverage claim — `COMPLETE` includes bounded-by-request and no-total
    cases; any coverage conclusion must read the per-provider records + notes.
    WK-01: `answered_no` resolves `PARTIAL` when a *searched* leg shortfalled
    (the failure is real), `COMPLETE` when the non-answered legs are merely
    down/unrun (matrix (c), WK-02).
    """
    if order is not None:
        by_provider = {o.request_log.provider if o.request_log else "": o for o in outcomes}
        ordered = [by_provider[p] for p in order if p in by_provider]
        ordered += [o for o in outcomes if o not in ordered]
    else:
        ordered = list(outcomes)

    records = [r for o in ordered for r in o.per_provider]
    notes = [n for o in ordered for n in o.notes]

    real_delivered = any(not r.valid_negative for r in records)
    answered_no = any(r.valid_negative for r in records)
    # WS-07 — EMPTY requires ≥ 1 provider SEARCHED (a classified response);
    # a UNAVAILABLE sub-outcome never qualifies the EMPTY side.
    any_searched = any(o.aggregate != "UNAVAILABLE" for o in ordered)
    # WK-02 — the shortfall scan EXCLUDES UNAVAILABLE sub-outcomes: a provider
    # that could not run is "recorded in notes" (matrix (a)/(c)), never a
    # PARTIAL trigger. Only *searched* providers (aggregate != UNAVAILABLE)
    # carrying a SHORTFALL/UNKNOWN note count.
    # WK3-02 — the notes are the single source of truth: every driver-produced
    # PARTIAL outcome already carries a prefix note (_single_provider_aggregate
    # returns PARTIAL only after its own note scan), so a bare
    # aggregate="PARTIAL" is not a trigger (and would be unexplainable under
    # the WS-05 note-reading rule anyway).
    any_shortfall_or_unknown = any(
        o.aggregate != "UNAVAILABLE"
        and any(n.startswith(_SHORTFALL_PREFIX) or n.startswith(_UNKNOWN_PREFIX)
                for n in o.notes)
        for o in ordered
    )    # (a) ≥ 1 real result delivered → PARTIAL if any provider SHORTFALL/UNKNOWN.
    aggregate: SearchAggregate
    if real_delivered:
        aggregate = "PARTIAL" if any_shortfall_or_unknown else "COMPLETE"
    # (c)/(d) — a valid-negative answer is an answered lookup (walk() enforces
    #     the lookup-mode gate, WS-01).
    elif answered_no:
        # WK-01 — an answered lookup + a searched-then-failed leg is PARTIAL
        # (the failure is real: "every routed provider resolved" is false); +
        # down/unrun providers stays COMPLETE per matrix (c) — those are
        # excluded by the WK-02 scan.
        aggregate = "PARTIAL" if any_shortfall_or_unknown else "COMPLETE"
    # (b) — zero delivered: EMPTY (searched, found nothing) vs UNAVAILABLE
    #     (could not search); WS-07.
    elif any_searched:
        aggregate = "EMPTY"
    else:
        aggregate = "UNAVAILABLE"

    providers = sorted({o.request_log.provider for o in ordered if o.request_log})
    if aggregate == "EMPTY":
        # WK-06 — the raise carries the merged notes: WHICH provider
        # shortfalled and why, not just that one did.
        raise RetrievalShortfallError(
            "search ran and found nothing",
            provider_id=", ".join(providers),
            got=0,
            cause_class="EMPTY",
            aggregate="EMPTY",
            notes=notes,
        )
    if aggregate == "UNAVAILABLE":
        raise ProviderUnavailableError(
            "could not search — no provider searched",
            provider_id=", ".join(providers),
            hazard_class="UNAVAILABLE",
            notes=notes,
        )

    return SearchOutcome(
        per_provider=tuple(records),
        aggregate=aggregate,
        notes=tuple(notes),
        request_log=None,
    )


# ── internals ──


def _single_provider_aggregate(
    delivered: list[SearchResult], searched: bool, notes: list[str]
) -> SearchAggregate:
    """The single-provider restriction of the matrix — walk()'s own aggregate
    (self-describing); combine() re-derives the final aggregate from these."""
    if not searched and not delivered:
        return "UNAVAILABLE"
    if not delivered:
        return "EMPTY" if searched else "UNAVAILABLE"
    if not any(not r.valid_negative for r in delivered):
        return "COMPLETE"  # valid-negative-only lookup — answered
    if any(n.startswith(_SHORTFALL_PREFIX) or n.startswith(_UNKNOWN_PREFIX)
           for n in notes):
        return "PARTIAL"
    return "COMPLETE"


def _fetch_page(
    adapter: ProviderAdapter,
    spec: ProviderHazardSpec,
    req: RequestSpec,
    state: PageState,
    redacted_params: dict[str, str],
    transport: object,
    limiter: object,
    request: WalkRequest,
    clock: object,
) -> tuple[object | None, str, str | None, str]:
    """One page with transient retry (contract §6.3): THROTTLED/TRANSIENT are
    retried with backoff honoring Retry-After, ≤ max_retries; permanent classes
    fail immediately. Returns (decoded payload, hazard class,
    failure_class | None, denial_reason | '') — a failure_class non-None
    means retries exhausted (transient) or a permanent class; the driver
    shapes it per WS-04. `denial_reason` (RT3-03) carries the limiter's
    `last_denial_reason` after an acquire `False` — 'daily_cap_exhausted'
    (no retry) vs 'admission_wait_expired' (transient — the attempt loop
    retried); '' otherwise — the walk loop appends the cause note."""
    policy = request.retry_policy
    attempts = getattr(policy, "max_retries", 3) + 1
    base_delay = getattr(policy, "base_delay_seconds", 1.0)
    max_delay = getattr(policy, "max_delay_seconds", 30.0)
    jitter = getattr(policy, "jitter", True)

    last_failure: str | None = None
    denial_reason = ""
    for attempt in range(attempts):
        if _deadline_expired(request.deadline_monotonic, clock):
            # D1 — the overall budget is spent mid-retries: stop now with the
            # transient verdict the retry loop would produce at exhaustion.
            return None, "TRANSIENT", "TRANSIENT", "deadline_exhausted"
        # RT2-03/RT3-02/03 — the acquire return-check happens BEFORE the try:
        # a False NEVER reaches the finally:release (a release of an
        # un-acquired slot would underflow the semaphore and admit MORE than
        # `concurrency`). False is reserved for the daily cap (a no-retry
        # hard stop); the admission-wait expiry is TRANSIENT contention —
        # backoff and RETRY the page (the next acquire may succeed; the
        # per-request release pattern frees the slot). The cause rides
        # `last_denial_reason` (RT3-03) and returns with the verdict for the
        # walk loop's cause note. The acquire itself is still per transport
        # request, retries included (WK-05) and every grant is released
        # before the attempt ends (WK3-01).
        granted, reason = limiter.acquire(spec.provider_id)  # type: ignore[attr-defined]
        if not granted:
            # RL-01 (fourth gate) — the denial reason is ATOMIC with the
            # decision (acquire -> (bool, str), one lock): the driver can no
            # longer read another caller's denial between its own False and a
            # separate accessor call, so the branch below is ALWAYS the
            # caller's own cause. False is reserved for the daily cap (a
            # no-retry hard stop); the admission-wait expiry is TRANSIENT
            # contention — backoff and RETRY the page (the next acquire may
            # succeed; the per-request release pattern frees the slot). The
            # cause returns with the verdict for the walk loop's note.
            if reason == "daily_cap_exhausted":
                return None, "THROTTLED", "THROTTLED", reason
            denial_reason = reason or "admission_wait_expired"
            last_failure = "THROTTLED"
            _backoff(clock, base_delay, max_delay, jitter, attempt)
            continue
        try:
            try:
                resp: TransportResponse = transport.request(req)  # type: ignore[attr-defined]
            except TransientProviderError as exc:
                last_failure = exc.hazard_class or "TRANSIENT"
                _backoff(clock, base_delay, max_delay, jitter, attempt)
                continue
            except PermanentProviderError as exc:
                # transport-level permanent (message redacted) — named class
                cls = exc.hazard_class or "MALFORMED_200"
                return None, cls, cls, ""
            except ProviderError:
                # ADV-08 — any OTHER ProviderError escaping the transport
                # (RedactionError, ProviderValidationError,
                # ProviderUnavailableError) is a contract/programming failure,
                # NOT a provider page hazard: re-raise loudly, never a
                # MALFORMED_200 search verdict (the same discipline as the
                # non-ProviderError catch below).
                raise
            except Exception:
                # RT2-06 — a NON-ProviderError escaping the transport is a
                # BUG (http.py raises only ProviderError subclasses): re-raise
                # loudly, never a MALFORMED_200 schema verdict.
                raise
        finally:
            limiter.release(spec.provider_id)  # type: ignore[attr-defined]

        verdict = evaluate_hazards(
            spec.provider_id,
            spec,
            resp.body,
            HazardContext(
                scope="SEARCH",
                status_code=resp.status,
                request_params=redacted_params,
                endpoint=req.url,
                # RT2-04/RT3-01/04 (step 4) — the label + completed-body size
                # evidence for the evaluator's pinned-slot checks.
                content_type=getattr(resp, "content_type", None),
                body_size=len(resp.body),
                size_cap_bytes=getattr(request, "size_cap_bytes", None),
            ),
        )
        hazard = verdict.hazard_class
        if hazard in ("THROTTLED", "TRANSIENT"):
            limiter.note_throttled(  # type: ignore[attr-defined]
                spec.provider_id, _retry_after(resp))
            last_failure = hazard
            _backoff(clock, base_delay, max_delay, jitter, attempt)
            continue
        # Permanent classes (contract §6.3) fail immediately — never retried.
        # EMPTY_RESULT is NOT permanent: an empty page flows through the page
        # shape and drives the exhaustion/EMPTY_MID_WALK rules (WS-02).
        if hazard in _PERMANENT_CLASSES:
            return None, hazard, hazard, ""
        return _decode_payload(resp.body), hazard, None, ""

    return None, last_failure or "TRANSIENT", last_failure or "TRANSIENT", denial_reason


def _decode_payload(body: bytes) -> object | None:
    if not body or not body.strip():
        return None
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    try:
        return json.loads(text)
    except ValueError:
        return text


def _retry_after(resp: TransportResponse) -> float | None:
    raw = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _backoff(clock: object, base: float, max_delay: float, jitter: bool, attempt: int) -> None:
    delay = min(max_delay, base * (2 ** attempt))
    if jitter:
        delay *= random.uniform(0.5, 1.0)
    sleep = getattr(clock, "sleep", None)
    if sleep is not None:
        sleep(delay)


def _position_of(state: PageState, kind: str) -> str | None:
    if kind == "cursor":
        return state.cursor
    if kind == "offset":
        return None if state.offset is None else str(state.offset)
    return None


def _effective_retrieved(spec: ProviderHazardSpec, dedup_seen: set[str], raw: int) -> int:
    """PS-04/PS2-05 — `counts_raw_rows: true` (Crossref) compares the dedup'd
    identifier count against `total`; everything else compares raw rows."""
    return len(dedup_seen) if spec.counts_raw_rows else raw


def _make_result(
    adapter: ProviderAdapter,
    hints: RetrievalHints,
    redacted_params: dict[str, str],
    ids: dict[str, str],
    record: dict[str, object],
    state: PageState,
    spec: ProviderHazardSpec,
    clock: object,
) -> SearchResult:
    provider = adapter.contract.provider_id
    endpoint = _endpoint_of(adapter, hints)
    query = _query_of(hints)
    return SearchResult(
        result_id=make_search_result_id(
            provider, endpoint, query, state.page_index, state.cursor, ids),
        provider=provider,
        endpoint=endpoint,
        query=query,
        request_params_redacted=redacted_params,
        identifiers=ids,
        title=_str_field(record, "title"),
        authors=(),
        year=None,
        venue="",
        abstract_sha256=None,
        source_url=_str_field(record, "url"),
        access_timestamp_utc=_now(clock),
        page_index=state.page_index,
        cursor_key=state.cursor,
        raw_retrieved_count=0,  # patched with the walk-final counts
        delivered_count=0,
        total_count=None,
        total_is_estimate=spec.count_semantics == "estimate",
        reconciliation="COMPLETE",
        content_hash="",
        provenance={"provider_spec_version": spec.version},
    )


def _valid_negative_result(
    adapter: ProviderAdapter,
    hints: RetrievalHints,
    redacted_params: dict[str, str],
    state: PageState,
    spec: ProviderHazardSpec,
    clock: object,
) -> SearchResult:
    """PS-11 — a real "no" on an identifier lookup is a RESULT: a record with
    `valid_negative: true` + the identifier that resolved to "no"."""
    provider = adapter.contract.provider_id
    endpoint = _endpoint_of(adapter, hints)
    query = _query_of(hints)
    # HR-04 — the same single normalization path as the record-extraction
    # branch: a hand-built spec.hints payload (source_handlers._hints_from_spec)
    # bypasses parse_query_hints, so the walk canonicalizes here too. The pass
    # is idempotent, so the already-canonical parse_query_hints path is a no-op.
    ids = canonicalize_identifiers(dict(hints.identifiers))
    return SearchResult(
        result_id=make_search_result_id(
            provider, endpoint, query, state.page_index, state.cursor, ids),
        provider=provider,
        endpoint=endpoint,
        query=query,
        request_params_redacted=redacted_params,
        identifiers=ids,
        title="",
        authors=(),
        year=None,
        venue="",
        abstract_sha256=None,
        source_url="",
        access_timestamp_utc=_now(clock),
        page_index=state.page_index,
        cursor_key=state.cursor,
        raw_retrieved_count=0,
        delivered_count=1,
        total_count=None,
        total_is_estimate=spec.count_semantics == "estimate",
        reconciliation="COMPLETE",
        content_hash="",
        provenance={"provider_spec_version": spec.version},
        valid_negative=True,
        # HR-04 — the identifier that resolved to "no" is the CANONICAL form
        # (the same `ids` persisted on the record), never the raw hint value.
        valid_negative_for=next(iter(ids.values()), None),
    )


def _patch_delivered(
    delivered: list[SearchResult],
    verdict: str,
    raw_retrieved: int,
    total: int | None,
    spec: ProviderHazardSpec,
) -> None:
    """Fill the walk-final counts + reconciliation onto every record (frozen —
    `dataclasses.replace`)."""
    for i, r in enumerate(delivered):
        patched = dataclasses.replace(
            r,
            reconciliation=verdict,
            raw_retrieved_count=raw_retrieved,
            delivered_count=len(delivered),
            total_count=total,
            total_is_estimate=spec.count_semantics == "estimate",
        )
        delivered[i] = dataclasses.replace(
            patched, content_hash=content_hash_of_search_result(patched))


def _ensure_verdict_first(notes: list[str], verdict: str, detail: str) -> list[str]:
    first = _verdict_note(verdict, detail)
    if notes and notes[0].startswith(verdict + "("):
        return notes
    return [first, *notes]


def _str_field(record: dict[str, object], key: str) -> str:
    value = record.get(key)
    return value if isinstance(value, str) else ""


def _now(clock: object) -> str:
    now = getattr(clock, "now_utc", None)
    return now() if now is not None else ""


def _query_of(hints: RetrievalHints) -> str:
    if hints.mode == "IDENTIFIER" and hints.identifiers:
        return next(iter(hints.identifiers.values()))
    return hints.topic


def _endpoint_of(adapter: ProviderAdapter, hints: RetrievalHints) -> str:
    route = None
    if hints.mode == "IDENTIFIER" and hints.identifiers:
        kind = next(iter(hints.identifiers))
        route = adapter.contract.hint_routes.get(kind)
    if route is None:
        return adapter.contract.base_url
    return f"{adapter.contract.base_url}/{route}"


def _load_shipped_spec(provider: str) -> ProviderHazardSpec:
    import json as _json
    from pathlib import Path

    from hermes.tools.providers.hazards import load_hazard_spec

    path = Path(__file__).resolve().parent / "hazard_specs" / f"{provider}.json"
    if not path.exists():
        raise ValueError(
            f"no shipped hazard spec for {provider!r} — pass hazard_spec= explicitly")
    return load_hazard_spec(provider, _json.loads(path.read_text(encoding="utf-8")))


# ── the fetch driver (step 5a — blueprint §5.3, gate-remediated) ──


def fetch_batch(
    adapter: ProviderAdapter,
    sources: list[SearchResult],
    request: FetchRequest,
    transport: object,
    limiter: object,
    recorder: object,
    clock: object,
    hazard_spec: ProviderHazardSpec | None = None,
    redaction_policy: RedactionPolicy = DEFAULT_POLICY,
) -> FetchOutcome:
    """Fetch every source serially, in the caller's list order (PS2-06).

    The authoritative step-5a record is
    `hermes_researchsourceprovider_fetch_gate_remediation.md` (gate-ruled
    ACCEPTED FOR IMPLEMENTATION, conditions GC-01…GC-03). Contracts carried
    here:

    - **Serial + deterministic (F13/PS2-06):** one source at a time, input
      order preserved; identical (sources, spec, recorded responses, policy,
      injected clock) ⇒ identical outcome incl. `payloads` and the log.
      Parallel fetch is a future optimization requiring a new design gate.
    - **Entry checks, fail closed (D4/F4/F5/FD-03, before ANY I/O):** empty
      list, > `max_sources`, a `valid_negative` source, or a duplicate
      `result_id`/`source_url` → `ProviderValidationError`. A zero-delivery
      search never reaches fetch (walk RETURNS EMPTY/UNAVAILABLE aggregates
      for zero delivery; combine — the task's aggregation point — RAISES on
      both, so the guarantee is task-side, never structural: the driver
      remains the final authoritative boundary). `valid_negative` is
      rejected here — the task's upstream filtering is an optimization only.
    - **Per source (D1/D2/F11/F12):** `limiter.acquire` before the try
      (RT2-03), the content-validation hook (FD-01) on the artifact verdicts
      before construction, artifact construction strictly AFTER classification
      + hook (F11), zero artifacts/payloads for any failure, `FetchFailure`
      never carries body/header/URL (F12).
    - **Retries (F6/F7):** transient verdicts and transport transients back
      off (Retry-After via `limiter.note_throttled`, RT-08); attempts ≤
      `retry_policy.max_retries + 1`; the admission-wait expiry consumes the
      attempt budget (documented); `FetchLogEntry.attempts` +
      `attempt_verdicts` make the logical fetch reconstructable. FC fold-in
      (2026-08-14): the adapter/redaction phase is OUTSIDE the transport
      exception map (a hook `ProviderError` propagates loudly, FC-01); every
      entry satisfies `attempts == len(attempt_verdicts)` incl. the cap-hit
      entry (FC-02); an unknown limiter denial reason is rejected loudly,
      never retried as admission-wait (FC-03).
    - **Daily cap (FD-02):** the FIRST `daily_cap_exhausted` STOPS the batch —
      the remaining sources are marked failed with the same cause (never
      fetched, never dropped) and an outcome note names the cap.
    - **Payloads (A1/GC-02/GC-03):** `FetchedPayload` rides
      `FetchOutcome.payloads` (transient, order-aligned with `per_source`).
      Consumers dereference by `artifact_id`, never by position. Envelope:
      one active body during the walk; the outcome retains Σ payloads ≤
      `max_sources × size_cap_bytes`; failed sources retain zero bytes.
    - **`recorder` is intentionally unused in step 5a (F10):** `FetchLogEntry`
      is the returned log; recorder persistence is deferred (the AR-02 budget
      hook) and does not occur inside this function.
    - **Aggregate (D7/F2):** `COMPLETE` = every source RESOLVED (fetched or
      `NoFullText`), never "full text obtained for all"; full-text
      availability derives from `per_source`/`fetched_count`/
      `no_full_text_count`/`failed`.
    """
    spec = hazard_spec or _load_shipped_spec(adapter.contract.provider_id)

    # ── entry checks — fail closed, before any limiter/transport call ──
    if not sources:
        raise ProviderValidationError(
            "fetch_batch: empty source list — a zero-delivery search never "
            "reaches fetch (walk returns EMPTY/UNAVAILABLE, combine raises); "
            "an empty batch is a caller bug (F4)")
    if len(sources) > request.max_sources:
        raise ProviderValidationError(
            f"fetch_batch: {len(sources)} sources exceed max_sources="
            f"{request.max_sources} (D4)")
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for src in sources:
        if src.valid_negative:
            raise ProviderValidationError(
                f"fetch_batch: valid_negative source {src.result_id!r} has no "
                "content to fetch — rejected before any limiter/transport "
                "call; the task's upstream filtering is an optimization only (F5)")
        if src.result_id in seen_ids:
            raise ProviderValidationError(
                f"fetch_batch: duplicate result_id {src.result_id!r} (FD-03)")
        seen_ids.add(src.result_id)
        if src.source_url in seen_urls:
            raise ProviderValidationError(
                f"fetch_batch: duplicate source_url {src.source_url!r} under "
                "different result ids (FD-03)")
        seen_urls.add(src.source_url)

    per_source: list[FetchedSource] = []
    no_full_text: list[NoFullText] = []
    failed: list[FetchFailure] = []
    payloads: list[FetchedPayload] = []
    logs: list[FetchLogEntry] = []
    notes: list[str] = []
    cap_stop = False
    cap_stop_at: int | None = None
    deadline_stop = False
    deadline_stop_at: int | None = None
    now = _now(clock)

    for index, source in enumerate(sources):
        if not deadline_stop and _deadline_expired(
                request.deadline_monotonic, clock):
            deadline_stop = True
            deadline_stop_at = index
        if cap_stop or deadline_stop:
            # FD-02 — never fetched, never dropped: marked failed with the
            # same cause; zero payloads, zero transport calls (GC-03/F1).
            # D1 — the deadline stop mirrors the cap stop (TRANSIENT /
            # deadline_exhausted), so the remaining sources are never
            # silently dropped and no further request is issued.
            stop_class = "THROTTLED" if cap_stop else "TRANSIENT"
            stop_reason = ("daily_cap_exhausted" if cap_stop
                           else "deadline_exhausted")
            failed.append(FetchFailure(source, stop_class, stop_reason))
            logs.append(_fetch_log_entry(
                source, "FAILED", stop_class, stop_class, None, None, now,
                attempts=0, attempt_verdicts=()))
            continue
        kind, fetched, payload, nft, failure, attempts, attempt_verdicts, denial = _fetch_one(
            adapter, source, request, transport, limiter, clock, spec, redaction_policy)
        if denial == "daily_cap_exhausted":
            cap_stop = True
            cap_stop_at = index
            failed.append(FetchFailure(source, "THROTTLED", "daily_cap_exhausted"))
            logs.append(_fetch_log_entry(
                source, "FAILED", "THROTTLED", "THROTTLED", None, None, now,
                attempts=attempts, attempt_verdicts=attempt_verdicts))
            continue
        if kind == "FETCHED":
            # GC-02 — the payload↔per_source binding: one payload per fetched
            # source, dereference-by-artifact_id (asserted here, pinned by the
            # golden fixtures).
            assert fetched is not None and payload is not None
            assert payload.artifact.artifact_id == fetched.artifact.artifact_id
            per_source.append(fetched)
            payloads.append(payload)
            logs.append(_fetch_log_entry(
                source, "FETCHED", None, fetched.hazard_verdict,
                fetched.artifact.size_bytes, fetched.artifact.content_hash, now,
                attempts=attempts, attempt_verdicts=attempt_verdicts))
        elif kind == "NO_FULL_TEXT":
            assert nft is not None
            no_full_text.append(nft)
            logs.append(_fetch_log_entry(
                source, "NO_FULL_TEXT", None, "NO_FULL_TEXT", None, None, now,
                attempts=attempts, attempt_verdicts=attempt_verdicts))
        else:  # FAIL
            assert failure is not None
            failed.append(failure)
            logs.append(_fetch_log_entry(
                source, "FAILED", failure.failure_class, failure.failure_class,
                None, None, now, attempts=attempts,
                attempt_verdicts=attempt_verdicts))

    if cap_stop_at is not None:
        notes.append(
            f"daily cap exhausted at source {cap_stop_at} of {len(sources)} "
            "(remaining sources marked failed with the same cause)")

    if deadline_stop_at is not None:
        notes.append(
            f"deadline exhausted at source {deadline_stop_at} of "
            f"{len(sources)} (remaining sources marked failed with the "
            "same cause)")

    if not failed:
        aggregate = "COMPLETE"
    elif len(failed) == len(sources):
        aggregate = "FAILED"
    else:
        aggregate = "PARTIAL"

    return FetchOutcome(
        per_source=tuple(per_source),
        no_full_text=tuple(no_full_text),
        failed=tuple(failed),
        aggregate=aggregate,
        fetched_count=len(per_source),
        no_full_text_count=len(no_full_text),
        fetch_log=tuple(logs),
        payloads=tuple(payloads),
        notes=tuple(notes),
    )


def _fetch_one(
    adapter: ProviderAdapter,
    source: SearchResult,
    request: FetchRequest,
    transport: object,
    limiter: object,
    clock: object,
    spec: ProviderHazardSpec,
    redaction_policy: RedactionPolicy,
) -> tuple[str, FetchedSource | None, FetchedPayload | None,
           NoFullText | None, FetchFailure | None, int, tuple[str, ...], str]:
    """One source's attempt loop (D1/H). Returns
    (kind, fetched, payload, nft, failure, attempts, attempt_verdicts,
    denial_reason) where kind ∈ {"FETCHED", "NO_FULL_TEXT", "FAIL", "CAP"}.
    `denial_reason` is "daily_cap_exhausted" only for the batch-stopping CAP
    case; the driver maps it to the FD-02 stop.
    """
    policy = request.retry_policy
    attempts = getattr(policy, "max_retries", 3) + 1
    base_delay = getattr(policy, "base_delay_seconds", 1.0)
    max_delay = getattr(policy, "max_delay_seconds", 30.0)
    jitter = getattr(policy, "jitter", True)

    last_failure: str | None = None
    attempt_verdicts: list[str] = []
    for attempt in range(attempts):
        if _deadline_expired(request.deadline_monotonic, clock):
            # D1 — the overall budget is spent mid-retries: the source fails
            # typed (TRANSIENT / deadline_exhausted), never a silent stall.
            return ("FAIL", None, None, None,
                    FetchFailure(source, "TRANSIENT", "deadline_exhausted"),
                    attempt, tuple(attempt_verdicts), "")
        granted, reason = limiter.acquire(spec.provider_id)  # type: ignore[attr-defined]
        if not granted:
            # RL-01 — the reason is ATOMIC with the decision: the branch is
            # ALWAYS the caller's own denial. daily_cap_exhausted is the
            # no-retry batch stop (FD-02); the admission-wait expiry is
            # transient contention that consumes the attempt budget (F7).
            if reason == "daily_cap_exhausted":
                # FC-02 — the cap denial IS an attempt verdict: the entry must
                # satisfy attempts == len(attempt_verdicts) like every other
                # path (the reconstruction invariant; the walk's
                # `hazard_verdicts` records a cap-denied page as THROTTLED).
                attempt_verdicts.append("THROTTLED")
                return ("CAP", None, None, None, None, attempt + 1,
                        tuple(attempt_verdicts), reason)
            if reason != "admission_wait_expired":
                # FC-03 — an UNKNOWN denial reason is a limiter/driver
                # contract violation: fail loudly, never default into the
                # retryable branch (a hard policy stop masked as transient
                # contention — the AR-02 class). The limiter contract has
                # exactly two denial reasons (ratelimit.py/RL-01).
                raise ProviderValidationError(
                    f"fetch_batch: limiter denied provider {spec.provider_id!r} "
                    f"with unknown reason {reason!r} — the limiter contract "
                    "has exactly two denial reasons (daily_cap_exhausted, "
                    "admission_wait_expired); an unknown reason is a "
                    "contract violation (FC-03)")
            last_failure = "THROTTLED"
            attempt_verdicts.append("THROTTLED")
            _backoff(clock, base_delay, max_delay, jitter, attempt)
            continue
        try:
            # FC-01 — build/redact OUTSIDE the transport exception map: an
            # adapter-hook ProviderError is a LOUD contract/programming
            # failure, never a network transient (the walk's audited
            # precedent builds + redacts outside `_fetch_page`; only
            # `transport.request` sits in the map). The acquire→release
            # pairing still holds — the finally below covers ANY error
            # between acquire and transport.
            req = adapter.build_fetch_request(source)
            redacted = redact_params(req.params, redaction_policy)
            try:
                resp = transport.request(req)  # type: ignore[attr-defined]
            except TransientProviderError as exc:
                last_failure = exc.hazard_class or "TRANSIENT"
                attempt_verdicts.append(last_failure)
                _backoff(clock, base_delay, max_delay, jitter, attempt)
                continue
            except PermanentProviderError as exc:
                cls = exc.hazard_class or "MALFORMED_200"
                attempt_verdicts.append(cls)
                return ("FAIL", None, None, None,
                        FetchFailure(source, cls, str(exc)), attempt + 1,
                        tuple(attempt_verdicts), "")
            except ProviderError:
                # ADV-08 — a RedactionError / ProviderValidationError escaping
                # is a contract/programming failure: loud, never a fetch verdict.
                raise
            except Exception:
                # RT2-06 — a NON-ProviderError is a bug: loud.
                raise
        finally:
            limiter.release(spec.provider_id)  # type: ignore[attr-defined]

        verdict = evaluate_hazards(
            spec.provider_id, spec, resp.body,
            HazardContext(
                scope="FETCH",
                status_code=resp.status,
                request_params=redacted,
                endpoint=req.url,
                content_type=getattr(resp, "content_type", None),
                body_size=len(resp.body),
                size_cap_bytes=getattr(request, "size_cap_bytes", None),
            ),
        )
        hazard = verdict.hazard_class
        attempt_verdicts.append(hazard)
        if hazard in ("THROTTLED", "TRANSIENT"):
            limiter.note_throttled(  # type: ignore[attr-defined]
                spec.provider_id, _retry_after(resp))
            last_failure = hazard
            _backoff(clock, base_delay, max_delay, jitter, attempt)
            continue
        if hazard in _FETCH_PERMANENT_CLASSES:
            # D2 — permanent, never silent; the FD-04 reason rewrite for
            # non-2xx permanents is already in the evaluator's reason text.
            return ("FAIL", None, None, None,
                    FetchFailure(source, hazard, verdict.reason), attempt + 1,
                    tuple(attempt_verdicts), "")
        if hazard == "NO_FULL_TEXT":
            # PS2-01/PS3-03 — a RESULT, never a failure; the kind + evidence
            # come ONLY from what the response evidenced (the evaluator's
            # detected_by — status + spec-declared markers, never guessed).
            kind = verdict.detected_by.get("no_full_text_kind", "NOT_OA")
            assert kind in ("NOT_OA", "REMOVED_OR_RETRACTED", "NOT_FOUND")
            return ("NO_FULL_TEXT", None, None,
                    NoFullText(source=source, no_full_text_kind=kind,
                               evidence_basis=dict(verdict.detected_by)),
                    None, attempt + 1, tuple(attempt_verdicts), "")
        if hazard in ("NONE", "INJECTION_SUSPECT"):
            # FD-01 — the content-validation hook runs BEFORE artifact
            # construction (F11): a rejection is a per-source EMPTY_RESULT
            # failure, never a junk artifact. INJECTION_SUSPECT is advisory —
            # the hook still runs (a junk body with instruction-like text is
            # rejected regardless of the label).
            try:
                adapter.validate_fetch(source, _decode_payload(resp.body))
            except FetchContentRejected as exc:
                return ("FAIL", None, None, None,
                        FetchFailure(source, "EMPTY_RESULT", str(exc)),
                        attempt + 1, tuple(attempt_verdicts), "")
            raw = resp.body
            # A1/FD-06 — the artifact identity is the RAW BYTES (content-
            # addressed): sha256 over the bytes, never a lossy text re-encode.
            content_hash = hashlib.sha256(raw).hexdigest()
            artifact = SourceArtifact(
                artifact_id="art_" + content_hash[:24],
                content_hash=content_hash,
                media_type=resp.content_type or "application/octet-stream",
                size_bytes=len(raw),
                retrieved_from=source.source_url,
                access_timestamp_utc=_now(clock),
                raw_bytes_ref="art_" + content_hash[:24],  # A4/FD-05 alias
            )
            fetched = FetchedSource(source=source, artifact=artifact,
                                    hazard_verdict=hazard)
            return ("FETCHED", fetched,
                    FetchedPayload(artifact=artifact, raw_bytes=raw),
                    None, None, attempt + 1, tuple(attempt_verdicts), "")
        # GC-01 — unreachable: the evaluator's `_verdict` guard enforces the
        # closed FETCH taxonomy; a class reaching here is a driver/spec bug.
        raise ProviderValidationError(
            f"fetch scope received illegal hazard class {hazard!r} "
            "(scope-closure violated — evaluator guard bypassed)")

    return ("FAIL", None, None, None,
            FetchFailure(source, last_failure or "TRANSIENT",
                         f"transient failures exhausted after {attempts} attempts"),
            attempts, tuple(attempt_verdicts), "")


def _fetch_log_entry(
    source: SearchResult,
    status: str,
    failure_class: str | None,
    hazard_verdict: str,
    size_bytes: int | None,
    content_hash: str | None,
    now: str,
    attempts: int,
    attempt_verdicts: tuple[str, ...],
) -> FetchLogEntry:
    """PS2-07 + F6 — one fetch-shaped log entry per source, in input order."""
    return FetchLogEntry(
        source_ref=source.result_id,
        status=status,  # type: ignore[arg-type]
        failure_class=failure_class,
        hazard_verdict=hazard_verdict,
        size_bytes=size_bytes,
        content_hash=content_hash,
        access_timestamp_utc=now,
        attempts=attempts,
        attempt_verdicts=attempt_verdicts,
    )
