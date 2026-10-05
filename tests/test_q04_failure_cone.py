"""Q-04 design-gate §6 — the eight acceptance fixtures for the derived
failure-propagation traversal (pure functions in ``core/graph.py``).

The graph is the TRANSITIVE view of the controller's own eligibility
predicate over the ratified ``task_dependencies`` edge set — deterministic,
cycle-defensive, read-only, never a scheduler input. These fixtures pin the
cone/blast-radius/blocked-roots semantics, the Q-05 classification labels,
the version-bound result hash, the no-authority structural check, and the
linear bounds.
"""
from __future__ import annotations

from hermes.core.graph import (
    GRAPH_QUERY_VERSION,
    FailureConeEntry,
    blocked_roots,
    change_blast_radius,
    failure_cone,
    graph_result_hash,
)
from hermes.core.task_status import TaskStatus

SUCCEEDED = TaskStatus.SUCCEEDED.value
FAILED = TaskStatus.FAILED.value
RETRYING = TaskStatus.RETRYING.value
PENDING = TaskStatus.PENDING.value


def _chain(*ids):
    """A→B→C... dependents map from a linear chain."""
    return {ids[i]: [ids[i + 1]] for i in range(len(ids) - 1)}


def _entry(task_id, blocker, status, label=None):
    return FailureConeEntry(task_id=task_id, blocking_ancestor=blocker,
                            blocking_status=status,
                            classification_label=label)


class TestFailureCone:
    def test_no_false_negatives_across_three_hops(self):
        """AC-1 — A→B→C→D, A FAILED-terminal: cone = {B, C, D}, every
        dependent present, each labeled by the FIRST blocking ancestor (A)."""
        dependents = _chain("A", "B", "C", "D")
        statuses = {"A": FAILED, "B": PENDING, "C": PENDING, "D": PENDING}
        cone = failure_cone(["A"], dependents, statuses)
        assert cone == (
            _entry("B", "A", FAILED),
            _entry("C", "A", FAILED),
            _entry("D", "A", FAILED),
        )

    def test_partial_failure_isolation(self):
        """AC-2 — A SUCCEEDED, B FAILED: cone(B) = {C, D}; B's sibling E
        (dep A only) is NOT in the cone; a SUCCEEDED seed blocks nothing."""
        dependents = {"A": ["B", "E"], "B": ["C"], "C": ["D"]}
        statuses = {"A": SUCCEEDED, "B": FAILED, "C": PENDING,
                    "D": PENDING, "E": PENDING}
        assert failure_cone(["B"], dependents, statuses) == (
            _entry("C", "B", FAILED),
            _entry("D", "B", FAILED),
        )
        assert failure_cone(["A"], dependents, statuses) == ()

    def test_terminal_vs_transient(self):
        """AC-3 — a RETRYING ancestor is transient (not a blocked root);
        a FAILED-terminal ancestor is permanent (shows in blocked_roots)."""
        dependents = {"A": ["B"], "B": ["C"]}
        transient = {"A": RETRYING, "B": PENDING, "C": PENDING}
        assert failure_cone(["A"], dependents, transient) == (
            _entry("B", "A", RETRYING),
            _entry("C", "A", RETRYING),
        )
        assert blocked_roots(dependents, transient) == ()  # no FAILED ancestor
        terminal = {"A": FAILED, "B": PENDING, "C": PENDING}
        assert blocked_roots(dependents, terminal) == ("B", "C")

    def test_classification_label_from_digest(self):
        """AC-4 — the blocking ancestor's Q-05 label rides the cone entry;
        a missing/corrupt label degrades to None (never a crash)."""
        dependents = _chain("A", "B")
        statuses = {"A": FAILED, "B": PENDING}
        labels = {"A": "IMPLEMENTATION_FAILURE"}
        cone = failure_cone(["A"], dependents, statuses,
                            classification_labels=labels)
        assert cone == (_entry("B", "A", FAILED, "IMPLEMENTATION_FAILURE"),)
        # Missing label for the same state: None, deterministic, no error.
        assert failure_cone(["A"], dependents, statuses) == (
            _entry("B", "A", FAILED, None),)
        assert failure_cone(["A"], dependents, statuses,
                            classification_labels={"other": "X"}) == (
            _entry("B", "A", FAILED, None),)

    def test_cycle_terminates_deterministically(self):
        """AC-5 — a hand-inserted 2-cycle (A→B, B→A) terminates (visited
        set) and yields deterministic output."""
        dependents = {"A": ["B"], "B": ["A"]}
        statuses = {"A": FAILED, "B": PENDING}
        assert failure_cone(["A"], dependents, statuses) == (
            _entry("B", "A", FAILED),)
        # Self-loop too (CHECK forbids it at the DB, defensively here).
        dependents2 = {"A": ["A"]}
        assert failure_cone(["A"], dependents2, statuses) == ()
        assert change_blast_radius(["A"], dependents) == ("B",)

    def test_determinism_and_version_bound_hash(self):
        """AC-6 — same state ⇒ byte-identical cone + identical content hash;
        query order does not matter; the version triple binds the identity."""
        dependents = {"A": ["B", "E"], "B": ["C"], "C": ["D"]}
        statuses = {"A": FAILED, "B": PENDING, "C": PENDING,
                    "D": PENDING, "E": PENDING}
        c1 = failure_cone(["A"], dependents, statuses)
        c2 = failure_cone(["A"], dependents, statuses)
        assert c1 == c2
        h1 = graph_result_hash("failure_cone", [c.task_id for c in c1])
        h2 = graph_result_hash("failure_cone", [c.task_id for c in c2])
        assert h1 == h2
        assert GRAPH_QUERY_VERSION == "1"
        # The version is part of the identity: a different version hashes
        # differently for the SAME payload.
        import hashlib
        import json as _json
        body = {"version": "2", "kind": "failure_cone",
                "payload": [c.task_id for c in c1]}
        other = hashlib.sha256(_json.dumps(
            body, sort_keys=True, separators=(",", ":"),
            default=str).encode("utf-8")).hexdigest()
        assert other != h1

    def test_change_blast_radius_regardless_of_status(self):
        """Blast radius — a SUCCEEDED seed still has a full dependent
        closure (a patch/re-run affects downstream even when it currently
        SUCCEEDED)."""
        dependents = {"A": ["B", "E"], "B": ["C"], "C": ["D"]}
        assert change_blast_radius(["A"], dependents) == ("B", "C", "D", "E")
        assert change_blast_radius(["A"], dependents) == (
            change_blast_radius(["A"], dependents))


