# STEP 5A — FETCH DRIVER — IMPLEMENTATION GATE (§20)
## Gate record on `hermes_researchsourceprovider_fetch_gate_remediation.md`

**Role:** the §20 implementation gate. Scope: a hostile review of the three surfaces
the remediation record restructured — **A1** (the `FetchedPayload` transient carrier),
**F3** (the hazards.py scope-closure guard), **F1** (the memory envelope) — for the
same bypass and silent-failure classes, cross-checked against the shipped code
(`hazards.py` `_verdict`/`evaluate_hazards`, `paginate.py` `_PERMANENT_CLASSES`/
`_fetch_page`, `research_sources.py` types, `ratelimit.py`/`http.py`). No production
code exists for `fetch_batch`; this is a design-text gate with shipped-code inspection.
Findings `GC-01…GC-03`, all P2/P3.

## VERDICT: **ACCEPTED FOR IMPLEMENTATION** (with conditions GC-01…GC-03)

No P1 design defect remains. The three restructured surfaces are sound in mechanism;
the conditions are implementation-shape pins that must land in the code and its
golden fixtures, not design rework. Per §20, no REMEDIATION REQUIRED is declared.

---

## Detail

### GC-01 (P2) — the F3 closure guard must live in `_verdict`, not at an exit point

The remediation record says "a scope-closure check at the evaluator boundary" — that
wording leaves the placement ambiguous, and a misplaced check is a silent-failure
class: `evaluate_hazards` has **20+ `return _verdict(...)` paths** (status verdicts,
throttle signature, valid-negative, drift, markers, rewrite, injection, the fetch
block, the `NONE` fall-through — verified at `hazards.py:1072–1388`). A guard placed
at a single exit point would be structurally bypassed by every early return.

**Verified sound:** `_verdict` (`hazards.py:491`) is the **single verdict-construction
helper** — every return path flows through it. The guard therefore belongs **inside
`_verdict`**: it takes the scope (passed from `evaluate_hazards`, which already
validates `scope ∈ {SEARCH, FETCH}` at entry) and rejects a class outside the scope's
closed taxonomy with `SpecValidationError`. That makes the invariant structural — no
return path can escape, now or after any future edit.

**The two closed sets, cross-checked against the shipped walk** (`_PERMANENT_CLASSES =
{MALFORMED_200, REWRITE_SUSPECT, CURSOR_TRAP, PARTIAL_CONTENT}`, `paginate.py:143`;
`EMPTY_RESULT` is deliberately NOT permanent at SEARCH — it flows the page shape,
WS-02; `VALID_NEGATIVE` is handled by the walk loop; `NO_FULL_TEXT` is fetch-only):

- `FETCH_ALLOWED = {NONE, MALFORMED_200, EMPTY_RESULT, PARTIAL_CONTENT, THROTTLED,
  TRANSIENT, INJECTION_SUSPECT, NO_FULL_TEXT}`
- `SEARCH_ALLOWED = {NONE, MALFORMED_200, EMPTY_RESULT, PARTIAL_CONTENT, THROTTLED,
  TRANSIENT, REWRITE_SUSPECT, CURSOR_TRAP, INJECTION_SUSPECT, VALID_NEGATIVE}`

Both must be enumerated in the record (the current text names `FETCH_ALLOWED`/
`SEARCH_ALLOWED` without the sets). The registration side needs no change today — the
shipped fetch block emits only FIXED classes (no fetch-side construct declares a
`failure_class`; `FetchHazardRules.error_field`/markers/composites hardcode their
classes in step 6a) — but the record should state the rule for the future: any
fetch-side construct that gains a declared class must be restricted to `FETCH_ALLOWED`
at registration (the belt to the `_verdict` suspenders).

### GC-02 (P3) — the payload↔`per_source` binding is positional; the contract must be identity-keyed

The remediation record says `payloads` is "order-aligned with `per_source` (only
FETCHED entries)". By construction today the driver appends both in the same
per-source loop, so no mismatch is currently possible — but "order-aligned" invites a
positional `zip()` in the future task write path, and a future driver edit (reorder,
skip, conditional append) would silently misbind payloads to sources.

