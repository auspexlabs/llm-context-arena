"""Parallel summarize pool with concurrency limit (DEC-018 Phase B)."""

from __future__ import annotations

import asyncio
from typing import Callable, Dict, List, Optional, Tuple

from .budget_metadata import SummarizeJob
from .frozen_config import get_frozen_snapshot
from .summarizer import SummarizerService


def resolve_summarize_concurrency(
    arena_models: List[str],
    chairman_model: str,
    override: Optional[int] = None,
) -> int:
    """Concurrency = len(arena) - 1 (chairman excluded); config override wins."""
    if override is not None:
        return max(1, override)
    pool = [m for m in arena_models if m != chairman_model]
    if len(pool) <= 1:
        return 1
    return max(1, len(pool) - 1)


async def summarize_targets_parallel(
    *,
    user_content: str,
    context_block: str,
    targets: Dict[str, int],
    query_model_fn: Callable,
    chairman_model: str,
    summarizer: SummarizerService,
    arena_models: Optional[List[str]] = None,
) -> Tuple[Dict[str, str], List[SummarizeJob]]:
    """
    Run per-model summarizations in parallel.

    Deduplicates identical target token budgets but emits one SummarizeJob per model.
    """
    from .budget import summarize_context_for_budget

    if not targets:
        return {}, []

    models = arena_models or list(targets.keys())
    cfg = get_frozen_snapshot().arena.summarizer
    concurrency = resolve_summarize_concurrency(models, chairman_model, cfg.concurrency)
    sem = asyncio.Semaphore(concurrency)

    by_target: Dict[int, List[str]] = {}
    for model, target in targets.items():
        by_target.setdefault(target, []).append(model)

    compressed_by_target: Dict[int, str] = {}
    jobs_by_target: Dict[int, SummarizeJob] = {}

    async def run_target(target: int, model_list: List[str]) -> None:
        async with sem:
            representative = model_list[0]
            compressed, job = await summarize_context_for_budget(
                user_content,
                context_block,
                target,
                query_model_fn,
                chairman_model,
                target_model_id=representative,
                summarizer=summarizer,
            )
            compressed_by_target[target] = compressed or context_block
            jobs_by_target[target] = job

    await asyncio.gather(*[run_target(t, ms) for t, ms in by_target.items()])

    compressed_by_model: Dict[str, str] = {}
    jobs: List[SummarizeJob] = []
    for model, target in targets.items():
        compressed_by_model[model] = compressed_by_target[target]
        base_job = jobs_by_target[target]
        if model == by_target[target][0]:
            jobs.append(
                SummarizeJob(
                    prompt_id=base_job.prompt_id,
                    target_model_id=model,
                    summarizer_model=base_job.summarizer_model,
                    chairman_fallback=base_job.chairman_fallback,
                    duration_ms=base_job.duration_ms,
                    input_tokens=base_job.input_tokens,
                    output_tokens=base_job.output_tokens,
                    target_tokens=base_job.target_tokens,
                    cache_hit=base_job.cache_hit,
                    outcome=base_job.outcome,
                    structure_preserved=base_job.structure_preserved,
                )
            )
        else:
            jobs.append(
                SummarizeJob(
                    prompt_id=base_job.prompt_id,
                    target_model_id=model,
                    summarizer_model=base_job.summarizer_model,
                    chairman_fallback=base_job.chairman_fallback,
                    duration_ms=0,
                    input_tokens=0,
                    output_tokens=base_job.output_tokens,
                    target_tokens=base_job.target_tokens,
                    cache_hit=True,
                    outcome=base_job.outcome,
                    structure_preserved=base_job.structure_preserved,
                )
            )

    return compressed_by_model, jobs