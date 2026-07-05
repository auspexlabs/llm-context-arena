"""AST-aware chunking for code repositories."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from .types import CodeChunk

SKIP_DIR_NAMES = {
    ".git", ".idea", ".vscode", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
}

SOURCE_EXTENSIONS = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".ipynb"}

MAX_FILE_BYTES = 500_000
LINE_WINDOW = 80
LINE_OVERLAP = 10


def _new_chunk_id() -> str:
    return uuid.uuid4().hex[:12]


def iter_source_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(skip in path.parts for skip in SKIP_DIR_NAMES):
            continue
        if path.suffix.lower() in SOURCE_EXTENSIONS:
            files.append(path)
    return files


def _line_window_chunks(
    rel_path: str,
    text: str,
    chunk_type: str = "text",
    language: str = "text",
) -> List[CodeChunk]:
    lines = text.splitlines()
    if not lines:
        return []

    chunks: List[CodeChunk] = []
    start = 0
    while start < len(lines):
        end = min(len(lines), start + LINE_WINDOW)
        body = "\n".join(lines[start:end]).strip()
        if body:
            chunks.append(
                CodeChunk(
                    chunk_id=_new_chunk_id(),
                    source=rel_path,
                    content=body,
                    line_start=start + 1,
                    line_end=end,
                    chunk_type=chunk_type,
                    language=language,
                    index_text=body[:2000],
                )
            )
        if end >= len(lines):
            break
        start = max(start + 1, end - LINE_OVERLAP)
    return chunks


def _node_text(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _chunk_from_node(
    rel_path: str,
    source: bytes,
    node,
    chunk_type: str,
    symbol: Optional[str],
    parent_body: Optional[str] = None,
) -> CodeChunk:
    content = _node_text(source, node)
    line_start = node.start_point[0] + 1
    line_end = node.end_point[0] + 1
    index_text = content
    if symbol:
        index_text = f"{symbol}\n{content[:1500]}"

    return CodeChunk(
        chunk_id=_new_chunk_id(),
        source=rel_path,
        content=content,
        line_start=line_start,
        line_end=line_end,
        chunk_type=chunk_type,
        symbol=symbol,
        language="python",
        parent_content=parent_body or content,
        index_text=index_text[:4000],
    )


def _extract_python_chunks(rel_path: str, text: str) -> List[CodeChunk]:
    try:
        import tree_sitter_python as tspython
        from tree_sitter import Language, Parser
    except ImportError:
        return _line_window_chunks(rel_path, text, chunk_type="module", language="python")

    parser = Parser(Language(tspython.language()))
    source = text.encode("utf-8")
    tree = parser.parse(source)
    root = tree.root_node

    chunks: List[CodeChunk] = []
    seen_spans: set[Tuple[int, int]] = set()

    def walk(node, class_name: Optional[str] = None):
        ntype = node.type
        if ntype in {"function_definition", "async_function_definition"}:
            name_node = node.child_by_field_name("name")
            symbol = _node_text(source, name_node) if name_node else None
            if symbol and class_name:
                symbol = f"{class_name}.{symbol}"
            span = (node.start_byte, node.end_byte)
            if span not in seen_spans:
                seen_spans.add(span)
                chunks.append(_chunk_from_node(rel_path, source, node, "method" if class_name else "function", symbol))
        elif ntype == "class_definition":
            name_node = node.child_by_field_name("name")
            class_symbol = _node_text(source, name_node) if name_node else None
            span = (node.start_byte, node.end_byte)
            if span not in seen_spans:
                seen_spans.add(span)
                chunks.append(_chunk_from_node(rel_path, source, node, "class", class_symbol))
            for child in node.children:
                walk(child, class_symbol)
            return
        for child in node.children:
            walk(child, class_name)

    walk(root)

    if not chunks:
        return _line_window_chunks(rel_path, text, chunk_type="module", language="python")
    return chunks


def _extract_references_python(text: str) -> List[str]:
    refs = set()
    for match in re.finditer(r"^\s*(?:from|import)\s+([\w\.]+)", text, re.MULTILINE):
        refs.add(match.group(1).split(".")[0])
    for match in re.finditer(r"\b([A-Za-z_][\w]*)\s*\(", text):
        name = match.group(1)
        if name not in {"if", "for", "while", "with", "def", "class", "return", "print"}:
            refs.add(name)
    return sorted(refs)


def chunk_file(path: Path, root: Path) -> List[CodeChunk]:
    rel = str(path.relative_to(root)).replace("\\", "/")
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    if not text.strip():
        return []

    suffix = path.suffix.lower()
    if suffix == ".py":
        chunks = _extract_python_chunks(rel, text)
        for chunk in chunks:
            chunk.references = _extract_references_python(chunk.content)
        return chunks

    chunk_type = "readme" if path.name.lower().startswith("readme") else "text"
    return _line_window_chunks(rel, text, chunk_type=chunk_type, language="text")


def chunk_repository(root: Path) -> List[CodeChunk]:
    all_chunks: List[CodeChunk] = []
    for path in sorted(iter_source_files(root)):
        all_chunks.extend(chunk_file(path, root))
    return all_chunks