"""Program-ref canonicalisation — the one comparison key (OPS-5Q).

The gateway admits a stored program reference in two spellings: a bare
``<program_id>`` and a ``research_program:<content_hash>`` ref (the
``failure_classifications._resolve_program`` contract). The N1 detector
and the HR-08 completion gate compare those refs. Comparing the raw
strings lets two classifications of one program fail to pair, and lets a
project complete over an open conflict.

This module is the one home for the comparison key. It is pure: callers
supply the project's program rows (already read), and both spellings
resolve to the row's ``program_id``. A ref that names no row, or names
more than one program, returns ``None`` — fail closed. No pairing is
safe; a wrong pairing is not.

The hypothesis half of the N1 key is resolved against the named
program's registered hypothesis refs when the row carries them. An exact
ref wins; a single ``hypothesis:<ref>`` spelling is accepted only when
the suffix is registered and the full value is not, so a hypothesis
literally named ``hypothesis:<x>`` is never merged with ``<x>``. A row
with no registered hypotheses (a shape the compiler never produces)
keeps the stored ref — the pre-OPS-5Q behaviour for legacy/fixture rows.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = [
    "HYPOTHESIS_REF_PREFIX",
    "PROGRAM_REF_PREFIX",
    "canonical_program_id",
    "canonical_program_scope",
    "program_ref_key",
]

PROGRAM_REF_PREFIX = "research_program:"
HYPOTHESIS_REF_PREFIX = "hypothesis:"


def program_ref_key(ref: object) -> str | None:
    """The bare lookup key of a program ref, or ``None`` for an unusable ref.

    Strips exactly one ``research_program:`` prefix. This is the parse step
    shared by the existing DB resolvers; it does not unify the content-hash
    spelling with the ``program_id`` — that needs the program rows (see
    ``canonical_program_id``).
    """
    if not isinstance(ref, str) or not ref:
        return None
    if ref.startswith(PROGRAM_REF_PREFIX):
        key = ref[len(PROGRAM_REF_PREFIX):]
        return key or None
    return ref


def canonical_program_id(
    ref: object,
    programs: Iterable[Mapping[str, Any]],
) -> str | None:
    """The one ``program_id`` a stored program ref names, or ``None``.

    Both admitted spellings resolve through the project's program rows: a
    bare ``<program_id>`` (or bare content hash) and a
    ``research_program:`` ref whose suffix is the ``program_id`` or the
    ``content_hash``. ``None`` when the ref is unusable, names no row, or
    names more than one program — fail closed.
    """
    key = program_ref_key(ref)
    if key is None:
        return None
    ids: set[str] = set()
    for program in programs:
        program_id = program.get("program_id")
        if not isinstance(program_id, str) or not program_id:
            continue
        content_hash = program.get("content_hash")
        if program_id == key or (
                isinstance(content_hash, str) and content_hash == key):
            ids.add(program_id)
    if len(ids) == 1:
        return next(iter(ids))
    if ids:
        return None
    # No row names this key. A bare ref is already the canonical program id;
    # a prefixed ref needs the row to know whether its suffix is an id or a
    # content hash, so it cannot be canonicalised without one (fail closed).
    if isinstance(ref, str) and ref.startswith(PROGRAM_REF_PREFIX):
        return None
    return key


def canonical_program_scope(
    program_ref: object,
    hypothesis_ref: object,
    programs: Iterable[Mapping[str, Any]],
) -> tuple[str, str] | None:
    """The canonical ``(program_id, hypothesis_ref)`` a stored pair names.

    Resolves the program ref through ``programs`` and the hypothesis ref
    against that program's registered hypothesis refs. Fail closed: an
    unresolved or ambiguous program, or a hypothesis the program does not
    register, returns ``None``.
    """
    rows = list(programs)
    program_id = canonical_program_id(program_ref, rows)
    if program_id is None:
        return None
    program = _program_row(program_id, rows)
    if program is None:
        # A bare ref with no row: the id is canonical, but there is no
        # hypothesis registry to verify the other half — keep the stored
        # ref (the legacy behaviour). A prefixed ref never reaches here
        # (canonical_program_id refuses it without a row).
        if (not isinstance(hypothesis_ref, str) or not hypothesis_ref):
            return None
        return program_id, hypothesis_ref
    hypothesis = _canonical_hypothesis_ref(hypothesis_ref, program)
    if hypothesis is None:
        return None
    return program_id, hypothesis


def _program_row(
    program_id: str, programs: list[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """The deterministic row for one program id (head version wins)."""
    candidates = [
        program for program in programs
        if program.get("program_id") == program_id]
    if not candidates:
        return None
    return max(candidates, key=lambda program: (
        _version(program), str(program.get("content_hash") or "")))


def _version(program: Mapping[str, Any]) -> int:
    try:
        return int(program.get("version") or 0)
    except (TypeError, ValueError):
        return 0


def _canonical_hypothesis_ref(
    ref: object, program: Mapping[str, Any],
) -> str | None:
    """Resolve one stored hypothesis ref against the program's registry."""
    if not isinstance(ref, str) or not ref:
        return None
    hypotheses = program.get("hypotheses")
    if not isinstance(hypotheses, list):
        hypotheses = []
    refs = {
        hypothesis.get("ref") for hypothesis in hypotheses
        if isinstance(hypothesis, Mapping)
        and isinstance(hypothesis.get("ref"), str)
        and hypothesis.get("ref")}
    if not refs:
        # No registry to verify against (legacy/fixture shape): the stored
        # ref is the key. A compiled program always carries its hypotheses.
        return ref
    if ref in refs:
        return ref
    if ref.startswith(HYPOTHESIS_REF_PREFIX):
        suffix = ref[len(HYPOTHESIS_REF_PREFIX):]
        if suffix in refs:
            return suffix
    return None
