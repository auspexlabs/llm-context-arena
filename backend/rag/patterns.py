"""Load pattern rules and infer probabilistic graph edges."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

DEFAULT_PATTERNS_PATH = Path(__file__).parent / "patterns.yaml"


def load_pattern_config(path: Path | None = None) -> Dict[str, Any]:
    path = path or DEFAULT_PATTERNS_PATH
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def infer_pattern_edges(
    chunk_id: str,
    content: str,
    config: Dict[str, Any] | None = None,
) -> List[Tuple[str, str, float]]:
    """Return (source_id, relation, weight) edges inferred from content."""
    config = config or load_pattern_config()
    edges: List[Tuple[str, str, float]] = []

    for _group, spec in config.items():
        if not isinstance(spec, dict):
            continue
        weight = float(spec.get("weight", 0.5))
        for rule in spec.get("rules", []):
            pattern = rule.get("match")
            relation = rule.get("relation", "pattern")
            if not pattern:
                continue
            if re.search(pattern, content):
                edges.append((chunk_id, relation, weight))
    return edges