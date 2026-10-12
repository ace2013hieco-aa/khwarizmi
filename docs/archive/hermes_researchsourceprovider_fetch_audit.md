# Adversarial Audit — Hazard Evaluator, Fetch Surface (pre-step-3 gate)

**Scope:** protest-stage attack on the **fetch surface** of the shipped `src/hermes/tools/providers/hazards.py` — the step 6a rule block (retraction → `no_full_text` → fetch `error_field` → fetch required-fields drift → the `body_required` composite → the PS3-02 fall-through), the `FetchHazardRules` registration rules, and the shipped `pmc.json`/`europepmc.json` fetch blocks. Method: attack the composite and fall-through rules for the same bypass/silent-failure classes the fetch surface was built to close — silent empty artifacts, silent error acceptance, and dead/never-firing rule combinations — treating the HZ/HZ2 closures as settled only where the shipped code actually enforces them. Every finding below is reproduced against the running evaluator with probes (each finding quotes the actual verdict output); no finding is a reading claim. This audit runs **before step 3** (the walk driver) so the driver is not built on top of a fetch surface with open holes.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| FS-01 | **P1** | `body_required` composite + fall-through | **Present-but-empty is only checked at the resolved-value granularity** — a body that is a structurally non-empty dict with all-empty leaves (`{"sec": ""}`) is treated as a PRESENT body → `NONE` → the walk admits a `FetchedSource` with zero content. Reachable with the **shipped** `pmc.json` path, no spec-author error (probe J) |
| FS-02 | **P1** | fetch `error_field` | **First-value-only error detection** — an error code hidden behind a leading benign value in a list-shaped payload is missed → `NONE` → an error response is silently admitted as full text. HZ-05 unified fetch *markers* to any-value; the `error_field` kept `values[0]` (probe D) |
| FS-03 | **P2** | 6a ordering | **Retraction masks a fetch error** — a 200 with `errCode` evidence AND a retraction event is classified `NO_FULL_TEXT` (a RESULT), not `MALFORMED_200`; PS3-08's dominance principle (error evidence beats body verdicts) is violated by the 6a ordering (probe A) |
| FS-04 | **P2** | 6a ordering | **`no_full_text` marker masks a fetch error** — same ordering family: marker evidence runs before the `error_field`, so a broad marker + `errCode` 500 → `NO_FULL_TEXT`, never `MALFORMED_200` (probe H) |
| FS-05 | **P2** | registration | **`body_required: false` + a declared `body_marker` is incoherent** — the unconditional fall-through still turns an absent body into `EMPTY_RESULT`, so the only effect of `false` is relabeling `PARTIAL_CONTENT` → `EMPTY_RESULT`; "body not required" is a lie in the schema (probe E) |
| FS-06 | **P2** | registration | **`body_required: true` + `metadata_marker: null` ships a dead composite** — the composite's guard (`metadata_marker is not None`) makes it never fire, and `body_required` has no other effect; the HZ2-05 dead-content class, unfixed in the fetch block (probe F) |
| FS-07 | **P3** | throttle × fetch scope | **Search-shaped throttle signatures are scope-blind** — pmc's search `error`-field signature fires on a FETCH-scope payload containing an `error` key; a latent trap for step-5 adapters (no shipped spec is wrong today) (probe G) |
| FS-08 | **P3** | composite presence | **Composite presence is first-value-only vs the HZ-05 any-value unification** — a wildcard metadata path with a leading empty element misclassifies `PARTIAL_CONTENT` → `EMPTY_RESULT` (diagnostic fidelity, both typed failures) (probe C) |

## Detail

**FS-01 — Present-but-empty bodies slip past BOTH the composite and the fall-through. (P1)**

PS3-02's rule — *"present-but-empty counts as absent"* — is implemented as `_is_empty_value(body[0])` on the **resolved value itself**. For the shipped `pmc.json`, the body marker is `pmc-articleset.article.body`, which resolves to a **dict**. `_is_empty_value` on a dict is `not value` — a dict whose *leaves* are all empty is structurally non-empty, so it is "present". The composite (`metadata present AND body absent-or-empty`) does not fire, and the fall-through (`body_marker declared + no body content → EMPTY_RESULT`) does not fire either. Probe J, with the **shipped** `pmc.json`:

```
payload = {"pmc-articleset": {"article": {
    "front": {"article-meta": {"title": "T"}},
    "body": {"sec": ""}}}}          # an article whose body is all-empty
→ NONE  (hazard_class="NONE", "no hazard detected")
```

