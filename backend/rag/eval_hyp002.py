"""HYP-002 evaluation: router × reranker on variant F (DEC-010 stack)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .eval import (
    CHECKPOINTS,
    GoldenQuery,
    build_eval_store,
    chunk_matches_target,
    load_golden_queries,
    make_eval_reranker,
    mean_recall_at_k,
    recall_at_k,
)
from .query_router import EmbeddingQueryRouter, QueryRoute, RouteFn, route_query_regex
from .rerank import CrossEncoderReranker
from .retriever import CodeRetriever, RetrievalConfig
from .store import ConversationStore
from .types import CodeChunk

HYP002_ROUTERS = ("regex", "embedding")
HYP002_RERANKERS = ("mock", "bge", "jina")


@dataclass
class ProbeQuery:
    id: str
    query: str
    relevant: List[Dict[str, Optional[str]]]
    category: str


def load_probe_queries(path: Path) -> List[ProbeQuery]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        ProbeQuery(
            id=item["id"],
            query=item["query"],
            relevant=item["relevant"],
            category=item.get("category", "architectural"),
        )
        for item in raw
    ]


def _labeled_training(
    golden: Sequence[GoldenQuery],
    probes: Sequence[ProbeQuery],
) -> List[Tuple[str, str]]:
    labeled: List[Tuple[str, str]] = [(q.query, q.category) for q in golden]
    labeled.extend((p.query, p.category) for p in probes)
    return labeled


def answer_slot_purity(retriever: CodeRetriever, query: str, k: int = 10) -> float:
    """Fraction of top-K slots that are reranked answers (not graph-appended)."""
    pre_graph = retriever.retrieve_post_rerank_pre_graph(query, top_k=k)
    full = retriever.retrieve_ranked(query)[:k]
    pre_ids = {chunk.chunk_id for chunk, _ in pre_graph}
    if not full:
        return 0.0
    answer_slots = sum(1 for chunk, _ in full if chunk.chunk_id in pre_ids)
    return answer_slots / min(k, len(full))


def router_accuracy(
    route_fn: Callable[[str], QueryRoute],
    labeled: Sequence[Tuple[str, str]],
) -> Dict[str, Any]:
    correct = 0
    per_item: Dict[str, str] = {}
    confusion: Dict[str, Dict[str, int]] = {}
    for text, expected in labeled:
        predicted = route_fn(text).category
        per_item[text[:48]] = predicted
        confusion.setdefault(expected, {})
        confusion[expected][predicted] = confusion[expected].get(predicted, 0) + 1
        if predicted == expected:
            correct += 1
        elif expected == "pattern" and predicted == "semantic":
            correct += 1
    total = len(labeled) or 1
    return {
        "accuracy": correct / total,
        "per_item": per_item,
        "confusion": confusion,
    }


def _make_variant_f_retriever(
    store: ConversationStore,
    *,
    route_fn: RouteFn,
    reranker: CrossEncoderReranker,
    k: int,
) -> CodeRetriever:
    config = RetrievalConfig.for_variant("F")
    return CodeRetriever(
        store,
        reranker=reranker,
        retrieve_candidates=50,
        rerank_top_k=k,
        context_chunk_cap=k + config.graph_append_slots,
        config=config,
        route_fn=route_fn,
    )


def _eval_golden(
    retriever: CodeRetriever,
    queries: Sequence[GoldenQuery],
    k: int,
) -> Dict[str, Any]:
    per_query: List[float] = []
    by_category: Dict[str, List[float]] = {}
    for gq in queries:
        ranked = retriever.retrieve_ranked(gq.query)
        chunks = [c for c, _ in ranked]
        score = recall_at_k(chunks, gq.relevant, k=k)
        per_query.append(score)
        by_category.setdefault(gq.category, []).append(score)
    return {
        "recall_at_k": mean_recall_at_k(per_query),
        "per_query": {gq.id: per_query[i] for i, gq in enumerate(queries)},
        "by_category": {cat: mean_recall_at_k(scores) for cat, scores in by_category.items()},
    }


def _eval_architectural(
    retriever: CodeRetriever,
    probes: Sequence[ProbeQuery],
    k: int,
) -> Dict[str, Any]:
    purity_scores: List[float] = []
    recall_scores: List[float] = []
    per_probe: Dict[str, Dict[str, float]] = {}
    for probe in probes:
        ranked = retriever.retrieve_ranked(probe.query)
        chunks = [c for c, _ in ranked]
        purity = answer_slot_purity(retriever, probe.query, k=k)
        recall = recall_at_k(chunks, probe.relevant, k=k) if probe.relevant else 0.0
        purity_scores.append(purity)
        recall_scores.append(recall)
        per_probe[probe.id] = {"purity": purity, "recall_at_k": recall}
    return {
        "mean_purity": mean_recall_at_k(purity_scores),
        "mean_recall_at_k": mean_recall_at_k(recall_scores),
        "per_probe": per_probe,
    }


def run_hyp002_cell(
    golden_store: ConversationStore,
    arena_store: ConversationStore,
    golden_queries: Sequence[GoldenQuery],
    architectural_probes: Sequence[ProbeQuery],
    *,
    router_mode: str,
    rerank_mode: str,
    k: int = 10,
    route_fn: Optional[RouteFn] = None,
    reranker: Optional[CrossEncoderReranker] = None,
) -> Dict[str, Any]:
    resolved_route = route_fn or route_query_regex
    resolved_reranker = reranker or make_eval_reranker(rerank_mode)

    golden_retriever = _make_variant_f_retriever(
        golden_store, route_fn=resolved_route, reranker=resolved_reranker, k=k
    )
    arena_retriever = _make_variant_f_retriever(
        arena_store, route_fn=resolved_route, reranker=resolved_reranker, k=k
    )

    router_eval = router_accuracy(resolved_route, [(q.query, q.category) for q in golden_queries])

    return {
        "router": router_mode,
        "reranker": rerank_mode,
        "variant": "F",
        "router_accuracy": router_eval,
        "golden": _eval_golden(golden_retriever, golden_queries, k),
        "architectural": _eval_architectural(arena_retriever, architectural_probes, k),
    }


def run_hyp002_matrix(
    golden_repo: Path,
    golden_queries_path: Path,
    arena_repo: Path,
    architectural_probes_path: Path,
    k: int = 10,
    *,
    colbert_mode: str = "hash",
    colbert_index_dir: Optional[Path] = None,
    rebuild_colbert: bool = True,
    routers: Sequence[str] = HYP002_ROUTERS,
    rerankers: Sequence[str] = HYP002_RERANKERS,
) -> Dict[str, Any]:
    golden_queries = load_golden_queries(golden_queries_path)
    architectural_probes = load_probe_queries(architectural_probes_path)
    training_labeled = _labeled_training(golden_queries, architectural_probes)

    golden_colbert_dir = colbert_index_dir or Path("data/conversations") / "hyp002_golden_colbert"
    arena_colbert_dir = (
        colbert_index_dir.parent / "hyp002_arena_colbert"
        if colbert_index_dir
        else Path("data/conversations") / "hyp002_arena_colbert"
    )
    golden_store = build_eval_store(
        golden_repo,
        conversation_id="hyp002_golden",
        colbert_mode=colbert_mode,
        colbert_index_dir=golden_colbert_dir,
        rebuild_colbert=rebuild_colbert,
    )
    arena_store = build_eval_store(
        arena_repo,
        conversation_id="hyp002_arena",
        colbert_mode=colbert_mode,
        colbert_index_dir=arena_colbert_dir,
        rebuild_colbert=rebuild_colbert,
    )

    route_fns: Dict[str, RouteFn] = {"regex": route_query_regex}
    if "embedding" in routers:
        embedding_router = EmbeddingQueryRouter.from_labeled_queries(training_labeled)
        route_fns["embedding"] = embedding_router.route

    reranker_instances: Dict[str, CrossEncoderReranker] = {
        mode: make_eval_reranker(mode) for mode in rerankers
    }

    cells: Dict[str, Dict[str, Any]] = {}
    for router in routers:
        for reranker_mode in rerankers:
            key = f"{router}+{reranker_mode}"
            cells[key] = run_hyp002_cell(
                golden_store,
                arena_store,
                golden_queries,
                architectural_probes,
                router_mode=router,
                rerank_mode=reranker_mode,
                k=k,
                route_fn=route_fns[router],
                reranker=reranker_instances[reranker_mode],
            )

    summary = {
        "golden_recall": {key: cells[key]["golden"]["recall_at_k"] for key in cells},
        "architectural_purity": {key: cells[key]["architectural"]["mean_purity"] for key in cells},
        "router_accuracy": {key: cells[key]["router_accuracy"]["accuracy"] for key in cells},
    }

    return {
        "golden_repo": str(golden_repo),
        "arena_repo": str(arena_repo),
        "query_count": len(golden_queries),
        "probe_count": len(architectural_probes),
        "k": k,
        "colbert_mode": colbert_mode,
        "variant": "F",
        "cells": cells,
        "summary": summary,
        "checkpoints": list(CHECKPOINTS),
    }