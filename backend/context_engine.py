"""Context Engine for LLM Context Arena.

Orchestrates directive parsing, RAG retrieval, and budget allocation
to prepare context for arena execution.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .directives import (
    ParsedDirectives,
    parse_directives,
    build_directive_instructions,
    build_mode_instructions,
)
from .budget import BudgetAllocator, build_budgeted_prompts
from .config import ARENA_MODELS, CHAIRMAN_MODEL
from .rag_lmstudio import get_context, _estimate_tokens

logger = logging.getLogger(__name__)


# Control prompt appended when RAG context is used
CONTROL_PROMPT = (
    "\n\n# Retrieval guidance\n"
    "If the provided context seems incomplete or missing related files or functions, "
    "explicitly say what seems missing (by filename or concept) and ask the user to provide it."
)


@dataclass
class ContextSource:
    """A single source of context (RAG chunk or manual file)."""
    source: str
    content: str
    source_type: str  # "rag" | "manual_picker" | "manual_at" | "manual_at_snippet"
    score: Optional[float] = None
    lines: int = 0
    est_tokens: int = 0


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
    warnings: List[str] = field(default_factory=list)


class ContextEngine:
    """
    Main orchestration layer for context preparation.

    Combines directive parsing, RAG retrieval, and budget allocation
    into a single entry point for the arena endpoints.

    Attributes:
        budget_allocator: Budget allocation service
        query_model_fn: Async function to query models (for summarization)
    """

    def __init__(
        self,
        query_model_fn: Callable,
        budget_allocator: Optional[BudgetAllocator] = None,
    ):
        """
        Initialize the context engine.

        Args:
            query_model_fn: Async function to query models (for summarization)
            budget_allocator: Optional budget allocator (creates default if not provided)
        """
        self.budget_allocator = budget_allocator or BudgetAllocator()
        self.query_model_fn = query_model_fn

    async def prepare_context(
        self,
        conversation_id: str,
        user_input: str,
        mode: str = "council",
        manual_context: Optional[List[Dict[str, Any]]] = None,
        arena_models: Optional[List[str]] = None,
        chairman_model: str = CHAIRMAN_MODEL,
    ) -> ContextResult:
        """
        Main entry point for context preparation.

        Performs:
        1. Directive parsing from user input
        2. RAG retrieval or manual context loading
        3. Budget allocation and summarization if needed
        4. Instruction text generation

        Args:
            conversation_id: The conversation ID for RAG retrieval
            user_input: Raw user input potentially containing @directives
            mode: Arena mode for instruction generation
            manual_context: Optional list of manually selected context items
            arena_models: List of model IDs for budget allocation
            chairman_model: Model to use for summarization

        Returns:
            ContextResult with all prepared context and metadata
        """
        models = arena_models or ARENA_MODELS
        manual_context = manual_context or []

        # Step 1: Parse directives
        clean_query, directives = parse_directives(user_input)
        if not clean_query:
            clean_query = user_input

        # Handle reset directive (special case - no context needed)
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
                warnings=directives.warnings,
            )

        # Step 2: Get context (RAG or manual)
        context_block, context_sources = await asyncio.to_thread(
            get_context,
            conversation_id,
            clean_query,
            manual_context,
            not directives.skip_rag,
        )

        rag_used = len(manual_context) == 0 and not directives.skip_rag
        if not context_block:
            context_sources = []

        # Step 3: Build instruction text
        instruction_parts = [
            build_directive_instructions(directives),
            build_mode_instructions(mode),
        ]
        instruction_text = "\n".join([p for p in instruction_parts if p])

        # Step 4: Build budgeted prompts
        base_prompt, per_model_prompts, context_token_map, summarize_targets = await build_budgeted_prompts(
            clean_query,
            context_block,
            rag_used,
            self.query_model_fn,
            force_summarize=directives.force_summarize,
            budget_override=directives.budget_override,
            extra_instructions=instruction_text,
            arena_models=models,
            chairman_model=chairman_model,
            control_prompt=CONTROL_PROMPT,
        )

        logger.info(
            "Context prepared (convo=%s user_len=%d ctx_chars=%d budgeted=%s skip_rag=%s force_sum=%s preview='%s')",
            conversation_id,
            len(clean_query),
            len(context_block),
            bool(per_model_prompts),
            directives.skip_rag,
            directives.force_summarize,
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
            warnings=directives.warnings,
        )

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for a text string.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        return _estimate_tokens(text)


# Convenience function for simple usage
async def prepare_arena_context(
    conversation_id: str,
    user_input: str,
    query_model_fn: Callable,
    mode: str = "council",
    manual_context: Optional[List[Dict[str, Any]]] = None,
    arena_models: Optional[List[str]] = None,
    chairman_model: str = CHAIRMAN_MODEL,
) -> ContextResult:
    """
    Convenience function to prepare context without instantiating ContextEngine.

    Args:
        conversation_id: The conversation ID for RAG retrieval
        user_input: Raw user input potentially containing @directives
        query_model_fn: Async function to query models (for summarization)
        mode: Arena mode for instruction generation
        manual_context: Optional list of manually selected context items
        arena_models: List of model IDs for budget allocation
        chairman_model: Model to use for summarization

    Returns:
        ContextResult with all prepared context and metadata
    """
    engine = ContextEngine(query_model_fn)
    return await engine.prepare_context(
        conversation_id=conversation_id,
        user_input=user_input,
        mode=mode,
        manual_context=manual_context,
        arena_models=arena_models,
        chairman_model=chairman_model,
    )
