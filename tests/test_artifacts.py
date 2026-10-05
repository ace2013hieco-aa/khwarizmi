"""Tests for the artifact store (v3 §16.1) — immutability, hashing, dedup."""
from __future__ import annotations

from pathlib import Path

import pytest

from hermes.artifacts.store import ArtifactStore, compute_content_hash
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ArtifactRepository


@pytest.fixture
def store_and_repo(tmp_path):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    artifact_root = tmp_path / "artifacts"
    repo = ArtifactRepository(conn)
    store = ArtifactStore(artifact_root, repo)
    yield store, repo
    conn.close()


class TestContentHash:
    def test_same_content_same_hash(self):
        h1 = compute_content_hash(b"hello world")
        h2 = compute_content_hash(b"hello world")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = compute_content_hash(b"hello world")
        h2 = compute_content_hash(b"hello World")
        assert h1 != h2

    def test_hash_is_64_chars_sha256(self):
        h = compute_content_hash(b"test")
        assert len(h) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in h)

    def test_empty_content_has_known_hash(self):
        h = compute_content_hash(b"")
        assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class TestArtifactWriteRead:
    def test_write_and_read_back(self, store_and_repo):
        store, _repo = store_and_repo
        data = b"test artifact content"
        meta = store.write(data, "TestArtifact", "test-producer")
        assert meta["artifact_type"] == "TestArtifact"
        assert meta["producer"] == "test-producer"
        assert meta["size_bytes"] == len(data)
        # Read content back
        read_data = store.read(meta["content_hash"])
        assert read_data == data

    def test_read_by_id(self, store_and_repo):
        store, _repo = store_and_repo
        data = b"content for id read"
        meta = store.write(data, "TestType", "producer-1")
        read_data = store.read_by_id(meta["artifact_id"])
        assert read_data == data

    def test_metadata_persisted(self, store_and_repo):
        store, repo = store_and_repo
        meta_dict = {"source": "experiment-1", "format": "json"}
        meta = store.write(b"data", "TestType", "p1", metadata=meta_dict)
        # Read back metadata
        fetched = repo.get(meta["artifact_id"])
        assert fetched["metadata"]["source"] == "experiment-1"
        assert fetched["metadata"]["format"] == "json"


class TestDeterministicHashes:
    def test_same_content_produces_same_hash(self, store_and_repo):
        store, _repo = store_and_repo
        meta1 = store.write(b"identical content", "Type1", "p1")
        meta2 = store.write(b"identical content", "Type1", "p2")
        # Same content → same hash (dedup)
        assert meta1["content_hash"] == meta2["content_hash"]
        # Same artifact_id returned (dedup)
        assert meta1["artifact_id"] == meta2["artifact_id"]

    def test_different_content_different_hash(self, store_and_repo):
        store, _repo = store_and_repo
        meta1 = store.write(b"content A", "Type1", "p1")
        meta2 = store.write(b"content B", "Type1", "p1")
        assert meta1["content_hash"] != meta2["content_hash"]

    def test_hash_is_content_only_not_filename(self, store_and_repo):
        """Hash is over canonical bytes, not filename or path (IDR-009)."""
        _store, _repo = store_and_repo
        h = compute_content_hash(b"content")
        # Moving the content (same bytes) → same hash
        h2 = compute_content_hash(b"content")
        assert h == h2


class TestDedup:
    def test_duplicate_content_returns_existing(self, store_and_repo):
        store, _repo = store_and_repo
        data = b"duplicate me"
        meta1 = store.write(data, "Type1", "p1")
        meta2 = store.write(data, "Type1", "p2", metadata={"different": "metadata"})
        # Should return the same artifact (dedup)
        assert meta1["artifact_id"] == meta2["artifact_id"]
        assert meta1["content_hash"] == meta2["content_hash"]

    def test_repo_exists_by_hash(self, store_and_repo):
        store, repo = store_and_repo
        meta = store.write(b"check exists", "Type1", "p1")
        assert repo.exists(meta["content_hash"]) is True
        assert repo.exists("nonexistent_hash") is False


class TestImmutability:
    def test_no_overwrite_path(self, store_and_repo):
        """Writing new content creates a new artifact, never overwrites (v3 §12)."""
        store, repo = store_and_repo
        meta1 = store.write(b"version 1", "Type1", "p1")
        meta2 = store.write(b"version 2", "Type1", "p1")
        # Both artifacts exist
        assert repo.get(meta1["artifact_id"]) is not None
        assert repo.get(meta2["artifact_id"]) is not None
        # Different hashes
        assert meta1["content_hash"] != meta2["content_hash"]
        # Original content still readable
        assert store.read(meta1["content_hash"]) == b"version 1"
        assert store.read(meta2["content_hash"]) == b"version 2"

    def test_content_hash_is_unique_constraint(self, store_and_repo):
        """The artifacts table has a UNIQUE constraint on content_hash."""
        store, repo = store_and_repo
        meta = store.write(b"unique content", "Type1", "p1")
        # Trying to insert a duplicate hash directly should fail
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            repo.record(
                artifact_id="different-id",
                artifact_type="Type1",
                content_hash=meta["content_hash"],
                size_bytes=13,
                storage_path="fake/path",
                producer="p2",
            )


