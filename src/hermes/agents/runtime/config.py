"""Profile configuration — data, not classes (ARCHITECTURE_DELTA §2.3).

One runtime, six configurations
-------------------------------
`§2.3` requires the Runtime plane to expose `run(profile, task_context)`, and the
classification table (§5) types a new agent profile as "`AgentProfile`-typed;
Intent proposals only; no persistence import". That makes a profile a *record of
declared authority* — the thing the runtime reads — and not a subclass. This
module is therefore the whole of "profiles": a closed schema, a fail-closed
validator, and the loader. No profile name appears in executable code anywhere
in this package (`run.py` looks the spec up by name; the suite proves no class
or function is named after a profile).

Why a YAML *subset* parser lives here
-------------------------------------
The brief requires `profiles/*.yaml`. The minimal-core policy forbids adding a
dependency (`README.md:27`, core dependency list `[]`), and the interpreter that
runs this plane does not ship PyYAML. So the profiles are read by a small,
**deterministic, stdlib-only** parser for the subset the configuration format
uses:

* block mappings (`key: value`, nested by indentation of spaces);
* block sequences of scalars (`- EVIDENCE_TRANSITION`);
* inline lists of scalars (`[a, b]`);
* quoted and plain scalars, `true`/`false`, integers and floats, `null`/`~`.

Anything outside that subset is **refused**, never guessed: anchors and aliases
(`&`/`*`), explicit tags (`!!`), flow mappings (`{...}`), block scalars (`|`,
`>`), multi-document markers, tabs, duplicate keys, sequence items that are
mappings, and any indentation the block structure cannot resolve. A refusal names
the file and line — a config that cannot be read is a startup failure, not a
runtime surprise.

Comment stripping is quote-aware (`#` inside a quoted scalar is content), because
the alternative — a comment rule that eats part of a value — is exactly the kind
of silent config drift this format must not have.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from hermes.core.intents import IntentKind
from hermes.core.node import AgentProfile

#: Where the configurations live. `profiles/` sits inside the package so the
#: wheel carries them with the code (there is no separate install step).
PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
PROFILE_SUFFIX = ".yaml"

#: The output-contract name every profile declares. It is the *runtime's* own
#: schema name (models/router.py owns contracts; this plane only names one).
DEFAULT_CONTRACT = "runtime_proposal_v1"

#: Declared termination policies (§2.3 `termination` config). Every one of them
#: has a handler in the loop: `review_complete` stops the run once it has a
#: proposal set for its declared review to consider, so a profile that declares it
#: without `review.required` is incoherent and refused at load (fail closed).
STOP_WHEN_POLICIES: tuple[str, ...] = (
    "proposals_raised",
    "no_proposals",
    "converged",
    "review_complete",
)

_TOP_LEVEL_KEYS = frozenset({
    "version", "name", "role", "agent_profile", "model_policy", "tools",
    "authority", "schemas", "termination", "review",
})
_MODEL_POLICY_KEYS = frozenset({
    "tier", "contract", "kind_field", "rationale_field", "structured_fields",
    "allows_tool_calls", "max_output_tokens", "options",
})
_AUTHORITY_KEYS = frozenset({
    "proposable_kinds", "director_only", "allowed_capabilities",
    "requires_human_for",
})
_TERMINATION_KEYS = frozenset({
    "max_ticks", "max_proposals", "stop_when", "max_model_calls_per_tick",
    "max_tool_calls", "deadline_seconds",
})
_REVIEW_KEYS = frozenset({"reviewer_profile", "required", "max_review_rounds"})

_TRUE = ("true", "True")
_FALSE = ("false", "False")
_NULL = ("null", "~", "")
_INT = re.compile(r"[+-]?\d+")
_FLOAT = re.compile(r"[+-]?\d+\.\d+")
_UNSUPPORTED_PREFIXES = ("&", "*", "|", ">", "{", "}", "!", "%", "@", "`")


class ProfileConfigError(ValueError):
    """A profile configuration is unreadable or incoherent — fail closed.

    Configuration is *declared authority*, so an incoherent declaration must not
    start a run: a profile that could propose an internal-only intent, or name a
    capability it never declared, is a hole in the declaration itself.
    """


# ═══════════════════════ the YAML subset ═══════════════════════


def _strip_comment(raw: str) -> str:
    """Remove a trailing comment, quote-aware."""
    quote = ""
    for index, char in enumerate(raw):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            continue
        if char == "#" and (index == 0 or raw[index - 1] in " \t"):
            return raw[:index].rstrip()
    return raw.rstrip()


def parse_profile_yaml(text: str, *, source: str = "<profile>") -> dict[str, Any]:
    """Parse the profile YAML subset into plain Python data.

    Deterministic and total: either the document is inside the subset and parses,
    or it raises `ProfileConfigError` naming the line. There is no permissive
    fallback and no partial parse.
    """
    lines: list[tuple[int, str, int]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw:
            raise ProfileConfigError(
                f"{source}:{number}: tabs are not supported (indent with spaces)")
        if raw.lstrip().startswith("---"):
            raise ProfileConfigError(
                f"{source}:{number}: multi-document markers are not supported")
        content = _strip_comment(raw)
        if not content.strip():
            continue
        indent = len(content) - len(content.lstrip(" "))
        lines.append((indent, content.strip(), number))
    if not lines:
        raise ProfileConfigError(f"{source}: empty document")
    if lines[0][0] != 0:
        raise ProfileConfigError(
            f"{source}:{lines[0][2]}: the document must start at column 0")
    document, index = _parse_block(lines, 0, 0, source)
    if index != len(lines):
        indent, _content, number = lines[index]
        raise ProfileConfigError(
            f"{source}:{number}: unexpected indentation (indent {indent})")
    if not isinstance(document, dict):
        raise ProfileConfigError(f"{source}: the top level must be a mapping")
    return document


def _parse_block(lines: list[tuple[int, str, int]], index: int, indent: int,
                 source: str) -> tuple[Any, int]:
    if lines[index][1].startswith("- "):
        return _parse_sequence(lines, index, indent, source)
    return _parse_mapping(lines, index, indent, source)


def _parse_sequence(lines: list[tuple[int, str, int]], index: int, indent: int,
                    source: str) -> tuple[list[Any], int]:
    items: list[Any] = []
    while (index < len(lines) and lines[index][0] == indent
           and lines[index][1].startswith("- ")):
        text = lines[index][1][2:].strip()
        number = lines[index][2]
        if not text:
            if index + 1 < len(lines) and lines[index + 1][0] > indent:
                item, index = _parse_block(lines, index + 1, lines[index + 1][0],
                                           source)
                items.append(item)
                continue
            items.append(None)
            index += 1
            continue
        if _looks_like_mapping_entry(text):
            raise ProfileConfigError(
                f"{source}:{number}: a sequence item must be a scalar or a nested "
                f"block — a mapping inside a sequence is outside the supported "
                f"subset")
        items.append(_scalar(text, source, number))
        index += 1
    return items, index


def _parse_mapping(lines: list[tuple[int, str, int]], index: int, indent: int,
                   source: str) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while (index < len(lines) and lines[index][0] == indent
           and not lines[index][1].startswith("- ")):
        content, number = lines[index][1], lines[index][2]
        key, rest = _split_entry(content, source, number)
        if key in mapping:
            raise ProfileConfigError(f"{source}:{number}: duplicate key {key!r}")
        if rest:
            mapping[key] = _scalar(rest, source, number)
            index += 1
            continue
        if index + 1 < len(lines) and lines[index + 1][0] > indent:
            child, index = _parse_block(lines, index + 1, lines[index + 1][0],
                                        source)
            mapping[key] = child
            continue
        mapping[key] = None
        index += 1
    return mapping, index


def _looks_like_mapping_entry(text: str) -> bool:
    quote = ""
    for position, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            continue
        if char == ":" and (position + 1 == len(text) or text[position + 1] == " "):
            return True
    return False


def _split_entry(content: str, source: str, number: int) -> tuple[str, str]:
    for position, char in enumerate(content):
        if char == ":" and (position + 1 == len(content)
                            or content[position + 1] == " "):
            key = content[:position].strip()
            if not key:
                raise ProfileConfigError(f"{source}:{number}: empty key")
            return key, content[position + 1:].strip()
    raise ProfileConfigError(f"{source}:{number}: expected 'key: value'")


def _scalar(text: str, source: str, number: int) -> Any:
    if text[:1] in _UNSUPPORTED_PREFIXES or "!!" in text or text.startswith("- "):
        raise ProfileConfigError(
            f"{source}:{number}: unsupported YAML construct in {text!r} "
            f"(anchors, aliases, tags, flow mappings and block scalars are "
            f"deliberately outside this format)")
    if text.startswith(("\"", "'")):
        return _quoted(text, source, number)
    if text.startswith("["):
        return _inline_list(text, source, number)
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    if text in _NULL:
        return None
    if _INT.fullmatch(text):
        return int(text)
    if _FLOAT.fullmatch(text):
        return float(text)
    return text


def _quoted(text: str, source: str, number: int) -> str:
    quote = text[0]
    if len(text) < 2 or not text.endswith(quote):
        raise ProfileConfigError(f"{source}:{number}: unterminated quoted scalar")
    body = text[1:-1]
    if quote == "\"":
        if "\\\"" in body.rstrip("\\"):
            raise ProfileConfigError(
                f"{source}:{number}: escaped quotes are not supported in "
                f"double-quoted scalars")
        body = (body.replace("\\\\", "\u0000").replace("\\n", "\n")
                .replace("\u0000", "\\"))
    return body


def _inline_list(text: str, source: str, number: int) -> list[Any]:
    if not text.endswith("]"):
        raise ProfileConfigError(f"{source}:{number}: unterminated inline list")
    body = text[1:-1].strip()
    if any(char in body for char in "[]{}"):
        raise ProfileConfigError(
            f"{source}:{number}: nested structures are not supported inside an "
            f"inline list")
    if not body:
        return []
    return [_scalar(item.strip(), source, number) for item in body.split(",")]


# ═══════════════════════ the profile record ═══════════════════════


@dataclass(frozen=True, slots=True)
class ModelPolicySpec:
    """Which model tier the profile uses and what contract it expects back."""

    tier: str
    contract: str = DEFAULT_CONTRACT
    kind_field: str = "kind"
    rationale_field: str = "rationale"
    structured_fields: tuple[str, ...] = ()
    allows_tool_calls: bool = False
    max_output_tokens: int | None = None
    options: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AuthoritySpec:
    """The profile's declared proposal authority (the allowlist).

    `requires_human_for` is *declared-but-refused*: those kinds need a bound
    `HumanDecisionReceived`, which a plane can never supply (§2.3 `PROPOSAL`), so
    the runtime refuses them explicitly instead of leaving them ambiguous.
    """

    proposable_kinds: tuple[str, ...]
    director_only: bool = False
    allowed_capabilities: tuple[str, ...] = ()
    requires_human_for: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TerminationSpec:
    """When a run stops — declared as data, honoured as a bound."""

    max_ticks: int
    max_proposals: int
    stop_when: str
    max_model_calls_per_tick: int = 1
    max_tool_calls: int = 4
    deadline_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ReviewSpec:
    """The profile's review policy — a *child run*, never a callback."""

    reviewer_profile: str = ""
    required: bool = False
    max_review_rounds: int = 1


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """One runtime profile: declared authority, tools, limits and review."""

    name: str
    role: str
    agent_profile: str
    model_policy: ModelPolicySpec
    tools: tuple[str, ...]
    authority: AuthoritySpec
    schemas: Mapping[str, Any]
    termination: TerminationSpec
    review: ReviewSpec
    version: str = "1"

    def allows_kind(self, kind: IntentKind) -> bool:
        """True when the profile declares this kind as proposable."""
        return kind.value in self.authority.proposable_kinds

    def refuses_by_authority(self, kind: IntentKind) -> str:
        """Why this profile may not propose `kind` (`""` when it may).

        The order is deliberate: the partition checks come first (a profile may
        never propose an internal-only kind regardless of what it declares), then
        the declared allowlist, then the Director-only rule.
        """
        if kind in IntentKind.internal_only():
            return (f"{kind.value} is internal-only (v4 §8) — a plane may never "
                    f"propose it")
        if kind.value in self.authority.requires_human_for:
            return (f"{kind.value} requires a bound HumanDecisionReceived, which a "
                    f"runtime plane cannot supply (declared in "
                    f"authority.requires_human_for)")
        if not self.allows_kind(kind):
            return (f"{kind.value} is outside {self.name}'s declared proposable "
                    f"kinds")
        if kind in IntentKind.director_only() and self.agent_profile != AgentProfile.DIRECTOR.value:
            return (f"{kind.value} is Director-only (IDR-018) and this profile is "
                    f"bound to {self.agent_profile}")
        return ""


