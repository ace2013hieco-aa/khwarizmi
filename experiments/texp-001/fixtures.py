"""TEXP-001 S5 — acceptance fixtures F1–F7 + pilot gate (Case B).

Each fixture is a runnable function with spec §5 pass criteria; the pilot
runs them at scale, while `test_generator.py` pins their mechanics at
micro-scale with fixed seeds (deterministic code ⇒ reproducible).
K-S2a/K-S2b are WIRED here (not comments): hub fractions are computed
per arm inside F2's verdict dict, and `pilot_gate` takes the
informativeness bar as a REQUIRED parameter (no default — declared at
B-calibration). F7 implements the K1 amendment (same-budget
degraded-policy cripple), not spec v1.2's budget-cut text.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from arms import flat_energy, make_a0, make_a1, make_a2, run_arm
from energy import SearchContext, reference_energy
from generator import (BenchmarkInstance, GroundTruth, edge_seq, generate,
                       recall_at_k)
from kernel import BudgetCounter, initial_path, make_rng_stream
from validator import validate_path

PathT = tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class FixtureVerdict:
    """One fixture outcome. ``passed`` applies the spec pass criterion;
    ``details`` carries the measured numbers (hub fractions, recalls)."""

    fixture_id: str
    passed: bool
    details: str


def canonical(instance: BenchmarkInstance) -> str:
    """Canonical serialization for byte-identity checks (F1)."""
    g, t = instance.graph, instance.truth
    return json.dumps({
        "nodes": list(g.nodes),
        "edges": [list(e) for e in g.edges],
        "planted": [[list(e) for e in p] for p in t.planted],
        "hubs": list(t.hubs),
        "violating": [list(e) for e in t.violating_edges],
        "nearmiss": [[list(e) for e in p] for p in t.nearmiss],
        "strata": [g.strata.n_nodes, g.strata.n_communities,
                   g.strata.bridge_len, g.strata.noise_rate],
        "seed": g.seed,
    }, sort_keys=True, separators=(",", ":"))


def collect_k_paths(make_arm, arm_kwargs: dict, graph, seeds, k: int,
                    budget: int, steps: int, l_max: int = 2,
                    ) -> list[PathT]:
    """Harness-level K-path collection (fixture composition, not arm
    semantics): per seed, run the arm's segments with a logging energy
    wrapper (identical values — behavior-preserving observation) and
    gather every distinct VALIDATOR-ADMISSIBLE evaluated path in
    first-seen order (energy is evaluated only post-admissibility in
    `run_chain`, so everything logged passed the validator). Cap K.
    Deterministic given inputs. NOTE: best-per-segment collection was
    tried first and is structurally blind under monotone energy (bests
    are always shortest); evaluated-set collection is the honest
    harness composition. The production K-output discipline remains a
    future arms refinement."""
    from dataclasses import replace
    from generator import as_adjacency
    adj = as_adjacency(graph)
    ctx = SearchContext(graph_id=f"fx-{graph.seed}")
    base = flat_energy if arm_kwargs.get("_flat") else reference_energy
    kw = {k2: v for k2, v in arm_kwargs.items() if not k2.startswith("_")}
    seen: list[PathT] = []
    for seed in seeds:
        logged: list[PathT] = []

        def logging_energy(path, context, _log=logged):
            _log.append(edge_seq(path))
            return base(path, context)

        rng = make_rng_stream(f"fx-{graph.seed}", seed, stream="fixture")
        init = initial_path(rng, adj, validate_path, l_max)
        if arm_kwargs.get("_flat"):
            spec = make_arm(validator=validate_path, budget=budget,
                            steps=steps, l_max=l_max, **kw)
        else:
            spec = make_arm(validator=validate_path, budget=budget,
                            steps=steps, l_max=l_max, energy=base, **kw)
        spec = replace(spec, energy_fn=logging_energy)
        for _seg in run_arm(spec, adj, init, rng, ctx):
            pass
        for p in logged:
            if p and p not in seen:
                seen.append(p)
            if len(seen) >= k:
                return seen[:k]
    return seen[:k]


def hub_fraction(paths: Sequence[PathT], hubs: Sequence[str]) -> float:
    """Fraction of returned paths touching a hub node (K-S2a recording)."""
    if not paths:
        return 0.0
    hset = set(hubs)
    touch = sum(1 for p in paths
                if any(u in hset or v in hset for u, v, _ in p))
    return touch / len(paths)


def f1_determinism(params, seed: int) -> FixtureVerdict:
    a = canonical(generate(params, seed))
    b = canonical(generate(params, seed))
    return FixtureVerdict("F1", a == b,
                          f"byte-identical={a == b} bytes={len(a)}")


def _arm_paths(graph, seeds, k: int, budget: int, steps: int,
               extra_arms: dict | None = None) -> dict[str, list[PathT]]:
    arms: dict[str, tuple] = {
        "A0": (make_a0, {"_flat": True}),
        "A1": (make_a1, {"temperature": 5.0}),
        "A2": (make_a2, {"t0": 50.0, "alpha": 0.9, "t_end": 0.5}),
    }
    if extra_arms:
        arms.update(extra_arms)
    return {aid: collect_k_paths(mk, kw, graph, seeds, k, budget, steps)
            for aid, (mk, kw) in arms.items()}


def _arm_recalls(graph, truth: GroundTruth, seeds, k: int, budget: int,
                 steps: int, extra_arms: dict | None = None,
                 ) -> dict[str, float]:
    paths = _arm_paths(graph, seeds, k, budget, steps, extra_arms)
    return {aid: recall_at_k(p, truth.planted) for aid, p in paths.items()}


def f2_null_sanity(graph, truth: GroundTruth, seeds, k: int, budget: int,
                   steps: int) -> FixtureVerdict:
    r = _arm_recalls(graph, truth, seeds, k, budget, steps)
    passed = r["A1"] > r["A0"] and r["A2"] > r["A0"]
    return FixtureVerdict("F2", passed, f"recalls={r}")


def f3_label_shuffle(graph, truth: GroundTruth, seeds, k: int,
                     budget: int, steps: int) -> FixtureVerdict:
    """Shuffle which paths count as planted (graph byte-identical —
    asserted); recompute recalls. Deterministic in (truth, seed)."""
    before = canonical(BenchmarkInstance(graph=graph, truth=truth))
    pool: list[PathT] = []
    for p in truth.planted:
        pool.append(p)
    for nm in truth.nearmiss:
        pool.append(nm)
    shr = random.Random(999)
    shr.shuffle(pool)
    fake = tuple(pool[:len(truth.planted)])
    moved = set(fake) != set(truth.planted)
    r = _arm_recalls(graph, truth, seeds, k, budget, steps)
    rs = {}
    paths = _arm_paths(graph, seeds, k, budget, steps)
    for aid, p in paths.items():
        rs[aid] = recall_at_k(p, fake)
    after = canonical(BenchmarkInstance(graph=graph, truth=truth))
    return FixtureVerdict(
        "F3", moved and after == before,
        f"labels-moved={moved} graph-unchanged={after == before} "
        f"true={r} shuffled={rs}")


def f4_budget(graph, seed: int, budget: int, steps: int) -> FixtureVerdict:
    """Counter equality across arms + overrun raises (D3/F4)."""
    from generator import as_adjacency
    adj = as_adjacency(graph)
    ctx = SearchContext(graph_id=f"fx-{graph.seed}")
    used: dict[str, int] = {}
    for aid, spec in (
            ("A0", make_a0(validate_path, budget=budget, steps=steps)),
            ("A1", make_a1(5.0, reference_energy, validate_path,
                           budget=budget, steps=steps)),
            ("A2", make_a2(50.0, 0.9, 0.5, reference_energy, validate_path,
                           budget=budget, steps=steps))):
        rng = make_rng_stream(f"fx-{graph.seed}", seed, stream=aid)
        init = initial_path(rng, adj, validate_path, 2)
        total = 0
        for seg in run_arm(spec, adj, init, rng, ctx):
            total = seg.budget_used  # cumulative shared-counter reading
        used[aid] = total
    ok = all(u <= budget for u in used.values())
    c = BudgetCounter(1)
    c.evaluate(reference_energy, [{"edge_type": "supports"}], ctx)
    try:
        c.evaluate(reference_energy, [{"edge_type": "supports"}], ctx)
        overrun = False
    except Exception:
        overrun = True
    return FixtureVerdict("F4", ok and overrun, f"used={used} overrun={overrun}")


def f5_isolation() -> FixtureVerdict:
    """Twin write to production stores impossible (closed prefix
    vocabulary refuses ``texp001:``); production acceptance rejects a
    twin artifact end-to-end. Exercises (never modifies) production."""
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import (
        ClaimAssumptionRepository, ProjectRepository, TaskRepository,
        ResearchClaimError,
    )
    from hermes.research.claims import (
        CLAIM_SCHEMA_VERSION, ExtractionDraft, ResearchAssumptionDraft,
        ResearchClaimDraft, validate_extraction,
    )
    from hermes.core.node import AgentProfile, NodeContract, NodeType
    from hermes.core.task_status import TaskStatus
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    conn.execute(
        "INSERT INTO dataset_manifests (manifest_id, project_id, location,"
        " format, size_bytes, headers_json, schema_observations_json,"
        " query_recipes_json, content_hash, provenance_json, created_at,"
        " immutable) VALUES ('dm-1','p1','data/x.csv','csv',100,'[]','[]',"
        " '[]','dmhash1',NULL,'2026-01-01T00:00:00.000000+00:00',1)")
    node = NodeContract(
        task_id="extract-f5", project_id="p1",
        task_type=NodeType.AGENT_TASK.value,
        profile=AgentProfile.RESEARCHER.value, idempotency_key="f5",
        iteration=1,
        spec={"template": "extract", "template_version": "1",
              "source_ref": "texp001:run-1", "scope": "both"},
        inputs=[], outputs=[], dependencies=[], provenance=[],
        cost_class="small", concurrency_group=None, max_retries=3,
        parent_task_id=None)
    tr = TaskRepository(conn)
    tr.create(node)
    tr.transition_status("extract-f5", TaskStatus.READY, caused_by="test")
    tr.transition_status("extract-f5", TaskStatus.RUNNING, caused_by="test")
    repo = ClaimAssumptionRepository(conn)
    direct = repo._dereference_artifact_ref("p1", "texp001:run-1")
    draft = ExtractionDraft(
        source_ref="task_evidence:run-1",
        claims=(ResearchClaimDraft(
            ref="c1", statement="Twin claim.",
            source_ref="texp001:dm-1", support_state="INFERRED",
            span_ref="s1", claim_type="causal",
            context_tags={"regime": "ICSS-v1:low-vol",
                          "dataset_ref": "dm-1"},
            assumption_refs=("a1",)),),
        assumptions=(ResearchAssumptionDraft(
            ref="a1", statement="Twin premise.",
            context_tags={"population": "adults-18-65"},
            supporting_artifact_refs=("dataset_manifest:dm-1",)),),
        extracted_by="task-1", schema_version=CLAIM_SCHEMA_VERSION)
    result = validate_extraction(draft)
    assert result.verdict.name == "ADMITTED", result.errors
    refused = False
    try:
        repo.record_extraction("p1", result, producing_task_id="extract-f5",
                               extracted_by="task-1")
    except ResearchClaimError:
        refused = True
    conn.close()
    return FixtureVerdict("F5", (not direct) and refused,
                          f"direct-deref={direct} write-refused={refused}")


def f6_validator(graph, truth: GroundTruth) -> FixtureVerdict:
    """Injected type-violating + near-miss proposals refused by the
    reference validator (Case B-1); planted accepted."""
    bad = 0
    checked = 0
    for u, v, t in truth.violating_edges:
        r = validate_path([{"src": u, "dst": v, "edge_type": t}])
        checked += 1
        bad += r.accepted
    for nm in truth.nearmiss:
        r = validate_path([{"src": u, "dst": v, "edge_type": t}
                           for u, v, t in nm])
        checked += 1
        bad += r.accepted
    ok_planted = all(
        validate_path([{"src": u, "dst": v, "edge_type": t}
                       for u, v, t in p]).accepted
        for p in truth.planted)
    return FixtureVerdict(
        "F6", bad == 0 and ok_planted and checked > 0,
        f"admitted-violations={bad}/{checked} planted-ok={ok_planted}")


def f7_sensitivity(graph, truth: GroundTruth, seeds, k: int,
                   budget: int, steps: int) -> FixtureVerdict:
    """K1-amended cripple: same-budget degraded policy (A1 at infinite
    temperature = accept-all admissible walk), not a budget cut."""
    base = _arm_recalls(graph, truth, seeds, k, budget, steps)
    crip = _arm_recalls(
        graph, truth, seeds, k, budget, steps,
        extra_arms={"CRIPPLED": (make_a1, {"temperature": float("inf")})})
    c = crip["CRIPPLED"]
    passed = c < base["A1"]
    return FixtureVerdict("F7", passed,
                          f"crippled={c} a1={base['A1']} recalls={base}")


def pilot_gate(recalls: Mapping[str, float],
               hub_fractions: Mapping[str, float], bar: float,
               ) -> tuple[bool, dict]:
    """Pilot acceptance (K-S2a/K-S2b wired): F2 directional check +
    declared informativeness bar (REQUIRED — no default) + hub fractions
    RECORDED (not gated). ``bar`` is declared at B-calibration."""
    r0, r1, r2 = recalls["A0"], recalls["A1"], recalls["A2"]
    f2 = r1 > r0 and r2 > r0
    above_bar = r1 >= bar and r2 >= bar
    details = {"recalls": dict(recalls),
               "hub_fractions": dict(hub_fractions), "bar": bar,
               "f2": f2, "above_bar": above_bar}
    return (f2 and above_bar, details)


__all__ = [
    "FixtureVerdict",
    "canonical",
    "collect_k_paths",
    "f1_determinism",
    "f2_null_sanity",
    "f3_label_shuffle",
    "f4_budget",
    "f5_isolation",
    "f6_validator",
    "f7_sensitivity",
    "hub_fraction",
    "pilot_gate",
]


# ══════════════════════════════════════════════════════════════════════
# B4 SOURCE (GR3-P2-b4fixtures) — real typed-edge reference graphs.
#
# SIMULATED twin-namespace consumption of the GR3 mainline's packaged
# reference graphs (docs/gr3-b4/b4-fixtures/, decision record
# docs/gr3-b4/P2-b4fixtures.md). Everything below is ADDITIVE: the
# synthetic F1–F7 fixtures above are byte-unchanged and keep their exact
# behaviour, and the `__all__` above is deliberately NOT edited — callers
# opt in by importing these names explicitly.
#
# READ PATH ONLY. Nothing here runs an experiment: no arm, no kernel, no
# energy, no validator, no production import, no writes. It reads the
# content-addressed fixture files the mainline wrote (each file is named
# by the sha256 of its own bytes), re-verifies that name/digest binding,
# enforces the SIMULATED + twin-namespace markers, and returns a frozen,
# data-only graph.
#
# A B4 graph's only edge type is `cites`, which is NOT a member of the
# twin's 14-class EDGE_ALPHABET (validator.py / SOURCES.md). B4 graphs
# are therefore reference STRUCTURE for the twin today — not yet
# admissible sequences, and not runnable benchmark instances.
# ══════════════════════════════════════════════════════════════════════

B4_FIXTURES_RELPATH = "docs/gr3-b4/b4-fixtures"
B4_EDGE_TYPE = "cites"
B4_NAMESPACE = "texp-001-twin"
B4_CONSUMPTION = "SIMULATED"
B4_AUTHORITY = "ADVISORY"
B4_FIXTURE_SCHEMA_VERSION = "1"

_B4_BODY_KEYS = frozenset({
    "fixture_id", "rationale", "fixture_schema_version",
    "extraction_version", "namespace", "consumption", "authority",
    "source_set", "edges", "skipped", "counts",
})


class B4FixtureError(ValueError):
    """A twin-side B4 read failed the closed contract (absent fixture,
    name/digest mismatch, foreign namespace, non-SIMULATED consumption,
    unknown keys, bad edge) — fail closed, return nothing."""


@dataclass(frozen=True, slots=True)
class B4ReferenceGraph:
    """One B4 reference graph as the twin sees it: data only, no
    executable payload, addressed by its own content digest."""

    fixture_id: str
    digest: str
    twin_ref: str
    namespace: str
    consumption: str
    authority: str
    extraction_version: str
    sources: tuple[str, ...]
    edges: tuple[tuple[str, str, str], ...]
    skipped: tuple[str, ...]


def b4_fixtures_dir() -> str | None:
    """Locate the mainline B4 fixtures directory, or ``None`` when the
    handoff is absent (the twin degrades gracefully on twin-only
    branches instead of failing the whole suite)."""
    from pathlib import Path
    for base in Path(__file__).resolve().parents:
        candidate = base / B4_FIXTURES_RELPATH
        if candidate.is_dir():
            return str(candidate)
    return None


def b4_available() -> bool:
    """True when the B4 handoff is present for consumption."""
    return b4_fixtures_dir() is not None


def _b4_parse(data: bytes, digest: str) -> B4ReferenceGraph:
    """Verify + read one fixture body (closed, fail-closed)."""
    import hashlib
    import json
    actual = hashlib.sha256(data).hexdigest()
    if actual != digest:
        raise B4FixtureError(
            f"B4 fixture digest mismatch: name says {digest!r} but the "
            f"bytes hash to {actual!r} — the file was edited or the "
            f"name is forged")
    try:
        body = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise B4FixtureError(f"B4 fixture is not JSON ({exc})") from None
    if not isinstance(body, dict):
        raise B4FixtureError("B4 fixture body must be a JSON object")
    unknown = sorted(set(body) - _B4_BODY_KEYS)
    if unknown:
        raise B4FixtureError(
            f"B4 fixture: unknown keys {unknown} — schema is closed")
    if body.get("namespace") != B4_NAMESPACE:
        raise B4FixtureError(
            f"B4 fixture namespace {body.get('namespace')!r} is not the "
            f"twin namespace {B4_NAMESPACE!r}")
    if body.get("consumption") != B4_CONSUMPTION:
        raise B4FixtureError(
            f"B4 fixture consumption {body.get('consumption')!r} is not "
            f"{B4_CONSUMPTION!r} — a twin artifact is never presented "
            f"as production")
    if body.get("fixture_schema_version") != B4_FIXTURE_SCHEMA_VERSION:
        raise B4FixtureError(
            f"B4 fixture schema version "
            f"{body.get('fixture_schema_version')!r} is unsupported")
    fixture_id = body.get("fixture_id")
    if not isinstance(fixture_id, str) or not fixture_id:
        raise B4FixtureError("B4 fixture_id must be a non-empty string")
    sources: list[str] = []
    for i, entry in enumerate(body.get("source_set") or []):
        if not isinstance(entry, dict) or "corpus_ref" not in entry:
            raise B4FixtureError(f"source_set[{i}] is malformed")
        sources.append(str(entry["corpus_ref"]))
    edges: list[tuple[str, str, str]] = []
    for i, entry in enumerate(body.get("edges") or []):
        if not isinstance(entry, dict):
            raise B4FixtureError(f"edges[{i}] is malformed")
        citing, cited = entry.get("citing_ref"), entry.get("cited_ref")
        etype = entry.get("edge_type")
        if not isinstance(citing, str) or not isinstance(cited, str):
            raise B4FixtureError(f"edges[{i}]: endpoints must be strings")
        if citing == cited:
            raise B4FixtureError(f"edges[{i}]: self-edge refused")
        if etype != B4_EDGE_TYPE:
            raise B4FixtureError(
                f"edges[{i}]: edge_type {etype!r} is not {B4_EDGE_TYPE!r}")
        edges.append((citing, cited, etype))
    skipped = body.get("skipped") or []
    if not all(isinstance(s, str) for s in skipped):
        raise B4FixtureError("B4 fixture skipped entries must be strings")
    extraction_version = body.get("extraction_version")
    if not isinstance(extraction_version, str) or not extraction_version:
        raise B4FixtureError(
            "B4 fixture must record its extraction_version")
    return B4ReferenceGraph(
        fixture_id=fixture_id,
        digest=digest,
        twin_ref=f"texp001:b4/{fixture_id}",
        namespace=B4_NAMESPACE,
        consumption=B4_CONSUMPTION,
        authority=B4_AUTHORITY,
        extraction_version=extraction_version,
        sources=tuple(sorted(sources)),
        edges=tuple(sorted(edges)),
        skipped=tuple(sorted(skipped)),
    )


def b4_reference_graphs() -> tuple[B4ReferenceGraph, ...]:
    """Read every packaged B4 fixture (verified, sorted by id)."""
    from pathlib import Path
    directory = b4_fixtures_dir()
    if directory is None:
        raise B4FixtureError(
            f"B4 handoff absent: no {B4_FIXTURES_RELPATH!r} directory "
            f"above {__file__!r}")
    out: list[B4ReferenceGraph] = []
    for path in sorted(Path(directory).glob("*.json")):
        out.append(_b4_parse(path.read_bytes(), path.stem))
    return tuple(sorted(out, key=lambda g: g.fixture_id))


def b4_fixture_ids() -> tuple[str, ...]:
    """The fixture ids currently available to the twin."""
    return tuple(g.fixture_id for g in b4_reference_graphs())


def b4_reference_graph(fixture_id: str) -> B4ReferenceGraph:
    """Read ONE B4 fixture by id (the demonstrated read path)."""
    for graph in b4_reference_graphs():
        if graph.fixture_id == fixture_id:
            return graph
    raise B4FixtureError(
        f"no B4 fixture with id {fixture_id!r}")
