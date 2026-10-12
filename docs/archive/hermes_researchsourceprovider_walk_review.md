# Adversarial Review — Reconciliation Walk Driver Design (pre-step-3 gate)

**Scope:** protest-stage attack on the **step-3 walk-driver design** — blueprint §5.1 (`paginate.py` driver steps 1–9), §5.2 (request log), contract §4.1 (per-provider verdicts), §4.2 (aggregate + zero-delivered matrix), §4.3 (`total_is_estimate`/dedup-direction), §4.4 (pagination discipline + cursor guard). Method: attack the reconciliation walk, the cursor guard, and the aggregate matrix for the same bypass/silent-failure classes the slice exists to close — silent truncation, silent "answered no", dead/ambiguous rules, and aggregate polysemy — treating the PS/PS2/PS3/FS closures as settled only where the design text actually pins them. **The driver does not exist yet (steps 1–2 only are implemented); this is a design-level review against the ratified design text, run before step 3 writes any code** — every finding quotes the exact contract/blueprint text it contradicts or leaves open. No probes are possible against code that does not exist; the findings are text-precision gaps, the same class the PS/PS2/PS3 blueprint gates caught.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| WS-01 | **P1** | aggregate matrix | **`VALID_NEGATIVE` is never scoped to lookup mode** — a topic QUERY walk whose page 3 returns a 404 is classified `VALID_NEGATIVE` (SEARCH scope) and the matrix's (c)/(d) rules would resolve it as an "answered" `COMPLETE`, silently truncating a query walk with the answered-no class |
| WS-02 | **P1** | reconciliation verdict | **"Empty next page → exhausted naturally" is cursor-blind and position-blind** — an empty page WITH a live next-cursor (provider says more exists), or a mid-walk empty after ≥ 1 non-empty page, is recorded `COMPLETE` with zero note when `total` is absent: silent truncation with no signal (§4.1 (c)) |
| WS-03 | **P2** | cursor guard | **Spec `loop_guard` vs request `max_pages` reconciliation is undefined** — which cap wins, and what verdict (bare `COMPLETE`, `STOPPED_AT_LIMIT` note, or `CURSOR_TRAP` suspicion) when the spec's guard is hit |
| WS-04 | **P2** | mid-walk failure | **Mid-walk PERMANENT failures are unpinned** — §4.1 (b) says "failed after retries were exhausted" (transient shape); a mid-walk `MALFORMED_200` (permanent, never retried) raised uncaught would abort the walk and lose pages 1–2 |
| WS-05 | **P2** | aggregate | **The walk's `COMPLETE` is polysemous (the PS3-04 analog)** — bounded-by-request `COMPLETE`-with-note never signals that more existed; the "reading rule" (aggregate = resolution signal, per-provider reconciliations = coverage signal) is stated for fetch but never for the walk |
| WS-06 | **P3** | cursor guard | **`CURSOR_TRAP` should fire BEFORE issuing the duplicate request** — the contract wording implies post-hoc detection (the duplicate page was already fetched); also, the driver-detected trap must be injected into `RequestLogRecord.hazard_verdicts` (§5.2 step 8) for re-runnability |
| WS-07 | **P3** | zero-delivered matrix | **"Ran" is used in two senses** — `UNAVAILABLE` says "no provider ran (throttled/errored…)" while `EMPTY` requires "≥ 1 provider ran AND searched"; a provider whose first page throttled to exhaustion ran but never searched, and the wording must pin that it never qualifies the `EMPTY` side alone |

## Detail

**WS-01 — The answered-no class is applied to query walks. (P1)**

The contract defines a valid negative as *"a `doi:`/`pmid:` lookup that resolves to 'not found'"* (§4.2) and the evaluator emits `VALID_NEGATIVE` at SEARCH scope whenever `status ∈ valid_negative_statuses` (404/410/451 — the not-found family). The aggregate matrix then says: (c) a **valid-negative-only identifier lookup** is `COMPLETE` (answered); (d) **valid-negative mixes** with empty searches or real results are `COMPLETE`. But the driver's step 7 applies (c)/(d) with **no gate on the walk's mode** — the driver never says "these rules apply only when the walk is an identifier lookup". The mode IS derivable (the parsed hints: `doi:`/`pmid:`/`pmcid:`/`arxiv:`/`url:` = lookup; topic = query). A topic QUERY walk whose page 3 returns a 404 — a provider anomaly, not an answer — is `VALID_NEGATIVE` → the matrix resolves it as "the lookup was answered" → `COMPLETE`, silently truncating the query walk and reporting an answered result for a query that never completed. This is the answered-no class applied outside its domain. **Fix: the driver carries a `lookup`/`query` mode from the parsed hints; `VALID_NEGATIVE` resolution (c)/(d) applies ONLY in lookup mode; in query mode a `VALID_NEGATIVE` page is a mid-walk anomaly → provider `SHORTFALL(cause=VALID_NEGATIVE_MID_WALK)` with the page failure recorded — never an "answered" `COMPLETE`.**

