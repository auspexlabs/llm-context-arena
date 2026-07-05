"""Orchestrates semantic + hybrid + graph retrieval."""

from __future__ import annotations

import logging
import time
from typing import List, Optional, Tuple

from .entity_index import EntityIndex
from .format import build_context_block
from .graph import CodeGraph
from .hybrid import apply_readme_demotion, is_trace_query, seed_chunks_from_query
from .rerank import CrossEncoderReranker
from .store import ConversationStore
from .types import CodeChunk

logger = logging.getLogger(__name__)


class CodeRetriever:
    """Full CodeRAG retrieval pipeline (Phases 1–3, pre-ColBERT)."""

    def __init__(
        self,
        store: ConversationStore,
        reranker: Optional[CrossEncoderReranker] = None,
        retrieve_candidates: int = 50,
        rerank_top_k: int = 20,
        context_chunk_cap: int = 60,
        graph_hops: int = 3,
    ):
        self.store = store
        self.reranker = reranker or CrossEncoderReranker(enabled=False)
        self.retrieve_candidates = retrieve_candidates
        self.rerank_top_k = rerank_top_k
        self.context_chunk_cap = context_chunk_cap
        self.graph_hops = graph_hops

    def _expand_graph(self, seeds: List[Tuple[CodeChunk, float]], query: str) -> List[Tuple[CodeChunk, float]]:
        graph: Optional[CodeGraph] = self.store.graph
        if graph is None or not seeds:
            return seeds

        seed_ids = [c.chunk_id for c, _ in seeds]
        if is_trace_query(query):
            expanded_ids = graph.trace_expand(seed_ids, max_hops=self.graph_hops)
        else:
            expanded_ids = graph.neighbors_1hop(seed_ids)

        by_id = {c.chunk_id: (c, s) for c, s in seeds}
        for cid in expanded_ids:
            if cid in by_id:
                continue
            chunk = self.store.chunks.get(cid)
            if chunk:
                by_id[cid] = (chunk, 0.45)

        merged = list(by_id.values())
        merged.sort(key=lambda x: x[1], reverse=True)
        return merged

    def retrieve(self, query: str) -> Tuple[str, List[dict], float]:
        start = time.monotonic()

        if self.store.vectorstore is None and not self.store.chunks:
            return "", [], 0.0

        semantic = self.store.similarity_search(query, k=self.retrieve_candidates)

        entity_index: EntityIndex = self.store.entity_index or EntityIndex()
        seeded = seed_chunks_from_query(query, entity_index, self.store.chunks, limit=8)

        merged: dict[str, Tuple[CodeChunk, float]] = {}
        for chunk, score in semantic + seeded:
            prev = merged.get(chunk.chunk_id)
            if prev is None or score > prev[1]:
                merged[chunk.chunk_id] = (chunk, score)

        pool = list(merged.values())
        pool.sort(key=lambda x: x[1], reverse=True)
        pool = pool[: self.retrieve_candidates]

        ranked = self.reranker.rerank(query, pool, top_k=self.rerank_top_k)
        ranked = apply_readme_demotion(ranked)
        ranked = self._expand_graph(ranked, query)
        ranked = ranked[: self.context_chunk_cap]

        context_block, entries = build_context_block(ranked)
        elapsed_ms = (time.monotonic() - start) * 1000

        logger.info(
            "CodeRAG retrieved %d chunks (convo=%s query_len=%d ms=%.0f top=%s)",
            len(entries),
            self.store.conversation_id,
            len(query),
            elapsed_ms,
            [e.get("citation") for e in entries[:5]],
        )
        return context_block, entries, elapsed_ms