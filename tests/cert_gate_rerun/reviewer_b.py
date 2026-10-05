"""Held-out author (lexical technique), independent of reviewer A.

Second-author review for the cert-gate rerun experiment. Uses purely
lexical token scanning over source lines (regex and substring checks).
No AST parsing is used, keeping the technique separate from reviewer A.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SEED_PATH = Path(__file__).with_name("seeded_errors.json")

_SQL_RE = re.compile(r"\b(?:SELECT|DELETE|INSERT|UPDATE)\b", re.IGNORECASE)
_CRED_RE = re.compile(r"token|secret|password|api[_-]?key", re.IGNORECASE)
_ASSIGN_RE = re.compile(r"(?<![=!<>])=(?!=)")
_QUOTED_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'')
_CONST_RETURN_RE = re.compile(r"return\s+[A-Z_][A-Z0-9_]*$")
_DEF_RE = re.compile(r"def\s+\w+")
_EMPTY_RE = re.compile(r"=\s*(\[\]|\{\})")
_SUBSCRIPT_STORE_RE = re.compile(r"\]\s*=\s*\S")


def _has_injection(lines: list[str]) -> bool:
    for line in lines:
        if _SQL_RE.search(line) and (
            'f"' in line
            or "f'" in line
            or "+" in line
            or "%" in line
            or ".format(" in line
        ):
            return True
    return False


def _has_secret(lines: list[str]) -> bool:
    for line in lines:
        if "os.environ" in line or "os.getenv" in line:
            continue
        if not _CRED_RE.search(line):
            continue
        if not _ASSIGN_RE.search(line):
            continue
        for match in _QUOTED_RE.finditer(line):
            lit = match.group(1) if match.group(1) is not None else match.group(2)
            if lit is not None and len(lit) >= 8:
                return True
    return False


def _has_failopen(lines: list[str]) -> bool:
    stripped = [line.strip() for line in lines]
    for i, cur in enumerate(stripped):
        if cur.startswith("except"):
            for offset in (1, 2, 3):
                j = i + offset
                if j >= len(stripped):
                    break
                nxt = stripped[j]
                if nxt == "pass":
                    return True
                if _CONST_RETURN_RE.match(nxt):
                    return True
    count = 0
    in_func = False
    for raw in lines:
        cur = raw.strip()
        if _DEF_RE.match(cur):
            if count >= 2:
                return True
            count = 0
            in_func = True
            continue
        if in_func and cur == "return True":
            count += 1
            if count >= 2:
                return True
    return False


def _has_unbounded(code: str, lines: list[str]) -> bool:
    has_empty = any(_EMPTY_RE.search(line) for line in lines)
    if not has_empty:
        return False
    has_growth = any(".append(" in line for line in lines)
    if not has_growth:
        has_growth = any(_SUBSCRIPT_STORE_RE.search(line) for line in lines)
    if not has_growth:
        return False
    return "len(" not in code


def review(item_id: str, code: str) -> list[str]:
    """Flag defect classes for one seeded item using lexical rules."""
    assert isinstance(item_id, str)
    lines = code.splitlines()
    found: list[str] = []
    if _has_injection(lines):
        found.append("INJECTION")
    if _has_secret(lines):
        found.append("SECRET")
    if _has_failopen(lines):
        found.append("FAILOPEN")
    if _has_unbounded(code, lines):
        found.append("UNBOUNDED")
    return found


def review_all() -> dict[str, list[str]]:
    """Flag every seeded item from the seed JSON file."""
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for group in ("defective", "clean"):
        entries = payload.get(group, [])
        for entry in entries:
            eid = str(entry["id"])
            out[eid] = review(eid, str(entry["code"]))
    return out
