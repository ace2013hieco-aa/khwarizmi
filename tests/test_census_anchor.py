"""Self-enforcing census: no ``$`` end-anchor in identity grammars.

Phase-4 precedent (commit 1918dad, anchor hygiene 4.1/4.2): ``$`` matches
before a trailing newline, so ``"abc\\n"`` satisfied ``^abc$`` and a
newline could be smuggled into an identifier. The fix was a ``$`` -> ``\\Z``
sweep plus ``core/grammar.compile_identifier``. This test pins that
invariant so a ``$`` cannot silently reappear in an identity grammar.

Scope: every string literal in ``src/hermes`` that is compiled as a regex
(``re.compile``/``re.match``/``re.fullmatch``/``re.search`` first argument,
or a module-level constant whose name ends in ``_RE``/``_PATTERN``) and
that carries an unescaped ``$`` outside a character class. Redaction
matchers (``eval/ops.py`` ``_REDACTION_*``) are *search* patterns, not
identity grammars, and are excluded explicitly below.

Current grammar table (as of this file; ``$`` present = violation):

    grammar                                   location                              anchor
    ----------------------------------------  ------------------------------------  -------
    op / svc / read token                     eval/ops.py:207-209                    \\Z-required
    sha256 hex                                eval/ops.py:966                        \\Z-required
    program ref / slot ref                    research/programs.py:168,175           \\Z-required
    capability HANDLE                         tools/capabilities/invoke.py:136       \\Z-required
    content type                              tools/providers/hazards.py:655         \\Z-required
    arXiv new / old / resolver                tools/providers/normalize.py:42-45     \\Z-required
    redaction matchers (search, excluded)     eval/ops.py:277-292                    n/a
    pbkdf2 storage format (split, excluded)   persistence/repositories.py:964,1038   n/a

The scanner finds only ``$`` *outside* character classes; ``$`` inside
``[...]`` (e.g. ``[a-z0-9!#$&^_.+-]``) is a literal and is not an anchor.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "hermes"

# Non-identity strings that legitimately contain ``$`` (search patterns,
# shell/format text, storage-format delimiters). Keyed by (relpath, lineno).
EXCLUDED_NON_GRAMMAR = {
    ("eval/ops.py", 277),
    ("eval/ops.py", 278),
    ("eval/ops.py", 279),
    ("eval/ops.py", 280),
    ("eval/ops.py", 281),
    ("eval/ops.py", 282),
    ("eval/ops.py", 283),
    ("eval/ops.py", 284),
    ("eval/ops.py", 285),
    ("eval/ops.py", 286),
    ("eval/ops.py", 287),
    ("eval/ops.py", 288),
    ("eval/ops.py", 289),
    ("eval/ops.py", 290),
    ("eval/ops.py", 291),
    ("eval/ops.py", 292),
    ("persistence/repositories.py", 964),
    ("persistence/repositories.py", 1001),
    ("persistence/repositories.py", 1025),
    ("persistence/repositories.py", 1038),
}

_REGEX_CALLS = {"compile", "match", "fullmatch", "search"}


def _unescaped_dollar_outside_class(pattern: str) -> bool:
    depth = 0
    escaped = False
    for ch in pattern:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "[":
            depth += 1
        elif ch == "]" and depth:
            depth -= 1
        elif ch == "$" and depth == 0:
            return True
    return False


def _is_regex_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _str_value(node: ast.AST) -> str:
    assert isinstance(node, ast.Constant) and isinstance(node.value, str)
    return node.value


def _regex_string_nodes(tree: ast.AST):
    """Yield string constants used as regex patterns in this module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else None
            )
            if name in _REGEX_CALLS and _is_regex_literal(node.args[0]):
                yield node.args[0]
        if isinstance(node, ast.Assign) and _is_regex_literal(node.value):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and (
                    tgt.id.endswith("_RE") or tgt.id.endswith("_PATTERN")
                ):
                    yield node.value  # type: ignore[misc]


def _scan() -> list[str]:
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        seen: set[int] = set()
        for node in _regex_string_nodes(tree):
            if id(node) in seen:
                continue
            seen.add(id(node))
            if (rel, node.lineno) in EXCLUDED_NON_GRAMMAR:
                continue
            if _unescaped_dollar_outside_class(_str_value(node)):
                violations.append(f"{rel}:{node.lineno}: {_str_value(node)!r}")
    return violations


def test_no_dollar_end_anchor_in_identity_grammars() -> None:
    violations = _scan()
    assert not violations, (
        "identity grammar uses '$' end-anchor (matches before a trailing "
        "newline; use '\\Z' or core.grammar.compile_identifier):\n  "
        + "\n  ".join(violations)
    )


def test_scanner_detects_injected_dollar() -> None:
    """Self-test: the detector itself must flag a planted '$' anchor and
    must NOT flag a '$' that sits inside a character class."""
    assert _unescaped_dollar_outside_class(r"^abc$")
    assert _unescaped_dollar_outside_class(r"^(?:x)$")
    assert not _unescaped_dollar_outside_class(r"^abc\Z")
    assert not _unescaped_dollar_outside_class(r"^[a-z0-9!#$&^_.+-]+\Z")
    assert not _unescaped_dollar_outside_class(r"\$literal\Z")


def test_grammar_table_pinned_to_known_sites() -> None:
    """The set of regex-literal sites must not silently grow: any new
    identity grammar must be added here deliberately."""
    sites = set()
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _regex_string_nodes(tree):
            if _unescaped_dollar_outside_class(_str_value(node)):
                sites.add((rel, node.lineno))
    unexpected = sites - EXCLUDED_NON_GRAMMAR
    assert not unexpected, f"unexpected '$' regex sites: {sorted(unexpected)}"
