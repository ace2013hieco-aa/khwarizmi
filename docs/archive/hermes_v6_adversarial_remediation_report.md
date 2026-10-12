# ADVERSARIAL REMEDIATION REPORT

**Scope:** independent hostile verification + remediation of ADV-01 … ADV-08 against
the Hermes v6 repository at HEAD `11dea29` (branch `main`, clean baseline: 770 passed,
`uvx pyright src` 0 errors).

**Method:** every finding was independently reproduced against the actual code before
any change; fixes were applied only to confirmed defects; adversarial regression tests
were added for every fix; the audit's cross-cutting rules (no new authority, no silent
fallback, fail-closed preserved, no speculative redesign) were enforced throughout.

**Result:** 4 defects confirmed and fixed (ADV-01, ADV-02, ADV-03, ADV-05), 1 partially
confirmed (ADV-08 — one latent misclassification fixed + boundary tests pinned), 1 test-
integrity finding fixed (ADV-06), 1 governance gap fixed (ADV-07), 1 finding verified as
already remediated at HEAD (ADV-04). **Full suite: 798 passed** (770 baseline + 28 new
adversarial/strengthened tests). **`uvx pyright src`: 0 errors.**

---

## ADV-01 — Content-hash self-reference

**Verdict: VERIFIED.** `content_hash_of_search_result` hashed
`canonical_json(dataclasses.asdict(result))` — the preimage **included the `content_hash`
field itself**. The walk producer (`paginate.py._patch_delivered`) constructs records with
`content_hash=""`, computes the hash over that form, and stores it — so the persisted hash
is `H(record WITH content_hash="")`, which is **not** independently recomputable from the
persisted record as-is (you must know to zero the field first). Exactly the
`H(record INCLUDING H(record))` class the audit named.

- **Files inspected:** `src/hermes/tools/research_sources.py:121-128`,
  `src/hermes/tools/providers/paginate.py` (producers `_make_result`/`_valid_negative_result`
  → `_patch_delivered:756-775`), `tests/test_research_sources.py` (weak determinism test),
  contract §2.2.
- **Files changed:** `src/hermes/tools/research_sources.py` (preimage now excludes
  `content_hash`), `tests/test_research_sources.py` (semantic suite).
- **Remediation:** `data = dataclasses.asdict(result); data.pop("content_hash", None)` before
  `canonical_json` — the contract is now `H(canonical(record WITHOUT content_hash))`, using
  the existing deterministic canonicalization (no ad-hoc serialization).
- **Adversarial tests added (9):** determinism; independent recomputation vs an explicitly
  constructed preimage (test-local canonicalizer + plain hashlib — never the production
  helper verifying itself); serialize→deserialize→recompute; content-mutation sensitivity;
  **mutating `content_hash` alone does NOT change the identity hash** (the ADV-01 probe);
  field-ordering invariance; Unicode determinism (`ensure_ascii=False`); semantically
  identical records hash equal; persisted hash equals independent recomputation.
- **Tests passed:** full suite green; end-to-end probe confirmed a walk-produced record's
  stored hash equals the independent recomputation from its persisted form.
- **Remaining risk:** none identified — the producer path (`_patch_delivered`) was the only
  hashing site and it flows through the fixed helper.
- **CLOSED.**

## ADV-02 — Controller lease expiry / stale live controller

**Verdict: VERIFIED.** The controller holds `scheduler_lock` for a whole tick; `locked_at`
is written once at acquisition and never renewed; the code comment itself records
"[PA7] generation fencing is DEFERRED". A live controller A whose tick outlasts the 60s
lease can keep writing after B legitimately reclaims the stale lock — two live writers.
Worse, B's recovery pass can re-claim A's RUNNING task while A is still executing it.

- **Files inspected:** `src/hermes/research/controller.py` (lock acquire/release/tick, all
  write call sites), `src/hermes/persistence/migrations.py` (scheduler_lock schema, v7),
  `src/hermes/persistence/repositories.py` (`transition_status` transaction shape),
  `src/hermes/research/extraction.py` (`accept_extraction_output`), `tests/test_controller.py`.
- **Files changed:** `src/hermes/persistence/migrations.py` (migration 7→8:
  `ALTER TABLE scheduler_lock ADD COLUMN generation INTEGER NOT NULL DEFAULT 0`),
  `src/hermes/research/controller.py` (`LockLostError`, `_FencedConnection`, generation
  capture/bump in `_acquire_lock`, fenced repos + write call sites, `tick()` lock_lost
  handling), `tests/test_controller.py`.
