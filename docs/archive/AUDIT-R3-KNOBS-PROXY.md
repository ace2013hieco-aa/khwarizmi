# AUDIT-R3 knobs+proxy — redteam findings only, no code

Repo: `D:\New folder\research-agent`
Branch: `audit/r3-knobs` from `main` @ `a8f018068e3c04b3160891ebd56cfd95d3590c95` (2026-10-04, `test(platform): allowlist eval hostile/import_gate…`)
Worktree (isolated, unmodified base): `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/audit-r3-knobs-wt` @ `a8f0180`, `git status --short --branch` clean (`## audit/r3-knobs`).
Slice under audit: `51a4a99d2eea97d3a5fceab30df8c57c3edcbef4` (`feat(cli): read the operator knobs from config; prove the proxy path E2E (R-3)`).
Diff: `a8f0180...51a4a99` = 5 files, 507 insertions(+), 16 deletions(-): `src/hermes/cli.py |12`, `src/hermes/research/autonomy_caps.py |28`, `src/hermes/tools/providers/http.py |17 (comment-only)`, `tests/test_operator_knobs.py 262`, `tests/test_proxy_path_e2e.py 204`.
NOT-topics (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`): absent from `git diff --name-only` and from `git diff | Select-String` — no STOP triggered.
Constraints: localhost/loopback probes only (127.0.0.1 listeners, `*.invalid` hosts, patched `getaddrinfo` for test hosts only); no public egress; probes live in `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/audit_{a_pin,b_knobs,c_proxy}.py` (outside repo, not committed).
Role: redteam auditor. Findings only, no code. Python 3.14.1 (`D:\New folder\research-agent\.venv\Scripts\python.exe`), `PYTHONPATH=<worktree>/src`.

## Verdict: FAIL (1 MUST-FIX) — slice PASS for its 3 claims, side-finding FAILs the dial property

- Knobs handoff (CLI tighten/widen/absent): PASS (confirmed on base red + slice green via independent probe, not the slice harness).
- Proxy guard independence: PASS (rebuilt from scratch with distinct hosts/body — guard holds on unmodified base).
- Default-golden byte-identity: PASS (absent == code defaults over all 5 builders + controller internals).
- Pin-shadowing (FIX-D): FAIL — CONFIRMED on unmodified base AND on the slice (independent probe, different host/listener). Breaks `check-time == dial-time`. Graded MUST-FIX, not fixed here per STOP condition.

## MUST-FIX (1, minimal)

- MUST-FIX-1 (severity: High — DNS-rebinding TOCTOU): FIX-D pinned dial is shadowed by the default `HTTPSHandler` on CPython 3.14 through the module opener, so the vetted-pin dial is never the code path a request takes. `src/hermes/tools/providers/http.py:189-199` drops the exact-type default from `opener.handlers` bookkeeping but `opener.handle_open["https"]` still holds `['HTTPSHandler','PinnedHTTPSHandler']` with the default FIRST; a pinned host dials via default DNS (`gaierror`, 0 loopback hits) instead of `_PinnedHTTPSConnection`. Consequence: S2 `check-time == dial-time` not enforced through `_OPENER`, though `_AllowlistedTransport` vetting/refusal still holds. Fix needs its own gate record: make the pinned handler authoritative on the dial path (e.g. unregister the default from the `handle_open` chain or route `https_open` through the pin first), additive-only, no behavior change to allowlist/redirect/proxy; add socket-accounting dial-target test (pinned host lands on loopback, unpinned path unchanged). Do NOT bundle with knobs/proxy.

## SHOULD-FIX (0) / NOTE (3)

- NOTE-1: `src/hermes/tools/providers/http.py:166` slice change is comment-only (mechanism note + outcome pinned by socket accounting). No behavior change — correct scope.
- NOTE-2: `src/hermes/research/autonomy_caps.py:259/275` base already refused widen loudly but unnamed (`P-AUTO-4 {name} widens…`); slice only adds the named code `KNOB_WIDEN_REFUSED` (`:157`, exported `:109`, embedded `:266/:287`). Naming is the fix, not new refusal semantics.
- NOTE-3: slice `tests/test_proxy_path_e2e.py` docstring already discloses the shadowing (`FIX-D pin deliberately NOT used… reported separately`). Disclosure is accurate; grading it MUST-FIX here does not contradict the slice.

## (A) Pin-shadowing — reproduced on unmodified base (independent probe)

Probe: `audit_a_pin.py` (distinct host `pin-shadow-audit.invalid`, fresh loopback `HitListener`, `pin_resolver=lambda h: 127.0.0.1`, patched `getaddrinfo` to fail for the test host only). Base `src/hermes/tools/providers/http.py:160 (_build_opener)`, `:273 (PinnedHTTPSHandler)`, `:302 (_OPENER)`.

Raw (base @ `a8f0180`, `hermes from: …/audit-r3-knobs-wt/src/hermes/tools/providers/http.py`):

```
bookkeeping opener.handlers: ['UnknownHandler','HTTPHandler','HTTPDefaultErrorHandler','FTPHandler','FileHandler','DataHandler','_SameOriginRedirectHandler','PinnedHTTPSHandler','HTTPErrorProcessor']
dispatcher chain https_open order: ['HTTPSHandler','PinnedHTTPSHandler']
has_default_https: True has_pinned: True
pinned_first? False
default_first? True
exact-type default in bookkeeping? False
PinnedHTTPSHandler in bookkeeping? True
dial outcome: URLError | reason: gaierror(11001,'getaddrinfo failed (audit probe: origin unresolvable)')
origin TCP hits=0 (pinned dial would hit >=1; shadowed default dial hits 0 + gaierror)
CONCLUSION: PIN SHADOWED — default HTTPSHandler won, pinned dial never consulted
```

Same probe with `PYTHONPATH=D:/New folder/research-agent/.worktrees/operator-knobs/src` (slice `51a4a99`) reproduces byte-identically (same chain order, same `gaierror`, `hits=0`). Adjudication: CONFIRMED on both main and slice → MUST-FIX-1. Existing FIX-D evidence (`test_d_opener_routes_pinned_hosts_through_pin_handler`) is construction-level (`PinnedHTTPSHandler in kinds`) and does not observe the dispatcher chain or dial target.

## (B) Knob matrix re-derived (tighten/widen/absent x deadline/rates) — independent probe, real hermes.toml

Probe: `audit_b_knobs.py` (real `hermes.toml` files in `tempfile` dirs, `cli.main`, `Controller.run` capture, `build_*` + `build_live_fetch_wiring` limiter). Base refs: `src/hermes/cli.py:469 (def _run)`, `:493 (ctrl = Controller(conn, project_id=args.project_id))` — no `autonomy_operator`; `src/hermes/research/autonomy_caps.py:245 (narrow_int)`, `:265 (narrow_float)`, `:671/:695/:714/:743/:750 (builders)`, `:162 (DEFAULT 300.0)`; `src/hermes/research/live_fetch.py:151/165/278`, `src/hermes/config.py:91`; `src/hermes/research/controller.py:705/730`.

Raw (base):

```
KNOB_WIDEN_REFUSED absent on base: ImportError (expected)
B1 tighten-deadline-via-CLI: rc=0 controller_deadline=300.0 (base IGNORED => 300.0, fixed => 30.0)
B2 config accepts widen value: 600.0 (file range-check only)
B2 widen-deadline-via-CLI: rc=0 (…) out='Ran 0 tick(s) for project p1: …' controller_deadline_seen=300.0 (base => 0 no refusal; fixed => 1 KNOB_WIDEN_REFUSED)
B3 narrow builder tighten: wallclock=30.0 (expect 30.0)
B3 widen builder refused: 'P-AUTO-4 overall_deadline_seconds=600.0 widens the code-owned ceiling 300.0 …' has_named_code=False
B3 rate widen refused unnamed? has_named_code=False msg='P-AUTO-4 openalex_rps=50.0 widens the code-owned ceiling 5.0 …'
B4 rate tighten reaches limiter: 2 grants then granted=False reason='daily_cap_exhausted' (expect False daily_cap_exhausted)
```

Same probe on slice worktree (green legs, not the slice harness):

```
KNOB_WIDEN_REFUSED present: KNOB_WIDEN_REFUSED
B1 tighten-deadline-via-CLI: rc=0 controller_deadline=30.0
B2 widen-deadline-via-CLI: rc=1 out='Error: P-AUTO-4 KNOB_WIDEN_REFUSED: overall_deadline_seconds=600.0 widens the code-owned ceiling 300.0 …'
B3 widen builder refused: 'P-AUTO-4 KNOB_WIDEN_REFUSED: overall_deadline_seconds=600.0 …' has_named_code=True
```

Adjudication: base CLI ignores `[autonomy_caps]` (tighten 30→300, widen 600→rc 0); builders already narrow-only but unnamed; live-fetch rate path already wired (B4 green pre/post). Slice handoff CONFIRMED: tighten applies, widen refused loudly with the named code, no silent clamp. File:line for handoff on slice (from diff): `src/hermes/cli.py:502-503 (autonomy_operator=cfg.autonomy_caps)`, `src/hermes/research/autonomy_caps.py:157/266/287`.

## (C) Proxy proof independence — rebuilt from scratch (distinct harness)

Probe: `audit_c_proxy.py` (different hosts `audit-c-origin.invalid`/`audit-c-dead.invalid`, different origin body `b"audit-ok-c"`, different `HitListener` class/timing, `HTTPS_PROXY/HTTP_PROXY` + lowercase variants). Base `src/hermes/tools/providers/http.py:181-187 (empty ProxyHandler({}) suppresses env-reading default)`.

Raw (base @ `a8f0180`):

```
C0 teeth default-machinery contacts proxy: True hits=1 (must be True, else listener dead)
C1 guarded HTTP reaches origin: status=200 body_ok=True proxy_hits=0 (must be 0)
C1 PASS
C2 https pinned-origin dial: ProviderError (expected, raw TCP no TLS) origin_hits=1
C2 origin dialed=True origin_hits=1 proxy_hits=0 (expect True/>=1 and 0)
C2 PASS
C3 dead origin ProviderError (expected): 'connection error for https://audit-c-dead.invalid/'
C3 proxy silent on unresolvable origin: before=0 after=0 (must be equal)
C3 PASS
PROBE C DONE (independent harness, distinct hosts/body)
```

Adjudication: PASS — guard holds without the slice's exact harness (socket accounting at both destinations, never handler-list inspection). Teeth leg proves the env proxy was live, so silence is a fact. Slice `http.py` comment-only change is consistent (no behavior delta to re-prove).

## (D) Default-golden byte-identity re-derived

Same `audit_b_knobs.py` tail (base):

```
D1 absent==AutonomyCapsConfig(): True
D1 build_envelope: absent==None? True default==None? True
D1 build_wallclock: absent==None? True default==None? True
D1 build_retry_caps: absent==None? True default==None? True
D1 build_loop_threshold: absent==None? True default==None? True
D1 build_rate_profiles: absent==None? True default==None? True
D1 default deadline: 300.0 expect 300.0
D2 controller wallclock equal? True envelope equal? True loop equal? True
```

Adjudication: PASS — absent `[autonomy_caps]` carries code-owned defaults byte-identically (all 5 builders + `Controller._wallclock/_budget.envelope/_loops.repeat_threshold`).

## Gates (unmodified base worktree, committed content @ a8f0180; 11 files + ruff + pyright src)

11 files = `test_p_auto_4_caps` + `test_p_auto_4_fix` + `test_p_auto_3_live_fetch` + `test_config` + `test_provider_ratelimit` + `test_provider_hazards` + `test_provider_walk` + `test_research_sources` + `test_s2_egress_guard` (9-file batch) + `test_cli` + `test_controller`. `PYTHONPATH=<worktree>/src`, `python -m pytest -p no:cacheprovider --tb=short`.

```
# 9-file batch
$ python -m pytest tests/test_p_auto_4_caps.py tests/test_p_auto_4_fix.py tests/test_p_auto_3_live_fetch.py tests/test_config.py tests/test_provider_ratelimit.py tests/test_provider_hazards.py tests/test_provider_walk.py tests/test_research_sources.py tests/test_s2_egress_guard.py -p no:cacheprovider --tb=short
........................................................................ [ 20%]
........................................................................ [ 40%]
........................................................................ [ 60%]
........................................................................ [ 80%]
....................................................................     [100%]
356 passed in 9.94s
EXIT:0

# test_cli
$ python -m pytest tests/test_cli.py -p no:cacheprovider --tb=short
...............................                                          [100%]
31 passed in 8.91s
EXIT:0

# test_controller (slow leg)
$ python -m pytest tests/test_controller.py -p no:cacheprovider --tb=short
........................................................................ [ 66%]
.....................................                                    [100%]
109 passed in 437.05s (0:07:17)
EXIT:0

# total 11 files: 356 + 31 + 109 = 496 passed, 0 failed

$ uvx ruff check src tests
All checks passed!
EXIT:0

$ uvx pyright src
0 errors, 0 warnings, 0 informations
EXIT:0
```

Counts: `tests/test_p_auto_4_caps.py: 26` collected; full 11-file total `496 passed`. File:line anchors: `src/hermes/cli.py:493`, `src/hermes/research/autonomy_caps.py:96/157(absent on base)/245/265/671/695/714/743/750`, `src/hermes/tools/providers/http.py:160/181-187/189-199/273/302`, `src/hermes/research/live_fetch.py:151/165/278`, `src/hermes/config.py:91`, `src/hermes/research/controller.py:705/730`.

## Scope

LOCAL-ONLY, NO PUSH. Single doc commit on `audit/r3-knobs`. No `src/` or `tests/` touched in this worktree (`git status` clean except this doc before commit).
