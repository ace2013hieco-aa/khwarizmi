"""TokenJuice-style per-kind compression plane (O3 — NEW, not wired).

Clean-room implementation: no vendored code, standard library only.
Pure and deterministic — the same input bytes always yield the same
output bytes (pinned by the golden corpus in
``tests/test_compression_plane.py``). No I/O, no clock, no randomness.

Kind router (closed set — an unknown kind refuses, it never falls
through to a generic path):

- ``json`` — canonical JSON (sorted keys, compact separators);
- ``diff`` — line-ending normalization for unified diffs;
- ``html`` — whitespace-only normalization (no parser; inter-tag runs
  are left byte-identical);
- ``search`` — line-oriented result-text normalization;
- ``code`` — trailing-whitespace + blank-line normalization (tabs are
  never expanded — that would alter Python semantics);
- ``log`` — line-oriented log normalization.

Every lossless strategy is whitespace, line-ending, or canonical-form
only — the decoded content is never reworded. Anything that drops,
folds, or truncates content is a LOSSY strategy and is gated (below).

Size gate: ``budget_bytes`` is the threshold input. The default is the
4 KiB bounded-payload discipline
(``src/hermes/persistence/event_validation.py:23``
``DEFAULT_PAYLOAD_MAX_BYTES`` — cited, not imported, so this module
stays stdlib-only; ``tests/test_compression_plane.py`` pins the
equality). A result that still exceeds the budget refuses with the
``RATIONALE`` shape instead of emitting oversized bytes. The module
never returns more bytes than it was given: a strategy with no
savings is a no-op returning the input unchanged.

CCR cache: process-local memo keyed by the content hash over
``kind + strategy + designation + payload bytes``. A refusal is never
cached — refusals carry no bytes to replay.

Savings ledger: exact byte accounting per call
(``original - compressed = saved``) with totals. The ledger is a
record, never authority: it cannot admit, promote, or refuse anything.

Lossy gating (KIND + DESIGNATION, refuse rather than degrade): the
default designation is ``EVIDENCE`` (fail-closed), so a lossy request
without an explicit ``NON_EVIDENCE`` designation refuses. A
lossy-on-evidence request refuses with ``MALFORMED_PAYLOAD`` — it is
never silently degraded to lossless, because silent substitution would
hide what the caller asked for. Lossless strategies are always
available on evidence-designated content.

Refusals use the FROZEN vocabulary only (mirrored, never extended):

- ``MALFORMED_PAYLOAD`` (``src/hermes/research/gateway.py:110``) —
  unknown kind / designation / strategy, non-bytes input, bad budget,
  undecodable text, invalid JSON, lossy-on-evidence;
- ``RATIONALE``
  (``src/hermes/research/controller.py:1803``,
  ``src/hermes/governance/policy.py:135``) — oversize-uncompressible
  or still-oversize-after-compression. The refusal detail names byte
  sizes only, never content (the PS3-07 discipline: name the
  parameter, never its value).

Integration: NOT wired into any provider path in this slice. The
public entry point is :func:`compress`; the later gate's wiring point
is named by :data:`COMPRESSION_INTEGRATION_POINT` and nothing else.
``tests/test_compression_plane.py::test_no_provider_path_calls_compression``
pins that no provider module references this plane, so there is no
silent behavior change.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

__all__ = [
    "COMPRESSION_INTEGRATION_POINT",
    "COMPRESSION_KINDS",
    "COMPRESSION_STRATEGIES",
    "CONTENT_DESIGNATIONS",
    "DEFAULT_BUDGET_BYTES",
    "DESIGNATION_EVIDENCE",
    "DESIGNATION_NON_EVIDENCE",
    "FROZEN_REFUSAL_CODES",
    "KIND_CODE",
    "KIND_DIFF",
    "KIND_HTML",
    "KIND_JSON",
    "KIND_LOG",
    "KIND_SEARCH",
    "LOSSY_HEAD_KEEP_LINES",
    "LOSSY_STRING_TRUNCATE_AT",
    "MALFORMED_PAYLOAD",
    "MAX_CACHE_ENTRIES",
    "RATIONALE",
    "STRATEGY_LOSSLESS",
    "STRATEGY_LOSSY",
    "CompressionCache",
    "CompressionOutcome",
    "CompressionRefusal",
    "LedgerEntry",
    "SavingsLedger",
    "cache_key_hex",
    "compress",
    "compress_cached",
    "content_hash_hex",
]

# ── frozen refusal vocabulary (mirrored, never extended) ──

#: Missing/oversized rationale — controller.py:1803, governance/policy.py:135.
RATIONALE = "RATIONALE"
#: Schema violation or unknown key — research/gateway.py:110.
MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"

#: The only codes a compression refusal may carry.
FROZEN_REFUSAL_CODES: frozenset[str] = frozenset({RATIONALE, MALFORMED_PAYLOAD})

# ── size gate ──

#: Default budget: the 4 KiB bounded-payload discipline
#: (persistence/event_validation.py:23 DEFAULT_PAYLOAD_MAX_BYTES).
DEFAULT_BUDGET_BYTES = 4096

# ── kind router (closed set) ──

KIND_JSON = "json"
KIND_DIFF = "diff"
KIND_HTML = "html"
KIND_SEARCH = "search"
KIND_CODE = "code"
KIND_LOG = "log"

#: Every routable kind. Anything else refuses MALFORMED_PAYLOAD.
COMPRESSION_KINDS: frozenset[str] = frozenset({
    KIND_CODE,
    KIND_DIFF,
    KIND_HTML,
    KIND_JSON,
    KIND_LOG,
    KIND_SEARCH,
})

# ── content designation (fail-closed default is EVIDENCE) ──

#: Evidence-designated content: lossy strategies are forbidden on it.
DESIGNATION_EVIDENCE = "EVIDENCE"
#: Explicitly non-evidence content: lossy strategies are permitted on it.
DESIGNATION_NON_EVIDENCE = "NON_EVIDENCE"

CONTENT_DESIGNATIONS: frozenset[str] = frozenset({
    DESIGNATION_EVIDENCE,
    DESIGNATION_NON_EVIDENCE,
})

# ── strategies ──

STRATEGY_LOSSLESS = "LOSSLESS"
STRATEGY_LOSSY = "LOSSY"

COMPRESSION_STRATEGIES: frozenset[str] = frozenset({
    STRATEGY_LOSSLESS,
    STRATEGY_LOSSY,
})

# ── lossy tuning (pinned constants, not caller inputs) ──

#: Search-lossy keeps at most this many head lines.
LOSSY_HEAD_KEEP_LINES = 50
#: JSON-lossy truncates strings longer than this many characters.
LOSSY_STRING_TRUNCATE_AT = 200

# ── cache bound ──

#: FIFO bound on CCR entries (deterministic eviction, oldest first).
MAX_CACHE_ENTRIES = 1024

# ── integration point (name only — NOT wired in this slice) ──

#: The later gate's wiring point. No provider module imports this plane.
COMPRESSION_INTEGRATION_POINT = (
    "hermes.tools.providers.paginate.combine:post-aggregate"
)


class CompressionRefusal(Exception):
    """Fail-closed refusal carrying a FROZEN code (never a new code).

    The ``to_refusal`` shape mirrors the controller RATIONALE dict
    (controller.py:1802-1805): ``rejected`` / ``code`` / ``detail``.
    """

    def __init__(self, code: str, detail: str) -> None:
        if code not in FROZEN_REFUSAL_CODES:
            raise ValueError(f"unknown compression refusal code {code!r}")
        self.code = code
        self.detail = detail
        super().__init__(f"compression refused ({code}): {detail}")

    def to_refusal(self) -> dict[str, object]:
        """The refusal-as-data shape (existing RATIONALE shape)."""
        return {"rejected": True, "code": self.code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class CompressionOutcome:
    """One successful compression: the bytes plus their exact sizes."""

    output: bytes
    kind: str
    strategy: str
    designation: str
    original_bytes: int
    compressed_bytes: int
    saved_bytes: int


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One recorded accounting line (a record, never authority)."""

    kind: str
    strategy: str
    original_bytes: int
    compressed_bytes: int
    saved_bytes: int


