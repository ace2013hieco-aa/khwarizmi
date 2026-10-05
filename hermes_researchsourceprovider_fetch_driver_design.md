# Step 5 — Fetch Driver (`fetch_batch`) — Design Decision Record

**Role:** Hermes implementation agent, ResearchSourceProvider Part 3, **step 5a of 7**
(blueprint `5.` list item 5a; §5.3). This is a **design-only** record: the hostile gate
reviews it before any code, per the manual-proof-first rule that carried steps 1–4.

**Builds on the shipped, audited surface:**
- `paginate.py` — the walk driver + the private helpers the fetch driver REUSES
  (`_backoff`, `_retry_after`, `_load_shipped_spec`, the redaction boundary) — the
  fetch driver lives in `paginate.py` beside `walk()` (blueprint step 5a), maximal
  reuse, no duplicated retry/backoff/limiter logic.
- `hazards.py` — the ONE generic evaluator with the fetch-scoped step 6a (PS2-02/PS3-01/
  PS3-02/PS3-03/PS3-08, HZ-02/04/05, FS-01…FS-08): error evidence first, retraction
  value-semantics, `no_full_text` status+marker, the composite, the recursive-emptiness
  body check, and the pinned label/size slots.
- `ratelimit.py`/`http.py` — the audited limiter (atomic `(bool, str)` acquire, CAP-01,
  RT4-01, per-request release) and transport (transport-level-only exceptions, HTTPError-
  as-response, TR-01 read-phase map, ADV-08 classification).
- The shipped fetch types (`research_sources.py`): `FetchedSource`/`NoFullText`/
  `FetchFailure`/`FetchOutcome`/`FetchRequest`/`FetchLogEntry`/`SourceArtifact` and the
  `FetchAggregate`/`NoFullTextKind` literals.