# ═══════════════════════ loading + validation ═══════════════════════


def parse_profile(document: Mapping[str, Any], *, source: str = "<profile>") -> ProfileSpec:
    """Validate one parsed document into a `ProfileSpec` — fail closed."""
    unknown = sorted(set(document) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ProfileConfigError(f"{source}: unknown keys: {unknown}")
    for required in ("name", "role", "agent_profile", "model_policy", "authority",
                     "termination"):
        if document.get(required) in (None, ""):
            raise ProfileConfigError(f"{source}: missing required key {required!r}")

    name = _require_text(document["name"], source, "name")
    role = _require_text(document["role"], source, "role")
    agent_profile = _require_text(document["agent_profile"], source,
                                 "agent_profile")
    if agent_profile not in {member.value for member in AgentProfile}:
        raise ProfileConfigError(
            f"{source}: agent_profile {agent_profile!r} is not a known "
            f"AgentProfile ({[member.value for member in AgentProfile]})")

    model_policy = _parse_model_policy(document["model_policy"], source)
    tools = _require_text_list(document.get("tools"), source, "tools")
    authority = _parse_authority(document["authority"], source, tools)
    termination = _parse_termination(document["termination"], source)
    review = _parse_review(document.get("review"), source)
    schemas = document.get("schemas") or {}
    if not isinstance(schemas, dict):
        raise ProfileConfigError(f"{source}: schemas must be a mapping")
    if authority.director_only and agent_profile != AgentProfile.DIRECTOR.value:
        raise ProfileConfigError(
            f"{source}: authority.director_only is set but agent_profile is "
            f"{agent_profile!r} — only DIRECTOR may carry Director-only authority")
    if termination.stop_when == "review_complete" and not review.required:
        raise ProfileConfigError(
            f"{source}: termination.stop_when 'review_complete' needs a declared "
            f"review (review.required with a reviewer_profile) — the policy stops "
            f"the run once there is a proposal set for the review to consider, so "
            f"a profile with no review has nothing to complete")

    return ProfileSpec(
        name=name,
        role=role,
        agent_profile=agent_profile,
        model_policy=model_policy,
        tools=tools,
        authority=authority,
        schemas=dict(schemas),
        termination=termination,
        review=review,
        version=str(document.get("version", "1")),
    )


def _parse_model_policy(value: Any, source: str) -> ModelPolicySpec:
    if not isinstance(value, dict):
        raise ProfileConfigError(f"{source}: model_policy must be a mapping")
    unknown = sorted(set(value) - _MODEL_POLICY_KEYS)
    if unknown:
        raise ProfileConfigError(f"{source}: unknown model_policy keys: {unknown}")
    tier = _require_text(value.get("tier"), source, "model_policy.tier")
    options = value.get("options") or {}
    if not isinstance(options, dict):
        raise ProfileConfigError(f"{source}: model_policy.options must be a mapping")
    max_output_tokens = value.get("max_output_tokens")
    if max_output_tokens is not None and (not isinstance(max_output_tokens, int)
                                          or max_output_tokens <= 0):
        raise ProfileConfigError(
            f"{source}: model_policy.max_output_tokens must be a positive integer")
    return ModelPolicySpec(
        tier=tier,
        contract=str(value.get("contract", DEFAULT_CONTRACT)),
        kind_field=str(value.get("kind_field", "kind")),
        rationale_field=str(value.get("rationale_field", "rationale")),
        structured_fields=_require_text_list(value.get("structured_fields"),
                                             source, "model_policy.structured_fields"),
        allows_tool_calls=bool(value.get("allows_tool_calls", False)),
        max_output_tokens=max_output_tokens,
        options={str(key): str(item) for key, item in options.items()},
    )


def _parse_authority(value: Any, source: str, tools: tuple[str, ...]) -> AuthoritySpec:
    if not isinstance(value, dict):
        raise ProfileConfigError(f"{source}: authority must be a mapping")
    unknown = sorted(set(value) - _AUTHORITY_KEYS)
    if unknown:
        raise ProfileConfigError(f"{source}: unknown authority keys: {unknown}")

    proposable = _require_text_list(value.get("proposable_kinds"), source,
                                   "authority.proposable_kinds")
    known_kinds = {member.value for member in IntentKind}
    for kind_name in proposable:
        if kind_name not in known_kinds:
            raise ProfileConfigError(
                f"{source}: authority.proposable_kinds names {kind_name!r}, which "
                f"is not an IntentKind")
        if IntentKind(kind_name) in IntentKind.internal_only():
            raise ProfileConfigError(
                f"{source}: authority.proposable_kinds must not contain the "
                f"internal-only kind {kind_name!r} (v4 §8) — a plane may not be "
                f"configured with a partition breach")

    requires_human = _require_text_list(value.get("requires_human_for"), source,
                                        "authority.requires_human_for")
    for kind_name in requires_human:
        if kind_name not in known_kinds:
            raise ProfileConfigError(
                f"{source}: authority.requires_human_for names {kind_name!r}, "
                f"which is not an IntentKind")
        if IntentKind(kind_name) in IntentKind.internal_only():
            raise ProfileConfigError(
                f"{source}: authority.requires_human_for names the internal-only "
                f"kind {kind_name!r}")
        if kind_name in proposable:
            raise ProfileConfigError(
                f"{source}: {kind_name!r} is both proposable and "
                f"human-required — the runtime could never satisfy the second "
                f"declaration")

    allowed = _require_text_list(value.get("allowed_capabilities"), source,
                                 "authority.allowed_capabilities")
    undeclared = sorted(set(allowed) - set(tools))
    if undeclared:
        raise ProfileConfigError(
            f"{source}: authority.allowed_capabilities names {undeclared}, which "
            f"is not in the declared tools — a profile may not reach a capability "
            f"it never declared")

    return AuthoritySpec(
        proposable_kinds=proposable,
        director_only=bool(value.get("director_only", False)),
        allowed_capabilities=allowed,
        requires_human_for=requires_human,
    )


def _parse_termination(value: Any, source: str) -> TerminationSpec:
    if not isinstance(value, dict):
        raise ProfileConfigError(f"{source}: termination must be a mapping")
    unknown = sorted(set(value) - _TERMINATION_KEYS)
    if unknown:
        raise ProfileConfigError(f"{source}: unknown termination keys: {unknown}")
    max_ticks = value.get("max_ticks")
    max_proposals = value.get("max_proposals")
    if not isinstance(max_ticks, int) or max_ticks < 1:
        raise ProfileConfigError(f"{source}: termination.max_ticks must be >= 1")
    if not isinstance(max_proposals, int) or max_proposals < 1:
        raise ProfileConfigError(f"{source}: termination.max_proposals must be >= 1")
    stop_when = str(value.get("stop_when", "proposals_raised"))
    if stop_when not in STOP_WHEN_POLICIES:
        raise ProfileConfigError(
            f"{source}: termination.stop_when {stop_when!r} is not one of "
            f"{list(STOP_WHEN_POLICIES)}")
    deadline = value.get("deadline_seconds")
    if deadline is not None and (not isinstance(deadline, (int, float))
                                 or deadline <= 0):
        raise ProfileConfigError(
            f"{source}: termination.deadline_seconds must be positive or absent")
    max_tool_calls = value.get("max_tool_calls", 4)
    if not isinstance(max_tool_calls, int) or max_tool_calls < 0:
        raise ProfileConfigError(f"{source}: termination.max_tool_calls must be >= 0")
    max_model_calls = value.get("max_model_calls_per_tick", 1)
    if not isinstance(max_model_calls, int) or max_model_calls < 1:
        raise ProfileConfigError(
            f"{source}: termination.max_model_calls_per_tick must be >= 1")
    return TerminationSpec(
        max_ticks=max_ticks,
        max_proposals=max_proposals,
        stop_when=stop_when,
        max_model_calls_per_tick=max_model_calls,
        max_tool_calls=max_tool_calls,
        deadline_seconds=None if deadline is None else float(deadline),
    )


def _parse_review(value: Any, source: str) -> ReviewSpec:
    if value is None:
        return ReviewSpec()
    if not isinstance(value, dict):
        raise ProfileConfigError(f"{source}: review must be a mapping")
    unknown = sorted(set(value) - _REVIEW_KEYS)
    if unknown:
        raise ProfileConfigError(f"{source}: unknown review keys: {unknown}")
    rounds = value.get("max_review_rounds", 1)
    if not isinstance(rounds, int) or rounds < 0:
        raise ProfileConfigError(f"{source}: review.max_review_rounds must be >= 0")
    reviewer = str(value.get("reviewer_profile", "") or "")
    required = bool(value.get("required", False))
    if required and not reviewer:
        raise ProfileConfigError(
            f"{source}: review.required needs a reviewer_profile")
    return ReviewSpec(reviewer_profile=reviewer, required=required,
                      max_review_rounds=rounds)


def _require_text(value: Any, source: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileConfigError(f"{source}: {where} must be a non-empty string")
    return value.strip()


def _require_text_list(value: Any, source: str, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip()
                                             for item in value):
        raise ProfileConfigError(f"{source}: {where} must be a list of non-empty strings")
    items = tuple(item.strip() for item in value)
    if len(set(items)) != len(items):
        raise ProfileConfigError(f"{source}: {where} contains duplicates")
    return items


def load_profile(name: str, *, directory: Path | str | None = None) -> ProfileSpec:
    """Load one profile by name, binding the file stem to the declared name."""
    root = Path(directory) if directory is not None else PROFILES_DIR
    path = root / f"{name}{PROFILE_SUFFIX}"
    if not path.is_file():
        raise ProfileConfigError(f"no profile configuration at {path}")
    document = parse_profile_yaml(path.read_text(encoding="utf-8"),
                                  source=path.name)
    spec = parse_profile(document, source=path.name)
    if spec.name != name:
        raise ProfileConfigError(
            f"{path.name}: declares name {spec.name!r}, which does not match its "
            f"file name {name!r}")
    return spec


def load_profiles(*, directory: Path | str | None = None) -> dict[str, ProfileSpec]:
    """Load every profile in the directory, then check cross-profile coherence.

    The cross-check exists because review is a *child run*: a profile that
    declares a reviewer nobody defines would be a dangling declaration, which the
    fail-closed rule cannot tolerate.
    """
    root = Path(directory) if directory is not None else PROFILES_DIR
    if not root.is_dir():
        raise ProfileConfigError(f"no profile directory at {root}")
    profiles: dict[str, ProfileSpec] = {}
    for path in sorted(root.glob(f"*{PROFILE_SUFFIX}")):
        spec = load_profile(path.stem, directory=root)
        profiles[spec.name] = spec
    if not profiles:
        raise ProfileConfigError(f"no {PROFILE_SUFFIX} profiles found in {root}")
    for spec in profiles.values():
        reviewer = spec.review.reviewer_profile
        if reviewer and reviewer not in profiles:
            raise ProfileConfigError(
                f"{spec.name}: review.reviewer_profile {reviewer!r} is not a "
                f"declared profile ({sorted(profiles)})")
        if spec.review.required and spec.review.max_review_rounds < 1:
            raise ProfileConfigError(
                f"{spec.name}: review.required needs max_review_rounds >= 1")
    return profiles


def profile_names(*, directory: Path | str | None = None) -> tuple[str, ...]:
    """The declared profile names, in sorted order (never a hardcoded list)."""
    return tuple(sorted(load_profiles(directory=directory)))
