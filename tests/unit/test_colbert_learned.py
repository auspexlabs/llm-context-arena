"""Tests for learned ColBERT index (PyLate) with mocks."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.rag.colbert import LateInteractionIndex, build_semantic_index
from backend.rag.types import CodeChunk


def _chunk(cid: str, text: str) -> CodeChunk:
    return CodeChunk(
        chunk_id=cid,
        source="a.py",
        content=text,
        line_start=1,
        line_end=5,
        chunk_type="function",
        symbol="foo",
        index_text=text,
    )


class TestBuildSemanticIndex:
    def test_hash_fallback_when_learned_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COLBERT_LEARNED", "false")
        chunks = [_chunk("c1", "def foo(): pass")]
        idx = build_semantic_index(chunks, tmp_path / "colbert", rebuild=True)
        assert isinstance(idx, LateInteractionIndex)

    def test_uses_learned_index_when_available(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COLBERT_LEARNED", "true")
        chunks = [_chunk("c1", "def foo(): pass")]
        mock_index = MagicMock()
        mock_index.search.return_value = [(chunks[0], 0.9)]

        with patch("backend.rag.colbert_learned._pylate_available", return_value=True):
            with patch(
                "backend.rag.colbert_learned.LearnedColBERTIndex.build",
                return_value=mock_index,
            ) as build_mock:
                idx = build_semantic_index(chunks, tmp_path / "colbert", rebuild=True)
                build_mock.assert_called_once()
                assert idx is mock_index

    def test_loads_existing_index_without_rebuild(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COLBERT_LEARNED", "true")
        chunks = [_chunk("c1", "def foo(): pass")]
        mock_index = MagicMock()

        with patch("backend.rag.colbert_learned._pylate_available", return_value=True):
            with patch(
                "backend.rag.colbert_learned.LearnedColBERTIndex.load",
                return_value=mock_index,
            ) as load_mock:
                idx = build_semantic_index(chunks, tmp_path / "colbert", rebuild=False)
                load_mock.assert_called_once()
                assert idx is mock_index

    def test_falls_back_on_learned_build_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COLBERT_LEARNED", "true")
        chunks = [_chunk("c1", "def foo(): pass")]

        with patch("backend.rag.colbert_learned._pylate_available", return_value=True):
            with patch(
                "backend.rag.colbert_learned.LearnedColBERTIndex.build",
                side_effect=RuntimeError("gpu oom"),
            ):
                idx = build_semantic_index(chunks, tmp_path / "colbert", rebuild=True)
                assert isinstance(idx, LateInteractionIndex)