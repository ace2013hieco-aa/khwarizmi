"""WIRE-6 structural pins (GAP-1 P2-8 / GAP-1 ruling D6-A).

D6-A pins the declared-but-unwired LLM-proposable intent kinds as
declared, with recorded future couplings: ``BRANCH`` / ``ABANDON`` /
``REQUEST_HUMAN`` await R2 / P1-12, ``REQUEST_ADDITIONAL_EXPERIMENT``
is parked behind D2, and ``REQUEST_REPLICATION`` /
``PROPOSE_GATE_OVERRIDE`` own their gates.

The pins are structural, derived from the live AST the way
``tests/test_hygiene_structural.py`` derives its census:

- the dispatch chain inside ``apply_intent`` is located by shape (an
  if/elif chain that positively compares the intent kind) and its
  covered kind set is derived from every comparison in the chain.
  ``IntentKind.X`` attributes, string-literal ``kind == "X"`` and
  ``"X" == kind`` comparisons, ``kind in (...)`` membership, and
  ``or`` unions of those all resolve;
- the uncovered remainder of ``llm_proposable()`` must be exactly the
  six D6 recorded, and every declared kind must be either dispatched
  or one of the six, so a new unwired kind cannot appear unannounced;
- the chain must end in an ``else`` that refuses with the frozen
  ``NOT_WIRED`` code, so an unwired kind cannot fall through silently;
- every ``director_only`` and ``internal_only`` kind must be covered
  by the dispatch.

Anything the resolver cannot read (an unrecognized dispatch shape, an
unresolvable comparison target, a phantom kind name) is an anomaly and
fails the pin closed with the offending node reported.
"""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
GATEWAY = SRC / "hermes" / "research" / "gateway.py"
INTENTS = SRC / "hermes" / "core" / "intents.py"

DECLARED_UNWIRED = frozenset({
    "BRANCH",
    "ABANDON",
    "REQUEST_HUMAN",
    "REQUEST_REPLICATION",
    "REQUEST_ADDITIONAL_EXPERIMENT",
    "PROPOSE_GATE_OVERRIDE",
})

D6_COUPLINGS: dict[str, tuple[str, ...]] = {
    "BRANCH": ("R2", "P1-12"),
    "ABANDON": ("R2", "P1-12"),
    "REQUEST_HUMAN": ("R2", "P1-12"),
    "REQUEST_ADDITIONAL_EXPERIMENT": ("D2",),
    "REQUEST_REPLICATION": ("own-gate",),
    "PROPOSE_GATE_OVERRIDE": ("own-gate",),
}

GATE_TOKENS = frozenset({"R2", "P1-12", "D2", "own-gate"})


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _intent_kind_class(tree: ast.Module) -> ast.ClassDef | None:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "IntentKind":
            return node
    return None


def _intent_kind_members() -> tuple[frozenset[str], list[str]]:
    """The declared ``IntentKind`` member names; any other class-body
    assignment shape is an anomaly, never a silent skip."""
    cls = _intent_kind_class(_parse(INTENTS))
    if cls is None:
        return frozenset(), [f"{INTENTS.name}: IntentKind class not found"]
    members: set[str] = set()
    anomalies: list[str] = []
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        else:
            continue
        if not (isinstance(target, ast.Name) and target.id.isupper()):
            continue
        if not (isinstance(value, ast.Constant)
                and isinstance(value.value, str)):
            anomalies.append(
                f"{INTENTS.name}:{stmt.lineno}: member {target.id} is not a "
                f"string literal")
            continue
        if value.value != target.id:
            anomalies.append(
                f"{INTENTS.name}:{stmt.lineno}: member {target.id} carries a "
                f"differing value {value.value!r}")
        members.add(target.id)
    if not members:
        anomalies.append(f"{INTENTS.name}: no IntentKind members found")
    return frozenset(members), anomalies


