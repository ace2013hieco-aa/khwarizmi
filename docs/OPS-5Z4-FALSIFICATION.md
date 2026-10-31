# OPS-5Z4 — the three falsification capabilities

Three ids were declared in the runtime profiles and had no implementation:
`evidence_inspect`, `contradiction_scan`, `statistic_check`. `SUPPLIED_CAPABILITY_IDS`
was `("source_fetch", "source_search")`, so every run reported them as
"declared but unsupplied" — a phrase that reads like a phase boundary and was
an absence. The critic reviewed prose against prose; the verifier verified
without a source.

This slice supplies them, makes their call path reachable, and fixes two
runtime assumptions that would otherwise have made the supply decorative.
No model is involved in any of the three decisions.

## 1. What each capability decides

### `evidence_inspect(ref, subjects?)`

**Decides:** what an artifact *states* — the dates it names, the figures it
states with the surface phrase each binds to, and its quoted spans.
Deterministic extraction by rule (`hermes/research/inspection.py:facts_in`,
`:372`).

- `ref`: `evidence:<artifact_id>`, `source_payload:<content_hash>`, the
  `/`-spelled forms, or a bare id/hash. A path cannot match: the executor
  refuses `INSPECT_REF_MALFORMED` before any lookup.
- `subjects`: optional filter; keeps figures whose subject phrase mentions one
  of the terms.
- Returns an `Observation` whose payload is canonical JSON
  `{capability, ref, facts: {dates, figures, quotes, subjects, analyzed_chars,
  truncated}}` and whose model-visible note is a bounded summary (≤900 chars;
  the runtime caps detail at 1 KiB).

**Determinism argument:** the extractor is regexes and nearest-date binding
over `semantic_text`; it reads no clock, no network, no model. The only
environment dependency is the artifact's bytes and its project membership —
both read through the store's hash-verifying, project-scoped path. Same bytes,
same facts, forever. A read that no longer re-derives its hash refuses
`INSPECT_INTEGRITY_REFUSED` rather than reporting different bytes.

**What it does not decide:** whether a figure is *true*, and whether the
subject is the entity the claim means. `entity` is the first capitalised token
of the subject phrase (falling back to its last token); two different
organisations with the same name are one entity here.

### `contradiction_scan(statements, refs?)`

**Decides:** which pairs of claims *cannot both be true* under three numeric
or lexical rules (`inspection.py:conflicts_between`, `:732`):

- `QUANTITY` — same entity, same date (or one date a coarser prefix of the
  other), different canonical figures;
- `ATTRIBUTION` — the same stated figure on two different entities (only for a
  figure with a thousands separator, a decimal, or a percent sign, so small
  round numbers that repeat innocently do not fire);
- `ORDER` — mutually exclusive superlatives, a superlative a larger peer figure
  on the same date contradicts, or an `A was ahead of B` assertion the figures
  on that date reverse. The last rule is read over the *whole* claim set, not
  one pair, because the incident shape puts the numbers in one claim and the
  ordering in another.

**Determinism argument:** pure over the supplied statements; every rule is a
regex plus integer/float comparison; results are deduped and sorted. No model,
no I/O.

**What it does not decide:** which side is right, which side rests on a weaker
source, or what to do. A conflict is a report; the critic's judgement and the
runtime's authority are unchanged.

### `statistic_check(statement, base_refs?)`

**Decides:** whether a *derived* figure follows from the figures it rests on
(`inspection.py:check_derivation`, `:874`). Recomputes, in order of structural
match: `X out of Y, or Z%`; `X% of Y is Z`; `from A to B ... by X%` (including
a direction check); `A minus B is C`; `A per B is C`; and a stated total over
its stated components. `base_refs` supplies components extracted from other
artifacts when the statement names only the total.

Returns `CONSISTENT`, `INCONSISTENT`, `UNPARSEABLE` (no derivation pattern) or
`NO_BASIS` (a pattern with a missing base). Only the first two are verdicts
about arithmetic; "could not check" is never reported as agreement.

**Determinism argument:** arithmetic on literals; tolerance is half a unit in
the asserted figure's last stated decimal place, so a rounded value agrees and
a changed digit does not. No model, no I/O.

**What it does not decide:** anything statistical. No confidence intervals, no
significance, no unit conversion beyond thousand/million/billion/trillion, no
multi-step chains.

## 2. What was built

