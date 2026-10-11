# PLATFORM-DEMO — recording checklist

Target: a recordable walkthrough of the four platform planes, driven
**directly** (the way a test drives them), offline, credential-free. The
demo is [scripts/demo_platform.py](../../scripts/demo_platform.py); the
transcript it produced is [DEMO-TRANSCRIPT.txt](DEMO-TRANSCRIPT.txt); the
two-run + mutation proof is [TWO-RUN-PROOF.txt](TWO-RUN-PROOF.txt).

Worked example (this machine, 2026-10-11): **35/35 checks, exit 0, ~0.01 s**,
`REPLAY DIGEST: c5c13934d0842fc26690d11d1703a8fc4794eebf002ef62066c82077e9e2f825`.

---

## 1. Pre-flight (before you hit record)

1. **Run it twice, back to back.** Not once. The point of the demo is that
   it replays: if the two runs disagree you must not record.
   ```bash
   cd <repo>
   PYTHONUTF8=1 .venv/Scripts/python.exe scripts/demo_platform.py   # Windows
   PYTHONUTF8=1 .venv/bin/python scripts/demo_platform.py           # POSIX
   ```
   Confirm on both runs: `RESULT: 35/35 checks passed`, `EXIT 0`, and the
   **same** `REPLAY DIGEST`.
2. **Check the exit code, not just the output.** `echo $?` must be `0`.
   Exit `1` = a check failed, exit `2` = the demo body raised.
3. **Close the network question on camera.** The demo blocks the socket
   layer in-process and proves it (Beat 1 prints
   `socket.create_connection -> NetworkBlocked`). The model backend is a
   labelled **stub** — say the word "stubbed" when you pass Beat 2.
4. **No credentials are needed or read.** The planes carry no credential
   field; the operator token in the script is an in-memory fixture
   (`platform-demo-local-fixture`). If you see a prompt for a key, stop.
5. **Terminal hygiene:** font ≥ 14 pt, height ≈ 45 lines (the run is ~85
   lines), scrollback clear, cwd = repo root. `chcp 65001` on Windows, or
   use Windows Terminal (UTF-8 by default).

## 2. Shot list (with narration cues)

| Time | Beat | On screen | Say (one line) |
|---|---|---|---|
| 0:00 | 1 — the frame | interpreter, `hermes` path, frozen clock, `NetworkBlocked` | "Before believing anything, prove the frame: no network, one frozen clock, no store." |
| 0:15 | 2 — the model plane | `PROPOSAL from stub/m1`, the structured draft, `account seq=0 attempt=1 outcome=OK`, `160 tokens / 0.12 usd` | "Config picks the tier → provider:model; a stub backend answers; the plane accounts every attempt and verifies no call went untracked." |
| 0:40 | 3 — the capability plane | `OBSERVATION status=OK`, `envelope complete=True authority=GRANTED`, then `REFUSAL code=ROLE` for the ungranted caller | "One gated execution path: declare, grant, gate, and record a who/why/authority envelope — and an ungranted caller is denied by default, as data." |
| 1:05 | 4 — the runtime plane | `state=SUCCEEDED`, the admitted proposal, `delegation … DONE/SUCCEEDED`, `checkpoint … terminal=True`, `resume … digest_match=True` | "One bounded loop emits intent proposals only; a delegation is a child task; a checkpoint resumes to the same digest." |
| 1:35 | 5 — the governance plane | `WEB_SEARCH … ALLOWED`, then three refusals: `ROLE/AUTHORITY`, `OPERATOR/CREDENTIAL`, `PROPOSAL/RECORDED_DECISION` | "Before any consequence lands, authority is decided: agent authority passes; a human surface needs a human, a credential, and a bound decision." |
| 2:00 | 6 — refusals are data | two `MALFORMED_PAYLOAD` refusals at two planes | "Every plane refuses a malformed request as a value, never an exception." |
| 2:15 | wrap | 7 citations, `35/35`, `REPLAY DIGEST` | "Every repo line this run read is cited and re-proven; two consecutive runs print the same digest." |

Runtime is ~0.01 s. Budget the rest for narration.

## 3. Flake protocol (if it goes red)

1. **Do not re-run hoping.** The demo is deterministic; a red run is
   information. Do not add retries.
2. Capture three things verbatim: the exit code, the `FAILED:` line, and
   the `REPLAY DIGEST`.
3. Likely classes, in order:
   - **Wrong tree imported.** If `hermes` resolves outside this checkout,
     Beat 1 fails on purpose (`hermes is imported from THIS tree`).
   - **A cited oracle moved.** Citations are line-pinned; editing a plane
     source re-points a citation and fails loudly. Re-read and update the
     pin — never delete the citation.
4. If any beat is flaky across two runs, **stop and report**; do not record.

## 4. Deliberate non-claims (keep these honest on camera)

- The demo proves **mechanism determinism** (frozen clock, in-memory state,
  recomputed identities, replay digests). It does **not** claim scientific
  validity, and a green run is not evidence about any hypothesis.
- The model backend is a **stub**: **no live model** was asked, **no
  network** was reached, **no key** was read. Do not narrate Beat 2 as if a
  model reasoned.
- The capability invoked is a **local echo**: it proves the gated path
  (declare → grant → gate → envelope), not any real capability's result.
- The orchestration API in the demo is an **in-process stub** that uses the
  real spine **value types** (content-addressed identity, duplicate
  detection) — no database is written and no journal row is appended. The
  runtime plane holds no store; checkpoint/delegation state is in-memory.
- The stack is **unwired**: this demo drives the planes **directly**, the
  way a test does. It does **not** wire O1/O3/O4/O5 into production, and the
  deferral stands.
- The governance verdicts are decisions about **authority over a governed
  action**, not judgments about evidence, truth, or scientific merit.

## 5. Re-verification recipes (for a reviewer, not the recording)

- **Exit-code contract (mutation, one knob).**
  ```bash
  PYTHONUTF8=1 .venv/Scripts/python.exe scripts/demo_platform.py                 # EXIT 0
  DEMO_PLATFORM_MUTATION=check PYTHONUTF8=1 .venv/Scripts/python.exe scripts/demo_platform.py   # EXIT 1
  DEMO_PLATFORM_MUTATION=raise PYTHONUTF8=1 .venv/Scripts/python.exe scripts/demo_platform.py   # EXIT 2
  ```
  `check` fails exactly one ledger check (the happy path is untouched);
  `raise` raises inside the demo body and prints the traceback.
- **Digest stability.** Mask elapsed seconds and scratch paths, hash the
  rest: two consecutive runs must be byte-identical after masking.
- **The planes in isolation** (each is independently runnable, same
  interpreter): the demo imports the planes directly —
  `hermes.tools.models.router`, `hermes.tools.capabilities.{registry,invoke}`,
  `hermes.agents.runtime.{run,checkpoint,delegate}`, `hermes.governance.authority`.
