# P2-16 — Contradiction detector blind spots (triage)

| Item | Value |
| --- | --- |
| Task | P2-16 (GAP-2): the contradiction detector's blind spots |
| Base | `54f6173` (`main`) |
| Branch | `triage/p2-16` (read-only investigation) |
| Status | **RULED A — document the boundary** (2026-10-23, human) |
| Deliverable | This document; no `src/`, test, migration, fixture, or governed-doc change |

**Ruling (2026-10-23, human): A — document the boundary.** A was chosen
because the ref-kind gap is unreachable by construction and the
dimensional gap has no agreed semantics. B (a diagnostic reporting 0
today) and C (changing a deliberately pinned boundary for 0 measured
pairs) were declined.

Source triage: `AUDIT-GAP-2-TRIAGE.md:198-222` on branch
`audit/gap-2-triage`. The verdict there is NEEDS-INVESTIGATION, not a
regression: candidate rows carry seven fields, and the uncompared
dimensions were never in the detector contract.

Two exclusions are owned and are **not** re-litigated here:

- **Web-derived evidence** is excluded on both evidence paths by ratified
  IDR-046 E4/E5/D2 (`docs/idr/IDR-046-commercial-search-allowlist-and-post-transport.md:60-62`).
- **Same-class disagreements** are excluded by the frozen N1 pair rule
  (`src/hermes/research/contradictions.py:349-366`): different
  `failure_class` **and** non-empty evidence overlap.

## 1. The recognition surface, re-derived live

### 1.1 Candidate rows

`detector_candidate_rows` (`contradiction_candidates.py:22-78`) derives one
row per digest-valid classification. The row is exactly:

```
{artifact_id, project_id, program_ref, hypothesis_ref, failure_class,
 evidence (sorted resolved bare artifact IDs), invalidated}
```

(`contradiction_candidates.py:68-77`; pinned by
`tests/test_s1_detector_rows.py:131`). The raw `evidence_refs` list is not
carried on the row: only the resolved IDs are (`:58-67`).

`detector_resolve_ref` (`contradiction_candidates.py:81-122`) is the first
implementation of the ref surface:

- bare ID (no `:`) → project-scoped row lookup (`:91-102`), then the
  IDR-046 web bar (`:100-101`);
- typed ref → exactly six prefixes (`evidence`, `source_result`,
  `source_payload`, `source_search`, `failure_classification`,
  `feature_binding`) resolved by `(project, content_hash, artifact_type)`
  (`:106-114`), then the web bar (`:120-121`);
- anything else, a missing row, a non-string, or a retracted source →
  `return None` (`:87-88,96,109,116`).

### 1.2 The gateway's second implementation

`_cx_resolve_evidence_ref` (`gateway.py:2974-3013`) has the same six
prefixes (`:2995-2998`), the same project/content/type lookup (`:2999-3003`),
the N9 retraction skip (`:3006-3007`), and the same web bar (`:3008-3012`).
It differs on bare IDs: `_cx_resolve_evidence_ref` returns `None` for every
ref without a separator (`:2991-2993`), while the detector resolves a bare
ID against its row. That is the known P3-15 parity gap, not this triage's
subject; it is noted so the two surfaces are not described as identical.

`_cx_classification_facts` (`gateway.py:3016-3067`) builds the evidence set
through the gateway resolver and silently skips every `None` (`:3057-3059`),
exactly as the detector does.

### 1.3 The pair rule

`detect_classification_conflicts` groups by
`(project_id, program_ref, hypothesis_ref)`, drops invalidated rows, and
emits a pair only when the two primary `failure_class` values differ and
`_overlap` is non-empty (`contradictions.py:349-366`; `_overlap` at
`:148-160`). Same-class rows are skipped before overlap is computed
(`:362-363`). Nothing else is compared.

### 1.4 What happens outside the six

