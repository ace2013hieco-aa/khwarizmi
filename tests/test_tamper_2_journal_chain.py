"""TAMPER-2 product pins: the per-event hash chain, migration 22 -> 23, and
the re-chain tool (``docs/idr/TAMPER-EVIDENT-JOURNAL.md`` §1, addendum A7).

The design record is the contract; this module proves it against the same
frozen fixtures the reference prover pins (``tests/tamper_evident_reference.py``
+ ``tests/fixtures/tamper_evident/``), and against a real SQLite journal:

- ``chain_row`` / ``verify_journal_chain`` reproduce the frozen digests
  (M1/M2/M11) and agree with the reference implementation on **every**
  ``tamper_cases.json`` mutant (M3-M8);
- the 22 -> 23 migration backfills a populated v22 journal to ``CHAIN_OK``
  with ``created_at`` byte-identical and both triggers refusing again;
- appends chain onto the backfilled tip, and onto the last non-NULL tip when
  a raw row left a hole (which still verifies as ``CHAIN_UNCHAINED_ROW``);
- a dropped trigger is a named structural finding, and restoring it is
  ``CHAIN_OK``;
- a re-chain of a tampered journal blesses the current bytes (``changed > 0``,
  new tip, then ``CHAIN_OK``) and refuses without an open transaction;
- the CLI verifies (exit 0 only on ``CHAIN_OK`` + no findings), refuses an
  unconfirmed re-chain, refuses a wrong schema version, and refuses a stale
  ``--anchor`` without touching the journal;
- no production read path verifies the chain (A3).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

import pytest

import hermes.persistence.migrations as migrations
from hermes.cli import main
from hermes.core import frozen_clock
from hermes.persistence.database import connect, get_schema_version
from hermes.persistence.journal_chain import (
    CHAIN_VERSION,
    CHAINED_FIELDS,
    GENESIS,
    chain_row,
    missing_append_only_triggers,
    rechain_journal,
    verify_journal,
    verify_journal_chain,
)
from hermes.persistence.migrations import (
    _MIGRATIONS,
    SUPPORTED_VERSION,
    _migrate_22_to_23,
    migrate_to_latest,
)
from hermes.persistence.repositories import (
    ProjectRepository,
    _append_event_to_db,
)
from tests.journal_tamper import tamper_events
from tests.tamper_evident_reference import (
    DELETE_TRIGGER_ERROR,
    UPDATE_TRIGGER_ERROR,
)
from tests.tamper_evident_reference import (
    verify_journal_chain as reference_verify,
)

CLOCK = frozen_clock("2026-01-01T00:00:00.000000+00:00")
TS = "2026-01-01T00:00:00.000000+00:00"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tamper_evident"

UPDATE_TRIGGER = "trg_events_append_only_update"
DELETE_TRIGGER = "trg_events_append_only_delete"


# ── fixtures and helpers ──

def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _clean() -> dict[str, Any]:
    return _load("journal_clean.json")


def _cases() -> list[dict[str, Any]]:
    return _load("tamper_cases.json")["cases"]


def _apply_case(
    case: Mapping[str, Any], rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Materialize one structural tamper case over a copy of the base rows."""
    mutated = [dict(row) for row in rows]
    op = case["op"]
    if op == "set":
        mutated[case["row_index"]][case["field"]] = case["value"]
    elif op == "delete":
        del mutated[case["row_index"]]
    elif op == "truncate":
        mutated = mutated[: case["keep"]]
    elif op == "clear_chain":
        row = mutated[case["row_index"]]
        row["prev_hash"] = None
        row["chain_hash"] = None
    elif op == "swap":
        row = mutated[case["row_index"]]
        row[case["field"]], row[case["other_field"]] = (
            row[case["other_field"]], row[case["field"]],
        )
    else:  # pragma: no cover — an unknown op is a fixture bug
        raise AssertionError(f"unknown op {op!r} in case {case['id']!r}")
    return mutated


