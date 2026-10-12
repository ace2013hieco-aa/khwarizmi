# ResearchSourceProvider — Step 6 FINAL INDEPENDENT REVIEW

**Date:** 2026-08-14 · **Auditor:** independent reviewer (no role in the
step-6 implementation or the R01–R04 remediation) · **HEAD at review:** the
S6-R01…R04 remediation commit `5e760ea` + the R01-resolver fold-in (this
package) · **Scope:** hostile re-verification of ALL four remediated
surfaces with fresh probes.

## Verdict

**READY FOR STEP 7.**

The four semantic cracks named by the second-round review are closed and
survive independent hostile probing:

1. **project lineage is explicit** — same-project `search_task_id` at
   admission AND in-transaction; refs must resolve FROM the cited search
   (two-hop); the cited search must be a declared dependency edge; the
   execution scope is the spec refs.
2. **artifact type is bound to content reuse** — same hash + different type
   is refused on BOTH reuse surfaces (`_verify_reused_row` for result rows
   and the slice write boundary for payload rows).
3. **task bounds are the runtime bounds** — `max_sources` /
   `size_cap_bytes` / `retry_policy` carried builder → gateway → persisted
   spec → `FetchRequest`; over-bound/malformed rejected at admission; no
   silent default substitution.
4. **provider routing is explicit and consistent** — required + allowlisted
   at admission and in the builder; fetch provider must agree with its
   cited search's provider at the write path.

## Probe battery (fresh, 20 probes)

| Surface | Probes | Result |
|---|---|---|
| R01 lineage | 6 (same-project PASS; cross-project REJECT; cross-project shared-artifact REJECT; direct-repo bypass REJECT; forged search_task_id REJECT; non-dependency REJECT) | 6/6 PASS |
| R02 type | 2 (existing source_result vs proposed source_payload REJECTED — the payload write boundary; same-type NEW→IDENTICAL) | 2/2 PASS |
| R03 bounds | 8 (over-bound max_sources 51/0/True, over-bound size, malformed retry ×3, custom bounds persisted) | 8/8 PASS |
| R04 provider | 4 (absent/unknown/non-string REJECTED; fetch/search mismatch REJECTED at write) | 4/4 PASS |

**One new finding surfaced by this review and folded in (P2):** the payload
write path dedups by hash through the type-blind `ArtifactStore`, so an
existing `source_result` row carrying a payload's content hash was silently
"deduped" — a successful fetch write whose payload row was actually typed
source_result (the exact R02 "successful write followed by resolver
failure" class, in the fetch direction). Closed at the slice write boundary:
`_prepare_fetch` refuses a returned row whose `artifact_type` is not
`source_payload`. Regression fixture:
`test_payload_reuse_requires_payload_type`.

## Verification

- Probe battery: **20/20 PASS**.
- Orchestration suite: **44 passed** (36 + 6 R01–R04 + 2 review-fold-ins).
- Full suite: **892 passed** (890 + 2), 0 failed, 0 errors.
- Pyright (`npx pyright src`): **0 errors, 0 warnings**.
- Ix: no new structure from the fold-ins (SELECT-only + a handler filter);
  baseline comparison stands (153 → 161, all documented orphan-class
  deltas).

## Remaining conditions (explicitly NOT claimed)

- Step 6 **RATIFIED-as-implemented**: NOT CLAIMED — the external closure
  gate remains the standing authority.
- Step 7 of 7 (record/replay acceptance): NOT STARTED — the next action,
  per the review sequence (final review → step-7 acceptance gate).
- Slice **EXTERNALLY VERIFIED**: NOT CLAIMED.

## Recommendation

The final step-6 review gate concludes **READY FOR STEP 7**. The next
scheduled step is the step-7 record/replay acceptance run against the
blueprint's `RecordedTransport` harness, followed by the external
independent closure gate before any RATIFIED / EXTERNALLY VERIFIED claim.
