# MERGE-LOG-OPS-5G — the shape a tool call lives in

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-5G: state the `tool_calls` shape, not just its keys |
| Base | `main` at `51dfe0f` (the OPS-5F addendum, run 15) |
| Branch | `slice/ops-5g-tool-call-shape` |
| Commits | `3633c26` (implementation + tests), this commit (this log and the stamp) |
| Status | **PASS** — the pinned falsifiers are green |

## The evidence

Run 15's `OBSERVATION` stage ended with

```
MALFORMED_PAYLOAD: model output carried unknown key(s)
                   ['arguments', 'capability_id'] for contract 'runtime_proposal_v1'
```

The model emitted the correct item keys — `capability_id`, `arguments` — at the
**top level of its reply** instead of inside a `tool_calls` array. It knew what a
call consists of; it did not know where it goes.

## The gap

`composition.py:355-382` rendered

```
Item keys: arguments, capability_id, rationale.
```

Key names, never the nesting. A model told "these are the item keys" has no way
to know that the keys belong inside an array named `tool_calls`, whose items are
objects — and the flat form it produced is exactly what that sentence invited.

## What landed

1. **One field-name constant** (`agents/runtime/run.py`). `TOOL_CALLS_FIELD =
   "tool_calls"` is now the name the validator reads (`_tool_phase`) and the
   name `output_contract_for` attaches the note to and `_CONTRACT_SECTIONS`
   declares. The composition imports it; the prompt and the check cannot
   disagree about where a call goes.
2. **One arguments-key constant.** `TOOL_CALL_ARGUMENTS_KEY = "arguments"` is
   the key the validator requires to be a mapping (`_one_tool_call`), and the
   one key the rendered shape shows as an object rather than a string.
   `TOOL_CALL_KEYS` is built from it. There is no second typed list.
3. **The shape helper** (`composition._tool_call_shape`). It iterates the
   validator's closed key set, renders the field name from `TOOL_CALLS_FIELD`,
   and states the negative case. It is used by both note branches — a profile
   with reachable capabilities and a profile with none.
4. **The note** now says, after the legal capability schemas:

   ```
   "tool_calls" is an array; each item is an object with exactly these keys:
   {"arguments": {...}, "capability_id": "...", "rationale": "..."}; the flat
   form — those keys at the reply's top level — is refused (MALFORMED_PAYLOAD).
   ```

   The sentence is one line in the rendered note; the line breaks here are the
   log's.
5. **Tests** (`tests/test_ops5g_tool_call_shape.py`, four tests): the exact
   rendered shape through `render_system`; the drift guard; the flat-form
   refusal; the nested draft that reaches the port.

## The rendered note, verbatim

The live composition over the shipped research-egress supply (in-memory
database, no network). The note rides the profile's `tool_calls` field line:

```
- tool_calls (array, optional; <note>)
```

`researcher` (1497 UTF-8 bytes):

```
legal capabilities: source_fetch(provider: string, one of ['openalex', 'pubmed'], url?: string, search_handle?: string, row_index?: integer) — Fetch one source by allowlisted URL, or one row of a prior search by its transient handle and 0-based index. Runs in-process (no sandbox).; source_search(provider: string, one of ['openalex', 'pubmed'], topic?: string, doi?: string, pmid?: string, max_results?: integer) — Search one allowlisted provider (OpenAlex or PubMed) for source rows. Runs in-process (no sandbox).. "tool_calls" is an array; each item is an object with exactly these keys: {"arguments": {...}, "capability_id": "...", "rationale": "..."}; the flat form — those keys at the reply's top level — is refused (MALFORMED_PAYLOAD). An observation returns artifact handles evidence/<artifact_id> and source_payload/<content_hash>; cite EVIDENCE_TRANSITION as evidence:<artifact_id> and a source/claim ref as source_payload:<content_hash>. A project-index artifact entry id is <artifact_type>:<artifact_id>; replace the type prefix with evidence: for EVIDENCE_TRANSITION. Proposals are admitted before tool calls in the same tick, so an artifact observed this tick can be cited only in a later tick. source_fetch takes exactly one target form: url, or search_handle with a 0-based row_index; a search's rows are in the provider's relevance order, so row_index 0 is the provider's top-ranked result, and search_handle is a transient locator for this composed run, never a citation.
```

