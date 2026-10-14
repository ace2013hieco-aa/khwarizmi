"""N9 resolve-path pin: every evidence-resolve site is classified.

EXT-3 (triage ``audit/ext-1-triage@bc1a5da`` item **L3** -- "N9 predicate
state drift"). The N9 predicate ``source_artifact_retracted``
(``persistence/source_outcomes.py``) is certified at exactly four call
sites (N9 cert ``02cb976``; frozen per ``AGENTS.md``). Several *other*
paths resolve ``source_result:`` / ``source_payload:`` refs through the
pre-existing ``_source_artifact_resolves`` helper **without** the
predicate. Whether each is an *evidence position* subject to N9 was a
per-surface judgement the code neither enforced nor recorded -- so a new
resolve path could be added that silently bypasses retraction fencing.

This module closes that drift by *recording* the judgement and *enforcing*
it structurally. It scans every ``.py`` under ``src/hermes`` and requires
every function that calls ``_source_artifact_resolves`` to appear in
exactly one of three tables below:

1. ``N9_FENCED_RESOLVE_SITES`` -- certified evidence positions: the
   function must contain the retraction predicate, ordered *after* the
   resolve call (the resolved artifact is re-checked before use).
2. ``N9_NON_EVIDENCE_ALLOWLIST`` -- resolve paths that are deliberately
   *not* N9 positions, each with the reason. Fencing them would be wrong,
   not merely redundant.
3. ``N9_FROZEN_GAP_REGISTER`` -- paths that *are* decision-affecting
   evidence positions but sit on certified writers/validators, so the
   fence may not be added without the owning gate re-run. Recorded here
   so the gap is explicit and cannot silently grow.

The predicate side is pinned too (``N9_CERTIFIED_PREDICATE_SITES``): a
certified fence that is deleted fails this module.

How a future developer cannot silently drift: adding a call to
``_source_artifact_resolves`` in a new function makes that function
appear in the scan but in none of the three tables, so
``test_every_resolve_site_is_classified`` fails and names the site. The
only way to land a new resolve path is to classify it here on purpose.

Current census (8 resolve sites, 4 predicate sites -- EXT-3, base
``main@6cce97c``):

    resolve site                                   enclosing function                       verdict
    ---------------------------------------------  ---------------------------------------  ----------------
    persistence/failure_classifications.py:361      ..._verify_evidence_owned               fenced
    persistence/failure_classifications.py:401      ..._evidence_resolver                   fenced
    persistence/graph_edges.py:338                  GraphEdgeRepository._resolve_endpoint   non-evidence
    persistence/repositories.py:2002                ClaimAssumption..._dereference_artifact_ref  frozen gap
    persistence/source_outcomes.py:474              SourceOutcomeRepository.dereference_ref non-evidence
    persistence/source_outcomes.py:719              SourceOutcomeRepository._validate_task_binding  non-evidence
    research/gateway.py:2386                        _validate_curate_knowledge              frozen gap
    research/gateway.py:3953                        _validate_source_spec                   non-evidence
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "hermes"

_RESOLVE = "_source_artifact_resolves"
_PREDICATE = "source_artifact_retracted"

# ── 1. Certified evidence positions: predicate required, after the resolve ──

N9_FENCED_RESOLVE_SITES = {
    (
        "persistence/failure_classifications.py",
        "FailureClassificationRepository._verify_evidence_owned",
    ),
    (
        "persistence/failure_classifications.py",
        "FailureClassificationRepository._evidence_resolver",
    ),
}

# ── 2. Certified predicate sites (N9 cert 02cb976) -- exactly these four ──
# The two failure_classifications entries are the resolve-side fences above;
# the other two resolve through their own project-scoped SQL rather than the
# shared helper, so they are pinned by presence only.

N9_CERTIFIED_PREDICATE_SITES = {
    (
        "persistence/failure_classifications.py",
        "FailureClassificationRepository._verify_evidence_owned",
    ),
    (
        "persistence/failure_classifications.py",
        "FailureClassificationRepository._evidence_resolver",
    ),
    ("research/contradiction_candidates.py", "detector_candidate_rows"),
    ("research/gateway.py", "_cx_resolve_evidence_ref"),
}

# ── 3. Non-evidence resolve paths (deliberately unfenced) ──

N9_NON_EVIDENCE_ALLOWLIST = {
    (
        "persistence/graph_edges.py",
        "GraphEdgeRepository._resolve_endpoint",
    ): (
        "gr3 corpus-edge endpoints: binds a content hash to its admitted "
        "artifact id and anti-substitutes against the row's corpus_ref "
        "metadata. Corpus membership/identity, not admissibility as "
        "decision evidence -- a retracted payload may remain a corpus "
        "member; N9 bars it as evidence for a NEW decision, not from the "
        "corpus graph."
    ),
    (
        "persistence/source_outcomes.py",
        "SourceOutcomeRepository.dereference_ref",
    ): (
        "The shared typed ref->bool dereference helper (SD-05 / S6-A1). It "
        "answers a form/resolution question -- does this typed ref point "
        "at a real carrier of the matching type? Admissibility is the "
        "caller's question. Fencing here would fence every caller "
        "indiscriminately, including pure provenance bindings."
    ),
    (
        "persistence/source_outcomes.py",
        "SourceOutcomeRepository._validate_task_binding",
    ): (
        "SOURCE_FETCH R01 binding: the fetch's spec refs must be produced "
        "by the cited search task (two-hop derived_from). Provenance "
        "binding, not admissibility -- a retracted source_result may still "
        "be the fetch's own declared input, and the payload read path is "
        "guarded by UntrustedContent envelopment plus content-hash "
        "re-verification (EXT-1 R2), not by N9."
    ),
    (
        "research/gateway.py",
        "_validate_source_spec",
    ): (
        "Same SOURCE_FETCH R01/D2 binding at the admission gate: the "
        "cited source_refs must belong to the cited search task. "
        "Provenance binding, not an admissibility position."
    ),
}

# ── 4. Frozen-gap register: decision-affecting, but gate-blocked ──
# Each entry is an evidence position that SHOULD carry the predicate. It is
# recorded, not fenced, because the fence may only be added with the owning
# gate re-run (N9 is FROZEN; AGENTS.md "changes near them need a design gate
# plus the owning certification slice re-run"). See the EXT-3 report.

N9_FROZEN_GAP_REGISTER = {
    (
        "persistence/repositories.py",
        "ClaimAssumptionRepository._dereference_artifact_ref",
    ): (
        "The extraction/claim source_ref dereference IS an evidence "
        "position (a claim's cited source is its evidence). But this "
        "helper's contract is *dereference* under a closed vocabulary -- "
        "'does a carrier exist?' -- not *admissibility*; the N9 fence "
        "belongs at the certified writer call site (record_extraction, a "
        "persistence acquisition owner under the ResearchSourceProvider "
        "step-6 gate record), not in the shared helper. Gate-blocked."
    ),
    (
        "research/gateway.py",
        "_validate_curate_knowledge",
    ): (
        "The CURATE_KNOWLEDGE retraction basis: resolves "
        "falsifying_evidence_refs into the evidence_basis that justifies "
        "the retraction. This IS an admissibility position and the fence "
        "does belong in this function. But it is a certified gateway "
        "validator (one of the 27 acquisition owners; P7 governance "
        "lifecycle) adjacent to the N9-certified gateway site, so the "
        "change needs a design gate plus the N9 certification re-run. "
        "Gate-blocked."
    ),
}

# ── scanner ──


def _callee_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _function_spans(tree: ast.AST) -> list[tuple[str, int, int]]:
    """(class-qualified name, first line, last line) for every function."""
    spans: list[tuple[str, int, int]] = []

    def walk(node: ast.AST, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            nxt = stack
            if isinstance(
                child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                nxt = [*stack, child.name]
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                spans.append(
                    (
                        ".".join(nxt),
                        child.lineno,
                        child.end_lineno or child.lineno,
                    )
                )
            walk(child, nxt)

    walk(tree, [])
    return spans


def _scan_root(root: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]], dict]:
    """Scan ``root`` (a ``src/hermes`` directory).

    Returns ``(resolve_sites, predicate_sites, detail)`` where the site sets
    hold ``(relpath, function)`` pairs and ``detail`` maps
    ``(relpath, function)`` to ``{"resolve": [lines], "predicate": [lines]}``.
    """
    resolve_sites: set[tuple[str, str]] = set()
    predicate_sites: set[tuple[str, str]] = set()
    detail: dict[tuple[str, str], dict[str, list[int]]] = {}

    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        spans = _function_spans(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _callee_name(node)
            if name not in (_RESOLVE, _PREDICATE):
                continue
            owner = None
            for fn_name, start, end in spans:
                if start <= node.lineno <= end:
                    owner = fn_name
            if owner is None:
                continue  # module level: not a function-scoped resolve site
            key = (rel, owner)
            bucket = detail.setdefault(
                key, {"resolve": [], "predicate": []}
            )
            if name == _RESOLVE:
                resolve_sites.add(key)
                bucket["resolve"].append(node.lineno)
            else:
                predicate_sites.add(key)
                bucket["predicate"].append(node.lineno)

    return resolve_sites, predicate_sites, detail


def _scan() -> tuple[set[tuple[str, str]], set[tuple[str, str]], dict]:
    return _scan_root(SRC)


# ── tests ──


def test_every_resolve_site_is_classified() -> None:
    """The drift guard: a resolve path in none of the three tables fails."""
    resolve_sites, _predicate_sites, _detail = _scan()
    classified = (
        N9_FENCED_RESOLVE_SITES
        | set(N9_NON_EVIDENCE_ALLOWLIST)
        | set(N9_FROZEN_GAP_REGISTER)
    )
    unclassified = resolve_sites - classified
    assert not unclassified, (
        "unclassified _source_artifact_resolves call site(s) -- a new "
        "evidence-resolve path was added without an N9 judgement. Add each "
        "to N9_FENCED_RESOLVE_SITES (carries the predicate), "
        "N9_NON_EVIDENCE_ALLOWLIST (documented non-evidence reason), or "
        "N9_FROZEN_GAP_REGISTER (gate-blocked):\n  "
        + "\n  ".join(f"{rel}:{fn}" for rel, fn in sorted(unclassified))
    )
    stale = classified - resolve_sites
    assert not stale, (
        "table entry no longer matches any resolve site (moved, renamed or "
        "deleted) -- update the tables:\n  "
        + "\n  ".join(f"{rel}:{fn}" for rel, fn in sorted(stale))
    )


def test_fenced_resolve_sites_carry_the_predicate_after_the_resolve() -> None:
    """Each certified evidence position re-checks retraction before use."""
    _resolve_sites, _predicate_sites, detail = _scan()
    offenders: list[str] = []
    for rel, fn in sorted(N9_FENCED_RESOLVE_SITES):
        bucket = detail.get((rel, fn))
        if bucket is None or not bucket["resolve"] or not bucket["predicate"]:
            offenders.append(f"{rel}:{fn} (fence missing)")
            continue
        if max(bucket["predicate"]) < min(bucket["resolve"]):
            offenders.append(
                f"{rel}:{fn} (predicate ordered before the resolve)"
            )
    assert not offenders, (
        "certified N9 fence missing or mis-ordered at:\n  "
        + "\n  ".join(offenders)
    )


def test_certified_predicate_sites_are_exactly_the_certified_four() -> None:
    """A certified N9 fence may not be deleted or relocated silently."""
    _resolve_sites, predicate_sites, _detail = _scan()
    assert predicate_sites == N9_CERTIFIED_PREDICATE_SITES, (
        "the set of source_artifact_retracted call sites changed -- N9 "
        "retraction fencing is FROZEN (AGENTS.md) and certified at exactly "
        "four sites by the N9 cert (02cb976). Removed: "
        f"{sorted(N9_CERTIFIED_PREDICATE_SITES - predicate_sites)}; added: "
        f"{sorted(predicate_sites - N9_CERTIFIED_PREDICATE_SITES)}"
    )


def test_frozen_gap_register_is_exact() -> None:
    """The recorded gap may not grow silently -- and may not be quietly
    closed either, so the record stays honest."""
    resolve_sites, _predicate_sites, _detail = _scan()
    gaps = resolve_sites - N9_FENCED_RESOLVE_SITES - set(
        N9_NON_EVIDENCE_ALLOWLIST
    )
    assert gaps == set(N9_FROZEN_GAP_REGISTER), (
        "the frozen-gap register drifted. NEW unrecorded gap(s): "
        f"{sorted(gaps - set(N9_FROZEN_GAP_REGISTER))}; recorded but no "
        "longer a gap (update the register and the EXT-3 report): "
        f"{sorted(set(N9_FROZEN_GAP_REGISTER) - gaps)}"
    )


def test_scanner_detects_a_planted_bypass(tmp_path: Path) -> None:
    """Self-test: the scanner itself must flag a planted bypass.

    Builds a synthetic tree with (a) a fenced site, (b) an allowlisted
    site, and (c) a brand-new unclassified resolve path, and asserts the
    classifier reports exactly (c) as unclassified. This proves the pin
    fails on a deliberately-added bypass rather than passing vacuously.
    """
    pkg = tmp_path / "src" / "hermes" / "persistence"
    pkg.mkdir(parents=True)
    (pkg / "planted.py").write_text(
        "def fenced(conn, pid, h):\n"
        "    if not _source_artifact_resolves(conn, pid, h, 'x'):\n"
        "        return False\n"
        "    return not source_artifact_retracted(conn, pid, h)\n"
        "\n"
        "\n"
        "def allowed(conn, pid, h):\n"
        "    return _source_artifact_resolves(conn, pid, h, 'x')\n"
        "\n"
        "\n"
        "def bypass(conn, pid, h):\n"
        "    return _source_artifact_resolves(conn, pid, h, 'x')\n",
        encoding="utf-8",
    )
    resolve_sites, predicate_sites, detail = _scan_root(
        tmp_path / "src" / "hermes"
    )
    assert ("persistence/planted.py", "fenced") in resolve_sites
    assert ("persistence/planted.py", "fenced") in predicate_sites
    assert ("persistence/planted.py", "allowed") in resolve_sites
    assert ("persistence/planted.py", "bypass") in resolve_sites

    # The planted bypass is unclassified against the real tables ...
    classified = (
        N9_FENCED_RESOLVE_SITES
        | set(N9_NON_EVIDENCE_ALLOWLIST)
        | set(N9_FROZEN_GAP_REGISTER)
    )
    assert ("persistence/planted.py", "bypass") in (resolve_sites - classified)

    # ... and the fenced site satisfies the ordered-fence rule ...
    bucket = detail[("persistence/planted.py", "fenced")]
    assert max(bucket["predicate"]) > min(bucket["resolve"])

    # ... so once the two legitimate sites are classified, ONLY the
    # deliberately-added bypass is reported. That is exactly what
    # test_every_resolve_site_is_classified asserts on the real tree.
    planted_ok = {
        ("persistence/planted.py", "fenced"),
        ("persistence/planted.py", "allowed"),
    }
    assert resolve_sites - classified - planted_ok == {
        ("persistence/planted.py", "bypass")
    }, "the scanner failed to isolate a planted bypass"
