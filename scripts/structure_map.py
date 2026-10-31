"""Structure map — the graph Ix would build, from the tree.

Ix parses a repo into a system graph (nodes, CALLS/IMPORTS edges) and answers
"what depends on what". Its backend needs Docker and ArangoDB; when that is not
reachable, this builds the part of the graph that matters for contract work:
the **module dependency graph**, aggregated to layers, with cycles and
layer-crossing edges called out.

Why this shape: every defect this project has suffered was two layers
disagreeing about a value. A disagreement needs an edge to travel along, so the
edges are the map. Cycles and layer inversions are where those disagreements
become reachable.

    python scripts/structure_map.py --root src/hermes
    python scripts/structure_map.py --root src/hermes --json

Read-only, deterministic, stdlib only.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

#: The package is the layer. Ordered outermost-first for the matrix.
LAYERS: tuple[str, ...] = (
    "agents", "research", "methodology", "tools", "persistence", "vault",
    "eval", "security", "core",
)

#: Import directions that are documented *in this tree*, each with where the
#: rule is written. Only rules with a citation belong here -- an invented
#: layering rule that the code deliberately breaks is a false positive, and the
#: first draft of this file shipped one (persistence -> research) that turned
#: out to be a documented design decision, not a slip.
DOCUMENTED_RULES: tuple[tuple[str, str, str, str], ...] = (
    ("methodology", "persistence",
     ("the methodology plane stays pure: the driver must NOT import "
      "hermes.persistence; the composition injects the reader"),
     "docs/OPS-5Y-DESIGN.md §9.1"),
)


def module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root.parent).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def resolve(node: ast.ImportFrom, package: str) -> Iterable[str]:
    """Absolute module names for one ``from ... import`` statement."""
    if node.level:
        base = package.split(".")
        base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
        prefix = ".".join(base)
        target = f"{prefix}.{node.module}" if node.module else prefix
    else:
        target = node.module or ""
    if not target.startswith("hermes"):
        return ()
    return (target,)


def _is_type_checking(test: ast.expr) -> bool:
    """True for `if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:`."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _runtime_nodes(tree: ast.AST) -> Iterable[ast.AST]:
    """Every node except the bodies of ``if TYPE_CHECKING:`` blocks.

    A type-only import is not runtime coupling. Counting it produced a false
    "new layer edge" the moment anyone annotated a cross-layer type, which
    would have made the ratchet cry wolf on good code.
    """
    stack: list[ast.AST] = list(getattr(tree, "body", []))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            stack.extend(node.orelse)
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def collect(root: Path) -> tuple[dict[str, set[str]], dict[str, Path],
                                 list[str]]:
    """``{module: imported modules}``, where each module lives, and unparseable.

    Two passes: the module set first, so ``from hermes.research import x`` can
    be resolved to ``hermes.research.x`` when that is a module rather than a
    symbol. Without it, two sibling modules importing each other were both
    recorded as importing the *package* and the cycle was invisible.
    """
    paths = sorted(root.rglob("*.py"))
    where: dict[str, Path] = {}
    shadowed: list[str] = []
    for path in paths:
        name = module_name(root, path)
        existing = where.get(name)
        if existing is None:
            where[name] = path
            continue
        # Two files, one module name. Python resolves this in favour of the
        # *package* (`models/__init__.py` over `models.py`), so the map must
        # too -- otherwise the file Python actually loads is never read.
        winner, loser = ((path, existing)
                         if path.name == "__init__.py" else (existing, path))
        where[name] = winner
        shadowed.append(f"{name} (shadowed: {loser.relative_to(root)})")
    known = set(where)

    edges: dict[str, set[str]] = defaultdict(set)
    unparseable: list[str] = []
    for name, path in where.items():
        is_package = path.name == "__init__.py"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            # Reported, not skipped: an unparseable module adds no edge, so
            # silently ignoring it makes the gate pass over a real file.
            unparseable.append(name)
            continue
        # A package __init__ *is* the package: its relative imports resolve
        # against itself, not its parent. Getting this wrong fabricated a
        # phantom layer for every `from .x import y` in an __init__.
        package = name if is_package else (
            name.rsplit(".", 1)[0] if "." in name else name)
        for node in _runtime_nodes(tree):
            if isinstance(node, ast.ImportFrom):
                for target in resolve(node, package):
                    if target != name:
                        edges[name].add(target)
                    for alias in node.names:
                        submodule = f"{target}.{alias.name}"
                        if submodule in known and submodule != name:
                            edges[name].add(submodule)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("hermes") and alias.name != name:
                        edges[name].add(alias.name)
    return dict(edges), where, unparseable, shadowed


