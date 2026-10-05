"""ProviderHazardSpec (hazards as data) + ONE generic ``evaluate_hazards``.

Step 2 of the Part 3 implementation (IDR-030, §27 item 55 RESOLVED).
Remediated per the hostile code audit `hermes_researchsourceprovider_hazard_audit.md`
(HZ-01…HZ-12 folded in — 2026-08-13).

The per-provider failure knowledge lives in ``hazard_specs/<provider>.json`` —
versioned, machine-readable *content* shipped with the ``paper-lookup``
SkillRecord (contract §5.1, blueprint §4). ``evaluate_hazards`` is ONE
deterministic, generic evaluator with ZERO per-provider branches; the catalog
entries (contract §5.3) are the fixtures that prove it. Spec files are content:
they change only through the engineering plane with version bumps, never at
runtime, and an invalid spec fails REGISTRATION (``SpecValidationError``) — a
startup/registration error, never a runtime skip (fail-closed).

Evaluation order (fixed, deterministic — blueprint §4.2):

1.  **Status check** — non-2xx → a status the spec declares as a no-full-text
    signal at FETCH scope is DEFERRED to that check (PS3-01 generalized,
    HZ-03 — the declaration, not just 404, owns the status); a status in the
    spec's ``valid_negative_statuses`` at SEARCH scope is a ``VALID_NEGATIVE``
    pending the throttle check (HZ-08); 429 → ``THROTTLED``; 5xx →
    ``TRANSIENT``. Any OTHER non-2xx is deferred until after step 2 (a throttle
    signature may declare a non-429 status — CORE's token-exhausted 403) and,
    still unclassified, → ``MALFORMED_200`` (the contract's permanent "HTTP 4xx
    validation" class; no dedicated literal exists, so ``MALFORMED_200``
    carries the status in ``reason``/``detected_by``). ``VALID_NEGATIVE`` is
    unreachable at fetch scope (PS3-01). The scope is a driver-set context
    flag, never payload-inferred.
2.  **Throttle signature** — status match, or a ``body_pattern`` matched
    against the RAW text of a plain-text payload (arXiv's ``Rate exceeded.``)
    **or** against the declared ``fields`` **str-leaf** values of a JSON-shaped
    payload (a dict, or bytes that parse to a dict) — **never against result
    content, never against container reprs, and never the whole body when
    ``fields`` are declared** (HZ-01/HZ2-01/HZ2-02: the unanchored whole-
    payload search that throttled legitimate results is closed for dicts AND
    for the realistic bytes transport form; a plain-text signature with no
    fields simply does not fire on JSON content). ``Retry-After`` is honored
    by the driver.
3.  **Error field + markers** — a declared ``error_field`` value matching its
    ``code_pattern`` (code mapped into ``reason``, contract §5.3), then each
    ``HazardMarker`` predicate; first hit wins in spec order. **SEARCH-shape:
    skipped at FETCH scope** — the search-shaped fields do not apply to fetch
    payloads (blueprint §4.1); the fetch rules carry their own
    ``error_field`` (HZ-04).
3a. **Required fields (PS-08)** — any ``required_fields`` path absent →
    ``MALFORMED_200`` (the schema-drift sentinel). **SEARCH-shape: skipped at
    FETCH scope** (the fetch rules carry their own drift sentinel).
4.  **Empty body** — an empty payload → ``EMPTY_RESULT``, or ``VALID_NEGATIVE``
    when the spec's search ``empty_body_rule`` says so. At FETCH scope the rule
    is always ``treat-as-failure`` — a fetch empty body is NEVER a valid
    negative (PS3-02). An empty payload short-circuits 3/3a: the empty case is
    not a drift case (contract: empty ``<PubmedArticleSet/>`` → ``EMPTY_RESULT``).
5.  **Rewrite rules** — declared-filter-vs-response consistency →
    ``REWRITE_SUSPECT`` with expected-vs-got counts (OpenAlex silent filter
    drop). **SEARCH-shape: skipped at FETCH scope.** ``counts_raw_rows``/
    dedup-direction are walk-level spec content, not evaluator concerns.
5b. **Label + completed-body size (RT-05/RT2-04/RT3-01/RT3-04, step 4)** —
    the pinned slot: at SEARCH scope after steps 1–5, before the advisory
    injection; at FETCH scope after the error/drift evidence AND the
    retraction/``NO_FULL_TEXT`` content evidence, before the body composites.
    The per-provider ``content_types`` allowlist vs ``context.content_type``
    (normalized media type; a declared allowlist + concrete mismatch →
    ``MALFORMED_200``; no allowlist / no reported label → skipped, the drift
    sentinel is the shape backstop); the completed-body size check
    (``context.body_size`` vs ``context.size_cap_bytes`` — an oversized
    COMPLETE 2xx body → ``PARTIAL_CONTENT``; the transport's streaming abort
    is the separate status-conditional hard cap, RT3-01 (a)). Status, shape
    (drift/empty), and content (retraction/``NO_FULL_TEXT``) evidence all
    dominate the label check.
6.  **Injection heuristic** — instruction-like text → ``INJECTION_SUSPECT``,
    **advisory only** (recorded for Adversary/review attention; never a block,
    never a content decision — contract §5.4).
6a. **Fetch scope** — only when ``spec.fetch`` is declared AND
    ``context.scope == FETCH``: **ERROR evidence first** (FS-03/04 — the
    PS3-08 dominance principle): fetch ``error_field`` (HZ-04, **any str leaf
    value**, FS-02) and fetch ``required_fields`` absence → ``MALFORMED_200``
    — which dominates ``PARTIAL_CONTENT`` when both would fire (PS3-08); then
    a retraction hit (any value at ``retraction_marker`` matching
    ``retraction_pattern`` — **value semantics, never bare presence**, HZ-02)
    → ``NO_FULL_TEXT`` with kind ``REMOVED_OR_RETRACTED``, never ``NOT_OA``
    (PS3-03); then ``no_full_text`` marker/status → ``NO_FULL_TEXT`` (a
    RESULT, never a failure — marker evidence wins over status alone, PS3-08;
    **any resolved value counts, not just the first**, HZ-05); then the
    ``body_required`` composite (metadata present AND body absent-or-empty —
    present-but-empty counts as absent, PS3-02, **recursively**: a body dict
    whose leaves are all empty (``{"sec": ""}``) is absent, FS-01; presence is
    any-value, FS-08) → ``PARTIAL_CONTENT``; then an empty fetch payload →
    ``EMPTY_RESULT`` (never a fall-through to "full text", PS3-02 —
    meaningful only when the provider declares a ``body_marker``; the
    zero-byte case is caught by step 4 for every provider). The evidence
    basis of every fetch verdict (status, marker path, endpoint) is recorded
    in ``detected_by``.
7.  **CURSOR_TRAP is NOT evaluated here** — the walk driver detects it and
    reports it into the verdict for recording (blueprint §4.2 step 7).

Class set: the ten documented classes plus ``TRANSIENT`` — the transport-mapped
5xx class the walk driver's "transient class only" backoff rule requires
(blueprint §5.2). The design's documented list is the *catalog* classes and
omits it; this module states the completion explicitly rather than forcing a
5xx into ``THROTTLED``.

Registration validation (PS2-09 + PS3-05 + HZ-06/09/10/12): the count-semantics
× ``counts_raw_rows`` matrix; the spec-format ``schema`` key (HZ-10); marker
shape checks + a marker ``failure_class`` restricted to failure/result classes
(a marker declaring ``NONE``/``TRANSIENT``/``INJECTION_SUSPECT``/``CURSOR_TRAP``
is rejected, HZ-12); structural field-path validation (no empty segments,
leading/trailing dots, whitespace — payload-level validity is the
golden-fixture gate, HZ-09); ``loop_guard`` capped at 1000 (HZ-06); throttle
statuses restricted to 4xx and ``fields``-patterns only on JSON-shaped
payloads with leaf-value matching — a fields-scoped signature never searches
whole-body or container-repr text (HZ-01/06/HZ2-01/HZ2-02);
``valid_negative_statuses`` restricted to the not-found family 404/410/451 —
auth failures are never an "answered no" (HZ2-04);
``no_full_text_status`` restricted to 4xx-except-429 (HZ-03/06);
``empty_body_rule: valid-negative`` requires a non-empty
``valid_negative_statuses`` (HZ-06); the fetch-rule coherence checks —
(a) ``body_required`` without ``body_marker``; (a2) ``body_marker`` with
``body_required: false`` (FS-05 — the fall-through enforces body presence
anyway, so the combination is incoherent); (a3) ``body_required`` without a
``metadata_marker`` (FS-06 — the composite needs both sides to fire);
(c) ``no_full_text_marker`` without ``no_full_text_status``;
(c2) ``retraction_marker`` and ``retraction_pattern`` must travel together
(HZ-02); (d) a fetch rule set that can never fire. Rule (b) — fetch rules on
a provider with no fetch surface — is enforced at adapter registration
(step 5), where the adapter declares its fetch capability; ``fetch: null``
means "no fetch hazard knowledge declared — the adapter's fetch parse is the
sole fetch-level gate" (HZ-04).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from hermes.research.programs import canonical_json
from hermes.tools.research_sources import PermanentProviderError

__all__ = [
    # constants
    "HAZARD_CLASSES",
    "SPEC_SCHEMA",
    "CursorRule",
    "ErrorFieldSpec",
    "FetchHazardRules",
    "HazardContext",
    "HazardMarker",
    # types
    "HazardScope",
    "HazardVerdict",
    "ProviderHazardSpec",
    "ProviderPayload",
    "RewriteRule",
    # errors
    "SpecValidationError",
    "ThrottleSig",
    # the one evaluator
    "evaluate_hazards",
    # registration loader + validation
    "load_hazard_spec",
    "resolve_field_path",
]

HazardScope: TypeAlias = Literal["SEARCH", "FETCH"]
ProviderPayload: TypeAlias = "dict[str, object] | str | bytes | None"
EmptyBodyRule: TypeAlias = Literal["treat-as-failure", "valid-negative"]
CursorKind: TypeAlias = Literal["cursor", "offset", "none"]

# The verdict class set (blueprint §4.2 — plus TRANSIENT, see module docstring).
HAZARD_CLASSES: tuple[str, ...] = (
    "NONE",
    "MALFORMED_200",
    "EMPTY_RESULT",
    "PARTIAL_CONTENT",
    "THROTTLED",
    "TRANSIENT",
    "REWRITE_SUSPECT",
    "CURSOR_TRAP",
    "INJECTION_SUSPECT",
    "VALID_NEGATIVE",
    "NO_FULL_TEXT",
)

# The spec-file format schema version (HZ-10) — every hazard_specs/*.json must
# declare it; a future format change bumps this constant and migrates content.
SPEC_SCHEMA = "hermes-hazard-spec/v1"

# Marker failure classes a spec author may declare (HZ-12): the failure classes
# plus the result classes. NONE/TRANSIENT/INJECTION_SUSPECT/CURSOR_TRAP are
# incoherent as marker targets — NONE says the marker fired yet found nothing,
# TRANSIENT is a transport class, INJECTION_SUSPECT is the evaluator's own
# advisory flag, CURSOR_TRAP is driver-detected.
_MARKER_CLASSES = frozenset(set(HAZARD_CLASSES) - {
    "NONE", "TRANSIENT", "INJECTION_SUSPECT", "CURSOR_TRAP",
})

# Verdicts that are typed failures for accounting (recordable). Results
# (VALID_NEGATIVE/NO_FULL_TEXT) and the advisory flag are never recordable.
_RECORDABLE_CLASSES = frozenset({
    "MALFORMED_200", "EMPTY_RESULT", "PARTIAL_CONTENT", "THROTTLED",
    "TRANSIENT", "REWRITE_SUSPECT", "CURSOR_TRAP",
})

# GC-01 (fetch-gate) — the scope-closed output domains. `evaluate_hazards`
# MUST emit only the classes legal for its scope; the guard lives in `_verdict`
# (the single verdict-construction helper — every return path flows through
# it), so no early return can escape. VALID_NEGATIVE is SEARCH-only (PS3-01:
# the fetch 404 short-circuits to NO_FULL_TEXT); REWRITE_SUSPECT/CURSOR_TRAP
# are SEARCH-only (the rewrite/step-5 rules and the cursor are walk concepts);
# NO_FULL_TEXT is FETCH-only (the fetch-scoped no-full-text evidence).
FETCH_ALLOWED = frozenset({
    "NONE", "MALFORMED_200", "EMPTY_RESULT", "PARTIAL_CONTENT",
    "THROTTLED", "TRANSIENT", "INJECTION_SUSPECT", "NO_FULL_TEXT",
})
SEARCH_ALLOWED = frozenset({
    "NONE", "MALFORMED_200", "EMPTY_RESULT", "PARTIAL_CONTENT",
    "THROTTLED", "TRANSIENT", "REWRITE_SUSPECT", "CURSOR_TRAP",
    "INJECTION_SUSPECT", "VALID_NEGATIVE",
})
_ALLOWED_BY_SCOPE = {"SEARCH": SEARCH_ALLOWED, "FETCH": FETCH_ALLOWED}

# The CURSOR_TRAP guard's upper bound (HZ-06) — a spec cannot ship an
# effectively-unbounded pagination walk.
_MAX_LOOP_GUARD = 1000

# The statuses that can mean "identifier resolved to a real no" at SEARCH
# scope (HZ2-04): the not-found family — 404 (not found), 410 (gone), 451
# (legally unavailable). Auth failures (401/403), client errors (400/405/422),
# and throttles (429) are never an "answered no" — a task must never conclude
# "no literature" from "we were forbidden".
_VALID_NEGATIVE_STATUSES = frozenset({404, 410, 451})

# Advisory-only instruction-like markers (contract §5.4 — a review aid, never a
# block). Deliberately narrow to unambiguous instruction text so scientific
# prose ("operating system: …") never false-positives into a flag.
_INJECTION_PATTERNS = (
    r"ignore (all )?previous instructions",
    r"ignore (all )?(prior|previous) (instructions|prompts|messages)",
    r"disregard (all )?(previous|prior|above)",
    r"you must ignore (all )?(previous|prior|above)",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
)


class SpecValidationError(PermanentProviderError):
    """An invalid ``ProviderHazardSpec`` failed registration (fail-closed).

    Spec content is engineering-plane content: an incoherent spec is a
    startup/registration error, never a runtime skip or a contradiction the
    walk driver must interpret.
    """


# ── spec schema (blueprint §4.1) ──


@dataclass(frozen=True)
class HazardMarker:
    """One field-path predicate: ``equals`` OR ``pattern`` (exactly one).

    ``equals`` compares the whitespace-stripped resolved value (HZ-07 — a
    padded provider value must not silently miss). ``pattern`` is a regex
    matched against each resolved value (any-value).
    """

    field_path: str  # dotted path; ``*`` matches any list index; "." = whole payload
    failure_class: str  # a _MARKER_CLASSES member
    equals: str | None = None
    pattern: str | None = None


@dataclass(frozen=True)
class ErrorFieldSpec:
    """A provider error field inside an HTTP-200 body (e.g. EuropePMC
    ``errCode``): a value matching ``code_pattern`` → ``MALFORMED_200`` with the
    code mapped into the reason (contract §5.3)."""

    name: str
    code_pattern: str


@dataclass(frozen=True)
class CursorRule:
    """Pagination shape for the walk driver (cursor/offset/none)."""

    kind: CursorKind
    loop_guard: int = 100  # max_pages — the CURSOR_TRAP guard bound; ≤ _MAX_LOOP_GUARD


@dataclass(frozen=True)
class ThrottleSig:
    """A throttle signature: status and/or body_pattern (at least one).

    ``body_pattern`` matching semantics (HZ-01/HZ2-01/HZ2-02):
    - plain-text payloads (str, or bytes that do not parse as JSON) with EMPTY
      ``fields``: the pattern matches the RAW body — the arXiv
      ``Rate exceeded.`` whole-body throttle;
    - JSON-shaped payloads (dict, or bytes that parse to a dict): the pattern
      matches ONLY the ``str`` leaf values at ``fields`` (field paths, any-
      value) — never result content, and never container reprs (HZ2-02).
    - a body pattern with non-empty ``fields`` NEVER falls to the whole-body
      branch, regardless of payload type (HZ2-01 — bytes-encoded JSON is
      parsed, not whole-body-searched); a pattern with empty ``fields`` never
      fires on JSON-shaped content (the HZ-01 false-positive throttle is
      closed).
    """

    status: int | None = None
    body_pattern: str | None = None
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class RewriteRule:
    """Silent-filter detection (OpenAlex): when the request declared
    ``request_param`` (and ``filter_contains`` is present in its value), any
    record under ``records_path`` missing ``record_field`` → ``REWRITE_SUSPECT``
    with expected-vs-got counts. The rule is spec content; the evaluator applies
    it generically."""

    request_param: str
    records_path: str
    record_field: str
    filter_contains: str | None = None


@dataclass(frozen=True)
class FetchHazardRules:
    """PS2-02 — the fetch-scoped hazard structure. The search-shaped spec fields
    (count_semantics/cursor_rule/rewrite_suspect) do NOT apply to fetch payloads."""

    body_marker: str | None = None  # where the body element lives
    metadata_marker: str | None = None  # where the front/metadata element lives
    body_required: bool = False  # composite: metadata present AND body absent → PARTIAL_CONTENT
    empty_body_rule: Literal["treat-as-failure"] = "treat-as-failure"  # PS3-02 —
    #   a fetch empty body is NEVER a valid negative
    no_full_text_status: int | None = None  # e.g. europepmc 404 → NO_FULL_TEXT
    no_full_text_marker: str | None = None  # PS3-08 — marker evidence wins over
    #   status; PRESENCE semantics — the path must be a LEAF path (a container
    #   path treats any non-empty structure as evidence, which is a spec-author
    #   error the golden-fixture gate must catch, HZ2-03)
    retraction_marker: str | None = None  # HZ-02 — VALUE semantics, never bare
    retraction_pattern: str | None = None  #   presence: any value at the marker
    #   matching the pattern → REMOVED_OR_RETRACTED (the presence-only form
    #   mislabeled normal pub-history as retracted)
    error_field: ErrorFieldSpec | None = None  # HZ-04 — fetch-scoped error field
    required_fields: tuple[str, ...] = ()  # fetch-side drift sentinel (PS-08)


@dataclass(frozen=True)
class ProviderHazardSpec:
    """One provider's versioned hazard knowledge (blueprint §4.1). Loaded from
    ``hazard_specs/<provider>.json`` and validated at registration — never
    edited at runtime."""

    provider_id: str
    version: str
    markers: tuple[HazardMarker, ...] = ()
    empty_body_rule: EmptyBodyRule = "treat-as-failure"
    error_field: ErrorFieldSpec | None = None
    count_semantics: Literal["exact", "estimate", "absent"] = "exact"
    counts_raw_rows: bool = False  # PS-04 — True = total counts EVERY raw row
    #   (Crossref) → dedup BEFORE comparing; False = total is dedup-truthful
    required_fields: tuple[str, ...] = ()
    cursor_rule: CursorRule = field(default_factory=lambda: CursorRule("cursor"))
    throttle_signature: tuple[ThrottleSig, ...] = ()
    rewrite_suspect: tuple[RewriteRule, ...] = ()
    fetch: FetchHazardRules | None = None
    # Statuses that mean "identifier resolved to a real no" at SEARCH scope
    # (404 is the norm; 410 Gone is legitimate). Restricted to 4xx-except-429 at
    # registration (HZ-06) and unreachable at FETCH scope (PS3-01).
    valid_negative_statuses: tuple[int, ...] = (404,)
    # RT-05/RT2-04/RT3-04 — the per-provider media-type allowlist the
    # evaluator's content-type check consults (arXiv: application/atom+xml,
    # PMC: text/xml — never a blanket JSON-only check). Empty = no label
    # check (the required-fields drift sentinel stays the shape-aware
    # backstop). Spec content, versioned, validated at registration.
    content_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class HazardContext:
    """The driver-set request context. ``scope`` is set by the walk/fetch
    driver — never inferred from the payload (PS3-01). ``request_params`` are
    the declared (redaction-safe) request params — the rewrite rules read the
    real declared filter from them. ``endpoint`` is recorded in the verdict
    evidence when set (HZ-11)."""

    scope: HazardScope
    status_code: int = 200
    request_params: dict[str, str] = field(default_factory=dict)
    endpoint: str = ""
    # RT2-04/RT3-01/RT3-04 (step 4) — the label + completed-body size
    # evidence the driver carries in: `content_type` from TransportResponse
    # (normalized media type), `body_size` = len(response body), and
    # `size_cap_bytes` = the task's declared cap (WalkRequest.size_cap_bytes
    # at search scope). The evaluator applies the two checks at the pinned
    # slots — after the status verdicts, the drift sentinel, and the empty-
    # body rule, before the fetch composites / the advisory heuristics.
    content_type: str | None = None
    body_size: int | None = None
    size_cap_bytes: int | None = None


@dataclass(frozen=True)
class HazardVerdict:
    """The deterministic evaluation result (blueprint §4.2). ``detected_by`` is
    the evidence basis (status_code, marker_path, expected/got, spec_version,
    endpoint) the fetch driver reads for ``NoFullText.evidence_basis``
    (PS3-03)."""

    hazard_class: str  # HAZARD_CLASSES member
    reason: str
    detected_by: dict[str, str]
    recordable: bool  # True = a typed failure for accounting; False = result/advisory


# ── field-path resolution (generic, spec-driven) ──


def resolve_field_path(payload: ProviderPayload, path: str) -> tuple[object, ...]:
    """Resolve a dotted field path into all matching values (deterministic).

    - ``"feed.entry"`` → the value at that key (a list resolves to one value).
    - ``"feed.entry.*.title"`` → every title across all entries.
    - ``"feed.entry.0.title"`` → the first entry's title.
    - **A dict-key segment descends into every element of a list and yields
      that key's VALUES** — the XML parse contract (repeated elements become
      lists), so ``"pub-history.event.event-type"`` yields the event-type
      values whether ``event`` is one element or many, and a trailing key
      segment over a list resolves the leaf values directly (HZ-02/HZ-05,
      HZ2-02/03: leaf-value discipline lives HERE — a container never resolves
      to its own repr).
    - ``""`` or ``"."`` → the whole payload (for text-payload markers).
    - A missing segment stops the walk → ``()``.
    """
    if path in ("", "."):
        return () if payload is None else (payload,)
    if not isinstance(payload, dict):
        return ()
    candidates: list[object] = [payload]
    for segment in path.split("."):
        nxt: list[object] = []
        for node in candidates:
            if segment == "*" and isinstance(node, list):
                nxt.extend(node)
            elif isinstance(node, dict) and segment in node:
                nxt.append(node[segment])
            elif isinstance(node, list) and segment.isdigit():
                index = int(segment)
                if 0 <= index < len(node):
                    nxt.append(node[index])
            elif isinstance(node, list):
                # HZ-05/HZ2-02/03: a dict-key segment descends into every list
                # element and yields the key's VALUE — not the element dict, so
                # a trailing key segment resolves the leaf values and a
                # container path never resolves to its repr.
                nxt.extend(item[segment] for item in node
                           if isinstance(item, dict) and segment in item)
        candidates = nxt
        if not candidates:
            return ()
    return tuple(candidates)


def _is_empty_value(value: object) -> bool:
    """Recursive emptiness (FS-01/FS-08): None, whitespace-only text, empty
    containers, and containers whose CONTENTS are all recursively empty count
    as ABSENT for the fetch composite/fall-through. A body dict whose leaves
    are all empty (``{"sec": ""}``) is treated as absent — a present-but-empty
    body can never fall through to FetchedSource (PS3-02)."""
    if value is None:
        return True
    if isinstance(value, dict):
        return all(_is_empty_value(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_is_empty_value(v) for v in value)
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, bytes):
        return not value.strip()
    return False


def _is_empty_payload(payload: ProviderPayload) -> bool:
    if payload is None:
        return True
    if isinstance(payload, dict):
        return not payload
    if isinstance(payload, (str, bytes)):
        return not payload.strip()
    return False


def _text_of(payload: ProviderPayload) -> str:
    """Deterministic text view of a payload for body patterns / the injection
    heuristic: str as-is, bytes decoded lossy, dicts as canonical JSON."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    if isinstance(payload, dict):
        return canonical_json(payload)
    return ""


