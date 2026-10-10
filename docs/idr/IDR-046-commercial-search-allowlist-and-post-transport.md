# IDR-046: Commercial search providers, web-text provenance, and an additive POST transport

**Status:** PROPOSED — ratified decision record; the O2-BUILD slice is
authorized by §5 (Acceptance) and by nothing else.
**Date:** 2026-10-07
**Decides for:** whether `brave`, `exa`, `tavily` and `searxng` may join
`SOURCE_PROVIDER_ALLOWLIST`; how their output is marked so it can never be
mistaken for scholarly evidence; and whether `RequestSpec` may carry a method
and body so POST-shaped vendor APIs are reachable.

**Anchored at:** branch `oh/o1-sidecar`, HEAD `d992248` (parent `ac1860a`).
Every `file:line` below is that tree. Lines with no prefix are repo-relative.

**Numbering:** `IDR-042` and `IDR-043` are held by reference (see
`src/hermes/research/corpus.py:1`, `src/hermes/research/graph_edges.py:1`), so
`046` is the next free number (`docs/idr/IDR-SKELETON.md:7`). Per that same
policy this side-branch number does not reserve a mainline slot; on merge,
renumber if `046` is taken and record the mapping in the merge commit.

---

## Context

### Why this gate exists

R6 declares web-reading stages but no web provider can serve them.
`src/hermes/methodology/workflows.py:333` and `:335` declare
`"governance_action": "WEB_SEARCH"` stages and `:340` a `WEB_READ` stage, and
`src/hermes/governance/policy.py:179-181` defines the matching action names.
The only reachable providers are the 11 scholarly ones at
`src/hermes/tools/research_sources.py:193-196`. A `SOURCE_SEARCH` naming
anything else is refused **at intent admission**, not at execution
(`src/hermes/research/gateway.py:3800-3806` for search, `:3839-3847` for
fetch), and the template-side check repeats it
(`src/hermes/research/source_templates.py:85-89`). So a commercial
web-search leg is an allowlist amendment, not an adapter addition.

### Two structural facts that shaped the decision

**1. The adapter contract is GET-only.** `RequestSpec`
(`src/hermes/tools/providers/base.py:97-105`) is
`(url, params, headers_meta)` — no method, no body. The single transport
issues one GET: `src/hermes/tools/providers/http.py:358` (`request`, "Issue one
GET"), `:367` (`_build_url`), `:373` (`urllib.request.Request(url, headers=…)`
— GET unless `data=` is passed, which it never is), and `:449-457` merges
params into the query string. Consequently a POST+JSON vendor cannot be
driven without a transport change.

**2. The evidence-qualification choke points are positive allowlists over the
*existing* source artifact types.** Web-derived artifacts must be barred from
every evidence position. But the web legs reuse the existing `source_search` /
`source_result` / `source_fetch_outcome` / `source_payload` taxonomy, so a new
artifact type is the wrong lever — and **bar by omission is not available**:
the outcome rows a web walk writes already carry listed types (`source_search`
at `source_outcomes.py:884`, `source_fetch_outcome` at `:923`). The bar has to
be **explicit** at each site, keyed on the provider marker D2 defines:

| Choke point | Anchor | Required clause |
|---|---|---|
| classification evidence-ref resolution | `src/hermes/research/gateway.py:2695-2704` | the resolved row is web-derived → `None` (**skip**) |
| contradiction qualification | `src/hermes/research/contradiction_candidates.py:87-105` | web-derived → `None` (**skip**), on **both** the bare-id and the typed path |
| L2 upstream resolution | `src/hermes/research/l2_resolution.py:52-63` | **named exemption**: web-derived rows resolve here, because this resolver serves only the retraction cone — an exclusion here would make a retracted web source unreachable |

The third row is not a bar and must not become one: `_l2_resolve_upstream` has
exactly one production caller — the S5 retraction cone (`gateway.py:84`
imports it, `gateway.py:1692` calls it inside `_validate_retract_source`) — so
resolution there is *retraction reach*, not evidence admission. Retraction is
the opposite case and **must** reach web artifacts (N9 applies to every
source), and it already does, with **no edit**: the retraction taxonomy
`gateway.py:1383-1384` (`_S5_SOURCE_ARTIFACT_TYPES`) and the
`controller.py:1361-1362` guard are unchanged, because the web legs introduce
no new types.

### Vendor facts verified for this gate

Brave and SearXNG are GET+query-param APIs and fit the current contract.
Exa is `POST https://api.exa.ai/search` with a JSON body and an `x-api-key`
header (per `exa.ai/docs/reference/search-api-guide-for-coding-agents`); Tavily's
`/search` is likewise POST+JSON. Their exact request/response field sets are
**vendor claims, not code in this repo**; §4 makes live re-verification a
precondition of ratification rather than asserting them here.

---

## Constraints

1. **Single mutation path.** Unchanged: `apply_intent`
   (`src/hermes/research/gateway.py:4038`). Web legs reach durable state only
   through the source-slice outcome write boundary
   (`src/hermes/persistence/source_outcomes.py:868-1067`).
2. **No new refusal codes.** The gateway vocabulary is
   `src/hermes/research/gateway.py:105-119`; the provider taxonomy is
   `src/hermes/tools/research_sources.py:620-714`. This IDR adds none.
3. **No new hazard classes.** `HAZARD_CLASSES` is fixed at
   `src/hermes/tools/providers/hazards.py:171-183`.
4. **Project isolation.** Unchanged; `_source_artifact_resolves` is
   project-scoped (`src/hermes/persistence/source_outcomes.py:96-156`).
5. **Replay determinism.** Fixture identity is recomputed, never trusted
   (`src/hermes/tools/providers/replay.py:102-115`).
6. **Determinism owns control.** No vendor response may decide a transition
   (`src/hermes/research/evaluation.py:1`).
