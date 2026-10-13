# Catalyst Grant — demo script & recording navigation

**Companion to:** [CATALYST-APPLICATION.md](CATALYST-APPLICATION.md) §8 and [CATALYST-QA-ANNEX.md](CATALYST-QA-ANNEX.md) §7.
**Recording:** https://github.com/ace2013hieco-aa/khwarizmi/releases/download/demo-2026-10-11/Demo.mp4 (HEAD-verified HTTP 200 on 2026-10-13; 15,232,993 bytes; URL unaltered).
**Source of truth:** [docs/judge-demo/DEMO-TRANSCRIPT.txt](docs/judge-demo/DEMO-TRANSCRIPT.txt) — 8 beats, 51/51 checks, `EXIT 0`, REPLAY DIGEST `f360c174eb2bfc7ec158f56821b0e2e9b49edc452f4542f2a8e6b21d79e285cf` (two consecutive runs, identical after masking; proof in [docs/judge-demo/TWO-RUN-PROOF.txt](docs/judge-demo/TWO-RUN-PROOF.txt)).

## 1. How to navigate the recording

The recording is the narrated judge walkthrough produced by `scripts/demo_judge.py`
(`docs/judge-demo/RECORDING-CHECKLIST.md` §2 is the shot list). **Beats are the
navigable unit**: each beat prints one narration line plus the real output of
what it just ran, and the transcript pins every expectation to a `path:line`
citation that the demo itself re-proves before printing it.

**Timestamps are deliberately blank.** An `mm:ss` mark requires watching
Demo.mp4, which this document's author did not do. Every row below therefore
carries a timestamp column marked `[mm:ss — owner to fill while watching]`.
An honest blank beats a fabricated number: no timestamp in this document was
estimated, inferred, or copied from the recording checklist's rehearsal table.

**Live-leg labels, repeated from the transcript (never laundered):**

- `[STUB] provider fetch` — the project's replay transports serve recorded bytes; no egress
- `[STUB] model calls` — `StubModelClient` answers deterministically; no model is asked
- `[SKIP] credential-bearing legs` — no key is read or required; the operator token is an in-memory fixture

## 2. Beat map (what plays → capability → Catalyst criterion → provenance)

| Beat | Timestamp | What plays | Capability shown | Catalyst criterion mapping | Demo leg / test / code (all verified at base `de1fd98`) |
|---|---|---|---|---|---|
| 1 — the question | `[mm:ss — owner to fill while watching]` | One operator question + the 6-stage contract + the three live-leg labels | A question enters one typed research program; the loop advances a state machine, not a chat | App §2 workflow (`CATALYST-APPLICATION.md:15`); Annex Q4 multi-step chain (`CATALYST-QA-ANNEX.md:42`) | Leg: `scripts/demo_judge.py:274` (`beat_question`); question `scripts/demo_judge.py:123`; stages `scripts/demo_judge.py:126`; labels `scripts/demo_judge.py:282-287` |
| 2 — the frame is hermetic | `[mm:ss — owner to fill while watching]` | Socket layer blocked before `hermes` imports; `:memory:` DB; frozen clock; this-tree import attestation | Prove the frame before believing the run; replay is byte-checkable, not asserted | App §3 trust/audit (`CATALYST-APPLICATION.md:21`); Technical Validation replay-digest claim (`CATALYST-APPLICATION.md`, "Technical Validation" section) | Leg: `scripts/demo_judge.py:294-332`; guard installed pre-import `scripts/demo_judge.py:88-90` (`NetworkBlocked` `scripts/demo_judge.py:80`); frozen clock `src/hermes/core/__init__.py:22` |
| 3 — the loop runs | `[mm:ss — owner to fill while watching]` | `pytest tests/test_p_auto_6_loop.py -v` — 6/6 PASSED, rc=0 | The shipped closed-loop scenario runs end to end: plan → dispatch → model-stub → validate → gate → project | Annex Q4 (`CATALYST-QA-ANNEX.md:42-52`); App §2 (`CATALYST-APPLICATION.md:15`) | Cited oracle: `tests/test_p_auto_6_loop.py:307`; leg runner `scripts/demo_judge.py:338-373` |
| 4 — refusal 1 (role) | `[mm:ss — owner to fill while watching]` | `apply_intent(ADMIT_TASK, proposed_by="RESEARCHER")` → `rejected code=ROLE`; journal `1 -> 2 (IntentRejected)`; task rows `0 -> 0` | The model tier may propose; it may never decide — the fail-closed role gate | App §2/§3 models-propose boundary (`CATALYST-APPLICATION.md:15`, `:21`); human-authority family | Cited oracles: `src/hermes/core/intents.py:144` (`internal_only`), `tests/test_gateway.py:170`; leg `scripts/demo_judge.py:379-421` |
| 5 — refusal 2 (bounded human gate) | `[mm:ss — owner to fill while watching]` | 5000-char rationale → `rejected=True code=RATIONALE` before any write; gate still `WAITING_HUMAN`; 0 verdict events; a normal rationale then resolves the same gate | The human-authority boundary is bounded (4 KiB payload discipline) and refusals never half-land | App §3 named refusal codes / bounded envelopes (`CATALYST-APPLICATION.md:21`); Annex Q5 (`CATALYST-QA-ANNEX.md:54`) | Cited oracle: `tests/test_controller.py:1001`; leg `scripts/demo_judge.py:427-483` |
| 6 — the refusal battery | `[mm:ss — owner to fill while watching]` | `scripts/break_it.py` — all 8 hostile-input scenarios `PASS` (`summary: 8/8`), rc=0, nothing written into the repo | Hostile inputs fail closed through the public surfaces only, offline, no model | App §5 fault-injection and adversarial batteries (`CATALYST-APPLICATION.md:31`); Annex Q5 (`CATALYST-QA-ANNEX.md:54-64`) | Cited oracles: `scripts/break_it.py:232` (S2 role), `scripts/break_it.py:571` (S8 oversize/secret), `scripts/break_it.py:630` (`main`); leg `scripts/demo_judge.py:489-520` |
| 7 — the vault verifies | `[mm:ss — owner to fill while watching]` | Journal projects to 16 notes + derived-view manifest; verify OK (0 findings); an outside edit to a note is caught and NAMED (`TAMPERED_NOTE`, event id + file); verification read-only | Verification recomputes the claim instead of trusting the derived view; the refusal finding is the authority-bearing statement | App §7 read surface — `hermes vault verify` refuses on journal/note mismatch (`CATALYST-APPLICATION.md:41`) | Cited oracles: `tests/test_vault_manifest.py:274`, `src/hermes/vault/manifest.py:104`; leg `scripts/demo_judge.py:550-605` |
| 8 — seeded-error numbers | `[mm:ss — owner to fill while watching]` | 3 seeded faults → 3 green detector legs; recovery PASSED; `test_no_production_declaration_in_this_slice` PASSED; counts parsed from the run, not typed in | The shipped envelopes fire in-loop; zero silent retries; the slice pins that it does not declare production | Technical Validation closed-loop 3/3 (`CATALYST-APPLICATION.md`, "Technical Validation" section); Annex §7 (`CATALYST-QA-ANNEX.md:88`) | Cited oracles: `tests/test_p_auto_6_loop.py:435`, `:468`, `:521`, `:571`, `:616`; leg `scripts/demo_judge.py:611-639` |

