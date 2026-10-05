# Step 6 — Task-Side Orchestration — Hostile Design Audit
**Gate:** `hermes_researchsourceprovider_step6_orchestration_design.md` (D1–D11)
**Verdict:** MERGE WITH REMEDIATION — two P1s (SD-01, SD-02) are design-record
gaps, not architectural violations; the execution surface and the recovery
re-execution are NOT implementable as described against the shipped
controller. OQ-1…OQ-6 ruled with evidence.

**Method:** every claim below was checked against the shipped code (the IDR-029
controller, `repositories.py`, `gateway.py`, the artifact store) — not assumed.
No code was written; the probe evidence is cited per finding.

**Status: FOLDED IN (2026-08-14).** All five dispositions landed in the design
record (`hermes_researchsourceprovider_step6_orchestration_design.md`) — SD-01
(dispatch-threaded `handler(task, fenced, repos)` contract, §3), SD-02
(template-generic re-execution + the source one-shot carrier, §5/§10), SD-03
(two-transaction write, §5), SD-04 (get-by-hash-first idempotent branch,
§5/§7), SD-05 (the dereference-resolver extension, §5); OQ-1…OQ-6 rulings in
§13; the fold-in fixtures 11–15 in §12. The design record's status line and the
blueprint step-6 line / README carry the disposition.

---

## Verdict summary

| ID | Severity | Target | Finding |
|---|---|---|---|
| SD-01 | **P1** | D1 execution surface | The handler cannot be wired "over the fenced connection" at Controller construction — the fence is rebuilt **per lock acquisition**; the design's "no controller code changes" is false |
| SD-02 | **P1** | D8 recovery | The recovery ladder's re-execution is **EXTRACT-hardwired** (`_re_execute_requeued` → `_execute_extract`); a source task requeued by the ladder would be re-executed as an EXTRACT task |
| SD-03 | **P2** | D3 write path | The write method cannot transition SUCCEEDED itself — the controller owns it after `handler(task)`; D3's "atomic with SUCCEEDED" double-transitions and contradicts D8's own crash-mid-acceptance chain |
| SD-04 | **P2** | D5 idempotency | "The `content_hash` UNIQUE row absorbs it" is false as shipped — `ArtifactRepository.record` is a plain INSERT; a duplicate raises IntegrityError; no get-by-hash-first flow is pinned |
| SD-05 | **P2** | D3 dereference | The dereference resolver form-checks unknown artifact types — `source_result:` refs would pass without resolving; the V6-FINAL-02 "resolves or fails" contract is unenforced until the resolver is extended |

## OQ rulings (evidence-backed)

| OQ | Ruling |
|---|---|
| OQ-1 carrier | **Per-result rows** (the recommendation is correct), conditioned on SD-05's resolver extension AND a **lossless round-trip**: the persisted row must reconstruct the `SearchResult` exactly (the fetch task resolves its input from the persisted outcome; a lossy carrier breaks the re-hash check) |
| OQ-2 templates | **Two templates** — the shipped `_discover_eligible` gates on deps-SUCCEEDED, so the SEARCH→FETCH dependency edge works with zero discovery changes; a single template needs an internal phase machine (a second scheduler shape) — rejected |
| OQ-3 cap interplay | A cap-stopped fetch task must **NOT burn the retry budget**: FAILED with the cap cause, no auto-requeue (RETRYING re-execution would re-fetch against an exhausted UTC window within the tick — the AR-02 class); re-arm is the planner's/human's after the window |
| OQ-4 log carrier | The redacted log facts ride the **outcome-level artifact's metadata** (single copy, F1 memory discipline); per-source provenance edges reference the outcome record; `request_log_ref` resolves to it |
| OQ-5 admission | **Yes, admission-time validation** — the exact V6-P7-E01/E02 precedent (`_is_extract_spec` + `_validate_extract_source`): canonical normalized marker + pinned profile + scope + cost_class + provider-allowlist membership + positive bounds at `INSERT_TASK` |
| OQ-6 sizing | The deterministic builders carry explicit bounds (S11 scale classes); the fetch envelope's real control is the task's `FetchRequest` sizing (GC-03); over-bound requests rejected at admission, never at execution |

---

## Detail

### SD-01 (P1) — the handler cannot capture the fence at construction

