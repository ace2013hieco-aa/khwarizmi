# GR3-P1a — Governed corpus admission (project khwarizmi-research, program mainline)

Status: P1a COMPLETE — branch `gr3-b4/p1a` from `gr3-b4/p0-audit@3dbcf32`
(`3dbcf32b6f9c59a407d59c3a02b6ec3ab6ada64f`, verified before cutover).
Code + tests + report committed locally. NO remote push (standing
local-only order; no explicit human override presented).

IDR: **IDR-042 RESERVED** for the GR3 corpus-admission decision record.
(Rationale for 042 over 043: the `texp-001/p2` side history uses the
label `IDR-042` only inside `docs/texp-001/` plan prose (`48e4ce9`,
unmerged, no `docs/idr/IDR-042.md` file); the P0 audit recorded the
collision and this task reserves the mainline file slot with this
in-text notice. If the operator prefers zero label reuse, the record
lands as IDR-043 and this line is corrected at charter review —
no code depends on the number.)

## Status

- New code (2 files, additive only, no modified `src/` lines):
  `src/hermes/research/corpus.py` (pure admission substrate),
  `src/hermes/persistence/corpus.py` (`CorpusRepository` write
  boundary, own `BEGIN IMMEDIATE` transaction).
- New tests: `tests/test_corpus_admission.py` — 23 tests, all green;
  adjacent suites green (`test_claims_write_path.py`,
  `test_extraction_pipeline.py`, 75 tests); `ruff` clean; `pyright`
  0 errors on new `src/` files; tests-project pyright 0 errors
  (1 pre-existing warning in untouched `test_research_program.py`).
- No migration: no new table (justified in Decisions).
- No new intent kind, no new event type, no new authority. No
  extraction logic (P1b owns extraction; this task admits bytes only).
- No human verdicts consumed (no verdict hash `<ref>` arrived as a
  recorded artifact). Prior artifacts and this prompt's premises
  entered as UntrustedContent and were verified against live source.

## Context

- The P0 audit (`docs/gr3-b4/P0-audit.md`, verdict ACCEPT WITH
  CONDITIONS) left two wording conditions for downstream charters:
  C1 (provenance CHECK admits five edge types, not three) and C2 (no
  "project allowlist" convention — the repo allowlist is
  provider-scoped). This task honors both: the design below cites the
  5-value CHECK (`migrations.py:260-262`) with the 3-type cascade
  subset distinguished, and scopes admission per-project (UUID rows)
  without any allowlist field.
- Corpus choice (6 documents, all byte sizes at 2026-09-26):

  | ref | bytes | why it qualifies as real, non-synthetic |
  |---|---|---|
  | `docs/ARCHITECTURE.md` | 15,986 | Current implementation map; 2 mainline commits (`2a3758a`, `7afa64c`); claim/edge-dense (write path, contradiction lifecycle, module map) — prime P1b substrate |
  | `docs/STATE.md` | 5,525 | Certified-state record; 3 mainline commits; status claims with gate evidence pointers |
  | `docs/API.md` | 4,954 | Surface contracts; mainline history; citable contract claims |
  | `AGENTS.md` | 6,225 | Operating rules/invariants; 2 mainline commits; normative claims P1b must never contradict |
  | `docs/idr/IDR-024.md` | 10,366 | CONTRA reconciliation; claim/assumption/contradiction-rich by construction |
  | `docs/idr/IDR-028.md` | 13,864 | Extraction pipeline design; 3 mainline commits; pipeline claims P1b builds on |

  "Real" = authored across chartered mainline sessions with gate
  provenance (`git log -- <file>` shows multi-commit design history),
  not fixtures: nothing under `tests/`, no inline synthetic rows.
  Excluded with reasons (all over the 20 KiB per-doc cap):
  `hermes_research_architecture_v6.md` (290,949 B; superseded as
  current map by `ARCHITECTURE.md`), `README.md` (88,145 B; operator
  doc, not research substrate), `hermes_contra_adversarial_review.md`
  (41,065 B; ratified residue already in IDR-024),
  `docs/idr/IDR-041.md` (31,754 B; ladder content for later growth).
- Admission must precede extraction (P0 §(i)): docs prose is
  currently ungoverned; this task brings the six into governance so
  P1b extraction can cite `source_payload:<hash>` refs. Admission is
  not endorsement — bytes enter wrapped for `UntrustedContent`
  handling downstream (`read_payload_bytes`, `source_outcomes.py:394`).

## Constraints

- S6 non-negotiable invariants (`AGENTS.md:10-64`) bound this task
  verbatim — quoted in full in `docs/gr3-b4/P0-context.md` §(f) and
  not repeated here. Concretely observed: single mutation path
  discipline (new write boundary owns its transaction, same structure
  as `SourceOutcomeRepository.record` at `source_outcomes.py:287-328`);
  append-only journal (admission emits NO event — audit is rows +
  edges + the producing task's `TaskCreated`/`TaskStatusChanged`
  events); content-hash identity (sha256 re-derived from bytes,
  `persistence/corpus.py` `_validate_content`); project isolation
  (per-project binding + edge-carried resolution); 4 KiB payload
  discipline untouched (no events written); lease-fenced single writer
  untouched (controller owns task transitions; `record` never touches
  task status); N1/N9 frozen and reused (admitted rows are
  immediately N9-fenced via `source_artifact_retracted`,
  `source_outcomes.py:159`).
