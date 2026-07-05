"""Per-conversation FAISS index and CodeRAG sidecar persistence."""

from __future__ import annotations

import json
import logging
import pickle
import time
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from .chunker import iter_source_files
from .colbert import LateInteractionIndex
from .entity_index import EntityIndex
from .graph import CodeGraph
from .types import CodeChunk

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    def embed_query(self, text: str) -> List[float]: ...
    def embed_documents(self, texts: List[str]) -> List[List[float]]: ...


class ConversationStore:
    """In-memory + on-disk index for one conversation."""

    def __init__(self, conversation_id: str, data_dir: Path, embedder: Embedder):
        self.conversation_id = conversation_id
        self.data_dir = data_dir
        self.embedder = embedder
        self.chunks: Dict[str, CodeChunk] = {}
        self.chunk_order: List[str] = []
        self.entity_index: Optional[EntityIndex] = None
        self.graph: Optional[CodeGraph] = None
        self.colbert_index: Optional[LateInteractionIndex] = None
        self.vectorstore: Optional[FAISS] = None

    def _base_path(self) -> Path:
        return self.data_dir / self.conversation_id

    def _faiss_path(self) -> Path:
        return Path("data") / "conversations" / f"{self.conversation_id}_faiss"

    def _chunks_path(self) -> Path:
        return Path("data") / "conversations" / f"{self.conversation_id}_chunks.pkl"

    def _entity_path(self) -> Path:
        return Path("data") / "conversations" / f"{self.conversation_id}_entities.pkl"

    def _graph_path(self) -> Path:
        return Path("data") / "conversations" / f"{self.conversation_id}_graph.pkl"

    def build_from_chunks(
        self,
        chunks: List[CodeChunk],
        root_dir: Path,
        manifest_path: Path,
    ) -> int:
        self.chunks = {c.chunk_id: c for c in chunks}
        self.chunk_order = [c.chunk_id for c in chunks]
        self.entity_index = EntityIndex.from_chunks(chunks)
        self.graph = CodeGraph.from_chunks(chunks, self.entity_index)
        self.colbert_index = LateInteractionIndex.from_chunks(chunks)

        texts: List[str] = []
        metadatas: List[dict] = []
        for idx, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = idx
            texts.append(chunk.index_text or chunk.content)
            metadatas.append(chunk.to_faiss_metadata(idx))

        if not texts:
            return 0

        self.vectorstore = FAISS.from_texts(texts, self.embedder, metadatas=metadatas)

        self._faiss_path().parent.mkdir(parents=True, exist_ok=True)
        self.vectorstore.save_local(str(self._faiss_path()))
        self._persist_sidecars(root_dir, manifest_path)
        return len(chunks)

    def _persist_sidecars(self, root_dir: Path, manifest_path: Path):
        with open(self._chunks_path(), "wb") as f:
            pickle.dump({"chunks": self.chunks, "order": self.chunk_order}, f)
        with open(self._entity_path(), "wb") as f:
            pickle.dump(self.entity_index, f)
        if self.graph:
            self.graph.save(self._graph_path())

        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}

        files_meta = []
        for src in iter_source_files(root_dir):
            try:
                stat = src.stat()
                files_meta.append({
                    "path": str(src.relative_to(root_dir)),
                    "bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                })
            except OSError:
                continue

        manifest[self.conversation_id] = {
            "root": str(root_dir),
            "file_count": len(files_meta),
            "indexed_at": time.time(),
            "chunk_count": len(self.chunks),
            "files": files_meta,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def load(self) -> bool:
        faiss_path = self._faiss_path()
        if not faiss_path.exists():
            return False
        try:
            self.vectorstore = FAISS.load_local(
                str(faiss_path),
                self.embedder,
                allow_dangerous_deserialization=True,
            )
        except Exception:
            logger.exception("Failed to load FAISS for %s", self.conversation_id)
            return False

        if self._chunks_path().exists():
            try:
                with open(self._chunks_path(), "rb") as f:
                    payload = pickle.load(f)
                self.chunks = payload.get("chunks", {})
                self.chunk_order = payload.get("order", list(self.chunks.keys()))
            except Exception:
                self._hydrate_chunks_from_faiss()

        if self._entity_path().exists():
            try:
                with open(self._entity_path(), "rb") as f:
                    self.entity_index = pickle.load(f)
            except Exception:
                self.entity_index = EntityIndex.from_chunks(list(self.chunks.values()))
        else:
            self.entity_index = EntityIndex.from_chunks(list(self.chunks.values()))

        self.graph = CodeGraph.load(self._graph_path()) or CodeGraph.from_chunks(
            list(self.chunks.values()), self.entity_index
        )
        self.colbert_index = LateInteractionIndex.from_chunks(list(self.chunks.values()))
        return True

    def _hydrate_chunks_from_faiss(self):
        if self.vectorstore is None:
            return
        try:
            store = self.vectorstore.docstore._dict  # type: ignore[attr-defined]
        except Exception:
            return
        for doc in store.values():
            meta = doc.metadata or {}
            cid = meta.get("chunk_id") or f"{meta.get('doc_id')}:{meta.get('chunk_index')}"
            chunk = CodeChunk(
                chunk_id=cid,
                source=meta.get("source", "unknown"),
                content=doc.page_content,
                line_start=int(meta.get("line_start", 1)),
                line_end=int(meta.get("line_end", 1)),
                chunk_type=meta.get("chunk_type", "text"),
                symbol=meta.get("symbol") or None,
                language=meta.get("language", "python"),
                metadata={"chunk_index": meta.get("chunk_index")},
            )
            self.chunks[cid] = chunk
        self.chunk_order = list(self.chunks.keys())

    def similarity_search(self, query: str, k: int) -> List[Tuple[CodeChunk, float]]:
        if self.vectorstore is None:
            return []
        docs: List[Document] = self.vectorstore.similarity_search_with_score(query, k=k)
        results: List[Tuple[CodeChunk, float]] = []
        for doc, distance in docs:
            meta = doc.metadata or {}
            cid = meta.get("chunk_id")
            chunk = self.chunks.get(cid) if cid else None
            if chunk is None:
                chunk = CodeChunk(
                    chunk_id=cid or "unknown",
                    source=meta.get("source", "unknown"),
                    content=doc.page_content,
                    line_start=int(meta.get("line_start", 1)),
                    line_end=int(meta.get("line_end", 1)),
                    chunk_type=meta.get("chunk_type", "text"),
                    symbol=meta.get("symbol") or None,
                )
            score = 1.0 / (1.0 + float(distance))
            results.append((chunk, score))
        return results

    def clear(self):
        self.chunks.clear()
        self.chunk_order.clear()
        self.entity_index = None
        self.graph = None
        self.colbert_index = None
        self.vectorstore = None
        for path in [self._faiss_path(), self._chunks_path(), self._entity_path(), self._graph_path()]:
            try:
                if path.is_dir():
                    import shutil
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            except OSError:
                pass


_STORES: Dict[str, ConversationStore] = {}


def get_or_load_store(
    conversation_id: str,
    embedder: Embedder,
    data_dir: Optional[Path] = None,
) -> ConversationStore:
    if conversation_id in _STORES and _STORES[conversation_id].vectorstore is not None:
        return _STORES[conversation_id]

    store = ConversationStore(conversation_id, data_dir or Path("data/conversations"), embedder)
    if store.load():
        _STORES[conversation_id] = store
        return store

    _STORES[conversation_id] = store
    return store


def register_store(store: ConversationStore):
    _STORES[store.conversation_id] = store


def clear_store_cache(conversation_id: Optional[str] = None):
    if conversation_id:
        _STORES.pop(conversation_id, None)
    else:
        _STORES.clear()