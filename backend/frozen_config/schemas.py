"""Pydantic schemas for arena_config.yaml and model_catalog.yaml."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ContextBudgetConfig(BaseModel):
    safety_margin: float = 0.85
    output_token_allowance: int = 4000
    default_registered_limit: int = 131072
    context_chunk_cap: int = 60


class SummarizerConfig(BaseModel):
    model: Optional[str] = None
    concurrency: Optional[int] = None
    chairman_fallback: bool = True


class CatalogPolicyConfig(BaseModel):
    refresh_ttl_hours: int = 168
    observation_delta_threshold: float = 0.10
    observation_ttl_days: int = 60


class ArenaConfig(BaseModel):
    version: int = 1
    context: ContextBudgetConfig = Field(default_factory=ContextBudgetConfig)
    summarizer: SummarizerConfig = Field(default_factory=SummarizerConfig)
    catalog: CatalogPolicyConfig = Field(default_factory=CatalogPolicyConfig)
    tag_modifiers: Dict[str, float] = Field(default_factory=lambda: {"free": 0.25})


class ModelEntry(BaseModel):
    tags: List[str] = Field(default_factory=list)
    registered_limit: Optional[int] = None
    model_modifier: float = 1.0
    manual_override_limit: Optional[int] = None
    provenance: str = "manual"


class ModelCatalog(BaseModel):
    version: int = 1
    models: Dict[str, ModelEntry] = Field(default_factory=dict)


class FrozenSnapshot(BaseModel):
    """Immutable config snapshot for the current process."""

    model_config = {"frozen": True}

    arena: ArenaConfig
    catalog: ModelCatalog
    generation: int
    arena_config_path: str
    catalog_config_path: str