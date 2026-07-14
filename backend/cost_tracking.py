"""OpenRouter usage and cost aggregation for arena runs."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def empty_usage_fields() -> Dict[str, Any]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }


def usage_fields_from_response(resp: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Flatten OpenRouter usage from a query_model response."""
    if not resp or resp.get("_failed"):
        return empty_usage_fields()
    usage = resp.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    cost_raw = usage.get("cost")
    try:
        cost = float(cost_raw) if cost_raw is not None else 0.0
    except (TypeError, ValueError):
        cost = 0.0
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cost_usd": cost,
    }


def apply_usage_fields(target: Dict[str, Any], resp: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    target.update(usage_fields_from_response(resp))
    return target


def sum_usage_fields(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    prompt = completion = total = 0
    cost = 0.0
    calls = 0
    for item in items:
        if not item:
            continue
        p = int(item.get("prompt_tokens") or 0)
        c = int(item.get("completion_tokens") or 0)
        t = int(item.get("total_tokens") or 0)
        cu = float(item.get("cost_usd") or 0.0)
        item_calls = int(item.get("calls") or 0)
        if item_calls:
            calls += item_calls
        elif p or c or t or cu:
            calls += 1
        prompt += p
        completion += c
        total += t
        cost += cu
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cost_usd": round(cost, 6),
        "calls": calls,
    }


def summarize_turn_cost(steps: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Aggregate per-turn cost from metadata.steps."""
    summary = sum_usage_fields(steps or [])
    return {
        "turn_cost_usd": summary["cost_usd"],
        "prompt_tokens": summary["prompt_tokens"],
        "completion_tokens": summary["completion_tokens"],
        "total_tokens": summary["total_tokens"],
        "calls": summary["calls"],
    }


def summarize_conversation_cost(messages: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Sum turn costs across all assistant messages."""
    turns: List[Dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        meta = msg.get("metadata") or {}
        cost = meta.get("cost")
        if cost:
            turns.append(cost)
        elif meta.get("steps"):
            turns.append(summarize_turn_cost(meta.get("steps")))
    prompt = completion = total = calls = 0
    cost = 0.0
    for turn in turns:
        prompt += int(turn.get("prompt_tokens") or 0)
        completion += int(turn.get("completion_tokens") or 0)
        total += int(turn.get("total_tokens") or 0)
        calls += int(turn.get("calls") or 0)
        cost += float(turn.get("turn_cost_usd") or turn.get("cost_usd") or 0.0)
    return {
        "conversation_cost_usd": round(cost, 6),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "calls": calls,
        "turns": len(turns),
    }
