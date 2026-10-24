# OPS-7 — operational notes

OPS-7 fixes the input-projection defect found by the first live run: the stage
context now carries the operator's question and ref ids as a `runtime.task`
envelope, so the question reaches the model instead of stopping at the
governance rationale. This note records the gap the next slice must own and
two facts the change surfaced. It is not a design gate and changes no
governed document.

## F2 — a failed run leaves no diagnostic (recorded, not fixed)

The first live run ended with a summary line, a quarantine note and a vector,
but none of them says *why* the drafts were refused. The supervisor trace that
holds the refusal codes is in-memory: `RuntimeWiring` builds it per stage run,
`on_stage` hands it to the vector sink, and it dies with `hermes run`. The
`vector:` line carries counts (calls, admitted, M1/M2), not codes. After the
process exits, the operator cannot recover the refusal sequence, the failing
provider attempt, or the quarantine reason without re-running the same inputs.

This is the next operational gap. A durable run report — the per-attempt
provider/model outcomes, refusal codes, stage outcomes, quarantine reason and
the run's terminal state, written at the run boundary — is its own slice. It
must not become a second write path: the append-only journal remains the one
durable record, and a run report either derives from it or is admitted through
`apply_intent`. OPS-7 neither implements nor papers over it.

## Surfaced — an empty question still meets the substrate floor

The projection treats an empty question as data: `project_stage` does not
raise, the stage runs, and the model sees an empty `question` in its
`runtime.task` envelope. The pre-existing substrate rule then refuses to
*record* a `QUESTION` node with a blank question
(`MALFORMED_PAYLOAD: a QUESTION node needs a non-empty 'question'`). That
floor is unchanged by this slice; changing it would be a separate domain
decision, not an input-projection fix.

## Surfaced — the plane-internal driver is not the operator path

`hermes.methodology.workflows.run_methodology` (the methodology plane's own
driver, exercised by the swap fixture) builds its own `TaskContext` and still
does not project `MethodologyInputs`. OPS-7 fixes the live W3 driver
(`hermes.research.task_handlers.methodology_driver.py`), which is the path
`hermes run` composes. If the plane-internal driver ever becomes an operator
surface, it needs the same `runtime.task` projection.
