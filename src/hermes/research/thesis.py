"""S1 thesis-mode validator — the AR-03 hardening (v6 §9.1).

The thesis-mode machinery (S1) is DESIGNED (P1/P2/P4 phases); the
``thesis_evidence`` table exists since migration 1 but nothing reads it.
This module lands the piece the adversarial review demanded (AR-03): the
round-2+ counter-search compliance rule must NOT accept a self-attested
``counter_search: {result: NONE_FOUND}`` — a legitimately empty
counter-evidence search must reference a **persisted empty-result-set
artifact** (query terms actually run + provider response actually
received, migration 6→7).

- ``validate_thesis_evidence(table, empty_result_resolver)`` — the pure
  deterministic check (never raises): round ≥ 2 requires either a row on
  the round-1 minority direction OR a ``NONE_FOUND`` counter-search that
  dereferences to a matching ``empty_result_artifacts`` row. A
  ``FOUND``/missing/undereferenceable counter-search is a compliance
  error (fail-closed — the table cannot be certified without the
  artifact). Round-1 tables and the majority-side rule are out of scope
  (the full §9.1 validator is the thesis-mode slice).
- The artifact is a search *record*, never evidence: it certifies that a
  search ran and came back empty; it cannot promote or refute a claim.

Pure: no clock, no SQL, no writes. The resolver is injected (the write
path supplies the real one over ``empty_result_artifacts``), so the
validator stays deterministic and fixture-testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from hermes.research.programs import canonical_json, sha256_hex

__all__ = [
    "COUNTER_SEARCH_RESULTS",
    "EmptyResultArtifact",
    "ThesisValidationError",
    "empty_result_id_of",
    "validate_thesis_evidence",
]

# The counter-search result vocabulary (§9.1).
COUNTER_SEARCH_RESULTS = frozenset({"NONE_FOUND", "FOUND"})

# The row directions (§9.1).
_ROW_DIRECTIONS = frozenset({"FOR", "AGAINST", "NEUTRAL", "MECHANISTIC", "META"})

# Resolver signature: (project_id, artifact_id) -> dict | None
EmptyResultResolver = Callable[[str, str], Mapping[str, Any] | None]


@dataclass(frozen=True)
class EmptyResultArtifact:
    """A persisted empty-result-set search record (migration 6→7, AR-03).

    ``query_terms`` are the terms actually run; ``provider_response`` is
    the provider's actual response (the empty-result evidence). Identity is
    content-derived — ``sr_<sha256(query + response)>[:24]`` — so a forged
    artifact id fails closed and duplicates collapse idempotently.
    """

    project_id: str
    query_terms: tuple[str, ...]
    provider_response: str
    content_hash: str = ""


def empty_result_id_of(query_terms: Sequence[str],
                       provider_response: str) -> str:
    """Content-derived artifact id: ``sr_<sha256>[:24]``."""
    return "sr_" + sha256_hex(canonical_json({
        "query_terms": sorted(query_terms),
        "provider_response": provider_response,
    }))[:24]


def empty_result_content_hash_of(query_terms: Sequence[str],
                                 provider_response: str) -> str:
    """The content hash (id minus the ``sr_`` prefix, EC-V6 discipline)."""
    return empty_result_id_of(query_terms, provider_response)[3:]


@dataclass(frozen=True)
class ThesisValidationError:
    """A structured, deterministic thesis-evidence validation error."""

    code: str
    field_path: str
    rule: str
    explanation: str
    remediation: str


def _err(code: str, path: str, rule: str, why: str, fix: str) -> ThesisValidationError:
    return ThesisValidationError(code, path, rule, why, fix)


def validate_thesis_evidence(
    table: Mapping[str, Any],
    empty_result_resolver: EmptyResultResolver | None = None,
) -> list[ThesisValidationError]:
    """Validate a thesis-evidence table's round-2+ counter-search compliance.

    Deterministic and never raises (mirrors ``validate_extraction``'s
    fail-closed contract). The single AR-03 rule implemented here:

    - ``round >= 2``: the table must have ≥1 row on the round-1 minority
      direction, OR a ``counter_search`` with ``result: NONE_FOUND`` that
      dereferences (via the injected resolver) to a persisted
      ``empty_result_artifacts`` row whose query terms cover the declared
      terms. A ``NONE_FOUND`` without a resolvable artifact — or with an
      artifact whose recorded terms do not cover the declared terms — is a
      compliance error. ``FOUND`` results, missing ``counter_search``, or
      an undereferenceable artifact are all fail-closed errors.

    The full §9.1 validator (verdict mapping, source dereference, subject
    tags) is the thesis-mode slice, out of scope here. The resolver is
    required for any round-2+ table; a table without a resolver cannot be
    certified (fail-closed), which is the structural point of AR-03.
    """
    errors: list[ThesisValidationError] = []
    if not isinstance(table, Mapping):
        return [_err(
            "TABLE_NOT_MAPPING", "table",
            "the thesis evidence table must be a mapping",
            f"got {type(table).__name__}", "supply the schema'd table")]

    rows = table.get("rows", [])
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return [_err(
            "ROWS_NOT_LIST", "rows",
            "table.rows must be a sequence",
            f"got {type(rows).__name__}", "supply the row list")]

    round_no = table.get("round", 1)
    if not isinstance(round_no, int) or round_no < 1:
        return [_err(
            "BAD_ROUND", "round",
            "round must be an int >= 1",
            f"got {round_no!r}", "record the actual round")]

    # Row shape checks (structural, minimal — direction vocabulary).
    minority_direction: str | None = table.get("minority_direction")
    minority_rows: list[Mapping[str, Any]] = []
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(_err(
                "ROW_NOT_MAPPING", f"rows[{i}]",
                "each row must be a mapping",
                f"got {type(row).__name__}", "supply schema'd rows"))
            continue
        direction = row.get("direction")
        if direction not in _ROW_DIRECTIONS:
            errors.append(_err(
                "BAD_DIRECTION", f"rows[{i}].direction",
                "direction must be one of the §9.1 vocabulary",
                f"got {direction!r}", "record a valid direction"))
            continue
        if minority_direction is not None and direction == minority_direction:
            minority_rows.append(row)

    # AR-03 rule: round >= 2 must be compliant.
    if round_no >= 2 and not minority_rows:
        errors.extend(_check_round2_counter_search(table, empty_result_resolver))

    return errors


def _check_round2_counter_search(
    table: Mapping[str, Any],
    empty_result_resolver: EmptyResultResolver | None,
) -> list[ThesisValidationError]:
    """The round-2+ counter-search compliance check (AR-03 enforcement).

    A round-2+ table with no minority-direction row must carry a schema'd
    ``counter_search``; a ``NONE_FOUND`` result must dereference (via the
    injected resolver) to a persisted ``empty_result_artifacts`` row whose
    recorded query terms cover the declared terms. Fail-closed: every
    missing or undereferenceable piece is a structured error.
    """
    errors: list[ThesisValidationError] = []
    counter = table.get("counter_search")
    if not isinstance(counter, Mapping):
        return [_err(
            "ROUND2_NO_COUNTER_SEARCH", "counter_search",
            "round ≥ 2 requires a minority row OR a schema'd counter_search "
            "(v6 §9.1)",
            "no minority row and no counter_search record",
            "target the weaker side or record the empty search")]

    result = counter.get("result")
    if result not in COUNTER_SEARCH_RESULTS:
        return [_err(
            "BAD_COUNTER_RESULT", "counter_search.result",
            "counter_search.result must be NONE_FOUND | FOUND",
            f"got {result!r}", "record the actual result")]
    if result == "FOUND":
        return [_err(
            "ROUND2_COUNTER_FOUND_NO_ROW", "counter_search.result",
            "a FOUND counter-search without a minority row does not satisfy "
            "round-2 compliance",
            "counter-evidence was found but the table has no "
            "minority-direction row",
            "add the found counter-evidence as a row")]

    # NONE_FOUND — the AR-03 enforcement point.
    terms = counter.get("terms")
    if not isinstance(terms, Sequence) or isinstance(terms, (str, bytes)) \
            or not terms:
        return [_err(
            "COUNTER_NO_TERMS", "counter_search.terms",
            "NONE_FOUND requires the recorded query terms",
            f"got {terms!r}", "record the terms actually run")]

    artifact_ref = counter.get("artifact_ref")
    if not isinstance(artifact_ref, str) or not artifact_ref:
        return [_err(
            "NONE_FOUND_NO_ARTIFACT", "counter_search.artifact_ref",
            "NONE_FOUND must reference a persisted empty-result-set "
            "artifact (AR-03)",
            "no artifact_ref on a NONE_FOUND counter-search",
            "persist the empty-result artifact and cite it")]
    if empty_result_resolver is None:
        return [_err(
            "NONE_FOUND_UNDEREFERENCEABLE", "counter_search.artifact_ref",
            "NONE_FOUND cannot be certified without a resolver",
            "no empty-result resolver supplied for a NONE_FOUND "
            "counter-search",
            "supply the write-path resolver over empty_result_artifacts")]

    artifact = empty_result_resolver(table.get("project_id", ""), artifact_ref)
    if artifact is None:
        return [_err(
            "NONE_FOUND_ARTIFACT_MISSING", "counter_search.artifact_ref",
            "NONE_FOUND must dereference to a persisted empty-result "
            "artifact (AR-03)",
            f"artifact {artifact_ref!r} does not exist",
            "persist the artifact before citing it")]

    recorded_terms = set(artifact.get("query_terms", ()))
    declared_terms = set(terms)
    if not declared_terms <= recorded_terms:
        return [_err(
            "NONE_FOUND_TERMS_MISMATCH", "counter_search.terms",
            "the declared terms must be covered by the artifact's recorded "
            "query terms",
            f"declared {sorted(declared_terms)} not in "
            f"recorded {sorted(recorded_terms)}",
            "record the actual terms run on the artifact")]

    return errors
