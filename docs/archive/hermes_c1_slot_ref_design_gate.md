# HERMES C1 — `slot_ref` DESIGN-CONCEPT IDENTITY: DESIGN GATE

**Status:** DESIGN (2026-08-19) — no implementation, no schema change, no
code, no IDR. This is the design gate the five-fundamentals blueprint
requires before C1 may enter architecture: blueprint §21 lists C1 under
"Should probably become architecture (**after their own five-stage
loops**)", and §27 records C1's defenses as not-yet-implemented. This
document resolves blueprint §19 open question 2 (G2/C1) into a decidable
contract and pins the acceptance criteria the implementation must meet.
**Nothing here is ratified.** Implementation is gated on (a) ratification
of the five-fundamentals blueprint itself and (b) operator approval of
this gate's decisions.

> **Ratification update (2026-08-20, additive):** this contract was RATIFIED
> with the FULL-HISTORY slot-vocabulary reading by operator ratification —
> `hermes_architecture_ratification.md` §6.2 (architecture frozen;
> implementation separately chartered, Step 3). The status paragraph above
> is the historical pre-ratification record.

**Inputs:** `hermes_five_fundamentals_blueprint.md` §2.3, §4.5, §4.6, §14,
§19 Q2, §21 C1 (incl. the F-B data-structure sketch and assignment-
authority ruling), §22 condition 1, §27 (corrected re-grade);
`src/hermes/research/programs.py` (`HypothesisSpec` :188–200,
`ResearchProgramDraft` :246–260, `canonical_json`/`sha256_hex` :325–331,
E1–E5 checks (E1/E4/E5 :401–465; E2 :770, E3 :758 — later compile phase), supersession check :726–731, `_draft_from_payload`
:1068–1127, `canonical_content_dict` :1209–1235, `content_hash_of`
:1238–1240, module identity contract :35–37); `src/hermes/research/
gateway.py` (`_handle_propose_research_program` :210–270 — payload shape,
R-02 scope resolution, `superseded_program_ids` context :240–246, the
`ratification_ref` optional-key precedent :254); `src/hermes/persistence/
migrations.py` (`hypothesis_json` column :374); `docs/idr/IDR-041.md`
(REFUTED-terminal resurrection model — the consumer C1's screen axis
serves); the Q-02 design gate (`hermes_q02_epistemic_roi_design.md`) as
the format precedent.

---

## 1. Repository reconciliation (verified live, 2026-08-19)

| Blueprint C1 claim | Live repository fact | Verdict |
|---|---|---|
| "one optional field on `HypothesisSpec` — `slot_ref: str \| None`" | `HypothesisSpec` (`programs.py:188–200`) has fields `ref`, `ladder_target`, `falsification_condition`, `rival_of`, `rival_status` — no `slot_ref` anywhere in `src/` | CONFIRMED ABSENT — the field is new |
| "carried in `hypothesis_json`, content-addressed WITH the program" | Hypotheses persist via the `hypothesis_json` TEXT column (`migrations.py:374`; written at `repositories.py:1433`); program identity is `content_hash_of` = SHA-256 over `canonical_content_dict`, whose `"hypotheses"` entry is `_h_to_dict(h)` per hypothesis (`programs.py:1209–1240`); `program_id = "rp_" + content_hash[:24]` (`programs.py:37`) | CONFIRMED FEASIBLE — a field on the spec rides the existing identity chain with zero new plumbing |
| "the validator CHECKS it (closed vocabulary per project: … supersession chain …)" | The compile layer already receives supersession context: the gateway resolves `program_repo.superseded_program_ids(project_id, supersedes_ref)` (`gateway.py:240–246`) and the validator rejects an unresolvable `supersedes_ref` (`programs.py:726–731`, `UNRESOLVABLE_SUPERSEDES`) | CONFIRMED FEASIBLE — the chain is already a compile input; a slot-vocabulary check needs no new data access |
| "one E-check in `compile_research_program`" | E1–E5 are allocated (E1/E4/E5 `programs.py:401–465`; E2 :770, E3 :758); E6 and above are free | CONFIRMED — E6 is the natural slot |
| "no new table, no new intent" | `PROPOSE_RESEARCH_PROGRAM` is the existing admission path (`gateway.py:1587`); its payload is a dict with optional keys (`ratification_ref` precedent, `gateway.py:254`) | CONFIRMED — the rationale channel exists as a payload key; no schema migration, no `IntentKind` addition |
| "a slot-axis extension to the refuted-registry screen (when S7 lands)" | No refuted-registry screen exists in `src/` (S7 is designed in v6 §10.2, unimplemented — verified by the §27 transcript re-grade, finding T4) | CONFIRMED DEFERRED — the screen axis is designed here but implementable only after S7 |

