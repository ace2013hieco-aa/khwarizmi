# P-AUTO-3 Redteam Audit Report

**Branch**: `audit/p-auto-3-redteam` (from `main@e5f06a7`)
**Slice under audit**: `slice/p-auto-3-fetch@0298b4e`
**Date**: 2026-10-02

---

## Executive Summary

| Attack Vector | Verdict | Severity |
|---------------|---------|----------|
| A) Allowlist bypass | **FAIL** | MUST-FIX (redirect bypass), SHOULD-FIX (DNS rebinding) |
| B) Envelope completeness | PASS | — |
| C) Adapter overrides vs fixture determinism | **FAIL** | SHOULD-FIX (parser version not bumped) |
| D) Timeout absence (hung-fetch) | **FAIL** | SHOULD-FIX (no overall deadline) |
| E) Rate-limiter restart semantics | PASS (code) / FAIL (test) | NOTE (test bug) |
| F) Live-test authenticity | PASS | — |
| G) Journal/provenance completeness | PASS | — |

---

## A) Allowlist Bypass — **FAIL** (MUST-FIX + SHOULD-FIX)

### A1: Redirect Out of Allowlist — **MUST-FIX**

**Location**: `src/hermes/tools/providers/http.py:143` (`urllib.request.urlopen`)

**Finding**: The `_AllowlistedTransport` in `live_fetch.py:79-103` validates the **initial request URL** against the allowlist. However, `ProviderHTTPTransport` uses `urllib.request.urlopen()` which **follows HTTP redirects (3xx) by default** without any allowlist re-validation on the redirect target.

**Impact**: If `api.openalex.org` returns a `302 Location: https://evil.example.com/steal`, the request will be issued to `evil.example.com` — completely bypassing the code-owned allowlist.

**Evidence**: Confirmed via test — `urllib.request.urlopen` follows redirects to `httpbin.org/redirect/1` → `httpbin.org/get`.

**Fix Required**: Install a custom `urllib.request.HTTPRedirectHandler` that either:
- (a) Disables redirects entirely (fail on 3xx), or
- (b) Validates each redirect target against the allowlist before following.

---

### A2: DNS Rebinding of API Hosts — **SHOULD-FIX**

**Location**: `src/hermes/research/live_fetch.py:79-103` (`_AllowlistedTransport.request`)

**Finding**: The allowlist validates **hostnames only** (`parsed.netloc.lower().split(":")[0]`). An attacker controlling DNS for `api.openalex.org` or `eutils.ncbi.nlm.nih.gov` could resolve the hostname to an internal IP (e.g., `127.0.0.1`, `169.254.169.254`, or private RFC1918 addresses), enabling SSRF.

**Impact**: In a deployment where the fetcher runs in a privileged network zone, this could expose internal services.

**Mitigation Context**: The architecture assumes the fetcher runs in a sandboxed/egress-controlled environment. DNS rebinding is a known limitation of hostname-based allowlists. Consider IP pinning or a DNS resolver that filters private ranges if the threat model requires it.

---

### A3: Scheme Tricks — **PASS**

**Location**: `src/hermes/research/live_fetch.py:91-94`

**Finding**: The transport explicitly refuses non-`https` schemes:
```python
if parsed.scheme != "https":
    raise ProviderValidationError(...)
```

---

### A4: Non-API Hosts — **PASS**

**Location**: `src/hermes/research/live_fetch.py:95-100`

**Finding**: Unknown hosts are refused before any I/O. The allowlist is exactly the four D5 hosts.

---

### A5: Config Widening — **PASS**

**Location**: `src/hermes/research/live_fetch.py:108-146` (`allowlist_from_config`)

**Finding**: Operator config can only **narrow** the code-owned allowlist. Entries outside the D5 surface are refused loudly.

---

## B) Envelope Completeness — **PASS**

**Location**: `src/hermes/security/boundaries.py` (`UntrustedContent`), `src/hermes/research/source_handlers.py` (`UntrustedContentView`)

**Finding**: All fetched/search text crosses the context boundary **only** as `UntrustedContent`:
- `UntrustedContent.__str__` / `__repr__` return a marker: `<UntrustedContent origin='fetched' ref='...' len=123>` — never the payload.
- Payload text is accessible **only** via explicit `.text` attribute (grep-auditable unwrap).
- `UntrustedContentView.search_results()` and `.fetched_text()` return only `UntrustedContent` — never raw `str`.
- Pyright strict rejects `UntrustedContent` where `str` is expected; `isinstance(c, str)` is `False`.

