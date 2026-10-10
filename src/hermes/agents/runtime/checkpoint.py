"""Checkpoints and resume (ARCHITECTURE_DELTA §2.3, §3.2, §4 B-2).

What a checkpoint is — and is not
---------------------------------
A checkpoint is the run's **derived working state**: the tick it reached, the
drafts it emitted, the derived delegation records it holds, and the content
digests that let a resume prove it is continuing the same run. It is *not* a
record of record, not a journal, and not a crossing: the runtime holds no
connection, opens no transaction, and appends no row (`repositories.py:92` stays
the only journal writer, §3.2). Durable effects still leave only as proposals to
the Orchestration API.

The store is a **port**. The default in-memory store is what a single process
uses; the file store exists so that "kill the process mid-run and resume" is a
real, testable property rather than a claim. Neither store takes a lock: the
file store writes one file per run with an atomic replace, so there is no
read-modify-write window for a private lock to protect (the B-2 constraint). A
run's identity is derived by rule from its command, so two processes writing the
same run id are writing the same content — the spine's lease fence is what keeps
a single writer, and this plane never participates in lease custody (§3.2.4).

The file store's single-writer precondition
-------------------------------------------
One writer per `run_id`, serialised by the **lease** and not by this store: the
plane holds no lease custody (§3.2.4) and takes no lock (B-2), so it cannot be
the component that decides which of two same-generation writers wins, and it must
not pretend to be. What the store does guarantee mechanically is that a collision
can neither corrupt nor crash: each write goes to its own uniquely named
temporary file and is then moved onto the run's document with one atomic replace,
so no two writers can share a temporary path (`os.replace` collisions such as
`[WinError 32] ...tmp -> ...json` are impossible by construction) and a reader
always sees one *complete* document — never an interleaved or torn one. Two
same-run writers therefore have a defined, benign outcome (the last complete write
is the state; nothing is truncated, nothing raises), which is a configuration
error against this precondition rather than a data-loss event.

The recovery chain
------------------
`RUNNING → NO_SIGNAL → FAILED` (v4 §6.3, `core/task_status.py`), applied as pure
functions over the checkpoint:

* heartbeat within the horizon → `LIVE` — the run is presumed alive and is left
  alone;
* a conclusive miss on a run with recorded progress → `RESUMABLE` — nothing is
  re-dispatched; the run can be continued *only* by an explicit `resume(...)`,
  and only from its own checkpoint;
* a conclusive miss on a run with no recorded progress → `NO_SIGNAL`;
* a second conclusive miss → `FAILED`, terminal, never re-dispatchable.

`RecoveryVerdict.may_dispatch` is `False` on every branch, including
`RESUMABLE`: recovery classifies, it never restarts work (B-2's second
constraint). That is the difference between "recover" and "a second scheduler".
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from hermes.agents.runtime.types import (
    RECOVERY_COMPLETE,
    RECOVERY_FAILED,
    RECOVERY_LIVE,
    RECOVERY_NO_SIGNAL,
    RECOVERY_RESUMABLE,
    Checkpoint,
    RecoveryVerdict,
    RuntimeFormatError,
)
from hermes.core.task_status import TaskStatus

#: Conclusive misses before a silent run is terminal: the first miss classifies,
#: the second fails it (v4 §6.3's "second conclusive miss").
MAX_MISSES = 2

#: Attempts a checkpoint's atomic replace gets before it fails loudly. Windows
#: refuses a `MoveFileEx` replace with `ACCESS_DENIED` while another writer's
#: replace of the same destination is in flight; the move did not happen, so
#: retrying it is lossless and loses no data. This is a **bound on retrying our
#: own move**, never a lock or an exclusion: both writers still race, and the last
#: complete write still wins (the single-writer precondition in the module
#: docstring is what makes two of them a configuration error).
_REPLACE_ATTEMPTS = 8


@runtime_checkable
class CheckpointStore(Protocol):
    """The checkpoint store port (§3.2.3: derived state, never a record)."""

    def put(self, checkpoint: Checkpoint) -> None: ...

    def get(self, run_id: str) -> Checkpoint | None: ...

    def owned(self, run_id: str, lease_generation: str) -> Checkpoint | None:
        """The checkpoint only when it is attributed to `lease_generation`."""
        ...

    def run_ids(self) -> tuple[str, ...]: ...


class InMemoryCheckpointStore:
    """Derived state for one process. No lock, no file, no journal."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, Checkpoint] = {}

    def put(self, checkpoint: Checkpoint) -> None:
        self._checkpoints[checkpoint.run_id] = checkpoint

    def get(self, run_id: str) -> Checkpoint | None:
        return self._checkpoints.get(run_id)

    def owned(self, run_id: str, lease_generation: str) -> Checkpoint | None:
        checkpoint = self._checkpoints.get(run_id)
        if checkpoint is None or checkpoint.lease_generation != lease_generation:
            return None
        return checkpoint

    def run_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._checkpoints))

    def delete(self, run_id: str) -> None:
        self._checkpoints.pop(run_id, None)