**Pin:** the consumer contract is dereference-by-`artifact_id` —
`payloads[i].artifact.artifact_id == per_source[i].artifact.artifact_id` — never by
position. The invariant becomes a golden fixture (alongside the FD-06
`sha256(raw) == content_hash` cross-check): exactly one payload per `FetchedSource`
with a matching artifact id, and zero payloads for any failure. This closes the
silent-corruption class at the write path before it exists.

### GC-03 (P3) — the F1 envelope text must document three inherited behaviors it currently omits

The product bound (`max_sources × size_cap_bytes`) is correct as the worst case, and
the driver's one-active-body claim holds (the `FetchedPayload.raw_bytes` is the
transport's body bytes by reference — immutable, shared, no defensive copy, so no 2×
peak). Three inherited behaviors must be stated so the envelope is honest:

1. **The per-body cap applies on 2xx only.** The transport's streaming size-abort is
   deliberately 2xx-only (RT3-01 — an oversized 429 stays `THROTTLED`, never
   `PARTIAL_CONTENT`); a non-2xx response body is read in full before the evaluator
   classifies. A pathological 429 with a large body is a one-body memory spike that no
   cap bounds — audited transport tradeoff, classification correctness over streaming.
2. **A `THROTTLED` body is held through the driver's backoff sleep** — in `_fetch_page`
   the verdict + `_backoff` run while `resp` is still in scope (the body is released at
   attempt end, not before backoff). Still one body at a time, but the sleep rides the
   body.
3. **The batch envelope's control is the task's `FetchRequest` sizing** (the S11 scale
   classes, the D4 discipline: "the task sizes its FetchRequest to its own stream") —
   the driver never exceeds the product, and the caller is the sizing authority.

## What survives — verified, not assumed

- **The guard-in-`_verdict` mechanism is structurally complete** — all 20+ return
  paths flow through the single construction helper; no early return can escape a
  guard placed there (GC-01's placement pin, not a rework).
- **The closure sets are correct against the shipped walk** — cross-checked
  `_PERMANENT_CLASSES`, the EMPTY_RESULT-not-permanent rule, the walk's VALID_NEGATIVE
  handling, and the fetch-only NO_FULL_TEXT (GC-01's enumeration).
- **The A1 carrier decision is sound** — separate transient carrier on
  `FetchOutcome.payloads`, `FetchedSource` ratified shape untouched, frozen dataclass +
  immutable bytes, no defensive copy; the only open point is the binding contract
  (GC-02).
- **The F1 envelope is bounded by construction** — one active body during the walk,
  Σ payloads ≤ `max_sources × size_cap_bytes` at the outcome, failed sources retain
  zero bytes; the open points are documentation of inherited transport/backoff
  behaviors (GC-03).
- **F2/F4/F5/F6/F7/F8/F9/F10/F11/F12/F13 and the FD-01…FD-07 fold-in** were not
  re-attacked by this gate (out of its stated scope — they passed the prior gates);
  no interaction found between them and the three surfaces here.

## Disposition

| ID | Severity | Decision | Where it lands |
|---|---|---|---|
| GC-01 | P2 | The closure guard lives in `_verdict` (scope passed from `evaluate_hazards`); both ALLOWED sets enumerated in the record; the registration rule for future fetch-side declared classes stated | `hermes_researchsourceprovider_fetch_gate_remediation.md` D-F3 + G; `hazards.py` at implementation |
| GC-02 | P3 | The payload contract is dereference-by-`artifact_id`; invariant fixture (one payload per `FetchedSource`, id match, zero for failures) | remediation record A1/K/L; `tests/test_provider_fetch.py` |
| GC-03 | P3 | The envelope text documents the 2xx-only per-body cap, the backoff-held throttled body, and the task-sizes-its-request control | remediation record K |

**Status:** the step-5a design is **ACCEPTED FOR IMPLEMENTATION** — `fetch_batch` may
be written per the gate-remediated record, carrying GC-01…GC-03 into the code and the
`tests/test_provider_fetch.py` golden fixtures. The slice remains NOT
ratified-as-implemented until step 7's adversarial review + §27 item 55 record.
