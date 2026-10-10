"""Vault manifest — a derived view of the projection, recomputable and verified.

The manifest is **not authority**: every field is derived from the journal,
it is written next to the cursor as projector-owned state
(``.projection-manifest.json``), and ``verify_manifest`` *recomputes* the
claim from the journal and the notes on disk instead of trusting the file.
It closes the D2/G silence-by-design findings of the P-AUTO-5 audits:

- **D2** — a cursor restored ahead of the vault used to leave the next note
  linking a stable-ID note that was never written (``exists-on-disk=False``)
  with no signal. The manifest claim is "one note per journal row in
  ``(0, cursor_after]``", so un-written IDs are named by
  ``MISSING_NOTE``/``DANGLING_LINK``.
- **G** — compacted/lost/backfilled ranges were skipped silently. Global
  journal holes are named by ``GAP_RANGE``, rows that appeared inside the
  covered range after the manifest was written by ``BACKFILLED_RANGE``, rows
  the manifest witnessed but the journal no longer has by ``LOST_RANGE``,
  and a cursor ahead of the journal by ``CURSOR_RESTORED_AHEAD``.

Schema (``hermes-vault-manifest/v1``, deterministic — no timestamps)::

    {
      "manifest": "hermes-vault-manifest/v1",
      "authority": "derived view — recomputed from the journal; never authority",
      "project_id": "p1",
      "cursor_before": 0,              # the run's starting cursor
      "cursor_after": 4,               # the run's end cursor (coverage (0, 4])
      "covered": "(0, 4]",
      "journal_head": {"event_id": 6, "sha256": "<hash of the head row>"},
      "gap_event_ids": [3],            # global journal holes inside coverage
      "notes": [                       # one entry per journal row in coverage
        {"event_id": 1, "filename": "evt-000001-....md", "sha256": "..."}
      ]
    }

``journal_head`` records the project's journal head *at write time* (it may
sit beyond ``cursor_after``; those rows are reported as unprojected, not as
an integrity failure). The notes list digests the **rendered note body**, so
a digest mismatch against the recomputation means the journal row changed
under the manifest, and a mismatch against the file on disk means the note
was edited since.

Verification is journal read-only (SELECTs only) and never writes: refusal is
the report (``ManifestReport.ok`` False) with every offending ID named, and
the ``hermes vault verify`` command returns 1.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from hermes.vault import projection as _projection

__all__ = [
    "AUTHORITY_LABEL",
    "FINDING_CODES",
    "MANIFEST_FILENAME",
    "MANIFEST_VERSION",
    "ManifestFinding",
    "ManifestReport",
    "build_manifest",
    "format_event_ids",
    "journal_gap_event_ids",
    "journal_head_hash",
    "manifest_bytes",
    "read_manifest",
    "sha256_bytes",
    "sha256_text",
    "verify_manifest",
    "write_manifest",
]

MANIFEST_VERSION = "hermes-vault-manifest/v1"
MANIFEST_FILENAME = ".projection-manifest.json"
AUTHORITY_LABEL = ("derived view — recomputed from the journal; "
                   "never authority")

# Closed finding set (refusal-as-data): every way the derived view can fail
# to match the journal is named, and nothing is skipped silently.
FINDING_CODES: tuple[str, ...] = (
    "BACKFILLED_RANGE",       # journal row inside coverage, absent from manifest
    "CURSOR_MISMATCH",        # live cursor != manifest cursor_after
    "CURSOR_MISSING",         # no cursor file at all
    "CURSOR_RESTORED_AHEAD",  # cursor beyond the journal head: never projectable
    "DANGLING_LINK",          # wikilink target note absent from disk (D2)
    "GAP_RANGE",              # global journal hole inside coverage (lost row)
    "GAP_MANIFEST_MISMATCH",  # manifest gap_event_ids != recomputed holes (M1)
    "INVENTED_NOTE",          # note file with no canonical journal row
    "JOURNAL_HEAD_CHANGED",   # head row digest differs from the manifest anchor
    "JOURNAL_HEAD_REGRESSED",  # head fell below the head the manifest witnessed
    "LOST_RANGE",             # manifest note whose journal row is gone
    "MANIFEST_MISSING",       # no manifest: nothing to verify against
    "MANIFEST_PROJECT_MISMATCH",  # manifest recorded a different project
    "MANIFEST_UNREADABLE",    # not JSON / wrong schema / malformed entry
    "MISSING_NOTE",           # manifest note absent from disk (D2 cause)
    "NON_CANONICAL_FILENAME",  # manifest filename != note_filename(id, type) (M2)
    "NOTE_BEYOND_CURSOR",     # note on disk for a row beyond cursor_after
    "NOTE_DIGEST_DIVERGES",   # recomputed journal digest != manifest digest
    "RECOMPUTE_REFUSED",      # the projector refused the recomputation itself
    "TAMPERED_NOTE",          # disk bytes differ / not readable text
)

# A fabricated cursor can be arbitrarily large; every ID list a finding
# names is capped so a report can never enumerate an unbounded range.
_AHEAD_NAMES = 32
_MAX_RUNS = 12

_NOTE_FILE_RE = re.compile(r"^evt-(\d{6,})-([a-z0-9-]+)\.md\Z")
_STEM_ID_RE = re.compile(r"^evt-(\d{6,})-")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}\Z")

# The columns the projector reads; the head hash covers all of them so a
# mutation anywhere in the head row moves the anchor.
_ROW_KEYS: tuple[str, ...] = (
    "event_id", "event_type", "project_id", "task_id", "from_state",
    "to_state", "correlation_id", "caused_by", "reason", "artifact_ids_json",
    "payload_json", "created_at",
)


def sha256_bytes(data: bytes) -> str:
    """Hex digest of raw bytes (the note-file comparison unit)."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Hex digest of a rendered note body (UTF-8, newline='\\n' as written)."""
    return sha256_bytes(text.encode("utf-8"))


