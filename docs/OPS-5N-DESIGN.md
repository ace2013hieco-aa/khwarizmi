# OPS-5N — design gate: a retry that changes its request is a new act

| Item | Value |
| --- | --- |
| Slice | OPS-5N, phase 1 (design gate) |
| Base | `main` at `5f1b13d` |
| Branch | `slice/ops-5n-retry-identity` |
| Date | 2026-10-27 |
| Status | **APPROVED and implemented** — see §11 for what shipped and §6 for the corrected §4 ruling |
| Census at base | 124 / 28 (19/5/4) / 1 / 15 / 0 — `scripts/check_census.py` PASS on this tree |

The question is short: **what is the unit of "once" — the slot, or the act?**
The answer is *the act*, and the change is one pure function's preimage plus its
callers. Everything below exists to make that one sentence defensible, and to
separate it from a second collision that looks identical and is not.

---

## 1. The first refusal, checked against the tree

### 1.1 The key names a slot

`agents/runtime/types.py:228-239`:

```python
def tool_idempotency_key_of(run_id, tick, index, capability_id) -> str:
    return digest_of({"run_id": run_id, "tick": int(tick), "index": int(index),
                      "capability_id": capability_id})
```

The docstring above it says why: a resumed run replays "the *same* call key" so
the ledger answers from its record. That is true only while the call is
the same. The arguments are not in the key, so the key cannot tell one act from
another — it names a position in a transcript.

### 1.2 The plane already knows better

`tools/capabilities/invoke.py:672-678`:

```python
def _request_digest(self, request, arguments) -> str:
    return digest_of({
        "capability_id": request.capability_id,
        "profile": request.profile,
        "arguments": redact_arguments(arguments),
    })
```

and `:680-693` refuses `IDEMPOTENCY_CONFLICT` when a settled key's remembered
digest differs. So the contradiction is not that the plane cannot tell two acts
apart. It can. It is that the *key* cannot, so the plane's detector sees a
difference the key promised could not exist.

### 1.3 Which retry can actually re-enter a slot — a correction

The charter pairs the key with OPS-15's re-prompt. Read together with the code,
that pairing is not the mechanism:

- OPS-15's re-prompt lives *inside* `_model_phase` (`run.py:861-960`), before the
  reply is parsed into drafts or tool calls. Attempt 1 returned a `ModelRefusal`,
  so no tool call existed to run. The re-prompt cannot re-enter a tool slot.
- The tool phase runs once per tick (`_tick:751`, calling `_tool_phase` at
  `run.py:780`); a batch's indices are unique within that run of it.
- What *does* re-enter the same slot is the **Controller's retry policy**:
  a failed task goes `FAILED → RETRYING → RUNNING` and `attempt` increments
  (`controller.py:5302-5340`, `_requeue_recovered:3065-3098`). `iteration` is
  never touched; the stage's context is built with `iteration=1` and
  `stage_task_id = f"{task_id}:{stage}"` (`methodology_driver.py:272,287-293`),
  and `run_id = run_id_of(profile, stage_task_id, project_id, iteration)`
  (`types.py:278-282`). Every attempt therefore re-derives the **identical run
  id**, and tick 1's `(run, tick, index, capability)` is identical too. A fresh
  model sample then hands different arguments to the same key.
- The ledger is process-local (`composition.py:954`,
  `InMemoryIdempotencyLedger`), so the settled record survives every retry inside
  one controller process, and nothing survives a restart.

The contradiction is real; its parties are the Controller's retry and the key,
not OPS-15's re-prompt. Fixing the key fixes both, which is why the correction
does not change the recommendation — only the claim about what it repairs.

**Confirmed by the journal** (§6.3): `meth-sars-30` was retried three times
(`attempt 4/4`), and each retry re-entered the same stage task and the same
tick-1 slots. Attempts 2–4 ended `TOOL_FAILED` at HYPOTHESIS: the capability
collision, exactly as this section predicts.

---

## 2. The unit of "once"

A key is a promise about identity. Today it promises "the same position". It is
named, consumed and tested as if it promised "the same act":

- `_replayed_or_conflict` compares **argument** digests, so the plane treats acts
  as the unit;
