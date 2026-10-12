# Step 5 — Fetch Driver Design — Hostile Gate Audit

**Scope:** protest-stage attack on `hermes_researchsourceprovider_fetch_driver_design.md`
(D1–D11) — the step-5a `fetch_batch` design record — before any code exists. Method:
attack the four pinned surfaces (the verdict→outcome mapping, the raw-bytes carrier A1,
the fail-closed bounds, the aggregate corners) for the same bypass and silent-failure
classes that carried steps 1–4, verified against the **shipped** code the design builds
on (the `research_sources.py` fetch types, the `evaluate_hazards` FETCH scope, the four
`hazard_specs/*.json`, the `paginate.py` `_fetch_page` shape, the `base.py` adapter
hooks). No production code exists for `fetch_batch` — this is a design-text review with
shipped-code probes. Findings `FD-01…FD-07`.

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| FD-01 | **P1** | D1/D2/D3 — verdict mapping | `NONE` admits junk bytes as full text for body-marker-less specs — no fetch content-validation hook exists, and the design adds none |
| FD-02 | **P2** | D1/D7 — daily-cap `False` | Mid-batch global-cap exhaustion degenerates the batch into N identical denials with no cap cause at the aggregate |
| FD-03 | **P3** | D4 — bounds | No batch-level duplicate check; crash-retry idempotency unstated |
| FD-04 | **P3** | D2/D11 A6 — `fetch: null` | A legitimately-absent full text (404) at arxiv/openalex is `MALFORMED_200` — a misleading permanent class |
| FD-05 | **P3** | D3/A4 — `raw_bytes_ref` | The self-address is non-dereferenceable; the dereference contract (V6-FINAL-02 discipline) is unstated |
| FD-06 | **P3** | D10 — fixture 1 | The carrier↔descriptor consistency invariant (`sha256(raw_bytes) == content_hash`) is not pinned |
| FD-07 | **P3** | D1 — retry budget | Admission-wait-expired consumes the per-source attempt budget (inherited `_fetch_page` shape) — unstated sharing |

## Detail

### FD-01 (P1) — the `NONE` verdict admits junk as full text; the "delegation" the evaluator promises does not exist

The design's D2 table maps `NONE` → `FetchedSource` (artifact built from the raw
bytes, D3), and its fall-through rule (PS3-02) claims a zero-content "full text" is
"structurally unadmittable." That claim is only as strong as the evaluator's emptiness
checks — which catch **zero-byte / empty-dict / whitespace bodies** (`_is_empty_payload`)
and the **PMC-only** `body_marker` composite. The shipped specs leave three corners with
**no body-content guard at fetch scope**:

