"""SourceOutcome repository (ResearchSourceProvider step 6 — IDR-030).

The task-side write path for SOURCE_SEARCH / SOURCE_FETCH outcomes — the
"natural seam" the source recording lands in (the god-module ruling: land the
source recording in its seam first, then split the cluster once, post-step-6).

ONE public mutation boundary (`SourceOutcomeRepository.record`), internally
factored into pure validation/preparation helpers + one transactional commit
(remediation §E). The controller owns the terminal task transition
(RUNNING → SUCCEEDED/FAILED) — this method never touches task status (SD-03).

Carried contracts (the thrice-folded design record + remediation):
- OB-01 — the one-shot hash-SET = the outcome-record hash + the per-result /
  per-payload content hashes; observation metadata (timestamps, the fetch
  ``FetchLogEntry`` stream) never enters.
- OB-02 — the reuse path re-verifies the PERSISTED row (both hashes) before
  reusing; a tampered row fails the reuse, not merely the later dereference.
- SD-04 — get-by-hash-first, inside the write transaction.
- SD2-02 — the one-shot is a hash-SET COMPARISON (the EXTRACT 3c model), not
  a bare has-prior probe.
- SD-05 / SD2-04 — ``dereference_ref`` resolves ``source_result`` /
  ``source_payload`` against the ``artifacts`` table with the FULL content
  hash as the only key, project-edge-scoped.
- §D — global content artifact + project-scoped provenance: the artifact row
  is global (``content_hash`` UNIQUE), ownership is edge-carried; cross-project
  identical content is legitimate sharing, the conflict class survives only
  for the divergent same-task one-shot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from hermes.core import Clock, utc_now
from hermes.core.task_status import TaskStatus

if TYPE_CHECKING:
    from hermes.persistence.repositories import ArtifactRepository
    from hermes.tools.research_sources import FetchedPayload
from hermes.research.source_templates import (
    SOURCE_FETCH_TEMPLATE,
    SOURCE_SEARCH_TEMPLATE,
)
from hermes.tools.research_sources import (
    WEB_SEARCH_PROVIDERS,
    content_hash_of_search_result,
    observation_hash_of_search_result,
    outcome_record_hash,
    search_result_from_mapping,
    search_result_to_mapping,
)

__all__ = [
    "SOURCE_ARTIFACT_TYPES",
    "SourceOutcomeBindingError",
    "SourceOutcomeConflictError",
    "SourceOutcomeError",
    "SourceOutcomeIntegrityError",
    "SourceOutcomeRepository",
    "SourceRepos",
    "_source_artifact_resolves",
    "source_artifact_is_web_derived",
]


class SourceOutcomeError(Exception):
    """Base error for the source-outcome write path (fail-closed: nothing
    written on any subclass)."""


class SourceOutcomeBindingError(SourceOutcomeError):
    """The outcome is not the output of the producing task it claims to be
    (V6-P7-A2-01/02 — task exists, project match, template marker, RUNNING,
    spec refs match) — no write."""


class SourceOutcomeIntegrityError(SourceOutcomeError):
    """A caller-supplied identity (content_hash / observation_hash / payload
    hash / outcome hash) does not match the canonical derivation, or a reused
    persisted row fails re-verification (OB-02) — fail-closed, nothing
    written."""


class SourceOutcomeConflictError(SourceOutcomeError):
    """One-shot refusal (A2-03 / OB-01): the producing task already produced
    an outcome with a DIFFERENT semantic hash-SET. One execution, one output —
    a divergent re-execution is refused, never overwritten."""


# The artifact-type taxonomy (remediation §G) — the only types the source
# slice may write; unknown types are rejected at admission.
SOURCE_ARTIFACT_TYPES = frozenset({
    "source_search", "source_result", "source_fetch_outcome", "source_payload",
})


def _source_artifact_resolves(
    conn: Any, project_id: str, content_hash: str, artifact_type: str,
    *, upstream_task_id: str | None = None,
) -> bool:
    """Project-scoped resolution of a ``source_result:<hash>`` /
    ``source_payload:<hash>`` reference against the ``artifacts`` table.

    The FULL content hash is the key (SD2-04 — never the truncated alias).
    The artifact row is GLOBAL (``content_hash`` UNIQUE, migration 1), so the
    project scoping is edge-carried (remediation §D): the reference resolves
    iff the artifact exists AND it is reachable from a task of ``project_id``
    via §14 ``derived_from`` edges — hop 1 (outcome → task) or hop 2
    (per-result/payload → outcome → task). Cross-project sharing is
    legitimate: the second project's edges make it resolve.

    S6-A1 — the ref PREFIX is the type: ``artifact_type`` (when given) is
    part of the resolution, so a ``source_result:`` reference can never
    dereference a ``source_payload`` row (or vice versa). Without it the
    type confusion let admission accept a payload hash cited as a
    ``source_result`` ref (SD-05).

    R01 — when ``upstream_task_id`` is given, resolution ALSO requires the
    artifact to be reachable from THAT task (two-hop ``derived_from``:
    task → outcome → artifact): a SOURCE_FETCH's source refs must BELONG to
    its cited search task, not merely to the project (the project-edge
    check alone is ambiguous under the global-content sharing model).
    """
    sql = (
        "SELECT 1 FROM artifacts a WHERE a.content_hash = ?"
        "  AND a.artifact_type = ?"
        "  AND ("
        "  a.project_id = ?"
        "  OR EXISTS (SELECT 1 FROM provenance_edges e"
        "             JOIN tasks t ON t.task_id = e.upstream_id"
        "             WHERE e.artifact_id = a.artifact_id"
        "               AND e.edge_type = 'derived_from'"
        "               AND t.project_id = ?)"
        "  OR EXISTS (SELECT 1 FROM provenance_edges e1"
        "             JOIN provenance_edges e2 ON e2.artifact_id = e1.upstream_id"
        "             JOIN tasks t ON t.task_id = e2.upstream_id"
        "             WHERE e1.artifact_id = a.artifact_id"
        "               AND e1.edge_type = 'derived_from'"
        "               AND e2.edge_type = 'derived_from'"
        "               AND t.project_id = ?)"
        ")"
    )
    params: list[Any] = [content_hash, artifact_type,
                         project_id, project_id, project_id]
    if upstream_task_id is not None:
        sql += (
            " AND EXISTS (SELECT 1 FROM provenance_edges e1"
            "             JOIN provenance_edges e2"
            "               ON e2.upstream_id = e1.artifact_id"
            "             WHERE e1.upstream_id = ?"
            "               AND e1.edge_type = 'derived_from'"
            "               AND e2.artifact_id = a.artifact_id"
            "               AND e2.edge_type = 'derived_from')"
        )
        params.append(upstream_task_id)
    row = conn.execute(sql, tuple(params)).fetchone()
    return row is not None


def source_artifact_retracted(
    conn: Any, project_id: str, artifact_id: str,
) -> bool:
    """Whether a source artifact is currently retracted in a project (N9).

    Reads the S5 operational projection only: a ``ResearchDecision``
    artifact of ``project_id`` with a ``supersedes`` edge to
    ``artifact_id`` (the decision + edge S5 writes atomically with the
    ``SourceRetracted`` journal event, which remains the authoritative
    history). Exact relational predicates — no LIKE, no JSON scanning.
    Pure read of committed state: deterministic, no writes, no cache.
    """
    if (not isinstance(project_id, str) or not project_id
            or not isinstance(artifact_id, str) or not artifact_id):
        return False
    row = conn.execute(
        "SELECT 1 FROM provenance_edges e "
        "JOIN artifacts a ON a.artifact_id = e.artifact_id "
        "WHERE e.upstream_id = ? AND e.edge_type = 'supersedes' "
        "AND a.project_id = ? AND a.artifact_type = 'ResearchDecision' "
        "LIMIT 1",
        (artifact_id, project_id)).fetchone()
    return row is not None


def source_artifact_is_web_derived(conn: Any, artifact_id: str) -> bool:
    """Whether a source artifact is web-derived (IDR-046 D2).

    The provider predicate on the row the choke point already holds: a
    row is web-derived iff *any* contributing provider is in
    ``WEB_SEARCH_PROVIDERS`` (``hermes.tools.research_sources`` — the
    single definition; no other module may hardcode the four ids). The
    marker rides the row's own metadata, dispatched on the row's type:

    - ``source_search`` / ``source_fetch_outcome``: the ``providers`` key
      (the sorted, de-duplicated contributing-provider list E8 authors);
    - ``source_result``: ``metadata.record.provider`` (the lossless
      ``SearchResult`` round-trip);
    - ``source_payload``: ``metadata.source_result_ref`` dereferenced ONE
      hop to its ``source_result`` row, then the same ``record.provider``
      read.

    Pure read of committed state beside ``source_artifact_retracted`` —
    same shape and discipline: no writes, no exceptions, project scoping
    left to the caller. Any other type, a missing row, or unparseable
    metadata     returns ``False``; absence of the key also returns ``False``
    (provably safe: no row can be web-derived without ``providers``,
    because the four web providers were unreachable until the allowlist
    amendment that ships with the marker).
    """
    if (not isinstance(artifact_id, str) or not artifact_id):
        return False
    row = conn.execute(
        "SELECT artifact_type, metadata_json FROM artifacts "
        "WHERE artifact_id = ?",
        (artifact_id,)).fetchone()
    if row is None:
        return False
    try:
        artifact_type = row["artifact_type"]
        metadata_json = row["metadata_json"]
    except (KeyError, IndexError, TypeError):
        return False
    import json as _json
    try:
        meta = _json.loads(metadata_json or "{}")
    except ValueError:
        return False
    if not isinstance(meta, dict):
        return False
    if artifact_type in ("source_search", "source_fetch_outcome"):
        providers = meta.get("providers")
        if not isinstance(providers, list):
            return False
        return any(isinstance(p, str) and p in WEB_SEARCH_PROVIDERS
                   for p in providers)
    if artifact_type == "source_result":
        record = meta.get("record")
        if not isinstance(record, dict):
            return False
        provider = record.get("provider")
        return isinstance(provider, str) and provider in WEB_SEARCH_PROVIDERS
    if artifact_type == "source_payload":
        ref = meta.get("source_result_ref")
        if not isinstance(ref, str):
            return False
        prefix, sep, rest = ref.partition(":")
        if not sep or prefix != "source_result" or not rest:
            return False
        target = conn.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE content_hash = ? AND artifact_type = 'source_result' "
            "ORDER BY created_at LIMIT 1",
            (rest,)).fetchone()
        if target is None:
            return False
        try:
            target_id = target["artifact_id"]
        except (KeyError, IndexError, TypeError):
            return False
        if not isinstance(target_id, str) or not target_id:
            return False
        return source_artifact_is_web_derived(conn, target_id)
    return False


def _proposed_set(outcome: object, outcome_kind: str) -> frozenset[str]:
    """The one-shot hash-SET (OB-01): the outcome-record hash PLUS the
    per-result/per-payload content hashes. Observation metadata never
    enters (the outcome hash excludes timestamps/log streams).

    Module-level and pure (DG-4 G-1): a function of its two arguments only —
    no connection, no SQL, no transaction, no event, no clock, no identity
    authorship. ``record`` computes it BEFORE ``BEGIN IMMEDIATE``.
    """
    s = {outcome_record_hash(outcome, outcome_kind)}
    if outcome_kind == "search":
        for r in getattr(outcome, "per_provider", ()):
            s.add(r.content_hash)
    else:
        for f in getattr(outcome, "per_source", ()):
            s.add(f.artifact.content_hash)
    return frozenset(s)


@dataclass(frozen=True)
class SourceRepos:
    """The per-tick source-slice repository bundle — built over the CURRENT
    fenced connection in ``Controller._refresh_fence`` (SD2-03 / HD-03).

    Exposes exactly the two write methods + the read resolver +
    ``load_search_results`` (the fetch task's persisted-input resolution,
    D2). NO connection attribute — a handler cannot reach the DB except
    through these methods (HD-02: the typed bundle is the only handler
    contract; ``repos._conn IS fenced`` is fixture-asserted).
    """

    artifacts: ArtifactRepository
    source: SourceOutcomeRepository

    def record(
        self,
        project_id: str,
        task_id: str,
        outcome: object,
        *,
        outcome_kind: str,
        produced_by: str = "",
    ) -> dict:
        return self.source.record(
            project_id, task_id, outcome,
            outcome_kind=outcome_kind, produced_by=produced_by,
        )

    def dereference(self, project_id: str, ref: str) -> bool:
        return self.source.dereference_ref(project_id, ref)

    def load_search_results(self, search_task_id: str) -> list:
        return self.source.load_search_results(search_task_id)

    def read_payload(self, ref: str) -> bytes | None:
        """The M3 payload reader delegate: resolve ``source_payload:`` /
        ``source_result:`` refs to their stored payload bytes (raw fetched
        content). Handler contexts envelope the result in
        ``UntrustedContent`` before any judgment surface — the raw bytes
        never cross the context boundary unenveloped.
        """
        return self.source.read_payload_bytes(ref)


class SourceOutcomeRepository:
    """The ONE source-outcome write boundary (design record D3 / remediation §E).

    ``record`` validates the outcome's identities (semantic content hashes,
    observation hashes, payload hashes, the outcome-record hash), then inside
    the write transaction re-checks the task binding (exists / project /
    template marker / RUNNING / spec-refs match), the project existence, and
    the one-shot (prior hash-SET by task vs the proposed SET — IDENTICAL
    reuses, DIVERGENT refuses, NEW inserts). Rows + §14 edges commit in ONE
    transaction; the controller owns the RUNNING → SUCCEEDED/FAILED
    transition (SD-03 — this method never touches task status).

    The FETCH path persists raw payload bytes through the injected
    ``ArtifactStore`` (content → filesystem → DB row, inside the same
    transaction — IDR-013; an orphaned file without a row is safe, never
    citable). ``store`` may be None for search-only wiring; a fetch outcome
    with no store fails closed.
    """

    def __init__(
        self,
        conn: Any,
        store: Any = None,
        clock: Clock | None = None,
    ) -> None:
        # Lazy: repositories.py imports this module at its top; the cycle is
        # broken by resolving repository names here, inside methods.
        from hermes.persistence.repositories import (
            ArtifactRepository,
            _json_loads,
        )
        self._conn = conn
        self._store = store
        self._clock = clock or utc_now
        self._artifacts = ArtifactRepository(conn, clock)
        self._json_loads = _json_loads

    # ── public write boundary ──

    def record(
        self,
        project_id: str,
        task_id: str,
        outcome: object,
        *,
        outcome_kind: str,
        produced_by: str = "",
    ) -> dict:
        """Persist an outcome atomically with its artifacts + §14 edges,
        bound to its producing task (one public mutation path).

        Raises ``SourceOutcomeBindingError`` (task binding), ``SourceOutcomeIntegrityError``
        (identity re-derivation / payload alignment / persisted-row
        re-verification), ``SourceOutcomeConflictError`` (one-shot divergent
        refusal). Returns a summary dict. The task's terminal transition is
        the CONTROLLER's (SD-03).
        """
        if outcome_kind not in ("search", "fetch"):
            raise SourceOutcomeError(
                f"outcome_kind must be 'search' or 'fetch', got {outcome_kind!r}")
        # Pure validation BEFORE the transaction (identity is derived, never
        # authored — ADV-01/06; payload alignment, GC-02).
        self._validate_identities(outcome, outcome_kind)
        proposed = _proposed_set(outcome, outcome_kind)

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._validate_task_binding(project_id, task_id, outcome, outcome_kind)
            self._validate_project(project_id)
            decision = self._resolve_idempotency(task_id, proposed)
            summary = self._commit(
                project_id, task_id, outcome, outcome_kind,
                produced_by or f"task:{task_id}", decision)
            self._conn.execute("COMMIT")
            return summary
        except SourceOutcomeError:
            self._conn.execute("ROLLBACK")
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # ── read surface (the fetch task's persisted input, D2) ──

    def load_search_results(self, search_task_id: str) -> list:
        """Reconstruct the ``SearchResult`` stream from the search task's
        PERSISTED ``source_result`` artifacts — the fetch input, never a
        hand-authored list (D2). Lossless round-trip (OQ-1(b) / OB-05).

        S6-A4 — the selection is EDGE-based (the same reachability the
        resolver uses), not ``task_id``-based: ``task_id`` is stamped only at
        write time, so a task that REUSED another task's content rows (global
        content + edge-carried ownership, §D) would otherwise find an empty
        input while ``dereference_ref`` resolves the same refs — the two read
        surfaces must agree. Two hops: the outcome's ``derived_from`` edge to
        the task, then each result's ``derived_from`` edge to the outcome.
        """
        rows = self._conn.execute(
            "SELECT a.* FROM artifacts a "
            "WHERE a.artifact_type = 'source_result' "
            "  AND EXISTS ("
            "    SELECT 1 FROM provenance_edges e1 "
            "    JOIN provenance_edges e2 ON e2.upstream_id = e1.artifact_id "
            "    WHERE e1.upstream_id = ? AND e1.edge_type = 'derived_from' "
            "      AND e2.artifact_id = a.artifact_id "
            "      AND e2.edge_type = 'derived_from'"
            "  ) "
            "ORDER BY a.created_at, a.artifact_id",
            (search_task_id,),
        ).fetchall()
        results = []
        for row in rows:
            meta = self._json_loads(row["metadata_json"]) or {}
            record = meta.get("record")
            try:
                results.append(search_result_from_mapping(record))
            except ValueError as exc:
                raise SourceOutcomeIntegrityError(
                    f"persisted source_result artifact {row['artifact_id']!r} "
                    f"of task {search_task_id!r} is not losslessly "
                    f"reconstructable: {exc}") from exc
        return results

    def dereference_ref(self, project_id: str, ref: str) -> bool:
        """The step-6 resolver extension (SD-05 / SD2-04): resolve
        ``source_result:<full-hash>`` / ``source_payload:<full-hash>``
        against the ``artifacts`` table, project-edge-scoped. A missing ref
        FAILS (never a form-checked pass); the FULL hash is the only key;
        the truncated ``[:24]`` alias is never accepted here.

        S6-A1 — the ref PREFIX is honored as the artifact type: a
        ``source_result:`` ref resolves only ``source_result`` rows and a
        ``source_payload:`` ref only ``source_payload`` rows (no type
        confusion).
        """
        if not isinstance(ref, str) or ":" not in ref:
            return False
        artifact_type, _, artifact_id = ref.partition(":")
        if artifact_type not in ("source_result", "source_payload"):
            return False
        if len(artifact_id) != 64 or not all(
                c in "0123456789abcdef" for c in artifact_id):
            return False  # never trust a truncated alias as a key (SD2-04/§18)
        return _source_artifact_resolves(
            self._conn, project_id, artifact_id, artifact_type)

    def read_payload_bytes(self, ref: str) -> bytes | None:
        """Resolve a ``source_payload:<full-hash>`` / ``source_result:<full-hash>``
        ref to its stored payload bytes — the raw fetched content (M3 trust
        boundary).

        Typed resolution mirrors ``dereference_ref`` (SD-05 / S6-A1): the
        prefix must match the artifact row's type (no type confusion), and the
        FULL 64-hex hash is the only key (a truncated alias is never accepted).
        Returns None when the ref does not dereference or the store holds no
        bytes (search results carry no payload — only ``source_payload`` rows
        have stored content). The raw bytes are the caller's ONLY via this
        method; the handler context wraps them in ``UntrustedContent`` so no
        unenveloped fetched text reaches a judgment surface.
        """
        if not isinstance(ref, str) or ":" not in ref:
            return None
        artifact_type, _, artifact_id = ref.partition(":")
        if artifact_type not in ("source_result", "source_payload"):
            return None
        if len(artifact_id) != 64 or not all(
                c in "0123456789abcdef" for c in artifact_id):
            return None
        if self._store is None:
            return None
        row = self._conn.execute(
            "SELECT 1 FROM artifacts WHERE content_hash = ? "
            "AND artifact_type = ?",
            (artifact_id, artifact_type),
        ).fetchone()
        if row is None:
            return None
        try:
            return self._store.read(artifact_id)  # content-addressed
        except FileNotFoundError:
            return None
    def _validate_identities(self, outcome: object, outcome_kind: str) -> None:
        """Re-derive EVERY identity with the shipped helpers; a mismatch
        fails closed before the write (EC-V6 / ADV-01/06 discipline)."""
        if outcome_kind == "search":
            for r in getattr(outcome, "per_provider", ()):
                expected = content_hash_of_search_result(r)
                if r.content_hash != expected:
                    raise SourceOutcomeIntegrityError(
                        f"search result {r.result_id!r}: content_hash "
                        f"{r.content_hash!r} does not match the canonical "
                        f"semantic identity {expected!r} — identity is "
                        f"derived, never authored (ADV-01/06)")
        else:  # fetch
            payloads = tuple(getattr(outcome, "payloads", ()) or ())
            by_id: dict[str, object] = {}
            for p in payloads:
                by_id[p.artifact.artifact_id] = p
            for f in getattr(outcome, "per_source", ()):
                payload = by_id.get(f.artifact.artifact_id)
                if payload is None:
                    raise SourceOutcomeIntegrityError(
                        f"fetched source {f.source.result_id!r}: payload with "
                        f"artifact_id {f.artifact.artifact_id!r} is missing — "
                        f"payloads dereference by artifact_id, never by "
                        f"position (GC-02)")
                pl = cast("FetchedPayload", payload)
                if self._sha256(pl.raw_bytes) != f.artifact.content_hash:
                    raise SourceOutcomeIntegrityError(
                        f"fetched source {f.source.result_id!r}: "
                        f"sha256(raw_bytes) != artifact.content_hash — "
                        f"content identity is derived (FD-06)")
                if f.artifact.content_hash != pl.artifact.content_hash:
                    raise SourceOutcomeIntegrityError(
                        f"fetched source {f.source.result_id!r}: carrier "
                        f"content_hash mismatch (A1)")
            if {p.artifact.artifact_id for p in payloads} != {
                    f.artifact.artifact_id for f in getattr(outcome, "per_source", ())}:
                raise SourceOutcomeIntegrityError(
                    "payload/per_source alignment mismatch — every payload "
                    "must belong to a fetched source and vice versa (A1/GC-02)")

    @staticmethod
    def _sha256(data: bytes) -> str:
        import hashlib
        return hashlib.sha256(data).hexdigest()

    # ── in-transaction validation ──

    def _validate_task_binding(
        self, project_id: str, task_id: str, outcome: object, outcome_kind: str,
    ) -> None:
        """A2-01/02 — checked INSIDE the write transaction so the status read
        is atomic with the write (TOCTOU closure, V6-P7-A2-02)."""
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,),
        ).fetchone()
        if row is None:
            raise SourceOutcomeBindingError(
                f"source outcome refused: producing task {task_id!r} does not "
                f"exist (V6-P7-A2-01)")
        if row["project_id"] != project_id:
            raise SourceOutcomeBindingError(
                f"source outcome refused: producing task {task_id!r} belongs "
                f"to project {row['project_id']!r}, not {project_id!r} "
                f"(V6-P7-A2-01)")
        spec = self._json_loads(row["spec_json"]) or {}
        template = (spec.get("template") or "").strip().casefold()
        expected = (SOURCE_SEARCH_TEMPLATE if outcome_kind == "search"
                    else SOURCE_FETCH_TEMPLATE)
        if template != expected:
            raise SourceOutcomeBindingError(
                f"source outcome refused: producing task {task_id!r} is not "
                f"a {expected} task (spec.template={template!r}) "
                f"(V6-P7-A2-01)")
        if row["status"] != TaskStatus.RUNNING.value:
            raise SourceOutcomeBindingError(
                f"source outcome refused: producing task {task_id!r} is "
                f"{row['status']}, not RUNNING (V6-P7-A2-02) — output may "
                f"only be accepted from a task currently executing")
        # spec refs must match the outcome's actual refs (A2-01)
        if outcome_kind == "search":
            # The multi-provider aggregate (`combine`) drops the request log,
            # so the provider is derived from BOTH the log (when present) and
            # the delivered per-provider results; a mix of providers under a
            # claimed log provider is a binding violation (fail closed).
            log = getattr(outcome, "request_log", None)
            log_provider = getattr(log, "provider", None) \
                if log is not None else None
            result_providers: set[str] = set()
            for r in getattr(outcome, "per_provider", ()):
                if getattr(r, "provider", None) is None:
                    # S6-B1 — a result that fails to declare its provider is
                    # refused, never silently dropped from the agreement
                    # check (its semantic identity REQUIRES a provider; a
                    # provider-less record under a provider-bound task is a
                    # forged/malformed carrier).
                    raise SourceOutcomeBindingError(
                        f"source outcome refused: search result "
                        f"{getattr(r, 'result_id', '?')!r} declares no "
                        f"provider — every delivered result must name its "
                        f"provider (S6-B1)")
                result_providers.add(cast(str, getattr(r, "provider", None)))
            if log_provider is not None and len(result_providers) > 1:
                raise SourceOutcomeBindingError(
                    "source outcome refused: search outcome mixes providers "
                    f"{sorted(cast(set[str], result_providers))} under log "
                    f"provider {log_provider!r} (V6-P7-A2-01)")
            # S6-A2 — the log and the results must AGREE when both are
            # present: a single result provider that contradicts the claimed
            # log provider is the same forgery as a mix (a forged outcome can
            # cite an arxiv log while delivering pubmed records).
            if log_provider is not None and result_providers \
                    and result_providers != {log_provider}:
                raise SourceOutcomeBindingError(
                    "source outcome refused: search outcome log provider "
                    f"{log_provider!r} contradicts the delivered results "
                    f"{sorted(cast(set[str], result_providers))} "
                    f"(V6-P7-A2-01)")
            actual_provider = log_provider
            if actual_provider is None and len(result_providers) == 1:
                actual_provider = next(iter(cast(set[str], result_providers)))
            if actual_provider != spec.get("provider"):
                raise SourceOutcomeBindingError(
                    f"source outcome refused: search outcome provider "
                    f"{actual_provider!r} does not match the producing task's "
                    f"spec.provider {spec.get('provider')!r} (V6-P7-A2-01)")
        else:
            # P1 (pre-step-7 closure) — re-check the fetch task's SEARCH
            # LINEAGE inside the write transaction (the V6-P7-A2 discipline):
            # the producing task's spec.search_task_id must resolve to a
            # SOURCE_SEARCH task of the SAME project. The gateway enforces
            # this at admission, but a stale/forged row (or a bypassed
            # admission) must not reach the write path — a fetch outcome may
            # only be recorded for a task whose search input is its own
            # project's search.
            search_task_id = spec.get("search_task_id")
            if not isinstance(search_task_id, str) or not search_task_id:
                raise SourceOutcomeBindingError(
                    "source outcome refused: fetch task "
                    f"{task_id!r} carries no spec.search_task_id — a fetch "
                    f"outcome requires the producing search lineage (P1)")
            srow = self._conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (search_task_id,),
            ).fetchone()
            if srow is None:
                raise SourceOutcomeBindingError(
                    "source outcome refused: fetch task "
                    f"{task_id!r} cites search task {search_task_id!r} "
                    f"which does not exist (P1 lineage)")
            if srow["project_id"] != project_id:
                raise SourceOutcomeBindingError(
                    "source outcome refused: fetch task "
                    f"{task_id!r} cites search task {search_task_id!r} of "
                    f"project {srow['project_id']!r}, not {project_id!r} "
                    f"— the search lineage must be same-project (P1)")
            sspec = self._json_loads(srow["spec_json"]) or {}
            if (sspec.get("template") or "").strip().casefold() \
                    != SOURCE_SEARCH_TEMPLATE:
                raise SourceOutcomeBindingError(
                    "source outcome refused: fetch task "
                    f"{task_id!r} cites {search_task_id!r} which is not a "
                    f"SOURCE_SEARCH task (P1 lineage)")
            # R04 — the fetch's provider must AGREE with its cited search's
            # provider (the fetched sources ARE the search's results; the
            # provider routes the adapter, so a pmc fetch over an arxiv
            # search is a routing/provenance contradiction).
            task_provider = spec.get("provider")
            if task_provider != sspec.get("provider"):
                raise SourceOutcomeBindingError(
                    "source outcome refused: fetch task "
                    f"{task_id!r} provider {task_provider!r} contradicts "
                    f"its cited search task {search_task_id!r} provider "
                    f"{sspec.get('provider')!r} (R04)")
            # R01 — the cited search task must be a DECLARED dependency of
            # the producing fetch task (re-checked here, not trusted from
            # admission alone): the task graph must express search → fetch.
            dep = self._conn.execute(
                "SELECT 1 FROM task_dependencies "
                "WHERE task_id = ? AND depends_on_task_id = ?",
                (task_id, search_task_id),
            ).fetchone()
            if dep is None:
                raise SourceOutcomeBindingError(
                    "source outcome refused: fetch task "
                    f"{task_id!r} does not declare its cited search task "
                    f"{search_task_id!r} as a task-graph dependency (R01)")
            # R01 — every spec ref must BELONG to the cited search task
            # (two-hop derived_from reachability), not merely resolve in the
            # project: the fetch input must be the cited search's own result
            # set. Combined with the A2-01 outcome ⊆ spec-refs check below,
            # the fetch outcome can never introduce results outside the
            # cited search task's result set.
            spec_refs = set(spec.get("source_refs") or [])
            for ref in sorted(spec_refs):
                if not ref.startswith("source_result:"):
                    raise SourceOutcomeBindingError(
                        "source outcome refused: fetch task "
                        f"{task_id!r} carries a non-source_result spec ref "
                        f"{ref!r} (R01)")
                if not _source_artifact_resolves(
                        self._conn, project_id, ref[len("source_result:"):],
                        "source_result", upstream_task_id=search_task_id):
                    raise SourceOutcomeBindingError(
                        "source outcome refused: fetch task "
                        f"{task_id!r} spec ref {ref!r} is not produced by "
                        f"its cited search task {search_task_id!r} — the "
                        f"fetch may only consume its own search's results "
                        f"(R01)")
            # R04 (defense-in-depth) — the fetch outcome's sources must all
            # declare the task's provider (the same provider-agreement
            # discipline as the search branch): a forged carrier that
            # delivers records under a different provider label is refused
            # at the write path even if the refs happen to match.
            source_providers: set[str] = set()
            for src in (
                *getattr(outcome, "per_source", ()),
                *getattr(outcome, "no_full_text", ()),
                *getattr(outcome, "failed", ()),
            ):
                prov = getattr(src.source, "provider", None)
                if prov is None:
                    raise SourceOutcomeBindingError(
                        "source outcome refused: fetch outcome source "
                        f"{getattr(src.source, 'result_id', '?')!r} "
                        f"declares no provider (R04)")
                source_providers.add(cast(str, prov))
            if source_providers and source_providers != {task_provider}:
                raise SourceOutcomeBindingError(
                    "source outcome refused: fetch outcome sources "
                    f"{sorted(source_providers)} contradict the task's "
                    f"provider {task_provider!r} (R04)")
            actual = {
                content_hash_of_search_result(f.source)
                for f in getattr(outcome, "per_source", ())
            }
            actual |= {
                content_hash_of_search_result(n.source)
                for n in getattr(outcome, "no_full_text", ())
            }
            actual |= {
                content_hash_of_search_result(fl.source)
                for fl in getattr(outcome, "failed", ())
            }
            for h in sorted(actual):
                if f"source_result:{h}" not in spec_refs:
                    raise SourceOutcomeBindingError(
                        f"source outcome refused: fetch outcome references "
                        f"source_result:{h} which is not among the producing "
                        f"task's spec.source_refs (V6-P7-A2-01)")

    def _validate_project(self, project_id: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM projects WHERE project_id = ?", (project_id,),
        ).fetchone()
        if row is None:
            raise SourceOutcomeBindingError(
                f"Project not found: {project_id!r} — source outcomes are "
                f"project-scoped artifacts (V6-P7-F03)")

    def _resolve_idempotency(
        self, task_id: str, proposed: frozenset[str],
    ) -> str:
        """The one-shot (A2-03 / SD2-02 / OB-01): prior artifact content
        hashes BY TASK (the persisted source-outcome rows) vs the proposed
        SET. EQUAL → IDENTICAL (crash-retry reuse); DIFFERENT → DIVERGENT
        (refusal); none → NEW."""
        prior = self._conn.execute(
            "SELECT content_hash FROM artifacts WHERE task_id = ? "
            "AND artifact_type IN ('source_search','source_result',"
            "'source_fetch_outcome','source_payload')",
            (task_id,),
        ).fetchall()
        if not prior:
            return "NEW"
        existing = {r["content_hash"] for r in prior}
        if existing == proposed:
            return "IDENTICAL"
        return "DIVERGENT"

    # ── the transactional commit (THE ONLY writer) ──

    def _commit(
        self,
        project_id: str,
        task_id: str,
        outcome: object,
        outcome_kind: str,
        produced_by: str,
        decision: str,
    ) -> dict:
        if decision == "DIVERGENT":
            raise SourceOutcomeConflictError(
                f"source outcome refused: task {task_id!r} already produced "
                f"an outcome with a different content hash-SET — one "
                f"execution, one output (A2-03/OB-01); identical "
                f"re-acceptance is idempotent, divergent output is not")
        ts = self._clock()
        if outcome_kind == "search":
            records, edges = self._prepare_search(
                project_id, task_id, outcome, produced_by, ts)
        else:
            records, edges = self._prepare_fetch(
                project_id, task_id, outcome, produced_by, ts)

        written: list[str] = []
        reused: list[str] = []
        for rec in records:
            existing = self._artifacts.get_by_hash(rec["content_hash"])
            if existing is not None:
                # SD-04 — get-by-hash-first, inside the transaction: reuse the
                # existing row (content-addressing is global); OB-02 re-verifies
                # the PERSISTED row before reusing.
                self._verify_reused_row(existing, rec)
                reused.append(existing["artifact_id"])
                continue
            self._artifacts.record(
                artifact_id=rec["artifact_id"],
                artifact_type=rec["artifact_type"],
                content_hash=rec["content_hash"],
                size_bytes=rec["size_bytes"],
                storage_path=rec["storage_path"],
                producer=rec["producer"],
                project_id=project_id,
                task_id=task_id,
                metadata=rec["metadata"],
            )
            written.append(rec["artifact_id"])
        for artifact_id, upstream_id, edge_type in edges:
            self._conn.execute(
                "INSERT OR IGNORE INTO provenance_edges "
                "(artifact_id, upstream_id, edge_type, created_at) "
                "VALUES (?, ?, ?, ?)",
                (artifact_id, upstream_id, edge_type, ts),
            )
        # IDR-040 §3 — auto-emit: a fetch that RECORDS a REMOVED_OR_RETRACTED
        # hazard (HZ-02 — kind is derived only from a provider-declared
        # retraction marker, never bare presence) is an EXECUTED observation
        # of a source retraction. Emit the ratified SourceRetracted audit
        # event for each retracted source in the SAME transaction as the
        # outcome record — the observation and the event are one atomic
        # fact, so the re-review advisory is driven by real execution.
        # NEW only: IDENTICAL reuse re-delivers an already-committed outcome
        # whose event was emitted at its first commit (a crash before commit
        # rolls the record AND the event back together).
        if decision == "NEW" and outcome_kind == "fetch":
            retracted: dict[str, str] = {}
            for n in getattr(outcome, "no_full_text", ()):
                if getattr(n, "no_full_text_kind", None) == "REMOVED_OR_RETRACTED":
                    ref = "source_result:" + content_hash_of_search_result(
                        n.source)
                    retracted.setdefault(ref, "")
            if retracted:
                # Lazy (module-import cycle): repositories.py imports this
                # module at its top — same resolution pattern as __init__.
                from hermes.persistence.repositories import _append_event_to_db
                for ref in sorted(retracted):
                    _append_event_to_db(
                        self._conn, self._clock, "SourceRetracted",
                        project_id, task_id, caused_by=f"task:{task_id}",
                        reason=f"fetch {task_id} recorded REMOVED_OR_RETRACTED",
                        artifact_ids=[ref],
                        payload={
                            "artifact_id": ref,
                            "no_full_text_kind": "REMOVED_OR_RETRACTED",
                            "observed_by_task": task_id,
                        },
                    )
        return {
            "outcome_kind": outcome_kind,
            "decision": decision,
            "task_id": task_id,
            "project_id": project_id,
            "artifacts_written": sorted(written),
            "artifacts_reused": sorted(reused),
            "edges": len(edges),
        }

    def _verify_reused_row(self, existing: dict, proposed: dict) -> None:
        """OB-02 — reuse re-verifies the PERSISTED row before reusing: for a
        ``source_result`` row, reconstruct the record and recompute BOTH
        hashes against the stored values (an observation-field tamper that
        content_hash alone cannot see FAILS here, not merely at the later
        dereference).

        Scope honesty (S6-A5): ``source_result`` rows carry the full
        record + observation_hash and are re-verified in full; outcome rows
        (``source_search`` / ``source_fetch_outcome``) verify content_hash
        only — their metadata is AUDIT-ONLY (no decision surface reads it),
        the semantic outcome identity lives in the content_hash itself, and
        observation fields legitimately vary across runs by design, so there
        is no second hash to re-derive (OB-04's inconsistent-forge honesty
        applies).

        R02 — the artifact TYPE is part of the reuse contract: ``content_hash``
        is globally unique but type-blind, so a same-hash/different-type row
        (e.g. an existing ``source_result`` proposed as ``source_payload``)
        is semantic type-confusion. Same hash + same type → reusable; same
        hash + different type → REJECTED here, before the reuse is reported
        (never silently coerced, never a duplicate row, never left for the
        resolver to discover later)."""
        if existing["artifact_type"] != proposed["artifact_type"]:
            raise SourceOutcomeIntegrityError(
                f"reused artifact row type mismatch: existing "
                f"{existing['artifact_type']!r} vs proposed "
                f"{proposed['artifact_type']!r} for content_hash "
                f"{existing['content_hash']!r} — same hash, different "
                f"artifact type is refused, never reused (R02)")
        if existing["content_hash"] != proposed["content_hash"]:
            raise SourceOutcomeIntegrityError(
                f"reused artifact row content_hash mismatch: "
                f"{existing['content_hash']!r} vs {proposed['content_hash']!r} "
                f"— the persisted row is corrupt (OB-02)")
        if proposed["artifact_type"] != "source_result":
            return
        meta = existing.get("metadata") or {}
        stored_obs = meta.get("observation_hash")
        if not isinstance(stored_obs, str):
            raise SourceOutcomeIntegrityError(
                f"reused source_result row {existing['artifact_id']!r} lacks "
                f"an observation_hash — the row is not a step-6 source_result "
                f"(OB-02)")
        try:
            record = search_result_from_mapping(meta.get("record"))
        except ValueError as exc:
            raise SourceOutcomeIntegrityError(
                f"reused source_result row {existing['artifact_id']!r} is not "
                f"losslessly reconstructable: {exc} (OB-02)") from exc
        if content_hash_of_search_result(record) != existing["content_hash"]:
            raise SourceOutcomeIntegrityError(
                f"reused source_result row {existing['artifact_id']!r}: "
                f"semantic content_hash does not match the persisted record — "
                f"tampered/corrupt row (OB-02)")
        if observation_hash_of_search_result(record) != stored_obs:
            raise SourceOutcomeIntegrityError(
                f"reused source_result row {existing['artifact_id']!r}: "
                f"observation_hash re-verification failed — an observation "
                f"field was tampered (content_hash alone cannot detect it; "
                f"OB-02)")

    # ── record preparation (pure — no writes) ──

    def _prepare_search(
        self,
        project_id: str,
        task_id: str,
        outcome: object,
        produced_by: str,
        ts: str,
    ) -> tuple[list[dict], list[tuple[str, str, str]]]:
        records: list[dict] = []
        edges: list[tuple[str, str, str]] = []
        outcome_hash = outcome_record_hash(outcome, "search")
        outcome_id = "art_" + outcome_hash
        records.append({
            "artifact_id": outcome_id,
            "artifact_type": "source_search",
            "content_hash": outcome_hash,
            "size_bytes": 0,
            "storage_path": "inline://source_search",
            "producer": produced_by,
            "metadata": self._search_outcome_metadata(outcome),
        })
        edges.append((outcome_id, task_id, "derived_from"))
        for r in getattr(outcome, "per_provider", ()):
            rid = "art_" + r.content_hash
            records.append({
                "artifact_id": rid,
                "artifact_type": "source_result",
                "content_hash": r.content_hash,
                "size_bytes": 0,
                "storage_path": "inline://source_result",
                "producer": produced_by,
                "metadata": {
                    "record": search_result_to_mapping(r),
                    "observation_hash": observation_hash_of_search_result(r),
                },
            })
            edges.append((rid, outcome_id, "derived_from"))
        return records, edges

    def _prepare_fetch(
        self,
        project_id: str,
        task_id: str,
        outcome: object,
        produced_by: str,
        ts: str,
    ) -> tuple[list[dict], list[tuple[str, str, str]]]:
        records: list[dict] = []
        edges: list[tuple[str, str, str]] = []
        outcome_hash = outcome_record_hash(outcome, "fetch")
        outcome_id = "art_" + outcome_hash
        records.append({
            "artifact_id": outcome_id,
            "artifact_type": "source_fetch_outcome",
            "content_hash": outcome_hash,
            "size_bytes": 0,
            "storage_path": "inline://source_fetch_outcome",
            "producer": produced_by,
            "metadata": self._fetch_outcome_metadata(outcome, task_id),
        })
        edges.append((outcome_id, task_id, "derived_from"))
        # the fetch outcome used the search task's outcome as input (§14)
        search_task_id = self._spec_search_task_id(task_id)
        if search_task_id is not None:
            edges.append((outcome_id, search_task_id, "used_as_input"))
        # payload bytes → filesystem + DB row inside THIS transaction (IDR-013)
        payloads = tuple(getattr(outcome, "payloads", ()) or ())
        by_id = {p.artifact.artifact_id: p for p in payloads}
        for f in getattr(outcome, "per_source", ()):
            payload = by_id.get(f.artifact.artifact_id)
            if payload is None:
                raise SourceOutcomeIntegrityError(
                    f"fetched source {f.source.result_id!r}: payload missing "
                    f"at commit (GC-02)")
            if self._store is None:
                raise SourceOutcomeError(
                    "fetch outcome refused: no artifact store wired for the "
                    "source-slice repository — payload bytes must persist "
                    "with the outcome (IDR-013)")
            row = self._store.write(
                payload.raw_bytes,
                artifact_type="source_payload",
                producer=produced_by,
                project_id=project_id,
                task_id=task_id,
                metadata={
                    "source_result_ref":
                        "source_result:" + content_hash_of_search_result(f.source),
                },
            )
            # R02 (final review) — the store dedups by hash only; the TYPE
            # discipline belongs to this slice's write boundary: an existing
            # row with the same content hash but a DIFFERENT artifact type
            # must never stand in for a source_payload (a successful write
            # followed by a resolver failure is the exact R02 failure class).
            if row["artifact_type"] != "source_payload":
                raise SourceOutcomeIntegrityError(
                    f"fetched source {f.source.result_id!r}: content hash "
                    f"{row['content_hash']!r} already exists as a "
                    f"{row['artifact_type']} row — same hash, different "
                    f"artifact type is refused, never reused as a payload "
                    f"(R02)")
            if row["content_hash"] != f.artifact.content_hash:
                raise SourceOutcomeIntegrityError(
                    f"fetched source {f.source.result_id!r}: store returned "
                    f"content_hash {row['content_hash']!r} != "
                    f"{f.artifact.content_hash!r} (FD-06)")
            edges.append((row["artifact_id"], task_id, "derived_from"))
            edges.append((row["artifact_id"], outcome_id, "derived_from"))
        return records, edges

    def _spec_search_task_id(self, task_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT spec_json FROM tasks WHERE task_id = ?", (task_id,),
        ).fetchone()
        if row is None:
            return None
        spec = self._json_loads(row["spec_json"]) or {}
        value = spec.get("search_task_id")
        return value if isinstance(value, str) else None

    # ── outcome metadata (the lossless persisted form; audit-only fields) ──

    @staticmethod
    def _search_outcome_metadata(outcome: object) -> dict:
        log = getattr(outcome, "request_log", None)
        request_log = None
        if log is not None:
            request_log = {
                "provider": log.provider,
                "endpoint": log.endpoint,
                "query": log.query,
                "request_params_redacted": dict(log.request_params_redacted or {}),
                # audit-only (observation — excluded from the outcome hash)
                "timestamps": list(log.timestamps or ()),
                "cursor_chain": list(log.cursor_chain or ()),
                "page_counts": [list(pc) for pc in (log.page_counts or ())],
                "reconciliation": log.reconciliation,
                "total_is_estimate": log.total_is_estimate,
                "hazard_verdicts": list(log.hazard_verdicts or ()),
                "provider_spec_version": log.provider_spec_version,
                "raw_artifact_hashes": list(log.raw_artifact_hashes or ()),
            }
        # IDR-046 D2 — the provenance marker: the union of per-provider
        # result carriers with the request-log carrier when present. The
        # union is what makes the marker total across both the success
        # path (per-provider results) and the shortfall paths (log only).
        providers: set[str] = set()
        for result in getattr(outcome, "per_provider", ()) or ():
            provider = getattr(result, "provider", None)
            if isinstance(provider, str) and provider:
                providers.add(provider)
        if log is not None:
            log_provider = getattr(log, "provider", None)
            if isinstance(log_provider, str) and log_provider:
                providers.add(log_provider)
        return {
            "outcome_kind": "search",
            "aggregate": getattr(outcome, "aggregate", ""),
            "notes": list(getattr(outcome, "notes", ()) or ()),
            "request_log": request_log,
            "providers": sorted(providers),
        }

    def _fetch_outcome_metadata(self, outcome: object,
                                task_id: str | None = None) -> dict:
        log_entries = []
        for e in getattr(outcome, "fetch_log", ()) or ():
            log_entries.append({
                "source_ref": e.source_ref,
                "status": e.status,
                "failure_class": e.failure_class,
                "hazard_verdict": e.hazard_verdict,
                "size_bytes": e.size_bytes,
                "content_hash": e.content_hash,
                "access_timestamp_utc": e.access_timestamp_utc,
                "attempts": e.attempts,
                "attempt_verdicts": list(e.attempt_verdicts or ()),
            })
        per_source = []
        for f in getattr(outcome, "per_source", ()):
            per_source.append({
                "source_ref": "source_result:"
                    + content_hash_of_search_result(f.source),
                "resolution": "fetched",
                "content_hash": f.artifact.content_hash,
            })
        for n in getattr(outcome, "no_full_text", ()):
            per_source.append({
                "source_ref": "source_result:"
                    + content_hash_of_search_result(n.source),
                "resolution": "no_full_text",
                "kind": n.no_full_text_kind,
                "evidence_basis": dict(n.evidence_basis or {}),
            })
        for fl in getattr(outcome, "failed", ()):
            per_source.append({
                "source_ref": "source_result:"
                    + content_hash_of_search_result(fl.source),
                "resolution": "failed",
                "failure_class": fl.failure_class,
                "reason": fl.reason,
            })
        # IDR-046 D2 — the fetch-side provenance marker:
        # `{x.source.provider}` over `per_source` / `no_full_text` /
        # `failed`, falling back to the producing fetch task's
        # `spec.provider` when that union is empty (a fetch that ran
        # nothing) — read with the accessor this class already uses
        # (`_spec_search_task_id`). Sorted, de-duplicated.
        providers: set[str] = set()
        for group in (getattr(outcome, "per_source", ()) or (),
                      getattr(outcome, "no_full_text", ()) or (),
                      getattr(outcome, "failed", ()) or ()):
            for item in group:
                provider = getattr(getattr(item, "source", None),
                                   "provider", None)
                if isinstance(provider, str) and provider:
                    providers.add(provider)
        if not providers and task_id is not None:
            task_row = self._conn.execute(
                "SELECT spec_json FROM tasks WHERE task_id = ?", (task_id,),
            ).fetchone()
            if task_row is not None:
                task_spec = self._json_loads(task_row["spec_json"]) or {}
                fallback = task_spec.get("provider") if isinstance(
                    task_spec, dict) else None
                if isinstance(fallback, str) and fallback:
                    providers.add(fallback)
        return {
            "outcome_kind": "fetch",
            "aggregate": getattr(outcome, "aggregate", ""),
            "notes": list(getattr(outcome, "notes", ()) or ()),
            "per_source": per_source,
            "fetch_log": log_entries,
            "fetched_count": getattr(outcome, "fetched_count", 0),
            "no_full_text_count": getattr(outcome, "no_full_text_count", 0),
            "providers": sorted(providers),
        }
