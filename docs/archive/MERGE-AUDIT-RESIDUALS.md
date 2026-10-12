# MERGE-AUDIT-RESIDUALS — verification of `merge/residuals` (audit verdict: PASS)

Task **MERGE-RESIDUALS**. Scope: verify the integrated branch
(`MERGE-LOG-RESIDUALS.md`) — full gates, patch-exactness, and an
independent re-proof of all four audits at the merged tip. **LOCAL-ONLY,
NO PUSH.**

| Value | Record |
| --- | --- |
| Verified tip (pre-doc commits) | `bafa728a60c42a97285c3a2939f0986c45d52fd9` |
| BASE (unmoved) | `a8f018068e3c04b3160891ebd56cfd95d3590c95` |
| Remote `refs/heads/main` (read-only ls-remote) | `e4b276db7880cb8c0e17e1239e03c589138541ae` — untouched |
| Interpreter | `D:\New folder\research-agent\.venv\Scripts\python.exe` (Python 3.14.1) |
| `PYTHONPATH` | `D:\New folder\merge-residuals-wt\src` (absolute) |

## VERDICT: **PASS**

All four audits re-proved green at the merged tip; all gates green;
patch-exactness holds (merely additive union, one mechanical add/add
resolution); `main` unmoved; nothing pushed. Residuals below are
pre-existing / declared-scope NOTEs, none introduced by this merge.

---

## 1. Gates at the merged tip (raw)

```
$ PYTHONPATH=<wt>/src $PY -m pytest -q --junitxml=merge_residuals_final_junit.xml
EXIT: 0
JUNIT: tests=3746  errors=0  failures=0  skipped=0
```

```
$ $PY -m pytest --collect-only -q        # base vs tip, file-line totals
BASE  main@a8f0180  : 3686
TIP   merge@bafa728 : 3746      (+60 — lineage in §7)
```

```
$ uvx ruff check src tests
All checks passed!
RUFF_EXIT=0

$ uvx pyright --pythonpath <abs-venv-python> src
0 errors, 0 warnings, 0 informations
PYRIGHT_SRC_EXIT=0

$ uvx pyright --pythonpath <abs-venv-python> --project pyrightconfig.tests.json
d:\New folder\merge-residuals-wt\tests\test_research_program.py
  ...test_research_program.py:144:23 - warning: Instance methods should take a "self" parameter (reportSelfClsParameterName)
0 errors, 1 warning, 0 informations
PYRIGHT_TESTS_EXIT=0
```

The single pyright-tests warning is **pre-existing and unrelated**
(`tests/test_research_program.py:144:23`, untouched by every merged line)
— the same warning the MERGE-CERT / MERGE-CFIX3 records carry.

**Final-tip re-run.** The gates were re-run after the
`MERGE-LOG-RESIDUALS.md` + `MERGE-AUDIT-RESIDUALS.md` commits, on the
final branch tip (the integration tree plus the two docs; this paragraph
is part of that tree — markdown-only, absent from every collection
surface):

```
$ $PY -m pytest -q --junitxml=<probes>/final_tip_junit.xml
JUNIT: tests=3746 errors=0 failures=0 skipped=0 (time 545.1s)   EXIT 0
$ uvx ruff check src tests
All checks passed!                                              EXIT 0
$ uvx pyright --pythonpath <venv> src
0 errors, 0 warnings, 0 informations                            EXIT 0
$ uvx pyright --pythonpath <venv> --project pyrightconfig.tests.json
0 errors, 1 warning (pre-existing test_research_program.py:144:23)  EXIT 0
```

Probe scripts (outside the repo, not committed):
`D:\New folder\merge-residuals-probes\probe_r1_manifest.py`,
`D:\New folder\merge-residuals-probes\probe_r3_pin.py`.

## 2. R-1 — manifest false-OK re-probe (FAIL → hardened M1/M2)

Independent probe `probe_r1_manifest.py` (drives only the public vault
surfaces — `project` / `verify_manifest`; not the slice harness), against
a fresh in-memory journal. Raw:

```
M1a honest vault: ok=True counts={}
M1a forged gap_event_ids=[999]: ok=False counts={'GAP_MANIFEST_MISMATCH': 1}
    finding GAP_MANIFEST_MISMATCH event_ids=(999,) filenames=()
M1b real hole event_id=3 manifest gap list=[3]
M1b hole hidden (gap_event_ids=[]): ok=False counts={'GAP_RANGE': 1, 'GAP_MANIFEST_MISMATCH': 1}
    finding GAP_RANGE event_ids=(3,) filenames=()
    finding GAP_MANIFEST_MISMATCH event_ids=(3,) filenames=()
M2 renamed note evt-000003-probe-renamed.md + manifest agreeing: ok=False counts={'NON_CANONICAL_FILENAME': 1}
    finding NON_CANONICAL_FILENAME event_ids=(3,) filenames=('evt-000003-probe-renamed.md',)
PROBE R1 RESULT: PASS (0 failing legs)
```

