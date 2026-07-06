"""AST-aware chunking for code repositories."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from .lang_registry import LanguageSpec, spec_for_suffix
from .types import CodeChunk

SKIP_DIR_NAMES = {
    ".git", ".idea", ".vscode", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
}

SOURCE_EXTENSIONS = {
    ".py", ".rs", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".go",
    ".md", ".txt", ".json", ".yaml", ".yml", ".ipynb",
}

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
    language: str,
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
        language=language,
        parent_content=parent_body or content,
        index_text=index_text[:4000],
    )


def _symbol_from_node(source: bytes, node) -> Optional[str]:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(source, name_node)

    for child in node.children:
        if child.type in {"identifier", "type_identifier", "property_identifier", "field_identifier"}:
            text = _node_text(source, child)
            if text and text not in {"func", "fn", "impl", "struct", "type", "interface", "class"}:
                return text
    return None


def _go_receiver_type(source: bytes, node) -> Optional[str]:
    for child in node.children:
        if child.type != "parameter_list":
            continue
        for param in child.children:
            if param.type != "parameter_declaration":
                continue
            type_node = param.child_by_field_name("type")
            if type_node is not None:
                return _node_text(source, type_node)
    return None


def _go_type_name(source: bytes, node) -> Optional[str]:
    for child in node.children:
        if child.type == "type_spec":
            id_node = child.child_by_field_name("name")
            if id_node is not None:
                return _node_text(source, id_node)
        if child.type in {"type_identifier", "identifier"}:
            return _node_text(source, child)
    return _symbol_from_node(source, node)


def _rust_impl_type(source: bytes, node) -> Optional[str]:
    for child in node.children:
        if child.type == "type_identifier":
            return _node_text(source, child)
    return None


def _extract_ast_chunks(rel_path: str, text: str, spec: LanguageSpec) -> List[CodeChunk]:
    try:
        from tree_sitter import Parser
    except ImportError:
        return _line_window_chunks(rel_path, text, chunk_type="module", language=spec.language)

    try:
        parser = Parser(spec.load_language())
    except Exception:
        return _line_window_chunks(rel_path, text, chunk_type="module", language=spec.language)

    source = text.encode("utf-8")
    tree = parser.parse(source)
    root = tree.root_node

    chunks: List[CodeChunk] = []
    seen_spans: set[Tuple[int, int]] = set()

    def add_chunk(
        node,
        chunk_type: str,
        symbol: Optional[str],
        parent_id: Optional[str] = None,
        parent_content: Optional[str] = None,
    ) -> CodeChunk:
        span = (node.start_byte, node.end_byte)
        if span in seen_spans:
            return None  # type: ignore[return-value]
        seen_spans.add(span)
        chunk = _chunk_from_node(rel_path, source, node, chunk_type, symbol, spec.language)
        if parent_id:
            chunk.parent_id = parent_id
            chunk.parent_content = parent_content or chunk.parent_content
        chunks.append(chunk)
        return chunk

    def walk(
        node,
        class_name: Optional[str] = None,
        parent_id: Optional[str] = None,
        parent_content: Optional[str] = None,
    ):
        ntype = node.type

        if ntype == "method_declaration" and spec.language == "go":
            receiver = _go_receiver_type(source, node)
            symbol = _symbol_from_node(source, node)
            if receiver and symbol:
                symbol = f"{receiver}.{symbol}"
            add_chunk(node, "method", symbol)
            return

        if ntype in spec.function_nodes:
            symbol = _symbol_from_node(source, node)
            if symbol and class_name:
                symbol = f"{class_name}.{symbol}"
            role = "method" if class_name else "function"
            link_parent = class_name is not None or (
                spec.language == "python" and parent_id is not None
            )
            fn_chunk = add_chunk(
                node,
                role,
                symbol,
                parent_id=parent_id if link_parent else None,
                parent_content=parent_content if link_parent else None,
            )
            if spec.language == "python":
                fn_id = fn_chunk.chunk_id if fn_chunk else parent_id
                fn_body = fn_chunk.content if fn_chunk else parent_content
                for child in node.children:
                    walk(child, class_name, fn_id, fn_body)
            return

        if ntype in spec.class_nodes:
            symbol = _symbol_from_node(source, node)
            class_chunk = add_chunk(node, "class", symbol)
            class_id = class_chunk.chunk_id if class_chunk else None
            class_body = class_chunk.content if class_chunk else None
            for child in node.children:
                walk(child, symbol, class_id, class_body)
            return

        if ntype in spec.interface_nodes:
            symbol = _symbol_from_node(source, node)
            class_chunk = add_chunk(node, "class", symbol)
            class_id = class_chunk.chunk_id if class_chunk else None
            class_body = class_chunk.content if class_chunk else None
            for child in node.children:
                walk(child, symbol, class_id, class_body)
            return

        if ntype in spec.type_nodes:
            symbol = _go_type_name(source, node) if spec.language == "go" else _symbol_from_node(source, node)
            add_chunk(node, "class", symbol)
            if spec.language != "go":
                for child in node.children:
                    walk(child, symbol)
            return

        if ntype in spec.impl_nodes:
            impl_type = _rust_impl_type(source, node)
            for child in node.children:
                if child.type == "declaration_list":
                    for decl in child.children:
                        walk(decl, impl_type)
                else:
                    walk(child, impl_type)
            return

        for child in node.children:
            walk(child, class_name, parent_id, parent_content)

    walk(root)

    if not chunks:
        return _line_window_chunks(rel_path, text, chunk_type="module", language=spec.language)
    return chunks


def _extract_python_chunks(rel_path: str, text: str) -> List[CodeChunk]:
    from .lang_registry import PYTHON_SPEC

    return _extract_ast_chunks(rel_path, text, PYTHON_SPEC)


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
    spec = spec_for_suffix(suffix)
    if spec is not None:
        chunks = _extract_ast_chunks(rel, text, spec)
        if suffix == ".py":
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