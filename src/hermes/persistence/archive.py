# SPDX-License-Identifier: Apache-2.0
"""EXT-4 — additive cold archive for resolved/superseded rows (triage L1 / I4).

The append-only journal (``events``) and the derived state it produces grow
without bound, and every full-surface scan over them is O(history). The L1
triage records that the certified invariant's sanctioned relief valve —
*archive-not-delete* — is unimplemented, so the hot path has no way to move
cold rows out of the way.

This module implements that valve, **additively only**:

- **Export** copies resolved/superseded rows into content-addressed cold
  chunk files plus a digest manifest. It is a COPY: nothing is deleted and
  nothing is mutated. ``events`` is never a cold table — the journal is the
  audit trail and stays whole.
- **Verify** re-reads every cold file and re-hashes it, fail-closed: a
  missing manifest, a missing chunk, a wrong chunk digest, a wrong row
  digest, a wrong row count, a duplicate key, or a row-set mismatch all
  raise ``ArchiveIntegrityError`` rather than passing silently.
- **Marking is deliberately NOT done here.** The cold set is derivable from
  the manifest itself (the archived key set), so the module needs no DB
  write, no schema migration, and no transaction — the certified
  transaction census (121 control calls / 27 owners) is unchanged by
  construction. An ``archived`` marker is the capacity gate's decision, not
  this slice's.

Discipline that must survive:

- **No DELETE, no UPDATE, no INSERT.** All reads are SELECT-only on the
  connection the caller owns; the module never opens a transaction.
- **Journal-hole tamper detection is untouched.**
  ``vault/manifest.py:journal_gap_event_ids`` scans the whole occupied span
  of ``events``; because no event row is ever removed or rewritten, a hole
  there still means tampering, and that function is not modified.
- **Cold, not deleted.** A row can be in the archive *and* still in the hot
  DB. The archive never removes the hot copy; it makes a verifiable cold
  surface that a later capacity gate can act on.

What is exported (the "no longer open/hot" classes), keyed by primary key:

- ``contradictions`` — every row whose ``status`` is not ``OPEN``
  (RESOLVED / SUPERSEDED).
- ``curated_knowledge_entries`` — every row whose ``status`` is not
  ``ADMITTED`` (SUPERSEDED / INVALIDATED).
- ``curated_knowledge_supersession`` — every row (the supersession ledger is
  cold by construction).

Export is idempotent and incremental by key: the manifest holds the archived
key set, so a re-run appends only keys that are not already cold.

**Prohibited-claims discipline:** this module makes no claim about scientific
validity or reproducibility. It verifies that the exported BYTES are exactly
the bytes the database held, nothing more.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ARCHIVE_SCHEMA = 1
"""The cold-archive layout version. A new layout is a new version, never an
in-place rewrite of an existing archive."""

_MANIFEST_NAME = "manifest.json"
_CHUNK_DIR = "chunks"

# The cold tables and the predicate that makes a row cold, plus the primary
# key column used for the archived-key set. Read-only SELECT text.
_COLD_SELECTS: tuple[tuple[str, str, str], ...] = (
    (
        "contradictions",
        (
            "SELECT * FROM contradictions WHERE status != 'OPEN' "
            "ORDER BY contradiction_id"
        ),
        "contradiction_id",
    ),
    (
        "curated_knowledge_entries",
        (
            "SELECT * FROM curated_knowledge_entries "
            "WHERE status != 'ADMITTED' ORDER BY curated_id"
        ),
        "curated_id",
    ),
    (
        "curated_knowledge_supersession",
        (
            "SELECT * FROM curated_knowledge_supersession "
            "ORDER BY new_curated_id"
        ),
        "new_curated_id",
    ),
)


class ArchiveError(Exception):
    """Base for cold-archive failures."""


class ArchiveIntegrityError(ArchiveError):
    """The archive does not verify: a digest, a row set, or a file is wrong.

    Fail-closed by construction — a verification failure is a refusal, never
    a silent acceptance, because the archive's only job is to be provably
    the same bytes the database held.
    """


class ArchiveBindingError(ArchiveError):
    """The caller handed the archive a connection or path it cannot use."""


def _canon_bytes(obj: Any) -> bytes:
    """Canonical JSON bytes (sorted keys, no whitespace) — the digest input.

    Deterministic and independent of dict insertion order or sqlite column
    order, so the same row always hashes to the same digest.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ArchivedRow:
    """One cold row: its table, its primary key, and its canonical columns."""

    table: str
    key: str
    columns: dict[str, Any]

    def row_bytes(self) -> bytes:
        return _canon_bytes(
            {"table": self.table, "key": self.key, "columns": self.columns}
        )

    def digest(self) -> str:
        return _digest(self.row_bytes())


