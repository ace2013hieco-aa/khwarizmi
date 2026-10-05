# GR3-P2-b4fixtures — B4 reference generation (project khwarizmi-research, program mainline)

Status: P2-b4fixtures **IMPLEMENTER-DRAFT — no director verdict issued; acceptance rests with audit** — branch `gr3-b4/p2`, cut from
`gr3-b4/p1b-audit2` = `1a051e437c2a888d6a0f468a7f8b4e43d765f84d`
(verified with `git rev-parse` before cutover) and additionally carrying
an additive merge of the TEXP twin at its pin (`texp-001/s6-audit` =
`a927c7a7900eb63e4b6e781637ac0dc24d7cca79`). Code + tests + fixtures +
report committed locally. **NO remote push** (standing local-only order;
no explicit human override presented).

IDR: **IDR-043 is recorded in text here as an implementer-side provisional record** (§Decisions → *IDR-043 decision record*, following the implementer precedent at `P1a-admission.md:14`; no charter has issued or ratified IDR-043 and no `docs/idr/IDR-043.md` file is written — the number is VOID until director ratification; this mirrors P2-audit §5.5). **IDR-042 stays RESERVED** for the P1a corpus-admission record. No code depends on either number.

Human authority: **no human verdict was consumed as authority.** No
`HumanDecisionReceived` journal row (or any other recorded verdict
artifact) arrived for this task. An operator-side route preference was
received in-session; because it is not a recorded artifact it binds
nothing, and every route below is recorded on its own stated merits as
an IMPLEMENTER decision.

## Status

- New code (additive): `src/hermes/research/ref_graphs.py` — the pure
  B4 reference-graph builder/packager/reader.
- Widened governance (two named constants + one union, in both layers):
  `CORPUS_B4_COHORT_REFS` and `GOVERNED_CORPUS_REFS` in
  `src/hermes/research/corpus.py` and `src/hermes/persistence/corpus.py`.
  **`CORPUS_REFS` itself is byte-unchanged** (`git diff` shows no edit
  to the six-member literal in either layer).
- New fixtures: `docs/gr3-b4/b4-fixtures/` — 4 content-addressed
  reference graphs (+ `README.md` index).
- New tests: `tests/test_b4_ref_graphs.py` (24 tests);
  `experiments/texp-001/test_b4_source.py` (12 tests, twin side).
- TEXP twin wiring: **additive only** — `experiments/texp-001/fixtures.py`
  gains a clearly-marked `B4 SOURCE` section (+181 lines, **0 removed
  lines**; the module `__all__` is deliberately untouched). Plus the
  additive twin merge (twin files imported verbatim at `a927c7a`; zero
  shared-file edits between the lineages).
- No migration, no new table, no new intent kind, no new event type, no
  new authority, no new persistence transaction owner (census stays 18).
- No model calls anywhere: the whole path is deterministic (bytes in ⇒
  edges out). Governed bytes and the in-session operator preference
  entered as `UntrustedContent` and were re-verified against live
  source.

## Context

- **What B4 is.** The TEXP-001 twin's benchmark generator states its own
  placeholder plainly: *"STIPULATED reference behavior throughout (no
  real graph exists — B4)"* and `StrataParams` are *"placeholders per
  spec (real scale pending B4)"* (`experiments/texp-001/generator.py` at
  `a927c7a`). B4 is the phase that supplies real typed-edge graphs from
  GR3 v0 output so the twin can consume real structure instead of an
  assumption.
- **The governed corpus was six documents.** P1a admitted six
  (`CORPUS_REFS`, IDR-042): `AGENTS.md`, `docs/API.md`,
  `docs/ARCHITECTURE.md`, `docs/STATE.md`, `docs/idr/IDR-024.md`,
  `docs/idr/IDR-028.md`. P1b's extractor is `cites`-only, so over those
  six the certified graph is **5 edges** (AGENTS→3, API→1, STATE→1;
  the two IDRs are empty no-ops). Five edges cannot replace an
  assumption; an expanded real sample was required.