`return None` → **silently dropped**. The ref is omitted from the row's
`evidence` set, so it cannot contribute to `_overlap`, cannot create a
pair, and cannot appear in the detection result. There is no log line, no
counter, no diagnostic key, and no journal event for an ignored ref. The
only diagnostic key in this area is `DETECTOR_TRUNCATED`
(`contradictions.py:52-59,292-345`), which reports the pair cap, not
ignored refs. The raw ref is not carried on the candidate row, so an
operator cannot see what was dropped even after the fact. The gateway's
`_cx_classification_facts` has the same silence (`gateway.py:3057-3059`).

## 2. Blind-spot inventory

### 2.1 Unrecognized ref kinds

Production writers, derived from the code (not from a hand-built type
list):

| `artifact_type` | Production writer | In the six? | Admission-reachable as a direct evidence ref? |
| --- | --- | --- | --- |
| `source_search` | `source_outcomes.py:975` | yes | no — one hop (`outcome → task`); the two-hop ownership check fails |
| `source_result` | `source_outcomes.py:987` | yes | yes — `task → source_search → result` (probe below) |
| `source_fetch_outcome` | `source_outcomes.py:1014` | **no** | no — one hop (`outcome → task`); the two-hop check fails; the gateway contradiction resolver returns `None` by an explicit test (`tests/test_web_provenance_fence.py:322-332`) |
| `source_payload` | `source_outcomes.py:1042` (fetch); `corpus.py:363` (corpus) | yes | fetch payload: yes (`task → fetch outcome → payload`, edges at `source_outcomes.py:1068-1069`); corpus payload: one hop (`corpus.py:390-393`) |
| `provider_response` | `provider_interactions.py:184` | **no** | no — written with `task_id` but no `derived_from` edge |
| `failure_classification` | `failure_classifications.py:303` | yes | no — admission explicitly refuses a classification as evidence (D8; `:376-380`, `:420-421`) |
| `ResearchDecision` | `gateway.py:1714-1729` | **no** | no — `task_id` is `NULL`; only a `supersedes` edge is written |
| `feature_binding` | no production writer at this base; constant only (`feature_binding.py:89`), tests insert the row | yes | only if a two-hop row exists; none is written |
| `evidence` | no production writer at this base; tests insert the row (the Step-7 basis convention) | yes | only if a two-hop row exists; tests insert it |
| `validation` | no production writer; tests insert the row | **no** | test-only |
| `research_claim` | not an artifact — table `research_claims` (`migrations.py:486`); one test inserts an artifact row | **no** | production: not an artifact; test-only |
| `dataset_manifest` | not an artifact — table `dataset_manifests` (`migrations.py:279`) | no | not a typed artifact ref |

The admission gate that decides the last column is
`_verify_evidence_owned` (`failure_classifications.py:364-407`): it refuses
a ref without `:`, refuses `failure_classification`, and otherwise requires
two-hop `derived_from` reachability from the producing task. The
`_evidence_resolver` used by the classification substrate
(`failure_classifications.py:409-433`) refuses only
`failure_classification`; the detector's six-prefix wall is a **separate**
restriction, not the admission rule.

A live scratch-database probe of `_source_artifact_resolves(...,
upstream_task_id=...)` on the tested chains produced:

| Type | project scope | two-hop upstream-task |
| --- | --- | --- |
| `source_search` | true | **false** |
| `source_result` | true | **true** |
| `source_fetch_outcome` | true | **false** |
| `source_payload` | true | **true** (with the fetch-payload edges) |
| `evidence` | true | **false** on the one-hop test chain; true only if a two-hop chain is built |

So the only production-written types that can currently reach a persisted
classification's `evidence_refs` and satisfy the two-hop check are
`source_result` and the fetch-path `source_payload` — **both recognized**.
The types the detector would silently drop (`source_fetch_outcome`,
`provider_response`, `ResearchDecision`) are not admission-reachable as
direct evidence refs at this base. The ref-kind drop is therefore
**latent**, not live; it becomes live only if a future admission change
makes a new type two-hop reachable without extending both resolvers.

