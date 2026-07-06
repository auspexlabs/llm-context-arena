"""Build conversation indexes from repository directories."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from .chunker import chunk_file, chunk_repository
from .manifest import ManifestDelta, diff_manifest, scan_repo_files
from .store import ConversationStore, register_store
from .types import CodeChunk

logger = logging.getLogger(__name__)


def _load_manifest_entry(manifest_path: Path, conversation_id: str) -> Optional[dict]:
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return manifest.get(conversation_id)


def merge_chunks_for_delta(
    existing_chunks: Dict[str, CodeChunk],
    chunk_order: List[str],
    root_dir: Path,
    delta: ManifestDelta,
) -> List[CodeChunk]:
    """Keep chunks for unchanged files; replace chunks for added/changed/removed paths."""
    affected = set(delta.added + delta.changed + delta.removed)
    kept = [
        existing_chunks[cid]
        for cid in chunk_order
        if cid in existing_chunks and existing_chunks[cid].source not in affected
    ]
    new_chunks: List[CodeChunk] = []
    for rel in sorted(set(delta.added + delta.changed)):
        path = root_dir / rel
        if path.is_file():
            new_chunks.extend(chunk_file(path, root_dir))
    return kept + new_chunks


def index_directory(
    root_dir: Path,
    conversation_id: str,
    store: ConversationStore,
    manifest_path: Path,
) -> str:
    current_files = scan_repo_files(root_dir)
    prior_entry = _load_manifest_entry(manifest_path, conversation_id)

    if prior_entry and prior_entry.get("files"):
        delta = diff_manifest(prior_entry["files"], current_files)
        if not delta.has_changes:
            return f"No changes since last index for conversation {conversation_id}."

        if store.load_chunks_only():
            merged = merge_chunks_for_delta(store.chunks, store.chunk_order, root_dir, delta)
            if not merged:
                return "No suitable source files found to index."
            count = store.build_from_chunks(merged, root_dir, manifest_path)
            register_store(store)
            return (
                f"Delta reindexed {count} chunks for {conversation_id} "
                f"(+{len(delta.added)} ~{len(delta.changed)} -{len(delta.removed)})."
            )
        logger.info(
            "Prior manifest for %s but chunks missing; falling back to full reindex",
            conversation_id,
        )

    chunks = chunk_repository(root_dir)
    if not chunks:
        return "No suitable source files found to index."

    count = store.build_from_chunks(chunks, root_dir, manifest_path)
    register_store(store)
    return f"Indexed {count} AST-aware chunks for conversation {conversation_id}."