"""Conversation creation, retrieval, and deliberation delivery routes."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import ARENA_MODELS, CHAIRMAN_MODEL
from ..dependencies import (
    get_context_engine,
    get_settings,
    get_storage_service,
    load_runtime_settings,
)
from ..run_turn import run_turn
from ..storage_service import StorageService

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
logger = logging.getLogger(__name__)

AgentId = Annotated[str | None, Header(alias="X-Agent-Id")]
RequestOrigin = Annotated[str | None, Header(alias="X-Curia-Origin")]
class ConversationCreate(BaseModel):
    mode: str = "council"


class MessageCreate(BaseModel):
    content: str
    manual_context: list[dict[str, Any]] | None = None


class ConversationSummary(BaseModel):
    id: str
    created_at: str
    title: str
    message_count: int
    mode: str | None = "council"
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    arena_models: list[str] = Field(default_factory=list)
    chairman_model: str | None = None
    squad_fingerprint: str = ""


class ConversationDocument(BaseModel):
    id: str
    created_at: str
    title: str
    messages: list[dict[str, Any]]
    mode: str = "council"


def _origin(agent_id: str | None, requested: str | None) -> str:
    return requested or ("mcp" if agent_id else "api")


def _require_conversation(
    storage: StorageService,
    conversation_id: str,
) -> dict[str, Any]:
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _sse(event_type: str, **payload: Any) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


async def _progress_stream(
    task: asyncio.Task[Any],
    queue: asyncio.Queue[dict[str, Any]],
) -> AsyncIterator[str]:
    while not task.done() or not queue.empty():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.05)
        except TimeoutError:
            continue
        yield f"data: {json.dumps(event)}\n\n"


@router.get("", response_model=list[ConversationSummary])
async def conversation_index(
    storage: StorageService = Depends(get_storage_service),
) -> list[dict[str, Any]]:
    return storage.list_conversations()


@router.post("", response_model=ConversationDocument)
async def conversation_create(
    request: ConversationCreate,
    storage: StorageService = Depends(get_storage_service),
    agent_id: AgentId = None,
    requested_origin: RequestOrigin = None,
) -> dict[str, Any]:
    return storage.create_conversation(
        str(uuid.uuid4()),
        request.mode,
        caller=agent_id,
        origin=_origin(agent_id, requested_origin),
    )


@router.get("/{conversation_id}", response_model=ConversationDocument)
async def conversation_detail(
    conversation_id: str,
    storage: StorageService = Depends(get_storage_service),
) -> dict[str, Any]:
    return _require_conversation(storage, conversation_id)


@router.post("/{conversation_id}/message")
async def deliberation_create(
    conversation_id: str,
    request: MessageCreate,
    storage: StorageService = Depends(get_storage_service),
    settings: dict[str, Any] = Depends(get_settings),
    agent_id: AgentId = None,
    requested_origin: RequestOrigin = None,
) -> dict[str, Any]:
    _require_conversation(storage, conversation_id)
    try:
        result = await run_turn(
            conversation_id=conversation_id,
            content=request.content,
            storage_svc=storage,
            settings=settings,
            manual_context=request.manual_context,
            progress_cb=None,
            persist=True,
            caller=agent_id,
            origin=_origin(agent_id, requested_origin),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.response_dict


async def _deliberation_events(
    *,
    conversation_id: str,
    request: MessageCreate,
    conversation: dict[str, Any],
    storage: StorageService,
    agent_id: str | None,
    requested_origin: str | None,
) -> AsyncIterator[str]:
    runner: asyncio.Task[Any] | None = None
    call_origin = _origin(agent_id, requested_origin)
    try:
        settings = load_runtime_settings()
        context = await get_context_engine().prepare_context(
            conversation_id=conversation_id,
            user_input=request.content,
            mode=conversation.get("mode", "council"),
            manual_context=request.manual_context,
            conversation=conversation,
            arena_models=settings.get("arena_models", ARENA_MODELS),
            chairman_model=settings.get("chairman_model", CHAIRMAN_MODEL),
        )

        if context.directives.reset:
            storage.reset_conversation(conversation_id)
            yield _sse("reset", message="Conversation reset as requested.")
            yield _sse("complete")
            return

        if context.context_sources:
            yield _sse("rag_context", data=context.context_sources)
        if context.summarize_targets:
            yield _sse(
                "summarization",
                data={
                    "models": list(context.summarize_targets),
                    "targets": context.summarize_targets,
                },
            )
        yield _sse("stage1_start")

        storage.add_user_message(
            conversation_id,
            context.clean_query,
            caller=agent_id,
            origin=call_origin,
        )
        progress: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def report(event: dict[str, Any]) -> None:
            await progress.put(event)

        runner = asyncio.create_task(
            run_turn(
                conversation_id=conversation_id,
                content=request.content,
                storage_svc=storage,
                settings=settings,
                manual_context=request.manual_context,
                progress_cb=report,
                persist_user=False,
                persist_assistant=False,
                prepared_ctx=context,
                schedule_title=not conversation["messages"],
                caller=agent_id,
                origin=call_origin,
            )
        )
        async for progress_event in _progress_stream(runner, progress):
            yield progress_event

        turn = await runner
        response = turn.response_dict
        stage1 = response.get("stage1", [])
        stage2 = response.get("stage2", [])
        stage3 = response.get("stage3", {})
        metadata = response.get("metadata", {})

        yield _sse(
            "stage1_complete",
            data=stage1,
            metadata={
                "steps": metadata.get("steps"),
                "mode": metadata.get("mode") or conversation.get("mode", "council"),
                "label_to_model": metadata.get("label_to_model"),
                "aggregate_rankings": metadata.get("aggregate_rankings"),
                "cost": metadata.get("cost"),
            },
        )

        if not stage1:
            message = "No arena responses received; check model availability or API key."
            yield _sse("error", message=message)
            storage.add_assistant_message(
                conversation_id,
                [],
                [],
                {"model": "system", "response": message},
                turn.context_sources,
                metadata={"mode": conversation.get("mode", "council")},
                caller=agent_id,
                origin=call_origin,
            )
            yield _sse("complete")
            return

        if stage2:
            yield _sse("stage2_start")
            yield _sse("stage2_complete", data=stage2, metadata=metadata)
        yield _sse("stage3_start")
        yield _sse("stage3_complete", data=stage3)

        if turn.title_task:
            title = await turn.title_task
            storage.update_conversation_title(conversation_id, title)
            yield _sse("title_complete", data={"title": title})

        storage.add_assistant_message(
            conversation_id,
            stage1,
            stage2,
            stage3,
            turn.context_sources,
            metadata=metadata,
            caller=agent_id,
            origin=call_origin,
        )
        yield _sse("complete")
    except asyncio.CancelledError:
        if runner and not runner.done():
            runner.cancel()
        raise
    except Exception as exc:
        logger.exception("Deliberation stream failed conversation=%s", conversation_id)
        yield _sse("error", message=str(exc))


@router.post("/{conversation_id}/message/stream")
async def deliberation_stream(
    conversation_id: str,
    request: MessageCreate,
    storage: StorageService = Depends(get_storage_service),
    agent_id: AgentId = None,
    requested_origin: RequestOrigin = None,
) -> StreamingResponse:
    conversation = _require_conversation(storage, conversation_id)
    events = _deliberation_events(
        conversation_id=conversation_id,
        request=request,
        conversation=conversation,
        storage=storage,
        agent_id=agent_id,
        requested_origin=requested_origin,
    )
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
