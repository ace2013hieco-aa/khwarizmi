"""A conflict is a reason to investigate — one bounded verification round.

OPS-5Z Group E. A ``CONFLICT`` from ``contradiction_scan`` is evidence that two
claims cannot both be true. Before this module the critic could report it and
the run ended with zero proposals: a noticed problem that became nothing. The
critic's ``REQUEST_ADDITIONAL_EXPERIMENT`` proposal opens one round of
investigation, the spine decides whether it runs, and the round's outcome is
recorded.

Two modes, chosen by where the disagreement lives (the spine derives the mode
from the claims' declared sources; the critic declares it and the gateway
checks the declaration):

* ``verify-one`` — the two claims rest on *different* sources. One targeted
  fetch of the primary source for the disputed figure; both sides are checked
  against that one artifact.
* ``parallel-two`` — the two claims rest on the *same* source and still
  disagree. Two branches, one per side, each fetching its own primary and
  establishing its own figure. Both branches are recorded.

The bound is structural: one round per claim (the round identity is a hash of
the claim refs and the disputed question; the gateway refuses a second round
for any claim that already had one — a persistent conflict is ``DISPUTED``,
not another fetch). The fetch itself is the capability plane's ``source_fetch``
— egress allowlist, provider consistency and the content gate included — and
the artifact is read through the one content model, so a challenge page is
refused before it can be cited.

Determinism: the adjudication is ``check_claim`` over the fetched content and
the two statements. The model proposes; the round produces evidence; this
module names which side (if either) the evidence establishes. It never ranks
the claims on its own authority and never lets the critic decide.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from hermes.research.grounding import check_claim
from hermes.research.inspection import facts_in
from hermes.research.programs import canonical_json, sha256_hex
from hermes.tools.capabilities.content import ArtifactRead, read_content
from hermes.tools.research_sources import SOURCE_PROVIDER_ALLOWLIST

__all__ = [
    "MAX_CONFLICT_DETAIL_CHARS",
    "MAX_REF_CHARS",
    "MAX_STATEMENT_CHARS",
    "MAX_TARGET_URL_CHARS",
    "VERIFICATION_MODES",
    "VERIFICATION_ROUND_PREFIX",
    "VERIFICATION_STATUSES",
    "VerificationBranch",
    "VerificationClaim",
    "VerificationOutcome",
    "VerificationRound",
    "VerificationTarget",
    "derive_mode",
    "outcome_payload",
    "parse_outcome_payload",
    "parse_round_payload",
    "round_key",
    "round_payload",
    "run_round",
]

VERIFICATION_ROUND_PREFIX = "vr_"
VERIFICATION_MODES = ("verify-one", "parallel-two")
VERIFICATION_STATUSES = ("RESOLVED", "DISPUTED", "REFUSED")

MAX_VERIFICATION_CLAIMS = 2
MAX_STATEMENT_CHARS = 900
MAX_REF_CHARS = 200
MAX_TARGET_URL_CHARS = 500
MAX_CONFLICT_DETAIL_CHARS = 600
MAX_OUTCOME_DETAIL_CHARS = 900
MAX_EVIDENCE_REFS = 2

_CLAIM_KEYS = frozenset({"ref", "statement", "source_ref"})
_CONFLICT_KEYS = frozenset({"kind", "left", "right", "subject", "date", "detail"})
_TARGET_KEYS = frozenset({"claim_ref", "provider", "url"})
_CONFLICT_KINDS = frozenset({"QUANTITY", "ATTRIBUTION", "ORDER"})
_OUTCOME_KEYS = frozenset({
    "round_id", "status", "winner_ref", "detail", "code", "evidence_refs",
    "branches",
})
_BRANCH_KEYS = frozenset({"claim_ref", "status", "detail", "evidence_ref"})


class VerificationError(ValueError):
    """A round payload/shape refused. Carries the reason the caller reports."""


@dataclass(frozen=True, slots=True)
class VerificationClaim:
    """One side of the conflict: its ref, statement and declared source."""

    ref: str
    statement: str
    source_ref: str = ""

    def to_mapping(self) -> dict[str, str]:
        return {"ref": self.ref, "statement": self.statement,
                "source_ref": self.source_ref}


@dataclass(frozen=True, slots=True)
class VerificationTarget:
    """One fetch the round needs: which side it serves, where to fetch it."""

    claim_ref: str
    provider: str
    url: str

    def to_mapping(self) -> dict[str, str]:
        return {"claim_ref": self.claim_ref, "provider": self.provider,
                "url": self.url}


@dataclass(frozen=True, slots=True)
class VerificationRound:
    """A validated round request, ready to be recorded and executed."""

    round_id: str
    claims: tuple[VerificationClaim, VerificationClaim]
    conflict: Mapping[str, str]
    mode: str
    targets: tuple[VerificationTarget, ...]

    @property
    def claim_refs(self) -> tuple[str, str]:
        return (self.claims[0].ref, self.claims[1].ref)


@dataclass(frozen=True, slots=True)
class VerificationBranch:
    """One side's outcome inside the round, with the artifact it rests on."""

    claim_ref: str
    status: str          # "established" | "not_established" | "refused"
    detail: str = ""
    evidence_ref: str = ""
    code: str = ""

    def to_mapping(self) -> dict[str, str]:
        return {"claim_ref": self.claim_ref, "status": self.status,
                "detail": self.detail, "evidence_ref": self.evidence_ref}


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    """The round's terminal answer: one of the three statuses and why."""

    status: str                       # RESOLVED | DISPUTED | REFUSED
    winner_ref: str = ""
    detail: str = ""
    code: str = ""
    evidence_refs: tuple[str, ...] = ()
    branches: tuple[VerificationBranch, ...] = ()

    def to_payload(self, round_id: str) -> dict[str, Any]:
        return {
            "round_id": round_id,
            "status": self.status,
            "winner_ref": self.winner_ref,
            "detail": self.detail[:MAX_OUTCOME_DETAIL_CHARS],
            "code": self.code,
            "evidence_refs": list(self.evidence_refs),
            "branches": [branch.to_mapping() for branch in self.branches],
        }


