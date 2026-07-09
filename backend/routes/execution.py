"""Opt-in detailed execution payloads for agent/history surfaces."""

from __future__ import annotations

from typing import Any, Dict, List, Set

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_storage_service
from ..storage_service import StorageService

router = APIRouter(prefix="/api/conversations/{conversation_id}", tags=["execution"])

_STEP_KEYS = frozenset(
    {
        "model",
        "role",
        "response",
        "prompt_preview",
        "prompt_full",
        "est_tokens",
        "context_tokens",
        "duration_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
        "parsed_ranking",
        "ranking",
    }
)


def _filter_steps(
    steps: List[Dict[str, Any]],
    include: Set[str],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for step in steps:
        row: Dict[str, Any] = {
            "model": step.get("model"),
            "role": step.get("role"),
            "response": step.get("response"),
        }
        if "prompts" in include:
            row["prompt_preview"] = step.get("prompt_preview")
        if "full_prompts" in include:
            row["prompt_full"] = step.get("prompt_full")
        if "cost" in include:
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cost_usd",
                "est_tokens",
                "context_tokens",
                "duration_ms",
            ):
                if key in step:
                    row[key] = step[key]
        if "rankings" in include and step.get("ranking"):
            row["ranking"] = step.get("ranking")
            row["parsed_ranking"] = step.get("parsed_ranking")
        out.append(row)
    return out


@router.get("/messages/{message_index}/execution")
async def get_message_execution(
    conversation_id: str,
    message_index: int,
    include: str = Query(
        "",
        description="Comma-separated: prompts,full_prompts,failures,cost,rankings,context,steps",
    ),
    storage_svc: StorageService = Depends(get_storage_service),
):
    """
    Opt-in execution detail for a stored assistant message.

    Default (empty include): stage summaries + failures only.
    """
    conversation = storage_svc.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = conversation.get("messages", [])
    if message_index < 0 or message_index >= len(messages):
        raise HTTPException(status_code=404, detail="Message index out of range")

    msg = messages[message_index]
    if msg.get("role") != "assistant":
        raise HTTPException(status_code=400, detail="Message is not an assistant turn")

    meta = msg.get("metadata") or {}
    flags = {part.strip().lower() for part in include.split(",") if part.strip()}
    if not flags:
        flags = {"failures"}

    payload: Dict[str, Any] = {
        "conversation_id": conversation_id,
        "message_index": message_index,
        "mode": meta.get("mode") or conversation.get("mode"),
    }

    if "failures" in flags or not include:
        payload["model_failures"] = meta.get("model_failures") or []

    if "context" in flags:
        payload["context_sources"] = msg.get("context_sources") or []

    if "cost" in flags:
        payload["cost"] = meta.get("cost")

    if "steps" in flags or "prompts" in flags or "full_prompts" in flags or "rankings" in flags:
        steps = meta.get("steps") or []
        if not steps and msg.get("stage1"):
            steps = list(msg.get("stage1") or [])
            if msg.get("stage2"):
                steps.extend(msg.get("stage2") or [])
            if msg.get("stage3"):
                steps.append(msg.get("stage3"))
        payload["steps"] = _filter_steps(steps, flags | {"prompts", "full_prompts", "cost", "rankings"})

    if flags == {"failures"} or (not include and "steps" not in payload):
        payload["stage3_preview"] = (msg.get("stage3") or {}).get("response", "")[:500]
        payload["aggregate_rankings"] = meta.get("aggregate_rankings")

    return payload