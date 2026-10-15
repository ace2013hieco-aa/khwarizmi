"""EXT-5 / triage R3 — the operator-output boundary, primitive level.

Pins the rule itself: a forbidden code point (C0, DEL, C1, or a
bidirectional override) becomes its visible ASCII spelling, every other
code point is preserved unchanged, nothing is dropped or truncated, and a
line that survives scrubbing is refused rather than written.

Prohibited-claims discipline: these tests pin a display transform. They
make no claim about the validity of any displayed content.
"""
from __future__ import annotations

import io

import pytest

from hermes import output
from hermes.output import (
    FORBIDDEN,
    REFUSAL_TEXT,
    OutputRefused,
    emit,
    emit_lines,
    run_boundary,
    scrub,
)

ESC = "\x1b"
BEL = "\x07"

# Allowed code points the CLI itself emits or a legitimate value may carry:
# ASCII printable, the CLI's em-dash, accented/arrow/CJK/emoji text, and the
# Cf characters deliberately left alone (ZWJ, soft hyphen).
_ALLOWED = ["a", "Z", "9", " ", "-", "—", "é", "→", "中", "🙂", "\u200d",
            "\u00ad"]


def _has_forbidden(text: str) -> bool:
    """True when a single line (or string) carries a forbidden code point."""
    return any(ord(char) in FORBIDDEN for char in text)


def _decode(text: str) -> str:
    """Test-local inverse of the escape spellings (proof aid only)."""
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text) and text[index + 1] in "xu":
            width = 2 if text[index + 1] == "x" else 4
            digits = text[index + 2:index + 2 + width]
            if len(digits) == width:
                out.append(chr(int(digits, 16)))
                index += 2 + width
                continue
        out.append(char)
        index += 1
    return "".join(out)


# ── the escaping rule: one code point at a time ──

@pytest.mark.parametrize("code", sorted(FORBIDDEN))
def test_every_forbidden_code_point_gets_a_visible_reversible_escape(
        code: int) -> None:
    char = chr(code)
    escaped = scrub(char)
    assert escaped != char
    assert escaped.startswith(("\\x", "\\u"))
    assert escaped.isascii()
    assert chr(int(escaped[2:], 16)) == char


def test_arabic_letter_mark_is_escaped_like_its_bidi_siblings() -> None:
    """EXT-5-FIX: U+061C (ALM) is Bidi_Control — escaped, never preserved.

    The audit found ALM passing `scrub()` raw while LRM (U+200E) was
    escaped; this pins the hole closed at the primitive level.
    """
    assert 0x061C in FORBIDDEN
    assert scrub(chr(0x061C)) == "\\u061c"


def test_the_bidi_set_is_the_full_bidi_control_inventory() -> None:
    """The covered set is exactly the 12 Unicode Bidi_Control code points.

    ALM/LRM/RLM, the LRE/RLE/PDF/LRO/RLO embeddings+overrides, and the
    LRI/RLI/FSI/PDI isolates — no member missing, no non-Bidi_Control
    member added. ZWSP/ZWNBSP/ZWJ (Cf, invisible but not direction-
    spoofing) are deliberately outside this set.
    """
    expected = sorted({0x061C, 0x200E, 0x200F,
                       0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
                       0x2066, 0x2067, 0x2068, 0x2069})
    assert sorted(output._BIDI_OVERRIDES) == expected


@pytest.mark.parametrize("char", _ALLOWED)
def test_allowed_code_points_are_preserved_exactly(char: str) -> None:
    """The boundary must not mangle ordinary text (em-dash, ZWJ, emoji)."""
    assert scrub(char) == char


def test_scrub_is_a_pure_per_code_point_map() -> None:
    """No hidden state and no context: the whole is the sum of its parts."""
    corpus = "".join(
        chr(code) for code in range(0x00, 0x300)) + "\u202e\U0001f642"
    assert scrub(corpus) == "".join(scrub(char) for char in corpus)


def test_scrub_never_drops_or_truncates_a_code_point() -> None:
    """Lossless: escaping is longer-or-equal and fully reversible."""
    corpus = "".join(chr(code) for code in range(0x00, 0x300)) + \
        f"{ESC}[31mRED{BEL}\nforged"
    escaped = scrub(corpus)
    assert not _has_forbidden(escaped)
    assert len(escaped) >= len(corpus)
    assert _decode(escaped) == corpus


def test_the_boundary_never_creates_a_control_byte() -> None:
    """A literal escape spelling in data stays literal — never an ESC byte."""
    for text in [r"\x1b", r"\u202e", "\\", r"1\x07", ESC * 3, "\x9b31m"]:
        assert not _has_forbidden(scrub(text))
    assert scrub(r"\x1b") == r"\x1b"


# ── the emit primitives ──

def test_emit_writes_one_scrubbed_line_and_its_newline() -> None:
    stream = io.StringIO()
    emit(f"a{ESC}[31mb", file=stream)
    assert stream.getvalue() == "a\\x1b[31mb\n"


def test_emit_lines_keeps_structure_and_escapes_a_data_newline() -> None:
    """Structure is the caller's; a newline inside ONE line is data."""
    stream = io.StringIO()
    emit_lines(["one", "two"], file=stream)
    assert stream.getvalue() == "one\ntwo\n"

    stream = io.StringIO()
    emit_lines(["data\nforged", "trailing\r"], file=stream)
    assert stream.getvalue() == "data\\x0aforged\ntrailing\\x0d\n"


def test_emit_refuses_rather_than_writing_an_unproven_line(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed: a line that survives scrubbing is refused, not written."""
    monkeypatch.setattr(output, "scrub", lambda text: text)
    stream = io.StringIO()
    with pytest.raises(OutputRefused) as excinfo:
        emit(f"raw {ESC}[31m", file=stream)
    assert excinfo.value.code == "CONTROL_BYTES"
    assert stream.getvalue() == ""  # nothing raw reached the stream


def test_run_boundary_turns_a_refusal_into_a_loud_nonzero_exit(
        capsys: pytest.CaptureFixture[str]) -> None:
    def dispatch() -> int:
        raise OutputRefused("CONTROL_BYTES", "planted")

    assert run_boundary(dispatch) == 1
    captured = capsys.readouterr()
    assert REFUSAL_TEXT in captured.err
    assert captured.out == ""