## 3. Under the hood — the exact path each beat drives

### Beat 1 → the question
`scripts/demo_judge.py:274` `beat_question` prints the operator question
(`scripts/demo_judge.py:123`), the six-stage contract
(`scripts/demo_judge.py:126`), and the three live-leg labels
(`scripts/demo_judge.py:282-287`) — each label asserted on screen by
`scripts/demo_judge.py:288-292` so a recording cannot show a live step that
did not run.

### Beat 2 → the hermetic frame
The socket layer is monkey-blocked **before** `hermes` is imported
(`scripts/demo_judge.py:88-90`; `NetworkBlocked` `scripts/demo_judge.py:80`);
`src` is forced onto `sys.path` (`scripts/demo_judge.py:92`); every clock is
`frozen_clock` (`src/hermes/core/__init__.py:22`, instant
`2026-01-01T00:00:00.000000+00:00`, `scripts/demo_judge.py:113`); the database
is `:memory:` (`scripts/demo_judge.py:303-312`); the tree attestation proves
`hermes` resolved from this checkout, never an editable install
(`scripts/demo_judge.py:296`, `:325-327`). Key test names: the in-process
guard checks at `scripts/demo_judge.py:323-332`.

### Beat 3 → the closed loop
Subprocess leg `scripts/demo_judge.py:359-362` runs the shipped golden
scenario `tests/test_p_auto_6_loop.py` with `PYTHONPATH=<tree>/src`
(`scripts/demo_judge.py:217-223`), `StubModelClient`
(`src/hermes/research/prompt_assembly.py:248`) standing in for the model tier
and `RecordedTransport` (`src/hermes/tools/providers/replay.py:313`) serving
recorded provider bytes. Under the hood the loop is `Controller.tick`
(`src/hermes/research/controller.py:934`) advancing typed tasks; every
mutation passes the single gateway `apply_intent`
(`src/hermes/research/gateway.py:4053`); rows are appended to the journal by
`src/hermes/persistence/repositories.py` and `src/hermes/core/events.py`. Key
test names: `test_closed_loop_plan_dispatch_stub_validate_gate_project`
(`tests/test_p_auto_6_loop.py:307`).

