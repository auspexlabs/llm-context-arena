"""Repository browsing and indexing endpoints."""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..config import INDEX_INCLUDE_UNTRACKED
from ..dependencies import get_rag_provider_dep, get_storage_service, load_runtime_settings
from ..rag_lmstudio import (
    _iter_source_files,
    _load_manifest,
    build_worktree_snapshot,
    index_repo_dir,
    index_repo_zip,
    rank_paths_against_query,
)
from ..storage_service import StorageService

router = APIRouter()
logger = logging.getLogger(__name__)


def _snapshot_root(conversation_id: str) -> Path:
    return Path("temp_repos") / conversation_id


def _safe_child(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Path is outside repository root"
        ) from exc
    return target


def _tree_entry(node: Path, root: Path) -> dict[str, Any]:
    relative = node.relative_to(root)
    if node.is_dir():
        children = sorted(
            node.iterdir(),
            key=lambda path: (not path.is_dir(), path.name.casefold()),
        )
        return {
            "type": "dir",
            "name": node.name,
            "path": str(relative),
            "children": [_tree_entry(child, root) for child in children],
        }
    return {"type": "file", "name": node.name, "path": str(relative)}


def _read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


@router.get("/api/conversations/{conversation_id}/repo_tree")
async def repository_tree(conversation_id: str):
    root = _snapshot_root(conversation_id)
    if not root.exists():
        logger.warning(
            "Repository snapshot is missing (conversation=%s, path=%s)",
            conversation_id,
            root,
        )
        return []

    try:
        tree = _tree_entry(root, root)
        return tree.get("children", [])
    except OSError as exc:
        logger.exception("Could not read repository snapshot (conversation=%s)", conversation_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read repository tree: {exc}",
        ) from exc


@router.get("/api/conversations/{conversation_id}/file")
async def repository_file(conversation_id: str, path: str):
    root = _snapshot_root(conversation_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Repository not uploaded yet")

    target = _safe_child(root, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        content = _read_source(target)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}") from exc

    return {
        "path": path,
        "content": content,
        "lines": content.count("\n") + 1 if content else 0,
        "bytes": len(content.encode("utf-8", errors="ignore")),
    }


@router.get("/api/conversations/{conversation_id}/resolve_path")
async def resolve_repository_path(
    conversation_id: str,
    q: str,
    user_query: str | None = None,
    limit: int = 5,
):
    root = _snapshot_root(conversation_id)
    if not root.exists():
        return {"matches": []}

    candidates = [
        path
        for path in _iter_source_files(root)
        if q.casefold() in str(path.relative_to(root)).casefold()
    ]
    if user_query and len(candidates) > 1:
        ranked = rank_paths_against_query(candidates, user_query)
    else:
        ranked = [(path, 0.0) for path in candidates]

    matches = []
    for path, score in ranked[: max(0, limit)]:
        try:
            content = _read_source(path)
        except OSError:
            content = ""
        matches.append(
            {
                "path": str(path.relative_to(root)),
                "score": score,
                "content": content,
                "lines": content.count("\n") + 1 if content else 0,
                "bytes": len(content.encode("utf-8", errors="ignore")),
            }
        )
    return {"matches": matches}


@router.get("/api/conversations/{conversation_id}/search")
async def search_repository(conversation_id: str, q: str, limit: int = 3):
    root = _snapshot_root(conversation_id)
    if not root.exists() or limit <= 0:
        return {"results": []}

    needle = q.casefold()
    results = []
    for path in _iter_source_files(root):
        try:
            content = _read_source(path)
        except OSError:
            continue
        match_at = content.casefold().find(needle)
        if match_at < 0:
            continue

        results.append(
            {
                "path": str(path.relative_to(root)),
                "snippet": content[max(0, match_at - 120) : match_at + 120],
                "lines": content.count("\n") + 1,
                "bytes": len(content.encode("utf-8", errors="ignore")),
            }
        )
        if len(results) >= limit:
            break
    return {"results": results}


@router.post("/api/conversations/{conversation_id}/upload_repo")
async def upload_repository(
    conversation_id: str,
    file: UploadFile = File(...),
    storage: StorageService = Depends(get_storage_service),
):
    filename = file.filename or ""
    if not filename.casefold().endswith(".zip"):
        return {"status": "error", "message": "Please upload a .zip file."}

    started_at = time.monotonic()
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temporary:
            temporary.write(await file.read())
            temporary_path = Path(temporary.name)

        message = index_repo_zip(str(temporary_path), conversation_id)
        storage.set_repository(conversation_id, filename)
        elapsed = time.monotonic() - started_at
        return {"status": "success", "message": f"{message} (took {elapsed:.2f}s)"}
    except Exception as exc:
        elapsed = time.monotonic() - started_at
        logger.exception("Repository upload indexing failed (conversation=%s)", conversation_id)
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Failed to index repo: {exc} (after {elapsed:.2f}s)",
            },
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@router.post("/api/conversations/{conversation_id}/reindex")
async def reindex_snapshot(conversation_id: str):
    root = _snapshot_root(conversation_id)
    if not root.is_dir():
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": (
                    f"No snapshot found for conversation {conversation_id}. "
                    "Upload a ZIP or reindex from git."
                ),
            },
        )
    try:
        return {"status": "success", "message": index_repo_dir(root, conversation_id)}
    except Exception as exc:
        logger.exception("Snapshot reindex failed (conversation=%s)", conversation_id)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Failed to reindex snapshot: {exc}"},
        )