- **M1 (forged `gap_event_ids`)** — a clean vault verifies OK; a forged
  list is refused and **named** `GAP_MANIFEST_MISMATCH(999)`; a real hole
  hidden behind a cleared list is named **twice** (`GAP_RANGE` +
  `GAP_MANIFEST_MISMATCH`). The verifier recomputes from the journal.
- **M2 (non-canonical filename)** — a renamed note with the manifest
  edited to agree is refused and named `NON_CANONICAL_FILENAME` with the
  filename.
- A1 (`correlation_id` on a non-head row) remains **by design** — the
  manifest verifies the projection, not journal internals
  (`AUDIT_R1_MANIFEST.md` A1).

Targeted harness legs (verbose names): `test_forged_gap_event_ids_are_named`,
`test_hidden_gaps_name_both_the_hole_and_the_mismatch`,
`test_non_canonical_filename_is_named` → **3 passed**; whole battery
`tests/test_vault_manifest.py` → **25 passed** (0.78s, EXIT 0).

Vault separation / notes / additivity at the tip:
`tests/test_p_auto_5_vault.py tests/test_p_auto_5_fix.py tests/test_notes_dedup.py`
→ **48 passed** (EXIT 0); read-only + derived-view claims included in the
25 above (`test_verify_is_read_only_and_the_manifest_is_a_derived_view`,
`test_manifest_rerun_is_byte_identical`, `test_scratch_equals_incremental_claim`).

## 3. R-2 — producer-ref additivity (PASS)

`tests/test_b3_producer_ref.py` → **10 passed** (0.31s, EXIT 0),
including the payload key-set pin (`ADMISSION_PAYLOAD_KEYS`), the
separate-column additivity, fabrication-hunt and legacy-row semantics.
`gateway.py` diff = +9/0 single-writer, merged blob == line blob
(`35f9396`). NOT-topics absent. No re-derivation conflict with R-1/R-3/R-4.

## 4. R-3 — knobs + pin-chain (FAIL → pin-fixed; red→green re-derived)

**Pin-chain differential (independent probe `probe_r3_pin.py`, real
loopback socket accounting, port 443).** Same probe, two trees:

```
# PRE-FIX base (main@a8f0180)
bookkeeping opener.handlers: [... '_SameOriginRedirectHandler', 'PinnedHTTPSHandler', 'HTTPErrorProcessor']
dispatch chain https: ['HTTPSHandler', 'PinnedHTTPSHandler']
pinned_first? False  exact-type default in chain? True
pinned dial (https://probe-pin.invalid/) outcome: URLError | [Errno 11001] getaddrinfo failed
pinned loopback TCP hits=0 (must be >=1)
unpinned loopback TCP hits delta=0 (must be 0)
PROBE R3 PIN RESULT: FAIL                       (EXIT 1)  <-- reproduces MUST-FIX-1

# MERGED TIP (bafa728)
dispatch chain https: ['PinnedHTTPSHandler']
pinned_first? True  exact-type default in chain? False
pinned dial (https://probe-pin.invalid/) outcome: URLError | [SSL: UNEXPECTED_EOF_WHILE_READING] ...
pinned loopback TCP hits=1 (must be >=1)
unpinned dial (https://probe-unpinned.invalid/) outcome: URLError | [Errno 11001] getaddrinfo failed
unpinned loopback TCP hits delta=0 (must be 0)
PROBE R3 PIN RESULT: PASS                       (EXIT 0)
```

- **Pinned-first**: the `handle_open["https"]` chain is the pin alone;
  the exact-type default is purged (base: default first → shadowed).
- **Loopback hits**: the pinned dial lands on the loopback listener
  (1 TCP hit; the SSL error is the raw listener, i.e. a real dial);
  base = 0 hits + `gaierror` = the audited shadow.
- **Unpinned path unchanged**: same opener, `.invalid` DNS failure,
  zero loopback dials (additive-only).
- Harness leg `test_fix_pin_dispatch_pinned_first_and_dials_loopback`
  → PASSED; full `tests/test_p_auto_4_fix.py` → **13 passed**.

**Knobs handoff** — `tests/test_operator_knobs.py` → **8 passed**:
tighten applies at the CLI; widen refused with the named
`KNOB_WIDEN_REFUSED`; a tightened knob beside a widened one is not
clamped; absent `[autonomy_caps]` byte-identical to code defaults; the
shipped operator config is narrow and builds.

**Proxy-guard E2E** — `tests/test_proxy_path_e2e.py` → **3 passed**:
env proxy live by default machinery; guarded HTTP reaches origin with a
proxy configured; guarded HTTPS dials the origin, never the proxy.

## 5. R-4 — fault harness (FAIL → doc-fixed M1)

