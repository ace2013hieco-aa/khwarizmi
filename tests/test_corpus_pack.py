"""Corpus-pack tests (O4): budget, determinism, scrub kills, partition.

Covers ``src/hermes/research/corpus_pack.py`` only:

1. recall/fetch against ``corpus.py`` reads (membership, errors);
2. token-budget exactness (fit boundary, skip reasons, invariants);
3. determinism — 100x identical bytes on synthetic docs, double
   assembly identical on the live corpus;
4. secret scrub — one test per rule (neutralize a rule and its test
   fails), clean prose byte-identical, and the end-to-end
   secret-absence proof on unpacked pack bytes;
5. per-project partition (cross-project refuses
   ``EVIDENCE_DOES_NOT_RESOLVE``);
6. advisory boundary — pack citations resolve to nothing at the
   classification resolver, both detector paths, and L2; assembly
   writes zero rows and zero events; markers pinned;
7. no-wire proof — nothing outside this module and test references it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hermes.core import frozen_clock
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.persistence.source_outcomes import SOURCE_ARTIFACT_TYPES
from hermes.research.contradiction_candidates import detector_resolve_ref
from hermes.research.corpus import GOVERNED_CORPUS_REFS
from hermes.research.corpus_pack import (
    ADVISORY_CONSUMPTION,
    CORPUS_PACK_KIND,
    DEFAULT_PACK_BUDGET_TOKENS,
    EVIDENCE_DOES_NOT_RESOLVE,
    FROZEN_PACK_REFUSAL_CODES,
    MALFORMED_PAYLOAD,
    PACK_AUTHORITY,
    PACK_REF_PREFIX,
    PACK_TOKEN_CHARS,
    PACK_VERSION,
    REASON_DUPLICATE_REF,
    REASON_ITEM_EXCEEDS_BUDGET,
    REASON_OVER_BUDGET,
    FetchedDoc,
    PackRefusal,
    assemble_pack,
    check_pack_partition,
    check_pack_project,
    estimate_tokens,
    fetch_pack_docs,
    make_citation,
    pack_bytes,
    pack_id,
    pack_mapping,
    recall,
    scrub_pack_text,
)
from hermes.research.gateway import _cx_resolve_evidence_ref
from hermes.research.l2_resolution import _l2_resolve_ref_to_artifacts

REPO_ROOT = Path(__file__).resolve().parents[1]
CLOCK = "2026-10-07T00:00:00.000000+00:00"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p2", "Other")
    yield conn
    conn.close()


def _counts(conn) -> tuple[int, int]:
    artifacts = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    return (artifacts, events)


def _doc(ref: str, text: str) -> FetchedDoc:
    return FetchedDoc(corpus_ref=ref, content=text.encode("utf-8"))


# ── 1. recall ──


def test_recall_defaults_to_all_governed_sorted() -> None:
    assert recall("p1") == tuple(sorted(GOVERNED_CORPUS_REFS))
    assert len(recall("p1")) == 12


def test_recall_explicit_subset_sorted_deduped() -> None:
    assert recall("p1", ["docs/STATE.md", "AGENTS.md", "AGENTS.md"]) == (
        "AGENTS.md",
        "docs/STATE.md",
    )


def test_recall_unknown_ref_refuses() -> None:
    with pytest.raises(PackRefusal) as exc:
        recall("p1", ["docs/idr/IDR-040.md"])
    assert exc.value.code == MALFORMED_PAYLOAD


def test_recall_bad_project_or_shape_refuses() -> None:
    with pytest.raises(PackRefusal) as exc:
        recall("", ["AGENTS.md"])
    assert exc.value.code == MALFORMED_PAYLOAD
    with pytest.raises(PackRefusal) as exc:
        recall("p1", "AGENTS.md")  # type: ignore[arg-type]
    assert exc.value.code == MALFORMED_PAYLOAD


# ── 2. budgeting units ──


@pytest.mark.parametrize(
    ("text", "tokens"),
    [("", 0), ("a", 1), ("abcd", 1), ("abcde", 2), ("abcdefgh", 2)],
)
def test_estimate_tokens_exact(text: str, tokens: int) -> None:
    assert PACK_TOKEN_CHARS == 4
    assert tokens == estimate_tokens(text)


def test_estimate_tokens_rejects_non_text() -> None:
    with pytest.raises(PackRefusal) as exc:
        estimate_tokens(b"a")  # type: ignore[arg-type]
    assert exc.value.code == MALFORMED_PAYLOAD


# ── 3. fetch ──


def test_fetch_reads_through_corpus_boundary() -> None:
    docs = fetch_pack_docs(REPO_ROOT, "p1", ("AGENTS.md", "docs/API.md"))
    assert [d.corpus_ref for d in docs] == ["AGENTS.md", "docs/API.md"]
    assert all(len(d.content) > 0 for d in docs)


def test_fetch_unlisted_ref_normalizes_to_malformed() -> None:
    with pytest.raises(PackRefusal) as exc:
        fetch_pack_docs(REPO_ROOT, "p1", ("docs/idr/IDR-040.md",))
    assert exc.value.code == MALFORMED_PAYLOAD


def test_fetch_missing_on_disk_is_rationale(tmp_path: Path) -> None:
    with pytest.raises(PackRefusal) as exc:
        fetch_pack_docs(tmp_path, "p1", ("AGENTS.md",))
    assert exc.value.code == "RATIONALE"


def test_fetch_bad_root_or_shape_refuses() -> None:
    with pytest.raises(PackRefusal) as exc:
        fetch_pack_docs(123, "p1", ("AGENTS.md",))  # type: ignore[arg-type]
    assert exc.value.code == MALFORMED_PAYLOAD


# ── 4. secret scrub, one test per rule ──


def test_scrub_exact_credential_assignment() -> None:
    assert scrub_pack_text("api_key=SECRET123") == "api_key=<redacted>"
    assert "SECRET123" not in scrub_pack_text("api_key=SECRET123")


def test_scrub_separator_suffixed_header_key() -> None:
    assert scrub_pack_text("X-Api-Key: hunter2") == "X-Api-Key=<redacted>"
    assert "hunter2" not in scrub_pack_text("X-Api-Key: hunter2")


def test_scrub_substring_is_not_a_key() -> None:
    # The suffix rule exists to stop this: ordinary prose survives.
    assert scrub_pack_text("monkey=banana") == "monkey=banana"


def test_scrub_polite_assignment_keeps_discipline_form() -> None:
    assert scrub_pack_text("email=a@b.c") == "email=<redacted:email>"


def test_scrub_openai_key() -> None:
    secret = "sk-abcdefghij1234567890"
    assert secret not in scrub_pack_text(f"key {secret} here")


def test_scrub_github_token() -> None:
    secret = "ghp_" + "a" * 36
    assert secret not in scrub_pack_text(f"token {secret} here")


def test_scrub_aws_key() -> None:
    assert "AKIAIOSFODNN7EXAMPLE" not in scrub_pack_text(
        "id AKIAIOSFODNN7EXAMPLE here"
    )


def test_scrub_pem_block() -> None:
    block = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIBordo\n"
        "-----END RSA PRIVATE KEY-----"
    )
    scrubbed = scrub_pack_text(f"cert {block} end")
    assert "MIIBordo" not in scrubbed
    assert "PRIVATE KEY" not in scrubbed


def test_scrub_slack_token() -> None:
    assert "xoxb-123-abc" not in scrub_pack_text("hook xoxb-123-abc here")


def test_scrub_bare_email() -> None:
    assert scrub_pack_text("ops@example.com") == "<redacted:email>"


def test_scrub_clean_prose_byte_identical() -> None:
    prose = "The quick brown fox cites AGENTS.md twice (see §3 and §3)."
    assert prose == scrub_pack_text(prose)


def test_scrub_rejects_non_text() -> None:
    with pytest.raises(PackRefusal) as exc:
        scrub_pack_text(b"a")  # type: ignore[arg-type]
    assert exc.value.code == MALFORMED_PAYLOAD


# ── 4b. secret scrub — the shapes O4_REDTEAM item 3 found passing ──


def test_scrub_json_quoted_credential_assignment() -> None:
    line = '{"api_key": "SECRETJSON123", "port": 1}'
    assert scrub_pack_text(line) == '{"api_key": <redacted>, "port": 1}'
    assert "SECRETJSON123" not in scrub_pack_text(line)


def test_scrub_json_quoted_assignment_keeps_style_and_spacing() -> None:
    assert scrub_pack_text("'token':   'tok123'") == "'token':   <redacted>"
    assert scrub_pack_text('{"secret": secretvalue}') == '{"secret": <redacted>}'


def test_scrub_json_quoted_rule_is_no_broader_than_the_plain_rule() -> None:
    # the suffix discipline still holds for a quoted key: no separator
    # before `key` means no key (this is what keeps monkey=banana clean)
    assert scrub_pack_text('{"monkey": "banana"}') == '{"monkey": "banana"}'


def test_scrub_credential_header_masks_scheme_and_value() -> None:
    auth = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payloadsig9"
    assert scrub_pack_text(auth) == "Authorization: <redacted>"
    assert scrub_pack_text("Proxy-Authorization: Basic dXNlcjpwdw==") == (
        "Proxy-Authorization: <redacted>"
    )
    cookie = "Set-Cookie: session=abcdef1234567890; Path=/"
    assert scrub_pack_text(cookie) == "Set-Cookie: <redacted>"
    assert "abcdef1234567890" not in scrub_pack_text(cookie)
    # the rule is unanchored, like the provider check it mirrors: a
    # header written mid-sentence still loses its value (the value runs
    # to the end of its line)
    assert scrub_pack_text("send Authorization: Bearer abc123 now") == (
        "send Authorization: <redacted>"
    )


def test_scrub_credential_headers_cover_the_provider_ps09_names() -> None:
    from hermes.tools.providers.redact import _CREDENTIAL_HEADERS

    for name in sorted(_CREDENTIAL_HEADERS):
        marker = f"value-{name}-marker"
        assert marker not in scrub_pack_text(f"{name}: {marker}")


def test_scrub_credential_header_needs_a_value() -> None:
    # a content-less header carries no secret
    assert scrub_pack_text("Cookie:") == "Cookie:"
    assert scrub_pack_text("Cookie:   ") == "Cookie:   "
    # and the names in prose, with no value after them, stay prose
    prose = "the reverse proxy sets Cookie and Authorization itself."
    assert scrub_pack_text(prose) == prose


def test_scrub_standalone_jwt() -> None:
    tri = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    assert scrub_pack_text(f"bearer {tri} end") == "bearer <redacted> end"
    # the header.payload prefix of the same shape masks too
    prefix = "eyJhbGciOiJIUzI1NiJ9.payloadsig9"
    assert prefix not in scrub_pack_text(f"standalone {prefix} here")


def test_scrub_jwt_boundary_is_the_dot() -> None:
    # documented boundary: the rule needs one dotted segment, so a lone
    # `eyJ` fragment and a dotted non-eyJ token are left alone
    lone = "eyJhbGciOiJIUzI1NiJ9"
    assert scrub_pack_text(lone) == lone
    assert scrub_pack_text("aGVsbG8.d29ybGQ") == "aGVsbG8.d29ybGQ"


def test_scrub_pem_header_without_end_line() -> None:
    header = "-----BEGIN RSA PRIVATE KEY-----"
    assert scrub_pack_text(f"key {header} here") == "key <redacted> here"
    assert "PRIVATE KEY" not in scrub_pack_text(f"key {header} here")
    assert scrub_pack_text(header) == "<redacted>"


def test_scrub_pem_truncated_block_takes_its_base64_body() -> None:
    # a header with no END is masked at the header line plus the base64-only
    # lines that follow it (the truncated body, where the key material is)
    text = """-----BEGIN RSA PRIVATE KEY-----
