"""Orchestrates semantic + hybrid + graph retrieval."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .colbert import SemanticIndex
from .entity_index import EntityIndex
from .format import build_context_block
from .graph import CodeGraph
from .hybrid import apply_readme_demotion, is_trace_query, seed_chunks_from_query
from .rerank import CrossEncoderReranker
from .store import ConversationStore
from .types import CodeChunk

logger = logging.getLogger(__name__)


@dataclass
class RetrievalConfig:
    """Retrieval pipeline flags.

    Production fuses layers in sequence (not bi-encoder + ColBERT in parallel):
      1. Semantic search — **one** backend: ``colbert`` (LateInteraction MaxSim) or
         ``biencoder`` (FAISS). These are alternatives, not additive.
      2. Union merge — entity/symbol seed hits merged in (max score per chunk_id).
      3. Cross-encoder rerank on the fused pool.
      4. README demotion.
      5. Graph expansion (1-hop, or multi-hop for trace queries) on reranked seeds.

    HYP-001 variants A–D are **isolated ablations** for measurement; variant E is
    the full fused production stack (ColBERT + entity seed + graph).
    """

    use_entity_seed: bool = True
    use_graph: bool = True
    graph_trace: bool = True
    semantic_backend: str = "colbert"  # biencoder | colbert
    use_rerank: bool = True
    use_readme_demotion: bool = True

    @classmethod
    def from_settings(cls) -> "RetrievalConfig":
        from ..config import SEMANTIC_BACKEND

        backend = SEMANTIC_BACKEND if SEMANTIC_BACKEND in {"colbert", "biencoder"} else "colbert"
        return cls(semantic_backend=backend)

    @classmethod
    def for_variant(cls, variant: str) -> "RetrievalConfig":
        if variant == "A":
            return cls(use_entity_seed=False, use_graph=False, semantic_backend="biencoder")
        if variant == "B":
            return cls(use_entity_seed=True, use_graph=False, semantic_backend="biencoder")
        if variant == "C":
            return cls(use_entity_seed=True, use_graph=True, graph_trace=False, semantic_backend="biencoder")
        if variant == "D":
            # Isolated: ColBERT replaces bi-encoder only (no entity seed, no graph).
            return cls(use_entity_seed=False, use_graph=False, semantic_backend="colbert")
        if variant in {"E", "production", "full"}:
            return cls(semantic_backend="colbert")
        return cls.from_settings()


class CodeRetriever:
    """Full CodeRAG retrieval pipeline (Phases 1–3 + optional ColBERT)."""

    def __init__(
        self,
        store: ConversationStore,
        reranker: Optional[CrossEncoderReranker] = None,
        retrieve_candidates: int = 50,
        rerank_top_k: int = 20,
        context_chunk_cap: int = 60,
        graph_hops: int = 3,
        config: Optional[RetrievalConfig] = None,
    ):
        self.store = store
        self.reranker = reranker or CrossEncoderReranker(enabled=False)
        self.retrieve_candidates = retrieve_candidates
        self.rerank_top_k = rerank_top_k
        self.context_chunk_cap = context_chunk_cap
        self.graph_hops = graph_hops
        self.config = config or RetrievalConfig.from_settings()

    def _semantic_search(self, query: str, k: int) -> List[Tuple[CodeChunk, float]]:
        if self.config.semantic_backend == "colbert":
            colbert: Optional[SemanticIndex] = getattr(self.store, "colbert_index", None)
            if colbert is not None:
                return colbert.search(query, k=k)
            logger.warning("ColBERT index missing; falling back to bi-encoder")
        return self.store.similarity_search(query, k=k)

    def _expand_graph(self, seeds: List[Tuple[CodeChunk, float]], query: str) -> List[Tuple[CodeChunk, float]]:
        if not self.config.use_graph:
            return seeds

        graph: Optional[CodeGraph] = self.store.graph
        if graph is None or not seeds:
            return seeds

        seed_ids = [c.chunk_id for c, _ in seeds]
        if self.config.graph_trace and is_trace_query(query):
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

    def retrieve_ranked(self, query: str) -> List[Tuple[CodeChunk, float]]:
        """Return ranked chunks without formatting — used by eval harness."""
        if self.store.vectorstore is None and not self.store.chunks:
            return []

        semantic = self._semantic_search(query, k=self.retrieve_candidates)

        merged: dict[str, Tuple[CodeChunk, float]] = {}
        for chunk, score in semantic:
            prev = merged.get(chunk.chunk_id)
            if prev is None or score > prev[1]:
                merged[chunk.chunk_id] = (chunk, score)

        if self.config.use_entity_seed:
            entity_index: EntityIndex = self.store.entity_index or EntityIndex()
            seeded = seed_chunks_from_query(query, entity_index, self.store.chunks, limit=8)
            for chunk, score in seeded:
                prev = merged.get(chunk.chunk_id)
                if prev is None or score > prev[1]:
                    merged[chunk.chunk_id] = (chunk, score)

        pool = list(merged.values())
        pool.sort(key=lambda x: x[1], reverse=True)
        pool = pool[: self.retrieve_candidates]

        if self.config.use_rerank and self.reranker.enabled:
            ranked = self.reranker.rerank(query, pool, top_k=self.rerank_top_k)
        else:
            ranked = pool[: self.rerank_top_k]

        if self.config.use_readme_demotion:
            ranked = apply_readme_demotion(ranked)

        ranked = self._expand_graph(ranked, query)
        return ranked[: self.context_chunk_cap]

    def retrieve(self, query: str) -> Tuple[str, List[dict], float]:
        start = time.monotonic()
        ranked = self.retrieve_ranked(query)
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