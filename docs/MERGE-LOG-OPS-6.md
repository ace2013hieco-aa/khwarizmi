# MERGE-LOG-OPS-6 — the gateway is admitted, on the record (wave 4)

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-6: admit `oxionai.com` as a provider; refuse budget-empty replies |
| Base (`main` before) | `082d7cc` |
| Slice | `slice/ops-6-gateway` — three commits, **fast-forwarded** |
| Landed tip | `cc39b524e8f3b232d45e2e4ab696fa00a1f1d499` (tree `b5a61e6e…`) |

```
 docs/idr/GATEWAY-PROVIDER.md      | 132 ++  (the trust decision)
 src/hermes/composition.py         |  40 +-  (three code-owned tables)
 src/hermes/tools/models/cloud.py  |  17 +-  (the budget refusal)
 tests/test_cloud_provider.py      |  56 +-  (the refusal matrix)
 tests/test_ops1_live_cli.py       |  45 +-  (drain-only byte-identity with tiers)
```

`config/hermes.toml`, `docs/STATE.md`, `docs/API.md`, `AGENTS.md` and the governed B4 cohort:
**0 changed files**. B4 stays 24.

## The boundary moved by exactly one reviewed entry

```
"openai": frozenset({"api.openai.com", "oxionai.com"}),
"oxionai": ("openai", "OXIONAI_API_KEY"),
```

`www.oxionai.com` is deliberately absent — it answers HTTP 403 (Cloudflare `1010`).

## The catch that mattered: `_PROVIDER_HOSTS`

The registry maps a provider to `(dialect, env var)` — it carries **no endpoint**. A provider
named `oxionai` with dialect `openai` and no host would therefore have defaulted to
`api.openai.com`, sending the **gateway's key to OpenAI**. The agent added a third code-owned
binding:

```
_PROVIDER_HOSTS = {"oxionai": "oxionai.com"}
```

and made an unbound non-canonical provider refuse by name instead of inheriting the vendor host.
That is the difference between "we admitted a gateway" and "we leaked a key to the wrong vendor";
it is the most important line in the diff.

## What the note records

1. **The trust.** `oxionai.com` terminates TLS, receives the bearer token and the full request
   body — system text, rationale, every untrusted evidence block — and produces the completion
   this plane parses. Deliberate, recorded, not a default; an unconfigured tree sends nothing.
2. **The non-claim.** `model: claude-opus-5.5` is the **gateway's assertion**. The plane records
   what the gateway said, not which weights produced the bytes. The ledger's provider id is
   `oxionai`, so the origin of the assertion sits beside the model string.
3. **The narrowness.** One provider, one host, both code-owned; `HostPinnedTransport` unchanged;
   the credential still lives only in `headers_meta`.
4. **Why not a custom base URL.** A config-supplied host would put the credential's destination in
   a config file. *"A host allowlist that accepts arbitrary hosts is not a boundary; it is a
   comment."*

## The budget refusal

Probing the gateway at `max_tokens: 8` returned `finish_reason: "length"` with `content: None` and
`reasoning_tokens: 6` — these are reasoning models, so a small budget yields **empty content, not
an error**. Left alone, the first real run would have looked blank for a reason nobody could
guess. Now:

```
EMPTY_COMPLETION: the reply had no content and finish_reason='length' — the output budget
(max_output_tokens) was exhausted before any text (completion_tokens=3); raise the model's
output budget (reasoning tokens count against it)
```

`PermanentProviderError` / `MALFORMED_200` — not retried. Empty content with `finish_reason="stop"`
behaves as before, and both branches are pinned.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted (cloud, OPS-1 CLI, B4, census) | **139 passed**; Director re-ran **128** at the merged tip |
| Full suite | **5105 passed / 3 skipped / 0 failed** |
| `stamp_suite_count.py --check` | `collected=5108` — **verified in a clean tree** |
| `check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0 |
| B4 ref graphs | **24 passed** |
| `ruff` / `pyright src` / tests | clean / **0/0/0** / **0 errors, 1 known warning** |

**On the stamp:** the agent's canonical run quarantined an untracked local probe
(`tests/test_audit_e1_prompt_probe.py`, 2 tests, sha256 unchanged, restored afterwards). The
Director's first check ran in a checkout where that probe was present and reported `5108 vs 5110`
— that is the probe, not the branch. In a clean tree the stamp matches exactly.

## Residuals

1. **The gateway is a third party.** Availability, latency, retention and the truth of
   `/v1/models` are all unverified and unclaimed.
2. **The model identity is asserted, not proven.** Any run report must say so.
3. `www.oxionai.com` remains unusable; a future gateway change that moves the endpoint is a code
   change, by design.

License: Apache-2.0 (LICENSE).
