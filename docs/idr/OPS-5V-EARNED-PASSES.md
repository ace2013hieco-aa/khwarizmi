# OPS-5V — a pass that nobody earned

| Item | Value |
| --- | --- |
| Task | OPS-5V: three findings from the fourth red-team audit, all of the shape "the record says something passed, and nothing did" |
| Base | `main` at `c07f634` |
| Branch | `slice/ops-5v-earned-passes` |
| Phase | **1 (design gate) — awaiting approval** |
| Status | No product code changed. This note is the deliverable; the probes are read-only |
| Findings | D2 (a review that never ran recorded as a pass), H1 (convergence with zero observations), H2 (a reused predecessor ships `{}` content) |

## 0. Verdict summary

1. **D2 is real and reachable.** A review delegation refused before the child
   runs is turned into `ReviewVerdict(passed=True, child_run_id="")`
   (`run.py:1697-1710`). The verdict gates **nothing durable**: the caller is
   `_close` (`run.py:691`); the only consumer of `passed` as a control
   decision is `_round_continues` (`run.py:735`); and the checkpoint that
   carries it is process-local in the composed live path (`wiring.py:262-274`
   refuses every non-in-memory store). The harm is a lying audit trail, plus a
   latent re-draft decision for a profile that sets `max_review_rounds > 1`;
   no shipped profile does. The fix is in the **verdict**, not in the
   completion: a verdict will distinguish
   `PASS`, `FAIL` and `NOT_RUN`, and `passed` will be true only for a
   completed review. The run's state is unchanged.

2. **D2b — the adjacent case is worse and is in scope.** A review child that
   *ran* and ended `FAILED` is also recorded `passed=True` today
   (measured, §1.2): the parent's `ProposalSet` shows a passing verdict beside
   a delegation whose `child_state` is `FAILED`. A failed child did not
   complete a review; it is `NOT_RUN`, not `PASS`. The same predicate covers
   it; no new surface is added.

3. **H1 is real.** A run whose only feedback is the same `TOOL_SKIPPED`
   refusal converges: `_absorb_evidence` counts every feedback identity,
   including refusals (`run.py:819-832`), and the refusal's content digest is
   stable (`types.py:655-671`). The probe terminates `SUCCEEDED`/`STOP_WHEN`
   after two ticks with zero observations (§1.3). The fix: the evidence set is
   **observations only** (`ToolFeedback.is_observation()`, `types.py:673-675`),
   and the secondary draft-repetition trip applies only when the run has
   **never attempted a tool call** — the legitimate "never sought evidence"
   case the predicate was written for. The attempt marker is set by any
   non-empty `tool_calls` reply, including a malformed call that produces no
   feedback record, and is carried in the checkpoint so a resume keeps the
   distinction. A run that tried tools and was refused does not converge; it
   stops on its declared bound.

4. **What a zero-observation termination is called.** It keeps the name of the
   bound that stopped it: normally `TICK_LIMIT`; `PROPOSAL_LIMIT` where the
   proposal cap fires first. It is **never** `STOP_WHEN`. No new termination
   member and no new event kind are needed. A legitimate zero-observation run
   is one that never attempted a tool (no non-empty `tool_calls` reply) and
   repeated its draft; that run keeps the pinned `STOP_WHEN` repetition trip
   (`test_the_secondary_trip_still_stops_a_run_that_observed_nothing`).

5. **H2's empty object is a bug of omission, but the audit's reachability
   premise is false in this tree.** The successor is meant to receive the
   predecessor's **recorded node content**; the normal path and the pinned test
   prove it (§4.1). The `{}` appears only when the predecessor is in the store
   but not in this execution's `content_cache`; the driver creates a fresh
   store per run (`methodology_driver.py:655`) and parsed documents forbid
   duplicate stages (`workflows.py:375-380`), so no composition can reach that
   state today. The audit's "the reused node can come from a different
   methodology run" requires a store the driver never shares. I reproduced the
   `{}` only by injecting a seeded store through a test seam (§1.4). It is a
   latent shape defect, not a live lie; it is still fixed: seed the cache from
   the existing node, and never fabricate `{}`.

