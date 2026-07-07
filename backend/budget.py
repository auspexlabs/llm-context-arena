"""Budget allocation for LLM Context Arena.

Manages per-model token budgets and context summarization to fit
within each model's context window limits.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Callable, Awaitable

from .config import (
    ARENA_MODELS,
    MODEL_CONTEXT_LIMITS,
    DEFAULT_MODEL_CONTEXT_LIMIT,
    CONTEXT_SAFETY_MARGIN,
    OUTPUT_TOKEN_ALLOWANCE,
    CHAIRMAN_MODEL,
)
from .rag_lmstudio import _estimate_tokens


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
) -> str:
    """
    Use the Chairman model to compress context to fit within a tighter budget.

    Args:
        user_question: The user's query
        context_block: The context to compress
        target_tokens: Target token count for compressed context
        query_model_fn: Async function to query the model
        chairman_model: Model to use for summarization

    Returns:
        Compressed context string
    """
    prompt = (
        "You are the Chairman of an LLM arena. Summarize the provided context so it can be fed to"
        " another model with a smaller input window. Keep critical facts, constraints, and code/API"
        " signatures. Prefer bullet points. Include source hints (filenames/sections) when present."
        f" Fit the context portion into roughly {target_tokens} tokens or less. Do not omit key safety"
        " constraints or numbers. Return only the compressed context, not an answer."
        f"\n\nUser question:\n{user_question}\n\nContext to compress:\n{context_block}"
    )

    resp = await query_model_fn(
        chairman_model,
        [{"role": "user", "content": prompt}],
        timeout=90.0,
    )

    return resp.get("content", "") if resp else ""


async def build_budgeted_prompts(
    user_content: str,
    context_block: str,
    rag_used: bool,
    query_model_fn: Callable,
    force_summarize: bool = False,
    budget_override: Optional[int] = None,
    extra_instructions: str = "",
    arena_models: Optional[List[str]] = None,
    chairman_model: str = CHAIRMAN_MODEL,
    control_prompt: str = "",
) -> Tuple[str, Dict[str, str], Dict[str, int], Dict[str, int]]:
    """
    Build the base prompt and per-model overrides that fit within each model's context window.

    Args:
        user_content: The user's query
        context_block: Retrieved/manual context
        rag_used: Whether RAG retrieval was used
        query_model_fn: Async function to query models (for summarization)
        force_summarize: Force context summarization even if under budget
        budget_override: Optional manual budget override
        extra_instructions: Additional instructions to append
        arena_models: List of model IDs (defaults to ARENA_MODELS)
        chairman_model: Model to use for summarization
        control_prompt: Control prompt to append when RAG is used

    Returns:
        Tuple of:
            - base_prompt: The default prompt for models that don't need summarization
            - per_model_prompts: Dict of model ID -> custom prompt for models needing summarization
            - context_token_map: Dict of model ID -> context token count
            - summarize_targets: Dict of model ID -> target token count used for summarization
    """
    models = arena_models or ARENA_MODELS
    allocator = BudgetAllocator()

    tail = f"\n\n{extra_instructions}" if extra_instructions else ""
    base_prompt = (
        f"{context_block}{control_prompt if rag_used else ''}\n\nUser question: {user_content}{tail}"
        if context_block
        else f"{user_content}{tail}"
    )

    # No context - nothing to budget
    if not context_block:
        return base_prompt, {}, {}, {}

    base_tokens = _estimate_tokens(base_prompt)
    per_model_prompts: Dict[str, str] = {}
    summary_cache: Dict[int, str] = {}
    context_token_map: Dict[str, int] = {"__base__": _estimate_tokens(context_block)}
    summarize_targets: Dict[str, int] = {}

    user_section_tokens = _estimate_tokens(f"User question: {user_content}")

    # If summarization is forced, compute a shared target using the smallest model window
    forced_target = None
    if force_summarize:
        min_budget = allocator.get_minimum_budget(models, budget_override)
        if min_budget > 0:
            forced_target = max(500, min_budget - user_section_tokens)

    for model in models:
        budget = allocator.calculate_budget(model, budget_override)
        if budget.available_tokens <= 0:
            continue

        # Skip summarization if under budget and not forced
        if not force_summarize and base_tokens <= budget.available_tokens:
            continue

        target_ctx_tokens = forced_target or max(500, budget.available_tokens - user_section_tokens)
        cache_key = target_ctx_tokens

        if cache_key not in summary_cache:
            compressed = await summarize_context_for_budget(
                user_content,
                context_block,
                target_ctx_tokens,
                query_model_fn,
                chairman_model,
            )
            summary_cache[cache_key] = compressed or context_block

        compressed_context = summary_cache[cache_key]
        per_model_prompts[model] = (
            f"{compressed_context}{control_prompt if rag_used else ''}\n\nUser question: {user_content}{tail}"
        )
        context_token_map[model] = _estimate_tokens(compressed_context)
        summarize_targets[model] = target_ctx_tokens

    return base_prompt, per_model_prompts, context_token_map, summarize_targets
