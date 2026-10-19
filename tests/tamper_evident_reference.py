"""Reference implementation of ``docs/idr/TAMPER-EVIDENT-JOURNAL.md`` §1.4/§1.5/§2.1.

Prover artifact, **not** production code. This module exists so the design
record's chain recurrence, verifier defect table, and append-only trigger
DDL are executable and falsifiable before any column, trigger, or migration
lands. `src/` is untouched by DESIGN-TAMPER-EVIDENT.

Not a test module (name does not match ``test_*.py``), so it is not
collected by pytest — same status as ``tests/texp_p3_*.py``. Its consumers
are ``tests/test_tamper_evident_journal.py`` and the fixture generator.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Sequence

from hermes.research.programs import canonical_json, sha256_hex

# ── §1.2 genesis ──

CHAIN_VERSION = "hermes.journal.chain.v1"
GENESIS = sha256_hex(f"{CHAIN_VERSION}/genesis")

# ── §1.3 field list — 11 hashed columns of 14 ──
#
# Order is documentary only: ``canonical_json`` sorts keys. ``created_at``
# is deliberately absent (G1 identity/provenance split, design record §1.1),
# as are the two chain columns themselves.
CHAINED_FIELDS: tuple[str, ...] = (
    "event_id",
    "event_type",
    "project_id",
    "task_id",
    "from_state",
    "to_state",
    "correlation_id",
    "caused_by",
    "reason",
    "artifact_ids_json",
    "payload_json",
)

# ── §1.4 the chain ──

#: Defect codes (design record §1.5).
DEFECT_CODES = (
    "CHAIN_EVENT_ID_OUT_OF_ORDER",
    "CHAIN_UNCHAINED_ROW",
    "CHAIN_PREV_MISMATCH",
    "CHAIN_HASH_MISMATCH",
    "CHAIN_UNENCODABLE_ROW",
    "CHAIN_TIP_MISMATCH",
    "CHAIN_OK",
)


def chain_body(row: Mapping[str, Any]) -> str:
    """The canonical body of one event: the hashed fields, verbatim as stored.

    ``canonical_json`` is invoked on a flat mapping of *scalars*, so
    ``_canonicalize``'s list-sorting branch (``programs.py``) is never
    reached and intra-payload byte order is preserved rather than erased.
    """
    return canonical_json({field: row.get(field) for field in CHAINED_FIELDS})


def chain_digest(previous: str, row: Mapping[str, Any]) -> str:
    """``h(n) = H(h(n-1) || "\\n" || canonical(row))`` (design record §1.4)."""
    return sha256_hex(f"{previous}\n{chain_body(row)}")


def chain_digests(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Digest every row from ``GENESIS``, in the given (``event_id``) order."""
    digests: list[str] = []
    running = GENESIS
    for row in rows:
        running = chain_digest(running, row)
        digests.append(running)
    return digests


# ── §1.5 verification ──

def _verdict(
    code: str,
    event_id: int | None = None,
    *,
    expected: str | None = None,
    actual: str | None = None,
    tip: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": code == "CHAIN_OK",
        "code": code,
        "event_id": event_id,
        "expected": expected,
        "actual": actual,
        "tip": tip,
        "genesis": GENESIS,
    }


def verify_journal_chain(
    rows: Sequence[Mapping[str, Any]],
    *,
    anchor: str | None = None,
    allow_unchained: bool = False,
) -> dict[str, Any]:
    """Walk the journal in ``event_id`` order; return the FIRST defect.

    ``anchor`` is the optional out-of-band tip digest that closes the
    tail-truncation gap (design record §1.6).
    """
    running = GENESIS
    previous_id: int | None = None

    for row in rows:
        event_id = row.get("event_id")
        if (previous_id is not None and isinstance(event_id, int)
                and event_id <= previous_id):
            return _verdict("CHAIN_EVENT_ID_OUT_OF_ORDER", event_id)
        if isinstance(event_id, int):
            previous_id = event_id

        stored_prev = row.get("prev_hash")
        stored_hash = row.get("chain_hash")
        if stored_prev is None or stored_hash is None:
            if allow_unchained:
                continue
            return _verdict("CHAIN_UNCHAINED_ROW", event_id)

        if str(stored_prev).lower() != running:
            return _verdict(
                "CHAIN_PREV_MISMATCH", event_id,
                expected=running, actual=str(stored_prev),
            )

        try:
            computed = chain_digest(running, row)
        except UnicodeEncodeError:
            return _verdict("CHAIN_UNENCODABLE_ROW", event_id)

        if str(stored_hash).lower() != computed:
            return _verdict(
                "CHAIN_HASH_MISMATCH", event_id,
                expected=computed, actual=str(stored_hash),
            )
        running = computed

    if anchor is not None and running != anchor:
        return _verdict("CHAIN_TIP_MISMATCH", expected=running, actual=anchor)
    return _verdict("CHAIN_OK", tip=running)


# ── §2.1 append-only triggers + §1.4 column shape ──

UPDATE_TRIGGER_ERROR = "HERMES_JOURNAL_IMMUTABLE_UPDATE"
DELETE_TRIGGER_ERROR = "HERMES_JOURNAL_IMMUTABLE_DELETE"

TRIGGER_DDL: tuple[str, ...] = (
    f"""
    CREATE TRIGGER IF NOT EXISTS trg_events_append_only_update
    BEFORE UPDATE ON events
    BEGIN
        SELECT RAISE(ABORT, '{UPDATE_TRIGGER_ERROR}');
    END
    """,
    f"""
    CREATE TRIGGER IF NOT EXISTS trg_events_append_only_delete
    BEFORE DELETE ON events
    BEGIN
        SELECT RAISE(ABORT, '{DELETE_TRIGGER_ERROR}');
    END
    """,
)

#: Column shape mirrors ``migrations.py`` (the ``events`` DDL up to v20) plus
#: the two nullable chain columns appended by the future chain migration.
EVENTS_DDL = """
CREATE TABLE events (
    event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type          TEXT NOT NULL,
    project_id          TEXT REFERENCES projects(project_id),
    task_id             TEXT REFERENCES tasks(task_id),
    from_state          TEXT,
    to_state            TEXT,
    correlation_id      TEXT NOT NULL DEFAULT '',
    caused_by           TEXT,
    reason              TEXT,
    artifact_ids_json   TEXT,
    payload_json        TEXT,
    created_at          TEXT NOT NULL,
    prev_hash           TEXT,
    chain_hash          TEXT,
    CHECK (length(CAST(payload_json AS BLOB)) <= 4096)
)
"""


def build_trigger_db(rows: Sequence[Mapping[str, Any]]) -> sqlite3.Connection:
    """An in-memory ``events`` table carrying both triggers, seeded with rows."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE projects (project_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY)")
    conn.execute(EVENTS_DDL)
    for statement in TRIGGER_DDL:
        conn.execute(statement)
    for row in rows:
        conn.execute(
            """INSERT INTO events
               (event_id, event_type, project_id, task_id, from_state, to_state,
                correlation_id, caused_by, reason, artifact_ids_json,
                payload_json, created_at, prev_hash, chain_hash)
               VALUES (:event_id, :event_type, :project_id, :task_id,
                       :from_state, :to_state, :correlation_id, :caused_by,
                       :reason, :artifact_ids_json, :payload_json,
                       :created_at, :prev_hash, :chain_hash)""",
            dict(row),
        )
    conn.commit()
    return conn
