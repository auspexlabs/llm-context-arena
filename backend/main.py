"""FastAPI backend for LLM Context Arena."""

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.responses import JSONResponse
import logging
import os
import tempfile
import time
import uuid
import json
import asyncio

from fastapi import UploadFile, File
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple

from . import storage
from .arena import run_full_arena, generate_conversation_title
from .config import (
    ARENA_MODELS,
    CHAIRMAN_MODEL,
    INDEX_INCLUDE_UNTRACKED,
)
from .run_turn import run_turn
from .routes.turns import router as turns_router
from .routes.execution import router as execution_router
from .routes.prompts import router as prompts_router
from .routes.metrics import router as metrics_router
from .dependencies import (
    get_context_engine,
    get_settings,
    get_storage_service,
    get_rag_provider_dep,
    apply_squad_preset,
    load_runtime_settings,
    save_runtime_settings,
)
from .squad_presets import list_squad_summaries
from .storage import reset_conversation
from .storage_service import StorageService
from .rag_lmstudio import (
    index_repo_zip,
    _iter_source_files,
    rank_paths_against_query,
    build_worktree_snapshot,
    index_repo_dir,
    _load_manifest,
)

app = FastAPI(title="LLM Context Arena API")
logger = logging.getLogger(__name__)
app.include_router(turns_router)
app.include_router(execution_router)
app.include_router(prompts_router)
app.include_router(metrics_router)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    mode: str = "council"


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str
    manual_context: List[Dict[str, Any]] | None = None
    # Future: accept structured directives; currently parsed inline.


def _repo_root(conversation_id: str) -> Path:
    return Path("temp_repos") / conversation_id


def _safe_resolve(root: Path, target: Path) -> Path:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if not str(target_resolved).startswith(str(root_resolved)):
        raise HTTPException(status_code=400, detail="Path is outside repository root")
    return target_resolved


def _build_tree(node: Path, base: Path) -> Dict[str, Any]:
    rel_path = node.relative_to(base)
    if node.is_dir():
        children = sorted(node.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        return {
            "type": "dir",
            "name": node.name,
            "path": str(rel_path),
            "children": [_build_tree(child, base) for child in children],
        }
    else:
        return {
            "type": "file",
            "name": node.name,
            "path": str(rel_path),
        }


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int
    mode: str | None = "council"


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]
    mode: str = "council"


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Context Arena API"}


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations(
    storage_svc: StorageService = Depends(get_storage_service),
):
    """List all conversations (metadata only)."""
    return storage_svc.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(
    request: CreateConversationRequest,
    storage_svc: StorageService = Depends(get_storage_service),
):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage_svc.create_conversation(conversation_id, request.mode)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: str,
    storage_svc: StorageService = Depends(get_storage_service),
):
    """Get a specific conversation with all its messages."""
    conversation = storage_svc.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(
    conversation_id: str,
    request: SendMessageRequest,
    storage_svc: StorageService = Depends(get_storage_service),
    settings: Dict[str, Any] = Depends(get_settings),
):
    """
    Send a message and run the arena deliberation process.
    Returns the complete response with all stages.
    """
    if storage_svc.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        result = await run_turn(
            conversation_id=conversation_id,
            content=request.content,
            storage_svc=storage_svc,
            settings=settings,
            manual_context=request.manual_context,
            progress_cb=None,
            persist=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return result.response_dict


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(
    conversation_id: str,
    request: SendMessageRequest,
    storage_svc: StorageService = Depends(get_storage_service),
):
    """
    Send a message and stream the arena deliberation process.
    Returns Server-Sent Events as each stage completes.
    """
    conversation = storage_svc.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        try:
            settings_local = load_runtime_settings()

            # Prepare context for early SSE (rag_context / summarization) before arena run
            ctx = await get_context_engine().prepare_context(
                conversation_id=conversation_id,
                user_input=request.content,
                mode=conversation.get("mode", "council"),
                manual_context=request.manual_context,
                conversation=conversation,
                arena_models=settings_local.get("arena_models", ARENA_MODELS),
                chairman_model=settings_local.get("chairman_model", CHAIRMAN_MODEL),
            )

            if ctx.directives.reset:
                reset_conversation(conversation_id)
                yield "data: " + json.dumps({"type": "reset", "message": "Conversation reset as requested."}) + "\n\n"
                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return

            if ctx.context_sources:
                yield "data: " + json.dumps({"type": "rag_context", "data": ctx.context_sources}) + "\n\n"
            if ctx.summarize_targets:
                yield "data: " + json.dumps({"type": "summarization", "data": {"models": list(ctx.summarize_targets.keys()), "targets": ctx.summarize_targets}}) + "\n\n"

            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"

            progress_events: asyncio.Queue = asyncio.Queue()

            async def _progress_cb(payload: Dict[str, Any]):
                await progress_events.put(payload)

            storage_svc.add_user_message(conversation_id, ctx.clean_query)

            runner_task = asyncio.create_task(
                run_turn(
                    conversation_id=conversation_id,
                    content=request.content,
                    storage_svc=storage_svc,
                    settings=settings_local,
                    manual_context=request.manual_context,
                    progress_cb=_progress_cb,
                    persist_user=False,
                    persist_assistant=False,
                    prepared_ctx=ctx,
                    schedule_title=is_first_message,
                )
            )

            while True:
                if runner_task.done():
                    break
                try:
                    payload = progress_events.get_nowait()
                    yield "data: " + json.dumps(payload) + "\n\n"
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.01)

            while not progress_events.empty():
                payload = await progress_events.get()
                yield "data: " + json.dumps(payload) + "\n\n"

            turn_result = await runner_task
            response = turn_result.response_dict
            stage1_results = response.get("stage1", [])
            stage2_results = response.get("stage2", [])
            stage3_result = response.get("stage3", {})
            mode_metadata = response.get("metadata", {})
            context_sources = turn_result.context_sources

            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "stage1_complete",
                        "data": stage1_results,
                        "metadata": {
                            "steps": mode_metadata.get("steps"),
                            "mode": mode_metadata.get("mode")
                            or conversation.get("mode", "council"),
                            "label_to_model": mode_metadata.get("label_to_model"),
                            "aggregate_rankings": mode_metadata.get("aggregate_rankings"),
                            "cost": mode_metadata.get("cost"),
                        },
                    }
                )
                + "\n\n"
            )

            if not stage1_results:
                err_msg = "No arena responses received; check model availability or API key."
                yield f"data: {json.dumps({'type': 'error', 'message': err_msg})}\n\n"
                storage_svc.add_assistant_message(
                    conversation_id,
                    [],
                    [],
                    {"model": "system", "response": err_msg},
                    context_sources,
                    metadata={"mode": conversation.get("mode", "council")},
                )
                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return

            if stage2_results:
                yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "stage2_complete",
                            "data": stage2_results,
                            "metadata": mode_metadata,
                        }
                    )
                    + "\n\n"
                )

            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            title_task = turn_result.title_task
            if title_task:
                title = await title_task
                storage_svc.update_conversation_title(conversation_id, title)
                yield (
                    "data: "
                    + json.dumps({"type": "title_complete", "data": {"title": title}})
                    + "\n\n"
                )

            storage_svc.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result,
                context_sources,
                metadata=mode_metadata,
            )

            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            logger.exception("Streaming failure (convo=%s)", conversation_id)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/conversations/{conversation_id}/repo_tree")