def _verdict(
    hazard_class: str,
    reason: str,
    detected_by: dict[str, str],
    recordable: bool | None = None,
    scope: str | None = None,
) -> HazardVerdict:
    """Build a HazardVerdict — the single construction point every
    `evaluate_hazards` return flows through.

    GC-01 (fetch-gate): when `scope` is given, the emitted class is checked
    against the scope's CLOSED taxonomy (`_ALLOWED_BY_SCOPE`) — a class
    outside it is a spec/evaluator contract violation (`SpecValidationError`),
    never a verdict the driver must discover. A scope-less call (tests,
    helpers) skips the check.
    """
    if scope is not None:
        allowed = _ALLOWED_BY_SCOPE.get(scope)
        if allowed is None or hazard_class not in allowed:
            raise SpecValidationError(
                f"scope {scope!r} cannot emit hazard class {hazard_class!r} "
                f"(closed taxonomy: {sorted(allowed) if allowed else 'unknown'})",
                hazard_class="SPEC_INVALID")
    if recordable is None:
        recordable = hazard_class in _RECORDABLE_CLASSES
    return HazardVerdict(
        hazard_class=hazard_class,
        reason=reason,
        detected_by=detected_by,
        recordable=recordable,
    )


# ── registration loader + validation (PS2-09 / PS3-05 / HZ-06/09/10/12) ──