class TestNoAuthorityAndBounds:
    def _executable_source(self):
        """Module source with docstrings stripped, so the authority scan
        reads real code — not the docstring documenting the absence of
        authority (the established AC-04 pattern)."""
        import ast
        import inspect

        import hermes.core.graph as graph
        tree = ast.parse(inspect.getsource(graph))
        for node in ast.walk(tree):
            if (isinstance(node, (ast.Module, ast.FunctionDef,
                                  ast.AsyncFunctionDef, ast.ClassDef))
                    and node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body = node.body[1:]
        return ast.unparse(tree)

    def test_module_has_no_write_sql(self):
        """AC-7 — the pure module never writes: no write statements
        anywhere in core/graph.py (the graph is a derived VIEW)."""
        src = self._executable_source()
        for banned in ("INSERT INTO", "UPDATE ", "DELETE FROM",
                       "REPLACE INTO", "sqlite3", "conn.execute"):
            assert banned not in src, (
                f"write surface leaked into core/graph.py: {banned!r}")

    def test_traversal_linear_in_edges(self):
        """AC-8 — a 60-node chain is fully covered in one pass each (the
        visited set makes the traversal linear in edges); correctness holds
        at size."""
        n = 60
        dependents = {f"t{i:02d}": [f"t{i+1:02d}"] for i in range(n - 1)}
        statuses = {f"t{i:02d}": PENDING for i in range(n)}
        statuses["t00"] = FAILED
        cone = failure_cone(["t00"], dependents, statuses)
        assert len(cone) == n - 1  # every dependent, once
        assert cone[-1].task_id == f"t{n-1:02d}"
        assert cone[-1].blocking_ancestor == "t00"  # root-cause labeled
        assert change_blast_radius(["t00"], dependents) == tuple(
            f"t{i:02d}" for i in range(1, n))


class TestAuditRegressionF9:
    def test_succeeded_intermediate_breaks_the_blocking_chain(self):
        """F9 (audit) — a SUCCEEDED intermediate stops the propagation: the
        predicate requires EVERY edge source on the path to be not SUCCEEDED,
        so C (whose direct dep B SUCCEEDED) runs regardless of A's failure —
        C is neither in the cone nor a blocked root; B (A's direct dependent)
        is in the cone only."""
        dependents = {"A": ["B"], "B": ["C"]}
        statuses = {"A": FAILED, "B": SUCCEEDED, "C": PENDING}
        assert failure_cone(["A"], dependents, statuses) == (
            _entry("B", "A", FAILED),)
        assert blocked_roots(dependents, statuses) == ()
        # And the normal blocked chain is unaffected.
        normal = {"A": FAILED, "B": PENDING, "C": PENDING}
        assert [e.task_id for e in failure_cone(
            ["A"], dependents, normal)] == ["B", "C"]
        assert blocked_roots(dependents, normal) == ("B", "C")
