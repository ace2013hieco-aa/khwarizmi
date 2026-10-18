"""RESOLVER-PARITY-1 (GAP-2 P3-15, ruling R10) — resolver parity pins.

Two resolvers consume the same recorded classification evidence refs:

- ``_cx_resolve_evidence_ref`` (``hermes.research.gateway``) — the
  gateway basis derivation for contradiction qualification;
- ``detector_resolve_ref`` (``hermes.research.contradiction_candidates``)
  — the detector candidate-row derivation.

They agree on the six typed prefixes (``evidence``, ``source_result``,
``source_payload``, ``source_search``, ``failure_classification``,
``feature_binding``) and diverge on exactly one documented behaviour:
a bare artifact ID resolves in the detector (project-scoped row check)
and never in the gateway. This module pins, per prefix, the agreement
on a resolvable project-scoped row and on a non-resolvable ref; the
shared web bar; the bare-ID divergence; and project scoping on both
sides.

The web marker is a per-row-type predicate, so only the three
source-carrier prefixes have a web-held form; the other three cannot be
web-derived by construction and are pinned as such. The N9 retraction
layering is deliberately NOT pinned here: the gateway resolver carries
the retraction fence itself while the detector applies it one layer up
in ``detector_candidate_rows`` — a certified, documented difference
(``tests/test_n9_resolve_path_pin.py``). Tests only, zero behaviour
change (R10: a shared resolver would feed the frozen N1 pair rule and
needs its own gate).
"""
from __future__ import annotations

import json

import pytest

from hermes.core import frozen_clock
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.persistence.source_outcomes import source_artifact_is_web_derived
from hermes.research.contradiction_candidates import detector_resolve_ref
from hermes.research.gateway import _cx_resolve_evidence_ref
from hermes.tools.research_sources import WEB_SEARCH_PROVIDERS

CLOCK = "2026-01-01T00:00:00.000000+00:00"
WEB_PROVIDER = "brave"
SCHOLARLY_PROVIDER = "arxiv"

# Prefix -> the artifact_type the typed lookup keys on (the
# ``evidence:`` prefix reads type-``evidence`` rows; the rest are
# identity mappings).
PREFIX_TYPES = {
    "evidence": "evidence",
    "source_result": "source_result",
    "source_payload": "source_payload",
    "source_search": "source_search",
    "failure_classification": "failure_classification",
    "feature_binding": "feature_binding",
}

# The prefixes whose carrier rows can be web-derived per the shared
# per-type predicate (source_result / source_payload / source_search).
WEB_ROW_TYPES = ("source_search", "source_result", "source_payload")

# The prefixes whose carrier rows have no web form at all — the
# predicate dispatches on the row's type and returns False for these.
NON_WEB_ROW_TYPES = ("evidence", "failure_classification",
                     "feature_binding")


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p2", "Other")
    yield conn
    conn.close()


def _insert(db, artifact_id: str, artifact_type: str, content_hash: str,
            *, project: str = "p1", meta: dict | None = None) -> None:
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, NULL, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, project, artifact_type, content_hash,
         None if meta is None else json.dumps(meta), CLOCK))
    db.commit()


def _row(db, artifact_id: str):
    return db.execute(
        "SELECT artifact_id, project_id, artifact_type, content_hash "
        "FROM artifacts WHERE artifact_id = ?",
        (artifact_id,)).fetchone()


def _seed_web_rows(db) -> dict[str, tuple[str, str]]:
    """One web-derived carrier per web-holdable prefix (p1).

    Returns ``{prefix: (content_hash, artifact_id)}``. The payload is
    web via its one-hop ``source_result_ref`` to the web result row.
    """
    web_result_hash = "ch-web-result"
    _insert(db, "art-web-result", "source_result", web_result_hash,
            meta={"record": {"provider": WEB_PROVIDER}})
    _insert(db, "art-web-search", "source_search", "ch-web-search",
            meta={"providers": [WEB_PROVIDER]})
    _insert(db, "art-web-payload", "source_payload", "ch-web-payload",
            meta={"source_result_ref": "source_result:" + web_result_hash})
    return {
        "source_search": ("ch-web-search", "art-web-search"),
        "source_result": (web_result_hash, "art-web-result"),
        "source_payload": ("ch-web-payload", "art-web-payload"),
    }


def _seed_scholarly_twin(db, prefix: str) -> tuple[str, str]:
    """A non-web row of ``prefix``'s type (p1); returns (hash, id)."""
    if prefix == "source_search":
        _insert(db, "art-sch-search", "source_search", "ch-sch-search",
                meta={"providers": [SCHOLARLY_PROVIDER]})
        return "ch-sch-search", "art-sch-search"
    if prefix == "source_result":
        _insert(db, "art-sch-result", "source_result", "ch-sch-result",
                meta={"record": {"provider": SCHOLARLY_PROVIDER}})
        return "ch-sch-result", "art-sch-result"
    _insert(db, "art-sch-result", "source_result", "ch-sch-result",
            meta={"record": {"provider": SCHOLARLY_PROVIDER}})
    _insert(db, "art-sch-payload", "source_payload", "ch-sch-payload",
            meta={"source_result_ref": "source_result:ch-sch-result"})
    return "ch-sch-payload", "art-sch-payload"


