"""In-process Prometheus-style metrics (DEC-018 A10, DEF-006 stack deferred)."""

from __future__ import annotations

import copy
import threading
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .frozen_config import get_frozen_snapshot

_LOCK = threading.Lock()

_COUNTERS: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
_GAUGES: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
_HISTOGRAMS: Dict[str, Dict[Tuple[Tuple[str, str], ...], Dict[str, float]]] = defaultdict(
    lambda: defaultdict(lambda: {"count": 0.0, "sum": 0.0})
)
_HISTOGRAM_BUCKETS: Dict[str, Tuple[float, ...]] = {}

_DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 90.0)
_TOKEN_BUCKETS = (100, 500, 1000, 2000, 5000, 10000, 25000, 50000, 100000)


def _label_key(labels: Dict[str, str]) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted((k, v) for k, v in labels.items()))


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(labels: Dict[str, str]) -> str:
    if not labels:
        return ""
    inner = ",".join(
        f'{k}="{_escape_label_value(v)}"' for k, v in sorted(labels.items())
    )
    return f"{{{inner}}}"


def increment_counter(name: str, value: float = 1.0, **labels: str) -> None:
    key = (name, _label_key(labels))
    with _LOCK:
        _COUNTERS[key] += value


def set_gauge(name: str, value: float, **labels: str) -> None:
    key = (name, _label_key(labels))
    with _LOCK:
        _GAUGES[key] = value


def observe_histogram(name: str, value: float, buckets: Tuple[float, ...], **labels: str) -> None:
    label_key = _label_key(labels)
    with _LOCK:
        if name not in _HISTOGRAM_BUCKETS:
            _HISTOGRAM_BUCKETS[name] = buckets
        hist = _HISTOGRAMS[name][label_key]
        hist["count"] += 1
        hist["sum"] += value
        for bound in buckets:
            bucket_key = f"le_{bound}"
            hist.setdefault(bucket_key, 0.0)
            if value <= bound:
                hist[bucket_key] += 1
        hist.setdefault("le_inf", 0.0)
        hist["le_inf"] += 1


def reset_metrics() -> None:
    """Clear all metrics (testing)."""
    with _LOCK:
        _COUNTERS.clear()
        _GAUGES.clear()
        _HISTOGRAMS.clear()
        _HISTOGRAM_BUCKETS.clear()


def record_turn_metrics(
    *,
    metadata: Optional[Dict[str, Any]] = None,
    quality: Optional[Dict[str, Any]] = None,
) -> None:
    """Record counters/histograms from a completed turn."""
    meta = metadata or {}
    qual = quality or {}
    mode = (meta.get("mode") or qual.get("mode") or "council").lower()
    severity = qual.get("severity") or "ok"

    increment_counter("arena_turns_total", mode=mode, quality_severity=severity)

    from .model_failures import failure_status_class

    for failure in meta.get("model_failures") or []:
        increment_counter(
            "arena_model_failures_total",
            status_class=failure_status_class(failure),
        )

    budget_decisions = meta.get("budget_decisions") or {}
    if isinstance(budget_decisions, dict):
        for decision in budget_decisions.values():
            components = (decision or {}).get("components") or {}
            for component, tokens in components.items():
                if component == "total" or not isinstance(tokens, (int, float)):
                    continue
                observe_histogram(
                    "arena_prompt_tokens",
                    float(tokens),
                    _TOKEN_BUCKETS,
                    component=component,
                )

    for job in meta.get("summarize_jobs") or []:
        outcome = str(job.get("outcome") or "unknown")
        prompt_id = str(job.get("prompt_id") or "unknown")
        cache_hit = "true" if job.get("cache_hit") else "false"
        increment_counter("arena_summarize_jobs_total", outcome=outcome)
        duration_ms = job.get("duration_ms") or 0
        observe_histogram(
            "arena_summarize_duration_seconds",
            float(duration_ms) / 1000.0,
            _DURATION_BUCKETS,
            prompt_id=prompt_id,
            cache_hit=cache_hit,
        )

    pending = qual.get("observation_pending") or meta.get("observation_pending") or []
    set_gauge("arena_catalog_limit_delta", float(len(pending)))

    try:
        snap = get_frozen_snapshot()
        set_gauge("arena_config_freeze_generation", float(snap.generation))
    except Exception:
        pass


def _snapshot_metrics() -> Tuple[
    Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float],
    Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float],
    Dict[str, Dict[Tuple[Tuple[str, str], ...], Dict[str, float]]],
    Dict[str, Tuple[float, ...]],
]:
    with _LOCK:
        return (
            copy.deepcopy(_COUNTERS),
            copy.deepcopy(_GAUGES),
            copy.deepcopy(_HISTOGRAMS),
            dict(_HISTOGRAM_BUCKETS),
        )


def render_prometheus() -> str:
    """Render all metrics in Prometheus text exposition format."""
    counters, gauges, histograms, histogram_buckets = _snapshot_metrics()
    lines: List[str] = []

    counter_names = sorted({name for name, _ in counters})
    for name in counter_names:
        lines.append(f"# HELP {name} Arena metric {name}")
        lines.append(f"# TYPE {name} counter")
        for (metric_name, label_key), value in sorted(counters.items()):
            if metric_name != name:
                continue
            labels = dict(label_key)
            lines.append(f"{name}{_format_labels(labels)} {value}")

    gauge_names = sorted({name for name, _ in gauges})
    for name in gauge_names:
        lines.append(f"# HELP {name} Arena metric {name}")
        lines.append(f"# TYPE {name} gauge")
        for (metric_name, label_key), value in sorted(gauges.items()):
            if metric_name != name:
                continue
            labels = dict(label_key)
            lines.append(f"{name}{_format_labels(labels)} {value}")

    for name in sorted(histograms):
        lines.append(f"# HELP {name} Arena metric {name}")
        lines.append(f"# TYPE {name} histogram")
        buckets = histogram_buckets.get(name, _TOKEN_BUCKETS)
        for label_key, hist in sorted(histograms[name].items()):
            labels = dict(label_key)
            for bound in buckets:
                bucket_val = hist.get(f"le_{bound}", 0.0)
                bucket_labels = {**labels, "le": str(bound)}
                lines.append(f"{name}_bucket{_format_labels(bucket_labels)} {bucket_val}")
            inf_labels = {**labels, "le": "+Inf"}
            lines.append(f"{name}_bucket{_format_labels(inf_labels)} {hist.get('le_inf', 0.0)}")
            lines.append(f"{name}_sum{_format_labels(labels)} {hist.get('sum', 0.0)}")
            lines.append(f"{name}_count{_format_labels(labels)} {hist.get('count', 0.0)}")

    return "\n".join(lines) + "\n"