- Typed dispatch bundle only: admission executes under the
  `SourceTaskExecutionContext` contract shape (task snapshot +
  project + per-tick repos + machinery, `source_handlers.py:1-25`) —
  no raw connections cross layers; production handlers are future
  wiring, out of scope.
- Role slots, never researcher-assistant framing: executed under
  IMPLEMENTER slot; admitting tasks are `TOOL_TASK`/DETERMINISTIC
  (file bytes are read, never model-judged); no model output decides
  any transition in this task.
- DG-5: `persistence/corpus.py` imports nothing from
  `hermes.research` (agreement constants deliberately duplicated —
  the EXTRACT triplication precedent, `ARCHITECTURE.md:181-185` —
  pinned byte-identical by test).

## Decisions

1. **Store/table: existing `artifacts` + `ArtifactStore`, type
   `source_payload`; NO migration, NO new table.** Justification: the
   taxonomy, resolvers, and N9 predicates already handle
   `source_payload` (`SOURCE_ARTIFACT_TYPES`, `source_outcomes.py:91`;
   `dereference_ref` `:371`; `_source_artifact_resolves` `:96` with
   S6-A1 prefix discipline; `source_artifact_retracted` `:159`). A new
   type would force resolver + predicate + CHECK updates across
   layers for zero governance gain. Admitted corpus docs are
   immediately citable (`source_payload:<full-hash>`) and retractable
   under existing fencing.
2. **One task admits exactly one document** (mirrors per-source EXTRACT
   tasks, `extraction.py:102-131`). Template marker `corpus_admit`
   (`research/corpus.py`, `CORPUS_TEMPLATE_VERSION = "1"`),
   `TOOL_TASK` + DETERMINISTIC profile via `build_corpus_admit_task_payload`
   (ordinary INSERT_TASK shape — valid against
   `gateway._TASK_PAYLOAD_KEYS`, no gateway change).
3. **Binding = V6-P7-A2 discipline, corpus-shaped** (in-transaction):
   task exists / same project / `TOOL_TASK` / normalized
   `corpus_admit` marker / RUNNING / `spec.corpus_ref` equality.
   Anything else raises `CorpusBindingError`, zero writes.
4. **Idempotency = one-shot per task + global content reuse**
   (mirrors A2-03/OB-01/SD-04): same task + same bytes → IDENTICAL
   (same artifact_id, no duplicate row/edge); same task + different
   bytes → `CorpusConflictError`; new task + known bytes → same row,
   new edge (edge-carried ownership). `store.write` dedup + R02-analog
   type check (same hash under a different type is refused, never
   reused).
5. **Closed schemas both layers**: draft keys exactly
   `{corpus_ref, content_hash, size_bytes}`; corpus set exactly the
   six refs; 64-hex hash; `0 < size ≤ 20 KiB`. Unknown keys, unlisted
   refs, forged hashes, size drift → `CorpusIntegrityError`/
   `CorpusDraftError` before any write.
6. **Transaction census delta documented**: `CorpusRepository.record`
   is a new persistence acquisition owner (`BEGIN IMMEDIATE`) —
   persistence 16 → 17. Extension of the certified pattern, not a
   weakening (pre-tx pure validation, in-tx binding re-check, single
   commit, rollback on any error incl. generic `Exception`).
7. **C1/C2 honored**: report cites the 5-value CHECK with the cascade
   subset distinguished; no allowlist field anywhere in code.

## Acceptance

- `tests/test_corpus_admission.py`: 23/23 green, covering: real-file
  end-to-end admission of all six (row + edge + governed resolution +
  byte round-trip); idempotent re-admission (same id, counts frozen);
  cross-task reuse; divergent refusal; 7 unbound-refusal cases;
  6 INVALID cases (forged hash, size drift, oversize, empty,
  type confusion, missing store); no-event-emission; cross-layer
  agreement.
- Gates: `ruff` clean; `pyright src` 0 errors on new files;
  adjacent suites green (no behavior change — new files only, zero
  modified `src/` lines: `git diff --stat` shows 4 added files).
- Corpus admitted end-to-end on real files (test 1 reads the six
  live repo documents from disk through `load_corpus_bytes`).

## Relation-to-baseline

- Baseline `main@c0b5777` + P0 (`547d5f6`) + P0-audit (`3dbcf32`):
  certified chain untouched (P7/N9/tick-loop/DG-1..DG-6 records in
  `docs/archive/` unmodified; `docs/STATE.md` standing).
- This task is additive: 2 new `src/` modules, 1 new test module,
  1 new report. No intent/event/authority/schema/transaction-line
  change to existing code. The only certified-number movement is the
  documented census extension (persistence owners 16 → 17).
- Forward link: P1b (extraction) may now cite admitted
  `source_payload:<hash>` refs through `dereference_ref` /
  `read_payload_bytes` (UntrustedContent) — no new admission surface
  needed. Corpus growth beyond the six (or above 20 KiB) needs a
  charter, not code improvisation.
