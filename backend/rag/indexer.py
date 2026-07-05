"""Build conversation indexes from repository directories."""

from pathlib import Path

from .chunker import chunk_repository
from .store import ConversationStore, register_store


def index_directory(
    root_dir: Path,
    conversation_id: str,
    store: ConversationStore,
    manifest_path: Path,
) -> str:
    chunks = chunk_repository(root_dir)
    if not chunks:
        return "No suitable source files found to index."

    count = store.build_from_chunks(chunks, root_dir, manifest_path)
    register_store(store)
    return f"Indexed {count} AST-aware chunks for conversation {conversation_id}."