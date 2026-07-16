"""Agent turn control plane routes (PIV-001 Phase 1)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from ..dependencies import get_settings, get_storage_service
from ..storage_service import StorageService
from ..turn_service import TurnService

router = APIRouter(prefix="/api/conversations/{conversation_id}/turns", tags=["turns"])


def get_turn_service(
    storage_svc: StorageService = Depends(get_storage_service),
) -> TurnService:
    return TurnService(storage_svc)


class CreateTurnRequest(BaseModel):
    content: str
    manual_context: List[Dict[str, Any]] | None = None


class TurnResponse(BaseModel):
    turn: Dict[str, Any]


@router.post("", response_model=TurnResponse)
async def create_turn(
    conversation_id: str,
    request: CreateTurnRequest,
    turn_service: TurnService = Depends(get_turn_service),
    settings: Dict[str, Any] = Depends(get_settings),
    x_agent_id: Optional[str] = Header(None, alias="X-Agent-Id"),
    x_curia_origin: Optional[str] = Header(None, alias="X-Curia-Origin"),
):
    """
    Agent-initiated turn: prepare context and persist checkpoint.

    Council mode only. Does not run arena stages until advance.
    """
    try:
        turn = await turn_service.create_turn(
            conversation_id,
            request.content,
            settings=settings,
            manual_context=request.manual_context,
            agent_id=x_agent_id,
            origin=x_curia_origin or ("mcp" if x_agent_id else "api"),
        )
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail.lower() else 409
        raise HTTPException(status_code=status, detail=detail) from exc

    return {"turn": turn.to_api_dict()}


@router.post("/{turn_id}/advance", response_model=TurnResponse)
async def advance_turn(
    conversation_id: str,
    turn_id: str,
    turn_service: TurnService = Depends(get_turn_service),
):
    """Run the next council step: stage1 → stage2 → stage3."""
    try:
        turn = await turn_service.advance_turn(conversation_id, turn_id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return {"turn": turn.to_api_dict()}


@router.get("/{turn_id}", response_model=TurnResponse)
async def get_turn(
    conversation_id: str,
    turn_id: str,
    turn_service: TurnService = Depends(get_turn_service),
):
    """Poll turn state and partial execution."""
    turn = turn_service.get_turn(conversation_id, turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    return {"turn": turn.to_api_dict()}


@router.delete("/{turn_id}", response_model=TurnResponse)
async def cancel_turn(
    conversation_id: str,
    turn_id: str,
    turn_service: TurnService = Depends(get_turn_service),
):
    """Cancel an in-progress turn."""
    try:
        turn = turn_service.cancel_turn(conversation_id, turn_id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return {"turn": turn.to_api_dict()}


@router.get("")
async def list_turns(
    conversation_id: str,
    turn_service: TurnService = Depends(get_turn_service),
    storage_svc: StorageService = Depends(get_storage_service),
):
    """List turns for a conversation (newest first)."""
    if storage_svc.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    turns = turn_service.turn_store.list_for_conversation(conversation_id)
    return {"turns": [t.to_api_dict() for t in turns]}
