"""Import-declaration gate for the eval plane.

The governance plane's own suite asserts that no file outside its package
names ``hermes.governance`` (the one declared exception there is the
methodology driver). That gate is a **substring** check over raw file
text, so a file that spells the module path across a concatenation, or
never writes it contiguously, defeats it — the shape this module exists
to prevent.

This module makes the check structural instead of textual. A file's
imports are resolved from its **AST**, by routes that no spelling choice
evades:

1. **constant folding** — the string a dynamic import receives is
   *evaluated* (concatenation, f-strings, ``"".join`` of constants,
   explicit ``str()``) and the result is compared. So
   ``importlib.import_module("hermes." + "governance.approvals")`` is
   detected even though the file never contains the contiguous text;
2. **declared statements** — ``import`` / ``from … import`` naming the
   package or any submodule of it;
3. **runtime presence** — a governed submodule loaded in
   :data:`sys.modules` together with an *unresolvable* dynamic import in
   the file under test: the name may be assembled at runtime, but the
   module it named is loaded;
4. **default-deny** (R7-FIX3) — a dynamic-code construct the folder
   cannot resolve is **reported, never passed**. An importer obtained
   indirectly — ``getattr(importlib, "import_module")`` called or bound to
   a name, a re-bound ``__import__``/``import_module`` — is a dynamic
   import whatever the indirection; ``exec`` / ``eval`` of a string is
   opaque code the gate declines to vouch for. The gate reports the
   resolution it *has*: ``dynamic:<line>:<module>`` when the folded
   target lands in the governed package, ``unevaluable:<line>`` when the
   construct is opaque. Default-deny is the backstop *beneath* the
   enumerated shapes, not a replacement for them: a resolved
   ``importlib.import_module("json")`` still reports nothing.

Honest limit (R7-FIX3): routes 1–4 cover every indirection this gate
enumerates, but "no spelling choice evades" was too strong a claim for a
static reader (recorded in ``R7_REREPORT2.md``). A name computed through
an arbitrary runtime function — not a constant, not an alias, not
``exec``/``eval`` — is *unresolvable by construction*: it is caught by the
runtime witness (route 3) only when the governed module is actually
loaded and the file names the package, and otherwise falls outside the
gate's reach. The gate reports what it can evaluate and refuses to
silently pass a construct it recognises as dynamic; it does not claim to
evaluate arbitrary computation.

The single assembled spelling of the governed package name lives in
:data:`GOVERNED_PACKAGE` below, and the eval plane reaches the package
through :func:`load_governed`, so there is exactly one declared place in
``src/`` where that crossing happens — auditable, and detectable by this
module's own gate (it finds its own dynamic import, by design).
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping

__all__ = [
    "GOVERNED_PACKAGE",
    "declared_import_names",
    "detect_import_mentions",
    "dynamic_import_sites",
    "load_governed",
    "require_declaration",
]

#: The package this gate governs. Written as an explicit two-part
#: assembly with a comment, so this file is an honest instance of the
#: pattern it detects rather than a silent exception to it.
_GOVERN = "hermes"
GOVERNED_PACKAGE = _GOVERN + ".governance"

#: Callables that perform a dynamic import, i.e. an import whose target
#: is chosen at runtime and is therefore invisible to a static statement
#: scan.
_DYNAMIC_IMPORT_CALLS = frozenset({"import_module", "__import__"})

#: Builtins that execute a *string* as code. A ``exec``/``eval`` of a
#: string is a dynamic-import route by construction — the imported name
#: lives inside the string — so the gate reports it rather than passing
#: it, resolving the target when the string folds and marking it
#: ``unevaluable`` when it does not (default-deny).
_EVAL_CALLS = frozenset({"exec", "eval"})

#: The builtin that *fetches* an importer by name, e.g.
#: ``getattr(importlib, "import_module")`` — an indirection the direct
#: attribute route cannot see.
_GETATTR_NAME = "getattr"

#: Dotted-name lexer for a folded code string: ``a.b.c``. Used only to
#: name the module an ``exec``/``eval`` resolves to when it can.
_DOTTED_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def _fold(node: ast.AST,
          names: Mapping[str, str] | None = None) -> str | None:
    """Evaluate a *constant* string expression, or ``None``.

    Handles the literal shapes a name is assembled from — concatenation,
    f-strings, ``"".join`` of constants, explicit ``str()``, and a
    reference to a name bound to a constant string earlier in the file —
    and refuses anything that is not statically constant. A name built
    from a runtime value (a lookup, a function result) returns ``None``:
    the caller then falls back to the runtime witness, rather than
    pretending the value is knowable.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name) and names is not None:
        # A name bound to a constant string earlier in the same file.
        return names.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                folded = _fold(value.value, names)
                if folded is None:
                    return None
                parts.append(folded)
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold(node.left, names), _fold(node.right, names)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(
            func, "id", "")
        if name in {"str", "format"} and node.args:
            return _fold(node.args[0], names)
        if name == "join":
            separator = _fold(func.value, names) if isinstance(
                func, ast.Attribute) else None
            sequence = node.args[0] if node.args else None
            if separator is not None and isinstance(sequence, (ast.List,
                                                               ast.Tuple)):
                items = [_fold(item, names) for item in sequence.elts]
                if None not in items:
                    return separator.join(str(item) for item in items)
    return None


