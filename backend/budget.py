"""Budget allocation for LLM Context Arena.

Manages per-model token budgets and context summarization to fit
within each model's context window limits.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Callable, Awaitable

from .budget_metadata import BudgetDecision, SummarizeJob
from .component_budget import compute_prompt_components
from .config import (
    ARENA_MODELS,
    MODEL_CONTEXT_LIMITS,
    DEFAULT_MODEL_CONTEXT_LIMIT,
    CONTEXT_SAFETY_MARGIN,
    OUTPUT_TOKEN_ALLOWANCE,
    CHAIRMAN_MODEL,
)
from .frozen_config.catalog import CatalogLimitResolver
from .rag_lmstudio import _estimate_tokens
from .prompts import render_prompt
from .summarizer import SummarizerService
from .summarizer_pool import summarize_targets_parallel


@dataclass
class ModelBudget:
    """Budget information for a single model."""
    model_id: str
    context_limit: int
    safety_margin: float
    available_tokens: int
    requires_summarization: bool = False
    target_context_tokens: Optional[int] = None


@dataclass
class BudgetedPrompt:
    """A prompt budgeted for a specific model."""
    model_id: str
    prompt: str
    context_tokens: int
    was_summarized: bool
    target_tokens: Optional[int] = None


class BudgetAllocator:
    """
    Allocates token budgets across models and handles context compression.

    Attributes:
        context_limits: Dict mapping model IDs to their context window sizes
        safety_margin: Fraction of context window to use (default 0.85)
        output_allowance: Tokens reserved for output (default 4000)
    """

    def __init__(
        self,
        context_limits: Optional[Dict[str, int]] = None,
        safety_margin: float = CONTEXT_SAFETY_MARGIN,
        output_allowance: int = OUTPUT_TOKEN_ALLOWANCE,
    ):
        self.context_limits = context_limits or MODEL_CONTEXT_LIMITS
        self.safety_margin = safety_margin
        self.output_allowance = output_allowance

    def calculate_budget(self, model_id: str, budget_override: Optional[int] = None) -> ModelBudget:
        """
        Calculate the token budget for a specific model.

        Args:
            model_id: The model identifier
            budget_override: Optional manual budget override

        Returns:
            ModelBudget with calculated available tokens
        """
        limit = self.context_limits.get(model_id) or DEFAULT_MODEL_CONTEXT_LIMIT

        budget = int(limit * self.safety_margin) - self.output_allowance
        if budget_override:
            budget = min(budget, budget_override)

        return ModelBudget(
            model_id=model_id,
            context_limit=limit,
            safety_margin=self.safety_margin,
            available_tokens=max(0, budget),
            requires_summarization=False,
        )

    def calculate_all_budgets(
        self,
        models: Optional[List[str]] = None,
        budget_override: Optional[int] = None,
    ) -> Dict[str, ModelBudget]:
        """
        Calculate budgets for all specified models.

        Args:
            models: List of model IDs (defaults to ARENA_MODELS)
            budget_override: Optional manual budget override

        Returns:
            Dict mapping model IDs to their budgets
        """
        models = models or ARENA_MODELS
        return {
            model: self.calculate_budget(model, budget_override)
            for model in models
        }

    def get_minimum_budget(
        self,
        models: Optional[List[str]] = None,
        budget_override: Optional[int] = None,
    ) -> int:
        """
        Get the minimum available budget across all models.

        Useful for determining a shared summarization target.

        Args:
            models: List of model IDs (defaults to ARENA_MODELS)
            budget_override: Optional manual budget override

        Returns:
            Minimum available tokens across all models
        """
        budgets = self.calculate_all_budgets(models, budget_override)
        available = [b.available_tokens for b in budgets.values() if b.available_tokens > 0]
        return min(available) if available else 0


# Type alias for summarization function
SummarizeFn = Callable[[str, str, int], Awaitable[str]]


async def summarize_context_for_budget(
    user_question: str,
    context_block: str,
    target_tokens: int,
    query_model_fn: Callable,
    chairman_model: str = CHAIRMAN_MODEL,
    target_model_id: str = "__shared__",
    summarizer: Optional[SummarizerService] = None,
) -> Tuple[str, SummarizeJob]:
    """Compress context via SummarizerService (chairman fallback when unset)."""
    service = summarizer or SummarizerService(query_model_fn, chairman_model=chairman_model)
    return await service.summarize_rag(
        user_question=user_question,
        context_block=context_block,
        target_tokens=target_tokens,
        target_model_id=target_model_id,
    )


async def summarize_user_for_budget(
    user_content: str,
    target_tokens: int,
    query_model_fn: Callable,
    chairman_model: str = CHAIRMAN_MODEL,
    target_model_id: str = "__shared__",
    summarizer: Optional[SummarizerService] = None,
) -> Tuple[str, SummarizeJob]:
    """Compress user input alone via SummarizerService."""
    service = summarizer or SummarizerService(query_model_fn, chairman_model=chairman_model)
    return await service.summarize_user(
        user_content=user_content,
        target_tokens=target_tokens,
        target_model_id=target_model_id,
    )


async def maybe_compress_mid_turn(
    *,
    user_query: str,
    responses_text: str,
    arena_models: List[str],
    query_model_fn: Callable,
    chairman_model: str = CHAIRMAN_MODEL,
    budget_override: Optional[int] = None,
    summarizer: Optional[SummarizerService] = None,
    allocator: Optional[BudgetAllocator] = None,
) -> Tuple[str, List[SummarizeJob]]:
    """Compress between-stage responses when the ranking prompt exceeds squad budget."""
    models = arena_models or ARENA_MODELS
    if allocator is None:
        from .dependencies import get_budget_allocator

        allocator = get_budget_allocator()
    summarizer = summarizer or SummarizerService(query_model_fn, chairman_model=chairman_model)

    ranking_prompt = render_prompt(
        "council.rank",
        user_query=user_query,
        responses_text=responses_text,
    )
    prompt_tokens = _estimate_tokens(ranking_prompt)
    min_budget = allocator.get_minimum_budget(models, budget_override)
    if min_budget <= 0 or prompt_tokens <= min_budget:
        return responses_text, []

    shell_tokens = _estimate_tokens(
        render_prompt("council.rank", user_query=user_query, responses_text="")
    )
    target_tokens = max(500, min_budget - shell_tokens - 200)
    representative = models[0]
    compressed, job = await summarizer.summarize_semantic(
        user_query=user_query,
        responses_text=responses_text,
        target_tokens=target_tokens,
        target_model_id=representative,
    )
    return (compressed or responses_text), [job]


async def build_budgeted_prompts(
    user_content: str,
    context_block: str,
    rag_used: bool,
    query_model_fn: Callable,
    force_summarize: bool = False,
    budget_override: Optional[int] = None,
    directive_instructions: str = "",
    mode_instructions: str = "",
    extra_instructions: str = "",
    arena_models: Optional[List[str]] = None,
    chairman_model: str = CHAIRMAN_MODEL,
    control_prompt: str = "",
    allocator: Optional[BudgetAllocator] = None,
    resolver: Optional[CatalogLimitResolver] = None,
    summarizer: Optional[SummarizerService] = None,
) -> Tuple[
    str,
    Dict[str, str],
    Dict[str, int],
    Dict[str, int],
    Dict[str, BudgetDecision],
    List[SummarizeJob],
]:
    """
    Build the base prompt and per-model overrides that fit within each model's context window.

    Returns:
        Tuple of base_prompt, per_model_prompts, context_token_map, summarize_targets,
        budget_decisions, summarize_jobs.
    """
    models = arena_models or ARENA_MODELS
    if allocator is None:
        from .dependencies import get_budget_allocator

        allocator = get_budget_allocator()
    resolver = resolver or CatalogLimitResolver()
    resolver.preload_accepted_limits()
    summarizer = summarizer or SummarizerService(query_model_fn, chairman_model=chairman_model)

    tail_parts = [p for p in (directive_instructions, mode_instructions, extra_instructions) if p]
    tail = ("\n\n" + "\n\n".join(tail_parts)) if tail_parts else ""

    base_prompt = (
        f"{context_block}{control_prompt if rag_used else ''}\n\nUser question: {user_content}{tail}"
        if context_block
        else f"{user_content}{tail}"
    )

    empty_meta: Tuple[Dict[str, BudgetDecision], List[SummarizeJob]] = ({}, [])

    base_tokens = _estimate_tokens(base_prompt)
    tail_tokens = _estimate_tokens(tail) if tail else 0

    if not context_block:
        min_budget = allocator.get_minimum_budget(models, budget_override)
        needs_user_compress = force_summarize or (
            min_budget > 0 and base_tokens > min_budget
        )
        if not needs_user_compress:
            return base_prompt, {}, {}, {}, *empty_meta

        target_user_tokens = max(200, min_budget - tail_tokens - 100)
        summarize_targets: Dict[str, int] = {model: target_user_tokens for model in models}
        compressed_user, job = await summarize_user_for_budget(
            user_content,
            target_user_tokens,
            query_model_fn,
            chairman_model,
            target_model_id=models[0],
            summarizer=summarizer,
        )
        compressed_user = compressed_user or user_content
        base_prompt = f"{compressed_user}{tail}"

        budget_decisions: Dict[str, BudgetDecision] = {}
        for model in models:
            breakdown = resolver.breakdown(model, budget_override=budget_override)
            alloc = allocator.calculate_budget(model, budget_override)
            components = compute_prompt_components(
                compressed_context="",
                control_prompt="",
                user_content=compressed_user,
                directive_instructions=directive_instructions,
                mode_instructions=mode_instructions,
                rag_used=False,
                estimate_fn=_estimate_tokens,
            )
            budget_decisions[model] = BudgetDecision(
                model_id=model,
                registered_limit=breakdown.registered_limit,
                effective_limit=breakdown.effective_limit,
                available_tokens=alloc.available_tokens,
                tag_modifier=breakdown.tag_modifier,
                model_modifier=breakdown.model_modifier,
                summarized=True,
                components=components,
                tags=list(breakdown.tags),
                budget_override=budget_override,
            )

        return (
            base_prompt,
            {},
            {},
            summarize_targets,
            budget_decisions,
            [job],
        )
    per_model_prompts: Dict[str, str] = {}
    context_token_map: Dict[str, int] = {"__base__": _estimate_tokens(context_block)}
    summarize_targets: Dict[str, int] = {}
    summarize_jobs: List[SummarizeJob] = []
    compressed_by_model: Dict[str, str] = {}

    user_section_tokens = _estimate_tokens(f"User question: {user_content}")

    forced_target = None
    if force_summarize:
        min_budget = allocator.get_minimum_budget(models, budget_override)
        if min_budget > 0:
            forced_target = max(500, min_budget - user_section_tokens)

    for model in models:
        budget = allocator.calculate_budget(model, budget_override)
        if budget.available_tokens <= 0:
            continue

        if not force_summarize and base_tokens <= budget.available_tokens:
            continue

        target_ctx_tokens = forced_target or max(500, budget.available_tokens - user_section_tokens)
        summarize_targets[model] = target_ctx_tokens

    if summarize_targets:
        compressed_by_model, summarize_jobs = await summarize_targets_parallel(
            user_content=user_content,
            context_block=context_block,
            targets=summarize_targets,
            query_model_fn=query_model_fn,
            chairman_model=chairman_model,
            summarizer=summarizer,
            arena_models=models,
        )
        for model, compressed_context in compressed_by_model.items():
            per_model_prompts[model] = (
                f"{compressed_context}{control_prompt if rag_used else ''}\n\nUser question: {user_content}{tail}"
            )
            context_token_map[model] = _estimate_tokens(compressed_context)

    budget_decisions: Dict[str, BudgetDecision] = {}
    for model in models:
        breakdown = resolver.breakdown(model, budget_override=budget_override)
        alloc = allocator.calculate_budget(model, budget_override)
        rag_text = compressed_by_model.get(model, context_block)
        components = compute_prompt_components(
            compressed_context=rag_text,
            control_prompt=control_prompt,
            user_content=user_content,
            directive_instructions=directive_instructions,
            mode_instructions=mode_instructions,
            rag_used=rag_used,
            estimate_fn=_estimate_tokens,
        )
        budget_decisions[model] = BudgetDecision(
            model_id=model,
            registered_limit=breakdown.registered_limit,
            effective_limit=breakdown.effective_limit,
            available_tokens=alloc.available_tokens,
            tag_modifier=breakdown.tag_modifier,
            model_modifier=breakdown.model_modifier,
            summarized=model in summarize_targets,
            components=components,
            tags=list(breakdown.tags),
            budget_override=budget_override,
        )

    return (
        base_prompt,
        per_model_prompts,
        context_token_map,
        summarize_targets,
        budget_decisions,
        summarize_jobs,
    )