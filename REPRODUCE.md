# Reproduce Khwarizmi (judge path)

Requires Python 3.14 and `uv`. All commands run from the repository root.
On Windows consoles, set `$env:PYTHONUTF8 = '1'` first (one harness
prints non-ASCII glyphs; the scenarios themselves are encoding-clean).

```bash
uv venv --python 3.14
uv sync
.venv/Scripts/python.exe scripts/run_tests.py   # full suite: 4423 passed, 15 conditional skips (live legs; per merge-gate at ef41296; count carried — the demo merge adds demos, not tests; the cloud merge adds the 81-test provider battery)
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe scripts/break_it.py    # 8/8 refusal scenarios green
.venv/Scripts/python.exe -m pytest tests/test_p_auto_6_loop.py -q  # closed loop + fault injection
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe scripts/demo_judge.py             # judge demo: 51/51 checks, one replay digest
.venv/Scripts/python.exe scripts/demo_retraction_cone.py   # retraction demo: 40/40 checks, offline cone replay
```

What each step proves:

- `run_tests.py` — the certified control-plane suite (4,423 passed + 15 conditional skips, per merge-gate at ef41296), the
  basis of the production declaration in
  `docs/archive/CERT_GATE_RERUN_CERTIFICATION_2026-10-04.md`.
- `break_it.py` — 8 hostile scenarios (off-allowlist fetch, forged spans,
  retracted sources, forged gates, contradiction blocks) refused or
  escalated with recorded results; exit 0 only when every outcome matches
  its reference assertion.
- `test_p_auto_6_loop.py` — the autonomy loop end to end on fixtures
  (plan → dispatch → model stub → validate → gate → project) plus seeded
  fault injection (poison task, hung fetch, loop pattern) proving each
  safety envelope fires. Deterministic stub only; no network, no keys.
- `demo_judge.py` — the narrated end-to-end judge walkthrough (51/51
  checks): hermetic, offline, credential-free; two consecutive runs print
  the same replay digest, so "it ran twice in a row" is checkable rather
  than asserted.
- `demo_retraction_cone.py` — the S5 source-retraction cone replayed
  offline (40/40 checks): retract a source, invalidate the downstream
  dependency cone, supersede the contradiction it reached, and refuse a
  fresh citation of the retracted evidence.

Everything above runs offline except the two keyless scholarly APIs
(OpenAlex, PubMed) exercised by the marked live tests, which are
skippable via `HERMES_SKIP_LIVE_FETCH=1` with hermetic replay fixtures
covering the same paths.

## Watch it run

Recorded walkthrough (all three demos, narrated, exit 0 throughout):
https://github.com/ace2013hieco-aa/khwarizmi/releases/download/demo-2026-10-11/Demo.mp4
