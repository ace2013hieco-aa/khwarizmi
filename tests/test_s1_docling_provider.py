"""S1 golden fixtures — the docling provider behind the trust boundary (spike).

Pass criterion (adoption §5, S1): every extracted claim span resolves to page
plus location; table cells round-trip; re-running gives identical structure for
identical input.

Everything is proven against the recorded real-paper fixtures in
``tests/fixtures/s1_docling/`` (four vendored papers, captured 2026-10-01).
The hermetic tests need no docling installed; the live test re-converts the
vendored PDFs when the exact pinned docling is present (spike venv) and skips
with a reason otherwise — a different version never substitutes.

Honesty notes carried by the fixtures themselves:

- ``runs`` records two separate-process digests plus the *raw* field diff
  between those runs. The digest is computed over coordinates quantized to
  ``COORD_DECIMALS`` (0.001 pt) because docling's model pipeline was observed
  emitting a table-region bbox differing by ~2e-5 pt between processes on one
  of the four papers; any recorded raw difference must therefore be a
  sub-quantum coordinate float (asserted below).
- claim surrogates are selected by deterministic rules documented in
  ``scripts/s1_docling_record.py`` — no model extraction ran in the spike.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
from pathlib import Path
from typing import Any

import pytest

from hermes.research.claims import (
    ExtractionDraft,
    ResearchClaimDraft,
    validate_extraction,
)
from hermes.security.boundaries import UntrustedContent
from hermes.tools.providers.docling_provider import (
    COORD_DECIMALS,
    DOCLING_PIN,
    RECORD_VERSION,
    DoclingConfig,
    DoclingDocument,
    DoclingTable,
    DoclingUnavailableError,
    convert_pdf,
    resolver_for,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "s1_docling"
PAPERS_DIR = FIXTURE_DIR / "papers"
MANIFEST_PATH = FIXTURE_DIR / "MANIFEST.json"
FIXTURE_FILES = sorted(
    path for path in FIXTURE_DIR.glob("*.json")
    if path.name != "MANIFEST.json")
FIXTURE_IDS = [path.stem for path in FIXTURE_FILES]


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rebuilt(fixture: dict[str, Any]) -> DoclingDocument:
    return DoclingDocument.from_record(fixture["record"])


def _draft(source_ref: str, span_ref: str) -> ExtractionDraft:
    return ExtractionDraft(
        source_ref=source_ref,
        claims=(ResearchClaimDraft(
            ref="c1",
            statement="s1 fixture claim surrogate",
            source_ref=source_ref,
            support_state="DIRECT",
            span_ref=span_ref,
            claim_type="descriptive",
            context_tags={},
            assumption_refs=(),
            related_claims=(),
        ),),
        assumptions=(),
        extracted_by="spike:s1-docling",
    )


def _pinned_docling_available() -> bool:
    try:
        return importlib.metadata.version("docling") == DOCLING_PIN
    except importlib.metadata.PackageNotFoundError:
        return False


# ── boundary discipline ──


def test_pin_is_an_exact_version():
    assert DOCLING_PIN == "2.131.0"
    assert re.fullmatch(r"\d+\.\d+\.\d+", DOCLING_PIN)


def test_provider_module_is_the_only_docling_importer():
    """Adoption §4 rule 1: the library lives in one module, imported nowhere
    else in ``src/`` — and that module never imports it statically (lazy,
    version-checked resolution only).

    The controller imports the provider module for the EXTRACT wiring
    (docling_resolver_for / DoclingDocument) — this is the designated
    integration point for HR-05 span dereference. The third-party `docling`
    library itself is still only imported in the provider module.
    """
    src = Path(__file__).resolve().parents[1] / "src"
    provider_rel = Path("hermes/tools/providers/docling_provider.py")
    # Controller imports provider for EXTRACT wiring (HR-05 span dereference)
    allowed_provider_importers = {"hermes/research/controller.py", "hermes\\research\\controller.py"}
    offenders: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src)
        text = path.read_text(encoding="utf-8")
        if rel != provider_rel:
            if re.search(r"^\s*(?:from|import)\s+docling\b", text, re.M):
                offenders.append(str(rel))
            if "docling_provider" in text and str(rel) not in allowed_provider_importers:
                offenders.append(f"{rel} (imports the provider module)")
    assert offenders == []
    provider_text = (src / provider_rel).read_text(encoding="utf-8")
    # no static import statement, even in the provider module itself — the
    # resolution is lazy via importlib (see _load_docling)
    assert not re.search(r"^\s*(?:from|import)\s+docling\b", provider_text,
                         re.M)


def test_provider_module_has_no_core_or_persistence_surface():
    """The wrapper is a leaf: no trusted-state, DB or intent-gateway imports."""
    provider = (Path(__file__).resolve().parents[1] / "src" / "hermes" /
                "tools" / "providers" / "docling_provider.py")
    text = provider.read_text(encoding="utf-8")
    for forbidden in ("hermes.research", "hermes.persistence", "sqlite3",
                      "apply_intent"):
        assert forbidden not in text


def test_absent_or_mismatched_docling_fails_closed(monkeypatch):
    fixture = load_fixture(FIXTURE_FILES[0])
    pdf = PAPERS_DIR / fixture["paper"]["filename"]
    real_version = importlib.metadata.version

    def mismatched(name: str) -> str:
        if name == "docling":
            return "0.0.0-not-the-pin"
        return real_version(name)

    monkeypatch.setattr(importlib.metadata, "version", mismatched)
    with pytest.raises(DoclingUnavailableError):
        convert_pdf(pdf, source_ref="source_payload:s1-docling/fail-closed")

    def absent(name: str) -> str:
        if name == "docling":
            raise importlib.metadata.PackageNotFoundError(name)
        return real_version(name)

    monkeypatch.setattr(importlib.metadata, "version", absent)
    with pytest.raises(DoclingUnavailableError):
        convert_pdf(pdf, source_ref="source_payload:s1-docling/fail-closed")


# ── fixtures: provenance, bounds, rerun identity ──


@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=FIXTURE_IDS)
def test_fixture_provenance_and_rerun_identity(fixture_path: Path):
    fixture = load_fixture(fixture_path)
    assert fixture["fixture_version"] == "s1-docling-fixture/1"
    paper = fixture["paper"]
    raw = (PAPERS_DIR / paper["filename"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == paper["sha256"]
    assert len(raw) == paper["bytes"]

    doc = rebuilt(fixture)
    prov = doc.provenance
    assert fixture["record"]["record_version"] == RECORD_VERSION
    assert prov.library == "docling"
    assert prov.version == DOCLING_PIN
    assert prov.config_fingerprint == prov.config.fingerprint
    assert prov.pdf_sha256 == paper["sha256"]
    assert doc.content.origin == "docling.pdf"
    assert doc.content.ref == prov.source_ref
    assert prov.page_count == len(prov.page_sizes) >= 1
    assert all(width > 0 and height > 0 for width, height in prov.page_sizes)
    assert prov.span_count == len(doc.spans)
    assert prov.size_bytes() <= 4096

    runs = fixture["runs"]
    assert runs["rerun_identical"] is True
    assert runs["digest_a"] == runs["digest_b"]
    assert runs["payload_sha256_a"] == runs["payload_sha256_b"]
    assert runs["digest_a"] == doc.structure_digest()
    assert runs["payload_sha256_a"] == doc.payload_sha256()

    diffs = runs["raw_differences"]
    assert (runs["raw_difference_count"] == len(diffs)
            or runs["raw_difference_count"] > 64)
    for diff in diffs:
        a, b = diff["a"], diff["b"]
        assert isinstance(a, (int, float)) and isinstance(b, (int, float)), diff
        assert abs(a - b) <= 10 ** (-COORD_DECIMALS), diff
        assert round(a, COORD_DECIMALS) == round(b, COORD_DECIMALS), diff


# ── pass criterion: every claim span resolves to page + location ──


@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=FIXTURE_IDS)
def test_every_claim_resolves_to_page_bbox_and_charspan(fixture_path: Path):
    fixture = load_fixture(fixture_path)
    doc = rebuilt(fixture)
    payload = doc.payload
    assert len(fixture["claims"]) >= 4
    for claim in fixture["claims"]:
        quote = claim["quote"]
        located = doc.locate(quote)
        assert located, f"claim {claim['id']} did not resolve"
        first = located[0]
        assert payload[first.char_start:first.char_end] == quote
        expected = claim["span"]
        assert first.span.page == expected["page"] >= 1
        assert list(first.span.bbox) == expected["bbox"]
        assert first.span.coord_origin == expected["coord_origin"]
        assert first.span.kind == expected["kind"]
        page_w, page_h = doc.provenance.page_sizes[first.span.page - 1]
        left, top, right, bottom = first.span.bbox
        assert left <= right
        origin = first.span.coord_origin
        if "BOTTOMLEFT" in origin:
            assert bottom <= top  # y grows upward
        elif "TOPLEFT" in origin:
            assert top <= bottom  # y grows downward
        else:
            pytest.fail(f"unknown bbox coord origin {origin!r}")
        assert left >= -5.0 and right <= page_w + 5.0
        assert min(top, bottom) >= -5.0
        assert max(top, bottom) <= page_h + 5.0


@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=FIXTURE_IDS)
def test_negatives_and_wrong_source_ref_refuse(fixture_path: Path):
    fixture = load_fixture(fixture_path)
    doc = rebuilt(fixture)
    resolve = resolver_for(doc)
    assert len(fixture["negative_claims"]) >= 2
    for negative in fixture["negative_claims"]:
        quote = negative["quote"]
        assert doc.locate(quote) == (), negative["id"]
        assert resolve(doc.content.ref, quote) is False, negative["id"]
    positive = doc.span_ref_for(fixture["claims"][0]["quote"])
    assert positive.startswith("span:")
    assert resolve(doc.content.ref, positive) is True
    assert resolve("source_payload:not-this-document", positive) is False
    assert resolve(doc.content.ref, "") is False
    for word in ("T", "the", "a", "and", "of", "in", "is", "to"):
        assert resolve(doc.content.ref, word) is False, word
    parts = positive.split(":")
    forged = f"span:{parts[1]}:{int(parts[2]) + 1}:{parts[3]}"
    assert resolve(doc.content.ref, forged) is False, "forged charspan"


@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=FIXTURE_IDS)
def test_validate_extraction_seam_admits_and_refuses(fixture_path: Path):
    """The provider resolves through the certified HR-05 protocol callable —
    no writes, no controller wiring, admission decided by validate_extraction.
    Per AUDIT-S1 A1, only the document's own digest-anchored span token
    admits: bare substrings ("T", "the") refuse with dangling_span_ref."""
    fixture = load_fixture(fixture_path)
    doc = rebuilt(fixture)
    resolve = resolver_for(doc)
    good = validate_extraction(
        _draft(doc.content.ref, doc.span_ref_for(
            fixture["claims"][0]["quote"])),
        span_resolver=resolve)
    assert good.admitted, [error.code for error in good.errors]
    bad = validate_extraction(
        _draft(doc.content.ref, fixture["negative_claims"][0]["quote"]),
        span_resolver=resolve)
    assert not bad.admitted
    assert "dangling_span_ref" in {error.code for error in bad.errors}
    for word in ("T", "the", "a", "and", "of"):
        verdict = validate_extraction(
            _draft(doc.content.ref, word), span_resolver=resolve)
        assert not verdict.admitted, word
        assert "dangling_span_ref" in {e.code for e in verdict.errors}, word


# ── pass criterion: table cells round-trip ──


def test_table_cells_round_trip():
    total_tables = 0
    for path in FIXTURE_FILES:
        fixture = load_fixture(path)
        doc = rebuilt(fixture)
        payload = doc.payload
        assert len(doc.tables) == doc.provenance.table_count
        total_tables += len(doc.tables)
        cell_ranges = {(span.char_start, span.char_end) for span in doc.spans
                       if span.kind == "table_cell"}
        for table in doc.tables:
            assert DoclingTable.from_mapping(table.to_mapping()) == table
            assert table.rows >= 1 and table.cols >= 1
            assert table.cells, "a recorded table carries no cells"
            for cell in table.cells:
                assert payload[cell.char_start:cell.char_end]
                assert (cell.char_start, cell.char_end) in cell_ranges
                assert 0 <= cell.row < table.rows
                assert 0 <= cell.col < table.cols
                assert cell.row_span >= 1 and cell.col_span >= 1
    assert total_tables >= 10


# ── record round-trip + the untrusted envelope ──


@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=FIXTURE_IDS)
def test_record_round_trip_and_envelope_never_leaks(fixture_path: Path):
    fixture = load_fixture(fixture_path)
    doc = rebuilt(fixture)
    assert DoclingDocument.from_record(fixture["record"]) == doc
    assert doc.to_record() == fixture["record"]
    assert isinstance(doc.content, UntrustedContent)
    assert not isinstance(doc.content, str)
    sample = doc.payload[:60]
    assert sample not in str(doc.content)
    assert sample not in repr(doc.content)


# ── the live leg (spike venv only): model re-run matches the recorded digest ──


@pytest.mark.skipif(not _pinned_docling_available(),
                    reason="pinned docling 2.131.0 not installed "
                           "(live leg runs in the S1 spike venv)")
@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=FIXTURE_IDS)
def test_live_conversion_matches_recorded_structure(fixture_path: Path):
    fixture = load_fixture(fixture_path)
    record = fixture["record"]
    doc = convert_pdf(
        PAPERS_DIR / fixture["paper"]["filename"],
        source_ref=record["content"]["ref"],
        config=DoclingConfig.from_mapping(record["provenance"]["config"]),
    )
    assert doc.structure_digest() == fixture["runs"]["digest_a"]
    assert doc.payload_sha256() == fixture["runs"]["payload_sha256_a"]
    for claim in fixture["claims"]:
        assert doc.locate(claim["quote"]), claim["id"]
    for negative in fixture["negative_claims"]:
        assert doc.locate(negative["quote"]) == (), negative["id"]


# ── B1: the MANIFEST is an independent hermetic anchor (AUDIT-S1 B1) ──
#
# The fixture files are attacker-writable input: tamper-3 (a fully
# consistent payload+spans+claims+digests rewrite) passes every assertion
# that reads only the fixture record. These tests bind each fixture to
# MANIFEST.json — generated by the recording script alongside the fixtures,
# consumed by no runtime code — so a record rewrite fails here unless the
# attacker rewrites the MANIFEST too; and the vendored-PDF hash chain
# (below) catches a MANIFEST rewrite that also re-forges the PDF identity.


def _manifest_entry(fixture_name: str) -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest["papers"]:
        if entry["fixture"] == fixture_name:
            return entry
    raise AssertionError(f"{fixture_name} missing from MANIFEST.json")


@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=FIXTURE_IDS)
def test_manifest_binds_fixture_digest_and_paper_identity(fixture_path: Path):
    """Hermetic anchor 1 (AUDIT-S1 B1): fixture runs.digest_a and the vendored
    PDF identity must match MANIFEST.json independently of the record."""
    fixture = load_fixture(fixture_path)
    entry = _manifest_entry(fixture_path.name)
    assert entry["digest"] == fixture["runs"]["digest_a"]
    assert entry["sha256"] == fixture["paper"]["sha256"]
    assert entry["bytes"] == fixture["paper"]["bytes"]
    assert entry["pages"] == fixture["record"]["provenance"]["page_count"]
    assert entry["spans"] == fixture["record"]["provenance"]["span_count"]
    assert entry["claims"] == len(fixture["claims"])
    assert entry["negative_claims"] == len(fixture["negative_claims"])
    assert entry["rerun_identical"] is True


@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=FIXTURE_IDS)
def test_record_digest_matches_manifest_digest(fixture_path: Path):
    """Hermetic anchor 2 (AUDIT-S1 B1 / tamper-3): the structure digest
    recomputed from the fixture record equals the MANIFEST digest — a
    consistent payload/spans/claims rewrite changes the recomputed digest
    and fails here without docling installed and without the live leg."""
    fixture = load_fixture(fixture_path)
    doc = rebuilt(fixture)
    entry = _manifest_entry(fixture_path.name)
    assert doc.structure_digest() == entry["digest"]
    assert doc.payload_sha256() == fixture["runs"]["payload_sha256_a"]
