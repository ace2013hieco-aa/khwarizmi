#!/usr/bin/env python3
"""JUDGE-DEMO - the narrated end-to-end walkthrough (shortlist recording).

One deterministic run, under five minutes, offline, credential-free. It
walks the arc a judge needs to see, in order:

  BEAT 1  the question        - what an operator actually asks the system
  BEAT 2  the frame           - prove the run is hermetic before believing
                                anything that follows
  BEAT 3  the loop runs       - plan -> dispatch -> model-stub -> validate
                                -> gate -> project, on the shipped
                                closed-loop scenario
  BEAT 4  refusal #1          - an agent proposes an internal-only intent
  BEAT 5  refusal #2          - an oversize rationale at the human gate
  BEAT 6  the refusal battery - all 8 hostile-input scenarios, live
  BEAT 7  the vault verifies  - project, verify OK, then catch an edit
                                made outside the projector and NAME it
  BEAT 8  seeded-error numbers- the three seeded faults and their counts

Every beat prints one line of narration plus the REAL output of the thing
it just ran. Nothing is hard-coded as "expected": the seeded-error numbers
and the scenario tallies are parsed from the runs themselves.

Hermetic by construction
------------------------
The socket layer is blocked BEFORE ``hermes`` is imported (a demo that
silently reached the network would not be replayable by a judge offline).
The database is ``:memory:``; every clock is frozen at one instant; the
only files written are notes in a scratch directory this script removes
before it exits; no credential is read or required (the operator token is
a local fixture registered in memory by this script, labeled as such).

Live legs are LABELED, never faked: provider fetch and model calls are
served by the project's replay/refusing transports and its stub model
client. Those labels are printed on screen and asserted below, so a
recording can never show a live step that did not run.

Self-verifying
--------------
The script carries a check ledger and an exit-code contract: 0 = every
check passed, 1 = at least one check failed, 2 = the demo body raised
(traceback printed, never swallowed). Every repo file it reads to derive
an expectation is cited as ``path:line`` and the citation is PROVEN by
re-reading that exact line, so a drifted oracle fails the demo loudly
instead of silently shifting the story.

Replay determinism
------------------
Every line this script emits is hashed (after masking clock/temp values)
into a REPLAY DIGEST. Two consecutive runs must print the same digest:
running it twice in the same environment is byte-identical evidence, and
the digest is what makes "it ran twice in a row" checkable rather than
asserted.

Run (from the repository root, with the project venv):

  .venv/Scripts/python.exe scripts/demo_judge.py         # Windows
  .venv/bin/python scripts/demo_judge.py                 # POSIX
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Beat 1a: the hermetic guard, installed BEFORE hermes is imported ──


class NetworkBlocked(RuntimeError):
    pass


def _blocked_network(*_args: object, **_kwargs: object) -> Any:
    raise NetworkBlocked("JUDGE-DEMO is hermetic: network use refused")


socket.socket = _blocked_network              # type: ignore[assignment,misc]
socket.create_connection = _blocked_network   # type: ignore[assignment]
socket.getaddrinfo = _blocked_network         # type: ignore[assignment]

sys.path.insert(0, str(REPO_ROOT / "src"))

from hermes.core import frozen_clock  # noqa: E402
from hermes.core.intents import Intent, IntentKind  # noqa: E402
from hermes.core.task_status import TaskStatus  # noqa: E402
from hermes.persistence.database import connect  # noqa: E402
from hermes.persistence.migrations import migrate_to_latest  # noqa: E402
from hermes.persistence.repositories import (  # noqa: E402
    EventRepository,
    OperatorCredentialRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.research.controller import Controller  # noqa: E402
from hermes.research.gateway import (  # noqa: E402
    GatewayRejection,
    apply_intent,
)
from hermes.vault.manifest import verify_manifest  # noqa: E402
from hermes.vault.projection import project, write_cursor  # noqa: E402

CLOCK = "2026-01-01T00:00:00.000000+00:00"
PROJECT_ID = "p1"
OP_ID = "judge-op"
# Local fixture credential: registered in memory by this script, never a
# real secret, never read from the environment or from disk.
OP_TOKEN = "judge-demo-local-fixture"

BUDGET_SECONDS = 300.0
LEG_TIMEOUT_SECONDS = 240

QUESTION = ("Does a low-volatility regime condition the momentum-to-reversal "
            "flip in the cross-section?")

STAGES = ("plan", "dispatch", "model-stub", "validate", "gate", "project")

# The shipped hermetic harnesses this demo drives (subprocess legs).
LOOP_TEST = "tests/test_p_auto_6_loop.py"
BATTERY = "scripts/break_it.py"

# Node ids inside the closed-loop scenario, cited to the source that
# defines them (each citation is proven below, never trusted).
CLOSED_LOOP_NODE = "test_closed_loop_plan_dispatch_stub_validate_gate_project"
SEEDED_FAULTS = (
    ("poison task (quarantined, never retried silently)",
     "test_poison_task_quarantined_never_retried_silently"),
    ("loop pattern (detector trips at threshold, quarantine + named note)",
     "test_loop_pattern_trips_detector_at_threshold_and_quarantines"),
    ("hung fetch (deadline fires, typed TRANSIENT, no hang)",
     "test_hung_fetch_deadline_fires_typed_transient_no_hang"),
)
RECOVERY_NODE = "test_recovery_after_quarantine_legit_work_proceeds_and_idle_is_named"
BOUNDARY_NODE = "test_no_production_declaration_in_this_slice"

# ── episode capture: everything printed, for the replay digest ──

EPISODE: list[str] = []


def out(text: str = "") -> None:
    print(text, flush=True)
    EPISODE.append(text)


def banner(title: str) -> None:
    out("-" * 74)
    out(title)


# ── the check ledger ──

CHECKS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((label, bool(ok), detail))
    mark = "[PASS]" if ok else "[FAIL]"
    out(f"  {mark} {label}" + (f" - {detail}" if detail else ""))
    return bool(ok)


def passed() -> int:
    return sum(1 for _, ok, _ in CHECKS if ok)


# ── repo citations: every oracle read is proven line-by-line ──

CITATIONS: list[str] = []


def cite(rel: str, needle: str, expect_line: int | None = None) -> str:
    """Prove that ``rel`` contains ``needle`` at ``expect_line``.

    Returns the ``path:line`` citation for the transcript. A wrong line,
    a moved needle or a missing file is a FAILING check - the demo's
    expectations are never taken on faith.
    """
    path = REPO_ROOT / rel
    if not path.exists():
        check(f"citation {rel} exists", False, "file not found")
        return f"{rel}:MISSING"
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    found = None
    for number, line in enumerate(lines, start=1):
        if needle in line:
            found = number
            break
    if found is None:
        check(f"citation {rel}:{expect_line} holds", False,
              f"needle {needle!r} not present")
        return f"{rel}:MISSING"
    ok = expect_line is None or found == expect_line
    check(f"citation {rel}:{found} holds", ok,
          "" if ok else f"expected line {expect_line}, found {found}")
    citation = f"{rel}:{found}"
    CITATIONS.append(citation)
    return citation


# ── subprocess legs ──

LEGS: list[tuple[str, int, float]] = []


def leg_env() -> dict[str, str]:
    """Environment for a leg: this tree's ``src`` wins over any editable
    install of the package (which would otherwise import another checkout)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONUTF8"] = "1"
    return env