def journal_head_hash(row: dict[str, Any] | None) -> str | None:
    """Anchor hash of the journal head row (None when the journal is empty)."""
    if row is None:
        return None
    canonical = json.dumps({key: row.get(key) for key in _ROW_KEYS},
                           sort_keys=True, separators=(",", ":"), default=str)
    return sha256_text(canonical)


def build_manifest(*, project_id: str, cursor_before: int, cursor_after: int,
                   head_row: dict[str, Any] | None,
                   entries: list[tuple[int, str, str]],
                   gap_event_ids: tuple[int, ...] | list[int]) -> dict[str, Any]:
    """Build the manifest payload from the journal-derived plan.

    ``entries`` is the full-range plan ``[(event_id, filename, body)]`` as
    returned by ``hermes.vault.projection._plan_range`` — the claim this
    manifest makes about the vault.
    """
    notes = [
        {"event_id": event_id, "filename": filename,
         "sha256": sha256_text(body)}
        for event_id, filename, body in entries
    ]
    notes.sort(key=lambda entry: entry["event_id"])
    return {
        "manifest": MANIFEST_VERSION,
        "authority": AUTHORITY_LABEL,
        "project_id": project_id,
        "cursor_before": cursor_before,
        "cursor_after": cursor_after,
        "covered": f"(0, {cursor_after}]",
        "journal_head": {
            "event_id": None if head_row is None else head_row["event_id"],
            "sha256": journal_head_hash(head_row),
        },
        "gap_event_ids": sorted(gap_event_ids),
        "notes": notes,
    }


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    """Deterministic serialization (same journal state → identical bytes)."""
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
        "utf-8")


def write_manifest(root: str, manifest: dict[str, Any]) -> str:
    """Write the manifest under the jailed root; return its file name."""
    path = _projection._join_note(root, MANIFEST_FILENAME)
    with open(path, "wb") as handle:
        handle.write(manifest_bytes(manifest))
    return MANIFEST_FILENAME