- **Expanded sample — selection rule (stated, not hand-picked).** The
  B4 reference cohort is *exactly* the set of real documents the P1a six
  **directly cite** and that fit the existing per-document cap:

  | added document | bytes (governed identity; CRLF-normalized) | directly cited by (P1a member) |
  |---|---|---|
  | `docs/idr/IDR-018.md` | 15,096 (blob/LF) · 15,171 CRLF | `docs/ARCHITECTURE.md` |
  | `docs/idr/IDR-023.md` | 6,841 (blob/LF) · 6,898 CRLF | `docs/STATE.md`, `docs/idr/IDR-024.md` |
  | `docs/idr/IDR-025.md` | 6,729 (blob/LF) · 6,778 CRLF | `docs/idr/IDR-028.md` |
  | `docs/idr/IDR-026.md` | 16,754 (blob/LF) · 16,898 CRLF | `docs/ARCHITECTURE.md`, `docs/idr/IDR-028.md` |
  | `docs/idr/IDR-027.md` | 9,797 (blob/LF) · 9,870 CRLF | `docs/idr/IDR-028.md` |
  | `docs/idr/IDR-036.md` | 13,057 (blob/LF) · 13,256 CRLF | `docs/ARCHITECTURE.md` |

  *Sizes above are the governed identity bytes (CRLF-normalized to LF, which equals the git blob) — `load_corpus_bytes` now normalizes CRLF→LF (C1 fix), so the cap check uses LF sizes, and fixtures store those LF sizes/hashes. The previous draft mistakenly described the table as checkout-disk bytes; under `core.autocrlf=mixed` the CRLF checkout would inflate IDR files by +CRLF. The ≤20 KiB cap holds under both.*

  Every entry is a real mainline-authored document with multi-commit
  design history, is ≤ `CORPUS_MAX_BYTES` (20 KiB — no cap change), and
  is refused by the old allowlist today, so each one *enters governance
  first* (§Decisions D1). The rule is re-derived from the P1a six by
  test (`test_selection_rule_rederives_from_the_p1a_six`), so the cohort
  is a property of the corpus, not a preference.
- **Result.** The governed corpus is 12 documents; the `cites` graph
  over it is **19 edges** (vs 5). The expansion also converts previously
  *observed* outside-world mentions into real edges: `IDR-018`,
  `IDR-026` and `IDR-036` were in P1b's `skipped` set and are now
  governed members with real edges.
- **The twin handoff.** The TEXP twin lives only on the `texp-001/*`
  lineage; both lineages fork from `main@c0b5777` with **zero
  shared-file edits** (verified with `git diff --name-status` — no `M`
  entries). `gr3-b4/p2` therefore carries an explicit additive merge of
  `texp-001/s6-audit@a927c7a` (commit `18ac780`) so the B4 fixtures can
  be wired into `experiments/texp-001/fixtures.py` and the twin's own
  suite can be run here.
