# MERGE-LOG-OPS-5N — the key names an act, and the retry stops refusing itself

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-5N: a capability key that names the act rather than a slot, so a Controller retry that changes its request executes |
| Base | `main` at `0c0ccba` (the OPS-5N design gate; the branch was already at it — no rebase) |
| Branch | `slice/ops-5n-retry-identity` |
| Gate | `docs/OPS-5N-DESIGN.md` — phase 1 approved; §3 and §5 amended and §6 corrected by the Director's phase-2 audit |
| Status | **PASS** — the falsifiers are green, census / LOOP baseline / B4 unchanged |

**Name collision, for the record:** `main` already carries `2c46657 feat(ops-5n): admit openrouter, with a code-owned path allowlist`. This slice uses the same `ops-5n` scope by the charter's naming; the two are unrelated work, and the openrouter commit is an ancestor of this branch.

## What landed

1. **The key names the act.** `tool_idempotency_key_of` (`agents/runtime/types.py:228`)
   now digests six parts:

   ```
   digest({run_id, tick, index, capability_id, profile, arguments})
   ```

   where `arguments` is the **raw** declared mapping, canonicalised by
   `digest_of` (sorted keys, compact separators). One `key_arguments` value is
   computed per tool-call item in `_one_tool_call` and used by all three exit
   paths (two `TOOL_SKIPPED` refusals and the invoke), so a refusal and the call
   it refuses are attributes of the same act.

2. **The disagreement that produced run 30 is gone.** The plane's ledger compares
   the request (`_request_digest`: capability, profile, redacted arguments). The
   old key could not, so a retry that re-entered tick 1 with a fresh model sample
   looked like a key reused for a different act and was refused
   `IDEMPOTENCY_CONFLICT`. The key is now strictly finer than the check it feeds:
   **equal key ⇒ equal raw arguments ⇒ equal request digest.** The plane's
   conflict branch therefore cannot fire on this path, and stays as the defence
   for a caller that mints its own keys (still tested, in both files).