def _require_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SpecValidationError(
            f"hazard spec: {key!r} must be a non-empty string",
            provider_id=str(data.get("provider_id", "")),
            hazard_class="SPEC_INVALID",
        )
    return value


def _reject_unknown_keys(data: dict[str, object], allowed: frozenset[str]) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise SpecValidationError(
            f"hazard spec: unknown key(s) {unknown}",
            provider_id=str(data.get("provider_id", "")),
            hazard_class="SPEC_INVALID",
        )


def _validate_path(path: str, provider_id: str, where: str) -> None:
    """Structural field-path validation (HZ-09/HZ2-05): no empty segments,
    leading/trailing dots, whitespace, or a ``"*"``-ROOTED path (the payload
    root is always a dict, so a first-segment wildcard can never resolve — a
    dead spec path must fail registration, not ship silently). ``"."`` (whole
    payload) is allowed. Payload-level validity is unverifiable at
    registration — the golden-fixture corpus is the standing gate for a spec's
    real response shapes."""
    if path == ".":
        return
    if any(ch.isspace() for ch in path):
        raise SpecValidationError(
            f"hazard spec: {where} {path!r} contains whitespace",
            provider_id=provider_id, hazard_class="SPEC_INVALID")
    if path.startswith(".") or path.endswith(".") or ".." in path:
        raise SpecValidationError(
            f"hazard spec: {where} {path!r} has empty segments",
            provider_id=provider_id, hazard_class="SPEC_INVALID")
    if path.split(".")[0] == "*":
        raise SpecValidationError(
            f"hazard spec: {where} {path!r} is *-rooted — the payload root is a "
            f"dict, so it can never resolve (HZ2-05)",
            provider_id=provider_id, hazard_class="SPEC_INVALID")


