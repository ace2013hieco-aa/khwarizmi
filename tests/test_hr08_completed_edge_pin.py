"""Pin: REPORTING is the only state with an edge into COMPLETED (GAP-1 D10-A).

Structural pin for the HR-08 completion choke point
(``ProjectRepository.transition_lifecycle`` -> ``can_complete_research``;
``src/hermes/persistence/repositories.py:206``/``:241``). The set of states
with an outgoing edge into ``LifecycleState.COMPLETED`` is DERIVED at runtime
from the live v4 §6.1 transition table ``_TRANSITIONS``
(``src/hermes/core/lifecycle.py:83``; the sole COMPLETED edge is the REPORTING
row at ``:114``) -- never hand-copied here -- so any future edge into COMPLETED
(an existing state's row or a new key) changes the derived set and fails this
pin.

D10 interlock (TAMPER-1 / GAP-1 P1-1, ruling D1-A; recorded per D10-A): the
"SQL-bypass coverage" claim for the completion choke point is VOID unless the
append-only journal triggers are in place -- with a mutable journal, a raw-SQL
writer could rewrite the event history the choke point's audit rests on. The
triggers ARE in place on this tree (verified live 2026-10-20 against a fresh
``migrate_to_latest`` database: in-DB UPDATE / DELETE abort with
``HERMES_JOURNAL_IMMUTABLE_UPDATE`` / ``HERMES_JOURNAL_IMMUTABLE_DELETE``):
``_EVENTS_APPEND_ONLY_TRIGGER_DDL`` (``src/hermes/persistence/migrations.py:31``)
creates ``trg_events_append_only_update`` / ``trg_events_append_only_delete``;
migration 20 -> 21 applies them (``_migrate_20_to_21``, ``migrations.py:1256``;
registry ``migrations.py:1326``), and every ``events`` rebuild re-creates them
last (``migrations.py:364``). The shipped behavior is pinned by
``tests/test_journal_append_only_triggers.py``. Out-of-DB journal substitution
(DB-file swap, ``DROP TRIGGER``) remains TAMPER-2, chartered-deferred -- NOT
covered by either the triggers or this pin.
"""
from __future__ import annotations

from hermes.core import lifecycle
from hermes.core.lifecycle import LifecycleState


def _incoming_sources(target: LifecycleState) -> set[str]:
    """Return the source states with an edge into ``target``, from the live table.

    Keys are normally ``LifecycleState`` members; a raw non-enum key (the
    scratch-mutation shape) is surfaced by its string form, so the pin still
    fails with the offending source rather than raising.
    """
    return {
        source.value if isinstance(source, LifecycleState) else str(source)
        for source, targets in lifecycle._TRANSITIONS.items()
        if target in targets
    }


def test_reporting_is_the_only_incoming_edge_into_completed():
    assert _incoming_sources(LifecycleState.COMPLETED) == {"REPORTING"}