The walk driver will classify this `NONE` → parse → **admit a `FetchedSource` whose content is empty** — the silent empty artifact the fetch surface was built to close, reachable with a real feed shape (whitespace-only `<sec>` bodies are routine) and **no spec-author error**. The same hole exists at the composite side: `{"sec": ""}` with the front present is not `PARTIAL_CONTENT`. **Fix: recursive emptiness** — a dict is empty iff all its values are recursively empty; a list iff all its elements are; strings/bytes via `strip()`. `_is_empty_value` gains the recursion and both call sites inherit it (the shipped fixtures — `{}` bodies, `""` bodies, full-text bodies — are unaffected).

**FS-02 — The fetch `error_field` is first-value-only: an error behind a benign value is silently accepted. (P1)**

HZ-05 unified fetch **markers** to any-value ("fetch markers are any-value, robust to list shape — single-vs-repeated XML elements"), but the fetch `error_field` check kept the search-shape form: `values and re.search(code_pattern, str(values[0]))`. With a wildcard error path — exactly the shape HZ-05 was built for — a response whose first code is benign and whose second is an error is classified `NONE`. Probe D:

```
fetch.error_field = {"name": "errCodes.*.code", "code_pattern": "5[0-9][0-9]"}
payload = {"article": {"front": {...}, "body": {"sec": "x"}},
           "errCodes": [{"code": "200"}, {"code": "503"}]}
→ NONE  (hazard_class="NONE", "no hazard detected")
```

An error response is admitted as full text — the **silent-acceptance** inversion of the silent-loss class. The shipped `europepmc.json` errCode is a leaf string, so nothing ships wrong today, but the mechanism is the exact first-value trap HZ-05 removed from the markers. **Fix: any-value** — `any(re.search(code_pattern, str(v)) for v in values)`, matching the marker semantics (leaf discipline: only `str` values).

**FS-03 — Retraction evidence masks a fetch error. (P2)**

6a runs retraction first, then `no_full_text`, THEN the `error_field`. A spec that declares both a retraction marker and an `error_field` — e.g. a JATS-capable provider with a European-API-style error envelope — classifies a 200 error response with a coincident retraction-shaped field as `NO_FULL_TEXT`, a RESULT that records "no full text" instead of the `MALFORMED_200` failure. Probe A:

```
fetch = {retraction_marker: "article.pub-history.event.event-type",
         retraction_pattern: "retract|withdraw",
         error_field: {"name": "errCode", "code_pattern": ".+"}}
payload = {"article": {"front": {...}, "body": {"sec": "x"},
                       "pub-history": {"event": [{"event-type": "retraction"}]}},
           "errCode": "503", "errMsg": "boom"}
→ NO_FULL_TEXT  ("retraction marker ... matched the retraction pattern")
```

PS3-08's own dominance principle — `MALFORMED_200` (required-fields drift) dominates `PARTIAL_CONTENT` when both would fire — says error evidence dominates body verdicts. The `error_field` is the same class and should run **before** the retraction and `no_full_text` result-classifications. **Fix: reorder 6a** — `error_field` → fetch required-fields drift → retraction → `no_full_text` → composite → fall-through.

**FS-04 — `no_full_text` marker evidence masks a fetch error. (P2)**

Same family, cheaper probe: `marker_evidence` (any non-empty resolved value) is checked before the `error_field`. A broad marker (a field present in every article) plus an `errCode` 500 in the same 200 → `NO_FULL_TEXT`, never `MALFORMED_200`. Probe H:

```
fetch = {no_full_text_marker: "article.front.article-meta", no_full_text_status: 404,
         error_field: {"name": "errCode", "code_pattern": ".+"}}
payload = {"article": {"front": {"article-meta": {"title": "T"}}}, "errCode": "500"}
→ NO_FULL_TEXT  ("no accessible full text (status=200, marker='article.front.article-meta')")
```

**Fix: same reorder as FS-03** — error evidence first.

**FS-05 — `body_required: false` with a declared `body_marker` is semantically incoherent. (P2)**

The PS3-02 fall-through is **unconditional** once a `body_marker` is declared: any fetch response with no body content and no earlier verdict → `EMPTY_RESULT`. So `body_required: false` does not mean "a body is not required" — the only effect of `false` is that the composite (which would say `PARTIAL_CONTENT` when metadata is present) is skipped, and the fall-through says `EMPTY_RESULT` anyway. Probe E (with a live `error_field` so the rule set passes PS3-05d):

```
fetch = {body_required: false, body_marker: "article.body",
         metadata_marker: "article.front", error_field: {...}}
payload = {"article": {"front": {"article-meta": {"title": "T"}}}}   # metadata only
→ EMPTY_RESULT  ("fetch response has no body content and no matching verdict (PS3-02)")
```

