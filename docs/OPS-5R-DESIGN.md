# OPS-5R — design gate: a verdict may not be more optimistic than the work

| Item | Value |
| --- | --- |
| Slice | OPS-5R, phase 1 (design gate) |
| Base | `main` at `bfd37ef` |
| Branch | `slice/ops-5r-evidence-integrity` |
| Date | 2026-10-27 |
| Status | **PROPOSED — awaiting the Director's approval. No code on this branch.** |
| Census at base | 124 / 28 (19/5/4) / 1 / 15 / 0 — `scripts/check_census.py` PASS on this tree |

The question is: **what must a walk record so that "complete" cannot mean
"delivered nothing"?** The answer is one sentence, and everything below exists to
make it defensible:

> A walk may record `COMPLETE` only when it holds an **exhaustion witness** — a
> short page, a reached total, or a provider's explicit end token — and a fixture
> id must be a commitment to **the request as sent**, not to the redacted form of it.

Stated as an invariant that covers all three defects:

> **A record may never be more optimistic than the aggregate it feeds.**

Today `request_log.reconciliation` can say `COMPLETE` while the same persisted
outcome says `aggregate=EMPTY`; it can say `COMPLETE` over 25 rows of a 500-row
result set. Those are the same violation, and this slice removes the class.

---

## 1. The three defects, checked against the tree

### 1.1 G1 is three independent stops, not one

The charter names `next_state=None` (`base_adapter.py:240,246,250`). That is real,
but it is not sufficient: an adapter that *did* advance would still stop after one
page, twice over.

**(a) `next_state` is `None` on all three exits.** `parse_page` never returns a
position, so `walk`'s `page.next_state is not None` branch (`paginate.py:349`) is
dead and every walk ends at the "exhausted" reconciliation.

**(b) The loop bound is the page size.** `walk` loops `while raw_retrieved <
request.max_results` (`paginate.py:247`) and derives `page_size =
min(request.page_size_cap, request.max_results)` (`:223`). The handler sets
`max_results = spec["page_size"]` (`source_handlers.py:479`). So `max_results ==
page_size` by construction, and a full first page satisfies the bound. A probe with
a *correct* adapter (advances offset, honours `retstart`) proves the stop is
independent of (a):

```
max_results= 20 max_pages=20: calls=1
max_results= 40 max_pages=20: calls=2
max_results=400 max_pages=20: calls=5
```

(The probe serves the same 20 rows on every page, so the delivered count stays 20
— the number that moves is `calls`.)

The task's declared envelope is `page_size × max_pages` (20 × 20 = 400 by
default, `source_templates.py:72-73`). The walk treats it as 20.

**(c) The position parameter is hardcoded, and it is the wrong name.** `build_request`
writes `params["cursor"]` and `params["offset"]` (`base_adapter.py:174-179`) and
never reads `start_param`. PubMed's offset parameter is `retstart`; page 2 of a
PubMed walk would send `offset=5` — which eutils ignores. Measured:

```
page 1 params: {'term': '<redacted>', 'retmax': '<redacted>', 'db': …, 'retmode': …}
page 2 params: {… , 'offset': '<redacted>'}          # retstart never appears
```

EuropePMC's declared `start_param` is `cursorMark`; it would receive `cursor`.

**(d) The contract card's bounds are unread.** `walk` reads exactly one key of
`contract.pagination` — `kind` (`paginate.py:219-222`). `start_param`,
`page_size_cap`, `max_pages` and `loop_guard` are never consulted; the live bounds
come from the hazard spec's `loop_guard` and the request. Measured over the 15
shipped adapters: **14 declare `max_pages: 50`, the fifteenth (`unpaywall`)
declares 1 — none is read.** Brave declares `page_size_cap: 20` and can be asked
for 50, because the driver's cap is policy (100, `SourcePolicy.page_size_cap`) and
a task may declare up to `SOURCE_PAGE_SIZE_CAP = 100` (`source_templates.py:66`) —
not the provider's cap. And
`pages_done >= spec_guard → CURSOR_TRAP` (`paginate.py:397`) is unreachable: every
shipped `loop_guard` is 100 and `max_pages` is capped at 50
(`SourcePolicy.max_pages_cap`), so the branch cannot fire.

