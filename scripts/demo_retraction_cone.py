#!/usr/bin/env python3
"""RETRACTION-DEMO - the S5 source-retraction cone, replayed offline.

What it proves, in one deterministic run (no network, no keys, no fixture
files, no writes outside the process):

  1. the run is hermetic: the network is hard-blocked, the database is
     ``:memory:``, the clock is frozen;
  2. a source enters the graph (a fetch task's outcome + its evidence
     node), and a downstream analyst task is bound to that evidence;
  3. two failure classifications from the analyst produce a REAL CHG-1
     contradiction (status OPEN), and the analyst task finishes;
  4. retracting the source without a recorded HumanDecision is REFUSED by
     the gateway (fail-closed authority boundary) - nothing is written;
  5. the ratified retraction admitted through the Controller surface runs
     the whole cascade in ONE ``BEGIN IMMEDIATE`` transaction: the
     superseding ``ResearchDecision`` artifact, the downstream cone
     invalidation, task invalidation, and the ``SourceRetracted`` event
     carrying a bounded cone commitment;
  6. the cone is printed, its members re-read from persisted state, and
     the event payload's counts and digest are INDEPENDENTLY recomputed
     from that state (a mismatch is a check failure, not a footnote);
  7. the OPEN contradiction the retraction reached is SUPERSEDED - named
     in the output - and its history survives;
  8. a fresh analyst task citing the same (now retracted) evidence is
     REFUSED, and the contradiction detector records nothing new.

Exit codes: 0 = every check passed; 1 = at least one check failed;
2 = the run raised inside the demo body (traceback printed, never
swallowed). Any non-zero exit is a deviation; a failure that happens
before the demo body starts (for example at import) exits 1 with the
interpreter's own traceback.

Hermeticity: the network layer is blocked before ``hermes`` is imported
and the database is created in memory, so a judge can re-run this offline.
The ingest beat writes the artifact/provenance rows directly (the same
shape ``tests/test_s5_retraction.py`` and
``tests/test_n9_retraction_admission.py`` use) because the production
source path drives provider transports; every step from the retraction
onward goes through the production surfaces only.
"""

from __future__ import annotations

import hashlib
import json
import socket
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# -- Beat 1a: the hermetic guard, installed BEFORE hermes is imported --
# A demo that silently reached the network would not be replayable by a
# judge offline, so the socket layer refuses loudly instead.


class NetworkBlocked(RuntimeError):
    pass


def _blocked_network(*_args: object, **_kwargs: object) -> Any:
    raise NetworkBlocked("RETRACTION-DEMO is hermetic: network use refused")


