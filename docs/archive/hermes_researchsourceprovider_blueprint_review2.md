# Adversarial Review — ResearchSourceProvider Blueprint, Second Gate (post-remediation)

**Scope:** second-gate protest-stage attack on the **remediated** `hermes_researchsourceprovider_implementation_design.md` (PS-01…PS-13 folded in) against its own contract and the first-gate's claims. Method: attack the five surfaces the remediation *introduced or rewrote* — the `FetchOutcome` surface, the fetch hazard pipeline, the exception-path redaction, the `counts_raw_rows` rule, and the `UNAVAILABLE` aggregate — for the same bypass/silent-failure classes, plus adjacent text the remediation touched. The first gate's findings were treated as closed only where the text actually closes them; every PS2 finding below is a hole in the *remediated* text, not a re-litigation of PS-01…PS-13.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| PS2-01 | **P1** | FetchOutcome | Fetch-level **valid negatives are unhandled** — a citation-only source (no OA full text; EuropePMC's clean 404, which the contract calls the *preferred* answer) is neither success nor failure, but the designed `FetchFailure`/`FetchOutcome` model reports it as a failure and `FAILED` when all sources are citation-only |
| PS2-02 | **P1** | fetch hazard pipeline | The "evaluate_hazards … with the **same spec**" claim is false for fetch — the `ProviderHazardSpec` is search-shaped (field-path markers, `count_semantics`, `cursor_rule`), and the PMC metadata-only check (front present **and** body absent) is a composite structural rule no single field marker can express |
| PS2-03 | **P1** | UNAVAILABLE aggregate | Adding `UNAVAILABLE` created a hole in the zero-delivered corner: mixed empty-and-down (some providers zero, some throttled) and mixed valid-negative-and-down have **no defined aggregate**, and the fetch/citation-only case is undefined at the task boundary |
| PS2-04 | **P2** | exception-path redaction | The rule is stated but **not structured**: the transport must hold the `RedactionPolicy` (or the driver must re-raise from the redacted form), and Python exception chaining (`__cause__`/`__context__`, tracebacks) must be suppressed — otherwise the raw URL survives the "redacted exception" promise |
| PS2-05 | **P2** | counts_raw_rows | The reconciliation conflates **pre-dedup raw** counts (bound-reached check, `counts_raw_rows:false` comparisons) with **post-dedup delivered** counts (`retrieved_count`, the consumer stream) — a dedup-heavy walk can misclassify a bound-reached `COMPLETE` as `SHORTFALL` |
| PS2-06 | **P2** | FetchOutcome | Fetch driver concurrency/aggregation order is unspecified — "per source, in the task's order" with no serialization rule under limiter concurrency; the §7.2 determinism guarantee does not cover `FetchOutcome` ordering |
| PS2-07 | **P3** | RequestLogRecord | The fetch driver writes a batch of per-source fetches into a **walk-shaped** `RequestLogRecord` (`cursor_chain`, `page_counts`, `reconciliation`) — needs a fetch-shaped log or a documented non-lossy mapping |
| PS2-08 | **P3** | text (remediation-introduced) | §7.3 now lists `test_providers_adapters.py` **twice** (the old row survived the annotation edit), and the "19 acceptance fixtures" count is stale against the contract's now-25 §9 rows |
| PS2-09 | **P3** | hazard spec | The `count_semantics` × `counts_raw_rows` combination matrix is undefined — spec validation should reject incoherent combinations (an "estimate" that is dedup-truthful is just "exact") |

## Detail

**PS2-01 — The fetch driver reports routine "no full text" as failure. (P1)**

The contract's own catalog says the honest answer for a non-OA article is a clean 404 (EuropePMC `fullTextXML`) — *preferred over* NCBI's metadata-only 200 — and that a search result with metadata but no accessible full text is still a citable `Source`. But the remediated fetch design has only two per-source outcomes — `FetchedSource` (artifact produced) or `FetchFailure` (failure_class + reason) — and three aggregates (`COMPLETE`/`PARTIAL`/`FAILED`). A `VALID_NEGATIVE` at fetch therefore lands in `FetchFailure`, and a batch of citation-only sources aggregates to `FAILED`. The task is then structurally forced to either treat a normal literature search as failed or invent its own convention to distinguish "fetch failed" from "no full text available." **Fix: a third per-source outcome, `NoFullText { source, reason }` (a result, never a failure, never counted against the aggregate), and the aggregate rule "all `NoFullText` ⇒ `COMPLETE` with a recorded note."** This is the same class of error PS-13 closed for search — the fetch side needs its own `VALID_NEGATIVE`-as-result semantics.

**PS2-02 — "The same spec" cannot express the PMC hazard. (P1)**

The remediation says `evaluate_hazards` runs "on the fetch payload with the same spec," but the `ProviderHazardSpec` is search-shaped: `markers` are `{field_path, equals | pattern}` predicates, and it carries `count_semantics`, `cursor_rule`, and `rewrite_suspect` — all meaningless for a JATS full-text response. The PMC metadata-only case — the exact hazard the fetch surface was built to catch — is **front present AND body absent**, a composite structural rule over two elements. A single field-path marker cannot express "`<front>` exists but `<body>` does not"; at best a marker could flag "no body," which false-positives on any legitimate metadata-only response and false-negatives the "front present" half. **Fix: a fetch-scoped hazard structure — e.g., `fetch_required`/`fetch_structure` rules in the spec (`body_required: true` for pmc, `404 → NO_FULL_TEXT` for europepmc) evaluated by the same generic evaluator, or a separate `FetchHazardSpec`.** The generic-evaluator discipline survives; the "same spec" claim does not.

**PS2-03 — The aggregate matrix has an undefined zero-delivered corner. (P1)**

Step 7 defines `EMPTY` (all zero), `UNAVAILABLE` (all down), and `PARTIAL` (≥ 1 delivering). The zero-delivered corner with **mixed causes** is undefined: a 6-provider topic search where 3 return zero and 3 are throttled is neither all-zero nor all-down nor delivering — the walk has no aggregate to return, so the driver must invent one. The valid-negative corner is equally undefined: an identifier lookup answered "no" by one provider while the others are down produces a delivered `valid_negative` record — which by the literal rule makes it `PARTIAL` (≥ 1 delivering), mislabeling a fully-answered "no" as a partial search. **Fix: a defined combination matrix for the zero-delivered corner** — e.g., `EMPTY` if any provider searched and none delivered (with the down/negative causes recorded in notes), `UNAVAILABLE` only if *no* provider ran; and valid-negative-delivered searches resolve to `COMPLETE`-answered-no with the down providers recorded, never `PARTIAL`. The matrix belongs in the contract §4.2 (the contract wins).

**PS2-04 — Exception redaction is a rule, not a structure. (P2)**

PS-02's fix states "the transport never embeds a raw URL in an exception message," but nothing says **how the transport gets the redacted form**: the transport must receive the raw `RequestSpec` (it needs the credential to make the call), so unless it holds the `RedactionPolicy` itself — or the driver catches transport exceptions and re-raises from the recorder's redacted form — the guarantee is a code convention, exactly the PS-02 class the first gate rejected. Two structural details are also missing: (a) **exception chaining** — a `raise RedactedError(...) from original` leaves the original (with the raw URL) reachable via `__cause__`/`__context__` and in the traceback; the rule must be `raise … from None` with no original attached; (b) **the S6 backstop doesn't apply here** — S6 validates *records*, not exception paths, so the chain leak reaches task output unguarded. **Fix: the transport is constructed with the `RedactionPolicy` and is the only component that raises provider errors; it raises from `None` with redacted-form messages only.**

**PS2-05 — Raw vs. post-dedup counts are conflated. (P2)**

The reconciliation needs two distinct numbers: **pre-dedup raw retrieved** (drives the bound-reached `COMPLETE` check and the `counts_raw_rows: false` comparison) and **post-dedup delivered** (the consumer stream, `retrieved_count`). The remediated text says the walk "compares against raw retrieved rows" (good) but never names which count the bound check and `SearchResult.retrieved_count` use. A Crossref-style walk that reaches `max_records` on a page full of duplicate version records: raw rows hit the bound, but post-dedup delivered < `max_results` — if the bound check reads the post-dedup count, the walk keeps paginating past its bound or false-fires `SHORTFALL` ("total > retrieved") on a *complete* bounded walk. **Fix: name the two counts (`raw_retrieved` in the reconciliation path; `delivered_count` on the stream), and state that the bound-reached check and `counts_raw_rows:false` comparisons read the raw count.**

**PS2-06 — Fetch outcome ordering is not covered by the determinism guarantee. (P1-gap → P2)**

§5.3 says "per source, in the task's order," and the limiter allows concurrent walks; but nothing states whether `fetch_batch` is serial or concurrent, nor the **re-serialization rule** for `per_source`/`failed` when it is concurrent. The §7.2 determinism guarantee covers the `SearchResult` stream only. A concurrent fetch batch that returns `failed` in completion order breaks "identical input ⇒ identical `FetchOutcome`." **Fix: state that `fetch_batch` is serial (per-source, in input order — consistent with §4.4's serial-walk discipline) or, if concurrent, that aggregation re-serializes to input order; extend the determinism guarantee to `FetchOutcome`.**

**PS2-07 — The request log is walk-shaped. (P3)**

`FetchOutcome.request_log` is a `RequestLogRecord` whose fields are `cursor_chain`, `page_counts`, `reconciliation` — the walk's shape. A batch of per-source fetches (with per-source hazards, sizes, 404s) does not fit without lossy flattening, which would defeat the re-runnable-provenance purpose. **Fix: a fetch-shaped log (`fetch_log: tuple[FetchLogEntry, …]` with per-source status/hazard/size/hash) or an explicit mapping into the existing record that preserves per-source facts.**

**PS2-08 — The remediation left text bugs in the table it edited. (P3)**

§7.3 now contains `test_providers_adapters.py` **twice** — the annotated row (PS-01/02/06/08) and the original un-annotated row both survived the remediation edit — and the fixture-count line still says "19 acceptance fixtures from contract §9," while the contract now carries 25 rows (§9 rows 20–25 added by the remediation). Both are trivial but they are *remediation-introduced* inconsistencies in the exact document Part 3 will consume.

**PS2-09 — The `counts_raw_rows` × `count_semantics` matrix is undefined. (P3)**

`count_semantics ∈ {exact, estimate, absent}` and `counts_raw_rows ∈ {true, false}` are orthogonal as declared, but not all combinations are coherent — an "estimate" that is dedup-truthful is indistinguishable from "exact"; "absent" makes `counts_raw_rows` moot. The spec-loading validation (fail-closed at registration) should reject the incoherent combinations (e.g., `estimate` requires `counts_raw_rows: true`) so a spec author cannot ship a contradiction the driver will then interpret.

## Interaction with prior findings

| Prior | Interaction |
|---|---|
| PS-01 (fetch surface) | **Opened, not closed.** The fetch surface now exists but carries its own P1s: PS2-01 (no-full-text semantics), PS2-02 (spec shape), PS2-06 (order), PS2-07 (log shape) |
| PS-02 (exception path) | **Rule landed, structure missing.** PS2-04 is the enforcement-point + chaining completion |
| PS-04 (counts_raw_rows) | **Refined, not closed.** PS2-05 names the raw-vs-delivered counts the rule needs; PS2-09 bounds the field's combinations |
| PS-13 (UNAVAILABLE) | **Closed for the all-down case, opened the matrix.** PS2-03 is the zero-delivered corner the new value created |
| PS-06 (fingerprint) | Unaffected — the fingerprint fix survives intact |
| PS-03/05/07/08/09/10/11/12 | Unaffected — no interaction found in the second pass |

## What survives

The first gate's remediations that are *structural* hold: the only-entry-point invariant (PS-03), the fixed allowlist fan-out order (PS-05), the full-request-state fingerprint (PS-06), the skip-and-count row policy (PS-07), the `required_fields` drift sentinel (PS-08), `redact_headers` (PS-09), the mandatory fixture assertions + review gate (PS-10), `valid_negative` fields (PS-11), and the parse contract restatement (PS-12). The generic-evaluator discipline, the driver-owns-control separation, and the read-only-by-construction claim all survive. The second gate's findings are the *new* surface's own gaps plus enforcement-point completions — no redesign, no new components, every fix lands in the same modules.

## Overall verdict: **MERGE WITH REMEDIATION (second round).**

The first gate's P1s are genuinely closed — the remediation was not superficial. But the fetch surface the remediation created has its own P1-class holes: routine "no full text" is reported as failure (PS2-01), the "same spec" fetch hazard evaluation cannot express the exact PMC check it was built for (PS2-02), and the `UNAVAILABLE` addition left the zero-delivered corner of the aggregate matrix undefined (PS2-03). The exception rule needs structure + chain suppression (PS2-04), and the counts and ordering semantics need naming (PS2-05/06). All nine map to concrete design-text changes in the same blueprint/contract modules; the contract wins for PS2-01/03. A third gate — or acceptance of the remediated-remediated text with the PS2 dispositions folded in — is the standing condition before §27 item 55 ratification and Part 3.

---

## Remediation disposition (second round — all nine closed in the design text)

| ID | Fix | Where it landed |
|---|---|---|
| PS2-01 | `NoFullText` outcome (a result, never a failure); fetch aggregate counts it as `COMPLETE`; all-citation-only batch never `FAILED`; `NO_FULL_TEXT` verdict class | blueprint §2.1, §4.2 step 6a, §5.3, §7.3; contract §5.2, §5.3, §9 row 26 |
| PS2-02 | `FetchHazardRules` (body/metadata markers, `body_required` composite, `no_full_text_status`) in the hazard spec; fetch-scoped evaluation step; the "same spec" claim replaced | blueprint §4.1, §4.2 step 6a; contract §5.3, §9 row 28 |
| PS2-03 | The zero-delivered matrix: `UNAVAILABLE` only if no provider ran; mixed empty-and-down → `EMPTY` with causes in notes; valid-negative-only → `COMPLETE`, never `PARTIAL` | blueprint §5.1 step 7, §7.3; contract §4.2, §9 row 27 |
| PS2-04 | Transport constructed with the `RedactionPolicy` and is the only exception raiser; `from None`, no original attached; traceback carries only redacted forms | blueprint §6.2; test row |
| PS2-05 | `raw_retrieved_count` (reconciliation: bound-reached check + comparison) vs `delivered_count` (consumer stream); reconciliation never reads the post-dedup count | blueprint §2.1, §5.1 step 6, §7.3 |
| PS2-06 | `fetch_batch` serial in the task's input order; determinism guarantee extended to `FetchOutcome` | blueprint §5.3, §7.2, §7.3 |
| PS2-07 | `FetchLogEntry` (per-source, fetch-shaped) replacing the walk-shaped `RequestLogRecord` on `FetchOutcome`; handoff persists it into `Source` provenance | blueprint §2.1, §5.3, §8 |
| PS2-08 | Duplicate `test_providers_adapters.py` row removed; fixture-count target updated to the contract's 28 acceptance rows | blueprint §7.3 |
| PS2-09 | Spec-loading validation rejects incoherent `count_semantics` × `counts_raw_rows` combinations (`estimate` ⇒ `counts_raw_rows: true`; `absent` ⇒ `false`) | blueprint §4.1 |

**Status:** all nine remediated in the design text (blueprint + contract, where the contract wins). No code exists. The blueprint's §9 step 7 gate now records both reviews as folded in; a third-gate review against this text — or acceptance with the dispositions verified — is the remaining condition before §27 item 55 ratification and Part 3.