**(e) Totals outside the three recognised paths.** `_items_from_json` reads
`total`, `meta.total`, `message.total-results` (`base_adapter.py:186-198`). The
shipped corpus shows two totals it cannot see:

| body | field | reader sees |
| --- | --- | --- |
| `tests/fixtures/p_auto_3_live/openalex.json` | `meta.count = 383439` | `total=None` |
| `tests/fixtures/p_auto_3_live/pubmed.json` | `esearchresult.count = "71367"` | `total=None` (only PubMed's override reads it) |

and the XML branch returns `total=None` unconditionally (`:246`), so arXiv's
`opensearch:totalResults` is structurally invisible.

**The evidence, four walks on this tree:**

| walk | delivered | aggregate | `request_log.reconciliation` | requests |
| --- | --- | --- | --- | --- |
| EuropePMC, `hitCount=500`, 25 rows, `max_results=50` | 25 | `COMPLETE` | `COMPLETE(total_not_reported(exhausted))` | 1 |
| OpenAlex shipped body, `meta.count=383439`, 5 rows, `max_results=5` | 5 | `PARTIAL` | `UNKNOWN(total_not_reported(bounded))` | 1 |
| PubMed, `count=71367`, 5 rows, `max_results=50` | 5 | `PARTIAL` | `SHORTFALL(cause=TOTAL_EXCEEDS_RETRIEVED)` | 1 |
| Brave, 10 url-only rows, `max_results=50` | 0 | `EMPTY` | `COMPLETE(total_not_reported(exhausted))` | 1 |

The first row is the charter's defect in its purest form: **a 500-result set,
one page, a `COMPLETE` verdict and a `COMPLETE` aggregate.** The second shows the
total being discarded even though it is in the bytes.

**Correction to the charter, for the record:** it is 14 of 15 adapters that
declare `max_pages: 50`, not 13 — and the count is beside the point, because none
of them is read. More materially, "pagination never advances" has three causes,
so a slice that only sets `next_state` would still stop after page 1 and would
still send the wrong parameter on page 2.

### 1.2 G2 — every web row is dropped, and the record says `COMPLETE`

The mechanism is one line of `extract_ids` (`base_adapter.py:252-263`): it iterates
`_ID_KINDS` and passes `url` through `normalize_identifier("url", …)`, which is not
a URL normalizer — it is a **resolver extractor** (`normalize.py:123-135`) that
returns `None` for any host other than `doi.org`/`dx.doi.org`/`arxiv.org`. A web
result's URL therefore yields no identifier, `ids` is empty, and the record takes
the `MALFORMED_ROW` path (`paginate.py:331-333`) before the delivery branch at
`:335-341` can be reached.

Measured on a Brave-shaped payload (`id_fields = ("url", "id")`):

```
10 rows, all url-only,        max_results=50: delivered=0  aggregate=EMPTY  verdict=COMPLETE
10 rows, all url-only,        max_results=10: delivered=0  aggregate=EMPTY  verdict=UNKNOWN(bounded)
10 rows, 3 carrying a doi,    max_results=50: delivered=0  aggregate=EMPTY  verdict=COMPLETE
                                                10 × MALFORMED_ROW(page=0): no identifiers
```

The third line is wider than the charter states: **a web row that carries a DOI is
dropped too**, because `id_fields` never copies `doi` into the record, so
`extract_ids` has nothing to canonicalize. The four web legs (`brave`, `exa`,
`tavily`, `searxng`) declare `id_fields` of `("url", "id")` / `("id", "url")`, and
`"id"` is not in `_ID_KINDS` at all.

The delivery branch is not dead — it is reachable for records whose identifiers are
non-empty but carry no dedup kind: provider-native ids (`openalex_id`, `core_id`)
and resolver URLs, whose value is a DOI/arXiv id stored under the `url` kind
(arXiv yields `{"url": "2103.10001"}`). The branch's comment says "e.g. url-only",
which is precisely the case that cannot reach it.

**What the aggregate does, and what the record does.** `_single_provider_aggregate`
(`paginate.py:547-561`) returns `EMPTY` for zero delivery; `combine` raises
`RetrievalShortfallError`; `_run_search` catches it and returns `failed_typed`
(`source_handlers.py:516-533`). **The task is refused.** The falsehood is in the
record: `_search_outcome_metadata` persists `aggregate` and
`request_log.reconciliation` side by side in one row (`source_outcomes.py:1085-1112`),
so the journal carries `aggregate="EMPTY"` beside `reconciliation="COMPLETE"`.

**Correction to the charter, for the record:** "the journal then treats it as a
successful acquisition" is too strong at the task boundary — `EMPTY` already
refuses the run. The defect is that the *walk's own record* contradicts the
aggregate that refused it, which is worse than a noiseless zero in one respect: it
is a zero that is noiseless in the field every coverage reader consults, and loud
only in the field the task gate happens to read.

The test that would have caught it asserts the hazard verdict and stops one
assertion short of delivery: `test_walk_golden_returns_none`
(`test_provider_breadth.py:217-226`) checks `hazard_verdicts == ("NONE",)` and
never `len(outcome.per_provider) == 1`.

### 1.3 G3 — the id is a function of the redaction, and the collapse is wider than queries

The chain is short: `redact_params` scrubs every unclassified name to
`"<redacted>"` under `default_deny` (`redact.py:84-97`); `normalized_request`
builds the preimage from that form (`replay.py:82-114`); `fixture_id_of` hashes it
(`:122-135`). Measured:

```
"crispr"          → fx_23d30ca8521cc4822e0c1aac
"malaria vaccine" → fx_23d30ca8521cc4822e0c1aac      # one id, two searches
retmax=5          → fx_23d30ca8521cc4822e0c1aac
retmax=10         → fx_23d30ca8521cc4822e0c1aac      # one id, two page sizes
```

The first id is the id in the shipped corpus. The second pair is not in the
charter and matters more than the query collapse: **a 5-row recording can answer a
10-row request**, and replay has no way to notice — it serves the recorded bytes
for a request that asked for something else.

Page 2 does get a distinct id, but only by accident: the driver adds an `offset`
key, so the *key set* differs even though every value is `<redacted>`. Identity is
being carried by the presence of a parameter name, not by the request.

The POST side already has the escape and the rationale: `_KNOWN_BODY_FIELDS`
(`redact.py:110-120`) keeps `query`/`numResults`/`max_results` values verbatim so
two searches differing only in a value stay distinct, and justifies it as "parity
with the GET legs" — because `RequestLogRecord.query` already records the search
text. The GET side never got the same treatment.

### 1.4 The shape, stated once

Each defect is the same trade made in a different place: **the record describes
the code path, not the evidence.**

- the verdict describes `next_state is None`, not "the result set ended";
- the verdict describes "the loop finished", not "rows were delivered";
- the fixture id describes the redacted form, not the request.

The fixes are therefore not three patches but three refusals: refuse `COMPLETE`
without a witness; refuse any verdict more optimistic than the aggregate; refuse
an identity that is a function of the presentation.

---

## 2. The answers

### 2.1 Cursor advancement, and what stops the walk honestly

**The card becomes the contract the driver and the base adapter read.** The five
declared keys already exist; between them the driver and `JsonSearchAdapter` read
one. The change is to read all of them, each where it belongs: the driver owns the
**bounds**, the adapter owns the **wire form**.

| declaration | today | design |
| --- | --- | --- |
| `kind` | read by the driver (`paginate.py:219`) | read by the driver |
| `start_param` | ignored | read by `build_request` as the position parameter name (`retstart`, `cursorMark`, `pageno`, `offset`, `start`) |
| `page_size_cap` | ignored | read by the driver; bounds the request **and** the witness: `effective_page_size = min(request.page_size_cap, card.page_size_cap, request.page_size)` |
| `max_pages` | ignored | read by the driver: `min(spec.loop_guard, card.loop_guard, card.max_pages, request.max_pages)` |
| `loop_guard` | read from the *hazard spec* only; the card's copy is ignored | both read, stricter wins — the last dead key on the card becomes live |

`page_size_cap` is load-bearing for the witness, not just for politeness: Brave
declares 20, and a task may ask for 50. Ask Brave for 50, receive its 20, and a
naive "short page" test calls the walk exhausted. The witness must be measured
against the size the provider agreed to.

**A page budget and a result budget are different numbers.** `WalkRequest` gains
`page_size` (default `None` → today's derivation). The handler passes the task's
`page_size` as the page size and `page_size × max_pages` as `max_results` — the
envelope the task already declared. No admission change, no new spec field: the
envelope was always implied by the two bounds the task carries.

**What advances `next_state`, per kind:**

| kind | advance | natural end |
| --- | --- | --- |
| `offset` | `offset += len(rows)` while `len(rows) == effective_page_size` and (`total` unknown or `offset + len < total`) | short page, or total reached |
| `page` | `page_index += 1` while `len(rows) == effective_page_size` | short page |
| `cursor` | `cursor = ` the declared next-cursor field | the provider omits or repeats its token |
| `none` | never | the single page returns |

Cursor walks need a **seed** on page 1 (`cursor=*` for OpenAlex, `cursorMark=*` for
EuropePMC). Today `build_request` only adds a cursor when one is already set, so a
cursor walk can never start. Declared as `cursor_seed`, sent on page 1 only.

**Two card corrections the driver cannot make for itself** (the declaration is
wrong, not the mechanism), plus one type widening:

- `europepmc` declares `kind: "offset"` with `start_param: "cursorMark"`. It is a
  cursor API (`nextCursorMark`, `hitCount`); declared `offset`, a correct driver
  would advance an integer and send it as `cursorMark`.
- `searxng` is a page-number API (`pageno`), not an offset API. Its position is
  `page_index + 1`, not a row count — so `PaginationKind` gains `"page"`. That is a
  type alias widening in `base.py:54`, not an event-kind change.

**The honest stop.** At natural exhaustion — not a failure, a trap, or a bound —
the walk must hold one of three witnesses:

- **W1 — a short page:** `len(rows) < effective_page_size`.
- **W2 — a reached total:** `total` is not `None`, `count_semantics != "estimate"`,
  and `effective_retrieved >= total`.
- **W3 — an explicit end token:** a `cursor` provider returned no next cursor. This
  is evidence, not inference: the token is not derivable from the position, so its
  absence is the provider saying "last page". An offset API's next position *is*
  derivable, which is why "no next offset" is not a witness there.

With no witness, the walk records `SHORTFALL(cause=UNKNOWN_DEPTH)` and retains what
it delivered (`PARTIAL` at the aggregate). If it delivered nothing, §2.2 applies
first. A page after the first that adds **no new identifier** is
`SHORTFALL(cause=PAGINATION_STALLED)` — the provider answered, the position moved,
the result set did not.

Two edges the witness rule must state, because pagination makes them reachable:

- **A `none` provider that fills its page** is `UNKNOWN(total_not_reported(single_page))`,
  not a shortfall: the provider's contract is one page, so the walk stopped at a
  declared bound and cannot say more. That is what `UNKNOWN` is for.
- **An empty page after a full page** is an end witness for `offset`/`page` walks —
  the client probes past the end, and an exact-multiple result set (20 of 20) ends
  that way. It stays `SHORTFALL(cause=EMPTY_MID_WALK)` for `cursor` walks, where the
  server owns the position and an empty page with a live cursor is a provider
  anomaly. WS-02's rule is right for the cursor case; it never had to distinguish
  the two, because no walk advanced far enough to reach an offset end.

**The verdict vocabulary already has what is needed.** `ReconciliationVerdict` is
`Literal["COMPLETE", "SHORTFALL", "UNKNOWN"]` (`research_sources.py:72`) — no
`PARTIAL`. `SearchAggregate` is `Literal["COMPLETE", "PARTIAL", "EMPTY",
"UNAVAILABLE"]` (`:75`) and already has `PARTIAL`, which `combine` derives from a
delivered set plus a `SHORTFALL(`/`UNKNOWN(` note. So the honest per-walk value for
"delivered some, more exists, cannot see it" is **`SHORTFALL(cause=…)`**, and the
aggregate already spells it `PARTIAL`. Adding `PARTIAL` to the walk vocabulary
would be a second spelling of one fact, would break `combine`'s prefix scan
(WK3-02 keys on the two prefixes), and would touch every consumer of
`SearchResult.reconciliation`. **No new verdict; no new event kind.**

### 2.2 The zero-row case

**Rule: `len(delivered) == 0` ⇒ never `COMPLETE`, never `UNKNOWN`.** The walk
records `SHORTFALL(cause=ZERO_DELIVERED)` plus one sub-cause note:

| sub-cause | when |
| --- | --- |
| `total_zero` | the provider declared an empty result set |
| `total_positive` | the provider declared rows it did not deliver (absorbs today's `ZERO_DELIVERED_TOTAL_POSITIVE`) |
| `unknown_depth` | no total, no witness, nothing delivered |
| `all_rows_unidentified` | rows arrived and every one failed identifier extraction |

It is placed **before** the bound branches, the same way WK-04's (d) rule dominates
`reached_max_results`/`hit_page_bound`: a zero delivery outranks "we stopped at a
bound", because a bound explains why we stopped, not why nothing arrived. It sits
**after** the never-searched branch: a walk whose every attempt was
throttle/transient exhaustion delivered nothing because it never ran, and that is
`UNAVAILABLE`, not a zero result. The order is therefore: never searched →
`SHORTFALL(cause=NEVER_SEARCHED)`; zero delivered → `SHORTFALL(cause=ZERO_DELIVERED)`;
bounds; exhaustion witnesses.

**Is it a refusal, a verdict, or a failure?** All three, at three layers, and the
layers already exist:

- the **verdict** is a distinct value in the existing vocabulary (`SHORTFALL`) with
  a named cause — no new kind;
- the **aggregate** is `EMPTY`, which `combine` already raises on;
- the **run** is refused: `_run_search` records the outcome and returns
  `failed_typed`. **The run may not proceed on it, and today it already does not.**

What changes is that the record stops contradicting the refusal. The cost is
explicit: `test_first_page_empty_is_exhausted_complete`
(`test_provider_walk.py:324-331`) currently asserts `COMPLETE(retrieved==total)`
for a `total=0` page while asserting `aggregate == "EMPTY"` three lines later. That
test encodes the contradiction this slice removes; its verdict assertion changes,
its aggregate and raise assertions do not.

`total_zero` is the honest edge: nothing existed, so "shortfall" overstates the
failure. It is still not `COMPLETE`, because in this system `COMPLETE` is read as
an acquisition verdict by the surfaces that read the log — the outcome metadata,
the audit surface, any coverage report — and a walk that acquired nothing cannot
carry the word. The sub-cause carries the distinction the verdict cannot.

### 2.3 Fixture identity

**Two forms, one request.**

| form | function | content | where it goes |
| --- | --- | --- | --- |
| presentation | `normalized_request` (unchanged) | every value `<redacted>` / `<redacted:name>` | journal, `RequestLogRecord.request_params_redacted`, interactions table |
| identity | `request_identity` (new) | name kept; value → `sha256:<hex>` for declared fields, the constant token otherwise | the fixture file (replacing `normalized_request` there), and the `fixture_id_of` preimage |

`fixture_id_of` hashes the identity form. Two requests differing in any **declared**
value get two ids; two requests differing only in a credential get one id — the
credential is deliberately not part of the request's meaning, and the same query
under a rotated key must still replay.

**The theorem, in the direction that matters:** equal id ⇒ equal `(url, method,
every declared value)`; a different declared value ⇒ a different id. The id
*commits* to the values without storing them — that is what a commitment is, and
it is the only form that satisfies both "values included" and "no value in the
file".

**Which names are "declared"** is not a hand-written whitelist; it is the adapter's
own wire vocabulary, already in the class:

```
query_param, page_size_param, page_param, the position parameter (start_param),
cursor_seed, and every key of extra_params
```

A parametrized contract test asserts that `build_request` emits nothing outside
that set. That closes the failure mode a whitelist has: a new provider parameter
cannot silently fall back to the constant, because the test fails before the
behaviour ships.

**How this squares with default-deny.** They govern different things and neither
moves:

- **default-deny governs what may be stored.** It is unchanged: an unclassified
  name still scrubs to `"<redacted>"` in the presentation form and still never
  reaches a durable store.
- **identity governs what may be compared.** A digest is a comparison, not a
  disclosure: it is one-way; the search text it commits is already recorded in
  plaintext (`RequestLogRecord.query`); the remaining declared fields are structural
  (page size, page number, format selectors); and it is computed only for names the
  adapter declares load-bearing.
- **No credential is ever digested.** A credential-class or polite name takes the
  constant token *before* the digest step, so a credential never enters the
  preimage even as a hash. That is the line the two rules must not cross, and this
  is where it is drawn.

**Why not the alternatives:**

- *Raw values in the fixture file* — violates §3.2 outright.
- *A name whitelist with plaintext values* (the POST precedent) — stores values,
  and degrades silently when a provider adds a parameter.
- *A keyed digest* — needs key material, which §3.5 forbids.
- *No identity form stored* — the id stops being recomputable from the file, so
  `interaction_to_fixture` could no longer recompute it and a fixture would become
  an unverifiable label.

**Schema.** The fixture file gains a `fixture_schema: 2` marker and stores
`identity_request` in place of `normalized_request`; a file without the marker is
refused `FIXTURE_INCOMPATIBLE` before any bytes are served, the same fail-closed
discipline `load_hazard_spec` applies to `schema` (`hazards.py:693-696`). No
migration: `request_json` is one JSON column (`migrations.py:1120`), so the
interactions table keeps the presentation form and needs no DDL.

### 2.4 What the shipped corpus becomes

**It cannot stay as it is.** Its ids were computed over the redacted form, and the
values that produced them are gone, so the new id is not recomputable from the
file. Under the schema marker, the two files would be refused loudly
(`FIXTURE_INCOMPATIBLE`), not silently served under a stale identity.

**Answer: re-stamp now, re-record when the corpus is next touched.**

- *Re-stamp* is an offline, deterministic migration: for each of the six entries,
  issue the request the recording script issues, compute the identity form from it,
  and rewrite `fixture_id` + `identity_request`. Bodies are untouched, no network is
  needed, and the diff is reviewable line by line. It is legitimate because the
  recording script is the record of which request produced which body — it is the
  same code path that recorded them.
- *Re-record* is the stronger option and is preferred whenever the environment has
  network at gate time: PubMed eutils and OpenAlex are keyless, and the record path
  already exists (`RecordedTransport` record mode, `live_fetch`-marked tests).
- *Rejected: a dual-scheme fallback* (serve legacy ids when the new lookup misses).
  It would keep the exact collapse alive for the only corpus that evidences the
  live-fetch claim, and would make the charter's fourth falsifier untestable
  against the shipped data.

**What happens to replay of existing recordings:** it fails loudly, before any
bytes are served — `FIXTURE_MISSING` for an old file loaded without the marker,
`FIXTURE_INCOMPATIBLE` for one whose marker is absent or whose parser version
mismatches. There is no path where a stale fixture answers a new request.

**Residual risk of a re-stamp, stated:** it asserts "this body answers this
request", which the migration can only inherit from the recording script, not
prove. It is bounded by three things: the bodies are unchanged, the diff shows both
the old and new identity, and the hermetic replay tests must still deliver the same
identifier set afterwards. If any of those fails, the answer is re-record, not
patch the test.

---

## 3. What must not change — and why it will not

1. **No new event kind, no new write path, no new transaction.** The new observable
   tokens are **causes**, not kinds — `UNKNOWN_DEPTH`, `ZERO_DELIVERED`,
   `PAGINATION_STALLED` ride the existing `SHORTFALL(cause=…)` note convention,
   which is already an open set (`MALFORMED_ROW`, `CURSOR_TRAP`, `EMPTY_MID_WALK`,
   `TOTAL_EXCEEDS_RETRIEVED`, …). Census re-verified on this tree today:
   `scripts/check_census.py` → 124 / 28 (19/5/4) / 1 / 15 / 0 — **PASS**.
2. **Default-deny redaction stays.** The presentation form is unchanged; the
   fixture stores a value-free commitment; no credential is digested (§2.3).
3. **The gateway's checks, the substrate's rules, the capability grants** —
   untouched. The diff is confined to `tools/providers/*`, one handler's
   `WalkRequest` construction, and tests.
4. **Drain-only byte-identical / B4 24 / LOOP baseline.** No event payload, no
   trace detail, no prompt byte moves: the change is inside the provider plane and
   its notes. `test_loop_baseline` and `test_b4_ref_graphs` do not touch the
   provider machinery (verified: neither imports `hermes.tools.providers` or
   constructs a walk).
5. **No key material.** The identity digest is unkeyed SHA-256 over request values;
   no salt, no key, no secret. A keyed digest was rejected for exactly this reason.

---

## 4. Falsifiers → the tests that carry them

| Falsifier | Test (`tests/test_ops5r_evidence_integrity.py` unless named) |
| --- | --- |
| A paginated walk over a multi-page provider advances and records every page | `test_a_multi_page_walk_advances_and_records_every_page` — 3 pages, 3 requests, `cursor_chain`/`page_counts` length 3 |
| A walk that cannot see past page 1 records an honest verdict — not `COMPLETE` | `test_a_full_page_without_a_witness_is_not_complete` (offset, no total, no advance → `SHORTFALL(cause=UNKNOWN_DEPTH)`), `test_a_stalled_position_is_a_shortfall` |
| A zero-row walk does not record `COMPLETE`, and the run does not treat it as an acquisition | `test_zero_delivered_is_never_complete` (four sub-causes), `test_zero_delivered_refuses_at_the_run_boundary` |
| Two different GET queries produce two different fixture ids; a replay of each serves its own recording | `test_two_queries_two_ids`, `test_each_recording_replays_only_its_own_request` |
| A page-size difference is a different request | `test_page_size_moves_the_fixture_id` (today's `retmax` collapse) |
| The fixture file still contains no un-redacted secret | `test_fixture_carries_no_value_and_no_credential_digest`, `test_credentials_are_never_digested` |
| Every param a shipped adapter sends is declared (the closed wire vocabulary) | `test_every_adapter_sends_only_declared_params` (parametrized over `PROVIDER_REGISTRY`) |
| The card is read: cap and page bound | `test_page_size_cap_bounds_the_request_and_the_witness`, `test_page_bound_is_the_card_bound` |
| Baseline and census unchanged | `test_loop_baseline`, `test_b4_ref_graphs`, `test_census_check`, `scripts/check_census.py` |

Plus the tests that must keep passing and that the change is *shaped* by:
`test_p_auto_3_live_fetch`, `test_ops5c_actionable_search`, `test_research_sources`,
`test_provider_walk`, `test_provider_breadth`, `test_chg2_providers`,
`test_replay_diff`, `test_q04_gate_replay`.

**Two existing tests change by design, in their verdict assertions only:**
`test_first_page_empty_is_exhausted_complete` (`test_provider_walk.py:324`) moves
from `COMPLETE(retrieved==total)` to `SHORTFALL(cause=ZERO_DELIVERED)`;
`test_zero_delivered_total_positive_is_shortfall` (`:335`) and
`test_wk04_zero_delivered_total_positive_when_bounded` (`:641`) move from
`SHORTFALL(cause=ZERO_DELIVERED_TOTAL_POSITIVE)` to `SHORTFALL(cause=ZERO_DELIVERED)`
plus `zero_delivered_reason=total_positive`. Every `aggregate` and raise assertion
in those tests is unchanged, because those were already right.

---

## 5. Gates at implementation

0. **Diff surface, so the gate is sized honestly:** `tools/providers/adapters/base_adapter.py`
   (advance + identity extraction + the declared-field set),
   `tools/providers/base.py` (`WalkRequest.page_size`),
   `tools/providers/paginate.py` (bounds, witness, zero-row rule, stall guard),
   `tools/providers/redact.py` (`request_identity` / the digest step),
   `tools/providers/replay.py` (`fixture_id_of` preimage, fixture schema v2),
   the 15 adapter modules (card corrections, the new cursor/total declarations),
   `research/source_handlers.py` (one `WalkRequest` construction),
   `research/capability_supply.py` (one `fixture_id_of` call site), tests, corpus.
   No new module; no new event; no new port.
1. Targeted: the new test file, `test_p_auto_3_live_fetch`,
   `test_ops5c_actionable_search`, `test_research_sources`, the replay tests
   (`test_chg2_providers`, `test_replay_diff`, `test_q04_gate_replay`),
   `test_provider_walk`, `test_provider_breadth`, `test_loop_baseline`,
   `test_b4_ref_graphs`, `test_census_check`.
2. `scripts/run_tests.py` (full).
3. `scripts/stamp_suite_count.py`, then `--check`.
4. `scripts/check_census.py` — unchanged.
5. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright tests project.

**Gate risk, named now:** step 1 cannot pass on the current corpus — the two
fixture files must be re-stamped or re-recorded in the same change (§2.4). If
neither is possible at gate time, the gate is blocked, not weakened.

---

## 6. What this note could not decide from the tree

| Open | Why the tree cannot close it | How it is closed |
| --- | --- | --- |
| EuropePMC's end-of-cursor behaviour (`nextCursorMark` repeated vs omitted on the last page) | Requires a live call; no recorded body in-tree | The design accepts both: a repeated token is an end witness **iff** the page added no new identifier; otherwise `PAGINATION_STALLED` |
| Whether arXiv's `opensearch:totalResults` is exact or an estimate | Not observable from code; arXiv has no recorded search body | Ship it as `count_semantics: "estimate"` until a live probe says otherwise — an estimate is never a W2 witness |
| CORE `totalHits`, Semantic Scholar `total`, SearXNG `number_of_results` | The adapters declare no total path; the payloads are not in the corpus | Named in the card audit as "to confirm at implementation"; each is a `total_fields` declaration, not a code path |
| Whether the corpus can be re-recorded in this environment | Phase 1 is offline by charter | Re-stamp is the offline path; re-record is preferred if network is available at gate time |
| Adding scholarly `id_fields` to the four web adapters | Safe today (they deliver zero, so no result id moves), but it is a per-provider table decision | Deferred: §2.1/§2.2 do not need it; the `url` identifier alone makes the rows deliverable |
| `pages_done >= spec_guard → CURSOR_TRAP` mislabels an offset walk | Dead today (`max_pages_cap` 50 < every `loop_guard` 100) | Left alone; recorded here so a future `loop_guard < 50` does not inherit the wrong cause silently |

---

## 7. The answers, in one place

1. **Cursor advancement.** The card becomes the contract the driver and the base
   adapter read; the adapter computes `next_state` per kind; the page budget and the
   result budget separate; `COMPLETE` requires an exhaustion witness. The verdict
   vocabulary already has the honest value: `SHORTFALL`, which the aggregate spells
   `PARTIAL`. `PARTIAL` exists in `SearchAggregate` and not in
   `ReconciliationVerdict`, and it must stay that way.
2. **Zero rows.** `SHORTFALL(cause=ZERO_DELIVERED)` with a sub-cause — a distinct
   verdict in the existing vocabulary, a refusal at the run boundary (the existing
   `EMPTY` raise and `failed_typed`), and the run may not proceed. Today it already
   does not; the record will stop saying otherwise.
3. **Fixture identity.** Identity is a function of the request as sent, committed
   as a digest per declared field; presentation stays redacted; no value and no
   credential enters the fixture; default-deny is unchanged and does not trade
   places with identity.
4. **The corpus.** Re-stamped (offline, deterministic) or re-recorded in the same
   change; old files refused loudly; no dual-scheme fallback.