socket.socket = _blocked_network              # type: ignore[assignment,misc]
socket.create_connection = _blocked_network   # type: ignore[assignment]
socket.getaddrinfo = _blocked_network         # type: ignore[assignment]

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes.core import frozen_clock  # noqa: E402
from hermes.core.events import EventType  # noqa: E402
from hermes.core.intents import Intent, IntentKind  # noqa: E402
from hermes.core.node import NodeContract  # noqa: E402
from hermes.persistence.database import connect  # noqa: E402
from hermes.persistence.migrations import migrate_to_latest  # noqa: E402
from hermes.persistence.repositories import (  # noqa: E402
    OperatorCredentialRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.persistence.source_outcomes import (  # noqa: E402
    source_artifact_retracted,
)
from hermes.research.contradictions import contradiction_id_of  # noqa: E402
from hermes.research.controller import Controller  # noqa: E402
from hermes.research.gateway import (  # noqa: E402
    GatewayRejection,
    apply_intent,
)

# -- The frozen frame (deterministic identities, no wall clock) --
CLOCK = "2026-01-01T00:00:00.000000+00:00"
PROJECT = "p-demo"
PROGRAM = "rp-demo"
HYPOTHESIS = "h1"
OP_ID = "op-demo"
OP_TOKEN = "op-demo-token-1"
EV_HASH = "evhash-demo-ev1"                  # content hash of the evidence
EV_ID = "art-ev1"
OUT_ID = "art-out1"
TASK_FETCH = "t-fetch"
TASK_ANALYST = "t-analyst"
NOTE_ID = "art-note"
MEMO_ID = "art-memo"
SOURCE_REF = f"source_result:{EV_HASH}"      # <source_type>:<content_hash>
RETRACTION_REASON = "retracted: the upstream study was withdrawn"
UNAUTHORIZED_REF = "retract-decision-absent"


class Demo:
    """Beat printer + check ledger. Checks never raise; they count."""

    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []
        self.t0 = time.monotonic()
        self.beat_no = 0

    def beat(self, title: str, narration: str) -> None:
        self.beat_no += 1
        print()
        print("-" * 74)
        print(f"BEAT {self.beat_no} - {title}")
        print(f"  > {narration}")

    def show(self, label: str, value: Any) -> None:
        # Echoed engine text may carry non-ASCII punctuation; escape it so
        # a captured transcript is pure ASCII on every console code page.
        rendered = value if isinstance(value, str) else json.dumps(
            value, sort_keys=True, default=str)
        rendered = rendered.encode("ascii", "backslashreplace").decode("ascii")
        print(f"  {label}: {rendered}")

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        self.checks.append((label, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}"
              + (f" - {detail}" if detail else ""))
        return ok

    def elapsed(self) -> float:
        return time.monotonic() - self.t0


def _controller(conn: Any) -> Controller:
    return Controller(conn, project_id=PROJECT, clock=frozen_clock(CLOCK))


# ===================== fixtures (the ingest shape) =====================


def _seed(conn: Any, demo: Demo) -> None:
    """Projects, operator credential, research program, tasks."""
    ProjectRepository(conn, frozen_clock(CLOCK)).create(
        PROJECT, "Retraction Cone Demo")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Demo Operator")
    conn.execute(
        """INSERT INTO research_programs
           (program_id, project_id, version, content_hash, supersedes_id,
            scope_ref, epistemic_objective, compiler_version, policy_version,
            schema_version, input_hash, hypothesis_json, prediction_json,
            discrimination_json, evidence_json, gate_json, methodology_json,
            task_graph_template_ref, produced_by, reason, created_at)
           VALUES (?, ?, 1, ?, NULL, 'scope', 'objective', 'c1', 'pol', '1',
                   'ih', ?, ?, '[]', '[]', '[]', '[]', NULL, 'director',
                   NULL, ?)""",
        (PROGRAM, PROJECT, "ch-" + PROGRAM,
         json.dumps([{"ref": HYPOTHESIS, "ladder_target": "SUPPORTED",
                      "falsification_condition": "fc", "rival_of": None,
                      "rival_status": None}]),
         json.dumps([{"ref": "p1"}]), CLOCK))
    for task_id, status in ((TASK_FETCH, "SUCCEEDED"),
                            (TASK_ANALYST, "RUNNING")):
        TaskRepository(conn, frozen_clock(CLOCK)).create(NodeContract(
            task_id=task_id, project_id=PROJECT, task_type="TOOL_TASK",
            idempotency_key=f"idem-{task_id}", dependencies=[]))
        conn.execute("UPDATE tasks SET status = ? WHERE task_id = ?",
                     (status, task_id))
    conn.commit()
    demo.show("seeded", {"project": PROJECT, "program": PROGRAM,
                         "tasks": {TASK_FETCH: "SUCCEEDED",
                                   TASK_ANALYST: "RUNNING"}})


def _artifact(conn: Any, artifact_id: str, content_hash: str,
              artifact_type: str = "source_result",
              task_id: str | None = None) -> None:
    """One artifact row; ``task_id`` is the producing task (the column the
    S5 cascade joins on to invalidate downstream tasks)."""
    conn.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type, content_hash,
            size_bytes, storage_path, producer, metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, 1, 'memory://fixture', 'demo', NULL, ?)""",
        (artifact_id, PROJECT, task_id, artifact_type, content_hash, CLOCK))


def _edge(conn: Any, child: str, parent: str,
          edge_type: str = "derived_from") -> None:
    conn.execute(
        """INSERT INTO provenance_edges
           (artifact_id, upstream_id, edge_type, created_at)
           VALUES (?, ?, ?, ?)""",
        (child, parent, edge_type, CLOCK))


def _ingest(conn: Any, demo: Demo) -> None:
    """Fetch-task outcome + evidence node + the analyst's downstream work."""
    _artifact(conn, OUT_ID, f"outhash-{OUT_ID}", task_id=TASK_FETCH)
    _artifact(conn, EV_ID, EV_HASH, task_id=TASK_FETCH)
    _edge(conn, OUT_ID, TASK_FETCH)     # outcome derived_from task
    _edge(conn, EV_ID, OUT_ID)          # evidence derived_from outcome
    # The analyst binds the SAME evidence node through its own outcome
    # node (the multi-analyst pattern: one content hash, one artifact row,
    # many consumers) and produces a note plus a memo derived from it.
    _artifact(conn, "art-out2", "outhash-art-out2", task_id=TASK_ANALYST)
    _edge(conn, "art-out2", TASK_ANALYST)
    _edge(conn, EV_ID, "art-out2")
    _artifact(conn, NOTE_ID, f"hash-{NOTE_ID}", "analysis",
              task_id=TASK_ANALYST)
    _artifact(conn, MEMO_ID, f"hash-{MEMO_ID}", "analysis",
              task_id=TASK_ANALYST)
    _edge(conn, NOTE_ID, EV_ID)
    _edge(conn, MEMO_ID, NOTE_ID)
    conn.commit()
    demo.show("ingested", {
        "evidence": f"{EV_ID} ({SOURCE_REF})",
        "upstream": f"{OUT_ID} <- {TASK_FETCH}",
        "downstream (1 hop)": f"{NOTE_ID} <- {TASK_ANALYST}",
        "downstream (2 hops)": MEMO_ID,
    })


