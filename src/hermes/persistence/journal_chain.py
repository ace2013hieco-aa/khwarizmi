"""Per-event hash chain over the append-only journal (TAMPER-2).

Implements ``docs/idr/TAMPER-EVIDENT-JOURNAL.md`` §1.2-§1.5 and the TAMPER-2
addendum (A1, A6, A7.3, A7.4). The chain is a **derived view** of the
journal: a green verify is a mechanically true statement about the bytes in
one file, never authority, scientific validity, reproducibility, or
authorship.

What the chain does not catch, by design (§1.6 / A6):

- **tail truncation** — a shorter self-consistent chain verifies; only an
  out-of-band ``anchor`` detects it;
- **a full re-chain** — an actor with DDL rights can recompute every row and
  produce a valid chain; only an ``anchor`` detects it;
- **``created_at`` rewrite** — excluded from the preimage (§1.1);
- **a wholesale DB-file swap** — a self-consistent replacement verifies; only
  ``anchor`` detects it. This design ships no sidecar anchor file, no
  signature, no MAC and no key material (an anchor store is P2-4).

The sharpest edge in this module: **a re-chain blesses the current bytes.**
After tampering, ``rechain_journal`` produces a journal that verifies and no
longer records that anything happened. It is a deliberate act for a known-good
journal (a rebuild, an import, an encoding migration), never a repair, and
never a response to a red verify.

One canonicalizer authority: ``canonical_json`` / ``sha256_hex`` come from
``hermes.research.programs`` — there is no local copy (the same argument as
ADV-05 for ``KNOWN_EVENT_TYPES``).
"""
from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Mapping

from hermes.research.programs import canonical_json, sha256_hex

# ── §1.2 / A1: chain version and genesis ──

CHAIN_VERSION = "hermes.journal.chain.v1"
GENESIS = sha256_hex(f"{CHAIN_VERSION}/genesis")

# ── §1.3: the 11 hashed columns of 14 ──
#
# Order is documentary only (``canonical_json`` sorts keys). ``created_at`` is
# deliberately absent (G1 identity/provenance split), as are the two chain
# columns themselves.
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

# ── §2.1: the refusal layer the structural check looks for ──

UPDATE_TRIGGER = "trg_events_append_only_update"
DELETE_TRIGGER = "trg_events_append_only_delete"
APPEND_ONLY_TRIGGERS: tuple[str, ...] = (UPDATE_TRIGGER, DELETE_TRIGGER)

# ── §1.5 / A7.3: the closed defect-code set ──

CHAIN_OK = "CHAIN_OK"
CHAIN_EVENT_ID_OUT_OF_ORDER = "CHAIN_EVENT_ID_OUT_OF_ORDER"
CHAIN_UNCHAINED_ROW = "CHAIN_UNCHAINED_ROW"
CHAIN_PREV_MISMATCH = "CHAIN_PREV_MISMATCH"
CHAIN_HASH_MISMATCH = "CHAIN_HASH_MISMATCH"
CHAIN_UNENCODABLE_ROW = "CHAIN_UNENCODABLE_ROW"
CHAIN_TIP_MISMATCH = "CHAIN_TIP_MISMATCH"
CHAIN_TRIGGERS_MISSING = "CHAIN_TRIGGERS_MISSING"

CHAIN_CODES: frozenset[str] = frozenset({
    CHAIN_OK,
    CHAIN_EVENT_ID_OUT_OF_ORDER,
    CHAIN_UNCHAINED_ROW,
    CHAIN_PREV_MISMATCH,
    CHAIN_HASH_MISMATCH,
    CHAIN_UNENCODABLE_ROW,
    CHAIN_TIP_MISMATCH,
    CHAIN_TRIGGERS_MISSING,
})

#: The columns every read of a journal row selects (never ``SELECT *``: the
#: two chain columns are appended after ``created_at``, so a positional copy
#: would silently mis-assign — §3.1 rule 3).
ROW_COLUMNS: tuple[str, ...] = (*CHAINED_FIELDS, "prev_hash", "chain_hash")


# ── §1.4: the recurrence ──


