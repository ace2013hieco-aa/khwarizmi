"""Contract matrix — do the layers agree about the same field?

Every blocker this week was one layer disagreeing with another about a value:
the completion gate counting a refusal as an admission (5T), a required artifact
nothing produced (5Y), a field declared optional and enforced mandatory (5Z).
Each slice tested its own claim and passed; nothing tested the seam.

This script walks four seams and reports disagreements. Read-only, no imports
of persistence, no writes, deterministic output.

    python scripts/contract_matrix.py            # human table, exit 1 on mismatch
    python scripts/contract_matrix.py --json     # machine form

The checks:

A. **Minted-kind content (key ablation).** For each chain kind, build the node
   the default producer makes and delete one content key at a time. A key whose
   removal makes the shape gate refuse is *load-bearing*; one whose removal is
   ignored is decorative. This is behavioural on purpose — the gate's
   requirements are code branches, not a declarative list, so asking it is more
   honest than parsing its messages.

B. **Declaration vs enforcement.** For each stage in the shipped methodology,
   resolve stage → profile → contract and compare the contract's `required`
   flag against the key ablation from A. A key the gate requires, offered to the
   model as optional, is the OPS-5Z defect.

C. **Refusal vocabulary.** Codes the substrate emits versus the codes it
   declares. An undeclared code is a refusal a consumer cannot branch on.

D. **Objectives.** A stage whose node needs a statement, whose objective never
   asks for one. The prose is not a validator, but a stage that never asks is a
   stage that will not get.
"""
from __future__ import annotations

import argparse
import contextlib
import inspect
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import structure_map

from hermes.agents.runtime.config import load_profiles
from hermes.agents.runtime.run import DRAFT_KEYS, output_contract_for
from hermes.core.intents import IntentKind
from hermes.methodology import substrate as S
from hermes.methodology import workflows as W
from hermes.methodology.workflows import MethodologyInputs
from hermes.research.gateway import INTENT_PAYLOAD_KEYS
from hermes.tools.models.cloud import render_system
from hermes.tools.models.router import _contract_mapping

PROFILES = Path(__file__).resolve().parent.parent / "src/hermes/agents/runtime/profiles"


def _node(kind: str, content: Mapping[str, Any]) -> S.SubstrateNode:
    return S.SubstrateNode(kind=kind, project_id="p", producing_task_id="t",
                           content=dict(content), rationale="r")


def _refuses(kind: str, content: Mapping[str, Any]) -> tuple[bool, str]:
    refusal = S._kind_refusal(_node(kind, content))
    if refusal is None:
        return False, ""
    return True, f"{refusal.code}: {refusal.detail[:80]}"


def _default_content(kind: str) -> Mapping[str, Any]:
    inputs = MethodologyInputs(question="a question")
    return W._default_content(kind, inputs, "mnode_pred", "mnode_q",
                              evidence_ref="evidence:x", statement="a statement")


def ablation() -> dict[str, Any]:
    """Which content keys does the shape gate actually require, per kind?"""
    out: dict[str, Any] = {}
    for kind in S.CHAIN_KINDS:
        content = dict(_default_content(kind))
        refuses, detail = _refuses(kind, content)
        empty_refused, _ = _refuses(kind, {})
        record: dict[str, Any] = {
            "produced": sorted(content),
            "accepts_empty_node": not empty_refused,
            "baseline_ok": not refuses,
            "baseline_refusal": detail,
            "load_bearing": [],
            "decorative": [],
        }
        for key in sorted(content):
            trimmed = {k: v for k, v in content.items() if k != key}
            refused, _ = _refuses(kind, trimmed)
            (record["load_bearing"] if refused else record["decorative"]).append(key)
        out[kind] = record
    return out


