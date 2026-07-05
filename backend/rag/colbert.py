"""Late-interaction (ColBERT-style) retrieval for code chunks."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .types import CodeChunk

logger = logging.getLogger(__name__)

TokenEmbedFn = Callable[[str], List[float]]


def _default_token_embed(token: str, dim: int = 64) -> List[float]:
    """Deterministic hash embedding — no model download required."""
    vec = [0.0] * dim
    for i, ch in enumerate(token.lower()):
        vec[(ord(ch) + i * 17) % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def tokenize_for_late_interaction(text: str) -> List[str]:
    return [t for t in re.findall(r"[A-Za-z_][\w]*", text) if len(t) >= 2]


def maxsim_score(
    query_tokens: List[str],
    doc_tokens: List[str],
    embed_fn: TokenEmbedFn,
) -> float:
    """ColBERT MaxSim: average over query tokens of max doc-token similarity."""
    if not query_tokens or not doc_tokens:
        return 0.0
    q_embs = [embed_fn(t) for t in query_tokens]
    d_embs = [embed_fn(t) for t in doc_tokens]
    total = 0.0
    for qe in q_embs:
        best = max(_cosine(qe, de) for de in d_embs)
        total += best
    return total / len(q_embs)


@dataclass
class LateInteractionIndex:
    """Token-level late-interaction index (ColBERT-style MaxSim)."""

    token_embed_fn: Optional[TokenEmbedFn] = None
    _entries: Dict[str, Tuple[CodeChunk, str]] = field(default_factory=dict)

    def index_chunks(self, chunks: List[CodeChunk]) -> None:
        self._entries.clear()
        for chunk in chunks:
            text = chunk.index_text or chunk.content
            self._entries[chunk.chunk_id] = (chunk, text)

    def search(self, query: str, k: int = 10) -> List[Tuple[CodeChunk, float]]:
        embed_fn = self.token_embed_fn or (lambda t: _default_token_embed(t))
        q_tokens = tokenize_for_late_interaction(query)
        scored: List[Tuple[CodeChunk, float]] = []
        for _cid, (chunk, text) in self._entries.items():
            d_tokens = tokenize_for_late_interaction(text)
            if chunk.symbol:
                d_tokens.extend(tokenize_for_late_interaction(chunk.symbol))
            score = maxsim_score(q_tokens, d_tokens, embed_fn)
            scored.append((chunk, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    @classmethod
    def from_chunks(cls, chunks: List[CodeChunk], token_embed_fn: Optional[TokenEmbedFn] = None) -> "LateInteractionIndex":
        idx = cls(token_embed_fn=token_embed_fn)
        idx.index_chunks(chunks)
        return idx


def try_load_colbert_model(model_name: str = "colbert-ir/colbertv2.0"):
    """Optional real ColBERT model — returns None if colbert-ai is unavailable."""
    try:
        from colbert import Indexer, Searcher  # type: ignore[import-untyped]
        logger.info("colbert-ai available (model=%s)", model_name)
        return model_name
    except Exception:
        logger.debug("colbert-ai not installed; using LateInteractionIndex fallback")
        return None