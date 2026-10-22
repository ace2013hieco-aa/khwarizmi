"""P3-3 pins — the scheduler lease generation survives release.

Pre-fix the Controller released by DELETing the scheduler_lock row, so the
next acquisition INSERTed a fresh row at generation 0. A token captured
before the release could then validate against the new holder at the same
generation (the ADV-02 fence was bypassed by the reset). The fix marks the
row released in place and the next acquisition increments the generation.
"""
from __future__ import annotations

import pytest

from hermes.core import frozen_clock
from hermes.persistence.database import RELEASED_LOCK_OWNER, connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.research.controller import Controller, LockLostError

CLOCK = "2026-01-01T00:00:00.000000+00:00"
STALE = "2025-01-01T00:00:00.000000+00:00"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    yield conn
    conn.close()


def _controller(db, owner):
    return Controller(db, project_id="p1", owner=owner,
                      clock=frozen_clock(CLOCK), lease_seconds=60)


def _row(db):
    return db.execute(
        "SELECT owner, locked_at, generation FROM scheduler_lock WHERE id = 0"
    ).fetchone()


def test_release_keeps_row_and_next_acquire_bumps_generation(db):
    a = _controller(db, "controller-A")
    assert a._acquire_lock() is True
    assert _row(db)["generation"] == 0

    a._release_lock()
    released = _row(db)
    assert released is not None
    assert released["owner"] == RELEASED_LOCK_OWNER
    assert released["generation"] == 0

    assert a._acquire_lock() is True
    reused = _row(db)
    assert reused["owner"] == "controller-A"
    assert reused["generation"] == 1
    a._release_lock()


def test_released_row_reclaim_bumps_and_fences_the_old_holder(db):
    a = _controller(db, "controller-A")
    assert a._acquire_lock() is True
    a._release_lock()
    with pytest.raises(LockLostError):
        a._assert_lock_valid()

    b = _controller(db, "controller-B")
    assert b._acquire_lock() is True
    assert _row(db)["generation"] == 1
    with pytest.raises(LockLostError):
        a._assert_lock_valid()
    b._release_lock()

    c = _controller(db, "controller-C")
    assert c._acquire_lock() is True
    assert _row(db)["generation"] == 2
    c._release_lock()


def test_stale_reclaim_continues_from_the_stored_generation(db):
    db.execute(
        "INSERT INTO scheduler_lock (id, owner, locked_at, generation) "
        "VALUES (0, 'crashed-controller', ?, 5)", (STALE,))
    a = _controller(db, "controller-A")
    assert a._acquire_lock() is True
    assert _row(db)["generation"] == 6
    a._release_lock()