def _run_migrations(conn: sqlite3.Connection, upto: int) -> None:
    """Apply the first ``upto`` registry migrations (legacy-build helper)."""
    for fn in _MIGRATIONS[:upto]:
        conn.execute("BEGIN")
        fn(conn, CLOCK)
        conn.execute("COMMIT")


def _v22_db() -> sqlite3.Connection:
    conn = connect(":memory:")
    _run_migrations(conn, 22)
    assert get_schema_version(conn) == 22
    return conn


def _raw_event(conn: sqlite3.Connection, event_type: str = "RawEvent") -> None:
    """A raw INSERT that bypasses the writer and leaves both chain columns NULL."""
    conn.execute(
        "INSERT INTO events (event_type, project_id, correlation_id, "
        "payload_json, created_at) VALUES (?, NULL, ?, '{}', ?)",
        (event_type, event_type.lower(), TS))
    conn.commit()


def _chain_of(conn: sqlite3.Connection) -> list[tuple[str | None, str | None]]:
    return [tuple(row) for row in conn.execute(
        "SELECT prev_hash, chain_hash FROM events ORDER BY event_id")]


def _created_at(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return [tuple(row) for row in conn.execute(
        "SELECT event_id, created_at FROM events ORDER BY event_id")]


def _assert_refused(conn: sqlite3.Connection, sql: str, message: str) -> None:
    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        conn.execute(sql)
    assert message in str(excinfo.value)


def _migrated_file(tmp_path: Path) -> Path:
    """A v23 database file holding one project and its event."""
    path = tmp_path / "journal.db"
    conn = connect(str(path))
    migrate_to_latest(conn, clock=CLOCK)
    ProjectRepository(conn, clock=CLOCK).create("p1", "Alpha")
    conn.close()
    return path


# ── A1: version, genesis, field list ──

def test_chain_version_and_genesis_are_frozen():
    assert CHAIN_VERSION == "hermes.journal.chain.v1"
    assert GENESIS == (
        "1cc5f8a885ca75f3edb337cef85b5f7835283725e46f72e629e225dbbcd46ba2")
    assert len(CHAINED_FIELDS) == 11
    assert CHAINED_FIELDS == (
        "event_id", "event_type", "project_id", "task_id", "from_state",
        "to_state", "correlation_id", "caused_by", "reason",
        "artifact_ids_json", "payload_json",
    )
    assert "created_at" not in CHAINED_FIELDS


# ── M1/M2/M11: the frozen digests are reproduced ──

@pytest.mark.parametrize("fixture_name", ["journal_clean.json",
                                          "journal_rebuilt.json"])
def test_chain_row_reproduces_the_frozen_digests(fixture_name):
    fixture = _load(fixture_name)

    assert fixture["chain_version"] == CHAIN_VERSION
    assert fixture["genesis"] == GENESIS

    running = GENESIS
    for row in fixture["rows"]:
        assert row["prev_hash"] == running
        running = chain_row(running, row)
        assert row["chain_hash"] == running

    assert running == fixture["tip"]


def test_verify_journal_chain_matches_the_frozen_tip():
    fixture = _clean()
    result = verify_journal_chain(fixture["rows"], anchor=fixture["tip"])

    assert result["ok"] is True
    assert result["code"] == "CHAIN_OK"
    assert result["tip"] == fixture["tip"]
    assert result["genesis"] == GENESIS


# ── M3-M8: every mutant agrees with the reference implementation ──

@pytest.mark.parametrize("case", _cases(), ids=[c["id"] for c in _cases()])
def test_verify_journal_chain_agrees_with_the_reference_on_every_mutant(case):
    fixture = _clean()
    rows = _apply_case(case, fixture["rows"])

    ours = verify_journal_chain(rows)
    reference = reference_verify(rows)

    assert ours["code"] == reference["code"]
    assert ours["event_id"] == reference["event_id"]
    assert ours["tip"] == reference["tip"]
    assert ours["code"] == case["expect"]["code"]
    assert ours["event_id"] == case["expect"]["event_id"]


def test_truncated_tail_is_caught_only_by_the_anchor():
    fixture = _clean()
    case = next(c for c in _cases() if c["op"] == "truncate")
    rows = _apply_case(case, fixture["rows"])

    assert verify_journal_chain(rows)["code"] == "CHAIN_OK"
    anchored = verify_journal_chain(rows, anchor=fixture["tip"])
    assert anchored["code"] == "CHAIN_TIP_MISMATCH"


def test_unchained_row_fails_closed_and_can_be_allowed():
    fixture = _clean()
    case = next(c for c in _cases() if c["op"] == "clear_chain")
    rows = _apply_case(case, fixture["rows"])

    strict = verify_journal_chain(rows)
    assert strict["code"] == "CHAIN_UNCHAINED_ROW"
    assert strict["ok"] is False

    lenient = verify_journal_chain(rows, allow_unchained=True)
    assert lenient["code"] != "CHAIN_UNCHAINED_ROW"


def test_unencodable_value_fails_closed_never_skipped():
    fixture = _clean()
    rows = [dict(row) for row in fixture["rows"]]
    rows[1]["reason"] = "\ud800"  # a lone surrogate, as a file-level edit leaves

    result = verify_journal_chain(rows)

    assert result["ok"] is False
    assert result["code"] == "CHAIN_UNENCODABLE_ROW"
    assert result["event_id"] == rows[1]["event_id"]


# ── migration 22 -> 23 on a populated journal ──

def test_migration_backfills_a_populated_v22_journal():
    conn = _v22_db()
    for marker in ("FirstEvent", "SecondEvent", "ThirdEvent"):
        _raw_event(conn, marker)
    before_created_at = _created_at(conn)
    v22_columns = {row["name"] for row in conn.execute(
        "SELECT name FROM pragma_table_info('events')")}
    assert "prev_hash" not in v22_columns  # v22 shape: no chain columns
    assert "chain_hash" not in v22_columns

    assert migrate_to_latest(conn, clock=CLOCK) == 23

    result = verify_journal(conn)
    assert result["code"] == "CHAIN_OK"
    assert result["findings"] == ()
    assert result["chain_version"] == CHAIN_VERSION
    assert _created_at(conn) == before_created_at  # byte-identical
    chain = _chain_of(conn)
    assert chain[0][0] == GENESIS
    assert all(prev is not None and digest is not None for prev, digest in chain)
    conn.close()


def test_migration_leaves_the_triggers_refusing():
    conn = _v22_db()
    _raw_event(conn)
    migrate_to_latest(conn, clock=CLOCK)

    _assert_refused(
        conn, "UPDATE events SET reason = 'forged' WHERE event_id = 1",
        UPDATE_TRIGGER_ERROR)
    _assert_refused(
        conn, "DELETE FROM events WHERE event_id = 1", DELETE_TRIGGER_ERROR)
    assert missing_append_only_triggers(conn) == ()
    conn.close()


def test_append_after_migration_chains_onto_the_backfilled_tip():
    conn = _v22_db()
    _raw_event(conn)
    migrate_to_latest(conn, clock=CLOCK)
    backfilled_tip = conn.execute(
        "SELECT chain_hash FROM events WHERE event_id = 1").fetchone()[0]

    conn.execute("BEGIN")
    _append_event_to_db(conn, CLOCK, "TaskStatusChanged")
    conn.execute("COMMIT")

    appended = conn.execute(
        "SELECT prev_hash FROM events WHERE event_id = 2").fetchone()[0]
    assert appended == backfilled_tip
    assert verify_journal(conn)["code"] == "CHAIN_OK"
    conn.close()


def test_append_after_a_null_chained_row_uses_the_last_chained_tip():
    conn = _v22_db()
    _raw_event(conn, "ChainedEvent")
    migrate_to_latest(conn, clock=CLOCK)
    chained_tip = conn.execute(
        "SELECT chain_hash FROM events WHERE event_id = 1").fetchone()[0]
    _raw_event(conn, "RawHoleEvent")  # bypasses the writer: NULL chain

    conn.execute("BEGIN")
    _append_event_to_db(conn, CLOCK, "TaskStatusChanged")
    conn.execute("COMMIT")

    appended = conn.execute(
        "SELECT event_id, prev_hash FROM events WHERE event_id = 3").fetchone()
    assert appended["prev_hash"] == chained_tip  # never chains onto NULL
    assert verify_journal(conn)["code"] == "CHAIN_UNCHAINED_ROW"
    assert verify_journal(conn)["event_id"] == 2  # the hole stays visible
    conn.close()


def test_migrate_22_to_23_twice_still_verifies():
    conn = _v22_db()
    _raw_event(conn)
    migrate_to_latest(conn, clock=CLOCK)
    first_tip = verify_journal(conn)["tip"]

    for _ in range(2):
        conn.execute("BEGIN")
        _migrate_22_to_23(conn, CLOCK)
        conn.execute("COMMIT")

    result = verify_journal(conn)
    assert result["code"] == "CHAIN_OK"
    assert result["tip"] == first_tip
    assert get_schema_version(conn) == 23
    assert conn.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = 23"
    ).fetchone()[0] == 1
    conn.close()


