"""Provider machinery for the ResearchSourceProvider slice (Part 3, IDR-030).

Module layout (blueprint §1):
  normalize.py   — parse_query_hints / normalize_identifier / dedup keys
  redact.py      — RedactionPolicy + redact_url / redact_params / redact_headers
  base.py        — ProviderAdapter ABC + contract cards (step 3)
  http.py        — the single HTTP client (step 4)
  hazards.py     — ProviderHazardSpec + one generic evaluate_hazards (step 2)
  paginate.py    — walk()/fetch_batch() drivers (steps 3/5a)
  ratelimit.py   — ProviderRateLimiter (step 4)
  replay.py      — RecordedTransport + fixture loader (CHG-2)
  adapters/      — the 11 thin adapters + PROVIDER_REGISTRY (CHG-2, step 5)
  hazard_specs/  — versioned machine-readable specs (step 2; 4/11 shipped)

Only-entry-point invariant (PS-03): the Tool Runtime owns the only `Transport`,
and the only entry points into the provider machinery are the runtime's `walk()`
and `fetch_batch()`. The provider package is not instantiable outside the runtime
context. The adapter registry (`PROVIDER_REGISTRY`, allowlist-enforced) is
code-owned — registry membership == §27 item 55 allowlist membership
(registry/allowlist drift fails import).
"""
from __future__ import annotations

__all__: list[str] = []