**WS-02 — "Empty next page → exhausted" silently truncates. (P1)**

§4.1 `COMPLETE` (c): *"`total` absent, walk exhausted naturally (no next cursor / **empty next page**)".* Two holes in that rule:

- **An empty page WITH a next cursor** — the provider explicitly says more results exist (a cursor for page N+1) yet returned zero rows. "Empty next page → exhausted" stops the walk, `COMPLETE`, and with `total` absent nothing else fires — but the provider's own cursor said the walk was not exhausted. Silent truncation.
- **A mid-walk empty page** — page 1 delivered 5 records, page 2 returns an empty body. "Empty next page → exhausted naturally" → `COMPLETE` with no note, `total` absent. Pages 1 had results; an empty page-2 is a provider anomaly, not exhaustion — yet the walk reports a clean `COMPLETE`.

Both are the silent-truncation class the reconciliation verdicts exist to surface, reachable with **no spec-author error** (any provider that emits a transient empty page). **Fix: the exhaustion rule is cursor-aware and position-aware** — an empty page with a next cursor continues the walk (up to bounds); an empty page after ≥ 1 non-empty page is `SHORTFALL(cause=EMPTY_MID_WALK)` (or at minimum `STOPPED_AT_LIMIT`-grade note), never a bare `COMPLETE`; "exhausted" is only (empty page AND no next cursor AND first page) or (no next cursor after a non-empty page).

**WS-03 — Spec `loop_guard` and request `max_pages` are two caps with no reconciliation rule. (P2)**

The hazard spec carries `cursor_rule.loop_guard` (HZ-06: capped at 1000 — "a spec cannot ship an effectively-unbounded pagination walk"); the walk carries `WalkRequest.max_pages` (per-task, S11 scale classes). The blueprint's step 3 says bounds (`page_size_cap`, `max_pages`, `max_records`) are "enforced by the driver" and exceeding one records `STOPPED_AT_LIMIT` — but never says how the SPEC's `loop_guard` participates: does the spec guard win over the request cap, and when the spec's guard is hit, is that `STOPPED_AT_LIMIT` (bounded, `COMPLETE`-with-note) or `CURSOR_TRAP` suspicion (a walk that runs to the spec's own page ceiling is a provider whose pagination never converges)? If the guard is silently treated as just another bound, a non-converging provider gets `COMPLETE`-with-note forever. **Fix: pin the reconciliation** — the driver enforces `min(spec.loop_guard, request.max_pages)`; hitting the SPEC guard (with a live cursor) is `SHORTFALL(cause=CURSOR_TRAP)` — the spec's guard IS the trap threshold; hitting the REQUEST bound is `STOPPED_AT_LIMIT` (bounded-by-request, `COMPLETE`-with-note).

**WS-04 — Mid-walk permanent failures would abort the walk. (P2)**

§4.1 `SHORTFALL` (b): *"a mid-walk page failed **after retries were exhausted**"* — the transient shape. The retry taxonomy (§6.3) says permanent classes "raise immediately" (never retried). A mid-walk `MALFORMED_200`/`REWRITE_SUSPECT` page-3 raises immediately; if the driver's page loop lets the permanent raise propagate, pages 1–2's records are lost with the whole walk, and the zero-delivered matrix never sees the delivered records. The design never says the driver converts a mid-walk permanent failure into `SHORTFALL(cause=<class>)` with the accumulated records retained-and-flagged. **Fix: pin the mid-walk failure rule** — any page failure after ≥ 1 successful page (transient-after-retries OR permanent-immediate) → provider `SHORTFALL(cause=<failure class>)`, records returned flagged; only a FIRST-page failure with zero delivery participates in the zero-delivered matrix (§4.2).

**WS-05 — The walk's `COMPLETE` carries the PS3-04 polysemy. (P2)**

