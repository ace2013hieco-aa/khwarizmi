"""CONTROL-2 reviewer A (§9.1) — authorship: session auditor (AST technique).

Independent of reviewer B (held-out authorship, lexical technique,
separate file — never imported here). Reads ONLY
tests/cert_gate_rerun/seeded_errors.json. Deterministic: source in,
flagged ids out.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

SEED_PATH = Path(__file__).with_name("seeded_errors.json")


def _has_string_built_sql(tree: ast.AST) -> bool:
    """INJECTION: SQL-shaped string built by interpolation/concat/format."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.JoinedStr, ast.BinOp, ast.Call)):
            text = ast.dump(node)
            if "SELECT" in text.upper() or "DELETE" in text.upper():
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Attribute) \
                            and func.attr == "format":
                        return True
                    continue
                return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if ("SELECT" in v.upper() or "DELETE" in v.upper()) and (
                "%s" in v or "{" in v or "'" in v
            ):
                parent_uses_format = False
                for other in ast.walk(tree):
                    if isinstance(other, ast.BinOp) and other.left is node:
                        parent_uses_format = True
                if parent_uses_format or "%" in v or "{" in v:
                    return True
    return False


def _has_hardcoded_secret(tree: ast.AST, source: str) -> bool:
    """SECRET: long string literal assigned to credential-named target."""
    names = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "KEY")
    for node in ast.walk(tree):
        targets: list[str] = []
        value: object = None
        if isinstance(node, ast.Assign):
            targets = [
                t.id.upper()
                for t in node.targets
                if isinstance(t, ast.Name)
            ]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(
            node.target, ast.Name
        ):
            targets = [node.target.id.upper()]
            value = node.value
        if (
            targets
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and len(value.value) >= 8
            and any(n in t for t in targets for n in names)
        ):
            return True
    _ = source
    return False


def _has_failopen(tree: ast.AST) -> bool:
    """FAILOPEN: swallowed exception or approval-shaped tautology."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            body = node.body
            if not body:
                return True
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                return True
            if len(body) == 1 and isinstance(body[0], ast.Return):
                ret = body[0].value
                if isinstance(ret, ast.Name) and ret.id.isupper():
                    return True
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            returns = [
                n
                for n in ast.walk(node)
                if isinstance(n, ast.Return)
            ]
            consts = [
                r.value for r in returns
                if isinstance(r.value, ast.Constant)
            ]
            if len(consts) >= 2 and all(c is True for c in consts):
                return True
    return False


def _has_unbounded(tree: ast.AST) -> bool:
    """UNBOUNDED: module-level mutable container grown without a bound."""
    grown: set[str] = set()
    bounded = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Compare, ast.If)):
            text = ast.dump(node)
            if "4096" in text or "len(" in text:
                bounded = True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
        ):
            grown.add(node.func.value.id)
        if isinstance(node, ast.Subscript) and isinstance(
            node.value, ast.Name
        ):
            grown.add(node.value.id)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) \
                else node.target
            if isinstance(target, ast.Name) and target.id in grown:
                val = node.value
                if isinstance(val, (ast.List, ast.Dict)):
                    return not bounded
    return False


def review(item_id: str, code: str) -> list[str]:
    """Return defect classes flagged in one seeded item (possibly empty)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    flags: list[str] = []
    if _has_string_built_sql(tree):
        flags.append("INJECTION")
    if _has_hardcoded_secret(tree, code):
        flags.append("SECRET")
    if _has_failopen(tree):
        flags.append("FAILOPEN")
    if _has_unbounded(tree):
        flags.append("UNBOUNDED")
    return flags


def review_all() -> dict[str, list[str]]:
    """Flag every item in the seeded set. Deterministic, no I/O but read."""
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for group in ("defective", "clean"):
        for item in data[group]:
            out[item["id"]] = review(item["id"], item["code"])
    return out