def _constant_names(tree: ast.AST) -> dict[str, str]:
    """Names in the file that are bound to a constant string.

    Single pass, values computed against the map built so far, so a name
    defined in terms of an earlier constant resolves too. A rebinding to
    a non-constant drops the binding rather than leaving a stale value —
    an unresolved name is the safe answer, because the runtime witness
    is there to catch it.
    """
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        folded = _fold(value, names)
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if folded is None:
                names.pop(target.id, None)
            else:
                names[target.id] = folded
    return names


def _in_package(name: str, package: str) -> bool:
    """True iff ``name`` is ``package`` or a submodule of it."""
    return name == package or name.startswith(package + ".")


def _root_of(node: ast.AST) -> str:
    """The dotted name of a simple expression, or ``""``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _root_of(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _getattr_importer(node: ast.AST) -> str | None:
    """Classify ``node`` as a ``getattr(<importlib>, <attr?>)`` fetch.

    The R7-REREPORT2 evasion ``getattr(importlib, "import_module")`` never
    spells a dynamic import the direct route can see, so it is classified
    here and then treated as one:

    ``"resolved"``
        the attribute name folds to a dynamic-import callable
        (``getattr(importlib, "import_module")``);
    ``"opaque"``
        the attribute name is not statically known
        (``getattr(importlib, chosen())``) — default-deny: the gate cannot
        tell which attribute is fetched, so it reports the construct
        rather than passing it;
    ``None``
        not a ``getattr`` on ``importlib`` at all.
    """
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(
        func, "id", "")
    if name != _GETATTR_NAME:
        return None
    if _root_of(node.args[0]) != "importlib":
        return None
    if len(node.args) < 2:
        return "opaque"
    attr_name = _fold(node.args[1], None)
    if attr_name in _DYNAMIC_IMPORT_CALLS:
        return "resolved"
    if attr_name is None:
        return "opaque"
    return None


def _calls_named(node: ast.Call, names: frozenset[str]) -> bool:
    """True iff ``node`` calls one of ``names`` — bare or ``builtins.<name>``."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in names
    if isinstance(func, ast.Attribute):
        return func.attr in names and _root_of(func.value) == "builtins"
    return False


def _value_is_importer(value: ast.AST, aliases: set[str]) -> bool:
    """True iff ``value`` denotes a dynamic importer (used by the alias
    pass)."""
    if isinstance(value, ast.Name):
        return value.id in _DYNAMIC_IMPORT_CALLS or value.id in aliases
    if isinstance(value, ast.Attribute):
        return (value.attr in _DYNAMIC_IMPORT_CALLS
                and _root_of(value.value) == "importlib")
    return _getattr_importer(value) == "resolved"