Test-only rows do not change that conclusion: `validation:` appears in
`tests/test_failure_classification.py:52,69,100` only through a fake
resolver in the pure substrate; `source_fetch_outcome:` appears in the
L2/web-fence tests (`tests/test_s5_l2_resolution.py:186-188`;
`tests/test_web_provenance_fence.py:322-332`) as a direct resolver probe,
not as persisted classification metadata. Neither is a corpus ref in the
sense measured below.

### 2.2 Uncompared payload dimensions

**Contributing factors.** The field is
`contributing_factors` in `failure_classification` metadata
(`failure_classifications.py:569-590`; built from the draft at
`failure_classification.py:295-340,897-920`). It is a tuple of
`FailureClass` values, validated for type, unknown values, primary-factor
duplication, and duplicates (`failure_classification.py:619-663`). It is
typed and comparable **within** a classification. No code compares it
across classifications; the pair rule reads only `failure_class` and
`evidence`.

**Numeric claims.** The typed numeric field is `ResourceGap`
(`failure_classification.py:270-282`): `resource_kind`, `observed: float`,
`required: float`, `unit`, persisted as `resource_gap` in the
classification metadata (`failure_classifications.py:569-590`). It exists
only for `RESOURCE_CONSTRAINT`. The program-level
`DiscriminationRequirement` fields `expected_difference`,
`required_condition`, and `measurement_method_ref`
(`programs.py:255-259,1412-1420`) are **strings**, not numeric claims, and
live on the program, not on either classification. No code compares
`resource_gap` or any numeric field across classifications.

**Sources.** The source artifacts are `source_result` / `source_payload`
(and the aggregate `source_search` / `source_fetch_outcome`). A
`SearchResult` carries `identifiers`, `title`, `source_url`, and a stable
`content_hash` (`tools/research_sources.py:429-458`); the identity preimage
is provider-inclusive and excludes observation/retrieval fields
(`research_sources.py:149-172`). Repeated retrieval of the same source by
the same provider is the same hash; a different provider or a changed
identity is a different row. The detector's overlap is by **artifact ID**
(`contradictions.py:148-160`), not by DOI/URL/title. There is no
cross-provider source-equivalence notion anywhere in the tree.

### 2.3 What a disagreement would mean

| Dimension | Is a difference a contradiction under the ratified contract? |
| --- | --- |
| Contributing factors | No. The contract says a contradiction is a relation between two classifications with different **primary** failure classes and evidence overlap (`contradictions.py:3-9`); same-primary pairs are excluded, whatever their factors. A factor difference is a distinction/richer diagnosis, or undefined; it is not a contradiction absent an N1 change. |
| Numeric claims | Undefined. `ResourceGap` is class-specific and unit-bearing; two different gaps may describe different resources, scopes, or measurement methods. No contract says differing numbers conflict, and no code compares them. |
| Sources | Undefined. Different source rows can be the same source via different providers, or different versions/observations of one source. There is no equivalence rule, so "these disagree about the source" has no defined truth value. |

The contract is silent on all three. Extending any of them is new scope,
not a regression; the triage does not invent the semantics.

## 3. Measurement

### 3.1 Method

A throwaway SQLite database was built under the OS temp directory from the
shipped test helpers; no repository database was read or written.

1. Create a temp file DB; `migrate_to_latest`; create project `p1`.
2. **CHG-1 corpus:** call `tests/test_chg1_contradictions.py`'s
   `_conflicting_pair` twice (four classifications, two evidence artifacts,
   two pairs).
3. **S-1 corpus:** call `tests/test_s1_detector_rows.py`'s
   `_program` / `_task` / `_chain` / `_pair` (two production-path
   classifications, one `source_result` artifact, one pair).
4. Query `artifacts` (types, hashes), parse every classification's
   `evidence_refs`, and call `detector_resolve_ref` on each ref.
5. Call `Controller._detector_candidate_rows()` and
   `detect_classification_conflicts`; count pairs.
6. For each detected pair, load both classification metadata rows and
   compare `contributing_factors`, `resource_gap`, and the raw
   `evidence_refs` sets.