def run_leg(name: str, argv: list[str]) -> tuple[int, str, float]:
    """Run one hermetic harness in a subprocess; return (rc, output, secs)."""
    started = time.perf_counter()
    proc = subprocess.run(
        argv, capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=str(REPO_ROOT), env=leg_env(),
        timeout=LEG_TIMEOUT_SECONDS, check=False)
    elapsed = time.perf_counter() - started
    output = (proc.stdout or "") + (proc.stderr or "")
    LEGS.append((name, proc.returncode, elapsed))
    for line in output.strip().splitlines():
        out(f"    | {line.rstrip()}")
    return proc.returncode, output, elapsed


def node_status(output: str) -> dict[str, str]:
    """Parse ``::name STATUS`` out of a pytest -v run (no guessing)."""
    found: dict[str, str] = {}
    for match in re.finditer(r"::(\w+)\s+(PASSED|FAILED|ERROR|XFAIL|SKIPPED)",
                             output):
        found[match.group(1)] = match.group(2)
    return found


# ── shared fixture: one in-memory database for the inline beats ──


def make_db() -> Any:
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create(PROJECT_ID, "Judge Demo")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Judge Demo Operator (local fixture)")
    conn.commit()
    return conn


def journal_count(conn: Any) -> int:
    return EventRepository(conn).count()


