"""Environment-backed defaults used by Curia's runtime services."""

from __future__ import annotations

import logging
import os
from typing import Optional

from dotenv import load_dotenv

from .squad_presets import resolve_startup_squad

load_dotenv()
logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _env_csv(name: str) -> list[str]:
    return [part.strip() for part in os.getenv(name, "").split(",") if part.strip()]


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = os.getenv(
    "OPENROUTER_API_URL",
    "https://openrouter.ai/api/v1/chat/completions",
)

_startup_squad = resolve_startup_squad(os.getenv("ARENA_SQUAD"))
ARENA_SQUAD: str = _startup_squad["name"]
ARENA_MODELS: list[str] = list(_startup_squad["arena_models"])
CHAIRMAN_MODEL: str = _startup_squad["chairman_model"]
COUNCIL_MODELS = ARENA_MODELS  # Compatibility alias; remove with DEF-011.

DEFAULT_MODEL_CONTEXT_LIMIT = int(os.getenv("DEFAULT_MODEL_CONTEXT_LIMIT", "131072"))
MODEL_CONTEXT_LIMITS = {
    "meta-llama/llama-3.3-70b-instruct:free": 131_072,
    "qwen/qwen3-coder:free": 1_048_576,
    "nvidia/nemotron-3-super-120b-a12b:free": 1_000_000,
    "openai/gpt-oss-120b:free": 131_072,
    "cohere/north-mini-code:free": 256_000,
    "tencent/hy3:free": 262_144,
    "nousresearch/hermes-3-llama-3.1-405b:free": 131_072,
    "qwen/qwen3-next-80b-a3b-instruct:free": 262_144,
    "poolside/laguna-xs-2.1:free": 262_144,
    "google/gemini-2.5-pro": int(os.getenv("CTX_LIMIT_GEMINI_2_5_PRO", "1048576")),
    "google/gemini-3.1-pro-preview": 1_048_576,
    "anthropic/claude-sonnet-4.5": int(
        os.getenv("CTX_LIMIT_CLAUDE_SONNET_4_5", "1000000")
    ),
    "openai/gpt-5.1": int(os.getenv("CTX_LIMIT_GPT_5_1", "400000")),
}
CONTEXT_SAFETY_MARGIN = float(os.getenv("CONTEXT_SAFETY_MARGIN", "0.85"))
OUTPUT_TOKEN_ALLOWANCE = int(os.getenv("OUTPUT_TOKEN_ALLOWANCE", "4000"))

DATA_DIR = os.getenv("CURIA_CONVERSATION_DIR", "data/conversations")

LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
LMSTUDIO_EMBED_MODEL = os.getenv(
    "LMSTUDIO_EMBED_MODEL",
    "text-embedding-nomic-embed-text-v1.5",
)
# Retained only for compatibility; DEC-009 moved reranking into Curia's process.
LMSTUDIO_RERANK_MODEL = os.getenv("LMSTUDIO_RERANK_MODEL", "")
RERANK_MODEL = os.getenv("RERANK_MODEL", "jinaai/jina-reranker-v3")
RERANK_ENABLED = _env_bool("RERANK_ENABLED", True)
QUERY_ROUTER = os.getenv("QUERY_ROUTER", "embedding").casefold()
FUSION_MODE = os.getenv("FUSION_MODE", "rrf").casefold()
GRAPH_MODE = os.getenv("GRAPH_MODE", "append").casefold()
SEMANTIC_BACKEND = os.getenv("SEMANTIC_BACKEND", "colbert").casefold()
COLBERT_LEARNED = _env_bool("COLBERT_LEARNED", True)
COLBERT_MODEL = os.getenv("COLBERT_MODEL", "colbert-ir/colbertv2.0")
COLBERT_DEVICE = os.getenv("COLBERT_DEVICE", "auto")
_COLBERT_DEVICE_RESOLVED: Optional[str] = None


def _cuda_usable_for_colbert() -> bool:
    """Probe whether the configured torch install can allocate a CUDA tensor."""
    from .cuda_bootstrap import ensure_nvidia_cuda_libs

    if not ensure_nvidia_cuda_libs():
        return False
    try:
        import torch

        if not torch.cuda.is_available():
            return False
        torch.zeros(1, device="cuda")
    except Exception as exc:
        logger.warning(
            "ColBERT CUDA probe failed (%s); falling back to CPU. "
            "Repair the torch CUDA installation with `uv sync --reinstall-package torch`.",
            exc,
        )
        return False
    return True


def get_colbert_device() -> str:
    """Resolve and cache the device used by learned late-interaction retrieval."""
    global _COLBERT_DEVICE_RESOLVED
    if _COLBERT_DEVICE_RESOLVED:
        return _COLBERT_DEVICE_RESOLVED

    requested = os.getenv("COLBERT_DEVICE", COLBERT_DEVICE).strip().casefold() or "auto"
    if requested in {"auto", "cuda", "gpu"}:
        resolved = "cuda" if _cuda_usable_for_colbert() else "cpu"
        if requested != "auto" and resolved == "cpu":
            logger.warning("COLBERT_DEVICE=%s requested but CUDA is unavailable", requested)
    elif requested == "cpu":
        resolved = "cpu"
    else:
        resolved = requested
        logger.warning("Passing unrecognized COLBERT_DEVICE=%r to the backend", requested)

    _COLBERT_DEVICE_RESOLVED = resolved
    logger.info("ColBERT device resolved to %s", resolved)
    return resolved


RETRIEVE_CANDIDATES = int(os.getenv("RETRIEVE_CANDIDATES", "50"))
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "20"))
CONTEXT_CHUNK_CAP = int(os.getenv("CONTEXT_CHUNK_CAP", "60"))

INDEX_INCLUDE_GLOBS = _env_csv("INDEX_INCLUDE_GLOBS")
INDEX_EXCLUDE_GLOBS = _env_csv("INDEX_EXCLUDE_GLOBS")
INDEX_INCLUDE_UNTRACKED = _env_bool("INDEX_INCLUDE_UNTRACKED", True)
INDEX_MANIFEST_PATH = os.getenv("INDEX_MANIFEST_PATH", "data/index_manifest.json")