def layer_of(module: str) -> str:
    parts = module.split(".")
    if len(parts) > 1 and parts[1] in LAYERS:
        return parts[1]
    return "(root)" if len(parts) == 1 else f"({parts[1]})"


def build(root: Path) -> dict[str, Any]:
    edges, where, unparseable, shadowed = collect(root)
    # Every module, including the ones with no edge in either direction. The
    # first version reported only modules that appeared in an edge and called
    # the count "modules", so 36 files were silently outside the map.
    modules = sorted(where)

    layer_edges: Counter[tuple[str, str]] = Counter()
    module_edges: set[str] = set()
    for src, targets in edges.items():
        for dst in targets:
            a, b = layer_of(src), layer_of(dst)
            if a != b:
                layer_edges[(a, b)] += 1
                # Pinning only the layer *pair* meant a brand-new module
                # importing an already-pinned pair was invisible. This is the
                # finer grain: which module reaches across, and to where.
                module_edges.add(f"{src}->{b}")

    fan_in: Counter[str] = Counter()
    for targets in edges.values():
        for dst in targets:
            fan_in[layer_of(dst)] += 1

    # Tarjan SCC over the module graph.
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cycles: list[list[str]] = []
    counter = [0]

    def strongconnect(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in edges.get(v, ()):
            if w not in modules:
                continue
            if w not in index:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                cycles.append(sorted(component))

    for module in modules:
        if module not in index:
            strongconnect(module)

    violations = []
    for src_layer, dst_layer, rule, citation in DOCUMENTED_RULES:
        count = layer_edges.get((src_layer, dst_layer), 0)
        if count:
            violations.append({"from": src_layer, "to": dst_layer,
                               "edges": count, "rule": rule,
                               "citation": citation})

    return {
        "modules": len(modules),
        "unparseable": sorted(unparseable),
        "shadowed": sorted(shadowed),
        "module_edges": sorted(module_edges),
        "edges": sum(len(t) for t in edges.values()),
        "layer_edges": {f"{a}->{b}": n
                        for (a, b), n in sorted(layer_edges.items())},
        "fan_in": dict(sorted(fan_in.items(), key=lambda kv: -kv[1])),
        "cycles": sorted(cycles, key=lambda c: (-len(c), c)),
        "violations": violations,
        "largest": sorted(((p.stat().st_size, m) for m, p in where.items()),
                          reverse=True)[:10],
    }


def _edge_pairs(report: dict[str, Any]) -> set[str]:
    return set(report["layer_edges"])


def _cycle_keys(report: dict[str, Any]) -> set[frozenset[str]]:
    return {frozenset(cycle) for cycle in report["cycles"]}


def compare(report: dict[str, Any], ratchet: dict[str, Any] | None
            ) -> dict[str, Any]:
    """What changed since the ratchet, in the only terms that matter.

    A *count* increase on an existing layer edge is normal — more imports of a
    kind the project already has. A **new kind of edge** is the event worth
    stopping for: it is a boundary that did not exist yesterday, and a contract
    disagreement needs one to travel along. Same for cycles: a second
    strongly-connected component means two subsystems just became one.
    """
    if ratchet is None:
        return {"first_run": True, "new_edges": [], "new_module_edges": [],
                "new_shadowed": [],
                "new_cycles": [], "gone_edges": [], "gone_cycles": []}
    known_edges = set(ratchet.get("edges", {}))
    known_cycles = {frozenset(c) for c in ratchet.get("cycles", [])}
    known_modules = set(ratchet.get("module_edges", []))
    current_modules = set(report["module_edges"])
    # An older ratchet has no module_edges; treat that as "not pinned yet"
    # rather than "every module edge is new".
    new_module_edges = (sorted(current_modules - known_modules)
                        if known_modules else [])
    # A shadowed file is a fact about the tree, not a gate defect: pin the known
    # set so a *new* duplicate module name is loud and the existing one is not
    # permanently red.
    known_shadowed = set(ratchet.get("shadowed", []))
    new_shadowed = [name for name in report["shadowed"]
                    if name not in known_shadowed]
    return {
        "first_run": False,
        "new_edges": sorted(_edge_pairs(report) - known_edges),
        "gone_edges": sorted(known_edges - _edge_pairs(report)),
        "new_module_edges": new_module_edges,
        "new_shadowed": new_shadowed,
        "new_cycles": [sorted(c) for c in _cycle_keys(report) - known_cycles],
        "gone_cycles": [sorted(c) for c in known_cycles - _cycle_keys(report)],
    }


def read_ratchet(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{path} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not isinstance(data, dict):
        # A list or a string here silently disabled the gate before: it read
        # as "no ratchet recorded yet" and exited 0.
        print(f"{path} is not a ratchet object (got {type(data).__name__})",
              file=sys.stderr)
        raise SystemExit(2)
    return data


def write_ratchet(path: Path, report: dict[str, Any], note: str,
                  previous: dict[str, Any] | None) -> None:
    data = {
        "edges": dict(sorted(report["layer_edges"].items())),
        "module_edges": list(report["module_edges"]),
        "shadowed": list(report["shadowed"]),
        "cycles": sorted(sorted(c) for c in report["cycles"]),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        "history": (previous or {}).get("history", []),
    }
    if previous is not None:
        data["history"].append({
            "edges": len(previous.get("edges", {})),
            "cycles": len(previous.get("cycles", [])),
            "reason": note or "update"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("STRUCTURE MAP — the module graph, aggregated to layers")
    add("=" * 70)
    add(f"  modules {report['modules']}   import edges {report['edges']}")

    add("")
    add("LAYER MATRIX — rows depend on columns (edge counts)")
    present = [layer for layer in LAYERS
               if any(k.startswith(f"{layer}->") or k.endswith(f"->{layer}")
                      for k in report["layer_edges"])]
    width = max((len(p) for p in present), default=8) + 2
    add(" " * width + "".join(f"{p[:6]:>7}" for p in present))
    for src in present:
        row = f"{src:<{width}}"
        for dst in present:
            n = report["layer_edges"].get(f"{src}->{dst}", 0)
            row += f"{n:>7}" if n else f"{'.':>7}"
        add(row)

    add("")
    add("DOCUMENTED IMPORT RULES — broken?")
    if not report["violations"]:
        add("  none broken (the rules cited in the tree all hold)")
    for v in report["violations"]:
        add(f"  {v['from']} -> {v['to']}  ({v['edges']} edge(s))  "
            f"{v['rule']} [{v['citation']}]")

    add("")
    add(f"CYCLES — {len(report['cycles'])} strongly-connected group(s) > 1")
    for cycle in report["cycles"][:8]:
        add(f"  [{len(cycle)}] {', '.join(cycle[:4])}"
            + (" ..." if len(cycle) > 4 else ""))

    add("")
    add("FAN-IN by layer (how many modules import into it)")
    for layer, n in list(report["fan_in"].items())[:8]:
        add(f"  {layer:<14} {n}")

    add("")
    add("LARGEST MODULES (proxy for where the logic concentrates)")
    for size, module in report["largest"]:
        add(f"  {size:>7}  {module}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("src/hermes"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--ratchet", type=Path, default=None,
                        help="Pin the layer matrix; fail on a new edge or cycle.")
    parser.add_argument("--update", action="store_true",
                        help="Record the current structure as the ratchet.")
    parser.add_argument("--allow", default="",
                        help="Permit every new edge/cycle, and record why.")
    parser.add_argument("--allow-edge", action="append", default=[],
                        metavar="EDGE",
                        help="Permit one named module edge (repeatable).")
    parser.add_argument("--note", default="", help="Context stored with --update.")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"no such package root: {args.root}", file=sys.stderr)
        return 2
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    report = build(args.root)
    print(json.dumps(report, indent=2) if args.json else render(report))

    if args.ratchet is None:
        return 0

    # A missing ratchet disabled the gate silently in the first version.
    if not args.ratchet.exists() and not args.update:
        print(f"\nno ratchet at {args.ratchet} — a missing ratchet is not a "
              f"pass. Run with --update to record one.", file=sys.stderr)
        return 2

    previous = read_ratchet(args.ratchet)
    if args.update:
        if report["violations"]:
            print("\nrefusing to pin a structure that breaks a documented rule:",
                  file=sys.stderr)
            for violation in report["violations"]:
                print(f"  {violation['from']} -> {violation['to']}: "
                      f"{violation['rule']}", file=sys.stderr)
            return 1
        write_ratchet(args.ratchet, report, args.note, previous)
        print(f"\nratchet updated -> {args.ratchet}")
        return 0

    delta = compare(report, previous)
    print("\nSTRUCTURAL RATCHET")
    if delta["first_run"]:
        print("  no ratchet recorded yet; run with --update to set one")
        return 0

    allowed_edges = set(args.allow_edge)
    # A name that matches nothing in the delta was accepted silently before: it
    # moved the ratchet while allowing nothing, or laundered every finding in
    # the same run. Reject it as a misconfiguration.
    unknown_allows = sorted(allowed_edges - set(delta["new_module_edges"]))
    if unknown_allows:
        print(f"\n--allow-edge names not in the new set: {unknown_allows}",
              file=sys.stderr)
        return 2
    new_module_edges = [edge for edge in delta["new_module_edges"]
                        if edge not in allowed_edges]
    violations = report["violations"]
    # A file that cannot be parsed adds no edge, so the gate would pass over
    # a real module. Report it as a finding rather than a silent skip.
    unparseable = report["unparseable"]
    shadowed = delta["new_shadowed"]
    failed = bool(delta["new_edges"] or delta["new_cycles"]
                  or new_module_edges or violations or unparseable or shadowed)

    if not failed:
        print("  no new layer edge, no new module edge, no new cycle")
        if delta["gone_edges"] or delta["gone_cycles"]:
            print(f"  (and {len(delta['gone_edges'])} edge(s) gone, "
                  f"{len(delta['gone_cycles'])} cycle(s) gone — record with "
                  f"--update)")
        return 0

    for edge in delta["new_edges"]:
        print(f"  NEW LAYER EDGE   {edge}")
    for edge in new_module_edges:
        print(f"  NEW MODULE EDGE  {edge}")
    for cycle in delta["new_cycles"]:
        print(f"  NEW CYCLE ({len(cycle)})  {', '.join(cycle)}")
    for name in unparseable:
        print(f"  UNPARSEABLE      {name} (adds no edge; not analysed)")
    for name in shadowed:
        print(f"  NEWLY SHADOWED   {name} (one file per module name; not read)")
    for violation in violations:
        print(f"  RULE BROKEN      {violation['from']} -> "
              f"{violation['to']}: {violation['rule']} "
              f"[{violation['citation']}]")

    if args.allow:
        named = list(delta["new_edges"]) + list(delta["new_module_edges"])
        named += [f"cycle:{','.join(cycle)}" for cycle in delta["new_cycles"]]
        named += [f"rule:{v['from']}->{v['to']}" for v in violations]
        write_ratchet(args.ratchet, report,
                      f"{args.allow} (allowed: {', '.join(named) or 'none'})",
                      previous)
        print(f"  allowed: {args.allow} (ratchet moved; the names above are "
              f"recorded in its history)")
        return 0

    if allowed_edges and not (delta["new_edges"] or delta["new_cycles"]
                              or new_module_edges or violations
                              or unparseable or shadowed):
        write_ratchet(args.ratchet, report,
                      f"allowed edges: {', '.join(sorted(allowed_edges))}",
                      previous)
        print(f"  allowed {len(allowed_edges)} named edge(s); ratchet moved")
        return 0

    print("  A new edge is a boundary that did not exist yesterday, and a "
          "contract disagreement needs one to travel along.\n"
          "  Re-run with --allow-edge <name> for a specific one, or "
          "--allow \"<reason>\" to accept all of them.")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - the exit status is the point
        import traceback
        traceback.print_exc()
        print("the gate itself failed — exit 2, not a finding", file=sys.stderr)
        raise SystemExit(2) from None
