# GR3-P1b-audit2 — adversary audit of P1b v0 cites extraction (project khwarizmi-research)

Status: **ACCEPT**. 12/12 probes held. All blocking checks passed; no
rejection-grade findings. Two minor notes recorded below (non-blocking).

Audited commit: `gr3-b4/p1b` == `13565f8` (verified: `git rev-parse
gr3-b4/p1b` = `13565f84070c10c7b894fea615cda2f737ae2341`). Audit branch:
`gr3-b4/p1b-audit2` from `13565f8`. NO remote push (standing local-only
order; no override presented).

## Checkout verification (PASS)

- `src/hermes/research/graph_edges.py` present (411 lines).
- `src/hermes/persistence/graph_edges.py` present (416 lines).
- `tests/test_gr3_edges.py` present, exactly **498** lines.
- `src/gr3_edges.py` **absent** (rg over `src/` returns nothing).

## Independent execution (PASS — 12/12)

Audit-owned probes: `scripts/p1b_audit2_probes.py` (committed with this
report). Executed against the real six-document corpus on this branch:

1. Extractor over the six real documents: **3/1/1/0/0/0** — AGENTS.md →
   {API, ARCHITECTURE, STATE}; API → {AGENTS}; STATE → {ARCHITECTURE};
   ARCHITECTURE / IDR-024 / IDR-028 → EMPTY. Exact-triple match with the
   report's claim. PASS.
2. Validator determinism: rerun byte-identical edge sets, ADMITTED twice
   for every document. PASS.
3. Hallucination (extra edge) and silent drop (missing edge) both
   INVALID, with `hallucinated:`/`dropped:` error attribution. PASS.
4. Zero-write on refusal: forged `derived_from` edge through
   `gr3_edge_draft_from_mapping` refused (`outside the v0 vocabulary`);
   `provenance_edges` row count **0 → 0**. PASS.
5. Outside-world observation: `IDR-018` present in `skipped`, never an
   edge. PASS.
6. Extractor version pinned (`GR3_EXTRACTOR_VERSION == "1"`). PASS.
7. Suite evidence: `tests/test_gr3_edges.py` **28/28 green**; adjacent
   suites (`test_corpus_admission.py`, `test_extraction_pipeline.py`,
   `test_claims_write_path.py`, `test_research_sources.py`) **151 green**
   (72+72+7 collected across the four modules, all passing). PASS.
8. Write-boundary gate chain re-derived from source: verdict-first gate
   (`_validate_result` raises `GraphEdgeIntegrityError` unless
   `verdict == "ADMITTED"`), closed result/edge keys, extractor-version
   pin, citing identity re-derived from bytes
   (`sha256(citing_bytes) != citing_hash` refuses), in-transaction task
   binding (exists / same project / TOOL_TASK / `gr3_extract` template /
   RUNNING / `spec.corpus_ref` equality), dual endpoint resolution
   (certified `_source_artifact_resolves` + admitted-row metadata
   `corpus_ref` anti-substitution), single `BEGIN IMMEDIATE` … `COMMIT`
   with rollback on any error. PASS.

## Report-claim vs source verification (all confirmed)