- **Remediation (minimal, architecture-preserving):** a fencing token on the existing lock
  row — `generation` incremented on every ownership change (reclaim). The controller
  captures its generation at acquisition; every authoritative write re-validates
  `owner + generation` **inside the write transaction** (the fenced connection checks
  before the first write statement; SQLite serializes writers, so no check/write
  interleave). A stale controller's write raises `LockLostError` and rolls back; the tick
  returns `idle="lock_lost"`. Same-owner refresh keeps the generation (a refreshed lease is
  valid). No new table, no new authority, no new scheduler — the single-writer discipline
  is now structural instead of conventional. Lease renewal alone was deliberately NOT used
  as the fix (the audit's rule: renewal is insufficient without fencing).
- **Adversarial tests added (5):** the core mid-tick attack (A's injected model call runs
  past the lease, B reclaims, A's acceptance write fails closed — 0 claims, B's recovery
  ladder then completes the task, 1 claim, generation bumped); direct fence probe (A's repo
  write raises `LockLostError`, rolls back, B writes fine); same-owner refresh stays valid
  (generation NOT bumped); crash-reclaim bumps generation; concurrent fresh-lease
  acquisition serialized. All deterministic clocks, no sleeps.
- **Tests passed:** all 5 new + the pre-existing controller suite (the one pre-existing
  test calling `_execute_extract` directly now acquires the lock first — the real flow).
- **Remaining risk:** a controller whose writes all committed *before* B's reclaim is
  unaffected — those writes were legitimate (B only reclaims a *stale* lease; staleness is
  the controller's own contract). The PA7 full generation-fencing slice remains deferred;
  this closes the concrete stale-live-controller double-write at the controller boundary.
- **CLOSED.**

## ADV-03 — Secret scanner list/container bypass

**Verdict: VERIFIED.** `validate_no_secrets._check_dict` recursed into `dict` values only —
a list/tuple payload (e.g. `{"evidence": [{"api_key": "..."}]}`, or a bare secret string
inside a list) bypassed the scanner entirely; even the *value-pattern* check never ran on
list members.

- **Files inspected:** `src/hermes/persistence/event_validation.py:99-136`,
  `tests/test_event_validation.py`.
- **Files changed:** `src/hermes/persistence/event_validation.py` (recursive walker),
  `tests/test_event_validation.py`.
- **Remediation:** a deterministic recursive walker over every permitted container —
  `dict`, `list`, `tuple` — with `[i]` paths; field-name patterns apply to dict keys at
  every depth, value patterns to every string at every depth (including bare strings in
  lists). Defense-in-depth is unchanged: typed schemas remain the primary defense, the
  scanner stays pattern-based (documented JWT/plain-password limitations preserved).
- **Adversarial tests added (7):** secret in a list; secret in list→dict (the ADV-03
  probe); secret in list→list→dict; secret in a tuple; secret value in a nested list of
  strings; plus 2 non-over-block guards (legitimate research content in lists accepted).
- **Tests passed:** all 7 new + the pre-existing known-limitation tests still pass.
- **Remaining risk:** none beyond the documented pattern-based limits (unchanged).
- **CLOSED.**

## ADV-04 — Rate limiter contract / driver mismatch

**Verdict: FALSE POSITIVE at current HEAD (already remediated).** The mismatch the audit
describes — a protocol declaring `acquire -> None` with a driver that doesn't branch —
existed in the *pre-step-4 design text* (RT3-05 flagged `base.py` still declared
`acquire -> None`), but the shipped step-4 implementation resolved it and the RT/RT2/RT3/TR/
RL fold-ins are committed (`11dea29`): the Protocol declares
`acquire(provider) -> tuple[bool, str]` (a strongly typed admission result: decision +
atomic cause), and `paginate.py._fetch_page` branches **before the try** —
`granted, reason = limiter.acquire(...); if not granted: return ... "THROTTLED" ...` — so a
denied request **structurally cannot reach `transport.request`**; retries re-acquire per
attempt (WK-05); Retry-After flows through `note_throttled` (RT-08); the unknown-provider
`ValueError` keeps the fail-closed guarantee.

- **Files inspected:** `src/hermes/tools/providers/base.py:204-229` (Protocol),
  `src/hermes/tools/providers/paginate.py:546-566` (the return-check before the try),
  `src/hermes/tools/providers/ratelimit.py`, the RT/RT2/RT3 design records + contract §6.
- **Files changed:** none (per the audit rule: do not change production code for a false
  finding; document + evidence).
- **Evidence (existing adversarial coverage):** `test_walk_daily_cap_denial_is_no_retry`
  (denied page never requested, `transport.calls == 1` for the *accepted* page only),
  `test_walk_admission_expiry_retries_then_throttled` (`transport.calls == 0` — every
  denied attempt never reached the transport), `test_walk_throttled_429_passes_limiter_and_
  retries`, `test_http_429_returned_not_raised`, the Retry-After cooldown fixtures, and the
  fail-closed construction validation. Invariant "IF admission denies → transport MUST NOT
  execute" is structurally enforced and test-pinned.
- **CLOSED (verified, no change).**

## ADV-05 — Duplicate event catalogs

**Verdict: VERIFIED.** Two authorities existed — the `EventType` enum and a hand-maintained
`KNOWN_EVENT_TYPES` literal — and they had silently diverged: 5 names in the validator set
were missing from the enum (`BudgetExceeded`, `EvidenceTransitionProposed`, `IterationAdvanced`,
`SourceRetracted`, `ThesisInvestigationCompleted`), and `IterationAdvanced` is **emitted by
the system** (`controller.py._park_human_gate` → `_append_event_to_db("IterationAdvanced"…)`).

- **Files inspected:** `src/hermes/core/events.py` (enum), `src/hermes/persistence/
  event_validation.py` (literal), all `_append_event*` call sites (AST-extracted — all
  emitted names are inside the union catalog), `tests/test_extraction_pipeline.py`
  (`test_5b` codified the drift as "known drift").
- **Files changed:** `src/hermes/core/events.py` (the 5 names become enum members),
  `src/hermes/persistence/event_validation.py` (`KNOWN_EVENT_TYPES = frozenset(e.value for e
  in EventType)` — one canonical catalog), `tests/test_extraction_pipeline.py`
  (`test_5b` now asserts the drift is closed: delta == empty in both directions),
  `tests/test_event_validation.py` (invariant tests).
- **Remediation:** `EventType` is authoritative; validation derives its accepted set from it
  — divergence is now structurally impossible. Compatibility preserved: the enum-derived
  set is exactly the previous union (49 + 5), so every persisted/emitted name still
  validates.
- **Adversarial tests added (2):** `KNOWN_EVENT_TYPES == frozenset(EventType)`; every enum
  member passes `validate_event_type`.
- **Tests passed:** all green, including the updated `test_5b`.
- **Remaining risk:** none — a future event must be added to the enum or validation will
  reject it loudly (fail-closed, never a silent drift).
- **CLOSED.**

## ADV-06 — Hash tests verify implementation, not semantic contract

**Verdict: VERIFIED (partially — test-integrity finding).** `test_content_hash_is_
deterministic_and_recomputable` proved only `hash(x) == hash(x)` (determinism), never that
the stored identity equals an independently constructed preimage. The ResearchProgram
identity tests compare compile-to-compile outputs (determinism of the compiler) but never
rebuild the preimage outside the production helpers.

- **Files inspected:** `tests/test_research_sources.py:166-172`,
  `tests/test_research_program.py::TestDeterminism`, `programs.py` (`canonical_content_dict`,
  `content_hash_of`, `input_hash_of`).
- **Files changed:** `tests/test_research_sources.py`, `tests/test_research_program.py`.
- **Remediation:** the weak determinism test was replaced by the ADV-01 semantic suite
  (above), and `TestDeterminism` gained three tests that construct the expected preimage
  EXPLICITLY with a test-local canonicalizer + plain `hashlib` — content-hash independent
  recomputation over `program_to_dict` minus the identity outputs; input-hash independent
  recomputation over the documented sorted-refs preimage; `program_id == "rp_" +
  content_hash[:24]`. Tests never call the production helper to verify itself.
- **Adversarial tests added (3 in test_research_program.py; 9 in test_research_sources.py
  counted under ADV-01).**
- **Tests passed:** all green.
- **Remaining risk:** the tests replicate the documented canonicalization contract
  (sort_keys/separators/list-ordering rules); a deliberate *contract* change would need both
  the implementation and the test contract updated together — which is the point (identity
  changes are loud, never silent).
- **CLOSED.**

## ADV-07 — CI / merge-gate hardening

**Verdict: VERIFIED.** The CI workflow ran on `push: branches: [main]` only — no
`pull_request` trigger — while the v6 engineering plane (v6 §20 / §29: worktree → PR →
human merge → CI+test pass) requires the quality gates *before* merge. Branch-protection
settings are not accessible from the repo checkout; the workflow trigger is the code-side
gate.

- **Files inspected:** `.github/workflows/ci.yml`.
- **Files changed:** `.github/workflows/ci.yml` — added `pull_request:` to the `on:` block
  (both jobs — full suite with coverage artifact + pyright — now run on every PR).
- **Remediation:** minimal and governance-consistent; no new tools, no coverage threshold
  imposed (the existing report artifact is kept), no branch-protection changes (not
  authorized to touch GitHub settings).
- **Adversarial tests added:** n/a (CI config) — the gate is exercised on the next PR.
- **CLOSED** (workflow change; branch-protection enforcement remains a repository-setting
  item for the owner).

## ADV-08 — Fail-closed / exception boundaries

**Verdict: PARTIALLY VERIFIED.** The driver's boundary classification is largely correct
(transport hazards → `_fetch_page` verdicts; non-`ProviderError` escapes → loud re-raise
RT2-06; malformed pages → MALFORMED_200; adapter/recorder failures already propagate
loudly). One latent misclassification was confirmed: `_fetch_page`'s
`except ProviderError` (the base class) would swallow a non-permanent `ProviderError`
escaping the transport (`RedactionError`/`ProviderValidationError`/`ProviderUnavailableError`)
and convert it into a `MALFORMED_200` search verdict — a programming/config failure turned
into a misleading search result. No transport currently raises those classes (latent), but
the boundary was wrong.

- **Files inspected:** `src/hermes/tools/providers/paginate.py` (`_fetch_page:556-576`,
  `walk`), `src/hermes/tools/providers/http.py` (raise sites), `src/hermes/tools/
  research_sources.py` (taxonomy), `src/hermes/tools/providers/redact.py` (no runtime
  raises), `tests/test_provider_walk.py`.
- **Files changed:** `src/hermes/tools/providers/paginate.py` — the permanent-verdict catch
  narrowed to `PermanentProviderError`; any other `ProviderError` subclass re-raises loudly
  (same discipline as the RT2-06 non-ProviderError catch); module docstring notes the
  "never raises" scope (hazard verdicts only; contract/programming failures are loud).
  `tests/test_provider_walk.py` — 4 boundary tests.
- **Adversarial tests added (4):** adapter contract violation (parse_page raises) → loud,
  never a verdict; recorder (audit-trail) failure → loud; `RedactionError` from the
  transport → loud re-raise, never `MALFORMED_200` (the ADV-08 probe); positive control —
  a real `PermanentProviderError(PARTIAL_CONTENT)` still resolves to a deterministic
  `SHORTFALL(cause=PARTIAL_CONTENT)` verdict. The pre-existing coverage already pins
  transient/throttle/permanent/malformed/exhaustion/cursor-trap/zero-result/valid-negative
  paths.
- **Tests passed:** all 4 new + full suite.
- **Remaining risk:** none confirmed — the classification is now explicit on both sides of
  the boundary.
- **CLOSED.**

---

## Test Results

- **Full suite:** 798 passed (770 baseline + 28 new/strengthened), 0 failed, ~9 s.
- **Targeted suites (post-change subsystems):** `test_controller.py` 17 passed (incl. 5
  ADV-02), `test_event_validation.py` (incl. 7 ADV-03 + 2 ADV-05), `test_research_sources.py`
  (incl. 9 ADV-01/06), `test_research_program.py` (incl. 3 ADV-06), `test_provider_walk.py`
  (incl. 4 ADV-08) — all green.
- **Adversarial suite:** the 28 new regression tests, run independently — green.
- **pyright:** `uvx pyright src` — **0 errors, 0 warnings**.
- **Lint/format:** n/a (project has no configured linter/formatter beyond pyright; CI
  mirrors the local commands).
- **Coverage:** not re-measured in this pass (baseline IDR-031: 88% at 732 passed; the new
  tests only raise it).

## Architecture Impact

Explicit statement — **none of the following changed semantics; all boundaries preserved:**
- **Authority boundaries:** unchanged — the controller remains the only `scheduler_lock`
  consumer; the fencing token lives on the existing lock row (no new authority, no new
  database, no second scheduler).
- **Persistence boundaries:** unchanged — the fenced connection wraps the *existing*
  connection and repos; the write path, `validate_*` gates, and the event journal are
  untouched (the fence is a controller-side attribution check, inside the same
  transactions).
- **Event model:** unchanged — no new event types; the *catalog* now has one canonical
  source (`EventType`), and `KNOWN_EVENT_TYPES` is derived from it.
- **Lifecycle model:** unchanged — all task transitions still flow through the atomic
  `transition_status`; the v4 §19 NO_SIGNAL ladder is preserved (the ADV-02 recovery test
  exercises it end-to-end).
- **Scheduler/controller authority:** unchanged — single-writer discipline strengthened
  (fencing), not replaced.
- **Provider architecture:** unchanged — the step-4 provider stack is NOT implemented
  beyond what step 4 already shipped; ADV-04 was verified as already consistent; ADV-08
  only narrowed one exception catch in the existing driver.
- **Evidence model:** unchanged — `SearchResult`/`Source` remain retrieval records, never
  evidence; the content-hash fix strengthens integrity without touching the evidence
  ladder.
- **Schema:** version 7 → 8 (forward-only, additive: one `generation` column with a
  default); all existing data/rows compatible.
- **Migrations:** `_migrate_7_to_8` added to the registry; upgrade-path tests updated;
  replay/future-version tests green.
- **Public APIs:** `content_hash_of_search_result` preimage contract corrected (the
  function's *meaning* is now the documented one); `Controller` internals gained
  `LockLostError` + the fenced connection (no public signature changes; `tick()` may now
  return `idle="lock_lost"` — an additive outcome).

## Deferred Work (intentionally NOT implemented)

- The full PA7 generation-fencing slice (per v6 §22's deferral list). ADV-02's fix is the
  minimal controller-scoped fencing that closes the confirmed stale-live-controller
  double-write; the wider PA7 machinery remains a later-phase item.
- Step 5–7 of the ResearchSourceProvider slice (fetch driver, orchestration, ratification)
  — untouched, per the audit's explicit instruction and the §27 item 55 staging.
- A repository-side "compilation receipt" for AR-01-class write-path validity — out of
  scope for this pass (already addressed by the AR-01 write-path hardening in earlier
  work); no new finding here required it.
- Branch-protection settings (repository-admin item, not accessible from the checkout).

## Remaining Risks

- **ADV-02 residual:** a controller's writes committed *before* B's reclaim are unaffected
  by design (they were legitimate); full PA7 fencing is deferred. If the controller is
  deployed with lease renewal later, the fence must be preserved (renewal ≠ fencing).
- **ADV-01 residual:** none in the producer path; the contract change alters the hash value
  of any persisted retrieval records — none are persisted yet (step 5+ deferred), so no
  back-compat concern.
- **ADV-05 residual:** none — divergence is now fail-closed (unknown type → validation
  error), which is the desired direction.
- **ADV-07:** the workflow change gates PRs, but branch-protection *enforcement* (required
  status checks) is a GitHub repository setting the owner must enable; the check itself
  will run on the next PR.
- **Needs separate adversarial review:** the fencing wrapper's statement-verb interception
  (`INSERT/UPDATE/DELETE/REPLACE` first-token) — a future write path that prepends a `WITH`
  CTE would bypass the fence; no such statement exists today (verified across the
  controller's write paths), but it is a documented assumption.
- **Still external/unverified:** v6 §27 item 43 closure-gate status (EXTERNALLY VERIFIED /
  RATIFIED) is unaffected by this pass; this remediation is a normal engineering-plane
  change.

## Commit Discipline

Changes are **uncommitted** (per house convention). Suggested logical commit grouping per
the audit: (1) hash integrity — ADV-01/06; (2) controller fencing — ADV-02 + migration 8;
(3) event validation — ADV-03; (4) event catalog — ADV-05; (5) provider boundary — ADV-08;
(6) test hardening — the updated version-assertion tests; (7) CI — ADV-07. The working set
is exactly the 16 files listed in the diff (no unrelated changes).