- `_evidence_refs` uses the key as a citation for *which call* informed a draft
  (`run.py:1046-1057`) — a citation to an act, not to a position;
- `ToolFeedback.invocation_ref` is documented as "the call's derived key, so a
  feedback envelope is attributable back to the exact call it came from"
  (`run.py:422-436`).

Two of the three already mean *act*. The key is the outlier.

---

## 3. Decision — A, in the six-field form, over the raw arguments

**Approved.** `tool_idempotency_key_of` names the act:

```python
tool_idempotency_key_of(run_id, tick, index, capability_id, profile, arguments)
= digest_of({
    "run_id": run_id, "tick": int(tick), "index": int(index),
    "capability_id": capability_id,
    "profile": profile,
    "arguments": dict(arguments),          # raw, canonicalised by digest_of
})
```

The charter's A is `digest(run, tick, index, capability, canonical(arguments))`.
Two additions, both ruled:

1. **`profile`.** `_request_digest` treats the profile as part of the act. A key
   coarser than the check it feeds leaves a reachable false conflict (the same
   derived key under two profiles) that A's own principle says should not exist.
   With it, the plane's `IDEMPOTENCY_CONFLICT` branch is not merely quiet — it is
   *provably* unreachable from this caller: equal key ⇒ equal `(capability,
   profile, arguments)` ⇒ equal request digest.
2. **The raw validated arguments, not the redacted record form.** This reverses
   my first recommendation, on the Director's audit, and the reversal is
   correct: `redact_params` masks by *substring* (`redact.py:73-78`), so any
   argument whose name merely contains `key`, `token`, `auth`, `secret`,
   `password`, `signature` or `apikey` is replaced with `<redacted>` before
   digesting. Two requests differing only in such a field — `sort_key`,
   `keywords`, and any future `author`-shaped field — would produce **one key**,
   and the second act would replay the first act's answer. Redaction is a
   journal-presentation rule; identity is not presentation.

**The theorem, stated in the direction that matters:** equal key ⇒ equal raw
arguments ⇒ equal `_request_digest`. Redaction is a function of the raw
arguments, so the implication survives; what does not hold is the converse, and
that is deliberate — a retry that changes only a masked-name argument is a *new*
act and executes.

If the Director prefers the literal five-field form, the design still works: the
only difference is that the cross-profile conflict stays reachable as a defence
rather than becoming dead code.

### 3.1 Consequences

- A retry that varies **any** declared argument is a different act: it derives a
  new key, executes once, and is recorded as a distinct call.
- A byte-identical re-issue recomputes the same key and replays the recorded
  observation without executing.
- `IDEMPOTENCY_CONFLICT` stays in the plane, tested, as the defence for any
  caller that mints its own keys. It simply stops firing on the runtime path,
  which is the point: the identity now excludes the collision instead of
  detecting it.
- **Not in scope:** two byte-identical calls at two indices of one batch remain
  two executions. The index is still part of the key, and removing it would turn
  a batch's second identical call into a replay of the first — a decision about
  batching, not about retries.
- **Executions per tick rise** from at most `max_tool_calls` to at most
  `max_retries × max_tool_calls` — 3 × the declared batch bound by default
  (`core/node.py:71`, `gateway.py:4217`; a RETRYING→RUNNING transition increments
  `attempt`, `repositories.py:671-680`). `max_tool_calls` itself is unchanged and
  still bounds **one batch**. This must be stated wherever the tool cap is
  described: the cap bounds a batch, and a retried tick is a new batch.

### 3.2 Rejected — B (the retry advances the index)

The `index` is the model's own batch position, and a retry re-enters the tick
with a **fresh reply** whose indices restart at 0. Making the index advance would
require a durable per-`(run, tick)` attempt counter that the model reply does not
control — new derived run state, and a new place for a resume to disagree with
itself. It also redefines `max_tool_calls` from "calls in a batch" to "attempts
recorded in a tick", which is a declared cap changing meaning under a bug fix. It
leaves the §6 collision untouched, because that one is a *task* id.

### 3.3 Rejected — C (a refused tool call is terminal for the tick)