async def get_repo_tree(conversation_id: str):
    root = _repo_root(conversation_id)
    if not root.exists():
        logger.warning("Repo tree requested but path missing (convo=%s path=%s)", conversation_id, root)
        return []

    try:
        tree = _build_tree(root, root)
        return tree.get("children", []) if tree else []
    except Exception as e:
        logger.exception("Failed to build repo tree (convo=%s path=%s)", conversation_id, root)
        raise HTTPException(status_code=500, detail=f"Failed to read repo tree at {root}: {e}")


@app.get("/api/conversations/{conversation_id}/file")
async def get_file_contents(conversation_id: str, path: str):
    root = _repo_root(conversation_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Repository not uploaded yet")

    target = _safe_resolve(root, root / path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        content = target.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

    return {
        "path": path,
        "content": content,
        "lines": content.count("\n") + 1 if content else 0,
        "bytes": len(content.encode("utf-8", errors="ignore")),
    }


@app.get("/api/conversations/{conversation_id}/resolve_path")
async def resolve_path(conversation_id: str, q: str, user_query: str | None = None, limit: int = 5):
    root = _repo_root(conversation_id)
    if not root.exists():
        return {"matches": []}

    matches: List[Path] = []
    for path_obj in _iter_source_files(root):
        rel = path_obj.relative_to(root)
        if q.lower() in str(rel).lower():
            matches.append(path_obj)

    if not matches:
        return {"matches": []}

    ranked: List[Tuple[Path, float]]
    if len(matches) > 1 and user_query:
        ranked = rank_paths_against_query(matches, user_query)
    else:
        ranked = [(m, 0.0) for m in matches]

    ranked = ranked[:limit]

    results = []
    for path_obj, score in ranked:
        rel = path_obj.relative_to(root)
        try:
            content = path_obj.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            content = ""
        results.append(
            {
                "path": str(rel),
                "score": score,
                "content": content,
                "lines": content.count("\n") + 1 if content else 0,
                "bytes": len(content.encode("utf-8", errors="ignore")),
            }
        )

    return {"matches": results}


@app.get("/api/conversations/{conversation_id}/search")
async def search_repo(conversation_id: str, q: str, limit: int = 3):
    root = _repo_root(conversation_id)
    if not root.exists():
        return {"results": []}

    q_lower = q.lower()
    results = []
    for path_obj in _iter_source_files(root):
        try:
            content = path_obj.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        idx = content.lower().find(q_lower)
        if idx == -1:
            continue

        start = max(0, idx - 120)
        end = min(len(content), idx + 120)
        snippet = content[start:end]

        results.append(
            {
                "path": str(path_obj.relative_to(root)),
                "snippet": snippet,
                "lines": content.count("\n") + 1,
                "bytes": len(content.encode("utf-8", errors="ignore")),
            }
        )

        if len(results) >= limit:
            break

    return {"results": results}


@app.post("/api/conversations/{conversation_id}/upload_repo")
async def upload_repo(conversation_id: str, file: UploadFile = File(...)):
    """
    Upload a repository as a .zip and index it for this conversation.
    Uses local LM Studio embeddings + FAISS (see backend/rag_lmstudio.py).
    """
    if not file.filename.lower().endswith(".zip"):
        return {"status": "error", "message": "Please upload a .zip file."}

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = tmp.name

    start = time.monotonic()
    try:
        msg = index_repo_zip(tmp_path, conversation_id)
        duration = time.monotonic() - start
        return {"status": "success", "message": f"{msg} (took {duration:.2f}s)"}
    except Exception as e:
        # Surface indexing errors to the client instead of 500ing.
        duration = time.monotonic() - start
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Failed to index repo: {str(e)} (after {duration:.2f}s)",
            },
        )
    finally:
        # Clean up temp file
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@app.post("/api/conversations/{conversation_id}/reindex")
async def reindex_snapshot(conversation_id: str):
    """Re-run indexing on the existing conversation snapshot (ZIP upload dir)."""
    root = Path("temp_repos") / conversation_id
    if not root.is_dir():
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": f"No snapshot found for conversation {conversation_id}. Upload a ZIP or reindex from git.",
            },
        )
    try:
        result = index_repo_dir(root, conversation_id)
        return {"status": "success", "message": result}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Failed to reindex snapshot: {e}",
            },
        )


