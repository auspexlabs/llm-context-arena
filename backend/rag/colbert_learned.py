"""Per-conversation ColBERT indexes with learned token embeddings (PyLate)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple

from .types import CodeChunk

logger = logging.getLogger(__name__)

_INDEX_SUBDIR = "index"
_INDEX_NAME = "chunks"


class SemanticIndex(Protocol):
    """Semantic retrieval backend (ColBERT late-interaction or fallback)."""

    def search(self, query: str, k: int = 10) -> List[Tuple[CodeChunk, float]]: ...


_MODEL = None
_MODEL_NAME: Optional[str] = None


def _pylate_available() -> bool:
    try:
        import pylate  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model(model_name: str, device: str):
    global _MODEL, _MODEL_NAME
    if _MODEL is not None and _MODEL_NAME == model_name:
        return _MODEL
    from pylate import models

    _MODEL = models.ColBERT(model_name_or_path=model_name, device=device)
    _MODEL_NAME = model_name
    logger.info("Loaded ColBERT model %s on %s", model_name, device)
    return _MODEL


def _embedding_size(embeddings) -> int:
    first = embeddings[0]
    if hasattr(first, "shape"):
        return int(first.shape[-1])
    return 128


def _normalize_scores(scored: List[Tuple[CodeChunk, float]]) -> List[Tuple[CodeChunk, float]]:
    if not scored:
        return scored
    values = [s for _, s in scored]
    lo, hi = min(values), max(values)
    if hi <= lo:
        return [(c, 1.0) for c, _ in scored]
    span = hi - lo
    return [(c, (s - lo) / span) for c, s in scored]


class LearnedColBERTIndex:
    """PyLate Voyager index — general model weights, per-conversation token embeddings."""

    def __init__(
        self,
        chunks: Dict[str, CodeChunk],
        index_dir: Path,
        model_name: str,
        device: str = "cpu",
    ):
        self.chunks = chunks
        self.index_dir = index_dir
        self.model_name = model_name
        self.device = device
        self._index = None
        self._retriever = None

    def _index_root(self) -> Path:
        return self.index_dir / _INDEX_SUBDIR

    def _is_built(self) -> bool:
        return (self._index_root() / _INDEX_NAME / "index.voyager").exists()

    def _load_runtime(self) -> None:
        if self._retriever is not None:
            return
        from pylate import indexes, retrieve

        self._index = indexes.Voyager(
            index_folder=str(self._index_root()),
            index_name=_INDEX_NAME,
            override=False,
        )
        self._retriever = retrieve.ColBERT(index=self._index)

    @classmethod
    def build(
        cls,
        chunks: List[CodeChunk],
        index_dir: Path,
        model_name: str,
        device: str = "cpu",
    ) -> "LearnedColBERTIndex":
        from pylate import indexes

        chunk_map = {c.chunk_id: c for c in chunks}
        index_dir.mkdir(parents=True, exist_ok=True)

        model = _get_model(model_name, device)
        texts = [c.index_text or c.content for c in chunks]
        ids = [c.chunk_id for c in chunks]

        logger.info(
            "Encoding %d chunks with ColBERT for %s",
            len(chunks),
            index_dir.name,
        )
        embeddings = model.encode(
            sentences=texts,
            batch_size=8,
            is_query=False,
            show_progress_bar=False,
        )
        dim = _embedding_size(embeddings)

        voyager = indexes.Voyager(
            index_folder=str(index_dir / _INDEX_SUBDIR),
            index_name=_INDEX_NAME,
            override=True,
            embedding_size=dim,
        )
        voyager.add_documents(documents_ids=ids, documents_embeddings=embeddings)

        inst = cls(chunk_map, index_dir, model_name, device)
        inst._index = voyager
        from pylate import retrieve

        inst._retriever = retrieve.ColBERT(index=voyager)
        return inst

    @classmethod
    def load(
        cls,
        chunks: Dict[str, CodeChunk],
        index_dir: Path,
        model_name: str,
        device: str = "cpu",
    ) -> Optional["LearnedColBERTIndex"]:
        inst = cls(chunks, index_dir, model_name, device)
        if not inst._is_built():
            return None
        inst._load_runtime()
        return inst

    def search(self, query: str, k: int = 10) -> List[Tuple[CodeChunk, float]]:
        self._load_runtime()
        model = _get_model(self.model_name, self.device)
        query_emb = model.encode(
            sentences=[query],
            batch_size=1,
            is_query=True,
            show_progress_bar=False,
        )
        results = self._retriever.retrieve(
            queries_embeddings=query_emb,
            k=k,
            device=self.device,
        )
        hits = results[0] if results else []
        scored: List[Tuple[CodeChunk, float]] = []
        for hit in hits:
            cid = str(hit["id"])
            chunk = self.chunks.get(cid)
            if chunk is None:
                continue
            scored.append((chunk, float(hit["score"])))
        return _normalize_scores(scored)