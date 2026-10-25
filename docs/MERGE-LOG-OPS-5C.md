# MERGE-LOG-OPS-5C — the actionable search handle

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-5C phase 2: implement the actionable search handle |
| Base | `main` at `0b94135` (the phase-1 design gate) |
| Branch | `slice/ops-5c-actionable-search` |
| Commits | `dc0c54d` (implementation + tests); this commit (merge log + generated suite-count stamp) |
| Status | **PASS** — every charter falsifier is green |

## The correction — the index is a ranked position, not a blind one

The approved caveat said C "makes a search actionable, not relevant". That is
half right, and the wrong half matters. **Providers deliver results in
relevance order**; row 0 is the provider's top-ranked hit. `(handle, 0)` is
therefore not a blind pick — it is "fetch the most relevant result the provider
found", which is what a human does when clicking the first hit. **The rank is
the relevance signal, and it costs nothing.**

Three consequences are implemented:

1. the generated `source_fetch` note states that a search's rows are in the
   provider's relevance order and that row index 0 is the provider's top-ranked
   result;
2. `search_handle_of` encodes the **delivered order** in the preimage and never
   normalises or re-sorts it — the order is the meaning (and the repository's
   `canonical_json` sorts lists of dicts, so it is deliberately not used; see
   §"The serialization trap" below);
3. the fetch artifact's metadata records `search_handle`, `row_index` and
   `search_result_hash`, so the choice is attributable, not only the bytes.

**R1 answered:** yes, C is acceptable for this slice — **because** the position
is ranked, not arbitrary. It remains true that the model cannot judge relevance
beyond rank. If run 13 shows it picking rows it cannot justify, the next gate is
A or B, and B would require stating the posture change plainly. That is recorded
here as the next decision point, not as a claim this slice settles relevance.

## The posture sentence

**C does not change the LOOP-2 posture — the search payload's title/URL text
never enters the prompt; the model receives a count, an omitted count and a
transient snapshot handle, plus the provider's ranked positions (row 0 is the
top-ranked hit) — and the handle locates a row, it does not disclose it.**

## What landed

1. **The transient registry.** `SearchResultRegistry` lives in the
   `ResearchEgressSupply` (one per composed run), in memory only: 32 snapshots,
   oldest-evicted, no TTL, no table/artifact/checkpoint/journal row. It maps a
   content-derived handle to an immutable delivered `SearchResult` tuple. The
   handle is
   `search_ + sha256(key-sorted, list-preserving JSON of {provider, rows:[{result_id,
   content_hash, source_url}]})` over the **delivered order**, full 64 hex.
   A repeated identical search re-derives the same handle and keeps the
   original tuple (the retrieval timestamp is not identity); a different row
   set under an existing handle raises, never remaps.
2. **The search detail.** A successful search renders
   `search <provider>: <n> source row(s) (<aggregate>); search_handle=<handle>;
   rows=<n>; omitted=<int|unknown>[; omitted_is_estimate=true]`. A 0-row search
   renders `search_handle=none`. No title, URL, identifier, result id or row
   hash is disclosed; the observation payload keeps the rows and carries no
   `search_handle` artifact.
3. **The two target forms.** `source_fetch` declares `provider` plus optional
   `url`, `search_handle` (≤96 bytes) and `row_index` (integer, 3-byte bound).
   Exactly one form is enforced in the executor before any dial: `url` alone, or
   `search_handle` + 0-based `row_index` alone. Both, neither, or a half-form is
   a named pre-dial refusal.
4. **The same writer.** The selected row goes through the shipped adapter's
   `build_fetch_request` → `preflight_egress` → host pin → `fetch_batch` → the
   OPS-5B `_record_payload`. One `source_payload` row, content-hash identity,
   `task_id` NULL, project-scoped, no body in the interaction row. The handle
   form adds exactly the three choice fields to the metadata; the URL form is
   unchanged.
5. **The generated note.** `build_capability_tool_notes` appends one generated
   sentence when the reachable `source_fetch` declaration carries all three
   fields, with the field spellings taken from the supply's constants:
   "source_fetch takes exactly one target form: url, or search_handle with a
   0-based row_index; a search's rows are in the provider's relevance order, so
   row_index 0 is the provider's top-ranked result, and search_handle is a
   transient locator for this composed run, never a citation."

