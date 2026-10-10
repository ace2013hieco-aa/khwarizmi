r"""Advisory corpus memory pack (O4 — NEW, advisory only, not wired).

A per-turn, token-budgeted recall/fetch/store triple over the governed
corpus, assembled for ONE project. Clean-room, deterministic: the same
corpus state plus the same budget yields byte-identical pack bytes
(pinned by ``tests/test_corpus_pack.py``, including a 100x loop).

The triple, against ``corpus.py`` reads (never raw file reads):

- ``recall`` — choose governed refs (closed membership; default: all
  twelve). Sorting + dedup make the choice deterministic.
- ``fetch_pack_docs`` — load bytes through ``load_corpus_bytes``,
  inheriting its closed membership, traversal guard, size cap, and
  EOL-stable identity. Reads disk; writes nothing.
- ``assemble_pack`` — decode (strict UTF-8), pre-egress secret scrub,
  token-budgeted inclusion with per-item citations, in-memory only.

ADVISORY ONLY (structural, not promissory):

- pack citations use the ``pack:<project>:<hash>`` family, which no
  resolver recognizes: presented to the classification resolver, the
  detector resolver (both paths), or L2, a pack citation resolves to
  nothing (fail-safe skip). Packs never enter a gate predicate.
- assembly performs zero durable writes: no journal supplement, no
  stored-row override — the module imports no repository and opens
  no transaction (it reads through ``corpus.py`` only).
- every item and citation is project-bound at assembly; presenting a
  pack or citation to another project refuses
  ``EVIDENCE_DOES_NOT_RESOLVE`` (cross-project citations fail closed).

Pre-egress secret scrub reuses the provider redaction discipline
(``hermes.tools.providers.redact.DEFAULT_POLICY`` — the same import
``source_handlers.py:55`` already makes) and mirrors the rest of it:
credential-alias ``key=value``/``key: value`` assignment masking (exact
or separator-suffixed keys, so ``monkey=banana`` is NOT masked),
fold-tolerant credential HEADERS (an obs-fold continuation line
supplies the value: ``Authorization:`` followed by an indented
``Bearer …`` is one credential, while a bare newline is still a hard
delimiter — the tolerance is scoped to the header form on purpose, see
the boundary note), quoted-key assignment masking for
the JSON shape a separator class cannot reach (``"api_key": …`` —
quote style, key text, and separator spacing preserved byte-for-byte,
with backslash-escaped quotes read as quotes so a JSON document nested
in a JSON string cannot pass), a structural sibling-split rule (a
mapping whose ``key``/``name``/``type``/``field`` value is a credential
ALIAS masks the string in a sibling ``value``/``secret``/``token``/
``password`` field — whole-value, shape-independent, and always; see the
rule's contract), credential-class header masking (the
PS-09 names mirrored from ``redact._CREDENTIAL_HEADERS``:
``Authorization``, ``Set-Cookie`` and the other two — scheme and
credentials masked together, never just the key), polite-identifier
masking in the ``<redacted:name>`` form, plus standalone secret-value
shapes whose authority is the S6 secret scanner
(``persistence/event_validation.py`` — cited, shapes mirrored,
not imported). Bare unknown secrets are out of scope (the same honest
limit the S6 scanner documents).

THREE SCRUB MECHANISMS ARE CLASS RULES, NOT INSTANCE RULES (O4_FIX3).
Each replaces a spelling-specific pattern with a mechanism that closes
the whole family it belongs to, and each is pinned by the family
rather than by the spelling that first exposed it:

- DECODE-THEN-SCAN. Before any shape or key/value rule runs, the text
  is passed through a bounded JSON-unescape: each escape is decoded
  through ``json.loads`` on a quoted form, the pass is repeated to a
  fixpoint, it runs at most three times, and an escape the grammar
  does not name is left exactly as written (a decode never guesses).
  Every pass yields a new LAYER of the same text and each layer records
  where every one of its characters came from, so the EXISTING shape and
  key/value rules run on every layer output and a mask found on any of
  them is applied to the bytes that spelled the secret. One pass
  removes one level of escaping — ``\\\\"`` becomes ``\\"``, ``\\"``
  becomes ``\"``, ``\"`` becomes ``"`` — so three passes reach a secret
  spelled through three levels of JSON string quoting; a fourth level
  is outside the bound and is a stated residual, not a silent hole.
  The layer set is bounded by character count as well as by depth
  (``_STRUCTURED_SCAN_MAX_CHARS``).
- STRUCTURAL WALK. When the text is a single well-formed JSON document
  (``json.loads`` accepts it), the sibling-split rule is applied to the
  PARSED object tree, recursively at every object level: a declarator
  member pairs with the value members of its own object, and when its
  own object has no value member it pairs with the value members of the
  nearest descendant object that does — so a declarator nested deeper
  than its value, and a value carried by a bridging member, are both
  one credential. O4_FIX4 extends the reach LATERALLY: an object the
  descent leaves unpaired also pairs with its SIBLING objects —
  children of the same parent, array elements included — in document
  order, first unpaired declarator with first unpaired value field,
  each side pairing once; the reach never crosses the document, so two
  separate roots stay unpaired (pinned). When the text is not a JSON
  document the rule falls back to the text scan, whose sibling
  transition carries the same lateral reach: one closing+opening brace
  pair at the declarator's own depth is crossed, a deeper imbalance
  ends the pairing.
- SEPARATOR NORMALIZATION. Before the fold scan, every line-separator
  spelling (CRLF, lone CR, vertical tab, form feed) is folded to a
  single LF by ONE function (``_normalize_separators``), so a fold
  written with a classic-Mac CR is the same credential as one written
  with LF. The fold span is still matched on the ORIGINAL bytes: the
  mask is written back through the normalization map, so prose that
  merely wraps stays byte-identical. A BLANK LINE IS STILL A HARD
  DELIMITER — folding makes CRLF followed by an empty line the same as
  LF followed by an empty line, and no grammar unfolds across an empty
  line, so ``"Authorization:\n\nBearer X"`` does NOT merge (pinned).

Three boundaries are stated rather than implied, and all three are
pinned:
(1) a JWT is masked in its dotted ``eyJ…`` form — the
``header.payload.signature`` tri-segment shape and its
``header.payload`` prefix — while a lone ``eyJ…`` fragment with no dot
carries no payload or signature segment and is left alone; (2) a
complete PEM block is masked whole, and a
``-----BEGIN … PRIVATE KEY-----`` header with no END line is masked
wherever it appears (S6's value pattern is the header line alone),
together with any base64-only lines that immediately follow it; (3)
the fold tolerance is span matching on the ORIGINAL text (never a
normalized copy), so prose that merely wraps stays byte-identical and a
bare newline still delimits — and it is scoped to the header form: an
assignment-side fold sweep wrote over ordinary governed code (the
``INSERT_TASK`` block in ``docs/idr/IDR-028.md``, whose
``idempotency_key:`` line is followed by an indented object), so it was
removed; ``api_key:`` plus an indented value is already masked by the
plain assignment rule, and a same-line value with an indented
continuation is a recorded residual. Scrub
runs on the DECODED text, so undecodable bytes refuse instead of
passing through half-scrubbed (the ``redact_body`` decoded-only rule).

Token budgeting is a deterministic budgeting unit, explicitly NOT a
model-token claim (prohibited-claims discipline): one token per four
characters (ceiling). The budget bounds what ships; oversized items
are SKIPPED with an exact reason, never truncated silently and never
a refusal (a pack that fits nothing is an empty pack, not an error).

Refusals use the FROZEN vocabulary only (mirrored, never extended):

- ``MALFORMED_PAYLOAD`` (``research/gateway.py:110``) — bad project,
  unknown ref/strategy input, non-bytes, undecodable text, malformed
  citation, budget that is not a positive int;
- ``RATIONALE`` (``research/controller.py:1803``) — a listed corpus
  record absent on disk (the required record is missing), emitted as
  the controller's inline literal: no module binds the name
  (capability-plane ownership rule);
- ``EVIDENCE_DOES_NOT_RESOLVE``
  (``methodology/substrate.py:206``) — cross-project pack/citation
  presentation.

Integration: NOT wired anywhere in this slice. Entry points are
:func:`recall` / :func:`fetch_pack_docs` / :func:`assemble_pack`
plus :func:`pack_bytes`; there is no call site outside this module
and its test (pinned by the no-wire test).

Three scrub limits are RECORDED rather than implied (O4_FIX3), and none
of them is a rule-shaped miss:

- BARE UNKNOWN SECRETS. A secret with no credential NAME and no
  recognized VALUE shape is not masked, exactly as the S6 scanner this
  module cites documents for itself. MEASURED: over the 50-spelling
  battery pinned in ``tests/test_corpus_pack.py`` — 41 spellings the
  module claims (credential-alias assignments, quoted-key assignments,
  escaped JSON at every depth, credential-class headers, obs-folded
  headers, sibling splits, and the standalone value shapes) plus 9
  bare-unknown secrets with neither a name nor a shape — the scrub masks
  41 of 50, i.e. 82%. Every survivor is a bare unknown BY CONSTRUCTION:
  a rule wide enough to catch a secret that carries neither a name nor a
  shape has to mask ordinary data, which the over-masking discipline
  forbids. The number is pinned, so a rule change that silently widens
  (or narrows) the limit has to be a decision.
- SPLIT-SECRET REASSEMBLY. A secret spelled in two or more pieces that
  no rule the module owns joins (``"sec"`` beside ``"ret"``) is OUT OF
  CONTRACT: no rule reassembles fragments, and none is planned. The
  decode and normalization mechanisms remove ESCAPING and SEPARATOR
  spelling, never content, so they cannot manufacture an adjacency that
  the bytes do not carry.
- APOSTROPHE PAIRING MISSES IN THE SAFE DIRECTION. The structural scan
  is string-aware and a prose apostrophe can open a spurious string,
  which can only make a candidate look OUTSIDE its object — a missed
  mask, never a mask on the wrong object. Miss, never wrong-object
  mask: the failure is stated in exactly that direction.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from hermes.research.corpus import (
    GOVERNED_CORPUS_REFS,
    CorpusDraftError,
    load_corpus_bytes,
)
from hermes.research.programs import canonical_json, sha256_hex
from hermes.tools.providers.redact import DEFAULT_POLICY

__all__ = [
    "ADVISORY_CONSUMPTION",
    "CORPUS_PACK_KIND",
    "DEFAULT_PACK_BUDGET_TOKENS",
    "EVIDENCE_DOES_NOT_RESOLVE",
    "FROZEN_PACK_REFUSAL_CODES",
    "MALFORMED_PAYLOAD",
    "PACK_AUTHORITY",
    "PACK_REF_PREFIX",
    "PACK_TOKEN_CHARS",
    "PACK_VERSION",
    "CorpusPack",
    "FetchedDoc",
    "PackItem",
    "PackRefusal",
    "SkippedRef",
    "assemble_pack",
    "check_pack_partition",
    "check_pack_project",
    "estimate_tokens",
    "fetch_pack_docs",
    "make_citation",
    "pack_bytes",
    "pack_id",
    "pack_mapping",
    "recall",
    "scrub_pack_text",
]

# ── frozen refusal vocabulary (mirrored, never extended) ──

#: Schema violation or unknown key — research/gateway.py:110.
MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"
#: Cited artifact does not resolve in-project — methodology/substrate.py:206.
EVIDENCE_DOES_NOT_RESOLVE = "EVIDENCE_DOES_NOT_RESOLVE"
# NOTE: no module-level RATIONALE binding exists on purpose. The
# capability plane certifies that no module under research/persistence/
# core owns a LOCK/RATIONALE constant (the controller emits them as
# inline literals) — so this plane emits the controller's "RATIONALE"
# literal at its one raise site instead of binding the name.

#: The only codes a pack refusal may carry.
FROZEN_PACK_REFUSAL_CODES: frozenset[str] = frozenset({
    EVIDENCE_DOES_NOT_RESOLVE,
    MALFORMED_PAYLOAD,
    "RATIONALE",
})

# ── pack identity ──

#: Pack format version (bump only with an explicit versioning decision).
PACK_VERSION = "1"
#: Citation family prefix — recognized by no resolver, by construction.
PACK_REF_PREFIX = "pack"
#: Advisory marker carried in every pack mapping.
ADVISORY_CONSUMPTION = "ADVISORY"
#: Authority marker: a pack is never authority for anything.
PACK_AUTHORITY = "NONE"
#: Kind tag carried per item (record-keeping only, never a gate input).
CORPUS_PACK_KIND = "corpus_pack_item"

# ── budgeting ──

#: Characters per budgeting token (ceiling). A budgeting unit, NOT a
#: model-token claim.
PACK_TOKEN_CHARS = 4
#: Default per-turn budget (tokens).
DEFAULT_PACK_BUDGET_TOKENS = 2000

#: Skip reasons (exact strings, pinned by tests).
REASON_ITEM_EXCEEDS_BUDGET = "item-exceeds-budget"
REASON_OVER_BUDGET = "over-budget"
REASON_DUPLICATE_REF = "duplicate-ref"


class PackRefusal(Exception):
    """Fail-closed refusal carrying a FROZEN code (never a new code)."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in FROZEN_PACK_REFUSAL_CODES:
            raise ValueError(f"unknown pack refusal code {code!r}")
        self.code = code
        self.detail = detail
        super().__init__(f"pack refused ({code}): {detail}")

    def to_refusal(self) -> dict[str, object]:
        """Refusal-as-data shape (rejected / code / detail)."""
        return {"rejected": True, "code": self.code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class FetchedDoc:
    """One fetched corpus document: ref + raw bytes as loaded."""

    corpus_ref: str
    content: bytes


@dataclass(frozen=True, slots=True)
class PackItem:
    """One packed item: scrubbed excerpt + citation + exact sizes."""

    project_id: str
    corpus_ref: str
    source_hash: str
    citation: str
    tokens: int
    excerpt: str


@dataclass(frozen=True, slots=True)
class SkippedRef:
    """A ref that did not fit the budget (exact reason, never silent)."""

    corpus_ref: str
    tokens_needed: int
    reason: str


@dataclass(frozen=True, slots=True)
class CorpusPack:
    """An assembled advisory pack (in-memory; writes nothing)."""

    version: str
    project_id: str
    budget_tokens: int
    used_tokens: int
    items: tuple[PackItem, ...]
    skipped: tuple[SkippedRef, ...]


def _require_project(project_id: Any) -> str:
    if not isinstance(project_id, str) or not project_id:
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "project_id must be a non-empty string — refusing",
        )
    return project_id