def _classify(conn: Any, failure_class: str, *,
              classifier_version: str = "1.0", task_id: str = TASK_ANALYST,
              **extra: Any) -> dict:
    return _controller(conn).record_failure_classification(
        program_ref=PROGRAM, hypothesis_ref=HYPOTHESIS,
        failure_class=failure_class, evidence_refs=[SOURCE_REF],
        falsifying_evidence_refs=[SOURCE_REF],
        explanation=f"demo analyst finding {failure_class}",
        classifier_version=classifier_version,
        proposed_by=f"operator:{OP_ID}", producing_task_id=task_id,
        rationale="", operator_id=OP_ID, operator_token=OP_TOKEN, **extra)


def _retract(conn: Any, *, source_ref: str, human_decision_ref: str) -> Any:
    """The raw gateway command - used to probe the authority boundary."""
    return apply_intent(conn, Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
        project_id=PROJECT, justification="RETRACTION-DEMO",
        payload={"source_ref": source_ref, "reason": RETRACTION_REASON,
                 "human_decision_ref": human_decision_ref}),
        clock=frozen_clock(CLOCK))


def _meta(conn: Any, artifact_id: str) -> dict:
    row = conn.execute(
        "SELECT metadata_json FROM artifacts WHERE artifact_id = ?",
        (artifact_id,)).fetchone()
    return json.loads(row["metadata_json"]) if row and row["metadata_json"] \
        else {}


def _cone_artifacts(conn: Any, decision_id: str) -> list[str]:
    """Cone membership re-read from persisted state (never from the event)."""
    rows = conn.execute(
        "SELECT artifact_id FROM artifacts WHERE project_id = ? "
        "ORDER BY artifact_id", (PROJECT,)).fetchall()
    return [r["artifact_id"] for r in rows
            if _meta(conn, r["artifact_id"]).get("invalidated_by")
            == decision_id]