class TestIntegrity:
    def test_verify_integrity_true(self, store_and_repo):
        store, _repo = store_and_repo
        meta = store.write(b"verifiable content", "Type1", "p1")
        assert store.verify_integrity(meta["artifact_id"]) is True

    def test_verify_integrity_detects_corruption(self, store_and_repo):
        store, _repo = store_and_repo
        meta = store.write(b"original", "Type1", "p1")
        # Corrupt the on-disk file
        path = Path(store._root) / meta["storage_path"]
        path.write_bytes(b"corrupted!!")
        assert store.verify_integrity(meta["artifact_id"]) is False


class TestAtomicWriteAndContainment:
    """Red-team B1/B2 hardening: temp+rename atomic writes with orphan hash
    verification, and storage_path containment on read_by_id."""

    def test_write_leaves_no_temp_files(self, store_and_repo, tmp_path):
        store, _repo = store_and_repo
        store.write(b"clean write", "Type1", "p1")
        leftovers = list(tmp_path.rglob("*.tmp-*"))
        assert leftovers == []

    def test_orphan_partial_file_replaced_not_recorded(self, store_and_repo, tmp_path):
        """B1: a truncated file at the canonical path (what a crash mid-write
        left under the OLD code) must be replaced, never reused and recorded
        as valid."""
        store, _repo = store_and_repo
        data = b"full valid content"
        h = compute_content_hash(data)
        dest = Path(store._root) / h[:2] / h[2:4] / h
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data[:7])  # simulated crash mid-write (truncated)

        meta = store.write(data, "Type1", "p1")
        assert store.read(h) == data                      # full content
        assert store.verify_integrity(meta["artifact_id"]) is True
        assert compute_content_hash(dest.read_bytes()) == h

    def test_valid_orphan_reused(self, store_and_repo, tmp_path):
        """B1: a content-consistent orphan (bytes match, no DB record) from a
        failed DB commit is still reused — dedup against disk is preserved."""
        store, _repo = store_and_repo
        data = b"orphan but intact"
        h = compute_content_hash(data)
        dest = Path(store._root) / h[:2] / h[2:4] / h
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)  # no DB record — the failed-commit orphan

        meta = store.write(data, "Type1", "p1")
        assert store.read(h) == data
        assert store.verify_integrity(meta["artifact_id"]) is True

    def test_storage_path_traversal_refused(self, store_and_repo, tmp_path):
        """B2: a tampered storage_path with '..' escapes the artifact root —
        read_by_id fails closed instead of reading an arbitrary file."""
        store, repo = store_and_repo
        secret = tmp_path / "secret.txt"
        secret.write_bytes(b"TOP SECRET")
        repo.record(
            artifact_id="evil-1", artifact_type="Type1",
            content_hash=compute_content_hash(b"x" * 64), size_bytes=0,
            storage_path="../secret.txt", producer="attacker",
        )
        with pytest.raises(ValueError, match="escapes the artifact root"):
            store.read_by_id("evil-1")

    def test_storage_path_absolute_refused(self, store_and_repo, tmp_path):
        """B2: an absolute storage_path also cannot redirect the read."""
        store, repo = store_and_repo
        repo.record(
            artifact_id="evil-2", artifact_type="Type1",
            content_hash=compute_content_hash(b"y" * 64), size_bytes=0,
            storage_path=str(tmp_path / "elsewhere.bin"), producer="attacker",
        )
        with pytest.raises(ValueError, match="escapes the artifact root"):
            store.read_by_id("evil-2")

    def test_stale_crash_temp_swept_on_next_write(self, store_and_repo, tmp_path):
        """S1 (audit): a temp file left by a crashed mid-write writer is
        swept on the next write — the crash window never leaves litter that
        could be mistaken for content, and the canonical artifact lands
        intact."""
        store, _repo = store_and_repo
        data = b"clean after crash"
        h = compute_content_hash(data)
        dest = Path(store._root) / h[:2] / h[2:4] / h
        dest.parent.mkdir(parents=True, exist_ok=True)
        stale = dest.with_name(f"{dest.name}.tmp-deadbeef")
        stale.write_bytes(b"partial garbage")

        meta = store.write(data, "Type1", "p1")
        assert store.read(h) == data
        assert store.verify_integrity(meta["artifact_id"]) is True
        leftovers = list(tmp_path.rglob("*.tmp-*"))
        assert leftovers == []
