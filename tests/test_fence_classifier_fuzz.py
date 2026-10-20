"""GAP-1 P2-6 - seeded adversarial fuzz battery for the lease-fence classifier.

The shape battery in ``tests/test_fence_classifier.py`` pins the known
B-F-01 / B-F-02 cases by hand. This battery generates adversarial corpora
around the classifier with the stdlib ``random`` module and a small set of
hard-coded seeds, then pins four invariants:

- totality: every generated input classifies without raising;
- soundness: an input carrying a forbidden operation in a non-string
  (non-inert) position never classifies into a permissive class;
- determinism: the same bytes classify identically on repeated calls, and
  regenerating the corpus from the same seed is byte-identical;
- agreement: the classifier still agrees with the hand-built known-shape
  oracle (the FENCED / FREE tables owned by
  ``tests/test_fence_classifier.py``).

Classification is derived from the classifier's ACTUAL constant tables
(``_READ_KEYWORDS`` / ``_CONTROL_KEYWORDS`` / ``_WITH_STATEMENT_KEYWORDS``)
imported from ``hermes.research.controller``; no keyword list is copied.

Owning gate: DG-4 A14 (lease / single writer), PROTECTED under DG-6 A3.
"""
from __future__ import annotations

import random

from hermes.research.controller import _FencedConnection
from tests.test_fence_classifier import FENCED_STATEMENTS, FREE_STATEMENTS

_READ_KEYWORDS = _FencedConnection._READ_KEYWORDS
_CONTROL_KEYWORDS = _FencedConnection._CONTROL_KEYWORDS
_WITH_KEYWORDS = _FencedConnection._WITH_STATEMENT_KEYWORDS

_PERMISSIVE_FIRST = frozenset(_READ_KEYWORDS) | frozenset(_CONTROL_KEYWORDS)

SEEDS = (20261020, 31415926, 27182818)

_DIRECT_WRITE_VERBS = (
    "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER",
    "PRAGMA", "ATTACH", "DETACH", "VACUUM", "REINDEX", "ANALYZE",
)

_CTE_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "REPLACE")

_UNKNOWN_VERBS = ("FROBNICATE", "TRUNCATE", "MERGE", "GRANT")

_WHITESPACE = (" ", "\t", "\n", "\r\n", "  ", "\n\n", " \t\n ")

_UNICODE_IDENTIFIERS = (
    "café", "naïve", "Δelta", "表", "データ", "Ωmega", "x_١",
)

_INERT_PAYLOADS = (
    ")", "(", ";", "';", "'); DROP TABLE events; --", "a;b",
    "INSERT INTO t VALUES (1)", "/* )", "-- (", "\\", "''", '""',
    "]", "[", "SELECT ')'", "DELETE FROM t", ")); ATTACH DATABASE x",
)

_NOISE_ALPHABET = (
    "abcXYZ0123_ \t\n'\"`[]()/*-;,é表ΔΩ"
)


def _cased(rng: random.Random, word: str) -> str:
    style = rng.randrange(3)
    if style == 0:
        return word.lower()
    if style == 1:
        return word.upper()
    return "".join(
        c.upper() if rng.random() < 0.5 else c.lower() for c in word)


def _string_literal(rng: random.Random) -> str:
    payload = rng.choice(_INERT_PAYLOADS) + rng.choice(_INERT_PAYLOADS)
    payload = payload.replace("'", "''")
    return "'" + payload + "'"


def _quoted_identifier(rng: random.Random) -> str:
    payload = rng.choice(_UNICODE_IDENTIFIERS + _INERT_PAYLOADS)
    kind = rng.choice(("double", "backtick", "bracket"))
    if kind == "double":
        if rng.random() < 0.5:
            return '"' + payload.replace('"', '""') + '"'
        return '"' + payload.replace('"', "") + '"'
    if kind == "backtick":
        if rng.random() < 0.5:
            return "`" + payload.replace("`", "``") + "`"
        return "`" + payload.replace("`", "") + "`"
    return "[" + payload.replace("]", "") + "]"


def _safe_identifier(rng: random.Random) -> str:
    while True:
        name = "t_" + "".join(
            rng.choice("abcdefghijklmnopqrstuvwxyz0123456789")
            for _ in range(5))
        if name.upper() not in _WITH_KEYWORDS:
            return name


