"""Effective model limits from frozen catalog (DEC-018)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .loader import get_frozen_snapshot
from .schemas import ArenaConfig, FrozenSnapshot, ModelCatalog, ModelEntry


def _observation_store():
    from ..observations.store import get_observation_store

    return get_observation_store()


@dataclass(frozen=True)
class LimitBreakdown:
    model_id: str
    registered_limit: int
    effective_limit: int
    available_tokens: int
    tags: tuple[str, ...]
    tag_modifier: float
    model_modifier: float
    safety_margin: float
    output_allowance: int
    budget_override: Optional[int] = None


def _infer_tags(model_id: str, entry: Optional[ModelEntry]) -> List[str]:
    tags = list(entry.tags) if entry else []
    if ":free" in model_id and "free" not in tags:
        tags.append("free")
    return tags


def _combined_tag_modifier(tags: List[str], arena: ArenaConfig) -> float:
    modifier = 1.0
    for tag in tags:
        modifier *= arena.tag_modifiers.get(tag, 1.0)
    return modifier


class CatalogLimitResolver:
    """Resolve registered and effective limits from the frozen catalog."""

    def __init__(self, snapshot: Optional[FrozenSnapshot] = None):
        self._snapshot = snapshot or get_frozen_snapshot()

    @property
    def arena(self) -> ArenaConfig:
        return self._snapshot.arena

    @property
    def catalog(self) -> ModelCatalog:
        return self._snapshot.catalog

    def registered_limit(self, model_id: str) -> int:
        entry = self.catalog.models.get(model_id)
        if entry and entry.manual_override_limit is not None:
            return entry.manual_override_limit
        if entry and entry.registered_limit is not None:
            return entry.registered_limit

        from ..config import DEFAULT_MODEL_CONTEXT_LIMIT, MODEL_CONTEXT_LIMITS

        return MODEL_CONTEXT_LIMITS.get(model_id) or self.arena.context.default_registered_limit

    def planning_base_limit(self, model_id: str) -> int:
        """Observed limit wins after user acceptance; else registered baseline."""
        accepted = _observation_store().get_accepted(model_id)
        if accepted:
            return accepted.observed_limit
        entry = self.catalog.models.get(model_id)
        if entry and entry.observed_limit is not None:
            return entry.observed_limit
        return self.registered_limit(model_id)

    def breakdown(
        self,
        model_id: str,
        budget_override: Optional[int] = None,
    ) -> LimitBreakdown:
        entry = self.catalog.models.get(model_id)
        tags = _infer_tags(model_id, entry)
        registered = self.registered_limit(model_id)
        base = self.planning_base_limit(model_id)
        tag_mod = _combined_tag_modifier(tags, self.arena)
        model_mod = entry.model_modifier if entry else 1.0
        effective = max(1, int(base * tag_mod * model_mod))
        margin = self.arena.context.safety_margin
        output = self.arena.context.output_token_allowance
        available = int(effective * margin) - output
        if budget_override is not None:
            available = min(available, budget_override)
        return LimitBreakdown(
            model_id=model_id,
            registered_limit=registered,
            effective_limit=effective,
            available_tokens=max(0, available),
            tags=tuple(tags),
            tag_modifier=tag_mod,
            model_modifier=model_mod,
            safety_margin=margin,
            output_allowance=output,
            budget_override=budget_override,
        )

    def effective_limit(self, model_id: str) -> int:
        return self.breakdown(model_id).effective_limit

    def available_tokens(
        self,
        model_id: str,
        budget_override: Optional[int] = None,
    ) -> int:
        return self.breakdown(model_id, budget_override=budget_override).available_tokens

    def build_context_limits(self, model_ids: Optional[List[str]] = None) -> Dict[str, int]:
        """Legacy dict for BudgetAllocator — effective limits (pre margin/output)."""
        if model_ids:
            return {mid: self.effective_limit(mid) for mid in model_ids}
        limits = {
            mid: self.effective_limit(mid) for mid in self.catalog.models.keys()
        }
        from ..config import MODEL_CONTEXT_LIMITS

        for mid in MODEL_CONTEXT_LIMITS:
            limits.setdefault(mid, self.effective_limit(mid))
        return limits