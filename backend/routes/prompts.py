"""Prompt registry API (DEC-018 A5)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from ..prompts import get_prompt, list_prompts

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("")
async def list_system_prompts(
    mode: Optional[str] = Query(None, description="Filter by arena mode"),
) -> Dict[str, Any]:
    """List registered system prompts (metadata only; no templates)."""
    prompts = list_prompts(mode=mode)
    return {"prompts": prompts, "count": len(prompts)}


@router.get("/{prompt_id}")
async def get_system_prompt(prompt_id: str) -> Dict[str, Any]:
    """Return one prompt entry including template."""
    entry = get_prompt(prompt_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown prompt_id: {prompt_id}")
    return {
        "prompt_id": entry.prompt_id,
        "version": entry.version,
        "mode": entry.mode,
        "variables": list(entry.variables),
        "description": entry.description,
        "template": entry.template,
    }