"""Orchestrates semantic + hybrid + graph retrieval."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .colbert import SemanticIndex
from .entity_index import EntityIndex
from .format import build_context_block
from .graph import CodeGraph
from .fusion import reciprocal_rank_fusion
from .hybrid import apply_readme_demotion, is_trace_query, seed_chunks_from_query
from .query_router import QueryRoute, RouteFn, route_query
from .rerank import CrossEncoderReranker
from .store import ConversationStore
from .types import CodeChunk

logger = logging.getLogger(__name__)


@dataclass
class RetrievalConfig:
    """Retrieval pipeline flags.

    Production fuses layers in sequence (DEC-010):
      1. Semantic search — **one** backend: ``colbert`` or ``biencoder``.
      2. **RRF** fuse semantic + entity seed ranked lists (``fusion_mode=rrf``), or
         legacy max-score union (``fusion_mode=max_score``, HYP-001 ablations).
      3. Cross-encoder rerank on fused pool — **no prior-score blend** when RRF.
      4. README demotion.
      5. Graph **append** (DEC-010): neighbors fill slots after top-K answers;
         legacy ``graph_mode=resort`` re-sorts injected neighbors (pre-DEC-010).

    HYP-001 variants A–D use ``max_score`` + ``resort``. Variant **F** (DEC-010) is
    ColBERT + entity + RRF + code rerank + append graph.
    """

    use_entity_seed: bool = True
    use_graph: bool = True
    graph_trace: bool = True
    semantic_backend: str = "colbert"  # biencoder | colbert
    use_rerank: bool = True
    use_readme_demotion: bool = True
    fusion_mode: str = "rrf"  # rrf | max_score
    graph_mode: str = "append"  # append | resort
    graph_append_slots: int = 10
    use_query_router: bool = True
    rerank_blend_prior: bool = False  # DEC-010: False when fusion_mode=rrf

    @classmethod
    def from_settings(cls) -> "RetrievalConfig":
        from ..config import FUSION_MODE, GRAPH_MODE, SEMANTIC_BACKEND

        backend = SEMANTIC_BACKEND if SEMANTIC_BACKEND in {"colbert", "biencoder"} else "colbert"
        fusion = FUSION_MODE if FUSION_MODE in {"rrf", "max_score"} else "rrf"
        graph = GRAPH_MODE if GRAPH_MODE in {"append", "resort"} else "append"
        return cls(
            semantic_backend=backend,
            fusion_mode=fusion,
            graph_mode=graph,
            rerank_blend_prior=fusion != "rrf",
        )

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
            # Legacy production stack (pre-DEC-010) for HYP-001 comparison.
            return cls(
                semantic_backend="colbert",
                fusion_mode="max_score",
                graph_mode="resort",
                rerank_blend_prior=True,
                use_query_router=False,
            )
        if variant == "F":
            return cls(
                semantic_backend="colbert",
                fusion_mode="rrf",
                graph_mode="append",
                rerank_blend_prior=False,
                use_query_router=True,
            )
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
        route_fn: Optional[RouteFn] = None,
    ):
        self.store = store
        self.reranker = reranker or CrossEncoderReranker(enabled=False)
        self.retrieve_candidates = retrieve_candidates
        self.rerank_top_k = rerank_top_k
        self.context_chunk_cap = context_chunk_cap
        self.graph_hops = graph_hops
        self.config = config or RetrievalConfig.from_settings()
        self._route_fn = route_fn

    def _semantic_search(self, query: str, k: int) -> List[Tuple[CodeChunk, float]]:
        if self.config.semantic_backend == "colbert":
            colbert: Optional[SemanticIndex] = getattr(self.store, "colbert_index", None)
            if colbert is not None:
                return colbert.search(query, k=k)
            logger.warning("ColBERT index missing; falling back to bi-encoder")
        return self.store.similarity_search(query, k=k)

    def _resolve_route(self, query: str) -> QueryRoute:
        if self.config.use_query_router:
            fn = self._route_fn or route_query
            return fn(query)
        trace = self.config.graph_trace and is_trace_query(query)
        return QueryRoute(
            category="trace" if trace else "semantic",
            use_graph_append=self.config.use_graph,
            graph_trace=trace,
            graph_seed_k=3,
        )

    def _expand_graph(
        self,
        ranked: List[Tuple[CodeChunk, float]],
        query: str,
        route: QueryRoute,
    ) -> List[Tuple[CodeChunk, float]]:
        if not self.config.use_graph or not route.use_graph_append:
            return ranked

        graph: Optional[CodeGraph] = self.store.graph
        if graph is None or not ranked:
            return ranked

        seed_k = route.graph_seed_k or min(3, len(ranked))
        seed_ids = [c.chunk_id for c, _ in ranked[:seed_k]]
        if route.graph_trace:
            expanded_ids = graph.trace_expand(seed_ids, max_hops=self.graph_hops)
        else:
            expanded_ids = graph.neighbors_1hop(seed_ids)

        if self.config.graph_mode == "resort":
            by_id = {c.chunk_id: (c, s) for c, s in ranked}
            for cid in expanded_ids:
                if cid in by_id:
                    continue
                chunk = self.store.chunks.get(cid)
                if chunk:
                    by_id[cid] = (chunk, 0.45)
            merged = list(by_id.values())
            merged.sort(key=lambda x: x[1], reverse=True)
            return merged

        # DEC-010 append-only: graph neighbors never displace reranked answer slots.
        seen = {c.chunk_id for c, _ in ranked}
        append_budget = self.config.graph_append_slots
        appended: List[Tuple[CodeChunk, float]] = []
        floor = ranked[-1][1] * 0.5 if ranked else 0.0
        for cid in expanded_ids:
            if cid in seen or append_budget <= 0:
                continue
            chunk = self.store.chunks.get(cid)
            if chunk is None:
                continue
            seen.add(cid)
            appended.append((chunk, floor))
            append_budget -= 1
        return ranked + appended

    def _entity_seed_list(self, query: str) -> List[Tuple[CodeChunk, float]]:
        entity_index: EntityIndex = self.store.entity_index or EntityIndex()
        return seed_chunks_from_query(query, entity_index, self.store.chunks, limit=8)

    def _fuse_lists(
        self,
        semantic: List[Tuple[CodeChunk, float]],
        entity: List[Tuple[CodeChunk, float]],
    ) -> List[Tuple[CodeChunk, float]]:
        if self.config.fusion_mode == "rrf":
            lists = [semantic]
            if entity:
                lists.append(entity)
            return reciprocal_rank_fusion(lists, limit=self.retrieve_candidates)

        merged: dict[str, Tuple[CodeChunk, float]] = {}
        for chunk, score in semantic:
            prev = merged.get(chunk.chunk_id)
            if prev is None or score > prev[1]:
                merged[chunk.chunk_id] = (chunk, score)
        for chunk, score in entity:
            prev = merged.get(chunk.chunk_id)
            if prev is None or score > prev[1]:
                merged[chunk.chunk_id] = (chunk, score)
        pool = list(merged.values())
        pool.sort(key=lambda x: x[1], reverse=True)
        return pool[: self.retrieve_candidates]

    def _build_candidate_pool(self, query: str) -> List[Tuple[CodeChunk, float]]:
        """Semantic + entity lists fused (RRF or max-score), capped at retrieve_candidates."""
        semantic = self._semantic_search(query, k=self.retrieve_candidates)
        entity: List[Tuple[CodeChunk, float]] = []
        if self.config.use_entity_seed:
            entity = self._entity_seed_list(query)
        return self._fuse_lists(semantic, entity)

    def retrieve_pre_rerank(self, query: str, top_k: Optional[int] = None) -> List[Tuple[CodeChunk, float]]:
        """Top-K after semantic + entity merge, before rerank/graph."""
        k = top_k or self.rerank_top_k
        return self._build_candidate_pool(query)[:k]

    def retrieve_post_rerank_pre_graph(
        self, query: str, top_k: Optional[int] = None
    ) -> List[Tuple[CodeChunk, float]]:
        """Top-K after rerank + README demotion, before graph expansion."""
        k = top_k or self.rerank_top_k
        pool = self._build_candidate_pool(query)
        if self.config.use_rerank and self.reranker.enabled:
            ranked = self.reranker.rerank(
                query,
                pool,
                top_k=k,
                blend_prior=self.config.rerank_blend_prior,
            )
        else:
            ranked = pool[:k]
        if self.config.use_readme_demotion:
            ranked = apply_readme_demotion(ranked)
        return ranked[:k]

    def retrieve_ranked(self, query: str) -> List[Tuple[CodeChunk, float]]:
        """Return ranked chunks without formatting — used by eval harness."""
        if self.store.vectorstore is None and not self.store.chunks:
            return []

        route = self._resolve_route(query)
        from .pre_cap import apply_ast_aware_cap

        ranked = self.retrieve_post_rerank_pre_graph(query, top_k=self.rerank_top_k)
        ranked = self._expand_graph(ranked, query, route)
        return apply_ast_aware_cap(ranked, self.context_chunk_cap)

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