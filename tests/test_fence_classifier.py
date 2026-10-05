"""FIX-FENCE-CLASSIFIER — adversarial battery for the lease-fence classifier.

IMPROVE-B B-F-01 (CTE paren desync through string literals / comments) and
B-F-02 (DDL / PRAGMA writes never fenced) are pinned here, together with the
B-F-04 re-check of the legacy ``acquire_writer_lock`` durability.

C-FIX-2 adds two batteries to the same slice (owning gate DG-4 §14,
PROTECTED by DG-6 §3): C-F-03 pins the now fail-closed connection
DELEGATION surface (all 11 bypass-capable raw-connection methods refused
loudly; undeclared attributes raise instead of delegating; the declared
read surface stays free), and C-F-08 pins that ``release_writer_lock``
never COMMITs a foreign transaction — an open transaction is only
committed when the caller asserts the acquisition owner its lock row
carries.

The pre-fix classifier tokenised with a naive whitespace split, so a ``)``
inside a literal or comment desynced the CTE paren depth (the statement
keyword was skipped -> the write executed unfenced), and its verb list
covered DML only (DDL / PRAGMA / VACUUM / ATTACH executed unfenced). The
widened contract:

- literals (``'...'``, ``"..."``, backtick, ``[...]``), line comments and
  block comments are inert during the scan — parens inside them never count;
- fail closed by default: only the read allowlist (SELECT / VALUES / EXPLAIN,
  including ``WITH ... SELECT``) and the transaction-control carve-out
  (BEGIN / COMMIT / ROLLBACK / SAVEPOINT / RELEASE / END — the repositories'
  own rollback must always be able to discard an open transaction) pass
  unfenced; every other first keyword — DML, DDL, PRAGMA, ATTACH/DETACH,
  VACUUM, REINDEX, ANALYZE, and any unknown / unparseable statement — runs
  the lease-generation check before execution;
- the refusal surface (executescript / cursor / commit / rollback methods)
  is unchanged — never narrowed.

Owning gate: DG-4 §14 (lease / single writer — "fenced writes via
``Controller._FencedConnection``"), PROTECTED under DG-6 §3; the fence
slice re-run for this change is ``tests/test_controller.py`` (the ADV-02
F1–F3 and HD-01 pins) plus this battery.
"""
from __future__ import annotations

import pytest