C does not delete OPS-15's retry: OPS-15 repairs whole-reply contract refusals at
the model plane (`_model_phase`), and never had a tool-call repair path. C would
delete the *possibility* of one, and it would make a collision caused by a wrong
identity a terminal property of the run — punishing the run for the key's
mistake. It treats the symptom, keeps the wrong semantics, and leaves §6 alone.

### 3.4 Named costs accepted

- The key preimage now carries argument **text**, hashed and never recorded. The
  live-credential scan runs before anything is recorded (`_require_secret_free_inputs`),
  and the key itself is a digest, so §7's "no key material" holds.
- **A retry that changes only a presentation-masked argument is a new act.**
  The case that matters is a name merely *containing* an alias (`sort_key`,
  `keywords`): those are real arguments and their values must not collapse. A
  true credential-class name never reaches execution — it is refused before the
  idempotency step — so the cost is bounded to names, not to secrets.
- **No new import.** Because the preimage is the raw mapping, `types.py` needs
  no `hermes.tools` dependency at all: the change stays inside the runtime plane,
  which is a smaller diff than the redacted form would have required.

---

## 4. The mutating-capability caveat

**A needs no new guard, and the reason is structural.**

`Tool.mutating` is refused `ROLE` at the authority step
(`invoke.py:558-565`) — before argument validation, before the idempotency step,
before any side effect. A tool that declares `mutating=True` therefore cannot
execute through this plane at all, under any key. There is no `mutating=True`
declaration anywhere in `src/` today. `artifact_store` — declared by `planner`,
`experimenter` and `synthesizer` — is **withheld**: the registry does not supply
it, so `plan_capability_plane` narrows it out of every profile and names it
(`composition.py:283-311`).

`source_payload` is not a capability call: it is a content-addressed dereference
ref, `source_payload:<hash>` (`gateway.py:1620`), and its identity is the hash.
Re-writing identical bytes reaches the same ref, so it is idempotent by content
and never depended on this key.

**Pinned:** if a later slice ever permits a mutating tool to execute, that slice
re-opens this decision and must supply its own once-only argument. The plane's
`ROLE` refusal is the current guard; this slice must not relax it, and must not
be read as having made mutating execution safe.

---

## 5. What replay determinism means now — one testable sentence

> **Within the composing process, a re-issued key returns the recorded
> observation without executing; across a process restart the ledger starts empty
> and the same request executes again, because durable replay would require
> seeding the ledger from the journal. A request that differs in any declared
> argument is a new act and executes exactly once.**

Two corrections to the phase-1 wording, both from the audit:

- **Process-local is the guarantee's scope, not a caveat.** The ledger is
  `InMemoryIdempotencyLedger()` (`composition.py:954`), so a crash resumed in
  the same process replays, and a crash resumed in a new process re-executes.
  The falsifier is therefore stated in its **same-process** form, and the note
  stops implying a durability it does not have.
- Determinism stops depending on *the slot being re-entered with the same
  request* and starts depending on *the request being identical*. That is the
  whole change: same act ⇒ same key ⇒ recorded answer; different act ⇒ new key
  ⇒ one execution.

---

## 6. The second refusal — the §4 answer

### 6.1 What the tree settles

- **The task id is positional.** `_derive_payload` (`run.py:1188-1190`) sets
  `task_id = child_task_id_of(context.task_id, spec.name, slot)` with
  `slot = len(drafts)` — the index among this tick's *surviving* drafts — and
  `child_task_id_of` (`types.py:199-207`) digests
  `{parent_task_id, profile, slot}` only. The observation round-trip is stricter
  still: `child_task_id_of(parent, actor, 0)` — a constant slot
  (`task_handlers/__init__.py:424`).
- **The id's own idempotency key *is* content-derived**:
  `child_idempotency_key_of` digests `{child_task_id, spec_digest}` (`types.py:210-218`).
  A task therefore admits with a content-sensitive key under a content-blind id.
  That asymmetry is the defect.
- **A refused proposal cannot mint an id.** Identity is computed in
  `_derive_payload`, and a row exists only after `task_repo.create`. The guard
  fires only against an existing row (`gateway.py:4726-4733`), which is to say
  against a task that was *already admitted*.

