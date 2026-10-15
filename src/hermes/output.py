"""Operator-output boundary (EXT-5 / triage R3) — control-byte scrubbing.

The operator CLIs (`hermes.cli` and `hermes.eval.platform_cli`) write
through this module. Text lifted out of the journal — an event `reason`,
a `caused_by` attribution, a `project_id`, a task field — is *foreign*
content: whoever journalled it chose the bytes, and a terminal obeys the
control sequences it is handed. This module is the single place that
neutralizes them.

The rule, applied per emitted line: every code point in a forbidden class
is **escaped visibly** (`\\x1b`, `\\u202e`) rather than dropped, and the
escaped result is checked before anything is written. A result that
still carries a forbidden code point is refused loudly (`OutputRefused`,
`CONTROL_BYTES`) — fail-closed. There is no truncation and no length
budget: escaping is a pure per-code-point function, so every character
either survives as itself or as its visible spelling.

Forbidden classes:

- C0 (`0x00`-`0x1F`) — includes ESC (`0x1b`, the ANSI/OSC introducer),
  BEL, CR, LF and TAB; a stored payload could otherwise repaint the
  terminal or forge an extra output line.
- DEL (`0x7F`) and C1 (`0x80`-`0x9F`) — the 8-bit CSI (`0x9b`) and OSC
  (`0x9d`) introducers.
- The Unicode Bidi_Control set (`U+061C`, `U+200E`, `U+200F`,
  `U+202A`-`U+202E`, `U+2066`-`U+2069`) — the complete 12-code-point
  inventory — which reorders *rendered* text so a payload can display
  something other than what is stored.

Deliberately preserved: every other printable code point, including
non-ASCII (the CLI's own em-dash, a legitimate path), and the rest of Cf
(ZWJ, soft hyphen) so ordinary text is not mangled.

Structure is the CLI's, never the data's: `emit` takes ONE line, so an
embedded newline inside a stored value is escaped rather than allowed to
start a new line; `emit_lines` joins with real newlines, which the caller
supplied as separate elements.

Prohibited-claims discipline: this is a display boundary. It says nothing
about the validity of what it displays.
"""
from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from typing import TextIO

__all__ = [
    "FORBIDDEN",
    "REFUSAL_TEXT",
    "OutputRefused",
    "emit",
    "emit_lines",
    "run_boundary",
    "scrub",
]

_C0: frozenset[int] = frozenset(range(0x00, 0x20))
_C1: frozenset[int] = frozenset(range(0x80, 0xA0))
_DEL: frozenset[int] = frozenset({0x7F})
_BIDI_OVERRIDES: frozenset[int] = (
    frozenset({0x061C, 0x200E, 0x200F})
    | frozenset(range(0x202A, 0x202F))
    | frozenset(range(0x2066, 0x206A))
)

FORBIDDEN: frozenset[int] = _C0 | _C1 | _DEL | _BIDI_OVERRIDES

REFUSAL_TEXT = (
    "Refused [CONTROL_BYTES]: output withheld — the text could not be "
    "proven free of terminal control sequences."
)


class OutputRefused(Exception):
    """A refusal with a closed-set code — refusal-as-data, never silent."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"output refused [{code}]: {detail}")


def _escaped(code: int) -> str:
    """Visible ASCII spelling of one forbidden code point (never dropped)."""
    if code <= 0xFF:
        return f"\\x{code:02x}"
    return f"\\u{code:04x}"


def scrub(text: str) -> str:
    """Escape every forbidden code point of one line as visible ASCII.

    Pure and total: a character is either preserved unchanged (allowed
    code point) or replaced by its visible escape spelling (forbidden code
    point). Nothing is dropped, so the result is never empty for a
    non-empty input and never shorter than its input.
    """
    return "".join(
        _escaped(ord(char)) if ord(char) in FORBIDDEN else char for char in text
    )


def _guard(safe: str) -> str:
    """Fail-closed post-condition: refuse a result that is still unsafe."""
    offenders = sum(1 for char in safe if ord(char) in FORBIDDEN)
    if offenders:
        raise OutputRefused(
            "CONTROL_BYTES",
            f"{offenders} forbidden code point(s) survived scrubbing",
        )
    return safe


def emit_lines(lines: Iterable[str], *, file: TextIO | None = None) -> None:
    """Write scrubbed lines to the operator's terminal, joined by newlines.

    Each element is treated as ONE line: its own control code points are
    escaped first, so the only newlines in the output are the ones this
    function inserts between elements.
    """
    safe = "\n".join(_guard(scrub(line)) for line in lines)
    print(safe, file=file)


def emit(line: str, *, file: TextIO | None = None) -> None:
    """Write one scrubbed line (plus its newline) to the terminal.

    `file` defaults to `sys.stdout` at call time, exactly like `print`.
    """
    emit_lines((line,), file=file)


def emit_refusal(*, file: TextIO | None = None) -> None:
    """Write the fixed refusal line — static text, safe by construction."""
    emit(REFUSAL_TEXT, file=file or sys.stderr)


def run_boundary(dispatch: Callable[[], int]) -> int:
    """Run one CLI dispatch under the boundary.

    A refusal anywhere inside `dispatch` (a line that could not be proven
    safe) is surfaced as the fixed refusal line on stderr plus a nonzero
    exit status — never as raw terminal bytes and never as a traceback.
    """
    try:
        return dispatch()
    except OutputRefused:
        emit_refusal()
        return 1