def _require_budget(budget_tokens: Any) -> int:
    if (not isinstance(budget_tokens, int)
            or isinstance(budget_tokens, bool)
            or budget_tokens <= 0):
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "budget_tokens must be a positive int — refusing",
        )
    return budget_tokens


def estimate_tokens(text: str) -> int:
    """Deterministic budgeting units for ``text`` (ceiling over 4 chars).

    A budgeting unit, NOT a model-token claim. Empty text costs zero.
    """
    if not isinstance(text, str):
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "estimate_tokens needs text, "
            f"got {type(text).__name__} — refusing",
        )
    if text == "":
        return 0
    return (len(text) + PACK_TOKEN_CHARS - 1) // PACK_TOKEN_CHARS


def recall(
    project_id: str,
    refs: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Choose the governed refs to pack (recall step; reads nothing).

    Default: all twelve governed refs. Explicit refs are validated
    against ``GOVERNED_CORPUS_REFS`` — unlisted refs refuse instead of
    entering silently. Output is sorted and deduplicated.
    """
    _require_project(project_id)
    if refs is None:
        return tuple(sorted(GOVERNED_CORPUS_REFS))
    if isinstance(refs, str) or not isinstance(refs, Sequence):
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "refs must be a sequence of corpus refs — refusing",
        )
    chosen: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or ref not in GOVERNED_CORPUS_REFS:
            raise PackRefusal(
                MALFORMED_PAYLOAD,
                f"corpus ref {ref!r} is not governed — refusing "
                "(unlisted documents never enter a pack)",
            )
        if ref not in chosen:
            chosen.append(ref)
    return tuple(sorted(chosen))


def fetch_pack_docs(
    root: str | Path,
    project_id: str,
    refs: Sequence[str],
) -> tuple[FetchedDoc, ...]:
    """Load raw bytes for ``refs`` through ``load_corpus_bytes`` (fetch).

    Reads disk; writes nothing. Corpus-boundary errors normalize to
    pack refusals: unlisted/oversize/empty drafts refuse
    ``MALFORMED_PAYLOAD``; a listed record missing on disk refuses
    ``RATIONALE`` (the required record is absent).
    """
    _require_project(project_id)
    if not isinstance(root, (str, Path)):
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "corpus root must be a path — refusing",
        )
    if isinstance(refs, str) or not isinstance(refs, Sequence):
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "refs must be a sequence of corpus refs — refusing",
        )
    docs: list[FetchedDoc] = []
    for ref in refs:
        try:
            content = load_corpus_bytes(root, ref)
        except CorpusDraftError as exc:
            raise PackRefusal(
                MALFORMED_PAYLOAD,
                f"cannot fetch {ref!r}: {exc} — refusing",
            ) from None
        except FileNotFoundError:
            raise PackRefusal(
                "RATIONALE",  # controller literal, never a module constant
                f"corpus record {ref!r} is absent on disk — refusing",
            ) from None
        docs.append(FetchedDoc(corpus_ref=ref, content=content))
    return tuple(docs)


def _kv_rule(alias: str, replacement: str) -> tuple[re.Pattern[str], str]:
    """One key=value masking rule: exact or separator-suffixed keys.

    ``api_key=`` and ``x-api-key:`` match; ``monkey=`` does not (the
    optional prefix must end in a separator — substring matching would
    eat ordinary prose, the failure the suffix rule exists to stop). The
    returned replacement is the VALUE's replacement: the mask covers the
    separator and the value and is written back as ``=`` plus it, so the
    key keeps its bytes and the separator is normalized to ``=``.
    """
    pattern = re.compile(
        r"(?i)\b((?:[\w.-]+[-_.])?" + re.escape(alias) + r")"
        r"\s*[:=]\s*(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    )
    return (pattern, replacement)


_KV_CREDENTIAL_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    _kv_rule(alias, "<redacted>")
    for alias in sorted(DEFAULT_POLICY.credential_aliases)
)


#: A quote token: a quote character, optionally backslash-escaped. A JSON
#: document nested inside a JSON string escapes its quotes (``\"api_key\":
#: \"…\"``), so every quoted rule has to read an escaped quote as a quote —
#: otherwise the whole escaped document passes verbatim (O4_FIX2 leak 1).
_QUOTE_TOKEN = r"\\?[\"']"


def _quoted_kv_rule(alias: str, replacement: str) -> tuple[re.Pattern[str], str]:
    """One quoted-key masking rule: ``"api_key": <value>`` (JSON shape).

    ``_kv_rule`` needs the separator immediately after the key, so the
    *closing quote* of a JSON key defeats it — and a JSON document is the
    commonest corpus shape there is. Quote style, key text, and separator
    spacing survive byte-for-byte; only the value is masked (the returned
    replacement is the VALUE's replacement, and the mask covers the value
    group alone). A quote may be
    backslash-escaped (``\"api_key\": \"…\"`` — a JSON document nested in a
    JSON string) and the key's opening and closing quote must use the same
    escape form (``(?P=q)``). The unquoted value branch stops at a comma,
    semicolon, or brace, so neighbouring JSON members are never eaten.
    """
    pattern = re.compile(
        r"(?i)(?P<q>" + _QUOTE_TOKEN + r")(?P<key>(?:[\w.-]+[-_.])?"
        + re.escape(alias) + r")(?P=q)(?P<sep>\s*:\s*)"
        r"(?P<value>" + _QUOTE_TOKEN + r"[^\"']*" + _QUOTE_TOKEN
        + r"|[^\s,;{}]+)"
    )
    return (pattern, replacement)


_KV_QUOTED_CREDENTIAL_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    _quoted_kv_rule(alias, "<redacted>")
    for alias in sorted(DEFAULT_POLICY.credential_aliases)
)

_KV_POLITE_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    _kv_rule(alias, f"<redacted:{alias.lower()}>")
    for alias in sorted(DEFAULT_POLICY.polite_identifiers)
)


# ── decode-then-scan: bounded, origin-tracking JSON unescape ──

#: Bounded-work bound for the class mechanisms. Above it the decode layers
#: and the structural walk stand down (the text rules are linear and keep
#: running), so an overlong input costs one linear pass instead of four.
#: Set far above the corpus per-document cap (``corpus.py``
#: ``CORPUS_MAX_BYTES``, 20 KiB) so every governed document is always
#: structured-scanned; the degrade above it is graceful and pinned, never
#: silent.
_STRUCTURED_SCAN_MAX_CHARS = 1 << 20

#: One unescape pass removes one level of escaping, so three passes reach
#: a secret spelled through three levels of JSON string quoting.
_DECODE_MAX_PASSES = 3

#: A JSON escape sequence: the simple escapes plus the ``\uXXXX`` form.
_DECODE_ESCAPE_RE = re.compile(r'\\(?:["\'\\/bfnrt]|u[0-9a-fA-F]{4})')


def _decode_escape(sequence: str) -> str | None:
    """Decode one backslash escape through ``json.loads`` on a quoted form.

    Returns ``None`` when the sequence is not an escape the JSON grammar
    names — the caller then keeps the original bytes, because a decode
    never guesses (this is the "exceptions keep the original" half of
    the decode contract).
    """
    try:
        decoded = json.loads('"' + sequence + '"')
    except ValueError:
        return None
    if not isinstance(decoded, str) or not decoded:
        return None
    return decoded


@dataclass(frozen=True, slots=True)
class _Layer:
    """One view of the text plus where each of its characters came from.

    ``starts[i]`` is the index, in the ORIGINAL text, of the character
    that produced ``text[i]``; ``starts[len(text)]`` is ``len(original)``.
    The identity layer carries a ``range`` so the common case (nothing to
    decode, nothing to fold) allocates nothing.
    """

    text: str
    starts: Sequence[int]


def _unescape_layer(layer: _Layer) -> _Layer | None:
    """One bounded unescape pass; ``None`` when the pass changes nothing.

    Escapes are resolved left to right and non-overlapping, so ``\\\\``
    is consumed as one escaped backslash before the quote after it is
    considered — which is what makes one pass remove exactly one level.
    """
    text = layer.text
    length = len(text)
    chars: list[str] = []
    starts: list[int] = []
    index = 0
    changed = False
    while index < length:
        match = _DECODE_ESCAPE_RE.match(text, index)
        if match is not None:
            decoded = _decode_escape(match.group(0))
            if decoded is not None:
                chars.append(decoded)
                starts.append(layer.starts[index])
                index = match.end()
                changed = True
                continue
        chars.append(text[index])
        starts.append(layer.starts[index])
        index += 1
    if not changed:
        return None
    starts.append(layer.starts[length])
    return _Layer("".join(chars), tuple(starts))


def _decode_layers(text: str) -> list[_Layer]:
    """The text plus every bounded unescape pass, to fixpoint (max 3).

    Layer 0 is the text itself; layer N is the text with N levels of JSON
    string escaping removed. The EXISTING shape and key/value rules then
    run on every layer, and a mask found on any of them is written back
    to the bytes that spelled the secret.
    """
    layers = [_Layer(text, range(len(text) + 1))]
    if len(text) > _STRUCTURED_SCAN_MAX_CHARS:
        return layers
    for _ in range(_DECODE_MAX_PASSES):
        following = _unescape_layer(layers[-1])
        if following is None:
            break
        layers.append(following)
    return layers


# ── separator normalization (O4_FIX3 class 3) ──

#: Every line-separator spelling the fold scan can meet, folded to LF.
_SEPARATOR_RE = re.compile(r"\r\n|\r|\v|\f")


def _normalize_separators(layer: _Layer) -> _Layer:
    """Fold CRLF, lone CR, VT and FF to one LF, keeping every origin.

    One function, one pinned rule: after it, the fold scan meets exactly
    one spelling of a line ending, so a fold written with a classic-Mac
    CR is the same credential as one written with LF. The mask is written
    back through this map, so prose that merely wraps stays byte-identical
    and a blank line is still a hard delimiter.
    """
    text = layer.text
    if not _SEPARATOR_RE.search(text):
        return layer
    chars: list[str] = []
    starts: list[int] = []
    position = 0
    for match in _SEPARATOR_RE.finditer(text):
        chars.append(text[position:match.start()])
        starts.extend(layer.starts[position:match.start()])
        chars.append("\n")
        starts.append(layer.starts[match.start()])
        position = match.end()
    chars.append(text[position:])
    starts.extend(layer.starts[position:])
    return _Layer("".join(chars), tuple(starts))


#: Whitespace JSON allows between tokens.
_JSON_WS = " \t\n\r"


@dataclass(frozen=True, slots=True)
class _Member:
    """One object member with the spans that spelled it."""

    key: str
    value_start: int
    value_end: int
    is_string: bool
    content: str
    obj: int


def _scan_string_end(text: str, start: int) -> int | None:
    """``text[start]`` is a quote; return the index one past its partner."""
    index = start + 1
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            return index + 1
        index += 1
    return None


def _scan_json(text: str) -> tuple[list[_Member], dict[int, int | None]] | None:
    """Structural scan of one JSON document: its members and object tree.

    A span-recovery pass over text ``json.loads`` has already accepted —
    the walk needs the BYTES each member was spelled with, which the
    parser does not report. Returns ``None`` when the text is not a
    single well-formed JSON document.
    """
    members: list[_Member] = []
    parents: dict[int, int | None] = {}
    length = len(text)

    def skip(index: int) -> int:
        while index < length and text[index] in _JSON_WS:
            index += 1
        return index

    def value(
        index: int, parent: int | None,
    ) -> tuple[int, bool, int, int, str] | None:
        """Return ``(end, is_string, value_start, value_end, content)``."""
        index = skip(index)
        if index >= length:
            return None
        char = text[index]
        if char == '"':
            end = _scan_string_end(text, index)
            if end is None:
                return None
            return (end, True, index, end, text[index + 1:end - 1])
        if char == "{":
            end = obj(index, parent)
            return None if end is None else (end, False, index, end, "")
        if char == "[":
            end = arr(index, parent)
            return None if end is None else (end, False, index, end, "")
        stop = index
        while stop < length and text[stop] not in ",}]" and text[stop] not in _JSON_WS:
            stop += 1
        if stop == index:
            return None
        return (stop, False, index, stop, text[index:stop])

    def arr(index: int, parent: int | None) -> int | None:
        cursor = skip(index + 1)
        if cursor < length and text[cursor] == "]":
            return cursor + 1
        while True:
            parsed = value(cursor, parent)
            if parsed is None:
                return None
            cursor = skip(parsed[0])
            if cursor < length and text[cursor] == ",":
                cursor = skip(cursor + 1)
                continue
            if cursor < length and text[cursor] == "]":
                return cursor + 1
            return None

    def obj(index: int, parent: int | None) -> int | None:
        parents[index] = parent
        cursor = skip(index + 1)
        if cursor < length and text[cursor] == "}":
            return cursor + 1
        while True:
            if cursor >= length or text[cursor] != '"':
                return None
            key_end = _scan_string_end(text, cursor)
            if key_end is None:
                return None
            colon = skip(key_end)
            if colon >= length or text[colon] != ":":
                return None
            parsed = value(colon + 1, index)
            if parsed is None:
                return None
            members.append(_Member(
                key=text[cursor + 1:key_end - 1],
                value_start=parsed[2],
                value_end=parsed[3],
                is_string=parsed[1],
                content=parsed[4],
                obj=index,
            ))
            cursor = skip(parsed[0])
            if cursor < length and text[cursor] == ",":
                cursor = skip(cursor + 1)
                continue
            if cursor < length and text[cursor] == "}":
                return cursor + 1
            return None

    parsed = value(0, None)
    if parsed is None or skip(parsed[0]) != length:
        return None
    return (members, parents)



#: Credential-class header NAMES (PS-09), mirrored from
#: ``tools/providers/redact.py`` ``_CREDENTIAL_HEADERS`` — cited, not
#: imported (the pack mirrors provider shapes instead of reaching across
#: the layer boundary): the provider masks these headers BY NAME, not
#: through the alias set, so the pack has to name them too or it is
#: weaker than the discipline it cites. Longest-first so ``Set-Cookie``
#: and ``Proxy-Authorization`` match whole; parity is pinned in the test.
_CREDENTIAL_HEADER_NAMES = (
    "Proxy-Authorization", "Authorization", "Set-Cookie", "Cookie",
)

#: One credential header: the name, a colon, then its value — unanchored,
#: like the provider check it mirrors: the name may appear wherever a
#: header does. The SCHEME and the credentials are masked together
#: (``Bearer eyJ…``, ``session=…``), never just the key; the value is the
#: rest of its line, and a content-less or whitespace-only ``Cookie:``
#: line is left alone.
_CREDENTIAL_HEADER_RE = re.compile(
    r"(?i)(?P<name>"
    + "|".join(_CREDENTIAL_HEADER_NAMES)
    + r")[ \t]*:[ \t]*(?P<value>\S[^\r\n]*)"
)

#: obs-fold (RFC 7230 §3.2.4): a line continues on the next line when that
#: next line begins with SP/HTAB. A credential header split by a fold is
#: still one credential, so the fold-tolerant rule matches the SPAN in the
#: original text — never a normalized copy. The mask replaces the whole
#: folded span, which keeps prose that merely wraps byte-identical and keeps
#: a bare newline a hard delimiter (O4_FIX2 leak 2).
#:
#: The separator itself is always LF here because every layer is passed
#: through ``_normalize_separators`` first: CRLF, a lone CR, a vertical
#: tab and a form feed all become one LF before this rule sees them, so a
#: fold written with a classic-Mac CR is the same credential as one
#: written with LF (O4_FIX3 class 3). A BLANK line still delimits: the
#: continuation must begin with SP/HTAB, so ``\n\n`` is a hard boundary
#: and never a fold.
_OBS_FOLD = r"\n[ \t]+"

#: The fold tolerance for a credential header ONLY: the name and its colon on
#: one line, the scheme and credentials on the continuation (``Authorization:``
#: plus a newline and an indented ``Bearer …``), with the sweep stopping at
#: the first non-indented line. Runs BEFORE the single-line header rule, so a
#: header whose value starts on the same line and continues on the next is
#: masked as one credential instead of leaving the continuation behind.
#: SCOPE: an assignment-side fold sweep ("credential alias" + an indented
#: block) was tried and removed — it wrote over ordinary governed code (the
#: ``INSERT_TASK`` block in ``docs/idr/IDR-028.md``, where
#: ``idempotency_key: sha256(…)`` is followed by an indented object), and a
#: credential value on the continuation line is already masked by the plain
#: assignment rule. Same-line value plus indented continuation: recorded
#: residual, see the module boundary note.
_FOLDED_CREDENTIAL_HEADER_RE = re.compile(
    r"(?i)(?P<name>"
    + "|".join(_CREDENTIAL_HEADER_NAMES)
    + r")[ \t]*:[^\r\n]*(?:" + _OBS_FOLD + r"[^\r\n]*)+"
)


#: Sibling-split rule (O4_FIX2 leak 3) — STRUCTURAL, never shape recognition.
#:
#: CONTRACT: in a mapping/object, when a field named ``key`` / ``name`` /
#: ``type`` / ``field`` holds a credential-ALIAS string (``"api_key"``,
#: ``"token"``, ``"x-api-key"`` …) and a sibling field named ``value`` /
#: ``secret`` / ``token`` / ``password`` holds a string, that sibling value
#: is ALWAYS scrubbed — whole-value, shape-independent. The secret is spelled
#: as a NAME in one field and as its VALUE in another, so no assignment rule
#: and no value-shape rule can see it; and a
#: ``value``/``secret``/``token``/``password`` field sitting next to a
#: credential-name field is secret-positioned by construction. Over-masking
#: is therefore accepted here BY DESIGN: ``{"key": "api_key", "value":
#: "banana"}`` masks ``banana``. The non-trigger is a NON-credential
#: declarator value: ``{"key": "monkey", "value": "banana"}`` keeps every
#: byte. The object binds the search, but by DEPTH rather than by adjacency:
#: the value field must sit at the declarator's own brace depth with no
#: unmatched brace between them, so another member's nested object
#: (``"meta": {"x": 1}``) is tolerated while a closed — or newly opened —
#: object ends the pairing.
#:
#: O4_FIX3: the depth-equality condition was the INSTANCE rule; the class
#: mechanism is the STRUCTURAL WALK. On text ``json.loads`` accepts, the
#: pairing is computed on the parsed object tree (see
#: ``_structural_sibling_masks``), recursively at every object level: the
#: value members of the declarator's own object pair first, and when its own
#: object has none, the value members of the nearest DESCENDANT object that
#: does pair — so a declarator nested deeper than its value and a value
#: carried by a bridging member are both one credential. O4_FIX4: an object
#: the descent leaves unpaired also pairs with its SIBLING objects —
#: children of the same parent, array elements included — in document
#: order, the first unpaired declarator taking the first unpaired value
#: field and each side pairing at most once; two separate roots are never
#: one tree and stay unpaired. On text that is not a JSON document, the
#: depth scan below runs with the same lateral reach: one closing+opening
#: sibling transition at the declarator's own depth is crossed and nothing
#: wider is.
_SIBLING_DECLARATOR_NAMES = ("key", "name", "type", "field")
_SIBLING_VALUE_NAMES = ("value", "secret", "token", "password")
_SIBLING_DECLARATOR_KEYS = frozenset(_SIBLING_DECLARATOR_NAMES)
_SIBLING_VALUE_KEYS = frozenset(_SIBLING_VALUE_NAMES)
#: The alias body, shared by the text scan and the structural walk so the
#: two cannot drift apart on what counts as a credential name.
_CREDENTIAL_ALIAS_BODY = (
    r"(?:"
    + "|".join(
        r"(?:[\w.-]+[-_.])?" + re.escape(alias)
        for alias in sorted(DEFAULT_POLICY.credential_aliases)
    )
    + r")"
)
_CREDENTIAL_ALIAS_RE = re.compile(r"(?i)^" + _CREDENTIAL_ALIAS_BODY + r"$")
_SIBLING_ALIAS = _QUOTE_TOKEN + _CREDENTIAL_ALIAS_BODY + _QUOTE_TOKEN
_SIBLING_DECLARATOR_RE = re.compile(
    r"(?i)(?P<q>" + _QUOTE_TOKEN + r")(?:"
    + "|".join(_SIBLING_DECLARATOR_NAMES)
    + r")(?P=q)\s*:\s*"
    + _SIBLING_ALIAS
)
_SIBLING_VALUE_FIELD_RE = re.compile(
    r"(?i)(?P<q>" + _QUOTE_TOKEN + r")(?:"
    + "|".join(_SIBLING_VALUE_NAMES)
    + r")(?P=q)\s*:\s*"
)
_SIBLING_STRING_RE = re.compile(
    _QUOTE_TOKEN + r"(?:[^\"'\r\n]|\\.)*" + _QUOTE_TOKEN
)


def _brace_depths(text: str) -> list[int]:
    """Brace depth immediately BEFORE each character (string-aware).

    ``{``/``}`` inside a quoted string (``"note": "}"``) do not count, and a
    backslash escapes the next character inside a string, so an escaped quote
    does not end it. Deliberately small and structural — just enough for the
    sibling rule to tell "same object" from "different object" on the
    brace-balanced mappings it targets.
    """
    depths: list[int] = []
    depth = 0
    quote = ""
    escaped = False
    for char in text:
        depths.append(depth)
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
    return depths


def _gap_keeps_the_pairing(between: list[int], member_depth: int) -> bool:
    """Whether a declarator-to-value gap stays within sibling depth.

    The gap between a declarator and a value field may leave the
    declarator's own depth for ONE sibling transition (O4_FIX4): one
    closing+opening brace pair at the declarator's own depth — the step
    from a member into a sibling branch and back — is crossed, so a value
    field in a sibling branch is still the declarator's sibling. Anything
    else ends the pairing: a dip BELOW the parent's depth (the enclosing
    object closed) or a SECOND transition (an intervening sibling branch).
    At the shallowest depths (``member_depth <= 1``) the strict "no
    unmatched brace between" rule stands, because a root-level close+open
    is two separate objects, not a sibling step, and cannot be told apart
    by brace depth alone.
    """
    if min(between) >= member_depth:
        return True
    if member_depth <= 1:
        return False
    seen_transition = False
    in_dip = False
    for depth in between:
        if depth < member_depth - 1:
            return False
        if depth < member_depth:
            if not in_dip:
                if seen_transition:
                    return False
                seen_transition = True
                in_dip = True
        else:
            in_dip = False
    return True


def _text_sibling_masks(text: str) -> list[tuple[int, int, str]]:
    """Mask the value sibling of a credential-named declarator (text scan).

    Deterministic and bounded: every declarator is paired with every sibling
    value field on either side — declarator first or value field first, the
    order is not part of the shape. "Sibling" is brace depth: the value field
    sits at the declarator's own depth, and the gap between them may cross
    ONE sibling transition — one closing+opening brace pair at that depth
    (``_gap_keeps_the_pairing``) — so another member's nested object and a
    sibling branch are both tolerated while a closed (or newly opened)
    object beyond one transition ends the pairing. This is the FALLBACK
    path — it runs on text that is not a JSON document, where there is no
    object tree to walk.
    """
    fields = list(_SIBLING_VALUE_FIELD_RE.finditer(text))
    if not fields:
        return []
    starts = [field.start() for field in fields]
    depths = _brace_depths(text)
    masks: set[tuple[int, int]] = set()
    for declarator in _SIBLING_DECLARATOR_RE.finditer(text):
        member_depth = depths[declarator.start()]
        forward = bisect_left(starts, declarator.end())
        backward = bisect_left(starts, declarator.start()) - 1
        for index, step in ((forward, 1), (backward, -1)):
            while 0 <= index < len(fields):
                field = fields[index]
                low, high = (
                    (declarator.end(), field.start())
                    if step == 1
                    else (field.end(), declarator.start())
                )
                between = depths[low:high]
                if between and not _gap_keeps_the_pairing(between, member_depth):
                    break  # the sibling depth was left — no sibling here
                value = _SIBLING_STRING_RE.match(text, field.end())
                if value is not None and depths[field.start()] == member_depth:
                    masks.add((field.end(), value.end()))
                index += step
    return [
        (start, end, "<redacted>") for start, end in sorted(masks, reverse=True)
    ]


def _is_credential_alias(content: str) -> bool:
    """Whether a string value IS a credential alias (raw or once-unescaped).

    A valid JSON document can spell an alias through an escape
    (``{"name": "\\u0061pi_key"}``); testing the raw content alone would
    miss it, so the unescaped spelling is tested too.
    """
    if _CREDENTIAL_ALIAS_RE.match(content):
        return True
    decoded = _DECODE_ESCAPE_RE.sub(
        lambda match: _decode_escape(match.group(0)) or match.group(0),
        content,
    )
    return decoded != content and bool(_CREDENTIAL_ALIAS_RE.match(decoded))


def _structural_sibling_masks(
    text: str,
) -> list[tuple[int, int, str]] | None:
    """The sibling rule over the PARSED object tree (recursive, every level).

    A declarator member pairs with the value members of its OWN object.
    When its own object has no value member it pairs with the value members
    of the nearest DESCENDANT object that does — which is what closes a
    declarator nested deeper than its value and a value carried by a
    bridging member. Symmetrically, a value member whose own object has no
    declarator pairs by masking its own value when a descendant object
    carries the declarator.

    O4_FIX4 — the LATERAL reach. An object the descent above leaves unpaired
    also pairs with its SIBLING objects (children of the same parent, array
    elements included) in document order: the first unpaired declarator
    takes the first unpaired value field, each side pairs at most once, and
    document order wins ties, so
    ``{"a": {"value": "V1"}, "b": {"name": "token"}, "c": {"value": "V2"}}``
    masks V1 and leaves V2 — deterministic, not nearest-wins.

    The whole reach stays inside ONE parsed document: two roots are never
    one tree, so two separate objects stay unpaired (the pinned boundary).
    Returns ``None`` when the text is not a JSON document, which is the
    caller's signal to use the text scan.
    """
    scanned = _scan_json(text)
    if scanned is None:
        return None
    members, parents = scanned
    if not members:
        return []

    by_object: dict[int, list[_Member]] = {}
    for member in members:
        by_object.setdefault(member.obj, []).append(member)

    declarators: dict[int, list[_Member]] = {}
    values: dict[int, list[_Member]] = {}
    for start in sorted(by_object):
        for member in by_object[start]:
            key = member.key.lower()
            if not member.is_string:
                continue
            if key in _SIBLING_DECLARATOR_KEYS:
                if _is_credential_alias(member.content):
                    declarators.setdefault(start, []).append(member)
            elif key in _SIBLING_VALUE_KEYS:
                values.setdefault(start, []).append(member)

    children: dict[int, list[int]] = {}
    for start in sorted(by_object):
        parent = parents.get(start)
        children.setdefault(-1 if parent is None else parent, []).append(start)

    def first_descendant(start: int, table: dict[int, list[_Member]]) -> int | None:
        """The nearest descendant object carrying what ``table`` holds."""
        for child in children.get(start, ()):
            if child in table:
                return child
            found = first_descendant(child, table)
            if found is not None:
                return found
        return None

    masks: list[tuple[int, int, str]] = []
    unpaired_declarators: dict[int, list[_Member]] = {}
    unpaired_values: dict[int, list[_Member]] = {}
    for start in sorted(by_object):
        own_values = values.get(start, [])
        own_declarators = declarators.get(start, [])
        if own_declarators and own_values:
            # the declarator's own object carries the value — the base case,
            # at every level of the tree
            masks.extend(
                (member.value_start, member.value_end, "<redacted>")
                for member in own_values
            )
        elif own_declarators:
            found = first_descendant(start, values)
            if found is not None:
                masks.extend(
                    (member.value_start, member.value_end, "<redacted>")
                    for member in values[found]
                )
            else:
                unpaired_declarators[start] = own_declarators
        elif own_values:
            found = first_descendant(start, declarators)
            if found is not None:
                masks.extend(
                    (member.value_start, member.value_end, "<redacted>")
                    for member in own_values
                )
            else:
                unpaired_values[start] = own_values

    def first_sibling(
        start: int,
        table: dict[int, list[_Member]],
        claimed: set[int],
    ) -> int | None:
        """The first unclaimed sibling in ``table``, in document order."""
        parent = parents.get(start)
        for sibling in children.get(-1 if parent is None else parent, ()):
            if sibling != start and sibling in table and sibling not in claimed:
                return sibling
        return None

    claimed: set[int] = set()
    for start in sorted(by_object):
        if start in claimed:
            continue
        if start in unpaired_declarators:
            partner = first_sibling(start, unpaired_values, claimed)
            if partner is not None:
                masks.extend(
                    (member.value_start, member.value_end, "<redacted>")
                    for member in unpaired_values[partner]
                )
                claimed.add(start)
                claimed.add(partner)
        elif start in unpaired_values:
            partner = first_sibling(start, unpaired_declarators, claimed)
            if partner is not None:
                masks.extend(
                    (member.value_start, member.value_end, "<redacted>")
                    for member in unpaired_values[start]
                )
                claimed.add(start)
                claimed.add(partner)
    return masks


def _sibling_masks(text: str) -> list[tuple[int, int, str]]:
    """The sibling rule: structural walk on a JSON document, text scan else."""
    if len(text) <= _STRUCTURED_SCAN_MAX_CHARS:
        try:
            root = json.loads(text)
        except (ValueError, RecursionError):
            root = None
        if isinstance(root, (dict, list)):
            structural = _structural_sibling_masks(text)
            if structural is not None:
                return structural
    return _text_sibling_masks(text)


#: Standalone secret-value shapes (authority: the S6 secret scanner,
#: persistence/event_validation.py — shapes mirrored, not imported).
_SK_RE = re.compile(r"sk-[A-Za-z0-9]{20,}")
_GITHUB_TOKEN_RE = re.compile(r"gh[ops]_[A-Za-z0-9]{36}")
_AWS_KEY_RE = re.compile(r"AKIA[A-Z0-9]{16}")
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z][A-Z ]*PRIVATE KEY-----"
    r"[\s\S]*?"
    r"-----END [A-Z][A-Z ]*PRIVATE KEY-----"
)

#: JWT / header-prefixed base64url token: ``eyJ`` followed by one or more
#: dot-separated segments — the ``header.payload.signature`` tri-segment
#: shape and its ``header.payload`` prefix. A lone ``eyJ`` fragment with
#: no dot carries no payload or signature segment and is left alone (a
#: documented boundary, pinned). S6 names JWT bearer tokens as one of its
#: own blind spots (``event_validation.py:97``), so this is a pack-side
#: addition rather than a mirrored shape.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}(?:\.[A-Za-z0-9_-]+)+")

#: A BEGIN header with no END line: S6's value pattern is the header line
#: alone (``-----BEGIN [A-Z]+ PRIVATE KEY-----``), so a truncated or
#: keyless-header PEM must scrub instead of slipping past the block rule,
#: which needs the END pair. Runs AFTER the block rule, so a complete
#: block is already gone. The header is masked together with any run of
#: base64-only lines that immediately follows it — a truncated body, where
#: the key material actually is — and the run ends at the first line that
#: is not base64-only, so a document that merely quotes the header shape
#: does not lose the text after it.
_PEM_HEADER_RE = re.compile(
    r"-----BEGIN [A-Z][A-Z ]*PRIVATE KEY-----"
    r"(?:\n[ \t]*[A-Za-z0-9+/=]{16,})*"
)

_SLACK_TOKEN_RE = re.compile(r"xox[baprs]-[A-Za-z0-9-]+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


# ── the scrub pipeline, expressed as masks ──
#
# The rules keep their fixed order and each still sees the text as the
# previous rules left it, exactly as the pipeline did when it ran as a
# chain of ``sub`` calls. Expressing them as (span, replacement) masks is
# what lets a mask found on a DECODE LAYER or on a SEPARATOR-NORMALIZED
# copy be written back to the bytes that spelled the secret: every mask
# is carried in the coordinates of the text the rule was given, and the
# layer's origin map converts it to the coordinates of the real text.


def _kv_masks(
    pattern: re.Pattern[str], replacement: str, text: str,
) -> list[tuple[int, int, str]]:
    """Masks for one bare ``key=value`` rule: separator + value, whole.

    The mask starts at the end of the key so the separator is normalized
    to ``=`` — the key's own bytes are never touched.
    """
    masks: list[tuple[int, int, str]] = []
    for match in pattern.finditer(text):
        start, end = match.span(2)
        if end > start:
            masks.append((match.end(1), end, "=" + replacement))
    return masks


def _quoted_masks(
    pattern: re.Pattern[str], replacement: str, text: str,
) -> list[tuple[int, int, str]]:
    """Masks for one quoted-key rule: the value, quoting preserved."""
    masks: list[tuple[int, int, str]] = []
    for match in pattern.finditer(text):
        start, end = match.span("value")
        if end > start:
            masks.append((start, end, replacement))
    return masks


def _header_masks(
    pattern: re.Pattern[str], text: str,
) -> list[tuple[int, int, str]]:
    """Masks for one credential-header rule: name kept, scheme+value gone."""
    return [
        (match.end("name"), match.end(), ": <redacted>")
        for match in pattern.finditer(text)
    ]


def _shape_masks(
    pattern: re.Pattern[str], replacement: str, text: str,
) -> list[tuple[int, int, str]]:
    """Masks for one standalone value-shape rule: the whole match."""
    return [(m.start(), m.end(), replacement) for m in pattern.finditer(text)]


#: Standalone value shapes, in the order the pipeline applies them.
_VALUE_SHAPE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (_SK_RE, "<redacted>"),
    (_GITHUB_TOKEN_RE, "<redacted>"),
    (_AWS_KEY_RE, "<redacted>"),
    (_PEM_BLOCK_RE, "<redacted>"),
    (_PEM_HEADER_RE, "<redacted>"),
    (_JWT_RE, "<redacted>"),
    (_SLACK_TOKEN_RE, "<redacted>"),
    (_EMAIL_RE, "<redacted:email>"),
)


def _record_edit(
    edits: list[tuple[int, int, str]],
    start: int,
    end: int,
    replacement: str,
) -> list[tuple[int, int, str]]:
    """Add one mask, merging it with any mask it swallows.

    A mask that swallows masks already recorded REPLACES them — that is
    what the ordered pipeline did, since the later rule's replacement
    covered the earlier one's. A mask that only partly overlaps an earlier
    one is dropped: the region is already masked and the earlier mask
    stands, so a mask can never grow past what a rule actually matched.
    """
    hit = [edit for edit in edits if edit[0] < end and start < edit[1]]
    if not hit:
        return sorted([*edits, (start, end, replacement)])
    low = min([start, *(edit[0] for edit in hit)])
    high = max([end, *(edit[1] for edit in hit)])
    if start <= low and end >= high:
        return sorted(
            [edit for edit in edits if edit not in hit]
            + [(low, high, replacement)]
        )
    return edits


def _render(
    text: str, edits: list[tuple[int, int, str]],
) -> tuple[str, list[int]]:
    """``text`` with ``edits`` applied, plus where each character came from.

    A replaced character is tagged with the start of the edit that
    produced it, so a later rule matching across an edit is mapped back
    to the byte where that edit began — never into the middle of a mask.
    """
    parts: list[str] = []
    origins: list[int] = []
    position = 0
    for start, end, replacement in edits:
        parts.append(text[position:start])
        origins.extend(range(position, start))
        parts.append(replacement)
        origins.extend([start] * len(replacement))
        position = end
    parts.append(text[position:])
    origins.extend(range(position, len(text)))
    origins.append(len(text))
    return ("".join(parts), origins)


def _rule_masks(text: str) -> list[tuple[int, int, str]]:
    """Every mask the scrub's rules produce, in ``text`` coordinates.

    Rules run in the fixed order and each sees the text as the previous
    rules left it; the origin tracker keeps every mask in the
    coordinates of the text the rules were given.

    The fold-tolerant header rule is evaluated on the SEPARATOR-NORMALIZED
    spelling of ``text`` — every line-ending spelling folded to one LF
    before the fold scan — and its masks are written back through that
    map. Every other rule is evaluated on ``text`` itself, so their value
    classes keep meeting exactly the bytes they always met (a vertical
    tab inside a header VALUE is still part of that value; a vertical tab
    where a LINE ENDING belongs is still a line ending to the fold).
    """
    normalized = _normalize_separators(_Layer(text, range(len(text) + 1)))
    edits: list[tuple[int, int, str]] = []
    for start, end, replacement in _header_masks(
        _FOLDED_CREDENTIAL_HEADER_RE, normalized.text,
    ):
        edits = _record_edit(
            edits, normalized.starts[start], normalized.starts[end], replacement,
        )
    current, origins = _render(text, edits)

    def step(found: list[tuple[int, int, str]]) -> None:
        nonlocal current, origins, edits
        if not found:
            return
        for start, end, replacement in found:
            canonical_start = origins[start]
            canonical_end = origins[end]
            if canonical_end <= canonical_start:
                continue  # entirely inside an earlier mask
            edits = _record_edit(
                edits, canonical_start, canonical_end, replacement,
            )
        current, origins = _render(text, edits)

    # One step per RULE, not per rule family: the pipeline applied each
    # rule to the output of the previous one, so a later rule can mask
    # what an earlier one left behind and that order is observable
    # (``{"api_key": "a\"b"}`` loses its whole value because the ``key``
    # alias rule re-masks the text the ``api_key`` alias left).
    step(_sibling_masks(current))
    for pattern, replacement in _KV_CREDENTIAL_RULES:
        step(_kv_masks(pattern, replacement, current))
    for pattern, replacement in _KV_QUOTED_CREDENTIAL_RULES:
        step(_quoted_masks(pattern, replacement, current))
    step(_header_masks(_CREDENTIAL_HEADER_RE, current))
    for pattern, replacement in _KV_POLITE_RULES:
        step(_kv_masks(pattern, replacement, current))
    for pattern, replacement in _VALUE_SHAPE_RULES:
        step(_shape_masks(pattern, replacement, current))
    return edits


def _layer_masks(text: str) -> list[tuple[int, int, str]]:
    """Masks from every decode layer, in the coordinates of ``text``.

    Each layer is separator-normalized before its fold rule runs, and the
    layer's origin map converts its masks back to the bytes that spelled
    them. Layer 0 is the text itself, so an ordinary document produces
    exactly the masks it always did.
    """
    masks: list[tuple[int, int, str]] = []
    for layer in _decode_layers(text):
        for start, end, replacement in _rule_masks(layer.text):
            masks.append((layer.starts[start], layer.starts[end], replacement))
    return masks


def scrub_pack_text(text: str) -> str:
    """Pre-egress secret scrub (provider redaction discipline, text form).

    Fixed order: fold-tolerant credential headers, sibling-split values,
    bare credential assignments,
    quoted-key (JSON, escape-aware) credential assignments, credential
    headers, polite assignments, standalone secret values (provider key
    shapes, JWT, PEM blocks, header-only PEM), bare emails. Deterministic;
    clean prose passes byte-identical (over-masking is a defect, pinned by
    tests — the sibling-split rule's accepted over-masking is stated in its
    contract).

    Every rule is evaluated on every DECODE LAYER of the text (bounded
    JSON-unescape to fixpoint, three passes) and on the SEPARATOR-NORMALIZED
    spelling of each layer, with each mask written back to the bytes that
    spelled the secret. See the module docstring for the three class
    mechanisms and the three recorded limits.
    """
    if not isinstance(text, str):
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "scrub_pack_text needs text, "
            f"got {type(text).__name__} — refusing",
        )
    accepted: list[tuple[int, int, str]] = []
    for start, end, replacement in _layer_masks(text):
        accepted = _record_edit(accepted, start, end, replacement)
    if not accepted:
        return text
    out = text
    for start, end, replacement in sorted(accepted, reverse=True):
        out = out[:start] + replacement + out[end:]
    return out


def make_citation(project_id: str, content_sha: str) -> str:
    """Pack citation: ``pack:<project>:<hash>`` (no resolver knows it)."""
    _require_project(project_id)
    if (not isinstance(content_sha, str) or len(content_sha) != 64
            or any(c not in "0123456789abcdef" for c in content_sha.lower())):
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "citation needs a 64-hex content sha — refusing",
        )
    try:
        int(content_sha, 16)
    except ValueError:
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "citation content sha must be hexadecimal — refusing",
        ) from None
    return f"{PACK_REF_PREFIX}:{project_id}:{content_sha.lower()}"


def check_pack_partition(citation: str, project_id: str) -> None:
    """Refuse cross-project pack-citation presentation (partition gate).

    Same-project citations pass silently (``None``); anything else
    refuses — ``MALFORMED_PAYLOAD`` for a non-citation,
    ``EVIDENCE_DOES_NOT_RESOLVE`` for a foreign project.
    """
    _require_project(project_id)
    if not isinstance(citation, str):
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "pack citation must be a string — refusing",
        )
    parts = citation.split(":")
    if len(parts) != 3 or parts[0] != PACK_REF_PREFIX or not parts[1]:
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            f"{citation!r} is not a pack citation — refusing",
        )
    if parts[1] != project_id:
        raise PackRefusal(
            EVIDENCE_DOES_NOT_RESOLVE,
            f"pack citation resolves for project {parts[1]!r}, "
            f"not {project_id!r} — cross-project pack content refused",
        )


def check_pack_project(pack: CorpusPack, project_id: str) -> None:
    """Refuse presenting a pack outside its project (partition gate)."""
    _require_project(project_id)
    if not isinstance(pack, CorpusPack):
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "check_pack_project needs a CorpusPack — refusing",
        )
    if pack.project_id != project_id:
        raise PackRefusal(
            EVIDENCE_DOES_NOT_RESOLVE,
            f"pack is bound to project {pack.project_id!r}, "
            f"not {project_id!r} — cross-project pack content refused",
        )


def assemble_pack(
    project_id: str,
    fetched: Sequence[FetchedDoc],
    *,
    budget_tokens: int = DEFAULT_PACK_BUDGET_TOKENS,
) -> CorpusPack:
    """Store fetched docs into an advisory pack (in-memory; writes zero).

    Decode (strict UTF-8 — undecodable bytes refuse), scrub, cite, and
    include while the budget holds. Oversized items are SKIPPED with
    exact reasons, never truncated and never a refusal: a pack that
    fits nothing is an empty pack. Input order never matters — refs
    pack in sorted order.
    """
    _require_project(project_id)
    _require_budget(budget_tokens)
    if isinstance(fetched, FetchedDoc) or not isinstance(fetched, Sequence):
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "fetched must be a sequence of FetchedDoc — refusing",
        )
    items: list[PackItem] = []
    skipped: list[SkippedRef] = []
    seen: set[str] = set()
    used = 0
    ordered = sorted(fetched, key=lambda doc: doc.corpus_ref)
    for doc in ordered:
        if not isinstance(doc, FetchedDoc):
            raise PackRefusal(
                MALFORMED_PAYLOAD,
                "fetched entries must be FetchedDoc — refusing",
            )
        if doc.corpus_ref in seen:
            skipped.append(SkippedRef(
                corpus_ref=doc.corpus_ref,
                tokens_needed=0,
                reason=REASON_DUPLICATE_REF,
            ))
            continue
        seen.add(doc.corpus_ref)
        if doc.corpus_ref not in GOVERNED_CORPUS_REFS:
            raise PackRefusal(
                MALFORMED_PAYLOAD,
                f"corpus ref {doc.corpus_ref!r} is not governed — refusing",
            )
        try:
            text = doc.content.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            raise PackRefusal(
                MALFORMED_PAYLOAD,
                f"cannot decode {doc.corpus_ref!r} "
                f"({len(doc.content)} bytes, undecodable) — refusing",
            ) from None
        excerpt = scrub_pack_text(text)
        tokens = estimate_tokens(excerpt)
        source_hash = sha256_hex(doc.content)
        citation = make_citation(project_id, sha256_hex(excerpt.encode("utf-8")))
        if tokens > budget_tokens:
            skipped.append(SkippedRef(
                corpus_ref=doc.corpus_ref,
                tokens_needed=tokens,
                reason=REASON_ITEM_EXCEEDS_BUDGET,
            ))
            continue
        if used + tokens > budget_tokens:
            skipped.append(SkippedRef(
                corpus_ref=doc.corpus_ref,
                tokens_needed=tokens,
                reason=REASON_OVER_BUDGET,
            ))
            continue
        used += tokens
        items.append(PackItem(
            project_id=project_id,
            corpus_ref=doc.corpus_ref,
            source_hash=source_hash,
            citation=citation,
            tokens=tokens,
            excerpt=excerpt,
        ))
    return CorpusPack(
        version=PACK_VERSION,
        project_id=project_id,
        budget_tokens=budget_tokens,
        used_tokens=used,
        items=tuple(items),
        skipped=tuple(skipped),
    )


def pack_mapping(pack: CorpusPack) -> Mapping[str, Any]:
    """The pack as plain data (advisory markers included, never authority)."""
    if not isinstance(pack, CorpusPack):
        raise PackRefusal(
            MALFORMED_PAYLOAD,
            "pack_mapping needs a CorpusPack — refusing",
        )
    return {
        "advisory_only": True,
        "authority": PACK_AUTHORITY,
        "budget_tokens": pack.budget_tokens,
        "consumption": ADVISORY_CONSUMPTION,
        "items": [
            {
                "citation": item.citation,
                "corpus_ref": item.corpus_ref,
                "excerpt": item.excerpt,
                "kind": CORPUS_PACK_KIND,
                "source_hash": item.source_hash,
                "tokens": item.tokens,
            }
            for item in pack.items
        ],
        "pack_version": pack.version,
        "project_id": pack.project_id,
        "skipped": [
            {
                "corpus_ref": entry.corpus_ref,
                "reason": entry.reason,
                "tokens_needed": entry.tokens_needed,
            }
            for entry in pack.skipped
        ],
        "used_tokens": pack.used_tokens,
    }


def pack_bytes(pack: CorpusPack) -> bytes:
    """Canonical pack bytes: same corpus state + same budget, same bytes."""
    return canonical_json(pack_mapping(pack)).encode("utf-8")


def pack_id(pack: CorpusPack) -> str:
    """Content hash of the canonical pack bytes."""
    return sha256_hex(pack_bytes(pack))
