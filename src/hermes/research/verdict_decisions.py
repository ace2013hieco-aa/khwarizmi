"""Shared HumanDecision idempotent-append step (S-2 internal seam).

The four V-a verdict surfaces (classification, contradiction
resolution, source-retraction decision, curation decision) record
their ratified operator verdict with a byte-identical
check-then-append sequence. This helper owns that sequence and
nothing else: no transaction (runs inside the caller's lease
bracket), no lease, no fence, no authority check, no gateway call,
no identity derivation (correlation strings are caller-built).

INTERNAL implementation location — not a supported public surface
(no ``__all__``; behavior pinned by
``tests/test_s2_human_decision_append.py`` through the verdict
surfaces).
"""
from __future__ import annotations

from typing import Any

from hermes.persistence.repositories import _append_event_to_db


def record_human_decision_once(
    *,
    conn: Any,
    clock: Any,
    project_id: str,
    correlation_id: str,
    caused_by: str,
    reason: str,
    payload: dict,
) -> bool:
    """Append one ``HumanDecisionReceived`` journal row unless the
    correlation already exists (idempotent per command hash — a
    replay never double-records). Returns True when recorded now,
    False when already present. Callers proceed unconditionally
    either way (gateway admission decides duplicates); a journal
    failure propagates to the caller unchanged."""
    existing = conn.execute(
        "SELECT 1 FROM events WHERE project_id = ? "
        "AND event_type = 'HumanDecisionReceived' "
        "AND correlation_id = ? LIMIT 1",
        (project_id, correlation_id)).fetchone()
    if existing is None:
        _append_event_to_db(
            conn, clock, "HumanDecisionReceived",
            project_id=project_id,
            correlation_id=correlation_id,
            caused_by=caused_by,
            reason=reason,
            payload=payload)
        return True
    return False
