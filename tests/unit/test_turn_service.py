"""Tests for agent turn step advancement."""

import asyncio
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
    async def test_create_turn_rejects_concurrent_context_preparation(
        self, turn_env, monkeypatch
    ):
        service, _, _ = turn_env
        started = asyncio.Event()
        release = asyncio.Event()

        class FakeDirectives:
            reset = False
            iterations_override = None

            def dict(self):
                return {}

        fake_ctx = type(
            "Ctx",
            (),
            {
                "clean_query": "q",
                "base_prompt": "p",
                "per_model_prompts": {},
                "context_token_map": {},
                "context_block": "",
                "context_sources": [],
                "directives": FakeDirectives(),
                "warnings": [],
                "context_from_last_chair": False,
            },
        )()

        async def prepare_context(_self, **_kwargs):
            started.set()
            await release.wait()
            return fake_ctx

        monkeypatch.setattr(
            "backend.turn_service.get_context_engine",
            lambda: type("Engine", (), {"prepare_context": prepare_context})(),
        )

        first = asyncio.create_task(
            service.create_turn(
                "conv-1",
                "q",
                settings={"arena_models": ["m1"], "chairman_model": "chair"},
            )
        )
        await started.wait()
        with pytest.raises(ValueError, match="already has a turn being created"):
            await service.create_turn(
                "conv-1",
                "q2",
                settings={"arena_models": ["m1"], "chairman_model": "chair"},
            )
        release.set()
        assert (await first).status == TurnStatus.PENDING

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
                return_value=[{
                    "model": "m1", "response": "a1", "role": "answer",
                    "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                    "cost_usd": 0.0,
                }]
            ),
        )
        monkeypatch.setattr(
            "backend.turn_service.stage2_collect_rankings",
            AsyncMock(
                return_value=(
                    [{
                        "model": "m1", "ranking": "1. Response A", "parsed_ranking": ["A"],
                        "prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30,
                        "cost_usd": 0.0,
                    }],
                    {"Response A": "m1"},
                    [],
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
                return_value={
                    "model": "chair", "response": "final", "role": "chair_final",
                    "prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45,
                    "cost_usd": 0.01,
                }
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
        assert turn.metadata["cost"] == {
            "turn_cost_usd": 0.01,
            "prompt_tokens": 60,
            "completion_tokens": 30,
            "total_tokens": 90,
            "calls": 3,
        }
        assert turn.metadata["execution_quality"]["acceptable"] is True
        assert turn.metadata["execution_trace"]["version"] == 1
        assert turn.metadata["execution_trace"]["summary"]["participant_succeeded"] == 1
        conv = storage.get_conversation("conv-1")
        assert conv["messages"][-1]["role"] == "assistant"
        assert conv["messages"][-1]["metadata"]["execution_trace"]["version"] == 1

    @pytest.mark.asyncio
    async def test_stepwise_failures_are_persisted_and_mark_quality_degraded(
        self, turn_env, monkeypatch
    ):
        service, storage, store = turn_env
        from backend.models import TurnCheckpoint, TurnRecord

        store.save(
            TurnRecord(
                turn_id="degraded",
                conversation_id="conv-1",
                user_query="q",
                user_query_raw="q",
                checkpoint=TurnCheckpoint(
                    augmented_content="p",
                    arena_models=["m1", "m2", "m3", "m4"],
                    chairman_model="chair",
                    directives={},
                ),
            )
        )

        async def fake_stage1(*_args, model_failures=None, **_kwargs):
            model_failures.extend(
                [
                    {"model": "m3", "status": 429, "message": "limited", "stage": "stage1"},
                    {"model": "m4", "status": 429, "message": "limited", "stage": "stage1"},
                ]
            )
            return [
                {"model": "m1", "response": "a1", "role": "answer"},
                {"model": "m2", "response": "a2", "role": "answer"},
            ]

        async def fake_stage2(*_args, model_failures=None, **_kwargs):
            model_failures.extend(
                [
                    {"model": "m3", "status": 429, "message": "limited", "stage": "stage2"},
                    {"model": "m4", "status": 429, "message": "limited", "stage": "stage2"},
                ]
            )
            return (
                [
                    {"model": "m1", "ranking": "1. Response A"},
                    {"model": "m2", "ranking": "1. Response A"},
                ],
                {"Response A": "m1", "Response B": "m2"},
                [],
            )

        monkeypatch.setattr("backend.turn_service.stage1_collect_responses", fake_stage1)
        monkeypatch.setattr("backend.turn_service.stage2_collect_rankings", fake_stage2)
        monkeypatch.setattr(
            "backend.turn_service.calculate_aggregate_rankings", lambda *_: []
        )
        monkeypatch.setattr(
            "backend.turn_service.stage3_synthesize_final",
            AsyncMock(return_value={"model": "chair", "response": "final"}),
        )

        await service.advance_turn("conv-1", "degraded")
        await service.advance_turn("conv-1", "degraded")
        turn = await service.advance_turn("conv-1", "degraded")

        assert len(turn.metadata["model_failures"]) == 4
        assert turn.metadata["execution_quality"]["acceptable"] is False
        assert turn.metadata["execution_quality"]["severity"] == "degraded"
        stored = storage.get_conversation("conv-1")["messages"][-1]
        assert len(stored["metadata"]["model_failures"]) == 4
        assert stored["metadata"]["execution_quality"]["acceptable"] is False
        assert stored["metadata"]["execution_trace"]["summary"]["participant_succeeded"] == 2
        assert stored["metadata"]["execution_trace"]["summary"]["participant_failed"] == 2
