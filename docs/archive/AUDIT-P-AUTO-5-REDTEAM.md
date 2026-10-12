# AUDIT-P-AUTO-5-REDTEAM — vault projector (slice/p-auto-5-vault@975655e)

- **Target**: `975655e` (3 files: `src/hermes/vault/projection.py` +519, `src/hermes/vault/__init__.py` +2, `tests/test_p_auto_5_vault.py` +377)
- **Base**: `main@9696d31`; **branch**: `audit/p-auto-5-redteam` (local-only, no push)
- **Isolated worktree**: `.worktrees/p-auto-5-redteam`; `PYTHONPATH=<worktree>/src`
- **Host**: Windows, Python 3.14.1, pytest 9.1.1; all probe writes in OS temp dirs only
- **Verdict: FAIL** — 4 MUST-FIX, 5 SHOULD-FIX, 4 NOTE. A/B/C/D/F fail; E passes (bytes); G adjudicated as silent skip.

## Raw gates (at target files, worktree `p-auto-5-redteam`)

```
$ PYTHONPATH=<wt>/src python -m pytest tests/test_p_auto_5_vault.py -p no:cacheprovider
........................                                                 [100%]
24 passed in 0.40s                                                        (exit 0)

$ ruff check src tests
All checks passed!                                                        (exit 0)

$ pyright --pythonpath <venv>/python.exe src                              # strict
0 errors, 0 warnings, 0 informations                                      (exit 0)

$ pyright --pythonpath <venv>/python.exe --project pyrightconfig.tests.json
tests/test_research_program.py:144:23 - warning: ...                      (exit 0)
0 errors, 1 warning, 0 informations        # pre-existing, not slice file
```

Probes ran with `PYTHONPATH=<worktree>/src` and the venv interpreter; projection.py sha256 prefix `c0d46e6b95f1091c`.

## A — authority leak: FAIL

**A1 (SHOULD-FIX). AN authoritative set is event_type-only; a REJECTED human verdict is labeled authoritative.**
`projection.py:433` (`authoritative = event_type in AUTHORITATIVE_EVENT_TYPES`) never consults the row's
verdict/status, and `HumanGateResolved` is emitted for both APPROVED and REJECTED
(`controller.py:1843-1848`, `payload={"verdict": verdict, ...}`). Seeded counter-proof beyond the slice's own
(its separation test seeds only APPROVED):

```
HumanGateResolved note header region:
---
projection: hermes-vault-projection/v1
event_id: 2
event_type: HumanGateResolved
project_id: p1
task_id: gate-1
authoritative: true
currently_valid: true
created_at: 2026-01-01T00:00:00.000000+00:00
---
parsed_frontmatter={... 'authoritative': 'true', 'currently_valid': 'true' ...}
reason: human gate gate-1 resolved: REJECTED ; payload: {"verdict":"REJECTED",...}
```
Docstring says process = "tasks, refusals, gates, proposals, recovery"; a refusal note is labeled as a
currently-valid authoritative fact. Design decision required, not a mechanical bug.

**A2 (MUST-FIX). Frontmatter label forgery/omission via unsanitized row content.**
`_render` concatenates raw `task_id` (`:299`), `project_id` (`:298`), `created_at` (`:305`) into the YAML head.
Two seeded counter-proofs on a *process* row (`IntentRejected`):

```
(a) task_id = 't-evil\nauthoritative: true\n---'
    raw head:  ... task_id: t-evil / authoritative: true / --- / authoritative: false / created_at: ...
    parsed frontmatter: {'...','task_id': 't-evil', 'authoritative': 'true'}   <- flag in BODY after injected ---
(b) created_at = CLOCK + '\nauthoritative: true\ncurrently_valid: true'
    parsed frontmatter: {..., 'authoritative': 'true', 'currently_valid': 'true'}  <- projector's own false line shadowed
```
A reader of the derived view sees `authoritative: true` on a refused process row. Same vector can omit the
flag entirely from parsed frontmatter (injected `---` closes the block early).

## B — validity staleness: FAIL

**B1 (MUST-FIX). Permanent `KeyError` wedge: no catch-up can run after an invalidation has been consumed.**
`projection.py:474` assumes the invalidator is in the current window (`by_id` is built only from `rows`, `:456`),
but `stale_victims` (`:457-458`) is derived from full history (`:396-420`), so a victim stays "stale" forever
after the invalidator's window has passed. Minimal repro:

```
scratch run (cursor=0, rows 1-3): cursor=3
victim note after invalidation: (authoritative False, currently_valid False)
catch-up #1 cursor=3: CRASH KeyError 3
  File ".../projection.py", line 474, in project
    invalidator = by_id[invalidated_by[victim_id]]
KeyError: 3
catch-up #2 (retry): CRASH KeyError(3)      <- permanent wedge; window notes were written before the crash
```
Replicating the slice's own `test_late_invalidation_rewrites_victim_identically` and appending one event
crashes the third run — the battery never runs a catch-up after the invalidation was processed (its last call is
a scratch re-run at cursor=0). Impact: one late invalidation wedges incremental projection for all future events,
with partial writes and an unhandled non-`ProjectionRefused` exception.

**B2 (MUST-FIX). Late-invalidation rewrite diverges from scratch: link order.**
In-window rendering appends the task link first (`:429-432`) then the superseded link (`:438-442`); the stale
rewrite appends them in the opposite order (`:477-483`). Probe:

```
created=2 victim=3 killer=4 extra=5
incremental victim sha: 0bfa98ba9a7ba5fe
  ['- see: [[evt-000004-task-invalidated|superseded by #4]]',
   '- see: [[evt-000002-task-created|task t-1]]']
scratch     victim sha: 9ace428ba72d4b8e
  ['- see: [[evt-000002-task-created|task t-1]]',
   '- see: [[evt-000004-task-invalidated|superseded by #4]]']
BYTES CHANGED BY SCRATCH RE-RUN (invariant 'zero bytes'): True
scratch re-run #2 stable: True
```
Violates the module docstring's "one journal row -> exactly one note (scratch == incremental)" and
"re-running a cursor range changes zero bytes". The slice's own test victim has no `TaskCreated` link, so the
divergence is invisible to the 24-test battery.

**B3 (SHOULD-FIX). Retraction cannot retire an admission (subject-key namespaces never intersect).**
Closed set `_SUBJECT_PAYLOAD_KEYS = ('entry_id','source','ref')` (`:67-68`) lacks `artifact_id`; the
`SourceRetracted` producer uses `payload={'artifact_id': ref}` + `artifact_ids=[ref]`
(`source_outcomes.py:786-795`, `controller.py:1305-1310`). Probe:

```
keys(victim   CuratedKnowledgeAdmitted) = ['payload:entry_id:k-1','payload:source:src-1','task:t-k']
keys(invalidator SourceRetracted)       = ['artifact:source_result:abc','task:t-r']
retracted-source admission note: (authoritative true, currently_valid true)   <- stale authority survives
control: same-key CuratedKnowledgeInvalidated -> (False, False)               <- mechanism works when keys line up
```
A retracted source's admitted claim stays in the authoritative graph unless the producer happens to reuse the
identical artifact ref (no producer does today).

## C — guard bypass: FAIL

**C1 (MUST-FIX). Trailing dot/space bypasses VAULT_ROOT_HUMAN_OWNED on Windows and creates the human-named dir.**
`init_vault_root` (`:195-210`) checks stage-1 components of `realpath` (lexical when the name does not exist)
with only `casefold()` (`:200-208`), then `os.makedirs` (`:209`); Win32 strips trailing dots/spaces, so the
projector creates the human-owned name. Probe (temp-dir simulation, no real human dir touched):

```
'reports.':        NOT REFUSED -> returned '...\\reports.'; listdir=['reports']   realpath='...\\reports'
'reports ':        NOT REFUSED -> listdir=['reports']
'Reports.':        NOT REFUSED -> listdir=['Reports']
'obsidian-vault.': NOT REFUSED -> listdir=['obsidian-vault']
'Prompts. ':       NOT REFUSED -> listdir=['Prompts']
middle 'reports./sub' (reports absent): NOT REFUSED -> creates 'reports'/sub
CONTROL 'reports' / 'OBSIDIAN-VAULT' / 'Prompts': refused VAULT_ROOT_HUMAN_OWNED
junction root -> 'reports': refused VAULT_ROOT_HUMAN_OWNED
```
Scope verified precisely: the *same* call sequence's second `init_vault_root` now canonicalizes (the dir exists)
and refuses, so no note bytes reached the simulated human dir in this probe; the concrete violation is the
persistent creation of a directory in the human-owned namespace, against "never written", plus an accepted root
handed back that names the human area.

