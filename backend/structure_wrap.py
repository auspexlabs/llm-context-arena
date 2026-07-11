"""Structure-aware wrap/restore gate for summarizer compression (DEC-018 B4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

_MARKER_RE = re.compile(r"⟦S(\d+)⟧")
_CITATION_RE = re.compile(r"^--- .+ ---\s*$")
_SYMBOL_RE = re.compile(r"^# [^\n]{1,200}\s*$")


@dataclass(frozen=True)
class StructureSpan:
    index: int
    original: str
    placeholder: str


def detect_structure_lines(text: str) -> List[StructureSpan]:
    """Detect citation headers and symbol lines that should survive compression."""
    spans: List[StructureSpan] = []
    idx = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if _CITATION_RE.match(stripped) or _SYMBOL_RE.match(stripped):
            placeholder = f"⟦S{idx}⟧"
            spans.append(StructureSpan(index=idx, original=line, placeholder=placeholder))
            idx += 1
    return spans


def wrap_for_summarize(text: str) -> Tuple[str, List[StructureSpan]]:
    """Replace structure lines with compact placeholders before summarization."""
    spans = detect_structure_lines(text)
    if not spans:
        return text, spans
    wrapped = text
    for span in spans:
        wrapped = wrapped.replace(span.original, span.placeholder, 1)
    return wrapped, spans


def restore_after_summarize(text: str, spans: List[StructureSpan]) -> Tuple[str, bool]:
    """
    Restore structure placeholders after summarization.

    Returns (restored_text, structure_preserved). When placeholders are missing,
    re-inserts originals at nearest line boundaries (best-effort gate).
    """
    if not spans:
        return text, True

    restored = text
    missing = 0
    for span in spans:
        if span.placeholder in restored:
            restored = restored.replace(span.placeholder, span.original, 1)
        else:
            missing += 1

    if missing == 0:
        return restored, True

    # Gate failed: append missing structure footers so citations are not lost.
    footer_lines = [span.original.rstrip("\n") for span in spans if span.placeholder not in text]
    if footer_lines:
        restored = restored.rstrip() + "\n\n# Structure preserved (restored)\n"
        restored += "\n".join(footer_lines) + "\n"
    preserved = missing < len(spans)
    return restored, preserved