from hermes.core import frozen_clock
from hermes.persistence.database import (
    DatabaseLockError,
    acquire_writer_lock,
    connect,
    release_writer_lock,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.research.controller import (
    Controller,
    LockLostError,
    _FencedConnection,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
STALE_CLOCK = "2026-01-01T00:02:00.000000+00:00"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    yield conn
    conn.close()


def _controller(db, owner: str, clock: str = CLOCK) -> Controller:
    return Controller(db, project_id="p1", owner=owner,
                      clock=frozen_clock(clock), lease_seconds=60)


def _stale_pair(db) -> tuple[Controller, Controller]:
    """A holds generation 0; B reclaims (generation 1) — A is now stale."""
    a = _controller(db, "controller-A")
    assert a._acquire_lock() is True
    b = _controller(db, "controller-B", STALE_CLOCK)
    assert b._acquire_lock() is True
    return a, b


# ── static classification battery ──
# Every non-read shape must run the generation check. The literal / comment
# rows are the B-F-01 probe shapes: pre-fix the `)` inside them desynced the
# paren depth and the statement keyword was skipped entirely.

FENCED_STATEMENTS = [
    # DML (the pre-existing verb list — unchanged)
    ("INSERT INTO t VALUES (1)", "dml-insert"),
    ("UPDATE t SET x = 1", "dml-update"),
    ("DELETE FROM t", "dml-delete"),
    ("REPLACE INTO t VALUES (1)", "dml-replace"),
    # B-F-01: literals / comments with parens inside a CTE preamble
    ("WITH t AS (SELECT ')') INSERT INTO t SELECT 1", "cte-paren-in-literal"),
    ("WITH t AS (SELECT '(') DELETE FROM t", "cte-open-paren-in-literal"),
    ("WITH t AS (SELECT 1) /* ) */ INSERT INTO t SELECT 1",
     "cte-paren-in-block-comment"),
    ("WITH t AS (SELECT 1) -- )\nUPDATE t SET x = 1",
     "cte-paren-in-line-comment"),
    ("WITH t AS (SELECT 'a''b)') CREATE TABLE t2 (x)",
     "cte-escaped-quote-literal"),
    ('WITH "t)" AS (SELECT 1) DROP TABLE t2',
     "cte-paren-in-quoted-identifier"),
    ("WITH [t)] AS (SELECT 1) DROP TABLE t2",
     "cte-paren-in-bracket-identifier"),
    ("WITH t AS (SELECT 1) PRAGMA user_version = 9",
     "cte-pragma-write"),
    # B-F-02: DDL / PRAGMA / ATTACH / VACUUM verdicts (all FENCED)
    ("CREATE TABLE t2 (x)", "ddl-create-table"),
    ("CREATE INDEX t2_i ON t (x)", "ddl-create-index"),
    ("DROP TABLE t2", "ddl-drop-table"),
    ("ALTER TABLE t ADD COLUMN y", "ddl-alter-table"),
    ("PRAGMA user_version = 9", "pragma-write"),
    ("ATTACH DATABASE ':memory:' AS other", "attach"),
    ("DETACH DATABASE other", "detach"),
    ("VACUUM", "vacuum"),
    ("REINDEX", "reindex"),
    ("ANALYZE", "analyze"),
    # comment-prefixed DDL (the leading-strip path)
    ("/* c */ CREATE TABLE t2 (x)", "comment-prefixed-ddl"),
    ("-- c\nDROP TABLE t2", "line-comment-prefixed-ddl"),
    # fail closed: an unknown first keyword is fenced, never passed
    ("FROBNICATE t", "unknown-verb-fails-closed"),
    # fail closed: a malformed (unterminated literal / block comment)
    # statement is fenced rather than passed as "unclassifiable"
    ("INSERT INTO t VALUES ('unterminated", "malformed-unterminated-literal"),
    ("/* never closed INSERT INTO t", "malformed-unterminated-comment"),
]

FREE_STATEMENTS = [
    ("SELECT 1", "select"),
    ("SELECT ')' AS x", "select-paren-literal"),
    ("VALUES (1)", "values"),
    ("EXPLAIN SELECT 1", "explain-select"),
    ("EXPLAIN QUERY PLAN SELECT * FROM t", "explain-query-plan"),
    ("WITH t AS (SELECT 1) SELECT * FROM t", "cte-select"),
    ("WITH t AS (SELECT ')') SELECT * FROM t", "cte-select-paren-literal"),
    ("/* ) */ SELECT 1", "comment-prefixed-select"),
    ("WITH t AS (SELECT 1) /* ) */ SELECT * FROM t",
     "cte-select-paren-comment"),
    (("WITH RECURSIVE t(n) AS (VALUES(1) UNION ALL SELECT n + 1 "
      "FROM t WHERE n < 5) SELECT n FROM t"), "recursive-cte-select"),
    # transaction control is a deliberate carve-out: the repositories' own
    # rollback must always be able to discard (HD-01 owns the method forms)
    ("BEGIN IMMEDIATE", "control-begin"),
    ("COMMIT", "control-commit"),
    ("ROLLBACK", "control-rollback"),
    ("SAVEPOINT s1", "control-savepoint"),
    ("RELEASE s1", "control-release"),
]


@pytest.mark.parametrize("sql", [s for s, _ in FENCED_STATEMENTS],
                         ids=[i for _, i in FENCED_STATEMENTS])
def test_classifier_fences_every_non_read_shape(sql):
    assert _FencedConnection._is_write(sql) is True


@pytest.mark.parametrize("sql", [s for s, _ in FREE_STATEMENTS],
                         ids=[i for _, i in FREE_STATEMENTS])
def test_classifier_lets_read_shapes_pass(sql):
    assert _FencedConnection._is_write(sql) is False


# ── DB-level: a stale generation must be refused and nothing may land ──

@pytest.mark.parametrize("sql", [
    ("WITH t AS (SELECT ')') INSERT INTO schema_version "
     "(version, applied_at) SELECT 99, 'probe'"),
    ("WITH t AS (SELECT 1) /* ) */ INSERT INTO schema_version "
     "(version, applied_at) SELECT 99, 'probe'"),
])
def test_f01_literal_paren_cte_write_fails_closed_on_stale_lease(db, sql):
    a, b = _stale_pair(db)
    with pytest.raises(LockLostError):
        a._fenced.execute(sql)
    row = db.execute(
        "SELECT 1 FROM schema_version WHERE version = 99").fetchone()
    assert row is None
    b._release_lock()


@pytest.mark.parametrize("sql", [
    "CREATE TABLE fence_probe (x)",
    "DROP TABLE events",
    "ALTER TABLE events ADD COLUMN fence_probe_col",
    "PRAGMA user_version = 9",
    "ATTACH DATABASE ':memory:' AS fence_probe_att",
    "VACUUM",
], ids=["ddl-create", "ddl-drop", "ddl-alter", "pragma", "attach",
        "vacuum"])
def test_b_f02_ddl_and_pragma_fail_closed_on_stale_lease(db, sql):
    user_version_before = db.execute("PRAGMA user_version").fetchone()[0]
    a, b = _stale_pair(db)
    with pytest.raises(LockLostError):
        a._fenced.execute(sql)
    # nothing landed
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND "
        "name = 'fence_probe'").fetchone() is None
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND "
        "name = 'events'").fetchone() is not None
    columns = {r[1] for r in db.execute("PRAGMA table_info(events)")}
    assert "fence_probe_col" not in columns
    assert db.execute("PRAGMA user_version").fetchone()[0] == \
        user_version_before
    attached = {r[1] for r in db.execute("PRAGMA database_list")}
    assert "fence_probe_att" not in attached
    b._release_lock()


