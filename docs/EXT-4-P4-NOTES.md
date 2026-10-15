# EXT-4-P4-NOTES — P4 row documentation notes (EXT-1 items 7–12)

- **Slice:** `slice/ext-8-p4notes` (local-only, no push)
- **Base:** `main@034a4ac3b4766afc8a9106073620deb81e7fe3d2`
- **Triage input:** `audit/ext-1-triage@bc1a5da` — EXT-1 roadmap items **7–12**
  (priority **P4**; the durable board is `docs/EXT-1-ROADMAP.md`).
- **Scope:** documentation only. This slice adds no `src/` change and no
  behaviour change; every row below is a *recorded position*, not a fix. The
  deliverable is this file and nothing else (proof: `git diff --name-only`
  against the base reports exactly one new file).

Every `file:line` pointer in this document was re-verified **live** against the
base tree at authoring time; each resolves to the text quoted beside it.

Row map:

| Section | Row | EXT-1 item | Verdict recorded |
| --- | --- | ---: | --- |
| 1 | L4 | 7 | PARTIAL — documented; upgrade hazard + future-work trigger |
| 2 | L2 | 12 | DESIGN-BY-CERTIFIED-CONTRACT — determinism owns control |
| 3 | I1 | 8 | design gate — inapplicable to single-host CLI topology |
| 4 | I2 | 9 | DESIGN-BY-CERTIFIED-CONTRACT — no plausibility gate by construction |
| 5 | I3 | 10 | mostly implemented — CAS substance recorded, no change |
| 6 | I5 | 11 | design gate — single-host topology |

## 1. L4 — artifact `content_hash` is unversioned (EXT-1 item 7)

**Status:** PARTIAL — recorded here as documentation. No code change lands in
this slice. The upgrade hazard and the required dual-read/migration shape are
recorded as future work.

**Live pointers**

- `src/hermes/artifacts/store.py:29` — `def compute_content_hash(data: bytes) -> str:`
  — the digest is `hashlib.sha256(data).hexdigest()` over the raw bytes alone;
  the preimage carries **no schema/version token**.
- `src/hermes/artifacts/store.py:75` — `return Path(artifact_root) / content_hash[:2] / content_hash[2:4] / content_hash`
  — the on-disk layout is keyed on the bare 64-hex digest.
- `src/hermes/artifacts/store.py:153` — `content_hash=content_hash,`
  — the artifact metadata row records the bare digest verbatim.
- `src/hermes/artifacts/store.py:8` — `artifact content is orphaned but safe (no DB record = cannot be cited).`
  — the orphan semantics an unversioned key produces on a re-hash.
- Contrast, `fc_` preimages **do** carry a version:
  - `src/hermes/research/failure_classification.py:74` — `FAILURE_CLASS_SCHEMA_VERSION = "2"`
  - `src/hermes/research/failure_classification.py:887` — `"schema_version": FAILURE_CLASS_SCHEMA_VERSION,`
  - `src/hermes/research/failure_classification.py:910` — `content_hash = sha256_hex(canonical_json(content))`
  - `src/hermes/research/failure_classification.py:912` — `classification_id="fc_" + content_hash[:24],`
- Contrast, `cx_` preimages likewise:
  - `src/hermes/research/contradictions.py:140` — `{"schema_version": CONTRADICTION_SCHEMA_VERSION,`
  - `src/hermes/research/contradictions.py:145` — `return "cx_" + hashlib.sha256(raw).hexdigest()[:24]`
- `AGENTS.md:58` — `- Content-hash identity: `fc_`/`cx_`/`cres_`/`fx_`/`retract_` IDs are`
  — the recomputed-never-trusted identity discipline the artifact hash sits
  beside.

**What is intentionally NOT done, and why**

No version token is added to `compute_content_hash`, and no re-hash/migration is
run. Artifact identity is certified as content-addressed (IDR-008/009) and is
consumed as a trusted, recomputed key (`AGENTS.md:58`). Changing the preimage
now would silently re-key every stored artifact — breaking existing rows, the
sharded on-disk paths, and every stored `content_hash` reference. That is a
behaviour change, and this slice is docs-only.

**Upgrade hazard (recorded)**

The digest is taken over *canonical bytes* whose canonicalization is explicitly
the caller's responsibility (`store.py:29`). If a future canonicalization change
(e.g. newline or encoding normalization) is introduced, the same logical
artifact re-hashes to a different key: it is written under a new path, the old
row is orphaned-but-safe (`store.py:8`), and any citation of the old hash stops
resolving. The `fc_`/`cx_` preimages avoid exactly this class of break by
binding `schema_version` into the hashed dict (`failure_classification.py:887`,
`contradictions.py:140`).

