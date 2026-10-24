# Hermes API reference

Stability labels — minimal convention, no versioning machinery:
FROZEN-BY-DECISION (changes only via architecture decision +
migration where state is involved); EVOLVING (documented in PRs,
tested); INTERNAL (free to change); UNDECLARED (callable today, no
promise — do not rely on it).

## CLI — PUBLIC / SUPPORTED, EVOLVING

Entry `hermes.cli:main` (`src/hermes/cli.py:760`,
`pyproject.toml` `hermes = "hermes.cli:main"`). Subcommands
(`_build_parser`, `cli.py:657`): `init`, `doctor [--json]`,
`backup`, `restore`, `status [--json]`, `audit [--project] [--json]`,
`project create|show`, `task show`, `events`, `pause|resume`,
`run <project_id> [--ticks N] [--drain-only]` (drives
`Controller.run`), `gate resolve <task_id> --verdict
APPROVED|REJECTED --operator (--token | --token-stdin)`, `operator
register (--token | --token-stdin)`.

The `run` mode is config-driven. With no `[model_tiers]` ref — the shipped
default — or with `--drain-only`, it composes no model plane and no handlers:
EXTRACT tasks keep their diagnostic, GATE tasks stay unhandled, HUMAN_GATE
tasks park, and the output is byte-identical to the pre-OPS-1 CLI. With at
least one tier naming a registry provider (`anthropic`, `openai`; a
code-owned table, not config) it composes the model plane and the methodology
handler, refuses (exit `1`, before the database is opened) on an unknown
provider, a malformed ref, a missing provider key or a broken profile tree,
and on success prints one `Model plane: live (tiers: ...)` line before the
first tick, one `model call` row per provider attempt (tier, provider, model,
outcome, token counts — never a price; capped at 20 with a remainder line),
and one `vector:` line after the run. Live is the only mode that prints those
lines, so silence means the model plane was never composed. The provider key
comes from the environment named by the registry and is never printed, logged
or traced. Reachability is not certification: no run output is evidence of
scientific validity or reproducibility.
`--config PATH` selects `hermes.toml` (schema `config.py`;
secrets never in config). `--json` emits one parseable document,
errors to stderr. Exit codes: `0` success, `1` operational
refusal/error; boundary never crashes (`cli.py:496`). Operator
tokens: `--token-stdin` (one line from stdin) is the preferred
channel — argv is visible to process inspection and shell history.
There is deliberately no env-var channel: the environment is
equally inspectable and is inherited by child processes.

## Controller — PUBLIC / SUPPORTED for listed methods, EVOLVING

Construct `Controller(conn, project_id=…, clock=…,
task_handlers=…, artifact_store=…)` (`controller.py:388`).
Workflow: `tick()` (`:482`, one pass, returns `TickResult`),
`run(max_ticks=1000)` (`:597`, until idle).
Verdict ingestion (credential + lease + recorded HumanDecision;
return `{"rejected": True, "code", "detail"}` on refusal):
`record_failure_classification` (`:2162`),
`record_contradiction_resolution` (`:2052`),
`record_source_retraction_decision` (`:1725`),
`resolve_human_gate` (`:1246`), `register_operator` (`:1214`),
`record_operator_decision` (`:1441`), `record_scope_review_decision`
(`:1518`), `record_curation_decision` (`:1599`).
Detection/reads (advisory, never authority): `detect_contradictions`
(`:1872`), `classification_proposals` (`:620`), `reconcile_digest`
(`:1047`), `re_review_candidates` (`:748`), cone/radius readers
(`:667-:716`), `notes` property (`:476`, read-only diagnostics).
UNDECLARED: all `_`-prefixed methods (fence, leases, passes,
resolvers) — internal even where importable.

## Intents — PUBLIC vocabulary / FROZEN-BY-DECISION values

