"""OPS-5Z backfill — restore the declared format, never the wall.

The four live artifacts were fetched before ``c5be230`` made a read a state and
a shape a declaration. Their rows carry no ``content_format``, so they read
``fallback`` and the claim gate caves every claim, including the 33,727-byte
OpenAlex record the live slices are measured against. This file is the
falsification of the one-shot migration that fills the key in.

The trap is the reason this file exists. A backfill that dispatches on
``media_type`` sees ``text/html`` on the three PubMed walls and declares them
pages; the reader then returns 153 characters of "Cookies must be enabled" as
content; and a claim quoting the wall grounds. The migration therefore runs the
fetch content gate over the stored bytes *before* it writes a format. Two
independent signals refuse these walls: the recorded HTTP 203 and the
"cookies must be enabled" marker.

The six falsifiers, in the charter's order:

1. The OpenAlex record becomes readable: ``05475c33`` → content, 1,260
   characters, and a verbatim abstract sentence is grounded through
   ``check_claim``. Before the migration the same claim caveats
   ``source_not_readable``.
2. The three walls stay refused. Their ``content_format`` is the reserved
   ``refused`` token, the gate verdict is recorded, they read ``unreadable``
   for every shape, and the wall sentence does not ground through the
   stored-format seam the methodology driver uses.
3. A row with no provider and no media type is left alone: its metadata is
   byte-identical and the report names the reason.
4. A row already carrying ``content_format`` is byte-identical.
5. A second run is a no-op: every metadata row is byte-identical and the run
   says zero changed.
6. The gate is not weakened: every row with a non-empty ``content_format``
   passes ``fetch_content_refusal`` at the status recorded for its bytes; every
   refused row keeps it empty.

The red proof is the failure this slice exists to prevent, not a synthetic
near-miss: stub ``fetch_content_refusal`` out and the wall becomes ``html``,
reads as content, and the wall sentence grounds — falsifier 2 fails in exactly
the state the migration is designed to refuse. The red proof and the bug are
the same state.

The real bytes are the committed fixtures: ``openalex_work_33727.json`` is the
live record (hash ``05475c33…``); ``pubmed_cookie_wall_5590.html`` is the live
wall (hash ``e142eeae…``), and two variants change only the wall's
``challengeId`` so all three live wall hashes are represented at the same
5,590 bytes. The live run — against a copy first, then the real database — is
in ``OPS-5Z-BACKFILL-REPORT.md``.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from hermes.agents.runtime.assembly import evidence_envelope
from hermes.artifacts.store import ArtifactStore
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.provider_interactions import (
    ProviderInteractionRepository,
)
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
)
from hermes.persistence.source_outcomes import SourceOutcomeRepository
from hermes.research.grounding import (
    CaveatCode,
    check_claim,
)
from hermes.tools.capabilities.content import (
    REFUSED_CONTENT_FORMAT,
    ContentState,
    read_content,
)
from hermes.tools.providers.content import fetch_content_refusal

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "backfill_content_format.py"
FIXTURES = Path(__file__).parent / "fixtures" / "source_payloads"
OPENALEX_WORK = FIXTURES / "openalex_work_33727.json"
WALL = FIXTURES / "pubmed_cookie_wall_5590.html"

CLOCK = "2026-10-30T16:00:00.000000+00:00"

SUBJECTS = ("COVID-19",)
CONTROL = (
    "When a novel infectious disease emerges, enhanced contact tracing and "
    "isolation are implemented to prevent a major epidemic, and indeed, they "
    "have been successful for the control of severe acute respiratory "
    "syndrome (SARS) and Middle East respiratory syndrome (MERS), which have "
    "been greatly reduced without causing a global pandemic."
)

#: 10 words, verbatim in the wall's rendered text. The bare four-word fragment
#: "Cookies must be enabled" is below the gate's five-word quotation floor and
#: caveats for *that* reason too; this sentence makes the measurement about the
#: wall, not about the floor.
WALL_QUOTE = (
    "Enable cookies for pubmed.ncbi.nlm.nih.gov and reload this page to "
    "continue.")

BENIGN_HTML = (
    b"<!doctype html><html><head><title>Containment</title></head>"
    b"<body><article><h1>Containment</h1><p>Contact tracing reduced the "
    b"effective reproduction number in the study setting.</p></article>"
    b"</body></html>"
)

PUBMED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticle>
  <MedlineCitation>
    <PMID>32456789</PMID>
    <Article>
      <ArticleTitle>Containment</ArticleTitle>
      <Abstract><AbstractText>Contact tracing reduced transmission in the
        study setting.</AbstractText></Abstract>
    </Article>
  </MedlineCitation>
</PubmedArticle>
"""


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "backfill_content_format", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses resolves class annotations via
    # sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


