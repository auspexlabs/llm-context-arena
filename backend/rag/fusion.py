"""Rank fusion for heterogeneous retrieval lists (DEC-010)."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .types import CodeChunk

# Standard RRF constant (Cormack et al.); stable across list length.
RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[Tuple[CodeChunk, float]]],
    *,
    k: int = RRF_K,
    limit: int | None = None,
) -> List[Tuple[CodeChunk, float]]:
    """Fuse ranked lists by reciprocal rank; scores are RRF sums, not raw retriever scores."""
    scores: Dict[str, float] = {}
    chunks: Dict[str, CodeChunk] = {}

    for ranked in ranked_lists:
        for rank, (chunk, _raw) in enumerate(ranked, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            chunks[chunk.chunk_id] = chunk

    fused = [(chunks[cid], score) for cid, score in scores.items()]
    fused.sort(key=lambda item: item[1], reverse=True)
    if limit is not None:
        return fused[:limit]
    return fused