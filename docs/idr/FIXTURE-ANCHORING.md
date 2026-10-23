# FIXTURE ANCHORING (P2-4 / GAP-1) — design note

| Item | Value |
| --- | --- |
| Task | P2-4 (GAP-1): fixture anchoring — manifest signature or journal anchor |
| Phase | 1 — design only; no code, tests, migration, or fixture change |
| Base | `67ba1e1` (`main`) |
| Branch | `slice/p2-4-anchor` |
| Status | Proposal; the ruling is requested in §4 |

The claim under audit is the module docstring of
`src/hermes/research/ref_graphs.py:21-24`:

> The fixture FILE NAME is the digest, so a fixture is addressed by its
> content and any edit to the file is detectable without a signature.

The same claim appears in `docs/gr3-b4/b4-fixtures/README.md:10-12` and,
more strongly ("needs no signature to detect tampering"), in
`docs/gr3-b4/P2-b4fixtures.md:277`. The GAP-1 triage records the intended
reading — "edits detectable without a signature (i.e. corruption-evident,
not tamper-evident); filename = content digest; no manifest signature or
journal anchor" (`AUDIT-GAP-1-TRIAGE.md:274-278`, branch
`audit/gap-1-triage`).

## 1. What is actually claimed today

### 1.1 What the mechanism does

- `fixture_filename` (`ref_graphs.py:369-371`) returns `<sha256>.json`;
  `reference_graph_digest` (`:364-366`) hashes exactly
  `reference_graph_bytes` (`:358-361`) — canonical JSON plus one trailing
  LF. The name is derived from the bytes, not stored inside the file.
- The strict reader recomputes the byte digest when `expected_digest` is
  supplied (`:414-420`) and refuses on mismatch. The twin consumer always
  supplies the file stem
  (`experiments/texp-001/fixtures.py:415-422,501`). A file whose bytes no
  longer hash to its name is therefore refused at read time. This catches
  truncation, partial writes, EOL/encoding damage, and any edit that does
  **not** rename the file.
- `tests/test_b4_ref_graphs.py:244-256` rebuilds every fixture from
  `GOVERNED_CORPUS_REFS` and requires the on-disk name set and the bytes
  to equal the build (`:248`, `:254-256`). CI runs the full suite on
  pull requests and pushes to `main` (`ci.yml:3-10,13,43`),
  so this is a merge gate — but it executes the candidate branch's own
  code, test, and corpus.

| Check | Where | Catches | Does not catch |
| --- | --- | --- | --- |
| Name equals sha256 of bytes | `ref_graphs.py:369-371,414-420`; twin `fixtures.py:415-422` | a corrupted, truncated, partially written, or EOL-mangled file; an edit that does not rename | a replaced file whose name was recomputed; an added fixture; a deleted fixture |
| Regeneration against the governed corpus | `test_b4_ref_graphs.py:244-256`; CI `ci.yml:3-10,13,43` | a replaced-and-renamed, added, or deleted fixture **provided** the builder, the test, and the governed source bytes are trusted | an actor who also edits the builder, the test, or the governed documents consistently; a skipped or altered test; a history rewrite |
| VCS history and review | repository/remote process | most coordinated edits, after the fact | a history rewrite or a compromised remote; not a property of the artifact |

### 1.2 What it does not do

A replaced fixture whose name has been recomputed is **self-consistent**:
the name matches the bytes, so the strict reader accepts it. Only
regeneration detects the replacement, and regeneration is code in the same
repository. An actor who can edit the fixture can also edit the builder,
the test, or the governed documents and regenerate consistently; the suite
then stays green and the artifact itself carries no evidence of the change.
The remaining checks are VCS history/review (defeated by a history rewrite
or a compromised remote) and an out-of-band copy of the expected digest
(none exists in the repository today).

The twin reads every `*.json` in the fixture directory
(`experiments/texp-001/fixtures.py:491-503`), so an added, self-consistent
fixture is **consumed**; the regeneration set check is what rejects it in
CI. A deleted fixture is likewise caught only by that set check.

### 1.3 Actors and capabilities

| Case | Actor / capability | Caught by |
| --- | --- | --- |
| Accidental corruption | none; any filesystem or tooling write | name ≠ bytes at read; regeneration |
| Fixture replaced and renamed, nothing else changed | write access to the repository | regeneration, if the builder/test/corpus are trusted |
| Fixture replaced plus builder, test, or corpus edited consistently | repository write plus the ability to land the change (merge rights or a history rewrite) | review, VCS history, or an out-of-band digest — not the artifact |
| Journal/database rewrite | database write and DDL (`DROP TRIGGER`, re-chain) | irrelevant to fixtures today: no link between fixtures and the journal exists (see §2, A) |