def _values(row: Mapping[str, Any] | sqlite3.Row) -> Mapping[str, Any]:
    """One journal row as a mapping (``sqlite3.Row`` is not a ``Mapping``)."""
    if isinstance(row, sqlite3.Row):
        return dict(row)  # Row iterates its VALUES; dict() uses the keys
    return row


def chain_row(prev_hash: str, row: Mapping[str, Any] | sqlite3.Row) -> str:
    """``h(n) = H(h(n-1) || "\\n" || canonical(11 stored fields))`` (§1.4).

    The 11 values are taken **verbatim as stored** (``NULL`` -> JSON
    ``null``), never parsed and re-serialized: hashing the stored bytes is
    what makes a reformatted-but-semantically-equal payload a defect rather
    than a silent pass. Raises ``UnicodeEncodeError`` for a value that cannot
    be UTF-8 encoded; callers fail closed on it (``CHAIN_UNENCODABLE_ROW``),
    they never skip the row.
    """
    values = _values(row)
    body = canonical_json({field: values.get(field) for field in CHAINED_FIELDS})
    return sha256_hex(f"{prev_hash}\n{body}")


# ── §1.5 / A7.3: verification ──


def _verdict(
    code: str,
    event_id: int | None = None,
    *,
    expected: str | None = None,
    actual: str | None = None,
    tip: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": code == CHAIN_OK,
        "code": code,
        "event_id": event_id,
        "expected": expected,
        "actual": actual,
        "genesis": GENESIS,
        "tip": tip,
    }


def verify_journal_chain(
    rows: Iterable[Mapping[str, Any] | sqlite3.Row],
    *,
    anchor: str | None = None,
    allow_unchained: bool = False,
) -> dict[str, Any]:
    """Walk the rows in ``event_id`` order; return the FIRST defect (§1.5).

    ``rows`` is an iterable of mappings or ``sqlite3.Row``. ``anchor`` is the
    optional out-of-band tip digest that closes the tail-truncation and
    file-swap gaps; ``allow_unchained`` accepts ``NULL`` chain columns and
    keeps the running digest (used only by diagnostics — the CLI verifier is
    strict).
    """
    running = GENESIS
    previous_id: int | None = None

    for row in rows:
        values = _values(row)
        event_id = values.get("event_id")
        if (previous_id is not None and isinstance(event_id, int)
                and event_id <= previous_id):
            return _verdict(CHAIN_EVENT_ID_OUT_OF_ORDER, event_id)
        if isinstance(event_id, int):
            previous_id = event_id

        stored_prev = values.get("prev_hash")
        stored_hash = values.get("chain_hash")
        if stored_prev is None or stored_hash is None:
            if allow_unchained:
                continue
            return _verdict(CHAIN_UNCHAINED_ROW, event_id)

        if str(stored_prev).lower() != running:
            return _verdict(
                CHAIN_PREV_MISMATCH, event_id,
                expected=running, actual=str(stored_prev),
            )

        try:
            computed = chain_row(running, values)
        except UnicodeEncodeError:
            return _verdict(CHAIN_UNENCODABLE_ROW, event_id)

        if str(stored_hash).lower() != computed:
            return _verdict(
                CHAIN_HASH_MISMATCH, event_id,
                expected=computed, actual=str(stored_hash),
            )
        running = computed

    if anchor is not None and running != anchor:
        return _verdict(CHAIN_TIP_MISMATCH, expected=running, actual=anchor)
    return _verdict(CHAIN_OK, tip=running)


# ── A6 / A7.3: the structural check ──