@app.post("/api/conversations/{conversation_id}/reindex_git")
async def reindex_git(conversation_id: str, include_untracked: bool | None = None, repo_root: str | None = None):
    """
    Index the current git working tree for this conversation.
    """
    settings_local = load_runtime_settings()
    root = Path(repo_root or settings_local.get("repo_root") or ".").resolve()
    if not root.exists() or not root.is_dir():
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": f"Repo root does not exist or is not a directory: {root}",
                "repo_root": str(root),
                "include_untracked": include_untracked,
            },
        )
    include_untracked = (
        INDEX_INCLUDE_UNTRACKED if include_untracked is None else bool(include_untracked)
    )
    try:
        msg = build_worktree_snapshot(conversation_id, repo_root=root, include_untracked=include_untracked)
        result = index_repo_dir(Path("temp_repos") / conversation_id, conversation_id)
        return {
            "status": "success",
            "message": f"{msg} {result}",
            "include_untracked": include_untracked,
            "repo_root": str(root),
        }
    except Exception as e:
        err = str(e)
        hint = ""
        if "Connection error" in err or "Connection refused" in err:
            hint = (
                " LM Studio is only required when SEMANTIC_BACKEND=biencoder. "
                "With colbert (default), ensure ColBERT can load — try COLBERT_DEVICE=cpu in .env."
            )
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Snapshot copied but indexing failed: {err}.{hint}",
                "include_untracked": include_untracked,
                "repo_root": str(root),
            },
        )


@app.get("/api/index_manifest")
async def index_manifest(conversation_id: str | None = None, repo_root: str | None = None):
    """Return index manifest with per-conversation 'changed since last index' deltas."""
    provider = get_rag_provider_dep()
    settings_local = load_runtime_settings()
    live_root = None
    root_candidate = repo_root or settings_local.get("repo_root")
    if root_candidate:
        candidate = Path(root_candidate).resolve()
        if candidate.is_dir():
            live_root = candidate

    if conversation_id:
        manifest = _load_manifest()
        entry = manifest.get(conversation_id)
        delta = provider.compute_index_delta(conversation_id, repo_root=live_root)
        if entry is None:
            return {
                "conversation_id": conversation_id,
                "has_index": False,
                "changed_since_index": delta,
            }
        return {
            **entry,
            "changed_since_index": delta,
        }

    enriched = provider.get_manifest_with_deltas()
    if live_root:
        for conv_id in list(enriched.keys()):
            enriched[conv_id]["changed_since_index"] = provider.compute_index_delta(
                conv_id, repo_root=live_root
            )
    return enriched


@app.get("/api/settings")
async def get_settings():
    """Return runtime settings (arena models/chairman)."""
    return load_runtime_settings()


class UpdateSettingsRequest(BaseModel):
    arena_models: List[str] | None = None
    chairman_model: str | None = None
    theme: str | None = None  # "light" | "dark"
    repo_root: str | None = None


@app.post("/api/settings")
async def update_settings(payload: UpdateSettingsRequest):
    data = payload.dict(exclude_none=True)
    saved = save_runtime_settings(data)
    return saved


@app.get("/api/settings/squads")
async def list_settings_squads():
    """List arena squad presets (JSON files under backend/squads/)."""
    return {"squads": list_squad_summaries()}


@app.post("/api/settings/squad/{squad_name}")
async def apply_settings_squad(squad_name: str):
    """Apply a squad preset to runtime settings (arena_models + chairman)."""
    try:
        return apply_squad_preset(squad_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
