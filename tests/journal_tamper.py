"""The one tamper-simulation helper (IDR TAMPER-EVIDENT-JOURNAL §5).

After the append-only triggers land, the suite's deliberate tamper
simulations (corrupt a payload, punch a journal hole, rewrite a reason)
raise at the SQL layer before reaching the consumer under test. This helper
keeps every simulation honest: it FIRST asserts the shipped trigger refuses
the mutation with its named error, then drops both triggers, performs the
mutation, and re-creates them from the exact DDL captured in
``sqlite_master`` — so each adapted site proves both the refusal and the
consumer's fail-closed behavior, and the discipline survives the mutation.

TAMPER-2: a forced mutation now also invalidates the per-event chain. The
row's stored ``chain_hash`` no longer matches its own bytes, so an explicit
``hermes journal verify`` (or ``verify_journal``) reports
``CHAIN_HASH_MISMATCH`` from that row onward. That is correct and expected —
the chain is the second detection layer, not a third refusal layer. It
changes no test here because **no production read path verifies the chain**
(verification is explicit only, IDR addendum A3), so a tampered fixture keeps
exercising exactly the consumer behavior it was written for.

Not a test module (name does not match ``test_*.py``).
"""
from __future__ import annotations

import sqlite3
from typing import Sequence

import pytest

from tests.tamper_evident_reference import (
    DELETE_TRIGGER_ERROR,
    UPDATE_TRIGGER_ERROR,
)

TRIGGER_NAMES = (
    "trg_events_append_only_delete",
    "trg_events_append_only_update",
)


def tamper_events(
    conn: sqlite3.Connection,
    sql: str,
    params: Sequence[object] = (),
) -> None:
    """Apply one deliberate journal mutation, refusing-then-forcing it.

    ``sql`` is the UPDATE/DELETE the simulation needs. The helper asserts it
    is refused (``sqlite3.IntegrityError``, named error) while the shipped
    triggers are in place, then drops both triggers, applies the mutation,
    and restores the triggers from their captured DDL.
    """
    head = sql.lstrip().split(maxsplit=1)[0].upper()
    expected = UPDATE_TRIGGER_ERROR if head == "UPDATE" else DELETE_TRIGGER_ERROR
    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        conn.execute(sql, params)
    assert expected in str(excinfo.value)

    saved = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' "
        "AND name IN (?, ?) ORDER BY name",
        TRIGGER_NAMES,
    ).fetchall()
    assert [row[0] for row in saved] == list(TRIGGER_NAMES)
    for name, _ in saved:
        conn.execute(f"DROP TRIGGER {name}")
    try:
        conn.execute(sql, params)
    finally:
        for _, ddl in saved:
            conn.execute(ddl)
