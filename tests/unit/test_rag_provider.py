"""Unit tests for RAG provider interface and NullRAGProvider."""

import pytest
from pathlib import Path

from backend.rag_provider import (
    RAGProvider,
    NullRAGProvider,
    RetrievedChunk,
    RetrievalResult,
    IndexResult,
)


class TestRetrievedChunk:
    """Tests for RetrievedChunk dataclass"""

    def test_create_with_required_fields(self):
        """RetrievedChunk should require content and source."""
        chunk = RetrievedChunk(
            content="Some code content",
            source="file.py",
        )
        assert chunk.content == "Some code content"
        assert chunk.source == "file.py"
        assert chunk.score is None
        assert chunk.metadata == {}

    def test_create_with_all_fields(self):
        """RetrievedChunk should accept all fields."""
        chunk = RetrievedChunk(
            content="Code content",
            source="file.py",
            score=0.95,
            line_start=10,
            line_end=25,
            metadata={"language": "python"},
        )
        assert chunk.score == 0.95
        assert chunk.line_start == 10
        assert chunk.line_end == 25
        assert chunk.metadata == {"language": "python"}


class TestRetrievalResult:
    """Tests for RetrievalResult dataclass"""

    def test_create_empty(self):
        """RetrievalResult should handle empty chunks."""
        result = RetrievalResult(chunks=[])
        assert len(result.chunks) == 0
        assert result.total_tokens == 0

    def test_to_context_sources(self):
        """to_context_sources should convert to legacy format."""
        result = RetrievalResult(
            chunks=[
                RetrievedChunk(
                    content="test content",
                    source="test.py",
                    score=0.9,
                    metadata={"lines": 10, "est_tokens": 50, "source_type": "rag"},
                )
            ],
            total_tokens=50,
        )
        sources = result.to_context_sources()
        assert len(sources) == 1
        assert sources[0]["source"] == "test.py"
        assert sources[0]["content"] == "test content"
        assert sources[0]["score"] == 0.9


class TestNullRAGProvider:
    """Tests for NullRAGProvider (no-op implementation)"""

    @pytest.fixture
    def provider(self):
        """Return a NullRAGProvider instance."""
        return NullRAGProvider()

    def test_index_from_zip_returns_success(self, provider):
        """index_from_zip should return success result."""
        result = provider.index_from_zip("/path/to/file.zip", "conv-123")
        assert isinstance(result, IndexResult)
        assert result.success is True
        assert "disabled" in result.message.lower() or "null" in result.message.lower()

    def test_index_from_directory_returns_success(self, provider, tmp_path):
        """index_from_directory should return success result."""
        result = provider.index_from_directory(tmp_path, "conv-123")
        assert isinstance(result, IndexResult)
        assert result.success is True

    def test_retrieve_returns_empty_chunks(self, provider):
        """retrieve should return empty chunks."""
        result = provider.retrieve("conv-123", "test query")
        assert isinstance(result, RetrievalResult)
        assert len(result.chunks) == 0
        assert result.total_tokens == 0

    def test_get_context_returns_empty_tuple(self, provider):
        """get_context should return empty context block and sources."""
        context, sources = provider.get_context("conv-123", "test query")
        assert context == ""
        assert sources == []

    def test_is_indexed_returns_false(self, provider):
        """is_indexed should always return False."""
        assert provider.is_indexed("conv-123") is False
        assert provider.is_indexed("any-id") is False

    def test_clear_index_returns_true(self, provider):
        """clear_index should always return True."""
        assert provider.clear_index("conv-123") is True
        assert provider.clear_index("any-id") is True

    def test_estimate_tokens_uses_len_over_4(self, provider):
        """estimate_tokens should use len/4 formula."""
        text = "a" * 100  # 100 characters
        tokens = provider.estimate_tokens(text)
        assert tokens == 25  # 100 / 4

    def test_estimate_tokens_empty_string(self, provider):
        """estimate_tokens should handle empty string."""
        tokens = provider.estimate_tokens("")
        assert tokens == 0

    def test_rank_paths_returns_zero_scores(self, provider, tmp_path):
        """rank_paths should return zero scores for all paths."""
        paths = [
            tmp_path / "file1.py",
            tmp_path / "file2.py",
            tmp_path / "file3.py",
        ]
        ranked = provider.rank_paths(paths, "test query")
        assert len(ranked) == 3
        for path, score in ranked:
            assert score == 0.0

    def test_build_git_snapshot_returns_message(self, provider):
        """build_git_snapshot should return informative message."""
        result = provider.build_git_snapshot("conv-123")
        assert isinstance(result, str)
        assert "null" in result.lower() or "disabled" in result.lower()


class TestRAGProviderInterface:
    """Tests for RAGProvider abstract interface"""

    def test_cannot_instantiate_abstract(self):
        """RAGProvider should not be directly instantiable."""
        with pytest.raises(TypeError):
            RAGProvider()

    def test_nullprovider_is_rag_provider(self):
        """NullRAGProvider should be an instance of RAGProvider."""
        provider = NullRAGProvider()
        assert isinstance(provider, RAGProvider)
