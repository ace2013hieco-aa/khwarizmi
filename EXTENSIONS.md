# EXTENSIONS — frozen extension points

This document is the manifest for the nine frozen extension points
defined in `src/hermes/eval/extensions.py`. Each entry below states
the **contract** (operations, refusal behaviour, registration shape)
and links to the **worked example** the test suite exercises.

## Reading order

1. **Vocabulary** — what the nine names mean and what they are NOT.
2. **The frozen registry** — the construction rule, the no-mutation
   rule, the test-suite pin.
3. **Per-point contracts** — one subsection per extension point,
   each one a worked example.

---

## 1. Vocabulary

| name              | role                                                                          |
|-------------------|-------------------------------------------------------------------------------|
| `ModelProvider`   | a model backend, the MODEL plane port. proposals/bytes only, never authority. |
| `Tool`            | a capability provider, the CAPABILITY plane port. read/observe/side-effect.   |
| `ToolSet`         | a named composition of `Tool`s (B-3). composition cannot widen authority.    |
| `AgentRole`       | a profile, the RUNTIME plane's typed entry. proposals only.                  |
| `Workflow`        | a methodology document, the data plane's config. fail-closed parser.          |
| `StorageBackend`  | a content-addressed storage backend. append-only, identity by digest.        |
| `EventSink`       | an in-process event consumer (B-5, derived-only). never a writer.             |
| `GovernancePolicy`| the action→authority matrix. immutable, frozen.                               |
| `Evaluator`       | an evaluator (the eval plane's plug-in). pure evaluation, no I/O.             |

What none of them is:

* not a transition decider (a model is not a gateway);
* not a writer (every state change still re-enters through `apply_intent`);
* not an authority (a tool cannot approve; an agent role cannot act on
  its own; an evaluator cannot record a result);
* not a clock, not a socket, not a connection (the extension is a
  value object the test suite can construct).

## 2. The frozen registry

The nine names above are the **only** names. Adding a tenth is a
design gate (R7: the extension-point vocabulary is frozen at nine
entries).

The registry is constructed in one place (`extensions._build_registry`)
and is **mechanically read-only** after construction:

```python
EXTENSION_POINTS: Mapping[str, ExtensionPoint] = MappingProxyType(
    _build_registry())
```

There is no setter, no writer, no deleter: `EXTENSION_POINTS[name] = ...`
and `del EXTENSION_POINTS[name]` raise `TypeError` (the mapping is a
`types.MappingProxyType` over a private dict). To replace an extension
the caller restarts the process and constructs a new registry. This
is what makes "the extension vocabulary is frozen" mechanical rather
than aspirational.

**No new refusal codes.** Every extension's `refused_code` is a member
of the existing frozen vocabulary (`matrix.FROZEN_REFUSAL_CODES`,
mirrored from `research.gateway`, `research.controller`,
`agents.runtime.types`, `governance.policy`, and the methodology
plane's own closed set). The contract refuses this for every entry
at construction time — ``__post_init__`` calls ``validate()``, so an
``ExtensionPoint`` with an unfrozen ``refused_code`` or an empty
operations list cannot be built at all:

```python
def __post_init__(self) -> None:
    self.validate()

def validate(self) -> None:
    if self.refused_code not in FROZEN_REFUSAL_CODES:
        raise ValueError(...)
```

**No new event / intent kinds / tables / authorities.** An extension
is a typed, closed value object. The eval plane adds no kinds, no
events, no tables, no credentials.

## 3. Per-point contracts

### `ModelProvider` — a model backend

* **operations**: `invoke`, `describe`
* **refused code**: `PROPOSAL` — a model that emits a decision-shaped
  output is refused; a model never authorises a transition.
* **registration shape**: `ModelProvider(name, model_id, decision_vocabulary)`
* **worked example** (`ExampleModelProvider`): a stub that returns a
  single canned proposal; the test suite invokes `primary()` and
  asserts the returned `ExampleOutcome.value` is a dict with
  `model_id` and `text` (the canned response).

### `Tool` — a capability provider

* **operations**: `invoke`, `describe`
* **refused code**: `ROLE` — a mutating tool is refused before
  anything else (the capability plane's
  `test_a_mutating_tool_refuses_role_before_anything_else`).
* **registration shape**: `Tool(tool_id, protocol, hazard_class)`
* **worked example** (`ExampleTool`): a stub that returns a single
  canned observation; the test suite asserts the returned value is
  a dict with `tool_id` and `observation`.

### `ToolSet` — a named composition

* **operations**: `enumerate`
* **refused code**: `ROLE` — a composition cannot widen authority.
* **registration shape**: `ToolSet(set_id, capability_ids)`
* **worked example** (`ExampleToolSet`): a fixed composition of two
  `ExampleTool`s; the test suite asserts the enumeration lists both
  tool ids and the set id is the documented "read-only-set".

### `AgentRole` — a profile

* **operations**: `draft`, `allowlist`
* **refused code**: `ROLE` — a kind outside the role's allowlist is
  refused; an internal-only kind on a non-DETERMINISTIC role is refused.
* **registration shape**: `AgentRole(profile, proposable_kinds)`
* **worked example** (`ExampleAgentRole`): a stub that names a profile
  and its allowlist; the test suite asserts the allowlist contains
  exactly the documented kinds and the role is a closed value object.

### `Workflow` — a methodology document

* **operations**: `parse`, `run`
* **refused code**: `MALFORMED_PAYLOAD` — a workflow missing a
  required key refuses; a workflow with an unknown stage refuses.
* **registration shape**: `Workflow(methodology_id, version, stages, termination)`
* **worked example** (`ExampleWorkflow`): a minimal document with
  three stages; the test suite asserts the parsed stages are exactly
  the documented names and the methodology id matches.

### `StorageBackend` — a content-addressed store

* **operations**: `put`, `get`
* **refused code**: `STALE` — an attempt to overwrite a committed
  digest is refused as stale; the store is append-only.
* **registration shape**: `StorageBackend(backend_id, scheme)`
* **worked example** (`ExampleStorageBackend`): an in-memory
  content-addressed store. The test suite `put`s one digest, then
  `put`s the same digest with a different value and asserts the
  second call returns a `STALE` refusal.

### `EventSink` — a derived-only consumer (B-5)

* **operations**: `observe`
* **refused code**: `ROLE` — a sink that asks to author state is
  refused; sinks are readers, not writers.
* **registration shape**: `EventSink(sink_id, handler_dependencies)`
* **worked example** (`ExampleEventSink`): an in-process list that
  records each observed event; the test suite asserts the sink
  records, never persists (a sink's `observe` does not write to
  any store; the test asserts `len(self._received) == 1` after one
  `observe`).

### `GovernancePolicy` — the action→authority matrix

* **operations**: `lookup`
* **refused code**: `MALFORMED_PAYLOAD` — a policy row that names an
  unknown code is refused at construction (the governance plane's
  `test_a_row_naming_an_unknown_code_is_refused_at_construction`).
* **registration shape**: `GovernancePolicy(version, rows)`
* **worked example** (`ExampleGovernancePolicy`): an immutable three-row
  table; the test suite asserts a `WEB_SEARCH` lookup returns
  `AGENT`, a `PUBLISH` lookup returns `HUMAN`, and a `HACK` lookup
  returns a `MALFORMED_PAYLOAD` refusal.

### `Evaluator` — an evaluator

* **operations**: `evaluate`
* **refused code**: `MALFORMED_PAYLOAD` — a malformed registry is
  refused; this is what keeps the eval plane honest about its own
  construction.
* **registration shape**: `Evaluator(name, signature)`
* **worked example** (`ExampleEvaluator`): a stub whose `primary`
  returns its name. The test suite asserts the worked example is a
  pure value object (no I/O, no clock, no socket).

## 4. The runtime registry

`ExtensionRegistry` is the **process-local** registry of installed
extensions. It is constructed once, then read: ``__post_init__``
copies the entries into a `MappingProxyType`, so `entries[name] = ...`
and `del entries[name]` raise `TypeError`, and the mapping exposes no
mutator at all (`clear`, `pop`, `popitem`, `setdefault`, `update` are
absent). There is no in-place mutation; the only way to install an
extension is at construction time. The copy is a **snapshot**: a caller
that mutates the mapping it passed in cannot install an extension after
construction:

```python
def register_extension(extension: Example) -> ExtensionRegistry:
    """Construct a fresh registry containing only the supplied extension."""
    return ExtensionRegistry(entries={extension.name: extension})
```

A caller that wants multiple extensions passes them as a sequence
through a single construction. The factory is **declarative**: the
registry holds the name and the instance, the registry never persists
either. A caller that wants durability re-enters through `apply_intent`.

## 5. Worked-example pin

The test suite exercises every worked example. A future extension
must provide a worked example too; a missing one is a construction
error in the registry, not a green pass.

## 6. Stated limits (R7-FIX3)

Three boundaries are recorded here so a reader can tell a *deliberate*
limit from an oversight. None of them is a gap the eval plane closes by
adding a refusal code or an authority — the plane is still pure
evaluation, and the extension vocabulary is still frozen at nine.

1. **Secret redaction keeps its shape rules fenced.** The free-text
   shape rules match only a *word-bounded* credential. A rule broad
   enough to also match a credential abutted by more identifier
   characters (``sekret-abc123tail``) was measured against 5,155 tokens
   harvested from this repository's own ``src/`` and ``tests/`` and
   destroyed **82%** of ordinary log text, so the fence is kept. The
   general answer to an abutted literal is the **registered-literal
   affix rule**: a credential the caller actually holds is registered
   (``ops.register_secret``, and ``ops.authenticate`` registers the token
   it consumes) and then matched as a raw substring that absorbs its own
   ``[A-Za-z0-9_-]`` glue. A credential the process has never seen and
   that carries no shape is, by construction, indistinguishable from
   prose.

2. **Split-secret reassembly is out of contract.** Redaction is applied
   per string. A secret split across two positions is redacted wherever
   either half is individually recognisable, so no half is written
   verbatim on its own; the layer does **not** reassemble a payload to
   test whether two individually-innocuous fragments concatenate into a
   credential. That is a property of a per-string redactor, stated rather
   than chased.

3. **The import gate reports what it can evaluate.** The gate resolves
   declared imports, foldable dynamic imports, indirect importers
   (``getattr(importlib, …)``, aliased ``__import__``/``import_module``)
   and ``exec``/``eval`` of a string, and it refuses to silently pass a
   dynamic-code construct it cannot resolve (``unevaluable``). It does
   not claim to evaluate arbitrary computation: a name produced by an
   unenumerated runtime function is caught by the ``sys.modules`` witness
   only when the governed module is actually loaded and the file names the
   package. This is why the module docstring no longer claims a spelling
   "no ... evades" (see ``R7_REREPORT2.md``).