def task_count(conn: Any) -> int:
    return conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]


# ── BEAT 1: the question ──


def beat_question() -> None:
    banner("BEAT 1 - THE QUESTION")
    out("  > one operator question enters one typed research program")
    out(f"  question: {QUESTION}")
    out("  the loop answers it by advancing a typed state machine, one tick "
        "at a time")
    out("  stages: " + " -> ".join(STAGES))
    out("  LIVE LEGS (labeled, never faked):")
    out("    [STUB] provider fetch - the project's replay transports serve "
        "recorded bytes; no egress")
    out("    [STUB] model calls - StubModelClient answers deterministically; "
        "no model is asked")
    out("    [SKIP] credential-bearing legs - no key is read or required; "
        "the operator token below is an in-memory fixture")
    labels = [line for line in EPISODE
              if line.strip().startswith(("[STUB]", "[SKIP]"))]
    check("the question and the 6-stage contract are on screen",
          len(STAGES) == 6 and any(QUESTION in line for line in EPISODE),
          f"{len(labels)} live-leg label(s)")

    banner("BEAT 2 - THE FRAME IS HERMETIC")
    out("  > prove the frame before believing anything that follows")
    out(f"  interpreter : {sys.executable}")
    import hermes as _hermes  # attestation only: prove which tree loaded

    hermes_path = Path(_hermes.__file__).resolve()
    out(f"  hermes      : {hermes_path}")
    out(f"  clock       : {CLOCK}")

    conn = connect(":memory:")
    rows = conn.execute("PRAGMA database_list").fetchall()
    db_file = ""
    for row in rows:
        name = row[0] if not isinstance(row, dict) else row["name"]
        path = row[2] if not isinstance(row, dict) else row["file"]
        if name == "main":
            db_file = str(path or "")
    conn.close()
    out(f"  database    : :memory: (main file = {db_file!r})")
    out("  no network  : the socket layer refuses before hermes was imported")

    raised: Exception | None = None
    try:
        socket.create_connection(("example.invalid", 443), timeout=0.01)
    except Exception as exc:  # noqa: BLE001 - the guard IS the assertion
        raised = exc
    out(f"  guard proof : socket.create_connection -> "
        f"{type(raised).__name__ if raised else 'NO REFUSAL'}")

    check("the network layer is hard-blocked in-process",
          isinstance(raised, NetworkBlocked))
    check("hermes is imported from THIS tree (never another checkout)",
          hermes_path.is_relative_to(REPO_ROOT / "src"),
          str(hermes_path.relative_to(REPO_ROOT)))
    check("the database is :memory: (no file on disk)", db_file == "")
    check("the clock is frozen at the documented instant",
          frozen_clock(CLOCK)() == CLOCK, CLOCK)
    check("all three live-leg labels are on screen",
          len(labels) == 3, f"{len(labels)} label(s)")


# ── BEAT 3: the loop runs (shipped closed-loop scenario) ──


