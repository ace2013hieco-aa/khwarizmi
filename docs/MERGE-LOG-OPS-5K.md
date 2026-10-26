# MERGE-LOG-OPS-5K — the ref spelling, the `spec` shape, and a report that shows the value

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-5K: G1 the ref spelling, G2 the `spec` shape, G3 the rejected value |
| Base | `main` at `8937632` |
| Branch | `slice/ops-5k-ref-spelling` |
| Commits | `676dbd7` implementation + tests; `0f4d5aa` the suite stamp; this commit (this log) |
| Status | **PASS** — all falsifiers green; the full suite reproduces the documented baseline-5 only |

## What landed

1. **G1 — one reference, two spellings.** `evidence/<artifact_id>` (the
   observation handle the capability plane returns) and
   `evidence:<artifact_id>` (the citation form) now normalise to the same
   canonical ref before validation. The artifact id still dereferences through
   `ArtifactRepository.in_project` — the one and only artifact-row check — so
   nothing about what a ref must *be* was relaxed. Both spellings produce the
   same transition id and the same stored payload: one reference, not two.
2. **G2 — every enforced `INSERT_TASK` shape is stated.** `spec` renders as
   `a dict` from the validator's own `_PAYLOAD_DICT_SHAPE`. The sibling audit
   found five more unstated enforced shapes — `iteration`, `max_retries`,
   `parent_task_id`, `cost_class`, `concurrency_group` — and all five are
   stated from their own refusal constants. Derived identity keys stay
   unstated because the contract forbids supplying them; `spec`'s inner keys
   stay unstated because the validator does not enforce them.
3. **G3 — the refused value reaches the operator.** Gateway refusals now quote
   the rejected value in their detail, bounded to 120 characters. The runtime
   also keeps the model's bounded reply excerpt on a gateway refusal, so the
   diagnostic report carries the reply text for gateway refusals exactly as it
   already did for model-plane refusals.

## G1 — the normalisation and its pins

The alias is the handle's own prefix, not a second hand-typed literal:
`EVIDENCE_HANDLE_REF_PREFIX = "evidence/"` in `evidence_transitions.py`, and
the drift test compares it to `artifact_handles(...)[0]` from
`capability_supply.py`.

The capability note now says so as well, generated from the same constants:
*"the observation handle `evidence/<artifact_id>` is accepted and normalized to
the same ref"*. The model need not translate the separator by hand; the
validator would accept either spelling even if it did.

`canonical_evidence_ref` accepts exactly two prefixes and returns the
`evidence:<id>` form. The gateway then:

1. canonicalises the ref;
2. checks the id is non-empty;
3. dereferences the id through `in_project`;
4. computes the deterministic transition id from the canonical ref;
5. stores the canonical ref in `EvidenceTransitionProposed`.

The pins:

| Pin | Test |
| --- | --- |
| Both orders admit; the second is a duplicate with the same entity id | `test_both_spellings_resolve_to_one_reference` |
| One event row, carrying the canonical ref | `test_the_stored_ref_is_canonical_for_a_slash_admission` |
| The capability plane's handle is accepted verbatim | `test_the_observation_handle_is_accepted_without_translation` |
| The alias is the handle's prefix | `test_the_handle_spelling_is_the_capability_plane_handle` |
| A ghost id under either spelling refuses `EVIDENCE_REF` | `test_a_ghost_id_under_either_spelling_refuses_evidence_ref` |
| The slash spelling does not bypass project scope | `test_the_slash_spelling_does_not_bypass_project_scope` |
| No prefix still refuses `MALFORMED_PAYLOAD` | `test_a_ref_with_no_recognized_prefix_refuses_malformed_payload` |
| An empty id under either spelling still refuses | `test_an_empty_id_under_either_spelling_refuses_malformed_payload` |
| The canonicalizer accepts exactly the two spellings | `test_the_canonicalizer_accepts_exactly_the_two_spellings` |

### The rejected alternative

The charter offered the alternative: keep the validator strict and state the
distinction far more sharply. I rejected it. The two spellings are not a
distinction to teach — they are one reference emitted by two adjacent
components. Run 18 is the evidence: the model had already fetched the artifact,
the contract stated both forms in adjacent sentences, and it still copied the
handle into the citation. A louder sentence would leave the trap in place and
make the model responsible for a separator the system itself uses two ways.
Changing the observation handle to `evidence:<id>` was the other strict option;
it would touch the capability plane's handle contract and every consumer for no
gain, because the handle is a handle, not a citation. Accepting and normalising
is the smaller change and keeps the dereference as the only authority.

## G2 — the rendered shapes

The rendered line, from the validator's constant:

```text
For INSERT_TASK, the payload key "spec" is optional (omitting it takes the
validator's default); when supplied it must be a dict. Any other value is
refused.
```

The sibling audit over `_TASK_PAYLOAD_KEYS`:

| Key | Validator enforces | Stated | Why |
| --- | --- | --- | --- |
| `spec` | dict | yes | the reported gap (×7) |
| `iteration` | int >= 1 (not bool) | yes | bespoke scalar check; now `_PAYLOAD_INT_AT_LEAST_1_SHAPE` |
| `max_retries` | int >= 0 (not bool) | yes | bespoke scalar check; now `_PAYLOAD_INT_AT_LEAST_0_SHAPE` |
| `parent_task_id` | string or null | yes | `_PAYLOAD_NULLABLE_STRING_SHAPE` |
| `cost_class` | string or null | yes | `_PAYLOAD_NULLABLE_STRING_SHAPE` |
| `concurrency_group` | string or null | yes | `_PAYLOAD_NULLABLE_STRING_SHAPE` |
| `task_id` | derived; supplying it is refused | no | the derived-keys sentence forbids it |
| `idempotency_key` | derived; supplying it is refused | no | the derived-keys sentence forbids it |
| `task_type` | `NodeType` value | already | OPS-13 value set |
| `profile` | `AgentProfile` value | already | OPS-14 value set |
| `inputs` / `outputs` / `dependencies` / `provenance` | list of strings | already | OPS-14/OPS-17 |

The map is exact-pinned in `test_the_shape_map_is_the_validator_shape_family`;
each stated scalar has a refusal pin in `test_each_stated_scalar_shape_refuses`
and a happy-path pin in `test_the_scalar_shapes_admit_legal_values`. The
`spec` pins are `test_spec_as_a_string_refuses_with_the_named_shape`,
`test_spec_as_a_dict_drafts`, and `test_an_omitted_spec_admits_an_empty_dict`.
The drift guard `test_shape_drift_flows_into_the_contract` moves the rendered
line when the map moves.

The shape family adds ten lines / +1 065 UTF-8 bytes to each of the four
task-drafting profiles (`experimenter`, `planner`, `researcher`, `synthesizer`);
`critic` and `verifier` declare no `INSERT_TASK` and are unchanged.

## G3 — the refusal, printed

A gateway `MALFORMED_PAYLOAD` refusal now reads:

```text
MALFORMED_PAYLOAD: payload.evidence_artifact_ref must be
'evidence:<artifact_id>' (or the observation handle 'evidence/<artifact_id>');
got 'evidence/ghost-artifact'
```

A gateway `EVIDENCE_REF` refusal now reads:

```text
PROPOSAL: evidence artifact 'ghost-artifact' (from 'evidence/ghost-artifact')
not in project 'p-ops5k' (spine code EVIDENCE_REF)
```

And the report entry for a gateway refusal carries both the detail and the
model's bounded reply excerpt:

```json
{
  "code": "PROPOSAL",
  "detail": "PROPOSAL: evidence artifact 'ghost-artifact' (from 'evidence/ghost-artifact') not in project 'p-ops5k' (spine code EVIDENCE_REF)",
  "profile": "researcher",
  "tick": 1,
  "stage": "OBSERVATION",
  "excerpt": "{\"kind\": \"EVIDENCE_TRANSITION\", \"rationale\": \"cite the artifact this stage fetched\", \"payload\": {\"evidence_artifact_ref\": \"evidence/ghost-artifact\", \"from_state\": \"SUPPORTED\", \"to_state\": \"ROBUST\", \"rationale\": \"the fetched source supports the rung\"}}"
}
```

The detail is bounded by `_MAX_REJECTED_VALUE_CHARS = 120`; the excerpt is
bounded by the runtime's `bounded_excerpt` and again by the report's
`excerpt_bytes`. The pins are
`test_a_gateway_refusal_carries_the_rejected_ref_in_its_detail`,
`test_a_gateway_refusal_bounds_the_rejected_value`,
`test_a_spec_refusal_carries_the_rejected_value_in_its_detail`,
`test_a_gateway_refusal_reaches_the_report_with_the_reply_excerpt`, and
`test_the_report_entry_is_bounded_by_the_configured_excerpt_cap`.

## Invariants

1. No new event kind, write path or transaction. Census: 124 / 28 (19/5/4) / 1
   / 15 / 0 — unchanged.
2. `proposable_kinds`, the substrate's content rules and the capability grants
   untouched.
3. Drain-only byte-identical. B4 24. Governed docs untouched. LOOP baseline
   unchanged — the new lines are system-message text, not `request.prompt`.
4. No second artifact-row check: `in_project` remains the only one.
5. No key material. No body in the journal row; the rejected value is quoted,
   bounded, and only in the refusal detail.

## Falsifiers