| Layer | Change |
|---|---|
| Extraction core | `src/hermes/research/inspection.py` — facts, conflicts, arithmetic, and the bounded note renderers. Pure; no clock, network, model or DB. |
| Content model | `src/hermes/tools/capabilities/content.py` — the one `semantic_text` / `reconstruct_inverted` implementation, shared by the evidence envelope and `evidence_inspect`. |
| Declarations | `capability_supply.py:falsification_declarations` (`:355`) — three `LOW`-risk, `network=False`, no-filesystem-scope tools; `set.falsification` composition (`FALSIFICATION_TOOL_SET_ID`). |
| Executors | `capability_supply.py:1064/1089/1133` — project-scoped, hash-verified artifact reads; refusals returned as data, never as exceptions. |
| Supply | `SUPPLIED_CAPABILITY_IDS` now five ids (`:194`); `supplied_capability_risks()` (`:341`) is the one risk table. |
| Grants | `composition.py:plan_capability_plane` (`:298`) opens the declared tool sets containing a granted capability (`:359`) instead of the one hardcoded egress set. |
| Profile | `verifier.yaml` now declares `allows_tool_calls: true` and `tool_calls` in `structured_fields` — see §6. |
| Tick accounting | `run.py:_tick_termination` (`:935`) does not end a `no_proposals` stage on a tick that actually invoked a capability (`:965`). |

## 3. Falsifiers and red proofs

`tests/test_ops5z4_falsification.py` (30 tests). The falsifiers that would fail
if a capability were stubbed:

| Capability | Falsifier | Red proof |
|---|---|---|
| `evidence_inspect` | the real OpenAlex record yields no figures and no dates because its abstract states none — and the record's own `publication_date` is not mined; a synthetic OpenAlex-shaped record binds `1,200` to `Hubei` and `2020-01-23`. The real cookie wall yields nothing. A second project's artifact refuses `INSPECT_ARTIFACT_MISSING`; tampered bytes refuse `INSPECT_INTEGRITY_REFUSED`; a path-shaped ref refuses `INSPECT_REF_MALFORMED`. | `facts_in` stubbed to an empty inspection: the "facts are reported" assertion fails. |
| `contradiction_scan` | the incident trio (India 5,275,035; Brazil 4,467,433; "Brazil was ahead of India") reports `ORDER` with both figures in the detail; two agreeing claims report none; same entity/date with two figures reports `QUANTITY`. | `conflicts_between` stubbed to `()`: the incident assertion fails. |
| `statistic_check` | a total wrong by one digit is `INCONSISTENT` with `computed=9742468.0`; the right total is `CONSISTENT`; `25% of 400 is 120` is `INCONSISTENT`; `base_refs` supply the components of a stated total; a missing basis refuses `STATISTIC_BASIS_MISSING`. | `check_derivation` stubbed to always `CONSISTENT`: the wrong-total assertion fails. |

One end-to-end test matters most: a scripted critic calls `evidence_inspect`
on tick 1, and tick 2's prompt contains a `runtime.observation` envelope with
`Hubei` and `1,200`. That is the only test proving the runtime actually
delivers a tool result to the stage that asked for it.

## 4. What could not be built, and why

1. **Claim-ref resolution.** `contradiction_scan` takes statements, not claim
   ids. Resolving a ref to a stored claim would add a new claim-store read
   surface and a new project-scope question to the capability plane. A critic
   must paste the statements, and the declared `statements` field is capped at
   4 KiB of recorded JSON — so roughly eight to ten short claims, not the
   internal 12 × 8,000 belt. The field bound bites first; this is the largest
   gap against the original ask.
2. **Semantic conflicts.** Paraphrase, negation, pronouns and coreference are
   not caught. `A was ahead of B` works only for a fixed verb list
   (`ahead of`, `leading`, `led`, `surpassed`, `overtaken`, `overtook`,
   `outpaced`, `exceeded`). Two claims in different vocabularies produce no
   conflict, and the tool says "no conflict found by the numeric, attribution
   or ordering rules" — it does not claim the claims agree.
3. **Unit conversion.** `million`/`billion`/`trillion`/`thousand` are scaled;
   `bn`, `lakh`, `crore`, `basis points` and currency are not.
4. **Statistical inference.** `statistic_check` checks arithmetic only. A
   p-value, a confidence interval or a significance claim is `UNPARSEABLE`.
5. **Document shapes.** No tables, figures, PDFs or equations; quoted spans are
   double-quoted or guillemet spans only.
6. **The stated OpenAlex falsifier is unsatisfiable.** The 33,727-byte
   fixture's abstract is a modelling study whose only digits are "COVID-19";
   the record's metadata carries `publication_date: 2020-09-27` and
   `cited_by_count: 34`. A whole-record extractor would have "passed" the
   original falsifier by reporting bibliographic metadata as the abstract's
   figures. The test now asserts the opposite (metadata is not mined) and uses
   a synthetic OpenAlex-shaped record for binding. This should have been
   checked before the falsifier was written.
7. **It does not fix the grounding gate.** `grounding.py` remains unwired, and
   the date rule's containment hole is unchanged. `evidence_inspect` exposes
   the facts; nothing yet compares a *draft's* figures to them automatically.

## 5. What changes in a run

