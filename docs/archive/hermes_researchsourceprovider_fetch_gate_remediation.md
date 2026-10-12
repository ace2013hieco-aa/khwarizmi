# STEP 5A — FETCH DRIVER (`fetch_batch`)
## HOSTILE GATE REMEDIATION — REVISED DESIGN DECISION RECORD

**Role:** Hermes implementation/design agent, ResearchSourceProvider Part 3, step 5a of 7.
This record is the **authoritative step-5a design after the hostile gate** — it
supersedes `hermes_researchsourceprovider_fetch_driver_design.md` (D1–D11, incl. the
FD-01…FD-07 fold-in) wherever they conflict. The prior record's **surviving** decisions
(the seriality/order discipline, the exhaustive verdict table, the 404→`NO_FULL_TEXT`
precedence, the batch-cap stop, the junk-200 hook, the dereference contract) carry
forward; this gate resolves the ownership/memory/closure/attempt-accounting questions
the prior record left open.

**NO CODE — the only deliverable of this turn is this record** (prompt §19). Status:
**DESIGNED**. NOT implemented, NOT tested, NOT ratified-as-implemented. The
implementation gate (§20) decides between ACCEPTED FOR IMPLEMENTATION and REMEDIATION
REQUIRED.

All decisions cross-checked against the shipped repository: `research_sources.py`
(types), `paginate.py` (`walk`/`combine`/`_fetch_page`/`_backoff`/`_retry_after`),
`hazards.py` (`HAZARD_CLASSES`/`_MARKER_CLASSES`/`evaluate_hazards`), `ratelimit.py`
(clock-injected limiter), `http.py` (content-type passthrough), `redact.py`, `base.py`
(`TransportResponse`/`Clock`/`Transport` protocols), the four `hazard_specs/*.json`.

---

## A. Findings accepted

All fourteen issues (A1 + F1–F13) are accepted in whole or part. The decisions are
resolved in sections C–D; the two structural answers (the payload carrier, the scope
closure) are **MODIFY** decisions that change the prior record's text.

## B. Findings rejected (with evidence)

None rejected outright. Two prompt hypotheses were examined and **not** adopted:

- **F4 option #1 ("empty fetch input is structurally impossible — upstream guarantees
  it").** Rejected as the *sole* defense. Evidence: `walk()` RETURNS an
  `EMPTY`/`UNAVAILABLE` aggregate for zero delivery — it does not raise
  (`paginate.py:394`, `_single_provider_aggregate`); the raising is `combine()`'s
  contract (`paginate.py:412-13`, "This is the raising point": `EMPTY` →
  `RetrievalShortfallError`, `UNAVAILABLE` → `ProviderUnavailableError`). A
  single-provider outcome could therefore reach task code without combine. The
  guarantee is task-side (combine/routing), never structural — so the driver must be
  the final authoritative boundary (decision #3, section D-F4).
- **A1.3's literal shape ("`FetchedPayload` = transient raw bytes" as a per-source
  replacement for the `FetchedSource.raw_bytes` field).** The separation is adopted;
  the carrier's home is `FetchOutcome.payloads` (one explicit, droppable tuple), not a
  per-source parallel type — the outcome of a fetch operation legitimately includes its
  payloads as transient handoff, and one carrier is easier to bound and release than N
  scattered per-source carriers. See C.

## C. Final A1 decision: **MODIFY**

**`FetchedSource` keeps the ratified shape (no `raw_bytes` field). The raw bytes ride a
new TRANSIENT carrier `FetchedPayload(artifact: SourceArtifact, raw_bytes: bytes)` in
`FetchOutcome.payloads: tuple[FetchedPayload, ...]` — order-aligned with
`per_source` (only FETCHED entries).**

