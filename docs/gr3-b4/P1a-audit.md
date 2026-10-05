# ADVERSARY audit — GR3 P1a corpus admission (`e5f01d3`, branch `gr3-b4/p1a`)

Verdict: ACCEPT (4 observations, no conditions).
Scope: `docs/gr3-b4/P1a-admission.md` + `src/hermes/research/corpus.py`
+ `src/hermes/persistence/corpus.py` + `tests/test_corpus_admission.py`
at `e5f01d3` (`e5f01d3646608c0f34aa2e7455a16f034e7df333`), reviewed
against LIVE SOURCE on branch `gr3-b4/p1a-audit` (cut from `e5f01d3`).
Every finding cites source locations. Claims verified by execution,
not by reading the design doc: 16/16 independent adversarial probes
held (probe script kept outside the repo; in-memory DB only), plus the
delivered 23-test suite re-run green on the audit branch and `ruff`
clean. No remote push (standing local-only order).

## (a) Write boundary — REAL (proven by forced failures)

- `BEGIN IMMEDIATE` ownership: `persistence/corpus.py:150`. Pre-tx
  pure validation: `:147-148` (`_validate_draft` `:169-217`,
  `_validate_content` `:219-240` — sha256 re-derived from the bytes,
  size equality, cap). Rollback on `CorpusError` AND generic
  `Exception`: `:160-165`.
- Forced partial write (probe A5): shared-connection proxy raising on
  the `provenance_edges` INSERT after the artifact row INSERT —
  result `(artifacts, edges) == (0, 0)` and `get_by_hash` None.
  Post-write failure (probe A6: `store.write` raising after the real
  row INSERT inside the tx) — result `(0, 0)`; any orphan file is
  uncitable (no DB row), the IDR-013 property.
- No partial write could be forced through any refusal path: all 7
  unbound and 6 INVALID shapes leave counts frozen (probes +
  delivered tests).

## (b) Production-wiring map — NO second write path; record unreachable in production

Exhaustive reference sweep (`CorpusRepository|corpus_admit|
CORPUS_ADMIT|persistence\.corpus|research\.corpus|...` over `src/`):
hits exist ONLY in the two new modules (definition) — zero references
in `controller.py`, `gateway.py`, `cli.py`, handlers, or any intent.
Route-by-route:

- OPEN (generic, inert): a `TOOL_TASK` with `spec.template =
  "corpus_admit"` could be created via generic INSERT_TASK (free-form
  spec, `gateway.py:3477-3480`) — but dispatch keys handlers by
  template (`controller.py:2496-2497, 4113`) from the injected
  `_task_handlers` dict (`:414`, default `{}`), in which
  `corpus_admit` is absent, so such a task classifies `"unhandled"`
  (`:4132`): no execution, no `record` call. No CLI subcommand, no
  intent kind, no handler factory exists.
- CLOSED: `CorpusRepository.record` — sole production-DB caller set is
  empty; only `tests/test_corpus_admission.py` calls it.
- CLOSED: interference with existing paths — corpus rows are stamped
  with corpus-task ids only, so fetch/classification one-shot queries
  (task-scoped, e.g. `source_outcomes.py:695-700`) are unaffected;
  same-type global reuse via `store.write` is the certified SD-04
  semantic; admitted rows are immediately N9-fenced
  (`source_outcomes.py:159`) and resolvable
  (`dereference_ref`, `:371-392`).
- The design doc's "production handlers are future wiring" is
  accurate, not an implication of a path: nothing delivered implies
  one.

## (c) Closed set — ENFORCED live (no 7th document)

