# MERGE-LOG-OPS-5L — the ref the stage can read, and a terminal that cannot lie

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-5L: the admitted evidence ref reaches the `EVIDENCE` prompt; a citationless run stops reporting success |
| Base | `main` at `5d976d1` (the OPS-5L design gate; the rebase onto it was a no-op) |
| Branch | `slice/ops-5l-evidence-ref-and-completion` |
| Gate | `docs/idr/OPS-5L-EVIDENCE-REF-AND-COMPLETION.md` — phase 1 approved ("A approved"), phase 2 rulings in its §10 |
| Commits | `21d97ad` implementation + tests; the §10 docs commit; the suite stamp; this log |
| Status | **PASS** — all four falsifiers green; census, B4, LOOP baseline and the drain-only bytes unchanged |

## What landed

1. **A — the `runtime.evidence` envelope.** `evidence_envelope`
   (`assembly.py:291`) renders exactly `{"evidence_ref": "evidence:<id>",
   "artifact_id": "<id>"}` with origin `runtime.evidence` (`assembly.py:123`) and
   ref `{stage_task_id}:evidence`. The live driver appends it after the project
   index and before `wiring.run` (`methodology_driver.py:628`), so the assembled
   order is `runtime.task`, `runtime.project_index`, `runtime.evidence`, then the
   `runtime.payload` parts. It is **absent** while the run holds no admitted ref —
   never a "none" object — and it rides every stage from the first one after the
   admission. Two short strings, no rationale, provider, URL, byte count, state
   rung or content, and no new port: the driver hands the runtime an
   already-rendered envelope.
2. **The reader gap is closed on the read side.**
   `_admitted_evidence_proposal` / `_evidence_ref_of` (`workflows.py:657`, `:695`)
   take an optional `canonicalise` callable, and the live driver injects the
   research plane's own `canonical_evidence_ref` — the same grammar OPS-5K applied
   at the writer. An admitted `evidence/<id>` now selects as the run's evidence
   ref, and the `EVIDENCE` node stores the canonical `evidence:<id>`. The gateway,
   the substrate, the stored event and the `EVIDENCE` requirement are untouched;
   the event was already canonical.
3. **The report mirrors the root methodology task.** `build_run_report` gains
   `task_outcomes` and a `terminal_reason` field; `_terminal` (`run_report.py:182`)
   ranks `QUARANTINED` > a non-`SUCCEEDED` root task > the fail-closed evidence
   backstop > `NO_STAGE_RUNS` > a non-`SUCCEEDED` stage > `SUCCEEDED`.
   `_root_task_outcomes` (`cli.py:477`) reads the root task's state and its latest
   `FAILED` `TaskStatusChanged` reason, read-only, on the run's own connection,
   before it closes; any failure returns `()` and the report falls back to its
   stage-only path. `terminal_reason` is in `_fit`'s minimal key set, so a
   truncated report never drops the field that explains the terminal. **No new
   terminal value exists** — `FAILED` was already in the vocabulary.

## The EVIDENCE prompt, as it now reads

A scripted fetch-then-cite run (real capability supply, real gateway, real
substrate, real live driver; no network). The `EVIDENCE` stage's parts, in order:

```text
 origin: runtime.task           ref: task-ops5d:EVIDENCE:task_input
 origin: runtime.project_index  ref: p-ops5d:project_index
 origin: runtime.evidence       ref: task-ops5d:EVIDENCE:evidence
   {"artifact_id": "0eb8332c7cbbb89c5cb0f626816a31ec02864879fe044c5df5b87b916c18df73",
    "evidence_ref": "evidence:0eb8332c7cbbb89c5cb0f626816a31ec02864879fe044c5df5b87b916c18df73"}
 origin: runtime.payload        ref: task-ops5d:EVIDENCE:objective
   {"objective": "Cite the artifact this run observed: the evidence: ref the
    observation admitted, as this stage's external_ref."}
 origin: runtime.payload        ref: task-ops5d:EVIDENCE:predecessor_content
   {"predecessor_content": {"cited_refs": ["evidence:0eb8332c…df73"], …}}
```

