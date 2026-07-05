"""Directed code graph for shallow and deep retrieval expansion."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx

from .entity_index import EntityIndex
from .patterns import infer_pattern_edges, load_pattern_config
from .types import CodeChunk


class CodeGraph:
    """Chunk/entity graph with weighted edges."""

    def __init__(self):
        self.graph = nx.DiGraph()

    @classmethod
    def from_chunks(
        cls,
        chunks: List[CodeChunk],
        entity_index: EntityIndex,
        pattern_config: Optional[dict] = None,
    ) -> "CodeGraph":
        cg = cls()
        pattern_config = pattern_config or load_pattern_config()

        for chunk in chunks:
            cg.graph.add_node(
                chunk.chunk_id,
                source=chunk.source,
                symbol=chunk.symbol,
                chunk_type=chunk.chunk_type,
            )

        symbol_to_chunk = {
            rec.chunk_id: rec.symbol
            for records in entity_index.by_symbol.values()
            for rec in records
        }
        chunk_by_id = {c.chunk_id: c for c in chunks}

        for chunk in chunks:
            for ref in chunk.references:
                for record in entity_index.lookup(ref):
                    if record.chunk_id != chunk.chunk_id:
                        cg.graph.add_edge(chunk.chunk_id, record.chunk_id, weight=1.0, relation="reference")

            for src, relation, weight in infer_pattern_edges(chunk.chunk_id, chunk.content, pattern_config):
                cg.graph.add_edge(src, f"pattern:{relation}", weight=weight, relation=relation)

            if chunk.parent_id and chunk.parent_id in chunk_by_id:
                cg.graph.add_edge(chunk.chunk_id, chunk.parent_id, weight=0.9, relation="parent")

        return cg

    def neighbors_1hop(self, chunk_ids: List[str]) -> List[str]:
        seen: Set[str] = set(chunk_ids)
        expanded: List[str] = list(chunk_ids)
        for cid in chunk_ids:
            if cid not in self.graph:
                continue
            for neighbor in self.graph.successors(cid):
                if neighbor.startswith("pattern:"):
                    continue
                if neighbor not in seen:
                    seen.add(neighbor)
                    expanded.append(neighbor)
            for neighbor in self.graph.predecessors(cid):
                if neighbor.startswith("pattern:"):
                    continue
                if neighbor not in seen:
                    seen.add(neighbor)
                    expanded.append(neighbor)
        return expanded

    def trace_expand(self, chunk_ids: List[str], max_hops: int = 3) -> List[str]:
        """Iterative deepening for trace-style queries (Phase 3)."""
        seen: Set[str] = set()
        frontier = list(chunk_ids)
        ordered: List[str] = []

        for _ in range(max_hops):
            if not frontier:
                break
            next_frontier: List[str] = []
            for cid in frontier:
                if cid in seen or cid.startswith("pattern:"):
                    continue
                seen.add(cid)
                ordered.append(cid)
                if cid not in self.graph:
                    continue
                for neighbor in list(self.graph.successors(cid)) + list(self.graph.predecessors(cid)):
                    if neighbor not in seen and not neighbor.startswith("pattern:"):
                        next_frontier.append(neighbor)
            frontier = next_frontier
        return ordered

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self.graph, f)

    @classmethod
    def load(cls, path: Path) -> Optional["CodeGraph"]:
        if not path.exists():
            return None
        try:
            with open(path, "rb") as f:
                g = pickle.load(f)
            cg = cls()
            cg.graph = g
            return cg
        except Exception:
            return None