6. **No new event kind, no new termination member, no new `TaskStatus`.** The
   H1 fix adds one derived checkpoint field (`tool_attempted`); D2 adds two
   fields inside each verdict (`completed`, `reason`). Neither is an event,
   an intent, a `TaskStatus` or a census entry. Census stays
   **124 / 28 (19/5/4) / 1 / 15 / 0**. The substrate's rules, the gateway's
   checks and the capability grants are untouched. Drain-only byte-identical;
   B4 24; LOOP baseline unchanged; governed docs untouched.

## 1. The measurements

All probes ran read-only on `c07f634` with the test-owned ports. They are
reproduced in Appendix A. No product file was edited to take them.

### 1.1 D2 — a refused review is recorded as a pass

A profile that requires a review, with the child-run budget exhausted before
the reviewer can be planned:

```
D2 state/termination: SUCCEEDED STOP_WHEN
D2 verdicts: [(True, '', ())]                 # passed, no child run, no objections
D2 refusals: ('MALFORMED_PAYLOAD',)           # "child-run budget 0 is exhausted"
D2 model calls: ['lead']                      # the reviewer was never invoked
```

The code path is exact. `_maybe_review` calls `_delegate_one`
(`run.py:1674-1683`). Every pre-child refusal path returns `None`:
child runs disabled, depth exceeded, child-run budget exhausted, a bad child
spec (`run.py:1510-1532`); a delegator plan refusal (`run.py:1545-1550`); an
oversized child command (`run.py:1561-1574`); and a spine refusal of the
child's `INSERT_TASK` (`run.py:1582-1588`). `_review_verdict` then takes
`proposals = ()`, `objections = ()`, and writes `passed=not objections` →
`True`; the verdict's only tell is `child_run_id=""`.

This is reachable in the live composition: the review is an ordinary
delegation, so any of those refusals applies to it. A run that exhausts its
`max_child_runs` before its terminal act refuses its own reviewer.

### 1.2 D2b — a failed reviewer is recorded as a pass

A reviewer child that ran and ended `FAILED` (here, a model refusal) with no
proposals:

```
state/termination: SUCCEEDED STOP_WHEN
verdicts: [(True, 'run_42db841f5fad6a291681830a80c7a6d8', ())]
delegations: [('DONE', 'FAILED')]             # the delegation says the child failed
refusals: ()                                  # the parent saw no refusal to explain the pass
```

The parent records a passing verdict beside a delegation record that says
`child_state=FAILED`. This is the same defect shape: the verdict answers
"did the reviewer object?" without first asking "did a review complete?".

### 1.3 H1 — identical refusals converge

A `stop_when: converged` profile whose model repeatedly calls a capability its
profile does not open, with repeated drafts:

```
H1 state/termination/ticks: SUCCEEDED STOP_WHEN 2
H1 tool_calls: 0 refusals: ('ROLE', 'ROLE')
H1 feedback: [('TOOL_SKIPPED', 'forbidden'), ('TOOL_SKIPPED', 'forbidden')]
```

Two ticks, zero observations, `SUCCEEDED` by `STOP_WHEN`. The mechanism is
visible in three lines: `_one_tool_call` records a `TOOL_SKIPPED` feedback
record for a capability outside the profile's tools (`run.py:1370-1387`), that
record's `evidence_digest()` includes its outcome and refusal code
(`types.py:663-671`), and `_absorb_evidence` absorbs every feedback record
without asking `is_observation()` (`run.py:830-832`). The second identical
refusal adds no fresh identity, so `evidence_stable=True` and the converged
policy stops (`run.py:859-861`).

Filtering the evidence set alone would not fix this: with no observations it
stays empty, and the secondary draft-repetition trip (`run.py:862-863`) would
still stop the run on the repeated draft. The fix needs both halves: the
observation-only evidence set, and a tool-attempt marker that disables the
secondary trip for a run that did try to call a tool.

A second probe uses a tool call with an unknown key — a malformed call the
plane refuses whole (`run.py:1316-1321`) without a feedback record. It also
converges on the base:

```
malformed state/termination/ticks: SUCCEEDED STOP_WHEN 2
malformed tool_calls: 0 refusals: ('MALFORMED_PAYLOAD', 'MALFORMED_PAYLOAD')
malformed feedback: []
```

The feedback list is empty, so a feedback-only condition cannot see this
attempt; the tool-attempt marker can.

`ToolFeedback.is_observation()` already exists (`types.py:673-675`) and is
already the origin rule for feedback envelopes (`assembly.py:376`); the
convergence predicate is the one place that did not use it.

### 1.4 H2 — the empty object, and why the audit's path is not in this tree

A two-stage workflow (`QUESTION`, `HYPOTHESIS`) with a fake wiring, run twice:
once with the driver's own fresh store, once with the store factory seeded
with a `QUESTION` node from a "previous execution".

```
normal  predecessor_content: {'question': 'q'}
seeded  predecessor_content: {}
```

The seeded run is the audit's shape: `nodes_of_kind` finds the existing
`QUESTION`, sets it as `predecessor_id`, and continues
(`methodology_driver.py:678-685`); the next stage's payload reads
`content_cache.get(predecessor_id, {})` (`:700-701`), and the cache only holds
nodes written in this execution (`:776`), so the successor is told it has a
predecessor whose content is `{}`.

But the driver constructs its own empty `SubstrateStore` at entry
(`methodology_driver.py:655`), so the seeded run required a test seam
(monkeypatching the store factory). A parsed document cannot produce the
state either: `parse_methodology` refuses duplicate stages and out-of-order
stages (`workflows.py:375-380`). A duplicate stage supplied through a directly
constructed `MethodologyConfig` is skipped, but its node was written and
cached by the first occurrence, so the content is present; the probe with
`QUESTION, HYPOTHESIS, HYPOTHESIS, PREDICTION` ran three stages and the
`PREDICTION` context carried the first `HYPOTHESIS`'s recorded content
(`{'external_ref': 'hypothesis:prior', 'predecessors': (...)}`), not `{}`.
The old plane driver has the same branch and the same fresh store
(`workflows.py:820, 841-848, 855-861, 917`).

Conclusion: the `{}` is unreachable in the composed tree. The audit's
"reused node can come from a different methodology run" is true only if a
caller supplies a shared store, and `run_methodology` accepts none. The defect
is latent in shape; the fix is still correct and cheap.

## 2. D2 — the verdict and its consumers

### 2.1 The derivation

`ReviewVerdict` is derived, never authored (`run.py:1685-1710`). Its docstring
says the caller never uses it "to approve, record or resolve anything
durable". That is true of the gateway and the journal, but the sentence is
too wide for the checkpoint and the run report. The design must be explicit
about both.

### 2.2 The consumers, named

| Consumer | What it reads | Durable? |
| --- | --- | --- |
| `_close` (`run.py:691`) | calls `_maybe_review`; appends the verdict (`:695`) | no; the verdict lives in `_RunState` |
| `_round_continues` (`run.py:735`) | `review.passed` decides whether a failing review owes another drafting round | no; it gates a bounded in-process loop |
| `_write_checkpoint` (`run.py:1842`) | carries `review_verdicts` into `Checkpoint` | **in-memory in the live composition**: `require_inmemory_checkpoints` (`wiring.py:262-274`) refuses every other store; `FileCheckpointStore` is test-harness-only (`checkpoint.py:130`) |
| `ProposalSet.review_verdicts` (`types.py:580`) | the run's report | not durable; `ProposalSet.digest()` explicitly excludes review verdicts (`types.py:585-600`) |
| `assembly.review_envelopes` (`assembly.py:476-513`) | renders verdicts into a later round's prompt | no; and a `NOT_RUN` verdict never starts a later round |
| `eval.loop_observations.collect_run` (`loop_observations.py:309`) | labels the verdict `PASS`/`FAIL` for the evaluation vector | an eval report, not a write path |
| `resume` (`run.py:2038-2040`) | restores verdicts and `seen_verdicts` | in-memory checkpoint only |

