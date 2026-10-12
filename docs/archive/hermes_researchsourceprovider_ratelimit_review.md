# Adversarial Review — Step-4 limiter/transport design (pre-implementation)

**Scope:** protest-stage attack on the step-4 DESIGN text before any code — `ratelimit.py` (`ProviderRateLimiter`: §6.1 blueprint, §6 contract) and `http.py` (the single HTTP client with the S11 defaults) — against the SHIPPED driver's actual acquire/release/exception shape in `src/hermes/tools/providers/paginate.py` + `base.py` (the `ProviderRateLimiter` Protocol and `RateProfile`). Method: treat the design's claims (per-provider token bucket + semaphore + global concurrency + FIFO fair-share, daily-cap hard stop → `SHORTFALL(THROTTLED)`, S11 defaults) as obligations and check whether the design text + the driver's current shape can satisfy them. Every finding quotes the design text it contradicts or leaves open, and is verified against the running driver's code shape (no limiter code exists yet — this is a design-text review, the WS-review precedent). Probes: code-reading pins against `_fetch_page` (the acquire is OUTSIDE the try; `transport.request` is inside `except Exception`).

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| RT-01 | **P1** | daily-cap hard stop vs `walk()` invariant | **The daily-cap hard stop has no specified surface in the acquire/release API — the walk's never-raises invariant and the promised `SHORTFALL(THROTTLED)` both depend on a mechanism the design doesn't define.** `limiter.acquire` sits OUTSIDE `_fetch_page`'s try (paginate.py:514): if the limiter raises on a daily-cap hit, the exception escapes `walk()` — violating its "Never raises for a verdict" docstring; if it BLOCKS, the retry loop hangs. Neither produces the blueprint's "daily cap hard-stop → `SHORTFALL(THROTTLED)`" test row (blueprint §step-4). Fix: pin a non-raising policy surface — a non-blocking check the driver maps to the THROTTLED verdict, or a THROTTLED-equivalent sentinel from acquire |
| RT-02 | **P1** | `http.py` exception taxonomy | **The transport's exception classes are unpinned — a bare timeout/socket error hits `_fetch_page`'s `except Exception` and is mislabeled `MALFORMED_200` (a PERMANENT class).** §6.3 calls timeouts transient, but nothing says http.py raises `TransientProviderError(hazard_class="TIMEOUT")` — a bare `socket.timeout`/`requests.Timeout` is caught by the generic handler (paginate.py:520) and the walk fails permanently on a transient condition, exactly the silent-misclassification class the hazard taxonomy exists to prevent. Fix: http.py's exception map (timeout/size/content-type → named hazard classes) pinned like the redaction-`from None` rule |
| RT-03 | **P2** | release contract | **`release`'s contract is unspecified — under the driver's per-request acquire/release, a release that refunds a TOKEN hollows the rps/burst bucket (a walk could loop at burst speed); release must return the semaphore slot only.** §6.1 says "acquire: blocking; token bucket + semaphore" and lists `release` with no doc |
| RT-04 | **P2** | fair-share slices | **The per-task fair-share claim is unimplementable with `acquire(provider: str)` — there is no task handle in the API and the driver passes none; either the signature grows a task token or the fair-share claim must be dropped from §6.1** |
| RT-05 | **P2** | S11 content-type check | **The content-type check is provider-blind — arXiv/PMC serve XML (`application/atom+xml`, `text/xml`), so a blanket JSON content-type check in http.py would reject canonical providers; the check must be per-provider (card-declared) or advisory with the drift sentinel as backstop** |
| RT-06 | **P2** | search-page size cap | **S11 "size caps apply verbatim to `fetch`" (§11) — the WALK's page loop has no size cap at all; an oversized SEARCH response (reject vs truncate vs `PARTIAL_CONTENT`) is undefined** |
| RT-07 | **P2** | wraps-the-transport claim | **§6.1 asserts BOTH "the limiter wraps the transport" and a driver-facing `acquire/release` API — if the driver holds a limiter-wrapped transport, its own acquire+release double-limits every request; if it holds the raw transport, the "wraps" claim is a call convention, not structure (the same class as AR-01). Pick one: driver holds raw transport + separate limiter gate, or wrapped transport with NO driver-side acquire/release** |
| RT-08 | **P3** | backoff division | **Both the driver's `_backoff` (clock.sleep, paginate.py) and the limiter's Retry-After bucket backoff exist — who sleeps for the CURRENT caller vs shapes future acquires is unspecified (double-delay risk)** |
| RT-09 | **P3** | profile validation | **Zero/negative `rps`/`burst`/`concurrency`/`daily_cap` semantics are deferred to "validated at P7" — construction-time rejection (fail-closed) must be defined by step 4, or a misconfigured profile means a dead provider or an unlimited one** |
| RT-10 | **P3** | daily-cap window | **"Hard stop for the day" — the window's reset point (UTC midnight from which clock?) is unspecified** |

