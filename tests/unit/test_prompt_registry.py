"""Unit tests for DEC-018 prompt registry."""

import pytest

from backend.prompts import get_prompt, list_prompts, render_prompt


class TestPromptRegistry:
    def test_list_includes_core_prompts(self):
        ids = {p["prompt_id"] for p in list_prompts()}
        assert "context.summarize.rag" in ids
        assert "context.summarize.user" in ids
        assert "mid_turn.semantic" in ids
        assert "council.rank" in ids
        assert "mode.council" in ids

    def test_render_summarize_user(self):
        text = render_prompt(
            "context.summarize.user",
            user_content="Very long user question about auth",
            target_tokens=800,
        )
        assert "Very long user question" in text
        assert "800" in text

    def test_render_mid_turn_semantic(self):
        text = render_prompt(
            "mid_turn.semantic",
            user_query="What is X?",
            responses_text="Response A:\nanswer",
            target_tokens=2000,
        )
        assert "What is X?" in text
        assert "Response A" in text

    def test_render_summarize_rag(self):
        text = render_prompt(
            "context.summarize.rag",
            user_question="What is X?",
            context_block="file.py: context",
            target_tokens=1200,
        )
        assert "What is X?" in text
        assert "1200" in text
        assert "file.py: context" in text

    def test_render_council_stage1(self):
        text = render_prompt("council.stage1", prompt="Explain asyncio")
        assert "single model" in text
        assert "Explain asyncio" in text

    def test_render_round_robin_turn_requires_only_embedded_variables(self):
        text = render_prompt(
            "round_robin.turn",
            iteration=1,
            passes=2,
            turn=1,
            model_count=3,
            prior_for_prompt="A predecessor draft",
        )
        assert "pass 1/2" in text
        assert "A predecessor draft" in text

    def test_render_mode_filter(self):
        council_only = list_prompts(mode="council")
        ids = {p["prompt_id"] for p in council_only}
        assert "council.stage1" in ids
        assert "mode.council" in ids
        assert "round_robin.turn" not in ids

    def test_missing_variables_raises(self):
        with pytest.raises(ValueError, match="Missing variables"):
            render_prompt("council.rank", user_query="hi")

    def test_unknown_prompt_raises(self):
        with pytest.raises(KeyError):
            render_prompt("does.not.exist", x=1)

    def test_get_prompt_metadata(self):
        entry = get_prompt("rag.control")
        assert entry is not None
        assert entry.version == "1"
        assert "Retrieval guidance" in entry.template
