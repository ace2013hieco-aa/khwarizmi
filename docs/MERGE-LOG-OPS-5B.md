# MERGE-LOG-OPS-5B — the capability plane and the artifact supply chain

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-5B: wire the capability plane and make a tool observation a citable artifact |
| Base | `main` at `1e97a9b` (the phase-1 gate) |
| Branch | `slice/ops-5b-capabilities` |
| Implementation groups | `0e3b556` (plane), `15041bd` (artifact write), `f357431` (M2 + line), `52a4e3a` (prompt schema) |
| Portability fix | `090aaa8` (ASCII capability-line separator) |
| Test-fixture correction | `1deb71b` (the loop profiles declare `allows_tool_calls` as well as the field) |
| Status | **PASS** — the first falsifier is green (see below) |

## What landed

1. **The plane.** `build_live_composition` builds the shipped research-egress
   supply, one `CapabilityInvoker`, one `RecordingCapabilityPort`, the
   per-`agent_profile` grants and the withheld set. `_model_only_profiles` is
   deleted; `ModelRequest.tools=()` so the router's tool gates are avoided, not
   weakened. The withheld set is one line and one `CapabilityPlaneComposed`
   event (ids/counts/environment only). `cfg.autonomy_caps` is threaded into the
   supply (FIX-C1 class).
2. **The artifact write.** A `FETCHED` `source_fetch` records the provider bytes
   as one `source_payload` artifact through the existing
   `ArtifactStore` -> `ArtifactRepository` path: project-scoped, `task_id` NULL,
   artifact id = content hash (R7), metadata carrying provider, host, content
   digest, redacted URL, idempotency key and lease generation. The tool returns
   `evidence/<artifact_id>` and `source_payload/<content_hash>` handles and no
   body text. Foreign-project dedup and same-hash different-type rows fail
   closed.
3. **M2 and the ledger line.** One recorder per composed run; `LiveVector`
   renders `M2(calls=N,repeat=X.XXX)`, with `0.000` for a measured zero and
   `n/a` only for a composition with no port. The CLI prints the one capability
   line before the first tick.
4. **The prompt schema.** `build_capability_tool_notes` generates the
   `tool_calls` field note from `registry.enumerate(grant)`, the tool summaries
   and closed input schemas, the runtime's `TOOL_CALL_KEYS`, and the supply's
   handle/ref constants. It states the legal ids, item keys, both handles, the
   evidence/source citation forms, the index prefix conversion and the
   proposals-before-tools ordering. The drift test changes a fake registry
   summary and proves the note changes.

## The first falsifier — the artifact row and `EVIDENCE_REF`

A scripted run over the real chain (`RecordedTransport` -> allowlist -> host pin
-> scripted HTTP; no network) produced:

```
OBSERVATION HANDLES: ('evidence/4ba5787cbf0e740291dbfd190867f2e3f06d5335776bee7fb71c6d5245cf5eef',
                      'source_payload/4ba5787cbf0e740291dbfd190867f2e3f06d5335776bee7fb71c6d5245cf5eef')
OBSERVATION PAYLOAD: {"artifact_id": "4ba5787cbf0e740291dbfd190867f2e3f06d5335776bee7fb71c6d5245cf5eef",
                      "capability": "source_fetch", "content_hash": "4ba5787cbf0e740291dbfd190867f2e3f06d5335776bee7fb71c6d5245cf5eef",
                      "media_type": "text/plain", "provider": "openalex", "size_bytes": 63,
                      "source_ref": "source_payload:4ba5787cbf0e740291dbfd190867f2e3f06d5335776bee7fb71c6d5245cf5eef",
                      "status": "FETCHED", "url": "https://openalex.org/W2060313932"}
ARTIFACT ROW:
  artifact_id: 4ba5787cbf0e740291dbfd190867f2e3f06d5335776bee7fb71c6d5245cf5eef
  project_id: p1
  task_id: None
  artifact_type: source_payload
  content_hash: 4ba5787cbf0e740291dbfd190867f2e3f06d5335776bee7fb71c6d5245cf5eef
  size_bytes: 63
  storage_path: 4b\a5\4ba5787cbf0e740291dbfd190867f2e3f06d5335776bee7fb71c6d5245cf5eef
  producer: capability:source_fetch:openalex:RESEARCHER:report-idem
  created_at: 2026-10-25T12:00:00.000000+00:00
  metadata: {"content_digest": "4ba5787cbf0e740291dbfd190867f2e3f06d5335776bee7fb71c6d5245cf5eef",
              "host": "api.openalex.org", "idempotency_key": "report-idem",
              "lease_generation": "lease-gen-7", "media_type": "text/plain",
              "provider": "openalex", "source_url_redacted": "https://api.openalex.org/W2060313932"}
BYTES VERIFY: True
IN_PROJECT: True
EVIDENCE_TRANSITION: ADMITTED entity_id=tr_c5462a9db44a4c148b8d2d0a proposed_events=1
```

