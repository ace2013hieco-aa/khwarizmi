# Khwarizmi-research

Khwarizmi-research is a deterministic control plane for quantitative research: operator
questions enter as typed research programs, a lease-fenced controller advances them one
tick at a time through a single intent gateway (apply_intent), and every mutation lands
in an append-only journal with recorded provider replay. Models propose; they never decide.

## Demo

No recorded video ships in-repo. The runnable judge demo is scripts/demo_judge.py
(51/51 checks, exit 0, ~5 s, offline): plan, dispatch, model-stub, validate, gate,
project, plus the 8-scenario refusal battery. Transcript: docs/judge-demo/DEMO-TRANSCRIPT.txt;
two-run proof: docs/judge-demo/TWO-RUN-PROOF.txt; checklist: docs/judge-demo/RECORDING-CHECKLIST.md.

## Operate (quickstart) <a id="operate"></a>

```powershell
uv venv --python 3.14; uv sync
.venv/Scripts/hermes doctor
.venv/Scripts/python scripts/demo_judge.py
```

## Guarantees (certified only)

| Guarantee | Evidence |
|---|---|
| apply_intent is the sole mutation path; refusals return data (ROLE, OPERATOR, LOCK, PROPOSAL, RATIONALE, ...), never silent success | docs/STATE.md, docs/ARCHITECTURE.md 3.3 |
| P6 classification writer, N9 retraction-aware admission, P7 contradiction lifecycle CERTIFIED/CLOSED, tick-loop detector wiring CERTIFIED | docs/STATE.md, docs/archive/N9_MAINLINE_MERGE_CERTIFICATION_2026-09-19.md, docs/archive/P7_MAINLINE_CERTIFICATION_2026-09-19.md, docs/archive/POST_P6_TICK_LOOP_CERTIFICATION_2026-09-19.md |
| Structural program CLOSED (DG-2 through DG-6, S-1 through S-4, G-1; DG-5 intentional, no correction) | docs/STATE.md, docs/archive/HERMES_DG6_FINAL_ARCHITECTURE_CLOSURE_GATE_2026-09-21.md |
| Provider bytes replay identically through RecordedTransport | docs/STATE.md, docs/ARCHITECTURE.md 3.8 |

## Limits (what this does NOT guarantee)

- Replay proves byte/evidence determinism only: never scientific validity, never admissibility of retracted sources.
- No scientific-reproducibility claim. A green demo or suite is not evidence about any hypothesis.
- Vault notes, digests, rankings, and diagrams are derived views, never authority.
- Completion is denied while a contradiction is OPEN; only a ratified human verdict resolves it.
- Causal DIRECT/PARTIAL claims are inadmissible (no experiment registry); INFERRED/SPECULATIVE is the downgrade path.
- Platform planes (R1-R7/W/O) are landed but unreachable, except O2: not certified capabilities. Execution engines are external; hermes doctor probes the environment (runtime, config, database, sandbox runner, lockfile), not the engines.

## Map

Rules: AGENTS.md. Map: docs/ARCHITECTURE.md. Surfaces: docs/API.md. Certified now: docs/STATE.md.
Ratified contract: hermes_research_architecture_v6.md. Live sequence: ROADMAP.md. Decisions: docs/idr/.
History (closed audits/gates, moved here by git mv; root keeps active reference only): docs/archive/.

License: Apache-2.0 (LICENSE).