7. Capability probes (clearly not corpus prevalence): insert artifact rows
   for `source_fetch_outcome`, `validation`, and `provider_response`, then
   call `detector_resolve_ref`; separately call
   `_source_artifact_resolves(..., upstream_task_id=...)` on the tested
   chains.

Repeat by importing the same helpers and running the same queries; the
temp DB paths are incidental and were not committed.

### 3.2 Corpus counts

| Corpus | Artifact types | Classifications | Evidence refs | Dropped refs | Detected pairs | Pairs differing on factors | Pairs differing on resource_gap | Pairs with differing raw source refs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CHG-1 scratch | `evidence`, `failure_classification` | 4 | 4 (`evidence:`) | **0** | 2 | **0** | **0** | **0** |
| S-1 scratch | `failure_classification`, `source_result` | 2 | 2 (`source_result:`) | **0** | 1 | **0** | **0** | **0** |
| Combined | — | 6 | 6 | **0** | 3 | **0** | **0** | **0** |

Unrecognized-kind prevalence in these persisted corpora: **0 refs of any
kind outside the six**. The static test-suite occurrences of `validation:`
and `source_fetch_outcome:` are not counted as persisted corpus refs; they
belong to the pure substrate and direct-resolver tests named above.

### 3.3 Probes (not prevalence)

Inserting one row each of `source_fetch_outcome`, `validation`, and
`provider_response`, then resolving their refs, produced `None` for all
three (and `None` for an unresolvable `source_result:` hash, which is a
different case). This demonstrates the silent drop mechanically; it does
**not** show that such refs occur in an admitted classification, and the
reachability probe above explains why they currently do not.

Per unrecognized kind:

| Kind | Corpus refs | Corpus dropped | Probe rows | Probe resolves |
| --- | --- | --- | --- | --- |
| `source_fetch_outcome` | 0 | 0 | 1 | `None` |
| `validation` | 0 | 0 | 1 | `None` |
| `provider_response` | 0 | 0 | 1 | `None` |
| `ResearchDecision` | 0 | 0 | not probed — no `derived_from` edge | — |
| `research_claim` | 0 | 0 | not an artifact (`research_claims` table) | — |

### 3.4 Additional pairs if a dimension were recognized

Under the current N1 rule: **0** for contributing factors, **0** for
numeric/resource-gap claims, and **0** for sources. A pair that differs on
a dimension and shares evidence overlap with different failure classes is
**already** detected; the dimension adds no new pair. A same-class pair
that differs on factors or gaps is exactly what N1 excludes
(`contradictions.py:362-363`), so recognizing it as a conflict would be an
N1 change. A source-identity rule (same DOI across different artifacts)
would be a new evidence-equivalence rule; no code defines it.

Constructed probes (not corpus) show the boundary:

- same primary `IMPLEMENTATION_FAILURE`, same evidence, factors `[]` vs
  `["FRAMING_ERROR"]` → 1 pair only if N1 is changed; this is a false
  contradiction under the current contract.
- two `RESOURCE_CONSTRAINT` classifications with different
  `resource_gap.observed/required` and different units/scopes → 1 pair only
  if numeric disagreement is invented as a conflict; undefined semantics.
- two `source_result` rows for the same DOI from different providers
  (different content hashes) → 1 pair only if source identity is
  equated; this would pair classifications whose underlying extractions
  differ.

### 3.5 False contradictions

The persisted corpus produced **0** candidate pairs for any dimension, so
there is no corpus sample to show. The constructed examples above are the
false-positive shapes: same primary class with different advisory factors;
different units/scopes with different numbers; same source identity with
different observations. They are the reason C is not a parameter tweak.

### 3.6 Tests that pin the surface

- `tests/test_s1_detector_rows.py:131` (row shape and values),
  `:177` (ordering/evidence).
- `tests/test_web_provenance_fence.py:322-332` (the gateway contradiction
  resolver returns `None` for `source_fetch_outcome`, by design; the
  comment says the distinction lives in L2), `:367-388` (detector web
  paths), `:421-424` (L2 resolves fetch outcomes).