**Test Verification**: `test_fetched_payload_is_readable_only_via_envelope` asserts:
- `str(env) == repr(env)`
- `env.text not in str(env)`
- Payload never resolved without envelope.

**No leakage paths found** in the handler code (`source_handlers.py:450-627`).

---

## C) Adapter Overrides vs Recorded-Fixture Determinism — **FAIL** (SHOULD-FIX)

### C1: PubMed `parse_page` Added Without Parser Version Bump

**Location**: `src/hermes/tools/providers/adapters/pubmed.py:52-105` (+55 lines)

**Finding**: The new `parse_page` method handles both JSON (eutils) and XML (esearch) response formats. The existing replay fixtures (`tests/fixtures/p_auto_3_live/pubmed.json`) were recorded with `parser_version: "1"`. The adapter's `parser_version` attribute defaults to `"1"`.

**Risk**: `RecordedTransport` in replay mode checks `fixture.parser_version == adapter.parser_version` (`replay.py:442-447`). Since both are `"1"`, replay **uses the NEW parsing code on OLD fixture bytes**. If the new `parse_page` behaves differently from the pre-slice parsing logic, replay outcomes will diverge from the originally recorded evidence.

**Evidence**: The fixture contains a JSON search response from `eutils.ncbi.nlm.nih.gov`. The new `parse_page` has a `isinstance(payload, dict)` branch that extracts `esearchresult.idlist`. The old `JsonSearchAdapter.parse_page` (parent class) may have had different error handling or field extraction.

**Test Status**: `test_replay_is_deterministic` passes (two replay runs agree), but this only proves **current** determinism — not fidelity to the original recording.

**Fix Required**: Bump `PubmedAdapter.parser_version` to `"2"` and re-record fixtures, OR verify the new parser produces identical `SearchOutcome` records as the old parser for the fixture corpus.

---

### C2: OpenAlex `build_fetch_request` Added — **LOW RISK**

**Location**: `src/hermes/tools/providers/adapters/openalex.py:39-58` (+20 lines)