def read_manifest(root: str) -> dict[str, Any]:
    """Read + shape-check the manifest (refusal-as-data, never silent).

    Refusals: MANIFEST_MISSING (no file), MANIFEST_UNREADABLE (not JSON,
    unknown schema version, or a malformed entry). Shape-checking here means
    the verifier never indexes a malformed manifest.
    """
    try:
        path = _projection._join_note(root, MANIFEST_FILENAME)
    except _projection.ProjectionRefused as exc:
        raise _projection.ProjectionRefused(
            "MANIFEST_UNREADABLE",
            f"the vault guards refused the manifest path [{exc.code}]: "
            f"{exc.detail}") from None
    if not os.path.exists(path):
        raise _projection.ProjectionRefused(
            "MANIFEST_MISSING",
            f"no manifest at {MANIFEST_FILENAME!r} — the vault's derived view "
            "was never recorded (or the vault root is not the projected one)")
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError) as exc:
        raise _projection.ProjectionRefused(
            "MANIFEST_UNREADABLE",
            f"manifest is not readable JSON: {exc}") from None
    if not isinstance(loaded, dict):
        raise _projection.ProjectionRefused(
            "MANIFEST_UNREADABLE", "manifest is not a JSON object")
    if loaded.get("manifest") != MANIFEST_VERSION:
        raise _projection.ProjectionRefused(
            "MANIFEST_UNREADABLE",
            f"unknown manifest schema {loaded.get('manifest')!r} "
            f"(expected {MANIFEST_VERSION!r})")
    for key in ("project_id", "cursor_before", "cursor_after", "covered",
                "journal_head", "gap_event_ids", "notes"):
        if key not in loaded:
            raise _projection.ProjectionRefused(
                "MANIFEST_UNREADABLE", f"manifest is missing {key!r}")
    if not isinstance(loaded["project_id"], str) or not loaded["project_id"]:
        raise _projection.ProjectionRefused(
            "MANIFEST_UNREADABLE", "manifest project_id is not a string")
    for key in ("cursor_before", "cursor_after"):
        value = loaded[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise _projection.ProjectionRefused(
                "MANIFEST_UNREADABLE",
                f"manifest {key} is not a non-negative int: {value!r}")
    head = loaded["journal_head"]
    if not isinstance(head, dict) or "event_id" not in head \
            or "sha256" not in head:
        raise _projection.ProjectionRefused(
            "MANIFEST_UNREADABLE", "manifest journal_head is malformed")
    head_id = head["event_id"]
    if head_id is not None and (not isinstance(head_id, int)
                                or isinstance(head_id, bool) or head_id < 1):
        raise _projection.ProjectionRefused(
            "MANIFEST_UNREADABLE",
            f"manifest journal_head.event_id is invalid: {head_id!r}")
    head_sha = head["sha256"]
    if head_sha is not None and (not isinstance(head_sha, str)
                                 or not _SHA256_RE.match(head_sha)):
        raise _projection.ProjectionRefused(
            "MANIFEST_UNREADABLE",
            "manifest journal_head.sha256 is not a sha256 hex digest")
    gaps = loaded["gap_event_ids"]
    if not isinstance(gaps, list) or any(
            not isinstance(gap, int) or isinstance(gap, bool) or gap < 1
            for gap in gaps):
        raise _projection.ProjectionRefused(
            "MANIFEST_UNREADABLE",
            f"manifest gap_event_ids is malformed: {gaps!r}")
    notes = loaded["notes"]
    if not isinstance(notes, list):
        raise _projection.ProjectionRefused(
            "MANIFEST_UNREADABLE", "manifest notes is not a list")
    for entry in notes:
        if not isinstance(entry, dict):
            raise _projection.ProjectionRefused(
                "MANIFEST_UNREADABLE", "manifest note entry is not an object")
        event_id = entry.get("event_id")
        filename = entry.get("filename")
        digest = entry.get("sha256")
        if (not isinstance(event_id, int) or isinstance(event_id, bool)
                or event_id < 1
                or not isinstance(filename, str)
                or not _NOTE_FILE_RE.match(filename)
                or not isinstance(digest, str)
                or not _SHA256_RE.match(digest)):
            raise _projection.ProjectionRefused(
                "MANIFEST_UNREADABLE",
                f"manifest note entry is malformed: {entry!r}")
    return loaded


def journal_gap_event_ids(conn: Any, upto: int) -> tuple[int, ...]:
    """Journal holes inside the occupied span of ``(0, upto]``.

    A hole is a compacted/lost row: the AUTOINCREMENT id was handed out and
    its row is gone. Interleaved rows of other projects occupy their slots,
    so this is not the project-scoped slot test (which reports false gaps).
    Only slots below the highest occupied id are scanned — slots above it
    are a cursor posture question, not a compaction hole, and the scan stays
    bounded by the real journal.
    """
    if upto < 1:
        return ()
    occupied = sorted(
        row[0] for row in conn.execute(
            "SELECT event_id FROM events WHERE event_id <= ?", (upto,)))
    if not occupied:
        return ()
    seen = set(occupied)
    ceiling = min(upto, occupied[-1])
    return tuple(slot for slot in range(1, ceiling + 1) if slot not in seen)


def format_event_ids(ids: tuple[int, ...] | list[int]) -> str:
    """Compact an ID list into runs (``[1,2,3,5]`` → ``"1-3,5"``).

    Capped at ``_MAX_RUNS`` runs so a large hole cannot flood a report line.
    """
    ordered = sorted(set(ids))
    if not ordered:
        return "-"
    runs: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        runs.append((start, previous))
        start = previous = value
    runs.append((start, previous))
    shown = runs[:_MAX_RUNS]
    rendered = ",".join(str(a) if a == b else f"{a}-{b}" for a, b in shown)
    hidden = sum(b - a + 1 for a, b in runs[_MAX_RUNS:])
    return rendered if not hidden else f"{rendered},…(+{hidden} id(s))"


def _ahead_ids(low: int, high: int) -> tuple[int, ...]:
    """IDs in ``(low, high]``, capped at ``_AHEAD_NAMES`` for reporting."""
    if high - low <= _AHEAD_NAMES:
        return tuple(range(low + 1, high + 1))
    return tuple(range(low + 1, low + 1 + _AHEAD_NAMES))


@dataclass(frozen=True)
class ManifestFinding:
    """One named mismatch (refusal-as-data)."""

    code: str
    detail: str
    event_ids: tuple[int, ...] = ()
    filenames: tuple[str, ...] = ()

    def line(self) -> str:
        out = f"[{self.code}] {self.detail}"
        if self.event_ids:
            out += f" event_ids=[{format_event_ids(self.event_ids)}]"
        if self.filenames:
            shown = ", ".join(self.filenames[:4])
            if len(self.filenames) > 4:
                shown += f", …(+{len(self.filenames) - 4} file(s))"
            out += f" files=[{shown}]"
        return out


@dataclass(frozen=True)
class ManifestReport:
    """Verification verdict: recomputed claim vs. manifest vs. disk."""

    ok: bool
    project_id: str
    cursor_after: int
    journal_head: int | None
    covered_notes: int
    unprojected_event_ids: tuple[int, ...]
    counts: dict[str, int]
    findings: tuple[ManifestFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verify": "hermes-vault-manifest-verify/v1",
            "ok": self.ok,
            "project_id": self.project_id,
            "cursor_after": self.cursor_after,
            "journal_head": self.journal_head,
            "covered_notes": self.covered_notes,
            "unprojected_event_ids": list(self.unprojected_event_ids),
            "counts": dict(sorted(self.counts.items())),
            "findings": [
                {"code": finding.code, "detail": finding.detail,
                 "event_ids": list(finding.event_ids),
                 "filenames": list(finding.filenames)}
                for finding in self.findings
            ],
        }

    def lines(self) -> list[str]:
        verdict = "OK" if self.ok else "REFUSED"
        head = "-" if self.journal_head is None else f"#{self.journal_head}"
        summary = (f"manifest verify {self.project_id}: {verdict} "
                   f"({len(self.findings)} finding(s))")
        out = [
            summary,
            f"  covered: (0, {self.cursor_after}] | notes: "
            f"{self.covered_notes} | journal head: {head}"
            + (f" | unprojected: ["
               f"{format_event_ids(self.unprojected_event_ids)}]"
               if self.unprojected_event_ids else ""),
        ]
        out += [f"  {finding.line()}" for finding in self.findings]
        return out


def _finding(findings: list[ManifestFinding], code: str, detail: str,
             event_ids: tuple[int, ...] | list[int] = (),
             filenames: tuple[str, ...] | list[str] = ()) -> None:
    findings.append(ManifestFinding(code, detail, tuple(event_ids),
                                    tuple(filenames)))


def _report(project_id: str, cursor_after: int, head_id: int | None,
            covered_notes: int, unprojected: tuple[int, ...],
            findings: list[ManifestFinding]) -> ManifestReport:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.code] = counts.get(finding.code, 0) + 1
    return ManifestReport(
        ok=not findings,
        project_id=project_id,
        cursor_after=cursor_after,
        journal_head=head_id,
        covered_notes=covered_notes,
        unprojected_event_ids=unprojected,
        counts=counts,
        findings=tuple(findings),
    )