**Future-work trigger**

Revisit only when a canonicalization or schema change to artifact bytes is
proposed. The required shape at that point: (a) a versioned preimage (e.g.
`sha256(version || canonical_bytes)`); (b) a **dual-read** window that accepts
both the legacy bare digest and the versioned digest; (c) a migration that
re-keys rows and paths without deleting (archive-not-delete, `AGENTS.md:52`).
No code lands until this trigger fires.

## 2. L2 — epistemic blindspot (EXT-1 item 12)

**Status:** DESIGN-BY-CERTIFIED-CONTRACT — recorded. The certified position is
that **determinism owns control**; the "blindspot" is a limitation of what the
system *claims*, not a missing control.

**Live pointers**

- `AGENTS.md:16` — `- Determinism owns control. No LLM/model output may decide a`
  — the invariant itself ("models are routed behind ports, never authorities").
- `src/hermes/research/evaluation.py:14` — `- **No LLM in evaluation.** Fully deterministic given (candidate set, state`
  — the deterministic evaluation library that survives the ratified verdict.
- `src/hermes/research/evaluation.py:16` — `- **No write path.** This module has no repository imports, no SQL, no`
  — the evaluator can never create tasks, spend budget, or promote evidence.
- `src/hermes/core/intents.py:124` — `def llm_proposable(cls) -> frozenset["IntentKind"]:`
  — the kinds a model MAY propose.
- `src/hermes/core/intents.py:144` — `def internal_only(cls) -> frozenset["IntentKind"]:`
  — the authority kinds a model may NOT propose.
- `AGENTS.md:49` — `- Prohibited-claims discipline: never claim scientific`
  — never claim scientific reproducibility, never present replay as validity,
  never present a digest/derived view as authority.
- `AGENTS.md:33` — `- Replay determinism: provider bytes replay identically through`
  — replay proves byte/evidence determinism only, never scientific validity.
- `docs/STATE.md:1` — `# Hermes current state (2026-09-21)`
  — the current-state reference (`docs/STATE.md` records what is certified *now*).

**What is intentionally NOT done, and why**

No "epistemic blindspot" detector, score, or gate is added to the control loop.
The blindspot is a *claim boundary*: the system is certified to make no
scientific-validity claim at all (`AGENTS.md:33`), so there is no epistemic
authority to instrument. Adding a surface here would invent authority the
architecture explicitly refuses.

**Future-work trigger**

Only a change to the claims the system makes (for example, presenting replay as
validity) reopens this. That is a certification-level change, not a slice: it
needs a design gate plus the owning certification slice re-run (`AGENTS.md:64`
documents the frozen-invariant discipline for N1/N9; the same rule governs the
control invariants).

## 3. I1 — mTLS / backpressure (EXT-1 item 8)

**Status:** design gate — **inapplicable** to the shipped single-host CLI
topology. Recorded here.

**Live pointers (why inapplicable)**

