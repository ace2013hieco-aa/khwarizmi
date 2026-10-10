"""Task handlers — the spine-owned shim package (wiring plan W1, BIND-1).

`WIRING_DESIGN.md` §6 reserves this package for the wiring slices. W1 created it
as an inert marker; **W4 adds the registration export** — the seam W1 reserved
for exactly this — and the marker stays import-light: every builder here
imports its collaborators lazily inside the function that needs them, so
importing this module still executes no other module.

What the registration export is
-------------------------------
The controller dispatches a handler-backed task through two duck-typed calls
(`controller.py` `_run_handler`): ``entry.build_context(task, project_id,
repos)`` and ``entry(ctx) -> HandlerResult``. A wiring template additionally
needs what only the controller can hand it — its **fenced** mutation surface
(`apply_intent` on the held-lease connection) and the lease generation it is
acting under. W4's single controller call site binds that:

```python
handler = build_methodology_handler(...)           # composition root
ctrl = Controller(conn, project_id=..., task_handlers={"methodology_run": handler})
# per dispatch, the controller calls
#   entry.bind_controller(orchestration=<apply_intent on the fenced conn>,
#                         lease_generation=<current scheduler generation>)
```

- `build_capability_handler` — the W1 `capability_handler` bridge (a template
  key → capability invocation) as a controller-dispatchable entry: dispatch,
  then admit the observation as an ordinary `INSERT_TASK` through the bound
  applier. No new kind, and no authored identity: the follow-up task's id and
  idempotency key are derived by the runtime plane's own rules.
- `build_methodology_handler` — the W3 `methodology_driver` as an entry: the
  task's spec carries the workflow document and its inputs; each stage drives
  the W2 `RuntimeWiring` under the bound lease generation; every durable effect
  is an intent the stage's run admits through the bound applier.
- `handoff_to_handler_result` — the `ObservationHandoff` → `HandlerResult`
  adaptation (W1's bridge returns a handoff, never the controller's verdict
  type). Refusals stay refusals-as-data.

Import discipline (§3.1 — "ports + core types only")
----------------------------------------------------
Modules under this package are spine-side handlers. They speak to the planes
through port protocols and core types, and they hold **no write surface**:
never `hermes.persistence`, never a repository, never a raw SQLite connection
or transaction. The one write path a wired entry can reach is the applier the
controller BINDS into it — the spine's `apply_intent`, on the controller's
fenced connection. Each slice's test suite pins this mechanically.

Modules (added slice by slice, none before it lands):

- `capability_handler` — W1, BIND-1: capability call dispatch.
- `methodology_driver` — W3, BIND-5: the methodology execution driver.
- this module — W4: the registration export + the handoff adaptation.

The W2 modules live where their slice landed them (`hermes.tools.models.binding`
and `hermes.agents.runtime.wiring`); this package depends on them by import,
never the other way round.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping

if TYPE_CHECKING:  # pragma: no cover — annotation-only, never imported at run time
    from hermes.agents.runtime.run import IntentApplier

__all__ = [
    "WIRING_TEMPLATE_FLAG",
    "WiringTaskHandler",
    "build_capability_handler",
    "build_methodology_handler",
    "handoff_to_handler_result",
]

#: The entry attribute (class-level, so it survives binding) the controller's
#: single wiring call site reads to recognize a wiring template: the entry is
#: bound to the controller's fenced write surface, and its completion is
#: verified against its own record rather than a source outcome.
WIRING_TEMPLATE_FLAG = "wiring_template"


@dataclass(frozen=True, slots=True)
class _WiringContext:
    """What a wiring dispatch is given: the task row and its project — no more.

    Deliberately no connection, no repository, no gateway and no controller: an
    entry cannot reach a write surface because there is none to reach. The one
    durable path is the applier the controller binds in.
    """

    task: dict
    project_id: str


def handoff_to_handler_result(handoff: Any, *, admitted: bool = False) -> Any:
    """`ObservationHandoff` → `HandlerResult` — the W4 registration adaptation.

    W1's bridge returns an `ObservationHandoff`, never the controller's
    `HandlerResult` (W1_REPORT §6.3); this function is the one place the two
    shapes meet. It is total and refusal-as-data:

    - a dispatch/plane refusal (``rejected``) or an unregistered key
      (``status == "unhandled"``) → ``status="failed_typed"`` carrying the
      frozen code (or the fail-closed sentinel) in its reason — an exception is
      never the answer, and a refusal is never a silent success;
    - a plane observation that the caller has **not** admitted through the one
      write path → ``status="failed_typed"`` with the design's own refusal code
      `PROPOSAL` (BIND-1: *output treated as evidence without repository write
      → `PROPOSAL`*) — an observation alone is not a verdict;
    - a plane observation whose ordinary admission intent reached the write path
      (``admitted=True``, the caller's record) → ``status="completed"`` with
      ``outcome_recorded=True``.
    """
    from hermes.research.source_handlers import HandlerResult

    if handoff.rejected or handoff.status == "unhandled":
        code = str(handoff.code or handoff.status)
        detail = str(handoff.detail or "")
        return HandlerResult(status="failed_typed",
                             reason=f"{code}: {detail}" if detail else code,
                             outcome_recorded=False)
    if admitted:
        return HandlerResult(status="completed", outcome_recorded=True)
    return HandlerResult(
        status="failed_typed",
        reason=("PROPOSAL: the observation was not admitted through the one "
                "write path — an observation without a repository write is "
                "not a verdict (BIND-1)"),
        outcome_recorded=False)


class WiringTaskHandler:
    """One wiring-template handler entry for the controller's `_task_handlers`.

    The controller's dispatch contract needs a ``build_context`` builder and a
    ``__call__`` returning a `HandlerResult` (HD-02). A wiring entry needs one
    thing more — the controller's **fenced** write surface and the lease
    generation currently held — and that is the W4 binding:
    ``bind_controller(orchestration=…, lease_generation=…)`` returns a bound
    copy whose accessors are read per dispatch. An unbound entry fails closed:
    without the controller's applier it has no write path, and guessing one is
    exactly the second writer this design forbids.

    The entry itself holds no connection, no repository, no journal and no SQL.
    """

    wiring_template = True

    def __init__(self, *, template: str, runner: Callable[..., Any]) -> None:
        self.template = str(template).strip().casefold()
        self._runner = runner
        self._orchestration: IntentApplier | None = None
        self._lease_generation: Callable[[], str] | None = None

    # ── the controller contract ──

    def build_context(self, task: dict, project_id: str,
                      repos: Any) -> _WiringContext:
        """The typed bundle for one dispatch — the task row and its project.

        A wiring entry reads no repos: its outcome is a proposal admitted
        through the bound applier, never a direct write, so the context
        deliberately carries no write surface at all.
        """
        return _WiringContext(task=dict(task), project_id=project_id)

    def bind_controller(self, *, orchestration: IntentApplier,
                        lease_generation: Callable[[], str]
                        ) -> "WiringTaskHandler":
        """Bind to the controller's live fenced surface — the one call site."""
        bound = WiringTaskHandler(template=self.template, runner=self._runner)
        bound._orchestration = orchestration
        bound._lease_generation = lease_generation
        return bound

    def __call__(self, ctx: _WiringContext) -> Any:
        if self._orchestration is None or self._lease_generation is None:
            raise RuntimeError(
                "a wiring handler must be bound by the controller before it is "
                "dispatched (bind_controller) — an unbound entry has no write "
                "path, and this is a composition error, never a silent skip")
        return self._runner(ctx, self._orchestration, self._lease_generation)


def build_capability_handler(
    *,
    template: str,
    registry: Any,
    port: Any,
    profile: str,
    grant: Any,
    admission_actor: str,
    child_template: str,
) -> WiringTaskHandler:
    """The W1 registration export: one capability template → the controller.

    `template` must already be registered in the W1 `CapabilityDispatchRegistry`
    (the bridge answers `unhandled` otherwise — fail closed, never a guess).
    The dispatch context is built from the task row: its own idempotency key,
    the declared arguments from ``spec["arguments"]``, and the composition's
    grant/profile. A refusal (dispatch-level or plane-level) is returned as
    data. An observation is admitted as an ordinary `INSERT_TASK` (the existing
    LLM-proposable kind; no new kind): the follow-up task's id and idempotency
    key are DERIVED by the runtime plane's own rules from the dispatched task,
    so a re-dispatch re-emits the same command and the spine answers duplicate
    instead of admitting a second row.
    """
    def _run(ctx: _WiringContext, orchestration: IntentApplier,
             lease_generation: Callable[[], str]) -> Any:
        from hermes.core.intents import IntentRejectedError
        from hermes.research.source_handlers import HandlerResult
        from hermes.research.task_handlers.capability_handler import (
            UNHANDLED,
            DispatchContext,
        )

        task = ctx.task
        spec = task.get("spec") or {}
        handoff = registry.dispatch(
            template,
            port=port,
            context=DispatchContext(
                task_id=str(task.get("task_id", "")),
                project_id=ctx.project_id,
                lease_generation=lease_generation(),
                profile=profile,
                idempotency_key=str(task.get("idempotency_key") or template),
                grant=grant,
                arguments=dict(spec.get("arguments") or {})))
        if handoff.rejected or handoff.status == UNHANDLED:
            return handoff_to_handler_result(handoff)
        intent = _observation_admission_intent(
            handoff, ctx=ctx, actor=admission_actor,
            child_template=child_template)
        try:
            orchestration(intent)
        except IntentRejectedError as exc:
            # The admission was refused: the refusal is the verdict, as data.
            code = str(getattr(exc, "code", "") or "PROPOSAL")
            return HandlerResult(
                status="failed_typed",
                reason=f"{code}: {exc}",
                outcome_recorded=False)
        return handoff_to_handler_result(handoff, admitted=True)

    return WiringTaskHandler(template=template, runner=_run)


def build_methodology_handler(
    *,
    template: str = "methodology_run",
    model: Any,
    profiles: Mapping[str, Any],
    grants: Mapping[str, Any] | None = None,
    capabilities: Any = None,
    artifacts: Any = None,
    actor: str = "methodology-driver",
    governance_context: Any = None,
) -> WiringTaskHandler:
    """The W3 registration export: one methodology template → the controller.

    The task's ``spec["methodology"]`` carries the workflow document and
    ``spec["inputs"]`` the run's inputs (``question``, ``external_refs``,
    ``admission_refs``, ``retracted_refs``, ``stage_content``). Each stage runs
    on a per-dispatch W2 `RuntimeWiring` assembled from the composition's model
    port and profiles, under the controller's bound applier and lease
    generation; every durable effect a stage produces is an ordinary intent its
    run admits through that applier (in production, `apply_intent` — the one
    write path). Substrate nodes stay derived in-process working state: the
    §8 item 9 durability gate is untouched, and `run_methodology` refuses any
    durability claim as data.

    ``governance_context`` is passed straight to `MethodologyInputs` — the
    snapshot rows the methodology plane's own declared governance consumer
    evaluates. It is deliberately untyped here: this package does not import
    the governance plane (BIND-4's consumer set).
    """
    def _run(ctx: _WiringContext, orchestration: IntentApplier,
             lease_generation: Callable[[], str]) -> Any:
        from hermes.agents.runtime.wiring import RuntimeWiring
        from hermes.methodology.substrate import MALFORMED_PAYLOAD as _PLANE_MALFORMED
        from hermes.methodology.workflows import MethodologyRefusal
        from hermes.research.source_handlers import HandlerResult
        from hermes.research.task_handlers.methodology_driver import (
            parse_workflow,
            run_methodology,
        )

        task = ctx.task
        spec = task.get("spec") or {}
        document = spec.get("methodology")
        if not isinstance(document, Mapping):
            return HandlerResult(
                status="failed_typed",
                reason=(f"{_PLANE_MALFORMED}: spec.methodology must be a "
                        f"workflow document mapping, got "
                        f"{type(document).__name__}"),
                outcome_recorded=False)
        parsed = parse_workflow(document)
        if isinstance(parsed, MethodologyRefusal):
            return HandlerResult(status="failed_typed",
                                 reason=f"{parsed.code}: {parsed.detail}",
                                 outcome_recorded=False)
        inputs = _inputs_from_spec(spec.get("inputs") or {},
                                   governance_context=governance_context)
        wiring = RuntimeWiring(
            model=model,
            orchestration=orchestration,
            lease_generation=lease_generation(),
            profiles=profiles,
            grants=grants,
            capabilities=capabilities,
            artifacts=artifacts)
        execution = run_methodology(
            parsed, inputs, wiring=wiring, project_id=ctx.project_id,
            task_id=str(task.get("task_id", "")), actor=actor)
        if isinstance(execution, MethodologyRefusal):
            return HandlerResult(status="failed_typed",
                                 reason=f"{execution.code}: {execution.detail}",
                                 outcome_recorded=False)
        applied = sum(stage.intents_applied for stage in execution.stages)
        if applied == 0:
            # S6-B2 at the entry: a completion that recorded nothing through
            # the one write path is not an outcome — the capability path's
            # unadmitted observation (:124-129) is the same code family and
            # reason shape, so a zero-admission run fails closed and never
            # claims completed.
            return HandlerResult(
                status="failed_typed",
                reason=("PROPOSAL: methodology completed with 0 admissions "
                        "via apply_intent — an effectless run is not a "
                        "recorded outcome (S6-B2)"),
                outcome_recorded=False)
        return HandlerResult(
            status="completed",
            outcome_recorded=True,
            reason=(f"methodology {execution.methodology_id!r} "
                    f"{execution.termination} over {len(execution.stages)} "
                    f"stage(s); {applied} admission(s) via apply_intent; "
                    f"substrate derived in-process only"))

    return WiringTaskHandler(template=template, runner=_run)


# ── pure helpers (no I/O, no writes) ──


def _observation_admission_intent(handoff: Any, *, ctx: _WiringContext,
                                  actor: str, child_template: str) -> Any:
    """The ordinary `INSERT_TASK` an observation round-trips through.

    Existing kind only, derived identity only: the follow-up task's id and
    idempotency key come from the runtime plane's own derivation rules, so the
    writer never authors identity, and a re-emit answers duplicate instead of
    admitting a second row. The handoff's record (no payload text) rides in
    the spec.
    """
    from hermes.agents.runtime.types import (
        child_idempotency_key_of,
        child_task_id_of,
    )
    from hermes.core.intents import Intent, IntentKind

    parent = str(ctx.task.get("task_id", ""))
    follow_up_spec = {
        "template": str(child_template),
        "observation": handoff.as_record(),
    }
    return Intent(
        kind=IntentKind.INSERT_TASK,
        proposed_by=actor,
        project_id=ctx.project_id,
        payload={
            "task_id": child_task_id_of(parent, actor, 0),
            "task_type": "AGENT_TASK",
            "profile": actor,
            "spec": follow_up_spec,
            "inputs": [],
            "outputs": [],
            "dependencies": [],
            "provenance": [
                f"wiring:{handoff.template_key}:{handoff.observation_digest}"
            ],
            "idempotency_key": child_idempotency_key_of(
                parent, actor, 0, follow_up_spec),
            "iteration": 1,
            "cost_class": "LOW",
        },
        justification=(
            f"capability observation {handoff.capability_id!r} for template "
            f"{handoff.template_key!r} admitted as an ordinary follow-up task "
            f"(the one write path admits; the observation is a proposal)"),
        origin_kind="deterministic",
        origin_ref=parent)


def _inputs_from_spec(raw: Any, *, governance_context: Any) -> Any:
    """Map a task spec's `inputs` mapping onto `MethodologyInputs`."""
    from hermes.methodology.workflows import MethodologyInputs

    data = raw if isinstance(raw, Mapping) else {}
    external = data.get("external_refs") or {}
    return MethodologyInputs(
        question=str(data.get("question", "")),
        external_refs=dict(external),
        admission_refs=tuple(str(ref) for ref in
                             (data.get("admission_refs") or ())),
        retracted_refs=tuple(str(ref) for ref in
                             (data.get("retracted_refs") or ())),
        stage_content=dict(data.get("stage_content") or {}),
        governance_context=governance_context)