For fetch, the blueprint states the reading rule explicitly: *"`COMPLETE` means 'every source resolved', never 'full text obtained for all'… the aggregate alone is never that signal"* (PS3-04). For the walk, `COMPLETE` means three different things: exhausted the corpus (reconciled `retrieved == total`), bounded-by-request (`STOPPED_AT_LIMIT`, more existed), or no-total-natural-exhaustion (`UNKNOWN`-grade). The blueprint never states the walk's analog of the reading rule — a consumer reading only `aggregate: COMPLETE` cannot distinguish "we saw everything" from "we stopped at your bound". **Fix: state the walk reading rule** — `COMPLETE` is a *resolution* signal, never a coverage claim; coverage conclusions must read per-provider reconciliations + notes (`STOPPED_AT_LIMIT`, `total_not_reported`, `MALFORMED_ROW`, `UNKNOWN`), and `SearchOutcome` carries them.

**WS-06 — The trap should fire before the duplicate request. (P3)**

§4.4: *"a `next_cursor` that repeats an already-seen cursor … fires `CURSOR_TRAP` → the walk stops"* — the trigger is a page's returned cursor, meaning the duplicate page was already requested and fetched before the trap fires. The purpose of the guard is to avoid exactly that re-request. **Fix: check before issuing** — after page N, if `next_cursor` was already in the seen-chain, stop without requesting; and record the driver-detected trap into `RequestLogRecord.hazard_verdicts` (§5.2 step 8 — the evaluator never emits `CURSOR_TRAP`, so the driver must inject it for the log to stay re-runnable).

**WS-07 — "Ran" is ambiguous in the zero-delivered matrix. (P3)**

`UNAVAILABLE` says *"no provider ran (every routed provider throttled/errored/unreachable)"* while `EMPTY` requires *"≥ 1 provider ran and searched"*. "Ran" is used in both senses: the transport was called (throttled) vs. a search completed (a response parsed). A provider whose first page throttled to exhaustion called the transport but never searched. The outcome is right today (all-throttled → `UNAVAILABLE`; mixed searched-empty + throttled → `EMPTY`), but the wording invites a driver misread where a throttled-to-exhaustion provider "ran" for the `EMPTY` side. **Fix: define the terms** — "searched" = ≥ 1 response parsed (any verdict); "ran" = transport called; `EMPTY` requires ≥ 1 provider *searched* with zero delivered; `UNAVAILABLE` requires zero *searched*.

## What survives