def contracts(abl: Mapping[str, Any]) -> dict[str, dict[str, dict[str, bool]]]:
    """Each profile's declared requirement, per field, in both shapes.

    ``required`` is unconditional. ``when_proposing`` (OPS-5Z) is the per-reply
    marker: a minting stage's gather tick has no proposal and must stay valid,
    so the requirement cannot be a plain ``required=True``. A field counts as
    offered when either is set.

    A minting profile is built **as its minting stage receives it** — with the
    flag set — because that is the contract the model is given. Building every
    profile with the default would make this seam blind to the marker by
    construction: it would report a disagreement that only exists in the
    shape nobody is served.
    """
    minting = {stage["profile"]
               for stage in W.LITERATURE_REVIEW_DOCUMENT["stages"]
               if "statement" in abl.get(stage["stage"], {}
                                         ).get("load_bearing", [])}
    out: dict[str, dict[str, dict[str, bool]]] = {}
    for name, spec in sorted(load_profiles(directory=PROFILES).items()):
        kwargs: dict[str, Any] = {}
        if name in minting and "requires_statement" in inspect.signature(
                output_contract_for).parameters:
            kwargs["requires_statement"] = True
        contract = output_contract_for(spec, **kwargs)
        out[name] = {
            f.name: {"required": bool(f.required),
                     "when_proposing": bool(
                         getattr(f, "required_when_proposing", False))}
            for f in contract.fields}
    return out


def _offered(flags: Mapping[str, Any], key: str) -> bool:
    """True when the contract demands this field in either shape."""
    entry = flags.get(key)
    if isinstance(entry, Mapping):
        return bool(entry.get("required") or entry.get("when_proposing"))
    return entry is True


#: The modules that own each side of a declaration/enforcement mismatch. A
#: finding is weighted by the widest of them: a disagreement inside `run.py`
#: (fan_in 36, fan_out 87) is a different order of problem from one in a leaf.
SEAM_OWNERS: tuple[str, ...] = (
    "hermes.agents.runtime.run",
    "hermes.methodology.substrate",
)


def module_fan_in() -> dict[str, int]:
    """Local import fan-in — the blast-radius proxy, no Docker required."""
    edges = structure_map.collect(
        Path(__file__).resolve().parent.parent / "src/hermes")[0]
    fan_in: dict[str, int] = {}
    for targets in edges.values():
        for target in targets:
            fan_in[target] = fan_in.get(target, 0) + 1
    return fan_in


def declaration_vs_enforcement(abl: Mapping[str, Any],
                               declared: Mapping[str, Mapping[str, bool]]
                               ) -> list[dict[str, Any]]:
    """Stage → profile → contract, for **every** key the gate requires.

    Not just `statement`. The first version hardcoded that one string, so
    renaming the field in the gate and the producer while leaving the contract
    alone produced zero findings — the exact defect class the matrix exists to
    catch, made invisible by a literal.
    """
    doc = W.LITERATURE_REVIEW_DOCUMENT
    rows: list[dict[str, Any]] = []
    for stage in doc["stages"]:
        kind, profile = stage["stage"], stage["profile"]
        required = list(abl.get(kind, {}).get("load_bearing", []))
        if profile not in declared:
            # A stage pointing at a profile that has no contract cannot be
            # satisfied, whatever its kind. Reported, not skipped.
            rows.append({
                "stage": kind, "profile": profile, "load_bearing": required,
                "unoffered": required or ["<no contract for profile>"],
                "verdict": "MISMATCH"})
            continue
        flags = declared[profile]
        # Only keys that cross the *model* boundary can be a contract finding.
        # `question`, `external_ref`, `subject_ref`, `question_ref` and `origin`
        # are driver-supplied content — the gate requiring them is not a
        # disagreement with the contract, it is the driver doing its job. A
        # load-bearing key that is not a draft field is checked elsewhere (or
        # is not the model's to supply).
        unoffered = [key for key in required
                     if key in DRAFT_KEYS and not _offered(flags, key)]
        rows.append({
            "stage": kind,
            "profile": profile,
            "load_bearing": required,
            "unoffered": unoffered,
            "verdict": "MISMATCH" if unoffered else "ok",
        })
    return rows


