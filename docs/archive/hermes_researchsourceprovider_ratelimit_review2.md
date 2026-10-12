# Adversarial Review — Step-4 limiter/transport design, second gate (post-RT fold-in)

**Scope:** protest-stage attack on ONLY the four surfaces the RT fold-in fixed, against the remediated §6.1/§6.1a text (blueprint `hermes_researchsourceprovider_implementation_design.md`) + contract §6 — (1) the acquire-returns-`False` policy-exception contract (RT-01), (2) the http.py exception class map (RT-02), (3) release-no-refund (RT-03), (4) the per-provider content-type rule (RT-05). Method: treat the RT dispositions as settled only where the remediated text actually enforces them; attack each surface for the SAME bypass/silent-misclassification classes (a verdict lost to a pre-empting check, a signal domain conflated, a gate underflow, a note with no carrier). Every finding quotes the remediated text it contradicts or leaves open, and is verified against the shipped driver's code shape (paginate.py `_fetch_page` — acquire outside the try, `except Exception` catch-all, `finally: release`) and the shipped hazard evaluator's status domain (`evaluate_hazards` owns THROTTLED/VALID_NEGATIVE/MALFORMED_200). No limiter code exists yet — design-text review, the WS/RT-review precedent.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| RT2-01 | **P1** | §6.1a exception map vs the hazard evaluator's status domain | **The map as written pre-empts the hazard evaluator's status handling — "client-error statuses → permanent classes per the spec" would raise on 404, killing the answered-lookup `VALID_NEGATIVE` (WS-01), and on 429, raising transient WITHOUT `note_throttled` (Retry-After never honored).** The transport and `evaluate_hazards` both classify statuses (§6.1a names 5xx/4xx; the walk driver calls `evaluate_hazards(status_code=...)` which owns THROTTLED/VALID_NEGATIVE/MALFORMED_200) — two classifiers, no precedence stated |
| RT2-02 | **P2** | `False` signal domain | **The `False` return conflates "daily cap exhausted" with a bounded-wait expiry — the semaphore/global-concurrency wait is NOT naturally bounded (unlike the bucket's refill), and the expiry semantics is unspecified; if the expiry returns `False`, the driver's no-retry mapping cuts off a walk that could proceed** |
| RT2-03 | **P2** | release contract vs the driver shape | **The release-without-acquire trap is unpinned: a step-4 implementation that checks the `acquire` return INSIDE the try would call `release` after a `False` (nothing acquired) and underflow the semaphore — the concurrency gate opens wider than configured. `False` must return BEFORE the try, never releasing** |
| RT2-04 | **P2** | content-type advisory path + precedence | **The advisory note has no carrier — the transport returns only `(status, body, headers)`, so a mismatched-content-type note never reaches the driver's notes/hazard_verdicts; and the declared-allowlist check has no stated order vs status — a 429 with a mismatched content-type would be `MALFORMED_200` (permanent, no retry) instead of THROTTLED (the FS-03/04 dominance class)** |
| RT2-05 | **P3** | fetch path | **The `False` contract names only `_fetch_page` — step 5a's `fetch_batch` also calls `acquire`, and its `False` handling (→ `FetchFailure(THROTTLED)`) is unspecified** |
| RT2-06 | **P3** | `except Exception` | **The map makes the catch-all "unreachable for transport failures" — but a NON-transport exception from the transport (a bug, an unexpected OSError) still lands in `_fetch_page`'s `except Exception` and is mislabeled `MALFORMED_200`; the RT-02 class survives for unknown failures** |

## Detail

**RT2-01 — Two status classifiers, no precedence. (P1)**

§6.1a: "timeout/connection errors → `TransientProviderError(hazard_class="TIMEOUT")` …; 5xx → transient; client-error statuses → permanent classes per the spec." But the shipped walk driver already classifies HTTP statuses via the hazard evaluator — `_fetch_page` calls `evaluate_hazards(status_code=...)`, which owns:

```
429 → THROTTLED (retryable, note_throttled + Retry-After)
404/410/451 → VALID_NEGATIVE at lookup scope (WS-01 — the answered-no RESULT)
other non-2xx → the HZ-08 "unclassified non-2xx" path
```

If http.py raises on client-error statuses per §6.1a:

```
lookup "doi:10.1000/x" → 404 → http.py raises a PERMANENT error before evaluate_hazards
→ the answered-lookup mechanism (WS-01, matrix (c)/(d), valid_negative_for) never fires
→ a real "no" becomes a failed walk
429 → http.py raises TransientProviderError → _fetch_page retries WITHOUT note_throttled
→ Retry-After / the bucket backoff (RT-08) are never honored; the throttle signature in the
  hazard spec (§5.2) is dead for its primary status
```

**Fix: split the domains structurally — `http.py` raises ONLY for TRANSPORT-level failures (timeout, connection, size cap); HTTP statuses are NEVER raised by the transport — they flow to `evaluate_hazards`, the single status classifier.** The "5xx → transient" claim moves into the hazard spec's status handling (or is deleted — the evaluator already owns it).

**RT2-02 — What does a bounded-wait expiry return? (P2)**

§6.1: "the token bucket/semaphore admit with a *bounded* wait". The bucket's wait is naturally bounded (a token refills every 1/rps; the max wait ≈ burst-replenish time). The **semaphore/global-concurrency wait is not** — another walker can hold the slot indefinitely, so "bounded" needs an explicit bound and an expiry semantics. Three options, each broken as the text stands: expiry → `False` conflates "waited and gave up" with "daily cap exhausted" (the driver's no-retry mapping cuts off a walk that could proceed); expiry → raise violates "NEVER raises for a policy condition"; expiry → loop forever violates "bounded". **Fix: reserve `False` for the daily cap only; the semaphore wait bound is a named constant whose expiry maps to a distinct outcome (or a very long defined bound) — never the same signal as the cap.**

