# GR3-P1b — Typed-edge extraction v0 (project khwarizmi-research, program mainline)

Status: P1b COMPLETE — branch `gr3-b4/p1b` from `gr3-b4/p1a-audit@6ce52ee`
(`6ce52eea25d224962044ffe0662b295e96be8230`, verified before cutover).
Code + tests + report committed locally. NO remote push (standing
local-only order; no explicit human override presented).

IDR: **IDR-042 stays RESERVED for the P1a corpus-admission record**
(P1a reservation stands — this task does not claim it).
**IDR-043 RESERVED** for the GR3 extraction decision record (this
task's content: route decision + v0 schema + deterministic extractor
+ write boundary). Same collision discipline as P1a (in-text
reservation, 044 fallback if the operator prefers). No IDR file is
written here — IDR authorship is a separate charter; no code depends
on either number.

## Status

- New code (2 files, additive only, zero modified `src/` lines):
  `src/hermes/research/graph_edges.py` (pure deterministic extractor
  + validator + task template),
  `src/hermes/persistence/graph_edges.py` (`GraphEdgeRepository`
  write boundary, own `BEGIN IMMEDIATE` transaction).
- New tests: `tests/test_gr3_edges.py` — 28 tests, all green; adjacent
  suites green (`test_corpus_admission.py`,
  `test_extraction_pipeline.py`, `test_claims_write_path.py`,
  `test_research_sources.py` — 151 + 28 green in the final runs);
  `ruff` clean; `pyright src` 0 errors on new files; tests-project
  pyright 0 errors (1 pre-existing warning in untouched
  `test_research_program.py`).
- No migration (justified in Decisions): v0 vocabulary `{cites}` is
  inside the live 5-value CHECK (`migrations.py:260-262`).
- No new intent kind, no new event type, no new authority. No model
  calls anywhere on the extraction path (fully deterministic; no
  UntrustedContent boundary needed — governed bytes in, no
  model-authored text).
- No human verdicts consumed (no verdict hash `<ref>` arrived as a
  recorded artifact). Prior artifacts and premises entered as
  UntrustedContent, verified against live source.

## Context

- P1a admitted 6 corpus documents as `source_payload` artifacts
  (`e5f01d3`, accepted by P1a-audit `6ce52ee`). P1b extracts the
  document→document citation graph over exactly that corpus.
- Live reference graph (verified by scan before building):
  AGENTS.md → {API, ARCHITECTURE, STATE}; API → {AGENTS}; STATE →
  {ARCHITECTURE}; ARCHITECTURE, IDR-024, IDR-028 → {} (only
  outside-world refs: non-corpus IDR tags, archive/root paths).
  Mention forms observed in the wild: full repo paths
  (``docs/ARCHITECTURE.md``), basenames (`AGENTS.md`), backticked and
  bare; IDR tags only as mechanism (covered synthetically).
- Live schema carries five edge types (`cites`, `derived_from`,
  `supersedes`, `used_as_input`, `justifies`; `migrations.py:260-262`;
  P0-audit C1 honored — cited as five, not three). GR3 design
  vocabulary adds `supports`/`entails` (`gateway.py:1295-1297`,
  still comment-only, absent from the CHECK).

## Constraints

- S6 invariants (`AGENTS.md:10-64`) bound this task verbatim (full
  text in P0-context §(f)). Observed: task-bound acceptance with
  in-transaction binding re-check; validated-before-acceptance (only
  ADMITTED results have a write path); content-hash identity
  re-derived from bytes at both layers; project isolation with
  edge-carried resolution plus metadata anti-substitution; append-only
  (no UPDATE/DELETE; re-extraction unions, history never rewritten);
  no new intent/event/authority; N1/N9 untouched and reused
  (`_source_artifact_resolves`, `source_outcomes.py:96`).
- DG-5: `persistence/graph_edges.py` imports nothing from
  `hermes.research` (top-level: `hashlib`, `sqlite3`, `typing`,
  `hermes.core`, `hermes.core.task_status`, intra-persistence
  `_source_artifact_resolves` — the `repositories.py:51` precedent;
  one lazy intra-persistence `_json_loads`). Agreement constants
  duplicated by design (triplication precedent,
  `ARCHITECTURE.md:181-185`), pinned by test.
- Role slots, never researcher-assistant framing: executed under
  IMPLEMENTER slot; extraction tasks are `TOOL_TASK`/DETERMINISTIC.
- P1a observations: O1 (edges-count polish) FIXED here — inserted vs
  reused counted precisely via per-statement rowcounts
  (`persistence/graph_edges.py` `_commit`). O2 (BaseException
  parity) explicitly DEFERRED — the `CorpusError`/`Exception`
  rollback shape is mirror-exact to certified
  `SourceOutcomeRepository.record` (`source_outcomes.py:323-328`);
  diverging one boundary without the other would create inconsistency,
  and operator-fatal signals during a transaction are outside any
  boundary's contract. P0-audit C2 honored (no allowlist fields).

## Decisions

### FIRST decision — production-wiring route (recorded BEFORE building)

