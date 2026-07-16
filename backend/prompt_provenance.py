"""Typed, UI-safe projections of Curia-owned prompt composition."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

from .prompts import render_prompt


PROMPT_PROVENANCE_VERSION = 1
_SLOT_PATTERN = re.compile(r"__CURIA_PROMPT_PROVENANCE_(\d+)__")


def text_part(text: str) -> Dict[str, Any]:
    return {"kind": "text", "text": text}


def context_ref(label: str = "Grounded question and repository context") -> Dict[str, Any]:
    return {"kind": "context_ref", "label": label, "target": "rag"}


def artifact_ref(
    label: str,
    *,
    producer_role: str,
    producer_model: str,
) -> Dict[str, Any]:
    return {
        "kind": "artifact_ref",
        "label": label,
        "producer": {"role": producer_role, "model": producer_model},
        "target": "answers",
    }


def provenance(parts: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "version": PROMPT_PROVENANCE_VERSION,
        "parts": _coalesce_text(list(parts)),
    }


def joined(parts: Iterable[Dict[str, Any]], separator: str = "") -> Dict[str, Any]:
    combined: List[Dict[str, Any]] = []
    for part in parts:
        if combined and separator:
            combined.append(text_part(separator))
        combined.append(part)
    return provenance(combined)


def render_projected_prompt(
    prompt_id: str,
    **variables: Any,
) -> Tuple[str, Dict[str, Any]]:
    """Render one prompt while retaining typed parts supplied in template slots."""
    projections: List[Dict[str, Any]] = []
    rendered_variables: Dict[str, Any] = {}
    for name, value in variables.items():
        if _is_provenance(value):
            slot = len(projections)
            projections.append(value)
            rendered_variables[name] = f"__CURIA_PROMPT_PROVENANCE_{slot}__"
        else:
            rendered_variables[name] = value

    rendered = render_prompt(prompt_id, **rendered_variables)
    parts: List[Dict[str, Any]] = []
    cursor = 0
    for match in _SLOT_PATTERN.finditer(rendered):
        if match.start() > cursor:
            parts.append(text_part(rendered[cursor : match.start()]))
        parts.extend(projections[int(match.group(1))]["parts"])
        cursor = match.end()
    if cursor < len(rendered):
        parts.append(text_part(rendered[cursor:]))

    result = provenance(parts)
    return render_provenance_text(result), result


def render_provenance_text(value: Dict[str, Any]) -> str:
    """Compatibility projection for existing orchestration_text consumers."""
    rendered: List[str] = []
    for part in value.get("parts") or []:
        kind = part.get("kind")
        if kind == "text":
            rendered.append(str(part.get("text") or ""))
        elif kind == "context_ref":
            rendered.append(
                f"[{part.get('label') or 'Grounded context'} attached separately; inspect RAG retrieval]"
            )
        elif kind == "artifact_ref":
            rendered.append(f"[{part.get('label') or 'model output'} artifact attached]")
    return "".join(rendered)


def _is_provenance(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("version") == PROMPT_PROVENANCE_VERSION
        and isinstance(value.get("parts"), list)
    )


def _coalesce_text(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for part in parts:
        if not part:
            continue
        if part.get("kind") == "text" and not part.get("text"):
            continue
        if compact and compact[-1].get("kind") == part.get("kind") == "text":
            compact[-1] = text_part(str(compact[-1].get("text") or "") + str(part["text"]))
        else:
            compact.append(dict(part))
    return compact