### 1.4 Vocabulary, precisely

- **Corruption-evident.** The artifact is self-addressing: accidental
  damage changes the bytes without changing the name, so re-hashing against
  the name fails. This needs no key material.
- **Regeneration-evident.** The artifact can be re-derived from governed
  inputs and compared byte-for-byte; the derivation is the check. This is
  stronger than a name check because it binds the artifact to a rule, not
  just to its own bytes — but the rule is code, and code can be edited.
- **Tamper-evident.** Evidence of tampering remains after an adversary with
  write access to the artifact **and its verification path** acts, because
  the evidence is bound to something the adversary cannot rewrite: a
  secret/MAC, a signature verified against an out-of-band key, or an
  out-of-band witness (for example, a human-held journal tip).

The current design is corruption-evident and regeneration-evident. It is
**not** tamper-evident. The docstring's "detectable without a signature" is
true for accidental damage and for an edit that leaves the name stale; it
is false as a claim about a deliberate replacement, because the replacement
can recompute the name. "Any edit to the file" is detected only where the
edit does not include the rename.

## 2. The three options, costed

### A — Pin the fixture digests to the journal chain

**Surface.** One event row in the existing `events` table, with a new
`EventType` member (proposed name: `FixtureManifestPinned` =
`"FixtureManifestPinned"`). Its payload records the four
`{fixture_id, digest, fixture_schema_version, extraction_version}` entries
and a payload schema version. The event is repo-global, so
`project_id = NULL` (the column is nullable; the event-retry path already
writes `NULL`, `repositories.py:918-922`). Four 64-hex digests plus ids are
well under the 4 KiB payload cap (`event_validation.py:23,74`).

**Why an event, not a table.** The chain preimage covers exactly eleven
`events` columns, including `payload_json` (`journal_chain.py:47-59`;
`repositories.py:141-202`). A separate `fixture_anchors` table would need a
schema migration (v24) and would **not** be hashed by `chain_row` — it
would be a second mutable copy of the digests, no stronger than a committed
manifest file. The honest form of A is therefore event-only.

**Migration.** None. The `events` table exists from v1 and the chain
columns from v23 (`migrations.py:21,1328-1397`); adding an enum member is a
code change, and `KNOWN_EVENT_TYPES` derives from the enum
(`event_validation.py:32`). `docs/API.md:94` points at that catalog rather
than listing it, so the event-type addition alone does not force a
governed-document edit. A table variant would need v24 and is rejected
above.

**Write path and census.** Append with the existing
`EventRepository.append_transactional` (`repositories.py:876-935`), which
already owns its transaction and accepts `project_id=None`. That reuses an
existing acquisition owner, so the frozen census (124 calls / 28 owners —
D12, `docs/GAP1-RULINGS.md:50`; `docs/ARCHITECTURE.md:147-172`) is
unchanged. A new CLI-owned transaction would add two calls and one owner
(126 / 29) and should be refused. If the pure fixture comparison lives in
`hermes.research` and the CLI does the `SELECT`, no new upward import is
added either. The remaining architectural cost is not in the census: this
is a **new event-only writer outside `apply_intent`**. It is a maintenance
path, in the class of `journal rechain`, and needs an explicit design-gate
ruling because the journal gains a writer not routed through the single
mutation path.

**Verification.** A command such as
`hermes fixtures verify [--db PATH] [--anchor HEX]` would: (1) run
`verify_journal(conn, anchor=...)` and require `CHAIN_OK` with no
structural findings; (2) read the latest pin event; (3) require the fixture
id set to equal the pinned set exactly; (4) recompute each file's sha256
and compare with the pinned digest. Any mismatch, missing pin, ambiguous
duplicate pin, extra file, or missing file exits non-zero. `--anchor` checks
the journal tip only; it does not bind the fixture files by itself.

**What it closes.** A fixture replacement by an actor with repository
write **only**, while a trusted database still holds the pin and a trusted
verifier is run against it. It also makes a coordinated fixture + builder +
corpus edit visible as "the files differ from the last pin" under the same
assumptions.

**What it does not close.** An actor with repository write **and** database
write/DDL can rewrite the pin event and re-chain
(`journal_chain.py:9-18,268-333`). Only an out-of-band tip detects that
(`CHAIN_TIP_MISMATCH`, `journal_chain.py:193-194`), and this design ships no
anchor store (`docs/idr/TAMPER-EVIDENT-JOURNAL.md:735-742`). A fresh clone
or CI has no database: failing closed makes a new install unverifiable, and
failing open makes deleting the database a bypass. Every legitimate fixture
regeneration — the README records nine re-derivation rounds, all of which
leave `b4-c3` unchanged — would require a new pin per database, or the
check goes red. The event also puts ADVISORY test data into the research
audit trail, which is a category question, not just a cost.