| Falsifier | Result |
| --- | --- |
| `evidence/<id>` and `evidence:<id>` resolve to the same artifact; a ghost id under either spelling refuses `EVIDENCE_REF` | **PASS** — same transition id, one event row, canonical stored ref; both ghost spellings refuse `EVIDENCE_REF` |
| `spec` as a string refuses with a named shape message; a dict drafts | **PASS** — `payload.spec must be a dict; got 'not-a-dict'`; a dict admits |
| A gateway refusal's detail (or the report) carries the rejected value, bounded | **PASS** — detail quotes the ref at 120 chars; report carries detail + excerpt |
| The three-tick sequence still produces an artifact `EVIDENCE_REF` accepts | **PASS** — `test_ops5h_tool_only_tick.py::test_the_three_tick_sequence_cites_the_fetched_artifact` |
| Baseline and census unchanged | **PASS** — LOOP baseline 4/4, B4 24/24, census 124 / 28 (19/5/4) / 1 / 15 / 0 |

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (new file + OPS-5H/5F/5B + LOOP baseline + B4 + census) | `143 passed in 9.00s`, exit 0 |
| Full suite (`scripts/run_tests.py`) | `5 failed, 5371 passed, 3 skipped, 1 warning in 610.86s (0:10:10)` — the 5 are the documented baseline-5 (below) |
| `scripts/stamp_suite_count.py` then `--check` | `Stamped docs\SUITE-COUNT.md: collected=5379`; `OK: docs\SUITE-COUNT.md collected=5379 matches the live collect` |
| `scripts/check_census.py` | `PASS - every certified figure is reproduced exactly.` (124 / 28 (19/5/4) / 1 / 15 / 0) |
| `uvx ruff check src tests scripts` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| `uvx pyright --pythonpath .venv/Scripts/python.exe --project pyrightconfig.tests.json` | `0 errors, 1 warning, 0 informations` (pre-existing `test_research_program.py:144`) |

### The red set is the documented baseline-5

```text
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

These are the five environmental reds documented in
`docs/MERGE-LOG-CAT-1.md` (3 SQLite `attempt to write a readonly database`
races + 1 Windows symlink-privilege refusal + 1 q05 race). They reproduce at the
base; this slice adds no new failure.

## What I refused to do

- **Did not reject the handle spelling.** See "The rejected alternative" above:
  one reference emitted two ways is a system defect, not a model mistake to
  admonish.
- **Did not add a second artifact-row check.** `in_project` is still the only
  dereference; the normalisation runs before it, never around it.
- **Did not state shapes the validator does not enforce.** `spec`'s inner keys
  are free-form and stay unstated; `task_id` and `idempotency_key` are derived
  and stay forbidden rather than described.
- **Did not touch the observation handle, the capability declarations, the
  grants or `proposable_kinds`.** The alias is gateway-side only.
- **Did not put the rejected value in the journal body.** It is quoted in the
  bounded refusal detail; the reply excerpt stays in the diagnostic report,
  which is not a record.

---

## Director addendum — run 19: real evidence, a ref that never arrives, and a success that shouldn't be

Landed at `eff305d`, then run 19.

```
runs 6, admitted 6, SUCCEEDED:6/OTHER:0, M2(calls=5)
artifacts: 1   source_payload, 33,727 bytes, provider=openalex, row_index=0
5 provider interactions
```

**The normalisation works and the agent fetched 33 KB from OpenAlex.** No runtime failures at all. The
model's own rationales show it understood the task: *"OpenAlex search returned 5 relevant rows on
SARS-CoV-2/COVID-19 and SARS containment; fetching the top-ranked row is the required step before any
evidence transition can cite an artifact. PubMed returned empty, so proceeding with the OpenAlex search
handle."*

That is a research agent doing the right thing. And it still did not cite.

### Finding 1 — the ref never reaches the stage that must cite it

`EVIDENCE` refused with:

```
payload.evidence_artifact_ref must be 'evidence:<artifact_id>' …; got 'claim:prior-art-sars19/c1'
```

The model cited the **claim** ref, and its rationale says why:

> *"No admitted evidence id appears in the supplied fragments (only claim/hypothesis/prediction refs and
> the question), so the transition is proposed with the observation chain node as the rationale."*

**OPS-5D made the `EVIDENCE` node carry the evidence ref. It never told the model at that stage what the
ref is.** The stage's objective says "cite the artifact this run observed" and the prompt supplies no way
to know it. The model guessed, honestly, and said so.

Earlier, at `OBSERVATION`, it proposed with `"evidence_artifact_ref": "pending"` — a placeholder, because
it wanted to say *"I will cite whatever I fetch"* and the schema cannot express that. That is the
ordering constraint again, in the model's own words.

### Finding 2 — the run reports SUCCEEDED with no evidence transition

```
terminal: SUCCEEDED | ticks: 3 | 6 stages of 9
EVIDENCE  SUCCEEDED  STOP_WHEN  props=1 adm=0 ref=1
```

A literature review that admitted **zero** evidence transitions — five `IntentRejected` events and no
`EvidenceTransitionProposed` — reported success after six of nine stages.

**That is the illusion this programme exists to prevent.** The run is not wrong that it did work; it is
wrong to call it a completed literature review.

### What this means

The last four gates built a working evidence path: search, fetch, artifact, normalised ref. The agent
walks it. What is missing is (a) the ref being *surfaced* where it is needed, and (b) the run refusing to
call itself complete without one.

Director gates at the merged tip: 93 targeted passed, stamp `5379`, census **PASS**, B4 24.
