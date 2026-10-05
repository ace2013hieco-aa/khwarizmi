# HR-04: source identifier capture — preserving stable bibliographic
# identifiers at SOURCE admission

**Status:** CONTRACT PINNED + NORMALIZATION CHOKE POINT HARDENED + TESTED
(2026-08-19). The future lineage engine (citation graph, source-independence
scoring, DOI resolver, semantic similarity) remains **DEFERRED**; this IDR
pins the cheap prerequisite — canonical scholarly-identifier preservation at
admission — so future lineage reasoning needs no disruptive schema migration.

**Date:** 2026-08-19
**Covers:** the existing identifier infrastructure (IDR-030 Step 1:
`src/hermes/tools/providers/normalize.py`), the HR-04 hardening
(`canonicalize_identifiers` + its two walk wiring sites), the identity
semantics of `SearchResult.identifiers`, the persistence path
(`source_result` artifact metadata), and
`tests/test_hr04_source_identifier_capture.py` (acceptance A–J + the
canonicalizer unit table).

---

## 1. The invariant

> **content_hash equality ≠ scholarly independence**, and
> **different content_hash ≠ independent research study.**

Three distinct identities coexist and MUST NOT be conflated:

| Identity | Meaning | Where it lives |
|---|---|---|
| **Content identity** | these bytes/this bibliographic essence are identical | `content_hash_of_search_result` (`research_sources.py:148`) |
| **Scholarly/lineage identity** | these records refer to the same scholarly work | `SearchResult.identifiers` (`research_sources.py:427`) — canonical DOI/PMID/PMCID/arXiv + provider-native ids |
| **Provenance identity** | actual Hermes relationship graph | `provenance_edges` (`derived_from` edges, `source_outcomes.py:860`) |

Identifiers are **inputs for future lineage reasoning**, never provenance
edges themselves. This task does NOT turn identifiers into edges.

## 2. Current identifier inventory (reconciliation — §1 of the brief)

Identifier capture **already existed** at HEAD `f3603b9` (IDR-030 Step 1,
contract §3.1). Nothing in this change adds a field that already existed
under another name:

| Structure | Location | Role |
|---|---|---|
| `normalize_identifier(kind, raw)` | `normalize.py:137` | contract §3.1 canonical forms (DOI/PMID/PMCID/arXiv/URL) |
| `parse_query_hints(query)` | `normalize.py:157` | query-side hint parsing → canonical `RetrievalHints.identifiers` |
| `dedup_key(identifiers)` | `normalize.py:226` | cross-provider dedup: doi → pmid → pmcid → arxiv, namespaced |
| `IDENTIFIER_KINDS` | `normalize.py:35` | `("doi", "pmid", "pmcid", "arxiv", "url")` — the dedup/hint tuple |
| `SearchResult.identifiers` | `research_sources.py:427` | `{doi?, pmid?, pmcid?, arxiv?, core_id?, openalex_id?, …}` — canonical form |
| `Source.identifiers` | `research_sources.py:404` | the v6 §16.1 write-path target's canonical identifiers |
| `make_search_result_id` | `research_sources.py:101` | identifiers participate in the content-addressed `result_id` |
| `_IDENTITY_FIELDS` | `research_sources.py:134` | identifiers participate in the semantic `content_hash` preimage |
| `search_result_to_mapping` / `_from_mapping` | `research_sources.py:315/320` | closed-schema persistence round-trip (OB-05) |

