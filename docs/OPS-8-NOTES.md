# OPS-8 — operational notes

OPS-8 makes the profile's declared `proposable_kinds` visible in the contract
the model reads. The allowlist is still the authority; the listing is guidance.
This note records the live-run chain that produced the slice and the metric
fact the charter's next comparison depends on. It is not a design gate and
changes no governed document.

## F3 — the run chain (recorded, not fixed)

Three live runs have each exposed one layer:

1. **OPS-7 — no question.** The stage context never carried the operator's
   input; M1 was 82 bytes and the model was asked to review literature with no
   question.
2. **OPS-8 — no legal kinds.** With the question present, the model invented
   `kind: "task-graph-planning"`; the runtime refused it `ROLE` because the
   prompt had never named the closed set the profile enforces. Zero
   admissions, every stage.
3. **F2 — no diagnostic.** The refusal codes live in an in-memory supervisor
   trace and die with `hermes run`; the operator sees counts, not codes. This
   is recorded in `docs/OPS-7-NOTES.md` as the next operational gap.

The common cause is that every unit test scripts the reply that a real model
has to invent. A scripted reply already uses a legal kind and already ignores
the missing question, so the suite can be green while the operator path cannot
produce a single admission. **A live run is the only instrument that finds
these layers.** A green suite is evidence about the scripted corpus, not about
the operator's run.

F3 is recorded, not fixed: each future live run should be read as the next
instrument, and its refusals should be captured before the process exits (the
durable run report that owns F2).

## M1 does not measure the contract

OPS-8 puts the legal kinds in the **system** message — the contract beside the
field description. M1 measures `request.prompt` only, so it does not move for
this change: the second run's M1 stays 304 for the same supplied question. The
system prompt grows by 90–124 bytes depending on the profile (planner +93,
critic +124); the next live run should be compared on system/contract bytes or
input tokens, not M1.

Making M1 include the system text would change the metric the LOOP baseline is
pinned on, so it is not done here. The baseline is unchanged.
