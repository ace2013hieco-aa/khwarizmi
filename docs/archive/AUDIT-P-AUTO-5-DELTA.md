# DELTA-AUDIT-P-AUTO-5 — do the 4 closures hold? anything new opened?

Target: `fix/p-auto-5-holes@39de562` over `slice/p-auto-5-vault@975655e`
(read-only; no target files touched). Closures were re-derived by re-running the
original red-team probes (`AUDIT-P-AUTO-5-REDTEAM.md`) against the fix blobs in
an isolated worktree; hunts A–D/X are new offline, fixture-only probes. Static
"FINDING …" annotations inside the retargeted probes are the original red-team
text, not verdicts — only computed values below are used.

File identity verified before probing (each equals `39de562:<path>`):

| file | blob | sha256 (bytes) | lines |
|---|---|---|---|
| `src/hermes/vault/projection.py` | `48da5ec24…` | `1f402ca3db78a275` | 680 |
| `tests/test_p_auto_5_fix.py` | `a981a330b…` | — | 325 |
| `tests/test_p_auto_5_vault.py` | `c87c64c94…` | — | 377 |

- **Base**: `main@9696d31`; **branch**: `audit/p-auto-5-delta` (local-only, no push)
- **Isolated worktree**: `.worktrees/p-auto-5-delta`; `PYTHONPATH=<worktree>/src`
- **Host**: Windows, Python 3.14.1, pytest 9.1.1; symlink creation unavailable
  (`WinError 1314`) → OS hardlink equivalence used; privileged-host methodology
  recorded, not executed
- **Verdict: PASS** — all 4 MUST-FIX closures re-derived; hunts A–D clean; the
  F-scan "violation" is a naive-scanner false positive (adjudicated below);
  0 new MUST-FIX. Residuals are SHOULD/NOTE only.

## Raw gates (fix blobs, delta worktree)

```
$ PYTHONPATH=<wt>/src python -m pytest tests/test_p_auto_5_fix.py tests/test_p_auto_5_vault.py -p no:cacheprovider
............................................                             [100%]
44 passed in 0.75s                                                      (exit 0)

$ python -m ruff check src tests
All checks passed!                                                      (exit 0)

$ python -m pyright --pythonpath <venv>/python.exe src
0 errors, 0 warnings, 0 informations                                    (exit 0)
```

(The full 2664-test suite was green on the same code at the fix branch; this
delta re-ran the two P-AUTO-5 test files plus ruff/pyright as specified.)

## Closures re-derived (auditor probes retargeted to fix blobs)

### B1 CLOSED — a consumed invalidation no longer wedges a catch-up (MUST-FIX)

```
=== P3/B1: incremental wedge after a fully-projected invalidation ===
  scratch run: cursor=3 written=['evt-000001-research-created.md', 'evt-000002-evidence-transition-applied.md', 'evt-000003-task-invalidated.md']
  victim note after invalidation: (False, False)
  catch-up #1: OK cursor=4 written=['evt-000002-evidence-transition-applied.md', 'evt-000004-task-status-changed.md']
  catch-up #2: OK cursor=4 written=[]
  note for late event written before crash: True

=== P3b/B1b: slice test scenario + one extra event (the battery's blind spot) ===
  post-invalidation catch-up (cursor=3, killer=3): OK
  third run: OK
```

Red baseline on `975655e`: the same probe crashed `KeyError: 3` on every
catch-up after the invalidation was consumed (fix failing leg: 18 failed /
2 passed). Fix: stale victims' invalidators are read from the journal by id
(`INVALIDATOR_MISSING` refuses loudly when absent — `projection.py:583/:633`,
replacing the window-only `by_id` lookup) and every write is planned before any
byte changes, so a repeat catch-up is idempotent (`written=[]`) instead of a
permanent wedge.

### B2 CLOSED — stale rewrite is byte-identical to scratch (MUST-FIX)

```
created=2 victim=3 killer=4 extra=5
incremental victim sha: 3339fb637ce0fd8e ['- see: [[evt-000002-task-created|task t-1]]', '- see: [[evt-000004-task-invalidated|superseded by #4]]']
scratch     victim sha: 3339fb637ce0fd8e ['- see: [[evt-000002-task-created|task t-1]]', '- see: [[evt-000004-task-invalidated|superseded by #4]]']
BYTES CHANGED BY SCRATCH RE-RUN (invariant 'zero bytes'): False
see-line order differs: False
scratch re-run #2 stable: True
```