**The gap found (probe-confirmed):** the walk persisted
`adapter.extract_ids(record)` output **raw** (`paginate.py:300` at pre-change
HEAD). Query hints were normalized by `parse_query_hints`, but
record-extracted identifiers were not — a provider returning
`10.1038/NATURE12373` (uppercase) or `2103.15348v2` (versioned) would persist
a **competing identity** for the same scholarly work, violating the brief's
§5 principle ("only persist canonical values through one deterministic
identity/normalization path"). The valid-negative branch
(`_valid_negative_result`) had the same exposure for hand-built
`spec.hints` payloads (`source_handlers.py:380` `_hints_from_spec` bypasses
`parse_query_hints`).

## 3. The fix — one deterministic normalization choke point (Path B)

**Decision: Path B** (small normalization change; no new fields, no new
table, no lineage subsystem — §17 of the brief).

`canonicalize_identifiers(identifiers)` (`normalize.py:244`) is the single
canonicalization pass, wired at the walk's two identifier entry points:

1. **Record extraction** — `paginate.py:304`:
   `ids = canonicalize_identifiers(adapter.extract_ids(record))`
2. **Valid-negative** — `paginate.py:758`:
   `ids = canonicalize_identifiers(dict(hints.identifiers))`, and
   `valid_negative_for` now reads the canonical `ids` (`paginate.py:786`),
   never the raw hint value.

Semantics of the pass:

- A known scholarly kind (`doi`/`pmid`/`pmcid`/`arxiv`, matched
  case-insensitively on the KEY) is re-keyed lowercase and its value
  normalized via `normalize_identifier` (contract §3.1). A value that fails
  normalization is **DROPPED** — storing it would forge a garbage identity
  (same drop semantics `parse_query_hints` applies to an invalid hint). If
  every identifier is dropped, the walk's existing `if not ids:
  MALFORMED_ROW` path handles the record (`paginate.py:305`).
- `url` and every provider-native kind (`openalex_id`, `core_id`, …) are
  preserved **VERBATIM** (key and value) — they are not in the §3.1 table
  and must never be coerced into, or mistaken for, a universal identity.
- The pass is **idempotent**: canonicalizing an already-canonical map (the
  `parse_query_hints` path) is a no-op, so both entry points converge on one
  identity and double-normalization is safe.

## 4. Normalization rules (contract §3.1 — unchanged, now enforced)

| Kind | Canonical form |
|---|---|
| DOI | lowercase; strip `doi:` / `https://doi.org/` / `http://dx.doi.org/` prefixes; strip trailing dot; require `10.<reg>/<suffix>` (`_DOI_PREFIX_RE`) |
| PMID | digits only (strip `PMID:` casing/whitespace) |
| PMCID | `PMC` + digits; bare numeric form → `None` (PMC-vs-PubMed ambiguity — never guessed) |
| arXiv | new scheme `YYMM.NNNNN` / old scheme `arch-ive/YYMMNNN`; **version suffix stripped for identity**; resolver URLs (`arxiv.org/abs|pdf/…`) extracted |
| URL | DOI/arXiv extracted on known resolver hosts only; otherwise stays a fetch hint (NOT canonicalized — a non-resolver URL is a legitimate value) |
| provider-native | verbatim — no universal parser (brief §4: provider-specific stays provider-specific) |

## 5. Identity semantics

- **Same DOI, same content** → one identifier map, one `content_hash`
  (acceptance A). Identifiers are in the semantic identity preimage
  (`_IDENTITY_FIELDS`), so canonical convergence collapses formatting
  variants into one identity.
- **Same DOI, different provider, different content** → shared identifier,
  **distinct** `content_hash` (acceptance B). No automatic content dedup —
  both provenance observations are preserved; future lineage reasoning
  decides same-work/version/mirror/preprint/correction/retraction (brief §6).
  The walk's `dedup_key` dedup is **within one provider walk** (first-seen
  wins); `combine` does NOT cross-provider-dedup by identifier.
- **Multiple identifiers** → all preserved; no universal-identity pick
  (acceptance D), unless the architecture already has such a rule — it has
  one only for dedup priority (`dedup_key`: doi → pmid → pmcid → arxiv),
  which selects a dedup KEY, never deletes identifiers.

## 6. Missing-identifier semantics (brief §8)

Missing DOI/identifiers MUST NOT cause source rejection:

- A record with a `url` only (or provider-native ids only) is **delivered**;
  it simply participates in no cross-provider dedup set (`dedup_key` →
  `None`, walk note path `paginate.py:305-311`). Identifier absence =
  **unknown lineage**, never an invalid source.
- A record with **no** identifier field at all is a `MALFORMED_ROW` note
  (skipped, walk continues) — this is the pre-existing walk contract,
  unchanged by HR-04.

## 7. Provider capability table (brief §10 — honest availability)

**No production adapters exist at this HEAD.** The provider slice is the
orchestration layer (normalize/walk/redact/ratelimit/hazard); the 11
ratified adapters (IDR-030 allowlist, `research_sources.py:193`) are
declared in the contract §3 table + hazard-spec JSON
(`src/hermes/tools/providers/hazard_specs/{arxiv,pmc,europepmc,openalex}.json`)
but their `extract_ids` implementations are **DEFERRED**. The table below
records what the ratified contract DECLARES each provider can supply — not
observed live behavior (nothing to fabricate from):

| Provider (declared) | DOI | PMID | PMCID | arXiv | OpenAlex | Provider-native |
|---|---|---|---|---|---|---|
| `pubmed` | resolves | native | — | — | — | PMID (native) |
| `pmc` | resolves | resolves | native | — | — | PMCID (native) |
| `europepmc` | native | native | native | — | — | cross-corpus ids |
| `arxiv` | resolves | — | — | native | — | arXiv id (native) |
| `biorxiv` / `medrxiv` | native (lookup key) | — | — | — | — | DOI (native) |
| `openalex` | native | resolves | resolves | resolves | native | OpenAlex id (native) |
| `crossref` | native (registry) | — | — | — | — | DOI (native) |
| `semantic-scholar` | native | resolves | — | resolves | — | S2 paper id |
| `core` | native | — | — | — | — | CORE id (native) |
| `unpaywall` | native (lookup key) | — | — | — | — | DOI (native) |