The parts of the walk design the prior gates already pinned hold under attack: the fixed allowlist fan-out order (PS-05, never dict order), the only-entry-point invariant (PS-03 — the four hooks receive request/payload only, never transport/limiter/recorder, so the invariant is structural), routing corners (PS3-06 — unknown hint prefix → `ProviderValidationError` before I/O; routeable-to-no-adapter → `UNAVAILABLE`), the count discipline (PS-04/PS2-05 — reconciliation reads `raw_retrieved_count`, never the dedup'd `delivered_count`; `counts_raw_rows` is spec content, never a driver guess), the dedup note discipline (PS-07 — malformed rows skipped-and-counted, never silent; structurally unparseable page = page failure, not row skip), the `STOPPED_AT_LIMIT` ≠ `SHORTFALL` distinction for request bounds, the fetch-is-separate rule (PS-01 — search and fetch never fused), the `UNAVAILABLE` vs `EMPTY` distinction (PS-13), and the retry taxonomy's "permanent never retried / transient ≤ `max_retries` with `Retry-After`" (contract §6.3). The seven findings are precision gaps in the walk's own text — the mode gate, the exhaustion rule, the cap reconciliation, and the mid-walk failure rules — not structural collapse.

## Overall verdict: **MERGE WITH REMEDIATION.**

**WS-01** and **WS-02** are gate-blocking for step 3: they are the silent-truncation class (an answered-no applied to a query; an empty page read as exhaustion) reachable against the *shipped* design text without any spec-author error, and the driver would implement them as specified. **WS-03/04** are undefined-behavior gaps the driver must resolve before or during implementation (cap reconciliation; mid-walk permanent failure handling). **WS-05/06/07** are stated-reading-rule, trap-timing, and wording pins. All seven land in blueprint §5.1/§5.2 and contract §4.1/§4.2/§4.4 — no new components, no redesign — and the fold-in (design text + the walk fixtures that will pin these behaviors in `test_provider_walk.py`) is the standing condition before step 3 writes `paginate.py`.

---

## Remediation disposition — **FOLDED IN (2026-08-14)**

| ID | Fix | Where it lands |
|---|---|---|
| WS-01 | Driver carries `lookup`/`query` mode from parsed hints; `VALID_NEGATIVE` resolution (c)/(d) applies only in lookup mode; query-mode `VALID_NEGATIVE` page → `SHORTFALL(cause=VALID_NEGATIVE_MID_WALK)` | blueprint §5.1 step 1/7 + contract §4.2; walk fixture |
| WS-02 | Exhaustion rule is cursor-aware + position-aware: empty page WITH next cursor continues; empty page after ≥ 1 non-empty page → `SHORTFALL(cause=EMPTY_MID_WALK)`; "exhausted" = (empty ∧ no cursor ∧ first) ∨ (no cursor after non-empty) | blueprint §5.1 step 6 + contract §4.1 (c); walk fixtures |
| WS-03 | Driver enforces `min(spec.loop_guard, request.max_pages)`; hitting the SPEC guard with a live cursor → `SHORTFALL(cause=CURSOR_TRAP)`; hitting the REQUEST bound → `STOPPED_AT_LIMIT` (`COMPLETE`-with-note) | blueprint §5.1 step 3 + contract §4.4; walk fixture |
| WS-04 | Any page failure after ≥ 1 successful page (transient-after-retries OR permanent-immediate) → provider `SHORTFALL(cause=<class>)`, records retained-flagged; first-page zero-delivery failures feed the zero-delivered matrix | blueprint §5.1 step 6 + contract §4.1 (b); walk fixture |
| WS-05 | Walk reading rule stated: `COMPLETE` is a resolution signal, never a coverage claim; coverage reads per-provider reconciliations + notes | blueprint §5.1 step 7 + contract §4.2; doc |
| WS-06 | Trap fires BEFORE issuing the duplicate request (seen-chain check post-page-N); driver injects the detected trap into `RequestLogRecord.hazard_verdicts` | blueprint §5.1 step 4 + §5.2; walk fixture |
| WS-07 | Define "searched" (≥ 1 response parsed) vs "ran" (transport called); `EMPTY` requires ≥ 1 searched with zero delivered; `UNAVAILABLE` requires zero searched | contract §4.2 matrix wording |

**Status: FOLDED IN — all seven dispositions are in the design text (blueprint §5.1 + contract §4.1/§4.2/§4.4), each verified against the exact sentences this review quoted; the behaviors are the `test_provider_walk.py` fixture plan for step 3.**

| WS | Fold-in landing | Re-check |
|---|---|---|
| WS-01 | Blueprint §5.1 step 1 (walk mode: `lookup` from identifier hints, `query` from topic hints) + step 7 (rules (c)/(d) apply only in `lookup` mode) + contract §4.2 matrix (mode gate row) | A query-mode `VALID_NEGATIVE` page is now `SHORTFALL(cause=VALID_NEGATIVE_MID_WALK)` (step 6 + §4.1 (e)) — never an "answered" `COMPLETE` |
| WS-02 | Blueprint §5.1 step 6 (exhaustion rule) + contract §4.1 `COMPLETE` (c) + §4.1 `SHORTFALL` (e) | Empty page WITH a live next cursor continues; empty page after ≥ 1 non-empty page → `SHORTFALL(cause=EMPTY_MID_WALK)`; "exhausted" = (empty ∧ no cursor ∧ first) ∨ (no cursor after non-empty) |
| WS-03 | Blueprint §5.1 step 3 + contract §4.4 (cap reconciliation) | Driver enforces `min(spec.loop_guard, request.max_pages)`; spec-guard hit with a live cursor → `SHORTFALL(cause=CURSOR_TRAP)`; request bound → `STOPPED_AT_LIMIT` |
| WS-04 | Blueprint §5.1 step 2 (mid-walk failure rule) + step 6 + contract §4.1 `SHORTFALL` (b) | Transient-after-retries OR permanent-immediate mid-walk failures → `SHORTFALL(cause=<class>)`, records retained-flagged; only first-page zero-delivery feeds the zero-delivered matrix |
| WS-05 | Blueprint §5.1 step 7 (reading rule) + contract §4.2 `COMPLETE` bullet | `COMPLETE` is a resolution signal, never a coverage claim; coverage reads per-provider reconciliations + notes |
| WS-06 | Blueprint §5.1 step 4 (pre-request seen-chain check) + step 8 (driver-injected `CURSOR_TRAP` in `hazard_verdicts`) + contract §4.4 | The trap fires BEFORE the duplicate request; the log stays re-runnable |
| WS-07 | Blueprint §5.1 step 7 (ran vs searched) + contract §4.2 matrix terms | "searched" = ≥ 1 response parsed; "ran" = transport called; `EMPTY` requires ≥ 1 searched, `UNAVAILABLE` requires zero searched |

No code exists yet — the fold-in is design text only, and the standing condition before step 3 writes `paginate.py` is now the remediated text with the seven behaviors pinned as `test_provider_walk.py` golden fixtures.
