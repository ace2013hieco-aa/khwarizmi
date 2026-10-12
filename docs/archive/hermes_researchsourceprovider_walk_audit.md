# Adversarial Audit — Reconciliation Walk Driver, shipped code (post-step-3 gate)

**Scope:** protest-stage attack on the **shipped** `src/hermes/tools/providers/paginate.py` (`walk()` + `combine()`) + `base.py` — the reconciliation walk, the cursor guard, and the aggregate matrix — for the same bypass/silent-failure classes the WS design review found and the WS fold-in was supposed to close. Method: treat the WS remediations as settled only where the shipped code actually enforces them; re-derive each attack surface independently and reproduce every finding against the running code with probes (each finding quotes the actual verdict/aggregate output — no reading claims). This is the second gate on the walk surface: the design review (WS-01…WS-07) was folded into the text and implemented, so every finding below is a hole in the *implemented* mechanism, not the text.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| WK-01 | **P1** | `combine` valid-negative branch | **A searched-then-failed leg is hidden behind an "answered" lookup** — `answered_no` forces `COMPLETE` regardless of other providers' SHORTFALL/UNKNOWN verdicts, so a lookup answered-no + a query leg that ran and failed with zero delivery aggregates `COMPLETE`, violating the aggregate's own reading rule ("every routed provider resolved") (probe W4) |
| WK-02 | **P2** | `combine` shortfall detection | **The never-searched note pollutes the SHORTFALL scan** — a DOWN provider (throttle-exhaustion) carries a `SHORTFALL(cause=THROTTLED)` note on an `UNAVAILABLE` outcome, so a delivered + down mix aggregates `PARTIAL`, but matrix (a) says PARTIAL only for SHORTFALL/UNKNOWN — down providers are "recorded in notes", never PARTIAL triggers (probe W5) |
| WK-03 | **P2** | reconciliation verdict | **Bounded-by-request with NO total is `COMPLETE`, but §4.1's `UNKNOWN` row says a no-total non-exhaustible walk is `UNKNOWN`** — the `reached_max_results` branch never consults `total` (probe W1) |
| WK-04 | **P2** | reconciliation verdict | **§4.1 (d) (`total > 0`, zero delivered → `SHORTFALL`) never fires when the walk is bounded** — the bound branches run before the zero-delivered check, so a provider that reports 50 results, delivers zero, and hits the request page bound aggregates `COMPLETE(STOPPED_AT_LIMIT)` (probe W2) |
| WK-05 | **P2** | page loop | **Retries bypass the limiter** — `limiter.acquire` is called once per page, not per transport request; a throttled-then-retried page makes 2 transport calls for 1 acquire, so the limiter (the future budget ledger's cost input, AR-02) under-accounts (probe W3) |
| WK-06 | **P3** | `combine` raises | **The `EMPTY`/`UNAVAILABLE` raise discards the outcome's notes** — the typed error carries provider ids + cause but not the per-provider causes the matrix promises are "recorded in notes"; the caller must re-inspect the sub-outcomes it already holds (documented, not lost) |
| WK-07 | **P3** | bounds | **The `max_results` bound reads the dedup'd `delivered` count, not `raw_retrieved`** — §4.1 (b) says "reached the caller's `max_results` with `retrieved == max_results`" (raw); a dedup-heavy walk issues more requests than the resource cap implies |

## Detail

**WK-01 — An answered lookup hides a failed search leg. (P1)**

`combine`'s branch order: `real_delivered` → `answered_no` → `any_searched` → else. The `answered_no` branch returns `COMPLETE` unconditionally. But the matrix (d) rows list only *empty-search* and *real-results* mixes — **never a failed or truncated leg**. A caller running a lookup AND a topic search gets `combine([lookup_outcome, query_outcome])`; if the query leg ran and failed with zero delivery (e.g., a first-page `MALFORMED_200`), the aggregate is `COMPLETE` even though "every routed provider resolved" is false — the aggregate's own reading rule (WS-05). Probe W4:

```
answered = walk(lookup "doi:10.1000/abc123" → 404 VALID_NEGATIVE)   # COMPLETE(answered-no)
failed_q = walk(topic → first page MALFORMED_200, zero delivered)   # EMPTY + SHORTFALL(cause=MALFORMED_200)
combine([answered, failed_q]) → COMPLETE
```

The failed leg is invisible at the aggregate level. **Fix: the `answered_no` branch must consult the shortfall signal** — `"PARTIAL" if shortfall_or_unknown else "COMPLETE"` — so an answered lookup + a searched-then-failed leg is `PARTIAL` (the failure is real), while an answered lookup + down/unrun providers stays `COMPLETE` per matrix (c).

**WK-02 — The never-searched note pollutes the SHORTFALL scan. (P2)**

A provider that never searched (all attempts throttled/transient-exhausted) gets aggregate `UNAVAILABLE` and verdict note `SHORTFALL(cause=THROTTLED)` / `SHORTFALL(cause=NEVER_SEARCHED)`. `combine`'s `any_shortfall_or_unknown` scans **all** notes for the `SHORTFALL(` prefix — including on `UNAVAILABLE` sub-outcomes. Probe W5:

```
delivered = walk(topic → 1 record)                                   # COMPLETE
down = walk(topic → 4× 429, exhausted)                                # UNAVAILABLE, notes[0]=SHORTFALL(cause=THROTTLED)
combine([delivered, down]) → PARTIAL
```

Matrix (a) says `PARTIAL` only for providers whose verdict is `SHORTFALL`/`UNKNOWN` — a provider that could not run is "recorded in notes", never a PARTIAL trigger; (c) says down/unrun with an answered lookup is "never `PARTIAL`". The current scan makes delivered + down and answered + down `PARTIAL`, over-reporting incompleteness (fail-safe direction, but a matrix violation that also breaks the (c) guarantee). **Fix: the shortfall scan excludes `UNAVAILABLE` sub-outcomes** — only *searched* providers (aggregate != `UNAVAILABLE`) carrying a `SHORTFALL(`/`UNKNOWN(` note (or a `PARTIAL` aggregate) count.

**WK-03 — Bounded-by-request with no total is `COMPLETE`, not `UNKNOWN`. (P2)**

§4.1: `UNKNOWN` = *"provider reports no total and the walk is not exhaustible (e.g., bounded by `max_results` with no total)"*. The shipped `reached_max_results` branch assigns `COMPLETE(bounded-by-request(max_results))` without consulting `total` — the no-total bounded walk is exactly the contract's `UNKNOWN` case. Probe W1:

```
walk(topic, request max_results=1; page 1: 1 record, total=None, next_cursor="c1")
→ notes[0] = COMPLETE(bounded-by-request(max_results))
```

The `max_pages`-bound branch handles the no-total case (`UNKNOWN`), but the `max_results`-bound branch does not. **Fix: the `reached_max_results` branch splits on `total`** — `None` → `UNKNOWN(total_not_reported(bounded))`, else `COMPLETE(bounded-by-request(max_results))`.

**WK-04 — The §4.1 (d) zero-delivered signal is lost when bounded. (P2)**

§4.1 (d): *"`total > 0` but **zero** records delivered"* → `SHORTFALL`. The shipped driver applies (d) only in the exhausted-naturally branch; the bound branches (reached_max_results, hit_page_bound) run first. A provider that reports 50 results, delivers zero on every page, and stops at the request page bound: Probe W2 —

```
pages: [empty, total=50, cursor c1] [empty, total=50, cursor c2], max_pages=2
→ notes[0] = COMPLETE(bounded-by-request(STOPPED_AT_LIMIT)), aggregate EMPTY
```

The provider demonstrably HAS results (total 50) and the walk delivered none — that is the (d) signal, but the aggregate says `COMPLETE` with a `STOPPED_AT_LIMIT` note. **Fix: the `len(delivered) == 0 and total > 0` check runs BEFORE the bound branches** — (d) dominates (a `total > 0` declaration with zero delivery is stronger than the bound reason).

**WK-05 — Retries bypass the limiter. (P2)**

`limiter.acquire` is called once per page (the walk's outer loop); `_fetch_page`'s retry loop calls `transport.request` directly on each attempt without re-acquiring. Probe W3 (shipped behavior):

```
script: [429, clean], retry succeeds → transport.calls == 2, limiter.acquire count == 1
```

The limiter is the rate authority AND the future budget ledger's cost input (AR-02/IDR29-04); each request must be accounted. The `note_throttled` backoff paces the retry, but the bucket/accounting sees one acquire for two requests. **Fix: `_fetch_page` acquires per attempt** — `limiter.acquire` moves inside the attempt loop, before each `transport.request` (the walk's outer acquire is removed).

**WK-06 — The `EMPTY`/`UNAVAILABLE` raise drops the notes. (P3)**

The matrix promises causes "recorded in notes"; `combine` raises `RetrievalShortfallError`/`ProviderUnavailableError` with provider ids + `cause_class`/`hazard_class` only — the outcome's notes (which provider throttled, which malformed) are not attached to the error. Not lost (the caller holds the sub-outcomes it passed in), but the typed error alone does not carry the "never silent" detail. **Fix: attach the merged notes to the raised error** (a `notes` attribute) or state the caller-side contract explicitly in the docstring.

**WK-07 — The `max_results` bound reads the dedup'd count. (P3)**

§4.1 (b): "reached the caller's `max_results` with `retrieved == max_results`" — `retrieved` is raw (PS2-05: the reconciliation reads `raw_retrieved_count`). The shipped loop exits on `len(delivered) >= request.max_results` (post-dedup). A dedup-heavy provider over-runs the raw bound, issuing more requests than the resource cap implies. **Fix: exit on `raw_retrieved >= request.max_results`** (with a note when dedup reduced the delivered stream below the bound).

## What survives

The WS remediations hold exactly where the fixtures exercise them: the lookup/query mode gate (a query-mode `VALID_NEGATIVE` page is `SHORTFALL(VALID_NEGATIVE_MID_WALK)`, never "answered"), the cursor-aware + position-aware exhaustion rule (empty-with-cursor continues; mid-walk empty → `EMPTY_MID_WALK`), the `min(spec.loop_guard, request.max_pages)` reconciliation with the spec guard as the trap threshold, the pre-request trap that never issues the duplicate request (and injects `CURSOR_TRAP` into the log), the mid-walk failure rule with records retained-flagged, the ran-vs-searched terms for the `EMPTY`/`UNAVAILABLE` split, and the `raw_retrieved_count` vs `delivered_count` split. The seven findings are precision gaps in the *implemented* verdict ordering and the combine scan — the same class the WS review found in the design — not structural collapse.

## Overall verdict: **MERGE WITH REMEDIATION.**

**WK-01** is gate-blocking: the aggregate's own reading rule (WS-05) is violated — an answered lookup can mask a searched-then-failed leg as `COMPLETE`, the silent-failure class the matrix exists to close. **WK-02/03/04/05** are matrix/verdict fidelity and accounting gaps (two of them fail-safe, two fail-open at the verdict level). **WK-06/07** are documentation/accounting pins. All seven land in `paginate.py` (the combine scan + `answered_no` branch, the verdict ordering, the per-attempt acquire, the bound reading) — no new components, no redesign — and the fold-in (code + regression fixtures for all probes) is the standing condition before step 4 builds the limiter on top of this driver.

---

## Remediation disposition — **pending (the fold-in is the standing condition before step 4)**

| ID | Fix | Where it lands |
|---|---|---|
| WK-01 | `answered_no` branch → `"PARTIAL" if shortfall_or_unknown else "COMPLETE"` (an answered lookup + a searched-then-failed leg is `PARTIAL`; answered + down/unrun stays `COMPLETE` per (c)) | `paginate.py` `combine`; fixture (probe W4) |
| WK-02 | The shortfall scan excludes `UNAVAILABLE` sub-outcomes — only searched providers carry the SHORTFALL/UNKNOWN trigger | `paginate.py` `combine`; fixture (probe W5 — delivered + down → `COMPLETE`) |
| WK-03 | `reached_max_results` splits on `total`: `None` → `UNKNOWN(total_not_reported(bounded))` | `paginate.py` verdict section; fixture (probe W1) |
| WK-04 | `len(delivered) == 0 and total > 0` → `SHORTFALL(ZERO_DELIVERED_TOTAL_POSITIVE)` runs BEFORE the bound branches (d) dominates | `paginate.py` verdict section; fixture (probe W2) |
| WK-05 | `limiter.acquire` moves into `_fetch_page`'s attempt loop (one acquire per transport request) | `paginate.py` `_fetch_page`/`walk`; fixture (probe W3 — acquire count == transport calls) |
| WK-06 | Attach the merged notes to the raised `EMPTY`/`UNAVAILABLE` errors (or state the caller contract) | `paginate.py` `combine`; docstring |
| WK-07 | Bound exit on `raw_retrieved >= request.max_results` (with a dedup note) | `paginate.py` page loop; fixture |

**Status:** all seven reproduced against the running code (probes W1–W5 above; W6/W7 are code-reading pins confirmed by inspection); dispositions are **FOLDED IN (2026-08-14)** and verified against the running code — see the re-check table below; the step-3 gate is clear for step 4.

## Re-check (2026-08-14, against the fixed code)

| Probe | Before | After |
|---|---|---|
| W1 (bounded, no total) | `COMPLETE(bounded-by-request(max_results))` | `UNKNOWN(total_not_reported(bounded))`, aggregate `PARTIAL` (matrix (a)) |
| W2 (zero delivered, total 50, page bound) | `COMPLETE(STOPPED_AT_LIMIT)` | `SHORTFALL(cause=ZERO_DELIVERED_TOTAL_POSITIVE)` |
| W3 (retry) | 2 transport calls, 1 acquire | 2 transport calls, 2 acquires |
| W4 (answered + failed leg) | `COMPLETE` | `PARTIAL` |
| W5 (delivered + down) | `PARTIAL` | `COMPLETE` (down recorded in notes) |
| WK-06 raises | no notes on the error | `notes` carried on both `RetrievalShortfallError` and `ProviderUnavailableError` |
| WK-07 bound | dedup'd count | `raw_retrieved`, `dedup_reduced_below_bound` note |

All seven flipped to the contract verdicts. **8 regression fixtures added (37 in `tests/test_provider_walk.py`, 729 passed suite-wide, pyright 0 errors);** the WK-03 fixture's expectation was corrected during the run — a delivered + UNKNOWN reconciliation is `PARTIAL` at the single-provider level per matrix (a), not `UNKNOWN`.
