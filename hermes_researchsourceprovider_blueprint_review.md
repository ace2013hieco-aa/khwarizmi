# Adversarial Review — ResearchSourceProvider Part 3 Blueprint

**Scope:** protest-stage attack on `hermes_researchsourceprovider_implementation_design.md` (the Part 3 implementation blueprint) against its own contract (`hermes_researchsourceprovider_contract.md`) and the ratified authority rules it claims to preserve (v6 §15 port contract, §18 untrusted-data rule, §16.1 hashing/immutability, S6 secrets-out, the §27 item 55 precondition). Method: hunt bypass paths, silent-failure surfaces, determinism breaks, and contract-vs-blueprint drift across the four named surfaces (three-hook adapter skeleton, generic hazard evaluator, walk-driver reconciliation edges, `RecordedTransport` fail-closed semantics) plus adjacent surfaces the four expose. Independent pass — the blueprint author's claims were not trusted; every finding below was re-derived from the blueprint text and checked against the contract.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| PS-01 | **P1** | fetch surface + handoff | Batch-fetch semantics and fetch-level hazard evaluation are unspecified — the PMC `PARTIAL_CONTENT` hazard is a *fetch* hazard, yet the designed flow only covers the search walk; per-source fetch failures degrade silently at the task level, and the request-log handoff to persistence is unstated for a read-only slice |
| PS-02 | **P1** | redaction | Transport exceptions conventionally embed the raw URL — a credential/`email` in the URL leaks into task output/events through the exception path, bypassing the recorder-boundary redaction that is the contract's core promise |
| PS-03 | **P2** | enforcement boundary | The only-entry-point invariant is unstated: nothing in the blueprint forbids a task/kernel from constructing its own HTTP call to a provider endpoint, bypassing limiter + hazard evaluation + redaction + (future) budget accounting |
| PS-04 | **P2** | reconciliation | `count_semantics` lacks a dedup-direction — the general "dedup before comparing to total" rule is right for Crossref but can produce a false `SHORTFALL` for a provider whose total counts raw rows while pages repeat, and the inverse is also unencoded |
| PS-05 | **P2** | determinism | Cross-provider fan-out and aggregation order are unspecified — the replay-determinism guarantee ("provider order → page order → dedup-first-seen") has no defined provider order, and the limiter's per-task slices imply concurrent walks |
| PS-06 | **P2** | replay harness | The request fingerprint is under-specified — `(provider, endpoint, query, page_index)` is ambiguous for cursor providers (same page_index, different cursors → stale fixture served as fresh) |
| PS-07 | **P3** | walk driver | Row-level parse failure semantics are unspecified — one malformed row inside a valid page: abort the walk (silent data loss) or skip-and-count (deterministic either way, but must be specified) |
| PS-08 | **P3** | hazard evaluator | No response-schema-drift sentinel — a provider field rename degrades silently (empty identifiers/abstracts) instead of failing closed; a required-field check in the spec closes it |
| PS-09 | **P3** | redaction | Header redaction is missing from the blueprint's redact module — `RequestSpec.headers_meta` and `Authorization` headers are in the contract but `redact_url`/`redact_params` only cover URL + query params |
| PS-10 | **P3** | replay harness | The recorded-fixture acceptance gate is unstated — `LIVE_SMOKE` recordings are trusted replay input and the `expected` block is optional; catalog fixtures must carry mandatory assertions and an engineering-plane review before merge |
| PS-11 | **P3** | types | `valid_negative` is referenced by the error taxonomy but is not a field of the `SearchResult` dataclass — spec inconsistency |
| PS-12 | **P3** | adapter skeleton | "canonicalization happens in parse, never after" contradicts the separate `extract_ids` hook, which runs after `parse_page` — the parse contract must include identifier canonicalization |
| PS-13 | **P2** | aggregate semantics | `EMPTY` conflates "no results" with "couldn't search" — an all-throttled/all-errored aggregate is labeled `EMPTY` (reads as a valid "nothing found"); a task could conclude "no literature exists" from "all providers were down" |

## Detail

