# HERMES v6 — STEP 4 ADVERSARIAL TRUST-BOUNDARY REPORT

Independent verifier, continuing the closure review. Step 3 result: **CENTRAL CLAIM
CONFIRMED WITH DEFERRED CONDITIONS**, with EC-V6-01 (record() trusts the caller-supplied
`CompilationResult.compiled` flag) as the central finding. This step determines what EC-V6-01
*is* — contract violation, intentional design, P3 dependency, P2 weakness, or a combination —
and resolves where Hermes' trust boundary actually lives.

**No release/ratification verdict is issued in this step.**

All evidence below is fresh runtime evidence against HEAD `7de1135f` (working tree:
`hermes_research_architecture_v6.md` modified to candidate status; 374 tests passing).

---

## A. EC-V6-01 Reproduction (strongest exploit)

**Exploit:** one hand-built program violating *many* requirements at once — two ROBUST
hypotheses with no predictions, no discrimination requirements, empty derived obligations,
empty gates, `compiler_version="999.999.999"`, `policy_version="forged-policy"`,
`schema_version="999"`, `input_hash="deadbeef_input"`, `content_hash="deadbeef_content"`,
`program_id="rp_handbuilt_forged_id"` — wrapped in `CompilationResult(status=COMPILED)` and
passed to `record(..., produced_by="ADVERSARY")`.

**Live result:**
- Row persisted: `program_id=rp_handbuilt_forged_id, version=1, produced_by='ADVERSARY'`,
  forged versions/hashes stored verbatim; `evidence_requirements=[]`, `gate_requirements=[]`.
- `ResearchProgramCompiled` event emitted with forged `program_id`/`content_hash` in payload
  and `artifact_ids=["rp_handbuilt_forged_id"]`.
- `current()` returns the forged program (the caller-claimed id became the project's head).
- **No validator invocation occurred** (no `compile_research_program`/`compile_from_payload`).
- **Control:** the same content through the real validator → `INVALID`
  (`SCHEMA_VERSION_MISMATCH`, `E1_PREDICTIONS_MISSING ×2`, `E5_RIVAL_COVERAGE`).

**Distinguishability of the persisted row (forged vs genuine):**
| Check | Genuine program | Forged program |
|---|---|---|
| stored `content_hash` == re-derived sha256(canonical content) | True | **False** (stored `deadbeef_content`) |
| `program_id == "rp_" + content_hash[:24]` | True | **False** (`rp_handbuilt_forged_id`) |
| obligations match validator derivation | 1 evidence / 8 gates | **0 / 0** |
| version triple | 1.0.0 / rp-2026.1 / 1 | **999.999.999 / forged-policy / 999** |

The forged row is **detectable by re-derivation** — the format itself carries the proof — but
**the repository performs none of these checks**, and no current consumer re-derives either.

## B. Trust Model Analysis — which model does v6 actually specify?

Evaluated against the normative text only (not implementation convenience):

| Model | v6 evidence |
|---|---|
| **A — Trusted Typed Result** | IDR-018 §5: "validate-before-write contract: only a `COMPILED` result may be persisted". The repository contract is status-gated; nothing requires re-running the validator. |
| **B — Repository Revalidation** | **Not specified.** No text says the repository independently re-validates epistemic content; v6 §28.2 assigns epistemic validation to the validator and "governance at the write path" to the repository. |
| **C — Gateway-Capability Trust** | IDR-018 rationale 3: "The only mutation is the gateway-admitted proposal → repository write." v6 §28.2: components "CANNOT … bypass the gateway (the intent kind is Director-only … admitted through the normal path)". Gateway = end-state admission authority. |
| **D — Hybrid** | R-02 (IDR-018 remediation + v6 §28.2): "the repository resolves the frozen brief's content hash from the DB and rejects any program compiled against a different hash" — a critical invariant **independently checked at persistence**; R-04 atomicity enforced at persistence. |

**Determination: v6 specifies MODEL D (hybrid), layered.** Epistemic validity is trusted from
the typed `CompilationResult` (A-component); *governance* is independently re-verified at the
write path (D-component, R-02 — live-verified in Step 3 D2b: forged scope hash rejected with
0 rows); *admission* is the Gateway's job in the end-state architecture (C-component, P3
deferred). Trust is layered: **validator → (COMPILED flag) → repository → (governance/atomicity) → event**.