- **Twin conventions honoured.** Every fixture declares
  `namespace: "texp-001-twin"`, `consumption: "SIMULATED"`,
  `authority: "ADVISORY"`; the twin read path carries a
  `texp001:b4/<fixture_id>` ref (the twin's `texp001:` namespace
  convention, cf. the twin's F5 isolation fixture) and **refuses** a
  fixture that does not declare `SIMULATED` — a twin artifact is never
  presented as production.

## Constraints

- **S6 non-negotiable invariants — verbatim, `AGENTS.md:10-64`**
  (12 bullets; the owning certification slices P6/N9/P7/tick-loop are
  untouched):

  > ## Non-negotiable architectural invariants
  >
  > These are certified and enforced in code. Do not weaken them;
  > changes near them need a design gate plus the owning certification
  > slice re-run (P6/N9/P7/tick-loop records live in `docs/archive/`).
  >
  > - Determinism owns control. No LLM/model output may decide a
  >   transition; models are routed behind ports, never authorities
  >   (`src/hermes/research/evaluation.py`, deterministic libraries only).
  > - Single mutation path: `apply_intent`
  >   (`src/hermes/research/gateway.py:3961`). Never write durable state
  >   around it — no direct repository writes from orchestration, no
  >   direct SQL mutation outside certified transaction boundaries:
  >   25 acquisition owners across persistence (16), gateway (5), and
  >   Controller (4), plus one rollback-only participant (DG-4/DG-6;
  >   details in `docs/ARCHITECTURE.md` §3.10). Most boundaries own a
  >   `BEGIN IMMEDIATE` transaction; a few intentional plain-`BEGIN`
  >   cases exist (repository creates, event-retry path, migrations,
  >   Controller floor/ladder/human-gate paths).
  > - Append-only journal (`src/hermes/core/events.py`; writer
  >   `src/hermes/persistence/repositories.py`). No DELETE exists in
  >   `src/`; supersession/invalidation are new rows/events, history is
  >   never rewritten.
  > - Replay determinism: provider bytes replay identically through
  >   `RecordedTransport` (`src/hermes/tools/providers/replay.py`);
  >   replay proves byte/evidence determinism only — never scientific
  >   validity, and never admissibility of retracted sources (N9).
  > - Human-authority fail-closed boundary: `CONTRADICTION_RESOLUTION`,
  >   `RECORD_CLASSIFICATION`, `RETRACT_SOURCE` and 6 more kinds are
  >   `internal_only` (`src/hermes/core/intents.py:144`); LLM-proposable
  >   kinds are listed at `intents.py:124`. A missing/unbound
  >   `HumanDecisionReceived` journal row refuses the command
  >   (`gateway.py`, `PROPOSAL`).
  > - Bounded payload discipline (4 KiB): event payloads are size-checked
  >   (`src/hermes/persistence/event_validation.py`); oversized verdicts
  >   refuse with `RATIONALE` before any write.
  > - Project isolation: every resolver, detector row, validator, and
  >   retraction predicate is project-scoped; cross-project citation
  >   fails closed (`EVIDENCE_DOES_NOT_RESOLVE`).
  > - Prohibited-claims discipline: never claim scientific
  >   reproducibility, never present replay as validity, never present a
  >   digest/derived view as authority.
  > - Archive-not-delete; head-only supersession (a second supersede
  >   link on one row is refused); refusal-as-data (rejections return
  >   data with codes from `gateway.py:93-109`, never silent success).
  > - Lease-fenced single writer: controller surfaces acquire the
  >   scheduler lock (`controller.py:2336`); contention returns `LOCK`;
  >   mid-tick loss aborts to `lock_lost` with rollback.
  > - Content-hash identity: `fc_`/`cx_`/`cres_`/`fx_`/`retract_` IDs are
  >   recomputed, never trusted (`contradictions.py:75`,
  >   N1 pair rule `:106`, N9 predicate
  >   `source_outcomes.py:159`).
  > - N1 contradiction semantics and N9 retraction fencing are frozen:
  >   same project/program/hypothesis, different failure class, neither
  >   party invalidated, non-empty currently-valid evidence overlap.

  **Phrasing correction (P1b-audit2 note 2).** Only the text above is
  the invariant section, and only it is called "verbatim". The
  boundary discipline this task reuses — *task-bound acceptance with
  in-transaction binding re-check* — is EXTRACT/P1a boundary discipline
  (IDR-026 Decision 2.1; `persistence/corpus.py` `record`), CITED here
  as reused certified structure, never relabelled "verbatim AGENTS.md".
  Observed concretely: content-hash identity re-derived from bytes
  (fixtures record sha256 per source; the boundary re-derives it);
  append-only (admission writes rows + `derived_from` edges, no
  UPDATE/DELETE); project isolation (admission is project-scoped);
  refusal-as-data (drafts/counts/digests refuse rather than silently
  drop); determinism owns control (no model output anywhere on the
  path); prohibited-claims (fixtures are explicitly `ADVISORY`).
- **DG-5.** `src/hermes/research/ref_graphs.py` imports only
  `hermes.research.*` (`corpus`, `graph_edges`, `programs`) — no
  persistence import, no `sqlite3`, no transaction (pinned by
  `test_build_path_holds_no_write_surface`). The widened
  `persistence/corpus.py` still imports nothing from `hermes.research`.
- **No new intent / event / authority.** No intent kind, no event type,
  no allowlist, no role, no human-verdict surface is added. The cohort
  enters through the *existing* `CorpusRepository.record` boundary
  (already-certified template `corpus_admit`, artifact type
  `source_payload`, `derived_from` edge) and extraction reuses the
  certified pure extractor/validator. Nothing is inserted outside
  `apply_intent`.
- **Role slots (implementer taxonomy, not a director-issued assignment).** Implemented as an implementer-authored task under the workflow's own ROADMAP slot taxonomy (P0, implementer-authored) — no director assignment was issued for this turn. The B4 build is
  a `TOOL_TASK`/DETERMINISTIC shape (bytes are read and scanned, never
  model-judged). No researcher-assistant framing is used.
- **Derive-on-read exclusion NAMED** — see §Decisions D2 (P1b-audit2
  note 1).
- **TEXP line is additive-only.** `experiments/texp-001/fixtures.py`:
  181 insertions, 0 deletions; `__all__` untouched so no existing line
  is edited; the synthetic F1–F7 fixtures keep byte-identical behaviour;
  the new twin test is a new file. Proven by the experiments suite:
  **97 passed** (85 pre-existing, all still green) and by the ruff delta
  on `fixtures.py` (6 pre-existing findings before and after — 0 new).

## Decisions

### IDR-043 decision record (written in-text)

#### D1 — Corpus-growth route: a NAMED cohort, admitted through the existing boundary

The governed allowlist is widened by exactly the expanded sample, as a
*separate named cohort*, while the P1a constant stays frozen:

- `CORPUS_B4_COHORT_REFS` — the six documents above (new, both layers);
- `GOVERNED_CORPUS_REFS = CORPUS_REFS | CORPUS_B4_COHORT_REFS` — the
  union the loader and the write boundary actually enforce (new, both
  layers, agreement-pinned by test);
- **`CORPUS_REFS` is byte-unchanged** — the P1a cohort remains the six.

Rejected alternatives, with reasons:

- **(a) Grow `CORPUS_REFS` itself to the twelve.** Rejected: P1b's
  *certified* anchored test (`tests/test_gr3_edges.py`) derives its
  corpus from `CORPUS_REFS` and pins the exact triples and `n == 5`
  (`ARCH`/`IDR-024`/`IDR-028` ⇒ EMPTY). Growing that constant would
  re-baseline a certified test — moving a certified artifact to buy
  nothing the union does not already buy. The cohort form keeps every
  P1a/P1b expectation literally true.
- **(b) A second mirror admission boundary for a B4-only corpus.**
  Rejected: it duplicates authority-facing machinery (a second
  admission surface and a new persistence transaction owner) to avoid
  an edit that is strictly smaller. The repo's discipline is one
  certified mutation structure per substrate; reusing
  `CorpusRepository.record` is the smaller, safer move.
- **(c) Do not expand at all.** Rejected: it leaves B4's whole purpose
  unaddressed (five edges replace no assumption), and the brief
  explicitly contemplates new documents entering, gated on governed
  admission.

The new documents therefore enter **only** through
`CorpusRepository.record` (one `corpus_admit` task per document, RUNNING,
`spec.corpus_ref` equality, hash re-derived from bytes); an unlisted ref
still refuses at *both* layers (`test_unlisted_ref_refuses_at_both_layers`,
including a hand-built task row that bypasses the template). No
migration, no new table, no new event, no new transaction owner.

#### D2 — Derive-on-read is EXCLUDED, and named (P1b-audit2 note 1)

A third option exists for obtaining these graphs and is excluded
explicitly rather than by omission:

- **Derive-on-read**: compute the `cites` graph at query time from the
  admitted corpus documents and never persist or package it.

Excluded for three reasons. (i) *It would defeat the deliverable*: a B4
fixture must be a stable, content-addressed artifact with a recorded
source set and extraction version, so a consumer can cite exactly which
bytes produced which graph — a value recomputed per read has no identity
to record and no drift attribution. (ii) *It re-opens the audited
question*: P1b-audit2 already rejected derive-on-read for the persisted
edge graph because P2 traversal and the §14 cascade need a governed,
append-only, cascade-walkable substrate; re-deriving inside B4 would
reintroduce exactly that unreviewed shape. (iii) *It hides drift*: an
extractor rule change (`GR3_EXTRACTOR_VERSION`) must be attributable;
a packaged fixture keeps the version it was built with, whereas a live
derivation silently changes with the code.

The same reasoning is why the fixtures are *packaged files* rather than
a runtime call into `ref_graphs`: the packaging step is where the source
set, the hashes, and the extractor version are frozen together.

#### D3 — Fixture format: content-addressed, closed, self-describing

Each fixture is canonical JSON (`programs.canonical_json` + one trailing
newline), stored at `docs/gr3-b4/b4-fixtures/<sha256>.json` where the
file name **is** the sha256 of the file's own bytes. The body records
`fixture_id`, `rationale`, `fixture_schema_version`,
`extraction_version` (= `GR3_EXTRACTOR_VERSION` = `"1"`), the
twin-namespace markers, `source_set` (each ref with its own content hash
and size), `edges`, `skipped`, and `counts`. Rationale: a fixture is
then verifiable by regeneration (and by name), needs no signature to
detect tampering, and carries its own provenance. The body is ASCII-only
and LF-only so the artifact cannot be mangled by a tooling encoding
choice, and `docs/gr3-b4/b4-fixtures/.gitattributes` pins `*.json` as
**non-text** (`-text`): this repo's checkout configuration would otherwise risk normalising LF→CRLF on checkout and silently invalidating
every fixture (the name would no longer hash to the bytes). With
`*.json -text`, `git ls-files --eol` reports `i/lf w/lf attr/-text` for
fixtures; the governed corpus sources are additionally pinned `eol=lf`
in top-level `.gitattributes` and `load_corpus_bytes` normalizes any
residual CRLF→LF (C1 fix), so fixture regeneration is EOL-stable on every
platform — the binding survives a fresh clone (before C1, only the
fixture files themselves were stable; regenerating from a fresh CRLF
checkout would drift, because the 12 sources were not pinned — see
P2-audit F1). The strict
reader (`parse_reference_graph`) is closed: unknown
keys, count drift, digest mismatch, non-governed source, foreign
namespace, non-`SIMULATED` consumption, and self-edges all refuse.

#### D4 — Count and strata: four fixtures, deliberately not exhaustive

Four strata of the same real corpus — the P1a baseline (`b4-c1`), the
full expanded cohort (`b4-c2`), the IDR design chain (`b4-c3`), and the
non-IDR authority spine (`b4-c4`). Enough to replace the twin's
assumption and to let a consumer separate "the certified baseline" from
"the expanded reference" and from two structurally distinct sub-strata;
no attempt at exhaustiveness; the only standing bounds for this workflow are local-only commits and S6/DG-5 (ROADMAP §Bounds) — no charter stated a B4 exhaustiveness bound, so this scope choice is recorded as an implementer decision under that bound (cf. P2-audit §5.4), not as a director-conferred bound.

#### D5 — Twin wiring: additive, read-only, absent-safe

The `B4 SOURCE` section in `experiments/texp-001/fixtures.py` reads
fixtures, re-verifies the name/digest binding, enforces the markers, and
returns a frozen data-only graph; it imports nothing from production,
runs no arm/kernel/energy/validator, and writes nothing. It is appended
after the existing `__all__` (which is left byte-identical, so the diff
is pure insertion); callers import the B4 names explicitly. When the
mainline handoff is absent (a twin-only branch) the section reports
unavailable and the twin test module skips rather than failing the
twin's suite — so a later twin branch is not broken by a missing
cross-namespace artifact. **Honest limit recorded:** the only edge type
is `cites`, which is not a member of the twin's 14-class
`EDGE_ALPHABET`, so B4 graphs are reference *structure* for the twin
today — not yet admissible sequences and not runnable benchmark
instances (asserted in `test_b4_edge_type_is_not_a_twin_alphabet_member`).

#### D6 — IDR numbering (provisional — VOID until ratified)

`IDR-043` is recorded in text here as an implementer-side provisional claim (extraction + B4 packaging record), following the implementer precedent at `P1a-admission.md:14`; no charter has issued IDR-043, IDR file authorship remains separately chartered per ROADMAP §Notes, and this claim is VOID until director ratification (P2-audit §5.5). `IDR-042` remains reserved for P1a. No `docs/idr/` file is written by this task; the collision discipline of P1a/P1b is unchanged.

## Acceptance

- `tests/test_b4_ref_graphs.py` — **24/24 green**: cohort shape,
  disjointness, agreement across layers; the selection rule re-derived
  from the P1a six; real end-to-end governed admission of the six new
  documents (rows + `derived_from` edges + `source_payload:<hash>`
  resolution + byte round-trip) with idempotent re-admission and no new
  event type; two-layer refusal of an unlisted ref; fixture
  regeneration reproducing the committed file names and bytes exactly;
  build determinism; extraction version + markers; source-set hashes
  re-derived from disk; the baseline fixture reproducing the certified
  P1b triples; the expanded fixture being the governed graph; strict
  reader round-trip; seven fail-closed reader/builder refusals; the
  no-write-surface check.
- `experiments/texp-001/test_b4_source.py` — **12/12 green** (the
  demonstrated texp-001-side read): the projected handful, the baseline
  read equalling the certified triples, the expanded cohort read, the
  file-name ⇔ digest binding, an all-fixtures verified read, the
  data-only return, the alphabet-limitation assertion, and five
  fail-closed refusals (unknown id, edited bytes, non-`SIMULATED`,
  foreign namespace, unknown key + self-edge).
- Whole-repo suite: **2176 passed** (baseline before this task: 2152).
  Experiments suite: **97 passed** (baseline: 85) — the pre-existing 85
  are unchanged and green, which is the additive-only proof.
  Certified P1a/P1b suites (`test_corpus_admission.py`,
  `test_gr3_edges.py`): **51 passed**, files byte-unchanged.
- Gates: `ruff` clean on every new/changed file; on the TEXP file
  `experiments/texp-001/fixtures.py` the finding count is **6 before and
  6 after** (0 new; the 6 are pre-existing at the twin pin `a927c7a`,
  verified by linting the pinned blob through stdin). `pyright` (src):
  **0 errors**; `pyright` (src+tests): **0 errors**, 1 pre-existing
  warning in the untouched `tests/test_research_program.py`.
- Fixtures produced (name = sha256 of the file's bytes; the blobs are
  LF and the frozen blob hash equals the file name, verified with
  `git cat-file -p <ref>:<path>` piped to sha256):

  | `fixture_id` | sources | edges | digest |
  |---|---|---|---|
  | `b4-c1-p1a-baseline` | 6 | 5 | `749bf19206efaedeafa49636c3759b9c418900eebfcd037295cf952f936137e5` |
  | `b4-c2-expanded-cohort` | 12 | 19 | `82ea9ec853b0242a963dbd5a071e9436de2b5d20e5eeee2cd36788fa96cc524b` |
  | `b4-c3-idr-design-chain` | 8 | 10 | `eef419463e5201c415615b1a8e33b03f237283a43b40af2b5a6709b3b63b664e` |
  | `b4-c4-authority-spine` | 4 | 5 | `2249067cdaf6b8d38d3d16995d83decb4ddd0a5565635624fe3301a87a1d2c16` |

  *Digests for b4-c1/c2/c4 corrected at p2-fix to the CRLF-normalized (LF) governed identity: before C1 the fixtures recorded CRLF-inflated bytes for AGENTS.md/ARCHITECTURE.md/STATE.md (mixed checkout); after the loader normalization + `eol=lf` pin, all 12 sources are LF and regeneration is EOL-stable (P2-audit F1 closed). b4-c3 is unchanged (IDR-only, already LF).*

## Relation-to-baseline

- Baseline chain `main@c0b5777` + P0 (`547d5f6`) + P0-audit (`3dbcf32`)
  + P1a (`e5f01d3`) + P1a-audit (`6ce52ee`) + P1b (`13565f8`) +
  P1b-audit2 (`1a051e4`): **untouched**. No gate record, no
  `docs/STATE.md` entry, and no P1a/P1b test file is modified
  (`test_corpus_admission.py` and `test_gr3_edges.py` are byte-identical
  and green).
- Additive inventory on `gr3-b4/p2`: 1 new `src/` module
  (`research/ref_graphs.py`), 1 new test module, 1 new twin test module,
  4 new fixture files + 1 index, this report; plus two small edits
  adding the named cohort constants to the two corpus layers
  (+18/−3 and +41/−10), and 181 purely-inserted lines in the twin's
  `fixtures.py`; plus the additive twin merge (`18ac780`, twin files
  imported verbatim from `a927c7a`).
- **Certified-number movement: none.** Persistence acquisition owners
  stay at 18 (no new boundary); no migration; no new intent kind, event
  type, table, or authority. The only allowlist change is membership of
  the governed corpus (6 → 12), effected by a new named constant so the
  certified P1a constant is literally unchanged.
- Forward links: (i) P2 traversal may read these graphs **advisory
  only** — a B4 graph is not evidence and not authority, and the
  fixtures say so in-body; (ii) the `cites`-only vocabulary remains the
  v0 bound — `supports`/`entails` remain deferred as an implementer judgment (the "director-gated semantic phase" wording is implementer deferral language per P1b-extraction.md:126,132,179 — no director has gated anything); the CHECK migration likewise remains UNCHARTERED; (iii) richer typing would also make B4
  graphs admissible to the twin's sequence validator, which is a future
  charter, not this one; (iv) further corpus growth (or any change above
  the 20 KiB cap) still needs a charter; (v) the real `IDR-043` file,
  if authored, should quote D1/D2 above.