**Finding**: New method rewrites `openalex.org/W...` → `api.openalex.org/works/W...` for fetch. This affects **fetch** path only. Search fixtures are unaffected. Fetch fixtures include the rewritten URL in `normalized_request`, so replay uses the rewritten URL directly (the adapter's `build_fetch_request` is not called during replay — `RecordedTransport` serves the recorded response).

**Risk**: Low. Fetch replay serves recorded bytes; the adapter's fetch request builder is only used in live mode.

---

## D) Timeout Absence (Hung-Fetch Behavior) — **FAIL** (SHOULD-FIX)

### D1: No Overall Deadline for Multi-Call Operations

**Location**: `src/hermes/research/live_fetch.py:18` (`DEFAULT_PER_CALL_TIMEOUT_SECONDS = 10.0`), `src/hermes/tools/providers/http.py:106-107`

**Finding**: 
- `ProviderHTTPTransport` has a **per-call** timeout (default 10s, overridden to 10s in `live_fetch.py:224`).
- The timeout applies to `urllib.request.urlopen()` — connection + read.
- **No application-level deadline** bounds the total time for a search (which may paginate across multiple calls) or fetch batch.
- The controller's `max_ticks` limits tick count, not wall time. A single tick executing a slow `walk()` could block indefinitely if the transport hangs in a way the 10s timeout doesn't catch (e.g., DNS resolution, slowloris).

**Impact**: A hung fetch can stall the controller tick loop, delaying other tasks and potentially causing lease loss (`lock_lost` with rollback).

**Fix Required**: Add an overall deadline mechanism (e.g., `asyncio.wait_for`-style or monotonic deadline passed through the driver chain) for search/fetch operations.

---

### D2: DNS Resolution Not Subject to Timeout

**Location**: `src/hermes/tools/providers/http.py:143`

**Finding**: `urllib.request.urlopen` timeout may not cover DNS resolution in all Python versions/platforms. A malicious/slow DNS server could block the thread indefinitely.

**Fix Required**: Consider a DNS resolver with timeout, or run fetches in a thread pool with a hard timeout.

---

## E) Rate-Limiter Restart Semantics — **PASS** (Code) / **FAIL** (Test)

### E1: Code — **PASS**

**Location**: `src/hermes/research/live_fetch.py:24` (`RATE_LIMITER_PERSISTENCE`), `src/hermes/tools/providers/ratelimit.py:96-342`

**Finding**: 
- `ProviderRateLimiter` stores all state in instance variables (`_tokens`, `_cap_used`, `_waiters`, etc.).
- New process → new `ProviderRateLimiter()` → fresh state (zeroed daily cap, full token bucket).
- Daily cap keyed by UTC date (`_day()` uses `clock.now_utc()[:10]`), reset on day rollover.
- Documented as `"in-memory (resets on restart; acceptable per P-AUTO-3)"` — decision is explicit and tested.

**No persistence bug found.**

---

### E2: Test `test_limiter_state_resets_on_restart` — **TEST BUG**

**Location**: `tests/test_p_auto_3_live_fetch.py:386-403`

**Finding**: The test attempts to drain the daily cap (1000) by looping `acquire`/`release`. With `rps=5.0, burst=5`, the token bucket grants 5 immediately, then refills at 5/sec. Draining 1000 grants takes ~200 seconds. The test has no timeout and blocks on `acquire` waiting for tokens (up to `ADMISSION_WAIT_BOUND=60s` per denial).

**Result**: Test hangs indefinitely (observed >120s timeout).

**Fix Required**: Test should use a test-only rate profile with `daily_cap=10` or mock the limiter's internal state directly.

---

## F) Live-Test Authenticity — **PASS**

### F1: Live Tests Actually Dial Out

**Location**: `tests/test_p_auto_3_live_fetch.py:474-478` (`_live_available`), `TestLiveEndToEnd` class

**Finding**: 
- `_live_available()` returns `False` if `HERMES_SKIP_LIVE_FETCH=1` → tests skipped via `pytest.skip`.
- Otherwise, probes `https://api.openalex.org/works?per-page=1` (5s timeout). If reachable, tests run live.
- Tests use `_wiring(mode="live")` → `build_live_fetch_wiring` → real `ProviderHTTPTransport` → real network.

**Verification**: With `HERMES_SKIP_LIVE_FETCH=1`, live tests are skipped (18/23 tests run). Without it, they attempt live egress.

### F2: Only Two APIs Contacted

**Finding**: The allowlist restricts egress to exactly the two D5 providers. The live tests' network probe only checks OpenAlex; if PubMed is down, its test would fail. This is a minor gap — the probe should check both, or each test should probe its own provider.

---

## G) Journal/Provenance Completeness — **PASS**

**Location**: `src/hermes/tools/providers/replay.py` (`RecordedTransport`, `RecordedInteraction`), `src/hermes/persistence/provider_interactions.py` (`make_persisting_sink`)

**Finding**: Every live provider interaction is journaled as a `provider_interaction` row with:
- `interaction_id` — deterministic hash (fixture_id + status + body_hash + failure_class + task_id)
- `provider_id`, `adapter_version`, `parser_version`
- `normalized_request` — **redacted** (params/URL redacted per `DEFAULT_POLICY`)
- `request_hash` — sha256 of normalized request
- `response_status_class` — `HTTP_XXX` or `ERROR_XXX`
- `response_body_hash` — sha256 of response body (or NULL)
- `outcome_kind` — `RECORDED_SUCCESS` / `RECORDED_FAILURE`
- `failure_class` — exception class name (if failed)
- `retrieved_at` — timestamp from clock
- `source_url_redacted` — redacted URL
- `content_type` — response media type
- `task_id`, `project_id` — execution context linkage

**Test Verification**: `test_live_search_then_fetch_per_provider` asserts:
- Search interaction journaled with correct `provider_id`, `outcome_kind`, `task_id`
- Request JSON does not contain "CRISPR" (redaction verified)
- Fetch interaction journaled similarly
- Payload bytes land as `source_payload` artifacts

**No provenance gaps found**.

---

## Additional Findings

### 1. Rate Limiter Test Uses Real Time — **NOTE**

**Location**: `tests/test_p_auto_3_live_fetch.py:386-403`, `src/hermes/tools/providers/ratelimit.py:104` (`ADMISSION_WAIT_BOUND = 60.0`)

The test uses the real `Clock` (via `lambda: CLOCK` which returns fixed time, but `monotonic()` uses `time.monotonic()`). The limiter's `ADMISSION_WAIT_BOUND` is 60s real time. Tests should inject a test clock with controllable monotonic time.

### 2. Live Test Network Probe Only Checks OpenAlex — **NOTE**

**Location**: `tests/test_p_auto_3_live_fetch.py:474-478`

```python
urllib.request.urlopen("https://api.openalex.org/works?per-page=1", timeout=5)
```

If OpenAlex is up but PubMed is down, the PubMed live test runs and fails. Probe should check both, or tests should probe their own provider.

### 3. Fixture Corpus Size — **NOTE**

**Location**: `tests/fixtures/p_auto_3_live/openalex.json` (496 KB), `pubmed.json` (26 KB)

The OpenAlex fixture is large (multiple interactions). Ensure fixture loading performance is acceptable.

---

## Raw Gate Results

### Offline Test Suite (HERMES_SKIP_LIVE_FETCH=1, excluding hanging test)
```bash
$ HERMES_SKIP_LIVE_FETCH=1 python -m pytest tests/test_p_auto_3_live_fetch.py -v -k "not TestLiveEndToEnd and not test_limiter_state_resets_on_restart"
18 passed, 5 deselected in 0.60s
```

### Ruff Lint
```bash
$ ruff check src/hermes/research/live_fetch.py src/hermes/tools/providers/adapters/openalex.py src/hermes/tools/providers/adapters/pubmed.py
All checks passed!
```

### Pyright (src)
```bash
$ pyright src
0 errors, 0 warnings, 0 informations
```

### Pyright (tests)
```bash
$ pyright --project pyrightconfig.tests.json tests/test_p_auto_3_live_fetch.py
1 error: Import "pytest" could not be resolved (expected — test deps not in main env)
```

---

## Verdict Summary

| ID | Finding | Severity | Action |
|----|---------|----------|--------|
| A1 | Redirect bypasses allowlist | MUST-FIX | Add redirect handler that validates/denies redirects |
| A2 | DNS rebinding possible | SHOULD-FIX | Consider IP pinning or private-IP filtering resolver |
| B  | Envelope complete | PASS | — |
| C1 | PubMed parser version not bumped | SHOULD-FIX | Bump `parser_version` to "2" and re-record fixtures |
| C2 | OpenAlex fetch rewrite | LOW RISK | Monitor; no action needed |
| D1 | No overall deadline for multi-call ops | SHOULD-FIX | Add application-level deadline to search/fetch |
| D2 | DNS resolution not timed out | SHOULD-FIX | Use threaded DNS with timeout |
| E1 | Rate limiter restart semantics correct | PASS | — |
| E2 | Test hangs draining daily cap | TEST BUG | Fix test to use small daily_cap or mock |
| F  | Live tests authentic | PASS | — |
| G  | Journal complete | PASS | — |

---

## Repository State

- **Branch**: `audit/p-auto-3-redteam`
- **Base commit**: `e5f06a7` (main)
- **Slice commit**: `0298b4e` (applied to working tree)
- **Changed files** (8, per slice diff):
  - `config/hermes.toml` (+5)
  - `pyproject.toml` (+3)
  - `src/hermes/research/live_fetch.py` (+287)
  - `src/hermes/tools/providers/adapters/openalex.py` (+20)
  - `src/hermes/tools/providers/adapters/pubmed.py` (+55)
  - `tests/fixtures/p_auto_3_live/openalex.json` (+61)
  - `tests/fixtures/p_auto_3_live/pubmed.json` (+63)
  - `tests/test_p_auto_3_live_fetch.py` (+563)

---

## Stop Conditions Checked

- [x] No egress beyond the two D5 APIs (allowlist enforced, except redirect bypass A1)
- [x] No credentials needed (keyless providers)
- [x] No forbidden topics (backtest_audit, SDA, TSE, Optimize-my-strategy — not encountered)

---

**Auditor**: Redteam (automated analysis)
**Status**: Findings delivered. Fixes required for A1, C1, D1, D2, E2.

---

## Director's Note — added 2026-10-02 at fix-branch recording

The P-AUTO-3 finding **A is CONFIRMED**: urllib's default redirect chain followed every 3xx past the one-shot allowlist check, so `fix/p-auto-3-redirect` re-vets each hop (same-origin https-only follow, otherwise refuse-and-record) and pins it with a redirect-to-evil regression. Findings C1 (parser version), D1 (overall deadline) and E2 (hanging limiter test) are carried as the budgeted fix on the same branch; A2/D2 remain recorded with no action in this fix; every other finding stands as written.