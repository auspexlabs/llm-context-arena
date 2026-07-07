"""Arena squad presets — JSON files in backend/squads/."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SQUADS_DIR = Path(__file__).resolve().parent / "squads"
DEFAULT_SQUAD = "normal"


def list_squad_names() -> List[str]:
    return sorted(p.stem for p in SQUADS_DIR.glob("*.json"))


def list_squad_summaries() -> List[Dict[str, Any]]:
    return [
        {
            "name": preset["name"],
            "label": preset.get("label", preset["name"]),
            "description": preset.get("description", ""),
            "arena_count": len(preset.get("arena_models", [])),
            "chairman_model": preset.get("chairman_model", ""),
        }
        for preset in (load_squad_preset(name) for name in list_squad_names())
    ]


def load_squad_preset(name: str) -> Dict[str, Any]:
    """Load a squad preset by filename stem (e.g. normal, freebee9)."""
    key = (name or DEFAULT_SQUAD).strip().lower()
    path = SQUADS_DIR / f"{key}.json"
    if not path.is_file():
        available = ", ".join(list_squad_names()) or "(none)"
        raise ValueError(f"Unknown arena squad {name!r}; available: {available}")

    data = json.loads(path.read_text(encoding="utf-8"))
    models = [m.strip() for m in data.get("arena_models", []) if m and str(m).strip()]
    chairman = (data.get("chairman_model") or "").strip()
    if not models:
        raise ValueError(f"Squad {key!r} has no arena_models")
    if not chairman:
        raise ValueError(f"Squad {key!r} has no chairman_model")

    return {
        "name": data.get("name", key),
        "label": data.get("label", key),
        "description": data.get("description", ""),
        "arena_models": models,
        "chairman_model": chairman,
    }


def resolve_startup_squad(env_value: str | None = None) -> Dict[str, Any]:
    """Load squad for process startup; fall back to normal on bad env."""
    requested = (env_value or DEFAULT_SQUAD).strip().lower()
    try:
        return load_squad_preset(requested)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        logger.warning("ARENA_SQUAD=%r invalid (%s); using %s", requested, exc, DEFAULT_SQUAD)
        return load_squad_preset(DEFAULT_SQUAD)