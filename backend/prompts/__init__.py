"""System prompt registry (DEC-018)."""

from .registry import PromptEntry, get_prompt, list_prompts, render_prompt

__all__ = ["PromptEntry", "get_prompt", "list_prompts", "render_prompt"]