# MERGE-AUDIT-FETCH — delta merge-audit of `merge/fetch@8acb887` (P-AUTO-3-FIX + H2)

Findings only. Counts and `file:line`. Executed in an isolated worktree; the
shared checkout and the input branches were opened read-only and never
written. Scored against the deliverables of the MERGE-FETCH charter and the
two recorded audits (`audits/AUDIT-P-AUTO-3-REDTEAM.md`,
`audits/AUDIT-H2-REDTEAM.md`), plus the MERGE-P-AUTO-1-RETRY precedent.

The audited integration tip is `8acb887` (M2). Committing this file moves the
branch; the src/tests tree is pinned byte-identical by INV7–INV9 below, so
every finding holds unchanged at the final tip.

## Verdict

| Scope | Verdict |
| --- | --- |
| Merge mechanics (clean, hash-preserving, no integrator src changes) | **PASS** |
| Gates (suite + ruff + both pyrights at M2) | **PASS** |
| Widened P-AUTO-3-FIX footprint (scope-creep scan) | **PASS** — no certified-path behavior change |
| S4-condition survival (NOTICE + pins) | **PASS** |
| Count lineage `2325 → 2358 → 2503` | **PASS** — re-derived |
| H2 controller-wiring A/B | **FAIL — MUST-FIX M1**: the docling branch of `controller._span_resolve` can never return `True` |

**Overall: FAIL on MUST-FIX M1.** The integration itself is mechanically
sound and no certified path regresses, but the audited H2 wiring is inert as
shipped. Per the charter, the finding is reported, not fixed; STOP BEFORE
PUSH is honored (`main` unmoved, nothing pushed).

## Inputs receipt (all readable, no STOP)

| Input | Value | State |
| --- | --- | --- |
| `main` (local) | `e5f06a72370ed4af02903b6504bad6c848c1fc4a` | read, never touched |
| `main` (remote, `git ls-remote origin refs/heads/main`) | `e5f06a72370ed4af02903b6504bad6c848c1fc4a` | identical — unmoved before, during and after |
| P-AUTO-3 tip | `bf7c34f2aaebc6f7fc7e5965c97923e82db7d84e` | read-only |
| H2 tip | `8de7f22298674300c58dbe0744a9f1652b541534` | read-only |
| M1 | `670e6433cf54ce130540ab01a2d654e52c2d9549` | new, local |
| M2 (branch tip) | `8acb8876beb8608a1783927d908bf58e12577569` | new, **local, unpushed** |
| `merge/fetch` on the remote | absent — `git ls-remote origin` lists only `refs/heads/main` among the queried refs | never pushed |