**RT2-03 — Release after a False acquire underflows the gate. (P2)**

The driver shape (paginate.py:514–527): `acquire` outside the try, `release` in the `finally`. The step-4 implementation must check the return:

```python
        if not limiter.acquire(spec.provider_id):   # False → hard stop
            return None, "THROTTLED", "THROTTLED"    # BEFORE the try — never release
        try:
            try: resp = transport.request(req)
            ...
        finally:
            limiter.release(spec.provider_id)
```

A naive check inside the try (`if not limiter.acquire(...): return None, ...` followed by the finally) calls `release` with nothing acquired — the semaphore count goes negative and the `concurrency` gate admits MORE than configured (the under-accounting class, inverted). The text says "the driver maps `False` → the THROTTLED failure path" but not WHERE; the code shape must be pinned.

**RT2-04 — The advisory note has no carrier; the allowlist check has no status precedence. (P2)**

§6.1a: "without an allowlist the check is advisory (a note) and the hazard evaluator's `required_fields` drift sentinel is the backstop." Two gaps:

- **No carrier:** `TransportResponse` is `(status, body, headers)` — the transport cannot write a note into the driver's `notes`/`hazard_verdicts`. Either the response gains a content-type field the driver reads, or the advisory check lives in the hazard spec (a content-type marker) — the text names the note but no mechanism.
- **No precedence:** "A declared allowlist + mismatch → `MALFORMED_200` (permanent)". A 429 (or 404 at lookup scope) whose body has a mismatched content-type (an HTML error page) must be THROTTLED / VALID_NEGATIVE — **status evidence must dominate the content-type check** (the FS-03/04 dominance principle, applied here). Unstated order → the permanent class pre-empts a retryable/re-solvable verdict.

**RT2-05 — The fetch path inherits the False contract. (P3)**

The contract names "the driver's `_fetch_page`" — step 5a's `fetch_batch` will call `acquire` per fetch request and needs the same mapping (a `False` → `FetchFailure(THROTTLED)`, never an unhandled bool, never a retry). Unspecified.

**RT2-06 — The catch-all still mislabels unknown failures. (P3)**