backfill = _load_script()


def _wall(challenge: str) -> bytes:
    """The live wall with a different challenge id — same 5,590 bytes, new hash."""
    raw = WALL.read_bytes()
    original = b"j4pAiePg8oaHIJkkoKQ0eQ"
    assert original in raw
    assert len(challenge) == len(original)
    encoded = raw.replace(original, challenge.encode("ascii"))
    assert len(encoded) == 5590
    return encoded


WALLS = (_wall("h87CYxUTB-HrTcjgwn4ZKQ"),
         _wall("q3YOwRhrM2EV5iUIM754VA"),
         _wall("j4pAiePg8oaHIJkkoKQ0eQ"))


@dataclass(frozen=True)
class SeededRow:
    artifact_id: str
    project_id: str
    data: bytes
    provider: str | None
    media_type: str | None
    status_class: str | None
    preformatted: bool = False


@dataclass
class Rig:
    conn: Any
    store: ArtifactStore
    root: Path
    rows: dict[str, SeededRow]

    def raw(self, key: str) -> bytes:
        return self.rows[key].data

    def metadata(self, key: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = ?",
            (self.rows[key].artifact_id,)).fetchone()
        return json.loads(row["metadata_json"])

    def metadata_json(self, key: str) -> str:
        row = self.conn.execute(
            "SELECT metadata_json FROM artifacts WHERE artifact_id = ?",
            (self.rows[key].artifact_id,)).fetchone()
        return str(row["metadata_json"])


def _seed_rows() -> list[SeededRow]:
    rows = [
        SeededRow(
            artifact_id=hashlib.sha256(OPENALEX_WORK.read_bytes()).hexdigest(),
            project_id="sars-covid-19",
            data=OPENALEX_WORK.read_bytes(),
            provider="openalex", media_type="application/json",
            status_class="HTTP_200"),
        SeededRow(
            artifact_id=hashlib.sha256(WALLS[0]).hexdigest(),
            project_id="sars-covid-31", data=WALLS[0],
            provider="pubmed", media_type="text/html",
            status_class="HTTP_203"),
        SeededRow(
            artifact_id=hashlib.sha256(WALLS[1]).hexdigest(),
            project_id="sars-covid-18", data=WALLS[1],
            provider="pubmed", media_type="text/html",
            status_class="HTTP_203"),
        SeededRow(
            artifact_id=hashlib.sha256(WALLS[2]).hexdigest(),
            project_id="sars-covid-31", data=WALLS[2],
            provider="pubmed", media_type="text/html",
            status_class="HTTP_203"),
        # Falsifier 3 — no provider, no media type. Never inferred from bytes.
        SeededRow(
            artifact_id=hashlib.sha256(b'{"foo": "bar"}').hexdigest(),
            project_id="sars-covid-31", data=b'{"foo": "bar"}',
            provider=None, media_type=None, status_class=None),
        # Falsifier 4 — already declared; the sentinel must survive.
        SeededRow(
            artifact_id=hashlib.sha256(b'{"title": "declared"}').hexdigest(),
            project_id="sars-covid-31", data=b'{"title": "declared"}',
            provider="openalex", media_type="application/json",
            status_class="HTTP_200", preformatted=True),
        # No recorded status is not 200: the 203 rule cannot be evaluated, so
        # the row is left alone rather than granted content.
        SeededRow(
            artifact_id=hashlib.sha256(
                b'{"title": "no status", "abstract": "a record"}').hexdigest(),
            project_id="sars-covid-19",
            data=b'{"title": "no status", "abstract": "a record"}',
            provider="openalex", media_type="application/json",
            status_class=None),
        # The provider proposes, the adapter disposes: OpenAlex serving a page
        # declares html, not openalex.
        SeededRow(
            artifact_id=hashlib.sha256(BENIGN_HTML).hexdigest(),
            project_id="sars-covid-19", data=BENIGN_HTML,
            provider="openalex", media_type="application/xhtml+xml",
            status_class="HTTP_200"),
        # The record branch: PubMed XML is a declared record, not a page.
        SeededRow(
            artifact_id=hashlib.sha256(PUBMED_XML).hexdigest(),
            project_id="sars-covid-19", data=PUBMED_XML,
            provider="pubmed", media_type="application/xml",
            status_class="HTTP_200"),
    ]
    return rows


