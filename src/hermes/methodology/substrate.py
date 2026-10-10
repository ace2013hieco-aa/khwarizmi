"""Methodology plane — the substrate ontology: chain nodes + provenance edges.

Scope of this module
--------------------
The repo already carries part of the research chain: ``research/programs.py``
holds the hypothesis and prediction artifacts plus the ladder targets,
``research/claims.py`` holds the claim/assumption artifacts,
``research/evidence_ladder.py`` + ``research/evidence_transitions.py`` hold the
evidence rungs and states, and ``research/contradictions.py`` holds the
contradiction pair identity. Those rows are **READ BY REF ONLY** here: this
module never redefines them, never re-derives their identity and never writes
them. What is *missing* — a question node, an experiment node, an observation
node, a critique node and a conclusion node, plus the provenance edges that
connect every step of the chain — is defined **alongside** them, in new value
objects that live entirely inside this plane.

The chain
---------
``QUESTION → HYPOTHESIS → PREDICTION → EXPERIMENT → OBSERVATION → EVIDENCE →
CLAIM → CRITIQUE → CONCLUSION``.

* The five **new** kinds (``NEW_NODE_KINDS``) are the nodes this round defines.
* The four **referenced** kinds (``REFERENCED_NODE_KINDS``) already exist in the
  repo. A substrate node of a referenced kind is a **citation**: it carries the
  artifact's own external ref (``hypothesis:…`` / ``prediction:…`` /
  ``evidence:…`` / ``claim:…``) and its identity is the identity of the
  *citation*, never of the cited artifact. A referenced-kind node without an
  external ref is refused — an existing-kind node cannot be minted here.

Provenance edges on every transition
------------------------------------
A node declares its predecessors (``content["predecessors"]``); the edge set is
the derived view of those declarations (:func:`provenance_edges`). Each edge
must connect kinds the transition map allows, must resolve to a recorded node
of this project, and must not close a cycle. A non-root node that declares no
predecessor is refused ``PROVENANCE``.

Identity — recomputed by rule, never authored
---------------------------------------------
A node's id is ``mnode_`` + a SHA-256 over
``(schema, kind, project_id, producing_task_id, content)``, recomputed at the
write boundary (:func:`write_node`). The id is not a field a caller can set: a
content mapping that carries ``node_id``/``id``/``content_hash`` is refused
``MALFORMED_PAYLOAD``. Edge ids (``medge_``) and contradiction-pair ids
(``mcon_``) are recomputed the same way.

Project scope and producing-task binding
----------------------------------------
Every node carries a ``project_id`` and a ``producing_task_id``, both
non-empty. A ref that resolves in another project is refused
``EVIDENCE_DOES_NOT_RESOLVE`` — citation fails closed across projects, the same
shape the repo's own ``EVIDENCE_DOES_NOT_RESOLVE`` refusal takes.

N9 — retracted sources stay inadmissible
----------------------------------------
A retracted ref is **cited, never admitted**. It may appear in
``content["cited_refs"]`` (a mention, recorded and flagged inadmissible) but an
appearance in ``content["admitted_refs"]`` (support-bearing) — **or as the
node's own ``content["external_ref"]``** — is refused ``RETRACTED_CITATION``:
the citation's own artifact is resolved under admission semantics, so a
retraction is never invisible on the position that carries the citation.
Nothing in this module ever promotes a retracted ref to support.

Reference resolution at the write boundary
------------------------------------------
Every artifact ref a node carries is resolved in its project before the node is
recorded: ``external_ref`` and every ``admitted_refs`` member under admission
semantics (existing, same project, not retracted), and every ``cited_refs``
member as a mention (existing, same project; retracted allowed). A ref that
resolves nowhere (a hallucination) and a ref that resolves in another project
both fail closed with ``EVIDENCE_DOES_NOT_RESOLVE``.

What this module does NOT claim
-------------------------------
Nothing here establishes the standing of any result, and nothing here is
authority: the nodes are derived value objects, the edges are derived views,
and refusal is returned as data (``{"rejected": True, "code", "detail"}``).
Element refusals belong to this plane's own closed vocabulary; they are not
gateway codes and never redefine a gateway code's frozen meaning.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ASSERTIONS",
    "AUTHORED_ID_KEYS",
    "CHAIN_KINDS",
    "CIRCULAR_REASONING",
    "CONTRADICTION_ID_PREFIX",
    "EDGE_ID_PREFIX",
    "EVIDENCE_DOES_NOT_RESOLVE",
    "MALFORMED_PAYLOAD",
    "NEW_NODE_KINDS",
    "NODE_CONTENT_KEYS",
    "NODE_ID_PREFIX",
    "OPPOSING_ASSERTIONS",
    "PREMATURE_CONCLUSION",
    "PROVENANCE",
    "RATIONALE",
    "REFERENCED_NODE_KINDS",
    "REF_NAMESPACES",
    "REQUIRED_PREDECESSOR",
    "RETRACTED_CITATION",
    "SUBSTRATE_REFUSAL_CODES",
    "SUBSTRATE_SCHEMA_VERSION",
    "UNSUPPORTED_CLAIM",
    "ChainReconstruction",
    "ChainStage",
    "NodeContradiction",
    "ProvenanceEdge",
    "SubstrateFormatError",
    "SubstrateNode",
    "SubstrateRefusal",
    "SubstrateStore",
    "canonical_json",
    "check_provenance_graph",
    "cited_but_inadmissible",
    "detect_contradictions",
    "digest_of",
    "edge_id_of",
    "is_admissible",
    "node_contradiction_id_of",
    "node_id_of",
    "provenance_edges",
    "reconstruct_chain",
    "resolve_endpoint",
    "resolve_ref",
    "sha256_hex",
    "write_node",
]

# ═══════════════════════ constants ═══════════════════════

SUBSTRATE_SCHEMA_VERSION = "1"

NODE_ID_PREFIX = "mnode_"
EDGE_ID_PREFIX = "medge_"
CONTRADICTION_ID_PREFIX = "mcon_"

#: The five kinds this round *defines* — the chain steps missing from the repo.
NEW_NODE_KINDS: frozenset[str] = frozenset({
    "QUESTION", "EXPERIMENT", "OBSERVATION", "CRITIQUE", "CONCLUSION",
})

#: The four kinds the repo already carries. Read by ref only — a node of one of
#: these kinds is a *citation* and carries the artifact's external ref.
REFERENCED_NODE_KINDS: frozenset[str] = frozenset({
    "HYPOTHESIS", "PREDICTION", "EVIDENCE", "CLAIM",
})

#: The namespace each referenced kind's external ref must carry. This is what
#: keeps a citation from re-identifying the cited row under a foreign family.
REF_NAMESPACES: Mapping[str, str] = {
    "HYPOTHESIS": "hypothesis:",
    "PREDICTION": "prediction:",
    "EVIDENCE": "evidence:",
    "CLAIM": "claim:",
}

#: The chain, in order. The transition map below is derived from it.
CHAIN_KINDS: tuple[str, ...] = (
    "QUESTION", "HYPOTHESIS", "PREDICTION", "EXPERIMENT", "OBSERVATION",
    "EVIDENCE", "CLAIM", "CRITIQUE", "CONCLUSION",
)

#: Allowed transition edges (predecessor kind → successor kind).
ALLOWED_TRANSITIONS: Mapping[str, tuple[str, ...]] = {
    "QUESTION": ("HYPOTHESIS",),
    "HYPOTHESIS": ("PREDICTION",),
    "PREDICTION": ("EXPERIMENT",),
    "EXPERIMENT": ("OBSERVATION",),
    "OBSERVATION": ("EVIDENCE",),
    "EVIDENCE": ("CLAIM",),
    "CLAIM": ("CRITIQUE",),
    "CRITIQUE": ("CONCLUSION",),
    "CONCLUSION": (),
}

#: The kind a node of kind ``K`` must descend from (``K`` is not ``QUESTION``).
REQUIRED_PREDECESSOR: Mapping[str, str] = {
    successor: predecessor
    for predecessor, successors in ALLOWED_TRANSITIONS.items()
    for successor in successors
}

#: Assertions a node may declare about a subject, and the pairs that conflict.
ASSERTIONS: frozenset[str] = frozenset({"SUPPORTS", "REFUTES", "NEUTRAL"})
OPPOSING_ASSERTIONS: frozenset[frozenset[str]] = frozenset({
    frozenset({"SUPPORTS", "REFUTES"}),
})

# ── refusal vocabulary ──
# The first four are the repo's own codes (reused, meanings unchanged): three
# gateway codes and the research-domain `EVIDENCE_DOES_NOT_RESOLVE`. The last
# four are this plane's own, closed and specified here.

MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"                 # repo: schema violation
RATIONALE = "RATIONALE"                                 # repo: required record absent
PROVENANCE = "PROVENANCE"                               # repo: a provenance ref does not dereference
EVIDENCE_DOES_NOT_RESOLVE = "EVIDENCE_DOES_NOT_RESOLVE"  # repo: a cited artifact does not resolve in-project

UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"                 # a CLAIM with no admitted evidence
PREMATURE_CONCLUSION = "PREMATURE_CONCLUSION"           # a CONCLUSION whose lineage is incomplete
CIRCULAR_REASONING = "CIRCULAR_REASONING"               # a provenance edge that closes a cycle
RETRACTED_CITATION = "RETRACTED_CITATION"               # N9: a retracted ref admitted as support

SUBSTRATE_REFUSAL_CODES: frozenset[str] = frozenset({
    MALFORMED_PAYLOAD, RATIONALE, PROVENANCE, EVIDENCE_DOES_NOT_RESOLVE,
    UNSUPPORTED_CLAIM, PREMATURE_CONCLUSION, CIRCULAR_REASONING,
    RETRACTED_CITATION,
})

#: Content keys that would make a node carry an authored identity. Refused.
AUTHORED_ID_KEYS: tuple[str, ...] = ("node_id", "id", "content_hash",
                                     "artifact_id", "entity_id")

#: The closed content key vocabulary a node may declare.
NODE_CONTENT_KEYS: frozenset[str] = frozenset({
    "question", "external_ref", "question_ref", "subject_ref",
    "assertion", "admitted_refs", "cited_refs", "predecessors",
    "summary", "label",
})


class SubstrateFormatError(ValueError):
    """A shape this module cannot read at all (direct-caller integrity error).

    Distinct from a :class:`SubstrateRefusal`, which is refusal-as-data: a
    caller that hands :func:`write_node` a value of the wrong *type* gets the
    data refusal; a caller that reads a store record directly and finds it
    unreadable gets this error.
    """


# ═══════════════════════ pure derivation ═══════════════════════


def _canonicalize(value: Any) -> Any:
    """A deterministic, JSON-representable form of ``value`` (never raises).

    Tuples become lists, sets become sorted lists, mapping keys become strings
    and non-finite/odd scalars become their ``repr`` — so that two equal
    structures always serialize identically and identity never depends on
    insertion order.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (
            float("inf"), float("-inf")) else repr(value)
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonicalize(item) for item in value),
                      key=lambda item: repr(item))
    return repr(value)