def test_migrate_to_latest_no_args_behaviour_is_unchanged():
    conn = connect(":memory:")

    assert migrate_to_latest(conn) == SUPPORTED_VERSION == 23
    assert migrate_to_latest(conn) == 23  # idempotent re-run, no new row
    assert conn.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = 23"
    ).fetchone()[0] == 1
    conn.close()


# ── A6: the structural finding ──

def test_dropped_trigger_is_a_named_structural_finding():
    conn = connect(":memory:")
    migrate_to_latest(conn, clock=CLOCK)
    ProjectRepository(conn, clock=CLOCK).create("p1", "Alpha")

    conn.execute(f"DROP TRIGGER {UPDATE_TRIGGER}")

    assert missing_append_only_triggers(conn) == (UPDATE_TRIGGER,)
    result = verify_journal(conn)
    assert result["ok"] is False
    assert result["code"] == "CHAIN_TRIGGERS_MISSING"
    assert result["findings"] == (UPDATE_TRIGGER,)

    migrations._create_events_append_only_triggers(conn)
    restored = verify_journal(conn)
    assert restored["code"] == "CHAIN_OK"
    assert restored["findings"] == ()
    conn.close()


def test_missing_trigger_outranks_a_row_defect():
    """A7.3: the structural finding precedes the walk — with the refusal layer
    gone, the row-level finding is not the most important one."""
    conn = connect(":memory:")
    migrate_to_latest(conn, clock=CLOCK)
    ProjectRepository(conn, clock=CLOCK).create("p1", "Alpha")
    tamper_events(
        conn, "UPDATE events SET reason = ? WHERE event_id = ?",
        ("forged", 1))
    assert verify_journal(conn)["code"] == "CHAIN_HASH_MISMATCH"

    conn.execute(f"DROP TRIGGER {UPDATE_TRIGGER}")

    result = verify_journal(conn)
    assert result["code"] == "CHAIN_TRIGGERS_MISSING"
    assert result["findings"] == (UPDATE_TRIGGER,)
    conn.close()