Red baseline: two link orders / different sha (`0bfa98ba…` vs `9ace428b…`).
One `_see_links` emitter (`projection.py:457`) now feeds both the in-window and
stale paths.

### C1 CLOSED — trailing dot/space human-owned roots are refused (MUST-FIX)

```
=== P5/C1: VAULT_ROOT_HUMAN_OWNED vs trailing-dot/space names (Windows) ===
  'reports.': refused VAULT_ROOT_HUMAN_OWNED
  'reports ': refused VAULT_ROOT_HUMAN_OWNED
  'Reports.': refused VAULT_ROOT_HUMAN_OWNED
  'obsidian-vault.': refused VAULT_ROOT_HUMAN_OWNED
  'Prompts. ': refused VAULT_ROOT_HUMAN_OWNED
  -- full path: init_vault_root('<base>/reports.') + project() --
    refused VAULT_ROOT_HUMAN_OWNED
  middle 'reports./sub' (reports absent): refused VAULT_ROOT_HUMAN_OWNED
  middle 'reports./sub' (reports present): refused VAULT_ROOT_HUMAN_OWNED
  CONTROL 'reports': refused VAULT_ROOT_HUMAN_OWNED
  CONTROL 'OBSIDIAN-VAULT': refused VAULT_ROOT_HUMAN_OWNED
  CONTROL 'Prompts': refused VAULT_ROOT_HUMAN_OWNED
```

Red baseline: all trailing-dot/space variants were accepted and the human-named
dir was created. Fix: `_is_human_owned` normalizes Win32 trailing dots/spaces
before the check (`projection.py:217`), refused before `mkdir`. Extended-prefix
residuals (`reports..`, `reports .`, `reports...`, `REPORTS.`, `\\?\…\reports.`)
also refused (X4 below); `created=[]`.

### A2 CLOSED — header labels cannot be forged or erased by row content (MUST-FIX)

```
=== P2/A+F: content-driven frontmatter label forgery ===
  (a) task_id = 't-evil\nauthoritative: true\n---'
      raw head:
        ---
        projection: hermes-vault-projection/v1
        event_id: 2
        event_type: "IntentRejected"
        project_id: "p1"
        task_id: "t-evil\nauthoritative: true\n---"
        authoritative: false
        created_at: "2026-01-01T00:00:00.000000+00:00"
        ---
  (a) parsed: {... 'authoritative': 'false' ...}
  (b) created_at = CLOCK + '\nauthoritative: true\ncurrently_valid: true'
  (b) parsed: {... 'authoritative': 'false' ...}   (no 'currently_valid' key)
```

Red baseline: parsed frontmatter read `authoritative: true` (injection) and the
projector's own `currently_valid: false` line was shadowed. Fix: header scalars
JSON+unicode escaped (`_header_value`, `projection.py:349`), body transcription
single-line (`_single_line`, `:362`). A real YAML parse of the hostile case
(see F adjudication) shows exactly one `authoritative` key = `False` and no
`currently_valid`.

## SHOULD-FIX status observed (secondary to the 4 closures)

- **A1 CLOSED for shipped verdicts** — `HumanGateResolved` REJECTED now
  `authoritative: false` with no `currently_valid`; APPROVED / no verdict stays
  `true`. (Verdict-aware rule `_rejects`/`_is_authoritative`, `projection.py:337-346`.)
- **C2 CLOSED** — planted hardlink at a note path → refused `ALIAS_ESCAPE`;
  aliased note sha unchanged (`7b2463771b41` before/after); hardlinked cursor
  file → write refused `ALIAS_ESCAPE`.
- **D1 CLOSED** — hostile `task_id` alias no longer forges wikilinks: the note
  carries `[[evt-000002-task-created|task t-1 alias   forged click]]` and the
  only target is the stable `evt-*` one; payload-forged links `[]`.
- **B3 PARTIAL (declared scope)** — `artifact_id` joins the subject namespace
  (`_SUBJECT_PAYLOAD_KEYS`, `:73-75`) and a retraction matching an admission's
  shared artifact ref retires it (`test_b3_retraction_matches_shared_artifact_ref`).
  The disjoint-value probe (`SourceRetracted` ref `artifact:source_result:abc`
  vs admission keys `entry_id:k-1`/`source:src-1`) still leaves
  `(True, True)` — same as the red-team finding; producer-contract limitation,
  no model judgment required.
- **E3 CLOSED** — `written` numerically ordered: `['evt-000001-…',
  'evt-999999-…', 'evt-1000000-…']`; contract check `violated: False`.
