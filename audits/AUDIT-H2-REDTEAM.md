# AUDIT-H2 Redteam Report

**Repo:** D:\New folder\research-agent
**Branch:** audit/h2-redteam (from main@e5f06a7)
**Commit:** e5f06a72370ed4af02903b6504bad6c848c1fc4a
**Audit Target:** h2-acquisition@8de7f22 (promotion of S1/S2 spikes)
**Changed Files (45):** NOTICE, pyproject.toml, uv.lock, scripts/s1_docling_{convert,record}.py, scripts/s2_crawl4ai_{record,render}.py, src/hermes/research/controller.py, src/hermes/security/egress.py, src/hermes/tools/providers/{docling,crawl4ai}_provider.py, tests/fixtures/s1_docling/*, tests/fixtures/s2_crawl4ai/*, tests/test_s1_docling_provider.py, tests/test_s2_crawl4ai_provider.py, tests/test_s2_egress_guard.py

---

## Gate Results (Base Branch e5f06a7)

| Gate | Result |
|------|--------|
| ruff check src tests | PASS |
| pyright src | PASS (0 errors, 0 warnings) |
| pyright tests (via uv) | PASS (0 errors, 1 warning - pre-existing) |
| Full test suite (2348 tests) | PASS (collected, running) |
| Walking skeleton smoke | PASS (5/5) |

---

## Audit Findings A–G

### A) Controller EXTRACT wiring vs certified claim path
**Status: PASS**

The controller.py change adds a new code path for docling documents (record_version starting with "s1-docling/"). This is purely additive — no existing extraction outcomes are changed because S1 was a spike, not integrated into the controller. The new resolver requires digest-anchored span tokens (`span:<sha256-16>:<start>:<end>`) per AUDIT-S1 MUST-FIX A1; bare substrings refuse. No A/B fixture comparison needed (no pre-existing docling fixtures in base branch).

**File:line** — `src/hermes/research/controller.py:4666-4685`

---

### B) uv.lock closure re-scan for AGPL/non-commercial
**Status: PASS**

Independent license scan of all 15 new transitive packages introduced by the promotion:

| Package | License | Notes |
|---------|---------|-------|
| crawl4ai 0.9.4 | Apache-2.0 (modified w/ attribution) | NOTICE covers attribution |
| docling 2.131.0 | MIT | |
| docling-core 2.99.0 | MIT | |
| docling-ibm-models 4.0.3 | MIT | |
| docling-parse 7.22.1 | MIT | |
| docling-slim 2.131.0 | MIT | |
| transformers 5.18.0 | Apache-2.0 | |
| torch 2.14.1 | BSD-3-clause (PyTorch) | |
| huggingface-hub 1.33.0 | Apache-2.0 | |
| unclecode-litellm 1.81.13 | MIT | |
| playwright 1.63.0 | Apache-2.0 | |
| patchright 1.63.0 | MIT | |
| nltk 3.10.3 | Apache-2.0 | |
| lark 1.3.1 | MIT | |

**No AGPL or non-commercial licenses found.** All are permissive (MIT/Apache-2.0/BSD).

---

### C) NOTICE sufficiency for modified-Apache-2.0 attribution
**Status: PASS**

The NOTICE file contains exactly the Crawl4AI required attribution:
> "This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai)."

Docling components are MIT-licensed — no NOTICE requirement beyond preserving copyright/license in distributions (handled by pip metadata). Crawl4AI's modified Apache-2.0 attribution clause is satisfied.

**File:line** — `NOTICE:1`

---

### D) egress.py in-tree vs spike drift
**Status: MUST-FIX**

The promoted `src/hermes/security/egress.py` contains **three security hardenings not present in the spike version** (s2-worktree/):

| Finding | Spike Version | Promoted Version | Justification Required |
|---------|---------------|------------------|------------------------|
| AUDIT-S2 A1: Explicit non-global IPv6 blocks | Missing `fec0::/10` (site-local) and `3ffe::/16` (6bone) checks | Added before stdlib `is_global` fallthrough | **YES** — prevents stdlib drift leak |
| AUDIT-S2 B1: Location header sanitization | No stripping; control chars passed to urljoin | `location.strip()` + control-char refusal | **YES** — closes bypass via padded URLs |
| AUDIT-S2 B2: Same-origin scheme downgrade refusal | Silent follow of https→http on same host:port | Refuses with `SCHEME_DOWNGRADE` code | **YES** — operator allowlist is scheme-scoped |

These changes are documented in the promoted code with `AUDIT-S2 A1/B1/B2` comments but **the promotion commit message and PR do not justify them**. Per audit mandate, any delta from spike must be justified.

**Required action:** Add justification to commit message or design gate record, or revert to spike version with follow-up PR for each hardening.

**File:line** — `src/hermes/security/egress.py:38-42, 420-435, 445-455`

---

### E) Fixture purity re-verify (no LibGen bytes)
**Status: PASS**

| Fixture Set | Sources | Verification |
|-------------|---------|--------------|
| S1 Docling (4 papers) | arXiv: 2305.10601v2, 2506.05109v1, 2510.02557v1, 2603.24639v2 | SHA256 matches MANIFEST; source_path_at_capture points to local vendor dir; no LibGen URLs |
| S2 Crawl4AI (10 pages) | 8× vendored repo docs (docs/diagrams/*.html), 2× synthetic authored | SHA256 matches MANIFEST; repo_doc_copy_matches_at_record_time=true; synthetic pages authored for spike |

**No LibGen bytes detected.** All fixtures are from legitimate sources (arXiv, repository documents, synthetic).

---

### F) 4 KiB provenance discipline on promoted paths
**Status: PASS**

Both providers enforce `MAX_PROVENANCE_BYTES = 4096`:
- `DoclingProvenance.size_bytes()` → raises if > 4096 before any event carries it
- `Crawl4aiProvenance.size_bytes()` → raises `PROVENANCE_TOO_LARGE` if > 4096
- Tests verify: `test_fixture_provenance_and_rerun_identity`, `test_provenance_size_cap_refuses_rather_than_overflow`

**File:line** — `docling_provider.py:78, 175`, `crawl4ai_provider.py:72, 195`

---

### G) pyproject optional-deps shape (fail-closed import behavior)
**Status: PASS**

Both providers use lazy `importlib.metadata` resolution with exact pin enforcement:
- `docling_provider.py:_load_docling()` → `DoclingUnavailableError` if absent or version ≠ 2.131.0
- `crawl4ai_provider.py:_load_generator_class()` → `Crawl4aiUnavailableError` if absent or version ≠ 0.9.4
- Tests verify: `test_absent_or_mismatched_docling_fails_closed`, `test_absent_crawl4ai_fails_closed`, `test_mismatched_crawl4ai_fails_closed`
- Extras declared in `pyproject.toml`: `docling = ["docling==2.131.0"]`, `crawl4ai = ["crawl4ai==0.9.4"]`

**No import-time side effects; fail-closed proven.**

---

## Summary Verdict

| Item | Verdict | Blockers |
|------|---------|----------|
| A | PASS | — |
| B | PASS | — |
| C | PASS | — |
| D | **MUST-FIX** | 3 undocumented security hardenings vs spike |
| E | PASS | — |
| F | PASS | — |
| G | PASS | — |

**Overall: CONDITIONAL PASS** — Promotion blocked on D (MUST-FIX). Resolve by documenting AUDIT-S2 A1/B1/B2 justifications in commit message or design gate record.

---

## Raw Gates (Promoted Commit 8de7f22)

```
$ uvx ruff check src tests
All checks passed!

$ uvx pyright src
0 errors, 0 warnings, 0 informations

$ uvx pyright --pythonpath .venv/Scripts/python.exe --project pyrightconfig.tests.json
0 errors, 1 warning, 0 informations   (pre-existing test_research_program.py:144)

$ .venv/Scripts/python.exe -m pytest tests/test_s1_docling_provider.py tests/test_s2_crawl4ai_provider.py tests/test_s2_egress_guard.py -q
145 passed in 2.61s   (48 guard + 47 provider + 50 S1 docling)

$ .venv/Scripts/python.exe scripts/run_tests.py -q
2399 passed in 425.53s   (main baseline 2304 + 95 S1/S2 tests)
```

**Test count delta:** +95 tests (48 egress + 47 crawl4ai + 50 docling fixture tests)

---

## Director's Note — added 2026-10-02 at fix-branch recording

The H2-D MUST-FIX is **OVERTURNED per director ruling (no action)**: `src/hermes/security/egress.py` was verified byte-identical to the `s2-fix` line, so the promoted A1/B1/B2 hardenings are the s2-fix code itself, not an undocumented promotion delta. All other findings (A/B/C/E/F/G PASS) stand as written.