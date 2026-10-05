# IDR-SKELETON: the template + numbering policy for IDR records

This is the skeleton every IDR record follows. Copy it for a new record;
never edit an existing record's decision text (append a dated addendum if a
record's status changes).

**IDR-numbering policy:** IDR numbers are mainline-scoped. Side-branch usage never reserves a mainline slot. On merge, incoming records keep their numbers iff free, else are renumbered with the mapping recorded in the merge commit message. (Live example: IDR-042/043 are labels in unmerged side history — their slots are free on mainline.)

## Skeleton

```markdown
# IDR-NNN: <one-line decision title>

**Status:** <Decided | Decided + implemented + tested | RATIFIED | DEFERRED | ...>
**Date:** <YYYY-MM-DD>
**Decides for:** <the question this record settles, one sentence>

## Context
<the problem, the live constraints, what the baseline assumes>

## Constraints
<hard boundaries the decision had to respect>

## Decisions
<the decision(s), numbered, each falsifiable>

## Acceptance
<what proves it — the green gates/fixtures, enumerated>

## Relation-to-baseline
<which certified invariants are touched (must be none unless a design gate
says otherwise), which deferred stances this operationalizes, and what any
follow-up slice owes>
```
