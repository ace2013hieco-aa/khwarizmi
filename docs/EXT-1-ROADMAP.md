# EXT-1 Remediation Roadmap

Source: AUDIT-EXT-1-TRIAGE.md (audit/ext-1-triage@bc1a5da) — adjudication of the external workflow audit. Base: main@3eed0a6. This is the durable board for the external-audit remediation program. Status-only edits after landing; history is never rewritten.

| # | Item | Verdict | Priority | Slice | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | L3 N9 predicate state-drift | PARTIAL — frozen invariant (AGENTS.md); 4 certified sites vs ≥4 resolve paths without the predicate; no path-enumerating pin | P0 | EXT-3 | LANDED-PIN (1a42183) / wiring GATE-BLOCKED |
| 2 | R2 artifact read verification | PARTIAL — verify_integrity had zero production callers | P1 | EXT-2 | LANDED (863f4b1) |
| 3 | L1/I4 journal growth + archival | VALID — no compaction/retention/archival; journal holes read as tampering | P2 | EXT-4 | LANDED (df4a579) |
| 4 | R3 CLI control-byte scrub | PARTIAL — unescaped reason column, no ANSI strip (cli.py:283-288) | P3 | EXT-5 | LANDED (c22441e) |
| 5 | R4 OPEN-contradiction bound | PARTIAL — no cumulative OPEN bound (LLM-flood path already blocked: internal-only kinds) | P3 | EXT-6 | LANDED (4fad0a6) |
| 6 | I6 batch verdict | design gate — changes certified human-authority shape (one verdict per cres_ id) | — | EXT-7 | BLOCKED-HUMAN |
| 7 | L4 hash-versioning | PARTIAL — artifact content_hash unversioned; fc_/cx_ preimages carry schema_version | P4 | EXT-8 | QUEUED |
| 8 | I1 mTLS/backpressure | design gate — inapplicable to single-host CLI topology | P4 | EXT-8 | QUEUED |
| 9 | I2 epistemic gate | DESIGN-BY-CERTIFIED-CONTRACT — determinism owns control | P4 | EXT-8 | QUEUED |
| 10 | I3 CAS | mostly implemented — content-addressed store + pre-proceed dereference | P4 | EXT-8 | QUEUED |
| 11 | I5 hardware fencing | design gate — single-host topology | P4 | EXT-8 | QUEUED |
| 12 | L2 epistemic blindspot | DESIGN-BY-CERTIFIED-CONTRACT | P4 | EXT-8 | QUEUED |
| 13 | R1 lease split-brain | INVALID — rejected with live proof (no lease coordinator exists in src/) | — | — | CLOSED-REJECTED |

Legend: QUEUED / CHARTERED / IN-FLIGHT / LANDED-PENDING-AUDIT / LANDED (hash) / BLOCKED-HUMAN / CLOSED-REJECTED.

Update rule: each landing edits only its row's Status; rows may be appended; nothing is deleted. EXT-8 is a docs-only batch covering items 7-12 unless a row escalates to a code slice.

Execution order is risk-ranked (P0 first). Every slice follows: implement → Director verify → redteam-audit → fix → merge-gate → dual push (origin + public mirror; D9 approval lapses after each landing). I6 (item 6) requires a human decision before chartering.

License: Apache-2.0 (LICENSE).