**What the anchor is anchored to.** The pin is anchored to the journal
chain, and the chain is anchored to its own tip. A self-consistent
replacement of the database **and** the fixtures verifies unless a human
holds the tip through a channel the database owner cannot rewrite. A as
described ships no such custody; without it, A is a cross-check between two
mutable stores, not tamper-evidence.

### B — A signed manifest

**What it requires.** A signing keypair, private-key custody, a trust root
for the public key, rotation and revocation, signing and verification
tooling, a CI secret, and a documented procedure for the offline verifier.
If the public key lives in the same repository as the verifier, a
repository attacker can replace both; to mean anything the key must be
out of band, which is the custody problem again.

**What it closes.** Repository-only replacement (with an out-of-band public
key), and repository + builder edits — a genuine cryptographic boundary,
unlike A.

**What it contradicts.** **D5** (`docs/GAP1-RULINGS.md:26,128-140`) is a
human override of the recommended key-custody track: document-and-accept,
and "no key-custody IDR unless that work is ever scoped to include key
custody." A signature proposal is exactly that scoping, so B cannot be
adopted under D5 as it stands. The TAMPER-2 addendum also records that the
design ships "no signature, no MAC, no key material"
(`docs/idr/TAMPER-EVIDENT-JOURNAL.md:735-742`). This note does not design a
key store.

### C — Document and accept

**What it is.** State that the fixtures are ADVISORY (`ref_graphs.py:88`)
and SIMULATED (`:85`), never production state and never authority — no
module under `src/` consumes them, and the only consumer is the TEXP-001
twin in `experiments/`. The `authority` value is carried and parsed as data
(`ref_graphs.py:485`) but no reader enforces it; the never-authority
property is structural (no consumer), not marker-enforced. Their integrity
is corruption-evident and regeneration-evident, not tamper-evident. The
residual is a deliberate editor with repository write (and, for any journal
pin, database write) acting with enough access to keep the derivation and
test consistent. A journal pin without out-of-band custody would only
relocate that trust.

**What it closes.** Nothing mechanically. It corrects the claim and records
the residual. It is consistent with D5, with the TAMPER-2 A6 statement, and
with the display rule that a digest or derived view is never authority.

**What it costs.** Prose. In this slice, this note only. After a ruling, a
wording correction in `ref_graphs.py:21-24` (docstring only, no behavior)
and `README.md:10-12`, plus an addendum to
`docs/gr3-b4/P2-b4fixtures.md` if wanted — all ungoverned. No migration, no
census change, no governed document, no B4 regeneration. If the human wants
the residual in `docs/STATE.md`, that is a governed edit and will move
`b4-c1`/`b4-c2`/`b4-c4`, forcing a deliberate regeneration (the 24 pinned
B4 tests stay 24).

**What it contradicts.** Only the expectation that every VALID audit
finding must produce machinery; it contradicts no invariant.

### Cost table

| Option | Closes | Files | Migration? | Census? | Governed docs? | B4 regeneration? | Conflicts with |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **A** — journal pin event | repository-only replacement with a trusted DB; pin drift from coordinated repository edits | `core/events.py` (event type), `cli.py` (pin/verify), a pure comparison module, a new test file | No (event-only). A `fixture_anchors` table would need v24 and is not chain-covered — rejected | 0 if `append_transactional` is reused; +2 calls / +1 owner if a new transaction is added — refused | None for the event type; `STATE.md` only if the human orders it | No | Single-mutation-path purity (new event-only writer); per-database pin loop; needs an out-of-band tip for force |
| **B** — signed manifest | repository-only replacement and repository + builder edits, with an out-of-band public key | signing/verification tooling, key custody and rotation, CI secret, an IDR | No, unless key metadata is stored | None | Likely `STATE.md` / `ARCHITECTURE.md` (new mechanism); an IDR | Yes, if a governed doc changes (regenerate `b4-c1`/`c2`/`c4`; 24 stays 24) | **D5** (no key custody); no out-of-band key store exists; adds the key material TAMPER-2 excludes |
| **C** — document and accept | nothing mechanically; corrects the claim and records the residual | this note; later docstring/README/IDR-043 wording (ungoverned) | No | No | None now; `STATE.md` only if ordered (then B4 regeneration) | No | Only the expectation of machinery for a VALID finding; no invariant |

## 3. Recommendation

**C — document and accept, with a wording correction.**