The design D1: *"a closure over the injected provider machinery and the
repositories (… over the fenced connection)"* wired at `Controller(...)`
construction, and *"No controller code changes are required."*

**Against the shipped code:** `Controller._fenced` is `None` in `__init__`
(`:232`) and is built by `_refresh_fence()` (`:309`) — which is called on
**every successful `_acquire_lock`** (`:330–370`), i.e. **per tick**. The fenced
connection exists only between `_acquire_lock` and `_release_lock`. A handler
closure constructed with the controller captures `None` (construction) or a
fence from a *previous* tick whose generation the current lock may not match —
both fail closed or crash, and neither is the design's intent.

The shipped EXTRACT pattern is the answer: `_execute_extract` is a **controller
method** and reads `self._fenced`/`self._project_repo`/`self._task_repo` at
dispatch time. The design must pin one of: (a) handlers become controller
methods (`_execute_source_search`/`_execute_source_fetch`), (b) the dispatch
threads `(task, fenced, repos)` into the handler (a handler-contract change), or
(c) the wiring passes a per-tick repos-provider callable. Under (a) the
"no controller code changes" claim becomes false; under (b) it is false by
definition. As written, the core execution surface is unimplementable.

### SD-02 (P1) — the recovery re-execution is EXTRACT-hardwired

The design D8: *"crash-mid-acceptance → the ratified ladder — lease expiry →
NO_SIGNAL → FAILED → RETRYING → RUNNING — the discovery path is the existing
`_recovery_pass`."*

**Against the shipped code:** the ladder's *re-execution* is
`_requeue_recovered` → `_re_execute_requeued` (`:428–477`), which calls
`_execute_extract(task_id)` — **hard-coded to the EXTRACT execution** (the
`extract_fn` model call + `accept_extraction_output`). A SOURCE_SEARCH/
SOURCE_FETCH task that crashes mid-acceptance (RUNNING with rows), gets NO_SIGNAL
→ FAILED via the ladder, and is requeued would be re-executed **as an EXTRACT
task** — the wrong handler, the wrong write path, and (with no `extract_fn`
wired) a FAILED with "no extract_fn wired — EXTRACT task cannot execute". The
design's "the existing `_recovery_pass`" + "no controller code changes" (D1)
contradict each other: the requeue/re-execute pass must become template-generic
(re-dispatch through the handler registry) or the source tasks' recovery chain
must be specified differently. **Gate-blocking for the recovery-correctness
claim.**

Related, unpinned: the one-shot "has prior output" probe in `_execute_extract`
hard-codes `SELECT 1 FROM research_claims WHERE producing_task_id = ?`
(`:669`). The source write method needs its own has-prior carrier (the source
outcome rows / artifacts by task), which the design doesn't name.

### SD-03 (P2) — the write method cannot transition SUCCEEDED

The design D3: *"the outcome rows, the §14 provenance edges, and the task's
SUCCEEDED transition commit in ONE transaction."* The controller's
`_dispatch_pass` handler branch (`:563–571`) does `handler(task)` **then**
`transition_status(task_id, SUCCEEDED)` itself.

`transition_status` validates the from-status (`validate_task_transition`,
`:504`) — SUCCEEDED is terminal, so the controller's second transition
(SUCCEEDED→SUCCEEDED) fails, and the branch's `except Exception` then attempts
FAILED-from-SUCCEEDED — also invalid → the exception propagates. Either the tick
crashes or the task wedges. The EXTRACT precedent is **two transactions**
(`accept_extraction_output` writes rows atomically; the controller transitions
SUCCEEDED separately). The design must drop the SUCCEEDED transition from the
write method — and then **D8's own crash-mid-acceptance chain is precisely the
RUNNING-with-rows case the ladder handles**, which D3's "atomic with SUCCEEDED"
makes impossible. D3 and D8 contradict each other as written.

### SD-04 (P2) — the idempotency engine is not an upsert

The design D5: *"the `content_hash` UNIQUE row absorbs it — atomic
re-admission."* `ArtifactRepository.record` (`:741–758`) is a plain INSERT with
**no ON CONFLICT** and no get-by-hash-first branch; `artifacts.content_hash` is
`NOT NULL UNIQUE`. A duplicate insert **raises IntegrityError** — the opposite
of absorption. The FD-03 idempotency claim needs a pinned flow: get-by-hash →
verify the bytes match → reuse the existing row, with the binding checks, inside
the write transaction. The design names the constraint but not the mechanism.

