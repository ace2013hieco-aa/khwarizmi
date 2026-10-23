"""TAMPER-1 product pins: the append-only journal triggers (IDR §2.1/§3.1).

The design record (``docs/idr/TAMPER-EVIDENT-JOURNAL.md``) specifies the
``BEFORE UPDATE`` / ``BEFORE DELETE`` abort triggers on ``events``, the named
error contract, and the rebuild rule (any migration touching ``events`` must
re-create both triggers last). This module pins the shipped behavior:

- fresh reachability (0 → 21) and upgrade reachability from a legacy v20;
- the exact surfacing: ``sqlite3.IntegrityError`` carrying the named error,
  with the aborted statement leaving the row unchanged;
- the single-writer path (``_append_event_to_db``) still appending;
- the ``_migrate_2_to_3`` rebuild re-forming the triggers (v2 → v3) and a
  fresh full run preserving pre-rebuild rows byte-identically;
- trigger DDL parity with the design's reference prover
  (``tests/tamper_evident_reference.py``);
- the documented residual gap: ``DROP TRIGGER`` is not covered (TAMPER-2).
"""
from __future__ import annotations

import re
import sqlite3

import pytest

from hermes.core import frozen_clock
from hermes.persistence.database import connect, get_schema_version
from hermes.persistence.migrations import (
    _MIGRATIONS,
    SUPPORTED_VERSION,
    _migrate_2_to_3,
    migrate_to_latest,
)
from hermes.persistence.repositories import (
    ProjectRepository,
    _append_event_to_db,
)
from tests.tamper_evident_reference import (
    DELETE_TRIGGER_ERROR,
    TRIGGER_DDL,
    UPDATE_TRIGGER_ERROR,
)

CLOCK = frozen_clock("2026-01-01T00:00:00.000000+00:00")
TS = "2026-01-01T00:00:00.000000+00:00"
UPDATE_TRIGGER = "trg_events_append_only_update"
DELETE_TRIGGER = "trg_events_append_only_delete"


def _run_migrations(conn: sqlite3.Connection, upto: int) -> None:
    """Apply the first ``upto`` registry migrations (legacy-build helper)."""
    for fn in _MIGRATIONS[:upto]:
        conn.execute("BEGIN")
        fn(conn, CLOCK)
        conn.execute("COMMIT")


def _triggers(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' "
        "AND tbl_name = 'events' ORDER BY name").fetchall()
    return {row["name"]: row["sql"] for row in rows}


def _append_raw(conn: sqlite3.Connection, marker: str) -> None:
    conn.execute(
        "INSERT INTO events (event_type, project_id, correlation_id, "
        "payload_json, created_at) VALUES (?, NULL, ?, '{}', ?)",
        (marker, marker.lower(), TS))
    conn.commit()


def _rows(conn: sqlite3.Connection) -> list[tuple]:
    return [tuple(row) for row in conn.execute(
        "SELECT event_id, event_type, correlation_id, payload_json, created_at "
        "FROM events ORDER BY event_id")]


def _assert_refused(conn: sqlite3.Connection, sql: str, message: str) -> None:
    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        conn.execute(sql)
    assert type(excinfo.value).__module__ == "sqlite3"
    assert str(excinfo.value) == message


# ── fresh + upgrade reachability ──

def test_fresh_db_migrates_to_latest_with_triggers():
    assert SUPPORTED_VERSION == 23
    assert len(_MIGRATIONS) == 23
    conn = connect(":memory:")
    assert migrate_to_latest(conn, clock=CLOCK) == 23

    triggers = _triggers(conn)
    assert set(triggers) == {UPDATE_TRIGGER, DELETE_TRIGGER}
    assert "BEFORE UPDATE ON events" in triggers[UPDATE_TRIGGER]
    assert "BEFORE DELETE ON events" in triggers[DELETE_TRIGGER]
    assert UPDATE_TRIGGER_ERROR in triggers[UPDATE_TRIGGER]
    assert DELETE_TRIGGER_ERROR in triggers[DELETE_TRIGGER]
    conn.close()


def test_upgrade_from_v20_adds_triggers_and_preserves_rows():
    """A legacy v20 database (no triggers) upgrades in place; v21 adds them."""
    conn = connect(":memory:")
    _run_migrations(conn, 20)
    assert get_schema_version(conn) == 20
    _append_raw(conn, "LegacyEvent")
    # A genuine pre-TAMPER-1 v20 database carries no triggers; the 2 → 3
    # rebuild re-forms them on this tree, so drop them to reproduce the
    # legacy shape — the 20 → 21 upgrade must add them on its own.
    for name in (UPDATE_TRIGGER, DELETE_TRIGGER):
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    assert _triggers(conn) == {}
    before = _rows(conn)

    assert migrate_to_latest(conn, clock=CLOCK) == 23
    assert set(_triggers(conn)) == {UPDATE_TRIGGER, DELETE_TRIGGER}
    assert _rows(conn) == before
    _assert_refused(
        conn, "UPDATE events SET event_type = 'T' WHERE event_id = 1",
        UPDATE_TRIGGER_ERROR)
    _assert_refused(
        conn, "DELETE FROM events WHERE event_id = 1", DELETE_TRIGGER_ERROR)
    _append_raw(conn, "PostUpgradeEvent")  # INSERT still works
    assert len(_rows(conn)) == 2
    conn.close()


# ── the surfacing: sqlite3.IntegrityError, named, row unchanged ──

