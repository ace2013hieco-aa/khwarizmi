"""Differential replay harness for the CHG-1 contradiction detector (FIX-DET-EXPRESS).

Three checks, each returning a list of human-readable failures (empty = pass):

1. ``run_twice_equal``: the same scenario run into two independent SQLite
   files must produce canonical dumps that are equal after the declared
   provenance strip (``PROVENANCE_STRIP``).
2. ``journal_reproduces_derived``: the ``contradictions`` table must equal the
   fold of ``ContradictionDetected`` journal events (id, parties, overlap,
   detector version). Absence of a journal row is a failure, not a skip.
3. ``fan_out_bounded``: a group of ``n`` conflicting classifications must emit
   no more intents than ``FAN_OUT_BOUND``, and a capped run must say so
   (``truncated`` diagnostic). ``FAN_OUT_BOUND`` is a literal here on purpose:
   the harness states the spec, it does not import the value under test.

PROVENANCE_STRIP (reviewed; the ONLY fields that are normalized)::

    events.correlation_id  — when it is a uuid4 string (repositories.py:171,
                             :223, :283, ... minted with uuid.uuid4()). Replaced
                             by the literal ``<uuid4>``; non-uuid values are kept.

Nothing else is stripped. Content fields (payload_json, artifact metadata,
contradiction parties/overlap/detector_version, created_at under the frozen
clock) are compared verbatim. Identity scheme (G1) is NOT changed here.

Clock: scenarios use a frozen clock. Production uses wall-clock
(``hermes.core.__init__``), so ``created_at`` differs across real runs; that is
part of the G1 identity gap and is out of scope for this harness.
"""
from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from hermes.core import frozen_clock
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.controller import Controller

CLOCK = "2026-01-01T00:00:00.000000+00:00"
PROJECT = "p1"
FAN_OUT_BOUND = 500  # spec literal; must be >= the pair cap, asserted below
TRUNCATED_KEY = "DETECTOR_TRUNCATED"
EVIDENCE_HASH = "evhash1"
EVIDENCE_ID = "art-ev1"

_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

PROVENANCE_STRIP: tuple[tuple[str, str], ...] = (("events", "correlation_id"),)

_CLASSES = ("DECLARED_CONSTRAINT_VIOLATION", "IMPLEMENTATION_FAILURE")


def _insert_artifact(conn: sqlite3.Connection, artifact_id: str, *,
                     artifact_type: str, content_hash: str | None,
                     meta: dict[str, Any] | None) -> None:
    conn.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, NULL, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, PROJECT, artifact_type, content_hash,
         json.dumps(meta) if meta is not None else None, CLOCK))


def _insert_classification(conn: sqlite3.Connection, cls_id: str,
                           failure_class: str, program: str,
                           hypothesis: str) -> None:
    from hermes.research.evidence_ladder import classification_content_hash
    from hermes.research.failure_classification import ACTION_MAP, FailureClass

    permitted = sorted(a.value for a in ACTION_MAP[FailureClass(failure_class)])
    refs = [f"evidence:{EVIDENCE_HASH}"]
    meta = {
        "schema_version": "1",
        "failure_class": failure_class,
        "hypothesis_ref": hypothesis,
        "program_ref": program,
        "classification_id": cls_id,
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": refs,
        "constraint_ref": f"hypothesis:{hypothesis}:falsification_condition",
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": f"replay-diff {cls_id}",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": list(refs),
        "permitted_actions": permitted,
    }
    _insert_artifact(conn, cls_id, artifact_type="failure_classification",
                     content_hash=classification_content_hash(meta, PROJECT),
                     meta=meta)


def build_scenario(db_path: Path, n: int) -> sqlite3.Connection:
    """Create a fresh DB with one project, one shared evidence artifact and
    ``n`` classifications alternating between two failure classes (all in the
    same program/hypothesis, so every cross-class pair is eligible)."""
    conn = connect(str(db_path))
    migrate_to_latest(conn, frozen_clock(CLOCK))
    ProjectRepository(conn, frozen_clock(CLOCK)).create(PROJECT, "Replay")
    _insert_artifact(conn, EVIDENCE_ID, artifact_type="evidence",
                     content_hash=EVIDENCE_HASH, meta=None)
    for i in range(n):
        _insert_classification(
            conn, f"fc-{i:03d}", _CLASSES[i % 2], "rp-1", "h1")
    return conn


def run_detector(conn: sqlite3.Connection) -> dict[str, Any]:
    return Controller(conn, project_id=PROJECT,
                      clock=frozen_clock(CLOCK)).detect_contradictions()