- `tests/test_chg1_contradictions.py:200` (same-class exclusion).
- `tests/test_cx_overlap_fresh_store.py` (fresh overlap provenance).
- `tests/test_chg_dedup_tick_skip.py` (dedup skip; no row-shape change).
- `tests/test_s5_l2_resolution.py:186-188` (L2 recognises
  `source_fetch_outcome`).
- `tests/test_failure_classification.py:52,69,100` (`validation:` refs
  through the pure substrate's fake resolver).
- `tests/test_p6_classification.py` (classification admission/ownership).
- `tests/test_q05_persistence.py` (persisted classification metadata).
- `tests/test_ext6_open_bound.py` (the pair cap; not ref recognition).

The C blast radius is therefore at least the row-shape pin, the web-fence
pin, the L2/contradiction distinction pin, and the pair-rule tests.

### 3.7 What the corpus cannot measure

The shipped contradiction corpus has no non-empty `contributing_factors`,
no `resource_gap`, and no multi-source/DOI variants. It cannot measure
production prevalence or false-positive rates for those dimensions. A
sanitized production corpus (classifications with those fields, same
project/program/hypothesis groups, different failure classes, and
multi-source evidence) would be required. The 197 on-disk DBs noted in
`contradictions.py:92-94` are a candidate source, but this charter forbids
using the repository's own DB; a sanitized export is out of scope here.

## 4. Options, costed

### A — accept the contract (recommended)

Document the closed recognition set and the seven-field/N1 boundary. The
natural home is the two ungoverned module docstrings, because that is
where a future maintainer reads the rule:

- `contradiction_candidates.py` module docstring, after the existing
  "evidence refs that do not resolve..." sentence (`:27-33`).
- `contradictions.py` module docstring, after "Nothing else is asserted"
  (`:3-9`).

Exact sentences:

> Recognition is a closed six-prefix set (`evidence`, `source_result`,
> `source_payload`, `source_search`, `failure_classification`,
> `feature_binding`); any other typed ref is silently omitted from the
> evidence set — never logged, counted, or surfaced. The certified
> classification write path's two-hop ownership check currently admits
> only `source_result` and two-hop `source_payload` as direct evidence
> refs, so the omission is latent; a future admitted type must extend this
> whitelist and `gateway._cx_resolve_evidence_ref` in the same change.

> Candidate rows carry only the N1 fields; contributing factors, resource
> gaps, and source attributes are not compared. The ratified pair rule is
> different failure class plus non-empty evidence overlap, and same-class
> pairs are excluded; extending the comparison is a new contract, not a
> detector setting.

Cost: prose only; no code, test, migration, census, event, governed doc,
or B4 regeneration. Residual: the documented invariant is not enforced;
future admission drift still needs review.

### B — surface ignored refs without changing detection

A read-only diagnostic reporting ignored/unresolved refs (count, kinds,
ids) on candidate derivation. Two viable surfaces:

- **Separate helper + CLI** (preferred if B): a new
  `detector_ignored_refs(conn, project_id, digest_items)` in
  `contradiction_candidates.py` that walks the same metadata and returns
  `{total, by_kind, refs}`, surfaced under a new read-only CLI command
  (`hermes contradictions inspect`) or a Controller read method. It does
  not touch `detect_classification_conflicts` or the gateway, but it
  duplicates the resolution walk and would need drift tests.
- **Detection return field**: add `ignored_evidence_refs` to
  `Controller.detect_contradictions()` (or an optional diagnostics dict in
  `detector_candidate_rows`). This is closer to the data, but it touches
  the certified candidate-derivation path and its tested return shape;
  pair selection itself is unchanged.

Cost: new code + tests; no migration, transaction, census, event, or
governed doc; no N1 change. It would report **0** on the measured corpus,
so its value is future drift detection, not a current defect. A log line
inside the pure derivation is the cheapest variant but adds a side effect
to a module documented as pure.

### C — extend the contract

Name the only plausible ref-kind extension: `source_fetch_outcome`. But
admission's two-hop check rejects it as a direct evidence ref (probe
above), and the gateway contradiction resolver's `None` for that type is
explicitly pinned (`tests/test_web_provenance_fence.py:322-332`), with the
comment that the distinction lives in L2. C would therefore require an
admission change, not just a detector prefix, and would erase a deliberate
test boundary. For the dimensions: contributing factors require an N1
change (same-class pairs), numeric claims have no cross-artifact semantics,
and source identity has no equivalence rule; all three measured 0 corpus
pairs and the constructed probes are false contradictions.

