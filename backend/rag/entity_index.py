"""Symbol → location index built at ingest time."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .types import CodeChunk


@dataclass
class EntityRecord:
    symbol: str
    source: str
    line_start: int
    line_end: int
    chunk_id: str
    chunk_type: str


@dataclass
class EntityIndex:
    by_symbol: Dict[str, List[EntityRecord]] = field(default_factory=dict)

    @classmethod
    def from_chunks(cls, chunks: List[CodeChunk]) -> "EntityIndex":
        index = cls()
        for chunk in chunks:
            if not chunk.symbol:
                continue
            record = EntityRecord(
                symbol=chunk.symbol,
                source=chunk.source,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                chunk_id=chunk.chunk_id,
                chunk_type=chunk.chunk_type,
            )
            index.by_symbol.setdefault(chunk.symbol, []).append(record)
            short = chunk.symbol.split(".")[-1]
            if short != chunk.symbol:
                index.by_symbol.setdefault(short, []).append(record)
        return index

    def lookup(self, symbol: str) -> List[EntityRecord]:
        return list(self.by_symbol.get(symbol, []))

    def seed_symbols_from_query(self, query: str) -> List[str]:
        tokens = []
        for raw in query.replace("/", " ").replace(".", " ").split():
            token = raw.strip(",()[]{}:;")
            if len(token) >= 3 and token[0].isalpha():
                tokens.append(token)
        found: List[str] = []
        for token in tokens:
            if token in self.by_symbol:
                found.append(token)
        return found