def _events(conn: Any, event_type: str, **where: str) -> list[dict]:
    sql = ("SELECT correlation_id, payload_json FROM events "
           "WHERE event_type = ?")
    params: list[Any] = [event_type]
    for column, value in sorted(where.items()):
        sql += f" AND {column} = ?"
        params.append(value)
    sql += " ORDER BY rowid"
    return [{"correlation_id": r["correlation_id"],
             "payload": json.loads(r["payload_json"])}
            for r in conn.execute(sql, tuple(params)).fetchall()]


def main() -> int:
    demo = Demo()
    print("=" * 74)
    print("RETRACTION-DEMO - S5 source-retraction cone, offline replay")
    print("=" * 74)

    # -- BEAT 1 - the hermetic frame ----------------------------------
    demo.beat("HERMETIC FRAME",
              "open an in-memory database at a frozen clock; the network "
              "layer is already refusing")
    conn = connect(":memory:")
    migrate_to_latest(conn)
    _seed(conn, demo)
    blocked = False
    try:
        socket.socket()
    except NetworkBlocked:
        blocked = True
    demo.check("network is hard-blocked in-process", blocked)
    demo.check("database is :memory: (no file written)",
               conn.execute("PRAGMA database_list").fetchone()["file"] == "")
    demo.show("clock", CLOCK)

    # -- BEAT 2 - ingest ----------------------------------------------
    demo.beat("INGEST THE SOURCE",
              "a fetch task's outcome and evidence node enter the graph, "
              "then an analyst task binds that evidence and derives a note "
              "plus a memo two hops downstream")
    _ingest(conn, demo)

    # -- BEAT 3 - derive classifications + a real contradiction --------
    demo.beat("DERIVE CLASSIFICATIONS",
              "two failure classifications cite the same evidence - "
              "different failure classes against one hypothesis - and the "
              "analyst task then finishes")
    dcv = _classify(conn, "DECLARED_CONSTRAINT_VIOLATION",
                    constraint_ref=f"hypothesis:{HYPOTHESIS}:"
                                   "falsification_condition")
    impl = _classify(conn, "IMPLEMENTATION_FAILURE",
                     failed_mechanism_ref="prediction:p1")
    demo.show("classification A", dcv)
    demo.show("classification B", impl)
    a_id = str(dcv.get("entity_id", ""))
    b_id = str(impl.get("entity_id", ""))
    demo.check("classification A recorded",
               dcv.get("rejected") is False and bool(a_id), a_id)
    demo.check("classification B recorded",
               impl.get("rejected") is False and bool(b_id), b_id)
    conn.execute("UPDATE tasks SET status = 'SUCCEEDED' WHERE task_id = ?",
                 (TASK_ANALYST,))
    conn.commit()
    demo.check("the analyst task has finished (SUCCEEDED)",
               conn.execute("SELECT status FROM tasks WHERE task_id = ?",
                            (TASK_ANALYST,)).fetchone()["status"]
               == "SUCCEEDED")
    detected = _controller(conn).detect_contradictions()
    cx_id = contradiction_id_of(a_id, b_id)
    demo.check("CHG-1 detector records the contradiction",
               detected["recorded"] == [cx_id], f"contradiction_id={cx_id}")
    cx_row = conn.execute(
        "SELECT party_a, party_b, status FROM contradictions "
        "WHERE contradiction_id = ?", (cx_id,)).fetchone()
    demo.show("contradiction", {"id": cx_id, "status": cx_row["status"],
                                "party_a": cx_row["party_a"],
                                "party_b": cx_row["party_b"]})

    # -- BEAT 4 - the authority boundary refuses first -----------------
    demo.beat("REFUSE UNBOUND AUTHORITY",
              "ask the gateway to retract the source with a decision ref "
              "that dereferences to no recorded HumanDecision")
    refusal: GatewayRejection | None = None
    try:
        _retract(conn, source_ref=SOURCE_REF,
                 human_decision_ref=UNAUTHORIZED_REF)
    except GatewayRejection as exc:
        refusal = exc
    demo.check("retraction with no recorded human decision is refused",
               refusal is not None and refusal.code == "PROPOSAL",
               f"code={refusal.code if refusal else 'NO-REFUSAL'}")
    if refusal is not None:
        demo.show("refusal detail", str(refusal)[:170])
    demo.check("nothing was written by the refusal",
               _events(conn, EventType.SOURCE_RETRACTED.value) == []
               and source_artifact_retracted(conn, PROJECT, EV_ID) is False)
    demo.check("the N9 fresh-citation predicate is False before retraction",
               source_artifact_retracted(conn, PROJECT, EV_ID) is False)

    # -- BEAT 5 - the ratified retraction -----------------------------
    demo.beat("RETRACT (RATIFIED)",
              "the controlled surface records the operator's human decision "
              "then submits RETRACT_SOURCE - one atomic BEGIN IMMEDIATE")
    artifacts_before = {r["artifact_id"] for r in conn.execute(
        "SELECT artifact_id FROM artifacts WHERE project_id = ?",
        (PROJECT,)).fetchall()}
    out = _controller(conn).record_source_retraction_decision(
        source_ref=SOURCE_REF, reason=RETRACTION_REASON,
        operator_id=OP_ID, operator_token=OP_TOKEN)
    demo.show("retraction result", out)
    demo.check("ratified retraction admitted", out.get("rejected") is False,
               f"entity_id={out.get('entity_id')}")
    retraction_id = str(out.get("retraction_id", ""))
    decision_ref = str(out.get("decision_ref", ""))
    demo.show("decision retraction_id (Controller)", retraction_id)
    demo.show("decision_ref (the recorded human decision)", decision_ref)
    # The gateway derives its OWN deterministic command key from the full
    # command - recompute it here and verify it against the journal below.
    command_id = "retract_" + hashlib.sha256(json.dumps(
        {"source_ref": SOURCE_REF, "reason": RETRACTION_REASON,
         "human_decision_ref": decision_ref},
        sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    demo.show("gateway command id (recomputed)", command_id)
    decision_row = conn.execute(
        "SELECT artifact_id FROM artifacts WHERE artifact_type = "
        "'ResearchDecision' ORDER BY artifact_id LIMIT 1").fetchone()
    decision_id = decision_row["artifact_id"] if decision_row else ""
    demo.show("superseding decision artifact", decision_id)

    # -- BEAT 6 - the cone --------------------------------------------
    demo.beat("THE CONE",
              "read the persisted cone back: artifacts invalidated by the "
              "decision, tasks invalidated, curated entries reached")
    inv_artifacts = _cone_artifacts(conn, decision_id)
    inv_tasks = [r["task_id"] for r in conn.execute(
        "SELECT task_id FROM tasks WHERE status = 'INVALIDATED' "
        "ORDER BY task_id").fetchall()]
    curated = [e["payload"]["curated_id"] for e in
               _events(conn, EventType.CURATED_KNOWLEDGE_INVALIDATED.value,
                       correlation_id=retraction_id)]
    demo.show("invalidated artifacts", inv_artifacts)
    demo.show("invalidated tasks", inv_tasks)
    demo.show("invalidated curated entries", curated)
    demo.check("the retracted evidence itself is NOT in the cone "
               "(superseded, not invalidated)", EV_ID not in inv_artifacts)
    demo.check("the evidence's upstream outcome is NOT in the cone "
               "(invalidation flows downstream only)",
               OUT_ID not in inv_artifacts)
    demo.check("the derived note is in the cone", NOTE_ID in inv_artifacts)
    demo.check("the two-hop memo is in the cone (transitive)",
               MEMO_ID in inv_artifacts)
    demo.check("the analyst task is INVALIDATED",
               TASK_ANALYST in inv_tasks)
    demo.check("both classification artifacts are in the cone (the "
               "normalized dependency edge resolves the evidence ref)",
               a_id in inv_artifacts and b_id in inv_artifacts)
    ti = conn.execute(
        "SELECT task_id, from_state, to_state FROM events WHERE "
        "event_type = ? AND correlation_id = ?",
        (EventType.TASK_INVALIDATED.value, command_id)).fetchall()
    demo.check("TaskInvalidated event: t-analyst SUCCEEDED -> INVALIDATED",
               len(ti) == 1 and ti[0]["task_id"] == TASK_ANALYST
               and ti[0]["from_state"] == "SUCCEEDED"
               and ti[0]["to_state"] == "INVALIDATED")
    demo.check("the fetch task keeps SUCCEEDED - its own artifacts were "
               "not invalidated",
               conn.execute("SELECT status FROM tasks WHERE task_id = ?",
                            (TASK_FETCH,)).fetchone()["status"]
               == "SUCCEEDED")
    for artifact_id in inv_artifacts:
        meta = _meta(conn, artifact_id)
        demo.check(f"{artifact_id} is marked INVALIDATED, archived in place",
                   meta.get("invalidation_marker") == "INVALIDATED"
                   and meta.get("invalidated_by") == decision_id)
    artifacts_after = {r["artifact_id"] for r in conn.execute(
        "SELECT artifact_id FROM artifacts WHERE project_id = ?",
        (PROJECT,)).fetchall()}
    demo.check("no artifact row was deleted by the cascade "
               "(archive-not-delete)", artifacts_before <= artifacts_after,
               f"{len(artifacts_before)} -> {len(artifacts_after)} rows")

    # -- BEAT 7 - the bounded event, independently recomputed ----------
    demo.beat("THE JOURNAL RECORD",
              "the SourceRetracted event carries counts and a digest of the "
              "cone; recompute both from persisted state and compare")
    events = _events(conn, EventType.SOURCE_RETRACTED.value)
    demo.check("exactly one SourceRetracted event in this project",
               len(events) == 1, f"{len(events)} event(s)")
    demo.check("its correlation_id IS the recomputed command id "
               "(identity recomputed, never trusted)",
               bool(events) and events[0]["correlation_id"] == command_id,
               events[0]["correlation_id"] if events else "")
    payload = events[0]["payload"] if events else {}
    demo.show("payload", payload)
    recomputed_digest = hashlib.sha256(json.dumps(
        {"artifacts": sorted(inv_artifacts), "tasks": sorted(inv_tasks),
         "curated": sorted(curated)},
        sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    demo.check("declared artifact_count matches the persisted cone",
               payload.get("artifact_count") == len(inv_artifacts),
               f"{payload.get('artifact_count')} == {len(inv_artifacts)}")
    demo.check("declared task_count matches the persisted task list",
               payload.get("task_count") == len(inv_tasks),
               f"{payload.get('task_count')} == {len(inv_tasks)}")
    demo.check("declared curated_count matches the persisted list",
               payload.get("curated_count") == len(curated))
    demo.check("cone_digest recomputes from persisted state",
               payload.get("cone_digest") == recomputed_digest,
               recomputed_digest)
    demo.check("payload names the source and the superseding decision",
               payload.get("source_artifact_id") == EV_ID
               and payload.get("decision_artifact_id") == decision_id
               and payload.get("human_decision_ref") == decision_ref)
    payload_bytes = len(json.dumps(payload).encode("utf-8"))
    demo.check("payload stays inside the 4 KiB event cap",
               payload_bytes < 4096, f"{payload_bytes} bytes")

    # -- BEAT 8 - the superseded contradiction, named ------------------
    demo.beat("THE SUPERSEDED CONTRADICTION",
              "the retraction reached a party of the OPEN contradiction, so "
              "it is SUPERSEDED in the same transaction")
    cx_row = conn.execute(
        "SELECT party_a, party_b, status FROM contradictions "
        "WHERE contradiction_id = ?", (cx_id,)).fetchone()
    demo.show("contradiction", {"id": cx_id, "status": cx_row["status"],
                                "party_a": cx_row["party_a"],
                                "party_b": cx_row["party_b"]})
    demo.check(f"contradiction {cx_id} is SUPERSEDED",
               cx_row["status"] == "SUPERSEDED")
    superseded = _events(conn, EventType.CONTRADICTION_SUPERSEDED.value)
    demo.check("ContradictionSuperseded event names the retraction "
               "(<contradiction_id>:superseded:<command_id>)",
               len(superseded) == 1
               and superseded[0]["correlation_id"]
               == f"{cx_id}:superseded:{command_id}",
               superseded[0]["correlation_id"] if superseded else "")
    demo.check("the contradiction's history survives "
               "(both parties still recorded)",
               (cx_row["party_a"], cx_row["party_b"])
               == (min(a_id, b_id), max(a_id, b_id)))
    demo.check("the N9 retraction predicate now reads True",
               source_artifact_retracted(conn, PROJECT, EV_ID) is True)

    # -- BEAT 9 - the fresh citation is refused ------------------------
    demo.beat("FRESH CITATION AFTER RETRACTION",
              "a new analyst task is bound to the same evidence and tries "
              "to classify against it under a new classifier version")
    fresh_task = "t-fresh"
    TaskRepository(conn, frozen_clock(CLOCK)).create(NodeContract(
        task_id=fresh_task, project_id=PROJECT, task_type="TOOL_TASK",
        idempotency_key=f"idem-{fresh_task}", dependencies=[]))
    conn.execute("UPDATE tasks SET status = 'RUNNING' WHERE task_id = ?",
                 (fresh_task,))
    _artifact(conn, "art-out-fresh", "outhash-art-out-fresh",
              task_id=fresh_task)
    _edge(conn, "art-out-fresh", fresh_task)
    _edge(conn, EV_ID, "art-out-fresh")   # rebind the evidence node
    conn.commit()
    before = conn.execute(
        "SELECT COUNT(*) c FROM artifacts WHERE artifact_type = "
        "'failure_classification'").fetchone()["c"]
    fresh = _classify(conn, "DECLARED_CONSTRAINT_VIOLATION",
                      classifier_version="2.0", task_id=fresh_task,
                      constraint_ref=f"hypothesis:{HYPOTHESIS}:"
                                     "falsification_condition")
    demo.show("fresh citation result", fresh)
    demo.check("the fresh classification is refused",
               fresh.get("rejected") is True, f"code={fresh.get('code')}")
    demo.check("refusal reuses the EVIDENCE_DOES_NOT_RESOLVE vocabulary",
               "EVIDENCE_DOES_NOT_RESOLVE" in str(fresh.get("detail", "")))
    after = conn.execute(
        "SELECT COUNT(*) c FROM artifacts WHERE artifact_type = "
        "'failure_classification'").fetchone()["c"]
    demo.check("no classification artifact was written by the refusal",
               after == before, f"{after} == {before}")
    redetected = _controller(conn).detect_contradictions()
    demo.check("the detector records nothing new after retraction",
               redetected["recorded"] == [])

    # -- Summary -------------------------------------------------------
    elapsed = demo.elapsed()
    print()
    print("=" * 74)
    demo.check("the whole demo ran inside the 90-second budget",
               elapsed < 90.0, f"{elapsed:.2f}s")
    failed = [label for label, ok, _ in demo.checks if not ok]
    print(f"RESULT: {len(demo.checks) - len(failed)}/{len(demo.checks)} "
          f"checks passed in {elapsed:.2f}s")
    if failed:
        print("FAILED CHECKS:")
        for label in failed:
            print(f"  - {label}")
    else:
        print("Every narrated step above was verified against persisted "
              "state. Replay is deterministic: the clock is frozen and "
              "every identity is recomputed from content.")
    print(f"EXIT {'1' if failed else '0'}")
    print("=" * 74)
    conn.close()
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:            # never swallow: print and exit 2
        traceback.print_exc()
        print("EXIT 2 - the demo raised (see traceback above)")
        sys.exit(2)
