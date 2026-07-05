"""Cross-encoder reranking for retrieved code chunks."""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence, Tuple

from .types import CodeChunk

logger = logging.getLogger(__name__)

ScoreFn = Callable[[str, str], float]


class CrossEncoderReranker:
    """Rerank (query, chunk) pairs with a cross-encoder model."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        score_fn: Optional[ScoreFn] = None,
        enabled: bool = True,
    ):
        self.model_name = model_name
        self._score_fn = score_fn
        self.enabled = enabled
        self._model = None

    def _load_model(self):
        if self._model is not None or self._score_fn is not None:
            return
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
        except Exception:
            logger.exception("Failed to load cross-encoder %s", self.model_name)
            self._model = None

    def score_pair(self, query: str, document: str) -> float:
        if self._score_fn is not None:
            return self._score_fn(query, document)
        self._load_model()
        if self._model is None:
            return 0.0
        try:
            return float(self._model.predict([(query, document)])[0])
        except Exception:
            logger.exception("Cross-encoder predict failed")
            return 0.0

    def rerank(
        self,
        query: str,
        items: Sequence[Tuple[CodeChunk, float]],
        top_k: int,
    ) -> List[Tuple[CodeChunk, float]]:
        if not items:
            return []
        if not self.enabled:
            ordered = sorted(items, key=lambda x: x[1], reverse=True)
            return ordered[:top_k]

        scored: List[Tuple[CodeChunk, float]] = []
        for chunk, prior in items:
            text = chunk.index_text or chunk.content
            score = self.score_pair(query, text)
            if prior is not None:
                score = 0.7 * score + 0.3 * prior
            scored.append((chunk, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]