@pytest.fixture
def rig(tmp_path: Path):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    projects = sorted({row.project_id for row in _seed_rows()})
    for project_id in projects:
        ProjectRepository(conn, lambda: CLOCK).create(project_id, project_id)
    store = ArtifactStore(
        str(tmp_path / "store"),
        ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)
    interactions = ProviderInteractionRepository(conn)
    rows: dict[str, SeededRow] = {}
    for spec in _seed_rows():
        metadata: dict[str, Any] = {}
        if spec.provider is not None:
            metadata["provider"] = spec.provider
        if spec.media_type is not None:
            metadata["media_type"] = spec.media_type
        if spec.preformatted:
            metadata["content_format"] = "openalex"
            metadata["sentinel"] = "keep-me"
        row = store.write(
            spec.data, "source_payload",
            f"test.ops5z-backfill:{spec.project_id}",
            project_id=spec.project_id, artifact_id=spec.artifact_id,
            metadata=metadata or None)
        assert row["artifact_id"] == spec.artifact_id
        if spec.status_class is not None:
            interactions.record(
                interaction_id=f"ix_{spec.artifact_id[:24]}",
                project_id=spec.project_id, task_id=None,
                provider_id=spec.provider or "",
                adapter_version="1", parser_version="2",
                normalized_request_hash="0" * 64,
                request_json='{"url": "https://example.test/"}',
                response_status_class=spec.status_class,
                response_body_hash=spec.artifact_id,
                outcome_kind="RECORDED_SUCCESS", failure_class=None,
                content_type=spec.media_type, retrieved_at=CLOCK,
                source_url_redacted="https://example.test/",
                evidence_artifact_id=None, created_at=CLOCK)
        rows[spec.artifact_id] = spec
    yield Rig(conn=conn, store=store, root=Path(str(tmp_path / "store")),
              rows=rows)
    conn.close()


def _key_by_prefix(rig: Rig, prefix: str) -> str:
    matches = [key for key in rig.rows if key.startswith(prefix)]
    assert len(matches) == 1, (prefix, matches)
    return matches[0]


def _ground_through_stored_format(
    raw: bytes, declared: str, claim: str,
):
    """The methodology driver's seam (``methodology_driver._ground_claim``).

    A fallback or an unreadable artifact never hands its blob to the gate: it
    hands ``None`` plus the reader's reason, and the verdict is a caveat. This
    is the seam the migration's ``content_format`` decides.
    """
    read = read_content(raw, format=declared)
    if read.is_content and not read.detail:
        artifact_text: str | None = read.text
        unreadable = ""
    else:
        artifact_text = None
        unreadable = read.detail or (
            f"the content reader returned {read.state.value}")
    return check_claim(claim, artifact_text, unreadable_detail=unreadable)


