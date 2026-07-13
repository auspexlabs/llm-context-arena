"""Catalog refresh and observation API (DEC-018 Phase B)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..catalog_editor import catalog_meta_summary, list_catalog_models, update_catalog_model_fields
from ..catalog_refresh import refresh_catalog, validate_frozen_config
from ..dependencies import load_runtime_settings
from ..observations import get_observation_service
from ..squad_presets import load_squad_preset

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


class ObservationActionResponse(BaseModel):
    ok: bool
    observation: Optional[Dict[str, Any]] = None


class CatalogModelUpdateRequest(BaseModel):
    tags: Optional[List[str]] = None
    model_modifier: Optional[float] = None
    manual_override_limit: Optional[int] = None
    clear_manual_override: bool = False


class CatalogModelUpdateResponse(BaseModel):
    ok: bool
    model_id: str
    entry: Dict[str, Any]
    requires_restart: bool = True


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


@router.post("/observations/sweep-expired")
async def sweep_expired_observations() -> Dict[str, Any]:
    """Archive expired accepted observations and flag models for re-verification."""
    return get_observation_service().sweep_expired_observations()


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


@router.get("/models")
async def catalog_models() -> Dict[str, Any]:
    """List all models in model_catalog.yaml (DEF-008 editor read path)."""
    return list_catalog_models()


@router.get("/meta")
async def catalog_meta() -> Dict[str, Any]:
    """Catalog refresh metadata and restart hints for the UI."""
    return catalog_meta_summary()


@router.patch("/models/{model_id:path}", response_model=CatalogModelUpdateResponse)
async def patch_catalog_model(
    model_id: str,
    body: CatalogModelUpdateRequest,
) -> CatalogModelUpdateResponse:
    """Update tags, modifiers, or manual override for one catalog model."""
    fields: Dict[str, Any] = {}
    if body.tags is not None:
        fields["tags"] = body.tags
    if body.model_modifier is not None:
        fields["model_modifier"] = body.model_modifier
    if body.clear_manual_override:
        fields["manual_override_limit"] = None
    elif body.manual_override_limit is not None:
        fields["manual_override_limit"] = body.manual_override_limit
    if not fields:
        raise HTTPException(status_code=400, detail="No editable fields provided")

    try:
        result = update_catalog_model_fields(model_id, fields)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Model not in catalog: {model_id}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CatalogModelUpdateResponse(
        ok=True,
        model_id=result["model_id"],
        entry=result["entry"],
        requires_restart=result.get("requires_restart", True),
    )