Probed against live code, all refused with counts frozen:
A1 unlisted `README.md` (real bytes) → `CorpusIntegrityError`
(`:188-191`); A2 tampered hash → `:235-240`; A3 oversize
(`CORPUS_MAX_BYTES + 1`) → `:209-212`; A4 traversal (`../../`,
absolute, `..` segment), case variant, empty/whitespace-padded refs →
`CorpusDraftError` BEFORE any filesystem access (proven by using a
nonexistent root: only a pre-filesystem refusal can raise there);
A7 non-mapping draft → `:174-177`. Loader membership gate
(`research/corpus.py`, `_require_ref`) and write-boundary membership
(`:188-191`) agree — both probed, plus the cross-layer agreement test.

## (d) DG-5 — HOLDS (zero persistence→research imports)

`persistence/corpus.py` imports, exhaustive (`:35-42` top-level,
`:119-122` the sole lazy import): `__future__`, `hashlib`,
`sqlite3`, `typing`, `hermes.core`, `hermes.core.task_status`, lazy
`hermes.persistence.repositories`. No `hermes.research` import at any
level. Reverse direction verified clean too:
`repositories.py` never imports corpus (empty grep), so no cycle.
`research/corpus.py` imports only `hermes.research.programs`
(intra-research, allowed). The constant duplication is the documented
triplication precedent with a pinning test — no new upward
dependency.

## (e) S6 invariants — DEMONSTRATED in code, not prose

- Task-bound acceptance: six in-tx checks
  (`persistence/corpus.py:253-289` — exists, project, TOOL_TASK,
  normalized marker, RUNNING, spec-ref equality); probed live
  (missing task, wrong project, PENDING/READY/SUCCEEDED/FAILED,
  AGENT_TASK, wrong template, ref mismatch — all `CorpusBindingError`,
  zero writes).
- Validated-before-acceptance: draft + bytes validated pre-tx
  (`:147-148`); the write path re-validates independently rather than
  trusting the research layer (`:169-240` vs
  `research/corpus.py:156-174`).
- Content-addressed idempotency: one-shot per task (`:300-316`) +
  global hash reuse (`:345`); probed live (A8 NEW→IDENTICAL same id;
  A9 divergent → `CorpusConflictError`).
- No new intent/event/authority: verified by the (b) sweep; admission
  emits no event (delivered no-event test + `record` contains no
  `_append_event` call); census delta (persistence 16→17) is stated in
  both the module docstring (`:28-33`) and the design doc.

## (f) IDR-042 reservation — SOUND

Verified: no `docs/idr/IDR-042.md` on the P1a tree, on `main`, or
anywhere in `--all` history; side-branch `48e4ce9` (`texp-001/p2`,
`docs/texp-001/` prose only) remains unmerged
(`merge-base --is-ancestor` exit 1). Reserving the mainline file slot
in-text with a documented 043 fallback is the correct strength for a
docs-level reservation (first-writer-wins by file existence remains
true, and the doc says so in effect). Note: the reservation is not a
ratification — the actual IDR-042 record is still unwritten.

## Observations (no action required for acceptance)

- O1: summary `"edges": 1` (`:389`) overstates on re-admission
  (`INSERT OR IGNORE` may insert 0 rows). Mirror-exact to the
  certified precedent (`source_outcomes.py` `"edges": len(edges)`,
  prepared-not-inserted). Polish candidate for P1b, not a condition.
- O2: `BaseException` (e.g. `KeyboardInterrupt`) bypasses the
  `:160-165` rollback — identical to certified
  `source_outcomes.py:323-328`. Mirror-exact, not a P1a defect.
- O3: delivered "23 tests" claim verified (20 `def test_` + 4
  parametrized non-running cases = 23 dots, green on audit branch).
- O4: `record` accepts `bytearray` (normalized via `bytes(content)`,
  `:227`) — harmless suppleness, hash still re-derived.

## Acceptance

P1a stands ACCEPTED with no conditions. P1b may proceed on the
admitted `source_payload:<hash>` surface. This audit is docs-only:
`docs/gr3-b4/P1a-audit.md` added on `gr3-b4/p1a-audit` from `e5f01d3`;
zero `src/`/`tests/` changes; no push.