# ── A7.4: the re-chain ──

def test_rechain_refuses_without_an_open_transaction():
    conn = connect(":memory:")
    migrate_to_latest(conn, clock=CLOCK)

    with pytest.raises(RuntimeError, match="open transaction"):
        rechain_journal(conn)
    conn.close()


def test_rechain_of_a_tampered_journal_blesses_the_current_bytes():
    conn = connect(":memory:")
    migrate_to_latest(conn, clock=CLOCK)
    ProjectRepository(conn, clock=CLOCK).create("p1", "Alpha")
    conn.execute("BEGIN")
    _append_event_to_db(conn, CLOCK, "TaskStatusChanged")
    conn.execute("COMMIT")
    old_tip = verify_journal(conn)["tip"]

    tamper_events(
        conn, "UPDATE events SET payload_json = ? WHERE event_id = ?",
        ('{"forged":true}', 1))

    assert verify_journal(conn)["code"] == "CHAIN_HASH_MISMATCH"

    conn.execute("BEGIN")
    summary = rechain_journal(conn)
    conn.execute("COMMIT")

    assert summary["rows"] == 2
    assert summary["changed"] > 0
    assert summary["old_tip"] == old_tip
    assert summary["new_tip"] != old_tip
    assert verify_journal(conn)["code"] == "CHAIN_OK"
    # the blessed journal no longer records that anything happened
    assert conn.execute(
        "SELECT payload_json FROM events WHERE event_id = 1").fetchone()[0] \
        == '{"forged":true}'
    conn.close()


