"""Fixture proof for ``docs/idr/TAMPER-EVIDENT-JOURNAL.md`` (DESIGN-TAMPER-EVIDENT).

Prover artifact only. The reference implementation lives in
``tests/tamper_evident_reference.py``; this module pins it against the frozen
fixtures under ``tests/fixtures/tamper_evident/``. No ``src/`` behavior
changes, and no migration, column, or trigger is added to the schema.

If the field list, the canonicalization, or the genesis rule changes, these
tests fail — that is their purpose (design record §6).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

import pytest

from tests.tamper_evident_reference import (
    CHAIN_VERSION,
    CHAINED_FIELDS,
    DELETE_TRIGGER_ERROR,
    GENESIS,
    UPDATE_TRIGGER_ERROR,
    build_trigger_db,
    chain_digests,
    verify_journal_chain,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tamper_evident"


# ── fixture loading ──

def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _clean() -> dict[str, Any]:
    return _load("journal_clean.json")


def _cases() -> list[dict[str, Any]]:
    return _load("tamper_cases.json")["cases"]


def _case(case_id: str) -> dict[str, Any]:
    return next(c for c in _cases() if c["id"] == case_id)


def _case_by(predicate: str, value: str) -> dict[str, Any]:
    return next(c for c in _cases() if c.get(predicate) == value)


def _apply_case(case: Mapping[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


# ── M1/M2: the frozen chain is reproduced, and verifies ──

def test_m1_reference_chain_reproduces_frozen_digests():
    fixture = _clean()
    rows = fixture["rows"]

    assert fixture["chain_version"] == CHAIN_VERSION
    assert fixture["genesis"] == GENESIS

    digests = chain_digests(rows)
    assert len(digests) == len(rows)

    previous = GENESIS
    for row, digest in zip(rows, digests, strict=True):
        assert row["prev_hash"] == previous
        assert row["chain_hash"] == digest
        previous = digest

    assert digests[-1] == fixture["tip"]


def test_m1b_independent_reimplementation_produces_the_same_digest():
    """A second construction path, straight from the design record's prose.

    Deliberately bypasses ``tamper_evident_reference`` *and*
    ``programs.canonical_json`` / ``sha256_hex``: the spec must be
    implementable by an external verifier holding only the document.
    """
    fixture = _clean()
    row = fixture["rows"][0]

    body = json.dumps(
        {field: row.get(field) for field in CHAINED_FIELDS},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    preimage = f"{fixture['genesis']}\n{body}".encode("utf-8")
    assert hashlib.sha256(preimage).hexdigest() == row["chain_hash"]


def test_m2_clean_journal_verifies_to_the_frozen_tip():
    fixture = _clean()
    result = verify_journal_chain(fixture["rows"], anchor=fixture["tip"])

    assert result["ok"] is True
    assert result["code"] == "CHAIN_OK"
    assert result["tip"] == fixture["tip"]
    assert result["genesis"] == GENESIS


# ── M3: every hashed field is covered ──

FIELD_CASES = [c for c in _cases() if c["op"] == "set" and c["field"] != "created_at"]


@pytest.mark.parametrize("case", FIELD_CASES, ids=[c["id"] for c in FIELD_CASES])
def test_m3_each_hashed_field_mutation_is_detected(case):
    fixture = _clean()
    rows = _apply_case(case, fixture["rows"])

    result = verify_journal_chain(rows)

    assert result["ok"] is False
    assert result["code"] == case["expect"]["code"]
    assert result["event_id"] == case["expect"]["event_id"]
    assert result["actual"] != result["expected"]


def test_m3_covers_all_eleven_hashed_fields():
    """The field-mutation matrix is exhaustive over CHAINED_FIELDS."""
    mutated = {c["field"] for c in FIELD_CASES}

    assert len(CHAINED_FIELDS) == 11
    assert mutated == set(CHAINED_FIELDS)
    assert "created_at" not in CHAINED_FIELDS


# ── M4: deletion of a middle row breaks the successor's link ──

def test_m4_middle_row_deletion_is_detected_at_successor():
    case = _case_by("op", "delete")
    fixture = _clean()
    rows = _apply_case(case, fixture["rows"])

    result = verify_journal_chain(rows)

    assert result["ok"] is False
    assert result["code"] == "CHAIN_PREV_MISMATCH"
    assert result["event_id"] == case["expect"]["event_id"]


# ── M5: created_at is provenance, not identity (G1 split) ──

def test_m5_created_at_rewrite_is_not_a_chain_defect():
    case = _case_by("field", "created_at")
    fixture = _clean()
    rows = _apply_case(case, fixture["rows"])
    index = case["row_index"]

    assert rows[index]["created_at"] != fixture["rows"][index]["created_at"]

    result = verify_journal_chain(rows, anchor=fixture["tip"])

    assert result["ok"] is True
    assert result["tip"] == fixture["tip"]


# ── M6: tail truncation needs the external anchor (§1.6) ──

def test_m6_tail_truncation_needs_the_anchor():
    case = _case_by("op", "truncate")
    fixture = _clean()
    rows = _apply_case(case, fixture["rows"])

    unanchored = verify_journal_chain(rows)
    assert unanchored["ok"] is True  # documented gap, not an oversight
    assert unanchored["tip"] != fixture["tip"]

    anchored = verify_journal_chain(rows, anchor=fixture["tip"])
    assert anchored["ok"] is False
    assert anchored["code"] == "CHAIN_TIP_MISMATCH"


# ── M7: an unchained row is reported, never silently accepted ──

def test_m7_unchained_row_fails_closed():
    case = _case_by("op", "clear_chain")
    fixture = _clean()
    rows = _apply_case(case, fixture["rows"])

    result = verify_journal_chain(rows)
    assert result["ok"] is False
    assert result["code"] == "CHAIN_UNCHAINED_ROW"
    assert result["event_id"] == case["expect"]["event_id"]

    lenient = verify_journal_chain(rows, allow_unchained=True)
    assert lenient["code"] != "CHAIN_UNCHAINED_ROW"


# ── M8: stored bytes are covered, not parsed semantics ──

def test_m8_payload_key_reordering_changes_the_digest():
    case = _case("reorder-payload-keys")
    fixture = _clean()
    rows = _apply_case(case, fixture["rows"])
    index = case["row_index"]

    before = fixture["rows"][index]["payload_json"]
    after = rows[index]["payload_json"]
    assert json.loads(before) == json.loads(after)  # same semantics...
    assert before != after                          # ...different bytes

    result = verify_journal_chain(rows)
    assert result["code"] == "CHAIN_HASH_MISMATCH"
    assert result["event_id"] == case["expect"]["event_id"]


# ── M9/M10: the trigger DDL, executed ──

@pytest.fixture()
def trigger_db():
    conn = build_trigger_db(_clean()["rows"])
    yield conn
    conn.close()


def test_m9_update_and_delete_raise_the_named_error(trigger_db):
    rows = _clean()["rows"]
    original_reason = rows[0]["reason"]

    with pytest.raises(sqlite3.IntegrityError) as update_exc:
        trigger_db.execute("UPDATE events SET reason = 'tampered' WHERE event_id = 1")
    assert UPDATE_TRIGGER_ERROR in str(update_exc.value)

    with pytest.raises(sqlite3.IntegrityError) as delete_exc:
        trigger_db.execute("DELETE FROM events WHERE event_id = 1")
    assert DELETE_TRIGGER_ERROR in str(delete_exc.value)

    # The aborted statements changed nothing.
    count = trigger_db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    reason = trigger_db.execute(
        "SELECT reason FROM events WHERE event_id = 1").fetchone()["reason"]
    assert count == len(rows)
    assert reason == original_reason


def test_m10_insert_still_succeeds_under_the_triggers(trigger_db):
    appended = dict(_clean()["rows"][0])
    appended["event_id"] = 4
    appended["prev_hash"] = None
    appended["chain_hash"] = None

    trigger_db.execute(
        """INSERT INTO events
           (event_id, event_type, project_id, correlation_id, artifact_ids_json,
            payload_json, created_at, prev_hash, chain_hash)
           VALUES (:event_id, :event_type, :project_id, :correlation_id,
                   :artifact_ids_json, :payload_json, :created_at,
                   :prev_hash, :chain_hash)""",
        appended,
    )
    trigger_db.commit()

    count = trigger_db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count == 4


# ── M11: the §3.1 rebuild rule is deterministic ──

def test_m11_rebuild_rechains_to_the_same_tip():
    base = _clean()
    rebuilt = _load("journal_rebuilt.json")

    # Same values, different JSON key order: canonicalization is key-order
    # invariant, so a rebuild re-chains to the same digests.
    base_keys = [list(row) for row in base["rows"]]
    rebuilt_keys = [list(row) for row in rebuilt["rows"]]
    assert rebuilt_keys != base_keys
    assert [sorted(k) for k in rebuilt_keys] == [sorted(k) for k in base_keys]

    result = verify_journal_chain(rebuilt["rows"], anchor=base["tip"])

    assert result["ok"] is True
    assert result["tip"] == base["tip"] == rebuilt["tip"]


def test_m11_positional_select_star_misassignment_is_detectable():
    """The §3.1 rule 3 hazard: a column-order mistake in a rebuild."""
    case = _case_by("op", "swap")
    fixture = _clean()
    rows = _apply_case(case, fixture["rows"])

    result = verify_journal_chain(rows)

    assert result["ok"] is False
    assert result["code"] == "CHAIN_HASH_MISMATCH"
    assert result["event_id"] == case["expect"]["event_id"]