**PS-01 — The fetch surface is the largest silent-failure hole in the blueprint. (P1)**

The blueprint's flow (steps 2–8 of the walk) designs `search()` end-to-end. But two of the contract's most dangerous catalog entries are **fetch-level hazards**: PMC's metadata-only-no-body `<pmc-articleset>` (the contract §5.3 entry the upstream source calls "the most dangerous failure in this skill") and arXiv's fetch-side behaviors. The blueprint's `test_providers_adapters.py` row says "search + fetch + parse" per adapter, but there is **no `fetch()` design at all**: no per-source fetch outcome, no aggregate fetch result, no fetch bounds, no fetch retry policy, no statement that `evaluate_hazards` runs on fetch payloads with the same spec. A task that fetches N sources where 3 return `PARTIAL_CONTENT` has no designed way to *know* it got 3 degraded artifacts — the per-source failure either silently disappears into the task's `Source` list or must be rediscovered ad hoc. **`FetchOutcome { per_source: [...], failed: [...], aggregate }` mirroring `SearchOutcome` is required** (§8 of the contract's "no silent failure" rule applies to fetch as much as search). Related: the `RequestLogRecord` (§8) is written by the recorder but the slice is read-only by construction — **the handoff of the request log to persistence (§14 edges / `search_accounting`) is never designed**; `SearchOutcome` has no `request_log_ref`, and `SearchResult.provenance.request_log_ref` points at a record with no defined home. This is the V6-FINAL-02 dereference discipline applied to the provider layer: a `request_log_ref` must dereference.

**PS-02 — Credentials leak through the exception path. (P1)**

The contract's core promise is "credentials never appear in any Hermes record" and redaction is "applied once, at the recorder boundary — before logging, provenance, events, **or error messages**." But the blueprint's `http.py` is "the single HTTP client" and nothing specifies that **transport exceptions are redacted before propagation**. Standard HTTP-client behavior embeds the request URL in `ConnectionError`/`HTTPError`/timeout messages. For `query`-auth providers (CORE key, OpenAlex/Crossref `mailto`, NCBI `email`), the URL carries the credential or the polite-pool identifier — an unredacted exception propagates it into the task's output/event path, where the S6 validator would catch it only if the task records it (and the S6 validator is a *write-path* backstop, not an exception sanitizer). **Fix: the transport must never embed a raw URL in an exception; the recorder's redaction applies to the exception message, or the transport raises redacted-form errors only.** This is the provider-side complement of S6: S6 guards the write path, PS-02 closes the path *before* the write path exists.

**PS-03 — The only-entry-point invariant is unstated. (P2)**

The blueprint correctly says the limiter "wraps the transport, not the adapter," and that adapters cannot bypass it. But nothing states the *structural* invariant: **the provider package has exactly one entry (the Tool Runtime's `walk()`/`fetch()`), and no task, kernel (PA1), or agent can construct a raw HTTP call to a provider endpoint.** Without that stated invariant, the "single HTTP client" in `http.py` is a convenience, not a boundary — and the moment it is a convenience, the limiter, the hazard evaluator, and the redaction recorder are all bypassable by importing the adapter and calling `build_request` + a hand-rolled `requests`/`urllib` call. The future budget ledger (AR-02) inherits the same hole: uncharged retrieval. **Fix: state the invariant — the Tool Runtime owns the only `Transport` implementation, and provider imports outside the runtime context are disallowed (same shape as the T4-only rule for generated code).**

**PS-04 — Reconciliation can false-positive `SHORTFALL`. (P2)**

Step 6 applies "dedup before comparing to total" per contract §4.3. That rule is *correct* for Crossref (whose `total-results` counts version records) but the blueprint generalizes it: "The reconciliation comparison always operates on deduplicated, canonicalized identifiers" (contract §4.3) with no per-provider direction. Two failure shapes: (a) a provider whose pages legally repeat rows **and** whose `total` counts raw rows — dedup-before-reconcile **under-counts retrieved, so `total > retrieved` falsely fires `SHORTFALL`** even though the walk was complete; (b) a provider whose `total` is dedup-truthful but whose pages never repeat — dedup-before is harmless, but the *estimate* flag semantics are still ambiguous. **Fix: `count_semantics` in the hazard spec gains a `dedup_direction: before | none` (or an explicit `counts_raw_rows: bool`), and the walk applies dedup-before-reconcile only where the spec declares it.** This belongs in the spec (content), not the driver (code) — the "one evaluator" discipline survives.

**PS-05 — The determinism guarantee has no defined provider order. (P2)**

§7.2 promises "provider order → page order → dedup-first-seen" as the replay determinism guarantee, and §6.1's limiter has "per-task fair-share slices" + "global bounded concurrency" — which implies **concurrent cross-provider walks**. If the fan-out order is a dict iteration or a scheduler artifact, the `SearchOutcome.per_provider` tuple order is nondeterministic, and the first-seen dedup winner can vary run to run (two providers both carrying a DOI → which one "wins" depends on arrival order). **Fix: the routing layer must define a fixed, sorted provider order for fan-out and aggregation (e.g., allowlist order), and the driver must serialize the aggregation regardless of walk concurrency.** Without it, the "identical (request, recorded bodies) ⇒ identical stream" promise is false.

**PS-06 — The fingerprint is ambiguous for cursor providers. (P2)**

The fixture `request_fingerprint` is `sha256(provider, endpoint, normalized query, page_index)`. For **cursor-based** providers (OpenAlex, Crossref, EuropePMC `cursorMark`) `page_index` is a walk-local counter, not a request identity: two different walks can reach page_index 2 with entirely different cursor values, and a stale fixture recorded at "page_index 2" would be served for a *different* request — the adapter "passes" against a response it never actually would have received. The fingerprint must cover **the full request-defining state** — provider, endpoint, normalized query, and the request params *including cursor/offset state and page_size*. This is the same fail-closed spirit as the fingerprint-miss rule: the fingerprint has to be able to *detect* drift, and page_index alone cannot.

**PS-07 — Row-level failure semantics are unspecified. (P3)**

`parse_page` returns `records`; nothing defines what happens when one row in an otherwise-valid page is malformed (missing fields, wrong types). Abort-the-walk silently discards the earlier pages' records (data loss presented as a clean run) unless the driver treats it as a page failure; skip-and-count changes `retrieved_count` and can itself trip reconciliation edges. Either is defensible, but the blueprint's "a malformed row → deterministic" claim is only true once the choice is specified. **Fix: state the row-level policy (recommended: skip-and-count with a `MALFORMED_ROW` note; page-level structural failure stays a page failure), and fixture it.**

**PS-08 — No schema-drift sentinel. (P3)**

The hazard evaluator detects *declared* failure signatures, but nothing detects **silent schema drift** — a provider renaming a field (e.g., `hitCount` → `totalHits`) produces empty identifiers/abstracts that pass every declared marker and parse as success. The worst case is caught by "total > 0 with zero delivered → SHORTFALL," but a *partial* drift (some fields survive) degrades quietly. **Fix: the spec gains a `required_fields` list; absence of a required field → `MALFORMED_200` (fail closed, the S6-class discipline applied to provider schemas).** Cheap, deterministic, and it makes the "provider drift is a typed failure, never a silent degrade" claim structural.

**PS-09 — Header redaction is not in the redact module. (P3)**

The contract (§7) covers `Authorization` headers and cookies; the blueprint's `RequestSpec` carries `headers_meta`; but `redact_url`/`redact_params` only cover URL + query params, and §6.2 never mentions headers. A `header`-auth adapter (or a provider that reflects auth in a cookie) would have its credential recorded verbatim if the recorder logs `headers_meta` as-is. **Fix: the redaction module gains `redact_headers(headers, policy)` and the recorder applies all three to the recorded request form.**

**PS-10 — Recorded fixtures need an acceptance gate. (P3)**

`LIVE_SMOKE=1` recordings are trusted replay input, and the `expected` block is "optional." A recorded fixture is *evidence about the provider*, not evidence of correctness: a recording that captured a silent degradation (an OpenAlex filter drop, a degraded PMC body) would replay as the golden expectation. **Fix: (a) the `expected` block is mandatory for catalog fixtures (hazard class + reconciliation verdict asserted, not just replayed); (b) new/adjusted recordings pass an engineering-plane review (the §20 discipline) before merge — the same "upstream CI is not evidence of safety" rule the amendment already applies to the source repository.**

**PS-11 — `valid_negative` is not a field. (P3)**

The error taxonomy says a `VALID_NEGATIVE` is "a `SearchResult` with a `valid_negative: true` marker" — but the `SearchResult` dataclass in §2.1 declares no such field, and `reconciliation`/`aggregate` cannot carry it (an identifier lookup answered "no" is `COMPLETE`, not `SHORTFALL`/`UNKNOWN`). As designed, a valid-negative record would be a `SearchResult` with empty title/authors and no marker distinguishing it from a genuinely empty search. **Fix: add `valid_negative: bool` (and, if the write path needs it, `valid_negative_for: str` — the identifier that resolved to "no") to `SearchResult`.**

**PS-12 — "Canonicalization happens in parse, never after" contradicts the hooks. (P3)**

`parse_page` is documented "records are RAW provider rows — canonicalization happens in parse, never after," yet `extract_ids` is a separate hook the walk calls **after** parse (step 5). The sentence is false as written and invites two competing canonicalization homes. **Fix: restate the parse contract — `parse_page` produces raw rows; `extract_ids` is *part of* the parse contract, called by the driver immediately per row, and is the only place identifier canonicalization happens.** (The `normalize_identifier` utility is the shared implementation.)

**PS-13 — `EMPTY` must not mean "couldn't search." (P2)**

Step 7 maps "all providers zero/errored → `EMPTY` → `RetrievalShortfallError(aggregate="EMPTY")`." A fully-throttled or fully-errored search is labeled `EMPTY`, which a downstream consumer reads as a valid "no literature found" — the exact silent-conclusion failure the contract exists to prevent (the difference between "no evidence" and "couldn't look"). The error does raise (not silent), but the *label* invites the wrong scientific conclusion. **Fix: introduce `UNAVAILABLE` as a distinct aggregate (all providers throttled/errored/unreachable) with its own typed failure, and keep `EMPTY` strictly for "searched, found nothing." The `reason` field alone is not enough — the aggregate vocabulary is the contract.**

## Interaction with prior findings

| Prior finding | Interaction |
|---|---|
| AR-02 (budget ledger unspecified) | **Reinforced.** PS-03's bypass would also bypass the future ledger's retrieval-cost inputs; the only-entry-point invariant is a precondition for AR-02's eventual enforcement, not just for the limiter |
| AR-04 (caller-role attestation honor-based) | Unaffected — the provider slice is role-agnostic read-only retrieval; the write path's role enforcement is untouched |
| IDR29-01/02 (controller recovery) | Unaffected — the slice is read-only; no task-state transitions, no recovery path to interact with |
| V6-FINAL-02 (provenance dereference) | **Reinforced.** PS-01's `request_log_ref`/`request_log` handoff must obey the same dereference contract — a ref that cannot be resolved must fail, never dangle |
| S6 (secrets-out validator) | **Reinforced.** PS-02 closes the leak *before* the write path; S6 remains the write-path backstop. Both are needed — S6 cannot catch an exception that never reaches a record |
| §27 item 55 (allowlist/redaction/reconciliation ratification) | **Scope-extended.** The five ratification points are unchanged, but PS-01 (fetch), PS-04 (dedup-direction), PS-13 (UNAVAILABLE) add ratification material: the contract text they touch must be ratified with the same item |

## What survives

The spine is sound and none of the findings require a new component or a redesign: the three-hook skeleton under one driver, the hazards-as-data evaluator, the fingerprint-miss fail-closed replay, the recorder-boundary redaction, and the clock-injected limiter all survive intact. PS-01 and PS-02 are **spec gaps in the current blueprint text**, not architecture errors — the blueprint simply does not yet cover the fetch surface or the exception path. PS-03–PS-13 are completions (one stated invariant, two spec fields, one aggregate value, one fingerprint formula, and several specified-behavior statements). The zero-new-components claim of the amendment is unaffected: every fix lands inside the existing blueprint's modules.

## Overall verdict: **MERGE WITH REMEDIATION.**

PS-01 and PS-02 are gate-blocking for the blueprint's own two load-bearing claims — "no silent failure" (the contract's rule 3) and "credentials never appear in any Hermes record" (the redaction contract) — because each has a designed flow that stops one step short of where the failure actually occurs. The remaining findings are P2/P3 completions. All thirteen map to concrete, fixture-able design text changes in `hermes_researchsourceprovider_implementation_design.md` (and, for PS-04/PS-13, the contract's `count_semantics`/aggregate vocabulary, which the contract wins by the blueprint's own precedence rule). No code exists yet, so no remediation touches implementation — the remediated blueprint is what Part 3 will consume.

---

## Remediation disposition (all thirteen closed in the design text)

| ID | Fix | Where it landed |
|---|---|---|
| PS-01 | `FetchOutcome`/`FetchedSource`/`FetchFailure`/`FetchRequest` types; `build_fetch_request` hook; §5.3 fetch driver with per-source hazard evaluation (PMC `PARTIAL_CONTENT` caught at fetch); fetch aggregate `COMPLETE/PARTIAL/FAILED`; request-log carried on the outcome and persisted into `Source` provenance at admission — no new table, V6-FINAL-02 dereference contract | blueprint §2.1, §3, §5.1 step 9, §5.3, §8, §9 step 5a; contract §9 rows 21 |
| PS-02 | Exception-path rule: the transport raises errors built only from the redacted request form; zero credential/`email` text in exceptions; test row added | blueprint §6.2; contract §9 row 23 |
| PS-03 | Only-entry-point invariant stated: Tool Runtime owns the only `Transport`; `walk()`/`fetch_batch()` are the only entries; provider package not importable outside the runtime context (T4-rule shape) | blueprint §1 ownership rule |
| PS-04 | `counts_raw_rows` field in the hazard spec; reconciliation compares raw counts unless the spec declares dedup-before; no false `SHORTFALL` either way | blueprint §4.1, §5.1 step 6; contract §4.3, §9 row 25 |
| PS-05 | Routing fan-out + aggregation in the fixed §3 allowlist order, never dict/arrival order; determinism guarantee restated | blueprint §5.1 step 1, §6.1, §7.2 |
| PS-06 | Fingerprint covers full request-defining state (params incl. cursor/offset + page_size), same formula as the request log; same-page_index-different-cursor is a miss | blueprint §7.1; contract §9 row 22 |
| PS-07 | Row-level policy: malformed row = skip-and-count with `MALFORMED_ROW` note (never abort); structurally unparseable page = page failure | blueprint §5.1 step 5; test row |
| PS-08 | `required_fields` in the hazard spec; absence → `MALFORMED_200` (schema-drift sentinel, fail closed) | blueprint §4.1, §4.2 step 3a; contract §9 row 24 |
| PS-09 | `redact_headers` added; `RequestSpec.headers_meta` recorded only redacted (Authorization/cookies covered) | blueprint §6.2 |
| PS-10 | `expected` block mandatory for catalog fixtures; new `LIVE_SMOKE` recordings pass an engineering-plane review before merge | blueprint §7.1 |
| PS-11 | `valid_negative: bool` + `valid_negative_for` fields on `SearchResult`; error-taxonomy mapping uses them | blueprint §2.1, §2.2 |
| PS-12 | Parse contract restated: `parse_page` yields raw rows; `extract_ids` is part of the parse contract, the only canonicalization home | blueprint §3 |
| PS-13 | `UNAVAILABLE` added to the aggregate vocabulary; `EMPTY` strictly = searched-and-found-nothing; `ProviderUnavailableError` | blueprint §2.1, §2.2, §5.1 step 7; contract §4.2, §9 row 20 |

**Status:** all thirteen remediated in the design text (blueprint + contract, where the contract wins). No code exists; the remediated blueprint is what Part 3 consumes. A second-gate review against the remediated text is the standing next step before implementation.