**What is missing:** the architecture never states the *assumption* that makes the A-component
safe — that only the validator produces `CompilationResult` objects. It is implied ("no direct
mutation bypass", E6/E7) but never declared as a normative property with a phase owner. This
is the ambiguity the final principle forbids, and it is the substance of EC-V6-01.

## C. Normative Contract Analysis — what v6/IDR-018 actually requires

- **Validator is authoritative for epistemics** (§28.2: validator "checks" the E-checks and
  produces the verdict; IDR-018 §5: "E1–E5 checked; E2/E3 guard the §10.2 obligation map").
- **Repository is authoritative for governance and atomicity** (R-02, R-04, E9, PA4 —
  live-verified D1–D9, P1–P5).
- **Gateway is authoritative for admission** (intent path) — **deferred to P3** (§28.5 row:
  "`PROPOSE_RESEARCH_PROGRAM` gateway wiring … P3 | DEFERRED"; IDR-018 rationale 4:
  "`apply_intent` is a P3 placeholder on this baseline").
- E6/E7 as defined (IDR-018 §5): "no write path in the validator; closed payload schema;
  versioning-only change path" — these are enforced. The **additional gloss** "no direct
  mutation bypass" is attached to the repository contract as if structural; the live A-L
  evidence shows the only structural mechanism is a boolean flag on a caller-constructed
  object (see §L, EC-V6-10).
- **Nothing in the approved text requires repository-side epistemic re-validation.**
  **Nothing in the approved text states that arbitrary callers are prevented from calling
  `record()` at P2.** Both gaps are documentation omissions, not violated prohibitions.

## D. COMPILED Authenticity Analysis — what proves the object was genuinely compiled?

Systematic evaluation of the §5 mechanism list:

| Mechanism | Present? |
|---|---|
| Constructor restrictions / private constructors | No — `CompilationResult` is a public frozen dataclass; any caller constructs it |
| Signed/hashed compilation receipt | No — the enum value is the entire claim |
| Opaque compiled-result type | No — `program` is a fully public `ResearchProgram` |
| Compiler-issued provenance token | No — `produced_by` is a caller-supplied string |
| Content-derived revalidation at persistence | **No** — `content_hash`/`input_hash` stored verbatim, never re-derived (verified §G) |
| Repository revalidation | Partial — **governance only** (R-02 scope hash); never epistemic content |
| Gateway-only admission | Deferred — no gateway exists at HEAD (P3) |
| Explicit "validated" marker with deterministic proof | The marker is the enum value; **the deterministic proof exists in the format** (hash re-derivation, program_id prefix, obligation derivation) but is not *enforced* anywhere at the boundary |

**Conclusion:** `COMPILED` is **not an authenticated state** in the current system. Its only
trust property is the *convention* "only the intended compilation pipeline produces these
objects." The deterministic authenticity proof that would make it authenticated (re-derive
content_hash/input_hash from content; verify `program_id`; re-derive obligations) is
computable in ~10 lines and is what the identity contract (AC-01/R-01/PA4) already *assumes*
— but no boundary currently computes it.

## E. Repository Boundary Analysis — what `record()` trusts

Trusted from the object (no check): `compiled` flag, epistemic content (hypotheses/
predictions/discriminations), derived obligations, gate requirements, ladder targets,
`content_hash`, `input_hash`, `program_id`, `compiler_version`, `policy_version`,
`schema_version`, `produced_by`, `reason`.

Independently verified at the write path (repositories.py:874-965): `project_id` match vs
argument; frozen `ScopeBrief` existence **and** content-hash resolution **for the project**
(R-02; cross-project `scope_ref` rejected — live); supersession head/identity/content rules
(E9); duplicate idempotency (PA4, on the **caller-supplied** content_hash); atomic
row+event (R-04).

So the boundary enforces *governance and chain semantics* rigorously, and trusts *everything
epistemic* including its own identity material. That asymmetry is the precise shape of
EC-V6-01.

## F. Metadata Trust Analysis

| Field | Live behavior | Classification |
|---|---|---|
| `produced_by` | `produced_by="DIRECTOR"` from an arbitrary caller persisted verbatim; nothing verifies the caller | **UNTRUSTED** — recorded provenance only (E9). It is **not** authoritative, **not** used for governance, **cannot** identify a fake compiler, and **must never** be used for admission (the P3 gateway must use the actual calling context, not the payload string) |
| `compiler_version` | `"999.999.999"` persisted verbatim (A-L D); validator treats it as identity, does not validate it | **UNTRUSTED** (identity input; advisory as a *claim* about the toolchain) |
| `policy_version` | forged value persisted (A-L E) | **UNTRUSTED** (identity input) |
| `schema_version` | `"999"` persisted by repository, **rejected by the validator** (`SCHEMA_VERSION_MISMATCH`) (A-L F, §L EC-V6-12) | **UNTRUSTED at repository; VERIFIED at validator** — a program the validator would declare INVALID can be persisted |
| `reason` | stored verbatim | **ADVISORY** — free-text provenance, no semantics |

