"""Backward-compatible facade over LMStudioRAGProvider (CodeRAG)."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import INDEX_INCLUDE_UNTRACKED
from .rag.chunker import iter_source_files as _iter_source_files_impl
from .rag.format import estimate_tokens as _estimate_tokens
from .rag_lmstudio_provider import get_rag_provider

_provider = None


def _p():
    global _provider
    if _provider is None:
        _provider = get_rag_provider()
    return _provider


def __getattr__(name: str):
    if name == "embeddings":
        return _p().embeddings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def index_repo_zip(zip_path: str, convo_id: str) -> str:
    return _p().index_from_zip(zip_path, convo_id).message


def index_repo_dir(root_dir: Path, convo_id: str) -> str:
    return _p().index_from_directory(root_dir, convo_id).message


def build_worktree_snapshot(
    convo_id: str,
    repo_root: Path | None = None,
    include_untracked: bool | None = None,
) -> str:
    flag = INDEX_INCLUDE_UNTRACKED if include_untracked is None else bool(include_untracked)
    return _p().build_git_snapshot(convo_id, repo_root=repo_root, include_untracked=flag)


def get_context(
    convo_id: str,
    query: str,
    manual_items: Optional[List[Dict[str, Any]]] = None,
    allow_rag: bool = True,
) -> Tuple[str, List[Dict[str, Any]]]:
    return _p().get_context(convo_id, query, manual_items, allow_rag)


def rank_paths_against_query(paths: List[Path], query: str) -> List[Tuple[Path, float]]:
    return _p().rank_paths(paths, query)


def _iter_source_files(root: Path) -> List[Path]:
    return _iter_source_files_impl(root)


def _load_manifest() -> Dict[str, Any]:
    return _p().get_manifest()