def _spy_web_predicate(monkeypatch, module) -> list[str]:
    """Swap the module's web predicate for a recording wrapper."""
    seen: list[str] = []
    real = module.source_artifact_is_web_derived

    def spy(conn, artifact_id):
        seen.append(artifact_id)
        return real(conn, artifact_id)

    monkeypatch.setattr(module, "source_artifact_is_web_derived", spy)
    return seen


def test_web_provider_fixture_is_a_web_provider() -> None:
    assert WEB_PROVIDER in WEB_SEARCH_PROVIDERS
    assert SCHOLARLY_PROVIDER not in WEB_SEARCH_PROVIDERS


class TestTypedPrefixParity:
    @pytest.mark.parametrize("prefix", sorted(PREFIX_TYPES))
    def test_resolvable_project_row_resolves_identically(self, db, prefix):
        art_type = PREFIX_TYPES[prefix]
        content_hash = f"ch-resolvable-{prefix}"
        artifact_id = f"art-resolvable-{prefix}"
        _insert(db, artifact_id, art_type, content_hash)
        ref = f"{prefix}:{content_hash}"
        # Non-vacuity: the row is genuinely in the table under exactly
        # the lookup key both resolvers use (project + hash + type).
        row = _row(db, artifact_id)
        assert row is not None
        assert row["content_hash"] == content_hash
        assert _cx_resolve_evidence_ref(db, "p1", ref) == artifact_id
        assert detector_resolve_ref(db, "p1", ref) == artifact_id

    @pytest.mark.parametrize("prefix", sorted(PREFIX_TYPES))
    def test_nonresolvable_ref_refused_identically(self, db, prefix):
        ref = f"{prefix}:ch-no-such-row-{prefix}"
        assert _cx_resolve_evidence_ref(db, "p1", ref) is None
        assert detector_resolve_ref(db, "p1", ref) is None

    def test_type_keyed_lookup_parity(self, db):
        # One row per type; each prefix cites a different type's hash —
        # neither resolver may type-confuse (the prefix is the type).
        types = sorted(set(PREFIX_TYPES.values()))
        hashes = {}
        for art_type in types:
            content_hash = f"ch-typed-{art_type}"
            hashes[art_type] = content_hash
            _insert(db, f"art-typed-{art_type}", art_type, content_hash)
        for prefix, art_type in PREFIX_TYPES.items():
            other = types[(types.index(art_type) + 1) % len(types)]
            ref = f"{prefix}:{hashes[other]}"
            assert _cx_resolve_evidence_ref(db, "p1", ref) is None, ref
            assert detector_resolve_ref(db, "p1", ref) is None, ref

    @pytest.mark.parametrize("ref", ["", ":", "x:", ":y", "no-colon",
                                     "unknown_prefix:ch-1", None, 7])
    def test_malformed_or_unknown_refs_refused_identically(self, db, ref):
        assert _cx_resolve_evidence_ref(db, "p1", ref) is None
        assert detector_resolve_ref(db, "p1", ref) is None


class TestSharedWebBar:
    @pytest.mark.parametrize("prefix", WEB_ROW_TYPES)
    def test_web_held_row_refused_by_both(self, db, prefix):
        content_hash, artifact_id = _seed_web_rows(db)[prefix]
        # Non-vacuity: the row exists and the shared predicate marks it
        # web-derived — the refusal is the bar, not a lookup miss.
        assert _row(db, artifact_id) is not None
        assert source_artifact_is_web_derived(db, artifact_id) is True
        ref = f"{prefix}:{content_hash}"
        assert _cx_resolve_evidence_ref(db, "p1", ref) is None
        assert detector_resolve_ref(db, "p1", ref) is None
        # Control: a scholarly row of the same type is admitted by both
        # — the refusal tracks the web marker, not the prefix.
        sch_hash, sch_id = _seed_scholarly_twin(db, prefix)
        sch_ref = f"{prefix}:{sch_hash}"
        assert source_artifact_is_web_derived(db, sch_id) is False
        assert _cx_resolve_evidence_ref(db, "p1", sch_ref) == sch_id
        assert detector_resolve_ref(db, "p1", sch_ref) == sch_id

    @pytest.mark.parametrize("prefix", NON_WEB_ROW_TYPES)
    def test_non_source_carrier_has_no_web_form(self, db, prefix):
        # The web marker dispatches on the row's type; a row whose type
        # has no web form is not web-held even with marker metadata, so
        # both resolvers admit it — pinned agreement, not an exemption.
        art_type = PREFIX_TYPES[prefix]
        content_hash = f"ch-marker-{prefix}"
        artifact_id = f"art-marker-{prefix}"
        _insert(db, artifact_id, art_type, content_hash,
                meta={"providers": [WEB_PROVIDER]})
        assert source_artifact_is_web_derived(db, artifact_id) is False
        ref = f"{prefix}:{content_hash}"
        assert _cx_resolve_evidence_ref(db, "p1", ref) == artifact_id
        assert detector_resolve_ref(db, "p1", ref) == artifact_id