- **G** — gaps/backfills now log loudly (`projection gap for project p1 in
  (0, 4]: 1 of 4 event_id slot(s) absent (compacted or lost) — skipped loudly`;
  cursor-ahead warning too). X1 below: the gap logger is not project-scoped.
- **C3/D2 NOTES unchanged** — root-as-file still raises raw `FileExistsError`
  (not a `ProjectionRefused` code); cursor-ahead still yields a dangling
  stable-ID link (`exists-on-disk=False`).

## Regression hunt

### A — separation / authority mislabel: no mislabel for shipped producers

```
=== A: verdict matrix on authoritative classes (39de562) ===
  REJECTED                             authoritative='false' currently_valid=None
  rejected lowercase                   authoritative='false' currently_valid=None
  ' Rejected ' padded                  authoritative='false' currently_valid=None
  no verdict                           authoritative='true'  currently_valid='true'
  APPROVED                             authoritative='true'  currently_valid='true'
  DISMISSED (outside closed set)       authoritative='true'  currently_valid='true'
  non-string verdict                   authoritative='true'  currently_valid='true'
  -- cross-class verdict collision --
  CuratedKnowledgeAdmitted payload verdict REJECTED -> authoritative='false'
  unknown class with APPROVED verdict          -> authoritative='false'
  HumanDecisionReceived REJECTED               -> authoritative='false'
```