## Detail

**RT-01 — The daily-cap hard stop has no surface. (P1)**

The blueprint test row promises "daily cap hard-stop → `SHORTFALL(THROTTLED)`" and contract §6.1 says "A daily cap is a hard stop for that provider for the day (recorded in the request log + `search_accounting`); the walk reports `SHORTFALL(THROTTLED)` rather than hammering." But the API has only `acquire` (blocking), `release`, `note_throttled` — and the shipped driver calls `limiter.acquire(spec.provider_id)` OUTSIDE `_fetch_page`'s try (paginate.py:514). Three failure modes, none producing the promised verdict:

```
(a) acquire RAISES on the cap  → the exception escapes _fetch_page (acquire is
    outside the try) → escapes walk() → the "Never raises for a verdict"
    invariant (walk docstring) is violated; the caller sees an untyped error
    instead of a SHORTFALL(THROTTLED) outcome
(b) acquire BLOCKS on the cap  → the walk's retry loop hangs at the acquire
    (the driver retries ≤ max_retries, each retry calling acquire again)
(c) acquire returns "ok" and the cap is checked later → the cap is advisory
```

The design intends (a) or (b) to become a SHORTFALL(THROTTLED) verdict — the mechanism (a non-raising "can I go?" check, or a THROTTLED-equivalent sentinel the driver maps in `_fetch_page`) is simply absent. **Fix: pin the policy-exception contract — the limiter NEVER raises out of `acquire` for a policy condition; it either blocks with a bounded cap-wait or returns a sentinel the driver maps to the THROTTLED failure path (which already exists: `_fetch_page` treats a THROTTLED hazard as retryable → exhaustion → `SHORTFALL(cause=THROTTLED)`).**

**RT-02 — The transport's exception taxonomy is unpinned. (P1)**

§6.3: timeouts are **transient**. The driver's `_fetch_page`:

```python
        try:
            resp = transport.request(req)
        except TransientProviderError as exc:
            last_failure = exc.hazard_class or "TRANSIENT"
            _backoff(...); continue
        except Exception as exc:
            cls = getattr(exc, "hazard_class", "MALFORMED_200") or "MALFORMED_200"
            return None, cls, cls
```

A bare `socket.timeout`/`requests.exceptions.Timeout` has no `hazard_class` → `cls = "MALFORMED_200"` → the walk fails PERMANENTLY with a schema-drift verdict on a transient condition. The design's redaction rule is pinned to the exception (`from None`, redacted messages — PS-02/PS3-07) but the CLASS of every transport exception is not. **Fix: http.py raises only `ProviderError` subclasses with named `hazard_class` (`TIMEOUT` → `TransientProviderError`, size-cap → a permanent class, content-type → advisory/drift) — the same `from None` discipline, extended to the class map; `_fetch_page`'s generic `except Exception` becomes unreachable for transport failures.**

**RT-03 — What does `release` release? (P2)**