def _string(value: object, name: str, *, limit: int,
            allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise VerificationError(f"{name} must be a string")
    text = value.strip()
    if not text and not allow_empty:
        raise VerificationError(f"{name} must not be empty")
    if len(text) > limit:
        raise VerificationError(
            f"{name} is {len(text)} chars, over the {limit}-char bound")
    return text


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VerificationError(f"{name} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str],
                name: str) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown:
        raise VerificationError(f"{name} has unknown keys {unknown}")
    if missing:
        raise VerificationError(f"{name} is missing keys {missing}")


def _claim(value: object, index: int) -> VerificationClaim:
    claim = _mapping(value, f"claims[{index}]")
    _exact_keys(claim, _CLAIM_KEYS, f"claims[{index}]")
    return VerificationClaim(
        ref=_string(claim.get("ref"), f"claims[{index}].ref",
                    limit=MAX_REF_CHARS),
        statement=_string(claim.get("statement"), f"claims[{index}].statement",
                          limit=MAX_STATEMENT_CHARS),
        source_ref=_string(claim.get("source_ref"),
                           f"claims[{index}].source_ref",
                           limit=MAX_REF_CHARS, allow_empty=True),
    )


def _conflict(value: object) -> dict[str, str]:
    conflict = _mapping(value, "conflict")
    _exact_keys(conflict, _CONFLICT_KEYS, "conflict")
    kind = _string(conflict.get("kind"), "conflict.kind", limit=32)
    if kind not in _CONFLICT_KINDS:
        raise VerificationError(
            f"conflict.kind {kind!r} is not one of {sorted(_CONFLICT_KINDS)}")
    return {
        "kind": kind,
        "left": _string(conflict.get("left"), "conflict.left",
                        limit=MAX_REF_CHARS),
        "right": _string(conflict.get("right"), "conflict.right",
                         limit=MAX_REF_CHARS),
        "subject": _string(conflict.get("subject"), "conflict.subject",
                           limit=MAX_REF_CHARS, allow_empty=True),
        "date": _string(conflict.get("date"), "conflict.date",
                        limit=64, allow_empty=True),
        "detail": _string(conflict.get("detail"), "conflict.detail",
                          limit=MAX_CONFLICT_DETAIL_CHARS, allow_empty=True),
    }


def _target(value: object, index: int) -> VerificationTarget:
    target = _mapping(value, f"targets[{index}]")
    _exact_keys(target, _TARGET_KEYS, f"targets[{index}]")
    provider = _string(target.get("provider"), f"targets[{index}].provider",
                       limit=64)
    if provider not in SOURCE_PROVIDER_ALLOWLIST:
        raise VerificationError(
            f"targets[{index}].provider {provider!r} is not an allowlisted "
            f"source provider ({sorted(SOURCE_PROVIDER_ALLOWLIST)})")
    url = _string(target.get("url"), f"targets[{index}].url",
                  limit=MAX_TARGET_URL_CHARS)
    if not url.lower().startswith("https://") or "://" not in url:
        raise VerificationError(
            f"targets[{index}].url must be an absolute https URL")
    return VerificationTarget(
        claim_ref=_string(target.get("claim_ref"),
                          f"targets[{index}].claim_ref",
                          limit=MAX_REF_CHARS, allow_empty=True),
        provider=provider, url=url)


def derive_mode(claims: Sequence[VerificationClaim]) -> str:
    """The cost the spine will pay, from where the disagreement lives.

    Different sources (or one side naming none) — the claims do not rest on
    the same artifact, so one fetch of the primary source can settle it:
    ``verify-one``. The same non-empty source on both sides — the source
    itself is in dispute: ``parallel-two``.
    """
    if len(claims) != 2:
        raise VerificationError("a round has exactly two claims")
    left, right = claims
    if left.source_ref and left.source_ref == right.source_ref:
        return "parallel-two"
    return "verify-one"


def round_key(project_id: str, claims: Sequence[VerificationClaim],
              conflict: Mapping[str, str]) -> str:
    """The round's content identity: the disputed question, not its wording.

    The statements and target URLs are not part of the key — a crash/retry
    that re-states the same conflict is the same round. The claim refs and the
    conflict's kind/subject/date are: a different question between the same
    claims is still bounded by the claim refs at the gateway.
    """
    preimage = {
        "project_id": project_id,
        "claims": sorted(claim.ref for claim in claims),
        "kind": conflict["kind"],
        "subject": conflict["subject"],
        "date": conflict["date"],
    }
    return VERIFICATION_ROUND_PREFIX + sha256_hex(canonical_json(preimage))


def parse_round_payload(payload: object, *, project_id: str) -> VerificationRound:
    """Validate the closed payload and derive the round identity/mode.

    Raises :class:`VerificationError` with a statement a caller can report;
    the gateway maps it to ``MALFORMED_PAYLOAD``.
    """
    document = _mapping(payload, "payload")
    expected = frozenset({"claims", "conflict", "mode", "targets"})
    _exact_keys(document, expected, "payload")
    claims_value = document.get("claims")
    if not isinstance(claims_value, (list, tuple)) or len(
            claims_value) != MAX_VERIFICATION_CLAIMS:
        raise VerificationError(
            f"payload.claims must be a list of exactly "
            f"{MAX_VERIFICATION_CLAIMS} claims")
    claims = (_claim(claims_value[0], 0), _claim(claims_value[1], 1))
    if claims[0].ref == claims[1].ref:
        raise VerificationError("the two claims must have different refs")
    conflict = _conflict(document.get("conflict"))
    refs = {claims[0].ref, claims[1].ref}
    if not {conflict["left"], conflict["right"]} <= refs:
        raise VerificationError(
            "conflict.left/right must name the two claims (got "
            f"{conflict['left']!r}, {conflict['right']!r}; claims are "
            f"{sorted(refs)})")
    mode = _string(document.get("mode"), "payload.mode", limit=32)
    if mode not in VERIFICATION_MODES:
        raise VerificationError(
            f"payload.mode {mode!r} is not one of {list(VERIFICATION_MODES)}")
    expected_mode = derive_mode(claims)
    if mode != expected_mode:
        raise VerificationError(
            f"payload.mode {mode!r} contradicts the claims' sources: "
            f"derived {expected_mode!r} (different sources cost one fetch; "
            "the same source on both sides is two branches)")
    targets_value = document.get("targets")
    if not isinstance(targets_value, (list, tuple)):
        raise VerificationError("payload.targets must be a list")
    targets = tuple(_target(item, index)
                    for index, item in enumerate(targets_value))
    if mode == "verify-one":
        if len(targets) != 1:
            raise VerificationError(
                "verify-one needs exactly one target (one targeted fetch)")
    else:
        if len(targets) != 2:
            raise VerificationError(
                "parallel-two needs exactly two targets (one per side)")
        if {target.claim_ref for target in targets} != refs:
            raise VerificationError(
                "parallel-two targets must name each claim exactly once")
    return VerificationRound(
        round_id=round_key(project_id, claims, conflict),
        claims=claims, conflict=conflict, mode=mode, targets=targets)


def round_payload(round_: VerificationRound) -> dict[str, Any]:
    """The journal record of an opened round — names the conflict, always."""
    return {
        "round_id": round_.round_id,
        "claim_refs": list(round_.claim_refs),
        "claims": [claim.to_mapping() for claim in round_.claims],
        "conflict": dict(round_.conflict),
        "mode": round_.mode,
        "targets": [target.to_mapping() for target in round_.targets],
        "budget": 1,
    }


def _evidence_ref(value: object, name: str) -> str:
    ref = _string(value, name, limit=MAX_REF_CHARS)
    prefix, separator, artifact_id = ref.partition(":")
    if prefix != "evidence" or separator != ":" or len(artifact_id) != 64 \
            or not all(c in "0123456789abcdef" for c in artifact_id):
        raise VerificationError(
            f"{name} must be 'evidence:<64-hex artifact id>', got {ref!r}")
    return ref


def parse_outcome_payload(payload: object) -> dict[str, Any]:
    """Validate a round outcome; the gateway checks it against the open round."""
    document = _mapping(payload, "payload")
    _exact_keys(document, _OUTCOME_KEYS, "payload")
    round_id = _string(document.get("round_id"), "payload.round_id", limit=96)
    if not round_id.startswith(VERIFICATION_ROUND_PREFIX) \
            or len(round_id) != len(VERIFICATION_ROUND_PREFIX) + 64:
        raise VerificationError(
            f"payload.round_id must be {VERIFICATION_ROUND_PREFIX}<64 hex>")
    status = _string(document.get("status"), "payload.status", limit=16)
    if status not in VERIFICATION_STATUSES:
        raise VerificationError(
            f"payload.status {status!r} is not one of "
            f"{list(VERIFICATION_STATUSES)}")
    winner_ref = _string(document.get("winner_ref"), "payload.winner_ref",
                         limit=MAX_REF_CHARS, allow_empty=True)
    detail = _string(document.get("detail"), "payload.detail",
                     limit=MAX_OUTCOME_DETAIL_CHARS, allow_empty=True)
    code = _string(document.get("code"), "payload.code", limit=64,
                   allow_empty=True)
    evidence_value = document.get("evidence_refs")
    if not isinstance(evidence_value, (list, tuple)):
        raise VerificationError("payload.evidence_refs must be a list")
    if len(evidence_value) > MAX_EVIDENCE_REFS:
        raise VerificationError(
            f"payload.evidence_refs may name at most {MAX_EVIDENCE_REFS} "
            "artifacts")
    evidence_refs = tuple(
        _evidence_ref(ref, f"payload.evidence_refs[{index}]")
        for index, ref in enumerate(evidence_value))
    branches_value = document.get("branches")
    if not isinstance(branches_value, (list, tuple)):
        raise VerificationError("payload.branches must be a list")
    branches: list[dict[str, str]] = []
    for index, value in enumerate(branches_value):
        branch = _mapping(value, f"payload.branches[{index}]")
        _exact_keys(branch, _BRANCH_KEYS, f"payload.branches[{index}]")
        branches.append({
            "claim_ref": _string(branch.get("claim_ref"),
                                 f"payload.branches[{index}].claim_ref",
                                 limit=MAX_REF_CHARS),
            "status": _string(branch.get("status"),
                              f"payload.branches[{index}].status", limit=32),
            "detail": _string(branch.get("detail"),
                              f"payload.branches[{index}].detail",
                              limit=MAX_OUTCOME_DETAIL_CHARS,
                              allow_empty=True),
            "evidence_ref": _string(
                branch.get("evidence_ref"),
                f"payload.branches[{index}].evidence_ref",
                limit=MAX_REF_CHARS, allow_empty=True),
        })
    if status == "RESOLVED":
        if not winner_ref:
            raise VerificationError(
                "a RESOLVED round must name the winning claim ref")
        if not evidence_refs:
            raise VerificationError(
                "a RESOLVED round must name the artifact it rests on")
    if status in ("DISPUTED", "REFUSED") and not detail:
        raise VerificationError(f"a {status} round must say why")
    if status == "REFUSED" and not code:
        raise VerificationError(
            "a REFUSED round must carry the code that stopped it")
    return {
        "round_id": round_id,
        "status": status,
        "winner_ref": winner_ref,
        "detail": detail,
        "code": code,
        "evidence_refs": list(evidence_refs),
        "branches": branches,
    }


def outcome_payload(outcome: VerificationOutcome,
                    round_id: str) -> dict[str, Any]:
    return outcome.to_payload(round_id)


# ── execution ──


@dataclass(frozen=True, slots=True)
class _Fetched:
    """One target's decoded artifact, or why it could not be read."""

    claim_ref: str
    content: str = ""
    evidence_ref: str = ""
    code: str = ""
    detail: str = ""


def _observation_payload(observation: object) -> Mapping[str, Any] | None:
    payload = getattr(observation, "payload", None)
    text = getattr(payload, "text", None)
    if not isinstance(text, str):
        return None
    try:
        document = json.loads(text)
    except ValueError:
        return None
    return document if isinstance(document, Mapping) else None


def _read_artifact(port: Callable[[str, str], Any] | None,
                   project_id: str, artifact_id: str) -> ArtifactRead:
    if port is None:
        return ArtifactRead(data=b"")
    value = port(project_id, artifact_id)
    if isinstance(value, ArtifactRead):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ArtifactRead(data=bytes(value))
    return ArtifactRead(data=b"")


def _fetch_target(
    target: VerificationTarget,
    *,
    invoke: Callable[[Any], Any] | None,
    read_artifact: Callable[[str, str], Any] | None,
    project_id: str,
    lease_generation: str,
    grant: Any,
    deadline_seconds: float,
) -> _Fetched:
    if invoke is None:
        return _Fetched(claim_ref=target.claim_ref, code="NO_CAPABILITY",
                        detail="no capability plane is wired for the round")
    if grant is None:
        return _Fetched(claim_ref=target.claim_ref, code="NO_GRANT",
                        detail="no RESEARCHER grant is wired for the round")
    from hermes.tools.capabilities.types import InvokeRequest

    request = InvokeRequest(
        capability_id="source_fetch",
        arguments={"provider": target.provider, "url": target.url},
        idempotency_key=(f"verification:{target.claim_ref}:"
                         f"{sha256_hex(target.url)[:24]}"),
        lease_generation=lease_generation,
        profile="RESEARCHER",
        rationale=("verification round: fetch the primary source for the "
                   "disputed figure"),
        grant=grant,
        deadline_seconds=deadline_seconds)
    observation = invoke(request)
    payload = _observation_payload(observation)
    if payload is None:
        code = str(getattr(observation, "code", "") or "MALFORMED_PAYLOAD")
        detail = str(getattr(observation, "detail", "") or
                     "the fetch returned no observation payload")
        return _Fetched(claim_ref=target.claim_ref, code=code, detail=detail)
    if payload.get("status") != "FETCHED":
        return _Fetched(
            claim_ref=target.claim_ref,
            code=str(payload.get("code") or "EMPTY_RESULT"),
            detail=str(getattr(observation, "detail", "")
                       or "the fetch did not produce an artifact"))
    artifact_id = str(payload.get("artifact_id") or "")
    artifact = _read_artifact(read_artifact, project_id, artifact_id)
    read = read_content(artifact.data, format=artifact.format)
    if not read.is_content or read.partial:
        return _Fetched(
            claim_ref=target.claim_ref, code="SOURCE_NOT_READABLE",
            detail=(f"the fetched artifact could not be read as its content "
                    f"({read.state.value}"
                    + (f": {read.detail}" if read.detail else "") + ")"))
    return _Fetched(claim_ref=target.claim_ref, content=read.text,
                    evidence_ref=f"evidence:{artifact_id}")


def _adjudicate_claim(claim: VerificationClaim, content: str,
                      conflict: Mapping[str, str]) -> tuple[bool, str]:
    """Whether one side's figures are established by the fetched content."""
    inspection = facts_in(claim.statement)
    if not inspection.figures:
        return False, "the claim states no figure the gate can check"
    subjects = tuple(sorted({figure.entity for figure in inspection.figures
                             if figure.entity}))
    if conflict["subject"]:
        for name in conflict["subject"].split("/"):
            name = name.strip()
            if name and name.casefold() in claim.statement.casefold() \
                    and name not in subjects:
                subjects = (*subjects, name)
    verdict = check_claim(claim.statement, content, subjects=subjects)
    if verdict.grounded:
        return True, "its figures are established by the fetched artifact"
    if verdict.refusal is not None:
        return False, f"{verdict.refusal.value}: {verdict.detail}"
    if verdict.caveat is not None:
        return False, f"{verdict.caveat.value}: {verdict.detail}"
    return False, verdict.detail or "the evidence does not establish it"


def run_round(
    round_: VerificationRound,
    *,
    invoke: Callable[[Any], Any] | None,
    read_artifact: Callable[[str, str], Any] | None,
    project_id: str,
    lease_generation: str,
    grant: Any,
    deadline_seconds: float = 60.0,
) -> VerificationOutcome:
    """Fetch, read and adjudicate one round. No writes; returns the outcome.

    ``invoke`` is the capability invoker; ``read_artifact`` the project-scoped
    byte port (the same one the evidence envelope reads). Both are ports: this
    module performs no I/O of its own, so a test can bind the real capability
    plane or a scripted one.
    """
    fetched: list[_Fetched] = []
    for target in round_.targets:
        fetched.append(_fetch_target(
            target, invoke=invoke, read_artifact=read_artifact,
            project_id=project_id, lease_generation=lease_generation,
            grant=grant, deadline_seconds=deadline_seconds))

    branches: list[VerificationBranch] = []
    evidence_refs: list[str] = []
    for item in fetched:
        if item.evidence_ref:
            evidence_refs.append(item.evidence_ref)

    if round_.mode == "verify-one":
        item = fetched[0]
        if not item.content:
            # One fetch serves both sides; a refused fetch refuses both, and
            # each branch still names its claim (a branch without a claim is
            # not a record a consumer can attribute).
            branches.extend(VerificationBranch(
                claim_ref=claim.ref, status="refused", detail=item.detail,
                code=item.code) for claim in round_.claims)
            return VerificationOutcome(
                status="REFUSED", detail=item.detail, code=item.code,
                branches=tuple(branches))
        for claim in round_.claims:
            survives, reason = _adjudicate_claim(
                claim, item.content, round_.conflict)
            branches.append(VerificationBranch(
                claim_ref=claim.ref,
                status=("established" if survives else "not_established"),
                detail=reason, evidence_ref=item.evidence_ref))
    else:
        by_ref = {item.claim_ref: item for item in fetched}
        refused = [item for item in fetched if not item.content]
        if refused:
            for item in fetched:
                branches.append(VerificationBranch(
                    claim_ref=item.claim_ref,
                    status=("refused" if not item.content else "not_established"),
                    detail=(item.detail if not item.content
                            else "its branch did not run"),
                    code=item.code,
                    evidence_ref=item.evidence_ref))
            first = refused[0]
            return VerificationOutcome(
                status="REFUSED",
                detail=(f"branch {first.claim_ref or '?'} could not run: "
                        f"{first.detail}"),
                code=first.code, evidence_refs=tuple(evidence_refs),
                branches=tuple(branches))
        for claim in round_.claims:
            item = by_ref.get(claim.ref)
            if item is None:
                branches.append(VerificationBranch(
                    claim_ref=claim.ref, status="refused",
                    code="NO_TARGET", detail="no branch targeted this claim"))
                return VerificationOutcome(
                    status="REFUSED", code="NO_TARGET",
                    detail=f"no branch targeted claim {claim.ref!r}",
                    evidence_refs=tuple(evidence_refs),
                    branches=tuple(branches))
            survives, reason = _adjudicate_claim(
                claim, item.content, round_.conflict)
            branches.append(VerificationBranch(
                claim_ref=claim.ref,
                status=("established" if survives else "not_established"),
                detail=reason, evidence_ref=item.evidence_ref))

    winners = [branch for branch in branches if branch.status == "established"]
    if len(winners) == 1:
        return VerificationOutcome(
            status="RESOLVED", winner_ref=winners[0].claim_ref,
            detail=(f"{winners[0].claim_ref} is established by the fetched "
                    f"evidence; "
                    + "; ".join(f"{branch.claim_ref}: {branch.detail}"
                                for branch in branches)),
            evidence_refs=tuple(evidence_refs), branches=tuple(branches))
    if not winners:
        detail = "neither side is established: " + "; ".join(
            f"{branch.claim_ref}: {branch.detail}" for branch in branches)
    else:
        detail = "both sides are established: " + "; ".join(
            f"{branch.claim_ref}: {branch.detail}" for branch in branches)
    return VerificationOutcome(
        status="DISPUTED", detail=detail[:MAX_OUTCOME_DETAIL_CHARS],
        evidence_refs=tuple(evidence_refs), branches=tuple(branches))