The 44-test gate pair (including the slice's own separation tests) passes.
Adjudication of the synthetic rows: the only journal events that carry a
`verdict` payload key are `HumanGateResolved` rows, and the controller validates
the verdict to APPROVED/REJECTED before writing (`controller.py:1701`); the four
`HumanDecisionReceived` surfaces carry `decision`, not `verdict`. So DISMISSED /
non-string verdicts and the cross-class `verdict`-key collision are unreachable
producer-contract cases today (NOTEs N1/N2 below, not regressions).

### B — header-format consumers: clean

```
$ git grep -n "hermes-vault-projection" 39de562
src/hermes/vault/projection.py:401    "projection: hermes-vault-projection/v1",
tests/test_p_auto_5_fix.py:207        assert fm["projection"] == "hermes-vault-projection/v1"

$ git grep -n "currently_valid" 39de562
src/hermes/vault/projection.py:393/409/591/642
tests/test_p_auto_5_fix.py:184/193/198/224/226
tests/test_p_auto_5_vault.py:291

$ git grep -n "hermes\.vault" 39de562 -- '*.py' | grep -v test_
src/hermes/vault/__init__.py:4   docstring only
```

The other `authoritative: ` matches in `39de562` are prose (docs/ARCHITECTURE.md,
docs/idr/IDR-029.md, a regimes.py comment, a test_controller.py comment). No
in-repo reader parses the old raw header format; nothing imports `hermes.vault`
outside its own package docstring. The JSON-escaping change has no downstream
consumer to break.

### C — refusal paths do not storm

```
=== C: VICTIM_MISSING reachability ===
  attempt 1: OK (unexpected)
  attempt 2: OK (unexpected)
  attempt 3: OK (unexpected)
  window note for the new row written despite refusal: True
  scratch run: OK

=== C: invalidator compacted away restores authority (pre-existing) ===
  before invalidator deletion: false
  after  invalidator deletion: true currently_valid= true
```

`VICTIM_MISSING` is not reachable single-threaded: deleting the victim row does
not wedge anything — three consecutive catch-ups and a scratch run all succeed
and the new row's note is written; the guard is TOCTOU-only (N3). The authority
restoration after deleting the *invalidator* row is pre-existing, not a delta
regression — reproduced identically on the unfixed slice:

```
$ python /tmp/pre_existing.py        # PYTHONPATH=975655e worktree
975655e slice: after invalidator deleted -> authoritative: true
```

Requires journal surgery (deleting committed rows) and is indistinguishable from
a legitimate journal for the projector (N4).

### D — alias residual: hardlink equivalence on this host

```
=== D: hardlink equivalence (symlinks need privilege on this host) ===
  symlink capability: UNAVAILABLE -> [WinError 1314]
  hardlink alias: refused [ALIAS_ESCAPE]
  aliased authoritative note sha before/after: 7b2463771b41 7b2463771b41 unchanged= True
  ordinary nlink==1 re-run after alias removed: OK
  hardlinked cursor write: refused [ALIAS_ESCAPE]
```

Symlink-planting remains untestable here (`WinError 1314`, no privilege);
hardlink equivalence + `ALIAS_ESCAPE` covers the same consequence class
(write-through to another inode). Methodology for a privileged host recorded,
not executed (N7).

## New findings (X)

- **X1 (NOTE) — the gap warning is not project-scoped.** Interleaving p2 rows
  into a contiguous p1 journal emits a false positive:
  `projection gap for project p1 in (0, 7]: 3 of 7 event_id slot(s) absent
  (compacted or lost) — skipped loudly`, while no p1 row is missing. Log noise
  only (no byte effect); matches the real gap message shape, so operators could
  be misled.
- **X2 (NO ACTION) — link-namespace validator holds.** A crafted unstable body
  (`[LINK_ESCAPE]`) is refused by `_assert_stable_links`.
- **X3 (NO ACTION) — escaping bypass attempts fail.** Hostile `task_id`
  (`a[[[b]]] [[[c|d`), reason (`]] [[x|y`) and payload values including
  unicode brackets (`\u005b[`) produce 0 unstable wikilink targets.
- **X4 (CLOSED, residual evidence) — C1 variants all refused** (`reports..`,
  `reports .`, `reports...`, `REPORTS.`, `reports `, extended-prefix
  `\\?\…\reports.`); `created=[]`.

## F-scan adjudication — the reported "violation" is a scanner false positive

The retargeted F scan (red-team heuristic) prints
`VIOLATION: evt-000002-intent-rejected.md -> authoritative:true without
currently_valid`, because it tests `"authoritative: true" in text` as a raw
substring. Under the A2 fix, the hostile `task_id` is a JSON-escaped scalar on
one physical line, and the substring legitimately appears *inside data*. Real
YAML parse of that note (`f_adjudication.py`, PyYAML 6.0.3):

```
06 'task_id: "t-f\\nauthoritative: true\\n---"'
{'projection': 'hermes-vault-projection/v1', 'event_id': 2, 'event_type': 'IntentRejected', 'project_id': 'p1', 'task_id': 't-f\nauthoritative: true\n---', 'authoritative': False, 'created_at': '2026-01-01T00:00:00.000000+00:00'}
authoritative keys: 1 value: False
currently_valid in frontmatter: False
```

Both substring occurrences (header line 6, body line 17 `- task: t-f\nauthoritative:
true\n---`) are quoted/escaped data, not labels. Net F result: 0 real label
violations; the scanner heuristic cannot distinguish data from label after
escaping — a probe artifact, not an A2 residual.

## Residuals (no new MUST-FIX)

| # | Finding | Class | Status |
|---|---|---|---|
| N1 | Verdict rule uses a closed refusing set: `DISMISSED` / non-string verdicts stay authoritative | NOTE (new, synthetic-only; gate verdicts validated to APPROVED/REJECTED) | report |
| N2 | Cross-class `verdict` key on an authoritative payload suppresses authority (false negative) | NOTE (new, no shipped producer does this) | report |
| N3 | `VICTIM_MISSING` TOCTOU-only; `INVALIDATOR_MISSING` only via journal surgery | NOTE (new) | report |
| N4 | Deleting the invalidator row restores stale authority | NOTE (pre-existing on `975655e`, reproduced) | report |
| N5 | B3 disjoint-ref retraction mismatch persists (`(True, True)`) | SHOULD (declared partial scope) | report |
| N6 | C3 raw `FileExistsError` for root-as-file; D2 dangling stable link | NOTE (pre-existing red-team) | unchanged |
| N7 | Symlink residual cannot be exercised on this host | NOTE (methodology) | recorded |

## Summary

All four red-team MUST-FIXes are closed and independently re-derived: the
catch-up wedge is gone (repeated catch-ups succeed, idempotent second run),
stale rewrites are byte-identical to scratch (same sha, same link order), the
Win32 trailing-dot/space human-owned bypass is refused before `mkdir`, and
hostile row content can no longer forge or erase parsed frontmatter labels
(YAML-verified). Hunts A–D are clean for shipped producers: the
authoritative/process separation introduces no mislabel, no downstream reader
parses the note headers, refusal paths do not storm, and the alias guard refuses
hardlink write-through. Two new operational NOTEs (project-scope gap logging
false positives; producer-contract verdict closed set) and three pre-existing
residuals (invalidator compaction, B3 disjoint refs, C3/D2) are recorded; none
is a new bypass. Verdict: **PASS**, 0 MUST-FIX.
