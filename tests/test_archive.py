"""EXT-4 cold-archive tests (triage L1 / I4 — additive archival only).

Pins the discipline the L1 triage demands:

- **Additive only.** An export COPIES resolved/superseded rows into a
  content-addressed cold archive. It never deletes and never mutates a hot
  row — proven here by snapshotting the whole database before and after.
- **The journal stays whole.** ``events`` is never a cold table, so
  ``journal_gap_event_ids`` still reports a compaction hole as tampering
  after an export ran.
- **Verification is fail-closed.** A flipped byte, a missing chunk, or a
  row-set mismatch each refuse rather than pass.
- **Idempotent by key.** A second export appends nothing; a newly resolved
  row appears in the next export.
- **Cold classes only.** OPEN contradictions and ADMITTED curated entries
  stay hot; only their terminal counterparts are exported.

Prohibited-claims discipline: these tests verify byte fidelity of the export
against the database. They make no claim about scientific validity or
reproducibility of any research result.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from hermes.persistence.archive import (
    ARCHIVE_SCHEMA,
    ArchiveBindingError,
    ArchiveError,
    ArchiveIntegrityError,
    ColdArchive,
)
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.vault.manifest import journal_gap_event_ids

TABLES = (
    "events", "artifacts", "contradictions",
    "curated_knowledge_entries", "curated_knowledge_supersession",
)
TS = "2026-01-01T00:00:00Z"


def _canon(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _snapshot(conn: sqlite3.Connection) -> dict[str, str]:
    """A digest of every row of every table under test — the mutation tripwire."""
    out: dict[str, str] = {}
    for table in TABLES:
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        payload = [
            dict(r) for r in rows
        ]
        out[table] = _canon(payload)
    return out


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(str(tmp_path / "arch.db"))
    migrate_to_latest(conn)
    conn.execute(
        "INSERT INTO projects (project_id, name, lifecycle_state, "
        "created_at, updated_at) VALUES ('p1','arch','CREATED',?,?)", (TS, TS))
    # 12 artifacts: contradictions need party_a < party_b, distinct, admitted.
    for i in range(12):
        conn.execute(
            "INSERT INTO artifacts (artifact_id, project_id, artifact_type, "
            "content_hash, size_bytes, storage_path, producer, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (f"art-{i}", "p1", "failure_classification", f"{i:064x}",
             16, "/dev/null", "test", TS))
    # 4 journal rows — the append-only truth that must never move.
    for i in range(4):
        conn.execute(
            "INSERT INTO events (event_type, project_id, correlation_id, "
            "payload_json, created_at) VALUES (?,?,?,?,?)",
            ("ArchiveTest", "p1", f"c{i}", _canon({"i": i}), TS))
    # 6 contradictions: 2 OPEN (hot), 2 RESOLVED (cold), 2 SUPERSEDED (cold).
    cxs = []
    for i, status in enumerate(
            ["OPEN", "OPEN", "RESOLVED", "RESOLVED", "SUPERSEDED",
             "SUPERSEDED"]):
        a, b = f"art-{2 * i}", f"art-{2 * i + 1}"
        assert a < b
        cxs.append((
            f"cx-{i}", "p1", "CLASSIFICATION_CONFLICT", a, b, "[]", status,
            "v1", TS, f"det-{i}",
            None if status == "OPEN" else f"res-{i}",
            None if status != "RESOLVED" else _canon({"v": "A"}),
            None, TS))
    for row in cxs:
        conn.execute(
            "INSERT INTO contradictions (contradiction_id, project_id, type, "
            "party_a, party_b, evidence_overlap_json, status, "
            "detector_version, detected_at, detection_event_ref, "
            "resolution_event_ref, resolution_rationale_digest, "
            "supersedes_ref, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
    # 4 curated entries: 2 ADMITTED (hot), 1 SUPERSEDED, 1 INVALIDATED (cold).
    curs = []
    for i, status in enumerate(
            ["ADMITTED", "ADMITTED", "SUPERSEDED", "INVALIDATED"]):
        curs.append((
            f"cur-{i}", "REFUTED_PATTERN", _canon({"s": i}), "p1",
            f"art-{2 * i}", f"dec-{i}", "prog", "hyp", f"adm-{i}",
            f"adec-{i}", TS, status,
            None if status != "INVALIDATED" else f"inv-{i}"))
    for row in curs:
        conn.execute(
            "INSERT INTO curated_knowledge_entries (curated_id, kind, "
            "signature_json, source_project_id, source_binding_ref, "
            "source_decision_event_ref, program_ref, hypothesis_ref, "
            "admission_event_ref, admission_decision_ref, admitted_at, "
            "status, invalidation_event_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            row)
    conn.execute(
        "INSERT INTO curated_knowledge_supersession (new_curated_id, "
        "supersedes_ref, supersession_event_ref) VALUES (?,?,?)",
        ("cur-2", "cur-0", "sup-0"))
    return conn


def _chunks(root: Path) -> list[Path]:
    return sorted((root / "chunks").glob("*.ndjson"))


# ── export: cold classes only ──


def test_export_takes_only_terminal_rows(db, tmp_path):
    """OPEN contradictions and ADMITTED curated entries stay hot."""
    arch = ColdArchive(tmp_path / "a1")
    result = arch.export(db, chunk_size=2)

    # cold = 4 contradictions (2 RESOLVED + 2 SUPERSEDED) + 2 curated entries
    # (1 SUPERSEDED + 1 INVALIDATED) + 1 supersession row = 7
    assert result.appended == 7
    assert result.total == 7
    assert result.appended_by_table == {
        "contradictions": 4,
        "curated_knowledge_entries": 2,
        "curated_knowledge_supersession": 1,
    }
    assert result.chunks_written == 4  # ceil(7 / 2)

    lines = b"".join(p.read_bytes() for p in _chunks(tmp_path / "a1"))
    keys = {
        f"{json.loads(ln)['table']}:{json.loads(ln)['key']}"
        for ln in lines.split(b"\n") if ln
    }
    assert keys == {
        "contradictions:cx-2", "contradictions:cx-3",
        "contradictions:cx-4", "contradictions:cx-5",
        "curated_knowledge_entries:cur-2", "curated_knowledge_entries:cur-3",
        "curated_knowledge_supersession:cur-2",
    }


def test_status_is_none_before_and_populated_after(db, tmp_path):
    arch = ColdArchive(tmp_path / "a2")
    assert arch.status() is None
    arch.export(db, chunk_size=10)
    status = arch.status()
    assert status is not None
    assert status.rows == 7
    assert status.tables == (
        "contradictions", "curated_knowledge_entries",
        "curated_knowledge_supersession")
    assert status.chunk_count == 1


# ── additive: never a delete, never a mutation ──


def test_export_never_mutates_the_database(db, tmp_path):
    """The whole-DB tripwire: every row of every table is byte-identical."""
    before = _snapshot(db)
    arch = ColdArchive(tmp_path / "a3")
    arch.export(db, chunk_size=3)
    arch.export(db, chunk_size=3)
    after = _snapshot(db)

    assert after == before, "an export mutated the hot database"
    # specifically: the journal is still whole
    assert after["events"] == before["events"]
    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 4


def test_events_is_never_a_cold_table(db, tmp_path):
    """No journal row may ever be exported — the journal is the audit trail."""
    arch = ColdArchive(tmp_path / "a4")
    arch.export(db, chunk_size=10)
    manifest = json.loads(
        (tmp_path / "a4" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == ARCHIVE_SCHEMA
    assert "events" not in manifest["tables"]
    assert not any(k.startswith("events:") for k in manifest["row_digests"])


# ── verification: fail-closed ──


def test_verify_proves_a_clean_export(db, tmp_path):
    arch = ColdArchive(tmp_path / "a5")
    arch.export(db, chunk_size=4)
    proof = arch.verify()
    assert proof.rows == 7
    assert proof.chunks == 2
    assert proof.files_checked == 2
    assert proof.row_digests_checked == 7


def test_verify_refuses_a_flipped_byte(db, tmp_path):
    arch = ColdArchive(tmp_path / "a6")
    arch.export(db, chunk_size=10)
    chunk = _chunks(tmp_path / "a6")[0]
    raw = bytearray(chunk.read_bytes())
    raw[-2] ^= 0x01  # inside the last row, before the trailing newline
    chunk.write_bytes(bytes(raw))
    with pytest.raises(ArchiveIntegrityError):
        arch.verify()


def test_verify_refuses_a_missing_chunk(db, tmp_path):
    arch = ColdArchive(tmp_path / "a7")
    arch.export(db, chunk_size=1)
    _chunks(tmp_path / "a7")[0].unlink()
    with pytest.raises(ArchiveIntegrityError):
        arch.verify()


def test_verify_refuses_a_row_set_mismatch(db, tmp_path):
    """A manifest row that is not on disk (or vice versa) must refuse."""
    arch = ColdArchive(tmp_path / "a8")
    arch.export(db, chunk_size=10)
    manifest_path = tmp_path / "a8" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["row_digests"]["contradictions:cx-999"] = "0" * 64
    manifest["row_count"] += 1
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8")
    with pytest.raises(ArchiveIntegrityError):
        arch.verify()


def test_verify_refuses_an_absent_archive(tmp_path):
    with pytest.raises(ArchiveIntegrityError):
        ColdArchive(tmp_path / "never").verify()


def test_verify_refuses_an_unknown_schema(db, tmp_path):
    arch = ColdArchive(tmp_path / "a9")
    arch.export(db, chunk_size=10)
    manifest_path = tmp_path / "a9" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema"] = 99
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8")
    with pytest.raises(ArchiveIntegrityError):
        arch.verify()


# ── idempotence and increment ──


def test_export_is_idempotent_by_key(db, tmp_path):
    arch = ColdArchive(tmp_path / "a10")
    first = arch.export(db, chunk_size=2)
    second = arch.export(db, chunk_size=2)
    assert first.appended == 7
    assert second.appended == 0
    assert second.total == first.total
    assert second.chunks_written == 0
    assert arch.verify().rows == first.total


def test_export_picks_up_a_newly_terminal_row(db, tmp_path):
    """A row that becomes cold later is exported by the NEXT pass."""
    arch = ColdArchive(tmp_path / "a11")
    arch.export(db, chunk_size=10)
    db.execute("UPDATE contradictions SET status='RESOLVED' "
               "WHERE contradiction_id='cx-0'")
    second = arch.export(db, chunk_size=10)
    assert second.appended == 1
    assert second.appended_by_table == {"contradictions": 1}
    arch.verify()
    lines = b"".join(p.read_bytes() for p in _chunks(tmp_path / "a11"))
    keys = {json.loads(ln)["key"] for ln in lines.split(b"\n") if ln}
    assert "cx-0" in keys


# ── the tamper evidence that must survive ──


def test_journal_hole_detection_survives_an_export(db, tmp_path):
    """Exporting must not disable the compaction-hole tamper signal."""
    arch = ColdArchive(tmp_path / "a12")
    arch.export(db, chunk_size=2)
    arch.verify()

    ceiling = db.execute("SELECT MAX(event_id) FROM events").fetchone()[0]
    assert journal_gap_event_ids(db, ceiling + 10) == ()

    # a hole is what a compacted/lost row looks like — still detected after export
    db.execute("DELETE FROM events WHERE event_id = 2")
    assert journal_gap_event_ids(db, ceiling + 10) == (2,)


# ── binding refusals ──


def test_bad_chunk_size_refuses(db, tmp_path):
    arch = ColdArchive(tmp_path / "a13")
    for bad in (0, -1, "2", None):
        with pytest.raises(ArchiveBindingError):
            arch.export(db, chunk_size=bad)  # type: ignore[arg-type]


def test_root_that_is_a_file_refuses(tmp_path):
    a_file = tmp_path / "not-a-dir"
    a_file.write_text("x", encoding="utf-8")
    with pytest.raises(ArchiveBindingError):
        ColdArchive(a_file)


def test_archive_errors_share_a_base(db, tmp_path):
    assert issubclass(ArchiveIntegrityError, ArchiveError)
    assert issubclass(ArchiveBindingError, ArchiveError)
    arch = ColdArchive(tmp_path / "a14")
    arch.export(db, chunk_size=10)
    arch.verify()