`IntentKind` (`src/hermes/core/intents.py:26`, 21 members): LLM-proposable (9:
`intents.py:115`), director-only (4: `:124` — CRED-1 adds the
credential-lifecycle kinds, REVOKE/ROTATE_OPERATOR_CREDENTIAL),
`internal_only` (9: `:135` — admission, resolution, retraction,
classification, curation, contradiction record, scope decision,
proposal resolution, parallel-regime emission). Adding a kind, moving
a partition, or redefining a value string is an architecture decision.
`apply_intent` (`gateway.py:3732`) is the sole mutation entry;
refusal codes (`gateway.py:93-108`: `ROLE`, `OPERATOR`, `LOCK`,
`PROPOSAL`, `EVIDENCE_REF`, `MALFORMED_PAYLOAD`, `STALE`,
`RATIONALE`, …) are EVOLVING in set but FROZEN in meaning once
emitted against a certified behavior.

## Lease contention — `LOCK` is retryable; nothing else is

Controller write surfaces acquire the single-writer lease before
calling `apply_intent`. Contention returns
`{"rejected": True, "code": "LOCK", "detail": …}` as data before any
durable write. Retry rule: `LOCK` is the only controller refusal that
clears by waiting — retry the same intent with a client-owned bounded
backoff. `ROLE`, `OPERATOR`, `RATIONALE`, `PROPOSAL`, `STALE`,
`EVIDENCE_REF` and `MALFORMED_PAYLOAD` are deterministic refusals; a
retry cannot change them. The system performs no automatic retry or
backoff. A mid-tick lease loss aborts the tick with rollback
(`lock_lost`), and leases are generation-fenced, so a `LOCK` or a
lost lease never leaves a partial write or admits a superseded
holder's write.

## Provider adapters — PUBLIC / SUPPORTED, EVOLVING

Implement `ProviderAdapter` (`tools/providers/base.py:139`): exactly
`build_request`, `parse_page`, `extract_ids`, `build_fetch_request`
(`:144-161`) plus optional `validate_fetch` (`:165`); register in
`PROVIDER_REGISTRY` (`src/hermes/tools/providers/adapters/__init__.py:37`, 15 adapters);
declare hazards/rate profile per provider. Transports: `Transport`
and `ProviderRateLimiter` protocols (`base.py:182-217`); replay via
`RecordedTransport` (`replay.py:293`) + fixture identity `fx_`.
Adapter code may import `hermes.tools.*` only (recorded exception:
`hazards.py:137`).

## Events / records — PUBLIC shapes / FROZEN-BY-DECISION

`EventType` catalog (`core/events.py`); payloads bounded 4 KiB
(`event_validation.py`); correlation IDs carry identity
(`cx_…`, `cres_…`, `retract_…`, `classification-decision-…`).
Content identities (`fc_`/`cx_`/`cres_`/`fx_`) are recomputed by
rule (`contradictions.py:75`, N9 predicate
`source_outcomes.py:159`) — clients must never author them.
Artifact/edge/contradiction row shapes: INTERNAL (read via
repository readers: `ContradictionRepository`
(`repositories.py:2656`, read-only), `classifications_for_project/
for_evidence`, `dereference_failure_classification_ref`).

## Repositories — INTERNAL (except via Controller/CLI)

Writers own their transactions and enforce binding/identity rules;
direct construction is test/operational scaffolding, not a supported
external surface (STABILITY: UNDECLARED — DECISION REQUIRED before
any external reliance). Direct SQL mutation outside repository write
boundaries is forbidden (AGENTS.md).

## Errors — EVOLVING set, FROZEN meanings

Gateway codes above; controller `OPERATOR`/`LOCK`/`RATIONALE`/
`DETECTOR`/gate codes; `IDEMPOTENCY_CONFLICT` when a repeated
decision identity arrives with different content (a repeat is only
an idempotent replay when its payload matches); completion denials
(`NO_PROGRAM`,
`OPEN_CONTRADICTION`, … `completion.py:96-101`); provider
`ProviderError` hierarchy (`research_sources.py:614-703`) +
`ReplayUnavailableError`. New codes require the behavior they
refuse to be specified and tested; meanings never silently change.