- Supplied set: 2 → 5 ids. Withheld declarations: 10 (7 ids) → 6 (4 ids:
  `artifact_store`, `experiment_execute`, `graph_read`, `provenance_read`).
  Grants: `RESEARCHER` (egress set) and `ADVERSARY` (falsification set), two
  disjoint compositions.
- The critic can now inspect an admitted artifact and scan a claim set. Its
  next tick receives the note in a `runtime.observation` envelope. It can
  catch, for the first time: a citation whose artifact does not state the
  claim's figures; two claims with the same entity and date but different
  numbers; the same figure attributed to two entities; an ordering the figures
  reverse.
- The verifier can now inspect the artifact behind an `evidence:` ref and
  recompute a reported statistic. `max_tool_calls: 2` is now a reachable
  bound rather than dead config.
- A gather tick no longer terminates a `no_proposals` stage. Before the tick
  fix, the critic's first tool call ended the run as `NO_PROPOSALS` and it
  never saw the result — the capability was unusable by the only profile whose
  job is to falsify (the verifier uses `proposals_raised` and was not
  affected).
- Still bounded: the critic sees at most six figures and four dates in the
  note (`+N more`), never the full payload; the full facts travel as size and
  digest only.

## 6. What nobody was looking for

1. **Grant derivation assumed one tool set.** `plan_capability_plane` minted
   every grant with `tool_set_ids=frozenset({RESEARCH_EGRESS_TOOL_SET_ID})`.
   A second composition could be declared and supplied but never granted: the
   plan would say "granted" and the invoker would refuse `ROLE` at call time.
   This had to be fixed before the falsifiers were usable; the new test proves
   an egress-only grant cannot reach a falsifier.
2. **The verifier's `max_tool_calls: 2` was unreachable.** `allows_tool_calls:
   false` and no `tool_calls` in `structured_fields` meant the profile could
   never emit the field its two declared tools needed. The comment called it a
   phase boundary; the config called it an absence. Treated as an oversight
   and fixed; the F4 gate is now proven on a synthesised profile that lacks
   the field.
3. **`no_proposals` counted a gather tick as a completed pass.** The contract
   sentence says "a reply that proposes nothing is valid when it calls a tool:
   … the stage continues within its tick budget", and `_tick_termination`
   stopped the stage anyway. The fix counts only a real invocation
   (`state.tool_calls` increased); a refused or skipped call buys no tick.
4. **The shared content model cannot live in `tools.providers`.** The agent
   runtime may import only `hermes.core`, `hermes.security`,
   `hermes.tools.models`, `hermes.tools.capabilities` and itself (pinned by
   `test_agent_runtime.TestModuleInvariants`). Moving `semantic_text` there
   from `assembly.py` broke that invariant; it now lives in
   `hermes/tools/capabilities/content.py`, and the assembly purity test names
   the new module. One implementation, legal direction.
5. **A falsification is deterministic but not auditable after the fact.** The
   agent-runtime tool phase emits `TOOL_OBSERVED` (capability + artifacts) and
   keeps the payload's size and digest in feedback; it does not journal the
   invocation envelope. The task-handler path (`capability_handler.py`) does.
   So what the critic saw is in the prompt, not in the journal. The follow-up
   is to persist the envelope (or a `CapabilityObserved` event carrying inputs
   digest, observation digest, environment and authority) on this path too.
6. **Global hash dedup meets project scoping.** `ArtifactStore.write` returns
   an existing row for the same content hash regardless of project, while
   `ArtifactRepository.in_project` / the new `_row_by_hash` require the row's
   recorded project to match. A document first admitted in project A and
   re-admitted in project B resolves to A's row, so `evidence_inspect` (and the
   evidence envelope's `read_artifact`) refuse it in B. Not exercised by a
   test here; worth verifying before cross-project corpus reuse is relied on.

## 7. Gates

- `uvx ruff check src tests`: clean.
- `uvx pyright src`: 0 errors. `pyright --project pyrightconfig.tests.json`:
  0 errors, 1 pre-existing warning in `test_research_program.py`.
- `scripts/contract_matrix.py`: 0 declaration/enforcement mismatches.
- `scripts/stamp_suite_count.py --check`: OK, collected 5769.
- Targeted batteries: `test_ops5z4_falsification.py` (30), `test_ops5b_*`,
  `test_ops5_capabilities`, `test_ops5c`, `test_ops5d`, `test_ops5f`,
  `test_ops5g/h/k/l`, `test_agent_runtime`, `test_loop1_context_assembly`,
  `test_ops5z3` — green.
- `scripts/suite_baseline.py --baseline docs/SUITE-BASELINE.json`: exit 0 —
  **0 failing of 5769** (log: `.hermes/ops5z4_final3.log`). No baseline
  update; the 5–6 known-flaky are not findings. An intermediate full run
  failed one pinned CLI line (`"Capability plane: 2 supplied"` in
  `tests/test_ops1_live_cli.py`); the assertion was updated to the supplied
  count and the withheld count, and the final run above is clean.