def verify_manifest(conn: Any, project_id: str,
                    vault_root: str) -> ManifestReport:
    """Recompute the manifest claim from the journal and diff everything.

    Never trusts the manifest: the claim is rebuilt with the projector's own
    planner over ``(0, manifest.cursor_after]`` and compared per event_id
    against (a) the journal, (b) the manifest, (c) the note bytes on disk,
    and (d) the note files present in the vault. Journal read-only.
    """
    if not isinstance(project_id, str) or not project_id:
        raise _projection.ProjectionRefused(
            "BAD_PROJECT_ID",
            f"project_id must be non-empty, got {project_id!r}")
    root = _projection.init_vault_root(vault_root)
    findings: list[ManifestFinding] = []
    try:
        manifest = read_manifest(root)
    except _projection.ProjectionRefused as exc:
        _finding(findings, exc.code, exc.detail)
        return _report(project_id, 0, None, 0, (), findings)
    if manifest["project_id"] != project_id:
        _finding(findings, "MANIFEST_PROJECT_MISMATCH",
                 f"manifest was written for project "
                 f"{manifest['project_id']!r}, not {project_id!r}")
        return _report(project_id, manifest["cursor_after"], None, 0, (),
                       findings)

    cursor_after: int = manifest["cursor_after"]
    manifest_entries: dict[int, tuple[str, str]] = {
        entry["event_id"]: (entry["filename"], entry["sha256"])
        for entry in manifest["notes"]
    }

    # ── journal recomputation (never trust the manifest) ──
    rows = {
        row["event_id"]: row for row in conn.execute(
            "SELECT event_id, event_type FROM events WHERE project_id = ?",
            (project_id,)).fetchall()
    }
    journal_ids = {event_id for event_id in rows if event_id <= cursor_after}
    unprojected = tuple(sorted(
        event_id for event_id in rows if event_id > cursor_after))
    head_row = _projection._journal_head(conn, project_id)
    head_id = None if head_row is None else head_row["event_id"]
    try:
        plan = _projection._plan_range(conn, project_id, cursor_after)
    except _projection.ProjectionRefused as exc:
        _finding(findings, "RECOMPUTE_REFUSED",
                 f"the projector refused to recompute the covered range "
                 f"[{exc.code}]: {exc.detail}")
        plan = []
    recomputed: dict[int, tuple[str, str]] = {
        event_id: (filename, sha256_text(body))
        for event_id, filename, body in plan
    }
    recomputed_ids = set(recomputed)

    # ── range integrity: journal vs manifest vs global holes ──
    lost = sorted(set(manifest_entries) - journal_ids)
    if lost:
        _finding(findings, "LOST_RANGE",
                 f"{len(lost)} note(s) claimed by the manifest have no "
                 "journal row (row lost or compacted after the manifest was "
                 "written)", lost)
    backfilled = sorted(journal_ids - set(manifest_entries))
    if backfilled:
        _finding(findings, "BACKFILLED_RANGE",
                 f"{len(backfilled)} journal row(s) appeared inside the "
                 "covered range after the manifest was written "
                 "(backfill or journal mutation)", backfilled)
    gaps = journal_gap_event_ids(conn, cursor_after)
    if gaps:
        _finding(findings, "GAP_RANGE",
                 f"{len(gaps)} event_id slot(s) inside the covered range have "
                 "no journal row in any project (compacted or lost) — their "
                 "notes can never be projected", gaps)
    # M1 — the manifest's gap list is a certified claim, not metadata: a
    # forged gap_event_ids (invented holes, or hidden real ones) must be
    # named even when the recomputed GAP_RANGE already fires. Honest
    # manifests record exactly the recomputed holes, so this is silent then.
    claimed_gaps = sorted(set(manifest["gap_event_ids"]))
    recomputed_gaps = sorted(set(gaps))
    if claimed_gaps != recomputed_gaps:
        forged = sorted(set(claimed_gaps) - set(recomputed_gaps))
        hidden = sorted(set(recomputed_gaps) - set(claimed_gaps))
        _finding(findings, "GAP_MANIFEST_MISMATCH",
                 f"manifest gap_event_ids "
                 f"[{format_event_ids(claimed_gaps)}] != recomputed journal "
                 f"holes [{format_event_ids(recomputed_gaps)}]"
                 + (f" — forged: [{format_event_ids(forged)}]" if forged else "")
                 + (f" — hidden: [{format_event_ids(hidden)}]" if hidden else ""),
                 sorted(set(claimed_gaps) ^ set(recomputed_gaps)))

    # ── cursor posture: restored-ahead / mismatch / missing ──
    manifest_head = manifest["journal_head"]
    if head_id is None and cursor_after > 0:
        _finding(findings, "CURSOR_RESTORED_AHEAD",
                 f"cursor {cursor_after} is ahead of an empty journal — "
                 "slots can never be projected", _ahead_ids(0, cursor_after))
    elif head_id is not None and cursor_after > head_id:
        _finding(findings, "CURSOR_RESTORED_AHEAD",
                 f"cursor {cursor_after} is ahead of journal head #{head_id} "
                 "— the slots between can never be projected (restored or "
                 "fabricated cursor)", _ahead_ids(head_id, cursor_after))
    try:
        cursor_path = _projection._join_note(
            root, _projection.CURSOR_FILENAME)
    except _projection.ProjectionRefused as exc:
        _finding(findings, "CURSOR_MISMATCH",
                 f"the vault guards refused the cursor path [{exc.code}]: "
                 f"{exc.detail}")
        cursor_path = None
    if cursor_path is None:
        pass
    elif not os.path.exists(cursor_path):
        _finding(findings, "CURSOR_MISSING",
                 "no cursor file — the vault has no persisted projection "
                 "position (the next run would reproject from 0)")
    else:
        live_cursor: int | None
        try:
            with open(cursor_path, encoding="utf-8") as handle:
                live_cursor = int(handle.read().strip() or "0")
        except (OSError, ValueError):
            _finding(findings, "CURSOR_MISMATCH",
                     "cursor file is unreadable (expected a single int)")
            live_cursor = None
        if live_cursor is not None and live_cursor != cursor_after:
            _finding(findings, "CURSOR_MISMATCH",
                     f"live cursor {live_cursor} != manifest cursor_after "
                     f"{cursor_after} — the vault position was changed after "
                     "the manifest was written")
        if live_cursor is not None and live_cursor > cursor_after:
            _finding(findings, "CURSOR_RESTORED_AHEAD",
                     f"live cursor {live_cursor} is beyond the manifest's "
                     f"coverage (cursor_after {cursor_after}) — the slots "
                     "between were never recorded by a projection run",
                     _ahead_ids(cursor_after, live_cursor))

    # ── journal head anchor ──
    if manifest_head["event_id"] is not None:
        witnessed = manifest_head["event_id"]
        if head_id is None or head_id < witnessed:
            current = "empty" if head_id is None else f"#{head_id}"
            _finding(findings, "JOURNAL_HEAD_REGRESSED",
                     f"manifest witnessed journal head #{witnessed}; current "
                     f"head is {current} — the rows it anchored are gone",
                     _ahead_ids(head_id or 0, witnessed))
        elif head_id == witnessed and journal_head_hash(head_row) != \
                manifest_head["sha256"]:
            _finding(findings, "JOURNAL_HEAD_CHANGED",
                     f"journal head #{head_id} differs from the manifest's "
                     "anchor hash (row content changed under the manifest)",
                     (head_id,))
    elif head_id is not None and head_id > cursor_after:
        _finding(findings, "JOURNAL_HEAD_CHANGED",
                 f"the journal was empty when the manifest was written and "
                 f"now has head #{head_id} (the anchor no longer matches)",
                 (head_id,))

    # ── per-ID digest recomputation ──
    diverged = sorted(
        event_id for event_id in (recomputed_ids & set(manifest_entries))
        if recomputed[event_id][1] != manifest_entries[event_id][1])
    if diverged:
        _finding(findings, "NOTE_DIGEST_DIVERGES",
                 f"{len(diverged)} journal row(s) no longer render to the "
                 "manifest digest (row content changed since the manifest "
                 "was written)", diverged)

    # M2 — filename canonicality: the manifest's filename for each covered
    # row must equal note_filename(event_id, event_type from the journal).
    # A renamed file with the manifest edited to agree (digest matching)
    # is otherwise invisible — the disk-vs-manifest scan below compares
    # the two forgeries to each other. Rows the journal no longer has are
    # skipped here (LOST_RANGE already names them — there is no event_type
    # left to canonicalize against).
    non_canonical_ids: list[int] = []
    non_canonical_names: list[str] = []
    for event_id in sorted(manifest_entries):
        if event_id not in rows:
            continue
        canonical = _projection.note_filename(
            event_id, str(rows[event_id]["event_type"] or "Event"))
        if manifest_entries[event_id][0] != canonical:
            non_canonical_ids.append(event_id)
            non_canonical_names.append(manifest_entries[event_id][0])
    if non_canonical_ids:
        _finding(findings, "NON_CANONICAL_FILENAME",
                 f"{len(non_canonical_ids)} manifest filename(s) are not the "
                 "canonical note_filename(event_id, event_type) (renamed "
                 "note with the manifest edited to agree — the projector "
                 "would never write these names)", non_canonical_ids,
                 non_canonical_names)

    # ── vault scan: disk vs manifest, invented notes, out-of-band notes ──
    present = {name.casefold() for name in os.listdir(root)}
    missing_ids: list[int] = []
    missing_names: list[str] = []
    tampered_ids: list[int] = []
    tampered_names: list[str] = []
    invented_ids: list[int] = []
    invented_names: list[str] = []
    beyond_ids: list[int] = []
    beyond_names: list[str] = []
    note_paths: dict[str, str] = {}
    note_ids: dict[str, int] = {}
    for name in sorted(os.listdir(root)):
        match = _NOTE_FILE_RE.match(name)
        if match is None:
            continue
        event_id = int(match.group(1))
        note_paths[name] = os.path.join(root, name)
        note_ids[name] = event_id
        covered = manifest_entries.get(event_id)
        if covered is not None:
            if covered[0] != name:
                invented_ids.append(event_id)
                invented_names.append(name)
                continue
            try:
                with open(note_paths[name], "rb") as handle:
                    on_disk = sha256_bytes(handle.read())
            except OSError:
                on_disk = None
            if on_disk != covered[1]:
                tampered_ids.append(event_id)
                tampered_names.append(name)
            continue
        if event_id in rows and event_id > cursor_after:
            canonical = _projection.note_filename(
                event_id, str(rows[event_id]["event_type"] or "Event"))
            if canonical != name:
                invented_ids.append(event_id)
                invented_names.append(name)
            else:
                beyond_ids.append(event_id)
                beyond_names.append(name)
            continue
        invented_ids.append(event_id)
        invented_names.append(name)

    # ── link integrity: D2's dangling stable-ID link, checked directly ──
    dangling_ids: list[int] = []
    dangling_files: list[str] = []
    for name in sorted(note_paths):
        try:
            with open(note_paths[name], encoding="utf-8") as handle:
                body = handle.read()
        except (OSError, UnicodeDecodeError):
            if name not in tampered_names:
                tampered_ids.append(note_ids[name])
                tampered_names.append(name)
            continue
        source_id = note_ids[name]
        for target in _projection._WIKILINK_TARGET_RE.findall(body):
            if f"{target}.md".casefold() in present:
                continue
            stem_match = _STEM_ID_RE.match(target)
            target_id = int(stem_match.group(1)) if stem_match else source_id
            dangling_ids.append(target_id)
            dangling_files.append(f"{name} -> {target}")

    for event_id, (filename, _digest) in sorted(manifest_entries.items()):
        if filename.casefold() not in present:
            missing_ids.append(event_id)
            missing_names.append(filename)
    if missing_ids:
        _finding(findings, "MISSING_NOTE",
                 f"{len(missing_ids)} note(s) claimed by the manifest are "
                 "absent from disk (never written, or deleted) — stable-ID "
                 "links to them dangle", missing_ids, missing_names)
    if tampered_ids:
        _finding(findings, "TAMPERED_NOTE",
                 f"{len(tampered_ids)} note(s) differ from the manifest "
                 "digest (edited outside the projector, or not readable "
                 "text)", tampered_ids, tampered_names)
    if beyond_ids:
        _finding(findings, "NOTE_BEYOND_CURSOR",
                 f"{len(beyond_ids)} note(s) exist for journal rows beyond "
                 f"cursor_after {cursor_after} (projected out of band; the "
                 "cursor/manifest pair is behind the vault)", beyond_ids,
                 beyond_names)
    if invented_ids:
        _finding(findings, "INVENTED_NOTE",
                 f"{len(invented_ids)} note file(s) have no canonical journal "
                 "row (planted, renamed, or written for an id the journal "
                 "never had)", invented_ids, invented_names)
    if dangling_files:
        _finding(findings, "DANGLING_LINK",
                 f"{len(dangling_files)} wikilink target(s) point at notes "
                 "that do not exist on disk (stable-ID link dangling)",
                 dangling_ids, dangling_files)

    return _report(project_id, cursor_after, head_id, len(manifest_entries),
                   unprojected, findings)