def beat_loop() -> str:
    banner("BEAT 3 - THE LOOP RUNS")
    out("  > the shipped closed-loop scenario runs hermetically: plan -> "
        "dispatch -> model-stub -> validate -> gate -> project")
    cite(LOOP_TEST, f"def {CLOSED_LOOP_NODE}(", 307)
    out(f"  leg: pytest {LOOP_TEST} -v  (fixtures + replay transports + "
        "StubModelClient + frozen clocks)")

    attestation = subprocess.run(
        [sys.executable, "-c",
         "import hermes, pathlib; print(pathlib.Path(hermes.__file__).resolve())"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT), env=leg_env(), check=False)
    att_path = Path((attestation.stdout or "").strip().splitlines()[-1]
                    if attestation.stdout.strip() else "")
    out(f"  leg import attestation: {att_path}")
    check("the loop leg imports THIS tree's src (PYTHONPATH wins over the "
          "editable install)",
          str(att_path).startswith(str(REPO_ROOT / "src")),
          str(att_path))

    rc, output, elapsed = run_leg("closed-loop", [
        sys.executable, "-m", "pytest", LOOP_TEST, "-v", "--no-header",
        "-p", "no:cacheprovider", "-p", "no:hypothesis", "-p", "no:anyio",
        "-o", "addopts="])
    status = node_status(output)

    check("the closed-loop leg exits 0", rc == 0, f"rc={rc} in {elapsed:.2f}s")
    check("the closed-loop golden PASSED", status.get(CLOSED_LOOP_NODE) == "PASSED",
          CLOSED_LOOP_NODE)
    check("every stage test in the leg passed",
          bool(status) and all(v == "PASSED" for v in status.values()),
          f"{sum(1 for v in status.values() if v == 'PASSED')}/{len(status)} PASSED")
    check("no FAILED/ERROR line in the leg output",
          "FAILED" not in output and "ERROR" not in output)
    return output


# ── BEAT 4: refusal #1 - an agent proposes an internal-only intent ──


def beat_refusal_role(conn: Any) -> None:
    banner("BEAT 4 - REFUSAL 1: AN AGENT PROPOSES AN INTERNAL-ONLY INTENT")
    out("  > the model tier may propose; it may never decide - the gateway "
        "refuses a non-operator role outright")
    cite("src/hermes/core/intents.py", "def internal_only(cls)", 144)
    cite("tests/test_gateway.py",
         "def test_admit_task_internal_only(self, db):", 170)

    before = journal_count(conn)
    tasks_before = task_count(conn)
    rejection: GatewayRejection | None = None
    try:
        apply_intent(conn, Intent(
            kind=IntentKind.ADMIT_TASK, proposed_by="RESEARCHER",
            project_id=PROJECT_ID, payload={"task_id": "t-admit"}))
    except GatewayRejection as exc:
        rejection = exc
    after = journal_count(conn)
    tasks_after = task_count(conn)
    landed = [row["event_type"]
              for row in EventRepository(conn).list_all()[before:]]

    if rejection is None:
        out("  outcome: ADMITTED (unexpected)")
    else:
        out(f"  outcome: rejected code={rejection.code} "
            f"kind={rejection.kind.value}")
        out(f"  detail : {str(rejection.reason)[:120]}")
    out(f"  journal rows: {before} -> {after} "
        f"({', '.join(landed) or 'none'})")
    out(f"  task rows   : {tasks_before} -> {tasks_after}")

    check("the agent's internal-only proposal is refused",
          rejection is not None)
    check("the refusal uses the ROLE code (fail-closed role gate)",
          rejection is not None and rejection.code == "ROLE",
          rejection.code if rejection else "no rejection")
    check("the refusal names ADMIT_TASK, an internal-only kind",
          rejection is not None and rejection.kind is IntentKind.ADMIT_TASK)
    check("the refusal is recorded as data, not silence (refusal-as-data)",
          landed == ["IntentRejected"], ", ".join(landed) or "no row")
    check("the refusal created no task row (nothing was admitted)",
          tasks_after == tasks_before, f"{tasks_before} -> {tasks_after}")


# ── BEAT 5: refusal #2 - an oversize rationale at the human gate ──