Run 19's `EVIDENCE` stage had no `runtime.evidence` part and no admitted ref to
put in any part — it invented `claim:prior-art-sars19/c1`. Now the ref the run
admitted is on the prompt under its own origin, and the objective already names it.

## The reader gap, before and after

| Layer | Before (measured, note §1.5) | After |
| --- | --- | --- |
| The model writes `evidence/<id>` | admitted by the gateway | admitted by the gateway (unchanged) |
| The stored event | canonical `evidence:<id>` | canonical `evidence:<id>` (unchanged) |
| The driver's selector | **skipped it** — read the raw payload, required `evidence:` | **selects it** via `canonical_evidence_ref` |
| `EVIDENCE` node `external_ref` | empty → substrate refusal, chain stops at 6 of 9 | canonical ref, chain `COMPLETE` 9/9 |
| `OBSERVATION.cited_refs` / `CLAIM.admitted_refs` | empty | the canonical ref |

That is the regression test: `test_an_admitted_handle_is_selected_and_the_node_is_canonical`.

## Falsifiers

| Falsifier | Result |
| --- | --- |
| The `EVIDENCE` prompt carries `runtime.evidence` with the admitted ref, and a scripted run citing it is admitted with `EVIDENCE.external_ref` = the fetched artifact | **PASS** — exactly one part, `{evidence_ref, artifact_id}`, ref `task-ops5d:EVIDENCE:evidence`; `CiteTheEnvelopeModel` quotes it, both transitions are `ADMITTED` (fresh, not duplicates), the node's `external_ref` is the fetched artifact, `COMPLETE` over 9/9 |
| The reader gap: raw `evidence/<id>` is admitted **and selected**, and the node carries `evidence:<id>` | **PASS** — `COMPLETE`, node/`cited_refs`/`admitted_refs`/envelope/event all canonical; the handle string appears nowhere in the recorded content |
| The run-19 shape cannot terminate `SUCCEEDED` | **PASS** at four layers — driver refusal (`source=substrate`), handler `failed_typed`, task row `RETRYING`/`FAILED`, and the report `FAILED` with a reason, both with and without a task outcome, and again through `hermes.cli.main` |
| A stage before any admission carries no `runtime.evidence` part | **PASS** — `QUESTION`…`OBSERVATION` carry none (the admitting stage cannot see its own admission); a run with no admitted ref carries none anywhere |
| Baseline and census unchanged | **PASS** — LOOP baseline green, B4 24, census 124 / 28 (19/5/4) / 1 / 15 / 0, drain-only byte-identical |

## Two things the design did not name

1. **The empty-id guard** (`_canonical_citation`, `methodology_driver.py:514`).
   `canonical_evidence_ref("evidence/")` returns `"evidence:"` — it deliberately
   leaves the id to the gateway. The real gateway refuses an empty id (OPS-5K),
   but behind an *injected* applier such a ref would reach `evidence_envelope`,
   which raises on a ref naming no artifact: a `ValueError` inside the stage loop
   is a crash, not a refusal. The guard treats a canonical ref with no artifact id
   as *no admitted ref*, so the run stops on the substrate's own refusal. It is a
   shape check of a string; `EVIDENCE_REF` remains the only artifact-row check,
   and the "no second check" source scan still passes.
2. **One new driver import, with the pin that makes it safe.**
   `test_wiring_w3.py`'s `DRIVER_IMPORTS` admits
   `hermes.research.evidence_transitions`. The reason is an AST pin in this
   slice's file: that module imports `__future__` and `enum` and nothing else —
   no repository, no connection, no gateway — so it is vocabulary, never a second
   validation path.

