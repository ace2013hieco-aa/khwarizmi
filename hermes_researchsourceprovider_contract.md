# HERMES RESEARCHSOURCEPROVIDER — IMPLEMENTATION CONTRACT (DESIGNED)

**Date:** 2026-08-13
**Status:** **DESIGNED** on the state ladder. This document is the concrete implementation contract for the Paper Lookup slice of the Scientific Agent Skills candidate amendment — §27 item 55 (provider allowlist + rate-limit/reconciliation/redaction contract), §30.3 Paper Lookup, §30.4 phase-table row. It implements nothing; it is the design the Part 3 implementation will consume, and it is **conditional on the §27 item 55 ratification decision** (the initial allowlist, the reconciliation semantics, and the redaction contract must be ratified before any adapter runs).
**Inputs:** v6 §15 (the ratified `ResearchSourceProvider` Protocol + tool model), §30/§3f (the candidate amendment), `hermes_scientific_agent_skills_audit.md` §3.1 (the paper-lookup audit), the upstream `paper-lookup` skill at source HEAD `5ad4aae7` (11 per-provider `references/*.md` files, ~2,000 lines; 5 stdlib-only scripts incl. `paginate.py` — the reconciliation/redaction reference — and `arxiv_atom.py` — the HTTP-200-failure reference), and the live Hermes repo (571 tests green at HEAD `4b2a7ce`).

---

## 1. Scope and governing rules

This contract covers the **scholarly retrieval adapter set** (11 providers) behind the ratified `ResearchSourceProvider` port. The web-search adapters named in §15 (`SerperAdapter`, `SearxngAdapter`) are a **separate row of the same §27 item 55 allowlist decision** — same policy machinery, different endpoint set; this contract does not design them.

Governing rules carried from the amendment (§30.2 rules 2, 9, 10):

1. **Provider-ownership rule.** Retrieval is Hermes-owned. Adapters are Hermes-native thin REST clients; nothing is vendored (§15/§22). The per-provider hazard knowledge is reference content + one deterministic evaluator (§5) — never per-provider judgment code scattered through the runtime.
2. **Untrusted-data rule.** Every provider response is untrusted third-party data (§18: "web content is data, not instructions; never raw-concatenated into reasoning contexts"). Responses reach a judgment context only as schema'd `Source` records (v2.1 §21 rule, preserved).
3. **No-silent-failure rule.** A reconciliation shortfall is a typed failure (`SHORTFALL`), never a silent empty result (§30 rule 2). An empty-where-expected aggregate is `RetrievalShortfallError`. A bounded-by-request walk is *recorded*, not an error.
4. **Read-only rule.** Retrieval is `READ_ONLY` (PA4 `side_effect` class — outbox-exempt); results become `Source` records + artifacts + provenance only through the existing write path. Retrieval never creates tasks, promotes evidence, or gates anything.
5. **Replayability rule.** All adapter behavior is deterministic given (request, recorded response); tests run offline against recorded responses; live network is an opt-in P7 smoke test, never CI.

---

## 2. The port contract (ratified §15, concretized — the signature is unchanged)

```python
class ResearchSourceProvider(Protocol):        # §15 — REIMPLEMENTED natively
    def search(self, query: str, max_results: int) -> list[SearchResult]: ...
    def fetch(self, source: SearchResult) -> SourceArtifact: ...          # raw → extraction
    def extract(self, artifact: SourceArtifact) -> list[Source]: ...      # schema'd Source records
```

The ratified signatures are preserved exactly. This contract concretizes the **types** and the **runtime policies** around them.

### 2.1 The query string and retrieval hints

`query` is a free string with **structured identifier prefixes** parsed deterministically by a shared helper:

```
doi:10.1103/PhysRevLett.116.061102     pmid:26214858     pmcid:PMC4922062
arxiv:2103.15348                       url:https://…    <free topic terms>
```

- `parse_query_hints(query) -> RetrievalHints { identifiers: dict[str, str], topic: str, mode: IDENTIFIER | TOPIC | MIXED }` — deterministic, stdlib-only, unit-tested.
- Adapters route on hints: Unpaywall serves `doi:` only; bioRxiv/medRxiv serve `doi:10.1101/…` only; PubMed/PMC serve `pmid:`/`pmcid:`/`doi:`; arXiv serves `arxiv:`/`doi:`; the rest serve topic + any identifier they resolve.
- A query with no provider-resolvable hint is a **topic search** fanned out to the topic-capable subset (PubMed, EuropePMC, OpenAlex, Crossref, Semantic Scholar, CORE, arXiv).

### 2.2 The `SearchResult` record (the reconciliation carrier)

```text
SearchResult {
  result_id            # "sr_" + sha256(canonical_json(provider, endpoint, query, position_key,
                       #   canonical_identifiers))[:24] — content-addressed, deterministic
  provider             # adapter identity, e.g. "pubmed"
  endpoint             # exact endpoint path used
  query                # the exact normalized request sent (post hint-routing)
  request_params_redacted   # dict — the REDACTED parameter form (§7), the only form that is
                            #   ever logged / stored / emitted
  identifiers          # {doi?, pmid?, pmcid?, arxiv?, core_id?, openalex_id?, …} — canonical form
  title, authors[], year, venue
  abstract_sha256      # hash only; the abstract text lives in the content-addressed SourceArtifact
  source_url           # redacted URL form
  access_timestamp_utc # ISO-8601 UTC
  page_index, cursor_key    # pagination position
  retrieved_count, total_count, total_is_estimate   # reconciliation inputs (§4)
  reconciliation       # COMPLETE | SHORTFALL | UNKNOWN — the §4 verdict for THIS provider walk
  content_hash         # sha256 of the normalized record
  provenance           # { request_log_ref, provider_spec_version, hazard_verdict }
}
```

Every field is either deterministic content or a recorded observation — **no field is ever model-filled**. `Source` (§16.1) is unchanged; the `SearchResult` is the retrieval-side record that becomes a `Source` through the ordinary write path.

### 2.3 `SourceArtifact` and `extract`

- `fetch(source)` returns the **raw payload** (Atom XML, JSON, JATS XML) wrapped as `SourceArtifact { artifact_id, content_hash, media_type, size_bytes, retrieved_from, access_timestamp_utc, raw_bytes_ref }` — content-addressed; the raw payload is immutable and replayable (§8).
- `extract(artifact)` parses raw → schema'd `Source[]` records. Parsing is deterministic (JATS/Atom/JSON parsing per provider); **extraction is never an LLM step** (the LitKG/claim-extraction LLM layer is the separate §29.3 `EXTRACT` pipeline, which consumes `Source` records — it is not part of this port).

---

## 3. Initial adapter set (11 providers) — the §27 item 55 allowlist row