def beat_refusal_rationale(conn: Any) -> None:
    banner("BEAT 5 - REFUSAL 2: AN OVERSIZE RATIONALE AT THE HUMAN GATE")
    out("  > the human-authority boundary is bounded: a 5000-char rationale "
        "is refused BEFORE any write (4 KiB payload discipline)")
    cite("tests/test_controller.py",
         "def test_11_oversized_rationale_refused_with_specific_code(db)", 1001)

    gate_id = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id=PROJECT_ID,
        payload={
            "task_id": "gate-big", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "gate-big-key",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        })).entity_id
    ctrl = Controller(conn, project_id=PROJECT_ID, clock=frozen_clock(CLOCK))
    ctrl.tick()
    out(f"  gate {gate_id} admitted and ticked to "
        f"{TaskRepository(conn).get_status(gate_id).value}")

    oversize = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", rationale="x" * 5000,
        operator_id=OP_ID, operator_token=OP_TOKEN)
    status_after = TaskRepository(conn).get_status(gate_id)
    verdict_rows = conn.execute(
        "SELECT COUNT(*) AS c FROM events WHERE task_id = ? AND event_type IN "
        "('GatePassed', 'HumanGateResolved')", (gate_id,)).fetchone()["c"]
    out(f"  outcome: rejected={oversize['rejected']} code={oversize['code']}")
    out(f"  detail : {str(oversize['detail'])[:120]}")
    out(f"  gate status after refusal: {status_after.value}, verdict events "
        f"written: {verdict_rows}")

    check("the oversize rationale is refused with the specific code RATIONALE",
          oversize["rejected"] and oversize["code"] == "RATIONALE",
          str(oversize["code"]))
    check("the refusal names the bound ('too large')",
          "too large" in str(oversize["detail"]))
    check("the gate is still WAITING_HUMAN after the refusal",
          status_after is TaskStatus.WAITING_HUMAN, status_after.value)
    check("no verdict event landed (nothing half-written)", verdict_rows == 0,
          f"{verdict_rows} row(s)")

    normal = ctrl.resolve_human_gate(
        task_id=gate_id, verdict="APPROVED", rationale="ok",
        operator_id=OP_ID, operator_token=OP_TOKEN)
    resolved_rows = conn.execute(
        "SELECT COUNT(*) AS c FROM events WHERE task_id = ? AND event_type = "
        "'HumanGateResolved'", (gate_id,)).fetchone()["c"]
    out("  follow-up: a normal rationale resolves the SAME gate -> "
        f"rejected={normal['rejected']}, HumanGateResolved rows={resolved_rows}")
    check("a normal rationale still resolves the same gate (nothing was "
          "half-landed)", not normal["rejected"])
    check("exactly one HumanGateResolved lands on the audit",
          resolved_rows == 1, f"{resolved_rows} row(s)")


# ── BEAT 6: the refusal battery (all hostile-input scenarios, live) ──


def beat_battery() -> None:
    banner("BEAT 6 - THE REFUSAL BATTERY (ALL 8 SCENARIOS, LIVE)")
    out("  > the hostile-input harness runs every scenario through the "
        "public surfaces, offline, no model")
    cite(BATTERY, "def scenario_2(lines)", 232)
    cite(BATTERY, "def scenario_8(lines)", 571)
    cite(BATTERY, "def main() -> int:", 630)

    dirty_before = repo_dirty_paths()
    rc, output, elapsed = run_leg("break-it battery", [
        sys.executable, BATTERY])
    dirty_after = repo_dirty_paths()
    summary = [line for line in output.splitlines()
               if line.startswith("summary:")]
    scenario_lines = [line.strip() for line in output.splitlines()
                      if re.match(r"^\s+S[1-8]: (PASS|FAIL)", line)]
    out("  parsed tallies: " + (summary[0] if summary else "(no summary line)"))
    out(f"  scenarios: {len(scenario_lines)} reported, "
        f"{sum(1 for line in scenario_lines if line.endswith('PASS'))} PASS")

    check("the refusal battery exits 0", rc == 0, f"rc={rc} in {elapsed:.2f}s")
    check("all 8 scenarios matched their reference-test assertions",
          bool(summary) and "8/8" in summary[0],
          summary[0] if summary else "no summary")
    check("the role (S2) and oversize/secret (S8) scenarios PASS",
          any(line.startswith("S2: PASS") for line in scenario_lines)
          and any(line.startswith("S8: PASS") for line in scenario_lines),
          ", ".join(line for line in scenario_lines
                    if line.startswith(("S2", "S8"))))
    check("the battery wrote nothing into the repository",
          dirty_after == dirty_before,
          f"dirty before={sorted(dirty_before)} after={sorted(dirty_after)}")