def _assert_openalex_is_citable(rig: Rig) -> None:
    key = _key_by_prefix(rig, "05475c33")
    metadata = rig.metadata(key)
    assert metadata["content_format"] == "openalex"
    assert metadata["content_format_candidate"] == "openalex"
    assert metadata["content_gate"] == {"verdict": "pass"}
    assert metadata["content_state"] == "content"
    assert metadata["content_read"] == "content"
    read = read_content(rig.raw(key), format=metadata["content_format"])
    assert read.state is ContentState.CONTENT
    assert len(read.text) == 1260
    verdict = _ground_through_stored_format(
        rig.raw(key), metadata["content_format"], CONTROL)
    assert verdict.grounded is True, verdict.detail
    assert verdict.refusal is None and verdict.caveat is None


def _assert_walls_are_not_citable(rig: Rig) -> None:
    for prefix in ("705db439", "e142eeae", "ebcd5b02"):
        key = _key_by_prefix(rig, prefix)
        metadata = rig.metadata(key)
        assert metadata["content_format"] == REFUSED_CONTENT_FORMAT, prefix
        assert metadata["content_format_candidate"] == "html", prefix
        assert metadata["content_gate"]["verdict"] == "refused", prefix
        assert metadata["content_gate"]["code"] in {
            "NON_AUTHORITATIVE_RESPONSE", "NON_CONTENT_PAYLOAD"}, prefix
        assert metadata["content_state"] == "refused", prefix
        assert metadata["content_read"] == "unreadable", prefix
        read = read_content(rig.raw(key), format=metadata["content_format"])
        assert read.state is ContentState.UNREADABLE, prefix
        verdict = _ground_through_stored_format(
            rig.raw(key), metadata["content_format"], WALL_QUOTE)
        assert verdict.grounded is False, (prefix, verdict.detail)
        assert verdict.caveat is CaveatCode.SOURCE_NOT_READABLE, prefix


# ═══════════ 1. OpenAlex becomes readable; the caveat becomes a grounding ═══════════


def test_the_openalex_record_becomes_content_and_a_quotation_grounds(
        rig: Rig) -> None:
    key = _key_by_prefix(rig, "05475c33")
    raw = rig.raw(key)
    before = read_content(raw)
    assert before.state is ContentState.FALLBACK
    caved = check_claim(CONTROL, None, unreadable_detail=before.detail)
    assert caved.grounded is False
    assert caved.caveat is CaveatCode.SOURCE_NOT_READABLE

    summary = backfill.run_backfill(rig.conn, rig.root, apply=True)
    assert summary.changed == 6, summary.changed
    _assert_openalex_is_citable(rig)


# ═══════════ 2. The three walls stay refused; the red proof is the same state ═══════════


def test_the_three_walls_stay_refused_and_the_wall_sentence_does_not_ground(
        rig: Rig) -> None:
    # The variants are the live wall bytes, changing only the challenge id:
    # the three live hashes are represented at the same 5,590 bytes.
    assert [hashlib.sha256(wall).hexdigest()[:8] for wall in WALLS] == [
        "705db439", "ebcd5b02", "e142eeae"]
    before = read_content(rig.raw(_key_by_prefix(rig, "705db439")))
    assert before.state is ContentState.FALLBACK
    caved = check_claim(WALL_QUOTE, None, unreadable_detail=before.detail)
    assert caved.grounded is False

    backfill.run_backfill(rig.conn, rig.root, apply=True)
    _assert_walls_are_not_citable(rig)

    # The status lookup is not decorative: the live walls arrived 203, and the
    # gate must use that stored status rather than assuming 200.
    key = _key_by_prefix(rig, "705db439")
    assert rig.metadata(key)["content_backfill"]["status"] == 203
    assert (rig.metadata(key)["content_gate"]["code"]
            == "NON_AUTHORITATIVE_RESPONSE")


