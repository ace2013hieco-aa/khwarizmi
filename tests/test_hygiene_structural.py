"""HYGIENE-2 structural pins (P3-4, P3-6).

P3-4 — ``database.acquire_writer_lock`` is a dormant primitive with zero
``src`` callers. It is retained, not deleted: the certified Phase-1
acceptance surface imports and exercises it directly
(``tests/test_phase1_acceptance.py``, ``tests/test_fence_classifier.py``)
and IDR-016 records it as a dormant-by-design production primitive. The
pin is therefore "defined in ``database.py``, never referenced from any
other ``src`` module" — acquisition boundaries stay owned by the
certified ``BEGIN IMMEDIATE`` convention (28 owners / 124 calls).

P3-6 — the gateway refusal vocabulary is a closed set of module-level
code constants, and every refusal call names one of them. The exact
per-code counts below are derived from the live AST, not from prose.
The scan fails closed on any string-built/computed code expression or
any refusal call that is not raised, so a future code cannot slip past
the census silently. ``spine_code`` (the registry that never existed)
must remain absent from ``src``.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
GATEWAY = SRC / "hermes" / "research" / "gateway.py"
DATABASE = SRC / "hermes" / "persistence" / "database.py"

EXPECTED_REFUSAL_CODE_COUNTS = {
    # OPS-5Z Group E adds the round request/outcome validators: 8 new
    # MALFORMED_PAYLOAD sites (payload/schema/journal-record shape), 2 BUDGET
    # (the same-round and already-round claim bounds), 2 PROPOSAL (no such
    # round; a winner outside the round), 2 EVIDENCE_REF (a round cannot cite
    # an artifact it did not fetch, nor a web-derived row) and 1 STALE (one
    # terminal record).
    "BUDGET": 3,
    "CLASSIFICATION_REF": 19,
    "CONTRADICTION_BACKLOG": 1,
    "DEPENDENCY": 4,
    "EVIDENCE_REF": 28,
    "IDEMPOTENCY_CONFLICT": 3,
    "MALFORMED_PAYLOAD": 132,  # COND-TYPE +1; P2-10 +1; AUDIT-TXN +1
    "NOT_COMPILED": 2,
    "NOT_WIRED": 1,
    "OPERATOR": 5,
    "PROJECT_NOT_FOUND": 3,
    "PROPOSAL": 46,  # OPS-5Q +1 (unresolvable contradiction party scope)
    "PROVENANCE": 15,
    "ROLE": 8,
    "SCOPE_NOT_GOVERNED": 2,
    "STALE": 12,
    "UNKNOWN_KIND": 1,
}

_SPINE_CODE_RE = re.compile(r"\bspine_code\b")


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _refusal_calls(tree: ast.Module) -> tuple[dict[str, int], list[str]]:
    """Count gateway refusal calls by code symbol.

    Returns ``(counts, anomalies)``. An anomaly is either a refusal call
    whose code argument is not a bare module-level name (computed or
    string-built codes would defeat the census) or a refusal call in a
    non-raise position (a returned/passed rejection would escape a
    raise-site-only scan).
    """
    raised = {
        id(node.exc)
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
    }
    factory_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_reject":
            factory_nodes = {id(child) for child in ast.walk(node)}
            break
    counts: dict[str, int] = {}
    anomalies: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in factory_nodes:
            continue
        func = node.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            continue
        if name not in {"_reject", "GatewayRejection"}:
            continue
        if id(node) not in raised:
            anomalies.append(f"line {node.lineno}: refusal call is not raised")
            continue
        if len(node.args) < 2:
            anomalies.append(f"line {node.lineno}: missing code argument")
            continue
        code = node.args[1]
        if not isinstance(code, ast.Name):
            anomalies.append(
                f"line {node.lineno}: code is not a bare constant name: "
                f"{ast.dump(code, include_attributes=False)}")
            continue
        counts[code.id] = counts.get(code.id, 0) + 1
    return counts, anomalies


def test_acquire_writer_lock_is_defined_but_has_no_src_callers() -> None:
    database_tree = _tree(DATABASE)
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "acquire_writer_lock"
        for node in ast.walk(database_tree)
    ), "acquire_writer_lock must remain defined (deletion is unsafe: tests "
    "and IDR-016 depend on the dormant primitive)"

    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if path == DATABASE:
            continue
        for node in ast.walk(_tree(path)):
            if ((isinstance(node, ast.Name)
                 and node.id == "acquire_writer_lock")
                    or (isinstance(node, ast.Attribute)
                        and node.attr == "acquire_writer_lock")):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "acquire_writer_lock":
                        offenders.append(
                            f"{path.relative_to(SRC)}:{node.lineno}")
    assert offenders == [], (
        "acquire_writer_lock must have zero src callers; transaction "
        f"boundaries are owned by the certified convention: {offenders}")


def test_gateway_refusal_code_census_is_exact() -> None:
    counts, anomalies = _refusal_calls(_tree(GATEWAY))
    assert anomalies == [], (
        "refusal codes must be bare module constants raised in place; "
        f"string-built or non-raise refusals defeat the census: {anomalies}")
    assert counts == EXPECTED_REFUSAL_CODE_COUNTS
    # COND-TYPE +1 site; GAP-1 P2-10 +1 site; AUDIT-TXN +1 site (the
    # pre-dispatch audit-payload gate in apply_intent); OPS-5Q +1 site
    # (unresolvable contradiction party scope); OPS-5Z Group E +14 sites
    # (the round request and its terminal record — see the table above).
    assert sum(counts.values()) == 285


def test_proposal_refusal_code_count_is_deterministic() -> None:
    counts, _ = _refusal_calls(_tree(GATEWAY))
    assert counts["PROPOSAL"] == 46


def test_refusal_code_symbols_are_stable_module_constants() -> None:
    constants: dict[str, str] = {}
    for stmt in _tree(GATEWAY).body:
        if (isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)):
            constants[stmt.targets[0].id] = stmt.value.value
    assert set(EXPECTED_REFUSAL_CODE_COUNTS) <= set(constants)
    for name in EXPECTED_REFUSAL_CODE_COUNTS:
        assert constants[name] == name


def test_no_spine_code_token_in_src() -> None:
    hits: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if _SPINE_CODE_RE.search(line):
                hits.append(f"{path.relative_to(SRC)}:{lineno}")
    assert hits == [], f"spine_code must not exist in src: {hits}"