class FileCheckpointStore:
    """One JSON file per run, written with an atomic replace.

    Lock-free by construction: a reader sees either the previous or the new
    complete document, and no read-modify-write cycle exists to serialise. Every
    write goes to its own uniquely named temporary file first, so two writers can
    never share a temporary path and cannot interleave their bytes. A crash can
    leave a `*.tmp` file at worst; it never matches `*.json`, so it is never read
    as a document, and the canonical document is never truncated. One writer per
    run id, serialised by the lease — see the module docstring.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, run_id: str) -> Path:
        return self._root / f"{run_id}.json"

    def put(self, checkpoint: Checkpoint) -> None:
        path = self.path_for(checkpoint.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # A *unique* temporary file per write, then one atomic replace: two writers
        # racing on one run id cannot collide on a shared temporary path (the
        # `[WinError 32] ...tmp -> ...json` rename-collision class is impossible by
        # construction) and cannot interleave their bytes, because each writes its
        # own file. Whichever replaces last leaves one complete document.
        descriptor, tmp_name = tempfile.mkstemp(dir=path.parent,
                                                prefix=f"{path.name}.",
                                                suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(checkpoint.to_mapping(), sort_keys=True,
                                        indent=2, ensure_ascii=False))
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(_REPLACE_ATTEMPTS):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    # A transient refusal (the move did not happen): yield, then
                    # retry the same lossless move.
                    if attempt + 1 >= _REPLACE_ATTEMPTS:
                        raise
                    time.sleep(0.0005 * (attempt + 1))
        finally:
            if tmp.exists():
                # A failed replace must not leave a stray partial document behind.
                tmp.unlink()

    def get(self, run_id: str) -> Checkpoint | None:
        path = self.path_for(run_id)
        if not path.is_file():
            return None
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeFormatError(
                f"checkpoint {path.name} is unreadable: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeFormatError(f"checkpoint {path.name} is not a mapping")
        return Checkpoint.from_mapping(data)

    def owned(self, run_id: str, lease_generation: str) -> Checkpoint | None:
        checkpoint = self.get(run_id)
        if checkpoint is None or checkpoint.lease_generation != lease_generation:
            return None
        return checkpoint

    def run_ids(self) -> tuple[str, ...]:
        if not self._root.is_dir():
            return ()
        return tuple(sorted(path.stem for path in self._root.glob("*.json")))

    def delete(self, run_id: str) -> None:
        path = self.path_for(run_id)
        if path.is_file():
            path.unlink()


# ═══════════════════════ the recovery chain ═══════════════════════


def classify_recovery(checkpoint: Checkpoint, *, stale: bool) -> RecoveryVerdict:
    """Classify an interrupted run. Pure; `may_dispatch` is always `False`.

    `stale` is the caller's heartbeat judgement (the supervisor owns the clock
    and the horizon); everything else is the checkpoint's own state.
    """
    if checkpoint.is_terminal():
        return RecoveryVerdict(
            kind=RECOVERY_COMPLETE, misses=checkpoint.misses,
            reason=f"run is already terminal ({checkpoint.state})",
            may_resume=False, may_dispatch=False)
    if not stale:
        return RecoveryVerdict(
            kind=RECOVERY_LIVE, misses=checkpoint.misses,
            reason="heartbeat is within the horizon — the run is presumed alive",
            may_resume=False, may_dispatch=False)
    if checkpoint.misses >= 1:
        return RecoveryVerdict(
            kind=RECOVERY_FAILED, misses=checkpoint.misses + 1,
            reason="second conclusive miss — the run is FAILED and is never "
                   "re-dispatched (v4 §6.3, B-2)",
            may_resume=False, may_dispatch=False)
    if checkpoint.tick > 0:
        return RecoveryVerdict(
            kind=RECOVERY_RESUMABLE, misses=checkpoint.misses + 1,
            reason="conclusive miss with recorded progress — resumable from its "
                   "own checkpoint, but nothing is re-dispatched",
            may_resume=True, may_dispatch=False)
    return RecoveryVerdict(
        kind=RECOVERY_NO_SIGNAL, misses=checkpoint.misses + 1,
        reason="conclusive miss with no recorded progress — nothing to resume",
        may_resume=False, may_dispatch=False)


def apply_recovery(checkpoint: Checkpoint, verdict: RecoveryVerdict, *,
                   at: str) -> Checkpoint:
    """Fold a verdict back into the checkpoint (pure; returns a new record)."""
    state = checkpoint.state
    if verdict.kind == RECOVERY_FAILED:
        state = TaskStatus.FAILED.value
    elif verdict.kind == RECOVERY_NO_SIGNAL:
        state = TaskStatus.NO_SIGNAL.value
    return checkpoint.with_changes(state=state, misses=verdict.misses,
                                   updated_at=at)