```
# guards, default suite (HERMES_FAULT_KILL unset)
$ $PY -m pytest tests/test_r4_fault_harness.py
13 passed in 0.19s                                     (EXIT 0)

# M1 control — flag set, plugin NOT loaded (no -p): inert
$ HERMES_FAULT_KILL=all $PY -m pytest tests/test_p_auto_6_loop.py
6 passed in 1.10s                                      (EXIT 0)

# ARMED — flag set + -p tests.fault_injection.plugin
$ HERMES_FAULT_KILL=all $PY -m pytest -p tests.fault_injection.plugin tests/test_p_auto_6_loop.py
FAILED tests/test_p_auto_6_loop.py::test_poison_task_quarantined_never_retried_silently
FAILED tests/test_p_auto_6_loop.py::test_loop_pattern_trips_detector_at_threshold_and_quarantines
FAILED tests/test_p_auto_6_loop.py::test_hung_fetch_deadline_fires_typed_transient_no_hang
FAILED tests/test_p_auto_6_loop.py::test_recovery_after_quarantine_legit_work_proceeds_and_idle_is_named
4 failed, 2 passed in 1.18s                            (EXIT 1)
```

Default-OFF holds (double-fenced: plugin not loaded without `-p`, and
`apply()` refuses without the env opt-in); armed, exactly the 4 claim
legs redden; the docfix now documents the load-bearing
`-p tests.fault_injection.plugin` (M1). Harness blobs at the tip are the
R-4b (doc-fixed) content: `kills.py 4d0a271`, `plugin.py a31dcfb`,
`__init__.py 0783dfe`, `test_r4_fault_harness.py f825d81`.

## 6. Patch-exactness & refusal re-scan

- Merged `main..HEAD` numstat is the arithmetic union of the line diffs;
  the two cross-line overlaps (`cli.py` 104/1+11/1=115/2; `http.py`
  10/7+17/0=27/7) auto-merged with both hunks present; every other file
  is byte-identical to its single-writer line blob (full table in
  `MERGE-LOG-RESIDUALS.md`).
- Conflict markers: `grep -rn '^<<<<<<<|^=======$|^>>>>>>>' src tests`
  → **empty**.
- Refusal re-scan: no merged line softens a refusal. The R1 verifier
  *adds* refusals (M1/M2); the pin fix only changes the dial target
  (allowlist/redirect/proxy behavior unchanged — `http.py:203-221`
  says so and §4's unpinned leg proves it); the R-4 diff is tests-only;
  R-2 is additive on a separate column; R-3b adds no new authority.
- Four audit docs present byte-identical to their source branches
  (blobs `2e0cde7`, `1c86eac`, `7a6a6a6`, `727c479`).
- NOT-topics (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`)
  absent from every diff — no STOP triggered.

## 7. Count lineage (reconciled)

| Source | Tests |
| --- | --- |
| BASE `main@a8f0180` (`--collect-only`) | 3686 |
| + `tests/test_vault_manifest.py` (R-1, new) | +25 |
| + `tests/test_b3_producer_ref.py` (R-2, new) | +10 |
| + `tests/test_operator_knobs.py` (R-3a, new) | +8 |
| + `tests/test_proxy_path_e2e.py` (R-3a, new) | +3 |
| + `tests/test_p_auto_4_fix.py` (R-3b, 12 → 13) | +1 |
| + `tests/test_r4_fault_harness.py` (R-4b, new) | +13 |
| **Merged tip** | **3746** |

60 = 25+10+8+3+1+13; 3686 + 60 = 3746 = JUnit `tests`. Zero skips in
both counts — the skip-count mismatch class is absent.

## 8. Residuals / NOTEs (documented, none introduced by this merge)

1. **R-3 port-form pin nuance (NOTE)** — production publishes the pin
   under the bare hostname (`live_fetch.py:136`,
   `parsed.netloc.split(":")[0]`) while `_lookup_pin` receives `req.host`
   (netloc incl. `:port`); a port-bearing URL therefore misses the pin
   and falls back to the DNS path (allowlist gate still applies). Probe
   leg 3: `https://probe-pin.invalid:443/` → `gaierror`, 0 loopback.
   **Pre-existing to FIX-PIN** (FIX-D wiring); no provider base URL
   carries an explicit port today. Candidate follow-up, not a STOP.
2. **R-2 NOTE** — `artifact_ids_json` has no independent size check at
   the persistence boundary (transitively bounded by the ≤4 KiB payload).
3. **R-4 S1/S2** — expected-red-count pin and static-vs-static seam line
   pins remain unfixed (declared scope in `AUDIT-R4-HARNESS-REDTEAM.md`).
4. **R-1 A1** — by-design invisibility of non-head, non-projected columns.
5. **R-4 N1..N4 / R-3 N2/N3 / R-2 NOTE 1..4 / R-1 residual** — carried
   verbatim in the four audit docs; unchanged by this merge.

## 9. Verdict & stop condition

**PASS.** All gates green; all four audits re-proved at the merged tip;
patch-exactness additive; four audit docs byte-identical; `main` verified
unmoved (`git rev-parse main` = `a8f018068e3c04b3160891ebd56cfd95d3590c95`);
remote `refs/heads/main` unchanged (`e4b276db...`, read-only ls-remote).
**STOPPED BEFORE PUSH — no push, no fetch, no platform-line change.**