Recorded, deliberately **not** changed: the methodology *plane's*
`_admitted_evidence_proposal` default still reads colon-only. Its reference/swap
driver has no capability plane and never sees a handle, so widening the default
would be an unrequested behaviour change. `test_the_plane_default_keeps_its_colon_only_reading`
pins the asymmetry as a decision rather than an accident.

## The latent second path — named, and not fixed here

The Director asked whether run 19's task row also said `SUCCEEDED`. **It did not**:
the row was `FAILED` at events 626 and 632, so for run 19 the report was the only
liar and the diagnosis stands.

Asking the question found a different path that run 19 never travelled:

**Shape.** Any stage run ends non-`SUCCEEDED` (a terminal model refusal, a tool
failure, a timeout) **after** an earlier stage admitted something. The driver
breaks and returns a `MethodologyExecution` whose `termination` names the
stopping stage — not a refusal — and the handler's only gate is the run-level
admission count (`applied == 0`, S6-B2). A non-zero count is `completed`, so the
root task reaches **`SUCCEEDED`** over a chain that stopped early, and the CLI
prints `1 succeeded`. Reproduced through the real `Controller` (citationless and
cited) and through the live CLI.

**Why it stayed.** Turning a non-`COMPLETE` execution into `failed_typed` moves
methodology tasks that succeed today into `RETRYING`/`FAILED`. That is a
task-state semantics change with its own blast radius (the W3/W4 dispatch pins
among them) and it is outside the approved OPS-5L scope, which is: surface the
ref, fix the reader, stop the false *report*. OPS-5L does make the report honest
for this shape — it reads the record and the admitted proposal kinds, so it says
`FAILED` with a reason even where the row says `SUCCEEDED`. The demonstration test
asserts only the report's verdict; pinning the row as `SUCCEEDED` would freeze the
defect as the contract.

**Recommended follow-up slice.** In `build_methodology_handler`, treat an
execution with `termination != "COMPLETE"` as `failed_typed`, carrying the
termination and the stopping stage in the reason — the same fail-closed shape
S6-B2 already uses for a zero-admission run. Needs its own design gate.

## The caveat, verbatim

> A cannot create a ref. The acceptance is that **the system never calls the
> citationless run a success**, not that the model automatically succeeds.

Run 19's `"pending"` placeholder left no admitted ref, so in that shape the
`EVIDENCE` envelope is still absent — pinned — and what changed is the verdict.

## Invariants

1. No new event kind, write path, transaction, table or port. Census
   **124 / 28 (19/5/4) / 1 / 15 / 0** — unchanged.
2. Gateway checks and substrate content rules untouched; `EVIDENCE` is still
   required; no stage state changed — a refusal is still data.
3. Drain-only byte-identical; B4 24; governed docs untouched; LOOP baseline
   unchanged (the envelope is a methodology-driver prompt part and the baseline
   corpus does not use the driver).
4. `proposable_kinds`, grants, `max_ticks` and the objectives untouched — the
   objective already named the admitted ref, so no prompt sentence was added.
5. No key material: the envelope carries two ids; the report reason is the
   task's own bounded text, and the CLI test asserts the injected key never
   reaches the file.
6. The report stays a diagnostic artifact: `terminal_reason` and the task
   outcome are never read back as authority. The journal and the task row are the
   record.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (this file + OPS-5K/5D + plane + W3 + W4 + LOOP + B4 + census + OPS-1 + OPS-10 + CLI) | `345 passed in 30.42s`, exit 0 |
| Full suite (`.venv/Scripts/python.exe -m pytest`, under the heavy-gate lock) | `5413 passed, 3 skipped in 603.47s (0:10:03)` — exit 0, 5416 collected |
| `scripts/stamp_suite_count.py` then `--check` | `Stamped docs\SUITE-COUNT.md: collected=5416`; `OK: docs\SUITE-COUNT.md collected=5416 matches the live collect` |
| `scripts/check_census.py` | `PASS - every certified figure is reproduced exactly.` (124 / 28 (19/5/4) / 1 / 15 / 0) |
| `uvx ruff check src tests scripts` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| `uvx pyright --pythonpath .venv/Scripts/python.exe --project pyrightconfig.tests.json` | `0 errors, 1 warning, 0 informations` (pre-existing `test_research_program.py:144`) |