- The four shipped hazard specs: `pmc.json` (composite `PARTIAL_CONTENT`), `europepmc.json`
  (404 → `NO_FULL_TEXT`, `errCode` error field), `arxiv.json`/`openalex.json` (`fetch:
  null` — **no declared fetch-hazard knowledge**, HZ-04's documented meaning).

**Standing condition:** the step-5 hostile gate (the same three-gate pattern: design
review → fold-in → implementation). Nothing here is code; nothing here claims
IMPLEMENTED/TESTED. The slice remains NOT ratified-as-implemented until step 7.

---

## D1 — The driver shape: signature, seriality, determinism

```python
def fetch_batch(adapter: ProviderAdapter, sources: list[SearchResult], request: FetchRequest,
                transport: Transport, limiter: ProviderRateLimiter,
                recorder: RequestRecorder, clock: Clock,
                hazard_spec: ProviderHazardSpec | None = None,
                redaction_policy: RedactionPolicy = DEFAULT_POLICY) -> FetchOutcome
```

- **Serial, in the caller's list order (PS2-06).** The caller's order IS the task's input
  order (the search stream's delivered order, dedup-first-seen). The driver never
  re-sorts — determinism is by construction, not by post-hoc sort. The outcome's
  `per_source`/`no_full_text`/`failed` tuples are partitioned views of the SAME order;
  `fetch_log` preserves the full input order.
- **One source, one attempt-loop** (`_fetch_one`): `limiter.acquire` (before the try,
  RT2-03) → `build_fetch_request` → redact at the boundary → `transport.request` →
  `evaluate_hazards(scope="FETCH")` → verdict mapping → **the content-validation hook
  (FD-01, D3) on the artifact rows (`NONE`/`INJECTION_SUSPECT`) before artifact
  construction**. `limiter.release` per request in a `finally` (WK3-01). The shape is the
  walk's `_fetch_page` loop, minus pagination.
- **Transient retry** (per source, ≤ `request.retry_policy.max_retries`): `TIMEOUT`/
  `THROTTLED`/`TRANSIENT` verdicts and transport transients back off (honoring
  `Retry-After` via `limiter.note_throttled`, RT-08) then retry the SAME source. The
  admission-wait expiry is retryable contention (RT3-02, atomic reason RL-01) — **it
  consumes the same per-source attempt budget (FD-07, inherited `_fetch_page` semantics:
  attempts = `max_retries + 1` total; under sustained limiter contention a source's
  attempts may be consumed by admission waits before a genuine transient — documented,
  matches the walk).** The daily-cap `False` is a **batch-level** no-retry hard stop
  (FD-02): the FIRST `daily_cap_exhausted` ends the batch — the remaining sources are
  marked `FetchFailure(THROTTLED, "daily_cap_exhausted")` (never fetched, never silently
  dropped) and the outcome carries a `"daily cap exhausted at source <i> of <n>"` note —
  the aggregate's cause is the CAP, never N independent source failures (a consumer
  cannot misread "6 of 10 failed" and retry the batch into an immediate re-denial storm).
- **Batch entry (FD-03):** duplicate `result_id`s — and duplicate `source_url`s under
  different `result_id`s — are rejected loudly (`ProviderValidationError`) before any
  I/O; the walk's dedup-first-seen makes the task stream unique, so a duplicate here is
  a caller bug (a double fetch would double transport cost and double log entries).
  **Crash-retry idempotency (stated):** a task re-run re-fetches (network cost) but is
  content-idempotent — same bytes → same artifact id → atomic re-admission at the task
  write path (the A2-03 discipline; no duplicate artifacts, no duplicate log facts).
- **Deterministic by construction (PS2-06/PS-05 discipline):** identical (sources, spec,
  recorded transport responses, clock) ⇒ identical `FetchOutcome` — including artifact
  ids (`"art_" + sha256(raw)[:24]`) and the log. Replay-verified through the step-3
  offline recorded-transport harness.

## D2 — The per-source verdict → outcome mapping (PS3-01 table, operationalized)

The table is **complete, no fall-through**; every evaluator class at FETCH scope maps:

| `HazardVerdict.hazard_class` | Outcome |
|---|---|
| `NONE` | **content-validation hook (FD-01) →** `FetchedSource` — artifact built from the raw bytes (D3) |
| `NO_FULL_TEXT` | `NoFullText(source, kind=verdict.detected_by["no_full_text_kind"], evidence_basis={status_code, marker_path?, provider_spec_version})` — a RESULT, never a failure (PS2-01) |
| `INJECTION_SUSPECT` | advisory — **content-validation hook (FD-01) →** `FetchedSource` with `hazard_verdict="INJECTION_SUSPECT"`, never a block; the hook still runs (a junk body with instruction-like text is rejected, never artifact'd) |
| `PARTIAL_CONTENT` / `MALFORMED_200` / `EMPTY_RESULT` | `FetchFailure(failure_class=<class>)` — permanent, never silent |
| `THROTTLED` (after retries) | `FetchFailure(THROTTLED, reason=<denial cause or status>)` |
| `TIMEOUT` / `TRANSIENT` (after retries) | `FetchFailure(<class>)` |
| `VALID_NEGATIVE` / `CURSOR_TRAP` / `REWRITE_SUSPECT` | **scope error — raise `ProviderValidationError`** (loud, never a silent failure/result). `VALID_NEGATIVE` is unreachable at FETCH scope (the 404 short-circuits to `NO_FULL_TEXT`, PS3-01); the walk-only classes are unreachable by construction; receiving one means a driver/spec contract violation. |

`NoFullText.evidence_basis` is copied from the verdict's `detected_by` — the driver
asserts ONLY what the response evidenced (status + spec-declared markers, PS3-03): the
`REMOVED_OR_RETRACTED` kind comes from a `retraction_marker` hit, never guessed, never
`NOT_OA`.

**Fall-through rule (PS3-02 + FD-01):** a fetch response with no body content and no
matching verdict is `FetchFailure(EMPTY_RESULT)` — the evaluator's fetch-scope
`treat-as-failure` empty rule + the recursive-emptiness body check (FS-01: `{"sec": ""}`
is absent) make a zero-content "full text" structurally unadmittable as `FetchedSource`.
A **non-empty junk** body (HTML error page, `<error>`-rooted wrapper, HTML-when-PDF-
promised) is caught by the content-validation hook (D3) — never admitted by the
fall-through, never artifact'd as the fetched paper (the body-marker-less corner the
shipped specs leave open: europepmc `body_marker: null`/`body_required: false`,
arxiv/openalex `fetch: null`).

**Non-2xx permanents at fetch scope (FD-04):** an unclassified non-2xx (a 404 on a
`fetch: null` provider) keeps the permanent class but the driver rewrites the REASON to
the honest form — `HTTP <status> — no accessible full text for this source (provider
declares no fetch hazard knowledge)` — so task failure analysis never reads a
legitimately-absent full text as schema corruption (`MALFORMED_200, "HTTP 404"`).
Per-provider `no_full_text_status` declarations are the later-slice extension (D11 A6);
the class catalog stays closed.

## D3 — Artifact construction + the raw-bytes carrier (AMENDMENT A1)

```python
content_hash = sha256_hex(raw)                      # full hash — identity of the bytes
artifact = SourceArtifact(
    artifact_id="art_" + content_hash[:24],
    content_hash=content_hash,
    media_type=resp.content_type or "application/octet-stream",   # A3 default
    size_bytes=len(raw),
    retrieved_from=source.source_url,               # redacted form
    access_timestamp_utc=now,
    raw_bytes_ref="art_" + content_hash[:24],       # A4 — in-phase self-address; the
)                                                   #   S12 manifest ref replaces it later
```

**AMENDMENT A1 — `FetchedSource` gains `raw_bytes: bytes` (transient carrier).** The
ratified `FetchedSource`/`SourceArtifact` carry the descriptor only — the driver would
hash the raw payload and **discard it**, making the fetched content unrecoverable (a
silent data-loss class: the slice's whole purpose is obtaining full text). The amendment
keeps the persisted `SourceArtifact` descriptor unchanged and adds the byte carrier to
the per-source fetch outcome so the task's ordinary write path persists the payload
(content-addressed) atomically with admission. The hostile gate must rule on this — it
is the one ratified-type change the design requires.

**Only a clean fetch creates an artifact** — a verdict that is a real failure (D2) never
leaves a half-artifact; the artifact is constructed in-memory only after `NONE`/
`INJECTION_SUSPECT` **passes the content-validation hook**.

**The content-validation hook (FD-01 — the P1 fold-in).** The adapter gains a FIFTH
hook — `validate_fetch(self, source: SearchResult, payload: object) -> None`, raising
`FetchContentRejected(reason)` on non-full-text shapes (a typed per-source rejection,
NOT the caller-bug `ProviderValidationError`). The driver calls it on the artifact rows
(`NONE`/`INJECTION_SUSPECT`) BEFORE artifact construction, on the decoded payload; a
rejection maps to `FetchFailure(EMPTY_RESULT, reason=<hook message>)` — never a
`FetchedSource`. Per provider: europepmc rejects non-JATS / `<error>`-rooted payloads
(its spec declares no body marker — `body_required: false` is only coherent WITH the
hook, contract §5.1); arxiv/openalex reject HTML when the URL promised a PDF (their
`fetch: null` means no declared hazard knowledge — the hook still runs). This closes the
reproduced junk-200 acceptance (probes Q1/Q2/Q4/Q5 → `NONE` → artifact) at the
body-marker-less corner, and the injection-before-6a ordering can no longer artifact a
junk body (an instruction-like error page is rejected by the hook regardless of the
`INJECTION_SUSPECT` label); the junk fixtures join D10.

**Dereference contract (FD-05, the V6-FINAL-02 discipline):** in this phase
`raw_bytes_ref` ≡ `artifact_id` — an identity ALIAS, not a store address; the bytes ride
`FetchedSource.raw_bytes`, and the task write path is the SOLE dereference point,
persisting the payload under the content hash atomically with admission. The deferred
S12 manifest replaces the alias when a real store ref exists. Nothing else may
dereference `raw_bytes_ref` as if bytes existed at that address.

## D4 — Bounds: fail-closed, never a silent partial fetch

- `len(sources) > request.max_sources` → **`ProviderValidationError`** (a caller contract
  violation, loud). A truncated fetch would silently drop sources — the audit rule's
  "stricter option." The task sizes its `FetchRequest` to its own stream.
- `len(sources) == 0` → **`ProviderValidationError`**. The walk already makes zero-result
  searches loud (combine raises `EMPTY`), so a task reaching `fetch_batch` with an empty
  stream is a caller bug; a vacuous `COMPLETE` would mask it.
- **Duplicate sources (FD-03):** a repeated `result_id`, or two sources sharing a
  `source_url`, → **`ProviderValidationError`** (identity check before any I/O — a
  double fetch would double transport cost and double log entries; the walk's
  dedup-first-seen makes the task stream unique, so a duplicate is a caller bug).
- `request.size_cap_bytes` → the evaluator's completed-body check via
  `HazardContext.size_cap_bytes` (RT3-01b — an oversized COMPLETE 2xx is `PARTIAL_CONTENT`,
  never silent truncation); the transport's 2xx streaming abort is a transport-construction
  concern (per-task config), unchanged.

## D5 — FetchLogEntry population + the recorder role

Per source, in input order (PS2-07 — fetch-shaped, not the walk's
`RequestLogRecord`): `source_ref` (the `SearchResult.result_id`), `status`
(`FETCHED`/`NO_FULL_TEXT`/`FAILED`), `failure_class` (FAILED only), `hazard_verdict`
(the evaluator class, or `NONE`), `size_bytes` + `content_hash` (FETCHED only),
`access_timestamp_utc`.

**Recorder:** `fetch_batch` does **not** call `recorder.record` in this phase — the
`FetchLogEntry` stream rides the outcome and the task persists it atomically with
admission (PS-01/PS2-07, no new table, dereference per V6-FINAL-02). The `recorder`
parameter is **retained** in the ratified signature, documented as unused-in-this-phase,
reserved for the AR-02 budget-ledger cost hook (the only-entry-point invariant keeps the
machinery unbypassable). Gate question A5: keep (recommended — signature stability) vs
drop.

## D6 — `valid_negative` sources in the input are rejected (loud)

A `valid_negative: True` `SearchResult` is a real "no" on an identifier lookup — it has
no content to fetch; feeding one to `fetch_batch` is a caller error →
**`ProviderValidationError`** (never a silent skip). The task filters valid-negatives
out of its fetch stream; the driver fails closed if one leaks in.

## D7 — Aggregate semantics (PS-01/PS2-01/PS3-04)

- `COMPLETE` — every source **resolved**: fetched **or** `NoFullText`; zero `FetchFailure`s.
- `PARTIAL` — ≥ 1 `FetchFailure` and ≥ 1 resolved; returned with the `failed` list.
- `FAILED` — every source failed; **`NoFullText` keeps the aggregate off `FAILED`** (an
  all-`NoFullText` batch is `COMPLETE`, never `FAILED` — PS2-01).
- **Reading rule (PS3-04):** the aggregate is a **resolution** signal — "every source
  resolved", never "full text obtained for all". `fetched_count`/`no_full_text_count`
  make the split structural; any full-text-availability conclusion reads per-source
  outcomes.
- **Batch-cap exhaustion (FD-02):** the batch stops on the FIRST `daily_cap_exhausted`;
  the remaining sources are marked failed with the same cause and the outcome carries a
  cap note — the aggregate can never read as N independent source failures when the CAP
  was the cause, and a batch retry never re-hits an exhausted cap source-by-source.

## D8 — The slice stays read-only

No events, no tables, no gateway calls, no repository writes. The outcome + `fetch_log`
are carried (transient); the task's ordinary write path persists `Source` + artifact
bytes + the redacted log facts atomically at admission. `FetchLogEntry` has no
credential-bearing fields (source_ref/status/classes/hashes/timestamps only), so the
redaction boundary (D1: `redact_params` before transport) keeps credentials out of every
log surface; `headers_meta` (auth) is never logged.

## D9 — Failure semantics

- Per-source failures are typed (`FetchFailure`), never silent, never counted as
  results.
- A failure leaves **zero** artifacts and a FAILED log entry with the class — a consumer
  can enumerate exactly what failed and why.
- Transport/programming errors (non-`ProviderError` escapes, ADV-08; non-permanent
  `ProviderError` re-raises) stay loud — never converted into a misleading fetch verdict.

## D10 — The golden-fixture plan (`tests/test_provider_fetch.py`, step 5a gate)

1. clean 200 (europepmc-style payload) → `FetchedSource` (artifact id/content_hash/
   media_type/size/ref), log `FETCHED`, aggregate `COMPLETE`, `fetched_count` — and
   **`raw_bytes` carried (A1) with the carrier↔descriptor cross-check pinned (FD-06):
   test-local `hashlib.sha256(raw).hexdigest() == artifact.content_hash` + the id
   prefix — independent recomputation, never the production helper (ADV-06).**
2. PMC metadata-only-no-body (200, `<front>` present, `<body>` absent) →
   `FetchFailure(PARTIAL_CONTENT)` (PS-01/PS2-02/FS-01), never a `FetchedSource`.
3. europepmc fetch 404 → `NoFullText(NOT_OA)` with evidence_basis, aggregate `COMPLETE`
   (PS2-01/PS3-01/PS3-03), never `FAILED`.
4. europepmc 404 + retraction marker → `NoFullText(REMOVED_OR_RETRACTED)`, never `NOT_OA`
   (PS3-03).
5. fetch 200 with `errCode` error field → `FetchFailure(MALFORMED_200)` — error evidence
   beats the result-classes (FS-03/04, PS3-08).
6. empty fetch body — and the recursive-emptiness corner `{"sec": ""}` — →
   `FetchFailure(EMPTY_RESULT)`, never `FetchedSource` (PS3-02/FS-01).
6b. **junk-200 content rejection (FD-01 — the Q1/Q2/Q4/Q5 probes as golden fixtures):**
    europepmc 200 junk-HTML → `FetchFailure(EMPTY_RESULT)` via the hook; europepmc 200
    `<error message=…>`-rooted wrapper → `FetchFailure(EMPTY_RESULT)`; arxiv 200
    HTML-when-PDF-promised → `FetchFailure(EMPTY_RESULT)`; openalex same → rejected —
    never a `FetchedSource` of the error page.
7. all-citation-only batch (every source `NoFullText`) → `COMPLETE`, never `FAILED`
   (PS2-01); `no_full_text_count` correct.
8. mixed batch (fetched + `NoFullText` + failure) → `PARTIAL` with the `failed` list;
   counts correct (PS3-04).
9. `len(sources) > max_sources` → `ProviderValidationError` (D4).
10. `valid_negative` source in input → `ProviderValidationError` (D6).
10b. duplicate `result_id` (and duplicate `source_url` under different ids) →
    `ProviderValidationError` before any I/O (FD-03).
11. serial-order determinism — identical inputs ⇒ identical outcome AND log order (PS2-06).
12. transient fetch (TIMEOUT then clean) → retried → `FetchedSource`; exhausted →
    `FetchFailure(TIMEOUT)`; Retry-After honored (RT-08).
13. daily-cap denial → `FetchFailure(THROTTLED, daily_cap_exhausted)`, no retry,
    transport never called (RT2-05).
13b. **mid-batch daily-cap exhaustion (FD-02):** the cap exhausts at source 4 of 10 →
    the batch stops; sources 5–10 are `FetchFailure(THROTTLED, daily_cap_exhausted)`
    (never fetched, never dropped); the outcome note names the cap; the aggregate's
    cause is legible as the cap, never N independent source failures.
14. scope-error class (contrived spec emitting `VALID_NEGATIVE` at FETCH) → raise
    `ProviderValidationError` (PS3-01, D2).
15. `no_full_text_marker` presence path → `NO_FULL_TEXT` via marker (PS3-08, contrived
    spec).
16. oversize fetch body → `PARTIAL_CONTENT` via the evaluator's completed-body check
    (RT3-01b).
17. content-type mismatch at fetch → `MALFORMED_200` via the pinned label slot (RT3-04,
    contrived spec).
18. `INJECTION_SUSPECT` advisory → `FetchedSource` flagged, never a block.

## D11 — Open questions for the hostile gate

| # | Question | Proposed | Why |
|---|---|---|---|
| A1 | `FetchedSource.raw_bytes` carrier | **add** | without it the fetched payload is discarded after hashing — the data-loss class |
| A2 | over-bound / empty / valid-negative inputs | **raise** | fail-closed; truncation/vacuous-COMPLETE would mask caller bugs |
| A3 | `media_type` when no Content-Type | `application/octet-stream` | honest default, never a fabricated label |
| A4 | `raw_bytes_ref` in this phase | artifact self-address | the S12 manifest/durable-outbox phase (deferred) replaces it |
| A5 | `recorder` parameter | **retain**, unused-in-phase | signature stability; the AR-02 cost hook needs the boundary |
| A6 | providers with `fetch: null` (arxiv/openalex) | generic rules + the content-validation hook (FD-01) | HZ-04's documented meaning — no declared fetch hazard knowledge, but the hook still rejects junk before artifact construction; per-provider `no_full_text_status` declarations are the later-slice extension (a 404 then reads `NoFullText`, not the FD-04 permanent) |
| A7 | the fetch content-validation hook | **add** — a FIFTH adapter hook | FD-01: the body-marker-less corner has no guard and the evaluator's promised "adapter parse" delegation does not exist; the hook is the minimal provider-shaped answer, consistent with the thin-adapter discipline |
| A8 | mid-batch daily-cap exhaustion | **stop the batch** | FD-02: stop-with-cause (remaining sources marked failed, cap note on the outcome) — the stricter option, per D4's own discipline; continue-and-collect would degenerate the aggregate |

**Status:** DESIGNED — step 5a text. The FD-01…FD-07 hostile-gate fold-in is
**FOLDED IN (2026-08-14)** — the content-validation hook (A7), the batch-cap stop (A8),
the duplicate / 404-reason / dereference / fixture-invariant / retry-budget pins (FD-03…
FD-07). NOT implemented, NOT tested, NOT ratified-as-implemented. **The A1 + F1–F13
pre-implementation hostile gate is resolved in `hermes_researchsourceprovider_fetch_gate_remediation.md`
(2026-08-14) — the AUTHORITATIVE step-5a record; it supersedes this document where
they conflict (A1 MODIFIED: the raw bytes ride a separate transient `FetchedPayload`
carrier on `FetchOutcome.payloads`, not `FetchedSource.raw_bytes`; F1–F13 resolve
memory bound, closure, empty/valid-negative boundaries, attempt accounting,
Retry-After replay, `fetch: null` safety, media-type ownership, recorder retention,
failure-artifact ownership, no-body-in-failures, seriality).** The implementation gate
(review → fold-in → implementation) is the standing condition, per the
manual-proof-first rule.