The schema advertises a choice that the fall-through makes meaningless. **Fix: reject at registration** — a declared `body_marker` requires `body_required: true` (a body marker implies the body matters; a provider whose body semantics are the adapter's business — europepmc — declares no `body_marker` at all).

**FS-06 — `body_required: true` with `metadata_marker: null` ships a dead composite. (P2)**

The composite's guard is `body_required and metadata_marker is not None`; registration closes "`body_required` without `body_marker`" (PS3-05a) but **not** "`body_required` without `metadata_marker`". With `metadata_marker: null`, the composite can never fire, and `body_required` has no other effect anywhere in the evaluator — a never-firing rule, the HZ2-05 dead-content class, in the fetch block. Probe F: the combination registers cleanly, and a metadata-less article with a body is `NONE`. **Fix: registration** — `body_required: true` requires a non-null `metadata_marker` (the composite needs both sides).

**FS-07 — Search-shaped throttle signatures fire at FETCH scope. (P3)**

Step 2 (throttle) is scope-agnostic; the shipped signatures were written against search envelopes (`pmc.json` `fields: ["error"]`, `europepmc.json` `fields: ["errMsg"]`). At FETCH scope, a payload carrying a same-named field in a different semantic role is `THROTTLED`. Probe G, shipped `pmc.json`:

```
payload = {"error": "too many requests", "pmc-articleset": {"article": {}}}
scope=FETCH → THROTTLED
```

`THROTTLED` makes the walk retry to exhaustion — the silent-loss class — if a step-5 adapter's fetch parse ever surfaces an `error`/`errMsg` field. No shipped spec is wrong today (JATS fetch payloads carry neither key), so this is a **latent trap**: either restrict throttle signatures to the scope they were written for, or state in the contract that fetch-side throttles are declared as part of the fetch block. P3 because nothing ships wrong; the driver should document the handoff.

**FS-08 — Composite presence is first-value-only vs the HZ-05 any-value unification. (P3)**

The composite's `metadata_present`/`body_absent` use `_is_empty_value(metadata[0])` / `_is_empty_value(body[0])` — first-resolved-value semantics, while HZ-05 unified fetch markers to any-value precisely because single-vs-repeated XML elements make list shape nondeterministic. With a wildcard metadata path, a leading empty element flips the classification. Probe C:

```
fetch = {metadata_marker: "article.front.*", body_marker: "article.body", body_required: true}
payload = {"article": {"front": ["", {"article-meta": {"title": "T"}}]}}   # no body
→ EMPTY_RESULT  (composite skipped — metadata[0] is ""; fall-through fires)
```

Both `EMPTY_RESULT` and `PARTIAL_CONTENT` are typed recordable failures, so this is diagnostic fidelity, not a bypass — but the metadata/body presence checks should share the markers' any-value discipline (any non-empty resolved value counts as present). **Fix: fold into FS-01's recursive-emptiness change** — presence = any value that is recursively non-empty.

## What survives

The parts of the fetch surface that the shipped fixtures already pin down hold under attack: the status-driven `NO_FULL_TEXT` deferral (any declared 4xx-except-429, fetch-scope precedence over step 1's `VALID_NEGATIVE`), the fetch-404 retraction-kind refinement, the `required_fields` drift sentinel (runs before the composite), the empty-whole-payload path (step 4 catches the zero-byte case for every provider), leaf-value retraction semantics (the HZ2-02/03 closures hold — a normal article whose body mentions "retracted" is `NONE`), and the `empty_body_rule: treat-as-failure` enforcement. FS-01 and FS-02 are precision gaps in the exact text the PS3/HZ remediations wrote — the recursion depth of "present-but-empty" and the any-value scope of the error check — not structural collapse.

## Overall verdict: **MERGE WITH REMEDIATION.**

**FS-01** is gate-blocking for the step-3 driver: the walk's `fetch_batch` will run every fetch payload through 6a, and a whitespace-only-body article — a routine real-feed shape — is admitted as a `FetchedSource` with zero content under the **shipped** `pmc.json`. **FS-02** is gate-blocking for the same reason in the other direction: a list-shaped error envelope is silently accepted as full text. **FS-03/04** are ordering violations of the PS3-08 dominance principle (error evidence must beat result-classifications); **FS-05/06** are two registration allowances admitting incoherent/dead fetch rule sets; **FS-07/08** are documented-latent / fidelity notes. All eight land in `hazards.py` (recursive `_is_empty_value`, any-value `error_field`, the 6a reorder, two registration rules) — no new components, no redesign — and the fold-in (with regression fixtures for all probes) is the standing condition before step 3 builds the driver on this surface.

---

## Remediation disposition — **FOLDED IN (2026-08-14)**

| ID | Fix | Where it lands |
|---|---|---|
| FS-01 | Recursive emptiness: a dict is empty iff all values recursively empty; a list iff all elements; the composite's `body_absent` and the fall-through inherit it | `hazards.py` `_is_empty_value`; fixture (probe J — `{"sec": ""}` → `PARTIAL_CONTENT` with front, `EMPTY_RESULT` without) |
| FS-02 | Any-value fetch `error_field`: `any(re.search(code_pattern, str(v)) for v in values)`, str leaves only | `hazards.py` step 6a `error_field` check; fixture (probe D — 503 behind 200 → `MALFORMED_200`) |
| FS-03/04 | Reorder 6a: fetch `error_field` → fetch required-fields drift → retraction → `no_full_text` → composite → fall-through | `hazards.py` step 6a; fixtures (probes A, H — errCode wins) |
| FS-05 | Registration: a declared `body_marker` requires `body_required: true` | `hazards.py` `_load_fetch_rules`; fixture (probe E — combination rejected) |
| FS-06 | Registration: `body_required: true` requires a non-null `metadata_marker` | `hazards.py` `_load_fetch_rules`; fixture (probe F — combination rejected) |
| FS-07 | Contract note: fetch-side throttles are declared in the fetch block; step-3 driver documents the handoff (or scope-scoped throttle signatures) | contract §5 + blueprint §5.2 note; no code today |
| FS-08 | Composite presence uses the any-value discipline (folded into FS-01) | `hazards.py` composite; fixture (probe C) |

**Status: FOLDED IN — all eight dispositions implemented (code + docs) with regression fixtures in `tests/test_provider_hazards.py` (84 fixtures in the file, 692 passed suite-wide, pyright 0 errors), and re-checked against the running code:**

| FS | Fold-in landing | Re-check |
|---|---|---|
| FS-01 | `_is_empty_value` is recursive — a dict is empty iff all values recursively empty, a list iff all elements; the composite's `body_absent` and the fall-through inherit it | Shipped `pmc.json` + body `{"sec": ""}` with front → `PARTIAL_CONTENT`; without front → `EMPTY_RESULT`; deep all-empty nesting → absent; real content stays present (probe J re-run, plus the no-over-fire guard) |
| FS-02 | Fetch `error_field` is any-value — any str leaf matching the code pattern, not `values[0]`; the search-side `error_field` inherits the same discipline | `errCodes.*.code` = `["200", "503"]` → `MALFORMED_200` with `code: "503"`, at both FETCH and SEARCH scope (probes D re-run) |
| FS-03 | 6a reordered: fetch `error_field` → required-fields drift → retraction → `no_full_text` → composite → fall-through | errCode + retraction event in a 200 → `MALFORMED_200`; clean retraction still → `NO_FULL_TEXT(REMOVED_OR_RETRACTED)` (probe A re-run) |
| FS-04 | Same reorder — error evidence runs before the `no_full_text` result-classes | errCode 500 + broad `no_full_text_marker` in a 200 → `MALFORMED_200` (probe H re-run) |
| FS-05 | Registration: a declared `body_marker` requires `body_required: true` | `body_required: false` + body_marker → `SpecValidationError` (probe E re-run; shipped `europepmc.json` — no body_marker — unaffected) |
| FS-06 | Registration: `body_required: true` requires a non-null `metadata_marker` | `body_required: true` + `metadata_marker: null` → `SpecValidationError` (probe F re-run; shipped `pmc.json` — both declared — unaffected) |
| FS-07 | Contract §5.1 note + blueprint §5.3 driver note: step 2's `throttle_signature` is scope-agnostic; fetch-side throttles are declared in the fetch block | No code change (documented handoff); the scope-blind behavior is now stated, not silent |
| FS-08 | Composite presence is any-value — `any(not _is_empty_value(v))` for metadata, `all(...)` for body — folded into the FS-01 recursion | Wildcard metadata path `["", {"article-meta": {"title": "T"}}]` + no body → `PARTIAL_CONTENT` (probe C re-run) |

One shipped-fixture adjustment: `test_pmc_present_but_empty_body_counts_as_absent` previously used an all-empty front (`{"article-meta": {}}`), which the recursion now correctly treats as absent metadata → `EMPTY_RESULT`; the fixture now carries a titled front so it isolates body emptiness, and the all-empty-shell case is covered by the FS-01 fixture. The step-2 gate is now clear for step 3.
