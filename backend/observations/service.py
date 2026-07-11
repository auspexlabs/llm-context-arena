"""Observation vetting business logic (DEC-018 Phase B)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional

from ..frozen_config import CatalogLimitResolver, get_frozen_snapshot
from ..frozen_config.loader import MODEL_CATALOG_PATH
from .store import AcceptedObservation, ObservationStore, PendingObservation, get_observation_store


def _delta_ratio(registered: int, observed: int) -> float:
    if registered <= 0:
        return 0.0
    return abs(observed - registered) / registered


class ObservationService:
    """Propose, accept, decline, and surface pending limit observations."""

    def __init__(
        self,
        store: Optional[ObservationStore] = None,
        resolver: Optional[CatalogLimitResolver] = None,
    ):
        self.store = store or get_observation_store()
        self.resolver = resolver or CatalogLimitResolver()

    def pending_for_models(self, model_ids: List[str]) -> List[PendingObservation]:
        pending = self.store.list_pending()
        if not model_ids:
            return pending
        wanted = set(model_ids)
        return [p for p in pending if p.model_id in wanted]

    def observation_pending_dicts(self, model_ids: List[str]) -> List[Dict[str, Any]]:
        threshold = get_frozen_snapshot().arena.catalog.observation_delta_threshold
        return [
            {
                **p.to_dict(),
                "exceeds_threshold": p.delta_ratio >= threshold,
            }
            for p in self.pending_for_models(model_ids)
            if p.delta_ratio >= threshold
        ]

    def record_from_turn_steps(
        self,
        steps: Optional[List[Dict[str, Any]]],
        *,
        arena_models: Optional[List[str]] = None,
    ) -> List[PendingObservation]:
        """Record max successful prompt_tokens per model as candidate observations."""
        if not steps:
            return []
        max_tokens: Dict[str, int] = {}
        for step in steps:
            model = step.get("model")
            if not model:
                continue
            if arena_models and model not in arena_models:
                continue
            if step.get("status") == "failed" or step.get("_failed"):
                continue
            prompt_tokens = int(step.get("prompt_tokens") or 0)
            if prompt_tokens <= 0:
                continue
            max_tokens[model] = max(max_tokens.get(model, 0), prompt_tokens)

        created: List[PendingObservation] = []
        threshold = get_frozen_snapshot().arena.catalog.observation_delta_threshold
        for model_id, observed in max_tokens.items():
            registered = self.resolver.registered_limit(model_id)
            delta = _delta_ratio(registered, observed)
            if delta < threshold:
                continue
            obs = self.store.propose(
                model_id=model_id,
                registered_limit=registered,
                observed_limit=observed,
                prompt_tokens=observed,
            )
            if obs:
                created.append(obs)
        return created

    def accept(self, obs_id: int) -> Optional[AcceptedObservation]:
        ttl = get_frozen_snapshot().arena.catalog.observation_ttl_days
        accepted = self.store.accept(obs_id, ttl_days=ttl)
        if accepted:
            self._sync_catalog_observed_limit(accepted)
        return accepted

    def decline(self, obs_id: int) -> bool:
        return self.store.decline(obs_id)

    def effective_limits_report(
        self,
        model_ids: List[str],
        *,
        squad_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows = []
        for model_id in model_ids:
            breakdown = self.resolver.breakdown(model_id)
            accepted = self.store.get_accepted(model_id)
            pending = [p for p in self.store.list_pending() if p.model_id == model_id]
            rows.append(
                {
                    "model_id": model_id,
                    "registered_limit": breakdown.registered_limit,
                    "observed_limit": accepted.observed_limit if accepted else None,
                    "effective_limit": breakdown.effective_limit,
                    "available_tokens": breakdown.available_tokens,
                    "tags": list(breakdown.tags),
                    "tag_modifier": breakdown.tag_modifier,
                    "model_modifier": breakdown.model_modifier,
                    "pending_observations": [p.to_dict() for p in pending],
                    "observation_accepted": accepted.to_dict() if accepted else None,
                }
            )
        return {
            "squad": squad_name,
            "models": rows,
            "pending_count": sum(len(r["pending_observations"]) for r in rows),
        }

    def _sync_catalog_observed_limit(self, accepted: AcceptedObservation) -> None:
        """Persist accepted observed limit to model_catalog.yaml."""
        import yaml

        path = MODEL_CATALOG_PATH
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not isinstance(raw, dict):
            raw = {}
        models = raw.setdefault("models", {})
        entry = models.setdefault(accepted.model_id, {})
        if not isinstance(entry, dict):
            entry = {}
            models[accepted.model_id] = entry
        entry["observed_limit"] = accepted.observed_limit
        entry["observed_accepted_at"] = accepted.accepted_at
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


@lru_cache(maxsize=1)
def get_observation_service() -> ObservationService:
    return ObservationService()