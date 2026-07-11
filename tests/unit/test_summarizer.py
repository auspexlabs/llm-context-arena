"""Tests for SummarizerService (DEC-018 A6)."""

import pytest

from backend.summarizer import SummarizerService


async def _fake_query(model, messages, timeout=90.0):
    return {
        "content": "compressed context",
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


@pytest.mark.asyncio
async def test_summarizer_chairman_fallback():
    service = SummarizerService(_fake_query, chairman_model="chair/test")
    text, job = await service.summarize_rag(
        user_question="What is X?",
        context_block="long context",
        target_tokens=500,
        target_model_id="model/small",
    )
    assert text == "compressed context"
    assert job.chairman_fallback is True
    assert job.summarizer_model == "chair/test"
    assert job.target_model_id == "model/small"
    assert job.outcome == "ok"
    assert job.cache_hit is False


@pytest.mark.asyncio
async def test_summarizer_cache_miss_on_different_user_question():
    calls = []

    async def counting_query(model, messages, timeout=90.0):
        calls.append(1)
        return {"content": "compressed context", "usage": {}}

    service = SummarizerService(counting_query, chairman_model="chair/test")
    await service.summarize_rag(
        user_question="auth?",
        context_block="ctx",
        target_tokens=100,
        target_model_id="m1",
    )
    await service.summarize_rag(
        user_question="errors?",
        context_block="ctx",
        target_tokens=100,
        target_model_id="m1",
    )
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_summarize_user_mode():
    service = SummarizerService(_fake_query, chairman_model="chair/test")
    text, job = await service.summarize_user(
        user_content="long user question",
        target_tokens=300,
        target_model_id="model/small",
    )
    assert text == "compressed context"
    assert job.prompt_id == "context.summarize.user"
    assert job.structure_preserved is True


@pytest.mark.asyncio
async def test_summarize_semantic_mode():
    service = SummarizerService(_fake_query, chairman_model="chair/test")
    text, job = await service.summarize_semantic(
        user_query="What is X?",
        responses_text="Response A:\nlong answer",
        target_tokens=1500,
        target_model_id="model/small",
    )
    assert text == "compressed context"
    assert job.prompt_id == "mid_turn.semantic"


@pytest.mark.asyncio
async def test_structure_preserved_recorded_on_failure():
    async def partial_restore(model, messages, timeout=90.0):
        return {"content": "summary without placeholders", "usage": {}}

    service = SummarizerService(partial_restore, chairman_model="chair/test")
    text, job = await service.summarize_rag(
        user_question="q",
        context_block="--- src/a.py:1-5 ---\nbody\n",
        target_tokens=100,
        target_model_id="m1",
    )
    assert "Structure preserved" in text or "--- src/a.py" in text
    assert job.structure_preserved is False


@pytest.mark.asyncio
async def test_summarizer_cache_hit():
    service = SummarizerService(_fake_query, chairman_model="chair/test")
    await service.summarize_rag(
        user_question="q",
        context_block="ctx",
        target_tokens=100,
        target_model_id="m1",
    )
    text, job = await service.summarize_rag(
        user_question="q",
        context_block="ctx",
        target_tokens=100,
        target_model_id="m2",
    )
    assert text == "compressed context"
    assert job.cache_hit is True
    assert job.duration_ms == 0