§6.1: "acquire: blocking; token bucket + semaphore". The driver (WK3-01-pinned) acquires and releases per request. If `release` refunds a token, a burst of requests can loop at `burst` speed forever (each release replenishes the bucket) — the rps axis becomes decorative. Token buckets never refund; the semaphore slot is the only releasable resource. The design must say so, or a naive limiter implements a refund and the rate limit is hollow.

**RT-04 — Fair-share slices need a task handle. (P2)**

§6.1/§6 contract: "FIFO with per-task fair-share slices". `acquire(provider: str)` carries no task identity, and the driver passes none — the limiter cannot distinguish walk A's acquires from walk B's, so "per-task slices" is unimplementable with this API. Either the signature grows (`acquire(provider, task_token)`) or the claim is dropped. The design text asserts a capability the API cannot express.

**RT-05 — The content-type check is provider-blind. (P2)**

S11: "content-type checks apply verbatim to fetch" (§11) — and the step-4 line says http.py carries them. But the canonical providers include arXiv (Atom XML, `application/atom+xml`) and PMC (`text/xml`/NXML). A blanket JSON-only content-type check in http.py rejects canonical providers before the hazard evaluator ever sees them; the drift sentinel (`required_fields` → `MALFORMED_200`) is the existing shape-aware backstop. The check must be per-provider (declared on the contract card) or advisory.

**RT-06 — The search-page size cap is undefined. (P2)**

S11 says size caps "apply verbatim to `fetch`" — and only fetch. The walk's page loop (paginate.py) has no size concept; `WalkRequest` carries `max_pages`/`max_results` but no byte cap. An oversized SEARCH response (a 100 MB JSON dump) is ungoverned: reject, truncate (→ drift sentinel), or `PARTIAL_CONTENT`? The design names the fetch cap (`size_cap_bytes` per artifact) but never the search-page cap.

**RT-07 — "Wraps the transport" vs the driver's acquire/release. (P2)**

Contract §6.1: "the limiter wraps the single HTTP client the Tool Runtime owns" — the only-entry-point claim. Blueprint §6.1: "it wraps the transport, not the adapter". But the driver's shape has the driver call `limiter.acquire` → `transport.request` → `limiter.release` with the RAW transport passed to `walk(...)`. Two readings, both broken as written: (a) the driver holds a limiter-WRAPPED transport → its own acquire+release plus the wrapper's internal acquire double-limits every request; (b) the driver holds the raw transport → the "wraps" claim is a call convention, not structure — nothing stops a future component from calling `transport.request` without the limiter (the AR-01 class). **Fix: pick one — driver holds the raw transport and the limiter is a separate gate (current shape, needs the "only the driver calls the transport" invariant enforced structurally), or the driver holds a wrapped transport and its acquire/release calls are removed.**

**RT-08 — Two backoff authorities. (P3)**

The driver's `_backoff` (exponential + jitter, `clock.sleep`) and the design's "a THROTTLED response backs off that provider's bucket" are both in the retry path. If the bucket backoff sleeps the CURRENT caller AND `_backoff` sleeps, a throttled retry is double-delayed; if the bucket only shapes future acquires, fine. Unspecified.

**RT-09 — Profile validation deferred. (P3)**

§6.2: "validated at P7". Step 4's limiter must decide at construction what `rps=0`/`burst=0`/`daily_cap=0`/negative mean — fail-closed (reject the profile) or a dead/unlimited provider. A misconfigured profile with a hollow bucket is the under-accounting class (AR-02's cost input) at the source.

**RT-10 — The daily-cap window. (P3)**

"Hard stop for the day" — which day? UTC midnight per `clock.now_utc`? The window and its reset are unspecified; a sliding vs fixed window changes the cap's meaning.

## What survives

