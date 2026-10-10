"""Subagent dispatch/completion as child tasks — the B-2 slot (§4 B-2).

The borrowed *shape*, and the five constraints that bind it
-----------------------------------------------------------
B-2 permits borrowing the behaviour of a durable delegation record
(`pending → done`, with pruning) and states that the source is a counter-example
in five specific ways. This module implements the shape and encodes each
constraint mechanically:

1. **No private lock.** `InMemoryDelegationStore` holds a dict and takes no lock;
   `FileDelegationStore` writes one file per record with an atomic replace, so
   there is no read-modify-write cycle to serialise. The suite scans this
   module's source for `Lock`, `fcntl` and `msvcrt` and fails on any of them.
2. **No restart re-dispatch, no second scheduler.** `recover()` classifies
   `PENDING` records it finds after a restart as `NO_SIGNAL` and returns them —
   it executes nothing, and there is no code path in this module that runs a
   child. A resumed run's delegation is re-derived from the checkpoint's
   re-emitted proposal and hits the spine's idempotency, never this module's
   "restart everything pending" loop.
3. **Lease-generation attribution on every record.** `plan()` refuses without a
   non-blank generation (`LOCK`), and `complete()`/`refuse()` refuse when the
   caller's generation does not match the record's (`LOCK`) — a stale writer
   cannot finish someone else's delegation. Attribution comes from the caller's
   lease, never from a settable ambient variable (B-4).
4. **Payload ≤4 KiB or artifact-ref overflow.** `payload_digest` is always
   recorded; a payload over the cap is handed to the artifact port and the record
   keeps the ref. With no port wired, an oversized payload refuses (`RATIONALE`)
   rather than being silently truncated.
5. **`repositories.py:92` stays the only journal writer.** Nothing here imports
   `hermes.persistence`, opens SQLite, or appends an event: the child's
   *admission* is a proposal to the Orchestration API, and this record is derived
   working state beside it.

A delegated child is a **child task**, never a direct call
---------------------------------------------------------
`Delegator` builds the child's command (a derived, deterministic
`task_id` + `idempotency_key`) and its `TaskContext`; the child's own run is
started by `run.py` — as a separate `run()` with the child profile, its own
bounds, its own checkpoint — and only after the spine admitted the child's
creation. This module never calls a profile.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from hermes.agents.runtime.config import ProfileSpec
from hermes.agents.runtime.types import (
    LOCK,
    MALFORMED_PAYLOAD,
    MAX_PAYLOAD_BYTES,
    RATIONALE,
    ROLE,
    DelegationRecord,
    DelegationState,
    RunLimits,
    RuntimeFormatError,
    RuntimeRefusal,
    TaskContext,
    child_idempotency_key_of,
    child_task_id_of,
    delegation_id_of,
    digest_of,
    size_of,
)
from hermes.core import Clock, utc_now
from hermes.security.boundaries import UntrustedContent


@runtime_checkable
class ArtifactOverflowPort(Protocol):
    """The one artifact-facing port the plane may use (§3.3).

    Two operations, both about *bytes*: hand over an oversized payload and get
    back an opaque handle, or dereference a handle back into bytes. The port
    mints nothing the plane trusts — `artifacts/store.py` recomputes
    content-hash identity at its own write boundary — so this plane never
    authors, caches or interprets an artifact id.
    """

    def store(self, body: bytes, *, media_type: str) -> str: ...

    def dereference(self, ref: str) -> bytes: ...


@runtime_checkable
class DelegationStore(Protocol):
    """Derived-record storage (B-2 constraint 1: lock-free, no journal)."""

    def put(self, record: DelegationRecord) -> None: ...

    def get(self, delegation_id: str) -> DelegationRecord | None: ...

    def records(self, *, run_id: str = "") -> tuple[DelegationRecord, ...]: ...

    def delete(self, delegation_id: str) -> None: ...


class InMemoryDelegationStore:
    """One process's derived records. No lock — none is needed or permitted."""

    def __init__(self) -> None:
        self._records: dict[str, DelegationRecord] = {}

    def put(self, record: DelegationRecord) -> None:
        self._records[record.delegation_id] = record

    def get(self, delegation_id: str) -> DelegationRecord | None:
        return self._records.get(delegation_id)

    def records(self, *, run_id: str = "") -> tuple[DelegationRecord, ...]:
        items = [record for record in self._records.values()
                 if not run_id or record.run_id == run_id]
        return tuple(sorted(items, key=lambda record: record.delegation_id))

    def delete(self, delegation_id: str) -> None:
        self._records.pop(delegation_id, None)


