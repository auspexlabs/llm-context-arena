"""Unit tests for budget allocation."""

import pytest

from backend.budget import BudgetAllocator, ModelBudget
from backend.config import DEFAULT_MODEL_CONTEXT_LIMIT


class TestBudgetAllocator:
    """Tests for BudgetAllocator"""

    @pytest.fixture
    def allocator(self):
        """Return a BudgetAllocator with test context limits."""
        return BudgetAllocator(
            context_limits={
                "model-a": 100000,
                "model-b": 50000,
                "model-c": 200000,
            },
            safety_margin=0.85,
            output_allowance=4000,
        )

    def test_calculate_budget_known_model(self, allocator):
        """Known model should get calculated budget."""
        budget = allocator.calculate_budget("model-a")
        assert budget.model_id == "model-a"
        assert budget.context_limit == 100000
        assert budget.safety_margin == 0.85
        # 100000 * 0.85 - 4000 = 81000
        assert budget.available_tokens == 81000

    def test_calculate_budget_unknown_model(self, allocator):
        """Unknown model should fall back to DEFAULT_MODEL_CONTEXT_LIMIT."""
        budget = allocator.calculate_budget("unknown-model")
        assert budget.model_id == "unknown-model"
        assert budget.context_limit == DEFAULT_MODEL_CONTEXT_LIMIT
        expected = int(DEFAULT_MODEL_CONTEXT_LIMIT * 0.85) - 4000
        assert budget.available_tokens == expected

    def test_calculate_budget_with_override(self, allocator):
        """Budget override should cap available tokens."""
        budget = allocator.calculate_budget("model-a", budget_override=10000)
        # min(81000, 10000) = 10000
        assert budget.available_tokens == 10000

    def test_calculate_budget_override_larger_than_natural(self, allocator):
        """Large override should not exceed natural budget."""
        budget = allocator.calculate_budget("model-a", budget_override=999999)
        # Should be capped at natural budget: 81000
        assert budget.available_tokens == 81000

    def test_calculate_all_budgets(self, allocator):
        """Should calculate budgets for all specified models."""
        budgets = allocator.calculate_all_budgets(["model-a", "model-b"])
        assert len(budgets) == 2
        assert "model-a" in budgets
        assert "model-b" in budgets
        assert budgets["model-a"].available_tokens == 81000
        # 50000 * 0.85 - 4000 = 38500
        assert budgets["model-b"].available_tokens == 38500

    def test_get_minimum_budget(self, allocator):
        """Should return the smallest budget across models."""
        min_budget = allocator.get_minimum_budget(["model-a", "model-b", "model-c"])
        # model-b has smallest: 38500
        assert min_budget == 38500

    def test_get_minimum_budget_single_model(self, allocator):
        """Single model should return its own budget."""
        min_budget = allocator.get_minimum_budget(["model-a"])
        assert min_budget == 81000

    def test_safety_margin_applied(self):
        """Safety margin should be applied correctly."""
        allocator = BudgetAllocator(
            context_limits={"test": 100000},
            safety_margin=0.5,  # 50%
            output_allowance=0,
        )
        budget = allocator.calculate_budget("test")
        assert budget.available_tokens == 50000

    def test_output_allowance_deducted(self):
        """Output allowance should be deducted."""
        allocator = BudgetAllocator(
            context_limits={"test": 100000},
            safety_margin=1.0,  # No safety margin
            output_allowance=10000,
        )
        budget = allocator.calculate_budget("test")
        assert budget.available_tokens == 90000

    def test_negative_budget_clamped(self):
        """Negative budget should be clamped to zero."""
        allocator = BudgetAllocator(
            context_limits={"tiny": 1000},
            safety_margin=0.85,
            output_allowance=50000,  # Much larger than context
        )
        budget = allocator.calculate_budget("tiny")
        assert budget.available_tokens == 0


class TestModelBudget:
    """Tests for ModelBudget dataclass"""

    def test_model_budget_creation(self):
        """ModelBudget should store all fields."""
        budget = ModelBudget(
            model_id="test-model",
            context_limit=100000,
            safety_margin=0.85,
            available_tokens=81000,
        )
        assert budget.model_id == "test-model"
        assert budget.context_limit == 100000
        assert budget.safety_margin == 0.85
        assert budget.available_tokens == 81000
        assert budget.requires_summarization is False

    def test_model_budget_with_summarization(self):
        """ModelBudget can indicate summarization requirement."""
        budget = ModelBudget(
            model_id="test-model",
            context_limit=100000,
            safety_margin=0.85,
            available_tokens=81000,
            requires_summarization=True,
            target_context_tokens=50000,
        )
        assert budget.requires_summarization is True
        assert budget.target_context_tokens == 50000
