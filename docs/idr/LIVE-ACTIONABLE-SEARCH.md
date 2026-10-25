# OPS-5C — let the model act on a search result without reading it

| Item | Value |
| --- | --- |
| Task | OPS-5C: make a successful `source_search` actionable without putting its payload text in the prompt |
| Base | `main` at `0f90d38` (OPS-5B merged + run-12 addendum) |
| Branch | `slice/ops-5c-actionable-search` |
| Phase | **1 — design gate. No code in this phase.** |
| Status | **PROPOSED (2026-10-25)** — C chosen; the posture sentence and rulings in §0.1/§10 |
| Run 12 | `M2(calls=4, repeat=0.000)`; four successful searches; **zero fetches, zero artifact rows** |

## 0. Verdict summary

1. **C — make the handle actionable — chosen.** A successful search returns its delivered
   rows to a per-composed-run, in-memory **search-snapshot registry** and gives the model a
   content-derived `search_handle` plus the delivered row count. `source_fetch` accepts
   either the existing `url` form or `(provider, search_handle, row_index)`; the second
   resolves the snapshot row and runs the **same** fetch chain and the **same** OPS-5B
   `source_payload` writer.
2. **The posture is preserved, in one sentence:** *C does not change the LOOP-2 posture —
   the search payload's title/URL text never enters the prompt; the model receives a count,
   an omitted count and a transient snapshot handle, not content.*
3. **The model chooses by position, not by title.** C makes the search **actionable**, not
   **relevant**. The falsifier is "the next `source_fetch` names a row it can identify from
   what it was shown" — a count and a handle satisfy it; titles are not required for the
   gate. If the live run shows blind position choice is inadequate, the next gate is A
   (source-result artifacts + a read capability) or B (bounded rows in the feedback, an
   explicit posture change); both are costed in §2.
4. **The handle is not an artifact and is not citable.** It is a transient locator into the
   in-memory search snapshot. It cannot satisfy `EVIDENCE_REF`; only the fetched
   `source_payload` artifact can. The search observation's `artifacts` list stays empty.
5. **The handle survives the next tick and the composed run, not a process.** The registry
   lives in the supply object, in memory, bounded (32 snapshots), oldest-evicted. A
   process end, a resume in a new process, an eviction or a malformed handle refuses with a
   named tool result; it never falls back to another row. The model can search again.
6. **Refusals are tool results, not a new plane/gateway code or event.** An out-of-range
   index, an expired/invalid handle, a provider mismatch or an ambiguous target returns an
   observation payload `status="REFUSED"`, `code=<named tool code>`, no artifacts, no dial
   and no journal row. The run continues; the model can correct. No new event kind, no new
   refusal vocabulary in the gateway/plane, no new write path.
7. **The fetch writes exactly what OPS-5B writes.** The selected `SearchResult` row goes
   through `adapter.build_fetch_request` → the allowlisted/pinned/recorded fetch → the
   existing `_record_payload` (`source_payload`, content-hash artifact id, project-scoped,
   `task_id` NULL, no body in the interaction row). The artifact metadata adds the search
   handle and row index; no second writer, type, table or transaction.
8. **Determinism is content-derived.** The handle is
   `search_<sha256(canonical({provider, rows:[{result_id, content_hash, source_url}]}))>`;
   the registry maps it to the immutable delivered row tuple; `(handle, 0-based index)`
   always selects the same row while present, and expiry refuses. A collision is a
   composition error, never a silent remap.

### 0.1 The exact posture answer

The search result's title, URL and identifiers stay in the observation payload, which the
prompt never carries; the full `SearchResult` (including its abstract hash) stays in the
in-memory snapshot. The prompt carries the feedback envelope's `payload_bytes`,
`payload_digest`, `artifacts` (empty for a search), and the bounded `detail`. C adds to
that detail only a **count**, an **omitted count** and a **derived handle**. The handle
names a snapshot, not its content; the model cannot read a title from it. This is the
smallest disclosure that makes the first hop actionable.

## 1. Run 12, and what the tree does at this base

### 1.1 The measurement

Landed at `58f9b01`; run 12 (`M2(calls=4, repeat=0.000)`) executed four successful
`source_search` calls — three PubMed eutils and one OpenAlex works — and **zero**
`source_fetch`, **zero** `artifact` rows. The model searched and had nothing to do next.

### 1.2 What the model sees after a search today

`SourceSearchExecutor` (`capability_supply.py:318-360`) returns `_search_result`
(`:701-724`), whose `ToolResult.notes` is:

```
search <provider>: <n> source row(s) (<aggregate>)
```

OPS-5B R3 carries that note as the **bounded success detail** (`TOOL_DETAIL_MAX_BYTES =
1024`, `run.py:380-397`) into `ToolFeedback.detail`; `feedback_envelopes`
(`assembly.py:295-339`) renders it, plus:

- `capability_id="source_search"`, `outcome="TOOL_OBSERVED"`;
- `artifacts=[]` — a search writes no artifact;
- `payload_bytes` and `payload_digest` of the full search payload;
- `invocation_ref` (the derived call key).

The full search payload (`_search_result`, `:702-723`) carries each row's `result_id`,
`title`, `year`, `venue`, `identifiers`, `source_url` and `content_hash`, but **none of
that reaches the prompt**. The model knows how many rows there are (the note), and nothing
that lets it name one.

### 1.3 Why the model cannot fetch

`source_fetch`'s declared inputs are exactly `provider` and `url`
(`capability_supply.py:196-209`); `url` is required by the plane's closed schema. The
executor builds a synthetic `SearchResult` from the URL (`:727-773`) and runs the fetch
chain. A model with no title and no URL cannot satisfy the schema. The run-12 searches
were correct calls with no possible next call.

### 1.4 The read surfaces that do not exist

- `ToolCallContext` (`tools/capabilities/types.py:424-439`) carries only
  `capability_id`, `tool_id`, `idempotency_key`, `lease_generation`, `profile`,
  `deadline_monotonic`, `scratch_dir` — **no connection, no repository, no store**.
- `evidence_inspect` is declared by `critic` and `verifier` but has **no implementation**
  (OPS-5 §3.2; the registry supplies only `source_search`/`source_fetch`).
- The task-side source path writes `source_result` artifacts through
  `SourceOutcomeRepository` (`persistence/source_outcomes.py:331-411`), but that writer
  requires a **RUNNING** `SOURCE_SEARCH`/`SOURCE_FETCH` task; a capability call has no task
  row. The project index lists artifact ids/types (`research/project_index.py:44-47`); it
  lists no search rows and carries no content.

Option A would need a read port this plane deliberately does not have.

### 1.5 The prompt today

The OPS-5B generated `tool_calls` note (`composition.py:330-398`) states the two tools,
their closed schemas, the artifact handles/refs, the index prefix conversion and the
proposals-before-tools ordering. It says `source_fetch(provider, url)`. OPS-5C adds the
second target form and the search-handle rules; the note remains generated from the
registry, not hand-typed.

## 2. A / B / C, costed

### 2.1 A — make the search result an artifact, plus a read capability

Write one `source_result` artifact per delivered row (the task-side taxonomy:
`source_outcomes.py:93-95`) and supply a read capability (`evidence_inspect`, declared by
`critic`/`verifier`) that returns a row's bounded fields to the model.

| Cost | Detail |
| --- | --- |
| A new writer call site | the capability path has no task; `SourceOutcomeRepository.record` refuses without a RUNNING source task, so a new `source_result` write path (or a task-shaped bridge) is needed |
| A read capability | no implementation exists; `ToolCallContext` has no connection/store; a read port into the capability plane is a new authority surface, and `evidence_inspect` is not supplied |
| A round trip | search → inspect → fetch → cite; each inspection is another tool call and another prompt hop |
| The model sees titles | only after the inspection, through the read capability's bounded payload |

**Verdict: rejected for 5C.** It preserves the posture and is the right shape if the model
must judge relevance. It is not needed to satisfy the actionability falsifier.

### 2.2 B — put bounded rows in the feedback

Put title + URL + id per row into the bounded success `detail` (or a new structured
feedback field), capped at the R3 1 KiB detail / 4 KiB envelope.

| Cost | Detail |
| --- | --- |
| **The posture changes** | the LOOP-2 rule says the payload's certified route to a judgment surface is its artifact handle; B puts provider text (title/URL) into the prompt. One sentence would have to say so. |
| Injection surface | titles/URLs are untrusted provider text; they would enter as data but would be read as decision input; the existing system rule covers untrusted blocks, not the decision quality |
| The disclosure is partial | 1 KiB shows only a few rows; the model would see a subset and an omitted count, and may still choose badly |
| No new capability/writer | cheapest to build; the model can choose by relevance |

**Verdict: rejected for 5C.** C meets the falsifier without changing the posture. B is the
cheap relevance fallback if C's blind choice proves inadequate; choosing B would require
this note to say plainly that the posture is being changed.