def test_rechain_of_a_clean_journal_changes_nothing():
    conn = connect(":memory:")
    migrate_to_latest(conn, clock=CLOCK)
    ProjectRepository(conn, clock=CLOCK).create("p1", "Alpha")
    before = _chain_of(conn)

    conn.execute("BEGIN")
    summary = rechain_journal(conn)
    conn.execute("COMMIT")

    assert summary["changed"] == 0
    assert summary["old_tip"] == summary["new_tip"]
    assert _chain_of(conn) == before
    assert verify_journal(conn)["code"] == "CHAIN_OK"
    conn.close()


# ── the CLI ──

def test_cli_verify_exits_zero_only_on_a_clean_chain(tmp_path, capsys):
    path = _migrated_file(tmp_path)

    assert main(["journal", "verify", "--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert "CHAIN_OK" in out
    assert CHAIN_VERSION in out
    assert "only --anchor detects one" in out

    assert main(["journal", "verify", "--db", str(path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is True
    assert doc["code"] == "CHAIN_OK"
    assert doc["findings"] == []
    assert doc["chain_version"] == CHAIN_VERSION


def test_cli_verify_exits_one_on_a_defect(tmp_path, capsys):
    path = _migrated_file(tmp_path)
    conn = connect(str(path))
    tamper_events(
        conn, "UPDATE events SET reason = ? WHERE event_id = ?",
        ("forged", 1))
    conn.close()

    assert main(["journal", "verify", "--db", str(path)]) == 1
    out = capsys.readouterr()
    assert "CHAIN_HASH_MISMATCH" in out.out
    assert "does not verify" in out.err


def test_cli_verify_exits_one_on_a_structural_finding(tmp_path, capsys):
    path = _migrated_file(tmp_path)
    conn = connect(str(path))
    conn.execute(f"DROP TRIGGER {DELETE_TRIGGER}")
    conn.close()

    assert main(["journal", "verify", "--db", str(path)]) == 1
    assert "CHAIN_TRIGGERS_MISSING" in capsys.readouterr().out


def test_cli_verify_without_a_database_returns_one(tmp_path, capsys):
    assert main(["journal", "verify", "--db", str(tmp_path / "nope.db")]) == 1
    assert "No database" in capsys.readouterr().out


def test_cli_rechain_requires_confirmation(tmp_path, capsys):
    path = _migrated_file(tmp_path)
    before = path.read_bytes()

    assert main(["journal", "rechain", "--db", str(path)]) == 1
    assert "Refused" in capsys.readouterr().out
    assert path.read_bytes() == before


def test_cli_rechain_refuses_a_database_below_supported_version(
        tmp_path, capsys):
    path = tmp_path / "v22.db"
    conn = connect(str(path))
    _run_migrations(conn, 22)
    _raw_event(conn)
    conn.close()

    assert main([
        "journal", "rechain", "--db", str(path), "--confirm-rechain"]) == 1
    assert "run migrations first" in capsys.readouterr().out

    conn = connect(str(path))
    assert get_schema_version(conn) == 22
    columns = {row["name"] for row in conn.execute(
        "SELECT name FROM pragma_table_info('events')")}
    assert "prev_hash" not in columns and "chain_hash" not in columns
    conn.close()


def test_cli_verify_refuses_a_pre_chain_schema(tmp_path, capsys):
    path = tmp_path / "v22.db"
    conn = connect(str(path))
    _run_migrations(conn, 22)
    _raw_event(conn)
    conn.close()
    before = path.read_bytes()

    assert main(["journal", "verify", "--db", str(path)]) == 1
    out = capsys.readouterr().out
    assert "the journal has no chain to verify; run migrations first" in out
    assert path.read_bytes() == before

    conn = connect(str(path))
    assert get_schema_version(conn) == 22
    conn.close()


def test_cli_rechain_with_a_stale_anchor_refuses_and_leaves_the_file_alone(
        tmp_path, capsys):
    path = _migrated_file(tmp_path)
    conn = connect(str(path))
    tamper_events(
        conn, "UPDATE events SET reason = ? WHERE event_id = ?",
        ("forged", 1))
    tampered = verify_journal(conn)
    conn.close()
    before = path.read_bytes()

    assert main([
        "journal", "rechain", "--db", str(path),
        "--anchor", GENESIS, "--confirm-rechain"]) == 1
    assert "Refused" in capsys.readouterr().out
    assert path.read_bytes() == before

    conn = connect(str(path))
    after = verify_journal(conn)
    assert after["code"] == tampered["code"] == "CHAIN_HASH_MISMATCH"
    assert after["tip"] == tampered["tip"]
    conn.close()


def test_cli_rechain_runs_exactly_one_migration_body(
        tmp_path, monkeypatch, capsys):
    path = _migrated_file(tmp_path)
    calls: list[int] = []
    wrapped: list[Any] = []
    for index, fn in enumerate(migrations._MIGRATIONS):
        def counter(conn, clock, _index=index, _fn=fn):
            calls.append(_index)
            _fn(conn, clock)
        wrapped.append(counter)
    monkeypatch.setattr(migrations, "_MIGRATIONS", wrapped)

    assert main([
        "journal", "rechain", "--db", str(path), "--confirm-rechain"]) == 0
    out = capsys.readouterr().out
    assert calls == [22]
    assert "Old tip:" in out and "New tip:" in out
    assert "blessed" in out


# ── A3: verification is explicit only ──

def test_no_production_read_path_verifies_the_chain():
    src = Path(__file__).resolve().parents[1] / "src" / "hermes"
    allowed = {"persistence/journal_chain.py", "cli.py"}
    offenders = sorted(
        str(path.relative_to(src)).replace("\\", "/")
        for path in src.rglob("*.py")
        if "verify_journal" in path.read_text(encoding="utf-8")
        and str(path.relative_to(src)).replace("\\", "/") not in allowed
    )

    assert offenders == []


# ── the tamper helper still proves both halves ──

def test_tamper_helper_still_refuses_then_forces_and_leaves_a_chain_defect():
    conn = connect(":memory:")
    migrate_to_latest(conn, clock=CLOCK)
    ProjectRepository(conn, clock=CLOCK).create("p1", "Alpha")

    tamper_events(
        conn, "UPDATE events SET reason = ? WHERE event_id = ?",
        ("forged", 1))

    assert conn.execute(
        "SELECT reason FROM events WHERE event_id = 1").fetchone()[0] \
        == "forged"
    assert verify_journal(conn)["code"] == "CHAIN_HASH_MISMATCH"
    assert missing_append_only_triggers(conn) == ()  # triggers restored
    conn.close()