| Report claim | Source check | Result |
|---|---|---|
| Route (a) via CURATE_KNOWLEDGE is human-verdict-bound and writes `curated_knowledge_entries`, not graph edges | `gateway.py:1881-1901` — "Authority: a ratified operator decision (a recorded HumanDecision whose payload binds the full-command curation_id hash)… internal-only intent" | CONFIRMED — routing cites through it would fabricate per-edge human authority |
| No other intent admits graph edges | Gateway intent surface: RECORD_CONTRADICTION / EVIDENCE_TRANSITION / RECORD_CLASSIFICATION / INSERT_TASK write other substrates; no graph-edge writer outside `record_extraction` | CONFIRMED |
| `record_extraction` already writes `cites`/`derived_from` edges in production | `repositories.py:2299-2303` — "§14 edges: derived_from source; cites assumptions" + INSERT OR IGNORE loop at 2315-2319 | CONFIRMED — route (b) mirrors a production shape; no new authority presumed |
| `supports`/`entails` comment-only, absent from CHECK | `gateway.py:1293-1299` comment + `migrations.py:260-262` five-value CHECK (`cites, derived_from, supersedes, used_as_input, justifies`) | CONFIRMED — deferring the CHECK widening to the director-gated semantic phase is consistent |
| No migration justified; `cites` inside live CHECK | `migrations.py:260-262` | CONFIRMED |
| Self-edges impossible | `migrations.py:265` `CHECK (artifact_id != upstream_id)` + draft-level and boundary-level self-edge refusals | CONFIRMED (defense in depth) |
| P1a O1 (precise inserted/reused counts) FIXED here | `persistence/graph_edges.py:391-399` — per-statement `cur.rowcount`, `reused = prepared - inserted` | CONFIRMED |
| P1a O2 (BaseException parity) DEFERRED with reason | `persistence/graph_edges.py:157-162` mirror-exact to certified `source_outcomes.py:323-328` (`except … ROLLBACK/raise` twice) | CONFIRMED — deferral reasoning sound; boundary-consistent |
| DG-5: new persistence module imports nothing from `hermes.research` | imports: `hashlib`, `sqlite3`, `typing`, `hermes.core`, `hermes.core.task_status`, intra-persistence `_source_artifact_resolves` (the `repositories.py:51` precedent — import verified at that line) | CONFIRMED |
| Transaction census persistence 17 → 18 | P1a added `CorpusRepository.record` (16 → 17); P1b adds `GraphEdgeRepository.record` (17 → 18), same certified structure | CONFIRMED |
| IDR-043 reserved in text; no IDR file written | Report reserves it; `rg IDR-043 docs/` shows only the reservation text; no code references either number | CONFIRMED |
| No event emission from the edge path | `_commit` writes edge rows only; no event INSERT in either new module | CONFIRMED |

## Route decision assessment

The FIRST decision (recorded before building, per the report's own
ordering statement) — route (b), a task-bound repository write boundary —
is sound:

- (a) is correctly refused: CURATE_KNOWLEDGE is an internal-only,
  human-verdict-bound registry; carrying observational cites through it
  would attach per-edge human authority that does not exist. The other
  intents write different substrates; semantic fraud either way.
- (c) is correctly refused: the task-output-acceptance shape is already
  production (`record_extraction`), so a new intent kind adds authority
  surface with no capability gain. `gr3_extract` tasks classify
  `"unhandled"` until controller wiring lands — inert, no shadow path.
- Unhandled third option: **derive-on-read** (compute the cites graph at
  query time from admitted corpus artifacts, never persisting edges).
  The report does not name this alternative. It is fairly excluded —
  P2 traversal and the §14 cascade need a governed, append-only,
  cascade-walkable substrate (P0-audit C1), and re-deriving on every
  read makes the graph unauditable — but the decision record is more
  complete for naming the exclusion. **Minor note 1 (non-blocking).**

## Minor notes (non-blocking)

1. **Derive-on-read not named.** See above. Recommend one paragraph in
   the IDR-043 record when authored.
2. **"S6 invariants bound this task verbatim" phrasing.** AGENTS.md:10-64
   is the invariants section, but phrases like "task-bound acceptance
   with in-transaction binding re-check" are the EXTRACT/P1a boundary
   discipline (IDR-026 Decision 2.1), not verbatim AGENTS.md text. The
   discipline itself is correctly implemented and cited elsewhere; only
   the "verbatim" word overstates. **Minor note 2 (non-blocking).**

## Verdict

**ACCEPT.** The P1b commit is additive-only (3 new files + this audit's
2), the boundary is the certified EXTRACT shape, the extractor is
deterministic and byte-anchored, refusals fail closed with zero writes,
and the certified chain (P0 → P1a → audits) is untouched. P2 may proceed
on the 5 persisted cites triples. The two minor notes should ride into
the IDR-043 authorship charter, not block it.