### 2.3 C — make the handle actionable (chosen)

`source_search` registers its delivered rows in a per-composed-run in-memory
`SearchResultRegistry`, derives a content handle, and adds to the success detail:

```
search_handle=search_<64 hex>; rows=<n>; omitted=<int|unknown>[; omitted_is_estimate=true]
```

`source_fetch` accepts `(provider, search_handle, row_index)` as an alternative to
`(provider, url)`; the handle resolves the immutable `SearchResult` row; the row goes
through the same fetch chain and the same OPS-5B artifact writer.

| Cost | Detail |
| --- | --- |
| A transient registry | in-memory, per composed run, bounded; no table/artifact; not durable |
| The handle lifetime | process-lifetime + capacity; an expired handle refuses; the model re-searches |
| Blind position choice | no titles; the model can fetch row 0..N-1 but cannot know which is relevant |
| A slightly larger prompt detail | ~120-180 bytes per search observation; M1 grows in a tool-bearing run; the LOOP baseline has no tool calls |
| Two target forms | the `source_fetch` schema gains optional `search_handle`/`row_index`; the executor enforces exactly one form; the generated note states it |

**Verdict: accepted**, with the caveat in §0.3. The posture sentence in §0.1 is the
decision.

### 2.4 Rejected alternatives not in the charter

| Option | Cost | Verdict |
| --- | --- | --- |
| Make `source_search` return a URL list in the detail (a narrow B) | same posture change as B; URLs are provider text | rejected with B |
| Have `source_fetch` accept a `result_id` only and resolve from a global search cache | the result_id is provider-derived and must be shown; it is content identity text; a global cache is neither per-run nor bounded | rejected |
| Persist the search rows as `source_result` artifacts and cite them without a read capability | the model cannot read them; persisting content without a reader adds artifacts and no actionability | rejected |
| Let the model fetch the search's query URL again and guess | not a row selection; the model cannot know a row | rejected |

## 3. What the model sees after a search — exact fields and bounds

A successful search produces one `ToolFeedback` (origin `runtime.observation`) rendered
by `feedback_envelopes` with these fields:

| Field | Value |
| --- | --- |
| `tick`, `index` | the call's position |
| `capability_id` | `source_search` |
| `outcome` | `TOOL_OBSERVED` |
| `refusal_code`, `failure` | empty |
| `detail` | `search <provider>: <n> source row(s) (<aggregate>); search_handle=search_<64 hex>; rows=<n>; omitted=<int\|unknown>[; omitted_is_estimate=true]` (0-row: `search_handle=none`) |
| `artifacts` | `[]` — a search result is not an artifact in C |
| `payload_bytes` | byte length of the full search payload (titles included; not shown) |
| `payload_digest` | SHA-256 of that payload (not content) |
| `invocation_ref` | the derived call key |

The `detail` is capped at `TOOL_DETAIL_MAX_BYTES = 1024` (R3) and the whole envelope at
`MAX_PAYLOAD_BYTES = 4096`; the search detail is far below both.

**Bounds and `omitted`:**

- `n` is the number of **delivered** rows: `≤ max_results ≤ 25` (`MAX_SEARCH_RESULTS`),
  one page (`max_pages=1`), `≤ 1 MiB` (`SOURCE_SEARCH_SIZE_CAP_BYTES`).
- `omitted` is `max(0, total_count - n)` when the provider row reports a `total_count`
  (`SearchResult.total_count`); `unknown` when it does not. `omitted_is_estimate=true`
  when that total is an estimate (`total_is_estimate`). It describes what **this call did
  not deliver**; it is not an index space. The handle holds exactly the `n` delivered rows;
  `row_index` outside `0..n-1` refuses. The model can issue another search with a different
  query/`max_results` (still ≤25) rather than ask for an omitted row.
- An `EMPTY` search (valid negative) has `n=0`, no `search_handle`, `omitted=unknown` (no
  row to carry a total). A `PARTIAL`/`UNKNOWN` aggregate keeps the delivered rows and the
  known/unknown omitted count; the aggregate is in the detail.

**No row titles, URLs, identifiers, result ids or row content hashes are shown.** The
payload digest is a digest, not content. The full rows remain in the observation payload
(and, in C, the snapshot), which the prompt never carries; the payload bytes/digest are
the only traces.

## 4. Handle lifetime, and what expiry does