7. **Layering.** New provider-plane code imports `hermes.tools.*` and stdlib
   only. The one recorded exception is `src/hermes/tools/providers/hazards.py:137`
   and this slice must not add another.
8. **Minimal dependency policy** (`pyproject.toml:13-15`). No new dependency is
   authorized; POST uses the stdlib client already imported
   (`src/hermes/tools/providers/http.py:63`).
9. **stdlib-first / Python ≥3.14** (`pyproject.toml:10`).

---

## Decisions

### D1 — The allowlist is amended to 15, split by provenance class

`SOURCE_PROVIDER_ALLOWLIST` (`src/hermes/tools/research_sources.py:193-196`)
gains exactly `brave`, `exa`, `tavily`, `searxng`. A second frozen set is
declared immediately beside it:

```python
WEB_SEARCH_PROVIDERS = frozenset({"brave", "exa", "tavily", "searxng"})
```

Everywhere this IDR says "web-derived", the predicate is exactly
`provider in WEB_SEARCH_PROVIDERS` (`src/hermes/tools/research_sources.py`).
This is the single definition; no other module may hardcode the four ids.

*Falsifiable:* a provider is web-derived iff its id is in that set, and the set
has exactly the four members. The gateway admission sites
(`gateway.py:3800`, `:3839`) and the template check
(`source_templates.py:85`) need **no edit** — they consult the same frozenset,
so the amendment propagates to admission automatically.

### D2 — Web provenance rides the outcome record, and is fenced at the evidence choke points

**The per-row artifact-type theory is withdrawn.** The previous draft added
`web_result` / `web_payload` to the closed taxonomy
(`src/hermes/persistence/source_outcomes.py:91-93`) and typed only the
*per-result* and *per-payload* rows. It left the parent **outcome** rows in the
scholarly taxonomy: a web search writes its outcome row as
`artifact_type="source_search"` (`source_outcomes.py:884`), a web fetch as
`source_fetch_outcome` (`source_outcomes.py:923`) — and both strings stay
positive-listed at every choke point. So `source_search:<hash>` and
`source_fetch_outcome:<hash>` resolved exactly like a paper-derived source: the
outcome-level hole the O2 gate redteam found. Marking rows was never the
mechanism; the mechanism is a **provider predicate on the row the choke point
already holds**.

**The marker.** Every web outcome row carries its contributing providers in the
outcome record's own metadata, under one new key:

```
providers — the sorted, de-duplicated provider ids that contributed to this
            outcome (e.g. ["arxiv", "brave"]); a row is web-derived iff
            `providers` intersects the D1 frozenset WEB_SEARCH_PROVIDERS
            (`src/hermes/tools/research_sources.py`).
```

`metadata_json` is one existing column (`repositories.py:862-865`), so this is
**a key, not a new column** — no new artifact type, column, table, index, or
intent kind. The predicate is set-based and conservative in the fail-closed
direction: a row is web-derived iff *any* contributing provider is in
`WEB_SEARCH_PROVIDERS`, so a mixed walk cannot launder a web leg through a
scholarly one. Exact predicates, never free-text scanning — the discipline N9
sets at `source_outcomes.py:167` applies to this projection too.

**Where the marker rides — two of the four types already carry provenance.**
This is why the new key is confined to the two outcome types:

| Row type | Carrier | Edit |
|---|---|---|
| `source_result` | `metadata.record.provider` — the lossless `SearchResult` round-trip (`research_sources.py:304-325`, `dataclasses.asdict`); `provider` is mandatory (`source_outcomes.py:518-530`, S6-B1) | **none** — the field exists |
| `source_payload` | `metadata.source_result_ref` (`source_outcomes.py:949-958`), dereferenced one hop to the `source_result` row above | **none** — the field exists |
| `source_search` | nothing | **new key** (E8) |
| `source_fetch_outcome` | nothing | **new key** (E8) |

**Proof that the marker cannot ride an existing outcome field.** Field by field,
on the *recorded* records — not on the in-memory carriers:

- **`request_log.provider` is absent on every successful search record.** The
  production path records the `combine` output
  (`src/hermes/research/source_handlers.py:505-515`, recorded at `:552-556`),
  and `combine` returns `SearchOutcome(..., request_log=None)`
  (`src/hermes/tools/providers/paginate.py:535-540`). `request_log` survives
  only on the two *shortfall* re-wraps — `EMPTY` (`source_handlers.py:517-527`)
  and `UNAVAILABLE` (`:535-545`) — so the field is present exactly in the
  failure records and absent in the success ones. It cannot carry a provenance
  predicate.
- **The fetch outcome has no provider field at all.** `_fetch_outcome_metadata`
  (`source_outcomes.py:1021-1067`) emits `outcome_kind`, `aggregate`, `notes`,
  `per_source`, `fetch_log`, `fetched_count`, `no_full_text_count`, and each
  `fetch_log` entry carries `source_ref`, `status`, `failure_class`,
  `hazard_verdict`, `size_bytes`, `content_hash`, `access_timestamp_utc`,
  `attempts`, `attempt_verdicts`. There is no field to ride.
- **The producing task's `spec_json` is a different row answering a different
  question.** `spec.provider` exists on both source templates
  (`src/hermes/research/source_templates.py:285`, `:358`) and is mandatory, but
  it names the *task's route*, not the *content's provenance*: a fetch
  outcome's `per_source` refs may resolve to another task's results, and a fetch
  that ran nothing carries no source at all. Reading it would also put an edge
  hop plus a JSON parse into three fail-closed resolvers whose contract is a
  cheap skip (`gateway.py:2680-2681`), and it would test the wrong proposition.
  The row's own metadata is the truthful carrier.