When real adapters land, each `extract_ids` emits raw provider strings; the
walk's `canonicalize_identifiers` choke point guarantees only canonical
values persist — no per-adapter normalization discipline required.

## 8. Provenance implications (brief §11)

- `content_hash` = byte/bibliographic identity (semantic preimage,
  `research_sources.py:148`).
- `identifiers` = bibliographic lineage HINTS — carried on the record,
  persisted in `source_result` metadata, never auto-promoted to edges.
- `provenance_edges` = the actual graph (`derived_from`: result → outcome →
  task, `source_outcomes.py:860-875`). Identifiers do not create edges.

## 9. Schema / migration decision (brief §12)

**No new table. No migration.** The existing schema already carries a
structured identifier collection cleanly:

- `SearchResult.identifiers: dict[str, str]` is a typed field, persisted via
  `search_result_to_mapping` into the `artifacts.metadata_json` column of
  the `source_result` row (`source_outcomes.py:861-874`), with closed-schema
  round-trip validation (OB-05, `research_sources.py:320`).
- Multiple identifiers per source are native to the dict shape; the
  closed-key validation already type-checks it as a string→string mapping
  (`research_sources.py:350`).

Path C (new persistence table) was therefore **not needed** — the current
schema represents the identifier collection without migration pain.

## 10. Compatibility with the provider closure (brief §16)

The ResearchSourceProvider slice status at HEAD `55c35c2` (closure gate
package, 2026-08-14): steps 1–6 of 7 **IMPLEMENTED + TESTED**, **NOT
RATIFIED-as-implemented**; step 7 (record/replay acceptance run) DEFERRED;
the external closure gate (§27 item 43) STANDING.

HR-04 is **post-closure hardening**, not a scope change:

- It adds no new provider-slice surface (no adapter, no endpoint, no hazard
  class, no contract-card field).
- It enforces an EXISTING contract clause (§3.1 normalization) at a point
  the closure package's step-1 normalization already owned.
- All 227 pre-existing provider/source tests pass unchanged at the new HEAD
  (every fixture was already canonical — the change is a no-op on canonical
  input by idempotency).
- The historical closure record is preserved; if the external gate re-runs,
  this hardening is disclosed as post-`55c35c2` hardening in the gate input.

## 11. Forged-identifier behavior (brief §9 — deterministic, no resolution)

| Attack | Behavior |
|---|---|
| Malformed DOI (`not-a-doi`, `10.abc/foo`) | dropped (never stored) → record falls to `MALFORMED_ROW` if nothing else remains |
| Wrong identifier type (bare number as PMCID) | dropped — ambiguity never guessed |
| Whitespace / case variants | normalized → collapse to ONE identity (dedup note on second sighting) |
| Uppercase KIND key (`DOI:`) | re-keyed lowercase, value normalized |
| Provider-specific aliases | provider-native kinds preserved verbatim — no universal parser |
| Same identifier, unrelated metadata | both preserved with distinct content identities (acceptance B) — lineage judgment deferred |
| Identifier mutation after admission | refused — reuse re-verification re-derives the semantic hash from the persisted record (OB-02, `source_outcomes.py:775`) |

No external resolution (DOI resolver, OpenAlex lookup) is built or called.

## 12. Future lineage design note (brief §13 — recorded, NOT implemented)

> Future source-independence analysis should distinguish bibliographic
> identity, version/correction lineage, content identity, and actual study
> independence.

Potential future relationships (none created now):
`same_work`, `version_of`, `correction_of`, `retraction_of`, `mirror_of`,
`derives_from`, `independent_study`. The canonical identifier collection
persisted by this change is the input that makes those edges computable
later without a schema migration.

## 13. Acceptance tests (brief §14) — `tests/test_hr04_source_identifier_capture.py`

