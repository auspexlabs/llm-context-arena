"""Summarizer service — optional model with chairman fallback (DEC-018)."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple

from .budget_metadata import SummarizeJob
from .config import CHAIRMAN_MODEL
from .frozen_config import get_frozen_snapshot
from .prompts import render_prompt
from .rag_lmstudio import _estimate_tokens
from .structure_wrap import restore_after_summarize, wrap_for_summarize

logger = logging.getLogger(__name__)

RAG_SUMMARIZE_PROMPT_ID = "context.summarize.rag"


class SummarizerService:
    """Compress context via optional summarizer_model; chairman fallback when unset."""

    def __init__(
        self,
        query_model_fn: Callable,
        chairman_model: str = CHAIRMAN_MODEL,
        summarizer_model: Optional[str] = None,
        chairman_fallback: Optional[bool] = None,
    ):
        snapshot = get_frozen_snapshot()
        cfg = snapshot.arena.summarizer
        self.query_model_fn = query_model_fn
        self.chairman_model = chairman_model
        self.summarizer_model = summarizer_model if summarizer_model is not None else cfg.model
        self.chairman_fallback = (
            chairman_fallback if chairman_fallback is not None else cfg.chairman_fallback
        )
        self._cache: Dict[tuple[str, str, int, str], tuple[str, str, bool]] = {}

    def _resolve_model(self) -> tuple[str, bool]:
        if self.summarizer_model:
            return self.summarizer_model, False
        if self.chairman_fallback:
            logger.info(
                "summarizer_model unset; using chairman fallback (%s)",
                self.chairman_model,
            )
            return self.chairman_model, True
        logger.warning("summarizer_model unset and chairman_fallback disabled; using chairman")
        return self.chairman_model, True

    async def summarize_rag(
        self,
        *,
        user_question: str,
        context_block: str,
        target_tokens: int,
        target_model_id: str,
        prompt_id: str = RAG_SUMMARIZE_PROMPT_ID,
    ) -> Tuple[str, SummarizeJob]:
        cache_key = (context_block, user_question, target_tokens, prompt_id)
        cache_hit = cache_key in self._cache
        if cache_hit:
            content, model, chairman_fallback = self._cache[cache_key]
            return content, SummarizeJob(
                prompt_id=prompt_id,
                target_model_id=target_model_id,
                summarizer_model=model,
                chairman_fallback=chairman_fallback,
                duration_ms=0,
                input_tokens=0,
                output_tokens=_estimate_tokens(content),
                target_tokens=target_tokens,
                cache_hit=True,
                outcome="ok" if content.strip() else "empty",
            )

        wrapped_context, structure_spans = wrap_for_summarize(context_block)
        prompt = render_prompt(
            prompt_id,
            user_question=user_question,
            context_block=wrapped_context,
            target_tokens=target_tokens,
        )
        model, chairman_fallback = self._resolve_model()
        input_tokens = _estimate_tokens(prompt)
        started = time.time()
        resp = await self.query_model_fn(
            model,
            [{"role": "user", "content": prompt}],
            timeout=90.0,
        )
        duration_ms = int((time.time() - started) * 1000)

        content = ""
        outcome = "failed"
        output_tokens = 0
        if resp and not resp.get("_failed"):
            raw_content = str(resp.get("content") or "")
            content, _ = restore_after_summarize(raw_content, structure_spans)
            outcome = "ok" if content.strip() else "empty"
            usage = resp.get("usage") or {}
            if usage.get("prompt_tokens"):
                input_tokens = int(usage["prompt_tokens"])
            output_tokens = int(usage.get("completion_tokens") or _estimate_tokens(content))

        if content.strip():
            self._cache[cache_key] = (content, model, chairman_fallback)

        job = SummarizeJob(
            prompt_id=prompt_id,
            target_model_id=target_model_id,
            summarizer_model=model,
            chairman_fallback=chairman_fallback,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            target_tokens=target_tokens,
            cache_hit=False,
            outcome=outcome,
        )
        return content, job