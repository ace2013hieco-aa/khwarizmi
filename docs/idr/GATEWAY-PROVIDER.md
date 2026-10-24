# OPS-6 — admit `oxionai.com` as a hosted-model provider

| Item | Value |
| --- | --- |
| Task | OPS-6: let the operator's key for an OpenAI-compatible gateway serve a `[model_tiers]` ref |
| Base | `082d7cc` (`main`) |
| Branch | `slice/ops-6-gateway` |
| Phase | 1 — design gate (this note); phase 2 — implementation on the same branch |
| Status | **RULED (2026-10-24)** — `oxionai` is admitted as one reviewed provider entry; nothing about the pin mechanism changes |

## Decision

The code-owned policy tables in `src/hermes/composition.py` grow by exactly
one provider:

- `_MODEL_REGISTRY` gains `"oxionai": ("openai", "OXIONAI_API_KEY")` — an
  OpenAI-dialect provider whose key is read from its own environment variable,
  never `OPENAI_API_KEY`.
- `_DIALECT_HOSTS["openai"]` gains `"oxionai.com"` — the apex host only.

A `[model_tiers]` ref of `oxionai:<model>` then resolves to a
`CloudModelSpec` whose `host` is `oxionai.com`. Nothing in
`config/hermes.toml` names a host or a URL, and no operator surface gains a
free-form endpoint setting.

This is a **trust decision, not a configuration value**. The reviewable diff
above is the record of that decision; a config edit is neither necessary nor
sufficient to repeat it.

## 1. What is being trusted

The credential and every prompt and response pass through a third party.
`oxionai.com` terminates TLS, receives the `Authorization: Bearer` header,
receives the full request body (system text, rationale, and every untrusted
evidence block), and produces the completion this plane parses. The gateway
sees all of it and can retain, log or transform it outside this repository's
control.

That is a deliberate operator decision, recorded here, not a default. The
shipped default remains the two vendor hosts; an unconfigured tree sends
nothing to the gateway. Configuring a tier is an explicit act, and the code
change that made `oxionai` nameable is this note plus its reviewed diff.

The operational facts below were probed by the Director against the live
gateway and are evidence for this decision, not a live dependency of the
suite:

| Probe | Result |
| --- | --- |
| `GET https://www.oxionai.com/v1/models` | HTTP 403 (Cloudflare `1010`) — the `www.` host is **not** usable |
| `GET https://oxionai.com/v1/models` | HTTP 200, 33 model ids |
| `POST https://oxionai.com/v1/chat/completions` | HTTP 200, OpenAI shape: `choices[0].message.content`, `finish_reason`, `usage` |
| Auth | `Authorization: Bearer <key>` |
| `claude-opus-5.5` | present in the catalog; the response echoes `model: claude-opus-5.5` |

## 2. What is *not* being claimed

The model identity is the **gateway's assertion**, not a vendor-verified
fact. When a response echoes `model: claude-opus-5.5`, this plane records that
the gateway said `claude-opus-5.5`; it does not and cannot verify which
weights, vendor or region produced the bytes. Any run report that names a
model names what the gateway said, and must say so. The provider id in the
dispatch ledger is `oxionai`, so the origin of the assertion is visible beside
the model string.

Nor is anything claimed about the gateway's availability, latency, data
retention, logging, subprocessors, model catalog stability, or the truth of
its `/v1/models` listing. The catalog is a gateway claim. Replay determinism
is unaffected and still proves byte/evidence determinism only — never
scientific validity.

## 3. How the boundary stays narrow

One provider entry, one host, both code-owned:

- The only new nameable provider is `oxionai`; an unknown provider still
  refuses by name (`specs_from_tiers`), and `oxionai`'s endpoint comes from
  the code-owned `_PROVIDER_HOSTS` binding, never from config.
- The only new destination is `oxionai.com`; `CloudModelSpec.__post_init__`
  still refuses any host outside `_DIALECT_HOSTS`, so even a code path that
  tried to set `www.oxionai.com` or `evil.example` would fail closed.
- `HostPinnedTransport` is unchanged. It still requires plain HTTPS on the
  default port, no userinfo and no fragment, vets every resolved address
  through the S2 egress rule layer, and pins the vetted address for exactly
  one request (check-time == dial-time).
- The credential still lives only in `headers_meta`; it is never placed in a
  body, prompt, error, log line or test fixture, and the existing secret-leak
  guard still refuses a leaking request.

The pin is unchanged in **mechanism** — only the allowlist grows by one
reviewed entry. `config/hermes.toml` is untouched, and no config value can
name a host.

## 4. Why not a general "custom base URL"

A config-supplied host would put the credential's destination in a config
file. That is precisely the hole the allowlist exists to prevent: anyone who
can edit the config (or hand the operator a config) could redirect the bearer
token and every prompt to an arbitrary server, and the refusal that protects
the credential would have to be removed to allow it. A host allowlist that
accepts arbitrary hosts is not a boundary; it is a comment.

The reviewed alternative is deliberately smaller: adding a gateway is a code
change with an owner, a diff and a test, and the resulting host is visible in
the same table that validates it. The operator learns the trade in review,
not by discovering where the key went.

## Implementation consequences

1. **Resolution.** `specs_from_tiers` must build the `oxionai` spec with
   `host="oxionai.com"`. A blank host would select the dialect default
   (`api.openai.com`) and send the gateway's key to OpenAI, so the gateway
   binding is part of the reviewed provider entry, not an inference from the
   dialect. Concretely: the registry entry stays `(dialect, api_key_env)`; a
   second code-owned table, `_PROVIDER_HOSTS`, binds a non-canonical provider
   id to its endpoint. A registry entry that is not the dialect's own provider
   and has no host binding refuses by name, so a future gateway cannot silently
   inherit the vendor host.
2. **Empty completion at the output budget is a named refusal.** With a
   too-small `max_tokens`, this gateway's reasoning models return
   `finish_reason: "length"`, `content: null`, and reasoning tokens counted
   against the completion budget. The OpenAI-dialect parser must raise a
   `PermanentProviderError` naming the output budget instead of returning an
   empty string to the contract parser. Empty content with
   `finish_reason: "stop"` keeps today's behavior (the router's contract
   refusal), because that is a different fact.
3. **No live network in tests.** Registry/host tests construct specs and
   scripted transports only; the empty-content tests feed recorded bytes.
4. **Governed surfaces stay put.** `docs/STATE.md` and `docs/API.md` do not
   change: no public surface, command, refusal code or architecture rule is
   added. This note is an ungoverned IDR, so the B4 reference graphs stay at
   24 and `docs/SUITE-COUNT.md` is the only generated doc this slice restamps.
