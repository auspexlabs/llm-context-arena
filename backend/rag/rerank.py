"""Cross-encoder reranking for retrieved code chunks."""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence, Tuple

from .types import CodeChunk

logger = logging.getLogger(__name__)
JINA_V3_REVISION = "10fb694fc21f7a710a563ff1eb977a460f3868e4"

ScoreFn = Callable[[str, str], float]


def create_reranker(
    model_name: str,
    *,
    enabled: bool = True,
    score_fn: Optional[ScoreFn] = None,
) -> "CrossEncoderReranker":
    """Factory: enables trust_remote_code for Jina models."""
    trust = "jina" in model_name.lower()
    return CrossEncoderReranker(
        model_name=model_name,
        score_fn=score_fn,
        enabled=enabled,
        trust_remote_code=trust,
    )


class CrossEncoderReranker:
    """Rerank (query, chunk) pairs with a cross-encoder model."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        score_fn: Optional[ScoreFn] = None,
        enabled: bool = True,
        trust_remote_code: bool = False,
    ):
        self.model_name = model_name
        self._score_fn = score_fn
        self.enabled = enabled
        self.trust_remote_code = trust_remote_code
        self._model = None
        self._model_kind = "pairwise"
        self._load_attempted = False

    @staticmethod
    def _document_text(chunk: CodeChunk) -> str:
        text = chunk.index_text or chunk.content
        if text.startswith(f"Path: {chunk.source}\n"):
            return text
        symbol = f"\nSymbol: {chunk.symbol}" if chunk.symbol else ""
        return f"Path: {chunk.source}{symbol}\n{text}"

    def _load_model(self):
        if self._model is not None or self._score_fn is not None or self._load_attempted:
            return
        self._load_attempted = True
        try:
            if "jina-reranker-v3" in self.model_name.lower():
                from transformers import AutoModel, AutoTokenizer

                from ..config import get_colbert_device

                self._model = AutoModel.from_pretrained(
                    self.model_name,
                    dtype="auto",
                    revision=JINA_V3_REVISION,
                    trust_remote_code=True,
                )
                tokenizer = AutoTokenizer.from_pretrained(
                    self.model_name,
                    revision=JINA_V3_REVISION,
                    trust_remote_code=True,
                )
                if tokenizer.pad_token is None:
                    tokenizer.pad_token = tokenizer.unk_token
                    tokenizer.pad_token_id = tokenizer.convert_tokens_to_ids(
                        tokenizer.unk_token
                    )
                tokenizer.padding_side = "left"
                self._model._tokenizer = tokenizer
                self._model.to(get_colbert_device())
                self._model.eval()
                if not hasattr(self._model, "rerank"):
                    raise TypeError("Jina v3 model did not expose rerank()")
                self._model_kind = "listwise"
            else:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(
                    self.model_name,
                    trust_remote_code=self.trust_remote_code,
                )
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
        *,
        blend_prior: bool = True,
    ) -> List[Tuple[CodeChunk, float]]:
        if not items:
            return []
        if not self.enabled:
            ordered = sorted(items, key=lambda x: x[1], reverse=True)
            return ordered[:top_k]

        if self._score_fn is None:
            self._load_model()
            if self._model is None:
                return sorted(items, key=lambda item: item[1], reverse=True)[:top_k]
        if self._model is not None and self._model_kind == "listwise":
            try:
                documents = [self._document_text(chunk) for chunk, _ in items]
                results = self._model.rerank(query, documents, top_n=len(documents))
                by_index = {
                    int(result["index"]): float(result["relevance_score"])
                    for result in results
                }
                scored = []
                for index, (chunk, prior) in enumerate(items):
                    score = by_index.get(index, 0.0)
                    if blend_prior and prior is not None:
                        score = 0.7 * score + 0.3 * prior
                    scored.append((chunk, score))
                scored.sort(key=lambda item: item[1], reverse=True)
                return scored[:top_k]
            except Exception:
                logger.exception("Listwise rerank failed for %s", self.model_name)
                return sorted(items, key=lambda item: item[1], reverse=True)[:top_k]

        scored: List[Tuple[CodeChunk, float]] = []
        for chunk, prior in items:
            text = self._document_text(chunk)
            score = self.score_pair(query, text)
            if blend_prior and prior is not None:
                score = 0.7 * score + 0.3 * prior
            scored.append((chunk, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
