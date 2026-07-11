"""Unit tests for DEC-018 frozen config loader."""

import pytest

from backend.dependencies import clear_caches, get_budget_allocator
from backend.frozen_config import clear_frozen_cache, get_frozen_snapshot
from backend.frozen_config.catalog import CatalogLimitResolver


@pytest.fixture(autouse=True)
def _reset_caches():
    clear_frozen_cache()
    clear_caches()
    yield
    clear_frozen_cache()
    clear_caches()


class TestFrozenSnapshot:
    def test_loads_seed_yaml(self):
        snap = get_frozen_snapshot()
        assert snap.generation >= 1
        assert snap.arena.context.safety_margin == 0.85
        assert snap.arena.tag_modifiers["free"] == 0.25
        assert "meta-llama/llama-3.3-70b-instruct:free" in snap.catalog.models

    def test_freeze_is_immutable(self):
        snap1 = get_frozen_snapshot()
        snap2 = get_frozen_snapshot()
        assert snap1 is snap2
        assert snap1.generation == snap2.generation

    def test_cache_clear_increments_generation(self):
        snap1 = get_frozen_snapshot()
        clear_frozen_cache()
        snap2 = get_frozen_snapshot()
        assert snap2.generation > snap1.generation


class TestCatalogLimitResolver:
    def test_free_tag_reduces_effective_limit(self):
        resolver = CatalogLimitResolver()
        breakdown = resolver.breakdown("cohere/north-mini-code:free")
        assert breakdown.registered_limit == 256000
        assert breakdown.tags == ("free",)
        assert breakdown.tag_modifier == 0.25
        assert breakdown.effective_limit == 64000

    def test_available_tokens_applies_margin_and_output(self):
        resolver = CatalogLimitResolver()
        breakdown = resolver.breakdown("cohere/north-mini-code:free")
        # 64000 * 0.85 - 4000 = 50400
        assert breakdown.available_tokens == 50400

    def test_auto_detect_free_suffix(self):
        resolver = CatalogLimitResolver()
        breakdown = resolver.breakdown("example/model:free")
        assert "free" in breakdown.tags
        assert breakdown.tag_modifier == 0.25

    def test_budget_allocator_uses_catalog(self):
        allocator = get_budget_allocator()
        budget = allocator.calculate_budget("cohere/north-mini-code:free")
        assert budget.context_limit == 64000
        assert budget.available_tokens == 50400