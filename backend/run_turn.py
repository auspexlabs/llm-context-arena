"""Shared turn execution service for sync, stream, and agent APIs."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .arena import generate_conversation_title, run_full_arena
from .config import ARENA_MODELS, CHAIRMAN_MODEL
from .context_engine import ContextResult
from .dependencies import get_context_engine, get_rag_provider_dep
from .models import (
    ArenaExecution,
    ArenaMetadata,
    ArenaMode,
    Stage1Result,
    Stage2Result,
    Stage3Result,
)
from .storage import reset_conversation
from .storage_service import StorageService

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


@dataclass
class TurnRunResult:
    """Outcome of a full arena turn."""

    response_dict: Dict[str, Any]
    execution: Optional[ArenaExecution] = None
    reset: bool = False
    context_sources: List[Dict[str, Any]] = field(default_factory=list)
    title_task: Optional[asyncio.Task] = None


def build_arena_execution(
    *,
    conversation_id: str,
    mode: str,
    ctx: ContextResult,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    metadata: Dict[str, Any],
    arena_models: List[str],
    chairman_model: str,
) -> ArenaExecution:
    """Map arena runner output to ArenaExecution."""
    meta = ArenaMetadata(
        mode=ArenaMode(mode) if mode in ArenaMode._value2member_map_ else ArenaMode.COUNCIL,
        chairman_model=chairman_model,
        arena_models=arena_models,
        label_to_model=metadata.get("label_to_model"),
        aggregate_rankings=metadata.get("aggregate_rankings"),
        steps=metadata.get("steps"),
        directives=ctx.directives.dict(),
        warnings=list(ctx.warnings or []),
        total_execution_time_ms=metadata.get("total_execution_time_ms"),
    )
    for key, value in metadata.items():
        if key not in meta.model_dump(exclude_none=True):
            setattr(meta, key, value)

    return ArenaExecution(
        conversation_id=conversation_id,
        mode=meta.mode,
        user_query=ctx.clean_query,
        user_query_raw=ctx.clean_query,
        context_block=ctx.context_block,
        context_sources=ctx.context_sources,
        rag_used=ctx.rag_used,
        stage1=Stage1Result.from_dicts(stage1_results) if stage1_results else None,
        stage2=Stage2Result.from_dicts(
            stage2_results,
            metadata.get("label_to_model") or {},
            metadata.get("aggregate_rankings"),
        )
        if stage2_results
        else None,
        stage3=Stage3Result.from_dict(stage3_result) if stage3_result else None,
        metadata=meta,
    )


def _assistant_metadata(
    metadata: Dict[str, Any],
    ctx: ContextResult,
    *,
    mode: str,
    arena_models: List[str],
    chairman_model: str,
) -> Dict[str, Any]:
    return {
        "label_to_model": metadata.get("label_to_model"),
        "aggregate_rankings": metadata.get("aggregate_rankings"),
        "directives": ctx.directives.dict(),
        "warnings": list(ctx.warnings or []),
        "mode": mode,
        "chairman_model": chairman_model,
        "arena_models": arena_models,
        "steps": metadata.get("steps"),
        "cost": metadata.get("cost"),
        "context_from_last_chair": ctx.context_from_last_chair,
    }


async def run_turn(
    *,
    conversation_id: str,
    content: str,
    storage_svc: StorageService,
    settings: Dict[str, Any],
    manual_context: Optional[List[Dict[str, Any]]] = None,
    progress_cb: Optional[ProgressCallback] = None,
    persist: bool = True,
    persist_user: Optional[bool] = None,
    persist_assistant: Optional[bool] = None,
    prepared_ctx: Optional[ContextResult] = None,
    schedule_title: bool = True,
) -> TurnRunResult:
    """
    Prepare context, run the arena for a conversation, optionally persist messages.

    Used by sync message API, streaming API, and MCP full-turn tools.
    """
    conversation = storage_svc.get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    arena_models = settings.get("arena_models", ARENA_MODELS)
    chairman_model = settings.get("chairman_model", CHAIRMAN_MODEL)
    mode = conversation.get("mode", "council")
    is_first_message = len(conversation.get("messages", [])) == 0
    save_user = persist if persist_user is None else persist_user
    save_assistant = persist if persist_assistant is None else persist_assistant

    if prepared_ctx is not None:
        ctx = prepared_ctx
    else:
        ctx = await get_context_engine().prepare_context(
            conversation_id=conversation_id,
            user_input=content,
            mode=mode,
            manual_context=manual_context,
            conversation=conversation,
            arena_models=arena_models,
            chairman_model=chairman_model,
        )

    if ctx.directives.reset:
        reset_conversation(conversation_id)
        reset_payload = {
            "stage1": [],
            "stage2": [],
            "stage3": {"model": "system", "response": "Conversation reset as requested."},
            "metadata": {"directives": ctx.directives.dict(), "warnings": ctx.warnings},
            "context_sources": [],
            "directives": ctx.directives.dict(),
            "warnings": ctx.warnings,
        }
        return TurnRunResult(response_dict=reset_payload, reset=True)

    context_tokens = (
        get_rag_provider_dep().estimate_tokens(ctx.context_block) if ctx.context_block else 0
    )

    title_task: Optional[asyncio.Task] = None
    if save_user:
        storage_svc.add_user_message(conversation_id, ctx.clean_query)
        if is_first_message and schedule_title:
            title_task = asyncio.create_task(generate_conversation_title(ctx.clean_query))
    elif is_first_message and schedule_title:
        title_task = asyncio.create_task(generate_conversation_title(ctx.clean_query))

    stage1_results, stage2_results, stage3_result, metadata = await run_full_arena(
        ctx.base_prompt,
        ctx.per_model_prompts if ctx.per_model_prompts else None,
        mode=mode,
        arena_models=arena_models,
        chairman_model=chairman_model,
        iterations=ctx.directives.iterations_override,
        context_tokens=context_tokens,
        context_tokens_map=ctx.context_token_map,
        progress_cb=progress_cb,
    )

    metadata["directives"] = ctx.directives.dict()
    metadata["warnings"] = list(ctx.warnings or [])
    metadata["mode"] = mode
    metadata["context_from_last_chair"] = ctx.context_from_last_chair

    execution = build_arena_execution(
        conversation_id=conversation_id,
        mode=mode,
        ctx=ctx,
        stage1_results=stage1_results,
        stage2_results=stage2_results,
        stage3_result=stage3_result,
        metadata=metadata,
        arena_models=arena_models,
        chairman_model=chairman_model,
    )
    response_dict = execution.to_response_dict()
    response_dict["warnings"] = list(ctx.warnings or [])

    if save_assistant:
        if title_task:
            title = await title_task
            storage_svc.update_conversation_title(conversation_id, title)

        storage_svc.add_assistant_message(
            conversation_id,
            stage1_results,
            stage2_results,
            stage3_result,
            ctx.context_sources,
            metadata=_assistant_metadata(
                metadata,
                ctx,
                mode=mode,
                arena_models=arena_models,
                chairman_model=chairman_model,
            ),
        )

    return TurnRunResult(
        response_dict=response_dict,
        execution=execution,
        context_sources=ctx.context_sources,
        title_task=title_task,
    )