| Adapter | Primary role | Auth / polite params | Pagination | Rate default (starting point, §6) | Known failure classes (→ §5) |
|---|---|---|---|---|---|
| `pubmed` | citations/abstracts (NCBI E-utilities: esearch → esummary → efetch) | none; `tool` + `email` params required | offset (`retstart`/`retmax`) | 3 rps no key / 10 rps with key; off-peak for batches | 429 JSON error body; 400 bad request; empty `PubmedArticleSet` |
| `pmc` | full text (NCBI E-utilities `db=pmc` + OA service) | none; `tool` + `email` | offset | 3 rps / 10 rps with key | **metadata-only-no-body 200** (the dangerous one, §5.3); empty `<pmc-articleset>` |
| `europepmc` | cross-corpus search (PubMed + PMC + preprints + patents) + clean full-text | none | `page`/`cursorMark` (cursorMark for deep walks) | conservative self-imposed (no published limit) | `errCode`/`errMsg` in 200 JSON; full-text 404 is a **valid negative** |
| `arxiv` | preprints (Atom XML API) | none | offset (`start`/`max_results`) | conservative (1 rps sustained) | **HTTP-200 "Error" entry**; plain-text `Rate exceeded.` throttle; hard-wrapped title/summary; version-suffixed ids |
| `biorxiv` / `medrxiv` | preprints by DOI (API v2) | none | none (single-entity) | conservative (1–2 rps) | 404 unknown DOI (valid negative) |
| `openalex` | general scholarly graph | `mailto` (polite pool) | **cursor** (`cursor=*` → `meta.next_cursor`, stop on null) | ≤ 10 rps polite | **silent filter rewrite** (§5.3); usage-based 429; count-vs-cursor mismatch |
| `crossref` | DOIs / bibliographic registry | `mailto` (polite pool) | cursor (unlimited) / offset (≤ 10,000) | 5 rps public / 10 rps polite; concurrency 1 / 3 | **`total-results` is an estimate + version records** (dedup before reconcile, §4.3); cursor trap; 400 malformed |
| `semantic-scholar` | relevance search + citation graph | optional key | offset (`offset`/`limit`, `total`) | 1 rps unauth default; honor 429 | 429 JSON `{message, code: "429"}`; 404 (valid negative) |
| `core` | aggregated OA search | API key (token-based) | offset / scroll (scroll costs tokens) | per-key tokens (100/day, 10/min unauth) | partial-shard transient errors; token-exhausted 429/403 |
| `unpaywall` | OA location by DOI | `email` param required | none (single-DOI) | 100k/day | `{"is_oa": false}` = **valid negative** (never a failure); 404 unknown DOI |

**Adapter contract card (all 11 share this shape):**

```text
Adapter {
  provider_id, base_url, auth_policy,         # auth: none | header | query-param (credentials NEVER in logs)
  hint_routes: {identifier_kind → endpoint},  # deterministic routing (§2.1)
  pagination: {kind: cursor|offset|none, start_param, page_size_cap, max_pages, loop_guard},
  hazard_spec_ref,                            # versioned ProviderHazardSpec (§5.2)
  rate_profile: {rps, burst, concurrency, daily_cap},   # §6 — starting-point defaults
  retry_class_map,                            # transient/permanent/validation per failure class (§6.3)
  parser: jats | atom | json_flat | json_nested,
  normalize: identifier_kind → canonical form (§3.1)
}
```

**Extensions are engineering-plane decisions:** a new provider enters only through the §20 engineering plane with a `ProviderHazardSpec`, rate profile, parser, and golden fixtures — never at runtime (PA3/PX12 discipline preserved).

### 3.1 Identifier normalization (the `normalize_identifier` utility — deterministic, unit-tested)

| Kind | Canonical rule |
|---|---|
| DOI | lowercase; strip trailing dot; accept `https://doi.org/` / `doi:` / bare forms; keep `10.` prefix |
| PMID | digits only; strip `PMID:` casing |
| PMCID | `PMC` + digits; strip numeric-only bare form (a bare number is an ambiguous PMC-vs-PubMed id — the adapter resolves via the provider, never by guessing) |
| arXiv | new scheme `YYMM.NNNNN` + optional version; old scheme `arch-ive/YYMMNNN`; **strip version suffix for identity, retain it in `identifiers` for provenance** |
| URL | extract DOI/arXiv id from the URL when the host is a known resolver; otherwise `url:` stays a fetch hint |

