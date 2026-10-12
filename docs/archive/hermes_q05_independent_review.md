# Q-05 — Independent Closure Review

**Reviewer:** Claude (Anthropic), no prior authorship of any Q-05 code, design
doc, or self-audit in this repository.
**Reviewed against:** commit `612ea5d` ("Q-05 CLOSED...") and live HEAD
`dedeec5` on `main` (working tree clean, identical Q-05 files at both).
**Repo:** `ace2013hieco-aa/khwarizmi-research` (confirmed via `git remote -v`;
the local folder name `research-agent` is unrelated — no naming conflict).
**Method:** direct reading of `src/hermes/research/failure_classification.py`,
`src/hermes/persistence/failure_classifications.py`, IDR-036, IDR-037, and
`hermes_q05_post_adversarial_remediation.md`, plus live execution of the test
suite and a fresh adversarial probe constructed independently of the
existing test matrix (not a re-run of the implementer's own X1–X12/F1–F4
attacks).

## 1. Why this review exists

`612ea5d`, IDR-036, IDR-037, and the remediation doc all state — accurately
and consistently — that the prior "adversarial review" (§10 of
`hermes_q05_post_adversarial_remediation.md`) was performed by the
implementation agent itself, at operator instruction, and explicitly
disclaim "INDEPENDENTLY VERIFIED by an external party." That disclaimer is
correct: an implementer auditing their own work, however carefully, cannot
rule out the specific blind spot of not having conceived of a test in the
first place. This review is that missing external pass.

## 2. Empirical verification (run fresh, not read from documentation)

| Check | Result |
|---|---|
| `test_failure_classification.py` + `test_q05_persistence.py`, run directly | 95 collected (42 + 53), all pass, exit code 0 |
| Full suite (`pytest -q`) | 1154 collected, all pass, exit code 0 (grew from the documented 997 at closure time — consistent with later Q-02/Q-04 commits, not a discrepancy) |
| `uvx pyright src` | 0 errors, 0 warnings |
| Substrate imports (`failure_classification.py`) | stdlib + `hermes.research.programs` only — no SQL, no repository/gateway imports, confirmed by direct read, not by trusting the docstring's claim |
| Persistence writes (`failure_classifications.py`) | writes only to the existing `artifacts` + `provenance_edges` tables, as documented; no new tables, no new event types, confirmed by direct read |

The documented numeric claims check out. This is not itself the finding —
matching your own numbers is a necessary, not sufficient, bar for
independence.

## 3. Design points that hold up under independent reading

- Renaming `HARD_AXIOM_VIOLATION` → `DECLARED_CONSTRAINT_VIOLATION` is the
  right call — "axiom" genuinely has no carrier in this codebase, and the
  substitute (declared `falsification_condition` / `methodology_constraint`)
  is a real, resolvable Hermes object, not a rationalization.
- `UNKNOWN` as a sixth class, disjoint from a rejected `MULTI_FACTOR`
  catch-all, is the correct choice — a catch-all would have hidden the
  primary and broken the action map's determinism.
- The action map (`ACTION_MAP`) is genuinely inert: every value is a
  proposal category, and I confirmed by reading `PermittedAction` that none
  of its members name a create/mutate operation. Authority is enforced by
  the *absence* of capability (no SQL/repository import in the module at
  all), not by a convention someone could forget to check — this is a
  stronger guarantee than most "advisory-only" designs achieve.
- The resolver-immutability argument in the remediation doc (§3) is sound:
  `research_programs` and `scope_briefs` having no UPDATE/DELETE path is a
  real structural fact I'd want to double check independently, but the
  reasoning built on top of it (pre-transaction resolution is stable) is
  valid *given* that premise.

## 4. Finding — `contributing_factors` carries no citation requirement and no effect on gating (MEDIUM)

**What I did.** The existing test matrix (X1–X12, F1–F4) is entirely about
identity, persistence, and resolver integrity. None of it probes the
*semantic* completeness of `contributing_factors`. I read `_validate_class_citations`
and `requires_human_confirmation_for` and noticed both operate on
`draft.failure_class` (the primary) only — `contributing_factors` is
validated for vocabulary membership, disjointness, and uniqueness
(`_validate_contributing_factors`) and nothing else. I then constructed a
fresh probe, independent of the existing fixtures, against the live module:

```python
draft = FailureClassificationDraft(
    failure_class=FailureClass.IMPLEMENTATION_FAILURE.value,
    explanation="mechanism failed",
    evidence_refs=("validation:ev1",),
    contributing_factors=(FailureClass.FRAMING_ERROR.value,),
    failed_mechanism_ref="prediction:P1",
    proposed_by="probe-agent",
    classifier_version="q05-2026.1",
)
result = classify_failure(record, draft,
                           evidence_resolver=evidence, mechanism_resolver=mechanism)
```

**Result, run against the live substrate:**

```
admitted: True
primary: FailureClass.IMPLEMENTATION_FAILURE
contributing_factors: (FailureClass.FRAMING_ERROR,)
permitted_actions: (PermittedAction.PROPOSE_MECHANISM_SUBSTITUTION,)
requires_human_confirmation: False
```

I then checked the persistence/digest layer (`failure_classifications.py`)
and confirmed the same pattern end to end: every call site —
`requires_human_confirmation_for` in the record-time write path, and again
in the digest's recompute-from-substrate step (`classifications_digest`) —
passes only `failure_class`, never `contributing_factors`. The gap is not a
missed spot in one layer; it is consistent through the whole read/write
surface.

**Why this matters.** IDR-036's own rationale (point 4) states: *"FRAMING_ERROR
is deliberately the most restricted class... no agent, LLM or otherwise, can
rewrite the brief through this mechanism."* That claim is true only when
FRAMING_ERROR is the *primary* class. As demonstrated above, a classifier —
LLM-proposed, per the module's own model-boundary design — can name any
other class as primary and list FRAMING_ERROR as merely "contributing," and
the system will: (a) require no citation at all for that contributing claim
(confirmed directly by the existing `test_h2_contributing_factors_validated`,
which admits `RESOURCE_CONSTRAINT` as a contributing factor with zero
resource-gap citation — this is an existing, intentional design choice, not
something I introduced), and (b) apply none of FRAMING_ERROR's safeguards —
no `requires_human_confirmation`, no restriction to `ROUTE_TO_SCOPE_REVIEW`.