### 6.2 The answer, corrected

**The colliding `task_id` was already admitted. The guard is right.** The
charter's second branch — "the id was derived from a proposal that was itself
refused" — is not reachable: refusals create no rows, so there is nothing to
collide with.

**And the derivation is a defect of the same class as §1.** My phase-1 ruling —
"the guard is right, so the derivation is untouched" — was wrong in its second
half, and the Director's audit plus the journal settle it. The id does not name
the work; it names a position `(parent, profile, surviving draft index)` that
resets to 0 in every model reply and is reused by every later tick, every review
round and every retry. A run can therefore express **at most one distinct child
per reply position, for its whole lifetime** — and the second one is refused by
a guard that is correctly reading the id as "the same task".

That is OPS-5N's own principle one layer up. It is one defect class, not two.

### 6.3 The `sars-covid-30` journal (found at `D:/New folder/hermes-live.db`)

The journal was one directory above the repository, not inside it: 44 events for
project `sars-covid-30`, root task `meth-sars-30` (`max_retries=4`, `attempt 4/4`).
Ordered by `created_at`:

```
20:24:46.115  meth-sars-30 RUNNING                              attempt 1
20:24:54.214  TaskCreated task_59e2de6a…   QUESTION/planner (DIRECTOR), slot 0
20:24:54.217  TaskCreated task_943eed41…   slot 1
20:25:37–20:26:19  TaskCreated ×4          HYPOTHESIS, PREDICTION — 6 admissions total
20:26:41.203  FAILED  MODEL_REFUSED, 3 of 9 stages recorded → RETRYING → RUNNING
20:26:51.147  IntentRejected INSERT_TASK ×2   QUESTION re-derives slots 0 and 1
20:26:57.799  FAILED  TOOL_FAILED, 1 of 9 → RETRYING → RUNNING
20:27:06.041  IntentRejected INSERT_TASK ×2   QUESTION re-derives slots 0 and 1
20:27:22.450  FAILED  TOOL_FAILED, 1 of 9 → RETRYING → RUNNING
20:27:30.656  IntentRejected INSERT_TASK ×2   QUESTION re-derives slots 0 and 1
20:27:44.383  IntentRejected INSERT_TASK ×1   HYPOTHESIS (RESEARCHER) re-derives its slot
20:27:44.385  FAILED + LOOP_PATTERN_QUARANTINED  (3 failures, attempts exhausted)
```

What it settles:

- `task_59e2de6a…` — the id the charter quotes — is created **once**, at
  20:24:54.214, in **attempt 1**, by the **QUESTION** stage (`planner` →
  `agent_profile DIRECTOR`), at slot 0. Every later attempt re-derives it at
  slot 0 and is refused. The charter's "three of these" are the three naming
  this id; the other slot gives three more, so the run produced **six**
  DIRECTOR `INSERT_TASK` refusals, plus one at HYPOTHESIS.
- The two layers coexist in one run: the **task-id** collision at QUESTION on
  every retry, and the **capability** collision at HYPOTHESIS that actually ends
  attempts 2–4 (`TOOL_FAILED`). The task-id refusals are refusal-as-data — the
  QUESTION run still reaches `SUCCEEDED` — which is why they never appear in the
  termination reason.
- The quarantine is the P-AUTO-4 repeat threshold (3 failures), written into the
  terminal reason by the 4th attempt; `max_retries=4` allowed that 4th attempt.

What it cannot settle, and why the tree proof is still needed:

- The `IntentRejected` payload carries `intent_kind`, `proposed_by`,
  `project_id`, `justification` only (`gateway.py:5001-5006`) and `reason` is
  `"intent rejected"` — **the refusal code is not journalled**, and the refused
  proposal's `task_id` is not recorded either. The identity of the refused rows
  rests on the derivation (same stage, same parent, same profile, slot 0) plus
  the charter's quoted message. That is why §6.4's reproduction exists: it names
  the id the journal cannot.

### 6.4 The tree proof (independent of the journal)