The same path is pinned by `tests/test_ops5b_artifact_write.py`:
`test_the_fetch_persists_one_attributable_source_payload_row`,
`test_the_row_is_accepted_by_evidence_ref_through_the_real_gateway`, and the
live-shaped `test_a_live_shaped_run_fetches_then_cites_an_artifact_it_can_prove`
(real runtime, invoker, supply, scripted transport and `apply_intent`).

## The confinement test

`test_the_model_cannot_influence_artifact_content_identity_type_project_or_destination`
**passed**. The declared schema is exactly `{provider, url}`; a hostile argument
set naming `artifact_id`, `artifact_type`, `project_id`, `storage_path` or
`content_hash` is refused `MALFORMED_PAYLOAD` before execution and writes no
row. The normal row's content, identity, type, project and storage path are the
derived values, not the model's strings.

## The capability line, verbatim from the CLI

```
Model plane: live (tiers: m=anthropic:test-model)
Capability plane: 2 supplied (source_fetch, source_search), in-process (no sandbox); granted 1 profile(s) (RESEARCHER); withheld 10 declaration(s): critic/contradiction_scan, critic/evidence_inspect, verifier/evidence_inspect, verifier/statistic_check, planner/artifact_store, planner/graph_read, synthesizer/artifact_store, synthesizer/provenance_read, experimenter/artifact_store, experimenter/experiment_execute
...
vector: runs=2 admitted=2 duplicate=0 intent_refused=0 other=2 mix=SUCCEEDED:1/TOOL_FAILED:0/TIMEOUT:0/CANCELLED:0/OTHER:1 M1(calls=4,min=425,med=795,max=1139) M2(calls=0,repeat=0.000)
```

The literal DB row's `storage_path` is OS-native (`4b\a5\...` on this host);
the tests assert `Path(...).as_posix()`. The line is ASCII; the console shows
it without replacement characters.

## M2

| Case | Value |
| --- | --- |
| CLI run, zero tool calls | `M2(calls=0,repeat=0.000)` |
| Live-shaped runtime run, one fetch | recorder `calls=1`; `repeat_tool_rate == 0.0` |
| Two identical calls (unit) | `M2(calls=2,repeat=0.500)` |
| No port (non-live / pre-5B caller) | `M2=n/a (no capability port on this run)` |

## The first full-suite run — an honest correction

The first full run at `090aaa8` was **red: 18 failed, 5230 passed, 3 skipped**.
Every failure was in `test_loop2_feedback.py` (14) or `test_loop4_hygiene.py`
(4), and every one was the new F4 gate doing its job: the two test-only profile
builders declared `tool_calls` in `structured_fields` but never declared
`allows_tool_calls: true`, because the pre-5B runtime read only `spec.tools`.
The new rule requires both.

The rule was **not** weakened. The two fixtures now declare the flag; the 33
tests in those files pass; no assertion changed. The full suite was rerun from
the corrected tree (gate row below).

## Gates (raw)

| Gate | Result |
| --- | --- |
| Full suite under heavy-gate lock | **5248 passed, 3 skipped, 0 failed** (5251 collected), exit 0, 844.07 s |
| `stamp_suite_count.py --check` | **OK — collected=5251** |
| `check_census.py` | **PASS — 124 / 28 (19/5/4) / 1 / 15 / 0** |
| `uvx ruff check src tests scripts` | **All checks passed** |
| `uvx pyright src` | **0 errors, 0 warnings, 0 informations** |
| pyright tests project | **0 errors, 1 known warning** (`test_research_program.py:144`) |
| B4 ref graphs | **24 passed** (targeted; full suite includes it) |
| LOOP baseline | unchanged (targeted; full suite includes it) |
| Drain-only | byte-identical snapshot passes (full suite includes it) |