**What is *not* at risk.** This is not an authority-boundary breach. The
`PROPOSE_MECHANISM_SUBSTITUTION` action in my probe still requires the
existing Director `PROPOSE_RESEARCH_PROGRAM` gateway per D2 — nothing is
auto-created, and the `contributing_factors` value is not hidden; it is
visible in the digest's `items[].contributing_factors` to whoever reads it.
The gap is specifically that the *stated safeguard* ("FRAMING_ERROR
implicates the ScopeBrief, so it requires human confirmation") silently
does not fire when framing doubt is present but demoted to secondary status
— which is exactly the shape of thing an LLM classifier under any pressure
to produce an actionable-looking primary class would be inclined to do,
even without any adversarial intent.

**Recommendation.** Not a blocker for the substrate's core soundness, but it
should be fixed before the IDR-036 rationale's point 4 is treated as an
accurate description of current behavior. Two independent, minimal fixes
(pick one, don't need both): (a) make `requires_human_confirmation_for` also
true whenever `FRAMING_ERROR ∈ {primary} ∪ contributing_factors`; or (b)
require the same class-specific citation discipline for contributing
factors that the primary class already has, so a `FRAMING_ERROR` contributor
can't be asserted for free. (a) is smaller and directly closes the gating
gap; (b) is more thorough but changes more surface. I'd lean toward (a) as
the immediate fix and treat (b) as a separate, optional hardening decision
Ace should make deliberately rather than one I'm bundling in here.

## 5. Minor notes (LOW — not blocking)

- `classifier_version` is validated only as a non-empty string with no
  registry/whitelist of known versions. It enters the content-derived
  `classification_id`, so this is a bookkeeping/audit-quality gap, not an
  authority gap — anyone can mint a new "version" identifier. Worth a
  registry check if `classifier_version` is ever used for anything beyond
  identity/versioning bookkeeping.
- No upper bound on `evidence_refs` length. Low practical risk (pure
  in-memory function, no I/O), not worth fixing unless this substrate is
  ever exposed to an untrusted caller directly.
- Minor semantic tension, not a defect: `UNKNOWN` (primary) can coexist with
  a non-empty `contributing_factors` list. If the classifier is honestly
  uncertain of the primary cause, asserting a specific contributing factor
  is a slightly odd combination — worth a design opinion from Ace, not a
  fix I'd insist on.

## 6. Verdict

**PASS, with one MEDIUM finding to remediate before the IDR-036 rationale
can be treated as accurate.** The substrate's core design — authority
enforced by absence of capability, fail-closed citation resolution, content-
derived identity, versioned reclassification, no silent pivot — holds up
under independent code reading and live execution, including a fresh
adversarial probe outside the existing test matrix. The one finding above
(§4) is real, reproducible against the current HEAD, and not covered by any
existing fixture; it does not compromise the authority boundary but does
undercut a specific, named claim in the ratifying IDR.

This review is independent in the sense that matters here: performed by a
different party than the implementer, using live execution and an
original probe rather than re-reading the implementer's own audit and
agreeing with it. It is not a claim of infallibility — a third pass by
yet another party could still find what I missed.

**Suggested governance status change**, pending Ace's decision:

    IMPLEMENTED + TESTED
    ARCHITECTURE ADOPTED BY OPERATOR
    INDEPENDENTLY REVIEWED (2026-08-15, Claude) — ONE MEDIUM FINDING OPEN
    RATIFIED / CLOSED — CONDITIONAL ON §4 REMEDIATION OR EXPLICIT ACCEPTANCE

Q-05 does not need to be reopened wholesale for this — a single, small,
well-scoped follow-up commit (§4 option (a)) would close it cleanly.

## 7. Follow-up: checking the resolver-immutability premise directly (requested)

I did not take §3's claim on faith this time — grepped the actual repository
rather than trusting the reasoning built on top of it.

**Confirmed as claimed:** no `UPDATE`/`DELETE` statement anywhere in `src`
touches `research_programs`. `ResearchProgramRepository`'s own class
docstring states "No UPDATE/DELETE path exists at all" (`repositories.py`
~line 845), and I read `record()` in full — it is insert/read-only, matching
the claim. Every actual `UPDATE` in the file targets `projects`, `tasks`, or
`research_assumptions` (a status flip to `SUPERSEDED`) — none touch
`research_programs` or `scope_briefs`.

**More specific than what was claimed, and worth flagging:** `scope_briefs`
has **no write path of any kind in `src`** — not "no UPDATE," no `INSERT`
either. Every `INSERT INTO scope_briefs` in the whole repository lives in a
*test* file (`test_gateway.py`, `test_q05_persistence.py`,
`test_research_program.py`, `test_v6_attacks.py`,
`test_walking_skeleton.py`), executed as raw SQL to seed fixtures.
`gateway.py` mentions `scope_brief:` only as a comment about a "future
lineage layer" — no implemented creation path exists yet.

**Why this matters for Q-05 specifically.** The immutability premise itself
still holds — a table nothing in production can write to is trivially
immutable, so §3's reasoning is not undermined. But it means the
FRAMING_ERROR citation path (`scope_brief_ref`/`scope_brief_field`, labeled
"AVAILABLE (best-effort)" in IDR-037 D5) is, in any real deployment today, in
the same practical position as `ENVIRONMENT_MISMATCH`'s regime resolver —
which D5 honestly labels "DEFERRED — fail closed." FRAMING_ERROR isn't given
that same label, even though a classifier proposing it has nothing to
resolve against until something outside `src` creates a ScopeBrief row.
Behavior is still safe (fail-closed refusal, not a false pass) — this is a
documentation-accuracy gap, not a new safety issue. **Recommendation:**
one-line correction to IDR-037 D5, labeling the scope resolver's current
real-world availability the same honest way the regime resolver already is.

This does not change the §6 verdict. It's a second, LOW-severity finding,
additive to the MEDIUM one in §4.
