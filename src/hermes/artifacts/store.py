"""Content-hash-keyed artifact writes; immutable once committed (v4 §16.1).

Filesystem-backed content-addressed store (IDR-008):
  artifacts/<first 2 hex>/<next 2 hex>/<full 64-char hash>

Artifacts are written to the filesystem FIRST, then the DB metadata is
recorded within a transaction (IDR-013). If the DB commit fails, the
artifact content is orphaned but safe (no DB record = cannot be cited).
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from hermes.core import Clock, utc_now
from hermes.persistence.repositories import ArtifactRepository


def compute_content_hash(data: bytes) -> str:
    """SHA-256 of canonical bytes (IDR-009).

    The hash is computed over the exact bytes provided. The caller is
    responsible for canonicalization (e.g., UTF-8, LF) if cross-platform
    reproducibility is required. The store does not modify content.
    """
    return hashlib.sha256(data).hexdigest()


def _atomic_write(dest: Path, data: bytes) -> None:
    """Write ``data`` to ``dest`` atomically: a unique temp file in the same
    directory (same filesystem, so os.replace is atomic), fully written and
    flushed, then renamed over the destination. A crash at any point leaves
    only a ``*.tmp-*`` file at worst — never a truncated canonical artifact
    (red-team B1)."""
    import os
    import time

    sweep_start = time.time()
    # Best-effort sweep of a CRASHED writer's stale temps in this directory
    # (the atomic-write crash window, red-team B1 audit): a temp left behind
    # by a process that died mid-write is cleaned on the next write here.
    # mtime guard: anything created after we started sweeping is another
    # LIVE writer's temp — never touch it.
    for stale in dest.parent.glob(f"{dest.name}.tmp-*"):
        try:
            if stale.stat().st_mtime < sweep_start:
                stale.unlink()
        except OSError:
            pass

    tmp = dest.with_name(f"{dest.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()


def _sharded_path(artifact_root: Path, content_hash: str) -> Path:
    """Return the sharded filesystem path for a content hash (IDR-008)."""
    return Path(artifact_root) / content_hash[:2] / content_hash[2:4] / content_hash


class ArtifactStore:
    """Filesystem-backed content-addressed artifact store.

    Write path: content → compute hash → write to sharded path → record DB
    metadata. If the DB commit fails, the content is orphaned but safe.

    Read path: DB lookup → read content from sharded path.

    Immutability: once written, content is never modified in place. A "new
    version" is a new content hash → a new artifact_id (v4 §12).
    """

    def __init__(
        self,
        artifact_root: str | Path,
        repo: ArtifactRepository,
        clock: Clock | None = None,
    ):
        self._root = Path(artifact_root)
        self._repo = repo
        self._clock = clock or utc_now

    def write(
        self,
        data: bytes,
        artifact_type: str,
        producer: str,
        project_id: str | None = None,
        task_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Write artifact content and record metadata.

        Returns the artifact metadata dict. If the same content already
        exists (same hash), the existing record is returned (dedup).
        """
        content_hash = compute_content_hash(data)

        # Check for existing artifact (dedup)
        existing = self._repo.get_by_hash(content_hash)
        if existing is not None:
            return existing

        # Write content to filesystem FIRST (IDR-013), ATOMICALLY (B1):
        # the content lands under its final name only via os.replace of a
        # fully-written temp file in the same directory — a crash mid-write
        # can never leave a truncated file at the canonical path, so a
        # retry can never record a partial artifact as valid.
        dest = _sharded_path(self._root, content_hash)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest.exists():
            # Content exists on disk but no DB record (orphan from a
            # previous failed transaction). Reuse ONLY if it verifies
            # against the content hash; a partial/orphan file whose bytes
            # do not re-derive the hash is replaced (orphans have no DB
            # record, so overwriting cannot corrupt a cited artifact).
            try:
                if compute_content_hash(dest.read_bytes()) == content_hash:
                    pass
                else:
                    dest.unlink()
                    _atomic_write(dest, data)
            except OSError:
                dest.unlink()
                _atomic_write(dest, data)
        else:
            _atomic_write(dest, data)

        # Record DB metadata
        artifact_id = str(uuid.uuid4())
        rel_path = str(dest.relative_to(self._root))
        return self._repo.record(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            content_hash=content_hash,
            size_bytes=len(data),
            storage_path=rel_path,
            producer=producer,
            project_id=project_id,
            task_id=task_id,
            metadata=metadata,
        )

    def read(self, content_hash: str) -> bytes:
        """Read artifact content by content hash.

        Raises FileNotFoundError if the content is not on disk.
        """
        path = _sharded_path(self._root, content_hash)
        return path.read_bytes()

    def read_by_id(self, artifact_id: str) -> bytes:
        """Read artifact content by artifact_id (DB lookup → filesystem read).

        The storage_path column is never trusted as a path (B2): the joined
        path is resolved and must stay inside the artifact root — a tampered
        DB or bad restore containing ``..`` escapes fail closed instead of
        reading an arbitrary file.
        """
        meta = self._repo.get(artifact_id)
        root_resolved = self._root.resolve()
        path = (self._root / meta["storage_path"]).resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError:
            raise ValueError(
                f"storage_path {meta['storage_path']!r} for artifact "
                f"{artifact_id!r} escapes the artifact root") from None
        return path.read_bytes()

    def verify_integrity(self, artifact_id: str) -> bool:
        """Verify that the on-disk content hash matches the recorded hash."""
        meta = self._repo.get(artifact_id)
        data = self.read(meta["content_hash"])
        return compute_content_hash(data) == meta["content_hash"]