§6.1a: "the generic `except Exception` becomes unreachable **for transport failures**". True for the named classes — but a non-`ProviderError` exception from the transport (a bug, an unexpected `OSError` from the stack) still lands in the catch-all and is labeled `MALFORMED_200` (a schema verdict). The RT-02 class survives for unknown failures. **Fix: the catch-all re-raises non-`ProviderError` exceptions (a transport bug must be loud) or maps them to a distinct `TRANSPORT_FAULT` class — never a schema-drift verdict.**

## What survives

The RT fixes hold exactly for the forms their text states: the `False`-on-daily-cap mechanism is coherent for the walk driver (the driver CAN check the return before the try); release-no-refund is unambiguous as written (the semaphore-slot-only rule is clear); the per-provider allowlist concept is right (arXiv `atom+xml`, PMC `text/xml` — no blanket JSON check); the construction-time profile validation and the fixed UTC window are complete; the gate-not-wrapper decision (RT-07) resolves the double-limit reading. The six findings are boundary/precedence gaps between the limiter/transport and the ALREADY-SHIPPED hazard evaluator — the interface the step-4 code must not silently cross.

## Overall verdict: **MERGE WITH REMEDIATION (second gate).**

**RT2-01 is gate-blocking**: as written, the exception map would kill the answered-lookup mechanism and the Retry-After path — the transport must raise ONLY for transport-level failures and defer ALL HTTP statuses to `evaluate_hazards`. **RT2-02/03/04** are signal-domain, code-shape, and precedence pins the step-4 implementation must carry. **RT2-05/06** are P3 pins for the step-4/5a fixture plan. All six land in §6.1/§6.1a + contract §6 text — no redesign, no new components — and the fold-in (design text + the step-4 fixture plan) is the standing condition before `ratelimit.py`/`http.py` are written.

## Disposition — FOLDED IN (2026-08-14)

| ID | Decision | Where it lands |
|---|---|---|
| RT2-01 | `http.py` raises ONLY for TRANSPORT-LEVEL failures (timeout/connection → `TIMEOUT`, size → `PARTIAL_CONTENT`); ALL HTTP statuses deferred to `evaluate_hazards` (the single status classifier — 404 `VALID_NEGATIVE` and 429 `THROTTLED`/`note_throttled` survive) | §6.1a exception map; contract §6.3 |
| RT2-02 | `False` reserved for the daily cap; admission waits bounded by construction + the named `ADMISSION_WAIT_BOUND` (default 60s) safety net; expiry → `False` as a THROTTLED-class admission failure, causes distinguished in notes (`daily_cap_exhausted` vs `admission_wait_expired`) | §6.1 policy bullet; contract §6.1 |
| RT2-03 | the return check happens BEFORE the try — `if not limiter.acquire(...): return None, "THROTTLED", "THROTTLED"` — a `False` never reaches `finally: release` (no semaphore underflow) | §6.1 release bullet; contract §6.1; step-4 fixture |
| RT2-04 | the content-type check moves into the evaluator — `TransportResponse.content_type` + `HazardContext`; per-provider allowlist consulted in the fixed order AFTER status verdicts (status evidence dominates: a 429/404 with a mismatched content-type keeps its verdict) | §6.1a content-type bullet; contract §6.3; `base.py` field + evaluator (step-4 impl) |
| RT2-05 | step 5a's `fetch_batch` maps a `False` acquire → `FetchFailure(THROTTLED)`, never an unhandled bool, never a retry | §6.1 release bullet; step-5a fixture plan |
| RT2-06 | `_fetch_page`'s catch-all RE-RAISES non-`ProviderError` exceptions (a transport bug is loud, never a `MALFORMED_200` schema verdict) | §6.1a exception map; contract §6.3; step-4 driver edit |

**Status: FOLDED IN (2026-08-14).** The step-4 design text (blueprint §6.1/§6.1a + contract §6) is remediated per the table; the step-4 fixture plan pins the status-deferral, the `False`-reservation + `ADMISSION_WAIT_BOUND`, the before-the-try check, the evaluator-hosted content-type with status dominance, and the catch-all re-raise. The standing condition is satisfied — `ratelimit.py`/`http.py` may be written against the remediated text.
