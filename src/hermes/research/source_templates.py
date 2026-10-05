"""SOURCE_SEARCH / SOURCE_FETCH task templates (ResearchSourceProvider step 6).

The deterministic template layer for the source-slice task graph (design record
`hermes_researchsourceprovider_step6_orchestration_design.md` D2/OQ-5/OQ-6):

- ``SOURCE_SEARCH_TEMPLATE`` / ``SOURCE_FETCH_TEMPLATE`` — the canonical,
  normalized template markers the gateway matches on (a hand-built payload
  cannot case-spoof past admission, V6-P7-E01 precedent).
- The pinned C-tier contract: RESEARCHER profile + ``small`` cost class
  (OQ-5).
- The builder-carried bounds (OQ-6): ``page_size``/``max_pages``/
  ``size_cap_bytes`` for search, ``max_sources`` for fetch — positive and
  capped at the S11 scale-class ceilings; over-bound requests are rejected at
  admission, never at execution.
- ``build_source_search_task_payload`` / ``build_source_fetch_task_payload`` —
  the deterministic INSERT_TASK payloads (task id + idempotency key
  content-derived from (provider, hints, bounds, template version) / (search
  task, source refs, template version) — re-running the planner cannot
  duplicate work, AC-05 discipline).

Pure and read-only: no DB, no events, no intents. The gateway imports the
marker/profile/bounds for admission (OQ-5); the handlers import the builders.
"""

from __future__ import annotations

from typing import Any

from hermes.research.programs import canonical_json, sha256_hex
from hermes.tools.research_sources import SOURCE_PROVIDER_ALLOWLIST

__all__ = [
    "DEFAULT_SOURCE_MAX_PAGES",
    "DEFAULT_SOURCE_MAX_SOURCES",
    "DEFAULT_SOURCE_PAGE_SIZE",
    "DEFAULT_SOURCE_SIZE_CAP_BYTES",
    "SOURCE_COST_CLASS",
    "SOURCE_FETCH_TEMPLATE",
    "SOURCE_MAX_PAGES_CAP",
    "SOURCE_MAX_SOURCES_CAP",
    "SOURCE_PAGE_SIZE_CAP",
    "SOURCE_PROFILE",
    "SOURCE_SEARCH_TEMPLATE",
    "SOURCE_SIZE_CAP_BYTES_CAP",
    "SOURCE_TEMPLATE_VERSION",
    "build_source_fetch_task_payload",
    "build_source_search_task_payload",
    "source_fetch_idempotency_key",
    "source_fetch_task_id",
    "source_search_idempotency_key",
    "source_search_task_id",
]

# ── the canonical template markers (normalized matching, V6-P7-E01) ──

SOURCE_SEARCH_TEMPLATE = "source_search"
SOURCE_FETCH_TEMPLATE = "source_fetch"
SOURCE_TEMPLATE_VERSION = "1"

# The C-tier source-slice contract (OQ-5 — the EXTRACT V6-P7-E02 precedent).
SOURCE_PROFILE = "RESEARCHER"
SOURCE_COST_CLASS = "small"

# S11 scale-class ceilings (blueprint §5.1 / OQ-6). Over-bound requests are
# rejected at admission (never at execution).
SOURCE_PAGE_SIZE_CAP = 100
SOURCE_MAX_PAGES_CAP = 50
SOURCE_MAX_SOURCES_CAP = 50
SOURCE_SIZE_CAP_BYTES_CAP = 16 * 1024 * 1024  # 16 MiB

# Builder-carried per-task defaults (the planner may tighten, never exceed).
DEFAULT_SOURCE_PAGE_SIZE = 20
DEFAULT_SOURCE_MAX_PAGES = 20
DEFAULT_SOURCE_MAX_SOURCES = 20
DEFAULT_SOURCE_SIZE_CAP_BYTES = 4 * 1024 * 1024  # 4 MiB
DEFAULT_SOURCE_RETRY_POLICY: dict[str, Any] = {
    "max_retries": 3,
    "base_delay_seconds": 1.0,
    "max_delay_seconds": 30.0,
    "jitter": True,
}


