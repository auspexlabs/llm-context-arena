"""Paged session-history queries for the Observatory."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_storage_service
from ..session_catalog import InvalidSessionCursor, SessionQuery
from ..storage_service import StorageService


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _normalize_timestamp(value: Optional[str], field: str) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field} timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
                from_at=_normalize_timestamp(from_at, "from"),
                to_at=_normalize_timestamp(to_at, "to"),
                sort=sort,
            )
        )
    except InvalidSessionCursor as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
