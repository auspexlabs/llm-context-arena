"""Tests for observation store and service (DEC-018 Phase B)."""

import pytest

from backend.frozen_config import clear_frozen_cache
from backend.observations.service import ObservationService
from backend.observations.store import ObservationStore


@pytest.fixture
def obs_store(tmp_path):
    return ObservationStore(tmp_path / "obs.db")


@pytest.fixture
def obs_service(obs_store):
    clear_frozen_cache()
    return ObservationService(store=obs_store)


class TestObservationStore:
    def test_propose_accept_decline(self, obs_store):
        pending = obs_store.propose(
            model_id="test/model:free",
            registered_limit=100000,
            observed_limit=50000,
            prompt_tokens=50000,
        )
        assert pending is not None
        assert pending.delta_ratio == 0.5

        accepted = obs_store.accept(pending.id, ttl_days=60)
        assert accepted is not None
        assert accepted.observed_limit == 50000
        assert obs_store.get_pending(pending.id) is None

    def test_decline_pending(self, obs_store):
        pending = obs_store.propose(
            model_id="test/model",
            registered_limit=100000,
            observed_limit=120000,
        )
        assert obs_store.decline(pending.id) is True
        assert obs_store.get_pending(pending.id) is None


class TestObservationService:
    def test_record_from_turn_steps_upward_discovery(self, obs_service):
        steps = [
            {"model": "m/a", "prompt_tokens": 200000},
            {"model": "m/a", "prompt_tokens": 150000},
        ]
        created = obs_service.record_from_turn_steps(steps, arena_models=["m/a"])
        assert len(created) == 1
        pending = obs_service.pending_for_models(["m/a"])
        assert len(pending) == 1

    def test_short_prompt_does_not_create_spurious_observation(self, obs_service):
        steps = [{"model": "m/a", "prompt_tokens": 10000}]
        created = obs_service.record_from_turn_steps(steps, arena_models=["m/a"])
        assert created == []

    def test_context_failure_can_propose_downward(self, obs_service):
        steps = [
            {
                "model": "m/a",
                "prompt_tokens": 50000,
                "status": "failed",
                "message": "context length exceeded",
            }
        ]
        created = obs_service.record_from_turn_steps(steps, arena_models=["m/a"])
        assert len(created) == 1
        assert created[0].observed_limit == 50000

    def test_observation_pending_dicts_flags_threshold(self, obs_service):
        obs_service.store.propose(
            model_id="m/b",
            registered_limit=100000,
            observed_limit=50000,
        )
        obs_service.store.propose(
            model_id="m/c",
            registered_limit=100000,
            observed_limit=95000,
        )
        pending = obs_service.observation_pending_dicts(["m/b", "m/c"])
        by_model = {p["model_id"]: p for p in pending}
        assert by_model["m/b"]["exceeds_threshold"] is True
        assert by_model["m/c"]["exceeds_threshold"] is False

    def test_expired_accepted_not_returned(self, obs_store):
        from datetime import datetime, timedelta, timezone

        pending = obs_store.propose(
            model_id="m/expired",
            registered_limit=100000,
            observed_limit=50000,
        )
        obs_store.accept(pending.id, ttl_days=60)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with obs_store._connect() as conn:
            conn.execute(
                "UPDATE observation_accepted SET expires_at = ? WHERE model_id = ?",
                (past, "m/expired"),
            )
        assert obs_store.get_accepted("m/expired") is None
        assert "m/expired" not in obs_store.accepted_limits_map()