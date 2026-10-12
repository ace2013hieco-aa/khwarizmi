# HERMES C1 / STEP 3 — `PROGRAM_SCHEMA_VERSION` bump vs AC-1 Delta=0: SPEC-CONFLICT NOTE

**Status:** **RATIFIED — Option A adopted (operator ratification,
2026-08-21).** Ratified text: "Adopt a supported program-schema-version
set containing the legacy version and the new current version
({"1", "2"}), with "2" as the current/default version. Preserve v1
program identity and validity; reject unsupported versions consistently
at both validation and persistence boundaries." Step 3 (C1) proceeds
under this exact contract; the architecture is NOT reopened and the C1
identity model is NOT modified. The original pending-ratification record
follows below, unchanged.

**Scope:** the single question of how the mandated `PROGRAM_SCHEMA_VERSION`
bump coexists with AC-1 (Delta=0 identity stability) given the ratified
strict-equality version check. Nothing else in the C1 contract is in
dispute: the `slot_ref` field, the non-None-only serialization rule, E6,
the slot-vocabulary projection, and AC-2..AC-8 are unaffected by this note.

---

## 1. The conflict in one paragraph

The frozen Step 3 charter and the C1 design gate both **mandate a
`PROGRAM_SCHEMA_VERSION` bump**, and both **mandate AC-1 Delta=0** (every
program compilable today keeps the identical `content_hash`/`program_id`
after C1 lands). But `schema_version` is an **input to the content hash**,
and the version check is **strict equality** against the single constant.
Bumping the constant to `"2"` while keeping strict equality makes AC-1
**unsatisfiable**: the post-C1 compiler rejects every pre-C1 payload
(`schema_version="1"`) as `SCHEMA_VERSION_MISMATCH`, so the AC-1 fixture
("compile a slot-less program with the pre-C1 and post-C1 compiler; hashes
equal") cannot even run. The three ratified mandates cannot all hold at
once under the current enforcement mechanism.

---

## 2. Evidence — the three colliding mandates (verified live, file:line)

### 2.1 Mandate A — the bump is required

| Source | Location | Text |
|---|---|---|
| Frozen sequence | `hermes_architecture_ratification.md:134` | STEP 3 = "C1 implementation (`HypothesisSpec.slot_ref` + E6 + vocabulary projection + **schema-version bump**; AC-1 Delta=0 corpus-rehash check is the gate)" |
| C1 design gate §5.1 | `hermes_c1_slot_ref_design_gate.md:281` | "`PROGRAM_SCHEMA_VERSION` bump" |
| Final ratification gate | `hermes_final_ratification_gate.md:147` | "`PROGRAM_SCHEMA_VERSION` bumps at implementation; no migration needed (TEXT column)" |
| Ratification readiness | `hermes_five_fundamentals_ratification_readiness.md:100-101, 325` | "`PROGRAM_SCHEMA_VERSION` bumps at implementation" |

### 2.2 Mandate B — AC-1 Delta=0 is the gate

| Source | Location | Text |
|---|---|---|
| C1 design gate §6 AC-1 | `hermes_c1_slot_ref_design_gate.md:304-308` | "Every program compilable today produces the IDENTICAL `content_hash` and `program_id` after C1 lands. Fixture: compile a slot-less program with the pre-C1 and post-C1 compiler; hashes equal." |
| C1 design gate §4.1 | `hermes_c1_slot_ref_design_gate.md:156-157` | "Programs compiled before C1 remain valid and unchanged (backward compatibility pinned as AC-1 below)." |
| Frozen sequence | `hermes_architecture_ratification.md:134` | "AC-1 Delta=0 corpus-rehash check **is the gate**" |

### 2.3 Mandate C — the enforcement mechanism that creates the collision

| Source | Location | Fact |
|---|---|---|
| The constant | `src/hermes/research/programs.py:111` | `PROGRAM_SCHEMA_VERSION = "1"` |
| Validator check | `src/hermes/research/programs.py:571` | `if draft.schema_version != PROGRAM_SCHEMA_VERSION:` → `INVALID` / `SCHEMA_VERSION_MISMATCH` (strict equality) |
| Write-path check (EC-V6-15) | `src/hermes/persistence/repositories.py:1315` | `if program.schema_version != PROGRAM_SCHEMA_VERSION:` → `ResearchProgramIntegrityError` (strict equality) |
| `schema_version` is a hash input | `src/hermes/research/programs.py:1234` | `canonical_content_dict` includes `"schema_version": program.schema_version` |
| → content hash | `src/hermes/research/programs.py:1238-1240` | `content_hash_of` = SHA-256 over `canonical_json(canonical_content_dict(...))` |
| → input hash too | `src/hermes/research/programs.py:1254` | `input_hash_of` also includes `"schema_version"` |

---

## 3. Why the mandates collide (the mechanism, step by step)

1. `schema_version` feeds `canonical_content_dict` → `content_hash_of` →
   `program_id` (programs.py:1234 → 1238). **Any change to the version a
   program carries changes its identity.**
2. The validator (programs.py:571) and the write path (repositories.py:1315)
   both enforce `schema_version == PROGRAM_SCHEMA_VERSION` by **strict
   equality against the single constant**.
3. Bump the constant `"1"` → `"2"`. Now:
   - A pre-C1 payload carries `schema_version="1"` (the old default,
     programs.py:259/1148). The post-C1 validator rejects it at
     programs.py:571 as `SCHEMA_VERSION_MISMATCH`. **The AC-1 fixture
     ("compile a slot-less program with the pre-C1 and post-C1 compiler")
     is unrunnable** — the post-C1 compiler refuses the pre-C1 program.
   - The alternative reading — recompile the same content with the new
     default `"2"` — changes the hash (step 1), so `hash_pre != hash_post`.
     **Delta ≠ 0.** AC-1 violated directly.
4. Therefore **bump + strict-equality + AC-1 are mutually unsatisfiable.**
   Exactly two of the three can hold; the charter demands all three.

This is consistent with, and forced by, the gate's own §4.1 sentence
"Programs compiled before C1 remain valid and unchanged": "remain valid"
means a `"1"` payload must still be *accepted* by the post-C1 compiler,
which strict equality against `"2"` forbids.

---

## 4. Resolution options

### Option A — SUPPORTED-VERSION SET (recommended)

Replace the single-constant strict-equality check with membership in an
explicit supported set. Post-C1: `SUPPORTED_PROGRAM_SCHEMA_VERSIONS =
{"1", "2"}`; new drafts default to `"2"`; the validator and the write path
both accept `"1"` **and** `"2"`.

- **AC-1 Delta=0 satisfied:** a pre-C1 `"1"` payload still compiles, and
  because its carried `schema_version` is unchanged (`"1"`) and `slot_ref`
  is emitted only when non-None, `content_hash`/`program_id` are identical
  pre- and post-C1. The AC-1 fixture is runnable and passes.
- **Bump satisfied:** the current/default version is `"2"`; new programs
  carry `"2"`.
- **EC-V6-15 security property preserved:** the invariant restates as
  "`schema_version ∈ SUPPORTED_PROGRAM_SCHEMA_VERSIONS` — a program the
  validator would reject as INVALID cannot persist." The validator and the
  write path still agree (the core EC-V6 discipline: they never disagree).
  A forged `"999"` is rejected by both, exactly as today
  (`test_research_program.py:948-971, 996` still pass).
- **No downgrade benefit:** `slot_ref` is optional in both versions (gate
  §7.2 pins it permanently optional), so a Director gains nothing by
  claiming `"1"` over `"2"`.

### Option B — HOLD + RATIFY, then implement Option A

This note **is** Option B's first half: record the conflict, ratify, then
implement. Selecting Option B means "ratify Option A's mechanism via this
note before any code." (Recommended path = ratify A.)

### Option C — bump strict, accept AC-1/§4.1 become unsatisfiable

Bump to `"2"` with strict equality and no set. **Not recommended:** it
violates the named gate (AC-1 "is the gate") and the gate's own §4.1
backward-compatibility sentence. Listed only for completeness.

---

## 5. Blast radius of Option A (verified, minimal)

Production (2 files):
- `src/hermes/research/programs.py:571` — strict equality → set membership;
  add `SUPPORTED_PROGRAM_SCHEMA_VERSIONS`; bump default to `"2"`
  (programs.py:259, 1148).
- `src/hermes/persistence/repositories.py:1315` — strict equality → set
  membership (same constant, one derivation, never two).

Tests (1 pin moves; the rest pass unchanged):
- `tests/test_research_program.py:269` — currently uses
  `base_payload(schema_version="2")` as the INVALID mismatch case. Under
  Option A `"2"` becomes valid, so this pin moves to a genuinely
  unsupported version (e.g. `"3"`). This is a chartered identity-contract
  test edit, made only after ratification.
- `tests/test_research_program.py:69, 836` — default `"1"` payloads: stay
  valid (this is exactly what makes AC-1 testable). **No change.**
- `tests/test_research_program.py:948-971, 996` — forged `"999"`: still
  rejected. **No change.**
- `tests/test_controller.py:126`, `tests/test_controller_q02.py:104` —
  these are **CLAIM**-schema versions (extract_fn payloads,
  `CLAIM_SCHEMA_VERSION`), unrelated to `PROGRAM_SCHEMA_VERSION`. **No
  change.**

No migration (TEXT column), no new table, no new intent — unchanged from
the gate.

---

## 6. What is HELD pending ratification

All Step 3 / C1 production and test code: the `slot_ref` field,
`_draft_from_payload` parsing, the non-None-only `_h_to_dict` rule, the E6
check, the slot-vocabulary projection, the gateway
`new_slot_declarations` handling, the `PROGRAM_SCHEMA_VERSION` bump, and
AC-1..AC-8. Nothing in `src/`, `tests/`, or `docs/idr/` is touched by this
note. The working tree remains clean apart from this document.

---

## 7. Ratification request

Operator: ratify **one** option. The recommendation is **Option A**
(supported-version set `{"1","2"}`, default `"2"`), as it is the only
reading that satisfies the bump mandate, AC-1 Delta=0, and the gate §4.1
backward-compatibility sentence simultaneously while preserving the EC-V6-15
forged-version rejection. On ratification, Step 3 implementation proceeds
under the ratified mechanism and this note's status flips to RATIFIED with
the decision recorded.

*End of spec-conflict note. Status: PENDING OPERATOR RATIFICATION —
NON-AUTHORITY until ratified. No file in `src/`, `tests/`, or `docs/idr/`
is touched by this document.*
