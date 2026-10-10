# Reproduce Khwarizmi (judge path)

Requires Python 3.14 and `uv`. All commands run from the repository root.
On Windows consoles, set `$env:PYTHONUTF8 = '1'` first (one harness
prints non-ASCII glyphs; the scenarios themselves are encoding-clean).

```bash
uv venv --python 3.14
uv sync
.venv/Scripts/python.exe scripts/run_tests.py   # full suite: 4308 passed, 16 skipped (live legs)
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe scripts/break_it.py    # 8/8 refusal scenarios green
.venv/Scripts/python.exe -m pytest tests/test_p_auto_6_loop.py -q  # closed loop + fault injection
```

What each step proves:

- `run_tests.py` — the certified control-plane suite (4,308 tests + 16 live skips), the
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

Everything above runs offline except the two keyless scholarly APIs
(OpenAlex, PubMed) exercised by the marked live tests, which are
skippable via `HERMES_SKIP_LIVE_FETCH=1` with hermetic replay fixtures
covering the same paths.