def _classmethod_kind_set(name: str) -> tuple[frozenset[str], list[str]]:
    """The kind names in ``IntentKind.<name>()``'s returned frozenset
    literal; any other return shape is an anomaly."""
    cls = _intent_kind_class(_parse(INTENTS))
    if cls is None:
        return frozenset(), [f"{INTENTS.name}: IntentKind class not found"]
    func = next(
        (stmt for stmt in cls.body
         if isinstance(stmt, ast.FunctionDef) and stmt.name == name),
        None,
    )
    if func is None:
        return frozenset(), [f"{INTENTS.name}: IntentKind.{name} not found"]
    returns = [node for node in ast.walk(func) if isinstance(node, ast.Return)]
    if len(returns) != 1 or returns[0].value is None:
        return frozenset(), [(
            f"{INTENTS.name}: IntentKind.{name} must carry exactly one "
            f"return statement (found {len(returns)})")]
    value = returns[0].value
    if not (isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "frozenset"
            and len(value.args) == 1):
        return frozenset(), [(
            f"{INTENTS.name}: IntentKind.{name} must return a frozenset "
            f"literal; cannot resolve {ast.dump(value, include_attributes=False)}")]
    literal = value.args[0]
    if not isinstance(literal, (ast.Set, ast.Tuple, ast.List)):
        return frozenset(), [(
            f"{INTENTS.name}: IntentKind.{name} return argument is not a kind "
            f"literal: {ast.dump(literal, include_attributes=False)}")]
    kinds: set[str] = set()
    anomalies: list[str] = []
    for element in literal.elts:
        if (isinstance(element, ast.Attribute)
                and isinstance(element.value, ast.Name)
                and element.value.id in {"cls", "IntentKind"}):
            kinds.add(element.attr)
        else:
            anomalies.append(
                f"{INTENTS.name}: IntentKind.{name} element is not a plain "
                f"kind reference: {ast.dump(element, include_attributes=False)}")
    return frozenset(kinds), anomalies


_KIND_MATCH_OPS = (ast.Eq, ast.Is, ast.In)
_FALLBACK_FACTORIES = ("_reject", "GatewayRejection")


def _is_kind_expr(node: ast.expr) -> bool:
    """``intent.kind`` (or a bare ``kind``) — the dispatched expression."""
    if isinstance(node, ast.Attribute) and node.attr == "kind":
        return True
    return isinstance(node, ast.Name) and node.id == "kind"


def _compares_kind(test: ast.expr) -> bool:
    """Whether ``test`` positively compares the intent kind at all.

    Positivity is structural, not resolvability: a comparison whose
    target cannot be read still marks the node as dispatch-shaped, so
    the resolver reports the unresolvable target instead of losing the
    chain head.
    """
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        return any(_compares_kind(value) for value in test.values)
    if not isinstance(test, ast.Compare):
        return False
    if not any(isinstance(op, _KIND_MATCH_OPS) for op in test.ops):
        return False
    return any(_is_kind_expr(operand)
               for operand in (test.left, *test.comparators))