The design's architecture is sound where it commits: the limiter is a Tool-Runtime-owned authority, not per-task, not in adapters (PS-03 preserved); `Retry-After` + the arXiv plain-text throttle path are handled by the hazard-spec mechanism that already exists; the budget-ledger scoping (§6.4 — provider policy ≠ task cost, DEFERRED AR-02) is honest and prevents the limiter from being mistaken for a budget authority; the redaction `from None` discipline is already folded into §6.2. The walk driver's per-request acquire/release (WK3-01) is the right shape for the semaphore axis — the gaps are the POLICY-exception surface (RT-01), the exception class map (RT-02), and four contract pins (RT-03…RT-06).

## Overall verdict: **MERGE WITH REMEDIATION.**

**RT-01/RT-02 are gate-blocking** for step 4: the daily-cap verdict and the transient retry both depend on exception/policy surfaces the design leaves undefined, and both would silently misclassify (a raise breaking `walk()`'s never-raises invariant; a bare timeout becoming a permanent `MALFORMED_200`). **RT-03…RT-07** are contract pins (release semantics, the fair-share signature, per-provider content-type, the search-page size cap, the wraps-vs-gate contradiction) that must land before `ratelimit.py`/`http.py` are written. **RT-08…RT-10** are P3 pins for the step-4 fixture plan. All ten land in the blueprint §6.1/§6.2 + contract §6 text and the step-4 implementation — no redesign, no new components — and the fold-in is the standing condition before step 4 writes code.

## Disposition — FOLDED IN (2026-08-14)

| ID | Decision | Where it lands |
|---|---|---|
| RT-01 | `acquire(provider) -> bool` — `False` WITHOUT blocking/raising on a hard policy stop (daily cap); the driver maps it to the THROTTLED verdict (`SHORTFALL(cause=THROTTLED)`), no retry | §6.1 policy-exception contract; step-4 driver change (check the return) |
| RT-02 | http.py raises ONLY `ProviderError` subclasses with named `hazard_class` (`TIMEOUT` → `TransientProviderError`); `_fetch_page`'s generic `except Exception` unreachable for transport failures | §6.1a exception class map; contract §6.3 |
| RT-03 | `release` returns the semaphore slot only — tokens never refunded | §6.1 release contract; contract §6.1 |
| RT-04 | per-task fair-share claim DROPPED (unimplementable with `acquire(provider)`); FIFO kept; task cost = the future budget ledger (§6.4) | §6.1 bullet; contract §6.1 |
| RT-05 | per-provider `content_types` allowlist on the contract card (arXiv `application/atom+xml`, PMC `text/xml`); mismatch with a declared allowlist → `MALFORMED_200`; without one → advisory + drift sentinel | §6.1a; contract §5.2 cross-ref |
| RT-06 | `WalkRequest` gains `size_cap_bytes` (S11 scale class); oversized page → `PARTIAL_CONTENT` (permanent), never silent truncation | §6.1a; contract §6.3 permanent row |
| RT-07 | the limiter is a GATE, not a wrapper — the driver holds the raw transport; `transport.request` has exactly one call site (the driver) | §6.1 wraps-vs-gate bullet; contract §6.1 |
| RT-08 | the bucket backoff shapes FUTURE acquires only (refill at rps) — never sleeps the current caller; the driver's `_backoff` is the only caller-sleep | §6.1; contract §6.1 |
| RT-09 | fail-closed profile validation at construction (`rps > 0`, `burst >= 1`, `concurrency >= 1`, `daily_cap > 0` → else `ValueError`); operator config validation stays at P7 | §6.1; contract §6.2 |
| RT-10 | fixed UTC daily-cap window — midnight per `clock.now_utc`'s date | §6.1; contract §6.1 |

**Status: FOLDED IN (2026-08-14).** The step-4 design text (blueprint §6.1/§6.1a + contract §6) is remediated per the table; the step-4 fixture plan now pins the daily-cap `False` sentinel, the `TIMEOUT` transient class, release-no-refund, per-provider content-type, and the `size_cap_bytes` `PARTIAL_CONTENT` rule. The standing condition is satisfied — `ratelimit.py`/`http.py` may be written against the remediated text.
