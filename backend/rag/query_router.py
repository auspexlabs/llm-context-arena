"""Query intent routing (HYP-002 promoted — embedding router default)."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .hybrid import is_trace_query

logger = logging.getLogger(__name__)

EncodeFn = Callable[[Sequence[str]], List[List[float]]]
RouteFn = Callable[[str], "QueryRoute"]

ROUTER_CATEGORIES = (
    "symbol_lookup",
    "trace",
    "cross_file",
    "semantic",
    "pattern",
    "architectural",
)

_TRAINING_PATH = Path(__file__).with_name("router_training.json")


@dataclass(frozen=True)
class QueryRoute:
    """Per-query retrieval policy; populated by router (learned or regex fallback)."""

    category: str
    use_graph_append: bool
    graph_trace: bool
    graph_seed_k: int


def route_from_category(category: str) -> QueryRoute:
    """Map a query-intent label to retrieval flags (shared by embedding + regex routers)."""
    if category == "trace":
        return QueryRoute("trace", True, True, 3)
    if category == "symbol_lookup":
        return QueryRoute("symbol_lookup", False, False, 0)
    if category == "architectural":
        return QueryRoute("architectural", False, False, 0)
    if category in {"cross_file", "pattern"}:
        return QueryRoute(category, True, False, 3)
    return QueryRoute("semantic", True, False, 3)


def route_query_regex(query: str) -> QueryRoute:
    """Regex fallback router (HYP-002 baseline)."""
    if is_trace_query(query):
        return route_from_category("trace")
    lowered = query.lower()
    if any(tok in lowered for tok in ("defined", "definition", "where is", "who calls")):
        return route_from_category("symbol_lookup")
    if any(tok in lowered for tok in ("pipeline", "architecture", "flow", "overview")):
        return route_from_category("architectural")
    return route_from_category("semantic")


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


_EMBED_MODEL = None


def _default_encode(texts: Sequence[str]) -> List[List[float]]:
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        from sentence_transformers import SentenceTransformer

        _EMBED_MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    vectors = _EMBED_MODEL.encode(list(texts), normalize_embeddings=True)
    return [v.tolist() for v in vectors]


def load_router_training(path: Optional[Path] = None) -> List[Tuple[str, str]]:
    data = json.loads((path or _TRAINING_PATH).read_text(encoding="utf-8"))
    return [(item["query"], item["category"]) for item in data]


class EmbeddingQueryRouter:
    """Embedding router: query vs per-class prototype centroids."""

    def __init__(
        self,
        prototypes: Dict[str, List[float]],
        *,
        encode_fn: Optional[EncodeFn] = None,
    ):
        self.prototypes = prototypes
        self._encode_fn = encode_fn or _default_encode

    @classmethod
    def from_labeled_queries(
        cls,
        labeled: Sequence[Tuple[str, str]],
        *,
        encode_fn: Optional[EncodeFn] = None,
    ) -> "EmbeddingQueryRouter":
        by_cat: Dict[str, List[str]] = {}
        for text, category in labeled:
            by_cat.setdefault(category, []).append(text)
        encode = encode_fn or _default_encode
        prototypes: Dict[str, List[float]] = {}
        for category, texts in by_cat.items():
            vectors = encode(texts)
            dim = len(vectors[0])
            centroid = [0.0] * dim
            for vec in vectors:
                for i, v in enumerate(vec):
                    centroid[i] += v
            n = float(len(vectors))
            prototypes[category] = [v / n for v in centroid]
        return cls(prototypes, encode_fn=encode)

    @classmethod
    def from_training_file(cls, path: Optional[Path] = None) -> "EmbeddingQueryRouter":
        return cls.from_labeled_queries(load_router_training(path))

    def classify(self, query: str) -> Tuple[str, Dict[str, float]]:
        vec = self._encode_fn([query])[0]
        scores = {cat: _cosine(vec, proto) for cat, proto in self.prototypes.items()}
        category = max(scores, key=scores.get)
        return category, scores

    def route(self, query: str) -> QueryRoute:
        category, _ = self.classify(query)
        return route_from_category(category)


_EMBEDDING_ROUTER: Optional[EmbeddingQueryRouter] = None
_PRODUCTION_ROUTE_FN: Optional[RouteFn] = None


def get_embedding_router() -> EmbeddingQueryRouter:
    global _EMBEDDING_ROUTER
    if _EMBEDDING_ROUTER is None:
        _EMBEDDING_ROUTER = EmbeddingQueryRouter.from_training_file()
    return _EMBEDDING_ROUTER


def reset_routers() -> None:
    """Clear cached routers (tests)."""
    global _EMBEDDING_ROUTER, _PRODUCTION_ROUTE_FN
    _EMBEDDING_ROUTER = None
    _PRODUCTION_ROUTE_FN = None


def get_production_route_fn() -> RouteFn:
    global _PRODUCTION_ROUTE_FN
    if _PRODUCTION_ROUTE_FN is not None:
        return _PRODUCTION_ROUTE_FN

    from ..config import QUERY_ROUTER

    if QUERY_ROUTER == "regex":
        _PRODUCTION_ROUTE_FN = route_query_regex
        return _PRODUCTION_ROUTE_FN

    try:
        router = get_embedding_router()
        _PRODUCTION_ROUTE_FN = router.route
        logger.info("Query router: embedding (%d training labels)", len(load_router_training()))
    except Exception:
        logger.exception("Embedding router init failed; falling back to regex")
        _PRODUCTION_ROUTE_FN = route_query_regex
    return _PRODUCTION_ROUTE_FN


def route_query(query: str) -> QueryRoute:
    """Production default: embedding router (HYP-002), regex via QUERY_ROUTER=regex."""
    return get_production_route_fn()(query)


def get_router_fn(mode: str, *, training_labeled: Optional[Sequence[Tuple[str, str]]] = None) -> RouteFn:
    if mode == "regex":
        return route_query_regex
    if mode == "embedding":
        if training_labeled is None:
            return get_embedding_router().route
        return EmbeddingQueryRouter.from_labeled_queries(training_labeled).route
    raise ValueError(f"Unknown router mode: {mode}")