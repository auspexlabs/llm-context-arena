"""Runtime settings and squad preset endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..dependencies import apply_squad_preset, load_runtime_settings, save_runtime_settings
from ..squad_presets import list_squad_summaries

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    arena_models: list[str] | None = None
    chairman_model: str | None = None
    theme: str | None = None
    repo_root: str | None = None


@router.get("")
async def read_settings():
    return load_runtime_settings()


@router.post("")
async def update_settings(payload: SettingsUpdate):
    return save_runtime_settings(payload.model_dump(exclude_none=True))


@router.get("/squads")
async def list_squads():
    return {"squads": list_squad_summaries()}


@router.post("/squad/{squad_name}")
async def select_squad(squad_name: str):
    try:
        return apply_squad_preset(squad_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