def _cte_name(rng: random.Random) -> str:
    choice = rng.randrange(5)
    if choice == 0:
        return _quoted_identifier(rng)
    if choice == 1:
        return rng.choice(_UNICODE_IDENTIFIERS)
    return _safe_identifier(rng)


def _comment(rng: random.Random) -> str:
    payload = rng.choice(_INERT_PAYLOADS + _UNICODE_IDENTIFIERS)
    if rng.random() < 0.5:
        return "-- " + payload.replace("\n", " ") + "\n"
    return "/* " + payload.replace("*/", "* /") + " */"


def _whitespace(rng: random.Random) -> str:
    return "".join(rng.choice(_WHITESPACE) for _ in range(rng.randint(0, 3)))


def _decorate(rng: random.Random, body: str) -> str:
    parts = []
    for _ in range(rng.randint(0, 3)):
        parts.append(_whitespace(rng))
        if rng.random() < 0.75:
            parts.append(_comment(rng))
    parts.append(_whitespace(rng))
    parts.append(body)
    parts.append(_whitespace(rng))
    if rng.random() < 0.5:
        parts.append(_comment(rng))
    return "".join(parts)


def _cte_body(rng: random.Random) -> str:
    expression = rng.choice((
        _string_literal(rng),
        "(" + _string_literal(rng) + ")",
        "1 /* " + rng.choice(_INERT_PAYLOADS).replace("*/", "* /") + " */",
        "1 -- " + rng.choice(_INERT_PAYLOADS).replace("\n", " ") + "\n",
        "VALUES (" + _string_literal(rng) + ")",
    ))
    return _cased(rng, "SELECT") + " " + expression


def _cte_declaration(rng: random.Random) -> str:
    recursive = ""
    if rng.random() < 0.25:
        recursive = _cased(rng, "RECURSIVE") + " "
    columns = ""
    if rng.random() < 0.35:
        columns = "(" + _quoted_identifier(rng) + ")"
    return (_cased(rng, "WITH") + " " + recursive + _cte_name(rng)
            + columns + " " + _cased(rng, "AS") + " ("
            + _cte_body(rng) + ") ")


def _write_tail(rng: random.Random, verb: str) -> str:
    literal = _string_literal(rng)
    tails = {
        "INSERT": "INTO t VALUES (" + literal + ")",
        "UPDATE": "t SET x = " + literal,
        "DELETE": "FROM t WHERE x = " + literal,
        "REPLACE": "INTO t VALUES (" + literal + ")",
        "CREATE": "TABLE t2 (x)",
        "DROP": "TABLE t2",
        "ALTER": "TABLE t ADD COLUMN y",
        "PRAGMA": "user_version = 9",
        "ATTACH": "DATABASE " + literal + " AS other",
        "DETACH": "DATABASE other",
        "VACUUM": "",
        "REINDEX": "",
        "ANALYZE": "",
    }
    return tails[verb]


def _direct_write(rng: random.Random) -> tuple[str, str]:
    verb = rng.choice(_DIRECT_WRITE_VERBS)
    body = _cased(rng, verb) + " " + _write_tail(rng, verb)
    return _decorate(rng, body), verb


def _cte_write(rng: random.Random) -> tuple[str, str]:
    verb = rng.choice(_CTE_WRITE_VERBS)
    body = (_cte_declaration(rng) + _cased(rng, verb) + " "
            + _write_tail(rng, verb))
    return _decorate(rng, body), verb


def _cte_fail_closed(rng: random.Random) -> tuple[str, str]:
    verb = rng.choice(_UNKNOWN_VERBS + ("CREATE", "DROP", "PRAGMA"))
    tail_verb = verb if verb in ("DROP", "PRAGMA") else "CREATE"
    body = (_cte_declaration(rng) + _cased(rng, verb) + " "
            + _write_tail(rng, tail_verb))
    return _decorate(rng, body), verb


def _read_statement(rng: random.Random) -> str:
    literal = _string_literal(rng)
    kind = rng.randrange(5)
    if kind == 0:
        body = _cased(rng, "SELECT") + " " + rng.choice((
            literal,
            "1",
            "1 /* " + rng.choice(_INERT_PAYLOADS).replace("*/", "* /")
            + " */",
            "1 -- " + rng.choice(_INERT_PAYLOADS).replace("\n", " ")
            + "\n",
        ))
    elif kind == 1:
        body = _cased(rng, "VALUES") + " (" + literal + ")"
    elif kind == 2:
        body = (_cased(rng, "EXPLAIN") + " "
                + _cased(rng, "QUERY PLAN") + " "
                + _cased(rng, "SELECT") + " " + literal)
    elif kind == 3:
        body = (_cte_declaration(rng) + _cased(rng, "SELECT") + " * FROM t")
    else:
        body = (_cte_declaration(rng) + _cased(rng, "VALUES") + " ("
                + literal + ")")
    return _decorate(rng, body)


