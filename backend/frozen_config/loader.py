"""Load and freeze arena + catalog YAML once per process."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

from .schemas import ArenaConfig, FrozenSnapshot, ModelCatalog

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ARENA_CONFIG_PATH = _PROJECT_ROOT / "data" / "arena_config.yaml"
MODEL_CATALOG_PATH = _PROJECT_ROOT / "data" / "model_catalog.yaml"

_GENERATION = 0


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        logger.info("Config file missing, using defaults: %s", path)
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


@lru_cache(maxsize=1)
def get_frozen_snapshot(
    arena_path: str = str(ARENA_CONFIG_PATH),
    catalog_path: str = str(MODEL_CATALOG_PATH),
) -> FrozenSnapshot:
    """Return the immutable config snapshot for this PID (FREEZE semantics)."""
    global _GENERATION
    _GENERATION += 1

    arena = ArenaConfig.model_validate(_read_yaml(Path(arena_path)))
    catalog = ModelCatalog.model_validate(_read_yaml(Path(catalog_path)))
    snapshot = FrozenSnapshot(
        arena=arena,
        catalog=catalog,
        generation=_GENERATION,
        arena_config_path=arena_path,
        catalog_config_path=catalog_path,
    )
    logger.info(
        "Frozen config loaded (generation=%s, models=%s)",
        snapshot.generation,
        len(snapshot.catalog.models),
    )
    return snapshot


def clear_frozen_cache() -> None:
    """Clear cached snapshot and dependent budget allocator cache."""
    get_frozen_snapshot.cache_clear()
    try:
        from ..dependencies import get_budget_allocator

        get_budget_allocator.cache_clear()
    except Exception:
        pass