Cost: two resolver edits if a ref kind, or a new conflict rule if a
dimension; N1/contract review; row-shape and web-fence test changes; a new
corpus; likely an IDR/design gate. No migration is inherent, but the
semantic change is larger than the code change. Not recommended on the
measurement.

| Option | Closes | Cost | Conflicts with |
| --- | --- | --- | --- |
| **A** | Records the closed six-prefix/seven-field boundary and its latent status | two ungoverned docstring paragraphs; no code/tests/migration/census/B4 | nothing; does not enforce the invariant |
| **B** | Makes future ignored refs visible without changing pairs or N1 | read-only helper + CLI or Controller field + tests; no migration/census/event; reports 0 today | the pure-module posture if a log line is used; duplicates the walk if separate |
| **C** | Would recognise a named type/dimension | resolver/contract change; N1 review; test blast radius; new corpus | the deliberate fetch-outcome exclusion and N1's same-class rule; produces false contradictions in the constructed samples |

## 5. Recommendation

**A — document the boundary.** The structural argument decides it, and
the corpus measurement is corroboration rather than evidence of production
prevalence: six refs across two test fixtures is a lower bound on nothing.

On the ref-kind side, admission's two-hop ownership check
(`_verify_evidence_owned`) can reach only `source_result` and the
fetch-path `source_payload` among production-written kinds, and both are
in the six. `source_fetch_outcome` is one hop and fails the check; the
contradiction resolver's exclusion of it is deliberately pinned.
`provider_response` and `ResearchDecision` have no `derived_from` edges;
`validation` and `research_claim` have no production writer or are not
artifacts. A ref kind outside the six therefore cannot reach a persisted
classification's evidence list — the drop is unreachable by construction,
not merely unobserved.

On the dimensional side, contributing factors, numeric claims, and source
identity have no agreed contradiction semantics: same-class pairs are
excluded by N1, and no cross-artifact numeric or source-equivalence rule
exists. Recognizing any of them would be a new contract, not a detector
setting. B would report 0 today; C would change a deliberately pinned
boundary or invent semantics for 0 measured pairs.

## 6. The ruling request

The question below is the historical request; the ruling paragraph above
records the decision.

> **P2-16 ruling.** The detector's evidence recognition is a closed
> six-prefix set and its candidate rows carry only the seven N1 fields.
> Both are silent/latent, not live: the two measured contradiction-test
> corpora have 0 dropped refs and 0 pairs differing on contributing
> factors, numeric resource gaps, or source attributes; the only plausible
> unrecognized production kind (`source_fetch_outcome`) is
> admission-unreachable under the two-hop ownership check and deliberately
> excluded at the contradiction resolver.
> Do we (A) document the boundary in the two ungoverned module docstrings,
> (B) add a read-only ignored-ref diagnostic, or (C) extend the contract
> to a named dimension? Recommended: **A**. A costs prose only; B would
> report 0 today; C would change N1 or invent undefined semantics and has
> no measured pairs. Please rule A, B, or C.

## 7. What could not be measured

- Production prevalence of non-empty contributing factors, resource gaps,
  and cross-provider source identity. The shipped corpus has none. A
  sanitized production corpus (or a purpose-built fixture set) with at
  least two classifications per dimension, the same
  project/program/hypothesis, different failure class, non-empty evidence
  overlap, and differing dimension values would be needed.
- False-positive rates for C on real classifications; the constructed
  samples show the shapes, not their frequency.
- Whether any future admission change will make a new type two-hop
  reachable. That is a design-time invariant, not a current measurement.

License: Apache-2.0 (LICENSE).