The reasoning, in one sentence: the only keyless option (A) cannot make a
coordinated repository + database rewrite detectable without the
out-of-band journal tip that TAMPER-2 deferred and no ruling has scoped,
while its marginal coverage over the existing regeneration test — a
repository-only replacement with an intact, trusted database — does not
justify a new event-only writer, a per-database pin loop, and the
placement of ADVISORY test data in the research journal.

Two points must not be softened if the human chooses A instead:

1. A's force comes from the out-of-band tip, not from the chain. A
   self-consistent replacement of the database and the fixtures still
   verifies; the chain is only as good as the tip a human actually holds.
2. A does not turn the fixtures into tamper-evident data. It adds a
   historical cross-check against a database that, in a single-workstation
   deployment, the same actor can usually write. It should be described as
   "pinned against this journal", never as "tamper-evident".

## 4. The decision the human must make

The exact question, recommended answer, and repo consequences:

> **P2-4 (GAP-1) ruling.** Fixture integrity today is corruption-evident
> by name and regeneration-evident by test, not tamper-evident. Do we
> (A) add a `FixtureManifestPinned` event to the journal plus a
> `hermes fixtures verify` command, (B) open a key-custody track and sign a
> manifest, or (C) document-and-accept the boundary and correct the claim?
> Recommended: **C**. A does not close a coordinated repository + database
> rewrite without an out-of-band journal tip (which the repo does not
> create, store, or refresh), and it adds a new event-only writer and a
> per-database pin loop; B contradicts D5. C ships a wording correction
> only. Please rule A, B, or C.

What changes in the repository under each answer:

- **C.** This note lands. A follow-up docs-only commit corrects
  `ref_graphs.py:21-24`, `README.md:10-12`, and `P2-b4fixtures.md:277`
  to say "corruption-evident by name, regeneration-evident by test; a
  replaced file with a recomputed name is caught by regeneration, not
  by the name." No behavior, no tests, no migration, no governed
  document, no B4 regeneration. If the residual belongs in
  `docs/STATE.md`, that is a separate governed edit and a deliberate B4
  regeneration.
- **A.** Approve the new event-only writer and the CLI surface. No
  migration, no census change if `EventRepository.append_transactional` is
  reused, no governed document, no B4 regeneration. New tests live in a new
  file so the 24 pinned B4 tests stay 24. Operators must create a pin in
  each database and refresh it after every fixture regeneration; the claim
  remains "pinned against this journal", not "tamper-evident", unless a
  human-held tip is added (out of scope here).
- **B.** D5 must be reopened or explicitly scoped to include key custody
  before any design work. Then: key store, rotation/revocation, CI secret,
  verifier, an IDR, likely governed documentation and a B4 regeneration.
  Not implementable under D5 as it stands.

## 5. What ships under the recommendation (C)

The design phase shipped this note only. Under the recommended C, this
note ships the wording corrections listed in §4: no code behavior, no
tests, no migration, no fixture change, and no governed document;
`tests/test_b4_ref_graphs.py` stays at 24 tests and the four fixture files
stay byte-identical.

If the human overrules to A, the implementation outline is the surface in
§2 and §4: one `FixtureManifestPinned` event per pin (no migration, no
census delta via the existing append owner), a pure comparison in
`hermes.research` with the CLI doing the database read (no new upward
import), a new test file (B4 stays 24), and the falsifiers: a swapped
fixture with a recomputed name must fail verification; a deleted pin must
refuse; an extra or missing fixture must fail the set check; an edited pin
payload without a re-chain must fail the chain walk; a re-chain after a
payload edit must fail against a human-held tip; and a legitimate
regeneration must fail until re-pinned (that last one is the operational
cost, not a defect). If the human overrules to B, nothing ships until D5 is
amended and key custody is scoped.

Proposed `docs/STATE.md`-style paragraph, not landed in this slice (a
governed edit would move `b4-c1`/`c2`/`c4` and require regeneration):

> B4 reference-graph fixtures are ADVISORY/SIMULATED test data, never
> production state and never authority for any transition; no module under
> `src/` consumes them. Their integrity is corruption-evident (the file
> name is the sha256 of the bytes, so a damaged file fails the read) and
> regeneration-evident (the suite rebuilds every fixture from the governed
> corpus and requires byte equality). They are not tamper-evident: an actor
> who can write the repository can replace a fixture and recompute its
> name, and the regeneration check is itself code in that repository. The
> residual is accepted. A journal pin would relocate the check to a
> per-install database and would itself require an out-of-band tip to
> resist a coordinated rewrite; a signature would require key custody,
> which D5 excludes. Neither is warranted for advisory test data.

License: Apache-2.0 (LICENSE).