**Verified gap:** there is no design-concept identity in the tree. Two
program versions that fill the same abstract slot are recognizable today
only by `supersedes_ref` adjacency — nothing distinguishes "same slot,
mutated mechanism" from "new research direction", and a resurrected
hypothesis (IDR-041 model) cannot be screened against the slot its
predecessor filled.

---

## 2. DECISION — the three §19-Q2 questions, resolved

### 2.1 Carrier: a field on `HypothesisSpec`, NOT a registry entry

**Resolved: `slot_ref` is an optional field on `HypothesisSpec` —
`slot_ref: str | None = None` — serialized into `hypothesis_json` and
content-addressed with the program.**

The alternative (a separate content-addressed registry entry) is rejected:

- It requires a new table and a new write path — forbidden by blueprint
  §21 C1 ("no new table, no new intent") and §22 condition 1 ("C1's
  slot_ref is a field, not a subsystem").
- It would make slot identity a *dereference* at compile time, adding a
  second identity source alongside `canonical_content_dict`. The ratified
  identity discipline (EC-V6 — identity is derived, never authored;
  IDR-041 F13 precedent) allows exactly ONE canonical content dict.
- A field on the frozen dataclass participates in `canonical_json`
  ordering automatically: same triple ⇒ same hash, different slot ⇒
  different `program_id`. The identity property the blueprint wants is
  obtained for free from the existing chain.

### 2.2 Assignment authority: Director assigns, validator checks (F-B ruling, pinned)

**Resolved: the Director ASSIGNS `slot_ref` in the `ResearchProgramDraft`
(it is a semantic judgment — which abstract slot a hypothesis fills); the
validator CHECKS it. No agent may re-assign an existing hypothesis's slot
in-place; the content-addressing makes that structurally impossible (a
slot change IS a new `program_id`, i.e. a new program version by
construction).**

The validator's check is membership + format, never semantics:

- **Format:** `slot:<snake_case_label>`, ≤ 128 characters total, ASCII.
  The `slot:` prefix namespaces the vocabulary away from every other
  ref family (`hypothesis:`, `evidence:`, `claim:`). Malformed →
  rejected at admission.
- **Closed vocabulary per project:** a carried `slot_ref` must EITHER
  already exist in the project's slot vocabulary (defined below) OR be
  declared new in the same payload with a rationale (§2.4). Typos and
  silent slot drift are rejected — this is the check that makes mutation-
  identity (blueprint F2) and resurrection screening (F6) trustworthy.
- **The validator never INVENTS a slot.** Absent `slot_ref` stays absent;
  there is no defaulting, no derivation from `observable`/`falsification_
  condition` text. Assignment is always an explicit Director act.

### 2.3 The refuted-registry screen axis: yes, deferred to S7

**Resolved: when S7 (the refuted-registry screen) lands, it gains a
`slot_ref` axis — a resurrection candidate is screened against the slot
its predecessor filled, so "same slot, new mechanism" is recognizable as
a legitimate resurrection attempt and "same content-hash lineage" is not
(IDR-041: resurrection is always a NEW hypothesis; content-hash equality
≠ same research trajectory, blueprint §14).** The axis is designed here
(§5.4) but is NOT implementable until S7 exists — recorded as a deferred
consumer, not a blocker for the field itself.

---

## 3. Exact authority owner

- **Who decides which slot a hypothesis fills?** The **Director** (the
  only LLM-producing surface for `ResearchProgramDraft` —
  `programs.py:247–248`). The assignment is a semantic judgment carried in
  the draft, admitted through the EXISTING `PROPOSE_RESEARCH_PROGRAM`
  path.
- **What does the validator decide?** Membership and format only: is the
  label well-formed, and is it either in the project's slot vocabulary or
  validly declared new? The validator never judges whether the assignment
  is *correct* — that is the Director's judgment, reviewable by the human
  gate that already governs program admission.
- **Does `slot_ref` influence scheduling, eligibility, ordering, or
  ladder state?** **No.** It is identity metadata. It adds no Q-02
  dimension, no eligibility predicate, no ladder precondition, no budget
  term. The no-scalar invariant (IDR-019) and the Q-02 dimension set are
  untouched. (Failure mode D stays solved: a label cannot be Goodharted.)
- **Does `slot_ref` create authority?** No. No new intent kind, no new
  gate, no new decision record, no new write path. The single-mutation-
  path invariant (blueprint §22 condition 2, failure mode R) is re-used,
  not extended.

---

## 4. The contract

### 4.1 The field

```python
@dataclass(frozen=True, slots=True)
class HypothesisSpec:
    ref: str
    ladder_target: LadderTarget
    falsification_condition: str
    rival_of: str | None = None
    rival_status: RivalStatus | None = None
    slot_ref: str | None = None          # C1 — design-concept identity
```

- Optional, default `None`. Programs compiled before C1 remain valid and
  unchanged (backward compatibility pinned as AC-1 below).
- Frozen dataclass: no in-place mutation of a recorded spec is possible
  through the data model; every change is a new draft → new program
  version.

### 4.2 Identity semantics (the load-bearing clause)

`slot_ref` participates in `canonical_content_dict` → `content_hash_of` →
`program_id`. Consequences, all by construction:

1. **A slot change is a contract change.** Re-pointing a hypothesis at a
   different slot produces a different `content_hash`, hence a different
   `program_id`, hence a new program version through supersession. There
   is no in-place re-assignment to forbid — the identity chain already
   makes it a new program.
2. **Mutation-identity (F2):** a mechanism substitution that preserves the
   slot (`PROPOSE_MECHANISM_SUBSTITUTION` → new program version, same
   `slot_ref` on the filling hypothesis) is recognizable as "same slot,
   new mechanism" — the supersession edge PLUS slot equality.
3. **Backward-compatibility hazard (pinned):** `_h_to_dict` must include
   `slot_ref` ONLY when it is not `None`. Including `"slot_ref": None` in
   the canonical dict would change the `content_hash` of EVERY existing
   program — an identity break of the entire corpus. AC-1 exists to catch
   exactly this.

### 4.3 The closed slot vocabulary

**Definition:** a project's slot vocabulary is the union of `slot_ref`
values over ALL program versions in the project's supersession history
(every immutable `research_programs` row), plus slots validly declared new
by admitted programs. The vocabulary is **append-only: slots are never
retired.**

Rationale: the resurrection consumer (§5.4) must recognize a slot even
after the hypothesis that filled it was dropped or REFUTED — a retired
vocabulary would make legitimate resurrections undeclarable. Append-only
vocabulary is consistent with the tree's append-only event/journal
discipline (IDR-041 §4, F14 precedent).

**Consequence:** "declare new" is valid only for a label NOT in the
vocabulary. Declaring an already-existing slot as new is rejected
(`E6_SLOT_ALREADY_DECLARED`) — the proposer must simply *use* it. This
makes the vocabulary decision deterministic and replay-stable: it is a
pure function of the project's immutable program rows.

### 4.4 New-slot declaration and its rationale

A payload introducing a `slot_ref` not in the vocabulary must carry the
declaration in the payload itself:

```json
{
  "scope_ref": "...",
  "hypotheses": [{"ref": "hypothesis:H1", "slot_ref": "slot:generate_upward_force", "...": "..."}],
  "new_slot_declarations": [
    {"slot_ref": "slot:generate_upward_force",
     "rationale": "Abstract function this hypothesis fills: ..."}
  ]
}
```

- `new_slot_declarations` is a **payload-only admission-time field** —
  validated at the gateway, recorded in the append-only admission event
  payload (the audit IS the record, IDR-040 precedent), and NEVER part of
  `canonical_content_dict`. Rationale is provenance evidence for the
  vocabulary growth, not program semantics — same governance split as
  `scope_content_hash` (input-side, never content-side; `programs.py:277–279`).
- Every `slot_ref` in `new_slot_declarations` must be used by ≥1
  hypothesis in the same payload (no orphan declarations); every
  not-in-vocabulary `slot_ref` used by a hypothesis must be declared
  (no undeclared growth). Both directions rejected (`E6_SLOT_UNDECLARED`,
  `E6_SLOT_DECLARATION_UNUSED`).
- Rationale: non-empty string, capped (same cap discipline as other
  rationale fields). Absent/empty rationale on a new declaration →
  rejected.
- A program with NO `slot_ref` anywhere requires no declarations — C1 is
  strictly additive.

### 4.5 The E6 check (validator surface)

One new check in the compile pass, alongside E1–E5 (`programs.py:734+`):

- **E6 — slot vocabulary discipline.** For every hypothesis carrying a
  `slot_ref`: format valid (§2.2); label is in the project vocabulary OR
  validly declared new in this payload (§4.4); declarations and uses
  agree in both directions. Rejection codes: `E6_SLOT_MALFORMED`,
  `E6_SLOT_UNDECLARED`, `E6_SLOT_ALREADY_DECLARED`,
  `E6_SLOT_DECLARATION_UNUSED`.
- The vocabulary lookup consumes the same supersession context the
  gateway already resolves (`superseded_program_ids`, `gateway.py:240–246`)
  plus the project's full program rows — no new repository surface beyond
  a read-only vocabulary projection.

### 4.6 What C1 does NOT do (explicit exclusions)

- **NOT a portfolio store.** The portfolio remains a derived projection
  (blueprint §22 condition 1). `slot_ref` labels the projection's rows;
  it adds no table, no write path, no query authority.
- **NOT a rival-discrimination mechanism.** Rivals MAY share a `slot_ref`
  (two mechanisms proposed for the same slot is exactly the P1-a
  portfolio shape — blueprint §3 diagram, H1/H3 both fill S1). E5 keeps
  its exclusive job: rivals are distinguished by structurally distinct
  predictions (`programs.py:444–465`), never by slot.
- **NOT an eligibility/ordering/ladder input.** (§3.) No Q-02 dimension,
  no floor entitlement, no rung precondition.
- **NOT a resurrection authority.** The S7 screen axis (§5.4) is advisory
  screening for the human gate; it never admits, rejects, or transitions
  anything by itself.
- **NOT a slot-merge/split mechanism.** Two labels naming one concept is a
  human curation problem, resolved by the existing program-version
  machinery (declare the canonical slot, supersede). No merge intent, no
  alias table.

---

## 5. Implementation surface (for the future implementation phase)

Exact and minimal — the blueprint's "implementable against the
controller/programs layer alone" claim, made concrete:

1. `programs.py` — `HypothesisSpec.slot_ref` field (§4.1);
   `_draft_from_payload` parses `slot_ref` + `new_slot_declarations`
   (`programs.py:1077–1092` insertion point); `_h_to_dict` includes
   `slot_ref` only when non-None (§4.2.3); E6 check (§4.5);
   `PROGRAM_SCHEMA_VERSION` bump. **Dual-consumer note (independent
   review 2026-08-20):** `_h_to_dict` feeds BOTH `canonical_content_dict`
   (identity) AND `program_to_dict` (the DB row JSON); the non-None-only
   rule covers both, but the persistence deserializer must tolerate a
   MISSING `slot_ref` key on pre-C1 rows (default None).
2. `gateway.py` — `_handle_propose_research_program` validates
   `new_slot_declarations` shape before compile and records it in the
   admission event payload (`gateway.py:210–270` insertion point).
3. `repositories.py` — read-only slot-vocabulary projection over the
   project's program rows (consumed by E6 via the compile context).
4. **No migration.** `hypothesis_json` is a TEXT column; the field rides
   inside it. `evidence_ladder_state`, satisfaction links, intents,
   events: untouched.
5. **Deferred consumer (S7):** the refuted-registry screen gains a
   `slot_ref` axis when S7 lands — a resurrection candidate's slot is
   compared against its predecessor's; equal slot + distinct content
   lineage = recognizable resurrection attempt; equal content-hash lineage
   = NOT a resurrection (IDR-041 terminality). Advisory, human-gated.

---

## 6. Acceptance criteria (the implementation must prove all of these)

- **AC-1 — identity stability (Delta=0 for the existing corpus).** Every
  program compilable today produces the IDENTICAL `content_hash` and
  `program_id` after C1 lands. Fixture: compile a slot-less program with
  the pre-C1 and post-C1 compiler; hashes equal. (Catches the
  `"slot_ref": None` canonical-dict hazard, §4.2.3.)
- **AC-2 — slot participation.** Two drafts identical except one
  hypothesis's `slot_ref` produce DIFFERENT `program_id`s; two drafts
  with the same `slot_ref` on the same hypothesis produce the SAME
  `program_id`.
- **AC-3 — closed vocabulary.** A `slot_ref` in the project vocabulary is
  admitted without declaration; one not in it is refused (`E6_SLOT_
  UNDECLARED`) unless validly declared new; declaring an existing slot as
  new is refused (`E6_SLOT_ALREADY_DECLARED`); an orphan declaration is
  refused (`E6_SLOT_DECLARATION_UNUSED`); a malformed label is refused
  (`E6_SLOT_MALFORMED`).
- **AC-4 — vocabulary is append-only and replay-stable.** The vocabulary
  derived from a project's program rows is a pure function of those rows:
  identical rows ⇒ identical vocabulary, independent of admission order;
  a REFUTED or dropped hypothesis's slot remains in the vocabulary.
- **AC-5 — rationale provenance.** A valid new-slot declaration's
  rationale appears in the admission event payload and in NO canonical
  content dict; the declaration never alters `content_hash`.
- **AC-6 — no authority leak.** No new `IntentKind`, no new table, no
  migration, no change to Q-02 dimensions, eligibility predicates, ladder
  obligations, or budget classes. Structural fixture: the intent-kind
  enum, the migration version, and the Q-02 dimension set are unchanged.
- **AC-7 — supersession-chain reachability.** E6's vocabulary lookup
  resolves slots across the full supersession history (grandparent
  programs included), and fails closed (refuses, never crashes) on a
  corrupt/unresolvable program row.
- **AC-8 — rivals may share a slot.** A program with two ACTIVE rivals
  carrying the SAME `slot_ref` and structurally distinct predictions
  (E5 satisfied) compiles; E5's distinguishability check is unaffected by
  slot equality.

---

## 7. Open questions for the architecture team (decisions this gate
defers, none blocking the field contract)

