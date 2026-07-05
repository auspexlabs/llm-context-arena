"""Hybrid retrieval helpers: symbol seeding and README demotion."""

import re
from typing import List, Tuple

from .entity_index import EntityIndex
from .types import CodeChunk

README_RE = re.compile(r"(^|/)readme(\.|$)", re.IGNORECASE)
TRACE_RE = re.compile(r"\b(trace|call\s*chain|how\s+does|where\s+is|who\s+calls)\b", re.IGNORECASE)


def is_trace_query(query: str) -> bool:
    return bool(TRACE_RE.search(query))


def readme_demotion_factor(source: str) -> float:
    return 0.55 if README_RE.search(source) else 1.0


def seed_chunks_from_query(
    query: str,
    entity_index: EntityIndex,
    chunk_by_id: dict[str, CodeChunk],
    limit: int = 5,
) -> List[Tuple[CodeChunk, float]]:
    """Entity/symbol grep seeding to complement vector search."""
    hits: List[Tuple[CodeChunk, float]] = []
    seen: set[str] = set()

    for symbol in entity_index.seed_symbols_from_query(query):
        for record in entity_index.lookup(symbol):
            if record.chunk_id in seen:
                continue
            chunk = chunk_by_id.get(record.chunk_id)
            if chunk is None:
                continue
            seen.add(record.chunk_id)
            hits.append((chunk, 0.85))
            if len(hits) >= limit:
                return hits

    query_lower = query.lower()
    for chunk in chunk_by_id.values():
        if chunk.chunk_id in seen:
            continue
        if chunk.symbol and chunk.symbol.lower() in query_lower:
            hits.append((chunk, 0.8))
            seen.add(chunk.chunk_id)
        elif any(tok in chunk.source.lower() for tok in query_lower.split() if len(tok) > 4):
            hits.append((chunk, 0.55))
            seen.add(chunk.chunk_id)
        if len(hits) >= limit:
            break

    return hits


def apply_readme_demotion(scored: List[Tuple[CodeChunk, float]]) -> List[Tuple[CodeChunk, float]]:
    adjusted = []
    for chunk, score in scored:
        factor = readme_demotion_factor(chunk.source)
        adjusted.append((chunk, score * factor))
    adjusted.sort(key=lambda x: x[1], reverse=True)
    return adjusted