**C2 (SHOULD-FIX). In-root alias at a note path is not refused: writes go through / clobber another note.**
`_join_note` resolves `realpath` first (`:221`) and the symlink check inspects the *resolved* path (`:234-237`),
so an in-root symlink resolves to its (non-link) target and is never `SYMLINK_ESCAPE`; the write lands on the
target. On this host symlink creation fails (`WinError 1314`), so an OS-level hardlink (same consequence class,
undetectable alias) was used:

```
symlink capability: UNAVAILABLE on this host -> [WinError 1314]
methodology for a privileged host (recorded, not executed):
  mklink <root>\<victim-note>.md <root>\<target-note>.md ; then project()
  expect SYMLINK_ESCAPE per docstring -- actual: write-through
planted hardlink at process note path -> authoritative note inode
noteA sha before=d8250002e7c3 after=676856aef853
noteA header now says authoritative: false (process body): True
```
Related gate-integrity issue: for a symlink pointing *outside* the root the prefix check (`:230-233`) fires
first, so `test_join_refuses_symlink_and_directory` (`tests:235-237`) asserts `SYMLINK_ESCAPE` while the code
would raise `PATH_ESCAPE`; the test only passes on this host because symlink creation fails and the monkeypatch
fallback fakes `islink`. On a symlink-capable host (developer mode/POSIX) that test fails. Junction control:
`sub/note.md` through a junction-to-outside -> `PATH_ESCAPE` (correct refusal, wrong code for the promise).

**C3 (NOTE). Root that exists as a file** raises raw `FileExistsError` (`:209`), not a `ProjectionRefused`
code (`root-is-a-file: FileExistsError: [WinError 183]`).

## D — link forgery: FAIL

**D1 (SHOULD-FIX). Wikilinks outside the stable-ID namespace via task_id / payload / reason.**
`_task_alias` (`:339-340`) interpolates the raw `task_id` into the alias, and the see-lines (`:429-432`,
`:477-483`) are not escaped; `_payload_text` (`:274-283`) and `reason` (`:324-326`) transcribe arbitrary text.
Probe (task_id `t-1|alias]] [[forged|click`):

```
- see: [[evt-000002-task-created|task t-1|alias]] [[forged|click]]
slice's own link regex targets: ['forged', 'forged', 'forged']   <- target 'forged' is not evt-*
payload-forged note links: [('forged-payload', 'tap')]
```
The slice's own link-shape test can never see this: it seeds clean task ids.

**D2 (NOTE). Stable-ID target that is not a note.** With a cursor restored ahead of the vault
(`write_cursor(root, 5)`), the next note links to a note that was never written:
`written=['evt-000006-...']; note links [[evt-000002-task-created|...]] exists-on-disk=False`.

## E — non-determinism: PASS (bytes)

Five independent processes, rich journal (10 rows incl. invalidated authority, multi-key payloads, unicode-safe
fields), scratch projections: `PYTHONHASHSEED` 0/1/4242/random/7 x `LC_ALL` C/tr_TR.UTF-8/en_US.UTF-8 x
`PYTHONUTF8` 0/1:

```
seed0/localeC                cursor=10 written=10 files=10
seed1/localeC                cursor=10 written=10 files=10
seed4242/localeTR            cursor=10 written=10 files=10
seedrandom/localeUS/utf8=0   cursor=10 written=10 files=10
seed7/utf8=1                 cursor=10 written=10 files=10
byte-identical across all 5 process/seed/locale environments: True
```
In-process re-runs are stable. No dict/set iteration or timestamp leaks into note bytes found.
(Windows largely ignores `LC_ALL` for runtime behavior; the seeds exercise the str-hash/set-order surface.)

**E3 (NOTE). `written[]` order contract**: `written.sort()` (`:492`) is lexicographic, so for >=7-digit ids:
`['evt-000001-...', 'evt-1000000-task-status-changed.md', 'evt-999999-task-created.md']` — not event_id order
(docstring `:349` promises event_id order).

## F — label integrity: FAIL (only via A2), clean otherwise

Scan of 15 generated notes (rich journal + 7-digit ids + injection case): every clean note has exactly one
`authoritative` key in frontmatter, `currently_valid` appears only on valid authoritative notes, the
derived-view marker is present, and process notes carry `authoritative: false`. The single violation is the
A2 injection case: `authoritative: true` parsed on a process note without `currently_valid`. The cursor file
`.projection-cursor` has no label (projector state, not a note).

