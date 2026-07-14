"""Tests for turn sidecar persistence."""

import pytest

from backend.models import TurnCheckpoint, TurnRecord, TurnStatus
from backend.turn_store import TurnCreationInProgress, TurnStore


def _sample_turn(conversation_id: str = "conv-1", turn_id: str = "turn-1") -> TurnRecord:
    return TurnRecord(
        turn_id=turn_id,
        conversation_id=conversation_id,
        user_query="What is auth?",
        user_query_raw="What is auth?",
        checkpoint=TurnCheckpoint(
            augmented_content="prompt",
            arena_models=["a"],
            chairman_model="chair",
        ),
    )


class TestTurnStore:
    def test_save_and_get(self, tmp_path):
        store = TurnStore(base_dir=str(tmp_path))
        turn = _sample_turn()
        store.save(turn)
        loaded = store.get("conv-1", "turn-1")
        assert loaded is not None
        assert loaded.user_query == "What is auth?"

    def test_active_turn_excludes_complete(self, tmp_path):
        store = TurnStore(base_dir=str(tmp_path))
        done = _sample_turn(turn_id="done")
        done.status = TurnStatus.COMPLETE
        store.save(done)

        pending = _sample_turn(turn_id="pending")
        store.save(pending)

        active = store.active_turn("conv-1")
        assert active is not None
        assert active.turn_id == "pending"

    def test_list_for_conversation(self, tmp_path):
        store = TurnStore(base_dir=str(tmp_path))
        store.save(_sample_turn(turn_id="a"))
        store.save(_sample_turn(turn_id="b"))
        turns = store.list_for_conversation("conv-1")
        assert {t.turn_id for t in turns} == {"a", "b"}

    def test_creation_guard_rejects_concurrent_creator(self, tmp_path):
        store = TurnStore(base_dir=str(tmp_path))
        with store.creation_guard("conv-1"):
            with pytest.raises(TurnCreationInProgress):
                with store.creation_guard("conv-1"):
                    pass
