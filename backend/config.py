"""Configuration for LLM Context Arena."""

import logging
import os
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Arena models - list of OpenRouter model identifiers
ARENA_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "openai/gpt-5.1"

# Backwards compatibility alias
COUNCIL_MODELS = ARENA_MODELS  # Deprecated: use ARENA_MODELS

# Model context limits (input tokens) for budgeting; tweak via env overrides
MODEL_CONTEXT_LIMITS = {
    "openai/gpt-5.1": int(os.getenv("CTX_LIMIT_GPT_5_1", "400000")),
    "google/gemini-3-pro-preview": int(os.getenv("CTX_LIMIT_GEMINI_3_PRO_PREVIEW", "1048576")),
    "anthropic/claude-sonnet-4.5": int(os.getenv("CTX_LIMIT_CLAUDE_SONNET_4_5", "1000000")),
    "x-ai/grok-4": int(os.getenv("CTX_LIMIT_GROK_4", "256000")),
}

# Safety margin + output allowance (tokens) for budgeting
CONTEXT_SAFETY_MARGIN = float(os.getenv("CONTEXT_SAFETY_MARGIN", "0.85"))
OUTPUT_TOKEN_ALLOWANCE = int(os.getenv("OUTPUT_TOKEN_ALLOWANCE", "4000"))

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# LM Studio + RAG defaults
LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
LMSTUDIO_EMBED_MODEL = os.getenv(
    "LMSTUDIO_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5"
)
# Deprecated: rerank runs locally via sentence-transformers (DEC-009), not LM Studio.
LMSTUDIO_RERANK_MODEL = os.getenv("LMSTUDIO_RERANK_MODEL", "")
RERANK_MODEL = os.getenv("RERANK_MODEL", "jinaai/jina-reranker-v3")
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() in {"1", "true", "yes"}
QUERY_ROUTER = os.getenv("QUERY_ROUTER", "embedding").lower()  # embedding | regex
FUSION_MODE = os.getenv("FUSION_MODE", "rrf").lower()  # rrf | max_score
GRAPH_MODE = os.getenv("GRAPH_MODE", "append").lower()  # append | resort
SEMANTIC_BACKEND = os.getenv("SEMANTIC_BACKEND", "colbert").lower()  # colbert | biencoder
COLBERT_LEARNED = os.getenv("COLBERT_LEARNED", "true").lower() in {"1", "true", "yes"}
COLBERT_MODEL = os.getenv("COLBERT_MODEL", "colbert-ir/colbertv2.0")
COLBERT_DEVICE = os.getenv("COLBERT_DEVICE", "auto")  # auto | cuda | cpu
_COLBERT_DEVICE_RESOLVED: Optional[str] = None


def get_colbert_device() -> str:
    """Resolve ColBERT device: auto (default) uses cuda when available, else cpu."""
    global _COLBERT_DEVICE_RESOLVED
    if _COLBERT_DEVICE_RESOLVED is not None:
        return _COLBERT_DEVICE_RESOLVED

    raw = (os.getenv("COLBERT_DEVICE") or "auto").strip().lower()
    if raw in {"", "auto"}:
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
        logger.info("COLBERT_DEVICE=auto resolved to %s", device)
    elif raw in {"cuda", "gpu"}:
        device = "cuda"
    elif raw == "cpu":
        device = "cpu"
    else:
        device = raw
        logger.warning("Unknown COLBERT_DEVICE=%r; using as-is", raw)

    _COLBERT_DEVICE_RESOLVED = device
    return device
RETRIEVE_CANDIDATES = int(os.getenv("RETRIEVE_CANDIDATES", "50"))
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "20"))
CONTEXT_CHUNK_CAP = int(os.getenv("CONTEXT_CHUNK_CAP", "60"))

# Git-based indexing settings
INDEX_INCLUDE_GLOBS = (
    os.getenv("INDEX_INCLUDE_GLOBS", "").split(",") if os.getenv("INDEX_INCLUDE_GLOBS") else []
)
INDEX_EXCLUDE_GLOBS = (
    os.getenv("INDEX_EXCLUDE_GLOBS", "").split(",") if os.getenv("INDEX_EXCLUDE_GLOBS") else []
)
INDEX_INCLUDE_UNTRACKED = os.getenv("INDEX_INCLUDE_UNTRACKED", "true").lower() in {"1", "true", "yes"}
INDEX_MANIFEST_PATH = os.getenv("INDEX_MANIFEST_PATH", "data/index_manifest.json")