`critic` (314 UTF-8 bytes; no grant, no reachable capability):

```
no capability is reachable for this profile — a tool_calls item is refused (ROLE). "tool_calls" is an array; each item is an object with exactly these keys: {"arguments": {...}, "capability_id": "...", "rationale": "..."}; the flat form — those keys at the reply's top level — is refused (MALFORMED_PAYLOAD).
```

The field name is `TOOL_CALLS_FIELD`; the keys are exactly `TOOL_CALL_KEYS`;
`arguments` is the key `TOOL_CALL_ARGUMENTS_KEY` and is shown as an object
because the validator requires a mapping.

## The two pins

**Flat refusal** —
`tests/test_ops5g_tool_call_shape.py::test_the_flat_form_still_refuses_malformed_payload`.
The live `runtime_proposal_v1` contract and a reply carrying top-level
`capability_id` and `arguments` (run 15's exact shape). The router's whole-reply
unknown-key check still refuses: `MALFORMED_PAYLOAD`, detail
`['arguments', 'capability_id']`, contract `runtime_proposal_v1`. The note is
guidance; the check is unchanged.

**Nested draft** —
`tests/test_ops5g_tool_call_shape.py::test_a_nested_tool_calls_array_drafts_and_reaches_the_supply`.
The runtime path with the same nested shape (a controlled profile without a
review child isolates the pin): the router accepts the reply, the runtime drafts
one `INSERT_TASK`, and the capability port receives `source_search` with the
declared arguments and the call's rationale. One model call, one draft, one tool
call, no refusal.

## The drift guard, and its demonstrated failure

`test_the_rendered_shape_moves_when_the_validator_key_set_moves` first asserts
the rendered shape's key set equals `TOOL_CALL_KEYS`, then renders with
`TOOL_CALL_KEYS | {"timeout_seconds"}` and asserts the new key appears and the
rendered set equals the grown set. Adding a key to the validator's closed set
therefore moves the prompt, not just a test-local copy.

Demonstrated by temporarily hardcoding the previous three keys in
`_tool_call_shape`:

```
>       assert '"timeout_seconds": "..."' in after
E       assert '"timeout_seconds": "..."' in "legal capabilities: source_search(..."
FAILED tests/test_ops5g_tool_call_shape.py::test_the_rendered_shape_moves_when_the_validator_key_set_moves
```

The renderer was restored; the test is green in the gate below.

## System-byte delta

The same probe (live supply, rendered system text, UTF-8 bytes with LF) before
and after, from a base worktree at `51dfe0f`:

| Profile | System before | System after | Delta | Note before | Note after |
| --- | --- | --- | --- | --- | --- |
| `researcher` | 2936 | 3118 | **+182** | 1315 | 1497 (+182) |
| `critic` | 1760 | 1942 | **+182** | 132 | 314 (+182) |

The delta is exactly the replaced sentence: `Item keys: arguments,
capability_id, rationale.` (47 UTF-8 bytes) → the 229-byte shape sentence. No
message, payload envelope, tick marker or prompt payload changed. The note is
system text, never a `ModelRequest.prompt` envelope, so M1 (payload bytes at
the port) is unchanged by construction; no token or cost claim is made.

## Invariants

- **No new event kind, write path or transaction.** Census unchanged:
  124 / 28 (persistence 19, gateway 5, Controller 4) / 1 rollback-only / 15
  persistence→research imports / 0 outside certified layers.
- **LOOP baseline unchanged.** No pinned scenario row, digest or metric moved;
  the note is composition-only system text.
- **Drain-only byte-identical.** The note is built only on the live path; the
  drain-only CLI path is untouched. B4 24.
- **Governed docs untouched.**
- **No key material.** The note names capabilities, schemas and handles only.
  The tests use a scripted provider and a fake capability port.
- **No second schema list.** The field name, key set and arguments key are the
  validator's own constants.
- **The budget and the objective are untouched.** `OBSERVATION: 3` and the
  stage objectives are exactly as OPS-5F landed them; this slice adds prompt
  guidance and no policy.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (the new file, OPS-5B composition, OPS-5C actionable search, OPS-5F stage budget, loop baseline, B4 ref graphs, census) | **106 passed in 11.72s** |
| Full suite under the heavy-gate lock | **5310 passed, 3 skipped in 594.29s (0:09:54)**, exit 0 (5313 collected) |
| `stamp_suite_count.py` → `--check` | **Stamped collected=5313** → **OK: collected=5313 matches the live collect** |
| `check_census.py` | `PASS - every certified figure is reproduced exactly.` (124 / 28 (19/5/4) / 1 / 15 / 0; BEGIN 29, COMMIT 28, ROLLBACK 67) |
| `uvx ruff check src tests scripts` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| pyright tests project | `0 errors, 1 warning, 0 informations` (the known `test_research_program.py:144`) |
| B4 ref graphs | 24 (targeted run) |
| LOOP baseline | unchanged (targeted run) |

## Limits

- **The note is guidance, not a validator.** A model can still mis-shape a
  call; the refusal remains data and the run remains bounded. Run 16 is the
  measurement of whether the model acts on the shape.
- **The note grows.** 182 bytes per profile is a deliberate prompt cost; no
  token or dollar bound is claimed (OPS-16 unlanded).
- **The field name is still configuration-visible.** A profile that declares
  `tool_calls` in `structured_fields` gets the note; a profile that does not is
  unchanged. The name is single-sourced in code, not in profile data.

License: Apache-2.0 (LICENSE).

---

## Director addendum — run 16, and the contradiction

Landed at `fcb6cc8`, then run 16.

```
runs 5, admitted 8, M2(calls=0), artifacts: 0
… OBSERVATION → FAILED/MODEL_REFUSED
intent_refused=0        → the flattening refusal is gone
```

The shape fix worked: no reply was refused for unknown keys at the top level. But the two refusals in
`OBSERVATION` tick 1 are the most informative of the whole session:

**[1] — the model formed the call correctly and was refused anyway.**

```json
{
  "rationale": "Begin evidence acquisition by searching PubMed for peer-reviewed literature …",
  "tool_calls": [
    {"capability_id": "source_search",
     "arguments": {"provider": "pubmed", "topic": "SARS 2003 containment vers…"}}
  ]
}
```

→ `ROLE: model proposed kind None, outside the injected proposable allowlist`

The nesting is right. The capability id is right. The arguments are right. **The reply has no `kind`,
because the model is not proposing anything yet — it is gathering.** And the contract refuses a reply
without a `kind`, so the tool call is discarded with it.

**[2] — the retry, which reverted to the flat form**, refused `MALFORMED_PAYLOAD`.

### The contradiction

`OBSERVATION`'s objective says *"Gather first, propose last."* The contract says *every reply carries a
proposal kind.* Those cannot both be satisfied:

- propose → the stage stops (`stop_when: proposals_raised`) before gathering;
- gather without proposing → refused `ROLE`, and the call is thrown away.

**The model did the right thing and the validator rejected it.** Fifteen runs of contract work taught it
the shape; the runtime then refused the only reply that could act on it.

### What this means

The capability plane, the budget, the objective and the shape are all now correct. What is missing is the
one thing none of them can provide: **a way to say "no proposal this tick, but here is a tool call."**

That is the next gate, and it is the last structural blocker I can identify.

Director gates at the merged tip: stamp `5313`, census **PASS**, both pins green.