| Question | Answer |
|---|---|
| **A1.1 ownership** | transport (buffers one body) → driver (decode/validate/hash) → `outcome.payloads` (the only retained copy) → task write path (persists content-addressed) → released (outcome dropped). No other component holds the bytes at any point. |
| **A1.2 semantics** | `FetchedSource` is a **source-resolution record** (matches its ratified docstring: "A source successfully fetched to an artifact"). It never carries heavyweight transient data. The Hermes artifact model already separates semantic records (descriptor + hash) from content (content-addressed bytes) — `SearchResult.abstract_sha256` vs the artifact store is the precedent. |
| **A1.3 carrier** | Separate transient carrier — **adopted**, as `FetchedPayload` on `FetchOutcome.payloads` (not per-source). `FetchedPayload` IS the artifact-store entry the task will persist: `(artifact, raw_bytes)` mirrors what a durable store holds. |
| **A1.4 hazards** | *Accidental retention:* the bytes exist only in the per-source local (dropped at loop end) and in `outcome.payloads` (one explicit tuple). *Duplication:* one `FetchedPayload` per FETCHED source, never per attempt. *Retry contamination:* each attempt's body is discarded before the next attempt — only the FINAL accepted body survives. *Memory:* bounded — see K. *Mutation:* `FetchedPayload` is frozen; `bytes` is immutable. |
| **A1.5 lifecycle** | created (transport read, one at a time) → validated (hazard verdict + content-validation hook, FD-01) → hashed (`sha256(raw)`, artifact built) → carried (`outcome.payloads`) → **persisted by the task write path atomically at admission** (the sole dereference point) → released (outcome GC'd; nothing retains). |
| **A1.6 self-address** | `raw_bytes_ref = "art_" + content_hash[:24]` is an **in-phase identity alias** (≡ `artifact_id`), NOT a durable address — the FD-05 dereference contract stands: the task write path is the sole dereference point; the S12 manifest replaces the alias later. The field is documented as an alias; no consumer may treat it as a store ref in this phase. |
| **A1.7 verdict** | **MODIFY** — accepted in intent (the data-loss class is real: without a carrier the payload is hashed and discarded), changed in placement (separate transient carrier, ratified `FetchedSource` untouched). |

## D. Final F1–F13 resolutions

| Finding | Decision | Reason | Invariant | Implementation impact | Test |
|---|---|---|---|---|---|
| **F1 memory** | Bound + prove | Serial driver ⇒ one active body during the walk; outcome retention is Σ payloads ≤ `max_sources × size_cap_bytes` by construction (every accepted body passed the per-response cap) | One active body at a time during the walk; the outcome retains exactly the accepted payloads; failed sources retain zero bytes | No new request field — the envelope is the product of existing `FetchRequest` fields; documented in the fetch docstring + contract | (a) one-live-body probe, (b) oversized rejected, (c) retries ⇒ 1 payload per accepted source, (d) `len(payloads) == len(per_source)` |
| **F2 COMPLETE** | Rule pinned + no-consumer audit | No consumer of `FetchOutcome.aggregate` exists today (grep: referenced only in `research_sources.py`); the rule must bind the future task write path | `COMPLETE` = **every source resolved** (fetched or `NoFullText`), never "full text obtained for all"; full-text availability derives ONLY from `per_source`/`fetched_count`/`no_full_text_count`/`failed` | Reading rule stated in the contract's fetch-aggregate row (WS-05-style) | all-`NoFullText` batch → `COMPLETE`, `fetched_count=0`, `no_full_text_count=N`, and a reading-rule assertion that the truthful signal is the count, not the aggregate name |
| **F3 closure** | **hazards.py owns the invariant** | The evaluator's output domain must be closed at the source; a driver discovering an illegal class is late. Today the closure is structural only (search branches gated by `not fetch_scope`; the fetch block emits only fetch classes) — no explicit guard exists (`HAZARD_CLASSES` = 11 classes, no scope→class check) | `evaluate_hazards(scope="FETCH")` returns ONLY `{NONE, MALFORMED_200, EMPTY_RESULT, PARTIAL_CONTENT, THROTTLED, TRANSIENT, INJECTION_SUSPECT, NO_FULL_TEXT}` — guaranteed by (a) a scope-closure check at the evaluator boundary (`SpecValidationError` on violation) and (b) registration: a fetch-side construct may only declare/emit fetch-taxonomy classes | `hazards.py`: a `FETCH_ALLOWED`/`SEARCH_ALLOWED` closure guard + a registration row; the driver's D2 scope-error raise becomes unreachable defense-in-depth (kept) | deliberately invalid spec emitting a walk-only class at FETCH → rejected at the evaluator/registration layer, deterministically |
| **F4 empty input** | **#3 fail closed** (with evidence, not assertion) | `walk()` returns `EMPTY`/`UNAVAILABLE` outcomes (no raise); `combine()` is the raising point. The empty case is task-handled, never structural — so the driver is the final authoritative boundary | `len(sources) == 0` → `ProviderValidationError`; a vacuous `COMPLETE` is impossible | unchanged from D4; evidence cited in the fetch docstring | `fetch_batch([])` → `ProviderValidationError`; pipeline fixture: walk zero-delivery → `EMPTY` aggregate → combine raises |
| **F5 valid_negative** | fetch_batch is the final authoritative boundary | Task-side filtering is an optimization; the driver must not trust the caller | a `valid_negative: True` source is rejected BEFORE `limiter.acquire`/`build_fetch_request`/transport — **transport never called** | unchanged from D6; check order pinned (reject before any limiter/transport) | upstream-filtered → normal fetch; leaked → `ProviderValidationError`; a recording transport asserts zero calls |
| **F6 attempt accounting** | Enrich `FetchLogEntry` (no new table/event) | A single `FETCHED`/`FAILED` entry loses "attempt 1 → TIMEOUT, attempt 2 → SUCCESS"; the walk's `RequestLogRecord.hazard_verdicts` tuple is the precedent | `FetchLogEntry` gains `attempts: int` (transport attempts, ≤ `max_retries + 1`) + `attempt_verdicts: tuple[str, ...]` (per-attempt hazard class or `TRANSIENT`); the logical fetch and its network attempts are reconstructable, ordered, bounded | `FetchLogEntry` +2 fields; driver records per-attempt classes | retry fixture: 3 attempts (TIMEOUT → THROTTLED → SUCCESS) ⇒ `attempts=3`, `attempt_verdicts=(TIMEOUT, THROTTLED, NONE)` |
| **F7 Retry-After/replay** | Recorded-state determinism | Retry-After lives in `TransportResponse.headers` — the recorded transport replays it; the limiter is fully clock-injected (`ratelimit.py`: `monotonic`/`now_utc`, no `time.`); `_backoff` sleeps via `clock.sleep` (optional attr), jitter affects only sleep DURATION, never the verdict/log (log timestamps come from `clock.now_utc()`) | identical sources + recorded responses (incl. Retry-After) + policy + injected clock ⇒ identical retry sequence and outcome; wall clock never leaks | none (inherited audited behavior); the replay contract is stated in the fetch docstring | transient→Retry-After→success; transient→no-Retry-After→success; Retry-After > max delay (driver backoff clamped at `max_delay`, limiter cooldown honors the value — deterministic under a frozen clock); malformed Retry-After → `_retry_after` returns None (treated as absent); Retry-After + daily-cap (cap denial is cooldown-independent, hard stop) |
| **F8 fetch:null** | Generic safety never disabled | `fetch: null` = no provider-specific fetch hazard knowledge (HZ-04's meaning) — it must not read as "no fetch safety" | generic controls always apply: transport failure handling, size cap, empty-body rule, redaction, content-type handling where declared, artifact bounds, retry policy, and the content-validation hook (FD-01 — the hook runs regardless of the fetch block) | contract + design wording pinned ("no declared hazard knowledge; generic safety unchanged") | for a `fetch: null` provider: empty body fails, oversized fails, transport error fails, redaction executes, content-type handling applies where declared |
| **F9 media type** | Ownership split, never invented | `TransportResponse.content_type` is the transport's NORMALIZED header media type or None (`base.py` — "the transport NEVER classifies on it"); the evaluator validates it against the spec's declared `content_types` at the pinned slot (RT3-04, mismatch → `MALFORMED_200`); the artifact records the VALIDATED value | transport provides (normalized); evaluator validates (declared allowlist); artifact `media_type` = validated content_type or `"application/octet-stream"` (honest default when absent) — never a fabricated label | none (D3/A3 already correct); ownership stated | valid; absent → octet-stream; mismatched → `MALFORMED_200` (pinned slot); malformed header → transport normalizes to None (no classification); provider-declared type |
| **F10 recorder** | **A — retain, explicitly unused** | Signature stability + the AR-02 budget hook needs the boundary (only-entry-point invariant); no fake recording, no hidden side effect | `recorder` is documented in the fetch docstring + contract: "intentionally unused in step 5a; `FetchLogEntry` is the step-5a returned log; recorder persistence is deferred and does not occur inside `fetch_batch`" | none (D11 A5 confirmed) | — (docstring/contract pin; no call site) |
| **F11 failure artifacts** | Zero artifacts before classification + hook | Artifact construction is strictly AFTER the verdict mapping AND the content-validation hook pass; a real failure (incl. hook rejection) leaves zero artifacts | malformed 200 / oversized / partial / empty / retry-exhaustion → zero artifacts; `INJECTION_SUSPECT` is genuinely successful (content passed hazard + hook — the flag is advisory) and produces an artifact, `hazard_verdict="INJECTION_SUSPECT"`, that consumers may use as content with the flag recorded for review — never as a block | unchanged from D3 (order pinned) | per-class zero-artifact fixtures + injection artifact fixture |
| **F12 no body in failures** | `FetchFailure` carries `source`/`failure_class`/`reason` only | Reasons come from verdict evidence (status/field/pattern — never body content), the hook message (must not embed the payload), or the limiter denial reason; transport exceptions are redacted at the boundary (`from None`, PS3-07) | a `FetchFailure` never contains a raw body, headers, or URL; no secret survives repeated wrapping | none (type already clean; reason sources pinned) | exception containing API key/token/email/private endpoint → no leakage through repeated wrapping (redaction + reason fixtures) |
| **F13 seriality** | Keep serial; document; no concurrency | serial = replay determinism + predictable rate limiting + simple audit ordering | parallel fetch is a future optimization requiring a NEW design gate; step 5a has no concurrency | stated in the fetch docstring | — (documented constraint; the serial-order determinism fixture covers it) |

## E. Revised API

```python
def fetch_batch(
    adapter: ProviderAdapter,
    sources: list[SearchResult],
    request: FetchRequest,
    transport: Transport,
    limiter: ProviderRateLimiter,
    recorder: RequestRecorder,          # F10 — intentionally unused in step 5a
    clock: Clock,
    hazard_spec: ProviderHazardSpec | None = None,
    redaction_policy: RedactionPolicy = DEFAULT_POLICY,
) -> FetchOutcome
```

Unchanged from the prior record. The gate's decisions are all inside the types
(section F) and the behavior contract (sections G–K), not the signature.

## F. Revised data model

| Type | Change |
|---|---|
| `FetchedSource` | **unchanged** (ratified shape — `source`, `artifact`, `hazard_verdict`). The FD-05 fold-in's "bytes ride `FetchedSource.raw_bytes`" is SUPERSEDED by this gate: bytes ride `FetchOutcome.payloads`. |
| `FetchedPayload` | **NEW transient carrier** — frozen dataclass `(artifact: SourceArtifact, raw_bytes: bytes)`. Exactly the artifact-store entry the task will persist. |
| `FetchOutcome` | gains `payloads: tuple[FetchedPayload, ...]` — transient, order-aligned with `per_source` (only FETCHED entries); released after the task persists. All other fields unchanged. |
| `FetchFailure` | **unchanged** — `source`/`failure_class`/`reason` only; never a body/header/URL (F12). |
| `FetchLogEntry` | gains `attempts: int` + `attempt_verdicts: tuple[str, ...]` (F6). |
| Tables/events | **none** — the slice stays read-only; `payloads` is transient memory, `FetchLogEntry` enrichment is a returned record. |

## G. Revised verdict table (closed FETCH taxonomy)

`evaluate_hazards(scope="FETCH")` output domain is CLOSED (F3 — hazards.py owns it):

| Class | Outcome |
|---|---|
| `NONE` | content-validation hook (FD-01) → `FetchedSource` + `FetchedPayload` |
| `INJECTION_SUSPECT` | advisory — hook → `FetchedSource(hazard_verdict="INJECTION_SUSPECT")` + `FetchedPayload`; never a block |
| `NO_FULL_TEXT` | `NoFullText(source, kind, evidence_basis)` — a RESULT, never a failure (PS2-01) |
| `THROTTLED` (after retries) | `FetchFailure(THROTTLED, reason=<denial cause or status>)`; daily-cap → batch stop (FD-02) |
| `TIMEOUT` / `TRANSIENT` (after retries) | `FetchFailure(<class>)` |
| `MALFORMED_200` / `EMPTY_RESULT` / `PARTIAL_CONTENT` | `FetchFailure(<class>)` — permanent; non-2xx permanents carry the honest FD-04 reason |
| `VALID_NEGATIVE` / `CURSOR_TRAP` / `REWRITE_SUSPECT` | **unreachable at FETCH scope** — hazards.py closure (F3) rejects; the driver's loud `ProviderValidationError` stays as defense-in-depth |

Every artifact-row class passes the hook first (FD-01); every failure row leaves zero
artifacts and zero payloads (F11/F12).

## H. Revised lifecycle

```
fetch_batch(adapter, sources, request, …)
  │  entry checks (F4 empty → raise; F5 valid_negative → raise; FD-03 duplicates → raise)
  ▼
for source in sources:                       # serial, input order (PS2-06)
  │  _fetch_one(source)
  │    for attempt in 1..max_retries+1:      # F7 — all timing via injected clock
  │      granted, reason = limiter.acquire(provider)      # before the try (RT2-03)
  │      if not granted:
  │          daily_cap_exhausted → BATCH STOP (FD-02: rest marked failed + cap note)
  │          admission_wait_expired → backoff (F6: consumes the attempt budget) → retry
  │      try:
  │          req = adapter.build_fetch_request(source)      # redacted at the boundary
  │          resp = transport.request(req)                  # transport-level errors only
  │          verdict = evaluate_hazards(scope="FETCH", …)   # closed domain (F3)
  │          if transient → note_throttled(Retry-After) → backoff → retry
  │      finally: limiter.release(provider)                 # per request (WK3-01)
  │    verdict mapping (G)
  │    NONE / INJECTION_SUSPECT:
  │        adapter.validate_fetch(source, payload)          # FD-01 — reject → EMPTY_RESULT failure
  │        artifact = SourceArtifact(sha256(raw), …)        # AFTER classification + hook (F11)
  │        payload = FetchedPayload(artifact, raw)          # the ONE retained copy (F1)
  │    NO_FULL_TEXT → NoFullText(source, kind, evidence_basis)
  │    failure → FetchFailure(source, class, reason)        # zero artifacts, zero payloads (F11/F12)
  │  log entry: FetchLogEntry(…, attempts, attempt_verdicts)  # F6
  ▼
aggregate (D7 — resolution signal, F2 reading rule) + payloads tuple (F1/K)
return FetchOutcome  →  task write path persists (sole dereference point, FD-05)  →  released
```

## I. Revised failure semantics

- Per-source failures are typed (`FetchFailure`), never silent, never results.
- A failure leaves **zero artifacts and zero payloads** and a `FAILED` log entry whose
  `failure_class` + `reason` (never body/header/URL — F12) enumerate the cause.
- The batch-cap stop (FD-02) marks the remaining sources failed with the same cause +
  an outcome note — the aggregate's cause is the CAP.
- Transport/programming errors (non-`ProviderError` escapes, ADV-08; non-permanent
  `ProviderError` re-raises) stay loud — never converted into a misleading verdict.
- Hook rejections (FD-01) are per-source `EMPTY_RESULT` failures, never `FetchedSource`.

## J. Revised determinism/replay contract

- Serial, input-order execution (PS2-06) — identical (sources, spec, recorded
  responses, policy, injected clock) ⇒ identical `FetchOutcome` incl. `payloads`
  (bytes hashed, ids content-addressed) and the log (with `attempts`/`attempt_verdicts`).
- Retry-After is recorded response state (headers), replayed by the recorder (F7);
  all timing is clock-injected (`limiter.monotonic`/`now_utc`, `_backoff` via
  `clock.sleep`); jitter affects only sleep duration, never verdicts or log facts.
- Wall clock never leaks into replay.

## K. Revised memory/ownership contract

- During the walk: **one active body** — transport buffers one; the per-source local is
  dropped at loop end; each retry discards the previous attempt's body (F1).
- At the outcome: `Σ len(payloads) ≤ max_sources × size_cap_bytes` — bounded by
  construction from existing `FetchRequest` fields; documented as the envelope.
- Failed sources retain zero bytes (F11/F12).
- Ownership: transport → driver → `outcome.payloads` → task write path (persist) →
  released. Nothing else holds the bytes; `FetchedPayload` is frozen (A1.4).

## L. Revised acceptance tests (`tests/test_provider_fetch.py`)

Prior record's fixtures 1–18 carry forward (with fixture 1 now asserting the
carrier↔descriptor cross-check against `payloads`, FD-06) plus:

1. **F1** — one-live-body probe (an instrumented transport asserts ≤ 1 body held at
   any instant across a multi-source batch); oversized per-source rejected; retries ⇒
   exactly 1 payload for the accepted source; `len(payloads) == len(per_source)`.
2. **F2** — all-`NoFullText` batch → `COMPLETE`, `fetched_count=0`,
   `no_full_text_count=N`, reading-rule assertion.
3. **F3** — invalid spec emitting a walk-only class at FETCH → rejected at the
   evaluator/registration layer, deterministically.
4. **F4** — `fetch_batch([])` → `ProviderValidationError`; pipeline fixture: walk
   zero-delivery → `EMPTY` → combine raises.
5. **F5** — `valid_negative` leaked → `ProviderValidationError`, transport never
   called (recording transport); upstream-filtered → normal fetch.
6. **F6** — 3-attempt retry (TIMEOUT → THROTTLED → SUCCESS) ⇒ `attempts=3`,
   `attempt_verdicts=(TIMEOUT, THROTTLED, NONE)`.
7. **F7** — the five Retry-After fixtures (transient→RA→success; transient→no-RA→
   success; RA > max delay; malformed RA → treated absent; RA + daily-cap
   independence).
8. **F8** — `fetch: null` provider: empty fails, oversized fails, transport error
   fails, redaction executes, content-type handling applies.
9. **F9** — valid / absent → octet-stream / mismatched → `MALFORMED_200` / malformed →
   None / provider-declared type.
10. **F11** — per-class zero-artifact fixtures + the `INJECTION_SUSPECT` artifact
    fixture (flag recorded, content usable, never blocked).
11. **F12** — secret-bearing transport exception (API key/token/email/private
    endpoint) through repeated wrapping → no leakage in `FetchFailure`/log.

## M. Explicitly deferred

- Parallel/concurrent fetch (F13) — requires a new design gate.
- Durable artifact writing — the S12 manifest/durable-outbox phase replaces
  `raw_bytes_ref`'s alias and gives the bytes a real store address (A1.6).
- `recorder.record` inside the fetch path — the AR-02 budget ledger lands first (F10).
- Per-provider `no_full_text_status` for arxiv/openalex (`fetch: null` today) — the
  later-slice extension that turns the FD-04 permanent into a `NoFullText` (D11 A6).
- Any provider-specific fetch hazard declarations beyond the four shipped specs.

---

**Status:** DESIGNED — revised step-5a record. The hostile gate's A1 + F1–F13 are
resolved. **The §20 implementation gate has run (`hermes_researchsourceprovider_fetch_gate_review.md`, 2026-08-14) and ruled
ACCEPTED FOR IMPLEMENTATION with conditions GC-01…GC-03** — GC-01 (**P2**): the F3
closure guard lives in `_verdict` (the single verdict-construction helper — every
`return _verdict(...)` path flows through it), scope passed from `evaluate_hazards`,
with both closed sets enumerated (`FETCH_ALLOWED` excludes `VALID_NEGATIVE`/
`REWRITE_SUSPECT`/`CURSOR_TRAP`; `SEARCH_ALLOWED` excludes `NO_FULL_TEXT` —
cross-checked against the shipped walk's `_PERMANENT_CLASSES`); GC-02 (**P3**): the
payload↔`per_source` contract is dereference-by-`artifact_id`, never positional, with
the invariant fixture; GC-03 (**P3**): the K envelope text documents the 2xx-only
per-body cap, the backoff-held throttled body, and the task-sizes-its-request control.
No P1 remains — `fetch_batch` may be written per this record carrying GC-01…GC-03 into
code and the `tests/test_provider_fetch.py` fixtures. No code exists; the slice
remains NOT ratified-as-implemented.
