"""OpenRouter catalog refresh job (DEC-018 Phase B)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import yaml

from .config import OPENROUTER_API_KEY
from .frozen_config.loader import MODEL_CATALOG_PATH

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CATALOG_META_PATH = _PROJECT_ROOT / "data" / "catalog_meta.yaml"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def get_catalog_meta() -> Dict[str, Any]:
    return _read_yaml(CATALOG_META_PATH)


def is_refresh_due(ttl_hours: int) -> bool:
    meta = get_catalog_meta()
    last = meta.get("last_refresh_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        return age_hours >= ttl_hours
    except Exception:
        return True


async def fetch_openrouter_models() -> Dict[str, Dict[str, Any]]:
    """Fetch model metadata from OpenRouter."""
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if OPENROUTER_API_KEY:
        headers["Authorization"] = f"Bearer {OPENROUTER_API_KEY}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(OPENROUTER_MODELS_URL, headers=headers)
        response.raise_for_status()
        payload = response.json()

    models = payload.get("data") or payload.get("models") or []
    by_id: Dict[str, Dict[str, Any]] = {}
    for item in models:
        model_id = item.get("id") or item.get("name")
        if not model_id:
            continue
        by_id[str(model_id)] = item
    return by_id


def _is_free_model(model_id: str, remote: Dict[str, Any]) -> bool:
    if ":free" in model_id:
        return True
    pricing = remote.get("pricing") or {}
    prompt = pricing.get("prompt")
    completion = pricing.get("completion")
    try:
        return float(prompt or 0) == 0 and float(completion or 0) == 0
    except (TypeError, ValueError):
        return False


def refresh_catalog_from_remote(
    remote_by_id: Dict[str, Dict[str, Any]],
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Update registered_limit for models present in model_catalog.yaml.

    Returns summary dict with updated/skipped/missing lists.
    """
    catalog = _read_yaml(MODEL_CATALOG_PATH)
    models: Dict[str, Any] = catalog.get("models") or {}
    updated: List[str] = []
    skipped: List[str] = []
    missing: List[str] = []

    for model_id, entry in models.items():
        if not isinstance(entry, dict):
            continue
        remote = remote_by_id.get(model_id)
        if not remote:
            missing.append(model_id)
            continue
        context_length = remote.get("context_length")
        if context_length is None:
            skipped.append(model_id)
            continue
        try:
            new_limit = int(context_length)
        except (TypeError, ValueError):
            skipped.append(model_id)
            continue

        old_limit = entry.get("registered_limit")
        entry["registered_limit"] = new_limit
        entry["provenance"] = "openrouter_refresh"
        if _is_free_model(model_id, remote):
            tags = list(entry.get("tags") or [])
            if "free" not in tags:
                tags.append("free")
            entry["tags"] = tags
        if old_limit != new_limit:
            updated.append(model_id)
        else:
            skipped.append(model_id)

    summary = {
        "updated": updated,
        "skipped": skipped,
        "missing": missing,
        "updated_count": len(updated),
        "dry_run": dry_run,
        "refreshed_at": _utcnow(),
    }
    if dry_run:
        return summary

    catalog["models"] = models
    _write_yaml(MODEL_CATALOG_PATH, catalog)
    from .frozen_config import clear_frozen_cache

    clear_frozen_cache()
    meta = {
        "last_refresh_at": summary["refreshed_at"],
        "last_refresh_source": "openrouter",
        "updated_count": len(updated),
    }
    _write_yaml(CATALOG_META_PATH, meta)
    logger.info(
        "Catalog refresh complete: updated=%s missing=%s",
        len(updated),
        len(missing),
    )
    return summary


async def refresh_catalog(*, force: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Fetch OpenRouter models and refresh local catalog YAML."""
    from .frozen_config import get_frozen_snapshot

    ttl = get_frozen_snapshot().arena.catalog.refresh_ttl_hours
    if not force and not dry_run and not is_refresh_due(ttl):
        meta = get_catalog_meta()
        return {
            "skipped": True,
            "reason": "ttl_not_elapsed",
            "last_refresh_at": meta.get("last_refresh_at"),
            "refresh_ttl_hours": ttl,
        }
    remote = await fetch_openrouter_models()
    return refresh_catalog_from_remote(remote, dry_run=dry_run)


def validate_frozen_config() -> Tuple[bool, List[str]]:
    """Validate arena + catalog YAML against frozen schemas."""
    from .frozen_config.schemas import ArenaConfig, ModelCatalog
    from .frozen_config.loader import ARENA_CONFIG_PATH

    issues: List[str] = []
    try:
        ArenaConfig.model_validate(_read_yaml(ARENA_CONFIG_PATH))
    except Exception as exc:
        issues.append(f"arena_config: {exc}")
    try:
        ModelCatalog.model_validate(_read_yaml(MODEL_CATALOG_PATH))
    except Exception as exc:
        issues.append(f"model_catalog: {exc}")
    return len(issues) == 0, issues