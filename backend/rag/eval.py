"""HYP-001 evaluation: recall@k across retrieval ablation variants."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.embeddings import Embeddings

from .chunker import chunk_repository
from .colbert import LateInteractionIndex
from .entity_index import EntityIndex
from .graph import CodeGraph
from .rerank import CrossEncoderReranker, create_reranker
from .retriever import CodeRetriever, RetrievalConfig
from .store import ConversationStore
from .types import CodeChunk

HYP001_VARIANTS = ("A", "B", "C", "D", "E")


@dataclass
class GoldenQuery:
    id: str
    query: str
    relevant: List[Dict[str, Optional[str]]]
    category: str


def load_golden_queries(path: Path) -> List[GoldenQuery]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        GoldenQuery(
            id=item["id"],
            query=item["query"],
            relevant=item["relevant"],
            category=item.get("category", "general"),
        )
        for item in raw
    ]


def chunk_matches_target(chunk: CodeChunk, target: Dict[str, Optional[str]]) -> bool:
    if chunk.source != target.get("source"):
        return False
    symbol = target.get("symbol")
    if not symbol:
        return True
    if chunk.symbol == symbol:
        return True
    if chunk.symbol and symbol in chunk.symbol:
        return True
    return False


def recall_at_k(
    retrieved: Sequence[CodeChunk],
    relevant: Sequence[Dict[str, Optional[str]]],
    k: int = 10,
) -> float:
    if not relevant:
        return 0.0
    top = list(retrieved)[:k]
    hits = 0
    for target in relevant:
        if any(chunk_matches_target(chunk, target) for chunk in top):
            hits += 1
    return hits / len(relevant)


def mean_recall_at_k(per_query: Sequence[float]) -> float:
    if not per_query:
        return 0.0
    return sum(per_query) / len(per_query)


# --- Simulated bi-encoder that misses bare symbols (HYP-001 observation) ---

_SEMANTIC_KEYWORDS: Dict[str, List[float]] = {
    "authentication": [1.0, 0.0, 0.0, 0.0, 0.2],
    "auth": [0.9, 0.0, 0.0, 0.0, 0.1],
    "login": [0.8, 0.0, 0.0, 0.0, 0.0],
    "permission": [0.7, 0.0, 0.2, 0.0, 0.0],
    "queue": [0.0, 1.0, 0.0, 0.0, 0.0],
    "worker": [0.0, 0.9, 0.0, 0.0, 0.0],
    "background": [0.0, 0.5, 0.3, 0.0, 0.0],
    "task": [0.0, 0.6, 0.2, 0.0, 0.0],
    "user": [0.0, 0.0, 1.0, 0.0, 0.0],
    "persistence": [0.0, 0.0, 0.8, 0.0, 0.0],
    "service": [0.0, 0.0, 0.6, 0.2, 0.0],
    "api": [0.0, 0.0, 0.0, 1.0, 0.0],
    "route": [0.0, 0.0, 0.0, 0.9, 0.0],
    "endpoint": [0.0, 0.0, 0.0, 0.8, 0.0],
    "bootstrap": [0.0, 0.0, 0.0, 0.0, 1.0],
    "entrypoint": [0.0, 0.0, 0.0, 0.0, 0.9],
    "application": [0.0, 0.0, 0.0, 0.0, 0.7],
    "session": [0.5, 0.0, 0.0, 0.0, 0.3],
    "token": [0.4, 0.0, 0.0, 0.0, 0.2],
    "handoff": [0.0, 0.7, 0.0, 0.0, 0.0],
    "registration": [0.0, 0.0, 0.0, 0.7, 0.2],
    "flow": [0.3, 0.0, 0.2, 0.0, 0.0],
    "consumer": [0.0, 0.8, 0.0, 0.0, 0.0],
    "defined": [0.1, 0.1, 0.1, 0.1, 0.1],
    "implementation": [0.1, 0.1, 0.1, 0.1, 0.1],
    "overview": [0.2, 0.0, 0.0, 0.0, 0.0],
}


def _normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _semantic_only_text(text: str) -> str:
    """Strip identifiers so the weak bi-encoder sees natural-language cues only."""
    text = re.sub(r"[A-Za-z_][\w]*", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


class WeakBiEncoder(Embeddings):
    """Bi-encoder that under-retrieves bare symbols — models nomic-style gaps."""

    dim = 5

    def _has_semantic_signal(self, text: str) -> bool:
        sem = _semantic_only_text(text)
        return any(kw in sem for kw in _SEMANTIC_KEYWORDS)

    def _embed_text(self, text: str) -> List[float]:
        sem = _semantic_only_text(text)
        vec = [0.0] * self.dim
        for word in sem.split():
            for keyword, weights in _SEMANTIC_KEYWORDS.items():
                if keyword in word or word in keyword:
                    for i, w in enumerate(weights):
                        vec[i] += w
        if not any(vec):
            # Code/symbol-heavy text: flat vector — bi-encoder cannot rank it
            bucket = hash(sem) % self.dim
            vec[bucket] = 0.001
        return _normalize(vec)

    def embed_query(self, text: str) -> List[float]:
        if not self._has_semantic_signal(text):
            return [0.0] * self.dim
        return self._embed_text(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_text(t) for t in texts]


def build_eval_store(
    repo_root: Path,
    conversation_id: str = "hyp001",
    *,
    colbert_mode: str = "hash",
    colbert_index_dir: Optional[Path] = None,
    rebuild_colbert: bool = True,
) -> ConversationStore:
    """Index golden repo with weak bi-encoder + full graph sidecars.

    colbert_mode:
        hash — deterministic MaxSim (fast, unit-test default)
        learned — PyLate ColBERTv2 per-conversation index (T8 / production parity)
    """
    chunks = chunk_repository(repo_root)
    embedder = WeakBiEncoder()
    store = ConversationStore(conversation_id, Path("data/conversations"), embedder)
    store.chunks = {c.chunk_id: c for c in chunks}
    store.chunk_order = [c.chunk_id for c in chunks]
    store.entity_index = EntityIndex.from_chunks(chunks)
    store.graph = CodeGraph.from_chunks(chunks, store.entity_index)

    if colbert_mode == "learned":
        from .colbert import build_semantic_index

        idx_dir = colbert_index_dir or Path("data/conversations") / f"{conversation_id}_colbert"
        store.colbert_index = build_semantic_index(chunks, idx_dir, rebuild=rebuild_colbert)
    else:
        store.colbert_index = LateInteractionIndex.from_chunks(chunks)

    # Bi-encoder sees natural-language cues only — symbols indexed via entity/ColBERT paths
    texts = [_semantic_only_text(c.content) or c.content[:200] for c in chunks]
    metadatas = [c.to_faiss_metadata(i) for i, c in enumerate(chunks)]
    from langchain_community.vectorstores import FAISS

    store.vectorstore = FAISS.from_texts(texts, embedder, metadatas=metadatas)
    return store


def make_eval_reranker(mode: str = "mock", *, model_name: Optional[str] = None) -> CrossEncoderReranker:
    """mock = flat 0.5; bge/jina = local sentence-transformers cross-encoders."""
    if mode == "mock":
        return CrossEncoderReranker(score_fn=lambda _q, _d: 0.5, enabled=True)
    if mode == "bge":
        from ..config import RERANK_ENABLED

        return create_reranker(model_name or "BAAI/bge-reranker-base", enabled=RERANK_ENABLED)
    if mode == "jina":
        from ..config import RERANK_ENABLED, RERANK_MODEL

        return create_reranker(model_name or RERANK_MODEL, enabled=RERANK_ENABLED)
    if model_name:
        return create_reranker(model_name, enabled=True)
    return CrossEncoderReranker(score_fn=lambda _q, _d: 0.5, enabled=True)


CHECKPOINTS = ("pre_rerank", "post_rerank_pre_graph", "full_pipeline")


def _eval_checkpoint(
    retriever: CodeRetriever,
    query: str,
    checkpoint: str,
    k: int,
) -> List[CodeChunk]:
    if checkpoint == "pre_rerank":
        ranked = retriever.retrieve_pre_rerank(query, top_k=k)
    elif checkpoint == "post_rerank_pre_graph":
        ranked = retriever.retrieve_post_rerank_pre_graph(query, top_k=k)
    else:
        ranked = retriever.retrieve_ranked(query)
    return [chunk for chunk, _ in ranked]


def _score_checkpoint(
    retriever: CodeRetriever,
    queries: Sequence[GoldenQuery],
    checkpoint: str,
    k: int,
) -> Dict[str, Any]:
    per_query: List[float] = []
    by_category: Dict[str, List[float]] = {}
    for gq in queries:
        retrieved = _eval_checkpoint(retriever, gq.query, checkpoint, k)
        score = recall_at_k(retrieved, gq.relevant, k=k)
        per_query.append(score)
        by_category.setdefault(gq.category, []).append(score)
    return {
        "recall_at_k": mean_recall_at_k(per_query),
        "per_query": {gq.id: per_query[i] for i, gq in enumerate(queries)},
        "by_category": {cat: mean_recall_at_k(scores) for cat, scores in by_category.items()},
    }


def run_variant_eval(
    store: ConversationStore,
    queries: Sequence[GoldenQuery],
    variant: str,
    k: int = 10,
    reranker: Optional[CrossEncoderReranker] = None,
) -> Dict[str, Any]:
    config = RetrievalConfig.for_variant(variant)
    retriever = CodeRetriever(
        store,
        reranker=reranker or CrossEncoderReranker(enabled=False),
        retrieve_candidates=50,
        rerank_top_k=k,
        context_chunk_cap=k,
        config=config,
    )

    checkpoints = {
        name: _score_checkpoint(retriever, queries, name, k) for name in CHECKPOINTS
    }

    return {
        "variant": variant,
        "recall_at_k": checkpoints["full_pipeline"]["recall_at_k"],
        "per_query": checkpoints["full_pipeline"]["per_query"],
        "by_category": checkpoints["full_pipeline"]["by_category"],
        "checkpoints": checkpoints,
        "k": k,
    }


def run_hyp001_matrix(
    repo_root: Path,
    queries_path: Path,
    k: int = 10,
    *,
    colbert_mode: str = "hash",
    rerank_mode: str = "mock",
    colbert_index_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    store = build_eval_store(
        repo_root,
        colbert_mode=colbert_mode,
        colbert_index_dir=colbert_index_dir,
    )
    queries = load_golden_queries(queries_path)
    reranker = make_eval_reranker(rerank_mode)
    results = {}
    for variant in HYP001_VARIANTS:
        results[variant] = run_variant_eval(store, queries, variant, k=k, reranker=reranker)
    summary = {checkpoint: {} for checkpoint in CHECKPOINTS}
    by_category = {checkpoint: {} for checkpoint in CHECKPOINTS}
    for variant in HYP001_VARIANTS:
        for checkpoint in CHECKPOINTS:
            cp = results[variant]["checkpoints"][checkpoint]
            summary[checkpoint][variant] = cp["recall_at_k"]
            by_category[checkpoint][variant] = cp["by_category"]

    return {
        "repo": str(repo_root),
        "query_count": len(queries),
        "k": k,
        "colbert_mode": colbert_mode,
        "rerank_mode": rerank_mode,
        "chunk_count": len(store.chunks),
        "variants": results,
        "summary": summary["full_pipeline"],
        "summary_by_checkpoint": summary,
        "by_category": by_category["full_pipeline"],
        "by_category_by_checkpoint": by_category,
    }