- `src/hermes/cli.py:1` — `"""CLI boundary (foundation decision §7).`
  — the system is driven by a one-shot CLI process ("Operational surface only;
  no business logic"), not a server.
- `src/hermes/security/egress.py:9` — `module therefore owns the socket:`
  — the only sockets in `src/` are **outbound**.
- `src/hermes/security/egress.py:353` — `self.sock = socket.create_connection(`
  — the outbound dial site. There is no inbound listener, no HTTP/RPC server,
  and no web-framework dependency: `pyproject.toml` core `dependencies` are
  empty (stdlib-first policy).
- `src/hermes/persistence/migrations.py:42` — `CREATE TABLE IF NOT EXISTS scheduler_lock (`
  — the single-row SQLite advisory lock; the writer is single and local.
- `src/hermes/research/controller.py:2878` — `def _acquire_lock(self) -> bool:`
  — the local lease acquisition guarding every tick.
- `src/hermes/research/gateway.py:106` — `ROLE = "ROLE"                       # proposed_by not permitted for this kind`
  — the refusal-code vocabulary (`gateway.py:106-122`; `class GatewayRejection`
  at `gateway.py:150`) a future admission surface would have to speak.

**What is intentionally NOT done, and why**

No mTLS, no connection-level peer auth, no queue-depth or backpressure control.
mTLS protects an inter-process network boundary that does not exist; backpressure
governs a request-admission queue that does not exist. Adding either would be an
unexercised surface with no caller — dead code against a non-existent boundary,
which the architecture's "no provider leakage / no unexercised surface"
discipline refuses.

**What a deployment WOULD need (if this ever becomes a service)**

1. A defined inbound listener and its trust boundary.
2. Peer identity at that listener (mTLS or equivalent).
3. An explicit admission/queue discipline with a bounded depth and a refusal
   code following the refusal-as-data convention (`gateway.py:106-122`).
4. A decision on whether the single-writer lease (`migrations.py:42`) becomes a
   distributed lock.

**Future-work trigger**

Any proposal to expose a network surface — a long-running server, an HTTP/RPC
API, or a remote worker pool. Until then: not applicable.

## 4. I2 — epistemic gate (EXT-1 item 9)

**Status:** DESIGN-BY-CERTIFIED-CONTRACT — recorded. A plausibility gate is
rejected by construction.

**Why a plausibility gate conflicts with determinism-owns-control**

A plausibility gate would let a model's judgment *decide* an admission or a
transition. The certified invariant is the opposite — models "are routed behind
ports, never authorities":

- `AGENTS.md:16` — `- Determinism owns control. No LLM/model output may decide a`
- `src/hermes/research/evaluation.py:1` — `"""ActionEvaluation — deterministic candidate-action comparison (Optimizer decision).`
  — the ratified verdict recorded in the module docstring: the
  optimizer-as-authority was **rejected**; what survives is "pure, deterministic
  comparison of **existing admissible candidate actions**".
- `src/hermes/research/evaluation.py:14` — `- **No LLM in evaluation.** Fully deterministic given (candidate set, state`
  — no model participates in evaluation at all.

The authority boundary is encoded at the type level:

- `src/hermes/core/intents.py:124` — `def llm_proposable(cls) -> frozenset["IntentKind"]:`
  — a model may propose a bounded set of kinds.
- `src/hermes/core/intents.py:144` — `def internal_only(cls) -> frozenset["IntentKind"]:`
  — a model may not propose the authority kinds (contradiction resolution,
  classification, retraction, and the rest of the internal-only set).

All mutation still funnels through one authoritative path:

- `src/hermes/research/gateway.py:4093` — `def apply_intent(`
  — the single authoritative mutation path that validates and refuses
  deterministically.

**What is intentionally NOT done, and why**

No plausibility/admission gate that consults a model is added. Such a gate would
either (a) be advisory only — in which case `evaluation.py` already provides the
deterministic advisory comparison and no new surface is needed — or (b) be
authoritative, which `AGENTS.md:16` prohibits. There is no third option that
keeps the invariant.

**Future-work trigger**

Reopening requires a certification-level change to the determinism-owns-control
invariant: a design gate plus the owning certification slice re-run. Not a
slice-level change; no code lands here.

## 5. I3 — content-addressed store (CAS) (EXT-1 item 10)

**Status:** mostly implemented — the existing substance is recorded here. No
code change.

**Existing substance (live pointers)**

- Content-addressed store: `src/hermes/artifacts/store.py:3` —
  `Filesystem-backed content-addressed store (IDR-008):`; key = SHA-256 of the
  bytes (`src/hermes/artifacts/store.py:29`); sharded path derived from the
  digest (`src/hermes/artifacts/store.py:75`).
- Pre-proceed dereference (read path):
  - `src/hermes/persistence/source_outcomes.py:454` — `def dereference_ref(self, project_id: str, ref: str) -> bool:`
    — typed prefix match, full 64-hex only; resolves the ref **before** bytes
    are handed on.
  - `src/hermes/persistence/source_outcomes.py:477` — `def read_payload_bytes(self, ref: str) -> bytes | None:`
    — returns the bytes through the verified read.
  - `src/hermes/persistence/source_outcomes.py:517` — `return self._store.read_verified(artifact_id)`
    — the decision read path re-derives the key (EXT-1 R2).
- Pre-proceed dereference (write path):
  - `src/hermes/persistence/repositories.py:73` — `# Write-path dereference vocabulary for ``_dereference_artifact_ref```
    — the CLOSED vocabulary (a type with no explicit decision never passes
    silently).
  - `src/hermes/persistence/repositories.py:83` — `DEFERRED_ARTIFACT_CARRIERS = frozenset({"task_evidence", "task_output"})`
    — the deferred carriers (form-checked only, no store yet).
  - `src/hermes/persistence/repositories.py:1976` — `def _dereference_artifact_ref(self, project_id: str, ref: str) -> bool:`
    — the write-path dereference.
  - `src/hermes/persistence/repositories.py:2141` — `if not self._dereference_artifact_ref(project_id, c.source_ref):`
    — claim `source_ref` dereferenced before the write.
  - `src/hermes/persistence/repositories.py:2149` — `if not self._dereference_artifact_ref(project_id, r):`
    — assumption supporting refs dereferenced before the write.
- Production wiring from EXT-2:
  - `src/hermes/artifacts/store.py:170` — `def read_verified(self, content_hash: str) -> bytes:`
    — fail-closed verified content-addressed read (re-derives the key).
  - `src/hermes/artifacts/store.py:213` — `def verify_integrity(self, artifact_id: str) -> bool:`
    — the recorded-hash comparison.
  - `src/hermes/research/controller.py:5461` — `except ArtifactIntegrityError as exc:`
    — the EXTRACT seam routes a tampered read to a named, terminal refusal
    (EXT-2 audit S1).
  - `docs/MERGE-LOG-EXT-2.md:1` — `# MERGE-LOG-EXT-2 -- local FF of slice/ext-2-restacked2@863f4b1`
    — lineage: `e7b446e` → `bafb138` → `863f4b1`.

**What is intentionally NOT done, and why**

No new CAS layer is added. The store is already content-addressed and
integrity-verifiable, and EXT-2 already wired verification into production — so
the triage observation that `verify_integrity` had zero production callers is
closed (the verified read is now reached at `source_outcomes.py:517` and guarded
at `controller.py:5461`). Adding a second CAS abstraction would duplicate a
certified substrate and risk two sources of truth for artifact identity.

**Future-work trigger**

Only if a *new* artifact class is introduced that needs a store. The deferred
carriers (`repositories.py:83`) are the known candidates. When such a store
lands it becomes a real resolver inside the same closed vocabulary
(`repositories.py:73`) — never a silent form-checked pass.

## 6. I5 — hardware fencing (EXT-1 item 11)

**Status:** design gate — single-host topology. Recorded here.

**Live pointers (why inapplicable)**

- `src/hermes/recovery/leases.py:2` — `leases — Phase 0 contract stub.` and
  `src/hermes/recovery/leases.py:5` — `Implementation arrives in later phases per architecture §24.`
  — there is no hardware-level lease; the module is a contract stub.
- `src/hermes/persistence/migrations.py:42` — `CREATE TABLE IF NOT EXISTS scheduler_lock (`
  — `scheduler_lock`, a single-row advisory lock inside the SQLite database.
- `src/hermes/research/controller.py:2878` — `def _acquire_lock(self) -> bool:`
  and `src/hermes/research/controller.py:2921` — `def _release_lock(self) -> None:`
  — the lease is process-level.
- `src/hermes/persistence/database.py:96` — `def acquire_writer_lock(conn: sqlite3.Connection, owner_id: str = "default",`
  and `src/hermes/persistence/database.py:151` — `def release_writer_lock(conn: sqlite3.Connection,`
  — the underlying acquire/release primitives.
- `src/hermes/research/controller.py:941` — `def tick(self) -> TickResult:`
  — "A second live controller fails the lock and returns `idle="lock_held"`
  without dispatching anything"; contention returns `LOCK`
  (`src/hermes/research/controller.py:949`).
- `AGENTS.md:55` — `- Lease-fenced single writer: controller surfaces acquire the`
  — the invariant: the lease is in one SQLite file on one host.

**What is intentionally NOT done, and why**

No fencing token that survives host failure, no STONITH/BMC integration, no
distributed consensus. Fencing exists to stop a *partitioned writer on another
host* from mutating shared state. Here the shared state is a local SQLite file
and the only writer is the local controller, so there is nothing to fence — an
unexercised fencing layer would be dead code against a topology that does not
exist.

**What a distributed deployment WOULD need**

1. A shared durable store with a real lease/epoch: a monotonically increasing
   fencing token returned on acquire and checked on every write, so a stale
   writer is rejected after a lease loss.
2. A failure detector that is not host-local (the current `NO_SIGNAL` ladder,
   `controller.py:941`, runs inside one process).
3. An operator path for the fence, replacing `scheduler_lock`
   (`migrations.py:42`) with a lease service, plus the owning certification
   slices re-run.

**Future-work trigger**

Any proposal to run controllers on more than one host against shared state.
Until then: not applicable.

License: Apache-2.0 (LICENSE).