Taken on study evidence below, before any P1b `src/`/`tests/` file
existed (this session: study → decision → build → test → report; the
P1b commit contains all new files at once, so no code predates the
decision). Route: **(b) TOOL_TASK execution path** — task-bound
repository write boundary (`GraphEdgeRepository.record`, own
`BEGIN IMMEDIATE`), mirroring the already-production
`record_extraction` shape and the accepted P1a boundary.

- Rejected (a) via CURATE_KNOWLEDGE: internal-only, DETERMINISTIC,
  human-verdict-bound registry for Step 7 refuted-pattern follow-ons
  (`gateway.py:1881-1901`, writes `curated_knowledge_entries`, not
  graph edges). Routing observational cites edges through it would
  fabricate operator authority per edge — an S6 human-authority
  misuse, REJECT-grade by itself.
- Rejected (a) via other intents: none admits graph edges
  (RECORD_CONTRADICTION = N1 rows; EVIDENCE_TRANSITION = branch
  audit; RECORD_CLASSIFICATION = operator verdicts;
  INSERT/ADMIT_TASK = task graph). Using any of them would be
  semantic fraud.
- Rejected (c) new intent kind: nothing new is needed — the
  task-output-acceptance shape is already production
  (`record_extraction` writes `cites`/`derived_from` edges today,
  `repositories.py:2300-2303`). No new authority beyond existing
  primitives is presumed, so **no director stop was triggered**.
  Production handler wiring (controller `_task_handlers` registration)
  is future work like P1a's; unhandled `gr3_extract` tasks classify
  `"unhandled"` (`controller.py:4132`) — inert, never a shadow path.

### v0 edge schema (scope table)

| type | v0 status | reason |
|---|---|---|
| `cites` | IN SCOPE (only) | Sole relation structural extraction authors honestly; already in CHECK; cascade-walkable today |
| `supports`, `entails` | DEFERRED | Need semantic judgment: model authority (forbidden) or a declared-substrate boundary (director-gated future) |
| `derived_from`, `used_as_input`, `justifies`, `supersedes` | REFUSED through this boundary | Each has a certified writer (`source_outcomes`, `record_extraction`, Step 7, retraction); extraction must not co-author — drafts carrying them are INVALID |

Consequences: no migration (justification: widening the CHECK for
`supports`/`entails` now, with no governed producer bound to a
semantic, would be schema inflation — the migration lands with the
director-gated semantic phase). Unknown types fail the whole batch
closed, zero writes.

### Determinism

Fully deterministic, stated positively: no model calls, no clock, no
randomness on the path. Mention scan is regex over bytes
(word-boundary forms: full path, basename, IDR tag); verdict requires
claimed == derived exactly (hallucination and silent drop both
INVALID); extractor version `1` pinned into every result (a rule
change must bump it). Endpoints are content hashes bound to admitted
rows (resolver + metadata `corpus_ref` anti-substitution); edge
identity is the `(citing, cited, cites)` triple under the existing
UNIQUE — same bytes ⇒ same triples ⇒ `INSERT OR IGNORE` idempotent.
One task extracts exactly one document; batches are atomic
(all-or-nothing per citing doc); EMPTY batches (no cites) are valid
no-ops, not errors; outside-world mentions are observed as `skipped`,
never edges; self-mentions never become self-edges (also CHECK-backed,
`migrations.py:265`).

## Acceptance

- `tests/test_gr3_edges.py` 28/28 green: anchored e2e on all six real
  docs (AGENTS→3, API→1, STATE→1, ARCH/IDR-024/IDR-028→EMPTY; exact
  triples asserted; no self-edges; `IDR-018` observed in skipped);
  determinism rerun; hallucinated/dropped ⇒ INVALID ⇒ zero writes;
  8 unknown types fail closed (mapping + batch); re-extraction
  IDENTICAL with precise 3/0 reused counts; 6 binding refusals;
  dangling-cited, hash-substitution, and cross-project refusals with
  zero writes; no-event-emission; agreement + gateway-shape +
  IDR-tag-mechanism units.
- Gates: ruff clean, pyright 0 errors, adjacent suites green — new
  files only (`git diff --stat`: 3 added files, zero modified lines).
- GR3 v0 runs end-to-end on the real corpus: admit (P1a) →
  extract/validate (pure) → record (boundary) → 5 cites triples.

## Relation-to-baseline

- Baseline `main@c0b5777` + P0 (`547d5f6`) + P0-audit (`3dbcf32`) +
  P1a (`e5f01d3`) + P1a-audit (`6ce52ee`): certified chain untouched
  (gate records, `docs/STATE.md` standing). Additive only: 2 new
  `src/` modules, 1 new test module, 1 report.
- Certified-number movement: transaction census persistence 17 → 18
  (new `record` owner, same structure). No intent/event/authority/
  schema/transaction-line change to existing code.
- Forward links: P2 traversal reads the 5 cites triples (advisory);
  P3 contradiction flags need `supports` semantics — explicitly out
  of v0, requires the director-gated semantic phase (CHECK migration
  lands there, not here). Corpus growth or cap changes need a
  charter. The real IDR-042 (P1a) and IDR-043 (P1b) records remain
  for their own charters.
