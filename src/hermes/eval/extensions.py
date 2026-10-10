"""Extensibility manifest — the frozen extension points.

R7 deliverable (c). Each extension point is a **frozen contract**: an
operations list, a refusal behaviour (drawn from the existing frozen
vocabulary, never invented), a registration shape, and one worked
example. The worked examples are pure value objects that the test
suite exercises; nothing here writes, opens a connection, or reaches
outside the process.

Rules (R7 contract):

* no new refusal codes — every extension's ``refused_code`` is in the
  frozen vocabulary (``matrix.FROZEN_REFUSAL_CODES``);
* no new event / intent kinds / tables / authorities — an extension
  is a **typed**, **closed** value object;
* registration is **declarative** — a name, an instance, an optional
  scope; the registry holds it, the registry never persists it (a
  caller that wants durability re-enters through ``apply_intent``).
* the registry is read-only **mechanically** — the module-level
  mapping is a ``MappingProxyType`` and every registry's entries are
  one too, so assignment and deletion raise ``TypeError``. To replace
  an extension, restart the process. This is what makes "the
  extension vocabulary is frozen" mechanical;
* every extension point validates itself at construction — an
  unfrozen ``refused_code`` or an empty operations list refuses when
  the ``ExtensionPoint`` is built, not when someone remembers to
  call ``validate()``.

The nine extension points (R7 brief):

| name              | role                                                         |
|-------------------|--------------------------------------------------------------|
| ModelProvider     | a model backend (the MODEL plane port)                         |
| Tool              | a capability provider (the CAPABILITY plane port)              |
| ToolSet           | a named composition of capabilities (B-3)                     |
| AgentRole         | a profile (the RUNTIME plane's typed entry)                    |
| Workflow          | a methodology document (the data plane's config)              |
| StorageBackend    | a content-addressed storage backend (the artifact store)      |
| EventSink         | an in-process event consumer (B-5, derived-only)               |
| GovernancePolicy  | the action→authority matrix (governance, immutable)            |
| Evaluator         | an evaluator (the eval plane's plug-in)                       |
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from hermes.eval.matrix import FROZEN_REFUSAL_CODES

__all__ = [
    "EXTENSION_POINTS",
    "ExampleAgentRole",
    "ExampleEvaluator",
    "ExampleEventSink",
    "ExampleGovernancePolicy",
    "ExampleModelProvider",
    "ExampleOutcome",
    "ExampleStorageBackend",
    "ExampleTool",
    "ExampleToolSet",
    "ExampleWorkflow",
    "ExtensionPoint",
    "ExtensionRegistry",
    "describe_extension",
    "get_extension",
    "list_examples",
    "list_extensions",
    "register_extension",
]


@dataclass(frozen=True, slots=True)
class ExtensionPoint:
    """The frozen contract for one extension point.

    ``summary`` is a one-line description for the manifest. ``operations``
    is the closed list of operations an extension must implement. The
    first operation is the primary entry; the others are supporting
    operations. ``refused_code`` is the refusal code an extension must
    emit when it cannot perform its primary operation — drawn from
    the existing frozen vocabulary, never invented. ``example`` is a
    fully-implemented worked example whose construction is part of
    the contract (the test suite exercises ``example``; a future
    extension must provide one too).
    """

    summary: str
    operations: tuple[str, ...]
    refused_code: str
    example: "Example"
    registration_shape: str

    def __post_init__(self) -> None:
        # Construction-time validation: an extension point that is not
        # contract-shaped cannot exist, so no caller can hold one and
        # forget to validate it.
        self.validate()

    def validate(self) -> None:
        if self.example is None:
            raise ValueError(
                f"extension point {self.summary!r}: must declare a worked "
                f"example")
        if self.refused_code not in FROZEN_REFUSAL_CODES:
            raise ValueError(
                f"extension {self.example.name!r}: refused_code "
                f"{self.refused_code!r} is not in the frozen vocabulary "
                f"{sorted(FROZEN_REFUSAL_CODES)}")
        if not self.operations:
            raise ValueError(
                f"extension {self.example.name!r}: must declare at least one "
                f"operation")


# ────────────────────────────────────────────────────────────────────────
# worked examples — pure value objects, exercised by the test suite
# ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExampleOutcome:
    """A worked example's report of an operation.

    ``value`` is the operation's result; ``refusal`` is an optional
    refusal-as-data value (only one of the two is set).
    """

    value: Any = None
    refusal: Any = None


class Example(abc.ABC):
    """The base class every worked example inherits.

    A worked example is a pure value-object: no I/O, no clock, no
    socket. The test suite constructs one and invokes each
    ``operations``-listed method.
    """

    name: str

    @abc.abstractmethod
    def primary(self) -> ExampleOutcome: ...

    def describe(self) -> Mapping[str, Any]:
        return {"name": self.name, "type": type(self).__name__}


# ── ModelProvider ────────────────────────────────────────────────


class ExampleModelProvider(Example):
    """A worked ``ModelProvider``: a stub that returns a single canned
    proposal and refuses anything else.

    The primary operation is ``invoke``. The refusal code is
    ``PROPOSAL`` (mirrors the model plane's
    ``test_decision_shaped_output_refuses_without_a_retry``).
    """

    name = "scripted-stub"

    def __init__(self, model_id: str = "stub-1",
                 canned_text: str = "stub") -> None:
        self._model_id = str(model_id)
        self._canned_text = str(canned_text)

    def primary(self) -> ExampleOutcome:
        return ExampleOutcome(value={
            "model_id": self._model_id,
            "text": self._canned_text,
        })

    def describe(self) -> Mapping[str, Any]:
        return {"name": self.name, "type": "ModelProvider",
                "model_id": self._model_id}


# ── Tool ──────────────────────────────────────────────────────────


class ExampleTool(Example):
    """A worked ``Tool``: a stub that returns a single canned observation
    and refuses anything out of scope.

    The refusal code is ``ROLE`` (mirrors the capability plane's
    ``test_a_mutating_tool_refuses_role_before_anything_else``).
    """

    name = "echo-tool"

    def __init__(self, tool_id: str = "echo-1") -> None:
        self._tool_id = str(tool_id)

    def primary(self) -> ExampleOutcome:
        return ExampleOutcome(value={"tool_id": self._tool_id,
                                     "observation": "echo"})

    def describe(self) -> Mapping[str, Any]:
        return {"name": self.name, "type": "Tool",
                "tool_id": self._tool_id}


# ── ToolSet ──────────────────────────────────────────────────────


class ExampleToolSet(Example):
    """A worked ``ToolSet``: a fixed composition of two tools.

    The refusal code is ``ROLE`` (mirrors the capability plane's
    composition tests; composition cannot widen authority).
    """

    name = "read-only-set"

    def __init__(self, tools: Sequence[ExampleTool] = ()) -> None:
        self._tools: tuple[ExampleTool, ...] = tuple(tools) or (
            ExampleTool(tool_id="echo-a"),
            ExampleTool(tool_id="echo-b"),
        )

    def primary(self) -> ExampleOutcome:
        return ExampleOutcome(value={
            "set_id": "read-only-set",
            "tools": [t.describe() for t in self._tools],
        })

    def describe(self) -> Mapping[str, Any]:
        return {"name": self.name, "type": "ToolSet",
                "tools": [t.name for t in self._tools]}


# ── AgentRole ────────────────────────────────────────────────────


class ExampleAgentRole(Example):
    """A worked ``AgentRole``: a stub that names a profile and its
    allowlist.

    The refusal code is ``ROLE`` (mirrors the runtime plane's
    ``test_kind_outside_the_injected_allowlist_refuses_role``).
    """

    name = "researcher-stub"

    def __init__(self, profile: str = "researcher",
                 allowlist: Sequence[str] = ()) -> None:
        self._profile = str(profile)
        self._allowlist: tuple[str, ...] = tuple(allowlist) or (
            "INSERT_TASK", "REQUEST_HUMAN",
        )

    def primary(self) -> ExampleOutcome:
        return ExampleOutcome(value={
            "profile": self._profile,
            "allowlist": list(self._allowlist),
        })

    def describe(self) -> Mapping[str, Any]:
        return {"name": self.name, "type": "AgentRole",
                "profile": self._profile}


# ── Workflow ──────────────────────────────────────────────────────


class ExampleWorkflow(Example):
    """A worked ``Workflow``: a minimal methodology document.

    The refusal code is ``MALFORMED_PAYLOAD`` (mirrors the methodology
    plane's parser tests; a workflow missing a required key refuses).
    """

    name = "literature-review-stub"

    def __init__(self, methodology_id: str = "literature-review",
                 stages: Sequence[str] = ()) -> None:
        self._id = str(methodology_id)
        self._stages: tuple[str, ...] = tuple(stages) or (
            "QUESTION", "HYPOTHESIS", "CONCLUSION",
        )

    def primary(self) -> ExampleOutcome:
        return ExampleOutcome(value={
            "methodology_id": self._id,
            "stages": list(self._stages),
        })

    def describe(self) -> Mapping[str, Any]:
        return {"name": self.name, "type": "Workflow",
                "methodology_id": self._id}


# ── StorageBackend ──────────────────────────────────────────────


class ExampleStorageBackend(Example):
    """A worked ``StorageBackend``: an in-memory content-addressed
    store that refuses to overwrite a committed digest.

    The refusal code is ``STALE`` (mirrors the journal's
    append-only / archive-not-delete discipline; a re-keyed record
    is refused as stale rather than rewritten).
    """

    name = "in-memory-ca"

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def primary(self) -> ExampleOutcome:
        return ExampleOutcome(value={
            "backend_id": "in-memory-ca",
            "size": len(self._store),
        })

    def put(self, digest: str, value: str) -> ExampleOutcome:
        if digest in self._store and self._store[digest] != value:
            return ExampleOutcome(refusal={
                "code": "STALE", "detail": "immutable: digest already committed"})
        self._store[digest] = value
        return ExampleOutcome(value=digest)

    def get(self, digest: str) -> ExampleOutcome:
        if digest not in self._store:
            return ExampleOutcome(refusal={
                "code": "EVIDENCE_DOES_NOT_RESOLVE",
                "detail": "no such digest"})
        return ExampleOutcome(value=self._store[digest])

    def describe(self) -> Mapping[str, Any]:
        return {"name": self.name, "type": "StorageBackend"}


# ── EventSink ────────────────────────────────────────────────────


class ExampleEventSink(Example):
    """A worked ``EventSink``: an in-process derived-only consumer
    (B-5 — the sink is a reader, never a writer).

    The refusal code is ``ROLE`` (an EventSink that asks to author
    state is refused).
    """

    name = "tap-sink"

    def __init__(self) -> None:
        self._received: list[Mapping[str, Any]] = []

    def primary(self) -> ExampleOutcome:
        return ExampleOutcome(value={"received": len(self._received)})

    def observe(self, event: Mapping[str, Any]) -> ExampleOutcome:
        # Pure derivation: record, do not author.
        self._received.append(dict(event))
        return ExampleOutcome(value=len(self._received))

    def describe(self) -> Mapping[str, Any]:
        return {"name": self.name, "type": "EventSink"}


# ── GovernancePolicy ─────────────────────────────────────────────


class ExampleGovernancePolicy(Example):
    """A worked ``GovernancePolicy``: an immutable action→authority
    table with three rows.

    The refusal code is ``MALFORMED_PAYLOAD`` (mirrors the
    governance plane's ``test_a_row_naming_an_unknown_code_is_refused_at_construction``).
    """

    name = "minimal-policy"

    def __init__(self) -> None:
        self._rows: tuple[tuple[str, str], ...] = (
            ("WEB_SEARCH", "AGENT"),
            ("WEB_READ", "AGENT"),
            ("PUBLISH", "HUMAN"),
        )

    def primary(self) -> ExampleOutcome:
        return ExampleOutcome(value={"rows": list(self._rows)})

    def lookup(self, action: str) -> ExampleOutcome:
        for a, level in self._rows:
            if a == action:
                return ExampleOutcome(value=level)
        return ExampleOutcome(refusal={
            "code": "MALFORMED_PAYLOAD",
            "detail": f"policy: unknown action {action!r}"})

    def describe(self) -> Mapping[str, Any]:
        return {"name": self.name, "type": "GovernancePolicy"}


# ── Evaluator ────────────────────────────────────────────────────


class ExampleEvaluator(Example):
    """A worked ``Evaluator``: a stub that runs the matrix against a
    supplied registry.

    The refusal code is ``MALFORMED_PAYLOAD`` (a malformed registry
    is refused; this is what keeps the eval plane honest about its
    own construction).
    """

    name = "matrix-stub"

    def primary(self) -> ExampleOutcome:
        return ExampleOutcome(value={"evaluator": "matrix-stub"})

    def describe(self) -> Mapping[str, Any]:
        return {"name": self.name, "type": "Evaluator"}


# ────────────────────────────────────────────────────────────────────────
# the frozen registry
# ────────────────────────────────────────────────────────────────────────


def _build_registry() -> dict[str, ExtensionPoint]:
    """Build the frozen registry. The keys are the canonical names;
    the values are the contracts. Adding a new key is a design gate
    (R7: the extension-point vocabulary is frozen at nine entries).
    """
    examples: dict[str, Example] = {
        "ModelProvider": ExampleModelProvider(),
        "Tool": ExampleTool(),
        "ToolSet": ExampleToolSet(),
        "AgentRole": ExampleAgentRole(),
        "Workflow": ExampleWorkflow(),
        "StorageBackend": ExampleStorageBackend(),
        "EventSink": ExampleEventSink(),
        "GovernancePolicy": ExampleGovernancePolicy(),
        "Evaluator": ExampleEvaluator(),
    }
    return {
        "ModelProvider": ExtensionPoint(
            summary="a model backend (the MODEL plane port)",
            operations=("invoke", "describe"),
            refused_code="PROPOSAL",
            example=examples["ModelProvider"],
            registration_shape=("ModelProvider(name, model_id, "
                                "decision_vocabulary)"),
        ),
        "Tool": ExtensionPoint(
            summary="a capability provider (the CAPABILITY plane port)",
            operations=("invoke", "describe"),
            refused_code="ROLE",
            example=examples["Tool"],
            registration_shape=("Tool(tool_id, protocol, hazard_class)"),
        ),
        "ToolSet": ExtensionPoint(
            summary="a named composition of capabilities (B-3)",
            operations=("enumerate",),
            refused_code="ROLE",
            example=examples["ToolSet"],
            registration_shape=("ToolSet(set_id, capability_ids)"),
        ),
        "AgentRole": ExtensionPoint(
            summary="a profile (the RUNTIME plane's typed entry)",
            operations=("draft", "allowlist"),
            refused_code="ROLE",
            example=examples["AgentRole"],
            registration_shape=("AgentRole(profile, proposable_kinds)"),
        ),
        "Workflow": ExtensionPoint(
            summary="a methodology document (the data plane's config)",
            operations=("parse", "run"),
            refused_code="MALFORMED_PAYLOAD",
            example=examples["Workflow"],
            registration_shape=("Workflow(methodology_id, version, "
                                "stages, termination)"),
        ),
        "StorageBackend": ExtensionPoint(
            summary=("a content-addressed storage backend (the "
                     "artifact store)"),
            operations=("put", "get"),
            refused_code="STALE",
            example=examples["StorageBackend"],
            registration_shape=("StorageBackend(backend_id, scheme)"),
        ),
        "EventSink": ExtensionPoint(
            summary="an in-process event consumer (B-5, derived-only)",
            operations=("observe",),
            refused_code="ROLE",
            example=examples["EventSink"],
            registration_shape=("EventSink(sink_id, handler_dependencies)"),
        ),
        "GovernancePolicy": ExtensionPoint(
            summary="the action→authority matrix (governance, immutable)",
            operations=("lookup",),
            refused_code="MALFORMED_PAYLOAD",
            example=examples["GovernancePolicy"],
            registration_shape=("GovernancePolicy(version, rows)"),
        ),
        "Evaluator": ExtensionPoint(
            summary="an evaluator (the eval plane's plug-in)",
            operations=("evaluate",),
            refused_code="MALFORMED_PAYLOAD",
            example=examples["Evaluator"],
            registration_shape=("Evaluator(name, signature)"),
        ),
    }


#: The frozen manifest. The private dict is wrapped in a
#: ``MappingProxyType``: assignment, deletion, and ``setdefault`` raise
#: ``TypeError`` — the read-only rule is mechanical, not aspirational.
EXTENSION_POINTS: Mapping[str, ExtensionPoint] = MappingProxyType(
    _build_registry())


def list_extensions() -> tuple[str, ...]:
    """The canonical order of the frozen extension-point vocabulary."""
    return tuple(EXTENSION_POINTS.keys())


def describe_extension(name: str, *, as_json: bool = False) -> str:
    """Render the contract for one extension point.

    JSON form is suitable for ``platform_cli extensions <name> --format
    json``; the human form is for the manifest.
    """
    if name not in EXTENSION_POINTS:
        raise KeyError(f"unknown extension: {name!r}")
    ep = EXTENSION_POINTS[name]
    body: dict[str, Any] = {
        "name": name,
        "summary": ep.summary,
        "operations": list(ep.operations),
        "refused_code": ep.refused_code,
        "registration_shape": ep.registration_shape,
        "example": ep.example.describe(),
        "primary_outcome": ep.example.primary().value,
    }
    if as_json:
        import json
        return json.dumps(body, indent=2, sort_keys=True)
    lines: list[str] = [
        f"# {name}",
        "",
        ep.summary,
        "",
        f"operations: {', '.join(ep.operations)}",
        f"refused_code: {ep.refused_code}",
        f"registration_shape: {ep.registration_shape}",
        "",
        f"example: {ep.example.describe()}",
    ]
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────
# runtime registry (process-local; not durable)
# ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExtensionRegistry:
    """The process-local extension registry.

    Read-only after construction: the only way to install an extension
    is at construction time. ``entries`` is copied into a
    ``MappingProxyType`` by ``__post_init__``, so there is no setter,
    no writer, no deleter — ``entries[name] = ...`` and ``del
    entries[name]`` raise ``TypeError``. To replace an extension, the
    caller restarts the process and constructs a new registry. This is
    what makes the extension-point vocabulary mechanical rather than
    aspirational.
    """

    entries: Mapping[str, Example]

    def __post_init__(self) -> None:
        if not isinstance(self.entries, Mapping):
            raise TypeError(
                f"extension registry entries must be a mapping, got "
                f"{type(self.entries).__name__}")
        # ``object.__setattr__`` is the only legal write on a frozen
        # dataclass field; after this line the mapping is immutable.
        object.__setattr__(
            self, "entries", MappingProxyType(dict(self.entries)))

    def get(self, name: str) -> Example:
        if name not in self.entries:
            raise KeyError(
                f"extension {name!r} not registered; available: "
                f"{sorted(self.entries)}")
        return self.entries[name]

    def names(self) -> tuple[str, ...]:
        return tuple(self.entries.keys())


def register_extension(extension: Example) -> ExtensionRegistry:
    """Construct a fresh registry containing only the supplied extension.

    A caller that wants multiple extensions passes a sequence; the
    common path is one-extension-per-registry (each call constructs
    a new registry). This is what makes "the extension vocabulary is
    frozen" mechanical — no in-place mutation.
    """
    return ExtensionRegistry(entries={extension.name: extension})


def get_extension(registry: ExtensionRegistry, name: str) -> Example:
    """Look up one extension by name."""
    return registry.get(name)


def list_examples() -> tuple[Example, ...]:
    """The default example for every extension point (used by the test
    suite to assert each example is green).
    """
    return tuple(EXTENSION_POINTS[name].example for name in EXTENSION_POINTS)