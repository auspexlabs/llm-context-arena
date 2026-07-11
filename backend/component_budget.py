"""PromptComponentBudget assembly (DEC-018)."""

from __future__ import annotations

from typing import Callable, Optional

from .budget_metadata import PromptComponentBudget


def compute_component_budget(
    *,
    rag_text: str,
    control_prompt: str,
    user_content: str,
    directive_instructions: str,
    mode_instructions: str,
    rag_used: bool,
    estimate_fn: Callable[[str], int],
) -> PromptComponentBudget:
    rag_tokens = estimate_fn(rag_text) if rag_text else 0
    system_tokens = estimate_fn(control_prompt) if rag_used and control_prompt else 0
    user_tokens = estimate_fn(f"User question: {user_content}") if user_content else 0
    directive_tokens = estimate_fn(directive_instructions) if directive_instructions else 0
    mode_tokens = estimate_fn(mode_instructions) if mode_instructions else 0
    total = rag_tokens + system_tokens + user_tokens + directive_tokens + mode_tokens
    return PromptComponentBudget(
        rag=rag_tokens,
        system=system_tokens,
        mode=mode_tokens,
        turn=0,
        user=user_tokens,
        directives=directive_tokens,
        total=total,
    )


def compute_prompt_components(
    *,
    compressed_context: str,
    control_prompt: str,
    user_content: str,
    directive_instructions: str,
    mode_instructions: str,
    rag_used: bool,
    estimate_fn: Callable[[str], int],
) -> PromptComponentBudget:
    """Component breakdown for a fully assembled per-model prompt."""
    return compute_component_budget(
        rag_text=compressed_context,
        control_prompt=control_prompt,
        user_content=user_content,
        directive_instructions=directive_instructions,
        mode_instructions=mode_instructions,
        rag_used=rag_used,
        estimate_fn=estimate_fn,
    )