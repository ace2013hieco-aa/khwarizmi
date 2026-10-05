"""Q-05 persistence slice — the failure-classification store (design D1–D8).

Design record: ``hermes_q05_persistence_slice_design.md`` (hostile gate
PASSED). Ratified upstream: IDR-036 (taxonomy + action map) and the pure
substrate ``hermes.research.failure_classification`` (41 golden fixtures).

The slice lands an ADMITTED ``FailureClassification`` as an ``artifacts`` row
(type ``failure_classification`` — the open ``artifact_type`` column needs no
migration) with §14 ``cites`` edges to the falsifying evidence and a
``derived_from`` edge to the producing falsification task. No new tables, no
new intents, no gateway change, no events, no scheduler, no state machine.

Non-negotiables (each is structural, not a rule):

- **The write path re-runs the substrate with REAL resolvers** (D1, EC-V6):
  a caller can never persist a REJECTED or forged classification — the
  verdict, identity, and citation resolution are re-derived inside this
  module from (``record``, ``draft``). An optional caller-supplied ``claimed``
  classification is compared, never trusted.
- **Task-bound** (D4): the producing task must exist, be same-project, and be
  RUNNING at commit time (checked INSIDE the transaction — the V6-P7-A2-02
  TOCTOU closure); every cited evidence artifact must be reachable from THAT
  task via ``derived_from`` edges (the ``_source_artifact_resolves`` two-hop
  precedent).
- **The ONLY writes are the artifact row + provenance edges.** This module
  never touches ``scope_briefs``, ``tasks``, ``research_programs``,
  hypotheses, events, budgets, or ladder state.
- **Advisory, never evidence** (D8): ``failure_classification`` is outside
  every citable type set; the evidence resolver refuses it as falsifying
  evidence.
- **The regime resolver is the closed registry** (D5; Step 4 / S-R2 wiring,
  IDR-044): the once-DEFERRED regime resolver now resolves declared regime
  citations against the closed regime registry (a registered versioned tag
  resolves; bare IDs and unregistered pairs do not) — the old
  substrate-admits/write-refuses asymmetry for ENVIRONMENT_MISMATCH is
  lifted, with the same registered-tag discipline live on both layers.
- **Immutability + versioning** (D6/D2): content-addressed rows
  (``content_hash`` UNIQUE). Identical content reuses (crash-retry
  idempotent); reclassification under a new ``classifier_version`` is a NEW
  row — historical truth is never mutated. R02: same hash with a different
  ``artifact_type`` is refused loudly.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from hermes.core import Clock, utc_now
from hermes.core.task_status import TaskStatus
from hermes.persistence.source_outcomes import (
    _source_artifact_resolves,
    source_artifact_retracted,
)
from hermes.research.failure_classification import (
    FAILURE_CLASS_SCHEMA_VERSION,
    FailureClass,
    FailureClassification,
    FailureClassificationDraft,
    FalsificationRecord,
    PermittedAction,
    classify_failure,
    parse_contributing_factors,
    permitted_actions_for,
    requires_human_confirmation_for,
)
from hermes.research.regimes import (
    RegimeResolutionError,
    parse_regime_ref,
    resolve_regime,
)

__all__ = [
    "FAILURE_CLASSIFICATION_ARTIFACT_TYPE",
    "FAILURE_CLASSIFICATION_REF_PREFIX",
    "FailureClassificationBindingError",
    "FailureClassificationError",
    "FailureClassificationIntegrityError",
    "FailureClassificationRepository",
    "classifications_digest",
]

# The artifact type (open column — no migration) and the D3 ref prefix the
# future REFUTED ladder record will carry as ``failure_classification_ref``.
FAILURE_CLASSIFICATION_ARTIFACT_TYPE = "failure_classification"
FAILURE_CLASSIFICATION_REF_PREFIX = "failure_classification:"

# Version of the advisory digest (D8 consumption) — the digest output is a
# deterministic function of (rows, digest_version); bumping the version never
# mutates recorded classifications.
DIGEST_VERSION = "2"

# Valid stored-action strings for digest integrity flags (F2): the digest
# never TRUSTS a stored permitted-action set, but a stored set that is not
# even well-formed (or disagrees with the ratified recomputation) is a
# corruption signal the Director must see — never a silent pass.
_VALID_ACTION_STRINGS = frozenset(a.value for a in PermittedAction)


class FailureClassificationError(Exception):
    """Base error for the Q-05 persistence slice (fail-closed write refusals)."""


class FailureClassificationBindingError(FailureClassificationError):
    """Task/evidence binding violation — the write is refused, nothing written."""


class FailureClassificationIntegrityError(FailureClassificationError):
    """Identity re-derivation or reuse-contract violation — nothing written."""


class FailureClassificationRepository:
    """The ONE failure-classification write boundary (design D1–D8).

    ``record`` re-runs the substrate with the real resolver bundle, re-checks
    the task binding and evidence ownership INSIDE the transaction, and
    commits the artifact row + §14 edges atomically. The read surface (D8)
    answers project/evidence queries and implements the D3 dereference
    contract the future REFUTED ladder record will enforce.
    """

    def __init__(self, conn: Any, clock: Clock | None = None) -> None:
        # Lazy: repositories.py imports this module's dependency graph at its
        # top; the cycle is broken by resolving repository names here, inside
        # methods (the source_outcomes pattern).
        from hermes.persistence.repositories import ArtifactRepository

        self._conn = conn
        self._clock = clock or utc_now
        self._artifacts = ArtifactRepository(conn, clock)


    # ── the transactional write boundary (THE only writer) ──

    def record(
        self,
        project_id: str,
        record: FalsificationRecord,
        draft: FailureClassificationDraft,
        *,
        producing_task_id: str,
        claimed: FailureClassification | None = None,
        reason: str = "",
    ) -> dict:
        """Persist an ADMITTED failure classification atomically (row + edges).

        Raises ``FailureClassificationError`` for any contract violation
        (project mismatch, undeclared/undeclarable regime citation, non-
        ADMITTED re-run, missing project),
        ``FailureClassificationIntegrityError`` when identity does not match
        the canonical re-derivation (forged ``claimed`` / R02 cross-type
        reuse), and ``FailureClassificationBindingError`` for a task/evidence
        binding violation. Returns a summary dict; the producing task's
        terminal transition is the CONTROLLER's (SD-03 — this method never
        touches task status).

        The caller supplies (``record``, ``draft``) — the write path re-runs
        the substrate with the real resolver bundle and never trusts an
        authored hash or an ADMITTED claim (D1, EC-V6).
        """
        if record.project_id != project_id:
            raise FailureClassificationError(
                f"classification write refused: the record's project "
                f"{record.project_id!r} does not match {project_id!r} — "
                f"classifications are project-scoped artifacts (D1)")

        # 1. Re-run the substrate with the REAL resolver bundle (D5/D1
        #    EC-V6): the verdict and identity are re-derived from (record,
        #    draft) — a caller's ADMITTED claim is never trusted.
        result = classify_failure(
            record,
            draft,
            evidence_resolver=self._evidence_resolver,
            constraint_resolver=self._constraint_resolver,
            mechanism_resolver=self._mechanism_resolver,
            regime_resolver=self._regime_resolver,
            scope_field_resolver=self._scope_field_resolver,
        )
        if not result.admitted or result.classification is None:
            reasons = [
                f"{e.code}@{e.field_path}: {e.explanation}"
                for e in result.errors
            ]
            raise FailureClassificationError(
                f"refusing to persist a non-ADMITTED classification — no "
                f"write path for unvalidated classifications (IDR-036): "
                f"{'; '.join(reasons)}")
        classification = result.classification

        # 2. Integrity boundary (EC-V6 / Model D): identity is derived, never
        #    authored. The re-run above IS the derivation; a caller-supplied
        #    `claimed` object must match it exactly or fail closed.
        if classification.schema_version != FAILURE_CLASS_SCHEMA_VERSION:
            raise FailureClassificationIntegrityError(
                f"classification schema_version "
                f"{classification.schema_version!r} is not the implemented "
                f"schema {FAILURE_CLASS_SCHEMA_VERSION!r} (IDR-036)")
        if classification.classification_id != (
                "fc_" + classification.content_hash[:24]):
            raise FailureClassificationIntegrityError(
                f"classification_id {classification.classification_id!r} "
                f"does not match the content identity 'fc_' + "
                f"{classification.content_hash[:24]!r} — identity is "
                f"derived, never authored (EC-V6)")
        if claimed is not None:
            for field, ours, theirs in (
                ("classification_id", classification.classification_id,
                 claimed.classification_id),
                ("content_hash", classification.content_hash,
                 claimed.content_hash),
                ("schema_version", classification.schema_version,
                 claimed.schema_version),
                ("project_id", classification.project_id,
                 claimed.project_id),
                ("failure_class", classification.failure_class.value,
                 claimed.failure_class.value),
            ):
                if ours != theirs:
                    raise FailureClassificationIntegrityError(
                        f"claimed {field} {theirs!r} does not match the "
                        f"re-derived {ours!r} — identity is derived, never "
                        f"authored (EC-V6); nothing written")

        # 3. Governance: the project must exist (V6-P7-F03) — resolved here,
        #    never trusted from the caller.
        proj = self._conn.execute(
            "SELECT 1 FROM projects WHERE project_id = ?", (project_id,),
        ).fetchone()
        if proj is None:
            raise FailureClassificationError(
                f"Project not found: {project_id!r} — failure "
                f"classifications are project-scoped artifacts (D1)")

        ts = self._clock()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # 4. Task binding — INSIDE the transaction (V6-P7-A2-02 TOCTOU
            #    closure): exists / same project / RUNNING at commit time.
            task = self._conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (producing_task_id,),
            ).fetchone()
            if task is None:
                raise FailureClassificationBindingError(
                    f"classification write refused: producing task "
                    f"{producing_task_id!r} does not exist (D4) — "
                    f"classifications are task output and require a "
                    f"producing falsification task")
            if task["project_id"] != project_id:
                raise FailureClassificationBindingError(
                    f"classification write refused: producing task "
                    f"{producing_task_id!r} belongs to project "
                    f"{task['project_id']!r}, not {project_id!r} (D4)")
            if task["status"] != TaskStatus.RUNNING.value:
                raise FailureClassificationBindingError(
                    f"classification write refused: producing task "
                    f"{producing_task_id!r} is {task['status']}, not RUNNING "
                    f"(D4) — output may only be accepted from a task "
                    f"currently executing")

            # 5. Evidence ownership (D4): every cited evidence artifact must
            #    be reachable from the producing task via derived_from edges
            #    (the _source_artifact_resolves two-hop precedent). A
            #    classification can never cite another classification (D8).
            for ref in classification.evidence_refs:
                self._verify_evidence_owned(
                    project_id, ref, producing_task_id)

            # 6. One-shot / idempotency (D6): get-by-hash-first (SD-04).
            #    Identical content reuses the existing row; a same-hash
            #    different-type row is refused loudly (R02). A new classifier
            #    version is a NEW content hash → a new row (versioning, NOT
            #    the divergent one-shot refusal of source outcomes).
            existing = self._artifacts.get_by_hash(classification.content_hash)
            if existing is not None:
                if existing["artifact_type"] != (
                        FAILURE_CLASSIFICATION_ARTIFACT_TYPE):
                    raise FailureClassificationIntegrityError(
                        f"reused artifact row type mismatch: existing "
                        f"{existing['artifact_type']!r} vs proposed "
                        f"{FAILURE_CLASSIFICATION_ARTIFACT_TYPE!r} for "
                        f"content_hash {existing['content_hash']!r} — same "
                        f"hash, different artifact type is refused, never "
                        f"reused (R02)")
                if existing["project_id"] != project_id:
                    raise FailureClassificationIntegrityError(
                        f"reused classification row "
                        f"{existing['artifact_id']!r} belongs to project "
                        f"{existing['project_id']!r}, not {project_id!r} — "
                        f"refused, never reused (R02)")
                decision = "REUSED"
                classification_id = existing["artifact_id"]
            else:
                self._artifacts.record(
                    artifact_id=classification.classification_id,
                    artifact_type=FAILURE_CLASSIFICATION_ARTIFACT_TYPE,
                    content_hash=classification.content_hash,
                    size_bytes=0,
                    storage_path="inline://failure_classification",
                    producer=f"falsification:{producing_task_id}",
                    project_id=project_id,
                    task_id=producing_task_id,
                    metadata=self._metadata(classification, record, reason),
                )
                decision = "NEW"
                classification_id = classification.classification_id

            # 7. §14 edges (D2), atomic with the row: cites per falsifying
            #    evidence artifact + derived_from to the producing task
            #    (INSERT OR IGNORE — reruns are idempotent).
            edges: list[tuple[str, str, str]] = []
            for ref in classification.evidence_refs:
                edges.append((classification_id, ref, "cites"))
            edges.append((classification_id, producing_task_id,
                          "derived_from"))
            for artifact_id, upstream_id, edge_type in edges:
                self._conn.execute(
                    "INSERT OR IGNORE INTO provenance_edges "
                    "(artifact_id, upstream_id, edge_type, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (artifact_id, upstream_id, edge_type, ts),
                )
            self._conn.execute("COMMIT")
        except FailureClassificationError:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        except Exception:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

        return {
            "project_id": project_id,
            "decision": decision,
            "classification_id": classification_id,
            "content_hash": classification.content_hash,
            "failure_class": classification.failure_class.value,
            "classifier_version": classification.classifier_version,
            "requires_human_confirmation":
                classification.requires_human_confirmation,
            "edges": sorted(edges),
        }

    def _verify_evidence_owned(
        self, project_id: str, ref: str, producing_task_id: str,
    ) -> None:
        """Every cited evidence ref must be reachable from the producing task
        (two-hop ``derived_from``, the ``_source_artifact_resolves``
        precedent) and must never be another failure classification (D8
        advisory boundary)."""
        if ":" not in ref:
            raise FailureClassificationBindingError(
                f"classification write refused: evidence ref {ref!r} is not "
                f"a typed artifact ref '<type>:<content_hash>' — falsifying "
                f"evidence must cite a real artifact (D4)")
        artifact_type, _, artifact_hash = ref.partition(":")
        if artifact_type == FAILURE_CLASSIFICATION_ARTIFACT_TYPE:
            raise FailureClassificationBindingError(
                f"classification write refused: evidence ref {ref!r} is "
                f"itself a failure classification — a classification can "
                f"never be falsifying evidence (D8 advisory boundary)")
        if not _source_artifact_resolves(
                self._conn, project_id, artifact_hash, artifact_type,
                upstream_task_id=producing_task_id):
            raise FailureClassificationBindingError(
                f"classification write refused: evidence ref {ref!r} is not "
                f"produced by task {producing_task_id!r} in project "
                f"{project_id!r} — the falsifying evidence must belong to "
                f"the producing task's outputs (D4, two-hop derived_from "
                f"reachability)")
        # N9: retraction state re-checked INSIDE the write transaction
        # (TOCTOU closure — a retraction committed after substrate
        # admission but before this commit still refuses).
        erow = self._conn.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE project_id = ? AND content_hash = ? "
            "AND artifact_type = ? ORDER BY created_at LIMIT 1",
            (project_id, artifact_hash, artifact_type)).fetchone()
        if erow is not None and source_artifact_retracted(
                self._conn, project_id, erow["artifact_id"]):
            raise FailureClassificationBindingError(
                f"classification write refused: evidence ref {ref!r} is "
                f"retracted in project {project_id!r} — retracted evidence "
                f"is inadmissible for new classifications (N9)")


    # ── the real resolver bundle (D5) ──

    def _evidence_resolver(self, project_id: str, ref: str) -> bool:
        """Project-scoped evidence resolution (D5): the ref must be a typed
        artifact ref (``<type>:<content_hash>``) whose row exists and is
        reachable from a task of the project via §14 ``derived_from`` edges
        (the ``_source_artifact_resolves`` two-hop pattern). A
        ``failure_classification`` ref is refused — advisory, never evidence
        (D8). A currently retracted source (N9 — S5 retraction state) does
        not resolve as admissible evidence."""
        if ":" not in ref:
            return False
        artifact_type, _, artifact_hash = ref.partition(":")
        if artifact_type == FAILURE_CLASSIFICATION_ARTIFACT_TYPE:
            return False
        if not _source_artifact_resolves(
                self._conn, project_id, artifact_hash, artifact_type):
            return False
        row = self._conn.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE project_id = ? AND content_hash = ? "
            "AND artifact_type = ? ORDER BY created_at LIMIT 1",
            (project_id, artifact_hash, artifact_type)).fetchone()
        if row is None:
            return False
        return not source_artifact_retracted(
            self._conn, project_id, row["artifact_id"])

    def _resolve_program(
        self, project_id: str, program_ref: str,
    ) -> dict | None:
        """Resolve a program ref (a ``program_id`` or a
        ``research_program:<content_hash>`` ref) to a project-scoped
        ``research_programs`` row, or None (the V6-FINAL-02 provenance
        pattern)."""
        program_id = program_ref
        if program_ref.startswith("research_program:"):
            program_id = program_ref[len("research_program:"):]
        row = self._conn.execute(
            "SELECT * FROM research_programs "
            "WHERE project_id = ? AND program_id = ?",
            (project_id, program_id),
        ).fetchone()
        if row is not None:
            return dict(row)
        row = self._conn.execute(
            "SELECT * FROM research_programs "
            "WHERE project_id = ? AND content_hash = ?",
            (project_id, program_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def _constraint_resolver(
        self, project_id: str, program_ref: str, ref: str,
    ) -> bool:
        """A declared constraint of the program: a hypothesis falsification
        condition (``hypothesis:<H>:falsification_condition``) or a
        methodology constraint index (``methodology_constraint:<i>``).
        Project-scoped: a foreign or missing program fails closed."""
        program = self._resolve_program(project_id, program_ref)
        if program is None:
            return False
        from hermes.persistence.repositories import _json_loads

        hypotheses = _json_loads(program["hypothesis_json"]) or []
        methodology = _json_loads(program["methodology_json"]) or []
        if (ref.startswith("hypothesis:")
                and ref.endswith(":falsification_condition")):
            h_ref = ref[len("hypothesis:"):-len(":falsification_condition")]
            return any(h.get("ref") == h_ref for h in hypotheses)
        if ref.startswith("methodology_constraint:"):
            idx = ref[len("methodology_constraint:"):]
            try:
                i = int(idx)
            except ValueError:
                return False
            return 0 <= i < len(methodology)
        return False

    def _mechanism_resolver(
        self, project_id: str, program_ref: str, ref: str,
    ) -> bool:
        """A program prediction/observable ref (``prediction:<P>``) — the
        IMPLEMENTATION_FAILURE citation target (the mechanism failed, not the
        claim)."""
        program = self._resolve_program(project_id, program_ref)
        if program is None:
            return False
        if not ref.startswith("prediction:"):
            return False
        from hermes.persistence.repositories import _json_loads

        predictions = _json_loads(program["prediction_json"]) or []
        p_ref = ref[len("prediction:"):]
        return any(p.get("ref") == p_ref for p in predictions)

    def _scope_field_resolver(
        self, project_id: str, brief_ref: str, field: str,
    ) -> bool:
        """The ScopeBrief field exists (OQ-1, best-effort): the frozen
        brief's ``scope_text_json`` must be structured (a dict) and contain
        the field as a top-level key. Non-dict / missing brief text fails
        closed — a FRAMING_ERROR classification is admissible now only when
        the brief's JSON is actually structured."""
        row = self._conn.execute(
            "SELECT scope_text_json FROM scope_briefs "
            "WHERE brief_id = ? AND project_id = ?",
            (brief_ref, project_id),
        ).fetchone()
        if row is None:
            return False
        from hermes.persistence.repositories import _json_loads

        parsed = _json_loads(row["scope_text_json"])
        if not isinstance(parsed, dict):
            return False
        return field in parsed

    def _regime_resolver(self, project_id: str, declared: str) -> bool:
        """Step 4 / S-R2 wiring (IDR-044): the DEFERRED regime resolver is
        now the closed regime registry. A declared regime citation resolves
        iff it is a registry-registered versioned tag (``VERSION:ID`` with a
        registered (version, ID) pair — a bare ID or an unregistered pair
        does not resolve). Registration is global; the surrounding
        classification stays project-scoped (the project_id parameter
        anchors the dereference call site, as for every other resolver)."""
        try:
            resolve_regime(parse_regime_ref(declared))
        except (RegimeResolutionError, TypeError):
            return False
        return True

    # ── metadata (D1) ──

    @staticmethod
    def _metadata(
        classification: FailureClassification,
        record: FalsificationRecord,
        reason: str,
    ) -> dict:
        """The structured classification metadata (D1 contract): class,
        contributing factors, evidence refs, class-specific citations,
        version identity, permitted actions, explanation, proposer — plus the
        record's full falsifying-evidence set for traceability (design §10)."""
        gap = None
        if classification.resource_gap is not None:
            gap = {
                "resource_kind": classification.resource_gap.resource_kind,
                "observed": classification.resource_gap.observed,
                "required": classification.resource_gap.required,
                "unit": classification.resource_gap.unit,
            }
        return {
            "schema_version": classification.schema_version,
            "classifier_version": classification.classifier_version,
            "classification_id": classification.classification_id,
            "hypothesis_ref": classification.hypothesis_ref,
            "program_ref": classification.program_ref,
            "falsifying_evidence_refs": list(record.falsifying_evidence_refs),
            "failure_class": classification.failure_class.value,
            "contributing_factors": [
                f.value for f in classification.contributing_factors],
            "evidence_refs": list(classification.evidence_refs),
            "constraint_ref": classification.constraint_ref,
            "failed_mechanism_ref": classification.failed_mechanism_ref,
            "regime_ref": classification.regime_ref,
            "resource_gap": gap,
            "scope_brief_ref": classification.scope_brief_ref,
            "scope_brief_field": classification.scope_brief_field,
            "explanation": classification.explanation,
            "proposed_by": classification.proposed_by,
            "condition_type": classification.condition_type.value,
            "permitted_actions": [
                a.value for a in classification.permitted_actions],
            "requires_human_confirmation":
                classification.requires_human_confirmation,
            "reason": reason,
        }


    # ── read / consumption surface (D8 — advisory only) ──

    def classifications_for_project(self, project_id: str) -> list[dict]:
        """All classifications recorded in the project, oldest first (D8)."""
        from hermes.persistence.repositories import _json_loads

        rows = self._conn.execute(
            "SELECT * FROM artifacts "
            "WHERE project_id = ? AND artifact_type = ? "
            "ORDER BY created_at",
            (project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # Fail-closed on corruption (never a crash): a corrupt
            # metadata_json degrades to an empty metadata dict, so the
            # row still REACHES the classifications_digest — which reports
            # it in ``errors`` as MALFORMED_METADATA (corruption-OBSERVABLE,
            # never silently dropped, never a tick crash via the cone
            # diagnostics or the digest read).
            try:
                d["metadata"] = _json_loads(d.pop("metadata_json")) or {}
            except ValueError:
                d["metadata"] = {}
            out.append(d)
        return out

    def classifications_for_evidence(
        self, project_id: str, evidence_ref: str,
    ) -> list[dict]:
        """The classifications in the project that cite a given evidence
        artifact (D8 — answers "what classifications exist for evidence E")."""
        from hermes.persistence.repositories import _json_loads

        rows = self._conn.execute(
            "SELECT a.* FROM artifacts a "
            "JOIN provenance_edges e ON e.artifact_id = a.artifact_id "
            "WHERE a.project_id = ? AND a.artifact_type = ? "
            "  AND e.edge_type = 'cites' AND e.upstream_id = ? "
            "ORDER BY a.created_at",
            (project_id, FAILURE_CLASSIFICATION_ARTIFACT_TYPE, evidence_ref),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # Fail-closed on corruption (never a crash): a corrupt
            # metadata_json degrades to an empty metadata dict, so the
            # row still REACHES the classifications_digest — which reports
            # it in ``errors`` as MALFORMED_METADATA (corruption-OBSERVABLE,
            # never silently dropped, never a tick crash via the cone
            # diagnostics or the digest read).
            try:
                d["metadata"] = _json_loads(d.pop("metadata_json")) or {}
            except ValueError:
                d["metadata"] = {}
            out.append(d)
        return out

    def dereference_failure_classification_ref(
        self, project_id: str, ref: str,
    ) -> bool:
        """The D3 dereference contract for the future REFUTED record's
        ``failure_classification_ref`` metadata field: the ref
        (``failure_classification:<content_hash>``) MUST resolve to an
        ``artifacts`` row of type ``failure_classification`` in the same
        project, or the record fails closed."""
        if not ref.startswith(FAILURE_CLASSIFICATION_REF_PREFIX):
            return False
        content_hash = ref[len(FAILURE_CLASSIFICATION_REF_PREFIX):]
        if not content_hash:
            return False
        row = self._conn.execute(
            "SELECT 1 FROM artifacts "
            "WHERE content_hash = ? AND artifact_type = ? AND project_id = ?",
            (content_hash, FAILURE_CLASSIFICATION_ARTIFACT_TYPE, project_id),
        ).fetchone()
        return row is not None


# ── D8 consumption: the advisory digest (pure, read-only, no authority) ──

def classifications_digest(rows: Sequence[Mapping[str, Any]]) -> dict:
    """Advisory digest of recorded classification rows for the reconcile/
    controller loop (D8 consumption) — corruption-OBSERVABLE.

    Pure: no SQL, no writes, no authority. Consumes the
    ``classifications_for_project`` row shape and produces a deterministic,
    versioned ``DigestResult``:

        digest_version      — schema of THIS result shape
        integrity_status    — "OK" | "FLAGGED" | "DEGRADED"
        count               — number of surfaced items
        items               — valid classifications (permitted_actions and
                              requires_human_confirmation RE-COMPUTED from the
                              ratified substrate — F2 rule, never trusted from
                              storage), each carrying the D3
                              ``failure_classification:<content_hash>`` ref the
                              future REFUTED record will dereference
        errors              — corrupt rows, NEVER surfaced as advisory
                              recommendations: the Director sees
                              "classification exists but is corrupt/unavailable",
                              never a silent "no classification"

    Integrity discipline (post-adversarial issue 1): persisted corruption is
    observable and never silently disappears. A row is DROPPED (reported in
    ``errors``) when its identity is forged, its metadata is malformed, its
    class is invalid, or required metadata is missing; a row whose STORED
    derived fields disagree with the ratified recomputation is SURFACED with
    the recomputed values AND flagged (``integrity_flags``). No new authority
    and no event — this is still the ActionEvaluation advisory posture
    (``evaluation.py``): the digest never executes or proposes anything beyond
    the taxonomy's action map.
    """
    items: list[dict] = []
    errors: list[dict] = []
    for row in sorted(rows, key=lambda r: str(r.get("artifact_id") or "")):
        artifact_id = str(row.get("artifact_id") or "")

        def _err(code: str, detail: str,
                 _artifact_id: str = artifact_id) -> dict:
            return {"artifact_id": _artifact_id, "code": code,
                    "detail": detail}

        # 1. Type gate: a non-classification row is never a recommendation.
        if str(row.get("artifact_type") or "") != (
                FAILURE_CLASSIFICATION_ARTIFACT_TYPE):
            errors.append(_err(
                "WRONG_ARTIFACT_TYPE",
                f"row {artifact_id!r} has artifact_type "
                f"{row.get('artifact_type')!r}, not "
                f"{FAILURE_CLASSIFICATION_ARTIFACT_TYPE!r}"))
            continue
        meta = row.get("metadata")
        if not isinstance(meta, dict):
            errors.append(_err(
                "MALFORMED_METADATA",
                f"row {artifact_id!r} metadata is not a JSON object"))
            continue
        # 2. Identity: classification_id must exist; a metadata claim that
        #    disagrees with the row's OWN artifact identity is a forgery.
        meta_id = meta.get("classification_id")
        row_identity = str(row.get("artifact_id") or "")
        if not meta_id and not row_identity:
            errors.append(_err(
                "MISSING_CLASSIFICATION_ID",
                f"row {artifact_id!r} has no classification identity"))
            continue
        classification_id = meta_id or row_identity
        if (isinstance(meta_id, str) and row_identity
                and meta_id != row_identity):
            errors.append(_err(
                "FORGED_IDENTITY",
                f"row {artifact_id!r} metadata claims classification_id "
                f"{meta_id!r} but the artifact identity is "
                f"{row_identity!r}"))
            continue
        # 3. The class must be a ratified member (invalid means forged/corrupt).
        raw_class = meta.get("failure_class")
        failure_class = None
        if isinstance(raw_class, str):
            try:
                failure_class = FailureClass(raw_class)
            except ValueError:
                failure_class = None
        if failure_class is None:
            errors.append(_err(
                "INVALID_FAILURE_CLASS",
                f"row {artifact_id!r} failure_class "
                f"{raw_class!r} is not a ratified taxonomy member"))
            continue
        # 4. Required metadata the write path always stores.
        if not meta.get("hypothesis_ref") or not meta.get("classifier_version"):
            errors.append(_err(
                "MISSING_REQUIRED_METADATA",
                f"row {artifact_id!r} is missing hypothesis_ref and/or "
                f"classifier_version — not written by the ratified path"))
            continue
        # 5. Stored-derived integrity flags (F2): the surfaced values are
        #    RECOMPUTED; a disagreeing STORED value is reported, never trusted.
        flags: list[str] = []
        stored_actions = meta.get("permitted_actions")
        recomputed_actions = sorted(
            a.value for a in permitted_actions_for(failure_class))
        if (not isinstance(stored_actions, list) or not stored_actions
                or not all(isinstance(a, str) and a in _VALID_ACTION_STRINGS
                           for a in stored_actions)):
            flags.append("MALFORMED_PERMITTED_ACTIONS")
        elif sorted(stored_actions) != recomputed_actions:
            flags.append("STORED_ACTIONS_MISMATCH")
        contributing = parse_contributing_factors(
            meta.get("contributing_factors"))
        stored_conf = meta.get("requires_human_confirmation")
        if (isinstance(stored_conf, bool)
                and stored_conf != requires_human_confirmation_for(
                    failure_class, contributing)):
            flags.append("STORED_CONFIRMATION_MISMATCH")
        # 6. Stored-fact integrity flags (independent-review finding F3/F4):
        #    a bare-string evidence_refs must not iterate per-character into
        #    garbage refs, a classification ref must never be "evidence" (D8),
        #    and a row without a content hash can never satisfy the D3
        #    dereference contract — all flagged, never silently surfaced.
        stored_evidence = meta.get("evidence_refs")
        if (not isinstance(stored_evidence, list)
                or not all(isinstance(e, str) and ":" in e
                           and not e.startswith(FAILURE_CLASSIFICATION_REF_PREFIX)
                           for e in stored_evidence)):
            flags.append("MALFORMED_EVIDENCE_REFS")
            surfaced_evidence: list[str] = []
        else:
            surfaced_evidence = sorted(str(e) for e in stored_evidence)
        content_hash = str(row.get("content_hash") or "")
        if not content_hash:
            flags.append("MISSING_CONTENT_HASH")
        items.append({
            "classification_id": str(classification_id),
            "failure_class_ref": (
                FAILURE_CLASSIFICATION_REF_PREFIX + content_hash
                if content_hash else None),
            "failure_class": failure_class.value,
            "classifier_version": meta.get("classifier_version"),
            "hypothesis_ref": str(meta.get("hypothesis_ref")),
            "permitted_actions": recomputed_actions,
            # Derived, not stored (F2 rule): both this and permitted_actions
            # are functions of the failure class alone and are RE-COMPUTED
            # from the ratified substrate — a tampered row's metadata can
            # never change what the digest reports.
            "requires_human_confirmation":
                requires_human_confirmation_for(failure_class, contributing),
            "evidence_refs": surfaced_evidence,
            "integrity_flags": sorted(flags),
        })
    if errors:
        integrity_status = "DEGRADED"
    elif any(item["integrity_flags"] for item in items):
        integrity_status = "FLAGGED"
    else:
        integrity_status = "OK"
    return {
        "digest_version": DIGEST_VERSION,
        "integrity_status": integrity_status,
        "count": len(items),
        "items": items,
        "errors": errors,
    }