| Test | Acceptance | Pins |
|---|---|---|
| `test_a_same_doi_different_raw_forms_one_identity` | A | same DOI + content → one identifier map, one content_hash |
| `test_b_same_doi_different_provider_content_distinct` | B | shared identifier, distinct content identities, both survive `combine` |
| `test_c_doi_format_variants_identical_through_the_walk` | C | `doi:` / resolver-URL / uppercase / trailing-dot → one identity |
| `test_d_multiple_identifiers_all_preserved` | D | DOI+PMID+PMCID+arXiv all preserved canonical; round-trip stable |
| `test_e_missing_identifiers_source_still_admissible` | E | url-only record delivered, no MALFORMED_ROW |
| `test_e2_record_with_no_identifier_at_all_is_malformed_row` | E (boundary) | pre-existing no-id contract unchanged |
| `test_f_provider_native_identifier_not_universal_identity` | F | `openalex_id` verbatim; `dedup_key` refuses it |
| `test_g_malformed_doi_dropped_deterministically` | G | malformed known kind dropped → MALFORMED_ROW |
| `test_g2_whitespace_and_case_variants_are_not_forged_identities` | G | variants collapse via dedup, one delivered record |
| `test_h_replay_identical_normalized_metadata` | H | identical input → identical identifiers/result_id/content_hash |
| `test_i_cross_provider_provenance_preserved` | I | both providers' observations + spec provenance kept |
| `test_valid_negative_carries_canonical_identifier` | (choke point) | hand-built hints canonicalized; `valid_negative_for` canonical |
| `test_j_identifier_mutation_after_admission_refused` | J | persisted-identifier tamper → `SourceOutcomeIntegrityError` (OB-02) |
| unit table (`test_canonicalize_*`, 6 tests) | §4 | convergence, idempotency, kind-case, verbatim native, drop semantics |

## 14. Rejected alternatives

1. **A new `source_identifiers` table** (Path C) — rejected: the existing
   typed `identifiers` dict on `SearchResult`/`Source` + `metadata_json`
   persistence already represents multiple identifiers cleanly; a table
   would be migration pain for zero current capability (brief §12).
2. **Normalizing inside each adapter's `extract_ids`** — rejected: no
   production adapters exist yet, and per-adapter discipline is exactly the
   "competing identities" failure mode; one walk-level choke point is
   enforceable and adapter-proof.
3. **A universal identifier parser for provider-native kinds** — rejected:
   brief §4 — provider-specific stays provider-specific; native ids are
   preserved verbatim, never coerced.
4. **Auto-deduplicating content across providers by shared identifier** —
   rejected: brief §6 — same scholarly identifier ≠ same byte artifact;
   both observations persist, lineage semantics deferred.
5. **Rejecting sources with missing identifiers** — rejected: brief §8 —
   absence = unknown lineage, never invalid source.
6. **External DOI/identifier resolution at admission** — rejected: out of
   scope; structural normalization only, no network, no resolver service.

## 15. Verification

- `tests/test_hr04_source_identifier_capture.py` — 19 tests, all pass.
- Pre-existing provider/source suites (`test_provider_walk`,
  `test_provider_orchestration`, `test_provider_fetch`,
  `test_provider_ratelimit`, `test_research_sources`) — 227 tests, all pass
  unchanged (zero regression; fixtures were already canonical).
- Full suite + pyright: see the commit message.

**STOP point:** the identifier-capture contract is pinned and tested. No
lineage graph, no independence scoring, no DOI resolver, no external
metadata service was built.

## 16. Step 1 follow-up — "no anonymous sources" four-field identity audit (2026-08-20, additive)

> **Status: KNOWN GAP, pinned by tests; fix separately chartered.**
>
> The operator's Step 1 charter (frozen sequence,
> `hermes_architecture_ratification.md` §8) defines source identity as four
> fields: **provider, source ID, retrieval timestamp, content hash** — no
> anonymous sources. A live-source audit (probe-verified against an
> in-memory DB, 2026-08-20) found the current admission state at
> `_validate_identities` (`source_outcomes.py:385`):
>
> | Field | Empty-value admission behavior | Mechanism |
> |---|---|---|
> | provider | REFUSED | incidental — task-binding check (V6-P7-A2-01), not a dedicated non-empty gate |
> | identifiers | ADMITTED | ratified by design (§14.5: absence = unknown lineage, never invalid) |
> | access_timestamp_utc | **ADMITTED — the genuine hole** | `_now(clock)` returns `""` when the clock lacks `now_utc` (`paginate.py:824-826`); no gate checks non-empty |
> | content_hash | enforced | derived, never authored (ADV-01/06) |
>
> Pinned by `TestStep1NoAnonymousSourcesCurrentBehavior` (4 tests,
> `tests/test_hr04_source_identifier_capture.py`). The operator chose
> tests-only: the fix (a dedicated non-empty identity gate in
> `_validate_identities`, fail-closed) is a **separately-chartered
> production follow-up** — not part of Step 1's tests-only scope. Severity:
> currently latent (no production clock/adapters wired; §7 deferral); it
> becomes live the moment production provider wiring lands.
