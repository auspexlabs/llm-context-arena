"""Observation vetting business logic (DEC-018 Phase B)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional

from ..frozen_config import CatalogLimitResolver, clear_frozen_cache, get_frozen_snapshot
from ..frozen_config.loader import MODEL_CATALOG_PATH
from .store import AcceptedObservation, ObservationStore, PendingObservation, get_observation_store


def _upward_delta_ratio(registered: int, observed: int) -> float:
    """Positive delta only — runtime max exceeded registered (upward discovery)."""
    if registered <= 0 or observed <= registered:
        return 0.0
    return (observed - registered) / registered


def _is_context_limit_failure(step: Dict[str, Any]) -> bool:
    """Heuristic for context-window failures (downward discovery)."""
    if step.get("status") != "failed" and not step.get("_failed"):
        return False
    haystack = " ".join(
        str(step.get(key) or "")
        for key in ("message", "error_message", "raw", "status")
    ).lower()
    return any(
        token in haystack
        for token in (
            "context length",
            "context window",
            "maximum context",
            "context exceeded",
            "too many tokens",
            "token limit",
        )
    )


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
        max_success_tokens: Dict[str, int] = {}
        failure_tokens: Dict[str, int] = {}
        for step in steps:
            model = step.get("model")
            if not model:
                continue
            if arena_models and model not in arena_models:
                continue
            prompt_tokens = int(step.get("prompt_tokens") or 0)
            if step.get("status") == "failed" or step.get("_failed"):
                if prompt_tokens > 0 and _is_context_limit_failure(step):
                    failure_tokens[model] = max(failure_tokens.get(model, 0), prompt_tokens)
                continue
            if prompt_tokens <= 0:
                continue
            max_success_tokens[model] = max(max_success_tokens.get(model, 0), prompt_tokens)

        created: List[PendingObservation] = []
        threshold = get_frozen_snapshot().arena.catalog.observation_delta_threshold
        candidate_models = set(max_success_tokens) | set(failure_tokens)
        for model_id in candidate_models:
            registered = self.resolver.registered_limit(model_id)
            observed = max_success_tokens.get(model_id, 0)
            failure_observed = failure_tokens.get(model_id, 0)

            # Upward: runtime max prompt_tokens exceeded registered catalog claim.
            if observed > registered and _upward_delta_ratio(registered, observed) >= threshold:
                obs = self.store.propose(
                    model_id=model_id,
                    registered_limit=registered,
                    observed_limit=observed,
                    prompt_tokens=observed,
                )
                if obs:
                    created.append(obs)
                continue

            # Downward: only from context-limit failures, not short successful prompts.
            if failure_observed > 0:
                downward_delta = (
                    (registered - failure_observed) / registered if registered > 0 else 0.0
                )
                if downward_delta >= threshold:
                    obs = self.store.propose(
                        model_id=model_id,
                        registered_limit=registered,
                        observed_limit=failure_observed,
                        prompt_tokens=failure_observed,
                        failure_reason="context_limit_failure",
                    )
                    if obs:
                        created.append(obs)
        return created

    def accept(self, obs_id: int) -> Optional[AcceptedObservation]:
        ttl = get_frozen_snapshot().arena.catalog.observation_ttl_days
        accepted = self.store.accept(obs_id, ttl_days=ttl)
        if accepted:
            self._sync_catalog_observed_limit(accepted)
            self.resolver.invalidate_accepted_cache()
        return accepted

    def decline(self, obs_id: int) -> bool:
        return self.store.decline(obs_id)

    def sweep_expired_observations(self) -> Dict[str, Any]:
        """Archive expired accepted limits and clear stale catalog observed_limit entries."""
        expired = self.store.archive_expired_accepted()
        if not expired:
            return {"archived_count": 0, "models": [], "reverify_required": []}

        reverify_required: List[str] = []
        for accepted in expired:
            self._clear_catalog_observed_limit(accepted.model_id)
            reverify_required.append(accepted.model_id)

        self.resolver.invalidate_accepted_cache()
        return {
            "archived_count": len(expired),
            "models": [a.model_id for a in expired],
            "reverify_required": reverify_required,
            "archived": [a.to_dict() for a in expired],
        }

    def effective_limits_report(
        self,
        model_ids: List[str],
        *,
        squad_name: Optional[str] = None,
        sweep_expired: bool = True,
    ) -> Dict[str, Any]:
        sweep_result: Optional[Dict[str, Any]] = None
        if sweep_expired:
            sweep_result = self.sweep_expired_observations()

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
        report: Dict[str, Any] = {
            "squad": squad_name,
            "models": rows,
            "pending_count": sum(len(r["pending_observations"]) for r in rows),
        }
        if sweep_result and sweep_result.get("archived_count"):
            report["reverify_required"] = sweep_result.get("reverify_required") or []
            report["expired_sweep"] = {
                "archived_count": sweep_result["archived_count"],
                "models": sweep_result.get("models") or [],
            }
        return report

    def _clear_catalog_observed_limit(self, model_id: str) -> None:
        """Remove stale observed_limit from catalog after TTL expiry."""
        import yaml

        path = MODEL_CATALOG_PATH
        if not path.is_file():
            return
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        models = raw.get("models")
        if not isinstance(models, dict):
            return
        entry = models.get(model_id)
        if not isinstance(entry, dict):
            return
        changed = False
        for key in ("observed_limit", "observed_accepted_at"):
            if key in entry:
                entry.pop(key, None)
                changed = True
        if changed:
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            clear_frozen_cache()

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
        clear_frozen_cache()


@lru_cache(maxsize=1)
def get_observation_service() -> ObservationService:
    return ObservationService()