"""Paged session-history queries for the Observatory."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_storage_service
from ..session_catalog import InvalidSessionCursor, SessionQuery
from ..storage_service import StorageService


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
async def list_sessions(
    limit: int = Query(50, ge=1, le=100),
    cursor: Optional[str] = Query(None, max_length=2048),
    mode: Optional[str] = Query(None, max_length=128),
    caller: Optional[str] = Query(None, max_length=256),
    origin: Optional[str] = Query(None, max_length=128),
    status: Optional[str] = Query(None, max_length=128),
    quality: Optional[str] = Query(None, max_length=128),
    squad: Optional[str] = Query(None, max_length=256),
    from_at: Optional[str] = Query(None, alias="from", max_length=64),
    to_at: Optional[str] = Query(None, alias="to", max_length=64),
    sort: str = Query("updated_desc", pattern="^(updated_desc|created_desc|cost_desc)$"),
    storage_svc: StorageService = Depends(get_storage_service),
):
    """Return a stable keyset page; filters are applied in SQLite."""
    try:
        return storage_svc.list_sessions(
            SessionQuery(
                limit=limit,
                cursor=cursor,
                mode=mode,
                caller=caller,
                origin=origin,
                status=status,
                quality=quality,
                squad=squad,
                from_at=from_at,
                to_at=to_at,
                sort=sort,
            )
        )
    except InvalidSessionCursor as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