def _check_provider(provider: Any) -> str:
    if not isinstance(provider, str) or provider not in SOURCE_PROVIDER_ALLOWLIST:
        raise ValueError(
            f"SOURCE_SEARCH provider must be one of "
            f"{sorted(SOURCE_PROVIDER_ALLOWLIST)}, got {provider!r} "
            f"(IDR-030 allowlist)"
        )
    return provider


def _check_positive_int(value: Any, name: str, cap: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not (1 <= value <= cap):
        raise ValueError(
            f"SOURCE {name} must be an integer in [1, {cap}], got {value!r}"
        )
    return value


def _check_retry_policy(value: Any) -> dict[str, Any]:
    """Validate a SOURCE_FETCH ``retry_policy`` carrier (R03): a mapping of
    exactly the RetryPolicy fields, each within the S11 bounds. Returns the
    canonical dict (the task spec's persisted form). Over/under/malformed
    values fail here — admission never lets a malformed retry policy through."""
    if not isinstance(value, dict):
        raise ValueError(
            "SOURCE retry_policy must be a mapping of RetryPolicy fields, "
            f"got {value!r}"
        )
    unknown = set(value) - {"max_retries", "base_delay_seconds",
                            "max_delay_seconds", "jitter"}
    if unknown:
        raise ValueError(
            f"SOURCE retry_policy has unknown fields: {sorted(unknown)}"
        )
    mr = value.get("max_retries", DEFAULT_SOURCE_RETRY_POLICY["max_retries"])
    bd = value.get("base_delay_seconds",
                   DEFAULT_SOURCE_RETRY_POLICY["base_delay_seconds"])
    md = value.get("max_delay_seconds",
                   DEFAULT_SOURCE_RETRY_POLICY["max_delay_seconds"])
    jit = value.get("jitter", DEFAULT_SOURCE_RETRY_POLICY["jitter"])
    if not isinstance(mr, int) or isinstance(mr, bool) or not (0 <= mr <= 10):
        raise ValueError(
            f"SOURCE retry_policy.max_retries must be an integer in [0, 10], "
            f"got {mr!r}"
        )
    for name, v, lo, hi in (("base_delay_seconds", bd, 0.1, 3600.0),
                            ("max_delay_seconds", md, 0.1, 3600.0)):
        if not isinstance(v, (int, float)) or isinstance(v, bool) \
                or not (lo <= v <= hi):
            raise ValueError(
                f"SOURCE retry_policy.{name} must be a number in "
                f"[{lo}, {hi}], got {v!r}"
            )
    if md < bd:
        raise ValueError(
            "SOURCE retry_policy.max_delay_seconds must be >= "
            "base_delay_seconds"
        )
    if not isinstance(jit, bool):
        raise ValueError(
            f"SOURCE retry_policy.jitter must be a bool, got {jit!r}"
        )
    return {
        "max_retries": mr,
        "base_delay_seconds": float(bd),
        "max_delay_seconds": float(md),
        "jitter": jit,
    }


# ── content-addressed task identity (deterministic, one derivation) ──


def source_search_task_id(
    provider: str,
    hints: dict[str, Any],
    *,
    page_size: int,
    max_pages: int,
    size_cap_bytes: int,
    scope_ref: str = "",
    template_version: str = SOURCE_TEMPLATE_VERSION,
) -> str:
    """Content-addressed SOURCE_SEARCH task id.

    Same provider + hints + bounds + scope/requirement ref + template version
    ⇒ same task (PA4 at the task level — re-planning an unchanged search is
    the same task; the scope ref keeps project-scoped requirements distinct,
    D2).
    """
    return "source_search_" + sha256_hex(canonical_json({
        "kind": "source_search_task",
        "provider": provider,
        "hints": hints,
        "page_size": page_size,
        "max_pages": max_pages,
        "size_cap_bytes": size_cap_bytes,
        "scope_ref": scope_ref,
        "template_version": template_version,
    }))[:24]


def source_search_idempotency_key(
    provider: str,
    hints: dict[str, Any],
    *,
    page_size: int,
    max_pages: int,
    size_cap_bytes: int,
    scope_ref: str = "",
    template_version: str = SOURCE_TEMPLATE_VERSION,
) -> str:
    """The search task's idempotency key (sha256 of spec + inputs, PA4)."""
    return sha256_hex(canonical_json({
        "kind": "source_search",
        "provider": provider,
        "hints": hints,
        "page_size": page_size,
        "max_pages": max_pages,
        "size_cap_bytes": size_cap_bytes,
        "scope_ref": scope_ref,
        "template_version": template_version,
    }))


def source_fetch_task_id(
    search_task_id: str,
    source_refs: tuple[str, ...] | list[str],
    template_version: str = SOURCE_TEMPLATE_VERSION,
) -> str:
    """Content-addressed SOURCE_FETCH task id.

    Same search task + same durable refs + same template version ⇒ same task.
    """
    return "source_fetch_" + sha256_hex(canonical_json({
        "kind": "source_fetch_task",
        "search_task_id": search_task_id,
        "source_refs": sorted(set(source_refs)),
        "template_version": template_version,
    }))[:24]


def source_fetch_idempotency_key(
    search_task_id: str,
    source_refs: tuple[str, ...] | list[str],
    template_version: str = SOURCE_TEMPLATE_VERSION,
) -> str:
    return sha256_hex(canonical_json({
        "kind": "source_fetch",
        "search_task_id": search_task_id,
        "source_refs": sorted(set(source_refs)),
        "template_version": template_version,
    }))


# ── the INSERT_TASK payload builders ──


def build_source_search_task_payload(
    provider: str,
    hints: dict[str, Any],
    *,
    page_size: int = DEFAULT_SOURCE_PAGE_SIZE,
    max_pages: int = DEFAULT_SOURCE_MAX_PAGES,
    size_cap_bytes: int = DEFAULT_SOURCE_SIZE_CAP_BYTES,
    scope_ref: str = "",
    dependencies: tuple[str, ...] = (),
    provenance: tuple[str, ...] = (),
    template_version: str = SOURCE_TEMPLATE_VERSION,
) -> dict[str, Any]:
    """The INSERT_TASK payload for a SOURCE_SEARCH task (deterministic).

    ``hints`` is the deterministic ``RetrievalHints`` form (identifiers dict,
    topic, mode, unrecognized_hints tuple) — json-serializable, canonical.
    The payload is an ordinary ``AGENT_TASK`` admitted through the gateway —
    the task graph is the operational authority; nothing is inserted outside
    ``apply_intent``.
    """
    provider = _check_provider(provider)
    if not isinstance(hints, dict):
        raise ValueError(f"SOURCE_SEARCH hints must be a mapping, got {type(hints).__name__}")
    _check_positive_int(page_size, "page_size", SOURCE_PAGE_SIZE_CAP)
    _check_positive_int(max_pages, "max_pages", SOURCE_MAX_PAGES_CAP)
    _check_positive_int(size_cap_bytes, "size_cap_bytes", SOURCE_SIZE_CAP_BYTES_CAP)
    if not isinstance(scope_ref, str):
        raise ValueError("SOURCE_SEARCH scope_ref must be a string")
    return {
        "task_id": source_search_task_id(
            provider, hints, page_size=page_size, max_pages=max_pages,
            size_cap_bytes=size_cap_bytes, scope_ref=scope_ref,
            template_version=template_version),
        "task_type": "AGENT_TASK",
        "profile": SOURCE_PROFILE,
        "idempotency_key": source_search_idempotency_key(
            provider, hints, page_size=page_size, max_pages=max_pages,
            size_cap_bytes=size_cap_bytes, scope_ref=scope_ref,
            template_version=template_version),
        "iteration": 1,
        "spec": {
            "template": SOURCE_SEARCH_TEMPLATE,
            "template_version": template_version,
            "provider": provider,
            "hints": hints,
            "page_size": page_size,
            "max_pages": max_pages,
            "size_cap_bytes": size_cap_bytes,
            "scope_ref": scope_ref,
        },
        "inputs": [],
        "outputs": [],
        "dependencies": list(dependencies),
        "provenance": list(provenance),
        "cost_class": SOURCE_COST_CLASS,
        "concurrency_group": None,
        "max_retries": 3,
        "parent_task_id": None,
    }


def build_source_fetch_task_payload(
    search_task_id: str,
    source_refs: tuple[str, ...] | list[str],
    *,
    provider: str,
    max_sources: int = DEFAULT_SOURCE_MAX_SOURCES,
    size_cap_bytes: int = DEFAULT_SOURCE_SIZE_CAP_BYTES,
    retry_policy: dict[str, Any] | None = None,
    dependencies: tuple[str, ...] | None = None,
    provenance: tuple[str, ...] = (),
    template_version: str = SOURCE_TEMPLATE_VERSION,
) -> dict[str, Any]:
    """The INSERT_TASK payload for a SOURCE_FETCH task (deterministic).

    ``source_refs`` are the durable ``source_result:<full-hash>`` refs the
    search task produced (the fetch input resolves from the PERSISTED outcome,
    never from a hand-authored list — D2). The task depends on its search
    task via ``task_dependencies`` (no alternate insertion path). The refs
    are the binding contract: the fetch outcome's per-source refs must match
    the spec's refs (A2-01). ``provider`` is REQUIRED — the fetch handler
    routes the adapter by it, and admission requires it (a provider-less
    fetch is rejected at admission, never at execution; C1).

    R03 — the task carries its OWN bounds (``max_sources``,
    ``size_cap_bytes``, ``retry_policy``), validated against the S11 caps
    here and persisted in the spec; the handler builds the runtime
    ``FetchRequest`` from the PERSISTED spec, never from global defaults
    (admission semantics == execution semantics)."""
    if not isinstance(search_task_id, str) or not search_task_id:
        raise ValueError("SOURCE_FETCH search_task_id must be a non-empty string")
    refs = list(source_refs)
    if not refs or not all(isinstance(r, str) and r.startswith("source_result:")
                           for r in refs):
        raise ValueError(
            "SOURCE_FETCH source_refs must be a non-empty list of "
            "'source_result:<full-hash>' references (D2 — the durable refs, "
            "never a payload copy)"
        )
    if len(refs) > SOURCE_MAX_SOURCES_CAP:
        raise ValueError(
            f"SOURCE_FETCH source_refs exceed max_sources cap "
            f"{SOURCE_MAX_SOURCES_CAP} (OQ-6)")
    deps = tuple(dependencies) if dependencies is not None else (search_task_id,)
    provider = _check_provider(provider)
    max_sources = _check_positive_int(
        max_sources, "max_sources", SOURCE_MAX_SOURCES_CAP)
    size_cap_bytes = _check_positive_int(
        size_cap_bytes, "size_cap_bytes", SOURCE_SIZE_CAP_BYTES_CAP)
    retry = (_check_retry_policy(retry_policy) if retry_policy is not None
             else dict(DEFAULT_SOURCE_RETRY_POLICY))
    spec: dict[str, Any] = {
        "template": SOURCE_FETCH_TEMPLATE,
        "template_version": template_version,
        "search_task_id": search_task_id,
        "source_refs": refs,
        "provider": provider,
        "max_sources": max_sources,
        "size_cap_bytes": size_cap_bytes,
        "retry_policy": retry,
    }
    return {
        "task_id": source_fetch_task_id(
            search_task_id, refs, template_version=template_version),
        "task_type": "AGENT_TASK",
        "profile": SOURCE_PROFILE,
        "idempotency_key": source_fetch_idempotency_key(
            search_task_id, refs, template_version=template_version),
        "iteration": 1,
        "spec": spec,
        "inputs": [],
        "outputs": [],
        "dependencies": list(deps),
        "provenance": list(provenance),
        "cost_class": SOURCE_COST_CLASS,
        "concurrency_group": None,
        "max_retries": 3,
        "parent_task_id": None,
    }
