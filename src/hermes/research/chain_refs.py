"""The OPS-5Y ref parser and provenance adapter — rows to ``FETCHED``/``ROW``.

The durable half lives in :mod:`hermes.persistence.chain_refs` (four
project-scoped ``SELECT``s and no transaction). This module is the one place
the ref grammar is parsed and the classification is decided, mirroring the
OPS-18 projection/adapter split: it imports the persistence projection, and the
composition injects it into the methodology handler as a callable so the
handler package itself never imports persistence.

The port is one read-only call::

    provenance_of(project_id, ref) -> "FETCHED" | "ROW" | None

``None`` means unbacked: no project row carries the ref, and
:meth:`SubstrateStore.admit_ref` refuses it. ``ROW`` means a real project row
carries it, but its content did not come from the fetch capability. Only
``FETCHED`` — a ``source_payload`` artifact whose producer begins
``capability:source_fetch:`` — may anchor a claim's support (OPS-5Y §4.1).
"""
from __future__ import annotations

from typing import Any

from hermes.persistence.chain_refs import (
    read_artifact,
    read_claim,
    read_program_refs,
)

__all__ = ["FETCHED", "ROW", "RefProvenanceReader", "parse_ref"]

FETCHED = "FETCHED"
ROW = "ROW"

#: The producer prefix the fetch capability writes. The one bit that makes an
#: artifact's bytes external to the run.
FETCH_PROVENANCE_PREFIX = "capability:source_fetch:"

_EVIDENCE = "evidence:"
_CLAIM = "claim:"
_HYPOTHESIS = "hypothesis:"
_PREDICTION = "prediction:"

#: Parsed refs are ``(family, parts)``. The family is the namespace; the parts
#: are the identifiers inside it (one for evidence/claim, two for hypothesis,
#: three for prediction).
ParsedRef = tuple[str, tuple[str, ...]]


def parse_ref(ref: str) -> ParsedRef | None:
    """Parse one ref into ``(family, parts)``, or ``None`` if it names nothing.

    The grammar is exact — no empty identifier and no extra separator. A
    hypothesis ref is ``hypothesis:<program>/<h>`` and a prediction ref is
    ``prediction:<program>/<h>/<p>``; ``HypothesisSpec.ref`` excludes ``/``, so
    the split is unambiguous.
    """
    if not isinstance(ref, str) or not ref:
        return None
    if ref.startswith(_EVIDENCE):
        identifier = ref[len(_EVIDENCE):]
        return ("evidence", (identifier,)) if identifier else None
    if ref.startswith(_CLAIM):
        identifier = ref[len(_CLAIM):]
        return ("claim", (identifier,)) if identifier else None
    if ref.startswith(_HYPOTHESIS):
        program, separator, hypothesis = ref[len(_HYPOTHESIS):].partition("/")
        if not separator or not program or not hypothesis or "/" in hypothesis:
            return None
        return ("hypothesis", (program, hypothesis))
    if ref.startswith(_PREDICTION):
        parts = ref[len(_PREDICTION):].split("/")
        if len(parts) != 3 or not all(parts):
            return None
        return ("prediction", (parts[0], parts[1], parts[2]))
    return None


class RefProvenanceReader:
    """Read one project's rows and classify a ref — the injected port.

    Constructed with the controller's connection. It never writes, never opens
    a transaction and never holds a lock. A ref this reader cannot classify is
    ``None`` (unbacked), which the substrate refuses at intake.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def __call__(self, project_id: str, ref: str) -> str | None:
        parsed = parse_ref(ref)
        if parsed is None:
            return None
        family, parts = parsed
        if family == "evidence":
            artifact = read_artifact(self._conn, project_id, parts[0])
            if artifact is None:
                return None
            if (artifact.artifact_type == "source_payload"
                    and artifact.producer.startswith(
                        FETCH_PROVENANCE_PREFIX)):
                return FETCHED
            return ROW
        if family == "claim":
            return ROW if read_claim(
                self._conn, project_id, parts[0]) else None
        program_id, hypothesis_ref = parts[0], parts[1]
        program = read_program_refs(self._conn, project_id, program_id)
        if program is None:
            return None
        if family == "hypothesis":
            return (ROW if hypothesis_ref in program.hypotheses else None)
        prediction_ref = parts[2]
        if (prediction_ref, hypothesis_ref) in program.predictions:
            return ROW
        return None