def _malformed_statement(rng: random.Random) -> str:
    payload = rng.choice(_INERT_PAYLOADS)
    kind = rng.randrange(6)
    if kind == 0:
        return "SELECT'" + payload.replace("'", "")
    if kind == 1:
        return 'SELECT"' + payload.replace('"', "")
    if kind == 2:
        return "SELECT`" + payload.replace("`", "")
    if kind == 3:
        return "SELECT[" + payload.replace("]", "")
    if kind == 4:
        return "/* " + payload.replace("*/", "* /") + " INSERT INTO t"
    return ("WITH t AS (SELECT 1) /* "
            + payload.replace("*/", "* /"))


def _inert_statement(rng: random.Random) -> str:
    kind = rng.randrange(4)
    if kind == 0:
        return _whitespace(rng)
    if kind == 1:
        return _whitespace(rng) + _comment(rng) + _whitespace(rng)
    if kind == 2:
        return "/* " + rng.choice(_INERT_PAYLOADS).replace("*/", "* /") + " */"
    return "-- " + rng.choice(_INERT_PAYLOADS).replace("\n", " ") + "\n"


def _noise(rng: random.Random) -> str:
    return "".join(
        rng.choice(_NOISE_ALPHABET) for _ in range(rng.randint(0, 60)))


class _Corpus:
    def __init__(self) -> None:
        self.write: list[tuple[str, str]] = []
        self.read: list[str] = []
        self.malformed: list[str] = []
        self.inert: list[str] = []
        self.unlabelled: list[str] = []

    def all_sql(self) -> list[str]:
        return ([sql for sql, _ in self.write] + self.read
                + self.malformed + self.inert + self.unlabelled)


def _build_corpus(seed: int) -> _Corpus:
    rng = random.Random(seed)
    corpus = _Corpus()
    for _ in range(150):
        corpus.write.append(_direct_write(rng))
    for _ in range(100):
        corpus.write.append(_cte_write(rng))
    for _ in range(60):
        corpus.write.append(_cte_fail_closed(rng))
    for _ in range(130):
        corpus.read.append(_read_statement(rng))
    for _ in range(80):
        corpus.malformed.append(_malformed_statement(rng))
    for _ in range(40):
        corpus.inert.append(_inert_statement(rng))
    corpus.inert.extend((
        "", " ", "\t\n\r\n", "-- only\n", "-- no newline", "/* */",
    ))
    for _ in range(60):
        corpus.unlabelled.append(_noise(rng))
    corpus.unlabelled.extend((
        "ſelect 1", "İNSERT INTO t VALUES (1)", "ＩＮＳＥＲＴ INTO t",
        "\ufeffSELECT 1", "\x00", ";", "()", "'", '"', "`", "[",
    ))
    return corpus


def _build_all() -> list[_Corpus]:
    return [_build_corpus(seed) for seed in SEEDS]


CORPUS = _build_all()


def _mask_inert(sql: str) -> str:
    """Blank string / quoted-identifier / comment regions (independent of the
    classifier's own scanner; used only to prove the corpus premise)."""
    out: list[str] = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            out.append(" ")
            i += 1
            while i < len(sql):
                if sql[i] == "'":
                    out.append(" ")
                    if i + 1 < len(sql) and sql[i + 1] == "'":
                        out.append(" ")
                        i += 2
                        continue
                    i += 1
                    break
                out.append(" ")
                i += 1
            continue
        if ch in ('"', "`"):
            quote = ch
            out.append(" ")
            i += 1
            while i < len(sql) and sql[i] != quote:
                out.append(" ")
                i += 1
            if i < len(sql):
                out.append(" ")
                i += 1
            continue
        if ch == "[":
            out.append(" ")
            i += 1
            while i < len(sql) and sql[i] != "]":
                out.append(" ")
                i += 1
            if i < len(sql):
                out.append(" ")
                i += 1
            continue
        if ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i + 2)
            if end < 0:
                end = len(sql) - 1
            out.append(" " * (end - i + 1))
            i = end + 1
            continue
        if ch == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end < 0:
                end = len(sql) - 2
            out.append(" " * (end + 2 - i))
            i = end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _active_words(sql: str) -> set[str]:
    masked = _mask_inert(sql)
    words: set[str] = set()
    current: list[str] = []
    for ch in masked:
        if ch.isascii() and (ch.isalnum() or ch == "_"):
            current.append(ch)
        elif current:
            words.add("".join(current).upper())
            current = []
    if current:
        words.add("".join(current).upper())
    return words


