# OPS-5I — the unreachable form

| Item | Value |
| --- | --- |
| Decision | **The multi-proposal form cannot be used in this build; decide whether to make it work or remove it.** |
| Recorded by | OPS-5H phase 2 (2026-10-26), as the Director's ruling on the contradiction the OPS-5H gate surfaced |
| Status | **OPEN** — the instruction was corrected in OPS-5H; the form's fate is this decision |
| Touches | OPS-9's form semantics; not OPS-5H's predicate |

## The finding

A reply that uses the multi-proposal form (`"proposals": [...]`) fails one of
two checks, whichever shape it takes:

1. **Without a top-level `kind`** it dies at the model plane's kind check —
   `router.py:2095` at the OPS-5H base (`5f44a27`; the check is at
   `router.py:2114` after OPS-5H): `ROLE`, *model proposed kind None, outside
   the injected proposable allowlist*.
2. **With a top-level `kind`** it dies at the runtime's both-forms check —
   `run.py:1071` at the base (now `run.py:1075`): `MALFORMED_PAYLOAD`, *the
   model output carries both the single-proposal and the multi-proposal form —
   exactly one is allowed*.

There is no third shape: the plane's kind check is not conditioned on the form,
and the runtime's both-forms check is. Every multi-form reply therefore fails
one of the two, and the form cannot be used.

## What OPS-5H did about it

**Corrected the instruction, not the validator.** The rendered note used to say
`kind` was *"required in the single-proposal form; omit it in the
multi-proposal form"* and offered a choice between the two forms. It now states
one form and says the other is refused:

```text
The top-level "kind" field is required: the single-proposal form is the only
proposal form in this build, and a reply carrying a non-empty "proposals" array
is refused.
```

and the field note reads `not usable in this build; a non-empty array is
refused`. Validator behaviour is unchanged; the pin is
`tests/test_ops5h_tool_only_tick.py::test_the_note_no_longer_offers_the_multi_proposal_form`
and the two refusal halves
(`test_a_multi_form_reply_refuses_without_a_top_level_kind`,
`test_a_multi_form_reply_refuses_at_the_runtime`).

## The decision this record leaves open

Two ways out, and neither is OPS-5H's:

- **Make it work** — skip the kind check when the multi-form field carries a
  non-empty list (the runtime validates each item's kind, including the
  profile's authority, at `run.py:1104-1118`), and relax the both-forms rule so
  a top-level `kind` beside `proposals` is not fatal. That is a validation
  change with its own falsifier and its own OPS-9 amendment.
- **Remove it** — drop `proposals` from the contracts and the validator, which
  is a vocabulary change to `structured_fields` and the draft schema.

Until one is decided, the note tells the truth and the form stays unreachable.

License: Apache-2.0 (LICENSE).
