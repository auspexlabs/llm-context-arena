"""Dependency injection providers for LLM Context Arena.

Provides singleton instances and factory functions for FastAPI's Depends().
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from .budget import BudgetAllocator
from .config import (
    ARENA_MODELS,
    ARENA_SQUAD,
    CHAIRMAN_MODEL,
    CONTEXT_SAFETY_MARGIN,
    MODEL_CONTEXT_LIMITS,
    OUTPUT_TOKEN_ALLOWANCE,
)
from .squad_presets import list_squad_summaries, load_squad_preset
from .openrouter import query_model
from .rag_lmstudio_provider import LMStudioRAGProvider, get_rag_provider
from .rag_provider import RAGProvider
from .storage_service import StorageService

SETTINGS_PATH = Path("data/config.json")
_PERSISTED_SETTINGS_KEYS = frozenset(
    {"arena_models", "chairman_model", "arena_squad", "theme", "repo_root"}
)


# -----------------------------------------------------------------------------
# Settings Functions (moved from main.py)
# -----------------------------------------------------------------------------


def load_runtime_settings() -> Dict[str, Any]:
    """Load persisted settings merged with defaults."""
    defaults = {
        "arena_models": ARENA_MODELS,
        "chairman_model": CHAIRMAN_MODEL,
        "arena_squad": ARENA_SQUAD,
        "available_squads": list_squad_summaries(),
        "theme": "light",
        "repo_root": ".",
    }
    if not SETTINGS_PATH.exists():
        return defaults
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        # Migrate legacy council_models key to arena_models
        if "council_models" in data and "arena_models" not in data:
            data["arena_models"] = data.pop("council_models")
        defaults.update(
            {
                k: v
                for k, v in data.items()
                if v is not None and k in _PERSISTED_SETTINGS_KEYS
            }
        )
    except Exception:
        pass
    defaults["available_squads"] = list_squad_summaries()
    return defaults


def save_runtime_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Save runtime settings to disk."""
    current = load_runtime_settings()
    for k, v in payload.items():
        if k in _PERSISTED_SETTINGS_KEYS:
            current[k] = v
    persisted = {k: current[k] for k in _PERSISTED_SETTINGS_KEYS if k in current}
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(persisted, indent=2), encoding="utf-8")
    current.update(persisted)
    current["available_squads"] = list_squad_summaries()
    return current


def apply_squad_preset(name: str) -> Dict[str, Any]:
    """Load a squad JSON preset and persist arena_models + chairman."""
    preset = load_squad_preset(name)
    return save_runtime_settings(
        {
            "arena_models": preset["arena_models"],
            "chairman_model": preset["chairman_model"],
            "arena_squad": preset["name"],
        }
    )


# -----------------------------------------------------------------------------
# Dependency Providers
# -----------------------------------------------------------------------------


@lru_cache()
def get_storage_service() -> StorageService:
    """Get singleton storage service instance."""
    return StorageService()


@lru_cache()
def get_budget_allocator() -> BudgetAllocator:
    """Get singleton budget allocator instance."""
    return BudgetAllocator(
        context_limits=MODEL_CONTEXT_LIMITS,
        safety_margin=CONTEXT_SAFETY_MARGIN,
        output_allowance=OUTPUT_TOKEN_ALLOWANCE,
    )


def get_query_model_fn():
    """Get the query model function for dependency injection."""
    return query_model


def get_settings() -> Dict[str, Any]:
    """Get current runtime settings (not cached - settings can change)."""
    return load_runtime_settings()


@lru_cache()
def get_rag_provider_dep() -> RAGProvider:
    """Get singleton RAG provider (LM Studio CodeRAG)."""
    return get_rag_provider()


def get_context_engine(rag_provider: RAGProvider | None = None):
    """Build ContextEngine with injected RAG provider (default: singleton)."""
    from .context_engine import ContextEngine

    return ContextEngine(
        query_model_fn=query_model,
        rag_provider=rag_provider or get_rag_provider_dep(),
        budget_allocator=get_budget_allocator(),
    )


# -----------------------------------------------------------------------------
# Testing Support
# -----------------------------------------------------------------------------


def clear_caches():
    """Clear all cached dependencies (useful for testing)."""
    get_storage_service.cache_clear()
    get_budget_allocator.cache_clear()
    get_rag_provider_dep.cache_clear()