## G. Hash Trust Analysis

- **Derived deterministically?** Only inside the validator (`_build_program`,
  programs.py:769-832). At the repository boundary they are **caller-assignable**.
- **Validated on persistence?** **No.** Verified live:
  - *Correct content + wrong content_hash:* persisted with `content_hash='NOT_THE_REAL_SHA'`
    while the real hash is `5d4a7f3f…` (probe §H).
  - *Wrong content + forged matching content_hash:* **idempotency corruption** — a second,
    entirely different program claiming the same forged `content_hash` was **returned as the
    existing row** (`rp_coll1`): PA4 treats two different epistemic contracts as one
    duplicate; `get_by_hash` returns the first row. Supersession "identical content"
    rejection (E9) is likewise defeated by a forged collision.
- **Identity derivability (AC-01/R-01) is unenforceable in the bypass path:** `program_id`
  is never re-derived (`"rp_" + content_hash[:24]`), so forged ids become chain heads and
  event `artifact_ids`.
- The R-02 scope-hash check is the **only** hash-related verification, and it operates on a
  *field the caller also supplies* (mismatch is detected because the DB is consulted — the
  one check where trust is anchored in the store, not the object).

## H. Derived-Obligation Trust Analysis

- The validator derives `evidence_requirements` and `gate_requirements` from the closed
  §10.2 obligation map (programs.py:776-777) — E2/E3.
- The repository persists whatever the object declares. Live: a confirmatory (`SUPPORTED`)
  target with `evidence_requirements=()` and `gate_requirements=()` **persists as COMPILED**
  (A-L C; Step 3 A6), and arbitrary artifact classes/gates persist (A-L L — the validator has
  no payload input for gates at all; they are derived).
- **Does this violate E2/E3?** E2/E3 are validator-side checks and the repository does not
  re-run them, so *as implemented* the write path cannot violate them. But it **violates the
  contract's intent at the persistence layer**: authoritative persisted state can carry a
  confirmatory target with no obligations, so any P3+ consumer (gate enforcement,
  `INSERT_TASK`/GR7 instantiation driven by `evidence_json`) would operate on an epistemic
  contract the validator would never have issued. This is the concrete corruption vector of
  EC-V6-01 (see EC-V6-14).

## I. Director-Only Enforcement Analysis

- §28.5 row: "`PROPOSE_RESEARCH_PROGRAM` gateway wiring (`apply_intent` per-kind validator →
  `compile_from_payload` → `ResearchProgramCompiled`) | P3 | DEFERRED" — explicit.
- IDR-018 rationale 4 and Consequences: "gateway wiring (`apply_intent` is a P3 placeholder
  on this baseline)"; "Deferred (explicitly not implemented): P3 gateway wiring" — explicit.
- `intents.py:7-11` docstring: "the gateway itself (apply_intent) lands in P3" — explicit.
- **Verdict:** the deferral is honest and the P2 slice explicitly allowed to have no Gateway.
  Step 3's DEFERRED/P3 classification stands. No P2 claim describes Director-only as *enforced*
  now; the two residual overclaims are both documentation-level: IDR-018 §5's "(E6/E7 — no
  direct mutation bypass)" and v6 §28.2's "rejected at validator *and* at the write path"
  (Step 3 EC-V6-08 — live D2 shows validator returns COMPILED for a forged scope hash).

## J. Evidence-Ladder Future Safety

- Current structural closure: no promotion path exists (no status fields, E8; closed schema;
  no evidence vocabulary; `ladder_target` is a declared target — verified live in Step 3).
