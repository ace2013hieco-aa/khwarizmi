"""Compression-plane tests (O3): goldens, gates, ledger kills, refusals.

Covers ``src/hermes/tools/compression.py`` only:

1. per-kind golden corpus (lossless + lossy) with pinned sha256 —
   same bytes in always give the same bytes out;
2. the size gate (at-budget, over-budget compressible, both RATIONALE
   oversize shapes, budget-as-input, positive-budget validation);
3. ledger exactness — one test per accounting line, so neutralizing
   any line fails its test;
4. the evidence-designation gate (lossy forbidden on evidence for
   every kind; lossless always available; fail-closed default);
5. the CCR cache (hit/miss accounting, key format, kind separation,
   FIFO eviction, refusals never cached);
6. integration discipline — the plane is NOT wired into any provider
   path in this slice (the later gate renames this proof when it
   wires :data:`COMPRESSION_INTEGRATION_POINT`).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hermes.tools.compression import (
    COMPRESSION_INTEGRATION_POINT,
    COMPRESSION_KINDS,
    COMPRESSION_STRATEGIES,
    CONTENT_DESIGNATIONS,
    DEFAULT_BUDGET_BYTES,
    DESIGNATION_EVIDENCE,
    DESIGNATION_NON_EVIDENCE,
    FROZEN_REFUSAL_CODES,
    KIND_CODE,
    KIND_DIFF,
    KIND_HTML,
    KIND_JSON,
    KIND_LOG,
    KIND_SEARCH,
    LOSSY_HEAD_KEEP_LINES,
    LOSSY_STRING_TRUNCATE_AT,
    MALFORMED_PAYLOAD,
    MAX_CACHE_ENTRIES,
    RATIONALE,
    STRATEGY_LOSSLESS,
    STRATEGY_LOSSY,
    CompressionCache,
    CompressionOutcome,
    CompressionRefusal,
    LedgerEntry,
    SavingsLedger,
    cache_key_hex,
    compress,
    compress_cached,
    content_hash_hex,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

NON_EVIDENCE = DESIGNATION_NON_EVIDENCE

# ── golden corpus: (kind, input, expected output, sha256 of output) ──

LOSSLESS_GOLDENS: tuple[tuple[str, bytes, bytes, str], ...] = (
    (
        KIND_JSON,
        b'{\n  "b": 2,\n  "a": 1\n}',
        b'{"a":1,"b":2}',
        "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777",
    ),
    (
        KIND_DIFF,
        b"--- a/f\r\n+++ b/f\r\n@@ -1 +1 @@\r\n-old\r\n+new\r\n",
        b"--- a/f\n+++ b/f\n@@ -1 +1 @@\n-old\n+new\n",
        "22258afe25466cb01fe16f8b5f851cc253dd72d38ff7600727bc9161a3da2946",
    ),
    (
        KIND_HTML,
        b"<html>\n   \n<body>   x   </body>\n</html>   \n",
        b"<html>\n\n<body>   x   </body>\n</html>\n",
        "ca57ca21f10e651d684091da2b3e4b9ece6d650807b63188a110930816de9151",
    ),
    (
        KIND_SEARCH,
        b"beta  \n\nalpha\nbeta\n",
        b"beta\nalpha\nbeta\n",
        "f17db5ee35928b2fc583afc76b6fab57588b556bad364fe2f16195a3950d2142",
    ),
    (
        KIND_CODE,
        b"def f():   \n\n\n    return 1\n",
        b"def f():\n\n    return 1\n",
        "b9a997af222ac51e567872ad0c180d730b6cb360151de965478da3fa8d558a91",
    ),
    (
        KIND_LOG,
        b"ok\nok\nfail\n",
        b"ok\nok\nfail\n",
        "c540a012f5913727a050e44472bcccb4055e93d536e7f4609eb4a708e66477cf",
    ),
)

LOSSY_JSON_INPUT = b'{"a": 1, "n": null, "s": "' + b"y" * 250 + b'"}'
LOSSY_JSON_EXPECTED = (
    b'{"a":1,"s":"' + b"y" * 200 + "…[truncated]\"}".encode("utf-8")
)

LOSSY_GOLDENS: tuple[tuple[str, bytes, bytes, str], ...] = (
    (
        KIND_JSON,
        LOSSY_JSON_INPUT,
        LOSSY_JSON_EXPECTED,
        "62ebf74161f9ff8bc18863991f58d1ecf19cac56fdae4749f6cbadac25a3b8fc",
    ),
    (
        KIND_DIFF,
        b"@@ -1,2 +1,2 @@\n keep\n-old\n+new\n",
        b"@@ -1,2 +1,2 @@\n-old\n+new\n",
        "e7d26069b401e64502ee21a16b3d6ad284bd3d81b5a31f2c2db4fb02d4d88bab",
    ),
    (
        KIND_HTML,
        b"<p>a</p><!-- gone --><p>b</p>",
        b"<p>a</p><p>b</p>\n",
        "9086937d31e8874d39e6382e1ba3af42c2b62f407692b1f86e002767fa01bcbf",
    ),
    (
        KIND_SEARCH,
        b"b\na\nb\n",
        b"b\na\n",
        "aea8a04c2f293417e499bf5de2def8ebb1ed40264d128a67180ea56fbe4600ff",
    ),
    (
        KIND_CODE,
        b"# comment\nx = 1\n\n",
        b"x = 1\n",
        "9e26bf369911c45c243c684147b23fc9e1dcfcf257d299a1c632016a6fcd33f4",
    ),
    (
        KIND_LOG,
        b"error timeout\n" * 10,
        b"error timeout (x10)\n",
        "6fac34f50231609a3aa0999eaf63fd1ce16fafe0baf75f43d184ac4b9898afd4",
    ),
)


def sha_hex(data: bytes) -> str:
    """Independent digest (stdlib direct — not via the module)."""
    return hashlib.sha256(data).hexdigest()


# ── 1. golden corpus ──


@pytest.mark.parametrize(
    "kind,payload,expected,digest", LOSSLESS_GOLDENS, ids=[g[0] for g in LOSSLESS_GOLDENS]
)
def test_lossless_golden_corpus(
    kind: str, payload: bytes, expected: bytes, digest: str
) -> None:
    first = compress(payload, kind=kind)
    second = compress(payload, kind=kind)
    assert isinstance(first, CompressionOutcome)
    assert first.output == expected
    assert second.output == expected
    assert sha_hex(first.output) == digest
    assert first.original_bytes == len(payload)
    assert first.compressed_bytes == len(expected)
    assert first.saved_bytes == len(payload) - len(expected)
    assert first.kind == kind
    assert first.strategy == STRATEGY_LOSSLESS


@pytest.mark.parametrize(
    "kind,payload,expected,digest", LOSSY_GOLDENS, ids=[g[0] for g in LOSSY_GOLDENS]
)
def test_lossy_golden_corpus(
    kind: str, payload: bytes, expected: bytes, digest: str
) -> None:
    outcome = compress(payload, kind=kind, designation=NON_EVIDENCE, strategy=STRATEGY_LOSSY)
    assert outcome.output == expected
    assert sha_hex(outcome.output) == digest
    assert outcome.saved_bytes == len(payload) - len(expected)
    assert outcome.strategy == STRATEGY_LOSSY


def test_kind_set_is_closed_and_complete() -> None:
    assert frozenset(
        {KIND_JSON, KIND_DIFF, KIND_HTML, KIND_SEARCH, KIND_CODE, KIND_LOG}
    ) == COMPRESSION_KINDS
    assert frozenset(
        {DESIGNATION_EVIDENCE, DESIGNATION_NON_EVIDENCE}
    ) == CONTENT_DESIGNATIONS
    assert frozenset({STRATEGY_LOSSLESS, STRATEGY_LOSSY}) == COMPRESSION_STRATEGIES
    assert LOSSY_HEAD_KEEP_LINES == 50
    assert LOSSY_STRING_TRUNCATE_AT == 200
    assert MAX_CACHE_ENTRIES == 1024


def test_content_hash_hex_is_plain_sha256() -> None:
    assert content_hash_hex(b"abc") == hashlib.sha256(b"abc").hexdigest()


# ── 2. size gate ──


def test_size_gate_at_budget_is_exact() -> None:
    outcome = compress(b"a\n" * 2048, kind=KIND_LOG)
    assert (outcome.original_bytes, outcome.compressed_bytes, outcome.saved_bytes) == (
        4096,
        4096,
        0,
    )


def test_size_gate_over_budget_compressible_passes() -> None:
    outcome = compress(b"a  \n" * 1500, kind=KIND_SEARCH)
    assert outcome.original_bytes == 6000
    assert outcome.compressed_bytes == 3000
    assert outcome.saved_bytes == 3000


def test_size_gate_over_budget_incompressible_refuses_rationale() -> None:
    lines = "".join(f"line-{i:05d}-MARKER-7QZ-{i * i}\n" for i in range(600))
    payload = lines.encode("utf-8")
    assert len(payload) > DEFAULT_BUDGET_BYTES
    with pytest.raises(CompressionRefusal) as exc:
        compress(payload, kind=KIND_LOG)
    assert exc.value.code == RATIONALE
    refusal = exc.value.to_refusal()
    assert refusal == {
        "rejected": True,
        "code": RATIONALE,
        "detail": exc.value.detail,
    }
    assert "oversize-uncompressible" in exc.value.detail
    assert str(len(payload)) in exc.value.detail
    assert "MARKER-7QZ" not in exc.value.detail
    assert "MARKER-7QZ" not in str(exc.value)


def test_size_gate_still_oversize_after_compression_refuses_rationale() -> None:
    with pytest.raises(CompressionRefusal) as exc:
        compress(b"a  \n" * 6000, kind=KIND_SEARCH)
    assert exc.value.code == RATIONALE
    assert "still oversize after compression" in exc.value.detail


def test_budget_is_a_caller_input() -> None:
    payload = b'{"b": 2, "a": 1}'
    assert len(payload) == 16
    ok_outcome = compress(payload, kind=KIND_JSON, budget_bytes=16)
    assert ok_outcome.compressed_bytes == 13
    with pytest.raises(CompressionRefusal) as exc:
        compress(payload, kind=KIND_JSON, budget_bytes=10)
    assert exc.value.code == RATIONALE


@pytest.mark.parametrize("bad_budget", [0, -1, -4096])
def test_budget_must_be_positive(bad_budget: int) -> None:
    with pytest.raises(CompressionRefusal) as exc:
        compress(b"a", kind=KIND_LOG, budget_bytes=bad_budget)
    assert exc.value.code == MALFORMED_PAYLOAD


def test_no_expansion_returns_input_unchanged() -> None:
    outcome = compress(b"a", kind=KIND_LOG)
    assert outcome.output == b"a"
    assert outcome.saved_bytes == 0


# ── 3. request-shape refusals (frozen vocabulary) ──


def test_unknown_kind_refuses_malformed() -> None:
    with pytest.raises(CompressionRefusal) as exc:
        compress(b"a", kind="parquet")
    assert exc.value.code == MALFORMED_PAYLOAD
    assert "parquet" in exc.value.detail


def test_unknown_designation_refuses_malformed() -> None:
    with pytest.raises(CompressionRefusal) as exc:
        compress(b"a", kind=KIND_LOG, designation="SECRET")
    assert exc.value.code == MALFORMED_PAYLOAD


def test_unknown_strategy_refuses_malformed() -> None:
    with pytest.raises(CompressionRefusal) as exc:
        compress(b"a", kind=KIND_LOG, strategy="LOSSYISH")
    assert exc.value.code == MALFORMED_PAYLOAD


def test_non_bytes_payload_refuses_malformed() -> None:
    with pytest.raises(CompressionRefusal) as exc:
        compress("a", kind=KIND_LOG)  # type: ignore[arg-type]
    assert exc.value.code == MALFORMED_PAYLOAD


def test_invalid_json_refuses_malformed() -> None:
    with pytest.raises(CompressionRefusal) as exc:
        compress(b"not json", kind=KIND_JSON)
    assert exc.value.code == MALFORMED_PAYLOAD


def test_non_utf8_text_refuses_malformed() -> None:
    with pytest.raises(CompressionRefusal) as exc:
        compress(b"\xff\xfe\x00binary", kind=KIND_LOG)
    assert exc.value.code == MALFORMED_PAYLOAD


def test_refusal_codes_are_frozen() -> None:
    assert frozenset({RATIONALE, MALFORMED_PAYLOAD}) == FROZEN_REFUSAL_CODES
    with pytest.raises(ValueError):
        CompressionRefusal("NEW_CODE", "must never exist")


def test_rationale_shape_matches_controller() -> None:
    refusal = CompressionRefusal(RATIONALE, "detail text").to_refusal()
    assert set(refusal) == {"rejected", "code", "detail"}
    assert refusal["rejected"] is True
    assert refusal["code"] == RATIONALE


# ── 4. evidence-designation gate ──


@pytest.mark.parametrize(
    "kind,payload",
    [
        (KIND_JSON, b'{"a": 1}'),
        (KIND_DIFF, b"@@ -1 +1 @@\n-old\n+new\n"),
        (KIND_HTML, b"<p>a</p><!-- c --><p>b</p>"),
        (KIND_SEARCH, b"b\na\nb\n"),
        (KIND_CODE, b"# c\nx = 1\n"),
        (KIND_LOG, b"ok\nok\nfail\n"),
    ],
    ids=[KIND_JSON, KIND_DIFF, KIND_HTML, KIND_SEARCH, KIND_CODE, KIND_LOG],
)
def test_lossy_forbidden_on_evidence_every_kind(kind: str, payload: bytes) -> None:
    with pytest.raises(CompressionRefusal) as exc:
        compress(payload, kind=kind, designation=DESIGNATION_EVIDENCE, strategy=STRATEGY_LOSSY)
    assert exc.value.code == MALFORMED_PAYLOAD
    assert kind in exc.value.detail


@pytest.mark.parametrize(
    "kind,payload",
    [(g[0], g[1]) for g in LOSSLESS_GOLDENS],
    ids=[g[0] for g in LOSSLESS_GOLDENS],
)
def test_lossless_always_available_on_evidence(kind: str, payload: bytes) -> None:
    on_evidence = compress(payload, kind=kind)
    assert on_evidence.designation == DESIGNATION_EVIDENCE
    explicit = compress(
        payload, kind=kind, designation=DESIGNATION_EVIDENCE, strategy=STRATEGY_LOSSLESS
    )
    assert explicit.output == on_evidence.output


def test_default_designation_is_evidence_fail_closed() -> None:
    with pytest.raises(CompressionRefusal) as exc:
        compress(b"<p>a</p><!-- c -->", kind=KIND_HTML, strategy=STRATEGY_LOSSY)
    assert exc.value.code == MALFORMED_PAYLOAD


# ── 5. ledger exactness (one test per accounting line) ──


def _three_line_ledger() -> SavingsLedger:
    ledger = SavingsLedger()
    ledger.record_bytes(100, 70, kind=KIND_JSON, strategy=STRATEGY_LOSSLESS)
    ledger.record_bytes(50, 50, kind=KIND_LOG, strategy=STRATEGY_LOSSLESS)
    ledger.record_bytes(10, 4, kind=KIND_SEARCH, strategy=STRATEGY_LOSSY)
    return ledger


def test_ledger_record_subtraction_is_exact() -> None:
    ledger = SavingsLedger()
    entry = ledger.record_bytes(100, 70, kind=KIND_JSON, strategy=STRATEGY_LOSSLESS)
    assert isinstance(entry, LedgerEntry)
    assert (entry.original_bytes, entry.compressed_bytes, entry.saved_bytes) == (100, 70, 30)
    assert entry.kind == KIND_JSON
    assert entry.strategy == STRATEGY_LOSSLESS


def test_ledger_total_original() -> None:
    assert _three_line_ledger().total_original == 160


def test_ledger_total_compressed() -> None:
    assert _three_line_ledger().total_compressed == 124


def test_ledger_total_saved() -> None:
    assert _three_line_ledger().total_saved == 36


def test_ledger_count_and_snapshot() -> None:
    ledger = _three_line_ledger()
    assert ledger.count == 3
    assert len(ledger) == 3
    snapshot = ledger.entries()
    assert isinstance(snapshot, tuple)
    assert len(snapshot) == 3
    assert snapshot[0].saved_bytes == 30


def test_ledger_totals_agree() -> None:
    ledger = _three_line_ledger()
    assert ledger.total_saved == ledger.total_original - ledger.total_compressed


def test_ledger_to_dict_is_exact_ints() -> None:
    assert _three_line_ledger().to_dict() == {
        "count": 3,
        "total_original_bytes": 160,
        "total_compressed_bytes": 124,
        "total_saved_bytes": 36,
    }


def test_ledger_empty_is_zero() -> None:
    ledger = SavingsLedger()
    assert (ledger.count, ledger.total_original, ledger.total_compressed) == (0, 0, 0)
    assert ledger.total_saved == 0
    assert ledger.entries() == ()


def test_ledger_record_outcome_uses_the_single_path() -> None:
    outcome = compress(b'{"b": 2, "a": 1}', kind=KIND_JSON)
    ledger = SavingsLedger()
    entry = ledger.record(outcome)
    assert (entry.original_bytes, entry.compressed_bytes, entry.saved_bytes) == (
        outcome.original_bytes,
        outcome.compressed_bytes,
        outcome.saved_bytes,
    )
    assert ledger.total_saved == outcome.saved_bytes


# ── 6. CCR cache ──


def test_cache_miss_then_hit_counts() -> None:
    cache = CompressionCache()
    assert len(cache) == 0
    assert cache.lookup(b"abc", kind=KIND_LOG, strategy=STRATEGY_LOSSLESS,
                        designation=DESIGNATION_EVIDENCE) is None
    assert (cache.hits, cache.misses) == (0, 1)
    cache.store(b"abc", b"abc", kind=KIND_LOG, strategy=STRATEGY_LOSSLESS,
                designation=DESIGNATION_EVIDENCE)
    assert cache.lookup(b"abc", kind=KIND_LOG, strategy=STRATEGY_LOSSLESS,
                        designation=DESIGNATION_EVIDENCE) == b"abc"
    assert (cache.hits, cache.misses) == (1, 1)


def test_cache_key_pins_content_hash_format() -> None:
    expected = hashlib.sha256(
        b"log\x00LOSSLESS\x00NON_EVIDENCE\x00abc"
    ).hexdigest()
    assert cache_key_hex(
        b"abc", kind=KIND_LOG, strategy=STRATEGY_LOSSLESS, designation=NON_EVIDENCE
    ) == expected


def test_cache_separates_kinds() -> None:
    cache = CompressionCache()
    cache.store(b"x", b"x", kind=KIND_LOG, strategy=STRATEGY_LOSSLESS,
                designation=DESIGNATION_EVIDENCE)
    cache.store(b"x", b"x", kind=KIND_JSON, strategy=STRATEGY_LOSSLESS,
                designation=DESIGNATION_EVIDENCE)
    assert len(cache) == 2


def test_cache_fifo_eviction_is_deterministic() -> None:
    cache = CompressionCache(max_entries=2)
    kwargs = {"kind": KIND_LOG, "strategy": STRATEGY_LOSSLESS,
              "designation": DESIGNATION_EVIDENCE}
    cache.store(b"one", b"one", **kwargs)  # type: ignore[arg-type]
    cache.store(b"two", b"two", **kwargs)  # type: ignore[arg-type]
    cache.store(b"three", b"three", **kwargs)  # type: ignore[arg-type]
    assert len(cache) == 2
    assert cache.lookup(b"one", **kwargs) is None  # type: ignore[arg-type]
    assert cache.lookup(b"two", **kwargs) == b"two"  # type: ignore[arg-type]
    assert cache.lookup(b"three", **kwargs) == b"three"  # type: ignore[arg-type]


def test_cache_rejects_bad_bound() -> None:
    with pytest.raises(ValueError):
        CompressionCache(max_entries=0)


def test_cache_never_stores_refusals() -> None:
    cache = CompressionCache()
    payload = b"x" * 5000
    for _ in range(2):
        with pytest.raises(CompressionRefusal):
            compress_cached(payload, kind=KIND_LOG, cache=cache)
    assert len(cache) == 0


def test_compress_cached_hit_returns_equal_outcome() -> None:
    cache = CompressionCache()
    payload = b'{"b": 2, "a": 1}'
    first = compress_cached(payload, kind=KIND_JSON, cache=cache)
    assert cache.misses == 1
    second = compress_cached(payload, kind=KIND_JSON, cache=cache)
    assert cache.hits == 1
    assert second == first
    assert second.output == b'{"a":1,"b":2}'


# ── 7. integration discipline (not wired in this slice) ──


def test_integration_point_named_not_wired() -> None:
    assert COMPRESSION_INTEGRATION_POINT == (
        "hermes.tools.providers.paginate.combine:post-aggregate"
    )
    assert callable(compress)


PIPELINE_FILES = (
    "src/hermes/tools/providers/paginate.py",
    "src/hermes/tools/providers/replay.py",
    "src/hermes/tools/providers/http.py",
    "src/hermes/tools/providers/base.py",
    "src/hermes/tools/research_sources.py",
    "src/hermes/tools/providers/adapters/__init__.py",
)


@pytest.mark.parametrize("relative", PIPELINE_FILES)
def test_no_provider_path_calls_compression(relative: str) -> None:
    """The current pipeline calls no compression (no silent behavior change).

    The later gate renames this proof when it wires
    COMPRESSION_INTEGRATION_POINT — until then every provider path
    must be free of compression references.
    """
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert "compression" not in text.lower()


def test_budget_matches_the_4kib_discipline() -> None:
    from hermes.persistence.event_validation import DEFAULT_PAYLOAD_MAX_BYTES

    assert DEFAULT_BUDGET_BYTES == DEFAULT_PAYLOAD_MAX_BYTES == 4096