Two ticks, one profile, one parent task; each tick proposes one `INSERT_TASK` at
slot 0 with different content, through the real `apply_intent`:

```
t1 INTENT_ADMITTED  entity_id=task_cd83d34c69697f196bbefcf4c6f01b07
t2 INTENT_REFUSED   "task admission rejected: task_id 'task_cd83d34c…' is
                     already admitted with different content — a task_id
                     identifies one command, never two (PA4)"
journal: #2 TaskCreated  task=task_cd83d34c…
         #3 IntentApplied  intent_kind=INSERT_TASK
         #4 IntentRejected intent_kind=INSERT_TASK
tasks:   task_cd83d34c…  spec={"goal": "… (v1)"}
```

and the pure derivation, with no gateway involved:

```
child_task_id_of(parent, "researcher", 0)  → task_cd83d34c…   (content "v1")
child_task_id_of(parent, "researcher", 0)  → task_cd83d34c…   (content "v2")
same id over different content: True
child_idempotency_key_of(…, "v1") → c0d2e879…   child_idempotency_key_of(…, "v2") → 7ee9a4d5…
```

### 6.5 Why the task id is still a separate gate — OPS-5O, a defect gate

This is a **deferral with an owner and evidence**, not a dismissal. The task-id
change is separable for three reasons, and the slice must say so rather than
ship "the derivation is fine":

1. **It changes what a run may express.** Today a run can express one distinct
   child per reply position; after the change it can express one per distinct
   content. That is an admission-semantics change, not a key fix, and it needs
   falsifiers this slice does not have (a re-proposal at the same position must
   become a *new* task; an exact re-emission must still answer `duplicate=True`).
2. **It sits on a certified surface.** GAP-1 D3 / TASK-ADMIT-1 pin the content
   comparison and the canonical byte domain; AGENTS.md requires the owning
   certification slice re-run for a change near them.
3. **It has its own blast radius.** `run.py:1514` uses
   `slot = len(state.delegations)` for the same derivation, so the delegation
   path moves with it.

OPS-5O opens with these three lines, verbatim, as its evidence:

```
run.py:1145   self._derive_payload(kind, dict(payload), context, spec, len(drafts))
run.py:1189   payload["task_id"] = child_task_id_of(context.task_id, spec.name, slot)
run.py:1514   slot = len(state.delegations)
```

with the sentence that is the whole of the gate: *an admission whose idempotency
key is content-sensitive sits under an id that is not.*

Task-id derivation is **byte-identical** in this slice, and
`tests/test_ops5n_retry_identity.py` pins the two derivation values so a later
change cannot arrive as a side effect.

---

## 7. What must not change — and why it will not

1. **No new event kind, write path or transaction.** The change is one pure
   function's preimage and its call sites in `run.py`. Census re-verified on this
   tree today: `scripts/check_census.py` → 124 executed transaction-control calls,
   28 acquisition owners (19/5/4), 1 rollback-only participant, 15
   persistence→research imports, 0 control calls outside certified layers — PASS.
2. **Replay determinism** — §5.
3. **Substrate content rules, gateway checks, capability grants** — untouched;
   the plane's conflict check stays and keeps its test.
4. **Drain-only byte-identical / B4 24.** The new key is still a 64-character
   lowercase hex SHA-256, so every surface that records its *length* (prompt byte
   counts) cannot move. **No trace detail carries the key** — `TOOL_OBSERVED`,
   `TOOL_FAILED` and `TOOL_SKIPPED` details are `capability_id` plus
   `artifacts`/`code`/`failure` — so `trace_digest` cannot move either. This is a
   design constraint on the implementation: the key must not be added to any
   trace detail. Under it, `test_loop_baseline`'s pinned rows and
   `test_b4_ref_graphs` are unchanged by construction.
5. **No key material, no body in the journal row.** The preimage is the raw
   argument mapping, hashed and never recorded; the envelope and the journal
   carry only the plane's redacted record form.

---

## 8. Falsifiers → the tests that carry them