## The falsifiers → evidence

### 1. A `(handle, 0)` fetch writes a citable, choice-attributed row

`tests/test_ops5c_actionable_search.py::test_fetch_by_handle0_writes_a_citable_artifact_with_the_choice_in_metadata`
searches, fetches the top-ranked row by handle, and admits an
`EVIDENCE_TRANSITION` naming `evidence:<artifact_id>` through the real gateway.
The same test shows the handle alone is **not** a citation: `evidence:<handle>`
is refused `EVIDENCE_REF`.

The live-shaped run
(`test_the_live_shaped_run_never_puts_a_row_into_the_prompt`) runs the real
`AgentRuntime` over a scripted transport: tick 1 searches, the scripted model
reads the handle from the previous tick's rendered feedback envelope, tick 2
fetches `(handle, 0)`, tick 3 cites the artifact; the evidence proposal is
`ADMITTED`.

### 2. The content-absence pin

The same live-shaped test builds a search whose three rows carry distinctive
`OPS5C-SENTINEL-TITLE-…` strings and `https://openalex.org/W90000000x` URLs.
It asserts that **no** row title, source URL, result id or row content hash
appears in the rendered feedback detail or in any prompt envelope the run
built, while the search envelope carries a 64-hex `payload_digest` and a
positive `payload_bytes`. The result is green; the test can be written, so the
posture did not have to change.

### 3. Determinism and the delivered order

`test_the_index_selects_its_own_row_and_repeats_are_stable`: an identical
second search derives the same handle; `(handle, 1)` resolves to the same URL,
row hash and artifact on every call; index 0 and index 1 select different rows;
the same bytes dedup to one artifact row.

`test_the_handle_preimage_is_the_delivered_order_and_a_different_order_differs`:
the handle re-derives from a hand-built preimage, and reversing the delivered
rows derives a different handle.

### 4. The named refusals (no dial, no artifact, no journal row)

| Code | Test |
| --- | --- |
| `SEARCH_ROW_INDEX_OUT_OF_RANGE` | `test_out_of_range_and_non_integer_indices_are_named` |
| `SEARCH_HANDLE_EXPIRED` | `test_an_expired_handle_refuses_and_selects_no_other_row` |
| `SEARCH_PROVIDER_MISMATCH` | `test_a_provider_mismatch_refuses_without_a_dial` |
| `FETCH_TARGET_AMBIGUOUS` | `test_an_ambiguous_target_refuses_without_a_dial` |
| `SEARCH_HANDLE_INVALID` | `test_a_malformed_handle_refuses` |
| `FETCH_TARGET_MISSING` | `test_a_missing_target_refuses_without_a_dial` (and the half-form variant) |

Each returns an **OK observation** whose payload is `status="REFUSED"` with the
named code: the run continues, the model can correct, and the OPS-5A C4
terminal rule is unchanged. The registry-level `resolve` names bool/non-integer
indices as out-of-range; the capability plane already refuses a non-integer
`row_index` by type before execution.

### 5. Drain-only byte-identical

No composition is entered by `--drain-only`; the CLI snapshot test passes
unchanged.

## The serialization trap (found during implementation)

The first handle encoder used the repository's `canonical_json`. That function
sorts a list of dicts by canonical JSON **by design** (it exists for
order-independent derived sets), so the delivered rank was silently erased:
reversing the rows produced the same handle. The reversal test caught it. The
handle now uses a key-sorted, **list-preserving** `json.dumps` and the
docstring says why. This is the exact failure the Director's correction is
about — the obvious serializer would have made the position arbitrary again.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (the new file, OPS-5B artifact/composition, OPS-5 capabilities, loop observations/baseline, B4, census, OPS-1 drain, CLI scrub) | **121 passed in 57.07s** |
| Full suite under the heavy-gate lock | **5267 passed, 3 skipped, 0 failed in 911.46s (0:15:11)**, exit 0 (5270 collected) |
| `stamp_suite_count.py` → `--check` | **Stamped collected=5270** → **OK: collected=5270 matches the live collect** |
| `check_census.py` | `PASS - every certified figure is reproduced exactly.` (124 / 28 (19/5/4) / 1 / 15 / 0) |
| `uvx ruff check src tests scripts` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| pyright tests project | `0 errors, 1 warning, 0 informations` (the known `test_research_program.py:144`) |
| B4 ref graphs | 24 passed (targeted; the full suite includes it) |
| LOOP baseline | unchanged (targeted; the full suite includes it) |
| Drain-only | byte-identical (targeted; the full suite includes it) |