## G — cursor-gap behavior: silent skip (NOTE)

```
g1 compacted range below cursor (2,3 deleted): -> (5, 1) no refusal          # intended retention behavior
g2 unprojected event 3 deleted before projection: cursor=4, written=[2,4]; note for lost id exists=False
g3 backfilled event 4 below cursor: -> (9, []); note exists=False            # never projected, no signal
g4 cursor ahead of any row: -> (99, []) silent no-op
```
There is no gap detector, no refusal code and no log: holes/backfills are invisible. Adjudication: **skip
silently** is the current behavior (not "refuse"); the projector cannot distinguish "never committed" from
"lost" without a manifest, so this is a documented limitation rather than a bug — but a maximum-id/cursor
sanity check would make g4/g3 loud.

## A–G adjudication

| Area | Verdict | Evidence |
|---|---|---|
| A authority leak | **FAIL** | A1 REJECTED verdict authoritative; A2 frontmatter label forgery |
| B validity staleness | **FAIL** | B1 permanent KeyError wedge; B2 scratch!=incremental bytes; B3 retraction no-match |
| C guard bypass | **FAIL** | C1 trailing-dot human-name creation; C2 in-root alias write-through; C3 file root crash |
| D link forgery | **FAIL** | D1 forged `[[forged|...]]` targets; D2 dangling stable target |
| E non-determinism | **PASS** (bytes) | 5 process/seed/locale maps identical; E3 written-order NOTE |
| F label integrity | **FAIL** (via A2) | 14/15 clean; injection forges the flag |
| G cursor gaps | **NOTE** | silent skip; no signal for lost/backfilled ids |

## MUST-FIX (minimal set)

1. **B1** — never index the invalidator through the window: derive/query the invalidator row by id for stale
   victims (and make the rewrite idempotent/deduplicated), so a consumed invalidation cannot wedge later runs
   (`projection.py:456-458,474`).
2. **B2** — build the see-link list in one deterministic order shared by the in-window and stale paths
   (`projection.py:429-432` vs `:477-483`).
3. **C1** — canonicalize each path component before the human-owned test (strip trailing dots/spaces on
   Windows, or compare `rsplit`-normalized components / use the OS final-path API), and re-check after
   `makedirs` (`projection.py:195-210`).
4. **A2/F** — sanitize frontmatter values: reject/escape CR/LF (and a line that equals `---`) in
   `event_type`, `project_id`, `task_id`, `created_at` before writing the head (`projection.py:293-306`).

## SHOULD-FIX

- **A1** — decide verdict semantics for `HumanGateResolved`/`HumanDecisionReceived` (exclude non-accepting
  verdicts from the authoritative graph, or label "ratified decision" distinctly from "accepted claim").
- **B3** — align retraction subject keys with admission keys (`artifact_id` is not in the closed set).
- **C2** — detect an alias at the note path itself (lstat before realpath) and fix the symlink test matrix so
  `SYMLINK_ESCAPE` vs `PATH_ESCAPE` is exercised — currently environment-dependent.
- **D1** — escape/mark `[[`, `]]`, `|` and newlines in transcribed text and aliases so wikilinks can only be
  the stable-ID see-lines.
- **E3** — sort `written` by integer event id.

## NOTE

- **G** silent skip for compacted/lost/backfilled ranges (no refusal, no log); consider an explicit
  cursor-vs-max(event_id) check.
- **D2** cursor restored ahead of the vault yields dangling stable-ID links.
- **C3** root path that exists as a file raises an unnamed `FileExistsError`.
- `pyright` tests-profile warning (`tests/test_research_program.py:144`) is pre-existing and unrelated.

## Summary

The slice delivers strong byte determinism (E, 5-env proof) and a clean label baseline (F) — but the trust
surface is not safe as shipped. Incremental projection **wedges permanently** (`KeyError`) after any fully
processed invalidation, and the late-invalidation rewrite **changes note bytes** relative to scratch. The guard
accepts trailing-dot/space human-owned roots and creates the human-named directory. The projector's own
`authoritative` label can be forged by row content, and a REJECTED verdict is labeled as a currently-valid
authoritative fact. Link aliases/payloads can forge wikilinks outside the stable-ID namespace. Verdict: **FAIL**;
fix B1/B2/C1/A2 minimally, then re-run the battery plus a catch-up-after-invalidation test.