def missing_append_only_triggers(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Names of the §2.1 triggers absent from ``sqlite_master`` (empty = all).

    ``DROP TRIGGER`` changes no row byte, so no chain walk can see it; this is
    the only honest detector of the refusal layer's absence. It detects
    **absence** only: a trigger dropped, used and recreated identically is
    indistinguishable from one that was never dropped.
    """
    present = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' "
            "AND name IN (?, ?)",
            APPEND_ONLY_TRIGGERS,
        )
    }
    return tuple(name for name in APPEND_ONLY_TRIGGERS if name not in present)


def verify_journal(
    conn: sqlite3.Connection,
    *,
    anchor: str | None = None,
) -> dict[str, Any]:
    """DB-facing verifier: structural check first, then the row walk (A7.3).

    ``CHAIN_TRIGGERS_MISSING`` outranks any row defect — with the refusal
    layer gone, the row-level finding is not the most important one. ``ok`` is
    true only for ``CHAIN_OK`` with an empty ``findings`` tuple.
    """
    findings = missing_append_only_triggers(conn)
    if findings:
        verdict = _verdict(CHAIN_TRIGGERS_MISSING)
        verdict["findings"] = findings
        verdict["chain_version"] = CHAIN_VERSION
        return verdict

    rows = conn.execute(
        f"SELECT {', '.join(ROW_COLUMNS)} FROM events ORDER BY event_id"
    ).fetchall()
    verdict = verify_journal_chain(rows, anchor=anchor)
    verdict["findings"] = ()
    verdict["chain_version"] = CHAIN_VERSION
    return verdict


# ── A7.2 / A7.4: the tip and the re-chain ──


def _stored_tip(conn: sqlite3.Connection) -> str | None:
    """The stored tip, or ``None`` when no row carries a chain hash."""
    row = conn.execute(
        "SELECT chain_hash FROM events WHERE chain_hash IS NOT NULL "
        "ORDER BY event_id DESC LIMIT 1"
    ).fetchone()
    return None if row is None else row[0]


def journal_tip(conn: sqlite3.Connection) -> str:
    """The append tip (A7.2): the highest ``event_id`` with a chain hash.

    ``GENESIS`` when no row carries one. Never "the last row": raw
    ``INSERT INTO events`` sites bypass the writer and leave ``chain_hash``
    NULL, and chaining onto NULL would make every later append unverifiable.
    """
    return _stored_tip(conn) or GENESIS


def rechain_journal(conn: sqlite3.Connection) -> dict[str, Any]:
    """Recompute every row's chain pair in ``event_id`` order from ``GENESIS``.

    **A re-chain blesses the current bytes.** It produces a journal that
    verifies and no longer records that anything happened; it is a deliberate
    act for a known-good journal, never a repair and never a response to a red
    verify.

    Issues **no transaction-control statement of its own**: it asserts that
    the caller holds an open transaction and refuses otherwise. The owner is
    the migration runner (``migrate_to_latest(conn, start_version=22)``), so
    a failure anywhere rolls back to the previous chain *and* both triggers.
    Returns ``{rows, old_tip, new_tip, changed}``; ``old_tip`` is ``None``
    when no row was chained before.
    """
    if not conn.in_transaction:
        raise RuntimeError(
            "rechain_journal requires an open transaction — the caller owns "
            "it (migrate_to_latest); this function never opens its own"
        )

    # Lazy import: ``migrations`` imports this module at module level (the
    # 22 -> 23 body and the writer's tip helper), so a module-level import
    # here would be circular. The DDL authority stays in ``migrations``.
    from hermes.persistence.migrations import _EVENTS_APPEND_ONLY_TRIGGER_DDL

    old_tip = _stored_tip(conn)

    conn.execute(f"DROP TRIGGER IF EXISTS {UPDATE_TRIGGER}")
    conn.execute(f"DROP TRIGGER IF EXISTS {DELETE_TRIGGER}")

    running = GENESIS
    rows = 0
    changed = 0
    reader = conn.cursor()
    writer = conn.cursor()
    try:
        reader.execute(
            f"SELECT {', '.join(ROW_COLUMNS)} FROM events ORDER BY event_id"
        )
        for row in reader:
            values = _values(row)
            new_hash = chain_row(running, values)
            if (values.get("prev_hash") != running
                    or values.get("chain_hash") != new_hash):
                changed += 1
            writer.execute(
                "UPDATE events SET prev_hash = ?, chain_hash = ? "
                "WHERE event_id = ?",
                (running, new_hash, values.get("event_id")),
            )
            running = new_hash
            rows += 1
    finally:
        reader.close()
        writer.close()

    for statement in _EVENTS_APPEND_ONLY_TRIGGER_DDL:
        conn.execute(statement)

    return {
        "rows": rows,
        "old_tip": old_tip,
        "new_tip": running,
        "changed": changed,
    }
