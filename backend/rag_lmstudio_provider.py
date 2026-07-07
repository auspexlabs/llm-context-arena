"""LM Studio + FAISS implementation of RAGProvider."""

from __future__ import annotations

import fnmatch
import logging
import math
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_openai import OpenAIEmbeddings

from .config import (
    CONTEXT_CHUNK_CAP,
    INDEX_EXCLUDE_GLOBS,
    INDEX_INCLUDE_GLOBS,
    INDEX_INCLUDE_UNTRACKED,
    INDEX_MANIFEST_PATH,
    LMSTUDIO_BASE_URL,
    LMSTUDIO_EMBED_MODEL,
    RERANK_ENABLED,
    RERANK_MODEL,
    RERANK_TOP_K,
    RETRIEVE_CANDIDATES,
)
from .rag.chunker import SKIP_DIR_NAMES, iter_source_files
from .rag.manifest import diff_manifest, scan_repo_files
from .rag.format import build_manual_context, estimate_tokens
from .rag.indexer import index_directory
from .rag.rerank import create_reranker
from .rag.retriever import CodeRetriever, RetrievalConfig
from .rag.store import ConversationStore, clear_store_cache, get_or_load_store, register_store
from .rag_provider import IndexResult, RAGProvider, RetrievalResult, RetrievedChunk

logger = logging.getLogger(__name__)


def _load_manifest() -> Dict[str, Any]:
    path = Path(INDEX_MANIFEST_PATH)
    if not path.exists():
        return {}
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _matches_globs(path: str, patterns: List[str]) -> bool:
    if not patterns:
        return False
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def _git_ls_tracked(root: Path) -> List[str]:
    try:
        res = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def _git_status_paths(root: Path) -> List[str]:
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        paths = []
        for line in res.stdout.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if path:
                paths.append(path)
        return paths
    except Exception:
        return []