def objective_mentions(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for stage in doc["stages"]:
        objective = str(stage.get("objective") or "")
        rows.append({
            "stage": stage["stage"],
            "mentions_statement": "statement" in objective.lower(),
            "objective_head": objective[:70],
        })
    return rows


EMITTED = re.compile(r"_refuse\(\s*(?:\n\s*)?([A-Z][A-Z_]{2,})")


def _render(name: str, spec: Any, *, minting: bool) -> str:
    """The system prompt for a profile, with the per-reply flag when asked.

    The flag does not exist before OPS-5Z, so the call is probed rather than
    assumed: today this renders the default contract (which says ``optional``,
    the defect), and once the keyword lands it renders the minting shape.
    """
    kwargs: dict[str, Any] = {}
    if minting and "requires_statement" in inspect.signature(
            output_contract_for).parameters:
        kwargs["requires_statement"] = True
    mapping = _contract_mapping(output_contract_for(spec, **kwargs))
    return render_system(name, mapping) if mapping else ""


def rendered_coverage(abl: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Does the prompt mention every field the validator checks — and does a
    minting stage's prompt actually *require* the statement?

    A field the contract declares but the renderer drops is a field the model is
    never told about. A field the renderer calls optional while the gate demands
    it is the OPS-5Z defect itself, and this seam must be able to show the
    difference — so a minting profile is rendered with the flag set.
    """
    minting_profiles = {stage["profile"]
                        for stage in W.LITERATURE_REVIEW_DOCUMENT["stages"]
                        if "statement" in abl.get(stage["stage"], {}
                                                  ).get("load_bearing", [])}
    rows: list[dict[str, Any]] = []
    for name, spec in sorted(load_profiles(directory=PROFILES).items()):
        contract = output_contract_for(spec)
        text = _render(name, spec, minting=name in minting_profiles)
        lowered = text.lower()
        absent = [f.name for f in contract.fields
                  if f.name.lower() not in lowered]
        statement_line = next(
            (ln for ln in text.splitlines()
             if ln.strip().startswith("- statement")), "")
        rows.append({
            "profile": name,
            "minting": name in minting_profiles,
            "fields": [f.name for f in contract.fields],
            "absent_from_prompt": absent,
            "statement_line": statement_line.strip()[:110],
            "statement_required": "required when the reply proposes"
                                  in statement_line.lower(),
        })
    return rows


def payload_schemas() -> list[dict[str, Any]]:
    """Can every kind a profile may propose have its payload schema rendered?"""
    rows: list[dict[str, Any]] = []
    for name, spec in sorted(load_profiles(directory=PROFILES).items()):
        for kind in sorted(str(getattr(k, "value", k))
                           for k in spec.authority.proposable_kinds):
            rows.append({
                "profile": name,
                "kind": kind,
                "has_payload_schema": IntentKind(kind) in INTENT_PAYLOAD_KEYS,
            })
    return rows


def refusal_vocabulary() -> dict[str, list[str]]:
    source = Path(S.__file__).read_text(encoding="utf-8")
    emitted = set(EMITTED.findall(source))
    declared = set(S.SUBSTRATE_REFUSAL_CODES)
    return {
        "emitted_not_declared": sorted(emitted - declared),
        "declared_not_emitted": sorted(declared - emitted),
    }


def build() -> dict[str, Any]:
    abl = ablation()
    declared = contracts(abl)
    doc = W.LITERATURE_REVIEW_DOCUMENT
    rows = declaration_vs_enforcement(abl, declared)
    fan_in = module_fan_in()
    weight = max((fan_in.get(owner, 0) for owner in SEAM_OWNERS), default=0)
    for row in rows:
        row["weight"] = weight if row["verdict"] == "MISMATCH" else 0
    return {
        "blast_radius": {owner: fan_in.get(owner, 0) for owner in SEAM_OWNERS},
        "ablation": abl,
        "contracts": declared,
        "stages": rows,
        "objectives": objective_mentions(doc),
        "vocabulary": refusal_vocabulary(),
        "rendered": rendered_coverage(abl),
        "payloads": payload_schemas(),
        "mismatches": sorted((r for r in rows if r["verdict"] == "MISMATCH"),
                             key=lambda r: -r["weight"]),
    }


def render(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("CONTRACT MATRIX — do the layers agree about the same field?")
    add("=" * 74)

    add("")
    add("A. MINTED-KIND CONTENT — which keys the shape gate actually requires")
    for kind, record in report["ablation"].items():
        add(f"  {kind:<12} produced={record['produced']}")
        add(f"  {'':<12} load-bearing={record['load_bearing']}"
            f"  decorative={record['decorative']}")
        if record["accepts_empty_node"]:
            add(f"  {'':<12} NO CONTENT RULE — an empty {kind} node records "
                f"once its predecessor is valid (provenance still "
                f"refuses a node with none)")
        if not record["baseline_ok"]:
            add(f"  {'':<12} DEFAULT CONTENT REFUSED: {record['baseline_refusal']}")

    add("")
    add("B. DECLARATION vs ENFORCEMENT — stage → profile → contract")
    add(f"  {'stage':<12} {'profile':<13} {'gate requires':<18} "
        f"{'contract omits':<16} {'blast':<6} verdict")
    for row in report["stages"]:
        needs = ",".join(row["load_bearing"]) or "-"
        off = ",".join(row["unoffered"]) or "-"
        add(f"  {row['stage']:<12} {row['profile']:<13} {needs:<18} "
            f"{off:<16} {str(row.get('weight', 0)):<6} {row['verdict']}")

    add("")
    add("A2. KINDS THE SHAPE GATE DOES NOT CONSTRAIN AT ALL")
    unconstrained = [k for k, r in report["ablation"].items()
                     if r["accepts_empty_node"]]
    add(f"  accepts an empty node: {unconstrained or 'none'}")
    add("  (CLAIM's admitted_refs is enforced in _support_refusal, not here;")
    add("   a decorative key above is not automatically a hole)")

    add("")
    add("E. CONTRACT RENDERING - is every declared field in the prompt?")
    add(f"  minting profiles whose line does not require it: "
        f"{[r['profile'] for r in report['rendered'] if r.get('minting') and not r.get('statement_required')] or 'none'}")
    for row in report["rendered"]:
        mark = "minting" if row.get("minting") else "        "
        add(f"  {row['profile']:<12} {mark} fields={row['fields']}")
        if row["absent_from_prompt"]:
            add(f"  {'':<12} ABSENT FROM PROMPT: {row['absent_from_prompt']}")
        if row["statement_line"]:
            add(f"  {'':<12} {row['statement_line']!r}")

    add("")
    add("F. PAYLOAD SCHEMAS - a proposable kind with no declared schema")
    missing = [r for r in report["payloads"] if not r["has_payload_schema"]]
    add(f"  without a schema: {len(missing)}/{len(report['payloads'])}")
    for row in missing:
        add(f"      {row['profile']:<12} {row['kind']}")

    add("")
    add("C. REFUSAL VOCABULARY")
    vocab = report["vocabulary"]
    add(f"  emitted but not declared: {vocab['emitted_not_declared'] or 'none'}")
    add(f"  declared but not emitted: {vocab['declared_not_emitted'] or 'none'}")

    add("")
    add("D. OBJECTIVES — does the stage that needs a statement ask for one?")
    for row in report["objectives"]:
        mark = "asks" if row["mentions_statement"] else "silent"
        add(f"  {row['stage']:<12} {mark:<7} {row['objective_head']!r}")

    add("")
    mismatches = report["mismatches"]
    add(f"VERDICT: {len(mismatches)} declaration/enforcement mismatch(es)")
    blast = report["blast_radius"]
    add("  blast radius (import fan-in of the modules that own the seam): "
        + ", ".join(f"{k.split('.')[-1]}={v}" for k, v in blast.items()))
    for row in mismatches:
        add(f"  [{row['weight']}] {row['stage']} ({row['profile']}): the gate "
            f"requires {row['load_bearing']}; the contract does not require "
            f"{row['unoffered']}")
    return "\n".join(lines)


def finding_keys(report: Mapping[str, Any]) -> list[str]:
    """Stable identities for **every** seam's findings, not just one.

    The first version keyed only the declaration/enforcement mismatches, so the
    vocabulary, rendering, payload-schema and objective seams could report a
    defect and never move the exit status. A seam that cannot fail the gate is a
    seam nobody has to fix.
    """
    keys = [f"{row['stage']}:{key}"
            for row in report["mismatches"]
            for key in row["unoffered"]]
    keys += [f"vocab:{code}"
             for code in report["vocabulary"]["emitted_not_declared"]]
    keys += [f"render:{row['profile']}:{field}"
             for row in report["rendered"]
             for field in row["absent_from_prompt"]]
    # A minting profile whose rendered line does not require the statement is
    # the OPS-5Z defect, in the prompt. Keyed so the baseline must lose these
    # three when the slice lands — a slice that leaves them baselined has not
    # been measured.
    keys += [f"render-required:{row['profile']}"
             for row in report["rendered"]
             if row.get("minting") and not row.get("statement_required")]
    keys += [f"payload:{row['profile']}:{row['kind']}"
             for row in report["payloads"]
             if not row["has_payload_schema"]]
    keys += [f"objective:{row['stage']}"
             for row in report["objectives"]
             if not row["mentions_statement"]]
    return sorted(keys)


def read_baseline(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}") from exc
    return data if isinstance(data, dict) else None


def write_baseline(path: Path, keys: Sequence[str], reason: str,
                   previous: dict[str, Any] | None) -> None:
    data = {
        "accepted": sorted(keys),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": reason,
        "history": (previous or {}).get("history", []),
    }
    if previous is not None:
        data["history"].append({
            "accepted": len(previous.get("accepted", [])),
            "reason": reason or "update"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--baseline", type=Path, default=None,
                        help="Accepted findings; fail only on an unlisted one.")
    parser.add_argument("--update", action="store_true",
                        help="Accept the current findings as the baseline.")
    parser.add_argument("--allow", default="",
                        help="Accept a NEW finding, and record why.")
    parser.add_argument("--note", default="", help="Context stored with --update.")
    args = parser.parse_args(argv)

    # The table contains an arrow and an em dash. A cp1252 console or a piped
    # stdout can raise UnicodeEncodeError *while printing*, which exits 1 —
    # indistinguishable from "a mismatch was found". Pin the encoding so the
    # exit status always means what it says.
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    try:
        report = build()
    except Exception:  # noqa: BLE001 - the exit status is the point
        # Exit 1 means "a finding"; a traceback must not masquerade as one.
        traceback.print_exc()
        print("\nthe matrix itself failed — exit 2, not a finding",
              file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True) if args.json
          else render(report))

    if args.baseline is None:
        return 1 if report["mismatches"] else 0

    keys = finding_keys(report)
    previous = read_baseline(args.baseline)

    if args.update:
        write_baseline(args.baseline, keys, args.note, previous)
        print(f"\naccepted {len(keys)} finding(s) -> {args.baseline}")
        return 0

    if previous is None:
        print(f"\nno baseline at {args.baseline} — a missing baseline is not a "
              f"pass. Run with --update to accept the current findings.",
              file=sys.stderr)
        return 2

    accepted = set(previous.get("accepted", []))
    new = [key for key in keys if key not in accepted]
    fixed = sorted(accepted - set(keys))

    print("\nCONTRACT BASELINE")
    if fixed:
        print(f"  {len(fixed)} baselined finding(s) no longer present — "
              f"record with --update: {fixed}")
    if not new:
        print(f"  no new finding ({len(keys)} known)")
        return 0

    for key in new:
        print(f"  NEW FINDING  {key}")
    if args.allow:
        write_baseline(args.baseline, sorted(accepted | set(new)), args.allow,
                       previous)
        print(f"  accepted: {args.allow} ({len(new)} new finding(s) baselined)")
        return 0

    print("  A finding not in the baseline is a disagreement that did not "
          "exist before.\n  Re-run with --allow \"<reason>\" if it is intended.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
