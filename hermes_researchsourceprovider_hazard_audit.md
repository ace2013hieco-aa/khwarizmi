# Adversarial Audit — ResearchSourceProvider Hazard Evaluator (Step 2, shipped code)

**Scope:** protest-stage attack on the **implemented** step-2 artifacts — `src/hermes/tools/providers/hazards.py` and the four shipped `hazard_specs/{arxiv,pmc,europepmc,openalex}.json` — against the ratified contract (§5.1/§5.2/§5.3) and the design blueprint §4. Method: hunt bypasses and silent-failure paths in marker precedence, the fetch-scope 404 path, throttle ordering, and the registration matrix. Every finding below was **reproduced against the running code** (probe evidence quoted); none is a reading of the text. The implementation's own green fixtures were treated as the claims under test, not as proof — the probes attack inputs the 52 fixtures do not cover.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| HZ-01 | **P1** | throttle ordering / spec content | **Throttle `body_pattern`s are unanchored substring searches over the ENTIRE canonical payload** — a legitimate result whose title/abstract mentions "Rate exceeded" (arXiv) or "too many requests / rate limit" (EuropePMC) is classified `THROTTLED`, retried to exhaustion, and the real results are lost. Both shipped specs are affected (probes 1, 4) |
| HZ-02 | **P1** | pmc.json fetch rules | The `retraction_marker` is **presence-only over `pub-history`**, which legitimately carries non-retraction events (`received`/`accepted`/`revised`) — a **normal** PMC article with a publication history is mislabeled `NO_FULL_TEXT(REMOVED_OR_RETRACTED)` (probe 3). The presence-only `FieldPath` cannot express `event-type == retraction` |
| HZ-03 | **P1** | fetch-scope 404 path | `no_full_text_status` is **only honored when it equals 404** — any other declared status (410 Gone is the real-world case) is unreachable: step 1's unclassified-4xx path fires `MALFORMED_200` before step 6a (probe 2). Latent contract bug the step-5 adapters would inherit silently |
| HZ-04 | **P2** | fetch-scope blindness | Search-shape skip leaves **undeclared-fetch providers with zero fetch hazard knowledge**: `europepmc` errCode in a fetch 200 → `NONE` (SEARCH → `MALFORMED_200`), arXiv "Error" entry at fetch scope → `NONE` (probes 10/11). `arxiv.json` ships `fetch: null` despite arXiv having a real fetch surface; the PS3-05b enforcement point is unimplemented |
| HZ-05 | **P2** | marker precedence | **Fetch-scope markers are first-value-only while search markers are any-value** — a wildcard fetch marker with an empty leading element silently misses (probe 5). The generic marker contract is inconsistent across scopes |
| HZ-06 | **P2** | registration matrix | Unbounded and dead-content registrations: `loop_guard` accepts 10⁹ (probe 6, effectively unbounded walks), `valid_negative_statuses` consults only 404 (probe 7, non-404 entries are dead content), throttle `status` accepts any int, `no_full_text_status` accepts any int (HZ-03), and `empty_body_rule: valid-negative` × `valid_negative_statuses: []` is an incoherent combination with no check |
| HZ-07 | **P3** | markers | `equals` is exact and whitespace-sensitive — a padded `"Error "` value silently misses the arXiv marker (probe 9); the exactness contract is unstated |
| HZ-08 | **P3** | status precedence | 1xx statuses are labeled "unclassified 4xx — permanent validation failure" (probe 8); and a declared-valid-negative 404 returns `VALID_NEGATIVE` before the throttle signature is consulted — the step-1-before-step-2 precedence surprise mirrored in HZ-03 |
| HZ-09 | **P3** | registration | `required_fields`/marker paths are unverifiable at registration — a typo'd path silently never fires the drift sentinel; the golden-fixture corpus is the only enforcement point and that gate is unstated |
| HZ-10 | **P3** | spec content | The spec-file format has no schema version — `version` is per-provider *content* version; a future change to the spec schema (load_hazard_spec's accepted keys) has no migration discipline |
| HZ-11 | **P3** | HazardContext | `endpoint` is a dead field — never consulted, never recorded; either wire it into verdict evidence or drop it |
| HZ-12 | **P3** | registration | `marker.failure_class` accepts the full `HAZARD_CLASSES` set — a marker declaring `NONE` or `TRANSIENT` is incoherent content design with no registration check (results classes `VALID_NEGATIVE`/`NO_FULL_TEXT` are legitimate marker targets) |

## Detail

**HZ-01 — A legitimate result can be silently throttled. (P1)**

`_throttle_matches` runs `re.search(body_pattern, text)` where `text` is the **canonical JSON of the whole response** (`_text_of` → `canonical_json(payload)`) — titles, abstracts, and all. The shipped signatures are unanchored:

```
arxiv.json:     "body_pattern": "Rate exceeded\\.?"
europepmc.json: "body_pattern": "too many requests|rate limit"
```

Probe 1 — a **normal one-hit arXiv feed** for a rate-limits paper:
`{"feed": {"entry": [{"title": "Rate exceeded in API gateways: a survey", …}]}}` → **`THROTTLED`** (recordable). Probe 4 — a normal EuropePMC search whose abstract says "we discuss rate limit enforcement in APIs" → **`THROTTLED`**. The walk then backs off, retries the identical request, gets the identical verdict, and after `max_retries` raises a typed failure — the query about rate limits silently fails every time. This is the exact silent-loss class the slice exists to close, inverted: the hazard detector itself discards real content. The arXiv `Rate exceeded.` throttle is documented as a plain-text whole-body error; anchoring (`^Rate exceeded\.?$` against a text/plain body) or field-scoping (error-field-only matching) is required, and the EuropePMC pattern must not search result content at all. **Both shipped specs need content fixes; the evaluator needs an anchor/scope rule for body patterns.**

**HZ-02 — The retraction marker mislabels normal articles. (P1)**

`FetchHazardRules.retraction_marker` is a bare `FieldPath` — **presence is the signal** (a non-empty value at the path → `REMOVED_OR_RETRACTED`). The shipped `pmc.json` declares `"retraction_marker": "pmc-articleset.article.pub-history"`. But JATS `pub-history` is a container of `<event>` elements whose `<event-type>` values include `received`, `accepted`, `revised`, `corrected` — **and** `retraction`/`withdrawal`. Probe 3: a perfectly normal article with `pub-history: {event: {event-type: "received"}}` and a full `<body>` → **`NO_FULL_TEXT` with kind `REMOVED_OR_RETRACTED`**; probe 3b, the same article without `pub-history` → `NONE`. A normal full-text article is silently reported as retracted — the PS3-03 protection inverted (there, a retraction must never be masked as `NOT_OA`; here, every publication-history-bearing article is masked as retracted). The presence-only structure cannot express "`event-type` equals retraction/withdrawal". **Fix: value semantics — a `retraction_pattern` (or a marker-shaped predicate) in `FetchHazardRules`, evaluated generically; `pmc.json` as shipped is unsafe and must not reach an adapter.**

**HZ-03 — `no_full_text_status` only works when it equals 404. (P1)**

Step 1 defers exactly one status at fetch scope: `if status == 404 and fetch_scope`. Every other non-2xx goes to the unclassified-4xx/5xx paths, which return **before** step 6a's `no_full_text_status` check ever runs. Probe 2: `europepmc` with `no_full_text_status: 410` (Gone — the semantically correct "no full text" signal) and a fetch response at status 410 → **`MALFORMED_200`**, not `NO_FULL_TEXT`. The field's name and the blueprint ("no_full_text_status (europepmc 404 → NO_FULL_TEXT)") present it as a general status mapping; the code honors exactly one value. No shipped spec is wrong today (all four use 404 or null), but the *generic evaluator* claim is false for the declared field surface, and the step-5 adapters would inherit the silent misclassification (a `410 Gone` fetch becomes a permanent failure instead of a citable `NoFullText`). **Fix: defer any status that equals `spec.fetch.no_full_text_status` at fetch scope (generalize the deferred-404 branch), or narrow registration to reject non-404 `no_full_text_status` until the generalization lands.**

**HZ-04 — Fetch-scope blindness for undeclared fetch surfaces. (P2)**

The search-shape skip (blueprint §4.1) is correct for JATS payloads, but it applies even when the spec declares **no fetch rules at all** — `arxiv.json` ships `fetch: null` and `europepmc`'s fetch block has no `error_field` equivalent. Probe 10: `europepmc` errCode in a **fetch** 200 → **`NONE`** (the same payload at SEARCH → `MALFORMED_200`); probe 11: arXiv "Error" entry at fetch scope → **`NONE`**. A provider error page at fetch scope is reported as "no hazard" and handed to the adapter parse. The blueprint's PS3-05 rule (b) — "no fetch rules on a spec whose provider has no fetch surface" — is the enforcement point, but it is unimplemented (no adapter registry exists yet, and the spec's `fetch: null` *is* the current declaration of "no surface"). **Fix: registration must require a fetch block (or an explicit `fetch_surface: false`) when an adapter registers a fetch hook (the step-5 wiring), and the errCode-in-fetch-200 case needs a declared home (fetch-scoped error-field or an explicit "falls to the adapter parse" statement).**

**HZ-05 — Fetch markers and search markers disagree on list semantics. (P2)**

Search markers (`_marker_matches`) are **any-value**: a wildcard path fires if any resolved value matches. Fetch-scope markers (`retraction_marker`, `no_full_text_marker`) consult **only `values[0]`**. Probe 5: `no_full_text_marker: "body.signal.*"` with payload `{"body": {"signal": ["", "no full text"]}}` → **`NONE`** — the empty leading element masks the real signal. One generic evaluator, two presence semantics. The shipped specs use non-wildcard fetch paths so nothing ships wrong today, but the generic contract is inconsistent. **Fix: unify to any-value for fetch markers too, or reject wildcard paths in fetch markers at registration and state the first-value convention.**

**HZ-06 — The registration matrix has unbounded and dead-content corners. (P2)**

Fail-closed registration is the slice's guarantee that "a spec that violates the matrix never ships a contradiction the driver must interpret." Four corners violate that promise:
- **`loop_guard`** accepts any positive int — probe 6: `loop_guard: 1_000_000_000` registers cleanly. A bad spec ships an effectively unbounded pagination walk (the CURSOR_TRAP guard never fires). Needs an upper bound (or a driver-side hard cap).
- **`valid_negative_statuses`** is consulted only when `status == 404` — probe 7: `[410]` registers but a 410 → `MALFORMED_200`. Non-404 entries are dead content; restrict to `{404}` or generalize the consult.
- **throttle `status`** accepts any int (999, negative) — dead content never matched.
- **`empty_body_rule: valid-negative` × `valid_negative_statuses: []`** — "an empty body is an answered no" while "no 404 is a valid negative" is an incoherent combination with no registration check.

**HZ-07 — `equals` markers are exact, whitespace-sensitive. (P3)** Probe 9: arXiv title `"Error "` (trailing space) → **`NONE`** — the catalog's one-hit error case silently degrades to a normal result. The audited source documents the exact title, so the shipped spec is faithful, but the generic `equals` contract should state exactness (or strip) so future specs don't ship padded-value misses.

**HZ-08 — 1xx statuses are mislabeled; VALID_NEGATIVE preempts throttle. (P3)** Probe 8: status 199 → reason `"HTTP 199 (unclassified 4xx — permanent validation failure)"` — a 1xx is not a final response and is not a 4xx; the label and the permanent classification are both wrong (the transport should never deliver 1xx, but the evaluator's reason must not lie). Separately, the step-1 `VALID_NEGATIVE` branch returns before step 2 — a 404-with-throttle-body on a valid-negative-declared provider is "answered no", never transient; the same precedence surprise as HZ-03, undocumented.

**HZ-09 — `required_fields`/marker paths are unverifiable at registration. (P3)** A typo'd path (`feed.entr`) is a valid non-empty string; the drift sentinel silently never fires. Registration cannot validate paths without a payload, so the enforcement point is the golden-fixture corpus (each spec's real response shapes) — that gate is currently unstated and must be a standing rule for any spec change.

**HZ-10 — The spec-file format has no schema version. (P3)** `version` is per-provider content version; a future change to the spec *schema* (the keys `load_hazard_spec` accepts) has no migration/back-compat discipline. The engineering-plane version-bump rule covers content; it does not cover the format.

**HZ-11 — `HazardContext.endpoint` is a dead field. (P3)** Never read, never recorded in `detected_by`. Either wire it into the verdict evidence (per-endpoint hazard knowledge) or drop it.

**HZ-12 — Marker failure classes are unconstrained. (P3)** `_load_marker` accepts any `HAZARD_CLASSES` member — a marker declaring `NONE` or `TRANSIENT` registers fine and produces incoherent verdicts (a "matching" marker that returns `NONE`, or a content marker that routes the driver into transient retry). `VALID_NEGATIVE`/`NO_FULL_TEXT` are legitimate marker targets (Unpaywall `is_oa:false`); the registration should reject `NONE`/`TRANSIENT`/`INJECTION_SUSPECT` as marker classes.

## Interaction with the design's own guarantees

| Guarantee | Status after this audit |
|---|---|
| "One generic evaluator, zero per-provider branches" | **Holds structurally, false in behavior for two declared fields** — `no_full_text_status` (HZ-03) and throttle body patterns (HZ-01) are only correct for the shipped 404 / plain-body cases |
| "Spec content, fail-closed at registration" | **Holds for the enforced matrix; four corners escape** (HZ-06), and path typo's have no registration-time check (HZ-09) |
| "PS3-01: VALID_NEGATIVE unreachable at fetch scope" | **Holds** — no probe reopened it; the fetch-404 short-circuit works for the shipped 404 case |
| "PS3-02/PS3-03: empty body never a valid negative; retraction never NOT_OA" | PS3-02 holds; **PS3-03 is inverted by spec content** — HZ-02 mislabels normal articles as retracted |
| "PS3-08: marker over status; MALFORMED_200 over PARTIAL_CONTENT" | **Holds** for the tested cases; the first-value marker semantics (HZ-05) are an unstated divergence |
| Recordable discipline, frozen verdicts, evidence basis in `detected_by` | Holds — no probe reopened |

## What survives

The spine is real: one generic evaluator reading spec content, the enforced count-semantics and fetch-coherence registration matrix, the fetch-scope 404 short-circuit for the shipped 404 case, the search-shape skip, the drift sentinel, the advisory injection flag, recordable discipline, and frozen verdicts with evidence in `detected_by`. The 52 green fixtures are all genuinely green and none of the probes contradicts them — the failures are in inputs the fixtures do not cover (legit content containing throttle phrases, non-retraction `pub-history`, non-404 no-full-text statuses).

## Overall verdict: **MERGE WITH REMEDIATION.**

Three P1s are gate-blocking for an honest "IMPLEMENTED + TESTED" claim on step 2: **HZ-01** and **HZ-02** are shipped-spec defects that silently mislabel real traffic (a legitimate rate-limits query fails every time; a normal PMC article is reported retracted), and **HZ-03** is a latent contract bug the step-5 adapters would inherit without any error. The fixes land in the same module and the two affected spec files — anchored/field-scoped throttle patterns, value-semantics retraction detection, the generalized (or 404-narrowed) `no_full_text_status` deferral, plus the registration completions — no redesign, no new components. The fold-in of HZ-01…HZ-12 into `hazards.py`, the shipped specs, and the regression fixtures is the standing condition before step 3 proceeds.

---

## Remediation disposition (all twelve folded in — 2026-08-13, verified by re-running every probe)

| ID | Fix | Where it landed | Probe re-check |
|---|---|---|---|
| HZ-01 | `ThrottleSig.fields` — a `body_pattern` matches the RAW text of a plain-text payload (anchored `^Rate exceeded\.?$`) or ONLY the declared error-field values of a dict payload; a pattern with no fields never searches dict content | `hazards.py` `_throttle_matches` + registration; `arxiv.json` (anchored) + `europepmc.json` (`fields: ["errMsg"]`) + `pmc.json` (`fields: ["error"]`) | legit arXiv title / EuropePMC abstract → `NONE` (was `THROTTLED`); `Rate exceeded.` body and `errMsg`/`error` field bodies still → `THROTTLED` |
| HZ-02 | `FetchHazardRules.retraction_marker` + `retraction_pattern` — VALUE semantics: any resolved value matching the pattern → `REMOVED_OR_RETRACTED`; bare presence is never the signal; the pair must travel together (registration) | `hazards.py` `_retraction_marker_hit` + registration; `pmc.json` → `retraction_marker: "…pub-history.event.event-type"`, `retraction_pattern: "retract|withdraw"` | normal `received` pub-history → `NONE` (was `REMOVED_OR_RETRACTED`); `retraction`/`withdrawal` event-type → `REMOVED_OR_RETRACTED` |
| HZ-03 | Generalized deferral: any status equal to `spec.fetch.no_full_text_status` is deferred at fetch scope (not just 404); registration restricts the field to 4xx-except-429 | `hazards.py` step 1 `deferred_status` + registration | fetch 410 with `no_full_text_status: 410` → `NO_FULL_TEXT` (was `MALFORMED_200`) |
| HZ-04 | `FetchHazardRules.error_field` — a fetch-scoped error field (an `errCode` inside a fetch 200 is `MALFORMED_200`, not `NONE`); `fetch: null` documented as "no fetch hazard knowledge declared — adapter parse is the fetch-level gate" with the step-5 registration enforcement point stated | `hazards.py` 6a + registration (never-fire check); `europepmc.json` fetch block | europepmc errCode in fetch 200 → `MALFORMED_200` (was `NONE`) |
| HZ-05 | Fetch-scope markers are ANY-value (search-marker semantics): a wildcard `no_full_text_marker` with an empty leading element fires; `resolve_field_path` descends a dict-key segment into every list element | `hazards.py` `_no_full_text_marker_evidence` + `resolve_field_path` | `body.signal.*` with `["", "no full text"]` → `NO_FULL_TEXT` (was `NONE`) |
| HZ-06 | Registration closures: `loop_guard` capped at 1000; `valid_negative_statuses` restricted to 4xx-except-429 with a generalized consult (`[410]` now works); throttle `status` restricted to 4xx; `no_full_text_status` restricted to 4xx-except-429; throttle `fields` require a `body_pattern`; `empty_body_rule: valid-negative` requires non-empty `valid_negative_statuses` | `hazards.py` `load_hazard_spec` | `loop_guard: 10⁹` → rejected; `[410]` search 410 → `VALID_NEGATIVE`; `[429]`/`[500]` → rejected; throttle `status: 999` → rejected |
| HZ-07 | `equals` compares the whitespace-stripped resolved value | `hazards.py` `_marker_matches` | arXiv `"Error "` (padded) → `MALFORMED_200` (was `NONE`) |
| HZ-08 | Unclassified reason now "unclassified non-2xx — permanent validation failure"; the valid-negative decision waits for step 2 (throttle evidence wins) | `hazards.py` step 1/2 | status 199 → reason contains "non-2xx", never "4xx"; declared-valid-negative 404 with throttle body → `THROTTLED` |
| HZ-09 | `_validate_path` structural path check (no empty segments / leading-trailing dots / whitespace) at registration; the golden-fixture corpus stated as the payload-level gate | `hazards.py` registration | `"a..b"`/`".a"`/`"a."`/`"a b"` → rejected |
| HZ-10 | `SPEC_SCHEMA = "hermes-hazard-spec/v1"` required in every spec file (missing/mismatched → registration error); all four shipped specs carry it | `hazards.py` + `hazard_specs/*.json` | spec without `schema` / with `"old/v0"` → rejected |
| HZ-11 | `HazardContext.endpoint` joins the verdict evidence when set | `hazards.py` `base_evidence` | `endpoint` recorded in `detected_by` when provided, absent when not |
| HZ-12 | Marker `failure_class` restricted to the marker class set (`NONE`/`TRANSIENT`/`INJECTION_SUSPECT`/`CURSOR_TRAP` rejected) | `hazards.py` `_MARKER_CLASSES` + `_load_marker` | `NONE`/`TRANSIENT`/`INJECTION_SUSPECT`/`CURSOR_TRAP` markers → rejected |

**Status:** all twelve folded into `hazards.py`, the four shipped specs, and 19 regression fixtures in `tests/test_provider_hazards.py` (71 fixtures, 679 passed suite-wide, pyright 0 errors). The three P1 probe classes re-verified against the running code: legitimate content is never throttled, normal `pub-history` is never a retraction, and any declared no-full-text status is honored. The step-2 gate is now IMPLEMENTED + TESTED with the audit folded in; the HZ dispositions are closed and the slice may proceed to step 3 (the walk driver).