def content_hash_hex(data: bytes) -> str:
    """sha256 hex over raw bytes (the CCR identity primitive)."""
    return hashlib.sha256(data).hexdigest()


def cache_key_hex(
    payload: bytes,
    *,
    kind: str,
    strategy: str,
    designation: str,
) -> str:
    """CCR key: sha256 over kind + strategy + designation + payload bytes."""
    digest = hashlib.sha256()
    digest.update(kind.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(strategy.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(designation.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(payload)
    return digest.hexdigest()


def _decode_text(data: bytes) -> str:
    """Strict UTF-8 decode; undecodable bytes refuse (never half-decoded)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise CompressionRefusal(
            MALFORMED_PAYLOAD,
            "payload is not valid UTF-8 text — refusing "
            f"({len(data)} bytes, undecodable)",
        ) from None


def _normalize_eol(text: str) -> str:
    """CRLF/CR → LF (the governed EOL identity, B4 precedent)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    """At most one consecutive blank line (deterministic)."""
    out: list[str] = []
    blanks = 0
    for line in lines:
        if line == "":
            blanks += 1
            if blanks > 1:
                continue
        else:
            blanks = 0
        out.append(line)
    return out


def _lossless_ws_text(data: bytes, *, drop_empty: bool) -> bytes:
    """Shared whitespace-only normalizer for text kinds.

    EOL normalization + per-line trailing-whitespace strip + optional
    empty-line drop + blank-line collapse + single trailing newline.
    Decoded words are never reordered, deduped, or reworded.
    """
    text = _normalize_eol(_decode_text(data))
    lines = [line.rstrip(" \t") for line in text.split("\n")]
    if drop_empty:
        lines = [line for line in lines if line != ""]
    lines = _collapse_blank_lines(lines)
    out = "\n".join(lines)
    if out != "" and not out.endswith("\n"):
        out += "\n"
    return out.encode("utf-8")


def _lossless_json(data: bytes) -> bytes:
    """Canonical JSON: sorted keys, compact separators (same object)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise CompressionRefusal(
            MALFORMED_PAYLOAD,
            "json payload is not valid UTF-8 text — refusing "
            f"({len(data)} bytes, undecodable)",
        ) from None
    try:
        value = json.loads(text)
    except ValueError:
        raise CompressionRefusal(
            MALFORMED_PAYLOAD,
            "json payload is not valid JSON — refusing "
            f"({len(data)} bytes, unparseable)",
        ) from None
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _truncate_json_value(value: object) -> object:
    """JSON-lossy recoding: drop nulls, truncate long strings (gated)."""
    if isinstance(value, dict):
        return {
            key: _truncate_json_value(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_truncate_json_value(item) for item in value]
    if isinstance(value, str) and len(value) > LOSSY_STRING_TRUNCATE_AT:
        return value[:LOSSY_STRING_TRUNCATE_AT] + "…[truncated]"
    return value


def _lossy_json(data: bytes) -> bytes:
    """Lossless canonicalization first, then the gated lossy recoding."""
    canonical = _lossless_json(data)
    value = json.loads(canonical.decode("utf-8"))
    return json.dumps(
        _truncate_json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _lossless_diff(data: bytes) -> bytes:
    """Diff normalization: EOL + blank-line collapse only.

    Trailing whitespace inside hunk lines is significant (it is the added
    content), so it is never stripped — only line endings move.
    """
    text = _normalize_eol(_decode_text(data))
    return "\n".join(_collapse_blank_lines(text.split("\n"))).encode("utf-8")


_DIFF_KEEP_PREFIXES = ("@@", "+", "-", "diff ", "index ", "---", "+++", "Binary ")


def _lossy_diff(data: bytes) -> bytes:
    """Drop unified-diff context lines (leading space), keep hunks (gated)."""
    text = _normalize_eol(_decode_text(data))
    kept = [
        line
        for line in text.split("\n")
        if line == "" or line.startswith(_DIFF_KEEP_PREFIXES)
    ]
    out = "\n".join(_collapse_blank_lines(kept))
    if out != "" and not out.endswith("\n"):
        out += "\n"
    return out.encode("utf-8")


def _lossless_html(data: bytes) -> bytes:
    """HTML whitespace-only normalization (no parser; tags untouched)."""
    return _lossless_ws_text(data, drop_empty=False)


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _lossy_html(data: bytes) -> bytes:
    """Strip HTML comments after the lossless pass (gated)."""
    text = _lossless_html(data).decode("utf-8")
    return _HTML_COMMENT_RE.sub("", text).encode("utf-8")


def _lossless_search(data: bytes) -> bytes:
    """Search-result normalization: whitespace-only + empty-line drop.

    Order and duplicates are preserved — dedup is the lossy variant.
    """
    return _lossless_ws_text(data, drop_empty=True)


def _lossy_search(data: bytes) -> bytes:
    """Order-preserving dedup + head truncation after the lossless pass."""
    text = _lossless_search(data).decode("utf-8")
    if text == "":
        return b""
    seen: set[str] = set()
    deduped: list[str] = []
    for line in text.split("\n"):
        if line == "" or line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    head = deduped[:LOSSY_HEAD_KEEP_LINES]
    return ("\n".join(head) + "\n").encode("utf-8") if head else b""


def _lossless_code(data: bytes) -> bytes:
    """Code whitespace-only normalization (tabs never expanded)."""
    return _lossless_ws_text(data, drop_empty=False)


def _lossy_code(data: bytes) -> bytes:
    """Drop full-line ``#`` comments and blank lines (gated).

    Inline comments are kept — only lines whose first non-blank
    character is ``#`` go. Shebangs go with them (lossy means lossy).
    """
    text = _lossless_code(data).decode("utf-8")
    kept = [
        line
        for line in text.split("\n")
        if line != "" and not line.lstrip(" \t").startswith("#")
    ]
    return ("\n".join(kept) + "\n").encode("utf-8") if kept else b""


def _lossless_log(data: bytes) -> bytes:
    """Log whitespace-only normalization (duplicates and order kept)."""
    return _lossless_ws_text(data, drop_empty=False)


def _lossy_log(data: bytes) -> bytes:
    """Fold adjacent duplicate lines with `` (xN)`` counts (gated).

    One-way recoding: a natural line already ending in `` (xN)`` would
    be ambiguous on unfold, so folding is lossy by construction.
    """
    text = _lossless_log(data).decode("utf-8")
    if text == "":
        return b""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    out: list[str] = []
    i = 0
    while i < len(lines):
        j = i + 1
        while j < len(lines) and lines[j] == lines[i]:
            j += 1
        run = j - i
        if run > 1:
            out.append(f"{lines[i]} (x{run})")
        else:
            out.append(lines[i])
        i = j
    return ("\n".join(out) + "\n").encode("utf-8") if out else b""


_LOSSLESS_ROUTES: dict[str, Callable[[bytes], bytes]] = {
    KIND_CODE: _lossless_code,
    KIND_DIFF: _lossless_diff,
    KIND_HTML: _lossless_html,
    KIND_JSON: _lossless_json,
    KIND_LOG: _lossless_log,
    KIND_SEARCH: _lossless_search,
}

_LOSSY_ROUTES: dict[str, Callable[[bytes], bytes]] = {
    KIND_CODE: _lossy_code,
    KIND_DIFF: _lossy_diff,
    KIND_HTML: _lossy_html,
    KIND_JSON: _lossy_json,
    KIND_LOG: _lossy_log,
    KIND_SEARCH: _lossy_search,
}


def compress(
    payload: bytes,
    *,
    kind: str,
    designation: str = DESIGNATION_EVIDENCE,
    strategy: str = STRATEGY_LOSSLESS,
    budget_bytes: int = DEFAULT_BUDGET_BYTES,
) -> CompressionOutcome:
    """Compress ``payload`` with the ``kind`` strategy (pure, deterministic).

    Fail-closed: unknown kind / designation / strategy, non-bytes
    input, and non-positive budgets refuse ``MALFORMED_PAYLOAD``;
    lossy-on-evidence refuses ``MALFORMED_PAYLOAD`` rather than
    degrading; oversize results refuse ``RATIONALE``. No savings is a
    no-op returning the input unchanged (never an expansion).
    """
    if not isinstance(payload, bytes):
        raise CompressionRefusal(
            MALFORMED_PAYLOAD,
            "payload must be bytes, "
            f"got {type(payload).__name__} — refusing",
        )
    if kind not in COMPRESSION_KINDS:
        raise CompressionRefusal(
            MALFORMED_PAYLOAD,
            f"unknown compression kind {kind!r} — refusing "
            "(closed kind set, no generic fallback)",
        )
    if designation not in CONTENT_DESIGNATIONS:
        raise CompressionRefusal(
            MALFORMED_PAYLOAD,
            f"unknown content designation {designation!r} — refusing",
        )
    if strategy not in COMPRESSION_STRATEGIES:
        raise CompressionRefusal(
            MALFORMED_PAYLOAD,
            f"unknown compression strategy {strategy!r} — refusing",
        )
    if not isinstance(budget_bytes, int) or budget_bytes <= 0:
        raise CompressionRefusal(
            MALFORMED_PAYLOAD,
            "budget must be a positive byte count — refusing",
        )
    if strategy == STRATEGY_LOSSY and designation == DESIGNATION_EVIDENCE:
        raise CompressionRefusal(
            MALFORMED_PAYLOAD,
            f"lossy compression is forbidden on EVIDENCE-designated "
            f"content (kind={kind}) — refusing rather than degrading",
        )
    routes = _LOSSY_ROUTES if strategy == STRATEGY_LOSSY else _LOSSLESS_ROUTES
    compressed = routes[kind](payload)
    effective = payload if len(compressed) >= len(payload) else compressed
    if len(effective) > budget_bytes:
        if len(effective) == len(payload):
            detail = (
                f"oversize-uncompressible: {len(payload)} bytes exceeds "
                f"budget {budget_bytes} with no savings (kind={kind})"
            )
        else:
            detail = (
                f"still oversize after compression: {len(effective)} bytes "
                f"exceeds budget {budget_bytes} "
                f"(was {len(payload)}, kind={kind})"
            )
        raise CompressionRefusal(RATIONALE, detail)
    original = len(payload)
    final = len(effective)
    saved = original - final
    return CompressionOutcome(
        output=effective,
        kind=kind,
        strategy=strategy,
        designation=designation,
        original_bytes=original,
        compressed_bytes=final,
        saved_bytes=saved,
    )


class CompressionCache:
    """CCR memo keyed by content hash (kind + strategy + designation + bytes).

    Refusals are never cached — a refusal carries no bytes to replay.
    Eviction is FIFO (oldest inserted goes first): deterministic.
    """

    def __init__(self, max_entries: int = MAX_CACHE_ENTRIES) -> None:
        if not isinstance(max_entries, int) or max_entries <= 0:
            raise ValueError("max_entries must be a positive int")
        self._max_entries = max_entries
        self._entries: dict[str, bytes] = {}
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)

    def lookup(
        self,
        payload: bytes,
        *,
        kind: str,
        strategy: str,
        designation: str,
    ) -> bytes | None:
        """Return cached output bytes, or ``None`` on a miss (counted)."""
        key = cache_key_hex(
            payload, kind=kind, strategy=strategy, designation=designation
        )
        if key in self._entries:
            self.hits += 1
            return self._entries[key]
        self.misses += 1
        return None

    def store(
        self,
        payload: bytes,
        compressed: bytes,
        *,
        kind: str,
        strategy: str,
        designation: str,
    ) -> str:
        """Store ``compressed`` under the payload's CCR key (FIFO-bounded)."""
        key = cache_key_hex(
            payload, kind=kind, strategy=strategy, designation=designation
        )
        if key not in self._entries and len(self._entries) >= self._max_entries:
            oldest = next(iter(self._entries))
            del self._entries[oldest]
        self._entries[key] = compressed
        return key


def compress_cached(
    payload: bytes,
    *,
    kind: str,
    designation: str = DESIGNATION_EVIDENCE,
    strategy: str = STRATEGY_LOSSLESS,
    budget_bytes: int = DEFAULT_BUDGET_BYTES,
    cache: CompressionCache,
) -> CompressionOutcome:
    """ :func:`compress` through a CCR cache (refusals bypass the cache)."""
    hit = cache.lookup(
        payload, kind=kind, strategy=strategy, designation=designation
    )
    if hit is not None:
        original = len(payload)
        final = len(hit)
        saved = original - final
        return CompressionOutcome(
            output=hit,
            kind=kind,
            strategy=strategy,
            designation=designation,
            original_bytes=original,
            compressed_bytes=final,
            saved_bytes=saved,
        )
    outcome = compress(
        payload,
        kind=kind,
        designation=designation,
        strategy=strategy,
        budget_bytes=budget_bytes,
    )
    cache.store(
        payload,
        outcome.output,
        kind=kind,
        strategy=strategy,
        designation=designation,
    )
    return outcome


class SavingsLedger:
    """Exact byte accounting: one line per successful compression.

    ``saved = original - compressed`` on every line, totals are plain
    sums. The ledger records; it never authorizes.
    """

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def __len__(self) -> int:
        return len(self._entries)

    def record_bytes(
        self,
        original_bytes: int,
        compressed_bytes: int,
        *,
        kind: str,
        strategy: str,
    ) -> LedgerEntry:
        """Record one accounting line (the exact subtraction lives here)."""
        saved = original_bytes - compressed_bytes
        entry = LedgerEntry(
            kind=kind,
            strategy=strategy,
            original_bytes=original_bytes,
            compressed_bytes=compressed_bytes,
            saved_bytes=saved,
        )
        self._entries.append(entry)
        return entry

    def record(self, outcome: CompressionOutcome) -> LedgerEntry:
        """Record a :func:`compress` outcome (single accounting path)."""
        return self.record_bytes(
            outcome.original_bytes,
            outcome.compressed_bytes,
            kind=outcome.kind,
            strategy=outcome.strategy,
        )

    @property
    def count(self) -> int:
        """Number of recorded lines."""
        return len(self._entries)

    @property
    def total_original(self) -> int:
        """Sum of original bytes over all lines."""
        total = 0
        for entry in self._entries:
            total += entry.original_bytes
        return total

    @property
    def total_compressed(self) -> int:
        """Sum of compressed bytes over all lines."""
        total = 0
        for entry in self._entries:
            total += entry.compressed_bytes
        return total

    @property
    def total_saved(self) -> int:
        """Sum of saved bytes over all lines."""
        total = 0
        for entry in self._entries:
            total += entry.saved_bytes
        return total

    def entries(self) -> tuple[LedgerEntry, ...]:
        """Immutable snapshot of the recorded lines."""
        return tuple(self._entries)

    def to_dict(self) -> dict[str, int]:
        """Exact totals as plain ints (no floats, no rounding)."""
        return {
            "count": self.count,
            "total_original_bytes": self.total_original,
            "total_compressed_bytes": self.total_compressed,
            "total_saved_bytes": self.total_saved,
        }
