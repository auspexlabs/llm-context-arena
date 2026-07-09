"""Tests for agent turn step advancement."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.models import TurnStatus
from backend.storage_service import StorageService
from backend.turn_service import TurnService
from backend.turn_store import TurnStore


@pytest.fixture
def turn_env(tmp_path):
    data_dir = tmp_path / "conversations"
    data_dir.mkdir(parents=True)
    storage = StorageService(data_dir=str(data_dir))
    conv = storage.create_conversation("conv-1", mode="council")
    store = TurnStore(base_dir=str(data_dir))
    return TurnService(storage, store), storage, store


class TestTurnService:
    @pytest.mark.asyncio
    async def test_create_turn_persists_checkpoint(self, turn_env, monkeypatch):
        service, storage, store = turn_env

        class FakeDirectives:
            reset = False
            iterations_override = None

            def dict(self):
                return {"reset": False}

        fake_ctx = type(
            "Ctx",
            (),
            {
                "clean_query": "auth?",
                "base_prompt": "augmented",
                "per_model_prompts": {},
                "context_token_map": {},
                "context_block": "",
                "context_sources": [],
                "directives": FakeDirectives(),
                "warnings": [],
                "context_from_last_chair": False,
            },
        )()

        monkeypatch.setattr(
            "backend.turn_service.get_context_engine",
            lambda: type(
                "Engine",
                (),
                {"prepare_context": AsyncMock(return_value=fake_ctx)},
            )(),
        )

        turn = await service.create_turn(
            "conv-1",
            "auth?",
            settings={"arena_models": ["m1"], "chairman_model": "chair"},
            agent_id="agent-x",
        )

        assert turn.status == TurnStatus.PENDING
        assert turn.step_index == 0
        assert turn.agent_id == "agent-x"
        assert turn.checkpoint.augmented_content == "augmented"
        conv = storage.get_conversation("conv-1")
        assert conv["messages"][-1]["content"] == "auth?"

    @pytest.mark.asyncio
    async def test_advance_council_steps(self, turn_env, monkeypatch):
        service, storage, store = turn_env

        class FakeDirectives:
            def dict(self):
                return {}

        from backend.models import TurnCheckpoint, TurnRecord

        turn = TurnRecord(
            turn_id="t1",
            conversation_id="conv-1",
            user_query="q",
            user_query_raw="q",
            checkpoint=TurnCheckpoint(
                augmented_content="p",
                arena_models=["m1"],
                chairman_model="chair",
                directives={},
            ),
        )
        store.save(turn)

        monkeypatch.setattr(
            "backend.turn_service.stage1_collect_responses",
            AsyncMock(
                return_value=[{"model": "m1", "response": "a1", "role": "answer"}]
            ),
        )
        monkeypatch.setattr(
            "backend.turn_service.stage2_collect_rankings",
            AsyncMock(
                return_value=(
                    [{"model": "m1", "ranking": "1. Response A", "parsed_ranking": ["A"]}],
                    {"Response A": "m1"},
                )
            ),
        )
        monkeypatch.setattr(
            "backend.turn_service.calculate_aggregate_rankings",
            lambda *_: [{"model": "m1", "avg_rank": 1.0, "votes": 1}],
        )
        monkeypatch.setattr(
            "backend.turn_service.stage3_synthesize_final",
            AsyncMock(
                return_value={"model": "chair", "response": "final", "role": "chair_final"}
            ),
        )

        turn = await service.advance_turn("conv-1", "t1")
        assert turn.status == TurnStatus.STAGE1_COMPLETE
        assert len(turn.stage1) == 1

        turn = await service.advance_turn("conv-1", "t1")
        assert turn.status == TurnStatus.STAGE2_COMPLETE
        assert turn.metadata["aggregate_rankings"]

        turn = await service.advance_turn("conv-1", "t1")
        assert turn.status == TurnStatus.COMPLETE
        assert turn.stage3["response"] == "final"
        conv = storage.get_conversation("conv-1")
        assert conv["messages"][-1]["role"] == "assistant"