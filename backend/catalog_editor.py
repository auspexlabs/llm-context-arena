"""Read/write helpers for model_catalog.yaml (DEC-018 Phase C / DEF-008)."""

from __future__ import annotations

import threading
from typing import Any, Dict

import yaml

from .catalog_refresh import get_catalog_meta
from .frozen_config import clear_frozen_cache
from .frozen_config.loader import MODEL_CATALOG_PATH
from .frozen_config.schemas import ModelCatalog, ModelEntry

_CATALOG_WRITE_LOCK = threading.Lock()


def _read_catalog_raw() -> Dict[str, Any]:
    if not MODEL_CATALOG_PATH.is_file():
        return {"version": 1, "models": {}}
    raw = yaml.safe_load(MODEL_CATALOG_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {"version": 1, "models": {}}


def _write_catalog_raw(data: Dict[str, Any]) -> None:
    MODEL_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_CATALOG_PATH.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def list_catalog_models() -> Dict[str, Any]:
    """Return all catalog entries validated against the frozen schema."""
    raw = _read_catalog_raw()
    catalog = ModelCatalog.model_validate(raw)
    models = {
        model_id: entry.model_dump()
        for model_id, entry in catalog.models.items()
    }
    return {
        "version": catalog.version,
        "models": models,
        "count": len(models),
    }


def catalog_meta_summary() -> Dict[str, Any]:
    """Last OpenRouter refresh metadata for the settings UI."""
    meta = get_catalog_meta()
    return {
        "last_refresh_at": meta.get("last_refresh_at"),
        "last_refresh_source": meta.get("last_refresh_source"),
        "updated_count": meta.get("updated_count"),
        "requires_restart": True,
        "catalog_path": str(MODEL_CATALOG_PATH),
    }


def update_catalog_model_fields(
    model_id: str,
    fields: Dict[str, Any],
) -> Dict[str, Any]:
    """Patch editable catalog fields (tags, model_modifier, manual_override_limit)."""
    with _CATALOG_WRITE_LOCK:
        raw = _read_catalog_raw()
        models = raw.setdefault("models", {})
        if model_id not in models or not isinstance(models[model_id], dict):
            raise KeyError(model_id)

        entry = dict(models[model_id])
        allowed = {"tags", "model_modifier", "manual_override_limit"}
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "tags":
                entry["tags"] = list(value or [])
            elif key == "model_modifier":
                entry["model_modifier"] = float(value)
            elif key == "manual_override_limit":
                if value is None:
                    entry.pop("manual_override_limit", None)
                else:
                    entry["manual_override_limit"] = int(value)

        validated = ModelEntry.model_validate(entry)
        models[model_id] = validated.model_dump(exclude_none=True)
        raw["models"] = models
        ModelCatalog.model_validate(raw)
        _write_catalog_raw(raw)

    clear_frozen_cache()
    return {
        "model_id": model_id,
        "entry": validated.model_dump(),
        "requires_restart": True,
    }