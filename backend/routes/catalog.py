"""Catalog refresh and observation API (DEC-018 Phase B)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..catalog_refresh import refresh_catalog, validate_frozen_config
from ..dependencies import load_runtime_settings
from ..observations import get_observation_service
from ..squad_presets import load_squad_preset

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


class ObservationActionResponse(BaseModel):
    ok: bool
    observation: Optional[Dict[str, Any]] = None


@router.post("/refresh")
async def catalog_refresh(
    force: bool = Query(False),
    dry_run: bool = Query(False),
) -> Dict[str, Any]:
    """Pull registered limits from OpenRouter and update model_catalog.yaml."""
    return await refresh_catalog(force=force, dry_run=dry_run)


@router.get("/effective-limits")
async def catalog_effective_limits(
    squad: Optional[str] = Query(None, description="Squad preset name"),
    models: Optional[str] = Query(None, description="Comma-separated model ids"),
) -> Dict[str, Any]:
    """Show computed effective limits and pending observations."""
    if models:
        model_ids = [m.strip() for m in models.split(",") if m.strip()]
        squad_name = None
    elif squad:
        preset = load_squad_preset(squad)
        model_ids = list(preset["arena_models"])
        squad_name = squad
    else:
        settings = load_runtime_settings()
        model_ids = list(settings.get("arena_models") or [])
        squad_name = settings.get("arena_squad")

    service = get_observation_service()
    return service.effective_limits_report(model_ids, squad_name=squad_name)


@router.get("/observations/pending")
async def list_pending_observations(
    squad: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """List pending limit observations (optionally filtered by squad models)."""
    service = get_observation_service()
    model_ids: List[str] = []
    if squad:
        preset = load_squad_preset(squad)
        model_ids = list(preset["arena_models"])
    pending = service.pending_for_models(model_ids)
    threshold = service.resolver.arena.catalog.observation_delta_threshold
    return {
        "pending": [p.to_dict() for p in pending],
        "count": len(pending),
        "delta_threshold": threshold,
    }


@router.post("/observations/{obs_id}/accept", response_model=ObservationActionResponse)
async def accept_observation(obs_id: int) -> ObservationActionResponse:
    """Accept a pending observation — promotes to live observed_limit."""
    service = get_observation_service()
    accepted = service.accept(obs_id)
    if accepted is None:
        raise HTTPException(status_code=404, detail=f"Pending observation {obs_id} not found")
    return ObservationActionResponse(ok=True, observation=accepted.to_dict())


@router.post("/observations/{obs_id}/decline", response_model=ObservationActionResponse)
async def decline_observation(obs_id: int) -> ObservationActionResponse:
    """Decline a pending observation."""
    service = get_observation_service()
    if not service.decline(obs_id):
        raise HTTPException(status_code=404, detail=f"Pending observation {obs_id} not found")
    return ObservationActionResponse(ok=True, observation=None)


@router.get("/validate")
async def config_validate() -> Dict[str, Any]:
    """Validate arena_config.yaml and model_catalog.yaml schemas."""
    ok, issues = validate_frozen_config()
    return {"ok": ok, "issues": issues}