class FileDelegationStore:
    """One JSON file per record, atomically replaced. No lock file, ever."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, delegation_id: str) -> Path:
        return self._root / f"{delegation_id}.json"

    def put(self, record: DelegationRecord) -> None:
        path = self.path_for(record.delegation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_mapping(), sort_keys=True, indent=2,
                                    ensure_ascii=False))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    def get(self, delegation_id: str) -> DelegationRecord | None:
        path = self.path_for(delegation_id)
        if not path.is_file():
            return None
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeFormatError(
                f"delegation record {path.name} is unreadable: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeFormatError(f"{path.name} is not a mapping")
        return DelegationRecord.from_mapping(data)

    def records(self, *, run_id: str = "") -> tuple[DelegationRecord, ...]:
        if not self._root.is_dir():
            return ()
        found: list[DelegationRecord] = []
        for path in sorted(self._root.glob("del_*.json")):
            record = self.get(path.stem)
            if record is not None and (not run_id or record.run_id == run_id):
                found.append(record)
        return tuple(found)

    def delete(self, delegation_id: str) -> None:
        path = self.path_for(delegation_id)
        if path.is_file():
            path.unlink()


class Delegator:
    """Builds, attributes, completes and prunes delegation records.

    It holds no authority: the child profile must be *declared* (ROLE otherwise),
    the payload must fit or overflow (`RATIONALE`), and completion is fenced by
    the lease generation (`LOCK`).
    """

    def __init__(
        self,
        *,
        store: DelegationStore,
        profiles: Mapping[str, ProfileSpec],
        clock: Clock = utc_now,
        artifacts: ArtifactOverflowPort | None = None,
        max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    ) -> None:
        self._store = store
        self._profiles = dict(profiles)
        self._clock = clock
        self._artifacts = artifacts
        self._max_payload_bytes = max_payload_bytes

    # ── read surfaces ──

    def records(self, *, run_id: str = "") -> tuple[DelegationRecord, ...]:
        return self._store.records(run_id=run_id)

    def pending(self, *, run_id: str = "") -> tuple[DelegationRecord, ...]:
        return tuple(record for record in self._store.records(run_id=run_id)
                     if record.state == DelegationState.PENDING.value)

    def child_context(self, record: DelegationRecord, *,
                      context: tuple[UntrustedContent, ...] = (),
                      limits: RunLimits | None = None,
                      depth: int = 1) -> TaskContext:
        """The child's bounded context — built here, run by `run.py`, not by us."""
        return TaskContext(
            task_id=record.child_task_id,
            project_id=record.project_id,
            lease_generation=record.lease_generation,
            iteration=1,
            context=context,
            inputs=(record.artifact_ref,) if record.artifact_ref else (),
            limits=limits if limits is not None else RunLimits(),
            depth=depth,
            parent_run_id=record.run_id,
            parent_task_id=record.parent_task_id,
        )

    # ── planning ──

    def plan(
        self,
        *,
        run_id: str,
        parent_task_id: str,
        project_id: str,
        child_profile: str,
        lease_generation: str,
        slot: int,
        spec: Mapping[str, Any],
        intent_kind: str,
    ) -> DelegationRecord | RuntimeRefusal:
        """Derive one `PENDING` record — or refuse, as data."""
        if not lease_generation.strip():
            return RuntimeRefusal(
                code=LOCK,
                detail="a delegation cannot be attributed without a lease "
                       "generation (B-4)",
                profile=child_profile)
        declared = self._profiles.get(child_profile)
        if declared is None:
            return RuntimeRefusal(
                code=ROLE,
                detail=f"profile {child_profile!r} is not a declared profile "
                       f"({sorted(self._profiles)}) — a plane cannot delegate to "
                       f"an authority nobody declared",
                profile=child_profile)
        if not str(parent_task_id).strip() or not str(project_id).strip():
            return RuntimeRefusal(
                code=MALFORMED_PAYLOAD,
                detail="a delegation needs a parent task and a project",
                profile=child_profile)
        if not isinstance(spec, Mapping):
            return RuntimeRefusal(
                code=MALFORMED_PAYLOAD,
                detail=f"a delegation spec must be a mapping, got "
                       f"{type(spec).__name__}",
                profile=child_profile)

        payload = {"spec": dict(spec), "profile": child_profile,
                   "project_id": project_id, "parent_task_id": parent_task_id,
                   "slot": int(slot)}
        payload_size = size_of(payload)
        artifact_ref = ""
        if payload_size > self._max_payload_bytes:
            if self._artifacts is None:
                return RuntimeRefusal(
                    code=RATIONALE,
                    detail=f"delegated payload is {payload_size} bytes, over the "
                           f"{self._max_payload_bytes}-byte cap, and no artifact "
                           f"overflow port is wired — refusing rather than "
                           f"truncating",
                    profile=child_profile)
            artifact_ref = self._artifacts.store(
                json.dumps(payload, sort_keys=True,
                           ensure_ascii=False).encode("utf-8"),
                media_type="application/json")

        child_task_id = child_task_id_of(parent_task_id, child_profile, slot)
        now = self._clock()
        record = DelegationRecord(
            delegation_id=delegation_id_of(run_id, parent_task_id, child_task_id),
            run_id=run_id,
            parent_task_id=parent_task_id,
            child_task_id=child_task_id,
            project_id=project_id,
            profile=child_profile,
            agent_profile=declared.agent_profile,
            lease_generation=lease_generation,
            state=DelegationState.PENDING.value,
            intent_kind=intent_kind,
            payload_digest=digest_of(payload),
            artifact_ref=artifact_ref,
            created_at=now,
            updated_at=now,
        )
        self._store.put(record)
        return record

    def child_command(self, record: DelegationRecord, *,
                      spec: Mapping[str, Any], slot: int,
                      task_type: str = "AGENT_TASK") -> dict[str, Any]:
        """The child's `INSERT_TASK` payload — every id derived, none authored."""
        return {
            "task_id": record.child_task_id,
            "task_type": task_type,
            "profile": record.agent_profile,
            "spec": dict(spec),
            "idempotency_key": child_idempotency_key_of(
                record.parent_task_id, record.profile, slot, spec),
        }

    # ── completion ──

    def complete(
        self,
        record: DelegationRecord,
        *,
        lease_generation: str,
        child_intent_id: str = "",
        child_run_id: str = "",
        child_state: str = "",
        child_digest: str = "",
        outcome: str = "",
    ) -> DelegationRecord | RuntimeRefusal:
        """Mark a record `DONE` — only under the generation that created it."""
        refusal = self._require_attribution(record, lease_generation)
        if refusal is not None:
            return refusal
        updated = record.with_changes(
            state=DelegationState.DONE.value,
            child_intent_id=child_intent_id or record.child_intent_id,
            child_run_id=child_run_id or record.child_run_id,
            child_state=child_state or record.child_state,
            child_digest=child_digest or record.child_digest,
            outcome=outcome or record.outcome,
            updated_at=self._clock())
        self._store.put(updated)
        return updated

    def refuse(self, record: DelegationRecord, *, lease_generation: str,
               detail: str) -> DelegationRecord | RuntimeRefusal:
        """Mark a record `REFUSED` (the child's admission was refused)."""
        refusal = self._require_attribution(record, lease_generation)
        if refusal is not None:
            return refusal
        updated = record.with_changes(state=DelegationState.REFUSED.value,
                                     outcome=detail, updated_at=self._clock())
        self._store.put(updated)
        return updated

    def _require_attribution(self, record: DelegationRecord,
                             lease_generation: str) -> RuntimeRefusal | None:
        if not lease_generation.strip():
            return RuntimeRefusal(
                code=LOCK, detail="completion without a lease generation (B-4)",
                profile=record.profile)
        if record.lease_generation != lease_generation:
            return RuntimeRefusal(
                code=LOCK,
                detail=f"delegation {record.delegation_id} is attributed to lease "
                       f"generation {record.lease_generation!r}, not "
                       f"{lease_generation!r} — a stale writer cannot complete "
                       f"another generation's record (B-2/B-4)",
                profile=record.profile)
        return None

    # ── restart behaviour: classify, never re-dispatch ──

    def recover(self, *, run_id: str = "") -> tuple[DelegationRecord, ...]:
        """Classify `PENDING` records found after a restart as `NO_SIGNAL`.

        Returns what it classified — and runs nothing. There is deliberately no
        "resume the pending ones" branch: that is B-2's forbidden second
        scheduler. A resumed run re-derives its delegation from its checkpoint's
        re-emitted proposal, and the spine's idempotency is what makes that safe.
        """
        recovered: list[DelegationRecord] = []
        for record in self.pending(run_id=run_id):
            updated = record.with_changes(
                state=DelegationState.NO_SIGNAL.value,
                misses=record.misses + 1,
                outcome="not re-dispatched after a restart (B-2: no restart "
                        "re-dispatch, no second scheduler)",
                updated_at=self._clock())
            self._store.put(updated)
            recovered.append(updated)
        return tuple(recovered)

    def prune(self, *, run_id: str = "",
              before: str | None = None) -> tuple[str, ...]:
        """Drop terminal records; `PENDING`/`NO_SIGNAL` records are never pruned.

        `before`, when given, bounds pruning to records last updated strictly
        earlier (string comparison on the ISO-8601 clock — the same ordering the
        journal uses).
        """
        pruned: list[str] = []
        for record in self._store.records(run_id=run_id):
            if not record.is_terminal():
                continue
            if before is not None and record.updated_at >= before:
                continue
            self._store.delete(record.delegation_id)
            pruned.append(record.delegation_id)
        return tuple(pruned)