@router.post("/api/conversations/{conversation_id}/reindex_git")
async def reindex_worktree(
    conversation_id: str,
    include_untracked: bool | None = None,
    repo_root: str | None = None,
    storage: StorageService = Depends(get_storage_service),
):
    settings = load_runtime_settings()
    root = Path(repo_root or settings.get("repo_root") or ".").resolve()
    if not root.is_dir():
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": f"Repo root does not exist or is not a directory: {root}",
                "repo_root": str(root),
                "include_untracked": include_untracked,
            },
        )

    include_untracked = INDEX_INCLUDE_UNTRACKED if include_untracked is None else include_untracked
    try:
        snapshot_message = build_worktree_snapshot(
            conversation_id,
            repo_root=root,
            include_untracked=bool(include_untracked),
        )
        index_message = index_repo_dir(_snapshot_root(conversation_id), conversation_id)
        storage.set_repository(conversation_id, str(root))
        return {
            "status": "success",
            "message": f"{snapshot_message} {index_message}",
            "include_untracked": bool(include_untracked),
            "repo_root": str(root),
        }
    except Exception as exc:
        logger.exception("Worktree reindex failed (conversation=%s)", conversation_id)
        error = str(exc)
        hint = ""
        if "Connection error" in error or "Connection refused" in error:
            hint = (
                " LM Studio is only required when SEMANTIC_BACKEND=biencoder."
                " With colbert, ensure ColBERT can load; try COLBERT_DEVICE=cpu."
            )
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Snapshot copied but indexing failed: {error}.{hint}",
                "include_untracked": bool(include_untracked),
                "repo_root": str(root),
            },
        )


@router.get("/api/index_manifest")
async def index_manifest(conversation_id: str | None = None, repo_root: str | None = None):
    provider = get_rag_provider_dep()
    settings = load_runtime_settings()
    live_root: Path | None = None
    configured_root = repo_root or settings.get("repo_root")
    if configured_root:
        candidate = Path(configured_root).resolve()
        if candidate.is_dir():
            live_root = candidate

    if conversation_id:
        entry = _load_manifest().get(conversation_id)
        delta = provider.compute_index_delta(conversation_id, repo_root=live_root)
        if entry is None:
            return {
                "conversation_id": conversation_id,
                "has_index": False,
                "changed_since_index": delta,
            }
        return {**entry, "changed_since_index": delta}

    manifest = provider.get_manifest_with_deltas()
    if live_root:
        for indexed_conversation, entry in manifest.items():
            entry["changed_since_index"] = provider.compute_index_delta(
                indexed_conversation, repo_root=live_root
            )
    return manifest