def test_ddl_pragma_and_literal_cte_write_pass_on_a_valid_lease(db):
    """Positive control — the widening must not over-block: every newly
    fenced verb still executes while the generation matches."""
    a = _controller(db, "controller-A")
    assert a._acquire_lock() is True
    a._fenced.execute("CREATE TABLE fence_probe (x)")
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND "
        "name = 'fence_probe'").fetchone() is not None
    a._fenced.execute("PRAGMA user_version = 7")
    assert db.execute("PRAGMA user_version").fetchone()[0] == 7
    a._fenced.execute(
        "WITH t AS (SELECT ')') INSERT INTO schema_version "
        "(version, applied_at) SELECT 90, 'probe'")
    assert db.execute(
        "SELECT 1 FROM schema_version WHERE version = 90").fetchone() \
        is not None
    read = a._fenced.execute(
        "WITH t AS (SELECT 42) SELECT * FROM t").fetchone()
    assert read[0] == 42
    a._release_lock()


def test_refusal_surface_unchanged(db):
    """The HD-01 / F3 refusals are untouched by the widening — never
    narrowed (they still raise loudly instead of delegating)."""
    a = _controller(db, "controller-A")
    assert a._acquire_lock() is True
    with pytest.raises(TypeError, match="executescript"):
        a._fenced.executescript("CREATE TABLE fence_probe (x)")
    with pytest.raises(TypeError, match="cursor"):
        a._fenced.cursor()
    with pytest.raises(TypeError, match="commit"):
        a._fenced.commit()
    with pytest.raises(TypeError, match="rollback"):
        a._fenced.rollback()
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND "
        "name = 'fence_probe'").fetchone() is None
    a._release_lock()


# ── B-F-04 re-check: legacy acquire_writer_lock durability ──

def test_b_f04_failure_path_leaves_no_open_transaction():
    """B-F-04 — when ``BEGIN IMMEDIATE`` succeeds and a later statement
    raises (missing ``scheduler_lock``), the refusal must leave the
    connection OUT of a transaction. Pre-fix: ``return False`` with
    ``in_transaction=True`` — the next ``BEGIN`` then failed with "cannot
    start a transaction within a transaction"."""
    conn = connect(":memory:")          # no migrate -> no scheduler_lock
    try:
        assert acquire_writer_lock(conn, owner_id="A") is False
        assert conn.in_transaction is False
        # the refusal is repeatable — no leaked transaction poisons the
        # next attempt
        assert acquire_writer_lock(conn, owner_id="B") is False
        assert conn.in_transaction is False
    finally:
        conn.close()


def test_b_f04_refusal_closes_transaction_and_success_is_caller_owned(
        tmp_path):
    """B-F-04 — the two deliberate contracts: a REFUSED acquire always
    closes its transaction (B), while a SUCCESSFUL acquire leaves the
    caller-owned transaction open (A) — the documented
    "caller holds the lock until they COMMIT/ROLLBACK" contract."""
    db_path = tmp_path / "fence_lock.db"
    a = connect(str(db_path))
    migrate_to_latest(a)
    b = connect(str(db_path))
    migrate_to_latest(b)
    try:
        assert acquire_writer_lock(a, owner_id="A") is True
        assert a.in_transaction is True      # caller-owned (contract)
        a.execute("COMMIT")                  # caller persists the lock row
        assert acquire_writer_lock(b, owner_id="B") is False
        assert b.in_transaction is False     # refusal closed its txn
        release_writer_lock(b)
    finally:
        a.close()
        b.close()