@dataclass(frozen=True)
class ArchiveStatus:
    """What the archive holds right now (read from the manifest only)."""

    rows: int
    tables: tuple[str, ...]
    chunk_count: int
    manifest_digest: str


@dataclass(frozen=True)
class ArchiveExportResult:
    """One export pass: what was appended and what the archive now holds."""

    appended: int
    total: int
    appended_by_table: dict[str, int]
    chunks_written: int


@dataclass(frozen=True)
class ArchiveVerifyResult:
    """A successful verification: the sizes and digests that were proved."""

    rows: int
    chunks: int
    files_checked: int
    row_digests_checked: int


class ColdArchive:
    """Additive cold archive rooted at a directory.

    The archive owns its directory layout: ``manifest.json`` plus
    ``chunks/chunk-NNNNNN.ndjson``. It never writes to the database and never
    removes a hot row.
    """

    def __init__(self, root: str | Path) -> None:
        root_path = Path(root)
        if root_path.exists() and not root_path.is_dir():
            raise ArchiveBindingError(
                f"archive root is not a directory: {root_path}")
        self._root = root_path
        self._manifest_path = root_path / _MANIFEST_NAME
        self._chunk_dir = root_path / _CHUNK_DIR

    # ── internals ──

    @property
    def root(self) -> Path:
        return self._root

    def _load_manifest(self) -> dict[str, Any] | None:
        if not self._manifest_path.is_file():
            return None
        try:
            data = json.loads(
                self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ArchiveIntegrityError(
                f"archive manifest is unreadable: {exc}") from None
        if not isinstance(data, dict) or data.get("schema") != ARCHIVE_SCHEMA:
            raise ArchiveIntegrityError(
                "archive manifest is missing or carries an unknown schema "
                f"version (expected {ARCHIVE_SCHEMA})")
        return data

    def _write_manifest(self, manifest: dict[str, Any]) -> str:
        self._root.mkdir(parents=True, exist_ok=True)
        payload = _canon_bytes(manifest)
        digest = _digest(payload)
        # Write to a sibling temp file and replace atomically, so a crash
        # mid-write can never leave a half-written manifest behind.
        tmp = self._manifest_path.with_suffix(".json.tmp")
        tmp.write_bytes(payload)
        tmp.replace(self._manifest_path)
        return digest

    def _archived_keys(self, manifest: dict[str, Any]) -> dict[str, set[str]]:
        """The archived key set per table, derived from the manifest.

        The manifest keys composite ``table:key``; the partition is on the
        FIRST colon so a key containing colons still round-trips.
        """
        keys: dict[str, set[str]] = {}
        for composite in manifest.get("row_digests", {}):
            table, _, key = composite.partition(":")
            keys.setdefault(table, set()).add(key)
        return keys

    def _row_from_row_factory(
        self, table: str, key_column: str, row: sqlite3.Row,
    ) -> ArchivedRow:
        # ``sqlite3.Row`` exposes ``keys()``, so ``dict(row)`` is the
        # column->value mapping. (Iterating a Row yields VALUES, not names —
        # SIM118's dict-shaped rewrite does not apply here.)
        columns = dict(row)
        key = columns.get(key_column)
        if not isinstance(key, str) or not key:
            raise ArchiveIntegrityError(
                f"cold table {table!r} row has no usable key column "
                f"{key_column!r}")
        return ArchivedRow(table=table, key=key, columns=columns)

    # ── export ──

    def export(
        self, conn: sqlite3.Connection, *, chunk_size: int = 500,
    ) -> ArchiveExportResult:
        """Append every not-yet-cold resolved/superseded row to the archive.

        SELECT-only on ``conn`` — the caller owns the connection and any
        transaction; this method never opens one. Idempotent by key.
        """
        if not isinstance(chunk_size, int) or chunk_size < 1:
            raise ArchiveBindingError(
                f"chunk_size must be a positive int, got {chunk_size!r}")
        manifest = self._load_manifest()
        row_digests: dict[str, str] = (
            dict(manifest["row_digests"]) if manifest is not None else {})
        archived = self._archived_keys(manifest or {"row_digests": {}})

        appended_by_table: dict[str, int] = {}
        pending: list[ArchivedRow] = []
        for table, sql, key_column in _COLD_SELECTS:
            already = archived.get(table, set())
            fresh: list[ArchivedRow] = []
            for row in conn.execute(sql).fetchall():
                candidate = self._row_from_row_factory(table, key_column, row)
                if candidate.key in already:
                    continue  # already cold: an export is a COPY, never a re-add
                fresh.append(candidate)
            if fresh:
                appended_by_table[table] = len(fresh)
                pending.extend(fresh)

        if not pending:
            # Nothing new: still report the true standing of the archive.
            status = self.status()
            return ArchiveExportResult(
                appended=0,
                total=status.rows if status is not None else 0,
                appended_by_table={},
                chunks_written=0,
            )

        self._chunk_dir.mkdir(parents=True, exist_ok=True)
        chunks: list[dict[str, Any]] = (
            list(manifest["chunks"]) if manifest is not None else [])
        chunks_written = 0
        for start in range(0, len(pending), chunk_size):
            batch = pending[start:start + chunk_size]
            body = b"".join(r.row_bytes() + b"\n" for r in batch)
            index = len(chunks) + 1
            name = f"chunk-{index:06d}.ndjson"
            (self._chunk_dir / name).write_bytes(body)
            chunks.append({
                "file": f"{_CHUNK_DIR}/{name}",
                "rows": len(batch),
                "digest": _digest(body),
                "tables": sorted({r.table for r in batch}),
            })
            chunks_written += 1
            row_digests.update(
                {f"{r.table}:{r.key}": r.digest() for r in batch}
            )

        manifest_out = {
            "schema": ARCHIVE_SCHEMA,
            "row_count": sum(c["rows"] for c in chunks),
            "tables": sorted({e.partition(":")[0] for e in row_digests}),
            "chunks": chunks,
            "row_digests": row_digests,
        }
        self._write_manifest(manifest_out)
        total = sum(c["rows"] for c in chunks)
        return ArchiveExportResult(
            appended=len(pending),
            total=total,
            appended_by_table=appended_by_table,
            chunks_written=chunks_written,
        )

    # ── read ──

    def status(self) -> ArchiveStatus | None:
        """The archive's standing, or None when it has never been written."""
        manifest = self._load_manifest()
        if manifest is None:
            return None
        return ArchiveStatus(
            rows=manifest["row_count"],
            tables=tuple(manifest["tables"]),
            chunk_count=len(manifest["chunks"]),
            manifest_digest=_digest(
                self._manifest_path.read_bytes()),
        )

    def verify(self) -> ArchiveVerifyResult:
        """Re-derive the archive from disk and prove it equals the manifest.

        Fail-closed: a missing manifest, a missing chunk, a wrong chunk
        digest, a wrong row digest, a duplicate key, or a key-set mismatch
        all raise ``ArchiveIntegrityError``.
        """
        manifest = self._load_manifest()
        if manifest is None:
            raise ArchiveIntegrityError(
                "no archive to verify: manifest is absent")

        seen: dict[str, str] = {}
        files_checked = 0
        row_digests_checked = 0
        rows_total = 0
        for chunk in manifest["chunks"]:
            rel = chunk["file"]
            path = self._root / rel
            if not path.is_file():
                raise ArchiveIntegrityError(
                    f"archive chunk is missing: {rel}")
            body = path.read_bytes()
            files_checked += 1
            if _digest(body) != chunk["digest"]:
                raise ArchiveIntegrityError(
                    f"archive chunk digest mismatch: {rel}")
            lines = [ln for ln in body.split(b"\n") if ln]
            if len(lines) != chunk["rows"]:
                raise ArchiveIntegrityError(
                    f"archive chunk row count mismatch: {rel} "
                    f"(manifest {chunk['rows']}, file {len(lines)})")
            rows_total += len(lines)
            for line in lines:
                try:
                    obj = json.loads(line.decode("utf-8"))
                    key = f"{obj['table']}:{obj['key']}"
                    actual = _digest(_canon_bytes(obj))
                except (ValueError, KeyError, TypeError) as exc:
                    raise ArchiveIntegrityError(
                        f"archive chunk {rel} carries an unusable row: "
                        f"{exc}") from None
                expected = manifest["row_digests"].get(key)
                if expected is None:
                    raise ArchiveIntegrityError(
                        f"archive row is not in the manifest: {key} "
                        f"(chunk {rel})")
                if actual != expected:
                    raise ArchiveIntegrityError(
                        f"archive row digest mismatch: {key} (chunk {rel})")
                if key in seen:
                    raise ArchiveIntegrityError(
                        f"archive row is duplicated: {key} (chunks "
                        f"{seen[key]} and {rel})")
                seen[key] = rel
                row_digests_checked += 1

        if rows_total != manifest["row_count"]:
            raise ArchiveIntegrityError(
                "archive row total mismatch: manifest "
                f"{manifest['row_count']}, files {rows_total}")
        # Every manifest row must also be on disk.
        on_disk = set(seen)
        in_manifest = set(manifest["row_digests"])
        if on_disk != in_manifest:
            missing = sorted(in_manifest - on_disk)
            extra = sorted(on_disk - in_manifest)
            raise ArchiveIntegrityError(
                "archive row set differs from the manifest "
                f"(manifest-only: {missing[:5]}, disk-only: {extra[:5]})")

        return ArchiveVerifyResult(
            rows=rows_total,
            chunks=len(manifest["chunks"]),
            files_checked=files_checked,
            row_digests_checked=row_digests_checked,
        )