**Lifetime:** the `SearchResultRegistry` is created in `build_research_egress_supply`,
owned by the composed run, and held by both executors. It is **in-memory only** — no
table, artifact, checkpoint or journal row. A handle is valid for later ticks of the same
composed run, including the next tick after the search (the prompt's feedback detail is
the route). It is not shown to a later methodology stage (each stage runtime has its own
feedback), though the registry would still resolve it if the handle were known.

**Bounds:** at most **32 snapshots**, each at most 25 delivered rows; the oldest snapshot
is evicted on insert. The registry holds the transient `SearchResult` objects (titles
included) only in memory; no disk, no prompt, no journal.

**Expiry:** a handle is absent after (a) the composed run/process ends, (b) eviction, or
(c) a resume in a new process (the registry is not checkpointed). An absent but
well-formed handle returns `SEARCH_HANDLE_EXPIRED` and resolves no row. A malformed handle
returns `SEARCH_HANDLE_INVALID`. A search repeated with the same delivered rows re-derives
the same handle and re-registers the snapshot; the handle becomes valid again. The model
can always search again.

## 5. Determinism

**The testable sentence:** *For every handle present in the registry,
`(search_handle, row_index)` resolves to the same immutable `SearchResult` on every call;
a second identical search derives the same handle; after the handle is removed, the fetch
returns `SEARCH_HANDLE_EXPIRED` and resolves no row; a handle is never remapped to a
different row.*

Mechanism:

- `search_handle = "search_" + sha256(canonical_json({provider, rows: [{result_id,
  content_hash, source_url}, ...]}))`; full 64 hex (256-bit, no truncated alias).
- The preimage uses the **delivered order** and excludes timestamps, counts, request logs
  and the aggregate; a re-retrieval of the same rows in the same order derives the same
  handle. A different order or different rows derives a different handle.
- The registry maps handle → `(provider, tuple[SearchResult, ...])`; the tuple is
  immutable and the index is 0-based.
- A duplicate handle with different row identities is a **composition/integrity error**
  (`SEARCH_HANDLE_COLLISION`, fail closed), never an overwrite.
- The row index is bound to the snapshot's order; the fetch uses the row's own
  `source_url` and identity, never a position into the provider's live response.

Test shape: search twice; assert equal handles; fetch `(handle, 1)` twice; assert the same
source URL/`source_payload` row/handles. Evict or rebuild the registry; assert
`SEARCH_HANDLE_EXPIRED` and no artifact. A different index selects the corresponding row.

## 6. The fetch chain and the refusal path

### 6.1 The two target forms

`source_fetch`'s declared inputs become:

| Input | Type | Required | Rule |
| --- | --- | --- | --- |
| `provider` | string, one of OpenAlex/PubMed | yes | must match the handle's provider when the handle form is used |
| `url` | string | no | the OPS-5B URL form |
| `search_handle` | string (max 96) | no | a handle from a prior `source_search` in this composed run |
| `row_index` | integer (max 3 bytes) | no | 0-based index into that snapshot's delivered rows |

Exactly one target form is accepted: `url` alone, or `search_handle` + `row_index` alone.
Both or neither is a named refusal. The generated prompt note states the forms, the 0-based
index, and that the handle is a transient locator, not a citation.

### 6.2 The path

```
source_fetch(provider, search_handle, row_index)
  → registry.resolve(handle, provider, index)      # typed pre-dial checks
  → the selected SearchResult row (source_url, identity)
  → adapter.build_fetch_request(row)
  → preflight_egress / allowlist / host pin / timeout   (unchanged)
  → fetch_batch                                         (unchanged)
  → _record_payload(payload, search_handle=..., row_index=...)   (OPS-5B writer)
  → source_payload artifact + evidence/<id> + source_payload/<hash>
```

The `source_fetch` URL form keeps its existing path. The handle form adds no fetch logic,
no host, no credential and no artifact writer; it only selects the row.

### 6.3 What the fetch writes

The OPS-5B writer exactly: one `source_payload` artifact, content hash = artifact id,
project-scoped, `task_id` NULL, project metadata (provider, host, content digest,
redacted source URL, media type, retrieved_at, idempotency key, lease generation), plus
`search_handle` and `row_index` for the handle form and `search_result_hash` = the selected
row's `content_hash`. The `source_payload` is the citable artifact; the search snapshot is
not. No `source_result` row is written; no `provenance_edge`; no second writer.

### 6.4 The refusal path

The pre-dial selection errors are **tool results**, not plane refusals or tool failures:

| Condition | Result payload | Artifact | Dial | Journal row |
| --- | --- | --- | --- | --- |
| handle malformed | `status="REFUSED"`, `code="SEARCH_HANDLE_INVALID"` | none | none | none |
| handle absent/evicted/process lost | `code="SEARCH_HANDLE_EXPIRED"` | none | none | none |
| provider differs from the handle's provider | `code="SEARCH_PROVIDER_MISMATCH"` | none | none | none |
| index not an integer in `0..n-1` | `code="SEARCH_ROW_INDEX_OUT_OF_RANGE"` | none | none | none |
| both `url` and `search_handle`/`row_index` | `code="FETCH_TARGET_AMBIGUOUS"` | none | none | none |
| neither target form | `code="FETCH_TARGET_MISSING"` | none | none | none |

The result is an `Observation` with `status="OK"`, `artifacts=()`, a payload
`{"capability":"source_fetch","status":"REFUSED","code":...,"detail":...}`, and a note.
The model sees the code in the next tick's bounded feedback detail. The run **continues**
(the model's target choice is a caller mistake, like a malformed call), rather than
`TOOL_FAILED`. No new gateway/plane refusal code, no new event kind, no new journal row.
An actual fetch failure (egress refusal, provider error, timeout) keeps OPS-5A's fatal
`TOOL_FAILED` path.

Rejected: raising a typed exception for the selection errors. That would make a single
bad index end the run and would record only `TOOL_ERROR`/the class name; the project's
refusal-as-data posture and the model's ability to correct both argue for a result. The
one-severity rule (OPS-5A C4) is unchanged: a plane refusal or an observation failure still
stops; a malformed/refused *call* is data.

## 7. What must not change

| Invariant | How C upholds it |
| --- | --- |
| Census 124 / 28 (19/5/4) / 1 / 15 / 0 | the registry is in-memory; the fetch reuses the OPS-5B `ArtifactStore` writer; no new table, transaction-control call or acquisition owner |
| No new event kind | the search and selection refusals are tool results/feedback; the existing `TOOL_OBSERVED` trace, no journal event |
| Single mutation path | tools gather evidence; they never write intents; the registry is derived in-memory state; the artifact write is the OPS-5B recording act |
| Posture | no title/URL/body text in the prompt; only count/omitted/handle; the handle is not citable |
| Drain-only | composition is not entered; byte-identical |
| B4 / governed docs | 24; no governed doc edited; this note is an IDR design record |
| `mutating=False` | unchanged on both tools |
| No key material / no body in journal | the handle is a hash of row identities; no query/title in the detail; the interaction row stays body-less |
| LOOP baseline | no tool calls in the baseline; the search detail grows a tool-bearing run's M1 only |
| OPS-18 read port | untouched; no search rows become artifacts or index entries |

## 8. What I could not decide from the tree

| # | Ruling needed | Why the tree cannot settle it | Recommendation |
| --- | --- | --- | --- |
| **R1** | Is C's blind position choice acceptable for the next live run? | The falsifier only requires actionability; relevance is a separate property. The tree cannot tell whether a live model can use row 0..N-1 without titles. | **C in this slice**; if the live run shows blind choice is inadequate, the next gate is A (source-result + read capability) or B (bounded rows, explicit posture change) |
| **R2** | Registry lifetime: per composed run (chosen) vs per runtime run vs TTL | A per-run registry makes the handle usable next tick; a TTL/cap needs a cost decision. The tree has no existing transient row-cache convention. | **Per composed run, cap 32, oldest-evicted, no TTL** |
| **R3** | Refusal severity: tool result (chosen) vs fatal `TOOL_FAILED` | The C4 rule defines plane refusals/failures as fatal; a selection error is neither. Only the Director can choose the severity of a caller's bad index. | **Tool result**, no dial/artifact; the run continues |
| **R4** | Row index base: 0-based (chosen) vs 1-based | The model sees `rows=N`; either is expressible; 0-based matches the delivered tuple and the note. | **0-based**, stated in the prompt note |
| **R5** | Handle length: full 64 hex (chosen) vs a truncated 24-hex alias | A truncated alias risks a collision/remap; the full handle is ~71 chars and fits the 96-byte input. | **Full 64 hex**; a collision is a composition error |
| **R6** | `omitted` when no total is reported | The provider may omit a total; `unknown` is honest; `0` would claim completeness. | **`unknown`**; `omitted_is_estimate` only when a total exists |
| **R7** | Should the search observation issue a handle for `n=0`? | An empty snapshot has no row to fetch; a handle would consume a slot and cannot be used. | **No handle (`search_handle=none`) for 0 rows** |
| **R8** | Does the search handle belong in the fetch artifact metadata? | It aids attribution but is not durable identity; no `source_result` row exists. | **Yes**, `search_handle` + `row_index` + `search_result_hash`; no `source_result_ref` |
| **R9** | The prompt sentence for the two target forms | The generated schema shows the fields; the "exactly one form / 0-based / transient" rule is prose. | **One generated fixed sentence** in the OPS-5B `tool_calls` note; drift-tested |
| **R10** | Do the selection refusals need a `TOOL_SKIPPED`-shaped feedback envelope? | Today a malformed call gets a refusal/feedback; the selection result is an OK observation with a REFUSED payload. | **No new outcome**; the detail carries the code; the model can correct |

## 9. Falsifiers → tests

| Falsifier | Test shape | Assertion |
| --- | --- | --- |
| After a search, the next `source_fetch` names a row identified from what was shown, and an artifact row exists that `EVIDENCE_REF` accepts | scripted two-tick run: tick 1 `source_search`; read the `search_handle`/rows from the feedback detail; tick 2 `source_fetch(handle, 0)`; then `EVIDENCE_TRANSITION` | the search `artifacts=[]`; the detail has the handle/count; the fetch row is the snapshot row; one `source_payload` artifact; `in_project`; transition `ADMITTED` |
| Out-of-range index refuses with a named code and fetches nothing | `source_fetch(handle, n)` | `Observation` OK, payload `status="REFUSED"`, `code="SEARCH_ROW_INDEX_OUT_OF_RANGE"`, no artifact, no dial, no journal row |
| Expired handle refuses rather than resolving to a different row | fetch after eviction/registry rebuild | `SEARCH_HANDLE_EXPIRED`; no artifact/dial; the same index never selects another row |
| Same handle + index selects the same row across two calls | two fetches with the same handle/index; search twice and compare handles | equal source URL/`search_result_hash`/artifact; equal handles; the second fetch dedups |
| Drain-only byte-identical | the OPS-1 snapshot | exact output; no registry/composition |
| Provider mismatch | `source_fetch(other_provider, handle, 0)` | `SEARCH_PROVIDER_MISMATCH`; no dial/artifact |
| Ambiguous/missing target | both `url` and handle; neither | `FETCH_TARGET_AMBIGUOUS` / `FETCH_TARGET_MISSING`; no dial |
| Detail discloses no content | search detail/envelope scan | no title/URL/identifier/result-id; only count/omitted/handle |
| Prompt schema drift | fake registry with changed `source_fetch` inputs | the generated note follows; the two-form sentence present |
| Census / B4 / baseline | chartered gates | unchanged |

## 10. Gates (implementation phase)

1. Targeted: the new test file, `test_ops5b_artifact_write`,
   `test_ops5b_capability_composition`, `test_ops5_capabilities`,
   `test_loop_observations`, `test_b4_ref_graphs`, `test_census_check`,
   `test_ops1_live_cli`, `test_cli_output_scrub`.
2. `scripts/run_tests.py` (full) under the heavy-gate lock.
3. `scripts/stamp_suite_count.py` then `--check`.
4. `scripts/check_census.py` — unchanged.
5. `uvx ruff check src tests scripts`; `uvx pyright src`; pyright tests project.
6. For **this phase-1 commit**, docs-only: full suite green, stamp `5251`, census PASS,
   B4 24, ruff/pyright; the raw results in the phase-1 report.

## 11. Claim boundary

This note claims the run-12 measurement (four searches, zero fetches, zero artifacts), the
current feedback fields (`assembly.py:295-339`; R3 detail `run.py:380-397`), the current
`source_fetch` schema (`capability_supply.py:196-209`), the search payload's row fields
(`:701-723`), the absence of a read port (`types.py:424-439`; OPS-5 §3.2), and the
OPS-5B artifact writer's behavior. It decides C, the exact disclosed fields, the registry
lifetime/expiry, the determinism sentence and the refusal path. It does **not** claim that
a live model will choose a useful row by position, that C is a relevance solution, or that
a search result is citable; it is not. It does not claim token/dollar boundedness or
scientific validity.

The one sentence to carry forward: **C makes the search actionable by giving the model a
count, an omitted count and a transient handle — never the title that would let it choose
well.**

License: Apache-2.0 (LICENSE).