def canonical_dump(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """Every user table, rows sorted by canonical JSON, with the declared
    provenance strip applied and nothing else changed."""
    out: dict[str, list[dict[str, Any]]] = {}
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for table in tables:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        rows = []
        for raw in conn.execute(f"SELECT * FROM {table}"):
            row = dict(zip(cols, tuple(raw)))
            for tbl, col in PROVENANCE_STRIP:
                if tbl == table and isinstance(row.get(col), str) \
                        and _UUID4.match(row[col]):
                    row[col] = "<uuid4>"
            rows.append(row)
        rows.sort(key=lambda r: json.dumps(r, sort_keys=True, default=str))
        out[table] = rows
    return out


def run_twice_equal(n: int, workdir: Path) -> list[str]:
    dumps = []
    for label in ("a", "b"):
        conn = build_scenario(workdir / f"run_{label}.db", n)
        try:
            run_detector(conn)
            dumps.append(canonical_dump(conn))
        finally:
            conn.close()
    failures: list[str] = []
    if dumps[0] != dumps[1]:
        for table in sorted(set(dumps[0]) | set(dumps[1])):
            if dumps[0].get(table) != dumps[1].get(table):
                failures.append(f"table {table!r} differs between runs")
    return failures


def journal_reproduces_derived(conn: sqlite3.Connection) -> list[str]:
    """Fold ContradictionDetected events and compare to the derived table."""
    projected: dict[str, tuple[str, str, str, str]] = {}
    for ev in conn.execute(
            "SELECT payload_json FROM events WHERE event_type = ? "
            "ORDER BY event_id", ("ContradictionDetected",)):
        p = json.loads(ev["payload_json"])
        projected[p["contradiction_id"]] = (
            p["party_a"], p["party_b"],
            json.dumps(p["evidence_overlap"]), p["detector_version"])
    derived: dict[str, tuple[str, str, str, str]] = {}
    for row in conn.execute(
            "SELECT contradiction_id, party_a, party_b, evidence_overlap_json, "
            "detector_version FROM contradictions"):
        derived[row["contradiction_id"]] = (
            row["party_a"], row["party_b"],
            json.dumps(json.loads(row["evidence_overlap_json"])),
            row["detector_version"])
    failures: list[str] = []
    if projected != derived:
        only_j = sorted(set(projected) - set(derived))
        only_d = sorted(set(derived) - set(projected))
        changed = sorted(k for k in set(projected) & set(derived)
                         if projected[k] != derived[k])
        failures.append(
            f"journal fold != derived table: journal-only={len(only_j)} "
            f"derived-only={len(only_d)} changed={len(changed)}")
    return failures


def replay_over_recorded_journal(n: int, workdir: Path) -> list[str]:
    """Run once, check the journal fold reproduces the derived table, then
    re-derive from the stored classification artifacts in a fresh DB and
    check the recorded set is reproduced."""
    src = build_scenario(workdir / "replay_src.db", n)
    try:
        first = run_detector(src)
        failures = journal_reproduces_derived(src)
        first_ids = sorted(first["recorded"])
    finally:
        src.close()
    dst = build_scenario(workdir / "replay_dst.db", n)
    try:
        second = run_detector(dst)
        if sorted(second["recorded"]) != first_ids:
            failures.append("re-derivation from stored artifacts did not "
                            "reproduce the recorded contradiction set")
        failures.extend(journal_reproduces_derived(dst))
    finally:
        dst.close()
    return failures


def fan_out_bounded(n: int, workdir: Path) -> tuple[list[str], dict[str, Any]]:
    """Intent fan-out for a dense group must be bounded and self-reporting.

    With ``n`` classifications alternating between two classes there are
    ``ceil(n/2) * floor(n/2)`` eligible cross-class pairs. If that exceeds
    FAN_OUT_BOUND the run must be capped AND carry the truncation diagnostic.
    """
    conn = build_scenario(workdir / "fanout.db", n)
    try:
        out = run_detector(conn)
    finally:
        conn.close()
    emitted = len(out["recorded"]) + out["duplicates"] + len(out["refused"])
    eligible = ((n + 1) // 2) * (n // 2)
    failures: list[str] = []
    if emitted > FAN_OUT_BOUND:
        failures.append(
            f"unbounded fan-out: {emitted} intents for n={n} "
            f"(bound {FAN_OUT_BOUND})")
    if eligible > FAN_OUT_BOUND and out.get("truncated") is None:
        failures.append(
            f"{eligible} eligible pairs exceed bound but no {TRUNCATED_KEY} "
            "diagnostic was raised")
    return failures, {"n": n, "eligible": eligible, "emitted": emitted,
                      "truncated": out.get("truncated")}


def run_all(workdir: Path | None = None) -> dict[str, list[str]]:
    base = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="rdiff-"))
    base.mkdir(parents=True, exist_ok=True)
    fan, _ = fan_out_bounded(100, base)
    return {
        "run_twice_equal[n=5]": run_twice_equal(5, base),
        "journal_reproduces_derived[n=5]":
            replay_over_recorded_journal(5, base),
        "fan_out_bounded[n=100]": fan,
    }


if __name__ == "__main__":
    import sys

    results = run_all()
    bad = {k: v for k, v in results.items() if v}
    for k, v in results.items():
        print(f"{'FAIL' if v else 'PASS'} {k}")
        for f in v:
            print(f"    - {f}")
    sys.exit(1 if bad else 0)
