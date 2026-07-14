"""Hybrid retrieval helpers: symbol seeding and README demotion."""

import re
from pathlib import PurePosixPath
from typing import Iterable, List, Tuple

from .entity_index import EntityIndex
from .types import CodeChunk

README_RE = re.compile(r"(^|/)readme(\.|$)", re.IGNORECASE)
TRACE_RE = re.compile(r"\b(trace|call\s*chain|how\s+does|where\s+is|who\s+calls)\b", re.IGNORECASE)
PATH_RE = re.compile(
    r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9_+-]+)?"
)
BARE_FILE_RE = re.compile(
    r"(?<![\w./-])[A-Za-z0-9_-]+\.(?:py|pyi|js|jsx|ts|tsx|go|rs|java|kt|kts|rb|php|cs|cpp|cc|c|h|hpp|md|rst|toml|yaml|yml|json)(?![\w-])",
    re.IGNORECASE,
)
CODE_IDENTIFIER_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")


def is_trace_query(query: str) -> bool:
    return bool(TRACE_RE.search(query))


def readme_demotion_factor(source: str) -> float:
    return 0.55 if README_RE.search(source) else 1.0


def extract_path_mentions(query: str) -> List[str]:
    """Extract path-like user references while preserving mention order."""
    found: List[Tuple[int, str]] = []
    for pattern in (PATH_RE, BARE_FILE_RE):
        for match in pattern.finditer(query):
            value = (
                match.group(0)
                .replace("\\", "/")
                .lstrip("./")
                .rstrip(".,;:!?)]}'\"")
            )
            found.append((match.start(), value))

    mentions: List[str] = []
    seen: set[str] = set()
    for _, value in sorted(found):
        key = value.lower()
        if key not in seen:
            seen.add(key)
            mentions.append(value)
    return mentions


def resolve_path_mentions(query: str, sources: Iterable[str], limit: int = 8) -> List[str]:
    """Resolve explicit query paths against indexed sources; bare names must be unique."""
    available = list(dict.fromkeys(source.replace("\\", "/") for source in sources))
    by_lower = {source.lower(): source for source in available}
    resolved: List[str] = []
    for mention in extract_path_mentions(query):
        match = by_lower.get(mention.lower())
        if match is None and "/" not in mention:
            basename_matches = [
                source
                for source in available
                if PurePosixPath(source).name.lower() == mention.lower()
            ]
            if len(basename_matches) == 1:
                match = basename_matches[0]
        if match is not None and match not in resolved:
            resolved.append(match)
        if len(resolved) >= limit:
            break
    return resolved


def seed_chunks_from_paths(
    query: str,
    chunk_by_id: dict[str, CodeChunk],
    limit: int = 8,
) -> List[Tuple[CodeChunk, float]]:
    """Return one query-relevant, protected seed for each explicitly named file."""
    sources = resolve_path_mentions(
        query,
        (chunk.source for chunk in chunk_by_id.values()),
        limit=limit,
    )
    query_lower = query.lower()
    query_terms = set(re.findall(r"[a-z_][a-z0-9_]+", query_lower))
    hits: List[Tuple[CodeChunk, float]] = []
    for source in sources:
        candidates = [chunk for chunk in chunk_by_id.values() if chunk.source == source]
        if not candidates:
            continue

        def relevance(chunk: CodeChunk) -> Tuple[int, int, int]:
            symbol = (chunk.symbol or "").lower()
            symbol_parts = set(re.findall(r"[a-z_][a-z0-9_]+", symbol))
            content_terms = set(
                re.findall(r"[a-z_][a-z0-9_]+", (chunk.index_text or chunk.content).lower())
            )
            return (
                1 if symbol and symbol in query_lower else 0,
                len(symbol_parts & query_terms),
                len(content_terms & query_terms),
            )

        best = max(candidates, key=relevance)
        hits.append((best, 1.0))
    return hits


def seed_chunks_from_identifiers(
    query: str,
    chunk_by_id: dict[str, CodeChunk],
    limit: int = 8,
) -> List[Tuple[CodeChunk, float]]:
    """Lexically seed chunks containing explicit code-style identifiers."""
    identifier_query = query
    for mention in extract_path_mentions(query):
        identifier_query = re.sub(
            re.escape(mention),
            " ",
            identifier_query,
            flags=re.IGNORECASE,
        )
    identifiers = list(
        dict.fromkeys(
            match.group(0).lower()
            for match in CODE_IDENTIFIER_RE.finditer(identifier_query)
        )
    )
    if not identifiers:
        return []

    scored: List[Tuple[CodeChunk, float]] = []
    for chunk in chunk_by_id.values():
        haystack = (chunk.index_text or chunk.content).lower()
        symbol = (chunk.symbol or "").lower()
        matches = sum(haystack.count(identifier) for identifier in identifiers)
        if matches == 0:
            continue
        symbol_match = any(
            symbol == identifier or symbol.endswith(f"_{identifier}")
            for identifier in identifiers
        )
        source_bonus = 0.1 if not chunk.source.startswith(("docs/", "tests/")) else 0.0
        score = 0.7 + min(matches, 5) * 0.03 + source_bonus + (0.1 if symbol_match else 0.0)
        scored.append((chunk, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


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
