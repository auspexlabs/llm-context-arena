"""AST-aware RAG chunk cap before summarization (DEC-018 B4)."""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from .types import CodeChunk


def apply_ast_aware_cap(
    ranked: List[Tuple[CodeChunk, float]],
    cap: int,
) -> List[Tuple[CodeChunk, float]]:
    """
    Trim ranked chunks to cap, dropping orphan children whose parent was cut.

    Keeps AST parent/child groups coherent when possible.
    """
    if cap <= 0 or not ranked:
        return []
    if len(ranked) <= cap:
        return ranked

    selected = ranked[:cap]
    selected_ids: Set[str] = {chunk.chunk_id for chunk, _ in selected}
    parent_ids: Dict[str, str] = {}
    for chunk, _ in ranked:
        if chunk.parent_id:
            parent_ids[chunk.chunk_id] = chunk.parent_id

    filtered: List[Tuple[CodeChunk, float]] = []
    for chunk, score in selected:
        parent_id = parent_ids.get(chunk.chunk_id)
        if parent_id and parent_id not in selected_ids:
            continue
        filtered.append((chunk, score))

    if len(filtered) >= cap or len(filtered) == len(selected):
        return filtered

    # Backfill from remainder when orphan filtering reduced count.
    used_ids = {chunk.chunk_id for chunk, _ in filtered}
    for chunk, score in ranked[cap:]:
        if len(filtered) >= cap:
            break
        if chunk.chunk_id in used_ids:
            continue
        parent_id = parent_ids.get(chunk.chunk_id)
        if parent_id and parent_id not in used_ids and parent_id not in selected_ids:
            continue
        filtered.append((chunk, score))
        used_ids.add(chunk.chunk_id)
    return filtered