1. **Vocabulary scope confirmation:** §4.3 rules append-only over the
   full supersession history. The narrower reading of blueprint §21 F-B
   ("must either already exist in the supersession chain") could mean the
   LIVE chain only — which would retire slots when a lineage is abandoned
   and break the resurrection consumer. This gate decides append-only;
   the team may overrule, but only together with an alternative
   resurrection-screening mechanism.
2. **Adoption policy:** is `slot_ref` permanently optional (programs may
   opt out forever), or does a future policy version require it on new
   programs once C1 is ratified? This gate pins optional; a requirement
   would be a versioned policy change with its own gate.
3. **Slot granularity guidance:** nothing prevents a Director from
   declaring one slot per hypothesis (degenerate) or one slot for the
   whole program (coarse). The validator cannot judge semantics; the team
   should decide whether the Director's prompt/digest carries granularity
   guidance, or whether this is left to human review of admissions.
4. **S7 axis weight:** when the refuted-registry screen gains the slot
   axis, is equal-slot a *necessary* condition for a resurrection
   candidate to surface, or one advisory signal among several? This gate
   designs the axis as advisory-only; the weighting is S7's design
   decision.

---

## 8. Authority boundary (ratifiable text, pending approval)

- **CAN** carry `slot_ref` on `HypothesisSpec` through the existing
  `PROPOSE_RESEARCH_PROGRAM` admission — identity metadata, content-
  addressed with the program.
- **CAN** validate format and vocabulary membership at compile time (E6),
  fail-closed, with observable rejection codes.
- **CAN** record new-slot declarations + rationale in the admission event
  payload — append-only audit provenance for vocabulary growth.
- **CANNOT** create slots by derivation or default — assignment is always
  an explicit Director act in the draft.
- **CANNOT** re-assign a recorded hypothesis's slot in-place — the
  identity chain makes any slot change a new program version.
- **CANNOT** feed `slot_ref` into scheduling, eligibility, ordering,
  ladder derivation, or budget — it is identity, never authority.
- **CANNOT** retire a slot — the vocabulary is append-only; curation
  happens through supersession with a canonical slot, not deletion.

---

*End of C1 design gate. Status: DESIGN — awaiting blueprint ratification
and operator approval before any implementation phase. No file in `src/`,
`tests/`, or `docs/idr/` is touched by this document.*