**No journal row. No repository write. No `apply_intent`. No gateway check.**
The only durable thing the verdict can influence is the drafting the run does
*before* it closes: with `max_review_rounds > 1`, `passed=False` reopens the
run for another round, and those drafts are then emitted through the ordinary
admission path. A false `passed=True` suppresses that round; it never approves
anything. All shipped profiles declare `max_review_rounds: 1`
(`experimenter.yaml:45`, `planner.yaml:48`, `researcher.yaml:53`,
`synthesizer.yaml:46`), so even that gate is inert today.

**Severity: audit-trail, not completion.** The audit's own alternative ("the
harm is an audit trail that lies rather than a completion that lies") is the
correct one. The completion state is not changed by this slice.

### 2.3 The ruling

A review verdict has three outcomes:

| Outcome | `completed` | `passed` | `objections` | When |
| --- | --- | --- | --- | --- |
| `PASS` | true | true | empty | child ran, ended `SUCCEEDED`, raised no proposals |
| `FAIL` | true | false | the raised draft digests | child ran, ended `SUCCEEDED`, raised proposals |
| `NOT_RUN` | false | false | empty | no child ran (pre-child refusal), **or** the child ran but did not end `SUCCEEDED` |

`ReviewVerdict` gains two optional fields, `completed: bool = True` and
`reason: str = ""` (the runtime's own explanation; never reviewer text). For
the no-child case the reason is the delegation refusal's code and detail; for
the failed-child case it names the child's terminal state and refusal codes.
`passed` stays a stored field so existing constructors and checkpoint records
keep working; the derivation sets it `False` whenever `completed` is false.
`to_mapping` / `from_mapping` carry the fields with defaults. For a mapping
that predates `completed`, `from_mapping` infers it from `child_run_id`
(empty means no child ran, so the old record is `NOT_RUN`, not a pass) and
forces `passed=False` when `completed` is false, so a read record cannot say
both "not a review" and "passed"; an old failed-child pass cannot be repaired
from the verdict alone, because the child's state lived only in the delegation
record. `evidence_digest()` stays over
`(reviewer, passed, objections)`: a `NOT_RUN` has `passed=False` and no
objections, distinct from a `FAIL` (which has objections) and a `PASS`; the
new fields are process facts, not verdict content. `_maybe_review` captures
the refusal(s) `_delegate_one` produced for this call (every pre-child path
appends one: `state.refuse` or the delegator's own record) and passes the last
one to `_review_verdict`; for a failed child, the child's own state and
`refusal_codes()` supply the reason.

`_round_continues` gains one guard: an uncompleted verdict never drives a
re-draft, whether it is a `NOT_RUN` or a failed child. `_close` still appends
the verdict, so `_review_pending` sees the round as accounted for and the run
closes rather than retrying a refusal that will not change. The checkpoint and
the report carry the reason. This is the only behavioral change beyond the
label: a failed child's partial objections no longer drive another round, and
that is confined to a profile with `max_review_rounds > 1` (none shipped). A
failed review is not a failing review.

`eval/loop_observations.collect_run` maps the three outcomes to
`PASS` / `FAIL` / `NOT_RUN` so the evaluation vector stops calling an
unexecuted review a failure or a pass. S4/S5 are completed verdicts and their
pinned labels do not move.

The undeclared-reviewer path (`run.py:1667-1671`) already records a refusal
and no verdict; it fabricates no pass, so it is left unchanged.

### 2.4 What this does not do

- It does not turn an unreviewed run into `FAILED`. The run's own acts (drafts,
  admissions) are valid; the review is a configured act that could not run,
  and the record now says so. If the Director wants a required-but-unrun review
  to be a run failure, that is a different ruling with a different blast radius;
  it is listed in §8.
- It does not retry a refused review. The refusal paths are budget/depth/spine
  decisions; a retry would need a policy and a new bound.
- It does not add an event kind, a `TaskStatus`, or a gate.

## 3. H1 — convergence needs an observation

### 3.1 The rule

The run's evidence is the set of **observation** content identities:

- `_absorb_evidence` filters the tick's feedback with
  `ToolFeedback.is_observation()` before digesting it. A `TOOL_SKIPPED` record
  still travels to the next prompt as refusal feedback, but it is not evidence
  and cannot stabilize the evidence set; a `TOOL_FAILED` record stops the run
  before any next prompt.
- The primary trip is unchanged: a non-empty observation set that gains no
  fresh identity in a tick (`run.py:859-861`).
- The secondary trip is narrowed to the case it was documented for: a run that
  has **never attempted a tool call** (`run.py:846-852` already says "no tool
  call returned, no refusal was recorded"). The predicate requires
  `not state.tool_attempted`, not merely an empty feedback list. `_tool_phase`
  sets the marker when a reply carries a non-empty `tool_calls` list, before
  any shape check, so a malformed call that the plane refuses without a
  feedback record still counts as an attempt. The marker is a derived
  checkpoint field; `resume` restores it (and treats any recorded feedback as
  an attempt for a checkpoint written before the field existed), so a resumed
  run keeps the distinction.
- `resume` rebuilds the evidence set from observations only
  (`run.py:2037`). Without this, a resumed refusal-only run would inherit a
  set of refusal identities that the live path no longer produces.

The three draft-trip tests are the contract:

| Case | Tool attempt | Observation | Result |
| --- | --- | --- | --- |
| never sought evidence; repeated draft | no | none | `STOP_WHEN` (the pinned secondary trip) |
| attempted a tool (refused or malformed); repeated draft | yes | none | bound-terminated (`TICK_LIMIT` / `PROPOSAL_LIMIT`), never `STOP_WHEN` |
| observed real evidence; no fresh identity | yes | yes | `STOP_WHEN` (the primary trip) |

### 3.2 What a zero-observation termination is called

The run is **bound-terminated, not converged**. Its `termination` is the
declared bound that stopped it: `TICK_LIMIT` in the ordinary case, or
`PROPOSAL_LIMIT` if the proposal cap fills first. A `stop_when: no_proposals`
profile can stop `NO_PROPOSALS`; that is its own policy, not a convergence
claim. The record already says why no observation arrived: the same refusals
the model kept earning (`TOOL_SKIPPED` / `ROLE` for a disallowed capability;
`MALFORMED_PAYLOAD` for a malformed call). No new termination member is
introduced.

A **legitimate run that observes nothing** is a run that never attempted a
tool: no non-empty `tool_calls` reply (so no feedback and no malformed call
either), and the model repeated its draft. That run's `STOP_WHEN` is the
pre-LOOP-2 repetition trip, preserved
deliberately (`test_the_secondary_trip_still_stops_a_run_that_observed_nothing`,
`test_converged_novelty_is_read_before_the_seen_set_absorbs_it`). The
distinction the fix draws is **"never sought evidence" versus "sought it and
was refused"**; only the former may call itself converged.

### 3.3 Why not a new `NO_OBSERVATION` termination

A new member would name the missing input rather than the reason the loop
stopped, and it would be a second way to say what the refusal feedback already
says. It also adds vocabulary that every termination consumer must learn for a
case whose stop is already correctly named by the tick or proposal bound. The
charter's rule is "no new event kind unless genuinely needed"; the same
discipline applies to termination members. If the bound-terminated outcome
proves too quiet in a live report, a diagnostic field can be added without
changing the stop vocabulary; it is not needed to close this finding.

### 3.4 What does not move

- S1/S2/S3 observe real evidence and still converge; S6 stops on tool failure
  before the predicate; S4/S5 use review rounds and no tools; S7/S8 are
  bounded/child cases. The LOOP baseline is untouched.
- `_tick_new_evidence` (M3, `loop_observations.py:382-397`) still counts
  feedback identities, including refusals. It is a **movement metric**, not the
  convergence predicate; filtering it would move the pinned S6 row (`[1]` to
  `[0]`) and is out of scope. This is a deliberate name/meaning tension,
  recorded here so a later reader does not "fix" the metric and move the
  baseline.
- The new `tool_attempted` field is derived working state in the checkpoint.
  It changes no stop vocabulary, no event kind, no `TaskStatus` and no
  `ProposalSet` digest.
- `max_ticks`, `stop_when` values, objectives, `proposable_kinds`, the act key:
  untouched.

## 4. H2 — predecessor content

### 4.1 The design intent: recorded content, not refs alone

The normal path is unambiguous. `_default_content` builds the stage's content
(`workflows.py:732-764`), `write_node` records it, `content_cache[node_id] =
content` stores it (`methodology_driver.py:776`), and the next stage receives
it as `predecessor_content` (`:700-701`). The pinned test asserts exactly
this: `test_the_objective_never_reenters_the_prompt_as_chain_content`
(`test_ops5f_stage_budget.py:673-687`) reads `predecessor_content` and checks
it is the recorded node content (`cited_refs`), not the stage configuration.

The observation-payload rule (`types.py:629-635`) is about **fetched text**:
the payload's certified route to a judgment surface is its artifact handle, so
the text stays out of prompts. Node content is not fetched text. It is the
substrate's structurally validated chain content — the question, the refs, the
predecessor links — and it is *designed* to flow from stage to stage. The same
principle does not apply. The content must be loaded when known.

### 4.2 Why the empty object is a bug, even though it is latent

`content_cache.get(predecessor_id, {})` fabricates an empty object for a
predecessor whose content the driver has not seen. In the composed tree that
cannot happen (§1.4), but the shape is still wrong in two ways:

1. It says "this predecessor has no content" when the store holds the
   predecessor and its content is right there (`existing[0][1].content`).
2. It makes a future store-sharing composition silently wrong instead of
   failing closed. The audit's cross-run path is exactly that future.

### 4.3 The fix

On a skip, seed the cache from the existing node before continuing:

```python
if existing:
    node_id, node = existing[0]
    predecessor_id = node_id
    content_cache.setdefault(node_id, dict(node.content))
    if projection.stage == "QUESTION":
        question_id = question_id or node_id
    continue
```

And in the live driver, add `predecessor_content` only when the predecessor's
content is known:

```python
if predecessor_id:
    payload = {**dict(context.payload), "predecessor": predecessor_id}
    if predecessor_id in content_cache:
        payload["predecessor_content"] = dict(content_cache[predecessor_id])
    context = context.with_changes(payload=payload)
```

For a known predecessor whose recorded content is itself empty, `{}` is the
truth and is carried; for an unknown predecessor, the key is absent. The
successor never receives a fabricated empty object. The old plane driver
(`workflows.py:841-861`) gets the cache-seeding half; its payload always names
both keys, and after the seeding its content is the recorded content.

The reuse match stays kind + project-wide. That is the substrate's rule and the
charter says the substrate is untouched; the fix does not change which node is
reused, only whether its content is told to the successor.

### 4.4 What this does not do

- It does not make the store durable or share it across runs. The driver still
  starts empty; the branch stays latent.
- It does not validate node content in the driver; `write_node` remains the
  boundary.
- It does not change the matching rule or the chain's project scope.

## 5. Invariants

The charter's "what must not change", restated as the implementation's
invariants:

1. **No new event kind.** The fixes touch `ReviewVerdict`, the convergence
   predicate and its checkpoint marker, and the driver's content cache. Census
   stays **124 / 28 (19/5/4) / 1 / 15 / 0** (`scripts/check_census.py` on the
   base: PASS).
2. **Substrate rules, gateway checks, capability grants untouched.** H2 reads
   `existing[0][1].content`; it does not write, validate or match differently.
   D2 and H1 are runtime-plane data and predicates.
3. **Drain-only byte-identical. B4 24. LOOP baseline unchanged. Governed docs
   untouched.** The changed code is outside the drain path and the B4 graph
   builder; the baseline corpus has no refusal-only convergence case and no
   refused/failed review.
4. **Convergence stays reachable.** The primary trip is unchanged; S1/S2/S3 and
   the LOOP-2 tests remain green. The fix removes only the zero-observation
   case.
5. **`proposable_kinds`, `max_ticks`, objectives, the act key untouched.**
6. **No key material.**

## 6. Falsifiers → tests

The new test file is `tests/test_ops5v_earned_passes.py`; it uses the existing
test-owned ports and a fake wiring for the driver case. The named pins:

| # | Falsifier | Test | Red on base? |
| --- | --- | --- | --- |
| 1 | A review whose child never ran is not recorded as `passed`; the record says why | `test_a_review_whose_child_never_ran_is_not_a_pass` | yes |
| 2 | A review whose child ran and objected is still `passed=False` | `test_a_completed_review_with_objections_is_still_a_fail` (plus the LOOP-3 pins) | no (regression) |
| 3 | A review whose child ran and objected to nothing is still `passed=True` | `test_a_completed_review_with_no_objections_is_still_a_pass` | no (regression) |
| 4 | A review whose child ran and failed is not recorded as `passed` | `test_a_review_whose_child_failed_is_not_a_pass` | yes |
| 5 | A run whose only feedback is identical refusals does not terminate `SUCCEEDED` by convergence | `test_identical_refusals_do_not_converge` | yes |
| 6 | A run whose only tool attempt is a malformed call (no feedback record) does not converge | `test_a_malformed_tool_call_does_not_converge` | yes |
| 7 | A run that observes real evidence and stops still converges | `test_a_run_that_observes_real_evidence_still_converges` (plus the LOOP-2 pins) | no (regression) |
| 8 | A legitimate no-tool repeated draft still converges | `test_a_no_tool_run_still_converges_by_repetition` (the existing pin is retained) | no (regression) |
| 9 | A reused predecessor's content is present or honestly absent, never `{}` pretending | `test_a_reused_predecessor_ships_its_recorded_content` (seeded-store test seam) | yes |
| 10 | Baseline and census unchanged | `test_loop_baseline`, `test_b4_ref_graphs`, `test_census_check` (existing) | no |

Test 9's red-on-base shape is the §1.4 probe: seed the store with a `QUESTION`
node, run the two-stage workflow, and assert the `HYPOTHESIS` context carries
`{"question": ...}` (base: `{}`). The test uses the same monkeypatched store
factory; production code gains no test-only parameter. Tests 5 and 6 assert
`termination == TICK_LIMIT` with `state == SUCCEEDED`, an empty evidence set,
and no new termination member; test 6's reply carries `tool_calls` with an
unknown key or a missing `capability_id`, which the plane refuses without a
feedback record, so it is the case the feedback-only condition would miss.
Test 1 asserts `completed is False`, `passed is False`,
`child_run_id == ""`, and the reason names the budget refusal; test 4 asserts
the same with the child's `FAILED` state named. The resume path gets one
companion pin, `test_a_resumed_refusal_only_run_does_not_converge`: the
checkpoint restores `tool_attempted` and an observation-only evidence set, so
a resumed run cannot inherit the pre-fix refusal identities.

## 7. Gates (implementation phase)

1. Targeted: `tests/test_ops5v_earned_passes.py`,
   `tests/test_ops5t_completion_truth.py`,
   `tests/test_ops5m_truncated_chain.py`, `tests/test_loop_baseline.py`,
   `tests/test_b4_ref_graphs.py`, `tests/test_census_check.py`.
2. `scripts/run_tests.py` (full).
3. `scripts/stamp_suite_count.py` then `--check` (the new file changes the
   count).
4. `scripts/check_census.py` — unchanged.
5. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright tests
   project.

For this design-note commit: the change is documentation-only, so the
AGENTS.md docs-only rule applies — the full suite must be green before the
commit. It ran on the base tree; the note changes no test, so the collected
count is the stamped 5554.

## 8. What I could not decide from the tree

1. **Should a required review that cannot run make the run `FAILED`?** I ruled
   no: it gates nothing durable, the run's other acts are valid, and the
   record now says `NOT_RUN` with a reason. The alternative is a terminal
   `FAILED` for a required-but-unrun review. It is a real policy choice with a
   wider blast radius (every child-run budget exhaustion would fail a run);
   the charter's falsifier only requires "not `passed`, and the record says
   why", which the chosen ruling meets. If the Director prefers the stricter
   terminal, it is one predicate in `_close` and a new falsifier.
2. **Should a failed review child trigger a re-draft?** I ruled no: a failed
   child is not a failing review; its objections are partial and re-drafting
   against them would treat an incomplete review as a judgment. `NOT_RUN`
   closes the round.
3. **Should the old plane driver (`workflows.py`) be fixed in the same
   slice?** I ruled yes for the cache-seeding half: it is the same rule, not a
   different project, and leaving a second spelling of the `{}` fallback would
   be the same defect one file over. Its payload shape is otherwise unchanged.
4. **Should a zero-observation stop get a distinct termination member?** I
   ruled no (§3.3). The bound's name is the stop; the refusals are the why.
5. **H2's cross-run path.** I could not find any composition that shares a
   `SubstrateStore` with `run_methodology`; the audit's premise needs one. If
   the Director knows of a caller that does, H2 is live rather than latent and
   the seeded test is the reproduction. The fix is the same either way.
6. **The undeclared-reviewer branch.** It records a refusal and no verdict
   today; it fabricates no pass, so I left it. If "the record says why" should
   also be a `NOT_RUN` verdict there, it is a third `_maybe_review` return
   shape, not a new concept.
7. **The `tool_attempted` checkpoint field.** I chose a persisted marker over
   the narrower `not state.feedback` condition because the narrower one leaves
   the malformed-call hole: a tool-phase shape refusal records no feedback, so
   the secondary trip would still fire on a repeated draft. The field is one
   derived-state key; if the Director prefers no checkpoint schema change, the
   narrower condition is the fallback and the malformed-call test becomes a
   documented boundary instead of a falsifier.

## 9. Claim boundary

This note claims the three defects' shapes and consumers as measured on
`c07f634`; it does not claim a live model will behave differently, that a
refused review will run, or that a predecessor's content is scientifically
meaningful. It does not claim the audit's H2 cross-run path exists in this
tree; it claims the opposite for the composed driver. It does not implement;
phase 2 waits for approval.

## 10. Phase 2 order (if approved)

1. `agents/runtime/types.py`: `ReviewVerdict.completed` and `.reason`, the
   mapping defaults, and `Checkpoint.tool_attempted`.
2. `agents/runtime/run.py`: capture the delegation refusal in
   `_maybe_review`; derive the three verdict outcomes in `_review_verdict`;
   guard `_round_continues`; filter `_absorb_evidence`; set
   `tool_attempted` in `_tool_phase`; narrow `_tick_termination`; carry the
   field through `_write_checkpoint` and `resume`.
3. `eval/loop_observations.py`: add the `NOT_RUN` label.
4. `research/task_handlers/methodology_driver.py`: seed the cache on reuse;
   emit `predecessor_content` only when known.
5. `methodology/workflows.py`: the cache-seeding half of the same rule.
6. `tests/test_ops5v_earned_passes.py`: the ten falsifiers and the resume
   companion; then the targeted and full gates, and the suite-count stamp.

## Appendix A — probe reproduction

The probes import the test-owned rig from `tests/test_loop2_feedback.py`; they
edit nothing. Run from the repository root with the venv interpreter and
`PYTHONPATH='src;tests'` (Windows separator; the shell is Git Bash).

- **D2** (child-run budget 0, review required): the probe described in §1.1.
  The review child's model script is absent, so the only call is the lead's.
- **D2b** (reviewer model refusal): the same script with the critic script
  omitted entirely; `_Model.invoke` returns the scripted `ModelRefusal`.
- **H1** (disallowed tool repeated, and the malformed-call variant): the
  probes in §1.3; the capability port is empty because `_one_tool_call`
  refuses the capability before invoking it, and the malformed call is refused
  at the shape check before any invocation.
- **H2** (seeded store): a `FakeWiring` returning a `ProposalSet` with one
  admitted `INSERT_TASK` per stage; a two-stage `MethodologyConfig` built
  directly (`QUESTION`, `HYPOTHESIS`); a `QUESTION` `SubstrateNode` seeded into
  a store returned by a monkeypatched `SubstrateStore` factory. The normal
  run's `HYPOTHESIS` context carries `{'question': 'q'}`; the seeded run's
  carries `{}` on the base tree.