- Future-risk scan: `ladder_target` naming (declared target, commented "never evidence
  status"), `ResearchProgramCompiled` event name (compilation semantics only), persisted
  program object (no status fields — unrepresentable), graph projection (deferred P7/P8),
  future validator interfaces (the §10.2 map derives *obligations*, never satisfaction).
- **Classification: future-only risk → INFO, not a current defect.** The permanent rule
  (§27 item 45; §28.2 E8) is documented; it must be re-pinned by regression when the
  Evidence Ladder lands (P2 roadmap) — tracked for Step 4's successor.

## K. ActionEvaluation Trust Analysis

- What prevents treating `CandidateRanking` as an execution command: nothing *needs* to — it
  is pure, unpersisted, uncalled, advisory (§28.3: "a transient projection (like
  `GraphDiagnostics`), never persisted as evidence, never a gate input"; IDR-019 item 6
  identical; CANNOT list includes "auto-dispatch"; "Ranking can never override a mandatory
  gate").
- **The invariant "advisory; cannot itself authorize or dispatch work" is already explicit**
  in both IDR-019 and §28.3. Documentation recommendation (optional): carry the same sentence
  verbatim into §28.5's P3 "Director/round integration" row so Part 2 integration inherits it.
- New observation (INFO, EC-V6-15): exclusion diagnostics are only as complete as the
  candidate set the caller supplies — a caller may omit a gate-blocked candidate and the
  ranking will not know it existed ("no candidate generation" cuts both ways).

## L. New Findings

Numbering continues from Step 3 (EC-V6-01…09 used there). All live-verified this step.

### EC-V6-10 — The trust model is MODEL D (hybrid), but the trusted-result assumption is unstated (P2 → ratification wording)
v6 specifies: epistemics trusted from the typed COMPILED result (A), governance independently
re-verified at the write path (D/R-02), admission via gateway in the end state (C/P3). The
implementation matches this layered model exactly. What is missing is the normative sentence
making the A-component's assumption explicit — "only the validator produces
`CompilationResult`; `record()` trusts the flag; origin enforcement is the P3 gateway's
responsibility; P2 persistence is intentionally a lower-level trusted primitive" — plus the
wording corrections below. Per the final principle, an ambiguous trust boundary cannot be
ratified. **Severity: P2 (documentation, ratification-gating).**

### EC-V6-11 — Identity fields are never re-derived at persistence; PA4 idempotency is forgeable (P2)
`content_hash`, `input_hash`, `program_id` are caller-assignable and stored verbatim; the
content↔hash relationship is never verified. Consequence beyond raw forgery: two *different*
contracts sharing one forged `content_hash` collapse via the idempotency path (second record
returns the first row; E9 "identical content" rejection also defeated). The determinism/
identity claims (AC-01, R-01, PA4) are therefore only enforceable for objects that came from
the validator. Minimal P2 hardening: re-derive `content_hash` (and `input_hash`) from the
stored content at the write path and reject mismatch — ~10 deterministic lines, no new
dependencies, closes the whole identity-forgery class. **Severity: P2 (SHOULD FIX).**

### EC-V6-12 — `schema_version` is verified by the validator but not by the repository (P2, tiny)
A program the validator rejects as `INVALID` (`SCHEMA_VERSION_MISMATCH`, `"999"`) persists via
the bypass path. One constant comparison at the write path (against the validator's
`PROGRAM_SCHEMA_VERSION`) or an explicit trust statement closes it. **Severity: P2 (SHOULD
FIX, or fold into the EC-V6-10 trust statement).**

### EC-V6-13 — `produced_by`/`compiler_version`/`policy_version`/`reason` are advisory provenance; never admission inputs (DOCUMENTATION)
Correct per contract (E9 records provenance; versions are identity inputs). Add an explicit
normative line: `produced_by` is never authoritative and the P3 gateway must bind admission to
the actual calling context, never to the payload string (a caller-supplied
`produced_by="DIRECTOR"` currently persists — live-verified). **Severity: P3/DOCUMENTATION.**

### EC-V6-14 — Derived-obligation divergence: persisted obligations may not be the validator's (P2, part of EC-V6-01)
A confirmatory target with empty or forged `evidence_requirements`/`gate_requirements`
persists as COMPILED (A-L C/L), so the *persisted* epistemic contract can differ from what
E2/E3 would derive — and P3+ consumers will trust the persisted copy. Either the write path
re-derives obligations (more coupling) or — the minimal option — the EC-V6-10 trust statement
plus EC-V6-11's content_hash check makes the divergence detectable (re-derivation of the hash
already includes obligations, so a hash check makes obligation forgery change the hash and
fail). **Severity: P2 (absorbed by EC-V6-11 hardening + EC-V6-10 statement).**