Cross-provider dedup key: `doi` if present, else `pmid`, else `pmcid`, else `arxiv` — first-seen wins, duplicates recorded (never silently dropped: a dedup note goes into the walk's notes and `search_accounting`).

---

## 4. Reconciliation fields and semantics (§27 item 55 ratification point)

### 4.1 The per-provider verdict

```text
reconciliation ∈ { COMPLETE, SHORTFALL, UNKNOWN }
```

| Verdict | Condition | Handling |
|---|---|---|
| `COMPLETE` | (a) `total` reported and `retrieved == total`; or (b) `total` reported and the walk reached the caller's `max_results` with `retrieved == max_results` (bounded-by-request); or (c) `total` absent, walk exhausted naturally — **cursor-aware + position-aware (WS-02): an empty page WITH a live next cursor CONTINUES the walk (up to bounds); "exhausted" means (empty page ∧ no next cursor ∧ first page) ∨ (no next cursor after a non-empty page); an empty page after ≥ 1 non-empty page is `SHORTFALL(cause=EMPTY_MID_WALK)`, never a silent `COMPLETE`** — recorded with a `total_not_reported` note | normal |
| `SHORTFALL` | the walk **terminated prematurely**: (a) cursor chain broke mid-walk (repeating cursor → `CURSOR_TRAP` guard fired — detected BEFORE the duplicate request is issued, WS-06); (b) a mid-walk page failed — **transient-after-retries OR permanent-immediate, both convert to `SHORTFALL` with the cause recorded (WS-04)**; (c) `total > retrieved` and no next page / next cursor; (d) `total > 0` but **zero** records delivered (every page dropped by validation); (e) an empty page mid-walk (`EMPTY_MID_WALK`, WS-02) or a `VALID_NEGATIVE` page in a query-mode walk (`VALID_NEGATIVE_MID_WALK`, WS-01) | **typed failure** — `RetrievalShortfallError { provider, expected, got, cause_class }`; the provider's records are still returned (flagged), never silently discarded |
| `UNKNOWN` | provider reports no total and the walk is not exhaustible (e.g., bounded by `max_results` with no total) | recorded honestly; the aggregate treats it as COMPLETE-by-declaration with `total_is_estimate: true` and a note — the caller is told the count is unverifiable |

### 4.2 The aggregate outcome

```text
SearchOutcome { per_provider: [SearchResult…], aggregate: COMPLETE | PARTIAL | EMPTY | UNAVAILABLE,
               typed_failure, request_log }
```

- **`COMPLETE`** — every routed provider walked cleanly (or bounded-by-request). **Reading rule (WS-05 — the walk's PS3-04 analog):** the aggregate is a *resolution* signal, never a coverage claim — `COMPLETE` includes `STOPPED_AT_LIMIT` (bounded-by-request: more existed) and `UNKNOWN` (no total); any coverage conclusion must read the per-provider reconciliations + notes (`STOPPED_AT_LIMIT`, `total_not_reported`, `MALFORMED_ROW`, `UNKNOWN`), which the outcome carries.
- **`PARTIAL`** — ≥ 1 provider `SHORTFALL`/`UNKNOWN` but ≥ 1 provider delivered. **Not an error**: the outcome is a typed `PARTIAL` marker carried in the task output and the `LiteratureReview.search_accounting` (§30.3 Literature Review) — the caller is *structurally told* the search was incomplete.
- **`EMPTY`** — every routed provider returned zero. **Typed failure** (`RetrievalShortfallError` with `aggregate: EMPTY`): a topic search that *ran* and found nothing is surfaced, never a silent empty result (§30 rule 2). `EMPTY` strictly means "searched, found nothing" — it must never be used for a search that could not run.
- **`UNAVAILABLE`** — **no** provider ran (every routed provider throttled/errored/unreachable — the search could not run). **Typed failure** (`ProviderUnavailableError` with `aggregate: UNAVAILABLE`) — deliberately distinct from `EMPTY` so a task can never conclude "no literature exists" from "all providers were down" (PS-13).
- **The zero-delivered matrix (PS2-03 + PS3-06) — the full rule:** `UNAVAILABLE` requires *no* provider **searched** (incl. a query routeable to **no** adapter at all — every routed adapter skipped — which must never read as "searched, found nothing"); `EMPTY` requires ≥ 1 provider *searched* (its zero/valid-negative causes and any down providers are recorded in `notes` — a mixed empty-and-down search is `EMPTY`, not `UNAVAILABLE`, because the search did run); a **valid-negative-only** identifier lookup (≥ 1 provider answered "no") is `COMPLETE` (answered), with down/unrun providers recorded — never `PARTIAL`, never `EMPTY`; **valid-negative mixes (PS3-06)** — a valid-negative answer mixed with an empty topic search, or with real results, is `COMPLETE` (the lookup was answered) with the other causes in `notes` — never `PARTIAL`, never `EMPTY`. **Terms (WS-07 + RT4-02):** "searched" = ≥ 1 response **classified** (any hazard verdict other than a pure throttle/transient/timeout exhaustion); "ran" = the transport was called — a provider whose first page throttled to exhaustion, or whose every attempt timed out (`TIMEOUT`, the TR-01 read-phase class — a transport failure never classified a response), ran but never searched and never qualifies the `EMPTY` side alone: a timeout exhaustion aggregates `UNAVAILABLE` (could not search — the PS-13-correct side), never `EMPTY` ("no literature"). **Mode gate (WS-01):** the valid-negative resolution rows above apply **only in `lookup` mode** (identifier hints); a `query`-mode walk is never "answered" by a valid negative — a query-mode `VALID_NEGATIVE` page is a mid-walk anomaly (`SHORTFALL(cause=VALID_NEGATIVE_MID_WALK)`). An **unknown hint prefix** (`xyz:…`) is a `ProviderValidationError` before any I/O — validation, not a search that could not run.
- A **valid negative** (a `doi:`/`pmid:` lookup that resolves to "not found" — Unpaywall `is_oa:false`, arXiv `id_list` with no matching entry, S2/Crossref 404 on an identifier) is *not* an `EMPTY` failure — it is a `VALID_NEGATIVE` result (`valid_negative: true` + `valid_negative_for`) with the identifier recorded, because the query itself was satisfiable and answered "no".

### 4.3 Provider-truthful counting (the `total_is_estimate` rule)

- Crossref `message.total-results` counts **every version record** and is an estimate → **deduplicate by DOI before comparing to `total`**, and record `total_is_estimate: true`.
- OpenAlex `meta.count` is exact → `total_is_estimate: false`.
- Semantic Scholar `total` is exact for the search snapshot → `false`.
- PubMed/EuropePMC counts are exact at query time → `false`; a corpus that changes mid-walk is recorded via the `UNKNOWN`/note path, never silently.
- **The dedup-direction is per-provider spec content, never a driver guess (PS-04).** `counts_raw_rows: true` (Crossref) means `total` counts *every* raw row including repeats → the walk dedups by DOI **before** comparing. `counts_raw_rows: false` (all other providers) means `total` is dedup-truthful → the walk compares **raw retrieved rows** against `total` and must NOT dedup first (deduping first on a provider whose pages legally repeat rows would under-count retrieved and false-fire `SHORTFALL`). The spec declares it; the driver obeys it.
- A provider page may legally repeat a record across pages; the returned `SearchResult` stream is still deduplicated for the consumer (first-seen wins, duplicates recorded in `search_accounting`) — dedup of *delivered records* and the *reconciliation comparison* are two different operations with two different rules.

### 4.4 Pagination discipline (the `paginate.py` discipline, Hermes-owned)

- Cursor-based where offered (OpenAlex, Crossref, EuropePMC `cursorMark`); offset otherwise (PubMed/PMC, arXiv, S2, CORE); single-entity for Unpaywall/bioRxiv/medRxiv.
- Bounds enforced by the Tool Runtime scale classes (S11 `tiny → huge`): `page_size_cap`, `max_pages`, `max_records` per task; exceeding a bound **records** `STOPPED_AT_LIMIT` (a note + `retrieved < max_results` with reason) — this is bounded-by-request, i.e. `COMPLETE`-with-note, never a `SHORTFALL` (§4.1).
- **Cursor-trap loop guard:** a `next_cursor` that repeats an already-seen cursor (or a non-advancing offset) fires `CURSOR_TRAP` → the walk stops, `SHORTFALL(cause=CURSOR_TRAP)`. **Pre-request check (WS-06):** the driver checks the seen cursor-chain BEFORE issuing page N+1 — a repeating cursor stops the walk without the duplicate request. **Cap reconciliation (WS-03):** the driver enforces `min(spec.cursor_rule.loop_guard, request.max_pages)` — hitting the SPEC guard while a live cursor remains is `SHORTFALL(cause=CURSOR_TRAP)` (the spec's guard IS the trap threshold); hitting a REQUEST bound is `STOPPED_AT_LIMIT` (bounded-by-request, `COMPLETE`-with-note).
- Concurrency within a walk is serial (per-provider); polite `delay` between pages from the rate profile.

---

## 5. The HTTP-200 failure catalog

### 5.1 Design: hazards as data, one deterministic evaluator

The catalog is **versioned reference content** (part of the `paper-lookup` SkillRecord — the §30.3 "per-provider failure catalog ships as reference content"), and the *detection* is **one deterministic evaluator** — no per-provider judgment code scattered through the runtime.

```text
ProviderHazardSpec (versioned, per provider, machine-readable) {
  markers: [ { field, equals | pattern, failure_class } ],   # e.g. arXiv entry.title == "Error"
  empty_body_rule:  treat-as-failure | valid-negative,       # search scope; a fetch empty body is
                                                             #   NEVER a valid negative (PS3-02)
  error_field:      { name, code_pattern } | null,           # e.g. EuropePMC errCode
  count_semantics:  exact | estimate | absent,
  cursor_rule:      { kind: cursor | offset | none, loop_guard: max_pages },
  throttle_signature: [ { status: 429, body_pattern } | body_only ],   # e.g. arXiv "Rate exceeded."
  rewrite_suspect:  [ rule… ],                               # silent-filter detection, §5.3
  fetch:            FetchHazardRules | null,                 # PS2-02/PS3-xx — fetch-scoped structure:
      body_marker, metadata_marker, body_required,           #   the PMC front-without-body composite
      empty_body_rule: "treat-as-failure",                   #   (present-but-empty == absent, PS3-02)
      no_full_text_status, no_full_text_marker,              #   europepmc 404 / body signal (PS3-08)
      retraction_marker, required_fields                      #   retraction signal (PS3-03) + drift
                                                             #   sentinel. Registration validates the
                                                             #   fetch rule set per PS3-05 (body_required
                                                             #   needs body_marker; no fetch rules on a
                                                             #   search-only provider; a fetch rule set
                                                             #   that can never fire fails registration).
}

**FD-01 — the fetch content-validation hook (a FIFTH adapter hook):**
`validate_fetch(source, payload) -> None`, raising `FetchContentRejected(reason)` on
non-full-text shapes. The fetch driver calls it on the artifact verdicts (`NONE` /
`INJECTION_SUSPECT`) BEFORE artifact construction; a rejection is a per-source
`FetchFailure(EMPTY_RESULT, reason=…)` — never a `FetchedSource`. Coherence rules:
`body_required: false` + `body_marker: null` (europepmc) is only coherent WITH the hook
(the evaluator's "delegates body semantics to the adapter's parse" has no other
delegate — the shipped adapter hooks are search-shaped); `fetch: null` (arxiv/openalex)
means no declared hazard knowledge, but the hook still runs. A 200 junk body (HTML
error page, `<error>`-rooted wrapper, HTML-when-PDF-promised) is rejected, never
artifact'd as the fetched paper. (FD-01 fold-in, 2026-08-14.)

evaluate_hazards(provider, spec, payload, request_context) -> HazardVerdict {
  class: NONE | MALFORMED_200 | EMPTY_RESULT | PARTIAL_CONTENT | THROTTLED |
         REWRITE_SUSPECT | CURSOR_TRAP | INJECTION_SUSPECT | VALID_NEGATIVE | NO_FULL_TEXT,
  reason, detected_by, recordable: bool
  # PS3-01: the evaluation scope (SEARCH | FETCH) is a driver-set context flag, never
  # payload-inferred. At FETCH scope the step-1 404 → VALID_NEGATIVE mapping is short-circuited
  # by the fetch-scoped no_full_text_status/marker rules; VALID_NEGATIVE is unreachable at
  # fetch scope.
}
```

**Fetch-scope throttle note (FS-07):** step 2's `throttle_signature` matching is **scope-agnostic** — the shipped search-shaped signatures (`errMsg`/`error` fields) are also evaluated on FETCH payloads. No shipped spec is wrong today (JATS/XML fetch payloads carry neither key), but a step-5 adapter whose fetch parse surfaces a same-named field would inherit the search signature and retry-to-exhaustion. **Fetch-side throttles are declared as part of the fetch block** when a provider needs one; the walk/fetch drivers document the handoff (blueprint §5.3).

The catalog **entries** (the per-provider knowledge, from the audited source) are the fixtures for the evaluator — a test corpus, not prose.

### 5.2 Failure classes → tool error taxonomy (§15)

| Hazard class | Semantics | Taxonomy class | Handling |
|---|---|---|---|
| `MALFORMED_200` | HTTP 200 but semantically failed | **permanent** | typed failure, no retry (retrying a malformed response is pointless — the provider will not fix itself) |
| `EMPTY_RESULT` | 200 empty where non-empty expected | permanent | `SHORTFALL`/`EMPTY` path (§4) |
| `PARTIAL_CONTENT` | 200 but content is a degraded form (metadata-only, truncated) | permanent | typed failure at the `fetch` level; never silently treated as full content |
| `THROTTLED` | rate-limited (429 or body-signature) | **transient** | backoff honoring `Retry-After`; jittered exponential; ≤ `max_retries` |
| `REWRITE_SUSPECT` | provider silently rewrote the request (e.g. dropped a filter) | permanent | typed failure with `expected vs got` counts; caller re-issues explicitly |
| `CURSOR_TRAP` | pagination loop | permanent | `SHORTFALL(cause=CURSOR_TRAP)` (§4.4) |
| `INJECTION_SUSPECT` | payload text resembles instructions (advisory heuristic) | — | **flag only** — recorded on the record for review; never blocks valid content (§5.4) |
| `VALID_NEGATIVE` | identifier resolved to a real "no" | — | a result, not a failure (§4.2) |
| `NO_FULL_TEXT` | fetch resolved to "no accessible full text" (europepmc 404) | — | a **result** (`NoFullText`) with structured `no_full_text_kind` (`NOT_OA`/`REMOVED_OR_RETRACTED`/`NOT_FOUND`) — the driver asserts only what the response evidences; a `retraction_marker` hit maps to `REMOVED_OR_RETRACTED`, never `NOT_OA` (PS3-03). Never a `FetchFailure`, never counted against the fetch aggregate (PS2-01); **`VALID_NEGATIVE` is unreachable at fetch scope** — the 404 is short-circuited to `NO_FULL_TEXT` (PS3-01) |

### 5.3 The catalog entries (each becomes ≥ 1 fixture)

- **arXiv:** HTTP 200 with `totalResults == 1` and a single `<entry><title>Error</title>` → `MALFORMED_200` (the audited source: "reads as a successful one-hit search"); plain-text body `Rate exceeded.` → `THROTTLED`; `<id>` is `https://` with a version suffix (e.g. `1706.03762v7`) → normalize (§3.1); title/summary hard-wrapped mid-sentence → normalize, never dropped.
- **PMC:** `efetch` returns a **well-formed `<pmc-articleset>` with `<front>` metadata but no `<body>`** with HTTP 200 for non-OA articles → `PARTIAL_CONTENT` (the audited source calls this "the most dangerous failure in this skill — nothing about the response says it failed"); empty `<pmc-articleset>` / `<PubmedArticleSet/>` → `EMPTY_RESULT`; a 200 with no body content and no matching verdict → `EMPTY_RESULT` via the fetch `empty_body_rule`, never a fall-through to `FetchedSource` (PS3-02); a **present-but-empty `<body/>`** counts as absent for the composite (PS3-02). The check is **fetch-scoped and composite** — metadata present AND body absent (the `FetchHazardRules` structure, never a single field marker, PS2-02). Contrast: **EuropePMC `fullTextXML` returns a clean 404** for non-OA — a `NO_FULL_TEXT` result that is *preferred* (the contract records this provider-level preference in the SkillRecord's database-selection guidance); a source with metadata but no accessible full text is still a citable `Source`, so `NoFullText` is a result, never a `FetchFailure` (PS2-01). **Scope split (PS3-01):** the europepmc 404 is `NO_FULL_TEXT` only at fetch scope; the same 404 as an *identifier search* response is `VALID_NEGATIVE`. At fetch scope it carries `no_full_text_kind: NOT_OA` unless a `retraction_marker` hit maps it to `REMOVED_OR_RETRACTED` (PS3-03).
- **PubMed:** 429 with `{"error": "API rate limit exceeded", "count": "…"}` → `THROTTLED`; HTTP 400 → permanent validation failure; `efetch` with empty `PubmedArticleSet` for a valid PMID (no abstract available) → `VALID_NEGATIVE` at the fetch level (distinguished from a missing ID).
- **EuropePMC:** JSON with `errCode`/`errMsg` fields in a 200 → `MALFORMED_200` (code mapped into `reason`); `fullTextXML` 404 → `NO_FULL_TEXT` at fetch scope (the PS3-01 scope split — `VALID_NEGATIVE` only as an identifier-search response); a `fullTextXML` 200 with a **non-JATS / `<error>`-rooted wrapper body** (no `errCode` child) → `FetchFailure(EMPTY_RESULT)` via the content-validation hook — never a full-text artifact (FD-01, 2026-08-14); the same for **arXiv/OpenAlex (`fetch: null`)** — an HTML page served where the PDF URL was promised → rejected via the hook, never artifact'd.
- **OpenAlex:** malformed `filter` silently ignored → results that do **not** match the requested filter, with `meta.count` inconsistent with the request → `REWRITE_SUSPECT` (detection rule: request declared `filter=X`, response count >> count expected for `X`, or returned records violate `X`); `cursor=*` → `meta.next_cursor` chain, stop on null → natural end.
- **Crossref:** `total-results` estimate + version records → `count_semantics: estimate` (dedup-before-reconcile, §4.3); cursor chain with repeating cursor → `CURSOR_TRAP`; HTTP 400 malformed query → permanent.
- **Semantic Scholar:** 429 `{"message": "Too Many Requests", "code": "429"}` → `THROTTLED`; 404 identifier → `VALID_NEGATIVE`; offset pagination with `total`.
- **CORE:** partial-shard failure messages under load → **transient** (retry after brief wait — the audited source says so explicitly); token-exhausted 429/403 → `THROTTLED`.
- **Unpaywall:** `{"is_oa": false}` → `VALID_NEGATIVE` (the audited source's whole point — it is the *answer*); 404 unknown DOI → `VALID_NEGATIVE`; malformed DOI → permanent validation failure.
- **bioRxiv/medRxiv:** 404 unknown DOI → `VALID_NEGATIVE`; no keyword search surface (the SkillRecord routes keyword preprints through EuropePMC `SRC:"PPR"` — the database-selection guidance, not an adapter capability).

### 5.4 Injection-boundary mechanics (the `INJECTION_SUSPECT` flag is advisory; the structure is the control)

- **Structural control (the real one):** responses are parsed into schema'd `Source` records only; raw payloads go to content-addressed `SourceArtifact`s; **no free-form passthrough field** exists in `SearchResult`/`Source`; external text reaches a judgment context only as schema'd records (v2.1 §21 / §18 rules preserved). The model never sees a provider response string.
- **Heuristic flag (advisory):** the evaluator may flag payload text matching instruction-like markers (e.g., "ignore previous instructions", tool-call syntax) as `INJECTION_SUSPECT` — recorded on the record for Adversary/review attention, **never** a block and never a content decision. The flag is honest about being heuristic; it is a review aid, not a security control.
- **SkillRecord guidance:** the `paper-lookup` skill instructs treating every response as untrusted third-party data (the source's own boundary, adopted verbatim in policy).

---

## 6. Rate-limit policy

### 6.1 Enforcement point

`ProviderRateLimiter` lives in the **Tool Runtime** (not per-task, not in adapters): a per-provider token bucket + per-provider semaphore + global bounded concurrency + FIFO (the waiter queue). The adapter **cannot bypass** it — the limiter is a **separate gate in front of the transport at the driver call site** (RT-07): the driver holds the RAW transport and calls acquire → request → release; `transport.request` appears in exactly one place (the driver) — that single call site is the only-entry-point invariant (PS-03) made structural. The limiter does NOT wrap the transport (no double-limit risk) and no component other than the driver may call it.

- Per-provider `rate_profile { rps, burst, concurrency, daily_cap }` from the adapter card (§3); **validated fail-closed at construction** (RT-09): non-positive `rps`/`burst`/`concurrency`/`daily_cap` → `ValueError` (operator-config validation remains at P7).
- **Policy-exception contract (RT-01/RT2-02/RT3-02/03/RL-01/CAP-01):** `acquire` NEVER raises out of the limiter for a policy condition and NEVER blocks on a hard stop — **`False` is reserved for the daily cap** (a hard stop, **no retry**), and the admission waits are bounded by construction (bucket: ≤ burst-refill; semaphores: short by the per-request release pattern) with a named `ADMISSION_WAIT_BOUND` (default 60s) safety net. **The DECISION and the CAUSE are atomic — `acquire(provider) -> tuple[bool, str]` (`(True, "")` | `(False, "daily_cap_exhausted")` | `(False, "admission_wait_expired")`, one lock):** a caller can never read ANOTHER caller's denial through a separate accessor (RL-01); `last_denial_reason` is diagnostic-only (`""` for non-limiter THROTTLED, so a provider 429 is never mislabeled). **The causes differ in retry semantics (RT3-02):** the daily cap is a no-retry hard stop; the admission-wait expiry is transient contention — the driver backs off and RETRIES the page (the next acquire may succeed). **The daily cap is a hard stop even under queued waiters (CAP-01):** the wait loop re-checks the cap before the grant condition — a queued waiter can never grant after the cap is exhausted; it is removed from the FIFO queue with the no-retry `daily_cap_exhausted` label. The driver maps `False` to the THROTTLED verdict (`SHORTFALL(cause=THROTTLED)`) with the cause note. A raise or unbounded block would break `walk()`'s never-raises invariant / hang the retry loop.
- **Release contract (RT-03/RT2-03):** `release` returns the **semaphore slot only** — a token is never refunded (a refund would hollow the rps/burst bucket under the driver's per-request acquire/release). The return check happens BEFORE the driver's try (`granted, reason = limiter.acquire(...)` — a `False` never reaches `release` — releasing an un-acquired slot underflows the semaphore and admits more than `concurrency`); step 5a's fetch driver maps `False` → `FetchFailure(THROTTLED)` (RT2-05), never an unhandled tuple.
- `Retry-After` headers honored for `THROTTLED`; arXiv's plain-text `Rate exceeded.` body triggers the same path (the throttle signature is in the hazard spec, §5.2). **Backoff division (RT-08):** the bucket backoff shapes FUTURE acquires only (refill at rps) — it never sleeps the current caller; the driver's `_backoff` is the only caller-sleeping backoff (no double-delay).
- A daily cap is a hard stop for that provider for a **fixed UTC window** — midnight per `clock.now_utc`'s date (RT-10) — recorded in the request log + `search_accounting`; the walk reports `SHORTFALL(THROTTLED)` rather than hammering.

### 6.2 Per-provider starting-point defaults (operator-configurable; **validated at P7**)

Recorded values from the audited source (where the source states a published limit, it is the *ceiling*; where none exists, the value is a conservative Hermes default — the honesty-instrument precedent of `C_MIN` (S2) and the payload cap (S6) applies):

| Provider | Published / default ceiling | Hermes starting default |
|---|---|---|
| PubMed | 3 rps no key, 10 rps with key | 3 rps, burst 5, off-peak for batches |
| PMC | same NCBI policy | 3 rps, burst 5 |
| EuropePMC | none published | 3 rps, burst 5 (serial walks) |
| arXiv | none published | 1 rps, burst 3 |
| bioRxiv/medRxiv | none published | 1 rps, burst 3 |
| OpenAlex | 100 rps max; usage-based pricing | 10 rps polite (`mailto`), burst 15 |
| Crossref | 5 rps public / 10 rps polite | 5 rps, concurrency 1 (10 rps / 3 with `mailto`) |
| Semantic Scholar | none stated (429s observed) | 1 rps, burst 3; honor 429 |
| CORE | token-based (100/day, 10/min unauth) | per-key profile from config; daily cap |
| Unpaywall | 100k/day | daily cap 10k (conservative) |

All values are **config, not code**; changing a value is an operator decision recorded in the request log's `provider_spec_version` — never a silent recompute (the §16.2 cache-key discipline applies to rate profiles too: a profile change invalidates nothing, but is version-recorded). **Construction validation (RT-09):** the step-4 limiter rejects non-positive profiles at `__init__` (fail-closed) regardless of the operator-config P7 validation.

### 6.3 Retry taxonomy

| Class | Examples | Policy |
|---|---|---|
| **transient** | 429/`THROTTLED`, 5xx, timeouts, network errors, CORE shard messages | jittered exponential backoff honoring `Retry-After`, ≤ `max_retries` (default 3), then typed failure |
| **permanent** | HTTP 4xx validation, `MALFORMED_200`, `REWRITE_SUSPECT`, `CURSOR_TRAP`, `PARTIAL_CONTENT`, oversized page (size cap, RT-06) | no retry — typed failure immediately |
| **validation** | malformed request (bad identifier, bad hint) | typed failure before any network I/O |

**Transport exception class map (RT-02/RT2-01/RT2-06/RT3-01/TR-01):** `http.py` raises ONLY `ProviderError` subclasses with a named `hazard_class` **for TRANSPORT-LEVEL failures** (`TIMEOUT` → `TransientProviderError`; the streaming size-abort → `PARTIAL_CONTENT`, **only on a 2xx status** — an oversized 429 keeps its THROTTLED verdict) — **never on an HTTP status** (statuses belong to `evaluate_hazards`: raising on 404 would kill the answered-lookup `VALID_NEGATIVE`, raising on 429 would bypass `note_throttled`/Retry-After). **The map covers the BODY-READ phase as well as `urlopen` (TR-01):** a mid-download read timeout / connection reset / `IncompleteRead`, on the success AND the HTTPError paths, maps to `TransientProviderError(TIMEOUT)` — it can never escape bare (which would crash the walk via the catch-all's re-raise); the size-abort `PermanentProviderError` passes through. A bare client-library exception is NEVER propagated, and a NON-`ProviderError` exception from the transport is a bug — `_fetch_page`'s catch-all RE-RAISES it, never a `MALFORMED_200` schema verdict. The completed-body size check and the content-type check live in the evaluator (per-provider allowlist, status + shape + content evidence dominate — a 429/404 with a mismatched content-type keeps its status verdict; the content-type slot is after drift/empty-body and before the fetch composites, RT3-04).

### 6.4 Relation to the budget ledger (AR-02, explicitly scoped)

The `ProviderRateLimiter` enforces **provider policy** (what the endpoint allows). The future budget ledger (AR-02, §28.6 — DEFERRED) enforces **task cost** (what the project allows). They are different authorities: the limiter is not a budget authority, and the ledger will draw its retrieval cost inputs from the request log (per-call cost class), not re-derive provider policy. Until the ledger exists, the limiter's caps are the only enforcement — the IDR29-04 honesty note applies: bounded retrieval is enforced, bounded *autonomy* is not yet (DEFERRED, unchanged).

---

## 7. Redaction contract (§27 item 55 ratification point)

### 7.1 What is redacted

Credential-class parameters wherever they appear — URL query params, **path segments** (a credential in a `/{token}/…` route is masked by the alias scan too, PS3-07), headers (`Authorization`, cookies), and body fields matching the alias set `{api_key, apikey, key, token, access_token, auth, password, secret, signature, …}` (the set is config). **Polite-pool identifiers** (`email`, `tool` for NCBI/OpenAlex/Crossref/Unpaywall) are a distinct class: they are *sent* where required, but **redacted in every log, provenance record, event, and error message**.

### 7.2 Where redaction is applied (and where it is not)

- **At the adapter boundary, by the request recorder** — the single deterministic `redact_url(url, policy)` / `redact_params(params, policy)` applied **before** the request form is logged, stored, or emitted anywhere. Redaction is not a post-hoc scrub of already-written records; it is applied at the only place a request form is created.
- Applied to: request logs, `SearchResult.request_params_redacted`, provenance records, event payloads (the S6 secrets-out validator is defense-in-depth on the write path — a redaction leak would fail it), error messages, and the SkillRecord's own walk notes.
- **Not applied to:** the outbound request itself (the provider needs the credential) — the contract's guarantee is that the credential **never appears in any Hermes record**, not that it never leaves the sandbox. Secrets are injected per-adapter-call (§18 rule, preserved); the outbound request is the adapter's only use.
- A redaction failure is fail-closed: if `redact_params` cannot classify a parameter, it redacts it (default-deny for unknown names) — and records the event so the policy set can be completed. **`RedactionError` names the offending parameter, never its value (PS3-07)** — it is raised while raw credentials are in scope, so its message must never embed a value; and the `from None` exception discipline (transport raises provider errors only, from `None`) holds at **every re-raise hop** — future wrappers and `ExceptionGroup` re-raises must preserve `__suppress_context__`, or the raw URL survives in the chain (PS3-07).

### 7.3 The tests

- A fixture request whose URL carries a real API-key value: the key appears in **zero** logs/provenance/events/errors.
- An `email`/`tool` polite param: sent on the wire, redacted in records.
- An unknown param name: default-deny redaction + a `redaction_policy_gap` note.
- The S6 secrets-out validator passes on every fixture (the write-path gate).

---

## 8. Provenance and reproducibility

- **RequestLogRecord** (per provider walk): provider, endpoint, exact normalized query, redacted params, timestamps, per-page cursor chain (each page's cursor_key + count), reconciliation verdict + counts, `total_is_estimate`, hazard verdicts, `provider_spec_version`, content hashes of raw artifacts. The walk is **re-runnable**: identical (request, provider_spec_version, recorded responses) ⇒ identical `SearchResult` stream (deterministic ordering: provider order then page order then dedup-first-seen).
- **Raw payloads** are content-addressed `SourceArtifact`s; large corpora route to `DatasetManifest` (S12) per the S15 triage — never copied into the store wholesale.
- **Record/replay for tests:** the adapter test corpus is recorded responses (the failure catalog entries double as fixtures, §5.3); all adapter tests run offline in CI. A live network smoke test is **opt-in at P7** (the §24 P7 entry criterion — real literature review on one question) and never part of CI.
- **Provenance continuity (Chain B, §F of the amendment):** `SearchResult` → `Source` (write path) → `LiteratureReview.search_protocol_ref`/`search_accounting` → `ResearchClaim` (span refs) → `Critique`/`ResearchChallenge` — one §14 graph, no second lineage store.

---

## 9. Acceptance tests (the §30.4 Paper Lookup row, concretized)

| # | Fixture | Assertion |
|---|---|---|
| 1 | arXiv 200 "Error" entry (totalResults=1, title "Error") | `MALFORMED_200`, typed failure, no retry, never a one-hit "success" |
| 2 | arXiv `Rate exceeded.` plain-text body | `THROTTLED` → backoff path (fake clock), `max_retries` then typed failure |
| 3 | PMC metadata-only `<pmc-articleset>` (front, no body), HTTP 200 | `PARTIAL_CONTENT` at fetch; never treated as full text |
| 4 | EuropePMC `errCode`/`errMsg` in 200 JSON | `MALFORMED_200` with code in `reason` |
| 5 | Crossref cursor trap (repeating `next-cursor`) | `CURSOR_TRAP` → `SHORTFALL`, loop guard fired |
| 6 | Crossref estimate: total counts version records | dedup-by-DOI before reconcile; `total_is_estimate: true` |
| 7 | OpenAlex silent filter drop | `REWRITE_SUSPECT` with expected-vs-got counts |
| 8 | S2 / PubMed 429 error bodies | `THROTTLED`, `Retry-After` honored |
| 9 | Unpaywall `{"is_oa": false}` and 404 DOI | `VALID_NEGATIVE` — a result, never `EMPTY` failure |
| 10 | Reconciliation shortfall mid-walk (page fails after retries) | `SHORTFALL` + aggregate `PARTIAL`, records still returned flagged |
| 11 | All-providers-empty topic search | `EMPTY` aggregate (searched, found nothing) → `RetrievalShortfallError` (never silent) |
| 20 | All-providers-throttled/unreachable search | `UNAVAILABLE` aggregate → `ProviderUnavailableError` — never labeled `EMPTY`, so "no literature" cannot be concluded from "providers down" (PS-13) |
| 21 | PMC full-text fetch returning metadata-only `<pmc-articleset>` (HTTP 200) | `PARTIAL_CONTENT` at the **fetch** level via `FetchOutcome.failed` — never silently admitted as full text; the task is structurally told 3-of-N fetches failed (PS-01) |
| 22 | Cursor provider, same page_index but different cursor | fingerprint (full request state incl. cursor + page_size) → **miss** → test failure; a stale fixture is never served as fresh (PS-06) |
| 23 | Transport failure (connection/timeout) on a credential-bearing URL | exception message contains only the **redacted** form — zero credential text in the exception (PS-02) |
| 24 | Provider field rename (schema drift) | `required_fields` absent → `MALFORMED_200`, fail closed — never silent empty identifiers/abstracts (PS-08) |
| 25 | Provider whose total counts raw rows vs. one whose total is dedup-truthful | `counts_raw_rows` drives the reconciliation direction — no false `SHORTFALL` either way (PS-04) |
| 26 | EuropePMC `fullTextXML` 404 / an all-citation-only fetch batch | `NoFullText` per source, aggregate `COMPLETE`, never `FAILED` — citable metadata, no full text, is a result (PS2-01) |
| 27 | Zero-delivered matrix: mixed empty-and-down; no-provider-ran; valid-negative-only lookup | `EMPTY` (with causes in notes) / `UNAVAILABLE` (only if no provider ran) / `COMPLETE`-answered-no — never `PARTIAL` (PS2-03) |
| 28 | PMC fetch: `<front>` present + `<body>` absent, HTTP 200 | `PARTIAL_CONTENT` via the **fetch-scoped** `FetchHazardRules` composite check (PS2-02); europepmc 404 → `NO_FULL_TEXT` via the same scope |
| 29 | Same europepmc 404 as a search response vs. a fetch response | **fetch scope** → `NO_FULL_TEXT` (step 1's 404 branch short-circuited, PS3-01); **search scope** → `VALID_NEGATIVE`; `VALID_NEGATIVE` at fetch scope is unreachable — a scope error fails closed, never a silent fall-through (PS3-01) |
| 30 | Fetch 200 with an empty body and no front/body elements; and `<body/>` present-but-empty | `FetchFailure(EMPTY_RESULT)` / `PARTIAL_CONTENT` — a zero-byte "full text" is never admitted as `FetchedSource` (PS3-02) |
| 31 | EuropePMC fetch 404 with and without a retraction marker | `no_full_text_kind`: `NOT_OA` (plain 404) vs `REMOVED_OR_RETRACTED` (marker hit — never `NOT_OA`); `evidence_basis` records status + marker path; `FetchOutcome` carries `fetched_count`/`no_full_text_count` and the aggregate alone is not an evidence signal (PS3-03/PS3-04) |
| 32 | Valid-negative answer mixed with an empty topic search; valid-negative mixed with real results; unknown hint prefix; routeable-to-no-adapter query | `COMPLETE` (answered, causes in notes) in both mixes — never `PARTIAL`/`EMPTY`; unknown prefix → `ProviderValidationError` before I/O; no-routeable-adapter → `UNAVAILABLE`, never "found nothing" (PS3-06) |
| 33 | Transport error re-raised through a future wrapper; `RedactionError` raised while handling a raw key | exception chain carries **zero** credential text, `__cause__` is `None` at every hop, `__suppress_context__` survives; `RedactionError` message names the param, never the value; a path-segment credential is masked (PS3-07) |
| 34 | SOURCE_SEARCH handler (dispatch-threaded `handler(task, fenced, repos)`) runs `walk`+`combine` on a COMPLETE outcome | per-result `source_result` rows persisted (OQ-1), aggregate + notes + redacted request-log facts on the outcome record; every ref resolves (SD-05) |
| 35 | `SHORTFALL` / `EMPTY` / `UNAVAILABLE` search outcomes | recorded typed with the walk's verdict-note convention — never silent, never mislabeled (the `combine()` raises caught as outcomes) |
| 36 | SOURCE_FETCH depending on its SOURCE_SEARCH task | input resolved from the persisted outcome via a **lossless** SearchResult round-trip (OQ-1 pin) — never a hand-authored list |
| 37 | `FetchedPayload` → artifact store + metadata row | `sha256(raw_bytes) == content_hash` == the artifact row (FD-06); dereference-by-`artifact_id` (GC-02) |
| 38 | Crash-retry re-fetch; divergent re-execution | identical bytes → ONE artifact row via the get-by-hash-first branch (SD-04, no IntegrityError); a different output → one-shot refusal, zero new rows (A2-03) |
| 39 | Task-binding violations (wrong template, wrong project, not RUNNING, mismatched refs) | typed errors, zero rows written (V6-P7-A2 discipline) |
| 40 | `daily_cap_exhausted` fetch task | FAILED with the cap cause, **no auto-requeue** (OQ-3 — RETRYING would re-fetch against the exhausted UTC window); re-arm is the planner's/human's after the window |
| 41 | Handler writing through a stale/fabricated fence vs. the dispatched current fence | stale → `LockLostError`, rollback, nothing lands; current → commits (SD-01, ADV-02 applied to the source write) |
| 42 | A requeued SOURCE_SEARCH task (NO_SIGNAL → FAILED → RETRYING → RUNNING) | re-executed by ITS OWN handler, never `_execute_extract` (SD-02 template-generic re-execution) |
| 43 | Crash between the rows+edges commit and the controller's SUCCEEDED transition | RUNNING-with-rows, recovered by the NO_SIGNAL ladder — no double-transition, no wedged task (SD-03 two-transaction shape) |
| 44 | `source_result:<id>` / fetched-artifact refs against the artifacts table | resolve project-scoped, or FAIL the write — never a form-checked pass (SD-05 resolver extension) |
| 12 | Bounded walk stops at `max_records` | `STOPPED_AT_LIMIT` note; `COMPLETE`-with-note, not `SHORTFALL` |
| 13 | Identifier normalization table (DOI/PMID/PMCID/arXiv old+new, version strip) | canonical forms; provenance retains version |
| 14 | Cross-provider dedup (same DOI from 3 providers) | first-seen wins, duplicates recorded in `search_accounting` |
| 15 | Credential-bearing URL redaction | zero credential text in logs/provenance/events/errors; S6 validator passes |
| 16 | Unknown param name | default-deny redaction + `redaction_policy_gap` note |
| 17 | Hostile payload (instruction-like text in abstract) | schema'd records only; no raw passthrough; `INJECTION_SUSPECT` flag recorded, never a block |
| 18 | Replay determinism | identical (request, recorded responses) ⇒ identical `SearchResult` stream |
| 19 | Rate limiter (fake clock) | per-provider budget honored; concurrency caps; daily cap hard-stops with recorded `SHORTFALL` |

---

## 10. Open ratification decisions (before implementation — §27 item 55)

1. **The initial allowlist** — the 11-provider set (§3) plus the web-search row (Serper/Searxng) ratified as the allowlist; extensibility via engineering plane only.
2. **Reconciliation semantics** — the `COMPLETE`/`SHORTFALL`/`UNKNOWN` verdicts and the `PARTIAL`-not-error vs `EMPTY`-typed-failure split (§4), and the `VALID_NEGATIVE` distinction (§4.2) — the exact "never a silent empty result" reading the amendment requires.
3. **Redaction contract** — the alias set, the polite-pool sent-but-redacted class, and default-deny for unknown params (§7).
4. **Rate-limit starting-point defaults** — validated against real literature tasks at P7 (the `C_MIN`/S6 precedent); values are config, not code.
5. **`total_is_estimate` + dedup-before-reconcile** for estimate-counting providers (§4.3).

---

## 11. Relations to other contracts

- **Step-6 orchestration (the task-side write path, folded in 2026-08-14):** `SOURCE_SEARCH`/`SOURCE_FETCH` are ordinary AGENT_TASK templates admitted through `INSERT_TASK` with admission-time spec validation (the V6-P7-E01/E02 precedent — canonical marker + profile + scope + cost_class + provider-allowlist membership + positive bounds, OQ-5); the controller's template-handler registry is the ONE execution surface (dispatch-threaded `handler(task, fenced, repos)`, SD-01) with template-generic recovery re-execution (SD-02); the outcome write is ONE repository method with task binding + identity re-derivation + get-by-hash-first idempotency (SD-04) + the resolver extension (SD-05), TWO transactions (rows + §14 edges, then the controller's SUCCEEDED — SD-03), journaling via the task's own events (zero new events), and NO evidence promotion / gate passage / task creation by the write path. Acceptance rows 34–44.
- **S11 tool-runtime defaults:** bounded downloads (timeouts, size caps, content-type checks) apply verbatim to `fetch`; scale classes `tiny → huge` bound pages/records per task (§4.4).
- **S12/S15:** large retrieval corpora route to `DatasetManifest`/triage, never wholesale store copies.
- **PA4 `side_effect`:** retrieval is `READ_ONLY` — exempt from the outbox; `fetch`/`search` never have external side effects beyond the request itself.
- **AR-02 budget ledger:** the limiter is provider policy; the future ledger is task cost (§6.4) — not the same authority, documented so neither is mistaken for the other.
- **§29.3 `EXTRACT` pipeline:** consumes schema'd `Source` records (this port's output) — the claim extraction stays a separate, already-implemented surface; this contract neither touches it nor is bypassed by it.

*Design-only. No code, no dependencies, no runtime surface, no ratification claim. Implementation begins only after the §27 item 55 ratification and the Part 3 process for the Paper Lookup slice. The implementation blueprint — module layout, adapter skeleton, hazard-spec evaluator, reconciliation walk, rate limiter, and the offline record/replay harness — is designed at `hermes_researchsourceprovider_implementation_design.md`.*
