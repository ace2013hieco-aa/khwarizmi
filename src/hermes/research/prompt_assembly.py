"""P-AUTO-2 — deterministic RESEARCHER-on-EXTRACT prompt assembly.

Minimal assembler over existing types. The ONLY new value types in this
slice are the assembler inputs named by the charter (audit 2):
``PromptCharter`` (the charter_versions bundle: charter + template
versions, model class, output schema, context policy) and ``BudgetClass``
(the budget-class tier the prompt is assembled under). Everything else —
task shape, cost_class strings, EXTRACT template marker, obligation refs,
allowlist metadata shape — reuses existing tree types.

Determinism contract (same inputs give the same prompt, byte for byte):
fixed section order, sorted refs, canonical rendering, deterministic
budget truncation with an explicit marker. No clock, no randomness, no
network, no repository access — this module is pure.

M3 trust boundary: evidence reaches the assembler ONLY as
``UntrustedContent`` envelopes (``hermes.security.boundaries``). The
assembled prompt carries envelope string forms (markers), never the
``.text`` payload — a non-envelope marker is a ``TypeError``, never a
silent coercion. The single grep-auditable unwrap (``.text``) lives in
exactly one place: nowhere in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Mapping

from hermes.research.claims import (
    CLAIM_SCHEMA_VERSION,
    ExtractionDraft,
    ResearchClaimDraft,
)
from hermes.research.extraction import EXTRACT_TEMPLATE
from hermes.research.source_handlers import UntrustedContentView
from hermes.security.boundaries import UntrustedContent

__all__ = [
    "PROMPT_ASSEMBLER_VERSION",
    "PROMPT_MAX_CHARS",
    "AssembledPrompt",
    "BudgetClass",
    "PromptCharter",
    "StubModelClient",
    "assemble_prompt",
]

# Version of the assembler itself (provenance alongside model_ref).
PROMPT_ASSEMBLER_VERSION = "1"

# 4 KiB bounded-payload discipline: no assembled prompt exceeds this.
PROMPT_MAX_CHARS = 4096

# The only role this assembler serves (RESEARCHER-on-EXTRACT).
ASSEMBLER_ROLE = "RESEARCHER"

# Marker appended when budget truncation fires (deterministic + auditable).
TRUNCATION_MARKER = "[truncated to budget]"


@dataclass(frozen=True, slots=True)
class PromptCharter:
    """The charter_versions bundle: versioned assembly inputs (all trusted).

    ``charter_version`` / ``prompt_template_version`` reuse the plumbing
    that already exists on Intent and gateway invariants; this bundle is
    their assembly-time value object (new in this slice per audit 2).
    """

    charter_version: str = "1"
    prompt_template_version: str = "1"
    model_class: str = "stub"
    output_schema: str = "extraction-draft/v1"
    context_policy: str = "refs-only"


@dataclass(frozen=True, slots=True)
class BudgetClass:
    """The budget-class tier (new in this slice per audit 2).

    Bounds for one assembled prompt. ``from_cost_class`` maps the
    EXISTING task cost_class strings onto tiers; unknown strings refuse
    (fail-closed) rather than guessing a budget.
    """

    name: str
    max_prompt_chars: int
    max_evidence_refs: int

    SMALL: ClassVar[BudgetClass]
    STANDARD: ClassVar[BudgetClass]
    LARGE: ClassVar[BudgetClass]

    @classmethod
    def from_cost_class(cls, cost_class: str | None) -> BudgetClass:
        """Map an existing task cost_class string onto a tier (fail-closed)."""
        if not isinstance(cost_class, str):
            raise ValueError(
                "budget-class requires a cost_class string, "
                f"got {type(cost_class).__name__}"
            )
        key = cost_class.strip().casefold()
        if key == "small":
            return BudgetClass.SMALL
        if key == "medium":
            return BudgetClass.STANDARD
        if key == "large":
            return BudgetClass.LARGE
        raise ValueError(
            f"unknown cost_class {cost_class!r} — no budget-class tier "
            "(expected one of small, medium, large)"
        )


# Class-level tier singletons (assigned post-definition: dataclass field
# defaults above keep the decorator honest; singletons are canonical).
BudgetClass.SMALL = BudgetClass("SMALL", 2048, 8)
BudgetClass.STANDARD = BudgetClass("STANDARD", 3072, 16)
BudgetClass.LARGE = BudgetClass("LARGE", 4096, 32)


@dataclass(frozen=True, slots=True)
class AssembledPrompt:
    """One assembled prompt (frozen record, never executed here).

    ``text`` carries envelope markers only. ``evidence_refs`` is the
    sorted ref list the markers were built from; ``truncated`` reports
    whether budget truncation fired.
    """

    text: str
    prompt_template_version: str
    charter_version: str
    model_ref: str
    evidence_refs: tuple[str, ...] = ()
    truncated: bool = False
    assembler_version: str = PROMPT_ASSEMBLER_VERSION


def _require_envelope(marker: Any) -> UntrustedContent:
    """Fail-closed envelope check: markers must BE envelopes (never strs)."""
    if not isinstance(marker, UntrustedContent):
        raise TypeError(
            "evidence markers must be UntrustedContent envelopes, "
            f"got {type(marker).__name__} — raw text can never enter "
            "an assembled prompt"
        )
    return marker


def _render_obligations(obligations: tuple[str, ...]) -> str:
    """Render trusted program-obligation strings (sorted, deterministic)."""
    return "\n".join(f"- {ob}" for ob in sorted(obligations))


def _render_allowlist(allowlist: Mapping[str, str]) -> str:
    """Render allowlist metadata, names plus descriptions only (sorted)."""
    return "\n".join(f"- {name}: {allowlist[name]}" for name in sorted(allowlist))


def assemble_prompt(
    charter: PromptCharter,
    role: str,
    task: Mapping[str, Any],
    program_obligations: tuple[str, ...],
    allowlist_metadata: Mapping[str, str],
    schema_ref: str,
    budget: BudgetClass,
    evidence_markers: tuple[UntrustedContent, ...],
) -> AssembledPrompt:
    """Assemble a RESEARCHER-on-EXTRACT prompt (pure, deterministic).

    Refuses (ValueError) on any non-RESEARCHER role, any non-EXTRACT
    template, or any budget/prompt overflow the deterministic truncation
    cannot bound. Refuses (TypeError) on any non-envelope evidence
    marker. Evidence appears as markers only — ``.text`` is never read
    here, so payload text cannot reach the prompt by construction.
    """
    if role != ASSEMBLER_ROLE:
        raise ValueError(
            f"assembler serves role {ASSEMBLER_ROLE!r}, not {role!r}"
        )
    spec = task.get("spec") if isinstance(task, Mapping) else None
    template = spec.get("template") if isinstance(spec, dict) else None
    if not isinstance(template, str) or (
        template.strip().casefold() != EXTRACT_TEMPLATE
    ):
        raise ValueError(
            "assembler serves EXTRACT tasks only "
            f"(spec.template must be {EXTRACT_TEMPLATE!r})"
        )
    if not isinstance(schema_ref, str) or not schema_ref:
        raise ValueError("schema_ref must be a non-empty string")
    for marker in evidence_markers:
        _require_envelope(marker)

    task_id = str(task.get("task_id", ""))
    source_ref = spec.get("source_ref", "") if isinstance(spec, dict) else ""
    trimmed = sorted({m.ref for m in evidence_markers if m.ref})
    kept_markers = [
        m for m in sorted(evidence_markers, key=lambda m: m.ref)
        if m.ref
    ][: budget.max_evidence_refs]

    sections = [
        f"# RESEARCHER extraction prompt (assembler v{PROMPT_ASSEMBLER_VERSION})",
        f"role: {ASSEMBLER_ROLE}",
        f"model_class: {charter.model_class}",
        f"charter_version: {charter.charter_version}",
        f"prompt_template_version: {charter.prompt_template_version}",
        f"output_schema: {charter.output_schema}",
        f"context_policy: {charter.context_policy}",
        f"schema_ref: {schema_ref}",
        f"task_id: {task_id}",
        f"source_ref: {source_ref}",
        "## obligations",
        _render_obligations(program_obligations),
        "## allowlist (names plus descriptions only)",
        _render_allowlist(allowlist_metadata),
        "## evidence (envelope markers only — resolve via refs, never raw text)",
    ]
    sections.extend(str(m) for m in kept_markers)
    omitted = len(trimmed) - len(kept_markers)
    if omitted > 0:
        sections.append(f"[withheld {omitted} evidence refs over budget]")
    text = "\n".join(sections) + "\n"

    truncated = False
    if len(text) > budget.max_prompt_chars:
        cut = budget.max_prompt_chars - len(TRUNCATION_MARKER) - 2
        text = text[:cut] + "\n" + TRUNCATION_MARKER + "\n"
        truncated = True
    if len(text) > PROMPT_MAX_CHARS:  # 4 KiB hard bound (fail-closed)
        raise ValueError(
            f"assembled prompt {len(text)} chars exceeds "
            f"{PROMPT_MAX_CHARS} char bound"
        )
    return AssembledPrompt(
        text=text,
        prompt_template_version=charter.prompt_template_version,
        charter_version=charter.charter_version,
        model_ref=f"{charter.model_class}/extract-v1",
        evidence_refs=tuple(sorted({m.ref for m in kept_markers})),
        truncated=truncated,
    )


@dataclass(frozen=True, slots=True)
class StubModelClient:
    """ModelClient as a deterministic test double (D4: stub first).

    No network, no credentials, no clock, no randomness. ``extract``
    matches the controller ``extract_fn`` contract
    ``(task, untrusted) -> ExtractionDraft`` via ``as_extract_fn``.

    The stub NEVER unwraps evidence (``.text`` appears nowhere here):
    the draft is derived from task-bound refs only, with support state
    SPECULATIVE (declared, not source-supported) and span_ref None.
    Grounding note (langextract idea, ideas-only): every claim carries
    the producing task's source_ref, so the output binds to exactly the
    artifact the task extracted (V6-P7-E03).
    """

    charter: PromptCharter = field(default_factory=PromptCharter)
    budget: BudgetClass | None = None

    def _budget_for(self, task: Mapping[str, Any]) -> BudgetClass:
        if self.budget is not None:
            return self.budget
        return BudgetClass.from_cost_class(task.get("cost_class"))

    def assemble(
        self, task: Mapping[str, Any], untrusted: Any
    ) -> AssembledPrompt:
        """Build the prompt the stub would send (markers only)."""
        if not isinstance(untrusted, UntrustedContentView):
            raise TypeError(
                "stub input must be an UntrustedContentView envelope, "
                f"got {type(untrusted).__name__} — unenveloped paths fail"
            )
        refs = self._evidence_refs(task)
        markers: list[UntrustedContent] = []
        for ref in refs:
            envelope = untrusted.fetched_text(ref)
            if envelope is not None:
                markers.append(envelope)
        return assemble_prompt(
            self.charter,
            ASSEMBLER_ROLE,
            task,
            (),
            {},
            "extraction-draft/v1",
            self._budget_for(task),
            tuple(markers),
        )

    def _evidence_refs(self, task: Mapping[str, Any]) -> tuple[str, ...]:
        """Refs the stub may cite: the task's own source_ref only."""
        spec = task.get("spec") if isinstance(task, Mapping) else None
        source_ref = spec.get("source_ref") if isinstance(spec, dict) else None
        if not isinstance(source_ref, str) or not source_ref:
            return ()
        return (source_ref,)

    def extract(self, task: Mapping[str, Any], untrusted: Any) -> ExtractionDraft:
        """Deterministic test-double extraction (no source text read)."""
        prompt = self.assemble(task, untrusted)  # envelope gate first
        task_id = str(task.get("task_id", ""))
        spec = task.get("spec") if isinstance(task, Mapping) else {}
        source_ref = spec.get("source_ref", "") if isinstance(spec, dict) else ""
        if not source_ref:
            raise ValueError(
                "stub refuses tasks without spec.source_ref "
                "(output must bind to the extracted artifact)"
            )
        claim = ResearchClaimDraft(
            ref="stub-1",
            statement=f"stub extraction for {task_id} from {source_ref}",
            source_ref=source_ref,
            support_state="SPECULATIVE",
            span_ref=None,
            claim_type="stub",
            # No context_tags: tags must use the closed CONTEXT_DIMENSIONS
            # set, and the stub declares nothing. Assembler provenance
            # travels via extracted_by plus the prompt record instead.
        )
        return ExtractionDraft(
            source_ref=source_ref,
            claims=(claim,),
            assumptions=(),
            extracted_by=prompt.model_ref,
            schema_version=CLAIM_SCHEMA_VERSION,
        )

    def as_extract_fn(
        self,
    ) -> Callable[[Mapping[str, Any], Any], ExtractionDraft]:
        """Adapt the stub to the controller ``extract_fn`` seam."""
        return self.extract