### EC-V6-15 — Evaluator exclusion completeness depends on the caller-supplied candidate set (INFO)
`CandidateRanking` reports exclusions only for candidates it is given; an omitted blocked
candidate is invisible. Inherent to "no candidate generation"; advisory by design. Note for
Part 2 integration (P3): candidate-set sourcing must be complete or labeled as sampled.
**Severity: INFO.**

### EC-V6-16 — Evidence-ladder future safety is a documented guard, not a current mechanism (INFO)
Current closure is structural (no status fields); future safety depends on §27 item 45's
permanent rule surviving the Evidence implementation. Re-pin by regression when Evidence
lands. **Severity: INFO.**

## M. Required Actions

**MUST FIX BEFORE v6 RATIFICATION (no code behavior change required):**
1. State the trust model in §28.2/IDR-018 (EC-V6-10): `record()` is a lower-level trusted
   primitive whose input contract is "a result produced by the ResearchProgramValidator";
   the repository trusts epistemic content of a COMPILED result and verifies governance
   (R-02) itself; origin/admission enforcement is the P3 gateway's responsibility. Declare
   that P2 persistence is not independently secure against arbitrary local callers.
2. Correct the two overclaiming phrases: IDR-018 §5 "(E6/E7 — no direct mutation bypass)"
   (the mechanism is a caller-set flag; the *end-to-end* no-bypass property is the gateway,
   P3) and v6 §28.2 "rejected at validator *and* at the write path" (live: governance
   mismatch is rejected at the write path only — Step 3 EC-V6-08, still open).

**SHOULD FIX (P2 hardening, small and deterministic):**
3. EC-V6-11: write-path re-derivation of `content_hash` (+`input_hash`) and `program_id`
   format check — closes identity forgery and the PA4 idempotency collision; makes R-01/
   AC-01 claims enforceable; makes EC-V6-14's obligation divergence detectable.
4. EC-V6-12: `schema_version` comparison at the write path (one constant), or explicit
   coverage by the trust statement.

**P3 / FUTURE:**
5. Gateway admission for `PROPOSE_RESEARCH_PROGRAM`: `apply_intent` per-kind validator →
   `compile_from_payload` → human gate → `record()`; enforcement of `director_only()`/
   `proposed_by` from the actual calling context (Step 3 EC-V6-02/03 — unchanged).
6. Part 2 integration (IDR-019): carry the "advisory, never authorizes/dispatches" invariant
   into the integration row (EC-V6-15 note); complete candidate-set sourcing.
7. Evidence Ladder landing: re-pin §27 item 45 by regression (EC-V6-16).

**DOCUMENTATION ONLY:**
8. EC-V6-13: `produced_by` never admission; versions advisory; `reason` advisory.
9. Step 3 findings still open for documentation: EC-V6-08 (§28.2 wording — see #2),
   EC-V6-07 (immutability boundary statement).

## N. Final Trust-Boundary Conclusion

**TRUST BOUNDARY SOUND WITH P2 HARDENING.**

The boundary Hermes actually specified is layered and coherent: the validator is authoritative
for epistemics, the repository independently re-verifies governance and atomicity at the write
path (R-02/R-04 — live-verified), and the gateway is the declared admission authority for the
end-state (P3, honestly deferred). Nothing in the current implementation silently corrupts
other research state; there is no second authority; the bypass is a local, detectable, and
bounded persistence trust-boundary gap under the documented single-operator trust model —
**not** a P0/P1 authority leak, and **not** a violation of any normative prohibition.

What is **incomplete** is the specification of the boundary's own assumption. The property
that makes a COMPILED ResearchProgram trustworthy enough to become authoritative persisted
state is currently: *"only the intended compilation pipeline produces COMPILED objects"* —
and nothing in the code, the schema, or the normative text enforces or even explicitly
declares that assumption. The deterministic proof that would authenticate it (content-hash
re-derivation) exists in the format but is computed nowhere. Per the final principle, that
ambiguity must be resolved — by the explicit trust statement (MUST FIX #1) and the two
wording corrections (MUST FIX #2) — before the §27 item 43 gate can ratify, with the
minimal write-path hardening (SHOULD FIX #3/#4) recommended as the P2 defense-in-depth that
makes the stated trust actually checkable.

---

*Probe artifacts: `%TEMP%/opencode/step3/probe_s4a.py` (reproduction + distinguishability),
`probe_s4b.py` (A-L table), `probe_s4c.py` + `s4c_xproj.py` (metadata/hash/governance trust).
In-memory DBs only; working tree unchanged by verification.*