def test_red_proof_without_the_gate_a_wall_becomes_a_citable_page(
        rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bug and the red proof are the same state: skip the gate, cite a wall.

    ``fetch_content_refusal`` is the only thing between the recorded media type
    (``text/html``) and a format declaration. Stub it out and the migration
    writes ``html``; ``read_content`` then returns the wall's 153 characters as
    content, and the wall sentence grounds. Falsifier 2 fails exactly here.
    """
    monkeypatch.setattr(backfill, "fetch_content_refusal",
                        lambda **_: None)
    backfill.run_backfill(rig.conn, rig.root, apply=True)

    key = _key_by_prefix(rig, "705db439")
    metadata = rig.metadata(key)
    assert metadata["content_format"] == "html"
    assert metadata["content_state"] == "content"
    assert metadata["content_gate"] == {"verdict": "pass"}
    read = read_content(rig.raw(key), format="html")
    assert read.state is ContentState.CONTENT
    verdict = check_claim(WALL_QUOTE, read.text)
    assert verdict.grounded is True, verdict.detail

    with pytest.raises(AssertionError):
        _assert_walls_are_not_citable(rig)


# ═══════════ 3–4. Ambiguous and already-declared rows are untouched ═══════════


def test_a_row_with_no_provider_and_no_media_type_is_left_alone(
        rig: Rig) -> None:
    key = _key_by_prefix(
        rig, hashlib.sha256(b'{"foo": "bar"}').hexdigest())
    before = rig.metadata_json(key)
    summary = backfill.run_backfill(rig.conn, rig.root, apply=True)
    plan = next(row for row in summary.rows if row.artifact_id == key)
    assert plan.action == "left-alone"
    assert "no provider recorded" in plan.reason
    assert rig.metadata_json(key) == before
    read = read_content(rig.raw(key), format=rig.metadata(key).get(
        "content_format", ""))
    assert read.state is ContentState.FALLBACK
    assert plan.read_state == ""


def test_a_row_already_carrying_content_format_is_untouched(rig: Rig) -> None:
    key = _key_by_prefix(rig, hashlib.sha256(
        b'{"title": "declared"}').hexdigest())
    before = rig.metadata_json(key)
    summary = backfill.run_backfill(rig.conn, rig.root, apply=True)
    plan = next(row for row in summary.rows if row.artifact_id == key)
    assert plan.action == "recorded"
    assert rig.metadata_json(key) == before
    metadata = rig.metadata(key)
    assert metadata["content_format"] == "openalex"
    assert metadata["sentinel"] == "keep-me"
    assert "content_backfill" not in metadata
    assert "content_state" not in metadata


# ═══════════ 5. Idempotence is byte-identical ═══════════


def test_the_recorded_format_reaches_the_live_read_seams(rig: Rig) -> None:
    """Not just ``read_content``: the repository and envelope dispatch on it.

    ``SourceOutcomeRepository.read_payload_format`` is the controller's seam;
    ``evidence_envelope`` is the model's view. The OpenAlex record is content
    in both (1,260 characters); the wall is unreadable in both, still shown,
    never mined.
    """
    backfill.run_backfill(rig.conn, rig.root, apply=True)
    repos = SourceOutcomeRepository(rig.conn, rig.store)
    openalex = _key_by_prefix(rig, "05475c33")
    ref = "source_payload:" + openalex
    assert repos.read_payload_format(ref) == "openalex"
    envelope = evidence_envelope(
        task_id="task:CLAIM", evidence_ref="evidence:" + openalex,
        artifact_bytes=repos.read_payload_bytes(ref),
        artifact_format=repos.read_payload_format(ref))
    excerpt = json.loads(envelope.text)["excerpt"]
    assert excerpt["read"] == "content"
    assert excerpt["format"] == "openalex"
    assert len(excerpt["text"]) == 1260

    wall = _key_by_prefix(rig, "705db439")
    wall_ref = "source_payload:" + wall
    assert repos.read_payload_format(wall_ref) == REFUSED_CONTENT_FORMAT
    wall_envelope = evidence_envelope(
        task_id="task:CLAIM", evidence_ref="evidence:" + wall,
        artifact_bytes=repos.read_payload_bytes(wall_ref),
        artifact_format=repos.read_payload_format(wall_ref))
    wall_excerpt = json.loads(wall_envelope.text)["excerpt"]
    assert wall_excerpt["read"] == "unreadable"
    assert wall_excerpt["format"] == REFUSED_CONTENT_FORMAT


def test_the_migration_is_additive_and_the_bytes_are_untouched(rig: Rig) -> None:
    key = _key_by_prefix(rig, "05475c33")
    columns = ("artifact_id", "content_hash", "size_bytes", "storage_path",
               "project_id", "created_at")
    before = dict(rig.conn.execute(
        "SELECT " + ", ".join(columns) + " FROM artifacts "
        "WHERE artifact_id = ?", (key,)).fetchone())
    before_metadata = rig.metadata(key)
    before_bytes = rig.store.read_verified(before["content_hash"])

    backfill.run_backfill(rig.conn, rig.root, apply=True)

    after = dict(rig.conn.execute(
        "SELECT " + ", ".join(columns) + " FROM artifacts "
        "WHERE artifact_id = ?", (key,)).fetchone())
    assert after == before
    assert rig.store.read_verified(before["content_hash"]) == before_bytes
    after_metadata = rig.metadata(key)
    for name, value in before_metadata.items():
        assert after_metadata[name] == value, name
    assert after_metadata["content_format"] == "openalex"


def test_a_second_run_is_a_no_op_and_says_so(rig: Rig) -> None:
    first = backfill.run_backfill(rig.conn, rig.root, apply=True)
    assert first.changed == 6
    snapshot = {
        key: rig.metadata_json(key) for key in rig.rows}

    second = backfill.run_backfill(rig.conn, rig.root, apply=True)
    assert second.changed == 0
    assert all(plan.action != "write" for plan in second.rows)
    assert second.recorded == 7 and second.left_alone == 2
    assert {key: rig.metadata_json(key) for key in rig.rows} == snapshot
    assert "0 changed" in backfill.format_summary(second)

    third = backfill.run_backfill(rig.conn, rig.root, apply=False)
    assert third.changed == 0
    assert "0 would change" in backfill.format_summary(third)


# ═══════════ 6. The gate is not weakened ═══════════


def test_no_artifact_gains_a_status_the_fetch_gate_would_deny(rig: Rig) -> None:
    backfill.run_backfill(rig.conn, rig.root, apply=True)
    for key, spec in rig.rows.items():
        metadata = rig.metadata(key)
        declared = metadata.get("content_format", "")
        raw = rig.raw(key)
        status = 200
        if spec.status_class is None:
            # No status: the migration leaves the row alone; there is no
            # declaration to check against the gate.
            assert "content_format" not in metadata, key
            continue
        status = int(spec.status_class.split("_")[1])
        refusal = fetch_content_refusal(
            status=status, media_type=spec.media_type, body=raw)
        if declared == REFUSED_CONTENT_FORMAT:
            assert refusal is not None, key
            assert metadata["content_gate"]["verdict"] == "refused", key
            assert read_content(
                raw, format=declared).state is ContentState.UNREADABLE, key
        elif declared:
            assert refusal is None, (key, declared, refusal)
        elif spec.provider is not None:
            assert metadata["content_gate"]["verdict"] == "refused", key
            assert read_content(
                raw, format=declared).state != ContentState.CONTENT, key


def test_two_equally_close_statuses_are_left_alone(rig: Rig) -> None:
    """A tie between 200 and 203 is not broken by picking the smaller number."""
    key = _key_by_prefix(rig, hashlib.sha256(
        b'{"title": "no status", "abstract": "a record"}').hexdigest())
    spec = rig.rows[key]
    interactions = ProviderInteractionRepository(rig.conn)
    for status in ("HTTP_200", "HTTP_203"):
        interactions.record(
            interaction_id=f"ix_tie_{status}_{key[:16]}",
            project_id=spec.project_id, task_id=None,
            provider_id=spec.provider or "",
            adapter_version="1", parser_version="2",
            normalized_request_hash="0" * 64,
            request_json='{"url": "https://example.test/"}',
            response_status_class=status, response_body_hash=key,
            outcome_kind="RECORDED_SUCCESS", failure_class=None,
            content_type=spec.media_type, retrieved_at=CLOCK,
            source_url_redacted="https://example.test/",
            evidence_artifact_id=None, created_at=CLOCK)
    before = rig.metadata_json(key)
    summary = backfill.run_backfill(rig.conn, rig.root, apply=True)
    plan = next(row for row in summary.rows if row.artifact_id == key)
    assert plan.action == "left-alone"
    assert "equally close" in plan.reason
    assert rig.metadata_json(key) == before


def test_no_recorded_status_is_left_alone_not_assumed_200(rig: Rig) -> None:
    key = _key_by_prefix(rig, hashlib.sha256(
        b'{"title": "no status", "abstract": "a record"}').hexdigest())
    before = rig.metadata_json(key)
    summary = backfill.run_backfill(rig.conn, rig.root, apply=True)
    plan = next(row for row in summary.rows if row.artifact_id == key)
    assert plan.action == "left-alone"
    assert "no recorded HTTP status" in plan.reason
    assert rig.metadata_json(key) == before
    assert "content_format" not in rig.metadata(key)


def test_the_refused_token_is_unreadable_for_every_shape() -> None:
    """The reserved token closes the plain-text hole an empty format leaves.

    An undeclared plain-text body is ``content`` — so writing ``""`` for a
    refused 203 ``text/plain`` response would grant it prose. The token the
    migration writes instead is unreadable for plain text, JSON and markup
    alike, and says why.
    """
    for raw in (b"Cookies must be enabled", b'{"a": 1}',
                b"<html><body>Cookies must be enabled</body></html>"):
        read = read_content(raw, format=REFUSED_CONTENT_FORMAT)
        assert read.state is ContentState.UNREADABLE, raw
        assert "not citable" in read.detail
        assert read.is_content is False


def test_the_bare_wall_fragment_is_below_the_quotation_floor() -> None:
    """The charter's four-word fragment caves for a second reason, by design.

    ``check_claim`` requires five words for a verbatim quotation. The wall's
    bare "Cookies must be enabled" is four, so it would cave even if the wall
    were declared content. The red proof therefore quotes the full wall
    sentence containing it — a falsifier that fails only when the wall becomes
    content, not one that passes because the quotation is too short.
    """
    read = read_content(WALLS[0], format="html")
    assert read.state is ContentState.CONTENT
    bare = check_claim("Cookies must be enabled", read.text)
    assert bare.grounded is False
    assert bare.caveat is CaveatCode.NO_CHECKABLE_ASSERTION
    assert check_claim(WALL_QUOTE, read.text).grounded is True


def test_the_derivation_is_the_adapters_declaration_not_the_provider_name(
        rig: Rig) -> None:
    """OpenAlex serving XHTML declares html; PubMed XML declares pubmed."""
    backfill.run_backfill(rig.conn, rig.root, apply=True)
    xhtml = _key_by_prefix(rig, hashlib.sha256(BENIGN_HTML).hexdigest())
    xml = _key_by_prefix(rig, hashlib.sha256(PUBMED_XML).hexdigest())
    assert rig.metadata(xhtml)["content_format"] == "html"
    assert rig.metadata(xhtml)["content_format_candidate"] == "html"
    assert rig.metadata(xhtml)["content_state"] == "content"
    assert rig.metadata(xhtml)["content_read"] == "content"
    assert rig.metadata(xml)["content_format"] == "pubmed"
    assert rig.metadata(xml)["content_format_candidate"] == "pubmed"
    assert rig.metadata(xml)["content_state"] == "content"
    assert rig.metadata(xml)["content_read"] == "content"