- **Nothing else on the row carries provenance.** `outcome_kind` is
  `"search"`/`"fetch"`; `aggregate` and `notes` are verdicts and free text;
  `artifact_type`, `size_bytes`, `storage_path` (`"inline://source_search"`),
  `producer`, `task_id` and `project_id` are structural; `content_hash` is the
  outcome hash, whose preimage is provider-blind (next paragraph).

**The marker is hash-neutral: no fixture, id, or digest moves.**
`outcome_record_hash` (`src/hermes/tools/research_sources.py:199-270`) builds
the `art_<hash>` identity from
`canonical(kind, aggregate, notes, per_source, request_facts)`; the two
`*_outcome_metadata` builders are not in that preimage and are not inputs to
it. Adding `providers` re-stamps no fixture and moves no `artifact_id` —
A12(d) asserts the equality rather than arguing it.

**Authoring rule.** `_search_outcome_metadata` (`source_outcomes.py:994-1018`)
takes the union of `{r.provider for r in outcome.per_provider}` with
`{request_log.provider}` when a log is present — the union is what makes the
marker total across both the success path (per-provider results) and the
shortfall paths (log only). `_fetch_outcome_metadata` (`:1021-1067`) takes
`{x.source.provider}` over `per_source`, `no_full_text`, and `failed`; when that
union is empty (a fetch that ran nothing), it falls back to the producing fetch
task's `spec.provider`, read with the accessor this class already uses
(`_spec_search_task_id`, `:981-989`). Every written outcome row therefore
carries a truthful `providers` list in every reachable case.

**Where the marker is read (the fence).** One pure read helper joins the
taxonomy seam beside `source_artifact_retracted` (`source_outcomes.py:159-181`),
same shape and same discipline — no writes, no exceptions, project scoping left
to its caller:

```python
source_artifact_is_web_derived(conn, artifact_id) -> bool
```

It dispatches on the row's type and reads only the carriers in the table above;
any other type, a missing row, or unparseable metadata returns `False`. Absence
of the key also returns `False`, and that is *provably* safe: no row can be
web-derived without `providers`, because the four web providers are unreachable
until the same slice amends the allowlist (D1) — the allowlist was the gate, and
the marker ships with it (A12 asserts the pairing).

*Falsifiable:* a web-derived row is skipped at both evidence resolvers (A5), the
payload hop is proven (A12(b)), and no `artifact_id` moves (A12(d)).

**Consequences, each of which is the point:**

| Position | Outcome | Mechanism |
|---|---|---|
| classification evidence ref | barred | explicit clause after the retracted check, `gateway.py:2695-2704` (E4) |
| contradiction qualification | barred | explicit clause on both resolver paths, `contradiction_candidates.py:87-105` (E5) |
| L2 upstream resolution | **resolves, by design** — it is retraction reach, not evidence admission (sole caller: the S5 retraction cone, `gateway.py:1692`) | the named exemption, E6 |
| ladder climb (SUPPORTED/ROBUST/REPLICATED) | barred, by derivation from the two clauses above | chain quoted in D3 |
| REFUTED terminus | barred — web text may not falsify either | the same evidence-set exclusion |
| N9 retraction | **reachable, unchanged** | `gateway.py:1383-1384`, `controller.py:1361-1362` — **no edit**; the previous draft's two taxonomy edits are withdrawn |
| redaction/injection advisory | active | `hazards.py:236-244` |

