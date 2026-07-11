"""Tests for parallel summarize pool (DEC-018 Phase B)."""

import asyncio

import pytest

from backend.summarizer import SummarizerService
from backend.summarizer_pool import resolve_summarize_concurrency, summarize_targets_parallel


def test_resolve_concurrency_defaults_to_arena_minus_one():
    models = ["a", "b", "c", "d"]
    assert resolve_summarize_concurrency(models, "chair", None) == 3


def test_resolve_concurrency_excludes_chairman_from_pool_size():
    models = ["a", "b", "chair"]
    assert resolve_summarize_concurrency(models, "chair", None) == 1


def test_resolve_concurrency_config_override():
    assert resolve_summarize_concurrency(["a", "b", "c"], "chair", 2) == 2


@pytest.mark.asyncio
async def test_parallel_summarize_runs_concurrently():
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def slow_query(model, messages, timeout=90.0):
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.05)
        async with lock:
            active -= 1
        return {"content": f"sum-{model}", "usage": {}}

    service = SummarizerService(slow_query, chairman_model="chair/x")
    targets = {f"model/{i}": 100 + i for i in range(4)}
    _, jobs = await summarize_targets_parallel(
        user_content="question",
        context_block="x" * 5000,
        targets=targets,
        query_model_fn=slow_query,
        chairman_model="chair/x",
        summarizer=service,
        arena_models=list(targets.keys()),
    )
    assert len(jobs) == 4
    assert peak >= 2