def _target_kind_names(node: ast.expr) -> frozenset[str] | None:
    """The kinds a comparison target denotes: a string literal, an
    ``IntentKind.X`` attribute, or a tuple/list/set of those."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return frozenset({node.value})
    if (isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "IntentKind"):
        return frozenset({node.attr})
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        names: set[str] = set()
        for element in node.elts:
            resolved = _target_kind_names(element)
            if resolved is None:
                return None
            names |= set(resolved)
        return frozenset(names)
    return None


def _match_dispatch_test(
    test: ast.expr,
) -> tuple[frozenset[str] | None, list[str]]:
    """The kind names one dispatch test covers.

    ``(None, [])`` means the test does not positively compare the intent
    kind (non-dispatch guards and negative checks do not route). A
    comparison that does compare the kind but cannot be resolved yields
    an anomaly — the pin fails closed instead of guessing.
    """
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        names: set[str] = set()
        anomalies: list[str] = []
        matched = False
        for value in test.values:
            resolved, value_anomalies = _match_dispatch_test(value)
            anomalies.extend(value_anomalies)
            if resolved is not None:
                names |= set(resolved)
                matched = True
        if not matched:
            return None, anomalies
        return frozenset(names), anomalies
    if not isinstance(test, ast.Compare):
        return None, []
    operands: list[ast.expr] = [test.left, *test.comparators]
    if not any(_is_kind_expr(operand) for operand in operands):
        return None, []
    names = set()
    anomalies = []
    matched = False
    for index, op in enumerate(test.ops):
        if not isinstance(op, _KIND_MATCH_OPS):
            continue
        left, right = operands[index], operands[index + 1]
        if not (_is_kind_expr(left) or _is_kind_expr(right)):
            continue
        target = right if _is_kind_expr(left) else left
        resolved = _target_kind_names(target)
        if resolved is None:
            anomalies.append(
                f"line {test.lineno}: cannot resolve a dispatch target: "
                f"{ast.dump(target, include_attributes=False)}")
            continue
        names |= set(resolved)
        matched = True
    if not matched:
        return None, anomalies
    return frozenset(names), anomalies


def _not_wired_fallback_lineno(body: list[ast.stmt]) -> int | None:
    """The line of the ``else`` raise that refuses with ``NOT_WIRED``, or
    ``None`` when the fallback does not carry that frozen code."""
    for stmt in body:
        for node in ast.walk(stmt):
            if not (isinstance(node, ast.Raise)
                    and isinstance(node.exc, ast.Call)):
                continue
            func = node.exc.func
            if isinstance(func, ast.Name):
                factory = func.id
            elif isinstance(func, ast.Attribute):
                factory = func.attr
            else:
                continue
            if factory not in _FALLBACK_FACTORIES:
                continue
            if (len(node.exc.args) >= 2
                    and isinstance(node.exc.args[1], ast.Name)
                    and node.exc.args[1].id == "NOT_WIRED"):
                return node.lineno
    return None


@dataclasses.dataclass(frozen=True)
class _Dispatch:
    covered: frozenset[str]
    fallback_lineno: int
    anomalies: tuple[str, ...]


def _resolve_dispatch(source: str | None = None) -> _Dispatch:
    """Derive the dispatch-covered kind set from ``apply_intent``'s
    if/elif chain, locate the final ``NOT_WIRED`` fallback, and report
    every shape the resolver cannot read as an anomaly."""
    tree = (ast.parse(source, filename="<synthetic>")
            if source is not None else _parse(GATEWAY))
    func = next(
        (node for node in tree.body
         if isinstance(node, ast.FunctionDef) and node.name == "apply_intent"),
        None,
    )
    if func is None:
        return _Dispatch(frozenset(), -1, ("gateway.py: apply_intent not found",))

    anomalies: list[str] = []
    ifs = [node for node in ast.walk(func) if isinstance(node, ast.If)]
    orelse_children = {
        id(child)
        for node in ifs
        for child in node.orelse
        if isinstance(child, ast.If)
    }
    heads = [
        node for node in ifs
        if id(node) not in orelse_children and _compares_kind(node.test)
    ]
    if len(heads) != 1:
        return _Dispatch(frozenset(), -1, (
            ("gateway.py: expected exactly one dispatch chain head in "
             f"apply_intent, found {len(heads)} (lines "
             f"{[node.lineno for node in heads]})"),))

    chain: list[ast.If] = []
    node = heads[0]
    covered: set[str] = set()
    fallback_lineno = -1
    while True:
        chain.append(node)
        names, node_anomalies = _match_dispatch_test(node.test)
        anomalies.extend(node_anomalies)
        if names is None:
            anomalies.append(
                f"line {node.lineno}: a chain test was located by shape but "
                f"its kind comparison did not resolve")
        else:
            covered |= set(names)
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            node = node.orelse[0]
            continue
        fallback_lineno = _not_wired_fallback_lineno(node.orelse)
        if not node.orelse:
            anomalies.append(
                f"line {node.lineno}: the dispatch chain ends without an "
                f"else - an unwired kind would fall through silently")
        elif fallback_lineno is None:
            anomalies.append(
                f"line {node.lineno}: the dispatch chain fallback does not "
                f"raise the NOT_WIRED refusal")
        break

    chain_ids = {id(item) for item in chain}
    for item in ifs:
        if id(item) in chain_ids:
            continue
        if _compares_kind(item.test):
            anomalies.append(
                f"line {item.lineno}: a kind-dispatch comparison sits "
                f"outside the single dispatch chain")

    members, member_anomalies = _intent_kind_members()
    anomalies.extend(member_anomalies)
    for name in sorted(covered - set(members)):
        anomalies.append(
            f"gateway.py: the dispatch covers {name!r}, which is not an "
            f"IntentKind member")

    return _Dispatch(frozenset(covered), fallback_lineno, tuple(anomalies))


def test_dispatch_coverage_pins_the_declared_unwired_remainder() -> None:
    """(a) llm_proposable minus the dispatch-covered set is exactly the
    six kinds D6-A pinned as declared-but-unwired."""
    dispatch = _resolve_dispatch()
    assert dispatch.anomalies == (), (
        "the dispatch chain could not be resolved cleanly; the WIRE-6 pin "
        f"fails closed instead of guessing: {list(dispatch.anomalies)}")
    llm, llm_anomalies = _classmethod_kind_set("llm_proposable")
    assert llm_anomalies == [], llm_anomalies
    members, member_anomalies = _intent_kind_members()
    assert member_anomalies == [], member_anomalies
    assert dispatch.covered <= members, (
        f"the dispatch names kinds that are not declared: "
        f"{sorted(dispatch.covered - members)}")
    assert llm - dispatch.covered == DECLARED_UNWIRED, (
        "llm_proposable minus the dispatch-covered set must be exactly the "
        "six kinds D6-A pinned as declared-but-unwired: "
        f"uncovered={sorted(llm - dispatch.covered)}, "
        f"covered={sorted(dispatch.covered)}")
    assert members - dispatch.covered == DECLARED_UNWIRED, (
        "every declared kind must be either dispatched or one of the six "
        "declared-unwired kinds — a new unwired kind cannot appear "
        f"unannounced: uncovered={sorted(members - dispatch.covered)}")


def test_the_declared_unwired_six_reach_only_the_not_wired_refusal() -> None:
    """(b) each of the six stays LLM-proposable, stays outside the
    dispatch, and lands in the chain's ``NOT_WIRED`` fallback — no silent
    fall-through."""
    dispatch = _resolve_dispatch()
    assert dispatch.anomalies == (), list(dispatch.anomalies)
    assert dispatch.fallback_lineno > 0, (
        "the dispatch chain must end in an else raising the NOT_WIRED "
        "refusal; a missing fallback would let an unwired kind fall "
        "through silently")
    llm, llm_anomalies = _classmethod_kind_set("llm_proposable")
    assert llm_anomalies == [], llm_anomalies
    for kind in sorted(DECLARED_UNWIRED):
        assert kind in llm, f"{kind} must stay declared LLM-proposable"
        assert kind not in dispatch.covered, (
            f"{kind} gained a dispatch branch - D6-A requires that wiring "
            "to land as an announced slice, not a silent change")


def test_the_d6_couplings_are_the_recorded_pin_values() -> None:
    """(c) the hardcoded six-to-coupling map is the D6 ruling text and
    matches the live uncovered set."""
    assert set(D6_COUPLINGS) == DECLARED_UNWIRED
    assert {token for tokens in D6_COUPLINGS.values() for token in tokens} \
        == GATE_TOKENS
    dispatch = _resolve_dispatch()
    assert dispatch.anomalies == (), list(dispatch.anomalies)
    llm, llm_anomalies = _classmethod_kind_set("llm_proposable")
    assert llm_anomalies == [], llm_anomalies
    assert set(D6_COUPLINGS) == llm - dispatch.covered, (
        "the D6-A coupling map and the live uncovered set diverged: "
        f"map={sorted(D6_COUPLINGS)}, "
        f"live={sorted(llm - dispatch.covered)}")


def test_the_dispatch_covers_every_director_only_and_internal_only_kind() -> None:
    """(d) no director-only or internal-only kind silently falls to
    ``NOT_WIRED``."""
    dispatch = _resolve_dispatch()
    assert dispatch.anomalies == (), list(dispatch.anomalies)
    director, director_anomalies = _classmethod_kind_set("director_only")
    internal, internal_anomalies = _classmethod_kind_set("internal_only")
    assert director_anomalies == [], director_anomalies
    assert internal_anomalies == [], internal_anomalies
    missing = sorted((director | internal) - dispatch.covered)
    assert missing == [], (
        "a director-only or internal-only kind silently falls to NOT_WIRED: "
        f"{missing}")


_SYNTHETIC_DISPATCH = '''
def apply_intent(conn, intent):
    if intent.kind == "INSERT_TASK":
        return 1
    elif "EVIDENCE_TRANSITION" == intent.kind:
        return 2
    elif intent.kind in ("ADMIT_TASK",):
        return 3
    elif intent.kind is IntentKind.CURATE_KNOWLEDGE or intent.kind == "BRANCH":
        return 4
    else:
        raise _reject(intent.kind, NOT_WIRED, "not wired")
'''


def test_the_resolver_reads_both_string_literal_orientations() -> None:
    """The two comparison orientations the pin must survive, plus the
    membership and ``or`` forms, resolve from source alone."""
    dispatch = _resolve_dispatch(source=_SYNTHETIC_DISPATCH)
    assert dispatch.anomalies == (), list(dispatch.anomalies)
    assert dispatch.covered == frozenset({
        "INSERT_TASK",
        "EVIDENCE_TRANSITION",
        "ADMIT_TASK",
        "CURATE_KNOWLEDGE",
        "BRANCH",
    }), sorted(dispatch.covered)
    assert dispatch.fallback_lineno > 0