| Falsifier | Test (`tests/test_ops5n_retry_identity.py` unless named) |
| --- | --- |
| A retry that changes its arguments executes, recorded as a distinct act | `test_a_retry_that_changes_its_request_executes_as_a_distinct_act` — two attempts, same `run_id`, different query → two executions, two keys, `SUCCEEDED` |
| A byte-identical replay returns the recorded answer and does not execute — **within the composing process** | `test_a_byte_identical_retry_recomputes_the_key_and_replays` (runtime) and `test_a_derived_key_from_the_plane_side_replays_but_never_conflicts` (plane) |
| Two different searches in one tick are two acts, not a conflict | `test_two_searches_in_one_tick_are_two_acts` — indices 0 and 1 |
| Every field of the act moves the key; raw arguments are the preimage | `test_the_key_changes_with_every_field_of_the_act`, `test_the_key_digests_raw_arguments_not_the_redacted_record_form` |
| The plane's `IDEMPOTENCY_CONFLICT` still refuses a hand-minted collision | `test_a_hand_minted_key_that_collides_still_refuses` (plus the existing plane battery) |
| The task-id derivation is byte-identical to today | `test_the_task_id_derivation_is_byte_identical_to_today`, `test_the_capability_key_is_not_part_of_any_task_id` |
| Baseline and census unchanged | `test_loop_baseline`, `test_b4_ref_graphs`, `test_census_check`, `scripts/check_census.py` |

---

## 9. Gates at implementation

0. **Diff surface, so the gate is sized honestly:** `agents/runtime/types.py`
   (the function and its docstring), `agents/runtime/run.py` (one `key_arguments`
   value and three call sites: 1375, 1389, 1401), and tests. No new module, no
   new event, no new port.
1. Targeted: the new test file, `tests/test_capability_plane.py`,
   `tests/test_ops5b_capability_composition.py`,
   `tests/test_ops5c_actionable_search.py`,
   **`tests/test_ops15_contract_retry.py`** (the charter's
   `test_ops15_contract_feedback` does not exist under that name), plus
   `tests/test_loop2_feedback.py` and `tests/test_loop4_hygiene.py`, which call
   `tool_idempotency_key_of` directly and must move with its signature.
2. `scripts/run_tests.py` (full). No mechanical lock exists in-tree; run it once
   and record the result.
3. `scripts/stamp_suite_count.py`, then `--check`.
4. `scripts/check_census.py` — unchanged.
5. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright tests project.

---

## 10. What this note could not decide — and how each was closed

| Open in phase 1 | Closed by |
| --- | --- |
| The `sars-covid-30` journal (absent from the tree) | The Director's path: `D:/New folder/hermes-live.db`; §6.3 |
| Five-field or six-field A | Ruled: six, over the raw arguments (§3) |
| Whether the task-id derivation is in this slice | Ruled out as a **defect gate** (OPS-5O, §6.5) with the audit's three lines as its opening evidence |
| Attempt counts for run 30 | The journal: 4 attempts, 3 retries, quarantine at the 4th; refusal pairs at QUESTION on each retry (§6.3) |
| Whether replay determinism is durable | Ruled: process-local only; the sentence now says so (§5) |

One thing found and deliberately **not** touched, because it is not this slice:
`_PROCESS_CONSTRUCTS` matches a bare semicolon in any argument
(`invoke.py:179-180, 714-734`), so a search topic containing `;` refuses `ROLE`
and terminates the run (`run.py:1404-1418`). It did not cause run 30's three
`TOOL_FAILED` — those were the idempotency conflict — but it is a live trap for
prose-shaped arguments and is queued separately.

---

## 11. What shipped

| Item | Value |
| --- | --- |
| Key | `tool_idempotency_key_of(run, tick, index, capability, profile, arguments)`, SHA-256 over canonical JSON, raw arguments |
| Diff surface | `agents/runtime/types.py` (the function and its docstring), `agents/runtime/run.py` (one `key_arguments` value, three call sites), four test files |
| New tests | `tests/test_ops5n_retry_identity.py` — 10, the falsifiers above |
| Untouched | task-id derivation, the plane's conflict branch, the substrate, the grants, the census surfaces, the governed documents |
| Census | 124 / 28 (19/5/4) / 1 / 15 / 0 — unchanged |
