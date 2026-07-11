"""Tests for BudgetDecision metadata hooks (DEC-018 A7/A8)."""

import pytest

from backend.budget import build_budgeted_prompts
from backend.component_budget import compute_component_budget
from backend.dependencies import clear_caches


async def _fake_query(*_args, **_kwargs):
    return {"content": "short summary", "usage": {"prompt_tokens": 50, "completion_tokens": 10}}


@pytest.fixture(autouse=True)
def _reset():
    clear_caches()
    yield
    clear_caches()


@pytest.mark.asyncio
async def test_build_budgeted_prompts_returns_decisions_and_jobs():
    _, per_model, _, targets, decisions, jobs = await build_budgeted_prompts(
        "user q",
        "x" * 500000,
        True,
        _fake_query,
        force_summarize=True,
        arena_models=["cohere/north-mini-code:free"],
        control_prompt="\n\n# Retrieval guidance\n",
        directive_instructions="Answer concisely.",
        mode_instructions="Mode: Council.",
    )
    assert per_model
    assert targets
    assert "cohere/north-mini-code:free" in decisions
    dec = decisions["cohere/north-mini-code:free"]
    assert dec.summarized is True
    assert dec.components.rag > 0
    assert dec.components.directives > 0
    assert dec.components.mode > 0
    assert jobs
    assert jobs[0].chairman_fallback is True


def test_compute_component_budget_splits_directives_and_mode():
    comp = compute_component_budget(
        rag_text="rag block",
        control_prompt="system",
        user_content="hello",
        directive_instructions="be brief",
        mode_instructions="Mode: Fight",
        rag_used=True,
        estimate_fn=lambda t: len(t) // 4,
    )
    assert comp.rag > 0
    assert comp.system > 0
    assert comp.user > 0
    assert comp.directives > 0
    assert comp.mode > 0
    assert comp.total == comp.rag + comp.system + comp.mode + comp.user + comp.directives