## What bounds a run — restated verbatim

**Bounded:** ticks per stage (3–6), model calls per phase/tick (1–2 plus one
retry), tool calls **per batch** (2–6), child runs (≤4) and depth (≤1), run
deadline (120–600 s), transport timeout (10 s), tool deadline (60 s; lowered to
the run's remaining budget by R8), search (≤25 rows, 1 page, 1 MiB), fetch
(1 source, 256 KiB, 1 retry), provider rate gate (in-memory, resets), 4 KiB
event/envelope caps, 40-entry/4 KiB index.

**Not bounded:** aggregate model tokens, aggregate tool bytes, aggregate
requests across ticks/stages, artifact-store disk/GC, or dollars. The
methodology handler reports zero provider requests, so capability HTTP calls
inside the runtime are invisible to `per_run_tokens`; the model ledger records
usage as a diagnostic, not a charge. A single in-flight call can overrun the run
deadline by the transport timeout; R8 lowers the *next* call's budget but cannot
preempt a call already in flight. **No run is token-bounded, spend-capped, or
dollar-bounded.**

## Limits and deliberate refusals

- `source_search` remains **non-actionable** in 5B: the model sees its size and
  digest, not the rows. OPS-5C (read capability) or a bounded structural
  summary is the follow-on.
- `artifact_store` is **not supplied**: a model-callable writer would author
  bytes; the recording write is confined to the fetch executor.
- `NO_FULL_TEXT` is a result without an artifact; no `source_result` row is
  written for search or no-full-text sources in this slice.
- Cross-project content dedup **refuses**; same-hash different-type rows
  **refuse**.
- The artifact row has `task_id` NULL and no `provenance_edges`; it is citable
  by `EVIDENCE_REF`, content-hash refs, retraction and the project index, but
  ref graphs/requirement satisfaction do not see it.
- `source_artifact_is_web_derived` returns False for a capability row (no
  `source_result_ref`); correct for OpenAlex/PubMed, a gap to close before any
  web-provider supply claims evidence.
- The process-construct scan (OPS-5A debt 2) still refuses shell-shaped
  arguments before the egress gate.

Nothing in R1–R10 was refused. The only refusals are the supply limits above.

License: Apache-2.0 (LICENSE).

---

## Director addendum — the first live run after landing (run 12)

Landed at `58f9b01`, then run 12 with the same seed as run 11 so the comparison is direct.

```
runs 9, admitted 8, SUCCEEDED:8/OTHER:1, 14 model calls
M2(calls=4, repeat=0.000)
```

**Four tool calls ran in a live run for the first time.** All four succeeded and were journaled:

```
pubmed    RECORDED_SUCCESS  https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esea…
pubmed    RECORDED_SUCCESS  …
pubmed    RECORDED_SUCCESS  …
openalex  RECORDED_SUCCESS  https://api.openalex.org/works
```

**And zero `artifacts` rows.** All four were `source_search`. The model never called `source_fetch`.

The reason is structural, and it is the LOOP-2 posture working as designed:

> `feedback_envelopes` — *"The record carries no observation payload: only its size and digest
> travel, because the payload's certified route to a judgment surface is its artifact handle."*

A successful search therefore returns `{size, digest, handles}`. **No titles, no URLs.** The model
cannot choose a source to fetch because it was never shown one. R4 predicted this ("`source_search`
remains non-actionable in 5B"); the live run turned the prediction into a measurement — 4 searches,
0 fetches, 0 artifacts, and `EVIDENCE_REF` still refusing.

**What OPS-5B proved, and what it did not.** The plane is live: the allowlist holds, the egress is
journaled, `M2` is a number, the ledger line states the environment and the withheld set, and the
artifact write is attributable and confined. What it did not prove is that a live agent can obtain
evidence — because the first hop of the evidence chain (a result the model can act on) is still
withheld. That is the next gate, and it is a design decision about how much of a search result may
reach a judgment surface, not a wiring bug.

Gates re-run by the Director at the merged tip: 65 targeted passed, stamp `5251`, census **PASS**,
B4 24.