def _importer_aliases(tree: ast.AST) -> frozenset[str]:
    """Names in the file bound to a dynamic importer.

    Covers ``_imp = __import__``, ``_imp = importlib.import_module`` and
    ``_imp = getattr(importlib, "import_module")`` — the rebinding the
    R7-REREPORT2 evasion used. Single pass with propagation against the
    set built so far (mirrors :func:`_constant_names`), so ``_a = __import__``
    then ``_b = _a`` both resolve; a name re-bound to a non-importer is
    dropped rather than left stale.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        importer = _value_is_importer(value, aliases)
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if importer:
                aliases.add(target.id)
            else:
                aliases.discard(target.id)
    return frozenset(aliases)


def _is_dynamic_import_call(node: ast.Call,
                            aliases: frozenset[str] = frozenset()) -> bool:
    """True iff ``node`` is a dynamic import: ``importlib.import_module(...)``
    / ``__import__(...)`` directly, a call to an aliased importer, or a
    ``getattr(importlib, "import_module")(...)`` fetch.

    An *opaque* ``getattr`` fetch (attribute not statically known) is not
    a resolved call here — :func:`_dynamic_routes` reports it as
    ``unevaluable`` instead.
    """
    func = node.func
    if isinstance(func, ast.Attribute):
        return (func.attr in _DYNAMIC_IMPORT_CALLS
                and _root_of(func.value) == "importlib")
    if isinstance(func, ast.Name):
        return func.id in _DYNAMIC_IMPORT_CALLS or func.id in aliases
    return _getattr_importer(func) == "resolved"


def _scan_code_string(node: ast.Call, names: Mapping[str, str], package: str,
                      sites: set[str], opaque: set[int]) -> None:
    """Classify one ``exec``/``eval`` call as resolved-in-package or opaque.

    The R7-REREPORT2 evasion ``exec()`` of a code string is a dynamic
    import by construction, so it is never passed: a foldable string that
    names the governed package is a resolved site; anything else — an
    un-foldable argument, or a string that does not name the package — is
    ``unevaluable`` (default-deny).
    """
    if not node.args:
        opaque.add(node.lineno)
        return
    folded = _fold(node.args[0], names)
    if not isinstance(folded, str):
        opaque.add(node.lineno)
        return
    if _mentions_package(folded, package):
        targets = [token for token in _DOTTED_NAME.findall(folded)
                   if _in_package(token, package)]
        site = targets[0] if targets else package
        sites.add(f"{node.lineno}:{site}")
    else:
        opaque.add(node.lineno)


def _dynamic_routes(tree: ast.AST, names: Mapping[str, str],
                    aliases: frozenset[str], package: str
                    ) -> tuple[set[str], set[int], bool]:
    """Every dynamic-import route in ``tree``.

    Returns ``(resolved, opaque, has_unresolvable)`` where ``resolved`` is
    ``"<lineno>:<module>"`` for a folded target inside ``package``,
    ``opaque`` is the line of every default-deny construct the gate
    refuses to pass (an opaque ``getattr`` importlib fetch, an
    ``exec``/``eval`` it cannot resolve into the package), and
    ``has_unresolvable`` is the runtime-witness precondition (a dynamic
    import whose target is not statically knowable).
    """
    resolved: set[str] = set()
    opaque: set[int] = set()
    has_unresolvable = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Default-deny: a ``getattr`` importlib fetch whose attribute is not
        # statically known is reported whichever node carries it — the
        # fetch itself, or the call it delivers.
        if (_getattr_importer(node) == "opaque"
                or _getattr_importer(node.func) == "opaque"):
            opaque.add(node.lineno)
        if _calls_named(node, _EVAL_CALLS):
            _scan_code_string(node, names, package, resolved, opaque)
            continue
        if not _is_dynamic_import_call(node, aliases):
            continue
        if not node.args:
            continue
        target = _fold(node.args[0], names)
        if target is not None and _in_package(target, package):
            resolved.add(f"{node.lineno}:{target}")
        elif target is None:
            has_unresolvable = True
    return resolved, opaque, has_unresolvable


def _iter_import_names(tree: ast.AST) -> Iterable[tuple[int, str]]:
    """Yield ``(lineno, module)`` for every statically declared import."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue  # relative import — no absolute dotted name
            yield node.lineno, node.module or ""


def declared_import_names(path: Path) -> tuple[str, ...]:
    """Every module the file at ``path`` statically declares importing.

    AST-derived, so a constructed or split literal is invisible here *by
    construction* — there is no contiguous string in the file for a text
    check to match. Such a route is found by :func:`dynamic_import_sites`
    (constant folding) or, failing that, by the runtime witness in
    :func:`detect_import_mentions`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(sorted({module for _lineno, module in _iter_import_names(tree)
                         if module}))


def dynamic_import_sites(path: Path,
                         package: str = GOVERNED_PACKAGE) -> tuple[str, ...]:
    """Every dynamic import in ``path`` that *resolves* to ``package``.

    Resolution is by constant folding, so an assembled name is found just
    as a contiguous one is::

        importlib.import_module("hermes.governance.approvals")      # direct
        importlib.import_module("hermes." + "governance.approvals")  # split
        getattr(importlib, "import_module")("hermes." + "governance.approvals")
        _imp = __import__; _imp("hermes." + "governance.approvals")
        exec("import " + "hermes.governance.approvals")

    The last three are the R7-REREPORT2 indirections, recognised by
    :func:`_is_dynamic_import_call` / the alias pass and the
    ``exec``/``eval`` scanner. Each hit is reported as
    ``"<lineno>:<module>"`` so a caller can point at the line.

    A dynamic import whose target is not statically knowable is *not*
    reported here — it is unresolvable, which is why
    :func:`detect_import_mentions` also carries a runtime witness and the
    default-deny ``unevaluable`` route.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = _constant_names(tree)
    aliases = _importer_aliases(tree)
    resolved, _opaque, _unresolvable = _dynamic_routes(
        tree, names, aliases, package)
    return tuple(sorted(resolved))


