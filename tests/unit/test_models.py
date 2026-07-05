"""Unit tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from backend.models import (
    ArenaMode,
    ModelResponse,
    RankingResult,
    AggregateRanking,
    Stage1Result,
    Stage2Result,
    Stage3Result,
    ArenaMetadata,
    ArenaExecution,
)


class TestArenaMode:
    """Tests for ArenaMode enum"""

    def test_council_value(self):
        """COUNCIL should have value 'council'."""
        assert ArenaMode.COUNCIL.value == "council"

    def test_round_robin_value(self):
        """ROUND_ROBIN should have value 'round_robin'."""
        assert ArenaMode.ROUND_ROBIN.value == "round_robin"

    def test_fight_value(self):
        """FIGHT should have value 'fight'."""
        assert ArenaMode.FIGHT.value == "fight"

    def test_all_modes_exist(self):
        """All expected modes should be defined."""
        modes = [m.value for m in ArenaMode]
        assert "council" in modes
        assert "round_robin" in modes
        assert "fight" in modes
        assert "stacks" in modes
        assert "complex_iterative" in modes
        assert "complex_questioning" in modes


class TestModelResponse:
    """Tests for ModelResponse model"""

    def test_create_with_required_fields(self):
        """ModelResponse should require model and response."""
        response = ModelResponse(
            model="openai/gpt-4",
            response="Test response",
        )
        assert response.model == "openai/gpt-4"
        assert response.response == "Test response"
        assert response.role == "answer"  # default

    def test_create_with_all_fields(self):
        """ModelResponse should accept all fields."""
        response = ModelResponse(
            model="openai/gpt-4",
            response="Test response",
            role="critique",
            prompt_preview="Preview...",
            prompt_full="Full prompt",
            est_tokens=100,
            context_tokens=50,
            reasoning_details="Thinking...",
            latency_ms=1500.5,
        )
        assert response.role == "critique"
        assert response.est_tokens == 100
        assert response.latency_ms == 1500.5

    def test_default_values(self):
        """ModelResponse should have sensible defaults."""
        response = ModelResponse(model="test", response="test")
        assert response.role == "answer"
        assert response.est_tokens == 0
        assert response.context_tokens == 0
        assert response.prompt_preview is None

    def test_extra_fields_allowed(self):
        """Extra fields should be allowed (Config.extra='allow')."""
        response = ModelResponse(
            model="test",
            response="test",
            custom_field="custom_value",
        )
        assert response.custom_field == "custom_value"


class TestStage1Result:
    """Tests for Stage1Result model"""

    def test_from_dicts_conversion(self):
        """from_dicts should convert list of dicts to Stage1Result."""
        dicts = [
            {"model": "gpt-4", "response": "Response 1"},
            {"model": "claude", "response": "Response 2"},
        ]
        result = Stage1Result.from_dicts(dicts)
        assert len(result.responses) == 2
        assert result.responses[0].model == "gpt-4"
        assert result.responses[1].model == "claude"

    def test_to_dicts_conversion(self):
        """to_dicts should convert Stage1Result back to list of dicts."""
        result = Stage1Result(responses=[
            ModelResponse(model="gpt-4", response="Response 1"),
            ModelResponse(model="claude", response="Response 2"),
        ])
        dicts = result.to_dicts()
        assert len(dicts) == 2
        assert dicts[0]["model"] == "gpt-4"
        assert dicts[1]["model"] == "claude"

    def test_empty_responses(self):
        """Stage1Result should handle empty responses."""
        result = Stage1Result(responses=[])
        assert len(result.responses) == 0
        assert result.to_dicts() == []


class TestStage2Result:
    """Tests for Stage2Result model"""

    def test_from_dicts_with_mapping(self):
        """from_dicts should handle rankings and label_to_model."""
        rankings = [
            {"model": "gpt-4", "ranking": "1. A, 2. B", "parsed_ranking": ["A", "B"]},
        ]
        label_to_model = {"A": "gpt-4", "B": "claude"}
        result = Stage2Result.from_dicts(rankings, label_to_model)
        assert len(result.rankings) == 1
        assert result.label_to_model == label_to_model

    def test_to_dicts_conversion(self):
        """to_dicts should convert rankings back to list of dicts."""
        result = Stage2Result(
            rankings=[
                RankingResult(
                    model="gpt-4",
                    ranking="1. A, 2. B",
                    parsed_ranking=["A", "B"],
                )
            ],
            label_to_model={"A": "gpt-4", "B": "claude"},
        )
        dicts = result.to_dicts()
        assert len(dicts) == 1
        assert dicts[0]["model"] == "gpt-4"


class TestStage3Result:
    """Tests for Stage3Result model"""

    def test_from_dict_conversion(self):
        """from_dict should convert dict to Stage3Result."""
        data = {
            "model": "gpt-4",
            "response": "Final synthesis",
            "role": "chair_final",
        }
        result = Stage3Result.from_dict(data)
        assert result.model == "gpt-4"
        assert result.response == "Final synthesis"

    def test_to_dict_conversion(self):
        """to_dict should convert Stage3Result back to dict."""
        result = Stage3Result(
            model="gpt-4",
            response="Final synthesis",
        )
        data = result.to_dict()
        assert data["model"] == "gpt-4"
        assert data["response"] == "Final synthesis"
        assert "timestamp" not in data  # excluded

    def test_default_role(self):
        """Stage3Result should default to chair_final role."""
        result = Stage3Result(model="test", response="test")
        assert result.role == "chair_final"


class TestArenaExecution:
    """Tests for ArenaExecution model"""

    def test_to_response_dict(self):
        """to_response_dict should return API-compatible format."""
        execution = ArenaExecution(
            conversation_id="test-123",
            user_query="What is Python?",
            stage1=Stage1Result(responses=[
                ModelResponse(model="gpt-4", response="Python is..."),
            ]),
            stage3=Stage3Result(model="gpt-4", response="Final answer"),
        )
        response = execution.to_response_dict()
        assert "stage1" in response
        assert "stage2" in response
        assert "stage3" in response
        assert "metadata" in response
        assert len(response["stage1"]) == 1

    def test_default_mode(self):
        """ArenaExecution should default to COUNCIL mode."""
        execution = ArenaExecution(
            conversation_id="test",
            user_query="test",
        )
        assert execution.mode == ArenaMode.COUNCIL


class TestPydanticValidation:
    """Tests for Pydantic validation behavior"""

    def test_model_response_requires_model(self):
        """ModelResponse should require model field."""
        with pytest.raises(ValidationError):
            ModelResponse(response="test")

    def test_model_response_requires_response(self):
        """ModelResponse should require response field."""
        with pytest.raises(ValidationError):
            ModelResponse(model="test")

    def test_arena_execution_requires_fields(self):
        """ArenaExecution should require conversation_id and user_query."""
        with pytest.raises(ValidationError):
            ArenaExecution()
