"""S5 ADVERSARIAL VERIFICATION PROBES (charter §12) — run ad hoc, not collected."""
from __future__ import annotations

import sys
sys.path.insert(0, r"D:\New folder\research-agent\src")

import json
import sqlite3
import threading

from hermes.core import frozen_clock, utc_now
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ProjectRepository, TaskRepository, _append_event_to_db)
from hermes.research.gateway import apply_intent, GatewayRejection
from hermes.core.node import NodeContract

CLOCK = "2026-01-01T00:00:00.000000+00:00"
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(("  PASS " if cond else "✗ FAIL ") + name + (f" — {detail}" if detail and not cond else ""))


def fresh():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "T")
    return conn


def decision(conn, ref="hd-1"):
    _append_event_to_db(conn, frozen_clock(CLOCK),
                        EventType.HUMAN_DECISION_RECEIVED.value,
                        project_id="p1", correlation_id=ref,
                        caused_by="operator", reason="op", payload={})


def art(conn, aid, atype="source_result", ch=None, task=None, meta=None):
    conn.execute(
        """INSERT INTO artifacts (artifact_id, project_id, task_id,
           artifact_type, content_hash, size_bytes, storage_path, producer,
           metadata_json, created_at) VALUES (?, 'p1', ?, ?, ?, 1, 'x', 't', ?, ?)""",
        (aid, task, atype, ch or f"ch-{aid}",
         json.dumps(meta) if meta else None, CLOCK))


def edge(conn, a, up, t):
    conn.execute("INSERT INTO provenance_edges (artifact_id, upstream_id, "
                 "edge_type, created_at) VALUES (?, ?, ?, ?)", (a, up, t, CLOCK))


def retract(conn, src="src-a", dec="hd-1", reason="r"):
    return apply_intent(conn, Intent(
        kind=IntentKind.RETRACT_SOURCE, proposed_by="DETERMINISTIC",
        project_id="p1",
        payload={"source_ref": src, "reason": reason,
                 "human_decision_ref": dec}))


print("== A1/A2: no direct-write bypass; gateway is the only mutation path ==")
conn = fresh()
# The validator writes ONLY inside apply_intent; there is no public function
# exposing the cascade. Verify the module exports nothing else:
import hermes.research.gateway as gw
exports = [n for n in dir(gw) if "retract" in n.lower()]
check("A2 no public retraction API besides the intent path",
      set(exports) <= {"_validate_retract_source", "_s5_source_artifact_id",
                       "_RETRACT_SOURCE_PAYLOAD_KEYS",
                       "_S5_DEPENDENCY_EDGE_TYPES",
                       "_S5_SOURCE_ARTIFACT_TYPES",
                       "_S5_DECISION_ARTIFACT_TYPE"},
      str(exports))

print("== A3: lower-level TaskRepository.invalidate cannot be reached to "
      "bypass the human-decision contract? It CAN be called directly — but it")
print("   was pre-existing substrate (IDR-017 single-task, 0 production "
      "callers); S5 does not extend it. Documented, not an S5 regression.")

print("== 4/5: cone boundaries — cycle + self-edge + diamond ==")
conn = fresh(); decision(conn)
art(conn, "src-a"); art(conn, "x"); art(conn, "y")
edge(conn, "x", "src-a", "cites"); edge(conn, "y", "x", "derived_from")
edge(conn, "x", "y", "used_as_input")  # 2-cycle x<->y
r = retract(conn)
check("cycle terminates and invalidates all", sorted(r.row["invalidated_artifacts"]) == ["x", "y"])

conn = fresh(); decision(conn)
art(conn, "src-a"); art(conn, "selfish")
edge(conn, "selfish", "src-a", "cites")
# self-edge is schema-blocked (CHECK artifact_id != upstream_id) — the DB
# itself refuses it; verify that defense instead of inserting one.
try:
    edge(conn, "selfish", "selfish", "cites")
    check("self-edge schema-blocked", False, "insert succeeded")
except sqlite3.IntegrityError:
    check("self-edge schema-blocked (defense-in-depth)", True)
r = retract(conn)
check("cascade unaffected by blocked self-edge",
      r.row["invalidated_artifacts"] == ["selfish"])

print("== 6: resurrection — invalidated artifact stays INVALIDATED after repeat ==")
conn = fresh(); decision(conn)
art(conn, "src-a"); art(conn, "d1"); edge(conn, "d1", "src-a", "cites")
retract(conn)
try:
    retract(conn, reason="try resurrect")
    check("6 resurrection blocked", False, "no STALE raised")
except GatewayRejection as e:
    check("6 resurrection blocked (STALE)", e.code == "STALE")
meta = json.loads(conn.execute(
    "SELECT metadata_json FROM artifacts WHERE artifact_id='d1'"
).fetchone()["metadata_json"])
check("6 marker persists", meta["invalidation_marker"] == "INVALIDATED")

print("== 7: terminal transitions — INVALIDATED task cannot transition again ==")
conn = fresh(); decision(conn)
t = TaskRepository(conn, frozen_clock(CLOCK))
t.create(NodeContract(task_id="tk", project_id="p1", task_type="TOOL_TASK",
                      idempotency_key="i-tk"))
