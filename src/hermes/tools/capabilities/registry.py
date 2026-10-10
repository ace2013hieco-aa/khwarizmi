"""Capability plane — the registry, `enumerate()`, and B-3 named composition.

`ARCHITECTURE_DELTA.md` §2.2 operation 1 is the contract: `enumerate()` is the
composition/discovery surface, and §4 **B-3** is the binding constraint on it.

B-3, honoured literally
-----------------------
B-3 permits borrowing the *behaviour* of "named toolset composition with plugin
participation" and forbids importing the host's implementation: providers stay
behind ports, composition must not leak a provider into core, and the borrowed
module graph is off limits. So composition here is **declared data**:

- a `ToolSet` names capability ids; the registry resolves them;
- a `PluginManifest` may contribute *names and composition only* — it cannot
  register a tool implementation, because there is no API here that accepts one.
  A plugin that names an undeclared capability fails registration instead of
  quietly introducing reach.

That is what "non-authoritative composition layer" means concretely: a plugin
participates in composition and gains no execution surface from it. Nothing here
imports a plugin, loads a module, or evaluates a string.

Composition and discovery are both fail-closed
---------------------------------------------
- **Registry membership must equal the allowlist.** The allowlist is injected
  (code-owned by the composition root, exactly like the provider registry's
  §27 item 55 rule) and a capability outside it cannot be registered.
  `drift_report()` reports the reverse direction — an allowlisted capability with
  no declaration — because that is the drift that silently removes reach.
- **Discovery is authority-scoped.** `enumerate(grant=None)` returns an empty
  `CapabilitySet`: enumeration must not advertise what a caller cannot invoke, so
  an absent grant discovers nothing. A grant's tool sets, risk ceiling and
  approvals decide what appears.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hermes.tools.capabilities.types import (
    INPUT_TYPES,
    Capability,
    CapabilityKind,
    CapabilitySet,
    Tool,
    ToolGrant,
    ToolSet,
    risk_at_most,
)
from hermes.tools.research_sources import ProviderValidationError

__all__ = [
    "CapabilityRegistry",
    "PluginManifest",
]


def _reject(message: str) -> ProviderValidationError:
    """A registration/composition error — before any I/O, fail-closed."""
    return ProviderValidationError(message, hazard_class="MALFORMED_REQUEST",
                                   recordable=False)


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """A declared external contribution (B-3 plugin participation).

    Declared data only — never imported, never executed, never able to add an
    implementation. It may reference already-registered capabilities and declare
    new named compositions over them, which is the whole of the participation
    surface.
    """

    plugin_id: str
    version: str
    capability_ids: tuple[str, ...] = ()
    tool_sets: tuple[ToolSet, ...] = ()


class CapabilityRegistry:
    """Declarations plus discovery. Holds no implementation and no authority.

    Tool *implementations* live with the invoker (`invoke.py`); this class knows
    only what is declared, which is what lets `enumerate()` be a pure, offline
    answer.
    """

    def __init__(self, *, allowlist: frozenset[str] | None = None) -> None:
        # Deny-everything (`frozenset()`) is a coherent policy; *omitting* the
        # allowlist is not, because it is indistinguishable from forgetting it.
        # So the default is `None` and only `None` refuses — `frozenset()` is a
        # deliberate, accepted statement.
        if allowlist is None:
            raise _reject("CapabilityRegistry requires an explicit allowlist "
                          "(pass frozenset() to deny everything deliberately)")
        self._allowlist = frozenset(allowlist)
        self._tools: dict[str, Tool] = {}
        self._capabilities: dict[str, Capability] = {}
        self._tool_sets: dict[str, ToolSet] = {}
        self._plugins: dict[str, PluginManifest] = {}

    # ── registration (fail-closed) ──

    def register_tool(self, tool: Tool) -> Tool:
        """Register one executable declaration, validating its own coherence."""
        if not tool.tool_id:
            raise _reject("a tool must declare a tool_id")
        if tool.tool_id in self._tools:
            raise _reject(f"tool {tool.tool_id!r} is already registered")
        if tool.timeout_seconds <= 0:
            raise _reject(f"tool {tool.tool_id!r} must declare a positive timeout")
        seen: set[str] = set()
        for spec in tool.inputs:
            if not spec.name:
                raise _reject(f"tool {tool.tool_id!r} declares an unnamed input")
            if spec.name in seen:
                raise _reject(f"tool {tool.tool_id!r} declares input "
                              f"{spec.name!r} twice")
            seen.add(spec.name)
            if spec.type not in INPUT_TYPES:
                raise _reject(f"tool {tool.tool_id!r} input {spec.name!r} has "
                              f"unknown type {spec.type!r}")
            if spec.pattern:
                try:
                    re.compile(spec.pattern)
                except re.error as exc:
                    raise _reject(f"tool {tool.tool_id!r} input {spec.name!r} "
                                  f"has an invalid pattern: {exc}") from None
        if tool.filesystem_scope:
            self._validate_scope(tool)
        self._tools[tool.tool_id] = tool
        return tool

    def _validate_scope(self, tool: Tool) -> None:
        """A declared filesystem scope must itself be contained.

        Registration is the right place to refuse an escaping scope: a tool that
        declares `../../etc` or an absolute path is malformed before it ever runs,
        and catching it here means the sandbox boundary has one fewer way to be
        wrong at call time.
        """
        scope = tool.filesystem_scope
        if scope.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", scope):
            raise _reject(f"tool {tool.tool_id!r} declares an absolute "
                          f"filesystem scope {scope!r}")
        if ".." in scope.split("/") or ".." in scope.split("\\"):
            raise _reject(f"tool {tool.tool_id!r} declares a filesystem scope "
                          f"{scope!r} escaping its root")

    def register_capability(self, capability: Capability) -> Capability:
        """Register an addressable capability, enforcing the allowlist and kind."""
        if not capability.capability_id:
            raise _reject("a capability must declare a capability_id")
        if capability.capability_id not in self._allowlist:
            raise _reject(
                f"capability {capability.capability_id!r} is not in the declared "
                f"allowlist — registry membership must equal allowlist "
                f"membership (drift fails closed)")
        if capability.capability_id in self._capabilities:
            raise _reject(f"capability {capability.capability_id!r} is already "
                          f"registered")
        tool = self._tools.get(capability.tool_id)
        if tool is None:
            raise _reject(f"capability {capability.capability_id!r} addresses "
                          f"unregistered tool {capability.tool_id!r}")
        if capability.kind is CapabilityKind.SANDBOX and not tool.sandboxed:
            raise _reject(
                f"sandbox capability {capability.capability_id!r} must address "
                f"a tool declaring sandboxed=True")
        self._capabilities[capability.capability_id] = capability
        return capability

    def register_tool_set(self, tool_set: ToolSet) -> ToolSet:
        """Register a named composition, validating every member resolves."""
        if not tool_set.set_id:
            raise _reject("a tool set must declare a set_id")
        if tool_set.set_id in self._tool_sets:
            raise _reject(f"tool set {tool_set.set_id!r} is already registered")
        if not tool_set.capability_ids:
            raise _reject(f"tool set {tool_set.set_id!r} declares no capabilities")
        unknown = [name for name in tool_set.capability_ids
                   if name not in self._capabilities]
        if unknown:
            raise _reject(f"tool set {tool_set.set_id!r} names unregistered "
                          f"capability(ies) {unknown} — composition fails closed")
        self._tool_sets[tool_set.set_id] = tool_set
        return tool_set

    def register_plugin(self, manifest: PluginManifest) -> PluginManifest:
        """Register a plugin's *declarations*. Grants it no execution surface."""
        if not manifest.plugin_id:
            raise _reject("a plugin manifest must declare a plugin_id")
        if manifest.plugin_id in self._plugins:
            raise _reject(f"plugin {manifest.plugin_id!r} is already registered")
        unknown = [name for name in manifest.capability_ids
                   if name not in self._capabilities]
        if unknown:
            raise _reject(
                f"plugin {manifest.plugin_id!r} names undeclared "
                f"capability(ies) {unknown} — a plugin composes what is already "
                f"declared and introduces no reach of its own")
        for tool_set in manifest.tool_sets:
            if tool_set.set_id in self._tool_sets:
                raise _reject(f"plugin {manifest.plugin_id!r} redeclares tool set "
                              f"{tool_set.set_id!r}")
            self.register_tool_set(tool_set)
        self._plugins[manifest.plugin_id] = manifest
        return manifest

    # ── lookup ──

    def capability(self, capability_id: str) -> Capability | None:
        return self._capabilities.get(capability_id)

    def tool(self, tool_id: str) -> Tool | None:
        return self._tools.get(tool_id)

    def tool_set(self, set_id: str) -> ToolSet | None:
        return self._tool_sets.get(set_id)

    def tool_for(self, capability_id: str) -> Tool | None:
        capability = self._capabilities.get(capability_id)
        if capability is None:
            return None
        return self._tools.get(capability.tool_id)

    def tool_set_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._tool_sets))

    def plugin_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))

    def capability_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))

    def drift_report(self) -> tuple[str, ...]:
        """Declared-allowlist vs declared-content drift (expected: empty).

        Registration already makes the forward direction impossible, so the
        only reachable drift is an allowlist entry with no declaration — which
        silently removes reach the allowlist promised.
        """
        problems: list[str] = []
        for capability_id in sorted(self._allowlist):
            if capability_id not in self._capabilities:
                problems.append(
                    f"allowlisted capability {capability_id!r} has no declaration")
        for capability_id, capability in sorted(self._capabilities.items()):
            if capability_id not in self._allowlist:
                problems.append(
                    f"declared capability {capability_id!r} is outside the allowlist")
        for tool_set in sorted(self._tool_sets.values(), key=lambda s: s.set_id):
            for member in tool_set.capability_ids:
                if member not in self._capabilities:
                    problems.append(
                        f"tool set {tool_set.set_id!r} references unknown "
                        f"capability {member!r}")
        return tuple(problems)

    # ── the discovery surface (§2.2 operation 1) ──

    def enumerate(self, *, grant: ToolGrant | None = None) -> CapabilitySet:
        """What `grant` can reach — nothing at all when there is no grant.

        Authority-scoped by construction: a capability reachable only through a
        tool set the grant does not open, or above its risk ceiling, is absent
        from the result rather than flagged. Discovery that advertised
        unreachable capabilities would be a leak dressed as convenience.
        """
        if grant is None:
            return CapabilitySet()
        reachable = tuple(tool_set for tool_set in
                          sorted(self._tool_sets.values(), key=lambda s: s.set_id)
                          if grant.opens(tool_set.set_id))
        selected: list[str] = []
        for tool_set in reachable:
            for capability_id in tool_set.capability_ids:
                capability = self._capabilities.get(capability_id)
                if capability is None:
                    continue
                tool = self._tools.get(capability.tool_id)
                if not risk_at_most(capability.effective_risk(tool), grant.max_risk):
                    continue
                if capability_id not in selected:
                    selected.append(capability_id)
        return CapabilitySet(
            capabilities=tuple(self._capabilities[name]
                               for name in sorted(selected)),
            tool_sets=reachable,
            grant_id=grant.grant_id)
