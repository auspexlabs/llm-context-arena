"""Unit tests for ContextEngine (directive → RAG → budget path)."""

import pytest

from backend.context_engine import ContextEngine, get_last_chair_context, prepare_arena_context
from backend.rag_provider import NullRAGProvider


class RecordingRAGProvider(NullRAGProvider):
    """Null provider that records get_context invocations."""

    def __init__(self, context_block: str = "# ctx\n\ncode", sources=None):
        super().__init__()
        self.context_block = context_block
        self.sources = sources or [{"source": "file.py", "content": "code", "source_type": "rag"}]
        self.calls: list = []

    def get_context(self, conversation_id, query, manual_items=None, allow_rag=True):
        self.calls.append(
            {
                "conversation_id": conversation_id,
                "query": query,
                "manual_items": manual_items,
                "allow_rag": allow_rag,
            }
        )
        if manual_items:
            block = "\n\n".join(item.get("content", "") for item in manual_items)
            return block, list(manual_items)
        if not allow_rag:
            return "", []
        return self.context_block, list(self.sources)


async def _noop_query_model(*_args, **_kwargs):
    return {"content": "summary"}


@pytest.fixture
def engine():
    return ContextEngine(_noop_query_model, rag_provider=RecordingRAGProvider())


class TestGetLastChairContext:
    def test_returns_latest_chair_response(self):
        conversation = {
            "messages": [
                {"role": "user", "content": "q1"},
                {
                    "role": "assistant",
                    "stage3": {"model": "chair-a", "response": "First answer"},
                },
                {"role": "user", "content": "q2"},
                {
                    "role": "assistant",
                    "stage3": {"model": "chair-b", "response": "Latest answer"},
                },
            ]
        }
        block, sources, model = get_last_chair_context(conversation)
        assert "Latest answer" in block
        assert len(sources) == 1
        assert sources[0]["source_type"] == "manual_last_chair"
        assert model == "chair-b"

    def test_empty_when_no_chair_response(self):
        block, sources, model = get_last_chair_context({"messages": []})
        assert block == ""
        assert sources == []
        assert model is None


class TestContextEngine:
    @pytest.mark.asyncio
    async def test_reset_skips_retrieval(self, engine):
        result = await engine.prepare_context("conv-1", "@reset What is Python?")
        assert result.directives.reset is True
        assert result.context_block == ""
        assert result.rag_used is False
        assert engine.rag_provider.calls == []

    @pytest.mark.asyncio
    async def test_norag_bypasses_rag(self, engine):
        result = await engine.prepare_context("conv-1", "@norag explain auth")
        assert result.directives.skip_rag is True
        assert engine.rag_provider.calls[-1]["allow_rag"] is False

    @pytest.mark.asyncio
    async def test_rag_invoked_for_normal_query(self, engine):
        result = await engine.prepare_context("conv-1", "How does login work?")
        assert len(engine.rag_provider.calls) == 1
        assert engine.rag_provider.calls[0]["query"] == "How does login work?"
        assert result.context_block.startswith("# ctx")
        assert result.rag_used is True

    @pytest.mark.asyncio
    async def test_manual_context_passed_through(self):
        provider = RecordingRAGProvider()
        eng = ContextEngine(_noop_query_model, rag_provider=provider)
        manual = [{"content": "manual snippet", "source": "picked.py"}]
        result = await eng.prepare_context("conv-1", "question", manual_context=manual)
        assert provider.calls[-1]["manual_items"] == manual
        assert "manual snippet" in result.context_block
        assert result.rag_used is False

    @pytest.mark.asyncio
    async def test_lastchair_uses_chairman_not_rag(self):
        provider = RecordingRAGProvider()
        eng = ContextEngine(_noop_query_model, rag_provider=provider)
        conversation = {
            "messages": [
                {
                    "role": "assistant",
                    "stage3": {"model": "chair", "response": "Prior synthesis"},
                }
            ]
        }
        result = await eng.prepare_context(
            "conv-1",
            "@lastchair follow up",
            conversation=conversation,
        )
        assert result.context_from_last_chair is True
        assert "Prior synthesis" in result.context_block
        assert provider.calls == []

    @pytest.mark.asyncio
    async def test_lastchair_missing_warns_and_falls_back(self, engine):
        result = await engine.prepare_context(
            "conv-1",
            "@lastchair follow up",
            conversation={"messages": []},
        )
        assert any("No previous chairman" in w for w in result.warnings)
        assert len(engine.rag_provider.calls) == 1

    @pytest.mark.asyncio
    async def test_base_prompt_includes_user_question(self, engine):
        result = await engine.prepare_context("conv-1", "What is X?")
        assert "User question: What is X?" in result.base_prompt

    @pytest.mark.asyncio
    async def test_prepare_arena_context_helper(self):
        result = await prepare_arena_context(
            "conv-1",
            "plain question",
            _noop_query_model,
            rag_provider=NullRAGProvider(),
        )
        assert result.clean_query == "plain question"
        assert result.context_block == ""