- **europepmc** — `body_marker: null`, `body_required: false`, `error_field: errCode`
  (`code_pattern: ".+"`). The ONLY fetch guards are the declared 404 and the
  `errCode`-named field. A 200 with a non-empty, non-`errCode` body (an HTML error
  page, or europepmc's wrapper `<error message="…">` XML — no `errCode` child) falls
  through to `NONE`.
- **arxiv / openalex** — `fetch: null`. Step 6a is **skipped entirely**
  (`if fetch_scope and spec.fetch is not None`); the only guards are step-1 status,
  step-4 emptiness, and step-6 injection. A 200 HTML page where the full-text URL
  landed on an error/CAPTCHA/redirect page → `NONE`.
- The evaluator's own step-6a comment promises "a spec without one (europepmc …)
  delegates body semantics to the adapter's parse" — **there is no fetch-parse hook**.
  The adapter's four hooks are `build_request` / `parse_page` / `extract_ids` /
  `build_fetch_request` (base.py); `parse_page` is search-shaped (returns `Page`).
  The delegation the comment relies on does not exist in the fetch path, and D1's
  pipeline (acquire → `build_fetch_request` → redact → transport → evaluate → map)
  adds none.

**Reproduced against the shipped evaluator** (probe, all against the running code):

| Q | Input | Verdict | Design consequence |
|---|---|---|---|
| Q1 | europepmc 200, junk HTML | `NONE` | → `FetchedSource` of the error page |
| Q2 | europepmc 200, `<error message=…>` wrapper | `NONE` | → `FetchedSource` of the error wrapper |
| Q3 | europepmc 404 (declared) | `NO_FULL_TEXT` | ✓ control — the declared path holds |
| Q4 | arxiv 200, junk HTML | `NONE` | → `FetchedSource` of the error page |
| Q5 | openalex 200, junk HTML | `NONE` | → `FetchedSource` of the error page |
| Q6 | pmc 200, front-no-body | `PARTIAL_CONTENT` | ✓ control — the composite holds |
| Q7 | europepmc 200, zero-byte | `EMPTY_RESULT` | ✓ control — the empty gate holds |

So the **PS2-01/PS3-02 silent-acceptance class — "no full text silently becomes full
text obtained" — is reopened at the body-marker-less corner**, and the artifact is then
content-addressed and handed to the task write path as if it were the fetched paper.
The D10 fixture plan would not catch it: fixture 6 tests empty and recursively-empty
bodies, never a **non-empty junk** 200.

Secondary note (same fix family): the shipped evaluator runs step 6 (injection) **before**
step 6a (fetch scope), so instruction-like text in an error-shaped body yields
`INJECTION_SUSPECT` — which D2 maps to an advisory `FetchedSource` — pre-empting even
the fetch `error_field`. A junk body containing instruction-like text becomes a
flagged artifact instead of a `MALFORMED_200` failure. A fetch content-validation hook
catches the junk regardless of the label.

**Fix direction (fold-in for the design):** add a **fetch-shape content-validation hook**
to the adapter (e.g., `validate_fetch(source: SearchResult, payload: object) -> None`,
raising `ProviderValidationError` on non-full-text shapes), called on `NONE` verdicts
**before** artifact construction — fail closed. europepmc rejects non-JATS /
`<error>`-rooted payloads; arxiv rejects HTML when a PDF was requested; openalex
rejects non-PDF/HTML-for-PDF mismatches. The contract must state that
`body_required: false` + `body_marker: null` (europepmc) is only coherent **with** the
hook, and D10 gains a junk-200 fixture per body-marker-less provider (Q1/Q2/Q4/Q5
probes as golden fixtures). Alternatively/additionally: spec-declared fetch content
rules (`reject_root`, `required_fetch_fields`) — but the hook is the minimal,
provider-shaped answer consistent with the thin-adapter discipline.

### FD-02 (P2) — mid-batch daily-cap exhaustion degenerates the batch into a per-source denial storm

D1's "the daily-cap `False` is a no-retry hard stop (`FetchFailure(THROTTLED,
daily_cap_exhausted)`)" is per-**source**; the design never says what the **batch loop**
does after the cap exhausts. Under a global cap (shipped `ProviderRateLimiter`), the
cap check fires at the top of every `acquire` — so after the cap is exhausted, **every
remaining source** is denied the same way: N identical `FetchFailure(THROTTLED,
daily_cap_exhausted)` entries, aggregate `PARTIAL` (or `FAILED`), with **no signal at
the aggregate that the cap — not the sources — is the cause**. A consumer reading "6 of
10 failed" may schedule a batch retry into an immediate re-denial of the same 6 (each a
cheap no-transport acquire, but the driver still walks all of them, calling
`build_fetch_request` + redaction per source). The design's own D4 discipline ("the
stricter option") argues for a batch-level response: on the first `daily_cap_exhausted`,
either stop the loop and mark the remaining sources failed with the same cause, or
continue-and-collect **with an outcome note** naming the cap. Whichever is chosen, the
design must pin it and the fixture plan must include a mid-batch-cap-exhaustion case
(currently absent from D10).

### FD-03 (P3) — no batch-level duplicate check; crash-retry idempotency unstated

D4 bounds `len(sources)` and emptiness but not **identity**. The walk dedups
first-seen so the task stream is unique, but `fetch_batch` is a public entry point: the
same `result_id` twice, or the same `source_url` under two `result_id`s, doubles the
transport cost and produces two log entries (and two artifacts with the **same**
content hash when the bytes match — a benign but unstated collision). The stricter
option: reject duplicate `result_id`s / `source_url`s at entry
(`ProviderValidationError`), consistent with D6's loud-rejection discipline. Related:
the design never states task-level crash-retry semantics — a re-run re-fetches (cost)
but is content-idempotent (same bytes → same artifact id, atomic re-admission). State it.

### FD-04 (P3) — `fetch: null` providers: a legitimately-absent full text is `MALFORMED_200`, a misleading permanent class

For arxiv/openalex (`fetch: null`), a 404 on the full-text URL (older paper, withdrawn
record) goes through step 1's `unclassified_4xx` branch → `MALFORMED_200` ("HTTP 404
(unclassified non-2xx — permanent validation failure)") → `FetchFailure(MALFORMED_200)`.
Fail-closed direction (never silent), but the class reads as **schema corruption /
provider bug**, not "full text absent" — it pollutes task failure analysis and the
D2 table's claim that `NO_FULL_TEXT` is the only "absent" result. D11 A6 covers the
"generic rules only" tradeoff; the design should at least map fetch-scope non-2xx
permanents to a **distinct reason string** (e.g., `no full text available (HTTP 404)`)
so the mislabel is honest, and note that per-provider `no_full_text_status` declarations
are the later-slice fix (same as A6's "spec authors add blocks per-provider later").

### FD-05 (P3) — `raw_bytes_ref` is a non-dereferenceable self-address

D3 sets `raw_bytes_ref = "art_" + content_hash[:24]` — identical to `artifact_id` — with
the S12 manifest "replacing it later." Nothing in the slice stores bytes at that ref
(read-only by construction), so a consumer following `raw_bytes_ref` gets nothing.
V6-FINAL-02's dereference discipline was exactly this class: state the contract —
**in this phase `raw_bytes_ref` is an identity alias (≡ `artifact_id`), the bytes ride
`FetchedSource.raw_bytes`, and the task write path is the sole dereference point**,
which persists the payload under the content hash atomically with admission.

### FD-06 (P3) — fixture 1 omits the carrier↔descriptor invariant

D10 fixture 1 asserts the artifact's id/hash/media_type/size/ref and that `raw_bytes`
is carried — but not the cross-check `sha256(raw_bytes) == artifact.content_hash` (and
the id prefix). A carrier/descriptor mismatch is exactly the content-addressing
violation the task write path would persist. The fixture must pin it (plain hashlib in
the test, per the ADV-06 independent-recomputation discipline — never the production
helper).

### FD-07 (P3) — admission-wait-expired consumes the per-source attempt budget

D1 says the fetch driver reuses the walk's `_fetch_page` shape, where the admission-wait
expiry does `_backoff; continue` — **burning an attempt** (attempts = `max_retries + 1`
total). Under limiter contention, a source's attempts are consumed by admission waits,
so a later genuine transient (network timeout) may exhaust without its retries. The
design inherits this from the audited walk, so it is not new — but the retry-budget
sharing should be stated (or a separate admission-retry budget pinned) in D1.

## What survives — verified against the shipped code, not assumed

- **The D2 table is exhaustive at FETCH scope.** I enumerated every class the shipped
  evaluator can emit at FETCH: `THROTTLED` (429 / throttle sig), `TRANSIENT` (5xx),
  `MALFORMED_200` (unclassified 4xx, fetch `error_field`, fetch required-fields drift,
  label check), `NO_FULL_TEXT` (deferred status / retraction / marker),
  `EMPTY_RESULT` (empty payload, body-marker-empty), `PARTIAL_CONTENT` (composite),
  `INJECTION_SUSPECT`, `NONE`. `VALID_NEGATIVE` is structurally unreachable at FETCH
  (step 1 gates `not fetch_scope`; step 4's empty rule is `treat-as-failure` at fetch);
  `REWRITE_SUSPECT`/`CURSOR_TRAP` are search-only. The loud scope-error raise for them
  is correct and matches the walk's "never silent" discipline.
- **The 404 → `NO_FULL_TEXT` precedence (PS3-01) holds** (Q3) — a declared
  `no_full_text_status` never resolves as a failure, and the retraction marker refines
  the kind without changing the outcome (PS3-03).
- **The A1 raw-bytes carrier is necessary and minimal — ACCEPT** (with FD-05/FD-06
  pins): without it the fetched payload is hashed and discarded — the data-loss class
  the design identifies; the amendment is additive (one frozen `bytes` field), the
  persisted descriptor is unchanged.
- **D4's empty/over-bound raises and D6's `valid_negative` rejection are consistent**
  with the shipped contract and the walk's loud-failure discipline; serial-order
  determinism (D1, PS2-06) is by construction and the `fetch_log` input-order
  preservation holds.

## Interaction with prior findings

| Prior finding | Status after this gate |
|---|---|
| PS2-01/PS3-02 (no full text ≠ failure; no silent zero-content artifact) | **Partially reopened** by FD-01 — the zero-content guard holds, but the *junk-but-non-empty* corner silently becomes full text for body-marker-less specs |
| FS-01 (recursive emptiness) | Holds for the empty class; the non-empty junk class is outside its scope (FD-01) |
| RT2-05/RL-01 (daily-cap `False`, atomic reason) | Mechanism holds; the batch-level consequence is unspecified (FD-02) |
| V6-FINAL-02 (dereference contract) | `raw_bytes_ref` needs the same discipline stated (FD-05) |
| ADV-06 (independent recomputation) | Fixture 1 needs the cross-check (FD-06) |
| WK3-01 (per-request release) | Inherited correctly by D1 |

## Overall verdict

**MERGE WITH REMEDIATION.** FD-01 is gate-blocking for the step-5 design: the claim
that a zero-content/junk "full text" is structurally unadmittable is false at the
body-marker-less corner (three of the four canonical providers ship no fetch body
guard), and the evaluator's promised "adapter parse" delegation does not exist. The fix
is a design fold-in — a fetch content-validation hook (or spec-declared fetch content
rules) + the junk-200 fixtures + the FD-02 batch-cap pin — before any `fetch_batch` code.
Everything else is P3 pins (duplicates, the 404 mislabel, the dereference contract, the
fixture invariant, the retry-budget sharing). The core spine — exhaustive mapping, the
404 precedence, serial determinism, the A1 carrier, fail-closed bounds — is sound.

---

**Probe evidence:** `probe_fetch_design.py` (Q1–Q7 above) — all against the running
shipped evaluator and the four shipped `hazard_specs/*.json`; removed after the audit
per house convention. Suite unchanged: **802 passed, `uvx pyright src` 0 errors**
(no production code touched — design-text review only).

---

## Disposition — FOLDED IN (2026-08-14)

| ID | Decision | Where it landed |
|---|---|---|
| **FD-01** | **Add** a FIFTH adapter hook `validate_fetch(source, payload) -> None` (raises `FetchContentRejected(reason)`), called on the artifact verdicts (`NONE`/`INJECTION_SUSPECT`) BEFORE artifact construction; rejection → `FetchFailure(EMPTY_RESULT, reason=…)`. europepmc `body_required: false` is only coherent WITH the hook; `fetch: null` (arxiv/openalex) means no declared hazard knowledge but the hook still runs. The injection-before-6a ordering can no longer artifact junk (the hook rejects regardless of the advisory label). | design D1/D2/D3/D10, blueprint §2.1 (fifth hook) + §5.3 (pipeline + junk fixtures), contract §5.1 (coherence rule) + §5.3 (EuropePMC/arXiv/OpenAlex entries) |
| **FD-02** | **Stop the batch** on the FIRST `daily_cap_exhausted`: remaining sources marked `FetchFailure(THROTTLED, daily_cap_exhausted)` (never fetched, never dropped) + a `"daily cap exhausted at source <i> of <n>"` outcome note — the aggregate's cause is the CAP, never N independent failures. | design D1 (batch-level hard stop) + D7 (aggregate note), blueprint §5.3 (batch discipline), fixture 13b |
| **FD-03** | **Reject duplicates** (`result_id` / shared `source_url`) at entry (`ProviderValidationError`, before I/O); state crash-retry idempotency (re-fetch is content-idempotent — same bytes → same artifact id → atomic re-admission). | design D4 (bounds) + D1 (batch entry), blueprint §5.3, fixture 10b |
| **FD-04** | Keep the permanent class but **rewrite the reason** for fetch-scope non-2xx permanents to `HTTP <status> — no accessible full text for this source (provider declares no fetch hazard knowledge)`; per-provider `no_full_text_status` declarations remain the later-slice extension (A6). | design D2 (non-2xx note), D11 A6 |
| **FD-05** | State the **dereference contract**: in-phase `raw_bytes_ref` ≡ `artifact_id` (identity alias), bytes ride `FetchedSource.raw_bytes`, the task write path is the SOLE dereference point; the S12 manifest replaces the alias later. | design D3 (dereference paragraph) |
| **FD-06** | Fixture 1 pins the **carrier↔descriptor invariant**: test-local `hashlib.sha256(raw).hexdigest() == artifact.content_hash` + the id prefix (independent recomputation, ADV-06). | design D10 fixture 1 |
| **FD-07** | **Document the retry-budget sharing**: admission-wait-expired consumes the same per-source attempt budget (attempts = `max_retries + 1`, inherited `_fetch_page` semantics). | design D1 (transient-retry bullet) |

All seven dispositions verified against the running code before landing (probes Q1–Q7;
the four surviving surfaces — exhaustive D2 mapping, 404→`NO_FULL_TEXT` precedence, A1
carrier, D4/D6 bounds — unchanged). The step-5 design record is now ready for the
implementation gate: `fetch_batch` per the remediated design, with the junk-200 /
mid-batch-cap / duplicate fixtures green (`tests/test_provider_fetch.py`).