3. **Raw, not redacted** (the audit's reversal, accepted). `redact_params` masks
   by name *and by substring* (`redact.py:73-78`), so digesting the record form
   would collapse `sort_key`, `keywords` and any future alias-shaped field into
   one key — a different act replaying the first act's answer. Redaction remains
   what the envelope and the journal record; identity is not presentation. This
   also removed the planned `hermes.tools` import from `types.py`: the change
   stays inside the runtime plane.

4. **No new state, port, event or transaction.** The diff is one function, one
   value, three call sites and tests. Census 124 / 28 (19/5/4) / 1 / 15 / 0 is
   unchanged; `scripts/check_census.py` PASS.

## The journal — what run 30 actually did

`D:/New folder/hermes-live.db`, project `sars-covid-30`, root task `meth-sars-30`
(`max_retries=4`, `attempt 4/4`), 44 events:

```
20:24:46.115  meth-sars-30 RUNNING                              attempt 1
20:24:54.214  TaskCreated task_59e2de6a…   QUESTION/planner (DIRECTOR), slot 0
20:24:54.217  TaskCreated task_943eed41…   slot 1
20:25:37–20:26:19  TaskCreated ×4          HYPOTHESIS, PREDICTION — 6 admissions total
20:26:41.203  FAILED MODEL_REFUSED, 3 of 9 stages → RETRYING → RUNNING
20:26:51.147  IntentRejected INSERT_TASK ×2  QUESTION re-derives slots 0 and 1
20:26:57.799  FAILED TOOL_FAILED, 1 of 9 → RETRYING → RUNNING
20:27:06.041  IntentRejected INSERT_TASK ×2  QUESTION re-derives slots 0 and 1
20:27:22.450  FAILED TOOL_FAILED, 1 of 9 → RETRYING → RUNNING
20:27:30.656  IntentRejected INSERT_TASK ×2  QUESTION re-derives slots 0 and 1
20:27:44.383  IntentRejected INSERT_TASK ×1  HYPOTHESIS (RESEARCHER) re-derives its slot
20:27:44.385  FAILED + LOOP_PATTERN_QUARANTINED  (3 failures, attempts exhausted)
```

Read with the derivation, it settles both halves:

- **The capability collision is what ended attempts 2–4** (`TOOL_FAILED` at
  HYPOTHESIS): the retried `source_search` re-entered the same
  `(run, tick, index, capability)` with a fresh query. §1 of the design note.
- **The task-id collision is at QUESTION on every retry**: `task_59e2de6a…` is
  created once, in attempt 1, at slot 0, and each retry re-derives it at slot 0
  with different content. Six DIRECTOR `INSERT_TASK` refusals in total (two
  slots × three retries); the charter's three name `task_59e2de6a…`. These are
  refusal-as-data — the QUESTION run still reaches `SUCCEEDED` — which is why
  they never appear in a termination reason.
- The quarantine is the P-AUTO-4 repeat threshold (3 failures) written into the
  terminal reason by the 4th attempt.

The journal does **not** carry the refusal code (`IntentRejected`'s payload is
`intent_kind`, `proposed_by`, `project_id`, `justification`; `reason` is
`"intent rejected"`) and does not name the refused `task_id`. The identification
above rests on the derivation plus the charter's quoted message — which is why
the tree proof in the design note (§6.4) exists.

## The corrected §4 ruling

The Director's phase-2 audit reversed half of the phase-1 ruling, and the code
agrees: `slot = len(drafts)` is the draft's position **within the current model
reply** and resets every model phase, so a run can express at most one distinct
child per reply position for its whole lifetime. The three lines, recorded as
OPS-5O's opening evidence:

```
run.py:1145   self._derive_payload(kind, dict(payload), context, spec, len(drafts))
run.py:1189   payload["task_id"] = child_task_id_of(context.task_id, spec.name, slot)
run.py:1514   slot = len(state.delegations)
```

One defect class, two layers: the capability layer is fixed here; the task-id
layer is **OPS-5O, a defect gate**, with the sentence *an admission whose
idempotency key is content-sensitive sits under an id that is not.* Separable
because it changes what a run may express, lives on a certified admission
surface (GAP-1 D3 / TASK-ADMIT-1), and moves the delegation path too. This
slice pins the task-id derivation byte-identical
(`test_the_task_id_derivation_is_byte_identical_to_today`), so OPS-5O cannot
arrive as a side effect of a retry fix.

## Replay determinism, as it now stands

> **Within the composing process, a re-issued key returns the recorded
> observation without executing; across a process restart the ledger starts empty
> and the same request executes again, because durable replay would require
> seeding the ledger from the journal. A request that differs in any declared
> argument is a new act and executes exactly once.**

The ledger is `InMemoryIdempotencyLedger()` (`composition.py:954`). The falsifier
is stated in its same-process form; no durability is claimed.

## Two pre-existing gate breaks, repaired separately

Both were red on `main` at `0c0ccba`, in files this slice does not own, and both
are behaviour-preserving:

- `tests/test_model_plane.py` — one import out of order (`_unwrap_code_fence`,
  added by `5f1b13d`), rejected by `ruff check`.
- `src/hermes/composition.py` — `OpenAIChatDialect(**{"path": ...})` unpacked a
  `dict[str, str]` into a dataclass with mixed field types; pyright reported the
  `path` value against `json_mode: bool`. Replaced with explicit keyword
  arguments (same construction, same defaults).

Each is its own commit, before the slice's, so the slice's diff stays one
concern. `tests/test_cloud_provider.py`, `tests/test_model_plane.py` and
`tests/test_provider_breadth.py` were re-run after the second: 292 passed.

## Gates (raw)

| Gate | Result |
| --- | --- |
| New file `tests/test_ops5n_retry_identity.py` | 10 passed |
| Targeted: new file + `test_capability_plane` + `test_ops5b_capability_composition` + `test_ops5c_actionable_search` + `test_ops15_contract_retry` + `test_loop2_feedback` + `test_loop4_hygiene` + `test_loop_baseline` + `test_b4_ref_graphs` + `test_census_check` | **305 passed in 12.09s** |
| Pre-fix RED (old derivation, runtime test) | `1 failed` — `assert 'FAILED' == 'SUCCEEDED'`, the run-30 shape |
| `scripts/run_tests.py` (full) | **5449 passed, 3 skipped in 589.28s (0:09:49)**, exit 0 (5452 collected) |
| `scripts/stamp_suite_count.py` then `--check` | Stamped 5452; `--check` → OK, matches the live collect |
| `scripts/check_census.py` | PASS — 124 / 28 (19/5/4) / 1 / 15 / 0 |
| `uvx ruff check src tests scripts` | All checks passed |
| `uvx pyright src` | 0 errors |
| `uvx pyright --project pyrightconfig.tests.json` | 0 errors (1 pre-existing warning) |

## Noted, not touched

`_PROCESS_CONSTRUCTS` matches a bare semicolon in any argument
(`invoke.py:179-180, 714-734`), so a search topic containing `;` refuses `ROLE`
and terminates the run (`run.py:1404-1418`). It did not cause run 30 — the three
`TOOL_FAILED` were the idempotency conflict — but it is a live trap for
prose-shaped arguments. Queued separately; out of scope here.
