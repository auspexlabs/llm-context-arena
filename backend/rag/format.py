"""Format retrieved chunks into LLM context blocks."""

from typing import Any, Dict, List, Tuple

from .types import CodeChunk


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def chunk_to_context_entry(chunk: CodeChunk, score: float | None = None) -> Dict[str, Any]:
    body = chunk.display_content()
    return {
        "source": chunk.source,
        "doc_id": chunk.source,
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.metadata.get("chunk_index"),
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "symbol": chunk.symbol,
        "chunk_type": chunk.chunk_type,
        "score": score,
        "content": body,
        "lines": chunk.line_end - chunk.line_start + 1,
        "chars": len(body),
        "bytes": len(body.encode("utf-8", errors="ignore")),
        "est_tokens": estimate_tokens(body),
        "source_type": "rag",
        "citation": chunk.citation_header(),
    }


def build_context_block(
    chunks: List[Tuple[CodeChunk, float | None]],
    header: str = "# Relevant repository context (CodeRAG)",
) -> Tuple[str, List[Dict[str, Any]]]:
    if not chunks:
        return "", []

    lines: List[str] = [header, ""]
    entries: List[Dict[str, Any]] = []

    for chunk, score in chunks:
        entry = chunk_to_context_entry(chunk, score)
        entries.append(entry)
        lines.append(f"--- {entry['citation']} ---")
        if chunk.symbol:
            lines.append(f"# {chunk.symbol}")
        lines.append(entry["content"])
        lines.append("")

    return "\n".join(lines).strip() + "\n", entries


def build_manual_context(manual_items: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    if not manual_items:
        return "", []

    entries: List[Dict[str, Any]] = []
    for item in manual_items:
        content = (item.get("content") or "").strip()
        src = item.get("path") or item.get("source") or "manual"
        entries.append({
            "source": src,
            "doc_id": src,
            "chunk_index": None,
            "score": item.get("score"),
            "content": content,
            "lines": content.count("\n") + 1 if content else 0,
            "chars": len(content),
            "bytes": len(content.encode("utf-8", errors="ignore")),
            "est_tokens": estimate_tokens(content),
            "source_type": item.get("source_type", "manual"),
        })

    lines = ["# Manually selected context", ""]
    for entry in entries:
        lines.append(f"--- {entry['source']} ---")
        lines.append(entry["content"])
        lines.append("")

    return "\n".join(lines).strip() + "\n", entries