*Marking is relational and queryable — more so than the withdrawn draft
claimed.* The draft promised auditability through the artifact type; the marker
is now readable off the row that produced it — `metadata.providers` for an
outcome, `metadata.record.provider` for a result, `metadata.source_result_ref`
for a payload. A reviewer enumerates every web-derived row with one pass over
`artifacts.metadata_json`, and the predicate is the D1 frozenset, never a
hardcoded literal (D1's single-definition rule).

### D3 — N9 and prohibited-claims discipline apply unchanged, and web text is never scholarly evidence

- N9 fencing is untouched: `source_artifact_retracted`
  (`src/hermes/persistence/source_outcomes.py:159-181`) is type-agnostic, so a
  retracted web artifact is inadmissible exactly as a retracted paper is — and
  it is retraction-reachable with **no edit at all**: the web legs reuse the
  existing `source_search`/`source_result`/`source_payload` types, so
  `_S5_SOURCE_ARTIFACT_TYPES` (`src/hermes/research/gateway.py:1383-1384`) and
  the `src/hermes/research/controller.py:1361-1362` guard already reach them
  (§Acceptance A6).
- **Prohibited claims.** `docs/ARCHITECTURE.md` prohibits presenting replay as
  validity and a derived view as authority. Therefore: replay of a
  web outcome record proves byte determinism only; a vendor ranking is never an
  authority; a search snippet is never full text.
- **Untrusted text.** Web bodies reach a judgment surface only as
  `UntrustedContent` (`src/hermes/security/boundaries.py:34-60`), and the fetch
  content gate runs before artifact construction
  (`src/hermes/tools/providers/paginate.py:1217-1218`, hook declared at
  `src/hermes/tools/providers/base.py:170-181`). The advisory injection flag
  is narrower in practice for web text than for papers, so it is **not** a
  sufficient control: the seam that matters is that web text never becomes
  evidence (D2), not that it is flagged.
- **Ladder rule, stated plainly:** web-derived content may be a hypothesis
  input, a `CLAIM` subject, or a `CRITIQUE` target; it may not be supporting
  evidence for any climb, may not satisfy an obligation, and may not be a
  contradiction's evidence overlap. This is now **derived, not asserted**, and
  the derivation is short enough to quote end to end:
  1. the climb reads artifact *classes*, not sources: `RUNG_ORDER`
     (`src/hermes/research/evidence_ladder.py:32-36`) is
     `("SUPPORTED", "ROBUST", "REPLICATED")`, and `derive_obligation_rung`
     (`:55-88`) climbs only while
     `set(LADDER_OBLIGATIONS[rung].artifacts) <= satisfied` (`:83-87`), so the
     first unmet rung caps the climb;
  2. the required sets are the citable classes `pre_registered_experiment`,
     `statistical_analysis`, `validation`, `adversarial_critique`,
     `robustness_validation`, `out_of_sample_validation`, `regime_analysis`,
     `replication_report` (`src/hermes/research/programs.py:131-152`);
  3. a class counts only through a recorded satisfaction whose linked artifact
     carries a dereferenceable **PASS** validation verdict covering that
     artifact's content hash
     (`src/hermes/persistence/program_obligations.py:15`, `:28-34`, `:256-262`;
     the precondition is restated at `evidence_ladder.py:71-77`);
  4. a web artifact cannot be *linked* as evidence in the first place, because
     the evidence-ref resolvers that build a classification's evidence set are
     exactly the two fenced ones (D2 E4/E5) — so no web artifact can enter
     `satisfied_classes`, and every rung that would need one stays unmet. The
     citation form those resolvers dereference is
     `EVIDENCE_REF_PREFIX = "evidence:"`
     (`src/hermes/research/evidence_transitions.py:53`).
  Net: web text cannot climb a rung, and the reason is the exclusion clause,
  not a special case inside the ladder.

### D4 — An additive POST path on the transport, GET semantics byte-identical

`RequestSpec` (`src/hermes/tools/providers/base.py:97-105`) gains two fields
with defaults that preserve every existing call site:

```python
method: str = "GET"      # "GET" | "POST" — anything else refuses
body: bytes = b""        # POST body; empty means "GET semantics"
```

Rules, all falsifiable:

1. **Default identity.** A spec with `method="GET"` and `body=b""` builds the
   same URL and issues the same GET as today (`http.py:367`, `:449-457`), and
   the recorded normalized form is byte-identical. Existing fixtures do not
   re-stamp.
2. **Closed method set.** `method` outside `{GET, POST}` refuses
   `ProviderValidationError` (`research_sources.py:697-699`) at
   `build_request` time, before I/O.
3. **POST sends the body, never the params.** On POST the query string is
   built from the URL alone; `params` are the *declared* form for redaction and
   identity only. This prevents a credential-class param from being smuggled
   into a body while being redacted as a param.
4. **Content-Type** is set from the adapter's `content_type` attribute, never
   guessed; a POST with a non-JSON content type and an empty body refuses.
5. **`urlencode` is preserved** for GET unchanged (`http.py:456`).

**Body redaction at the recorder boundary.** `redact_params`
(`src/hermes/tools/providers/redact.py:81-95`) is typed `dict[str, str]` and
cannot carry a nested JSON body. A new `redact_body`
(`src/hermes/tools/providers/redact.py`, new function; `__all__` at `:28-35`)
recursively classifies **keys** under `DEFAULT_POLICY`
(`redact.py:52-58`: `api_key, apikey, key, token, access_token, auth, password,
secret, signature`; polite: `email, tool`), replacing a classified key's
subtree with `"<redacted>"` and preserving the rest structurally. Nested key
redaction has precedent in the model plane (`src/hermes/tools/models/router.py:701-718`);
the provider plane gets its own, because `redact.py` is the only recorder-
boundary authority (`redact.py:1-22`).

Its two edge policies are decided here, not left to the builder:

- **Unknown keys are scrubbed, never passed through.** `DEFAULT_POLICY` carries
  `default_deny=True` (`redact.py:52-58`), so a key that is neither a
  credential alias nor a polite class classifies as `default_deny` and its
  subtree becomes `"<redacted>"`. That is exactly the frozen behaviour
  `redact_params` already has (`redact.py:81-95` through `_classify`, `:61`):
  the *unknown* case **is** the deny case, so `redact_body` inherits the posture
  rather than inventing one. The vendor-declared load-bearing body keys (`query`, `numResults`, `max_results`) pass through verbatim (E11); every other unknown key still scrubs under `default_deny`.
- **A non-JSON or undecodable body refuses; it is never identity-hashed.**
  `redact_body` operates on the **decoded** object, so a body it cannot decode
  is a body it cannot redact — and the recorder must not fall back to hashing
  raw bytes: `fixture_id_of` (`replay.py:102-115`) keys the fixture identity on
  the recorded request, so an unredacted body-hash would put a
  credential-derived value into a fixture id, which is the exact egress the
  credential invariant below forbids. The refusal is frozen code already in the
  provider taxonomy: `RedactionError` (`src/hermes/tools/research_sources.py:49`,
  class at `:701-705` — "redaction could not run → no request is issued",
  naming the offending *parameter*, never its value). A JSON **content type**
  with an empty body refuses `ProviderValidationError` at `build_request` time
  (rule 4, `research_sources.py:697-699`) — before any I/O, hence before any
  recorder call. Both classes sit inside the existing vocabulary, so
  constraint 2 holds.

*Falsifiable:* a body with an unknown key round-trips to `"<redacted>"` at that
key and byte-identical everywhere else; a binary/undecodable body refuses
`RedactionError` and writes nothing; two POST bodies differing anywhere produce
two fixture ids (A7).

**Fixture identity with bodies.** `normalized_request`
(`src/hermes/tools/providers/replay.py:81-94`) gains a `"body"` key holding the
*redacted* canonical body for POST specs, and nothing for GET specs. So:

- two POSTs differing only in body get distinct fixture ids (otherwise one
  would replay the other's bytes — an evidence-substitution failure mode);
- a credential can never enter a fixture id or a fixture file, because the body
  is redacted first;
- GET fixture ids are unchanged (the key is absent), so the 11 existing
  provider corpora are untouched.

*Falsifiable:* GET normalized form is byte-identical to `ac1860a`; two POST
bodies yield two fixture ids; a body containing a credential-class key never
reaches the sink or the fixture file.

**The walk driver is untouched — and here is why, not as an assertion.**
`walk` (`src/hermes/tools/providers/paginate.py:197`) is vendor-agnostic: the
loop guard is `min(spec.cursor_rule.loop_guard, request.max_pages)`
(`paginate.py:220`, WS-03 at `:27-30`), `CURSOR_TRAP` fires before the
duplicate request (`:264-267`, WS-06), and `combine` serializes providers in the
caller's fixed order (`:450-472`, PS-05). The driver's only contact with a
provider is `adapter.build_request(...)` → `transport.request(spec)`
(`paginate.py:308`, `:658`) — the two seams D4 extends. No branch in `walk`
names a vendor, a method, or a body. **Cited, not assumed.**

### D5 — Vendor posture, per leg

| Leg | Terms / licensing | Credential shape & handling | Egress |
|---|---|---|---|
| **brave** | Commercial API, subscription. Code we ship is our own; no vendor source is copied. **ToS review REQUIRED before registration** (redistribution of results, rate-plan terms). | `X-Subscription-Token` request **header** only. Never in params/body/URL, never recorded (`replay.py:83-84` excludes `headers_meta`). | Vendor-hosted egress of the query text. Query text is operator research, not user PII. |
| **exa** | Commercial API. Same no-copy posture. **ToS review REQUIRED.** | `x-api-key` header (Bearer accepted upstream). Header-only. | Query text leaves the host; Exa also returns page text. Highest egress of the four. |
| **tavily** | Commercial API. Same. **ToS review REQUIRED.** | `Authorization: Bearer` header. Header-only. | Query text leaves the host. |
| **searxng** | **Self-hosted open-source instance** — the operator runs it; there is no vendor and no vendor ToS. Deployment-owned base URL. | Instance `auth` is a deployment concern; when used it is a header, never a param. | Operator's own infrastructure. **Lowest egress.** |

**A licensing/ToS review is a precondition, not a deliverable of the build
slice.** No live credential is configured by this slice; the legs are
registered but unreachable until an operator supplies one through the existing
deployment-credential path. This is the same posture as the existing
credential-carriers (`src/hermes/tools/providers/adapters/core.py:5-6`
"injected at request construction, never logged", with
`auth_policy="header"` at `core.py:23`).

**Credential invariant for all four:** credentials appear only in
`RequestSpec.headers_meta`, which `RecordedTransport` never records
(`replay.py:84-86`; `redact_headers` at `redact.py:107-123` masks
`Authorization`/cookies at `redact.py:38-40`), and never in `params`, a body, a
fixture, an error message, or a journal row.

### D6 — Refusals: the frozen vocabulary only

No new code is introduced anywhere in this slice. Every failure maps to an
existing member:

| Condition | Emitted | Anchor |
|---|---|---|
| unknown `method`; POST with no body; non-JSON POST content type | `ProviderValidationError` | `research_sources.py:697-699` |
| provider not in the allowlist (search) | `MALFORMED_PAYLOAD` | `gateway.py:3800-3806` |
| provider not in the allowlist (fetch) | `MALFORMED_PAYLOAD` | `gateway.py:3839-3847` |
| HTTP 429 | `THROTTLED` | `hazards.py:171-183`, evaluated `hazards.py:1192-1193` |
| HTTP 5xx | `TRANSIENT` | `hazards.py:1194-1195` |
| unclassified 4xx | `MALFORMED_200` | `hazards.py:1225-1229` |
| schema drift (missing declared field) | `MALFORMED_200` | `hazards.py:1287-1292` |
| provider error field inside HTTP 200 | `MALFORMED_200` | `hazards.py:1266-1278` |
| empty body | `EMPTY_RESULT` | `hazards.py:1251-1258` |
| oversized completed body | `PARTIAL_CONTENT` | `hazards.py:1119-1127` |
| repeated cursor / guard hit | `SHORTFALL(cause=CURSOR_TRAP)` | `paginate.py:264-267` |
| whole chain down | `ProviderUnavailableError` | `research_sources.py:676-694` |
| no fetch full text | `NO_FULL_TEXT` | `hazards.py:1384-1395` |
| instruction-like text | `INJECTION_SUSPECT` (advisory, non-recordable) | `hazards.py:1332-1338` |

### D7 — Hazard-spec authorship: data, one reviewer per spec

Per vendor, one `hazard_specs/<provider>.json`, validated at registration by
`load_hazard_spec` (`src/hermes/tools/providers/hazards.py:677`) and
**fail-closed** — an incoherent spec raises `SpecValidationError`
(`hazards.py:247-253`) rather than shipping. If a spec is absent, the walk
refuses the provider outright (`paginate.py:874-884`).

Required content per spec (all keys already in the allowed set,
`hazards.py:684-689`):

- `schema` = `hermes-hazard-spec/v1` (`hazards.py:187`) — mandatory;
- `provider_id` matching the filename;
- `required_fields` — the drift sentinel. Brave: `web`, `web.results`. Exa:
  `results`. Tavily: `results`. SearXNG: `results`.
- `throttle_signature` — status `429` for all four, plus a `fields`-scoped
  `body_pattern` only where the vendor returns an error object in HTTP 200
  (SearXNG `error`; Tavily `detail`). **Fields-scoped only**: an empty-`fields`
  pattern never fires on JSON-shaped content (`hazards.py:1015-1028`,
  HZ-01/HZ2-01/HZ2-02) — that is the false-positive-throttle trap.
- `count_semantics` — Brave/Exa/Tavily report no total → `"absent"`
  (`hazards.py:715-716`), which also forbids `counts_raw_rows: true`
  (`hazards.py:732-735`). SearXNG's `number_of_results` is an estimate →
  `"estimate"` **with** `counts_raw_rows: true` (`hazards.py:727-731`); this
  is the matrix the loader enforces and it makes the driver dedup before
  comparing (`paginate.py:724-727`).
- `cursor_rule` — `offset` for brave (page offset) and searxng (`pageno`);
  `none` for exa and tavily (neither paginates in a GET/POST search call),
  with `loop_guard` ≥ 1 and ≤ 1000 (`hazards.py:750-755`).
- `fetch` — **`null` for all four.** A web fetch returns third-party HTML with
  no provider-declared full-text structure; `fetch: null` means "no declared
  provider-specific fetch knowledge; the adapter's parse plus the generic
  content/size controls are the gate" (`hazards.py:1438-1448`). Declaring a
  `body_marker` for arbitrary web HTML would be fabricated content.
- `valid_negative_statuses` — `[404]` (the not-found family only,
  `hazards.py:232`); 401/403 are never an "answered no".
- `content_types` — `["application/json"]` for all four (`hazards.py:658-674`
  rejects wildcards and parameters).
- `rewrite_suspect` — empty for all four. The rule shape
  (`hazards.py:316-327`) tests for a *missing* field on records under a
  declared filter; for a ranked web index a missing field is normal, so a rule
  here would fire on honest responses. **Empty is the correct content.**

*Review rule:* each spec file requires review against that vendor's live
documentation by a named reviewer, recorded in the slice report, before the
provider is treated as reachable. The specs encode vendor behaviour, and
vendor behaviour changes.

### D8 — Shared adapter contract obligations

Each adapter declares tables only — no per-provider control flow
(`src/hermes/tools/providers/adapters/base_adapter.py:124-159`), and defines
**no** `def extract_ids` (the choke point is the shared
`JsonSearchAdapter.extract_ids`, `base_adapter.py:252-263`, and
`normalize_identifier` `src/hermes/tools/providers/normalize.py:138-155`).

Two obligations the shared contract test will apply once registered
(`tests/test_chg2_providers.py:478-501`, which iterates `PROVIDER_REGISTRY`):

1. `build_request(...)` returns a spec whose URL starts with `http`;
2. **`items_paths` must include `"items"`** for all four, because that test
   feeds `{"items": [{"id": …, "title": …}]}` (`:494-497`). Vendor-native paths
   come first; `"items"` is the shared-shape fallback.

`auth_policy`: `header` for brave/exa/tavily (mirroring
`src/hermes/tools/providers/adapters/core.py:23`), `none` for searxng
(instance auth is deployment configuration).

Raw identifier shape (required by
`tests/test_hr04_source_identifier_capture.py:601`): all four are web
providers whose canonicalizable identity is `url`. Per
`src/hermes/tools/providers/normalize.py:123-135` and `:236-241`, a non-resolver
URL yields `None` from `normalize_identifier`, and `url` is deliberately not a
dedup kind — so the declared raw shape for each is
`{"url": "https://<a real public page url>"}` and the record is expected to
canonicalize to `{}` for a non-resolver host (the test at `:608` asserts the
canonicalized equality; the `:611`/`:623` probes then assert the record still
parses). The builder must pick a real, stable, public URL per vendor and record
it; a DOI-resolver host is **not** acceptable, because it would canonicalize to
a DOI and drag web results into the scholarly dedup key
(`normalize.py:226-233`).

---

## Acceptance

The O2-BUILD slice is complete when all of the following hold.

- **A1** `set(SOURCE_PROVIDER_ALLOWLIST)` has 15 members; `WEB_SEARCH_PROVIDERS`
  has exactly the four web ids; the two sets intersect in exactly those four.
- **A2** `PROVIDER_REGISTRY` covers the allowlist with no drift (the existing
  import-time check, `src/hermes/tools/providers/adapters/__init__.py:51-54`,
  stays green).
- **A3** `walk` returns `NONE` for a golden success payload per vendor, and
  each shipped spec loads via `load_hazard_spec`.
- **A4** For every vendor: `THROTTLED` on 429; `MALFORMED_200` when
  `required_fields` is missing; `EMPTY_RESULT` on an empty body; `NONE` on a
  zero-result body (a web search with no hits is `EMPTY_RESULT`/shortfall,
  **never** a `VALID_NEGATIVE` claim of "no literature exists" — the PS-13
  discipline at `paginate.py` WS-07/`_single_provider_aggregate`).
- **A5** A web-derived row is **skipped at both evidence resolvers**: a
  `source_search:<hash>`, `source_fetch_outcome:<hash>`, `source_result:<hash>`,
  or `source_payload:<hash>` ref whose row is web-derived resolves to `None` —
  one test per site, asserting the skip contract at `gateway.py:2695-2704`
  (the ref contributes nothing to `_cx_classification_facts`'s evidence set)
  and at `contradiction_candidates.py:87-105` (nothing to the detector row's
  `evidence`), the latter on **both** the typed path and the bare-id path.
- **A6** Retraction reach is unchanged and needs no edit: a web artifact is
  still retraction-reachable (`gateway.py:1383-1384` seeds the cone with the
  existing `source_search`/`source_result`/`source_payload` types;
  `controller.py:1361-1362` accepts them), a retracted web artifact is
  inadmissible (N9), and `source_search`/`source_fetch_outcome` still resolve in
  `l2_resolution._l2_resolve_ref_to_artifacts` (`l2_resolution.py:105-107`) —
  asserted, so E6's exemption cannot be silently narrowed later.
- **A7** POST: two bodies differing only in body produce two fixture ids; the
  redacted body reaches no fixture and no sink; GET normalized form and GET
  fixture ids are byte-identical to `ac1860a`.
- **A8** Credentials: no leg places a credential in `params`, `url`, or `body`;
  `headers_meta` is absent from every recorded interaction and fixture.
- **A9** The zero-delivered matrix rows hold per vendor (searched-vs-ran,
  `paginate.py:39-40`, WK-01/02).
- **A10** Full suite green, `uvx ruff check src tests` clean,
  `uvx pyright src` clean, and `uvx pyright --project pyrightconfig.tests.json`
  clean.
- **A11** `git status --short` shows only the files in §5.
- **A12** The provider marker is authored and read as D2 specifies, with the
  expected behaviour named per site:
  (a) a web search outcome row carries
  `metadata.providers ∩ WEB_SEARCH_PROVIDERS ≠ ∅`, including the mixed-walk
  case (a web leg beside a scholarly leg), and a web fetch outcome row likewise
  from its contributing sources;
  (b) `source_artifact_is_web_derived` returns `True` for a web `source_result`
  (via `metadata.record.provider`) and for a web `source_payload` (via
  `metadata.source_result_ref`, **dereferenced one hop**), and `False` for a
  scholarly row and for a row whose provider field is absent;
  (c) presented to the classification resolver the web row is **skipped**
  (`None`); presented to the detector resolver it is **skipped** (`None`) on
  both paths; presented to the L2 resolver it **resolves** — retraction reach,
  E6 — and the clause marks that as intentional;
  (d) the marker moves no identity: the outcome hash of a web walk equals the
  hash computed with `providers` absent, and no recorded fixture re-stamps.

---

## Build-slice authorization — the EXACT existing-file edit list

**These are the only existing files O2-BUILD may edit, and only these line
ranges.** Anything not listed is forbidden; a needed change outside this list
is a new gate.

**New files (unrestricted):**
`src/hermes/tools/providers/adapters/brave.py`, `exa.py`, `tavily.py`,
`searxng.py`; `src/hermes/tools/providers/hazard_specs/brave.json`, `exa.json`,
`tavily.json`, `searxng.json`; `tests/test_provider_breadth.py`,
`tests/test_web_provenance_fence.py` (the A5/A6/A12 fence suite).

| # | File | Lines | Authorized edit |
|---|---|---|---|
| **E1** | `src/hermes/tools/research_sources.py` | `189-196` | Amend the `SOURCE_PROVIDER_ALLOWLIST` literal to 15 ids; update the `189-192` comment ("11 scholarly-retrieval providers" → scholarly + the four commercial web legs, with the D1 rationale); add `WEB_SEARCH_PROVIDERS` immediately after `:196`. |
| **E2** | `src/hermes/tools/research_sources.py` | `37` (`__all__`) | Add `"WEB_SEARCH_PROVIDERS"`. |
| **E3** | `src/hermes/tools/providers/adapters/__init__.py` | `13-28`, `37-49` | Four `from … import` lines in alphabetical position; four `PROVIDER_REGISTRY` rows. `:51-54` unchanged. |
| **E4** | `src/hermes/research/gateway.py` | `76` (import block); `2695-2704` | Import `source_artifact_is_web_derived`; add the web-exclusion clause **after** the retracted check, before `return row["artifact_id"]` — a resolved row that is web-derived returns `None` (skip). No other line moves. |
| **E5** | `src/hermes/research/contradiction_candidates.py` | `16`; `87-105` | Import the same helper; add the clause on **both** paths — the bare-id branch (`:87-92`, which has no type check at all) and the typed branch (`:100-105`) — each returning `None` when the resolved row is web-derived. |
| **E6** | `src/hermes/research/l2_resolution.py` | `52-63` | Add the **named exemption clause** (comment only, **no behaviour change**): `_L2_HASH_TYPED_PREFIXES` keeps `source_search`/`source_fetch_outcome` because this resolver's sole production caller is the S5 retraction cone; a web exclusion here would make a retracted web source unreachable and break A6. The clause names `WEB_SEARCH_PROVIDERS` and points at E4/E5 for the evidence bar. |
| **E7** | `src/hermes/persistence/source_outcomes.py` | new function after `:181`; `__all__` `:53-62` | Add the pure read helper `source_artifact_is_web_derived(conn, artifact_id)` — type-dispatched metadata read, no writes, no exceptions, `False` for unknown/absent — and export it. |
| **E8** | `src/hermes/persistence/source_outcomes.py` | `45-51` (import); `994-1018`; `1021-1067`; **erratum E8-ER1 (ratified at the O2 gate)** `1011` — the `_fetch_outcome_metadata(outcome, task_id)` call site (the `:1008` hunk): the E8 task-spec fallback is inert without the producing fetch task's id, and this call site is its only source | Import `WEB_SEARCH_PROVIDERS`; add the `providers` key to `_search_outcome_metadata` (union of `{r.provider for r in outcome.per_provider}` with `{request_log.provider}` when present) and to `_fetch_outcome_metadata` (`{x.source.provider}` over `per_source`/`no_full_text`/`failed`, falling back to the producing fetch task's `spec.provider` when that union is empty), sorted. **No** taxonomy, writer, hash, or fixture change. |
| **E9** | `src/hermes/tools/providers/base.py` | `97-105` | Add `method: str = "GET"` and `body: bytes = b""` to `RequestSpec` (D4). |
| **E10** | `src/hermes/tools/providers/http.py` | `358-373`, `449-457` | Branch on `spec.method`; POST passes `data=` + `Content-Type`, GET path byte-identical. |
| **E11** | `src/hermes/tools/providers/redact.py` | new function + `28-35` (`__all__`) | Add `redact_body` with the D4 edge policies: unknown key → `"<redacted>"` under `default_deny`; undecodable/binary body → `RedactionError`, never a raw byte hash. |
| **E12** | `src/hermes/tools/providers/replay.py` | `81-94` | Add the redacted `"body"` key for POST specs only (D4). |
| **E13** | `tests/test_hr04_source_identifier_capture.py` | `555-573` (`STEP1_RAW_SHAPES`), `575-591` (`STEP1_EXPECTED_CANONICAL`), `602`, `744` | Four `STEP1_RAW_SHAPES` entries (D8 URL rule) **and** the four matching `STEP1_EXPECTED_CANONICAL` entries — the withdrawn draft named only `555-575` and silently skipped the expected-canonical map that `:608` compares against; `602` `len(...)` 11→15; `744` shipped-spec list gains the four ids. `:601` needs no edit (set equality against the grown map). |
| **E14** | `tests/test_chg2_providers.py` | `472` | `len(PROVIDER_REGISTRY) == 11` → `== 15`. Line `471` needs no edit (it is a set equality that becomes true by construction). |
| **E15** | `docs/API.md` | `64` | "11 adapters" → 15. |
| **E16** | `docs/ARCHITECTURE.md` | `33` | "(11 adapters, …)" → 15. |

### Explicitly NOT authorized

- Any edit to `src/hermes/research/gateway.py:3800-3806` or `:3839-3847` —
  admission already follows E1; touching them would be sprawl.
- **Withdrawn theory, with the reason.** The previous draft forbade edits at
  `src/hermes/research/gateway.py:2691`,
  `src/hermes/research/contradiction_candidates.py:96`, and
  `src/hermes/research/l2_resolution.py:56-63` on the theory that the web bar
  was **bar by omission**. That theory is withdrawn (D2): the web legs write
  *existing* types (`source_search` at `source_outcomes.py:884`,
  `source_fetch_outcome` at `:923`) that are listed at all three sites, so
  omission bars nothing and the clause must be explicit. E4/E5/E6 authorize
  exactly those clauses — and **nothing else at those sites**: no prefix may be
  removed from a list, no other branch may change, and the L2 clause stays a
  comment (a behavioural narrowing there would break A6).
- Any edit to `src/hermes/tools/providers/paginate.py` — vendor-agnostic by
  construction (cited in D4).
- Any edit to `src/hermes/tools/providers/hazards.py` — the evaluator has zero
  per-provider branches (its module docstring, `hazards.py:6-14`); vendor
  knowledge is data only.
- Any new table, intent kind, refusal code, hazard class, or dependency.
- Any edit to the type taxonomy or the retraction set:
  `SOURCE_ARTIFACT_TYPES` (`source_outcomes.py:91-93`),
  `_S5_SOURCE_ARTIFACT_TYPES` (`gateway.py:1383-1384`), or
  `controller.py:1361-1362`. The outcome-level fence needs none of them — the
  previous draft's five taxonomy/retraction edits were exactly these, and their
  now-repurposed E4-E8 slots carry the fence edits instead of them.
- Any new column, index, or table for the marker. It is one metadata key inside
  the existing `metadata_json` column (D2), and no choke-point clause may
  JSON-scan free text (`notes`) to decide web provenance.
- Any change under `docs/archive/`.

### Sequence (the builder follows it; each step is independently green)

1. E9 + E10 + E11 + E12 + tests → POST transport green with GET byte-identity.
2. E1 + E2 + E13 + E14 + E15 + E16 → allowlist amended, gates green.
3. Four adapter modules + four specs + `tests/test_provider_breadth.py` →
   contract + hazard regression green.
4. E3 → registry rows; the shared contract test
   (`test_chg2_providers.py:478-501`) now covers the new adapters.
5. E7 + E8 + E4 + E5 + E6 + `tests/test_web_provenance_fence.py` → the
   provider marker authored and read, the evidence bar skip-proven at both
   resolvers, the payload hop and the L2 exemption asserted, and retraction
   reach proven unchanged.
6. Full suite, ruff, pyright ×2.

---

## Relation-to-baseline

**Certified invariants touched: none.** No new intent kind, no new table, no
new writer, no change to `apply_intent` (`gateway.py:4038`), no change to
project isolation or content-hash identity. The changes are: one additive
frozenset; **one additive metadata key** on the source-slice outcome rows (a
key inside the existing `metadata_json` column — no new type, column, table, or
index); **one additive pure read helper** (`source_artifact_is_web_derived`, no
writes and no exceptions — the `source_artifact_retracted` shape); two additive
transport fields with GET-preserving defaults; one new pure redaction function;
and three evidence-resolver clauses (two behavioural exclusions plus one
documented exemption). The artifact-type taxonomy (`source_outcomes.py:91-93`)
and retraction reach (`gateway.py:1383-1384`, `controller.py:1361-1362`) are
**untouched** — the previous draft's five taxonomy edits are withdrawn.

**IDR-030 amended, deliberately and narrowly.** `research_sources.py:189-192`
records the ratified "11 scholarly-retrieval providers" allowlist (OQ-5). This
IDR amends it to 15 and states the amendment's boundary: the four new members
are (a) web-index providers, not bibliographic ones, and (b) barred from every
evidence position (D2/D3). IDR-030's own decision points are untouched;
nothing about the source slice's contract, admission, or replay changes.

**Deferred by this IDR, on purpose:** vendor ToS review (D5 precondition, not a
build deliverable); any use of web content as *supporting* evidence (would need
its own provenance gate); and live endpoint verification beyond the documented
shapes (the specs are the place that knowledge lives, reviewed per D7).

**Relationship to the OpenHuman audit.** `ADOPTION_AUDIT_R2.md` §4 B3 rated
general-web search as a *need* (R6 declares `WEB_SEARCH`; no such provider
exists) and as borrowable-as-pattern only. This IDR is the ratification that
B3 assumed and did not have. Its B1 sidecar seam is unrelated and unaffected.