## Bounds (unchanged and new)

The existing bounds stand: search ≤25 rows / one page / 1 MiB; fetch one
source / 256 KiB / one retry; 4 KiB envelope, 1 KiB tool detail, 4 KiB event
payload. New: 32 transient snapshots per composed run, each ≤25 rows; one
integer row index bound to the snapshot; full 64-hex handles (71 bytes, well
under the 96-byte field).

## Limits and deliberate refusals

- The search snapshot is **not durable** and the handle is **not a citation**.
  A process end, a resume in a new process, or eviction makes the handle
  `SEARCH_HANDLE_EXPIRED`; the model searches again. A snapshot is not
  checkpointed and writes no event, artifact, table row or journal row.
- The content-addressed store dedups by content hash. If the same bytes were
  already recorded (for example by an earlier URL-form fetch), a later
  `(handle, i)` fetch returns the **existing** row and its first metadata; the
  later choice cannot be appended to an immutable row, and this slice does not
  add a second writer to do so. The falsifier's row (a clean first write) does
  carry the three fields.
- The handle is derived from the delivered rows, not from the query string. The
  artifact metadata therefore ties the evidence to the ranked **snapshot** and
  index; the query itself is not re-derivable from the artifact alone (the
  search interaction's request form is redacted). This is the gate's specified
  preimage; no claim is made beyond it.
- C makes a search actionable by **rank**, not relevant by content. Titles,
  URLs, identifiers and row hashes remain outside the prompt; the model cannot
  judge relevance beyond position.
- A `row_index` that is not a JSON integer never reaches the executor: the
  declared `integer` type refuses it as `MALFORMED_PAYLOAD` at the capability
  plane, under the existing malformed-call severity (the C4 terminal rule is
  unchanged). The benign `SEARCH_ROW_INDEX_OUT_OF_RANGE` path covers integer
  indices outside `0..n-1` — the falsifier's "out-of-range index". This is a
  scope statement, not a new severity decision.
- No new event kind, refusal vocabulary, write path, transaction or acquisition
  owner; census remains 124 / 28 (19/5/4) / 1 / 15 / 0. `mutating=False` on
  both tools. No key material; no body in the journal row. The registry is
  memory-only.
- The LOOP baseline has no tool calls and is unchanged.

License: Apache-2.0 (LICENSE).

---

## Director addendum — run 13, and the wall behind it

Landed at `1bf49ef`, then run 13 with the same seed as run 12.

```
M2(calls=2, repeat=0.000)     → 2 searches, both RECORDED_SUCCESS
artifacts: 0                  → no fetch
PROPOSAL: evidence artifact 'synthetic-sars13/e1' not in project   ×3
```

The slice works exactly as specified — and the model still did not fetch. The reason is not the slice
and not the model:

`workflows.py:469-480`

```python
if kind in REF_NAMESPACES:
    ref = inputs.external_refs.get(kind, "")
    return {"external_ref": ref}
```

**Every stage's ref comes from the operator's seed.** The node content is fabricated by
`_default_content` from `inputs`; nothing the agent does can influence it. So the agent can now fetch a
real artifact and the `EVIDENCE` stage still cites whatever string I put in the seed.

**The model cited the synthetic ref because it is the only ref the methodology knows how to use.** That
is a plumbing fact that predates the capability plane, and it explains the whole session: thirteen runs
of contract work made the *prompt* progressively more accurate, and the agent's output still never
reached the substrate.

`CHARTER-OPS-5D.md` names it: **how does what the agent actually did become the content of the node that
records it?**

**One thing this slice caught that deserves naming separately.** The first handle encoder used the
repository's `canonical_json`, which sorts lists of dicts by design — reversing three distinct rows
produced the same handle, silently erasing rank. The reversal test caught it before landing. That is
precisely the failure the ranked-position correction was written to prevent, and it would have been
invisible in any test that did not reverse the rows.

Director gates at the merged tip: 66 targeted passed, stamp `5270`, census **PASS**, B4 24.