# Files this demo itself adds; they are the demo's own artifacts, not
# something a leg wrote, so they are excluded from the "legs wrote nothing"
# check.
DEMO_OWN_ARTIFACTS = ("scripts/demo_judge.py", "docs/judge-demo")


def repo_dirty_paths() -> set[str]:
    """Tracked modifications + untracked files, excluding this demo's own
    artifacts: a leg that polluted the repository shows up here."""
    proc = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(REPO_ROOT), check=False)
    paths = set()
    for line in (proc.stdout or "").splitlines():
        entry = line[3:].strip().strip('"')
        if not entry:
            continue
        if any(entry == own or entry.startswith(own + "/")
               for own in DEMO_OWN_ARTIFACTS):
            continue
        paths.add(entry)
    return paths


# ── BEAT 7: the vault verifies ──


def beat_vault(conn: Any) -> None:
    banner("BEAT 7 - THE VAULT VERIFIES (AND REFUSES WHEN IT MUST)")
    out("  > the journal projects into notes plus a derived-view manifest; "
        "verification recomputes the claim instead of trusting the file")
    cite("tests/test_vault_manifest.py", "def test_tampered_note_is_named(db, tmp_path)", 274)
    cite("src/hermes/vault/manifest.py", '"TAMPERED_NOTE"', 104)

    scratch = Path(tempfile.mkdtemp(prefix="judge-demo-vault-"))
    out(f"  [TEMP] vault root: {scratch} (outside the repo; removed below)")
    try:
        rows_before = journal_count(conn)
        cursor, written = project(conn, PROJECT_ID, str(scratch), cursor=0)
        write_cursor(str(scratch), cursor)
        out(f"  projected {len(written)} note(s) for journal rows in "
            f"(0, {cursor}]")
        report = verify_manifest(conn, PROJECT_ID, str(scratch))
        for line in report.lines():
            out(f"    | {line}")

        check("one note per journal row in the projected range",
              len(written) == cursor == rows_before,
              f"{len(written)} notes / cursor {cursor} / {rows_before} rows")
        check("a clean vault verifies OK with zero findings",
              report.ok and report.counts == {},
              f"ok={report.ok} counts={report.counts}")

        target = None
        for name in sorted(Path(scratch).glob("*.md")):
            target = name
        if target is None:
            check("a note exists to tamper with", False, "no notes on disk")
            return
        with target.open("a", encoding="utf-8") as handle:
            handle.write("OUTSIDE EDIT - hand-edited after projection\n")
        out(f"  outside edit applied to {target.name} (the human edited the "
            "derived view)")
        tampered = verify_manifest(conn, PROJECT_ID, str(scratch))
        for line in tampered.lines():
            out(f"    | {line}")

        named = tampered.counts.get("TAMPERED_NOTE", 0)
        check("the outside edit is caught and NAMED (TAMPERED_NOTE)",
              named == 1 and tampered.counts == {"TAMPERED_NOTE": 1},
              f"counts={tampered.counts}")
        check("verification is read-only (journal untouched)",
              journal_count(conn) == rows_before,
              f"{rows_before} -> {journal_count(conn)}")
        check("the refusal names the event id and the file",
              bool(tampered.findings)
              and bool(tampered.findings[0].event_ids)
              and bool(tampered.findings[0].filenames),
              tampered.findings[0].line()[:90] if tampered.findings else "")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    check("the scratch vault was removed (no residue outside the process)",
          not scratch.exists(), str(scratch))


# ── BEAT 8: seeded-error numbers ──


