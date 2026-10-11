# JUDGE-DEMO — recording checklist

Target: a recordable end-to-end walkthrough of the shipped system, under
five minutes, offline, credential-free. The demo is
[scripts/demo_judge.py](../../scripts/demo_judge.py); the transcript it
produced is [DEMO-TRANSCRIPT.txt](DEMO-TRANSCRIPT.txt); the two-run proof
is [TWO-RUN-PROOF.txt](TWO-RUN-PROOF.txt).

Worked example (this machine, 2026-10-11): **51/51 checks, exit 0, ~3.8 s**,
`REPLAY DIGEST: f360c174eb2bfc7ec158f56821b0e2e9b49edc452f4542f2a8e6b21d79e285cf`.

---

## 1. Pre-flight (5 minutes, before you hit record)

1. **Run it twice, back to back.** Not once. The point of the demo is that
   it replays: if the two runs disagree you must not record.
   ```bash
   cd <repo>
   PYTHONUTF8=1 .venv/Scripts/python.exe scripts/demo_judge.py   # Windows
   PYTHONUTF8=1 .venv/bin/python scripts/demo_judge.py           # POSIX
   ```
   Confirm on both runs: `RESULT: 51/51 checks passed`, `EXIT 0`, and the
   **same** `REPLAY DIGEST`.
2. **Check the exit code, not just the output.** `echo $?` must be `0`.
   A non-zero code with a cheerful-looking transcript is a failure:
   exit `1` means a check failed, exit `2` means the demo body raised.
3. **Close the network question on camera.** The demo blocks the socket
   layer in-process and proves it (Beat 2 prints
   `socket.create_connection -> NetworkBlocked`). Provider fetch and model
   legs are labeled `[STUB]`/`[SKIP]` on screen — say the word "stubbed"
   when you pass them, so nobody thinks a live call happened.
4. **No credentials are needed or read.** The operator token is an
   in-memory fixture registered by the script itself
   (`judge-demo-local-fixture`). If you see a prompt for a key, stop.
5. **Terminal hygiene for the recording:** font at least 14 pt, height
   ≈ 45 lines (the whole run is ~254 lines), scrollback clear, and a shell
   whose cwd is the repo root so the command you type matches the docs.
   `chcp 65001` on Windows, or use Windows Terminal (UTF-8 by default).

## 2. Shot list (with narration cues)

| Time | Beat | On screen | Say (one line) |
|---|---|---|---|
| 0:00 | 1 — the question | the question + `plan → dispatch → model-stub → validate → gate → project` | "This is what an operator asks; the loop answers it by advancing a typed state machine." |
| 0:10 | 2 — the frame | interpreter, `hermes` path, `:memory:`, `NetworkBlocked` | "Before believing anything, prove the frame: no network, no database file, one frozen clock." |
| 0:30 | 3 — the loop | six `PASSED` nodes from the closed-loop scenario | "Plan, dispatch, stub model, validate, gate, project — the whole loop, hermetic." |
| 0:50 | 4 — refusal 1 | `rejected code=ROLE`, `journal rows: 1 -> 2 (IntentRejected)`, `task rows: 0 -> 0` | "The model tier may propose, never decide: the intent is refused, and the refusal is recorded as data while nothing is admitted." |
| 1:10 | 5 — refusal 2 | `code=RATIONALE`, gate still `WAITING_HUMAN`, `0` verdict events | "The human boundary is bounded: a 5 KB rationale is refused before any write — and the same gate still resolves normally afterwards." |
| 1:40 | 6 — the battery | all 8 scenarios `PASS` + `summary: 8/8` | "Eight hostile-input scenarios, through the public surfaces only." |
| 2:20 | 7 — the vault | `verify OK (0 findings)`, then `TAMPERED_NOTE` with an event id and a file name | "The journal projects into notes and a derived-view manifest; when a human edits a note outside the projector, verification names it and refuses." |
| 3:00 | 8 — the numbers | three seeded faults `PASSED`, counts line | "Three seeded faults, three green detectors, zero silent retries — and the slice pins that it does not declare production." |
| 3:20 | wrap | 14 citations, `51/51`, `REPLAY DIGEST` | "Every repo line this run read is cited and re-proven; two consecutive runs print the same digest." |

Total: ~3.8 s of runtime. Budget the rest for narration — you have five
minutes, use the room.

## 3. Flake protocol (if it goes red)

1. **Do not re-run hoping.** Do not add retries, and do not paper over it.
   The demo is designed to be deterministic; a red run is information.
2. Capture three things verbatim: the exit code, the `FAILED:` line
   (the demo prints every failing check by name at the end), and the
   `REPLAY DIGEST`.
3. The likely classes, in order of probability:
   - **Wrong tree imported.** If `hermes` resolves outside this checkout,
     Beat 2 fails on purpose (`hermes is imported from THIS tree`). This
     happens when the venv carries an editable install pointing at another
     worktree — the canonical fix is to run from the repo that owns the
     venv, or ensure `PYTHONPATH=<repo>/src`, which the demo already does
     for its own subprocess legs.
   - **A cited oracle moved.** The citations are line-pinned; editing a
     test file re-points a citation and fails loudly. Re-read the file and
     update the pin — never delete the citation.
   - **A pre-existing red in a leg.** Check the leg's own exit code: the
     demo prints `rc=` per leg. A red leg is a repo condition, not a demo
     bug — report it as-is.
4. If any leg is flaky across two runs, **stop and report**; do not record.

## 4. Deliberate non-claims (keep these honest on camera)

- The demo proves **mechanism determinism** (frozen clock, `:memory:`,
  recomputed identities, replay digests). It does **not** claim scientific
  validity, and a green run is not evidence about any hypothesis.
- Stubbed legs mean **no live data** was fetched and **no model** reasoned.
  Do not narrate them as if they were live.
- The vault notes are a **derived view**, never authority. The refusal
  finding is the authority-bearing statement, not the note.
- The closed-loop leg runs the **shipped fixture scenario** (topic
  "CRISPR"); the operator question in Beat 1 is the framing, not the input
  to that fixture. Say so if a judge asks what the loop is actually
  chewing on.

## 5. Re-verification recipes (for a reviewer, not the recording)

- **Exit-code contract.** Two injected deviations were observed to fail
  closed: a drifted oracle line (`:307` → `:999`) produced
  `FAILED: citation tests/test_p_auto_6_loop.py:307 holds` and exit `1`;
  a `raise` inside the demo body produced the traceback and exit `2`.
  Restore is byte-identical (`sha256 65bbc086…`).
- **Digest stability.** Mask elapsed seconds and random scratch paths, hash
  the rest: two consecutive runs must be byte-identical after masking.
- **Legs in isolation** (each is independently runnable, same interpreter):
  ```bash
  PYTHONPATH=<repo>/src .venv/Scripts/python.exe -m pytest \
      tests/test_p_auto_6_loop.py -v -o addopts=
  PYTHONPATH=<repo>/src .venv/Scripts/python.exe scripts/break_it.py
  ```