# ── C-FIX-2 (C-F-03): delegation is fail-closed ──

DELEGATED_REFUSALS = (
    "load_extension", "enable_load_extension", "create_function",
    "create_aggregate", "backup", "serialize", "deserialize",
    "set_authorizer", "set_progress_handler", "set_trace_callback",
    "interrupt",
)


def test_c_f03_refused_table_is_exactly_the_eleven():
    """The verdict table is pinned: all 11 C-F-03 bypass methods, no more."""
    assert tuple(_FencedConnection._REFUSED_DELEGATIONS) == \
        DELEGATED_REFUSALS
    assert len(DELEGATED_REFUSALS) == 11


@pytest.mark.parametrize("name", DELEGATED_REFUSALS)
def test_c_f03_delegated_methods_are_refused_loudly(db, name):
    """Every bypass-capable raw-connection method is refused at ACCESS time
    (C-F-03 probe: pre-fix these delegated and ran with zero lease checks)."""
    f = _FencedConnection(db, lambda: None)
    with pytest.raises(TypeError, match=name):
        getattr(f, name)


def test_c_f03_undeclared_attributes_do_not_delegate(db):
    """Fail closed by default: anything not declared raises AttributeError
    instead of silently reaching the raw connection."""
    f = _FencedConnection(db, lambda: None)
    for name in ("close", "row_factory", "totally_unknown"):
        with pytest.raises(AttributeError, match=name):
            getattr(f, name)


def test_c_fix2_read_surface_is_still_free(db):
    """The declared surface stays usable: SQL entry points + read-only
    transaction status (the one passthrough)."""
    f = _FencedConnection(db, lambda: None)
    assert f.in_transaction is False
    assert f.execute("SELECT 42").fetchone()[0] == 42
    assert callable(f.executemany)


# ── C-FIX-2 (C-F-08): release never COMMITs a foreign transaction ──


def test_c_f08_release_refuses_a_foreign_transaction(tmp_path):
    """Pre-fix the trailing COMMIT made an unrelated insert durable."""
    db_path = tmp_path / "fence_lock_fix08.db"
    a = connect(str(db_path))
    migrate_to_latest(a)
    a.execute("BEGIN IMMEDIATE")
    a.execute("INSERT INTO schema_version (version, applied_at) "
              "VALUES (999, 'probe')")
    with pytest.raises(DatabaseLockError, match="C-F-08"):
        release_writer_lock(a)
    # Nothing committed, nothing discarded — the caller still owns the txn.
    assert a.in_transaction is True
    b = connect(str(db_path))
    assert b.execute(
        "SELECT 1 FROM schema_version WHERE version = 999").fetchone() is None
    a.execute("ROLLBACK")
    a.close()
    b.close()


def test_c_f08_release_refuses_a_wrong_owner_assertion(tmp_path):
    db_path = tmp_path / "fence_lock_fix08b.db"
    a = connect(str(db_path))
    migrate_to_latest(a)
    assert acquire_writer_lock(a, owner_id="A") is True
    with pytest.raises(DatabaseLockError, match="C-F-08"):
        release_writer_lock(a, owner_id="B")
    assert a.in_transaction is True
    # The correct assertion still commits the acquisition transaction.
    release_writer_lock(a, owner_id="A")
    assert a.in_transaction is False
    assert a.execute(
        "SELECT COUNT(*) AS n FROM scheduler_lock").fetchone()["n"] == 0
    a.close()


def test_c_f08_acquire_release_chain_unchanged(tmp_path):
    """Positive control: the documented chain still works with its owner
    assertion, and the released row is durably gone (re-acquire succeeds)."""
    db_path = tmp_path / "fence_lock_fix08c.db"
    a = connect(str(db_path))
    migrate_to_latest(a)
    assert acquire_writer_lock(a, owner_id="A") is True
    assert a.in_transaction is True          # caller-owned (contract)
    release_writer_lock(a, owner_id="A")
    assert a.in_transaction is False
    assert a.execute(
        "SELECT COUNT(*) AS n FROM scheduler_lock").fetchone()["n"] == 0
    assert acquire_writer_lock(a, owner_id="B") is True
    release_writer_lock(a, owner_id="B")
    a.close()
