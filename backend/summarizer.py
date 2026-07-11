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
USER_SUMMARIZE_PROMPT_ID = "context.summarize.user"
MID_TURN_SEMANTIC_PROMPT_ID = "mid_turn.semantic"


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
        self._cache: Dict[tuple[Any, ...], tuple[str, str, bool, bool]] = {}

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

    async def _summarize(
        self,
        *,
        content_block: str,
        target_tokens: int,
        target_model_id: str,
        prompt_id: str,
        cache_key: tuple[Any, ...],
        **prompt_vars: Any,
    ) -> Tuple[str, SummarizeJob]:
        cache_hit = cache_key in self._cache
        if cache_hit:
            content, model, chairman_fallback, structure_preserved = self._cache[cache_key]
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
                structure_preserved=structure_preserved,
            )

        wrapped_context, structure_spans = wrap_for_summarize(content_block)
        prompt_vars_with_block = dict(prompt_vars)
        if "context_block" in prompt_vars_with_block:
            prompt_vars_with_block["context_block"] = wrapped_context
        elif "user_content" in prompt_vars_with_block:
            prompt_vars_with_block["user_content"] = wrapped_context
        elif "responses_text" in prompt_vars_with_block:
            prompt_vars_with_block["responses_text"] = wrapped_context

        prompt_vars_with_block["target_tokens"] = target_tokens
        prompt = render_prompt(prompt_id, **prompt_vars_with_block)
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
        structure_preserved = True
        if resp and not resp.get("_failed"):
            raw_content = str(resp.get("content") or "")
            content, structure_preserved = restore_after_summarize(raw_content, structure_spans)
            outcome = "ok" if content.strip() else "empty"
            usage = resp.get("usage") or {}
            if usage.get("prompt_tokens"):
                input_tokens = int(usage["prompt_tokens"])
            output_tokens = int(usage.get("completion_tokens") or _estimate_tokens(content))

        if content.strip():
            self._cache[cache_key] = (content, model, chairman_fallback, structure_preserved)

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
            structure_preserved=structure_preserved,
        )
        return content, job

    async def summarize_rag(
        self,
        *,
        user_question: str,
        context_block: str,
        target_tokens: int,
        target_model_id: str,
        prompt_id: str = RAG_SUMMARIZE_PROMPT_ID,
    ) -> Tuple[str, SummarizeJob]:
        cache_key = (prompt_id, context_block, user_question, target_tokens)
        return await self._summarize(
            content_block=context_block,
            target_tokens=target_tokens,
            target_model_id=target_model_id,
            prompt_id=prompt_id,
            cache_key=cache_key,
            user_question=user_question,
            context_block=context_block,
        )

    async def summarize_user(
        self,
        *,
        user_content: str,
        target_tokens: int,
        target_model_id: str,
        prompt_id: str = USER_SUMMARIZE_PROMPT_ID,
    ) -> Tuple[str, SummarizeJob]:
        cache_key = (prompt_id, user_content, target_tokens)
        return await self._summarize(
            content_block=user_content,
            target_tokens=target_tokens,
            target_model_id=target_model_id,
            prompt_id=prompt_id,
            cache_key=cache_key,
            user_content=user_content,
        )

    async def summarize_semantic(
        self,
        *,
        user_query: str,
        responses_text: str,
        target_tokens: int,
        target_model_id: str,
        prompt_id: str = MID_TURN_SEMANTIC_PROMPT_ID,
    ) -> Tuple[str, SummarizeJob]:
        cache_key = (prompt_id, user_query, responses_text, target_tokens)
        return await self._summarize(
            content_block=responses_text,
            target_tokens=target_tokens,
            target_model_id=target_model_id,
            prompt_id=prompt_id,
            cache_key=cache_key,
            user_query=user_query,
            responses_text=responses_text,
        )