class TestBareIdDivergence:
    def test_bare_id_gateway_none_detector_resolves(self, db):
        _insert(db, "art-bare-1", "source_result", "ch-bare-1",
                meta={"record": {"provider": SCHOLARLY_PROVIDER}})
        # Non-vacuity: the row is genuinely resolvable by ID in p1 —
        # the divergence is the gateway's bare-ref refusal itself.
        assert _row(db, "art-bare-1") is not None
        assert _cx_resolve_evidence_ref(db, "p1", "art-bare-1") is None
        assert detector_resolve_ref(db, "p1", "art-bare-1") == "art-bare-1"

    def test_bare_id_missing_row_both_refuse(self, db):
        assert _cx_resolve_evidence_ref(db, "p1", "art-missing") is None
        assert detector_resolve_ref(db, "p1", "art-missing") is None

    def test_bare_id_web_row_both_refuse(self, db):
        web_id = _seed_web_rows(db)["source_result"][1]
        assert source_artifact_is_web_derived(db, web_id) is True
        assert _cx_resolve_evidence_ref(db, "p1", web_id) is None
        assert detector_resolve_ref(db, "p1", web_id) is None


class TestProjectScoping:
    @pytest.mark.parametrize("prefix", sorted(PREFIX_TYPES))
    def test_cross_project_typed_ref_fails_closed(self, db, prefix):
        art_type = PREFIX_TYPES[prefix]
        content_hash = f"ch-foreign-{prefix}"
        artifact_id = f"art-foreign-{prefix}"
        _insert(db, artifact_id, art_type, content_hash, project="p2")
        ref = f"{prefix}:{content_hash}"
        assert _cx_resolve_evidence_ref(db, "p1", ref) is None
        assert detector_resolve_ref(db, "p1", ref) is None
        # Non-vacuity: from its own project the same ref resolves on
        # both — the p1 refusal is scoping, not a missing row.
        assert _cx_resolve_evidence_ref(db, "p2", ref) == artifact_id
        assert detector_resolve_ref(db, "p2", ref) == artifact_id

    def test_cross_project_bare_id_fails_closed(self, db):
        _insert(db, "art-foreign-bare", "source_result", "ch-foreign-bare",
                project="p2",
                meta={"record": {"provider": SCHOLARLY_PROVIDER}})
        assert _row(db, "art-foreign-bare")["project_id"] == "p2"
        assert _cx_resolve_evidence_ref(db, "p1", "art-foreign-bare") is None
        assert detector_resolve_ref(db, "p1", "art-foreign-bare") is None
        # The documented divergence holds per project: in p2 the
        # detector resolves the bare id; the gateway still refuses.
        assert detector_resolve_ref(
            db, "p2", "art-foreign-bare") == "art-foreign-bare"
        assert _cx_resolve_evidence_ref(
            db, "p2", "art-foreign-bare") is None


class TestBothCodePathsExecute:
    """Non-vacuity: the pins above must exercise the real branches."""

    def test_gateway_typed_path_reaches_the_web_bar(self, db, monkeypatch):
        from hermes.research import gateway as gw
        seen = _spy_web_predicate(monkeypatch, gw)
        content_hash, web_id = _seed_web_rows(db)["source_result"]
        assert _cx_resolve_evidence_ref(
            db, "p1", f"source_result:{content_hash}") is None
        # The bar received exactly the row the typed lookup found.
        assert seen == [web_id]

    def test_detector_typed_path_reaches_the_web_bar(self, db, monkeypatch):
        from hermes.research import contradiction_candidates as cc
        seen = _spy_web_predicate(monkeypatch, cc)
        content_hash, web_id = _seed_web_rows(db)["source_result"]
        assert detector_resolve_ref(
            db, "p1", f"source_result:{content_hash}") is None
        assert seen == [web_id]

    def test_detector_bare_path_reaches_the_row_and_bar(
            self, db, monkeypatch):
        from hermes.research import contradiction_candidates as cc
        seen = _spy_web_predicate(monkeypatch, cc)
        web_id = _seed_web_rows(db)["source_result"][1]
        assert detector_resolve_ref(db, "p1", web_id) is None
        _insert(db, "art-bare-spy", "source_result", "ch-bare-spy",
                meta={"record": {"provider": SCHOLARLY_PROVIDER}})
        assert detector_resolve_ref(
            db, "p1", "art-bare-spy") == "art-bare-spy"
        # The bare path executed its row lookup, then consulted the bar
        # for each looked-up row.
        assert seen == [web_id, "art-bare-spy"]

    def test_gateway_bare_path_returns_before_the_row_lookup(
            self, db, monkeypatch):
        from hermes.research import gateway as gw
        seen = _spy_web_predicate(monkeypatch, gw)
        _insert(db, "art-bare-short", "source_result", "ch-bare-short")
        assert _cx_resolve_evidence_ref(db, "p1", "art-bare-short") is None
        assert _row(db, "art-bare-short") is not None
        # Were the gateway to fall into the bare-row lookup (the
        # detector behaviour), the bar would have been consulted.
        assert seen == []
