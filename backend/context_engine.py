"""Context Engine for LLM Context Arena.

Orchestrates directive parsing, RAG retrieval, and budget allocation
to prepare context for arena execution.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .budget import BudgetAllocator, build_budgeted_prompts
from .budget_metadata import BudgetDecision, PromptComponentBudget, SummarizeJob
from .config import ARENA_MODELS, CHAIRMAN_MODEL
from .prompts import render_prompt
from .directives import (
    ParsedDirectives,
    build_directive_instructions,
    build_mode_instructions,
    parse_directives,
)
from .rag.format import estimate_tokens
from .rag_provider import RAGProvider

logger = logging.getLogger(__name__)


CONTROL_PROMPT = render_prompt("rag.control")


def get_last_chair_context(conversation: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
    """Build context from the most recent chairman response (@lastchair)."""
    messages = conversation.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        chair = msg.get("stage3") or {}
        text = (chair.get("response") or "").strip()
        if not text:
            continue
        model = chair.get("model") or "chairman"
        source = {
            "source": "previous_chairman",
            "doc_id": "previous_chairman",
            "chunk_index": None,
            "score": None,
            "content": text,
            "lines": text.count("\n") + 1,
            "chars": len(text),
            "bytes": len(text.encode("utf-8", errors="ignore")),
            "est_tokens": estimate_tokens(text),
            "source_type": "manual_last_chair",
            "model": model,
        }
        block = "# Previous chairman response\n\n" + text
        return block, [source], model
    return "", [], None


@dataclass
class ContextResult:
    """Result of context preparation."""

    clean_query: str
    directives: ParsedDirectives
    context_block: str
    context_sources: List[Dict[str, Any]]
    rag_used: bool
    base_prompt: str
    per_model_prompts: Dict[str, str]
    context_token_map: Dict[str, int]
    summarize_targets: Dict[str, int]
    instruction_text: str
    directive_instructions: str = ""
    mode_instructions: str = ""
    budget_decisions: Dict[str, BudgetDecision] = field(default_factory=dict)
    summarize_jobs: List[SummarizeJob] = field(default_factory=list)
    component_budgets: Dict[str, PromptComponentBudget] = field(default_factory=dict)
    context_from_last_chair: bool = False
    warnings: List[str] = field(default_factory=list)


class ContextEngine:
    """Directive parse → RAG/manual context → budget → prompts."""

    def __init__(
        self,
        query_model_fn: Callable,
        rag_provider: Optional[RAGProvider] = None,
        budget_allocator: Optional[BudgetAllocator] = None,
    ):
        self.budget_allocator = budget_allocator or BudgetAllocator()
        self.query_model_fn = query_model_fn
        if rag_provider is None:
            from .dependencies import get_rag_provider_dep

            rag_provider = get_rag_provider_dep()
        self.rag_provider = rag_provider

    async def prepare_context(
        self,
        conversation_id: str,
        user_input: str,
        mode: str = "council",
        manual_context: Optional[List[Dict[str, Any]]] = None,
        conversation: Optional[Dict[str, Any]] = None,
        arena_models: Optional[List[str]] = None,
        chairman_model: str = CHAIRMAN_MODEL,
    ) -> ContextResult:
        models = arena_models or ARENA_MODELS
        manual_context = list(manual_context or [])

        clean_query, directives = parse_directives(user_input)
        if not clean_query:
            clean_query = user_input

        if directives.reset:
            return ContextResult(
                clean_query=clean_query,
                directives=directives,
                context_block="",
                context_sources=[],
                rag_used=False,
                base_prompt=clean_query,
                per_model_prompts={},
                context_token_map={},
                summarize_targets={},
                instruction_text="",
                directive_instructions="",
                mode_instructions="",
                warnings=list(directives.warnings),
            )

        context_block = ""
        context_sources: List[Dict[str, Any]] = []
        context_from_last_chair = False

        if directives.use_last_chair and conversation is not None:
            context_block, context_sources, _ = get_last_chair_context(conversation)
            if context_block:
                manual_context = []
                context_from_last_chair = True
                directives.skip_rag = True
            else:
                directives.warnings.append(
                    "No previous chairman response found; using normal context instead."
                )

        if not context_block:
            context_block, context_sources = await asyncio.to_thread(
                self.rag_provider.get_context,
                conversation_id,
                clean_query,
                manual_context,
                not directives.skip_rag,
            )

        rag_used = (
            len(manual_context) == 0
            and not directives.skip_rag
            and not context_from_last_chair
        )
        if not context_block:
            context_sources = []

        directive_instructions = build_directive_instructions(directives)
        mode_instructions = build_mode_instructions(mode)
        instruction_text = "\n".join(
            [p for p in (directive_instructions, mode_instructions) if p]
        )

        (
            base_prompt,
            per_model_prompts,
            context_token_map,
            summarize_targets,
            budget_decisions,
            summarize_jobs,
        ) = await build_budgeted_prompts(
            clean_query,
            context_block,
            rag_used,
            self.query_model_fn,
            force_summarize=directives.force_summarize,
            budget_override=directives.budget_override,
            directive_instructions=directive_instructions,
            mode_instructions=mode_instructions,
            arena_models=models,
            chairman_model=chairman_model,
            control_prompt=CONTROL_PROMPT,
            allocator=self.budget_allocator,
        )
        component_budgets = {
            mid: decision.components for mid, decision in budget_decisions.items()
        }

        warnings = list(directives.warnings)
        try:
            from .observations import get_observation_service

            pending = get_observation_service().observation_pending_dicts(models)
            for obs in pending:
                if not obs.get("exceeds_threshold"):
                    continue
                warnings.append(
                    "Limit observation pending for "
                    f"{obs['model_id']}: observed={obs['observed_limit']} "
                    f"registered={obs['registered_limit']} "
                    f"(delta={obs['delta_ratio']:.0%}) — accept or decline before trusting limits."
                )
            sweep = obs_service.sweep_expired_observations()
            for model_id in sweep.get("reverify_required") or []:
                warnings.append(
                    f"Accepted limit for {model_id} expired — re-verify before trusting observed limits."
                )
        except Exception:
            logger.debug("Observation warnings skipped", exc_info=True)

        logger.info(
            "Context prepared (convo=%s user_len=%d ctx_chars=%d budgeted=%s skip_rag=%s "
            "force_sum=%s last_chair=%s preview='%s')",
            conversation_id,
            len(clean_query),
            len(context_block),
            bool(per_model_prompts),
            directives.skip_rag,
            directives.force_summarize,
            context_from_last_chair,
            context_block.replace("\n", " ")[:200] if context_block else "",
        )

        return ContextResult(
            clean_query=clean_query,
            directives=directives,
            context_block=context_block,
            context_sources=context_sources,
            rag_used=rag_used,
            base_prompt=base_prompt,
            per_model_prompts=per_model_prompts,
            context_token_map=context_token_map,
            summarize_targets=summarize_targets,
            instruction_text=instruction_text,
            directive_instructions=directive_instructions,
            mode_instructions=mode_instructions,
            budget_decisions=budget_decisions,
            summarize_jobs=summarize_jobs,
            component_budgets=component_budgets,
            context_from_last_chair=context_from_last_chair,
            warnings=warnings,
        )

    def estimate_tokens(self, text: str) -> int:
        return self.rag_provider.estimate_tokens(text)


async def prepare_arena_context(
    conversation_id: str,
    user_input: str,
    query_model_fn: Callable,
    mode: str = "council",
    manual_context: Optional[List[Dict[str, Any]]] = None,
    conversation: Optional[Dict[str, Any]] = None,
    arena_models: Optional[List[str]] = None,
    chairman_model: str = CHAIRMAN_MODEL,
    rag_provider: Optional[RAGProvider] = None,
) -> ContextResult:
    engine = ContextEngine(query_model_fn, rag_provider=rag_provider)
    return await engine.prepare_context(
        conversation_id=conversation_id,
        user_input=user_input,
        mode=mode,
        manual_context=manual_context,
        conversation=conversation,
        arena_models=arena_models,
        chairman_model=chairman_model,
    )