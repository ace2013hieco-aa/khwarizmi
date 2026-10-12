# Adversarial Audit — WK-remediated walk driver, third gate (post-WK fold-in)

**Scope:** protest-stage attack on ONLY the four surfaces the WK fold-in fixed, against the **shipped** `src/hermes/tools/providers/paginate.py` (`walk()` + `combine()` + `_fetch_page()`) + `src/hermes/tools/providers/base.py` — (1) the `answered_no` shortfall consult (WK-01), (2) the `UNAVAILABLE`-excluding shortfall scan (WK-02), (3) the §4.1 (d) check before the bound branches (WK-04), (4) the per-attempt `limiter.acquire` (WK-05). Method: treat the WK dispositions as settled only where the shipped code actually enforces them; probe each surface for the SAME bypass/silent-failure classes (a masked leg, a suppressed trigger, a stale-total acceptance, an unaccounted request) plus the cross-surface mixes the fixes interact on. Every finding quotes the actual verdict/aggregate output (probes A–H) or is a structural code-reading pin.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| WK3-01 | **P2** | `_fetch_page` acquire / base.py Protocol | **Acquire-without-release: the lease reading of the limiter contract deadlocks the retry path and leaks one slot per walk.** The WK-05 fix moved `acquire` per-attempt but nothing ever calls `release`, and the Protocol declares it (base.py `ProviderRateLimiter.release`); the shipped `RateProfile` carries `concurrency: 1`. Probe F (a concurrency-1 lease limiter): a throttled-then-retried page BLOCKS on the 2nd acquire (`slot exhausted (previous acquire never released)`), and a single-request walk completes with `held = 1` — the slot leaks, deadlocking the next walk on the same provider (probe F) |
| WK3-02 | **P3** | `combine` scan | **The `o.aggregate == "PARTIAL"` disjunct is dead for driver output and enables an unexplainable `PARTIAL` for hand-built outcomes.** `_single_provider_aggregate` returns `PARTIAL` only after its own SHORTFALL/UNKNOWN note scan hits, so every driver-produced `PARTIAL` outcome already carries a prefix note — the disjunct fires only for outcomes a caller constructs with `aggregate="PARTIAL"` and no note, a `PARTIAL` the note-reading caller (WS-05) cannot explain (code-reading pin) |
| WK3-03 | **P3** | `walk` (d) total | **The (d) total is last-reported and a cross-page total-decline has no named cause.** Probe E: page-1 `total=50` (zero records, cursor) → page-2 `total=0` (no cursor) lands `SHORTFALL(cause=EMPTY_MID_WALK)` — no silent acceptance (the anomaly IS flagged), but the declining-total case rides `EMPTY_MID_WALK` instead of a `total_declined` cause; a monotonic-decline check would name it (fidelity, not a bypass) |

## Detail

**WK3-01 — The limiter contract is acquire-only as written; the lease reading deadlocks. (P2)**

The WK-05 fix's own comment says "the limiter is the rate authority AND the budget ledger's cost input (AR-02)". Two readings are defensible:

- **Charge-only** (a token bucket): `acquire` decrements a budget, `release` is a no-op. The driver's acquire-per-request is complete and correct.
- **Lease** (a concurrency slot — the Protocol's `release` and the shipped `RateProfile.concurrency: 1` anticipate this): `acquire` must be paired with `release`.

`paginate.py` never calls `release` (grep: the only `limiter.` sites are `acquire` at line 489 and `note_throttled` at line 513). Probe F with a concurrency-1 lease limiter:

```
script: [429(retry-after: 5), clean]
attempt 1: acquire (held=1) → request → 429 → note_throttled → backoff
attempt 2: acquire → held >= 1 → RuntimeError("slot exhausted (previous acquire never released)")
→ the retried page BLOCKS the walk
single-request walk (no retry): completes with held=1 → slot LEAKED
→ the next walk on the same provider blocks on its first acquire
```

The failure is real for the retry path and for any second walk; nothing in the shipped code makes the charge-only reading binding. **Fix (one of):** (a) `_fetch_page` wraps each attempt — `acquire` → try/`transport.request` → `finally: release` (per-request lease); or (b) pin the contract in `base.py` + the `ProviderRateLimiter` docstring as **charge-only** (release is a no-op, no concurrency-slot semantics) before step 4 implements the real limiter. The choice must land with step 4; today the driver and the declared contract disagree on the release side.

**WK3-02 — The `PARTIAL` disjunct is redundant for driver output. (P3)**

`combine`'s scan:

```python
any_shortfall_or_unknown = any(
    o.aggregate != "UNAVAILABLE"
    and (o.aggregate == "PARTIAL"
         or any(n.startswith(_SHORTFALL_PREFIX) or n.startswith(_UNKNOWN_PREFIX) for n in o.notes))
    for o in ordered
)
```

`_single_provider_aggregate` returns `"PARTIAL"` only via `if any(n.startswith(SHORTFALL/UNKNOWN) ...)` — so a driver-produced `PARTIAL` outcome ALWAYS carries a prefix note and the first disjunct never fires on shipped output. It fires only on hand-built outcomes (a caller constructing `SearchOutcome(aggregate="PARTIAL")` with bare notes), where it yields a `PARTIAL` whose cause the WS-05 note-reading contract cannot explain. The note scan alone is the single source of truth; the disjunct should be dropped or the notes made mandatory.

**WK3-03 — (d)'s total is last-reported; declines ride `EMPTY_MID_WALK`. (P3)**

`total` is overwritten by every non-`None` page total. Probe E — page-1 `total=50` (zero records, live cursor) then page-2 `total=0` (zero records, no cursor):

```
→ SHORTFALL(cause=EMPTY_MID_WALK)   # the anomaly IS flagged — no silent COMPLETE(retrieved==total)
```

No bypass (the stale-positive total can never produce a silent acceptance: any zero-delivered multi-page walk trips `EMPTY_MID_WALK` via `pages_done > 1`, and a single zero-delivered page with `total > 0` trips (d) itself). The gap is diagnostic: the declining-total case gets no named cause, and a provider that revises 50 → 0 across pages is indistinguishable in the notes from a provider that simply went empty. A monotonic-decline check (`page.total > previous total` → note) would name it.

## What survives — the four WK fixes hold exactly for their declared forms, and the cross-surface mixes are clean

| Probe | Mix | Result |
|---|---|---|
| A | answered + DOWN + searched-failed (three legs) | `PARTIAL` — the WK-02 exclusion does NOT let the down leg mask the failed leg; the WK-01 consult still fires |
| B | answered + clean-empty | `COMPLETE` — matrix (d) preserved; the WK-01 fix does not over-trigger |
| C | delivered + clean-empty + down | `COMPLETE` — WK-02 exclusion + matrix (a); down recorded in notes only |
| D | delivered + bounded-no-total UNKNOWN leg (zero delivered via MALFORMED_ROWs) | `PARTIAL` — the UNKNOWN prefix counts; the WK-03 split feeds the scan correctly |
| E | (d) total-decline | `SHORTFALL(cause=EMPTY_MID_WALK)` — no silent acceptance |
| G | answered + UNKNOWN-no-total leg | `PARTIAL` — consistent with the WK-01 rule as written |
| H | `PARTIAL` without a prefix note | unreachable for driver output (code-reading pin) |

The answered-no consult, the exclusion, the (d)-before-bounds ordering, and the per-attempt acquire all behave as the WK dispositions specify for their fixtures AND under the cross-surface mixes the fixtures don't pin. The three findings are contract/fidelity gaps — one of them (WK3-01) gate-blocking for step 4 because step 4 *implements the real limiter* and must know whether `release` is part of the driver's obligations.

## Overall verdict: **MERGE WITH REMEDIATION (third gate).**

**WK3-01** is the gate: the acquire/release contract must be pinned (per-request release in `_fetch_page`, or charge-only declared in `base.py` + the limiter docstring) before or with step 4 — under the Protocol's own `release` + `RateProfile.concurrency: 1`, the shipped driver demonstrably deadlocks the retry path. **WK3-02/03** are one-line robustness/fidelity pins. All three land in `paginate.py`/`base.py` — no redesign, no new components — and the fold-in (code + regression fixtures for the three probes) is the standing condition before step 4 writes `ratelimit.py`.

## Re-check (2026-08-14, against the fixed code)

| Probe | Before | After |
|---|---|---|
| F (lease limiter, retried page) | BLOCKED on the 2nd acquire (`slot exhausted (previous acquire never released)`); single-request walk leaked `held=1` | acquires=2, releases=2, held=0 — the retry completes, no slot leaks (per-request try/finally `release` in `_fetch_page`) |
| H (hand-built `aggregate="PARTIAL"`, no note) | `PARTIAL` (unexplainable under WS-05) | `COMPLETE` — the scan keys solely on the SHORTFALL/UNKNOWN notes (disjunct dropped); driver-produced PARTIALs (with their notes) still trigger |
| E (total-decline 50 → 0) | `SHORTFALL(cause=EMPTY_MID_WALK)` with no named cause | same verdict + `total_declined: 50 -> 0` note; a rise/equality is not a decline |

**Status: FOLDED IN (2026-08-14).** All three flipped to the contract behaviors. **3 regression fixtures added (40 in `tests/test_provider_walk.py`, 732 passed suite-wide, pyright 0 errors);** the WK3 fold-in is verified against the running code — the step-3 gate is clear for step 4 (which implements the real limiter under the now-pinned acquire/release behavior).