STOP-topic scan (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`)
over the integration diff `e5f06a7..8acb887`: **1 hit**, the P-AUTO-3 audit
record's own boilerplate — see §Forbidden-topic scan.

## Merge integrity — invariants

| # | Claim | Command | Result |
| --- | --- | --- | --- |
| INV1 | M1 authors **no** change over the P-AUTO-3 tip | `git diff --exit-code --stat bf7c34f M1 -- src tests` | exit 0 — IDENTICAL |
| INV2 | M2's src+tests delta vs `bf7c34f` is exactly H2's file list | `git diff --name-only bf7c34f M2 -- src tests` | 38 paths = H2's 45 minus `pyproject.toml`, `uv.lock`, `NOTICE`, 4 scripts |
| INV3 | M2's src+tests delta vs `8de7f22` is exactly the P-AUTO-3 file list | `git diff --name-only 8de7f22 M2 -- src tests` | 13 paths = the line's src+tests exactly |
| INV4 | P-AUTO-3's pyproject hunk survives | `git diff bf7c34f M2 -- pyproject.toml` | only the `live_fetch` marker insertion |
| INV5 | H2's pyproject hunk survives | `git diff 8de7f22 M2 -- pyproject.toml` | only the two extras pins |
| INV6 | no deletions, union complete | `git diff --diff-filter=D --name-only <parent> M2` (both parents); every parent path `git cat-file -e M2:<path>` | both empty; zero missing files |
| INV7 | docs commits change no src/tests byte | `git diff --exit-code M1..HEAD -- src tests` (run after each docs commit) | IDENTICAL at the final tip (reported with the deliverable) |

Merge topology: M1 = `[e5f06a7, bf7c34f]`, M2 = `[670e643, 8de7f22]`; both
created with `--no-ff`, so every input hash survives. Zero conflicts; the
only auto-merge was `pyproject.toml` (non-overlapping hunks, both kept).

## Widened P-AUTO-3-FIX footprint — scope-creep scan (`0298b4e..bf7c34f`)

The widened fix is **13 files, +1033/−42**. Hunk inventory and disposition:

| File | Hunk | Classification |
| --- | --- | --- |
| `src/hermes/tools/providers/http.py` | +92: A1 same-origin-https redirect handler, `_OPENER`, `_open_request` seam; `urlopen` call replaced | Live-transport-only behavior change (the audited A1 MUST-FIX). 3xx now returned as `TransportResponse`; the certified status/timeout/size/redaction outcomes keep their exact assertions (seam target moved only). |
| `src/hermes/tools/providers/paginate.py` | +59: `_deadline_expired` + checks in `walk`, `_fetch_page`, `fetch_batch`, `_fetch_one` | Guarded by `deadline_monotonic is None` default — inert unless a deadline is set. New tests cover the set case. |
| `src/hermes/tools/providers/base.py` | +7: `WalkRequest.deadline_monotonic: float | None = None` | Defaulted field, end-position; keyword construction preserved. |
| `src/hermes/tools/research_sources.py` | +8: `FetchRequest.deadline_monotonic` | Same. |
| `src/hermes/research/source_handlers.py` | +27: `DEFAULT_OVERALL_DEADLINE_SECONDS = 300.0`; `SourcePolicy.overall_deadline_seconds`; `_dispatch_deadline`; deadline attached in `_run_search`/`_run_fetch` | **Intentional D1 closure** — the shipped dispatch path now carries a 300 s monotonic budget (`<= 0` disables). No certified test reaches 300 s of monotonic time (full suite + the 147-test A/B below are green). Recorded as a note, not a MUST-FIX. |
| `src/hermes/tools/providers/adapters/pubmed.py` | +6: `parser_version = "2"` | Certified replay: the repo holds **no other pubmed fixture** — `git grep` over `tests/fixtures` finds only `tests/fixtures/p_auto_3_live/pubmed.json`, re-stamped to `"2"`. Nothing else replays pubmed. |
| `src/hermes/research/live_fetch.py` | +5: docstring + deadline wiring | P-AUTO-3-only new module. |
| `audits/` records | +504 | Docs. |
| `tests/fixtures/p_auto_3_live/*` | re-stamp + new `redirect_evil.json` | New-corpus fixtures only. |
| `tests/test_p_auto_3_live_fetch.py` | +325/−? (23 → 33 tests, measured) | New line tests, including the E2 fix (small-cap profile, frozen clock — verified, no wall-clock drain). |
| `tests/test_provider_ratelimit.py` | +15/−14 | See below. |
| `config/hermes.toml` | +5 | Comment-only (allowlist-narrowing note). |

Certified-test evidence — the only pre-existing test file the line touched is
`tests/test_provider_ratelimit.py`, and its complete `-U0` changed-line
inventory is **one import + 13 monkeypatch-target swaps**:

```
+import hermes.tools.providers.http as http_module
    monkeypatch.setattr(urllib.request, "urlopen", ...)   →   monkeypatch.setattr(http_module, "_open_request", ...)
```

No assertion, expected value, or test body changed. The seam had to move
because production now calls `_open_request` (the redirect-refusing opener);
the certified outcomes are pinned by the same assertions as before.

A/B legs (both run by this task; cwd = tree, `PYTHONPATH=<tree>/src`, shared
interpreter):

| Leg | Selection | Result |
| --- | --- | --- |
| BEFORE — `main` src + `main` tests (md5 `059fd155…` walk, `ad2b7169…` fetch, `61da518b…` orchestration — byte-identical after) | `test_provider_walk.py test_provider_fetch.py test_provider_orchestration.py` | **147 passed** |
| AFTER — merge src + merge tests (same md5s) | same | **147 passed** |
| BEFORE — `main` ratelimit file (md5 `17a46e3a…`) | `test_provider_ratelimit.py` | **38 passed** |
| AFTER — merge ratelimit file (md5 `fe08907e…`, seam-only diff) | same | **38 passed** |

**Disposition: no certified-path behavior change found; no MUST-FIX from
this item.** Non-blocking note: the 300 s overall deadline is now ON for
every shipped search/fetch dispatch (bounded, config-disableable) — worth
one architecture line in a future docs pass.

## H2 controller-wiring A/B — **MUST-FIX M1**

### Method

Probe `/tmp/fetch-audit/h2_wiring_ab.py` (md5 `c77e6291a9b1b158fd3c67fabb4b7599`)
drives the **real** `Controller._execute_extract` on an in-memory DB with the
promoted S1 fixture record
(`tests/fixtures/s1_docling/2305.10601v2.json`, inner `record` stored as a
`source_payload` artifact through `ArtifactStore.write`) and an EXTRACT task
whose only claim carries the scenario's `source_ref`/`span_ref`. Identical
script and fixture on both legs; only the src tree differs (BEFORE =
`main@e5f06a7`, AFTER = `merge/fetch@8acb887`). The valid span token is the
provider's own `span:<sha256-16>:<start>:<end>` for span 0, computed with
the documented canonical-JSON recipe.

### Raw outcomes

```
AFTER  unit_resolver:              {"own_ref_ok": true, "artifact_style_ref_ok": false}
BEFORE plain_substring:            {"status": "SUCCEEDED", "claim_rows": 1}
AFTER  plain_substring:            {"status": "SUCCEEDED", "claim_rows": 1}
BEFORE S1_recorded_artifact_ref:   {"status": "RETRYING",  "claim_rows": 0}
AFTER  S1_recorded_artifact_ref:   {"status": "RETRYING",  "claim_rows": 0}
BEFORE S1_recorded_bare:           {"status": "SUCCEEDED", "claim_rows": 1}
AFTER  S1_recorded_bare:           {"status": "RETRYING",  "claim_rows": 0}
BEFORE S1_recorded_ownref:         {"status": "RETRYING",  "claim_rows": 0}
AFTER  S1_recorded_ownref:         {"status": "RETRYING",  "claim_rows": 0}
```

(Scenarios: `S1_recorded_artifact_ref` cites the 64-hex artifact ref with the
valid digest token; `S1_recorded_bare` cites it with a bare token
`section_header` that literal-exists in the stored record bytes;
`S1_recorded_ownref` cites the recorder's own `source_payload:s1-docling/…`
ref. An initial bare token `first_page` was discarded — it exists only in the
fixture wrapper, not in the stored inner record; `section_header` is present
in the stored bytes, which is what the scenario needs.)

### Mechanism (why the branch can never admit)

1. `controller._span_resolve` (`src/hermes/research/controller.py:4669-4677`)
   reaches the docling branch only after `repos.read_payload(source_ref)`
   returns bytes. `read_payload_bytes`
   (`src/hermes/persistence/source_outcomes.py:394-424`) only resolves
   `source_payload:<64-hex>` refs that equal an artifact row's
   `content_hash` — and `ArtifactStore.write`
   (`src/hermes/artifacts/store.py:91-152`) content-addresses those bytes:
   the ref id **is** `sha256(stored bytes)`.
2. The branch parses those bytes as the record and calls
   `docling_resolver_for(doc)(source_ref, span_ref)`
   (`controller.py:4676-4677`). The resolver admits only when
   `source_ref == doc.content.ref` (`docling_provider.py:516-533`).
3. `doc.content.ref` is a string **inside** the stored bytes. Admission
   therefore requires `source_ref == own_ref == sha256(bytes containing
   own_ref)` — a fixed point, computationally infeasible. If `own_ref` is
   anything else (the promoted recorder writes
   `source_payload:s1-docling/<pdf>` at `scripts/s1_docling_record.py:252`),
   step 1 refuses before the branch (non-hex ref) or step 2 refuses
   (mismatch). The call site itself passes the claim's citation ref
   (`claims.py:453`, `extraction.py:395`), not the document's ref.

The measured outcomes are exactly this: the branch is **reachable** (the
bare-token scenario changes the outcome: OLD admitted, NEW refuses — the
intended AUDIT-S1 A1 tightening) but can **never return True** (the valid
token is refused on both legs, and the unit call
`resolver_for(doc)(artifact-style ref, token)` is `False` while
`resolver_for(doc)(doc.content.ref, token)` is `True`).

### Impact and disposition

- The promoted S1 controller wiring is **inert as shipped**: no docling
  extraction can ever be admitted through it, and no test covers the
  controller path (`git grep docling -- tests` finds only the provider-level
  tests). The H2 audit's item A (PASS, "no A/B fixture comparison needed")
  is superseded by this measurement.
- **Not a certified-path regression**: pre-existing payloads are unaffected
  (plain-text control unchanged on both legs); the only outcome change is a
  refusal-tightening on readable docling-record payloads, a class introduced
  by H2 itself. All four gates are green at M2.
- **MUST-FIX M1 (handed back; src changes are forbidden on this branch):**
  make the wiring able to admit — e.g., resolve/thread the record's own ref
  separately from the citation ref instead of requiring equality with the
  artifact hash, and add an end-to-end controller test whose red leg is the
  current tip.

## S4-condition survival (post-merge, M2)

| Condition | Evidence |
| --- | --- |
| `NOTICE` | present; `git show M2:NOTICE` exact Crawl4AI attribution (byte-identical to `8de7f22`) |
| Pins | `tomllib` parse: `{'docling': ['docling==2.131.0'], 'crawl4ai': ['crawl4ai==0.9.4']}` |
| `live_fetch` marker | `['live_fetch: makes real (keyless) egress …']` present |
| `uv.lock` | byte-identical to `8de7f22` (P-AUTO-3 line never touched it) — **PASS** |

## Count lineage (re-derived)

| Figure | Derivation (raw collection) |
| --- | --- |
| 2325 | `main` — `total_collected=2325` |
| 2358 | `bf7c34f` — `total_collected=2358`; live-fetch file 23 (`0298b4e`) → 33 (measured) |
| 2470 | `8de7f22` — `total_collected=2470` (= 2325 + 145: 50 docling + 47 crawl4ai + 48 egress) |
| **2503** | `merge/fetch@M2` — `total_collected=2503` = 2325 + 33 + 145 |

Suite reconciliation: `2499 passed + 4 skipped = 2503`; the 4 skips are the
live-egress tests under `HERMES_SKIP_LIVE_FETCH=1`.

## Gate integrity — raw results at M2

| Gate | Command | Raw result |
| --- | --- | --- |
| full suite (alone) | `PYTHONDONTWRITEBYTECODE=1 HERMES_SKIP_LIVE_FETCH=1 PYTHONPATH=<wt>/src .venv/Scripts/python.exe scripts/run_tests.py -v -p no:cacheprovider` | `2499 passed, 4 skipped, 13 warnings in 555.48s (0:09:15)` — exit 0 |
| lint | `uvx ruff check src tests` | `All checks passed!` |
| types src | `PYTHONPATH=<wt>/src uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| types tests | `PYTHONPATH=<wt>/src uvx pyright --pythonpath "D:/New folder/research-agent/.venv/Scripts/python.exe" --project pyrightconfig.tests.json` | `0 errors, 1 warning, 0 informations` (`tests/test_research_program.py:144:23`, pre-existing) |

Import proof per invocation: `hermes.__file__ = …\mergefetch\src\hermes\__init__.py`.
Suite header: `platform win32 -- Python 3.14.1, pytest-9.1.1, pluggy-1.6.0`.

## Forbidden-topic scan

Diff-scoped over `e5f06a7..8acb887`: **1 hit** — line 514 of the added
`audits/AUDIT-P-AUTO-3-REDTEAM.md`:

```
+- [x] No forbidden topics (backtest_audit, SDA, TSE, Optimize-my-strategy — not encountered)
```

That is the redteam record **reporting its own scan**, not the topics being
worked on — the repo's established precedent ("report, not trigger"). A hard
halt would make the charter unexecutable; the untouched base `main` itself
carries the same prose elsewhere. No STOP condition on scope is asserted.

## Post-audit integrity checks

- `git rev-parse HEAD` in the worktree when this audit body was written:
  `8acb8876beb8608a1783927d908bf58e12577569`; `git symbolic-ref --short HEAD`
  → `merge/fetch`.
- `git status --porcelain --untracked-files=all` before this doc was
  written: **empty** — no stray tracked modification, no src change made by
  this audit.
- `main` local == `main` remote == `e5f06a72370ed4af02903b6504bad6c848c1fc4a`,
  checked before the merges, between them, and again at the close.
  `main` was never checked out, reset, rebased, committed to, or pushed.
- **No `git push` of any ref was performed**; `merge/fetch` does not exist on
  the remote (`git ls-remote origin` returns only `refs/heads/main` for the
  queried refs). D9 lapsed with the last landing; **stopped before push**.
- The shared checkout stayed on `audit/p-auto-3-redteam` with its own staged
  state, unmodified; inputs were read via `git show` / `git diff` / `git
  archive` into `/tmp/fetch-audit/`.
- `git worktree list` = 38 entries after adding the one worktree this task
  owns (`mergefetch`); no existing worktree was written, checked out over,
  or pruned. Probe and logs live under `/tmp/fetch-audit/`.
- **Disclosure (repeat, still unresolved):** both merges logged
  `error: failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4': Permission denied`
  while pruning a stale, pre-existing worktree admin directory unrelated to
  this line. The merges landed correctly (parents/trees verified
  immediately); the directory was left in place rather than force-removed.

## Carry-forward

1. **M1 (blocking a fresh push decision):** rework the H2 docling span path
   so it can admit — the citation ref and the record's own ref must be
   reconciled (and the payload-ref format decided: the promoted recorder's
   `source_payload:s1-docling/<name>` refs are not artifact-addressable and
   would need a documented dereference). Add an end-to-end controller test
   with a digest token; it is red on `8acb887`.
2. **SHOULD-FIX:** record the now-ON 300 s default dispatch deadline from
   `source_handlers.py` in the architecture docs.
3. **Bookkeeping:** H2 audit item A should be re-scored against §M1; its
   "purely additive, no A/B needed" premise did not establish that the path
   works.

## Addendum — gates re-run at the final tip `7ea9b4e`

The table in §Gate integrity is at M2 `8acb887`. Committing this document and
`MERGE-LOG-FETCH.md` moved the tip twice, and per AGENTS.md a docs-only change
still requires the full suite green, so all four gates were re-run at the tip
after both docs commits. The docs-only proof was re-run first:

```
$ git diff --exit-code 8acb887 7ea9b4e -- src tests
(no output — IDENTICAL, exit 0)
```

| Gate | Result at `7ea9b4e` |
| --- | --- |
| full suite (alone) | `2499 passed, 4 skipped, 13 warnings in 540.71s (0:09:00)` — exit 0 |
| lint | `All checks passed!` — exit 0 |
| types src | `0 errors, 0 warnings, 0 informations` — exit 0 |
| types tests | `0 errors, 1 warning, 0 informations` — exit 0 (same pre-existing `tests/test_research_program.py:144:23`) |

Because every docs commit (M2 → `b5e5ef5` → `7ea9b4e`, and this addendum
commit on top) changes no `src/` or `tests/` byte — `git diff --exit-code
8acb887 <tip> -- src tests` is empty at each — the M2 findings and the gates
above hold unchanged at the final tip.
