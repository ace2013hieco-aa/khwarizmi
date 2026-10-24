# OPS-9 — operational notes

OPS-9 renders two validator rules into the contract: the mutually exclusive
single/multi proposal forms and the legal delegation keys. Both statements are
generated from the validator's own constants; the validator remains the
authority. This note records F2's new urgency, the run-3 provider flake, the
remaining rule layers, and the metric fact.

## F2 is now blocking the loop itself

Finding the OPS-9 layer required composing the controller in-process and
reading `ProposalSet.refusals` by hand — twice. An operator cannot do that.
The durable run report is the next slice after this one, and it must carry
refusal **codes** and the attempt outcome, not just counts. Without it, every
new validator layer costs a live run and an in-process post-mortem.

## Run 3 provider flake (observed, not fixed)

Model call 8 returned `PERMANENT (in 0, out 0)` — a provider-level failure with
no tokens. This is recorded as an observed flake; OPS-9 adds no retry logic. A
retry policy is a separate decision and must respect the run's bounds.

## Remaining validator rules (not covered here)

Observed in `_validate_drafts`, `_validate_tool_calls` and
`_delegation_phase`:

- The top-level output may carry only `kind`, `rationale`, `payload` plus the
  profile's `structured_fields`; an unknown top-level key is refused. The
  contract lists the fields but does not say "no other keys".
- `proposals` must be a list; each item must be a mapping and may carry only
  `kind`, `rationale`, `payload`; `kind` is required and must be an
  `IntentKind` inside the profile's authority; the rationale must be non-empty
  and the payload a mapping. Authored identity keys are refused, and the
  4 KiB cap applies.
- `tool_calls` must be a list of mappings, each carrying only `capability_id`,
  `arguments`, `rationale`; the batch is refused whole when over the bound; the
  capability must be declared and granted.
- `delegations` must be a list of mappings. The keys are now named, but the
  child `profile` must be declared, `spec` is a mapping, `task_type` is
  constrained, and the child-depth/allowance bounds apply.
- `rationale` is required non-empty (already stated); the legal `kind` values
  are stated by OPS-8; the two forms and the delegation keys are stated by
  OPS-9.

The next slice should pick the highest-value uncovered rule — likely the
top-level "no other keys" rule and the `tool_calls`/`proposals` item schemas —
rather than trying to enumerate every validator rule at once.

## Metric

M1 remains 304: the contract is the system message, not the user prompt M1
measures. The system prompt grows by 321 bytes for every profile (the two new
statements are profile-invariant).