def canonical_json(value: Any) -> str:
    """Deterministic JSON for any value — sorted keys, no incidental spacing."""
    return json.dumps(_canonicalize(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def sha256_hex(text: str | bytes) -> str:
    """SHA-256 of ``text`` as lowercase hex."""
    body = text if isinstance(text, bytes) else text.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def digest_of(value: Any) -> str:
    """SHA-256 of the canonical JSON of ``value``, as lowercase hex."""
    return sha256_hex(canonical_json(value))


def _node_identity(kind: str, project_id: str, producing_task_id: str,
                   content: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SUBSTRATE_SCHEMA_VERSION,
        "kind": kind,
        "project_id": project_id,
        "producing_task_id": producing_task_id,
        "content": dict(content),
    }


def node_id_of(kind: str, project_id: str, producing_task_id: str,
               content: Mapping[str, Any]) -> str:
    """The derived identity of one node — recomputed at the write boundary.

    Depends on the kind, the project, the producing task and the content, and
    on nothing else: no clock, no ambient counter, no caller-supplied id. The
    same node content written twice derives the same id.
    """
    return NODE_ID_PREFIX + digest_of(
        _node_identity(kind, project_id, producing_task_id, content))[:32]


def edge_id_of(from_ref: str, to_ref: str, edge_type: str,
               project_id: str) -> str:
    """The derived identity of one provenance edge."""
    return EDGE_ID_PREFIX + digest_of({
        "schema_version": SUBSTRATE_SCHEMA_VERSION,
        "from_ref": from_ref,
        "to_ref": to_ref,
        "edge_type": edge_type,
        "project_id": project_id,
    })[:32]


def node_contradiction_id_of(first_ref: str, second_ref: str) -> str:
    """The derived identity of a contradiction pair — order-independent.

    The pair is canonicalised (sorted) so ``(a, b)`` and ``(b, a)`` derive one
    id, mirroring the repo's own pair rule.
    """
    pair = sorted((str(first_ref), str(second_ref)))
    return CONTRADICTION_ID_PREFIX + digest_of({
        "schema_version": SUBSTRATE_SCHEMA_VERSION,
        "pair": pair,
    })[:32]


# ═══════════════════════ refusal ═══════════════════════


@dataclass(frozen=True, slots=True)
class SubstrateRefusal:
    """Refusal-as-data: ``{"rejected": True, "code", "detail"}`` plus context.

    ``code`` is always a member of :data:`SUBSTRATE_REFUSAL_CODES`.
    """

    code: str
    detail: str
    kind: str = ""
    project_id: str = ""
    ref: str = ""

    def as_dict(self) -> dict[str, Any]:
        """The §2.4 refusal shape, so a plane refusal reads like a spine one."""
        return {"rejected": True, "code": self.code, "detail": self.detail}

    def to_mapping(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "kind": self.kind,
            "project_id": self.project_id,
            "ref": self.ref,
        }


def _refuse(code: str, detail: str, *, kind: str = "", project_id: str = "",
            ref: str = "") -> SubstrateRefusal:
    if code not in SUBSTRATE_REFUSAL_CODES:
        raise SubstrateFormatError(
            f"refusal code {code!r} is outside the substrate vocabulary")
    return SubstrateRefusal(code=code, detail=detail, kind=kind,
                            project_id=project_id, ref=ref)


# ═══════════════════════ node ═══════════════════════


@dataclass(frozen=True, slots=True)
class SubstrateNode:
    """One chain node: a new ontology node, or a citation of an existing one.

    ``content`` carries only keys from :data:`NODE_CONTENT_KEYS`; identity is
    derived from it by :func:`write_node` and is not a field here, so a node
    cannot carry a stale or forged id.
    """

    kind: str
    project_id: str
    producing_task_id: str
    content: Mapping[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def is_citation(self) -> bool:
        """True for a node of a referenced (already-existing) kind."""
        return self.kind in REFERENCED_NODE_KINDS

    def external_ref(self) -> str:
        return str(self.content.get("external_ref", ""))

    def predecessors(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.content.get("predecessors", ()))

    def admitted_refs(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.content.get("admitted_refs", ()))

    def cited_refs(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.content.get("cited_refs", ()))

    def derived_id(self) -> str:
        """Recompute this node's identity by rule (never authored)."""
        return node_id_of(self.kind, self.project_id, self.producing_task_id,
                          self.content)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "project_id": self.project_id,
            "producing_task_id": self.producing_task_id,
            "content": _canonicalize(dict(self.content)),
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class ProvenanceEdge:
    """One transition edge, derived from a node's predecessor declaration."""

    from_ref: str
    to_ref: str
    edge_type: str
    project_id: str

    def edge_id(self) -> str:
        return edge_id_of(self.from_ref, self.to_ref, self.edge_type,
                          self.project_id)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "from_ref": self.from_ref,
            "to_ref": self.to_ref,
            "edge_type": self.edge_type,
            "project_id": self.project_id,
            "edge_id": self.edge_id(),
        }


@dataclass(frozen=True, slots=True)
class ChainStage:
    """One step of a reconstructed chain: the kind, the id and the node."""

    kind: str
    node_id: str
    node: SubstrateNode

    def to_mapping(self) -> dict[str, Any]:
        return {"kind": self.kind, "node_id": self.node_id,
                "node": self.node.to_mapping()}


@dataclass(frozen=True, slots=True)
class ChainReconstruction:
    """A full QUESTION → … → CONCLUSION walk, recomputed from the store."""

    project_id: str
    question_id: str
    stages: tuple[ChainStage, ...]
    edges: tuple[ProvenanceEdge, ...]

    def conclusion_id(self) -> str:
        return self.stages[-1].node_id if self.stages else ""

    def kinds(self) -> tuple[str, ...]:
        return tuple(stage.kind for stage in self.stages)

    def complete(self) -> bool:
        """True iff every chain kind is present, in order, exactly once."""
        return self.kinds() == CHAIN_KINDS

    def digest(self) -> str:
        return digest_of({
            "schema_version": SUBSTRATE_SCHEMA_VERSION,
            "project_id": self.project_id,
            "question_id": self.question_id,
            "stages": [stage.to_mapping() for stage in self.stages],
        })

    def to_mapping(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "question_id": self.question_id,
            "kinds": list(self.kinds()),
            "complete": self.complete(),
            "stages": [stage.to_mapping() for stage in self.stages],
            "edges": [edge.to_mapping() for edge in self.edges],
        }


@dataclass(frozen=True, slots=True)
class NodeContradiction:
    """Two nodes of one project asserting opposing things about one subject."""

    contradiction_id: str
    subject_ref: str
    project_id: str
    party_a: str
    party_b: str
    assertion_a: str
    assertion_b: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "contradiction_id": self.contradiction_id,
            "subject_ref": self.subject_ref,
            "project_id": self.project_id,
            "party_a": self.party_a,
            "party_b": self.party_b,
            "assertion_a": self.assertion_a,
            "assertion_b": self.assertion_b,
        }


# ═══════════════════════ store ═══════════════════════


@dataclass(slots=True)
class SubstrateStore:
    """The plane's whole state: derived nodes, resolving refs, retractions.

    ``resolving_refs`` maps an external artifact ref to the project it resolves
    in — the citation registry the write boundary checks against.
    ``retracted_refs`` is the N9 projection: refs whose S5 retraction state is
    current, inadmissible as support.
    """

    nodes: dict[str, SubstrateNode] = field(default_factory=dict)
    resolving_refs: dict[str, str] = field(default_factory=dict)
    retracted_refs: frozenset[str] = frozenset()

    # ── reads ──

    def node(self, node_id: str) -> SubstrateNode | None:
        return self.nodes.get(str(node_id))

    def nodes_of_kind(self, kind: str, *, project_id: str = ""
                      ) -> tuple[tuple[str, SubstrateNode], ...]:
        return tuple((node_id, node) for node_id, node in sorted(
            self.nodes.items())
            if node.kind == kind
            and (not project_id or node.project_id == project_id))

    def edges(self) -> tuple[ProvenanceEdge, ...]:
        """Every provenance edge derived from the recorded nodes."""
        return provenance_edges(self)

    def admit_ref(self, ref: str, project_id: str) -> None:
        """Register an external ref as resolving in ``project_id`` (fixture act).

        The registry is **last-writer-wins and keyed by ref string alone — it
        records no content hash**. Re-admitting the same ref in another project
        therefore re-homes it: the previous owner's citations then fail closed
        (``EVIDENCE_DOES_NOT_RESOLVE`` — "resolves in project 'p2', not 'p1'").
        That failure is in the safe direction (no cross-project read becomes
        possible), but it *is* a silent rebind, not a duplicate; a content-hash
        keyed registry would make it explicit and reject the second owner.
        """
        self.resolving_refs[str(ref)] = str(project_id)

    def retract(self, ref: str) -> None:
        """Mark a ref retracted (the N9 projection, supplied by the caller)."""
        self.retracted_refs = self.retracted_refs | {str(ref)}

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": SUBSTRATE_SCHEMA_VERSION,
            "nodes": {node_id: node.to_mapping()
                      for node_id, node in sorted(self.nodes.items())},
            "resolving_refs": dict(sorted(self.resolving_refs.items())),
            "retracted_refs": sorted(self.retracted_refs),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SubstrateStore":
        unknown = sorted(set(data) - {"schema_version", "nodes",
                                      "resolving_refs", "retracted_refs"})
        if unknown:
            raise SubstrateFormatError(f"unknown SubstrateStore keys: {unknown}")
        store = cls()
        for node_id, body in dict(data.get("nodes") or {}).items():
            body = dict(body)
            node = SubstrateNode(
                kind=str(body["kind"]),
                project_id=str(body["project_id"]),
                producing_task_id=str(body["producing_task_id"]),
                content=dict(body.get("content") or {}),
                rationale=str(body.get("rationale", "")))
            derived = node.derived_id()
            if derived != str(node_id):
                raise SubstrateFormatError(
                    f"node key {node_id!r} disagrees with the id its content "
                    f"derives ({derived}) — a mapping key is not trusted; a "
                    f"forged record does not enter the store")
            store.nodes[str(node_id)] = node
        store.resolving_refs = {str(key): str(value) for key, value in
                                dict(data.get("resolving_refs") or {}).items()}
        store.retracted_refs = frozenset(
            str(ref) for ref in (data.get("retracted_refs") or ()))
        return store


# ═══════════════════════ resolution (project scope + N9) ═══════════════════════


def _namespace_of(kind: str) -> str:
    return REF_NAMESPACES.get(kind, "")


def resolve_ref(store: SubstrateStore, project_id: str, ref: str,
                *, expect_kind: str = "") -> str | SubstrateRefusal:
    """Resolve one external ref in ``project_id``, or refuse it as data.

    Refusal order (each a distinct, named reason):

    * a ref that is not a non-empty string, or carries no known artifact
      namespace, does not resolve — ``EVIDENCE_DOES_NOT_RESOLVE`` (this is the
      hallucinated-evidence branch: a ref that was never admitted anywhere);
    * a ref whose expected kind does not match the namespace it carries does
      not resolve — ``EVIDENCE_DOES_NOT_RESOLVE``;
    * a ref that resolves in **another** project fails closed —
      ``EVIDENCE_DOES_NOT_RESOLVE`` (cross-project citation);
    * a **retracted** ref (N9) is refused ``RETRACTED_CITATION``: it may be
      cited, never admitted as support.
    """
    if not isinstance(ref, str) or not ref:
        return _refuse(
            EVIDENCE_DOES_NOT_RESOLVE,
            f"ref {ref!r} is not a non-empty artifact ref — it resolves nowhere",
            project_id=project_id, ref=str(ref))
    prefixes = tuple(REF_NAMESPACES.values())
    if not ref.startswith(prefixes):
        return _refuse(
            EVIDENCE_DOES_NOT_RESOLVE,
            f"ref {ref!r} carries no known artifact namespace {prefixes} — it "
            f"resolves nowhere in this project",
            project_id=project_id, ref=ref)
    if expect_kind and not ref.startswith(_namespace_of(expect_kind)):
        return _refuse(
            EVIDENCE_DOES_NOT_RESOLVE,
            f"ref {ref!r} does not carry the {expect_kind} namespace "
            f"{_namespace_of(expect_kind)!r}",
            kind=expect_kind, project_id=project_id, ref=ref)
    owner = store.resolving_refs.get(ref)
    if owner is None:
        return _refuse(
            EVIDENCE_DOES_NOT_RESOLVE,
            f"ref {ref!r} does not resolve in project {project_id!r} — no "
            f"admitted artifact carries it",
            project_id=project_id, ref=ref)
    if owner != project_id:
        return _refuse(
            EVIDENCE_DOES_NOT_RESOLVE,
            f"ref {ref!r} resolves in project {owner!r}, not {project_id!r} — "
            f"citation is project-scoped and fails closed across projects",
            project_id=project_id, ref=ref)
    if ref in store.retracted_refs:
        return _refuse(
            RETRACTED_CITATION,
            f"ref {ref!r} is currently retracted (N9): a retracted source is "
            f"cited, never admitted as support",
            project_id=project_id, ref=ref)
    return ref


def is_admissible(store: SubstrateStore, project_id: str, ref: str) -> bool:
    """True iff ``ref`` may be admitted as support in ``project_id``."""
    return not isinstance(resolve_ref(store, project_id, ref),
                          SubstrateRefusal)


def _endpoint_exists(store: SubstrateStore, node_id: str) -> bool:
    return str(node_id) in store.nodes


def resolve_endpoint(store: SubstrateStore, project_id: str, endpoint: str,
                     ) -> str | SubstrateRefusal:
    """Resolve a graph endpoint — a derived node id, or an external ref.

    A derived id must be recorded and belong to ``project_id``; anything else
    is treated as an external ref and goes through :func:`resolve_ref` (so a
    retracted endpoint is refused ``RETRACTED_CITATION`` and a cross-project
    one ``EVIDENCE_DOES_NOT_RESOLVE``).
    """
    if not isinstance(endpoint, str) or not endpoint:
        return _refuse(PROVENANCE, "an endpoint must be a non-empty ref",
                       project_id=project_id, ref=str(endpoint))
    if endpoint.startswith(NODE_ID_PREFIX):
        node = store.nodes.get(endpoint)
        if node is None:
            return _refuse(
                PROVENANCE,
                f"edge endpoint {endpoint!r} is not recorded — provenance must "
                f"dereference to a recorded node",
                project_id=project_id, ref=endpoint)
        if node.project_id != project_id:
            return _refuse(
                EVIDENCE_DOES_NOT_RESOLVE,
                f"edge endpoint {endpoint!r} belongs to project "
                f"{node.project_id!r}, not {project_id!r}",
                project_id=project_id, ref=endpoint)
        return endpoint
    return resolve_ref(store, project_id, endpoint)


def provenance_edges(store: SubstrateStore) -> tuple[ProvenanceEdge, ...]:
    """Every edge the recorded nodes declare, in a deterministic order.

    An edge exists for each ``(predecessor, node)`` pair a node declares; the
    edge type is ``"<PRED_KIND>-><KIND>"``. Derived — never stored separately,
    so an edge can never disagree with the node it came from.
    """
    edges: list[ProvenanceEdge] = []
    for node_id, node in sorted(store.nodes.items()):
        for predecessor in node.predecessors():
            pred = store.nodes.get(predecessor)
            pred_kind = pred.kind if pred is not None else "UNKNOWN"
            edges.append(ProvenanceEdge(
                from_ref=predecessor, to_ref=node_id,
                edge_type=f"{pred_kind}->{node.kind}",
                project_id=node.project_id))
    return tuple(edges)


def check_provenance_graph(store: SubstrateStore) -> SubstrateRefusal | None:
    """Refuse a store whose provenance graph contains a cycle.

    Cycles are **not creatable through** :func:`write_node` — a node's identity
    is derived from content that cannot name the id it will receive, and a node
    is only ever written forwards. They are nevertheless **detectable**: a
    record read back from a foreign shape (``from_mapping``) can declare a
    back-edge, and a graph that can return to a node it already visited is
    circular reasoning by construction. This is the fail-closed floor — a store
    holding a cycle refuses every further write rather than extending a
    corrupted lineage.
    """
    adjacency: dict[str, tuple[str, ...]] = {}
    for node_id, node in store.nodes.items():
        adjacency[node_id] = tuple(
            predecessor for predecessor in node.predecessors()
            if predecessor in store.nodes)
    visiting: set[str] = set()
    done: set[str] = set()

    def _walk(current: str, trail: tuple[str, ...]) -> SubstrateRefusal | None:
        if current in done:
            return None
        if current in visiting:
            node = store.nodes.get(current)
            return _refuse(
                CIRCULAR_REASONING,
                f"the provenance graph returns to {current!r} — circular "
                f"reasoning: a chain step never descends from its own "
                f"descendant (walk {(*trail, current)})",
                kind=node.kind if node is not None else "",
                project_id=node.project_id if node is not None else "",
                ref=current)
        visiting.add(current)
        for predecessor in adjacency.get(current, ()):
            found = _walk(predecessor, (*trail, current))
            if found is not None:
                return found
        visiting.discard(current)
        done.add(current)
        return None

    for node_id in sorted(store.nodes):
        found = _walk(node_id, ())
        if found is not None:
            return found
    return None


def _ancestors(store: SubstrateStore, start: str) -> set[str]:
    seen: set[str] = set()
    stack = [str(start)]
    while stack:
        current = stack.pop()
        for predecessor in (store.nodes[current].predecessors()
                            if current in store.nodes else ()):
            if predecessor not in seen:
                seen.add(predecessor)
                stack.append(predecessor)
    return seen


# ═══════════════════════ the write boundary ═══════════════════════


def _shape_refusal(node: SubstrateNode) -> SubstrateRefusal | None:
    """Every shape problem in a node, as the first refusal (never raises)."""
    if not isinstance(node, SubstrateNode):
        return _refuse(MALFORMED_PAYLOAD,
                       f"a node must be a SubstrateNode, not "
                       f"{type(node).__name__}")
    if node.kind not in CHAIN_KINDS:
        return _refuse(MALFORMED_PAYLOAD,
                       f"kind {node.kind!r} is not a chain kind {CHAIN_KINDS}",
                       kind=node.kind, project_id=node.project_id)
    if not isinstance(node.project_id, str) or not node.project_id.strip():
        return _refuse(MALFORMED_PAYLOAD,
                       "a node needs a non-empty project_id (project isolation)",
                       kind=node.kind)
    if (not isinstance(node.producing_task_id, str)
            or not node.producing_task_id.strip()):
        return _refuse(MALFORMED_PAYLOAD,
                       "a node needs a non-empty producing_task_id (every node "
                       "is bound to the task that produced it)",
                       kind=node.kind, project_id=node.project_id)
    if not isinstance(node.content, Mapping):
        return _refuse(MALFORMED_PAYLOAD,
                       f"content must be a mapping, not "
                       f"{type(node.content).__name__}",
                       kind=node.kind, project_id=node.project_id)
    authored = sorted(key for key in AUTHORED_ID_KEYS if key in node.content)
    if authored:
        return _refuse(
            MALFORMED_PAYLOAD,
            f"content carries an authored identity {authored} — identity is "
            f"recomputed at the write boundary and never supplied by a caller",
            kind=node.kind, project_id=node.project_id)
    unknown = sorted(set(node.content) - NODE_CONTENT_KEYS)
    if unknown:
        return _refuse(MALFORMED_PAYLOAD,
                       f"unknown content keys: {unknown}",
                       kind=node.kind, project_id=node.project_id)
    if not isinstance(node.rationale, str):
        return _refuse(RATIONALE,
                       f"rationale must be a string, not "
                       f"{type(node.rationale).__name__}",
                       kind=node.kind, project_id=node.project_id)
    return None


def _kind_refusal(node: SubstrateNode) -> SubstrateRefusal | None:
    """The kind-specific content requirements."""
    content = node.content
    if node.kind in NEW_NODE_KINDS:
        # R6-FIX2 (E3): a locally-defined kind (QUESTION, EXPERIMENT,
        # OBSERVATION, CRITIQUE, CONCLUSION — exactly the kinds with no
        # REF_NAMESPACES entry) carries its content **inline**; ``external_ref``
        # is the citation key for *existing-kind* artifacts only. A local kind
        # with a non-empty ``external_ref`` is refused ``MALFORMED_PAYLOAD`` —
        # the byte value points at an existing artifact, but the position is a
        # chain step this round defines, so no existing artifact is being cited.
        # This check fires *before* the QUESTION early return below, so the
        # shape rule applies to **every** local kind including QUESTION.
        ref = content.get("external_ref")
        if isinstance(ref, str) and ref:
            return _refuse(
                MALFORMED_PAYLOAD,
                f"a {node.kind} node carries a non-empty external_ref "
                f"{ref!r} — locally-defined nodes carry their content inline; "
                f"external_ref is for cited existing-kind artifacts only",
                kind=node.kind, project_id=node.project_id, ref=ref)
    if node.kind == "QUESTION":
        question = content.get("question")
        if not isinstance(question, str) or not question.strip():
            return _refuse(MALFORMED_PAYLOAD,
                           "a QUESTION node needs a non-empty 'question'",
                           kind=node.kind, project_id=node.project_id)
        return None
    if node.kind in REFERENCED_NODE_KINDS:
        ref = content.get("external_ref")
        if not isinstance(ref, str) or not ref:
            return _refuse(
                MALFORMED_PAYLOAD,
                f"a {node.kind} node cites an existing artifact: it needs a "
                f"non-empty 'external_ref' — an existing-kind node is never "
                f"minted here, only cited",
                kind=node.kind, project_id=node.project_id)
        namespace = _namespace_of(node.kind)
        if not ref.startswith(namespace):
            return _refuse(
                MALFORMED_PAYLOAD,
                f"external_ref {ref!r} does not carry the {node.kind} "
                f"namespace {namespace!r}",
                kind=node.kind, project_id=node.project_id, ref=ref)
        return None
    if node.kind == "CRITIQUE":
        subject = content.get("subject_ref")
        if not isinstance(subject, str) or not subject:
            return _refuse(MALFORMED_PAYLOAD,
                           "a CRITIQUE node needs a non-empty 'subject_ref'",
                           kind=node.kind, project_id=node.project_id)
    if node.kind == "CONCLUSION":
        question_ref = content.get("question_ref")
        if not isinstance(question_ref, str) or not question_ref:
            return _refuse(
                MALFORMED_PAYLOAD,
                "a CONCLUSION node needs a non-empty 'question_ref' naming the "
                "question its lineage answers",
                kind=node.kind, project_id=node.project_id)
    assertion = content.get("assertion")
    if assertion is not None and assertion not in ASSERTIONS:
        return _refuse(MALFORMED_PAYLOAD,
                       f"assertion {assertion!r} is not one of {sorted(ASSERTIONS)}",
                       kind=node.kind, project_id=node.project_id)
    return None


def _refs_refusal(store: SubstrateStore,
                  node: SubstrateNode) -> SubstrateRefusal | None:
    """Every artifact ref a node carries, resolved, scoped and N9-checked.

    Three positions are checked, each under the semantics its role carries:

    * the node's own ``external_ref`` — **kind-aware**:

        * a **referenced** kind (HYPOTHESIS, PREDICTION, EVIDENCE, CLAIM) is a
          *citation* of an existing-kind artifact. The shape gate already made
          an empty ``external_ref`` impossible, so this position **always
          resolves** under admission semantics — a hallucinated citation, a
          cross-project citation, and a retracted citation (``RETRACTED_CITATION``
          — N9) all fail closed here, and a node may not admit its own
          ``external_ref`` as support (``CIRCULAR_REASONING``);
        * a **locally-defined** kind (QUESTION, EXPERIMENT, OBSERVATION,
          CRITIQUE, CONCLUSION) carries its content inline. The shape gate
          already refused any non-empty ``external_ref`` with ``MALFORMED_PAYLOAD``;
          this position is **defense in depth** — if the shape gate is ever
          bypassed, the same refusal is returned here, not a silent resolve.

    * ``admitted_refs`` (support-bearing) resolve under the same admission
      semantics; a node may not admit its own ``external_ref`` — an artifact
      does not support itself (``CIRCULAR_REASONING``);
    * ``cited_refs`` (a mention) must resolve in this project, but a retracted
      one is allowed here and only here.
    """
    own_ref = node.content.get("external_ref")
    if node.kind in REFERENCED_NODE_KINDS:
        # Referenced-kind side: the shape gate forbids an empty external_ref;
        # resolve unconditionally under admission semantics.
        assert own_ref, (
            f"a {node.kind} node reached _refs_refusal with an empty "
            f"external_ref — the shape gate (kind_refusal) should have caught "
            f"this; the surface check has not")
        if own_ref in node.admitted_refs():
            return _refuse(
                CIRCULAR_REASONING,
                f"a {node.kind} node admits its own external_ref {own_ref!r} as "
                f"support — an artifact supports its chain position, never "
                f"itself",
                kind=node.kind, project_id=node.project_id, ref=own_ref)
        outcome = resolve_ref(store, node.project_id, own_ref,
                              expect_kind=node.kind)
        if isinstance(outcome, SubstrateRefusal):
            return replace(outcome, kind=node.kind)
    elif node.kind in NEW_NODE_KINDS:
        # Locally-defined side: the shape gate forbids a non-empty external_ref;
        # assert-empty, with the same refusal as a belt-and-braces. The shape
        # gate is the primary enforcement; this disposition is the second.
        if isinstance(own_ref, str) and own_ref:
            return _refuse(
                MALFORMED_PAYLOAD,
                f"a {node.kind} node carries a non-empty external_ref "
                f"{own_ref!r} — locally-defined nodes carry their content "
                f"inline; external_ref is for cited existing-kind artifacts "
                f"only",
                kind=node.kind, project_id=node.project_id, ref=own_ref)
    for ref in node.admitted_refs():
        outcome = resolve_ref(store, node.project_id, ref)
        if isinstance(outcome, SubstrateRefusal):
            return replace(outcome, kind=node.kind)
    for ref in node.cited_refs():
        # A citation is a mention, not support: it must resolve (the artifact
        # exists), but a *retracted* one is allowed here and only here.
        if not isinstance(ref, str) or not ref.startswith(
                tuple(REF_NAMESPACES.values())):
            return _refuse(EVIDENCE_DOES_NOT_RESOLVE,
                           f"cited ref {ref!r} carries no known artifact "
                           f"namespace — it resolves nowhere",
                           kind=node.kind, project_id=node.project_id,
                           ref=str(ref))
        owner = store.resolving_refs.get(ref)
        if owner is None or owner != node.project_id:
            return _refuse(
                EVIDENCE_DOES_NOT_RESOLVE,
                f"cited ref {ref!r} does not resolve in project "
                f"{node.project_id!r}",
                kind=node.kind, project_id=node.project_id, ref=ref)
    return None


def _subject_refusal(store: SubstrateStore,
                     node: SubstrateNode) -> SubstrateRefusal | None:
    """A CRITIQUE's ``subject_ref`` must dereference to a recorded node.

    A critique is *about* something: the subject it names is a provenance-shaped
    pointer into this project's chain, resolved through
    :func:`resolve_endpoint`. A ghost subject (one that resolves nowhere) or a
    foreign-project subject is refused at the write boundary rather than left
    for the advisory detector to key a contradiction on a subject that does not
    exist.
    """
    if node.kind != "CRITIQUE":
        return None
    subject = node.content.get("subject_ref")
    if not isinstance(subject, str) or not subject:
        return None
    outcome = resolve_endpoint(store, node.project_id, subject)
    if isinstance(outcome, SubstrateRefusal):
        return replace(outcome, kind=node.kind)
    return None


def _provenance_refusal(store: SubstrateStore,
                        node: SubstrateNode) -> SubstrateRefusal | None:
    """Predecessor presence, allowed-transition and project-scope checks."""
    predecessors = node.predecessors()
    if node.kind == "QUESTION":
        if predecessors:
            return _refuse(MALFORMED_PAYLOAD,
                           "a QUESTION is the chain root: it has no predecessor",
                           kind=node.kind, project_id=node.project_id)
        return None
    if not predecessors:
        return _refuse(
            PROVENANCE,
            f"a {node.kind} node declares no predecessor — every transition "
            f"carries a provenance edge, so {node.kind} must descend from "
            f"{REQUIRED_PREDECESSOR.get(node.kind, '?')}",
            kind=node.kind, project_id=node.project_id)
    required = REQUIRED_PREDECESSOR.get(node.kind, "")
    for predecessor in predecessors:
        if not _endpoint_exists(store, predecessor):
            return _refuse(
                PROVENANCE,
                f"predecessor {predecessor!r} is not recorded — provenance "
                f"must dereference to a recorded node",
                kind=node.kind, project_id=node.project_id, ref=predecessor)
        pred_node = store.nodes[predecessor]
        if pred_node.project_id != node.project_id:
            return _refuse(
                EVIDENCE_DOES_NOT_RESOLVE,
                f"predecessor {predecessor!r} belongs to project "
                f"{pred_node.project_id!r}, not {node.project_id!r}",
                kind=node.kind, project_id=node.project_id, ref=predecessor)
        if pred_node.kind != required:
            return _refuse(
                PROVENANCE,
                f"a {node.kind} transition requires a {required} predecessor, "
                f"but {predecessor!r} is a {pred_node.kind} — the transition is "
                f"not in the chain map",
                kind=node.kind, project_id=node.project_id, ref=predecessor)
    return None


def _support_refusal(store: SubstrateStore, node: SubstrateNode,
                     node_id: str) -> SubstrateRefusal | None:
    """Unsupported-claim and premature-conclusion checks.

    A chain *position* is not support: descending from an EVIDENCE node places
    the claim in the chain, but the claim is supported only by an **admitted**
    evidence ref. A claim with a position and no admitted evidence is exactly
    the unsupported claim this refuses.
    """
    if node.kind == "CLAIM":
        admitted = tuple(ref for ref in node.admitted_refs()
                         if ref.startswith("evidence:"))
        if not admitted:
            return _refuse(
                UNSUPPORTED_CLAIM,
                "a CLAIM carries no admitted evidence ref — descending from an "
                "EVIDENCE node is a chain position, not support; a claim "
                "without admitted evidence is refused",
                kind=node.kind, project_id=node.project_id)
    if node.kind == "CONCLUSION":
        question_ref = str(node.content.get("question_ref", ""))
        ancestry = _ancestors(store, node_id) | set(node.predecessors())
        present = {store.nodes[item].kind for item in ancestry
                   if item in store.nodes}
        missing = [kind for kind in CHAIN_KINDS[:-1] if kind not in present]
        if missing:
            return _refuse(
                PREMATURE_CONCLUSION,
                f"the lineage reaching this CONCLUSION is missing {missing} — a "
                f"conclusion is drawn from a complete chain, not a partial one",
                kind=node.kind, project_id=node.project_id, ref=question_ref)
        if question_ref not in ancestry:
            return _refuse(
                PREMATURE_CONCLUSION,
                f"the CONCLUSION binds question {question_ref!r}, which is not "
                f"in its own lineage — the conclusion answers a question it did "
                f"not descend from",
                kind=node.kind, project_id=node.project_id, ref=question_ref)
    return None


def write_node(store: SubstrateStore, node: SubstrateNode,
               ) -> str | SubstrateRefusal:
    """Record one node — the plane's single write boundary.

    Returns the derived ``mnode_`` id on success, or refusal-as-data. The
    identity is recomputed here from the node's own fields; a node whose
    recomputed id collides with a *different* recorded node is refused
    ``MALFORMED_PAYLOAD`` (a collision is an integrity incident, never a silent
    overwrite — records are append-only in this plane: an existing id is
    returned unchanged, never rewritten).
    """
    for check in (_shape_refusal(node), _kind_refusal(node)):
        if check is not None:
            return check
    # The fail-closed floor: a store that already holds a cycle refuses every
    # further write rather than extending a corrupted lineage (see
    # `check_provenance_graph`).
    graph = check_provenance_graph(store)
    if graph is not None:
        return graph
    node_id = node.derived_id()
    existing = store.nodes.get(node_id)
    if existing is not None:
        if existing != node:
            return _refuse(
                MALFORMED_PAYLOAD,
                f"node {node_id} is already recorded with different content — "
                f"identity collision; this plane never rewrites a record",
                kind=node.kind, project_id=node.project_id)
        return node_id
    refs = _refs_refusal(store, node)
    if refs is not None:
        return refs
    provenance = _provenance_refusal(store, node)
    if provenance is not None:
        return provenance
    subject = _subject_refusal(store, node)
    if subject is not None:
        return subject
    # Stage the node so the lineage checks can see it, then check support.
    staged = SubstrateStore(nodes=dict(store.nodes),
                            resolving_refs=dict(store.resolving_refs),
                            retracted_refs=store.retracted_refs)
    staged.nodes[node_id] = node
    support = _support_refusal(staged, node, node_id)
    if support is not None:
        return support
    store.nodes[node_id] = node
    return node_id


# ═══════════════════════ detection ═══════════════════════


def detect_contradictions(store: SubstrateStore, *,
                          project_id: str = "") -> tuple[NodeContradiction, ...]:
    """Advisory detection of opposing assertions about one subject.

    Purely derived (a read, never a write, never a mutation of any kind): two
    recorded nodes of the same project, the same kind and the same
    ``subject_ref`` whose ``assertion`` values form an opposing pair are
    reported with a by-rule pair id. Order-independent, deterministic.
    """
    buckets: dict[tuple[str, str, str], list[tuple[str, SubstrateNode]]] = {}
    for node_id, node in sorted(store.nodes.items()):
        if project_id and node.project_id != project_id:
            continue
        subject = node.content.get("subject_ref")
        assertion = node.content.get("assertion")
        if not isinstance(subject, str) or not subject:
            continue
        if not isinstance(assertion, str) or assertion not in ASSERTIONS:
            continue
        key = (node.project_id, node.kind, subject)
        buckets.setdefault(key, []).append((node_id, node))
    found: list[NodeContradiction] = []
    for (owner, kind, subject), entries in sorted(buckets.items()):
        for index, (first_id, first) in enumerate(entries):
            for second_id, second in entries[index + 1:]:
                pair = frozenset({str(first.content["assertion"]),
                                  str(second.content["assertion"])})
                if pair not in OPPOSING_ASSERTIONS:
                    continue
                ordered = sorted((first_id, second_id))
                by_id = {first_id: first, second_id: second}
                found.append(NodeContradiction(
                    contradiction_id=node_contradiction_id_of(ordered[0], ordered[1]),
                    subject_ref=subject,
                    project_id=owner,
                    party_a=ordered[0],
                    party_b=ordered[1],
                    assertion_a=str(by_id[ordered[0]].content["assertion"]),
                    assertion_b=str(by_id[ordered[1]].content["assertion"])))
    return tuple(found)


# ═══════════════════════ reconstruction ═══════════════════════


def reconstruct_chain(store: SubstrateStore, question_id: str,
                      ) -> ChainReconstruction | SubstrateRefusal:
    """Walk QUESTION → … → CONCLUSION from the recorded state.

    Deterministic and total: a missing stage refuses ``PROVENANCE``, an
    ambiguous stage (two successors of one kind under one predecessor) refuses
    ``MALFORMED_PAYLOAD``, and a record whose recomputed id disagrees with the
    key it is stored under refuses ``MALFORMED_PAYLOAD`` — **including the root
    QUESTION**, which is re-derived at this boundary exactly like every stage
    the walk reaches (a torn or forged record never reconstructs).
    """
    question = store.nodes.get(str(question_id))
    if question is None or question.kind != "QUESTION":
        return _refuse(PROVENANCE,
                       f"question {question_id!r} is not a recorded QUESTION "
                       f"node", ref=str(question_id))
    if question.derived_id() != str(question_id):
        return _refuse(
            MALFORMED_PAYLOAD,
            f"the root QUESTION {question_id} disagrees with the id its content "
            f"derives ({question.derived_id()}) — a record that cannot establish "
            f"its own identity does not reconstruct",
            kind="QUESTION", project_id=question.project_id,
            ref=str(question_id))
    project_id = question.project_id
    stages = [ChainStage(kind="QUESTION", node_id=str(question_id),
                         node=question)]
    edges: list[ProvenanceEdge] = []
    current_id = str(question_id)
    current_kind = "QUESTION"
    for kind in CHAIN_KINDS[1:]:
        successors = [node_id for node_id, node in sorted(store.nodes.items())
                      if node.kind == kind
                      and node.project_id == project_id
                      and current_id in node.predecessors()]
        if not successors:
            return _refuse(
                PROVENANCE,
                f"the chain from question {question_id!r} has no {kind} "
                f"successor of {current_kind} {current_id!r} — the walk stops at "
                f"{current_kind}",
                kind=kind, project_id=project_id)
        if len(successors) > 1:
            return _refuse(
                MALFORMED_PAYLOAD,
                f"{current_kind} {current_id!r} has {len(successors)} {kind} "
                f"successors {successors} — the walk is not deterministic",
                kind=kind, project_id=project_id)
        node_id = successors[0]
        node = store.nodes[node_id]
        if node.derived_id() != node_id:
            return _refuse(
                MALFORMED_PAYLOAD,
                f"node {node_id} disagrees with the id its content derives "
                f"({node.derived_id()}) — a record that cannot establish its own "
                f"identity does not reconstruct",
                kind=kind, project_id=project_id, ref=node_id)
        edges.append(ProvenanceEdge(from_ref=current_id, to_ref=node_id,
                                    edge_type=f"{current_kind}->{kind}",
                                    project_id=project_id))
        stages.append(ChainStage(kind=kind, node_id=node_id, node=node))
        current_id, current_kind = node_id, kind
    return ChainReconstruction(project_id=project_id,
                               question_id=str(question_id),
                               stages=tuple(stages), edges=tuple(edges))


def cited_but_inadmissible(store: SubstrateStore,
                           node: SubstrateNode) -> tuple[str, ...]:
    """The refs a node *cites* that are currently retracted (cite, never admit)."""
    return tuple(ref for ref in node.cited_refs()
                 if ref in store.retracted_refs)