### SD-05 (P2) — the dereference resolver doesn't know the new artifact type

The design D3: *"every request_log_ref / source_ref / artifact id written must
resolve to a row written in the same transaction."* The shipped
`_dereference_artifact_ref` (`repositories.py:1331`) dereferences
`dataset_manifest:<id>` concretely and **form-checks every other artifact type**
("deferred artifact-type carriers: form-checked only"). A `source_result:art_x`
that doesn't exist passes the resolver. The OQ-1 per-result citeability +
the V6-FINAL-02 contract require extending the resolver to check the `artifacts`
table for the source type — the resolver's own docstring calls itself "the
single extension point as those stores land", so landing the source store means
landing the resolver extension. The design doesn't mention it.

---

## What survives — verified against the shipped code, not assumed

- **The NO_SIGNAL ladder exists with the correct chain** (`_recovery_pass`
  `:381–418`): stale RUNNING → NO_SIGNAL (first miss) → still-stale → FAILED
  (second conclusive miss) → fresh heartbeat → revert to RUNNING.
- **Mode gating** (`tick` `:253–262`): a non-ACTIVE project returns
  `idle="mode:X"` before any dispatch — the wave stops.
- **The generation fence is per-write and the repos are rebuilt per
  acquisition** (`_refresh_fence`) — SD-01 is a *wiring* defect, not a fencing
  defect; a handler that receives the current fence gets the full ADV-02
  protection.
- **Discovery gates on deps-SUCCEEDED** (`_discover_eligible` `:466–482`) — the
  two-template dependency edge (OQ-2) works with zero discovery changes.
- **The handler registry dispatch exists and fail-closes** (`_classify`
  `:579–591`; the `"unhandled"` branch `:530–534`) — an unknown template is
  never a silent SUCCEEDED.
- **EXTRACT classification precedes the registry** (`template ==
  EXTRACT_TEMPLATE` first) — a source template cannot collide with EXTRACT.
- **A2-03 one-shot survives the attempt increment** (`_requeue_recovered`
  `:428`'s own comment: "keyed on producing_task_id, never on attempt") — the
  design's D8 claim on this specific point is correct.
- **The ADMIT/INSERT gateway path + the EXTRACT admission precedent exist**
  (`_is_extract_spec` `:397`, `_validate_extract_source` `:411`) — the OQ-5
  ruling has a shipped pattern to copy.

---

## Overall verdict

**MERGE WITH REMEDIATION.** The architecture is sound and the precedents are
the right ones — the EXTRACT pipeline is exactly the model for the source
write path, the artifact store already exists, the fence is per-write, the
ladder is real. The five findings are design-record gaps that make the record
**unimplementable as written**, not architectural violations:

- SD-01 + SD-02 are **gate-blocking** (P1): the execution surface (per-tick
  fence) and the recovery re-execution (EXTRACT-hardwired) must be pinned
  against the shipped controller before any code.
- SD-03/04/05 are P2 pins: the two-transaction EXTRACT pattern, the
  get-by-hash idempotent branch, and the resolver extension.
- OQ-1…OQ-6 are ruled above; OQ-3's cap-no-retry discipline is the sharpest
  open question and must land in D9.

The fold-in (with SD-01…SD-05 dispositions in the design record + the OQ
rulings) is the standing condition before any step-6 code — the three-gate
pattern that carried steps 1–5a.

---

**Probe evidence:** source inspection + targeted reads of `controller.py`
(`_refresh_fence` :309, `_acquire_lock` :330–370, `_recovery_pass` :381–418,
`_requeue_recovered` :428–453, `_re_execute_requeued` :455–477,
`_dispatch_pass` :512–577, `_classify` :579–591, the one-shot probe :669),
`repositories.py` (`transition_status` :485–530, `ArtifactRepository.record`
:741–758, `_dereference_artifact_ref` :1331–1352), `gateway.py` (`_is_extract_spec`
:397, `_validate_extract_source` :411). Suite unchanged: **837 passed,
`uvx pyright src` 0 errors** (design-only audit; no production code touched).
