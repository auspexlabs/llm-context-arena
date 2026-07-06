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
from .rerank import CrossEncoderReranker
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


def build_eval_store(repo_root: Path, conversation_id: str = "hyp001") -> ConversationStore:
    """Index golden repo with weak bi-encoder + full graph sidecars."""
    chunks = chunk_repository(repo_root)
    embedder = WeakBiEncoder()
    store = ConversationStore(conversation_id, Path("data/conversations"), embedder)
    store.chunks = {c.chunk_id: c for c in chunks}
    store.chunk_order = [c.chunk_id for c in chunks]
    store.entity_index = EntityIndex.from_chunks(chunks)
    store.graph = CodeGraph.from_chunks(chunks, store.entity_index)
    store.colbert_index = LateInteractionIndex.from_chunks(chunks)

    # Bi-encoder sees natural-language cues only — symbols indexed via entity/ColBERT paths
    texts = [_semantic_only_text(c.content) or c.content[:200] for c in chunks]
    metadatas = [c.to_faiss_metadata(i) for i, c in enumerate(chunks)]
    from langchain_community.vectorstores import FAISS

    store.vectorstore = FAISS.from_texts(texts, embedder, metadatas=metadatas)
    return store


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

    per_query: List[float] = []
    by_category: Dict[str, List[float]] = {}

    for gq in queries:
        ranked = retriever.retrieve_ranked(gq.query)
        retrieved = [chunk for chunk, _ in ranked]
        score = recall_at_k(retrieved, gq.relevant, k=k)
        per_query.append(score)
        by_category.setdefault(gq.category, []).append(score)

    return {
        "variant": variant,
        "recall_at_k": mean_recall_at_k(per_query),
        "per_query": {gq.id: per_query[i] for i, gq in enumerate(queries)},
        "by_category": {cat: mean_recall_at_k(scores) for cat, scores in by_category.items()},
        "k": k,
    }


def run_hyp001_matrix(
    repo_root: Path,
    queries_path: Path,
    k: int = 10,
) -> Dict[str, Any]:
    store = build_eval_store(repo_root)
    queries = load_golden_queries(queries_path)
    reranker = CrossEncoderReranker(
        score_fn=lambda q, d: 0.5,
        enabled=True,
    )
    results = {}
    for variant in HYP001_VARIANTS:
        results[variant] = run_variant_eval(store, queries, variant, k=k, reranker=reranker)
    return {
        "query_count": len(queries),
        "k": k,
        "variants": results,
        "summary": {v: results[v]["recall_at_k"] for v in HYP001_VARIANTS},
    }