conn.execute("UPDATE tasks SET status='SUCCEEDED' WHERE task_id='tk'")
art(conn, "src-a", task="tk")
art(conn, "d1", task="tk"); edge(conn, "d1", "src-a", "cites")
retract(conn)
from hermes.core.task_status import TaskStatus, validate_task_transition
for target in (TaskStatus.RUNNING, TaskStatus.SUCCEEDED, TaskStatus.PENDING):
    try:
        validate_task_transition(TaskStatus.INVALIDATED, target)
        check(f"7 INVALIDATED -> {target.value} rejected", False)
    except Exception:
        check(f"7 INVALIDATED -> {target.value} rejected", True)

print("== 9: replay determinism — two identical DBs produce identical ledgers ==")


def build_and_run():
    c = fresh()
    decision(c, "hd-x")
    art(c, "s"); art(c, "a"); art(c, "b")
    edge(c, "a", "s", "cites"); edge(c, "b", "a", "derived_from")
    rr = retract(c, src="s", dec="hd-x", reason="same")
    rows = c.execute(
        "SELECT event_type, correlation_id, caused_by FROM events "
        "WHERE correlation_id LIKE 'retract%' OR event_type='TaskInvalidated' "
        "ORDER BY rowid").fetchall()
    arts = c.execute(
        "SELECT artifact_id, metadata_json FROM artifacts "
        "WHERE artifact_id IN ('a','b') ORDER BY artifact_id").fetchall()
    return (rr.row["retraction_id"],
            [tuple(x) for x in rows],
            [(x["artifact_id"], json.loads(x["metadata_json"])["invalidation_marker"],
              json.loads(x["metadata_json"])["invalidated_by"]) for x in arts])


check("9 deterministic replay identical", build_and_run() == build_and_run())

print("== 10: persistence match — events vs state after reopen ==")
import tempfile, os
tmp = tempfile.mktemp(suffix=".db")
c = connect(tmp); migrate_to_latest(c)
ProjectRepository(c, frozen_clock(CLOCK)).create("p1", "T")
decision(c)
art(c, "src-a")
retract(c)
c.close()
c2 = connect(tmp)
n = c2.execute("SELECT COUNT(*) c FROM events WHERE event_type=?",
               (EventType.SOURCE_RETRACTED.value,)).fetchone()["c"]
n_rd = c2.execute("SELECT COUNT(*) c FROM artifacts WHERE artifact_type='ResearchDecision'").fetchone()["c"]
check("10 persisted state survives reopen", n == 1 and n_rd == 1)
c2.close(); os.unlink(tmp)

print("== 12: order independence — retraction before/after downstream edges exist ==")
# Edges are written by tasks BEFORE any retraction in real flows; the cascade
# reads current edges. A later-created downstream artifact is NOT retroactively
# invalidated — that is correct: it did not exist when the source died.
conn = fresh(); decision(conn)
art(conn, "src-a")
r = retract(conn)
art(conn, "late", ch="ch-late")
edge(conn, "late", "src-a", "cites")
meta = conn.execute("SELECT metadata_json FROM artifacts WHERE artifact_id='late'").fetchone()["metadata_json"]
check("12 post-retraction artifact not retro-invalidated (documented limit)",
      not meta or json.loads(meta).get("invalidation_marker") != "INVALIDATED")

print("== 13: repeated retraction across DIFFERENT sources same decision ==")
conn = fresh(); decision(conn, "hd-multi")
art(conn, "s1"); art(conn, "s2")
r1 = retract(conn, src="s1", dec="hd-multi")
r2 = retract(conn, src="s2", dec="hd-multi")
check("13 one decision can retract multiple distinct sources",
      r1.duplicate is False and r2.duplicate is False)

print("== concurrency: BEGIN IMMEDIATE serializes concurrent retractions ==")
tmp = tempfile.mktemp(suffix=".db")
c0 = connect(tmp); migrate_to_latest(c0)
ProjectRepository(c0, frozen_clock(CLOCK)).create("p1", "T")
decision(c0)
art(c0, "src-a"); art(c0, "z"); edge(c0, "z", "src-a", "cites")
c0.close()

results = []
def worker():
    c = connect(tmp)
    try:
        r = apply_intent(c, Intent(kind=IntentKind.RETRACT_SOURCE,
            proposed_by="DETERMINISTIC", project_id="p1",
            payload={"source_ref": "src-a", "reason": "r",
                     "human_decision_ref": "hd-1"}), clock=utc_now)
        results.append(("ok", r.duplicate))
    except GatewayRejection as e:
        results.append(("rejected", e.code))
    except sqlite3.OperationalError as e:
        results.append(("sqlite", str(e)))
    finally:
        c.close()

threads = [threading.Thread(target=worker) for _ in range(4)]
[t.start() for t in threads]
[t.join() for t in threads]
oks = [r for r in results if r[0] == "ok" and r[1] is False]
dupes_or_rejects = [r for r in results if r not in oks]
cc = connect(tmp)
n_ev = cc.execute("SELECT COUNT(*) c FROM events WHERE event_type='SourceRetracted' AND correlation_id LIKE 'retract_%'").fetchone()["c"]
n_rd = cc.execute("SELECT COUNT(*) c FROM artifacts WHERE artifact_type='ResearchDecision'").fetchone()["c"]
cc.close(); os.unlink(tmp)
check("14 concurrency: exactly ONE applied retraction", len(oks) <= 1 and n_ev == 1 and n_rd == 1,
      f"results={results} n_ev={n_ev} n_rd={n_rd}")

print()
print("=" * 60)
print(f"ADVERSARIAL PROBES: {len(PASS)} passed, {len(FAIL)} failed")
for name, detail in FAIL:
    print(f"  FAILED: {name} {detail}")