def test_update_and_delete_refused_with_named_error_row_unchanged():
    conn = connect(":memory:")
    migrate_to_latest(conn, clock=CLOCK)
    _append_raw(conn, "PinnedEvent")

    _assert_refused(
        conn, "UPDATE events SET event_type = 'Tampered' WHERE event_id = 1",
        UPDATE_TRIGGER_ERROR)
    _assert_refused(
        conn, "DELETE FROM events WHERE event_id = 1", DELETE_TRIGGER_ERROR)

    row = conn.execute(
        "SELECT event_type FROM events WHERE event_id = 1").fetchone()
    assert row["event_type"] == "PinnedEvent"
    assert conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"] == 1
    conn.close()


def test_repo_writer_appends_and_tamper_surfaces_as_integrity_error():
    """The single writer keeps appending; a raw tamper on the same
    connection surfaces as ``sqlite3.IntegrityError`` with the named error."""
    conn = connect(":memory:")
    migrate_to_latest(conn, clock=CLOCK)
    ProjectRepository(conn, clock=CLOCK).create("p1", "Alpha")
    _append_event_to_db(conn, CLOCK, "TaskStatusChanged", project_id="p1")
    conn.commit()
    types = [row[1] for row in _rows(conn)]
    assert types == ["ResearchCreated", "TaskStatusChanged"]

    _assert_refused(
        conn, "UPDATE events SET reason = 'forged' WHERE event_id = 1",
        UPDATE_TRIGGER_ERROR)
    _assert_refused(
        conn, "DELETE FROM events WHERE event_id = 1", DELETE_TRIGGER_ERROR)
    assert [row[1] for row in _rows(conn)] == types
    conn.close()


# ── the §3.1 rebuild rule on the _migrate_2_to_3 path ──

def test_v2_rebuild_recreates_triggers():
    conn = connect(":memory:")
    _run_migrations(conn, 2)
    assert get_schema_version(conn) == 2
    _append_raw(conn, "PreRebuildEvent")
    before = _rows(conn)

    conn.execute("BEGIN")
    _migrate_2_to_3(conn, CLOCK)
    conn.execute("COMMIT")

    assert get_schema_version(conn) == 3
    assert set(_triggers(conn)) == {UPDATE_TRIGGER, DELETE_TRIGGER}
    assert _rows(conn) == before
    _assert_refused(
        conn, "UPDATE events SET event_type = 'T' WHERE event_id = 1",
        UPDATE_TRIGGER_ERROR)
    _assert_refused(
        conn, "DELETE FROM events WHERE event_id = 1", DELETE_TRIGGER_ERROR)
    _append_raw(conn, "PostRebuildEvent")
    assert len(_rows(conn)) == 2
    conn.close()


def test_fresh_full_migration_preserves_pre_rebuild_rows():
    conn = connect(":memory:")
    _run_migrations(conn, 2)
    _append_raw(conn, "EarlyEvent")
    before = _rows(conn)

    assert migrate_to_latest(conn, clock=CLOCK) == 23
    assert _rows(conn) == before
    assert set(_triggers(conn)) == {UPDATE_TRIGGER, DELETE_TRIGGER}
    _assert_refused(
        conn, "DELETE FROM events WHERE event_id = 1", DELETE_TRIGGER_ERROR)
    conn.close()


# ── design parity + durability + the residual gap ──

def test_shipped_triggers_match_the_design_reference():
    """§2.1 DDL is "exact, to be reproduced verbatim": each migrated trigger
    must equal the reference prover's DDL, modulo whitespace — SQLite stores
    the statement text with ``IF NOT EXISTS`` stripped."""
    reference: dict[str, str] = {}
    for ddl in TRIGGER_DDL:
        match = re.search(r"CREATE TRIGGER IF NOT EXISTS (\w+)", ddl)
        assert match is not None
        reference[match.group(1)] = ddl
    assert set(reference) == {UPDATE_TRIGGER, DELETE_TRIGGER}
    assert any(UPDATE_TRIGGER_ERROR in ddl for ddl in TRIGGER_DDL)
    assert any(DELETE_TRIGGER_ERROR in ddl for ddl in TRIGGER_DDL)

    conn = connect(":memory:")
    migrate_to_latest(conn, clock=CLOCK)
    shipped = _triggers(conn)
    assert set(shipped) == set(reference)
    for name, ddl in reference.items():
        expected = " ".join(ddl.replace("IF NOT EXISTS ", "").split())
        assert " ".join(shipped[name].split()) == expected
    conn.close()


def test_triggers_persist_across_reopen(tmp_path):
    path = tmp_path / "hermes.db"
    conn = connect(str(path))
    migrate_to_latest(conn, clock=CLOCK)
    _append_raw(conn, "DurableEvent")
    conn.close()

    conn = connect(str(path))
    assert set(_triggers(conn)) == {UPDATE_TRIGGER, DELETE_TRIGGER}
    _assert_refused(
        conn, "UPDATE events SET event_type = 'T' WHERE event_id = 1",
        UPDATE_TRIGGER_ERROR)
    conn.close()


def test_drop_trigger_is_the_documented_residual_gap():
    """The addendum's honesty clause: raw ``DROP TRIGGER`` (explicit DDL)
    is not covered — the mutation then succeeds. TAMPER-2 territory."""
    conn = connect(":memory:")
    migrate_to_latest(conn, clock=CLOCK)
    _append_raw(conn, "GapEvent")
    conn.execute(f"DROP TRIGGER {UPDATE_TRIGGER}")
    conn.execute(f"DROP TRIGGER {DELETE_TRIGGER}")
    conn.execute("UPDATE events SET event_type = 'Rewritten' WHERE event_id = 1")
    conn.execute("DELETE FROM events WHERE event_id = 1")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"] == 0
    conn.close()