### Beat 4 → role refusal
`apply_intent` (`src/hermes/research/gateway.py:4053`) with
`proposed_by="RESEARCHER"` for an `internal_only` kind
(`src/hermes/core/intents.py:144`; the LLM-proposable complement is
`src/hermes/core/intents.py:124`) fails the role check
(`src/hermes/research/gateway.py:106` defines the `ROLE` code;
`src/hermes/research/gateway.py:229` `_require_role`), and the rejection is
journaled as data (`IntentRejected`), not silence. Key test names:
`tests/test_gateway.py:170` (`test_admit_task_internal_only`).

### Beat 5 → bounded human gate
`Controller.resolve_human_gate` (`src/hermes/research/controller.py:1764`)
submits the rationale through the event payload validator, whose cap is
`DEFAULT_PAYLOAD_MAX_BYTES = 4096`
(`src/hermes/persistence/event_validation.py:23`; size check
`src/hermes/persistence/event_validation.py:75-81`): the refusal
(`code=RATIONALE`) happens **before any write**, the gate stays
`WAITING_HUMAN`, and the follow-up normal verdict proves nothing was
half-landed. Key test names: `tests/test_controller.py:1001`
(`test_11_oversized_rationale_refused_with_specific_code`).

### Beat 6 → the refusal battery
`scripts/break_it.py` `main` (`scripts/break_it.py:630`) drives all eight
scenarios through the public surfaces: S1 enveloped hostile content
(inert), S2 role refusal (`scripts/break_it.py:232`), S3 provider allowlist,
S4 fabricated span (`dangling_span_ref`), S5 forged gate events (cannot
authorize), S6 open contradiction (completion denied), S7 retracted-source
citation (N9 fence, `EVIDENCE_DOES_NOT_RESOLVE`), S8 oversize + secret payload
(`scripts/break_it.py:571`). The repo-dirt guard
(`scripts/demo_judge.py:529-544`) proves the battery wrote nothing.

### Beat 7 → vault projection + verification
`project` (`src/hermes/vault/projection.py:800`) writes one note per journal
row and `write_cursor` (`src/hermes/vault/projection.py:895`) records the
cursor; `verify_manifest` (`src/hermes/vault/manifest.py:431`) recomputes
digests from disk and reports `TAMPERED_NOTE`
(`src/hermes/vault/manifest.py:104`, finding path
`src/hermes/vault/manifest.py:704`) naming the event id and file; verification
is read-only. Key test names: `tests/test_vault_manifest.py:274`
(`test_tampered_note_is_named`).

### Beat 8 → seeded-error numbers
The three seeded faults — poison task, loop pattern, hung fetch — are asserted
in-loop at `tests/test_p_auto_6_loop.py:435`, `:468`, `:521`; recovery after
quarantine at `:571`; the no-production boundary at `:616`. The beat's counts
are parsed from the leg output (`scripts/demo_judge.py:621-632`), never typed
in.

## 4. Adjacent evidence — measured in the application, not part of the recording

- **Reviewer independence** (Application §5 and Technical Validation 11/12 vs
  12/12; `CATALYST-QA-ANNEX.md:84`): `tests/cert_gate_rerun/test_reviewer_independence.py` —
  floors at `:48` and `:57`, union + disagreement at `:66`. Not a demo beat.
- **Digest fold under 5 injected corruptions** (`CATALYST-QA-ANNEX.md:87`):
  `tests/test_q04_review_candidates.py:272`
  (`class TestRecordSourceRetraction` at `:236`) — fail-closed, deterministic.
  Not a demo beat.

## 5. Deliberate non-claims (repeated from the recording checklist)

- The demo proves **mechanism determinism** (frozen clock, `:memory:`,
  recomputed identities, replay digests). It does **not** claim scientific
  validity, and a green run is not evidence about any hypothesis.
- Stubbed legs mean **no live data** was fetched and **no model** reasoned.
- The vault notes are a **derived view**, never authority; the refusal finding
  is the authority-bearing statement.
- The closed-loop leg runs the **shipped fixture scenario**; the operator
  question in Beat 1 is the framing, not the input to that fixture.
- The recording runs on **seeded/synthetic material**; it demonstrates
  control-plane handling, never evidence validity.

## 6. Governance note

This is the third human-owned root `CATALYST-*` document — the FRONT-1
exception family: `CATALYST-APPLICATION.md`, `CATALYST-QA-ANNEX.md`,
`CATALYST-DEMO-SCRIPT.md` (the first two exceptions are recorded in
`docs/MERGE-LOG-CAT-1.md` and `docs/MERGE-LOG-CAT-2.md`). None of the
`CATALYST-*` documents is a member of `GOVERNED_CORPUS_REFS`
(`src/hermes/research/corpus.py:118`, mirrored at
`src/hermes/persistence/corpus.py:84` — the P1a six plus the six-document B4
cohort) or of any B4 fixture source set
(`src/hermes/research/ref_graphs.py:162-196`); no test references any
`CATALYST-*` document.

License: Apache-2.0 (LICENSE).