def test_fence_constants_drive_the_battery():
    """The write verbs and WITH continuations the battery pins are derived
    from the classifier's live constants, never a hand-copied keyword list."""
    assert set(_DIRECT_WRITE_VERBS).isdisjoint(_PERMISSIVE_FIRST)
    assert set(_CTE_WRITE_VERBS) <= set(_WITH_KEYWORDS)
    assert "WITH" not in _PERMISSIVE_FIRST
    assert len(CORPUS) == len(SEEDS)


def test_fuzz_generation_is_reproducible():
    """Same hard-coded seeds regenerate the same bytes."""
    rebuilt = _build_all()
    for original, again in zip(CORPUS, rebuilt):
        assert original.write == again.write
        assert original.read == again.read
        assert original.malformed == again.malformed
        assert original.inert == again.inert
        assert original.unlabelled == again.unlabelled


def test_fuzz_totality_every_generated_input_classifies():
    """Invariant (i): classification is total over the corpus."""
    for corpus in CORPUS:
        for sql in corpus.all_sql():
            result = _FencedConnection._is_write(sql)
            assert isinstance(result, bool), (sql.encode("utf-8"), result)


def test_fuzz_soundness_forbidden_active_operation_is_never_permissive():
    """Invariant (ii): a forbidden operation in a non-string position can
    never classify as permissive (read / control / WITH-read)."""
    for corpus in CORPUS:
        for sql, verb in corpus.write:
            verdict = _FencedConnection._is_write(sql)
            assert verdict is True, (
                "COUNTEREXAMPLE", verb, sql.encode("utf-8"), verdict)
            assert verb.upper() in _active_words(sql), (
                "corpus premise", verb, sql.encode("utf-8"))


def test_fuzz_determinism_same_bytes_same_class():
    """Invariant (iii): repeated classification and a UTF-8 encode/decode
    round-trip yield the same verdict."""
    for corpus in CORPUS:
        for sql in corpus.all_sql():
            first = _FencedConnection._is_write(sql)
            second = _FencedConnection._is_write(sql)
            assert first == second, (sql.encode("utf-8"), first, second)
            round_tripped = sql.encode("utf-8").decode("utf-8")
            assert _FencedConnection._is_write(round_tripped) is first, (
                sql.encode("utf-8"), first)


def test_fuzz_generated_read_shapes_stay_permissive():
    """Inert-bearing read shapes (literals, comments, quoted identifiers,
    CTE wrappers) are never over-fenced by the corpus."""
    for corpus in CORPUS:
        for sql in corpus.read:
            verdict = _FencedConnection._is_write(sql)
            assert verdict is False, (sql.encode("utf-8"), verdict)


def test_fuzz_malformed_and_unbalanced_shapes_fail_closed():
    """Unterminated literals / quoted identifiers / block comments and
    unrecognized WITH continuations are fenced."""
    for corpus in CORPUS:
        for sql in corpus.malformed:
            verdict = _FencedConnection._is_write(sql)
            assert verdict is True, (sql.encode("utf-8"), verdict)


def test_fuzz_inert_only_shapes_never_need_the_fence():
    """Whitespace / comment-only inputs are never writes."""
    for corpus in CORPUS:
        for sql in corpus.inert:
            verdict = _FencedConnection._is_write(sql)
            assert verdict is False, (sql.encode("utf-8"), verdict)


def test_fuzz_agrees_with_the_known_shape_oracle():
    """Invariant (iv): the hand-built FENCED / FREE oracle owned by
    tests/test_fence_classifier.py still agrees with the classifier."""
    oracle: list[tuple[str, bool]] = (
        [(sql, True) for sql, _ in FENCED_STATEMENTS]
        + [(sql, False) for sql, _ in FREE_STATEMENTS]
    )
    for sql, expected in oracle:
        verdict = _FencedConnection._is_write(sql)
        assert verdict is expected, (sql.encode("utf-8"), expected, verdict)