The suite was fully green — no environmental red reproduced on this run (the
baseline-5 recorded in `docs/MERGE-LOG-CAT-1.md` did not appear).

Two annotation-only edits landed after the full run: the fixture's `-> Rig`
return (illegal on a generator fixture) and the mixed proposal/refusal model's
`-> Any`. They change no behaviour; after them the new file was re-run (`37
passed`) and so was the whole targeted set (`345 passed`), plus ruff and both
pyright projects.

## What I refused to do

- **Did not relax a rule to make the run pass.** `EVIDENCE` is still required,
  the substrate's non-empty `external_ref` rule is untouched, and the gateway's
  `EVIDENCE_REF` is still the only artifact-row dereference. The citationless run
  fails — that is the acceptance, not a pass.
- **Did not mark the `EVIDENCE` stage run `FAILED`.** A refused proposal is data
  and a clean-stopping run is `SUCCEEDED` by the runtime's contract; the report
  reads the failure instead of rewriting the runtime.
- **Did not invent a terminal.** `FAILED` + `terminal_reason` covers it; no new
  vocabulary value exists in the report.
- **Did not fix the handler.** A non-`COMPLETE` execution becoming `failed_typed`
  is a task-state change with its own blast radius; it is named, evidenced and
  recommended for its own slice (§above).
- **Did not widen the methodology plane's default selector.** The plane's
  reference/swap driver has no capability plane; its colon-only reading is
  pinned as a decision.
- **Did not add an event kind, write path, transaction, table or port,** and did
  not add an emit line to the CLI's census-guarded output. The report read is
  read-only on the run's own connection.
- **Did not put the envelope's ref anywhere the validators read.** No rationale,
  provider, URL, byte count, state rung or content rides it; it is prompt data on
  its own origin, never an admissibility claim, and a retracted ref still fails
  closed at the node write.
- **Did not pin the latent path's task row as `SUCCEEDED`.** That would freeze
  the defect as the contract; the test asserts only the report's verdict.

---

## Director addendum — runs 20 and 21: the provider ran out of credit, and the ledger did not say so

Landed at `7657772`, then two runs, both dead on the first call:

```
model call 1: tier=m provider=apinex model=deepseek-v4.1-flash PERMANENT (in 0, out 0)
terminal: NO_STAGE_RUNS
```

A direct probe of the same endpoint, same key, same User-Agent:

```
HTTP 402 {"error":{"message":"Insufficient balance. This request requires up to 266 tokens
          reserved.","type":"billing_error"}}
```

**The apinex account is out of credit.** Run 19's `PERMANENT` at call 14 was the same thing arriving
mid-run: it had balance for thirteen calls and then did not.

Nothing in this slice is implicated. The report's `NO_STAGE_RUNS` is correct — the model plane failed
before any stage could run, and after OPS-5L the report no longer invents a success.

### What this exposed anyway

`PERMANENT (in 0, out 0)` is the whole diagnostic. An operator seeing it has no way to know the account
is empty; they would reasonably start looking for a code fault. **A billing failure should say it is a
billing failure** — a 402 with `type: billing_error` is not the same class as a malformed request, and
the ledger currently collapses both into one word.

That is a small, real gap: the model ledger should carry the provider's error class (and the status
code), bounded, so the next exhausted account costs a glance rather than an investigation.

### Provider availability, measured

| provider | probe |
| --- | --- |
| `apinex` | **402 — insufficient balance** |
| `oxionai` | **502 Bad Gateway** |
| `nvidia` | 200, working |

Only `nvidia` answers, and it is the model that produced the refused flat form three times in run 17.
Run 22 needs credit on `apinex` or another capable key.

Director gates at the merged tip: 81 targeted passed, stamp `5416`, census **PASS**, B4 24.
