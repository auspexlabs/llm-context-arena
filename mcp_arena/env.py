"""Curia MCP/client environment variables (CURIA_* preferred; ARENA_* legacy)."""

from __future__ import annotations

import os


def env_prefixed(primary: str, legacy: str, default: str | None = None) -> str | None:
    return os.getenv(primary) or os.getenv(legacy) or default


def env_int_prefixed(primary: str, legacy: str, default: int) -> int:
    raw = env_prefixed(primary, legacy)
    return int(raw) if raw is not None else default