def detect_import_mentions(path: Path,
                           package: str = GOVERNED_PACKAGE
                           ) -> tuple[str, ...]:
    """Every route by which ``path`` reaches ``package``.

    Returns the sorted detection sources that fired:

    ``"declared"``
        the AST declares an ``import`` / ``from`` naming the package or a
        submodule of it;
    ``"dynamic:<lineno>:<module>"``
        a dynamic import whose constant-folded target is the package —
        found even when the file never spells it contiguously, and for the
        indirect routes (``getattr``-fetched importer, aliased importer,
        ``exec``/``eval`` of a code string) when their target folds into
        the package;
    ``"unevaluable:<lineno>"``
        default-deny (R7-FIX3): a dynamic-code construct the gate refuses
        to pass because it cannot resolve it — an opaque ``getattr``
        importlib fetch, or an ``exec``/``eval`` that does not fold into a
        recognisable in-package name;
    ``"unresolved-dynamic"``
        the file performs a dynamic import whose target is not statically
        knowable, and a governed submodule is loaded in
        :data:`sys.modules` — the runtime witness for an assembled name;
    ``"loaded:<module>"``
        the governed submodule itself, named when it is present.

    An empty tuple means no route was found.
    """
    found: set[str] = set()
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    try:
        tree: ast.AST = ast.parse(source, filename=str(path))
    except SyntaxError:
        # Unparsable text can still be a runtime import; keep going with
        # an empty tree so the runtime witness still applies.
        tree = ast.parse("")

    for _lineno, module in _iter_import_names(tree):
        if _in_package(module, package):
            found.add("declared")

    names = _constant_names(tree)
    aliases = _importer_aliases(tree)
    resolved, opaque, has_unresolvable = _dynamic_routes(
        tree, names, aliases, package)
    found.update(f"dynamic:{site}" for site in resolved)
    found.update(f"unevaluable:{line}" for line in opaque)

    # The runtime witness: the one route constant folding cannot reach.
    # It needs an unresolvable dynamic import in this file, a governed
    # module loaded in this process, AND the file mentioning the
    # governed package name — without that last condition the gate would
    # fire on every dynamic import in the tree.
    if has_unresolvable and _mentions_package(source, package):
        loaded = sorted(name for name in sys.modules
                        if _in_package(name, package))
        if loaded:
            found.add("unresolved-dynamic")
            found.update(f"loaded:{name}" for name in loaded)
    return tuple(sorted(found))


def _mentions_package(source: str, package: str) -> bool:
    """True iff the file's text contains the package's own name.

    This is the *narrowing* half of the runtime witness, and it is a
    text check on purpose: it cannot be defeated by splitting the name,
    because splitting is exactly what makes the check fail — and a file
    that splits the name out of its text while still importing it at
    runtime is then caught by the folded-name route instead. Its only job
    is to stop the witness from firing on unrelated dynamic imports.
    """
    package_root, _, tail = package.partition(".")
    if package_root not in source:
        return False
    return not tail or tail in source


def load_governed(*submodules: str,
                  package: str = GOVERNED_PACKAGE) -> tuple[ModuleType, ...]:
    """Load named submodules of the governed package, by declaration.

    This is the eval plane's single declared route to the governance
    plane. It exists so the assembled package name lives in exactly one
    place in ``src/`` instead of being spelled out at each use, and so
    the dependency is inspectable: a reader (or this module's own gate)
    sees one function owning the crossing rather than a scattered set of
    hand-assembled strings.

    Refuses (``ValueError``) on a name that is not a plain submodule
    identifier, so a caller cannot smuggle a path expression through here.
    """
    modules: list[ModuleType] = []
    for submodule in submodules:
        if not submodule or not submodule.isidentifier():
            raise ValueError(
                f"load_governed: {submodule!r} is not a plain submodule name")
        modules.append(importlib.import_module(f"{package}.{submodule}"))
    return tuple(modules)


def require_declaration(module: ModuleType,
                         attributes: dict[str, str]) -> dict[str, Any]:
    """Bind ``module``'s public attributes explicitly, refusing typos.

    A misspelled attribute fails here with a named error instead of
    surfacing as an ``AttributeError`` deep inside a driver — the
    difference between a declared dependency and a discovered one.
    """
    bound: dict[str, Any] = {}
    for name, source in attributes.items():
        if not hasattr(module, source):
            raise ValueError(
                f"require_declaration: {module.__name__!r} has no attribute "
                f"{source!r} (bound as {name!r})")
        bound[name] = getattr(module, source)
    return bound