def _compile(pattern: str, provider_id: str, where: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as exc:  # pragma: no cover — defensive
        raise SpecValidationError(
            f"hazard spec: invalid {where} regex {pattern!r}: {exc}",
            provider_id=provider_id, hazard_class="SPEC_INVALID") from None


def _load_marker(raw: object, provider_id: str) -> HazardMarker:
    if not isinstance(raw, dict):
        raise SpecValidationError("hazard spec: marker must be an object",
                                  provider_id=provider_id, hazard_class="SPEC_INVALID")
    allowed = frozenset({"field_path", "equals", "pattern", "failure_class"})
    _reject_unknown_keys(raw, allowed)
    field_path = _require_str(raw, "field_path")
    _validate_path(field_path, provider_id, "marker field_path")
    failure_class = _require_str(raw, "failure_class")
    if failure_class not in _MARKER_CLASSES:
        raise SpecValidationError(
            f"hazard spec: marker failure_class {failure_class!r} not in "
            f"the marker class set (NONE/TRANSIENT/INJECTION_SUSPECT/CURSOR_TRAP "
            f"are rejected — HZ-12)",
            provider_id=provider_id, hazard_class="SPEC_INVALID")
    equals = raw.get("equals")
    pattern = raw.get("pattern")
    if equals is not None and not isinstance(equals, str):
        raise SpecValidationError("hazard spec: marker equals must be a string or null",
                                  provider_id=provider_id, hazard_class="SPEC_INVALID")
    if pattern is not None and not isinstance(pattern, str):
        raise SpecValidationError("hazard spec: marker pattern must be a string or null",
                                  provider_id=provider_id, hazard_class="SPEC_INVALID")
    if (equals is None) == (pattern is None):
        raise SpecValidationError(
            "hazard spec: marker must declare exactly one of equals/pattern",
            provider_id=provider_id, hazard_class="SPEC_INVALID")
    if pattern is not None:
        _compile(pattern, provider_id, "marker pattern")
    return HazardMarker(field_path=field_path, failure_class=failure_class,
                        equals=equals, pattern=pattern)


def _load_error_field(raw: object, provider_id: str, where: str) -> ErrorFieldSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SpecValidationError(f"hazard spec: {where} must be an object or null",
                                  provider_id=provider_id, hazard_class="SPEC_INVALID")
    name = _require_str(raw, "name")
    _validate_path(name, provider_id, f"{where} name")
    code_pattern = _require_str(raw, "code_pattern")
    _compile(code_pattern, provider_id, f"{where} code_pattern")
    return ErrorFieldSpec(name=name, code_pattern=code_pattern)


def _load_string_list(raw: object, provider_id: str, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(f, str) and f for f in raw):
        raise SpecValidationError(f"hazard spec: {where} must be a list of strings",
                                  provider_id=provider_id, hazard_class="SPEC_INVALID")
    return tuple(raw)


_CONTENT_TYPE_RE = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")


def _load_content_types(raw: object, provider_id: str, where: str) -> tuple[str, ...]:
    """RT-05/RT2-04 — the per-provider media-type allowlist. Fail-closed:
    entries must be well-formed media types (type/subtype, lowercase, no
    wildcards, no parameters) — a "*/*" allowlist would disable the check it
    is supposed to declare (the HZ2-05 *-rooted dead-spec precedent applied
    to labels), and a parameterized entry would silently never match the
    normalized `content_type` the transport reports."""
    values = _load_string_list(raw, provider_id, where)
    out: list[str] = []
    for ct in values:
        if not _CONTENT_TYPE_RE.match(ct):
            raise SpecValidationError(
                f"hazard spec: {where} entry {ct!r} is not a media type "
                f"(type/subtype, no wildcards, no parameters)",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        out.append(ct.lower())
    return tuple(out)


def load_hazard_spec(provider_id: str, data: dict[str, object]) -> ProviderHazardSpec:
    """Validate and load a spec dict (from ``hazard_specs/<provider>.json``).

    Fail-closed registration: every incoherence below raises
    ``SpecValidationError`` — a spec that violates the matrix never ships a
    contradiction the driver must interpret (PS2-09/PS3-05/HZ-06/09/10/12).
    """
    allowed = frozenset({
        "schema", "provider_id", "version", "markers", "empty_body_rule",
        "error_field", "count_semantics", "counts_raw_rows", "required_fields",
        "cursor_rule", "throttle_signature", "rewrite_suspect", "fetch",
        "valid_negative_statuses", "content_types",
    })
    _reject_unknown_keys(data, allowed)
    # HZ-10 — the spec-file format is versioned; a missing/mismatched schema is
    # a registration error, not a silent reinterpretation.
    if data.get("schema") != SPEC_SCHEMA:
        raise SpecValidationError(
            f"hazard spec: schema {data.get('schema')!r} != {SPEC_SCHEMA!r} (HZ-10)",
            provider_id=provider_id, hazard_class="SPEC_INVALID")
    if data.get("provider_id") != provider_id:
        raise SpecValidationError(
            f"hazard spec: provider_id {data.get('provider_id')!r} != requested {provider_id!r}",
            provider_id=provider_id, hazard_class="SPEC_INVALID")
    version = _require_str(data, "version")

    markers_raw = data.get("markers", [])
    if not isinstance(markers_raw, list):
        raise SpecValidationError("hazard spec: markers must be a list",
                                  provider_id=provider_id, hazard_class="SPEC_INVALID")
    markers = tuple(_load_marker(m, provider_id) for m in markers_raw)

    empty_body_rule = data.get("empty_body_rule", "treat-as-failure")
    if empty_body_rule not in ("treat-as-failure", "valid-negative"):
        raise SpecValidationError(
            f"hazard spec: empty_body_rule {empty_body_rule!r} invalid",
            provider_id=provider_id, hazard_class="SPEC_INVALID")

    error_field = _load_error_field(data.get("error_field"), provider_id, "error_field")

    count_semantics = data.get("count_semantics", "exact")
    if count_semantics not in ("exact", "estimate", "absent"):
        raise SpecValidationError(
            f"hazard spec: count_semantics {count_semantics!r} invalid",
            provider_id=provider_id, hazard_class="SPEC_INVALID")
    counts_raw_rows = data.get("counts_raw_rows", False)
    if not isinstance(counts_raw_rows, bool):
        raise SpecValidationError("hazard spec: counts_raw_rows must be a boolean",
                                  provider_id=provider_id, hazard_class="SPEC_INVALID")
    # PS2-09 count-semantics × counts_raw_rows matrix.
    if count_semantics == "estimate" and not counts_raw_rows:
        raise SpecValidationError(
            "hazard spec: count_semantics 'estimate' requires counts_raw_rows: true "
            "(an estimate that is dedup-truthful is just 'exact')",
            provider_id=provider_id, hazard_class="SPEC_INVALID")
    if count_semantics == "absent" and counts_raw_rows:
        raise SpecValidationError(
            "hazard spec: count_semantics 'absent' forbids counts_raw_rows: true (moot)",
            provider_id=provider_id, hazard_class="SPEC_INVALID")

    required_raw = data.get("required_fields", [])
    required_fields = _load_string_list(required_raw, provider_id, "required_fields")
    for field_name in required_fields:
        _validate_path(field_name, provider_id, "required_fields entry")

    cursor_raw = data.get("cursor_rule", {"kind": "cursor", "loop_guard": 100})
    if not isinstance(cursor_raw, dict):
        raise SpecValidationError("hazard spec: cursor_rule must be an object",
                                  provider_id=provider_id, hazard_class="SPEC_INVALID")
    cursor_kind = cursor_raw.get("kind", "cursor")
    if cursor_kind not in ("cursor", "offset", "none"):
        raise SpecValidationError(f"hazard spec: cursor_rule.kind {cursor_kind!r} invalid",
                                  provider_id=provider_id, hazard_class="SPEC_INVALID")
    loop_guard = cursor_raw.get("loop_guard", 100)
    if not isinstance(loop_guard, int) or isinstance(loop_guard, bool) \
            or not 1 <= loop_guard <= _MAX_LOOP_GUARD:
        raise SpecValidationError(
            f"hazard spec: cursor_rule.loop_guard must be an int in 1..{_MAX_LOOP_GUARD} (HZ-06)",
            provider_id=provider_id, hazard_class="SPEC_INVALID")
    cursor_rule = CursorRule(kind=cursor_kind, loop_guard=loop_guard)

    throttle_raw = data.get("throttle_signature", [])
    if not isinstance(throttle_raw, list):
        raise SpecValidationError("hazard spec: throttle_signature must be a list",
                                  provider_id=provider_id, hazard_class="SPEC_INVALID")
    throttle_sigs: list[ThrottleSig] = []
    for item in throttle_raw:
        if not isinstance(item, dict):
            raise SpecValidationError("hazard spec: throttle entry must be an object",
                                      provider_id=provider_id, hazard_class="SPEC_INVALID")
        status = item.get("status")
        body_pattern = item.get("body_pattern")
        fields_raw = item.get("fields", [])
        if status is not None and (not isinstance(status, int) or isinstance(status, bool)
                                   or not 400 <= status <= 499):
            # HZ-06: a throttle is a client-visible 4xx; 5xx is TRANSIENT before
            # step 2, 429 is step 1's own branch, 2xx is not a throttle status.
            raise SpecValidationError(
                "hazard spec: throttle status must be an int in 400..499 or null (HZ-06)",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        if body_pattern is not None and not isinstance(body_pattern, str):
            raise SpecValidationError("hazard spec: throttle body_pattern must be a string or null",
                                      provider_id=provider_id, hazard_class="SPEC_INVALID")
        fields = _load_string_list(fields_raw, provider_id, "throttle fields")
        for f in fields:
            _validate_path(f, provider_id, "throttle fields entry")
        if status is None and body_pattern is None:
            raise SpecValidationError(
                "hazard spec: throttle signature must declare status and/or body_pattern",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        if fields and body_pattern is None:
            raise SpecValidationError(
                "hazard spec: throttle fields require a body_pattern (dead content)",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        if body_pattern is not None:
            _compile(body_pattern, provider_id, "throttle body_pattern")
        throttle_sigs.append(ThrottleSig(status=status, body_pattern=body_pattern,
                                         fields=fields))

    rewrite_raw = data.get("rewrite_suspect", [])
    if not isinstance(rewrite_raw, list):
        raise SpecValidationError("hazard spec: rewrite_suspect must be a list",
                                  provider_id=provider_id, hazard_class="SPEC_INVALID")
    rewrite_rules: list[RewriteRule] = []
    for item in rewrite_raw:
        if not isinstance(item, dict):
            raise SpecValidationError("hazard spec: rewrite rule must be an object",
                                      provider_id=provider_id, hazard_class="SPEC_INVALID")
        request_param = _require_str(item, "request_param")
        records_path = _require_str(item, "records_path")
        record_field = _require_str(item, "record_field")
        _validate_path(records_path, provider_id, "rewrite records_path")
        _validate_path(record_field, provider_id, "rewrite record_field")
        filter_contains = item.get("filter_contains")
        if filter_contains is not None and not isinstance(filter_contains, str):
            raise SpecValidationError("hazard spec: rewrite filter_contains must be a string or null",
                                      provider_id=provider_id, hazard_class="SPEC_INVALID")
        rewrite_rules.append(RewriteRule(
            request_param=request_param, records_path=records_path,
            record_field=record_field, filter_contains=filter_contains))

    fetch_raw = data.get("fetch")
    fetch: FetchHazardRules | None = None
    if fetch_raw is not None:
        if not isinstance(fetch_raw, dict):
            raise SpecValidationError("hazard spec: fetch must be an object or null",
                                      provider_id=provider_id, hazard_class="SPEC_INVALID")
        fetch_allowed = frozenset({
            "body_marker", "metadata_marker", "body_required", "empty_body_rule",
            "no_full_text_status", "no_full_text_marker", "retraction_marker",
            "retraction_pattern", "error_field", "required_fields",
        })
        _reject_unknown_keys(fetch_raw, fetch_allowed)

        def _opt_marker(key: str) -> str | None:
            value = fetch_raw.get(key)
            if value is not None and not isinstance(value, str):
                raise SpecValidationError(
                    f"hazard spec: fetch.{key} must be a string or null",
                    provider_id=provider_id, hazard_class="SPEC_INVALID")
            if value is not None:
                _validate_path(value, provider_id, f"fetch.{key}")
            return value

        body_marker = _opt_marker("body_marker")
        metadata_marker = _opt_marker("metadata_marker")
        body_required = fetch_raw.get("body_required", False)
        if not isinstance(body_required, bool):
            raise SpecValidationError("hazard spec: fetch.body_required must be a boolean",
                                      provider_id=provider_id, hazard_class="SPEC_INVALID")
        empty_rule = fetch_raw.get("empty_body_rule", "treat-as-failure")
        if empty_rule != "treat-as-failure":
            raise SpecValidationError(
                "hazard spec: fetch.empty_body_rule must be 'treat-as-failure' "
                "(a fetch empty body is never a valid negative, PS3-02)",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        no_full_text_status = fetch_raw.get("no_full_text_status")
        if no_full_text_status is not None and (
                not isinstance(no_full_text_status, int)
                or isinstance(no_full_text_status, bool)
                or not 400 <= no_full_text_status <= 499
                or no_full_text_status == 429):
            # HZ-03/06: a no-full-text signal is a 4xx answer (404/410/…); 429
            # is a throttle, 5xx is transient — both are never "no full text".
            raise SpecValidationError(
                "hazard spec: fetch.no_full_text_status must be an int in 400..499 "
                "excluding 429, or null (HZ-03/06)",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        no_full_text_marker = _opt_marker("no_full_text_marker")
        retraction_marker = _opt_marker("retraction_marker")
        retraction_pattern = fetch_raw.get("retraction_pattern")
        if retraction_pattern is not None and not isinstance(retraction_pattern, str):
            raise SpecValidationError(
                "hazard spec: fetch.retraction_pattern must be a string or null",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        if retraction_pattern is not None:
            _compile(retraction_pattern, provider_id, "fetch.retraction_pattern")
        # HZ-02 (c2) — value semantics: marker and pattern travel together.
        if (retraction_marker is None) != (retraction_pattern is None):
            raise SpecValidationError(
                "hazard spec: fetch.retraction_marker and fetch.retraction_pattern "
                "must be declared together (value semantics, HZ-02)",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        fetch_error_field = _load_error_field(fetch_raw.get("error_field"),
                                              provider_id, "fetch.error_field")
        fetch_required = _load_string_list(fetch_raw.get("required_fields", []),
                                           provider_id, "fetch.required_fields")
        for f in fetch_required:
            _validate_path(f, provider_id, "fetch.required_fields entry")
        # PS3-05 coherence — (a) body_required needs a body marker.
        if body_required and body_marker is None:
            raise SpecValidationError(
                "hazard spec: fetch.body_required requires fetch.body_marker (PS3-05a)",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        # FS-05 — a declared body_marker means the body matters: the
        # unconditional fall-through (PS3-02) turns an absent body into
        # EMPTY_RESULT regardless of body_required, so body_required:false with
        # a body marker would advertise "body not required" while enforcing it.
        if not body_required and body_marker is not None:
            raise SpecValidationError(
                "hazard spec: fetch.body_marker requires fetch.body_required — the "
                "fall-through enforces body presence either way, so "
                "body_required:false is incoherent with a body marker (FS-05)",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        # FS-06 — body_required's ONLY effect is the composite, which needs a
        # metadata marker to fire; without one the rule is dead content.
        if body_required and metadata_marker is None:
            raise SpecValidationError(
                "hazard spec: fetch.body_required requires fetch.metadata_marker — "
                "the composite needs both sides to fire (FS-06)",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        # (c) no_full_text_marker needs no_full_text_status.
        if no_full_text_marker is not None and no_full_text_status is None:
            raise SpecValidationError(
                "hazard spec: fetch.no_full_text_marker requires fetch.no_full_text_status "
                "(PS3-05c)",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        # (d) a fetch rule set that can never fire fails registration.
        if (not body_required and no_full_text_status is None and not fetch_required
                and fetch_error_field is None and retraction_marker is None):
            raise SpecValidationError(
                "hazard spec: fetch rule set can never fire — needs body_required, "
                "no_full_text_status, required_fields, error_field, or "
                "retraction_marker (PS3-05d)",
                provider_id=provider_id, hazard_class="SPEC_INVALID")
        fetch = FetchHazardRules(
            body_marker=body_marker, metadata_marker=metadata_marker,
            body_required=body_required, empty_body_rule=empty_rule,
            no_full_text_status=no_full_text_status,
            no_full_text_marker=no_full_text_marker,
            retraction_marker=retraction_marker,
            retraction_pattern=retraction_pattern,
            error_field=fetch_error_field, required_fields=fetch_required)

    valid_negative_raw = data.get("valid_negative_statuses", [404])
    if not isinstance(valid_negative_raw, list) or not all(
            isinstance(s, int) and not isinstance(s, bool)
            and s in _VALID_NEGATIVE_STATUSES for s in valid_negative_raw):
        # HZ2-04: only the not-found family (404/410/451) can be valid
        # negatives. Auth failures (401/403), client errors, and throttles are
        # never an "answered no" — a task must never conclude "no literature"
        # from "we were forbidden". 429 stays a throttle, 5xx stays transient.
        raise SpecValidationError(
            "hazard spec: valid_negative_statuses must be a subset of the "
            f"not-found family {sorted(_VALID_NEGATIVE_STATUSES)} (HZ2-04)",
            provider_id=provider_id, hazard_class="SPEC_INVALID")
    valid_negative_statuses = tuple(valid_negative_raw)
    # HZ-06 — the empty-body "answered no" rule and "no status is a valid
    # negative" contradict each other.
    if empty_body_rule == "valid-negative" and not valid_negative_statuses:
        raise SpecValidationError(
            "hazard spec: empty_body_rule 'valid-negative' requires a non-empty "
            "valid_negative_statuses (HZ-06)",
            provider_id=provider_id, hazard_class="SPEC_INVALID")

    content_types = _load_content_types(data.get("content_types", []),
                                        provider_id, "content_types")

    return ProviderHazardSpec(
        provider_id=provider_id, version=version, markers=markers,
        empty_body_rule=empty_body_rule, error_field=error_field,
        count_semantics=count_semantics, counts_raw_rows=counts_raw_rows,
        required_fields=required_fields, cursor_rule=cursor_rule,
        throttle_signature=tuple(throttle_sigs), rewrite_suspect=tuple(rewrite_rules),
        fetch=fetch, valid_negative_statuses=valid_negative_statuses,
        content_types=content_types,
    )


# ── the one evaluator ──


def _marker_matches(marker: HazardMarker, payload: ProviderPayload) -> bool:
    if marker.pattern is not None:
        values = resolve_field_path(payload, marker.field_path)
        if not values:
            return False
        return any(re.search(marker.pattern, str(v)) is not None for v in values)
    values = resolve_field_path(payload, marker.field_path)
    # HZ-07 — equals compares the whitespace-stripped resolved value so a
    # padded provider value cannot silently miss the marker.
    return any(str(v).strip() == marker.equals for v in values)


def _payload_as_dict(payload: ProviderPayload) -> dict[str, object] | None:
    """The dict view of a payload, or None when it is not JSON-shaped.

    HZ2-01 — bytes are the realistic transport form, so a bytes payload is
    decoded and parsed: JSON bytes become the dict (field-scoped matching
    applies), non-JSON bytes stay plain text (whole-body matching applies).
    Undecodable or unparseable bytes are not a throttle body — None.
    """
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        try:
            decoded = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
        try:
            parsed = json.loads(decoded)
        except ValueError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _throttle_matches(
    sig: ThrottleSig,
    status: int,
    payload: ProviderPayload,
    text: str,
) -> bool:
    if sig.status is not None and status == sig.status:
        return True
    if sig.body_pattern is None:
        return False
    dict_view = _payload_as_dict(payload)
    if dict_view is not None:
        # HZ-01/HZ2-01/HZ2-02 — JSON-shaped content is searched ONLY via the
        # declared error fields, and only their str LEAF values (a container
        # repr is never an error-message match). A plain-text signature with
        # empty fields does not fire on JSON content.
        if not sig.fields:
            return False
        return any(
            re.search(sig.body_pattern, value) is not None
            for field_name in sig.fields
            for value in resolve_field_path(dict_view, field_name)
            if isinstance(value, str)
        )
    # Plain-text payloads (str, or bytes that did not parse as JSON): whole-
    # body matching ONLY when no fields are declared (HZ2-01 — a fields-
    # scoped signature never falls to the whole-body branch, so a fields-
    # declared spec is never a silent whole-body search).
    if sig.fields:
        return False
    return re.search(sig.body_pattern, text) is not None


def _records_from(payload: ProviderPayload, records_path: str) -> list[dict[str, object]]:
    """Flatten the record candidates at ``records_path`` for rewrite rules:
    a resolved list value → its elements; a resolved dict → one record."""
    records: list[dict[str, object]] = []
    for value in resolve_field_path(payload, records_path):
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    records.append(item)
        elif isinstance(value, dict):
            records.append(value)
    return records


def _retraction_marker_hit(fetch_rules: FetchHazardRules, payload: ProviderPayload) -> str | None:
    """HZ-02 value semantics: the retraction marker path when ANY resolved str
    LEAF value matches the retraction pattern, else None. Bare presence is
    never the signal (presence-only mislabeled normal pub-history as
    retracted); a container value is never matched (HZ2-03 — matching a
    container repr would flag a normal paper whose body text merely mentions
    "retracted")."""
    if fetch_rules.retraction_marker is None or fetch_rules.retraction_pattern is None:
        return None
    for value in resolve_field_path(payload, fetch_rules.retraction_marker):
        if isinstance(value, str) and re.search(
                fetch_rules.retraction_pattern, value, re.IGNORECASE):
            return fetch_rules.retraction_marker
    return None


def _no_full_text_marker_evidence(fetch_rules: FetchHazardRules, payload: ProviderPayload) -> bool:
    """HZ-05: ANY resolved value counts as marker evidence (search-marker
    semantics) — the first-value-only form silently missed wildcard paths with
    an empty leading element."""
    if fetch_rules.no_full_text_marker is None:
        return False
    return any(
        not _is_empty_value(value)
        for value in resolve_field_path(payload, fetch_rules.no_full_text_marker)
    )


def _label_and_size_check(
    spec: ProviderHazardSpec,
    context: HazardContext,
    base_evidence: dict[str, str],
) -> HazardVerdict | None:
    # GC-01 — the scope-closure guard lives in `_verdict`; this helper threads
    # the context's scope so its verdicts are validated too.
    def _v(hazard_class: str, reason: str, detected_by: dict[str, str],
           recordable: bool | None = None) -> HazardVerdict:
        return _verdict(hazard_class, reason, detected_by, recordable,
                        scope=context.scope)

    """RT2-04/RT3-01/RT3-04 — the content-type + completed-body size checks
    at the PINNED slot: AFTER the status verdicts (status evidence dominates
    — a 429/404 with a mismatched label keeps its status verdict, the
    FS-03/04 principle), the drift sentinel, and the empty-body rule; at
    fetch scope additionally AFTER the retraction/NO_FULL_TEXT evidence (a
    retracted article with an unexpected content-type stays
    REMOVED_OR_RETRACTED, never MALFORMED_200) and BEFORE the body
    composites. Only a 200-with-parseable-body reaches the slot, so a
    mismatched label or an oversized completed body is shape evidence, never
    a status pre-emption.

    - Content-type: a declared allowlist + a concrete mismatch →
      MALFORMED_200 (permanent); without an allowlist, or with no
      content_type reported, the check is skipped — the required-fields
      drift sentinel stays the shape-aware backstop (RT-05/RT2-04).
    - Completed-body size: the task's declared `size_cap_bytes` vs the body
      length the driver carried in — an oversized COMPLETE 2xx body →
      PARTIAL_CONTENT (RT3-01 (b)); the transport's streaming abort is the
      separate status-conditional hard cap (RT3-01 (a)).
    """
    if (context.content_type is not None and spec.content_types
            and context.content_type not in spec.content_types):
            return _v(
                "MALFORMED_200",
                f"content-type {context.content_type!r} not in the declared "
                f"allowlist {sorted(spec.content_types)}",
                {**base_evidence, "content_type": context.content_type})
    if (context.body_size is not None and context.size_cap_bytes is not None
            and context.body_size > context.size_cap_bytes):
        return _v(
            "PARTIAL_CONTENT",
            f"completed body {context.body_size} bytes exceeds the task size "
            f"cap {context.size_cap_bytes}",
            {**base_evidence,
             "body_size": str(context.body_size),
             "size_cap_bytes": str(context.size_cap_bytes)})
    return None


def evaluate_hazards(
    provider: str,
    spec: ProviderHazardSpec,
    payload: ProviderPayload,
    context: HazardContext,
) -> HazardVerdict:
    """The ONE deterministic, generic evaluator (blueprint §4.2).

    Reads the spec; contains zero per-provider branches. Returns a
    ``HazardVerdict`` the walk/fetch drivers act on — THROTTLED/TRANSIENT →
    transient backoff; MALFORMED_200/EMPTY_RESULT/PARTIAL_CONTENT/
    REWRITE_SUSPECT → permanent typed failure; VALID_NEGATIVE/NO_FULL_TEXT →
    results; INJECTION_SUSPECT → advisory flag; NONE → parse.
    """
    if provider != spec.provider_id:
        raise SpecValidationError(
            f"hazard spec: provider_id {spec.provider_id!r} != caller {provider!r}",
            provider_id=provider, hazard_class="SPEC_INVALID")
    if context.scope not in ("SEARCH", "FETCH"):
        raise ValueError(f"evaluate_hazards: invalid scope {context.scope!r}")

    # GC-01 (fetch-gate) — the scope-closure guard lives in `_verdict` (the
    # single verdict-construction helper; every return path flows through it).
    # This local alias threads the scope so the emitted class is validated
    # against the scope's CLOSED taxonomy on every return.
    def _v(hazard_class: str, reason: str, detected_by: dict[str, str],
           recordable: bool | None = None) -> HazardVerdict:
        return _verdict(hazard_class, reason, detected_by, recordable,
                        scope=context.scope)
    # HZ2-01 — bytes are the realistic transport form (the walk evaluates
    # hazards on the raw payload BEFORE parse_page). Decode + parse ONCE at
    # entry so EVERY step — throttle fields, markers, required-fields drift,
    # fetch composites — sees the JSON dict or the plain text, never a bytes
    # blob: a fields-scoped signature can never silently search whole-body
    # bytes, and required-fields drift can never misfire on an undecoded
    # payload.
    if isinstance(payload, bytes):
        payload = _payload_as_dict(payload) or payload.decode("utf-8", errors="replace")
    status = context.status_code
    base_evidence = {"spec_version": spec.version, "status_code": str(status)}
    if context.endpoint:  # HZ-11 — the endpoint joins the evidence basis
        base_evidence["endpoint"] = context.endpoint
    fetch_scope = context.scope == "FETCH"

    # ── step 1: status check ──
    deferred_status = False
    pending_valid_negative = False
    unclassified_4xx = False
    if not 200 <= status < 300:
        if (fetch_scope and spec.fetch is not None
                and spec.fetch.no_full_text_status is not None
                and status == spec.fetch.no_full_text_status):
            # PS3-01 generalized (HZ-03): ANY declared no-full-text status is
            # deferred — never VALID_NEGATIVE, never a plain 4xx at fetch
            # scope. (Registration restricts the status to 4xx-except-429, so
            # this cannot swallow a throttle or a transient.)
            deferred_status = True
        elif not fetch_scope and status in spec.valid_negative_statuses:
            # Decided AFTER step 2 (HZ-08) — a throttle signature on the body
            # wins over the status-alone "answered no".
            pending_valid_negative = True
        elif status == 429:
            return _v("THROTTLED", f"HTTP {status} rate limit", base_evidence)
        elif 500 <= status < 600:
            return _v("TRANSIENT", f"HTTP {status} transient server error", base_evidence)
        else:
            # Any other non-2xx (400/401/403/404-not-declared/451…, 1xx) is
            # deferred to step 2 — a throttle signature may declare a non-429
            # status (CORE token-exhausted 403). Still unclassified → the
            # contract's permanent "HTTP 4xx validation" path (contract §6.3);
            # no dedicated class literal exists, so MALFORMED_200 is the
            # permanent failure class with the status in reason/detected_by.
            unclassified_4xx = True

    # ── step 2: throttle signature ──
    text = _text_of(payload)
    for sig in spec.throttle_signature:
        if _throttle_matches(sig, status, payload, text):
            return _v(
                "THROTTLED",
                f"throttle signature matched (status={sig.status}, "
                f"body_pattern={sig.body_pattern!r})",
                base_evidence)

    # Decided after step 2 — throttle evidence beats status-alone "answered no".
    if pending_valid_negative:
        return _v(
            "VALID_NEGATIVE",
            f"HTTP {status} on an identifier lookup (valid negative per spec)",
            base_evidence)

    # Unclassified non-2xx with no throttle signature → permanent (never
    # retried). The label is honest for every status class, including 1xx
    # (HZ-08 — a 1xx is not a 4xx, but it is never a final response either).
    if unclassified_4xx:
        return _v(
            "MALFORMED_200",
            f"HTTP {status} (unclassified non-2xx — permanent validation failure)",
            base_evidence)

    # ── PS3-01/HZ-03 deferred no-full-text status: the spec DECLARED this
    #    status means "no accessible full text"; the retraction marker refines
    #    the kind, never the outcome.
    if deferred_status:
        retraction_path = _retraction_marker_hit(spec.fetch, payload) \
            if spec.fetch is not None else None
        detected = {**base_evidence,
                    "no_full_text_kind": ("REMOVED_OR_RETRACTED"
                                          if retraction_path else "NOT_OA")}
        if retraction_path:
            detected["marker_path"] = retraction_path
        return _v(
            "NO_FULL_TEXT",
            f"no accessible full text (status={status}, declared by spec)",
            detected,
            recordable=False)

    # ── steps 3/4 short-circuit: an empty payload is the EMPTY case, never a
    #    drift case (contract: empty <PubmedArticleSet/> → EMPTY_RESULT). At
    #    fetch scope the rule is always treat-as-failure (PS3-02).
    if _is_empty_payload(payload):
        effective_empty_rule = "treat-as-failure" if fetch_scope else spec.empty_body_rule
        if effective_empty_rule == "valid-negative":
            return _v(
                "VALID_NEGATIVE",
                "empty body declared a valid negative by spec.empty_body_rule",
                base_evidence)
        return _v("EMPTY_RESULT", "empty response body", base_evidence)

    # ── steps 3/3a/5 are SEARCH-shape: error field, markers (first hit wins
    #    in spec order), required-fields drift, rewrite rules. They do NOT
    #    apply to fetch payloads (blueprint §4.1 — the search-shaped fields are
    #    meaningless for a JATS full-text response; the fetch rules carry their
    #    own error_field and drift sentinel, HZ-04).
    if not fetch_scope:
        if spec.error_field is not None:
            # FS-02 (completing the HZ-05 unification): ANY str leaf value is
            # evidence — a list-shaped error path with a benign leading value
            # can no longer hide a real error code behind values[0].
            values = [v for v in resolve_field_path(payload, spec.error_field.name)
                      if isinstance(v, str)
                      and re.search(spec.error_field.code_pattern, v)]
            if values:
                code = values[0]
                return _v(
                    "MALFORMED_200",
                    f"provider error field {spec.error_field.name} = {code!r} in HTTP 200",
                    {**base_evidence, "error_field": spec.error_field.name, "code": code})
        for marker in spec.markers:
            if _marker_matches(marker, payload):
                return _v(
                    marker.failure_class,
                    f"hazard marker {marker.field_path!r} matched",
                    {**base_evidence, "marker_path": marker.field_path})

        # ── step 3a: required fields (PS-08 schema-drift sentinel) ──
        for field_name in spec.required_fields:
            if not resolve_field_path(payload, field_name):
                return _v(
                    "MALFORMED_200",
                    f"required field {field_name!r} absent from payload (schema drift)",
                    {**base_evidence, "missing_field": field_name})

        # ── step 5: rewrite rules (silent-filter detection) ──
        for rule in spec.rewrite_suspect:
            declared = context.request_params.get(rule.request_param)
            if declared is None:
                continue
            if rule.filter_contains is not None and rule.filter_contains not in declared:
                continue
            records = _records_from(payload, rule.records_path)
            if not records:
                continue
            violating = [
                r for r in records
                if not resolve_field_path(r, rule.record_field)
                or _is_empty_value(resolve_field_path(r, rule.record_field)[0])
            ]
            if violating:
                return _v(
                    "REWRITE_SUSPECT",
                    f"declared {rule.request_param}={declared!r} but {len(violating)} of "
                    f"{len(records)} records lack {rule.record_field!r} (silent rewrite)",
                    {**base_evidence,
                     "request_param": rule.request_param,
                     "expected": str(len(records)),
                     "got": str(len(violating)),
                     "missing_field": rule.record_field})

        # ── step 5b (SEARCH slot): the label + completed-body size checks ──
        # RT2-04/RT3-01/RT3-04 — the pinned slot: after the status verdicts,
        # the drift sentinel (3a), and the empty-body rule (4); before the
        # advisory injection heuristic. Only a 200-with-parseable-body reaches
        # it, so a mismatched label / oversized body is shape evidence, never
        # a status pre-emption.
        label = _label_and_size_check(spec, context, base_evidence)
        if label is not None:
            return label

    # ── step 6: injection heuristic (advisory flag only — never a block) ──
    lowered = text.lower()
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            return _v(
                "INJECTION_SUSPECT",
                f"instruction-like text matched {pattern!r} (advisory flag)",
                {**base_evidence, "pattern": pattern},
                recordable=False)

    # ── step 6a: fetch scope (PS2-02/PS3-01/PS3-02/PS3-03/PS3-08, HZ-02/04/05,
    #    FS-02/03/04/08) ──
    if fetch_scope and spec.fetch is not None:
        fetch_rules = spec.fetch
        # ERROR evidence first (FS-03/04 — the PS3-08 dominance principle): an
        # error-shaped 200 must be MALFORMED_200, never a RESULT class. A fetch
        # error field (HZ-04) or required-fields drift beats retraction and
        # no_full_text evidence, which could otherwise mask an error response
        # as a benign "no full text" result.
        if fetch_rules.error_field is not None:
            # FS-02 — ANY str leaf value is evidence (the HZ-05 unification):
            # an error code behind a leading benign value in a list-shaped
            # payload can no longer be silently accepted as full text.
            values = [v for v in resolve_field_path(payload, fetch_rules.error_field.name)
                      if isinstance(v, str)
                      and re.search(fetch_rules.error_field.code_pattern, v)]
            if values:
                code = values[0]
                return _v(
                    "MALFORMED_200",
                    f"fetch error field {fetch_rules.error_field.name} = {code!r} in HTTP 200",
                    {**base_evidence,
                     "error_field": fetch_rules.error_field.name, "code": code})
        # Fetch required-fields drift — MALFORMED_200 DOMINATES PARTIAL_CONTENT
        # when both would fire (PS3-08).
        for field_name in fetch_rules.required_fields:
            if not resolve_field_path(payload, field_name):
                return _v(
                    "MALFORMED_200",
                    f"fetch required field {field_name!r} absent (schema drift)",
                    {**base_evidence, "missing_field": field_name})
        # Retraction — value semantics, any-value (HZ-02/HZ-05): never NOT_OA.
        retraction_path = _retraction_marker_hit(fetch_rules, payload)
        if retraction_path is not None:
            return _v(
                "NO_FULL_TEXT",
                f"retraction marker {retraction_path!r} matched the retraction pattern",
                {**base_evidence,
                 "marker_path": retraction_path,
                 "no_full_text_kind": "REMOVED_OR_RETRACTED"},
                recordable=False)
        # no_full_text: marker evidence wins over status alone (PS3-08); ANY
        # resolved value counts (HZ-05).
        marker_evidence = _no_full_text_marker_evidence(fetch_rules, payload)
        if marker_evidence or (
                fetch_rules.no_full_text_status is not None
                and status == fetch_rules.no_full_text_status):
            detected = {**base_evidence, "no_full_text_kind": "NOT_OA"}
            if marker_evidence:
                detected["marker_path"] = fetch_rules.no_full_text_marker or ""
            return _v(
                "NO_FULL_TEXT",
                f"no accessible full text (status={status}, "
                f"marker={fetch_rules.no_full_text_marker!r})",
                detected,
                recordable=False)
        # ── FETCH slot: the label + completed-body size checks ──
        # RT2-04/RT3-01/RT3-04 — pinned AFTER the error evidence, the drift
        # sentinel, and the retraction/NO_FULL_TEXT content evidence (a
        # retracted article with an unexpected content-type stays
        # REMOVED_OR_RETRACTED, never MALFORMED_200), BEFORE the body
        # composites below.
        label = _label_and_size_check(spec, context, base_evidence)
        if label is not None:
            return label
        # Body composite — metadata present AND body absent-or-empty (PS3-02).
        # FS-08 — presence follows the HZ-05 any-value discipline: any resolved
        # value that is recursively non-empty counts, so a leading empty element
        # in a list-shaped metadata/body path cannot flip the classification.
        if fetch_rules.body_required and fetch_rules.metadata_marker is not None:
            metadata = resolve_field_path(payload, fetch_rules.metadata_marker)
            metadata_present = any(not _is_empty_value(v) for v in metadata)
            body = resolve_field_path(payload, fetch_rules.body_marker) \
                if fetch_rules.body_marker is not None else ()
            body_absent = not body or all(_is_empty_value(v) for v in body)
            if metadata_present and body_absent:
                return _v(
                    "PARTIAL_CONTENT",
                    f"metadata present but body absent-or-empty "
                    f"(composite {fetch_rules.metadata_marker!r} / "
                    f"{fetch_rules.body_marker!r})",
                    {**base_evidence,
                     "metadata_marker": fetch_rules.metadata_marker or "",
                     "body_marker": fetch_rules.body_marker or ""})
        # A fetch response with no body content and no matching verdict →
        # EMPTY_RESULT, never a fall-through to FetchedSource (PS3-02). Only
        # meaningful when the provider DECLARES a body_marker (PMC); a spec
        # without one (europepmc — its no-full-text detection is status-based)
        # delegates body semantics to the adapter's parse. The zero-byte case
        # is still caught for every provider by step 4 above. FS-01 — recursive
        # emptiness: a body whose leaves are ALL empty ({"sec": ""}) is absent.
        if fetch_rules.body_marker is not None:
            body = resolve_field_path(payload, fetch_rules.body_marker)
            if not body or all(_is_empty_value(v) for v in body):
                return _v(
                    "EMPTY_RESULT",
                    "fetch response has no body content and no matching verdict (PS3-02)",
                    base_evidence)
    elif fetch_scope:
        # F8 (fetch-gate) — `fetch: null` (arxiv/openalex) means no DECLARED
        # provider-specific fetch-hazard knowledge, never a suspension of the
        # generic fetch safety controls: the label + completed-body size check
        # still runs (an oversized fetch body is PARTIAL_CONTENT; a mismatched
        # content-type, when declared, is MALFORMED_200). The declared-block
        # evidence above (error/drift/retraction/no_full_text) simply has no
        # spec to consult.
        label = _label_and_size_check(spec, context, base_evidence)
        if label is not None:
            return label

    return _v("NONE", "no hazard detected", base_evidence, recordable=False)