def _compute_cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class LMStudioRAGProvider(RAGProvider):
    """CodeRAG provider backed by LM Studio embeddings and local FAISS."""

    def __init__(
        self,
        embedder: Optional[Any] = None,
        reranker: Optional[Any] = None,
    ):
        self.embeddings = embedder or OpenAIEmbeddings(
            base_url=LMSTUDIO_BASE_URL,
            api_key=os.getenv("LMSTUDIO_API_KEY", "lmstudio"),
            model=LMSTUDIO_EMBED_MODEL,
            check_embedding_ctx_length=False,
        )
        self.reranker = reranker or create_reranker(RERANK_MODEL, enabled=RERANK_ENABLED)
        self.manifest_path = Path(INDEX_MANIFEST_PATH)

    def _store(self, conversation_id: str) -> ConversationStore:
        return get_or_load_store(conversation_id, self.embeddings)

    def index_from_zip(self, zip_path: str, conversation_id: str) -> IndexResult:
        start = time.monotonic()
        temp_dir = Path("temp_repos") / conversation_id
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(temp_dir)
            msg = self._index_dir(temp_dir, conversation_id)
            ms = (time.monotonic() - start) * 1000
            count = _load_manifest().get(conversation_id, {}).get("chunk_count", 0)
            return IndexResult(success=True, message=msg, chunks_indexed=count, time_taken_ms=ms)
        except Exception as e:
            return IndexResult(success=False, message=str(e))

    def index_from_directory(self, directory: Path, conversation_id: str) -> IndexResult:
        start = time.monotonic()
        try:
            msg = self._index_dir(directory, conversation_id)
            ms = (time.monotonic() - start) * 1000
            count = _load_manifest().get(conversation_id, {}).get("chunk_count", 0)
            return IndexResult(success=True, message=msg, chunks_indexed=count, time_taken_ms=ms)
        except Exception as e:
            logger.exception("index_from_directory failed")
            return IndexResult(success=False, message=str(e))

    def _index_dir(self, root_dir: Path, conversation_id: str) -> str:
        store = ConversationStore(conversation_id, Path("data/conversations"), self.embeddings)
        return index_directory(root_dir, conversation_id, store, self.manifest_path)

    def build_git_snapshot(
        self,
        conversation_id: str,
        repo_root: Optional[Path] = None,
        include_untracked: bool = False,
    ) -> str:
        root = repo_root or Path(".").resolve()
        tracked = set(_git_ls_tracked(root))
        include_untracked = INDEX_INCLUDE_UNTRACKED if include_untracked is None else include_untracked
        status_paths = set(_git_status_paths(root)) if include_untracked else set()
        candidates = tracked | status_paths

        snapshot_dir = Path("temp_repos") / conversation_id
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        for rel in sorted(candidates):
            src = root / rel
            if not src.is_file():
                continue
            rel_str = rel.replace("\\", "/")
            if _matches_globs(rel_str, INDEX_EXCLUDE_GLOBS):
                continue
            if INDEX_INCLUDE_GLOBS and not _matches_globs(rel_str, INDEX_INCLUDE_GLOBS):
                continue
            if any(skip in src.parts for skip in SKIP_DIR_NAMES):
                continue
            dest = snapshot_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dest)
                copied += 1
            except OSError:
                continue
        return f"Prepared git snapshot with {copied} files for {conversation_id}."

    def retrieve(self, conversation_id: str, query: str, top_k: int = 20) -> RetrievalResult:
        store = self._store(conversation_id)
        retriever = CodeRetriever(
            store,
            reranker=self.reranker,
            retrieve_candidates=RETRIEVE_CANDIDATES,
            rerank_top_k=min(top_k, RERANK_TOP_K),
            context_chunk_cap=CONTEXT_CHUNK_CAP,
            config=RetrievalConfig.from_settings(),
        )
        _block, entries, elapsed_ms = retriever.retrieve(query)
        chunks = [
            RetrievedChunk(
                content=e["content"],
                source=e["source"],
                score=e.get("score"),
                line_start=e.get("line_start"),
                line_end=e.get("line_end"),
                metadata=e,
            )
            for e in entries
        ]
        total_tokens = sum(c.metadata.get("est_tokens", 0) for c in chunks)
        return RetrievalResult(
            chunks=chunks,
            total_tokens=total_tokens,
            retrieval_time_ms=elapsed_ms,
            context_block=_block,
        )

    def get_context(
        self,
        conversation_id: str,
        query: str,
        manual_items: Optional[List[Dict[str, Any]]] = None,
        allow_rag: bool = True,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        if manual_items:
            return build_manual_context(manual_items)
        if not allow_rag:
            return "", []

        store = self._store(conversation_id)
        retriever = CodeRetriever(
            store,
            reranker=self.reranker,
            retrieve_candidates=RETRIEVE_CANDIDATES,
            rerank_top_k=RERANK_TOP_K,
            context_chunk_cap=CONTEXT_CHUNK_CAP,
            config=RetrievalConfig.from_settings(),
        )
        block, entries, _ = retriever.retrieve(query)
        return block, entries

    def is_indexed(self, conversation_id: str) -> bool:
        store = self._store(conversation_id)
        return store.vectorstore is not None or store._faiss_path().exists()

    def clear_index(self, conversation_id: str) -> bool:
        store = self._store(conversation_id)
        store.clear()
        clear_store_cache(conversation_id)
        return True

    def estimate_tokens(self, text: str) -> int:
        return estimate_tokens(text)

    def rank_paths(self, paths: List[Path], query: str) -> List[Tuple[Path, float]]:
        if not paths:
            return []
        try:
            query_vec = self.embeddings.embed_query(query)
            contents = []
            for p in paths:
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")[:4000]
                except OSError:
                    text = ""
                contents.append(text)
            doc_vecs = self.embeddings.embed_documents(contents)
            ranked = [(p, _compute_cosine(query_vec, vec)) for p, vec in zip(paths, doc_vecs)]
            ranked.sort(key=lambda x: x[1], reverse=True)
            return ranked
        except Exception:
            logger.exception("rank_paths failed")
            return sorted([(p, 0.0) for p in paths], key=lambda x: len(str(x[0])))

    def get_manifest(self) -> Dict[str, Any]:
        return _load_manifest()

    def compute_index_delta(self, conversation_id: str) -> Dict[str, Any]:
        """Compare on-disk repo against last indexed manifest for a conversation."""
        manifest = _load_manifest()
        entry = manifest.get(conversation_id)
        if not entry:
            return {"has_index": False, "has_changes": False}

        root_str = entry.get("root")
        if not root_str:
            return {"has_index": True, "has_changes": False, "root_missing": True}

        root = Path(root_str)
        if not root.is_dir():
            return {
                "has_index": True,
                "has_changes": False,
                "root_missing": True,
                "root": root_str,
            }

        current = scan_repo_files(root)
        delta = diff_manifest(entry.get("files"), current)
        payload = delta.to_dict()
        payload.update({
            "has_index": True,
            "root_missing": False,
            "root": root_str,
            "indexed_at": entry.get("indexed_at"),
            "file_count": entry.get("file_count"),
            "chunk_count": entry.get("chunk_count"),
        })
        return payload

    def get_manifest_with_deltas(self) -> Dict[str, Any]:
        """Return manifest entries enriched with per-conversation delta status."""
        manifest = _load_manifest()
        enriched: Dict[str, Any] = {}
        for conversation_id, entry in manifest.items():
            enriched[conversation_id] = {
                **entry,
                "changed_since_index": self.compute_index_delta(conversation_id),
            }
        return enriched

    def iter_source_files(self, root: Path) -> List[Path]:
        return iter_source_files(root)


_default_provider: Optional[LMStudioRAGProvider] = None


def get_rag_provider() -> LMStudioRAGProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = LMStudioRAGProvider()
    return _default_provider