MIIBordo0MIIBordo0MIIBordo0MIIBordo0
prose line"""
    assert scrub_pack_text(text) == """<redacted>
prose line"""


def test_scrub_pem_sweep_stops_at_the_first_non_base64_line() -> None:
    # documented boundary: the sweep is bounded by the base64 run, so a
    # document that merely quotes the header shape keeps what follows
    text = """-----BEGIN RSA PRIVATE KEY-----
the scanner matches this header shape itself.
more prose"""
    assert scrub_pack_text(text) == """<redacted>
the scanner matches this header shape itself.
more prose"""


# ── 4c. secret scrub — the three O4_FIX2 leak shapes (terminal round) ──


def test_scrub_escaped_json_credential_assignment() -> None:
    # O4_FIX2 leak 1: a JSON document nested inside a JSON string escapes
    # its quotes, and the quoted-key rule used to be blind to that shape
    line = '{"blob": "{\\"api_key\\": \\"SECRET-XYZ\\"}"}'
    assert scrub_pack_text(line) == '{"blob": "{\\"api_key\\": <redacted>}"}'
    assert "SECRET-XYZ" not in scrub_pack_text(line)


def test_scrub_escaped_single_quoted_variant() -> None:
    # the same tolerance for the single-quote style
    assert scrub_pack_text(r"{\'token\': \'SECRET-XYZ\'}") == (
        r"{\'token\': <redacted>}"
    )
    assert scrub_pack_text(r"{\'x-api-key\': \'SECRET-XYZ\'}") == (
        r"{\'x-api-key\': <redacted>}"
    )


def test_scrub_escaped_json_shaped_canary_stays_clean() -> None:
    # regression pin: a shaped canary inside escaped JSON was already clean
    # before this round (the value-shape rules never cared about quotes)
    line = '{"blob": "{\\"api_key\\": \\"sk-abcdefghij1234567890\\"}"}'
    assert "sk-abcdefghij1234567890" not in scrub_pack_text(line)


def test_scrub_folded_credential_header() -> None:
    # O4_FIX2 leak 2: obs-fold (RFC 7230 3.2.4) — the continuation line
    # begins with SP/HTAB and supplies the value
    assert scrub_pack_text("Authorization:\n Bearer SECRET-XYZ") == (
        "Authorization: <redacted>"
    )
    assert scrub_pack_text("Authorization:\n Bearer\n  SECRET-XYZ") == (
        "Authorization: <redacted>"
    )


def test_scrub_folded_header_sweep_stops_at_the_first_non_fold_line() -> None:
    text = "Cookie:\n a=1;\n b=2\nnext: value"
    assert scrub_pack_text(text) == "Cookie: <redacted>\nnext: value"
    # a value that starts on the header line and continues on the next is
    # one credential, not a masked first line plus a leaked continuation
    assert scrub_pack_text("Authorization: Bearer\n SECRET-XYZ") == (
        "Authorization: <redacted>"
    )


def test_scrub_folded_credential_assignment_is_already_covered() -> None:
    # the assignment side needs no fold rule of its own: the plain key rule
    # crosses a bare newline through \s*, so a value on the continuation
    # line is masked already (the O4 baseline behaved the same way)
    text = "api_key:\n  SECRET-XYZ\nnext: kept"
    assert scrub_pack_text(text) == "api_key=<redacted>\nnext: kept"
    assert "SECRET-XYZ" not in scrub_pack_text(text)


def test_scrub_fold_tolerance_is_scoped_to_headers() -> None:
    # census evidence (docs/idr/IDR-028.md): an assignment-side fold sweep
    # matched `idempotency_key:` plus every indented line of the INSERT_TASK
    # block and collapsed them into one mask. An indented block after a
    # credential-alias assignment is ordinary governed code, so the fold
    # tolerance is scoped to the header form — this block survives intact
    # (the one mask is the pre-existing assignment rule, unchanged).
    block = (
        "INSERT_TASK {\n"
        '  idempotency_key: sha256("extract:" + source_ref),\n'
        "  spec: {\n"
        '    source_ref: "dataset_manifest:<id>",\n'
        '    template_version: "1",\n'
        "  },\n"
        "}\n"
    )
    assert scrub_pack_text(block) == (
        "INSERT_TASK {\n"
        "  idempotency_key=<redacted> + source_ref),\n"
        "  spec: {\n"
        '    source_ref: "dataset_manifest:<id>",\n'
        '    template_version: "1",\n'
        "  },\n"
        "}\n"
    )


def test_scrub_folded_key_continuation_is_a_recorded_residual() -> None:
    # RECORDED RESIDUAL (not a desired property): a same-line value plus an
    # indented continuation keeps the continuation. Closing it needs a rule
    # wide enough to also rewrite indented code blocks in the governed corpus
    # (the census above), which the over-masking discipline forbids, and the
    # value-on-the-continuation form is covered by the plain rule.
    text = "api_key: part-one\n  part-two-secret"
    scrubbed = scrub_pack_text(text)
    assert scrubbed == "api_key=<redacted>\n  part-two-secret"
    assert "part-two-secret" in scrubbed


def test_scrub_fold_requires_a_continuation_line() -> None:
    # O4_FIX2 leak 2, negative: a continuation line must begin with SP/HTAB.
    # A bare newline is a hard delimiter — the naive "unfold every newline"
    # would merge these two lines and mask the column-0 line as the value.
    text = "Authorization:\nSECRET-XYZ"
    assert scrub_pack_text(text) == text


def test_scrub_sibling_split_declarator_first() -> None:
    # O4_FIX2 leak 3: the secret is spelled as a NAME in one field and as
    # its VALUE in a sibling field, so no assignment rule and no value-shape
    # rule can see it — the rule is structural and masks the sibling value
    line = '{"name": "api_key", "value": "SECRET-XYZ"}'
    assert scrub_pack_text(line) == '{"name": "api_key", "value": <redacted>}'
    assert "SECRET-XYZ" not in scrub_pack_text(line)


def test_scrub_sibling_split_value_field_first() -> None:
    # order is not part of the shape: the value field may come first
    line = '{"value": "SECRET-XYZ", "name": "api_key"}'
    assert scrub_pack_text(line) == '{"value": <redacted>, "name": "api_key"}'
    assert "SECRET-XYZ" not in scrub_pack_text(line)


def test_scrub_sibling_split_tolerates_other_members() -> None:
    # "sibling" is brace depth, not adjacency: other members in between are
    # fine (including a member that itself holds a nested object), while a
    # closed or newly opened object ends the pairing
    between = '{"name": "api_key",\n  "criticality": "low",\n  "value": "SECRET-XYZ"}'
    assert scrub_pack_text(between) == (
        '{"name": "api_key",\n  "criticality": "low",\n  "value": <redacted>}'
    )
    nested = '{"name": "api_key", "meta": {"x": 1}, "value": "SECRET-XYZ"}'
    assert "SECRET-XYZ" not in scrub_pack_text(nested)
    deeper = '{"name": "api_key", "meta": {"value": "X"}, "value": "SECRET-XYZ"}'
    assert scrub_pack_text(deeper) == (
        '{"name": "api_key", "meta": {"value": "X"}, "value": <redacted>}'
    )
    # a closing brace inside a string value is a string, not a boundary
    braced = '{"name": "api_key", "note": "}", "value": "SECRET-XYZ"}'
    assert "SECRET-XYZ" not in scrub_pack_text(braced)


def test_scrub_sibling_split_escaped_and_shaped() -> None:
    # escape tolerance and the shaped-canary regression in one place
    escaped = r'{"blob": "{\"name\": \"api_key\", \"value\": \"SECRET-XYZ\"}"}'
    assert "SECRET-XYZ" not in scrub_pack_text(escaped)
    shaped = '{"name": "api_key", "value": "sk-abcdefghij1234567890"}'
    assert "sk-abcdefghij1234567890" not in scrub_pack_text(shaped)


def test_scrub_sibling_split_requires_a_credential_declarator() -> None:
    # non-trigger: neither a non-credential alias value nor a non-credential
    # declarator name fires the rule (`"key":` itself is name-masked by the
    # quoted-credential rule, exactly as before this round)
    assert scrub_pack_text('{"key": "monkey", "value": "banana"}') == (
        '{"key": <redacted>, "value": "banana"}'
    )
    assert scrub_pack_text('{"field": "size", "value": "banana"}') == (
        '{"field": "size", "value": "banana"}'
    )
    # the directive's exact compact spelling of the same non-trigger
    assert scrub_pack_text('{"key":"monkey","value":"banana"}') == (
        '{"key":<redacted>,"value":"banana"}'
    )


def test_scrub_sibling_split_contract_over_masks_by_design() -> None:
    # CONTRACT (stated in the rule's docstring): a value/secret/token/
    # password field sitting next to a field whose string value is a
    # credential ALIAS is secret-positioned by construction, so its value is
    # always scrubbed — even a harmless one. Over-masking accepted by design.
    assert scrub_pack_text('{"key": "api_key", "value": "banana"}') == (
        '{"key": <redacted>, "value": <redacted>}'
    )
    # the directive's exact compact spelling of the accepted over-mask
    assert scrub_pack_text('{"key":"api_key","value":"banana"}') == (
        '{"key":<redacted>,"value":<redacted>}'
    )


def test_scrub_sibling_split_is_bounded_by_the_object() -> None:
    # two separate objects are not siblings: the rule never pairs across an
    # object boundary, and nothing else here is an assignment, so the line
    # passes through byte-identical
    text = '{"name": "api_key"} {"value": "SECRET-XYZ"}'
    assert scrub_pack_text(text) == text


# ── 4d. secret scrub — the three O4_FIX3 CLASS mechanisms ──
#
# Each mechanism below is a class rule, so each pin is built from the
# FAMILY it closes rather than the spelling that first exposed it, and
# each neutralization (dropping the mechanism) fails the family's pins.


def _escaped_nest(doc: str, depth: int) -> str:
    """``doc`` wrapped in ``depth`` levels of JSON string escaping."""
    for _ in range(depth):
        doc = json.dumps(doc)
    return '{"blob": ' + doc + '}'


# ── class 1: decode-then-scan (bounded JSON-unescape to fixpoint) ──


def test_scrub_decode_then_scan_closes_every_escape_depth() -> None:
    # one unescape pass removes one level of escaping, so three passes
    # reach a secret spelled through three levels of JSON string quoting.
    # The mask is written back to the bytes that spelled the secret, so
    # the backslashes that carried the escaping go with it.
    assert scrub_pack_text(_escaped_nest('{"api_key": "SECRET-XYZ"}', 1)) == (
        '{"blob": "{\\"api_key\\": <redacted>}"}'
    )
    assert "SECRET-XYZ" not in scrub_pack_text(
        _escaped_nest('{"api_key": "SECRET-XYZ"}', 2)
    )
    assert "SECRET-XYZ" not in scrub_pack_text(
        _escaped_nest('{"api_key": "SECRET-XYZ"}', 3)
    )
    # the sibling rule closes through the layers too
    assert "SECRET-XYZ" not in scrub_pack_text(
        _escaped_nest('{"name": "api_key", "value": "SECRET-XYZ"}', 2)
    )


def test_scrub_decode_then_scan_closes_the_unicode_quote_escape() -> None:
    # \u0022 is the documented JSON spelling of a double quote, and
    # \u0027 of a single one: neither is a quote character to a regex
    # token class, so the decode pass is what makes the shape visible.
    assert "SECRET-XYZ" not in scrub_pack_text(
        r'{"blob": "{\u0022api_key\u0022: \u0022SECRET-XYZ\u0022}"}'
    )
    assert scrub_pack_text(r"{\u0027token\u0027: \u0027SECRET-XYZ\u0027}") == (
        r"{\u0027token\u0027: <redacted>}"
    )
    # a decoded layer also closes a header spelled behind \u0041
    assert "SECRET-XYZ" not in scrub_pack_text(
        r'"\u0041uthorization: Bearer SECRET-XYZ"'
    )


def test_scrub_decode_passes_are_bounded_to_three() -> None:
    # the bound is stated, not implied: four levels of escaping are the
    # recorded residual, and the pass count is pinned so a widening has
    # to be a decision rather than a drift.
    from hermes.research.corpus_pack import _DECODE_MAX_PASSES, _decode_layers

    assert _DECODE_MAX_PASSES == 3
    assert len(_decode_layers("plain text")) == 1
    layers = _decode_layers(r'{"blob": "{\"a\": 1}"}')
    assert len(layers) == 2  # text plus one pass; the second is a fixpoint
    deep = _escaped_nest('{"api_key": "SECRET-XYZ"}', 4)
    assert len(_decode_layers(deep)) == 4  # original + three passes
    # three passes reach ONE level of escaping, which the quoted rules'
    # own one-backslash tolerance already reads: the closure is four levels
    assert "SECRET-XYZ" not in scrub_pack_text(deep)
    # five levels and beyond is the stated residual of the pass bound
    assert "SECRET-XYZ" in scrub_pack_text(
        _escaped_nest('{"api_key": "SECRET-XYZ"}', 5)
    )


def test_scrub_decode_layers_carry_every_character_origin() -> None:
    # a mask found on a layer is applied to the bytes that spelled it:
    # the escaped quote that opened the value carries its backslash into
    # the mask, which is why the escaped form keeps its exact bytes.
    from hermes.research.corpus_pack import _decode_layers

    text = r'{"blob": "{\"api_key\": \"SECRET\"}"}'
    layers = _decode_layers(text)
    assert layers[0].text == text
    # the escapes inside the literal are resolved; the literal's own quotes
    # are not escapes, so they stay
    assert layers[1].text == '{"blob": "{"api_key": "SECRET"}"}'
    origins = layers[1].starts
    assert text[origins[11]] == "\\"  # the decoded `"` came from `\"`
    # the value span on the layer maps back over the escaped quotes
    assert text[origins[22]:origins[30]] == r'\"SECRET\"'


def test_scrub_overlong_input_stands_down_only_the_class_mechanisms() -> None:
    # the bound is a work bound, not a coverage claim: above it the decode
    # layers and the structural walk stand down while the linear text rules
    # keep running, so the degrade is graceful and never silent.
    from hermes.research.corpus import CORPUS_MAX_BYTES
    from hermes.research.corpus_pack import _STRUCTURED_SCAN_MAX_CHARS

    assert _STRUCTURED_SCAN_MAX_CHARS > CORPUS_MAX_BYTES  # every governed doc
    overlong = "api_key=" + "x" * _STRUCTURED_SCAN_MAX_CHARS
    scrubbed = scrub_pack_text(overlong)
    assert scrubbed.startswith("api_key=<redacted>")   # text rules still run
    assert "x" * 16 not in scrubbed
    # at the bound itself the class mechanisms still apply
    at_bound = _escaped_nest('{"api_key": "SECRET-BOUND"}', 2)
    at_bound += " " * (_STRUCTURED_SCAN_MAX_CHARS - len(at_bound))
    assert len(at_bound) == _STRUCTURED_SCAN_MAX_CHARS
    assert "SECRET-BOUND" not in scrub_pack_text(at_bound)


# ── class 2: structural walk (recursive pairing on the parsed tree) ──


def test_scrub_sibling_split_walks_to_a_declarator_nested_deeper() -> None:
    # the depth-equality condition was the instance rule; the walk pairs a
    # declarator with a value at any level of the same root object.
    line = '{"meta": {"name": "api_key"}, "value": "SECRET-XYZ"}'
    assert scrub_pack_text(line) == (
        '{"meta": {"name": "api_key"}, "value": <redacted>}'
    )
    assert "SECRET-XYZ" not in scrub_pack_text(line)


def test_scrub_sibling_split_walks_to_a_value_under_a_bridging_member() -> None:
    # the declarator's own object has no value member, so the walk takes
    # the value members of the nearest descendant object that does.
    line = '{"name": "api_key", "value_holder": {"value": "SECRET-XYZ"}}'
    assert scrub_pack_text(line) == (
        '{"name": "api_key", "value_holder": {"value": <redacted>}}'
    )
    assert "SECRET-XYZ" not in scrub_pack_text(line)


def test_scrub_sibling_split_walks_three_levels_in_both_directions() -> None:
    declarator_deep = (
        '{"config": {"nested": {"deep": {"name": "api_key"}}}, '
        '"value": "SECRET-XYZ"}'
    )
    assert scrub_pack_text(declarator_deep) == (
        '{"config": {"nested": {"deep": {"name": "api_key"}}}, '
        '"value": <redacted>}'
    )
    value_deep = (
        '{"name": "api_key", "config": '
        '{"nested": {"deep": {"value": "SECRET-XYZ"}}}}'
    )
    assert "SECRET-XYZ" not in scrub_pack_text(value_deep)
    # the walk descends through arrays too — an array is not an object
    # boundary, it is just another container inside the same root
    through_array = (
        '{"items": [{"note": "x"}, {"name": "api_key"}], '
        '"value": "SECRET-XYZ"}'
    )
    assert "SECRET-XYZ" not in scrub_pack_text(through_array)


def test_scrub_sibling_split_walk_never_crosses_an_object_boundary() -> None:
    # the reach is ONE parsed tree, at every level: two separate roots are
    # not siblings — the O4_FIX4 lateral reach pairs WITHIN a root only,
    # and a document boundary is not a sibling transition
    assert scrub_pack_text('{"a": {"name": "api_key"}} {"b": {"value": "S"}}') \
        == '{"a": {"name": "api_key"}} {"b": {"value": "S"}}'


def test_scrub_sibling_split_walk_prefers_the_declarator_own_object() -> None:
    # when the declarator's own object carries a value member, that is the
    # pairing: a nested value under a NON-bridging member is not masked
    line = '{"name": "api_key", "meta": {"value": "X"}, "value": "SECRET-XYZ"}'
    assert scrub_pack_text(line) == (
        '{"name": "api_key", "meta": {"value": "X"}, "value": <redacted>}'
    )
    # a bridging member with no value field of the root's own is the
    # closure above, not a negative: the nested value IS the secret
    bridge = '{"name": "api_key", "meta": {"value": "X"}}'
    assert scrub_pack_text(bridge) == (
        '{"name": "api_key", "meta": {"value": <redacted>}}'
    )


def test_scrub_sibling_split_falls_back_to_text_rules_outside_json() -> None:
    # the fallback is the original text scan, byte-for-byte: a JSON
    # document embedded in prose is not a parseable document, so the
    # depth scan still does the work
    prose = 'see {"name": "api_key", "value": "SECRET-XYZ"} for the shape'
    assert scrub_pack_text(prose) == (
        'see {"name": "api_key", "value": <redacted>} for the shape'
    )
    assert scrub_pack_text('{"name": "api_key"} {"value": "S"}') == (
        '{"name": "api_key"} {"value": "S"}'
    )


# ── 4e. sibling split — the O4_FIX4 LATERAL reach (one tree, doc order) ──
#
# The reach that closed every prior round was vertical (the declarator's
# own object, then its descendants). O4_FIX4 adds the HORIZONTAL sweep:
# an object the descent leaves unpaired pairs with its SIBLING objects —
# children of the same parent, array elements included — in document
# order, the first unpaired declarator taking the first unpaired value
# field and each side pairing at most once. The whole reach stays inside
# ONE parsed tree; the text scan carries the same reach as a single
# closing+opening sibling transition at the declarator's depth, because
# text that is not a JSON document has no tree to walk.


def test_scrub_sibling_split_walks_across_sibling_branches_same_root() -> None:
    # the lateral shapes, declarator first, value field in a sibling
    # branch of the same root — including with a member in between and a
    # long flat chain: every one is one credential now
    ss = '{"a":{"name":"api_key"},"b":{"value":"SECRET-SS"}}'
    assert scrub_pack_text(ss) == '{"a":{"name":"api_key"},"b":{"value":<redacted>}}'
    assert "SECRET-SS" not in scrub_pack_text(ss)
    sm = '{"a":{"x":1},"b":{"name":"api_key"},"c":{"value":"SECRET-SM"}}'
    assert scrub_pack_text(sm) == (
        '{"a":{"x":1},"b":{"name":"api_key"},"c":{"value":<redacted>}}'
    )
    assert "SECRET-SM" not in scrub_pack_text(sm)
    se = '{"a":{"x":1},"c":{"value":"SECRET-SE"},"b":{"name":"api_key"}}'
    assert scrub_pack_text(se) == (
        '{"a":{"x":1},"c":{"value":<redacted>},"b":{"name":"api_key"}}'
    )
    assert "SECRET-SE" not in scrub_pack_text(se)
    sp = '{"a":{"name":"api_key"},"pad":"junk","b":{"value":"SECRET-SP"}}'
    assert scrub_pack_text(sp) == (
        '{"a":{"name":"api_key"},"pad":"junk","b":{"value":<redacted>}}'
    )
    assert "SECRET-SP" not in scrub_pack_text(sp)
    lc = '{"a":{"name":"api_key"},"x":1,"y":2,"z":3,"w":{"value":"SECRET-LC"}}'
    assert scrub_pack_text(lc) == (
        '{"a":{"name":"api_key"},"x":1,"y":2,"z":3,"w":{"value":<redacted>}}'
    )
    assert "SECRET-LC" not in scrub_pack_text(lc)


def test_scrub_sibling_split_walks_across_sibling_branches_reversed() -> None:
    # order is not part of the shape: the value field may lead and the
    # declarator follow, in sibling branches just as in one object
    sr = '{"a":{"value":"SECRET-SR"},"b":{"name":"api_key"}}'
    assert scrub_pack_text(sr) == '{"a":{"value":<redacted>},"b":{"name":"api_key"}}'
    assert "SECRET-SR" not in scrub_pack_text(sr)


def test_scrub_sibling_split_walks_across_sibling_branches_nested() -> None:
    # "sibling" is the parent, not the root: branches of a wrapper object
    # pair the same way as branches of the root
    ns = '{"wrap":{"a":{"name":"api_key"},"b":{"value":"SECRET-NS"}}}'
    assert scrub_pack_text(ns) == (
        '{"wrap":{"a":{"name":"api_key"},"b":{"value":<redacted>}}}'
    )
    assert "SECRET-NS" not in scrub_pack_text(ns)


def test_scrub_sibling_split_walks_across_sibling_branches_in_an_array() -> None:
    # array elements are siblings: a pair split across two elements of one
    # array is the same shape as a pair split across two members of one
    # object
    arr = '[{"name":"api_key"},{"value":"SECRET-AS"}]'
    assert scrub_pack_text(arr) == '[{"name":"api_key"},{"value":<redacted>}]'
    assert "SECRET-AS" not in scrub_pack_text(arr)


def test_scrub_sibling_split_lateral_tie_break_is_document_order() -> None:
    # deterministic, NOT nearest-wins: the first unpaired value field in
    # document order takes the declarator and the declarator is consumed
    # once — V2 stays
    line = '{"a":{"value":"V1"},"b":{"name":"api_key"},"c":{"value":"V2"}}'
    assert scrub_pack_text(line) == (
        '{"a":{"value":<redacted>},"b":{"name":"api_key"},"c":{"value":"V2"}}'
    )
    # order is not part of the shape — flip the sequence and the first
    # unpaired value field of the NEW document order wins
    flip = '{"c":{"value":"V2"},"b":{"name":"api_key"},"a":{"value":"V1"}}'
    assert scrub_pack_text(flip) == (
        '{"c":{"value":<redacted>},"b":{"name":"api_key"},"a":{"value":"V1"}}'
    )
    # discriminating shape: document order beats nearest — V1 is FIRST
    # even though V2 sits next to the declarator
    far = '{"a":{"value":"V1"},"c":{"value":"V2"},"d":{"name":"api_key"}}'
    assert scrub_pack_text(far) == (
        '{"a":{"value":<redacted>},"c":{"value":"V2"},"d":{"name":"api_key"}}'
    )


def test_scrub_sibling_split_text_scan_crosses_one_sibling_transition() -> None:
    # prose has no tree to walk, so the fallback carries the lateral reach:
    # ONE closing+opening brace pair at the declarator's own depth — the
    # step into a sibling branch and back — is crossed, both directions
    forward = 'see {"a": {"name": "api_key"}, "b": {"value": "SECRET-TS"}} here'
    assert scrub_pack_text(forward) == (
        'see {"a": {"name": "api_key"}, "b": {"value": <redacted>}} here'
    )
    backward = 'see {"a": {"value": "SECRET-TB"}, "b": {"name": "api_key"}} here'
    assert scrub_pack_text(backward) == (
        'see {"a": {"value": <redacted>}, "b": {"name": "api_key"}} here'
    )
    # a flat member (no object of its own) in between is still just the
    # one transition
    padded = (
        'see {"a": {"name": "api_key"}, "pad": "x", '
        '"b": {"value": "SECRET-TP"}} here'
    )
    assert scrub_pack_text(padded) == (
        'see {"a": {"name": "api_key"}, "pad": "x", '
        '"b": {"value": <redacted>}} here'
    )


def test_scrub_sibling_split_text_scan_stops_at_the_first_boundary() -> None:
    # exactly ONE transition: a second sibling branch in between is a
    # barrier, so the pairing does not reach across it
    twice = (
        'see {"a": {"name": "api_key"}, "x": {"k": 1}, '
        '"b": {"value": "SECRET-TW"}} here'
    )
    assert scrub_pack_text(twice) == twice
    # and a dip BELOW the declarator's own depth — the enclosing object
    # closed — ends the pairing at any depth, not only at the document roots
    deeper = 'insert {"a": {"name": "api_key"}} then {"value": "SECRET-TD"}'
    assert scrub_pack_text(deeper) == deeper


# ── class 3: separator normalization (one function, pinned) ──


def test_normalize_separators_folds_every_line_ending_spelling() -> None:
    from hermes.research.corpus_pack import _Layer, _normalize_separators

    text = "a\r\nb\rc\x0bd\x0ce"
    layer = _normalize_separators(_Layer(text, range(len(text) + 1)))
    assert layer.text == "a\nb\nc\nd\ne"
    # every folded character still points at the bytes that spelled it
    assert list(layer.starts) == [0, 1, 3, 4, 5, 6, 7, 8, 9, 10]
    # nothing to fold is handed back untouched (the identity layer)
    plain = _Layer("ab", range(3))
    assert _normalize_separators(plain) is plain


def test_scrub_fold_accepts_every_line_ending_spelling() -> None:
    # obs-fold (RFC 7230 3.2.4) names SP/HTAB as the continuation byte and
    # is silent on which spelling of a line ending precedes it, so a fold
    # written with a classic-Mac CR is the same credential as one with LF
    assert scrub_pack_text("Authorization:\r Bearer SECRET-XYZ") == (
        "Authorization: <redacted>"
    )
    assert scrub_pack_text("Authorization:\r\n Bearer SECRET-XYZ") == (
        "Authorization: <redacted>"
    )
    assert scrub_pack_text("Cookie:\r\tsession=abc123456") == (
        "Cookie: <redacted>"
    )
    # the sweep still stops at the first non-indented line, whatever the
    # separator was spelled with
    assert scrub_pack_text("Cookie:\r a=1;\r b=2\rnext: value") == (
        "Cookie: <redacted>\rnext: value"
    )


def test_scrub_fold_blank_line_is_still_a_hard_delimiter() -> None:
    # THE PRINCIPLE: folding normalizes the SPELLING of a line ending, not
    # the number of line endings. A blank line is still a hard delimiter —
    # no grammar unfolds across an empty line, so the continuation never
    # merges into a second credential.
    assert scrub_pack_text("Authorization:\n\nBearer SECRET-XYZ") == (
        "Authorization:\n\nBearer SECRET-XYZ"
    )
    assert scrub_pack_text("Authorization:\r\n\r\nBearer SECRET-XYZ") == (
        "Authorization:\r\n\r\nBearer SECRET-XYZ"
    )
    # a vertical tab or form feed is not a fold byte: after folding it is a
    # line ending, so a continuation behind it is the blank-line case
    assert scrub_pack_text("Authorization:\n\x0bBearer SECRET-XYZ") == (
        "Authorization:\n\x0bBearer SECRET-XYZ"
    )
    assert scrub_pack_text("Authorization:\x0c Bearer SECRET-XYZ") == (
        "Authorization: <redacted>"
    )


def test_scrub_fold_writes_the_mask_back_to_the_original_bytes() -> None:
    # the fold span is matched on a normalized copy but written back to the
    # ORIGINAL bytes, so a document whose separators are CRLF keeps them
    # everywhere the fold did not reach
    text = "line one\r\nline two\r\nAuthorization: Bearer\r\n SECRET-XYZ\r\n"
    assert scrub_pack_text(text) == (
        "line one\r\nline two\r\nAuthorization: <redacted>\r\n"
    )
    # prose that merely wraps is untouched by every spelling
    wrapped = "The pipeline reads the corpus\r\n  and never writes it.\r\n"
    assert scrub_pack_text(wrapped) == wrapped


# ── class 4: the three recorded limits, pinned where they are observable ──


def test_bare_unknown_secrets_are_the_measured_residual() -> None:
    # MEASURED LIMIT (82%): the battery below is every spelling the module
    # claims (41 lines: credential-alias assignments, quoted-key, escaped
    # JSON at three depths and the \u0022 spelling, credential-class
    # headers, obs-folded headers, sibling splits, and the standalone
    # value shapes) plus 9 bare-unknown secrets that carry neither a
    # credential NAME nor a recognized VALUE shape. The named 41 are all
    # masked; the bare 9 all survive, and they survive BY CONSTRUCTION —
    # that is the honest limit the S6 scanner documents for itself. A rule
    # that widened to catch them would have to mask ordinary data.
    named = (
        ("api_key=SECRET-A1", "SECRET-A1"),
        ("api_key: SECRET-A2", "SECRET-A2"),
        ("API_KEY = SECRET-A3", "SECRET-A3"),
        ("x-api-key: SECRET-A4", "SECRET-A4"),
        ("access_token=SECRET-A5", "SECRET-A5"),
        ("client_secret: SECRET-A6", "SECRET-A6"),
        ("password=SECRET-A7", "SECRET-A7"),
        ("auth: SECRET-A8", "SECRET-A8"),
        ('{"api_key": "SECRET-Q1", "port": 1}', "SECRET-Q1"),
        ('{"token" : "SECRET-Q2"}', "SECRET-Q2"),
        ("{'secret': 'SECRET-Q3'}", "SECRET-Q3"),
        ('{"x-api-key":"SECRET-Q4"}', "SECRET-Q4"),
        ('config = {"password": "SECRET-Q5"}', "SECRET-Q5"),
        ('{"signature": "SECRET-Q6"}', "SECRET-Q6"),
        ('{"access_token": "SECRET-Q7"}', "SECRET-Q7"),
        (_escaped_nest('{"api_key": "SECRET-E1"}', 1), "SECRET-E1"),
        (_escaped_nest('{"api_key": "SECRET-E2"}', 2), "SECRET-E2"),
        (_escaped_nest('{"api_key": "SECRET-E3"}', 3), "SECRET-E3"),
        (r'{"blob": "{\u0022api_key\u0022: \u0022SECRET-E4\u0022}"}', "SECRET-E4"),
        ("Authorization: Bearer SECRET-H1", "SECRET-H1"),
        ("Proxy-Authorization: Basic SECRET-H2", "SECRET-H2"),
        ("Set-Cookie: session=SECRET-H3; Path=/", "SECRET-H3"),
        ("Cookie: session=SECRET-H4", "SECRET-H4"),
        ("Authorization:\n Bearer SECRET-F1", "SECRET-F1"),
        ("Authorization:\r Bearer SECRET-F2", "SECRET-F2"),
        ("Authorization:\r\n Bearer SECRET-F3", "SECRET-F3"),
        ("Cookie:\n a=SECRET-F4", "SECRET-F4"),
        ('{"name": "api_key", "value": "SECRET-S1"}', "SECRET-S1"),
        ('{"value": "SECRET-S2", "name": "token"}', "SECRET-S2"),
        ('{"meta": {"name": "api_key"}, "value": "SECRET-S3"}', "SECRET-S3"),
        ('{"name": "api_key", "value_holder": {"value": "SECRET-S4"}}',
         "SECRET-S4"),
        ('{"field": "token", "secret": "SECRET-S5"}', "SECRET-S5"),
        ("token sk-abcdefghij1234567890", "sk-abcdefghij1234567890"),
        ("ghp_" + "a" * 36, "ghp_" + "a" * 36),
        ("AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        (("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
          "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"),
         "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"),
        (("-----BEGIN RSA PRIVATE KEY-----\nMIIBordo0\n"
          "-----END RSA PRIVATE KEY-----"), "MIIBordo0"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIBordo0MIIBordo0",
         "MIIBordo0MIIBordo0"),
        ("xoxb-123-abc", "xoxb-123-abc"),
        ("ops@example.com", "ops@example.com"),
        ("api_key: 'SECRET-Q8'", "SECRET-Q8"),
    )
    bare = (
        ("note = 7f3d9a2c1b8e4f6a", "7f3d9a2c1b8e4f6a"),
        ("the passphrase is Umbrella42!stable", "Umbrella42!stable"),
        ("id: 4821-9930-7741", "4821-9930-7741"),
        ("pin = 8814", "8814"),
        ('{"result": "qP7zLmXvT2"}', "qP7zLmXvT2"),
        ("session_ref: 9d0f1c77aa", "9d0f1c77aa"),
        ("cred = Zx!42pl-ok", "Zx!42pl-ok"),
        ('{"data": "R7kQ2mN9"}', "R7kQ2mN9"),
        ("license = HG-3391-QQ-88", "HG-3391-QQ-88"),
    )
    assert len(named) == 41 and len(bare) == 9
    for line, secret in named:
        assert secret not in scrub_pack_text(line), line
    for line, secret in bare:
        assert secret in scrub_pack_text(line), line
    # 41 of 50 masked is the measured coverage; the other 9 are the
    # bare-unknown residual, and the fraction is pinned here so a rule
    # change that silently widens (or narrows) it has to be deliberate
    masked = sum(
        1 for line, secret in (*named, *bare)
        if secret not in scrub_pack_text(line)
    )
    assert masked == 41
    assert 100 * masked // 50 == 82


def test_split_secret_reassembly_is_out_of_contract() -> None:
    # STATED OUT OF CONTRACT: a secret spelled in pieces that no rule the
    # module owns joins is not reassembled. The decode and normalization
    # mechanisms remove ESCAPING and SEPARATOR spelling, never content, so
    # they cannot manufacture an adjacency the bytes do not carry.
    pieces = '{"first": "sec", "second": "ret-XYZ"}'
    assert scrub_pack_text(pieces) == pieces
    # the same piece pair joined by an escape the decode layer resolves
    # IS masked — the mechanism removes spelling, not content
    joined = '{"blob": "{\\"first\\": \\"sec\\", \\"api_key\\": \\"ret-XYZ\\"}"}'
    assert "ret-XYZ" not in scrub_pack_text(joined)


def test_apostrophe_pairing_misses_inward_never_onto_another_object() -> None:
    # STATED DIRECTION: the structural scan is string-aware and a prose
    # apostrophe can open a spurious string, which can only make a
    # candidate look OUTSIDE its object — a MISSED mask, never a mask on
    # the wrong object. The prose keeps every byte it owns.
    prose = "the caller's note: it's the value field's value, and \"that's\" it"
    assert scrub_pack_text(prose) == prose
    # a real pair inside a JSON document still masks, and masks only the
    # value at its own level
    line = '{"name": "api_key", "note": "it\'s fine", "value": "SECRET-XYZ"}'
    assert scrub_pack_text(line) == (
        '{"name": "api_key", "note": "it\'s fine", "value": <redacted>}'
    )


def test_o4fix3_shapes_never_reach_unpacked_pack_bytes() -> None:
    # the O4_FIX3 class proof, end to end: a synthetic governed doc
    # carrying every family's escaping must ship none of them on any
    # emitted surface
    markers = (
        "SECRET-ESC1", "SECRET-ESC2", "SECRET-ESC3", "SECRET-U",
        "SECRET-FOLD", "SECRET-SIB", "SECRET-DEEP",
    )
    body = (
        _escaped_nest('{"api_key": "SECRET-ESC1"}', 1) + "\n"
        + _escaped_nest('{"api_key": "SECRET-ESC2"}', 2) + "\n"
        + _escaped_nest('{"api_key": "SECRET-ESC3"}', 3) + "\n"
        + r'{"blob": "{\u0022api_key\u0022: \u0022SECRET-U\u0022}"}' + "\n"
        + "Authorization:\r Bearer SECRET-FOLD\n"
        + '{"meta": {"name": "api_key"}, "value": "SECRET-SIB"}\n'
        + '{"name": "api_key", "value_holder": {"value": "SECRET-DEEP"}}\n'
    )
    pack = assemble_pack("p1", (_doc("AGENTS.md", body),), budget_tokens=1000)
    assert pack.skipped == ()
    blob = pack_bytes(pack).decode("utf-8")
    surfaces = blob + json.dumps(pack_mapping(pack)) + repr(pack) + repr(pack.items)
    for marker in markers:
        assert marker not in surfaces
    assert "<redacted>" in blob


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        (
            "The quick brown fox cites AGENTS.md twice (see section 3 and section 3).",
            "The quick brown fox cites AGENTS.md twice (see section 3 and section 3).",
        ),
        (
            "the reverse proxy sets Cookie and Authorization itself.",
            "the reverse proxy sets Cookie and Authorization itself.",
        ),
        (
            "monkey=banana and monkey: banana keep both their bytes.",
            "monkey=banana and monkey: banana keep both their bytes.",
        ),
        ('{"monkey": "banana", "port": 1}', '{"monkey": "banana", "port": 1}'),
        (
            "aGVsbG8.d29ybGQ is not a JWT; eyJhbGciOiJIUzI1NiJ9 is not one either.",
            "aGVsbG8.d29ybGQ is not a JWT; eyJhbGciOiJIUzI1NiJ9 is not one either.",
        ),
        (
            "The scanner matches -----BEGIN RSA PRIVATE KEY----- only in prose.",
            "The scanner matches <redacted> only in prose.",
        ),
        (
            "The pipeline reads the corpus\n  and never writes it.\nSecond paragraph.",
            "The pipeline reads the corpus\n  and never writes it.\nSecond paragraph.",
        ),
        (
            (
                "- the key and the value fields are siblings\n"
                "- the name field is a declarator\n"
            ),
            (
                "- the key and the value fields are siblings\n"
                "- the name field is a declarator\n"
            ),
        ),
        (
            'A JSON object like {"port": 1, "host": "example.invalid"} is untouched.',
            'A JSON object like {"port": 1, "host": "example.invalid"} is untouched.',
        ),
        (
            "See the Authorization: header section of the docs for the schemes.",
            "See the Authorization: <redacted>",
        ),
    ),
)
def test_scrub_prose_battery_unchanged_by_the_new_rules(text: str, expected: str) -> None:
    # the over-masking battery: ten prose/JSON lines whose scrub bytes are
    # exactly what the pre-round module produced. The new rules must not
    # move a single byte of them — including a wrapped paragraph, which the
    # fold tolerance deliberately leaves alone (it matches the folded SPAN
    # in the original text, never a normalized copy of the document).
    assert scrub_pack_text(text) == expected


def test_o4fix2_shapes_never_reach_unpacked_pack_bytes() -> None:
    # the O4_FIX2 leak proof, end to end: a synthetic governed doc carrying
    # the three new shapes must ship none of them on any emitted surface
    markers = ("SECRET-XYZ", "SECRET-FOLD", "SECRET-SIB")
    body = (
        r'{"blob": "{\"api_key\": \"SECRET-XYZ\"}"}' + "\n"
        "Authorization:\n Bearer SECRET-FOLD\n"
        '{"name": "api_key", "value": "SECRET-SIB"}\n'
    )
    pack = assemble_pack("p1", (_doc("AGENTS.md", body),), budget_tokens=1000)
    assert pack.skipped == ()
    blob = pack_bytes(pack).decode("utf-8")
    surfaces = blob + json.dumps(pack_mapping(pack)) + repr(pack) + repr(pack.items)
    for marker in markers:
        assert marker not in surfaces
    assert "<redacted>" in blob


def test_new_scrub_shapes_never_reach_unpacked_pack_bytes() -> None:
    # the O4_REDTEAM item 3 leak proof, re-run against the fixed rules: a
    # synthetic governed doc carrying all five shapes must ship none of them
    # on any emitted surface
    markers = (
        "SECRETJSON123",
        "session=abcdef1234567890",
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0",
        "MIIBordo0MIIBordo0",
        "PRIVATE KEY",
    )
    body = (
        '{"api_key": "SECRETJSON123", "port": 1}\n'
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV\n"
        "Set-Cookie: session=abcdef1234567890; Path=/\n"
        "the client inlines eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        " here\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIBordo0MIIBordo0MIIBordo0MIIBordo0\n"
    )
    pack = assemble_pack("p1", (_doc("AGENTS.md", body),), budget_tokens=1000)
    assert pack.skipped == ()
    blob = pack_bytes(pack).decode("utf-8")
    surfaces = blob + json.dumps(pack_mapping(pack)) + repr(pack) + repr(pack.items)
    for marker in markers:
        assert marker not in surfaces
    assert "<redacted>" in blob


def test_no_secret_reaches_unpacked_pack_bytes() -> None:
    markers = (
        "SECRET123",
        "hunter2",
        "sk-abcdefghij1234567890",
        "ghp_" + "b" * 36,
        "AKIAIOSFODNN7EXAMPLE",
        "MIIBo38sd9a",
        "xoxb-123-abc",
        "ops@example.com",
    )
    body = (
        "api_key=SECRET123\nX-Api-Key: hunter2\n"
        "sk-abcdefghij1234567890\nghp_" + "b" * 36 + "\n"
        "AKIAIOSFODNN7EXAMPLE\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIBo38sd9a\n"
        "-----END RSA PRIVATE KEY-----\n"
        "xoxb-123-abc\nops@example.com\n"
    )
    pack = assemble_pack("p1", (_doc("AGENTS.md", body),), budget_tokens=10000)
    assert len(pack.items) == 1
    raw = pack_bytes(pack)
    for marker in markers:
        assert marker.encode("utf-8") not in raw
    assert "PRIVATE KEY" not in raw.decode("utf-8")


# ── 5. budget exactness ──


def test_budget_exact_fit_boundary() -> None:
    pack = assemble_pack(
        "p1",
        (_doc("AGENTS.md", "aaaa"), _doc("docs/API.md", "bbbbbbbb")),
        budget_tokens=3,
    )
    assert [i.corpus_ref for i in pack.items] == ["AGENTS.md", "docs/API.md"]
    assert pack.skipped == ()
    assert 3 == pack.used_tokens == pack.budget_tokens


def test_budget_overflow_skips_with_exact_reasons() -> None:
    pack = assemble_pack(
        "p1",
        (
            _doc("AGENTS.md", "aaaa"),  # 1 token
            _doc("docs/API.md", "bbbbbbbb"),  # 2 tokens
            _doc("docs/STATE.md", "cccccccccccc"),  # 3 tokens
        ),
        budget_tokens=3,
    )
    assert [i.corpus_ref for i in pack.items] == ["AGENTS.md", "docs/API.md"]
    assert pack.used_tokens == 3
    assert [(s.corpus_ref, s.tokens_needed, s.reason) for s in pack.skipped] == [
        ("docs/STATE.md", 3, REASON_OVER_BUDGET)
    ]


def test_item_exceeding_whole_budget_skipped_not_refused() -> None:
    pack = assemble_pack("p1", (_doc("AGENTS.md", "a" * 41),), budget_tokens=10)
    assert pack.items == ()
    assert [(s.corpus_ref, s.tokens_needed, s.reason) for s in pack.skipped] == [
        ("AGENTS.md", 11, REASON_ITEM_EXCEEDS_BUDGET)
    ]
    assert pack.used_tokens == 0


def test_duplicate_ref_skipped_not_double_counted() -> None:
    pack = assemble_pack(
        "p1",
        (
            FetchedDoc(corpus_ref="AGENTS.md", content=b"aaaa"),
            FetchedDoc(corpus_ref="AGENTS.md", content=b"bbbb"),
        ),
        budget_tokens=100,
    )
    assert [i.corpus_ref for i in pack.items] == ["AGENTS.md"]
    assert [(s.corpus_ref, s.reason) for s in pack.skipped] == [
        ("AGENTS.md", REASON_DUPLICATE_REF)
    ]
    assert pack.used_tokens == 1


def test_used_tokens_is_the_exact_sum() -> None:
    pack = assemble_pack(
        "p1",
        (_doc("AGENTS.md", "aaaa"), _doc("docs/API.md", "bbbb")),
        budget_tokens=100,
    )
    assert 2 == pack.used_tokens == sum(i.tokens for i in pack.items)


@pytest.mark.parametrize("bad_budget", [0, -5, True])
def test_budget_must_be_positive_int(bad_budget: int) -> None:
    with pytest.raises(PackRefusal) as exc:
        assemble_pack("p1", (_doc("AGENTS.md", "a"),), budget_tokens=bad_budget)
    assert exc.value.code == MALFORMED_PAYLOAD


def test_default_budget_is_pinned() -> None:
    assert DEFAULT_PACK_BUDGET_TOKENS == 2000
    pack = assemble_pack("p1", (_doc("AGENTS.md", "a"),))
    assert pack.budget_tokens == 2000


def test_assemble_rejects_undecodable_and_foreign() -> None:
    with pytest.raises(PackRefusal) as exc:
        assemble_pack(
            "p1",
            (FetchedDoc(corpus_ref="AGENTS.md", content=b"\xff\xfe"),),
            budget_tokens=100,
        )
    assert exc.value.code == MALFORMED_PAYLOAD
    with pytest.raises(PackRefusal) as exc:
        assemble_pack("p1", (_doc("nope.md", "a"),), budget_tokens=100)
    assert exc.value.code == MALFORMED_PAYLOAD


# ── 6. citations + partition ──


def test_citation_shape_and_bad_inputs() -> None:
    digest = "ab" * 32
    assert f"pack:p1:{digest}" == make_citation("p1", digest)
    with pytest.raises(PackRefusal) as exc:
        make_citation("p1", "short")
    assert exc.value.code == MALFORMED_PAYLOAD
    with pytest.raises(PackRefusal) as exc:
        make_citation("", digest)
    assert exc.value.code == MALFORMED_PAYLOAD


def test_partition_same_project_passes() -> None:
    assert check_pack_partition(f"pack:p1:{'ab' * 32}", "p1") is None


def test_partition_cross_project_refuses() -> None:
    with pytest.raises(PackRefusal) as exc:
        check_pack_partition(f"pack:p1:{'ab' * 32}", "p2")
    assert exc.value.code == EVIDENCE_DOES_NOT_RESOLVE


def test_partition_malformed_citation_refuses() -> None:
    for bad in ("evidence:abc", "pack:p1", "pack::abc", "pack:p1:a:b", ""):
        with pytest.raises(PackRefusal) as exc:
            check_pack_partition(bad, "p1")
        assert exc.value.code == MALFORMED_PAYLOAD


def test_pack_object_partition() -> None:
    pack = assemble_pack("p1", (_doc("AGENTS.md", "a"),), budget_tokens=100)
    assert check_pack_project(pack, "p1") is None
    with pytest.raises(PackRefusal) as exc:
        check_pack_project(pack, "p2")
    assert exc.value.code == EVIDENCE_DOES_NOT_RESOLVE


def test_refusal_codes_are_frozen() -> None:
    # "RATIONALE" is the controller's inline literal (no module binds
    # the name — capability-plane ownership rule); the other two are
    # mirrored constants.
    assert frozenset({"RATIONALE", MALFORMED_PAYLOAD, EVIDENCE_DOES_NOT_RESOLVE}) == (
        FROZEN_PACK_REFUSAL_CODES
    )
    with pytest.raises(ValueError):
        PackRefusal("NEW_CODE", "must never exist")


# ── 7. determinism ──


def test_pack_bytes_deterministic_100x() -> None:
    fetched = (
        _doc("docs/STATE.md", "gamma gamma"),
        _doc("AGENTS.md", "alpha  \n\nbeta"),
        _doc("docs/API.md", '{"b": 2, "a": 1}'),
    )
    first = assemble_pack("p1", fetched, budget_tokens=100)
    first_bytes = pack_bytes(first)
    first_id = pack_id(first)
    for _ in range(100):
        again = assemble_pack("p1", fetched, budget_tokens=100)
        assert pack_bytes(again) == first_bytes
        assert pack_id(again) == first_id


def test_live_corpus_double_assembly_identical() -> None:
    first_docs = fetch_pack_docs(REPO_ROOT, "p1", recall("p1"))
    second_docs = fetch_pack_docs(REPO_ROOT, "p1", recall("p1"))
    first = assemble_pack("p1", first_docs, budget_tokens=100000)
    second = assemble_pack("p1", second_docs, budget_tokens=100000)
    assert pack_bytes(first) == pack_bytes(second)
    assert pack_id(first) == pack_id(second)
    assert len(first.items) == 12
    assert first.skipped == ()


def test_pack_id_is_sha_of_pack_bytes() -> None:
    pack = assemble_pack("p1", (_doc("AGENTS.md", "a"),), budget_tokens=100)
    assert hashlib.sha256(pack_bytes(pack)).hexdigest() == pack_id(pack)
    assert json.loads(pack_bytes(pack).decode("utf-8")) == dict(pack_mapping(pack))


def test_advisory_markers_pinned() -> None:
    assert ADVISORY_CONSUMPTION == "ADVISORY"
    assert PACK_AUTHORITY == "NONE"
    assert PACK_VERSION == "1"
    assert PACK_REF_PREFIX == "pack"
    assert CORPUS_PACK_KIND == "corpus_pack_item"
    mapping = dict(
        pack_mapping(assemble_pack("p1", (_doc("AGENTS.md", "a"),), budget_tokens=10))
    )
    assert mapping["advisory_only"] is True
    assert mapping["authority"] == "NONE"
    assert mapping["consumption"] == "ADVISORY"


# ── 8. advisory boundary: inadmissible as evidence ──


def test_pack_citation_resolves_to_nothing(db) -> None:
    pack = assemble_pack("p1", (_doc("AGENTS.md", "alpha"),), budget_tokens=100)
    citation = pack.items[0].citation
    assert not citation.startswith("evidence:")
    assert _cx_resolve_evidence_ref(db, "p1", citation) is None
    assert detector_resolve_ref(db, "p1", citation) is None
    assert set() == _l2_resolve_ref_to_artifacts(db, citation)


def test_pack_content_hash_admissible_nowhere(db) -> None:
    pack = assemble_pack("p1", (_doc("AGENTS.md", "alpha"),), budget_tokens=100)
    content_hash = pack.items[0].source_hash
    assert _cx_resolve_evidence_ref(db, "p1", f"evidence:{content_hash}") is None
    assert detector_resolve_ref(db, "p1", f"evidence:{content_hash}") is None
    assert set() == _l2_resolve_ref_to_artifacts(db, f"evidence:{content_hash}")


def test_pack_kind_outside_every_evidence_taxonomy() -> None:
    assert CORPUS_PACK_KIND not in SOURCE_ARTIFACT_TYPES
    assert isinstance(pack_bytes(
        assemble_pack("p1", (_doc("AGENTS.md", "a"),), budget_tokens=10)
    ), bytes)


def test_assembly_writes_zero_rows_and_zero_events(db) -> None:
    before = _counts(db)
    docs = fetch_pack_docs(REPO_ROOT, "p1", recall("p1"))
    pack = assemble_pack("p1", docs, budget_tokens=100000)
    _ = pack_bytes(pack)
    _ = pack_id(pack)
    assert before == _counts(db)


# ── 9. no-wire proof ──


def test_nothing_outside_module_and_test_references_pack() -> None:
    src_hits = [
        path
        for path in sorted((REPO_ROOT / "src").rglob("*.py"))
        if path.name != "corpus_pack.py"
        and "corpus_pack" in path.read_text(encoding="utf-8")
    ]
    assert src_hits == []
    test_hits = [
        path
        for path in sorted((REPO_ROOT / "tests").rglob("*.py"))
        if path.name != "test_corpus_pack.py"
        and "corpus_pack" in path.read_text(encoding="utf-8")
    ]
    assert test_hits == []
    assert isinstance(recall("p1"), tuple)