def beat_seeded_errors(loop_output: str) -> None:
    banner("BEAT 8 - SEEDED-ERROR NUMBERS (DERIVED FROM THE RUN, NOT TYPED IN)")
    out("  > the closed-loop scenario seeds three faults and proves the "
        "shipped envelopes fire in-loop")
    cite(LOOP_TEST, f"def {SEEDED_FAULTS[0][1]}(", 435)
    cite(LOOP_TEST, f"def {SEEDED_FAULTS[1][1]}(", 468)
    cite(LOOP_TEST, f"def {SEEDED_FAULTS[2][1]}(", 521)
    cite(LOOP_TEST, f"def {RECOVERY_NODE}(", 571)
    cite(LOOP_TEST, f"def {BOUNDARY_NODE}(", 616)

    status = node_status(loop_output)
    green = 0
    for label, node in SEEDED_FAULTS:
        state = status.get(node, "NOT REPORTED")
        out(f"  seeded fault: {label} -> {state}")
        if state == "PASSED":
            green += 1
    out(f"  numbers: seeded faults={len(SEEDED_FAULTS)} "
        f"detector legs green={green} "
        f"silent retries=0 (asserted by the quarantine/typed legs) "
        f"recovery leg={status.get(RECOVERY_NODE, 'NOT REPORTED')} "
        f"production claim={status.get(BOUNDARY_NODE, 'NOT REPORTED')}")

    check("every seeded fault is caught by a green detector leg",
          green == len(SEEDED_FAULTS), f"{green}/{len(SEEDED_FAULTS)}")
    check("recovery after quarantine is proven in-loop",
          status.get(RECOVERY_NODE) == "PASSED", RECOVERY_NODE)
    check("the slice pins that it does NOT declare production",
          status.get(BOUNDARY_NODE) == "PASSED", BOUNDARY_NODE)


# ── digest + main ──

# Everything volatile about a run, masked before hashing. The generic
# "Temp/<segment>" rule is what keeps the digest stable no matter which
# random scratch directory a leg or this script happened to create.
_VOLATILE = (
    (re.compile(r"\d+\.\d+s"), "<elapsed>"),
    (re.compile(r"[Tt][Ee][Mm][Pp][\\/][A-Za-z0-9_.-]+"), "<tmp-seg>"),
    (re.compile(r"judge-demo-vault-[0-9a-z_]+", re.I), "<vault>"),
    (re.compile(r"breakit-[0-9a-z]+"), "<breakit-tmp>"),
    (re.compile(r"pytest-\d+"), "pytest-N"),
    (re.compile(r"ALIZOG~1", re.I), "<user>"),
)


def replay_digest() -> str:
    masked = []
    for line in EPISODE:
        text = line
        for pattern, replacement in _VOLATILE:
            text = pattern.sub(replacement, text)
        masked.append(text)
    blob = "\n".join(masked).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def main() -> int:
    started = time.perf_counter()
    try:
        beat_question()
        loop_output = beat_loop()
        conn = make_db()
        try:
            beat_refusal_role(conn)
            beat_refusal_rationale(conn)
            beat_battery()
            beat_vault(conn)
        finally:
            conn.close()
        beat_seeded_errors(loop_output)
    except Exception:  # noqa: BLE001 - the demo body must never swallow
        out()
        out("DEMO RAISED - the traceback is printed, never swallowed:")
        out(traceback.format_exc())
        out()
        out("EXIT 2")
        return 2

    elapsed = time.perf_counter() - started
    banner("CITATIONS (every oracle line this run read, proven)")
    for citation in CITATIONS:
        out(f"  {citation}")
    files = {citation.rsplit(":", 1)[0] for citation in CITATIONS}
    check(f"{len(CITATIONS)} repo citations verified across {len(files)} file(s)",
          len(CITATIONS) >= 12 and len(files) >= 4,
          f"{len(CITATIONS)} citations / {len(files)} files")
    check(f"the whole demo ran inside the 5-minute budget "
          f"({elapsed:.2f}s)", elapsed < BUDGET_SECONDS, f"{elapsed:.2f}s")

    digest = replay_digest()
    total = len(CHECKS)
    good = passed()
    banner("RESULT")
    out("  legs: " + ", ".join(f"{name} rc={rc}" for name, rc, _ in LEGS))
    out(f"  checks: {good}/{total} passed")
    out(f"  REPLAY DIGEST: {digest}")
    out("  (two consecutive runs must print the same digest)")
    out(f"RESULT: {good}/{total} checks passed in {elapsed:.2f}s")
    failed = [label for label, ok, _ in CHECKS if not ok]
    if failed:
        out("FAILED: " + "; ".join(failed))
        out("EXIT 1")
        return 1
    out("EXIT 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
