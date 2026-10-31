"""Read-only, project-scoped dereferences for the methodology ref namespaces.

Four ref families resolve against durable rows (OPS-5Y §3.2):

===============================  =============================================
``evidence:<artifact_id>``       ``artifacts`` row in the same project
``claim:<claim_id>``             ``research_claims`` row in the same project
``hypothesis:<rp>/<h>``          ``research_programs.hypothesis_json`` entry
``prediction:<rp>/<h>/<p>``      ``research_programs.prediction_json`` entry
                                 whose ``claim_ref`` is ``<h>``
===============================  =============================================

This module owns only the SQL. The ref grammar and the ``FETCHED``/``ROW``
classification live in :mod:`hermes.research.chain_refs`, which is what the
composition injects into the methodology handler.

It opens no transaction, takes no lock, holds no lease and writes nothing: each
function is a single ``SELECT``. The census is unaffected by construction, and
``check_census.py`` confirms it. A corrupt JSON column returns ``None`` rather
than raising: an unreadable row cannot back a ref, and a ref that is not backed
fails closed at intake.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

__all__ = [
    "ArtifactProvenance",
    "ProgramRefs",
    "read_artifact",
    "read_claim",
    "read_program_refs",
]


@dataclass(frozen=True, slots=True)
class ArtifactProvenance:
    """The two artifact columns the classification reads."""

    artifact_type: str
    producer: str


@dataclass(frozen=True, slots=True)
class ProgramRefs:
    """The hypothesis/prediction refs embedded in one program row.

    ``predictions`` holds ``(ref, claim_ref)`` pairs: a prediction resolves
    only when both the prediction ref and the hypothesis it claims to arise
    from are named by the row.
    """

    hypotheses: frozenset[str]
    predictions: tuple[tuple[str, str], ...]


def read_artifact(conn: sqlite3.Connection, project_id: str,
                  artifact_id: str) -> ArtifactProvenance | None:
    """The artifact's type and producer, or ``None`` when this project has no row."""
    row = conn.execute(
        "SELECT artifact_type, producer FROM artifacts "
        "WHERE artifact_id = ? AND project_id = ?",
        (artifact_id, project_id)).fetchone()
    if row is None:
        return None
    return ArtifactProvenance(artifact_type=str(row[0]), producer=str(row[1]))


def read_claim(conn: sqlite3.Connection, project_id: str,
               claim_id: str) -> bool:
    """True iff this project holds the claim row."""
    return conn.execute(
        "SELECT 1 FROM research_claims WHERE claim_id = ? AND project_id = ?",
        (claim_id, project_id)).fetchone() is not None


def read_program_refs(conn: sqlite3.Connection, project_id: str,
                      program_id: str) -> ProgramRefs | None:
    """The refs one program row embeds, or ``None`` when absent/unreadable."""
    row = conn.execute(
        "SELECT hypothesis_json, prediction_json FROM research_programs "
        "WHERE program_id = ? AND project_id = ?",
        (program_id, project_id)).fetchone()
    if row is None:
        return None
    hypotheses = _refs_of(row[0])
    predictions = _prediction_refs_of(row[1])
    if hypotheses is None or predictions is None:
        return None
    return ProgramRefs(hypotheses=frozenset(hypotheses),
                       predictions=tuple(predictions))


def _json_list(raw: object) -> list[object] | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, list) else None


def _refs_of(raw: object) -> list[str] | None:
    items = _json_list(raw)
    if items is None:
        return None
    refs: list[str] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("ref"), str):
            refs.append(item["ref"])
    return refs


def _prediction_refs_of(raw: object) -> list[tuple[str, str]] | None:
    items = _json_list(raw)
    if items is None:
        return None
    pairs: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ref = item.get("ref")
        claim_ref = item.get("claim_ref")
        if isinstance(ref, str) and isinstance(claim_ref, str):
            pairs.append((ref, claim_ref))
    return pairs
