"""Shared types for the CodeRAG pipeline."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CodeChunk:
    """A semantically meaningful slice of source code."""

    chunk_id: str
    source: str
    content: str
    line_start: int
    line_end: int
    chunk_type: str  # function | class | method | module | text | readme
    symbol: Optional[str] = None
    language: str = "python"
    parent_id: Optional[str] = None
    parent_content: Optional[str] = None
    index_text: Optional[str] = None
    references: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def citation_header(self) -> str:
        """Format path:line range for @cite-friendly context blocks."""
        return f"{self.source}:{self.line_start}-{self.line_end}"

    def display_content(self) -> str:
        """Content injected into the LLM context (parent scope when available)."""
        if self.parent_content and self.parent_content != self.content:
            return self.parent_content
        return self.content

    def to_faiss_metadata(self, chunk_index: int) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source": self.source,
            "doc_id": self.source,
            "chunk_index": chunk_index,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "chunk_type": self.chunk_type,
            "symbol": self.symbol or "",
            "language": self.language,
        }