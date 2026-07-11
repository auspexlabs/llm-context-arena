"""Model failure classification enums and automated recommendations (DEC-018 Phase C)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional


class ModelFailureKind(str, Enum):
    RATE_LIMIT = "rate_limit"
    POLICY_BLOCKED = "policy_blocked"
    PRIVACY_BLOCKED = "privacy_blocked"
    CONTEXT_EXCEEDED = "context_exceeded"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


_CONTEXT_TOKENS = (
    "context length",
    "context window",
    "maximum context",
    "context exceeded",
    "too many tokens",
    "token limit",
    "max tokens",
)

_PRIVACY_TOKENS = (
    "privacy",
    "data policy",
    "training",
    "store data",
    "logging",
    "zdr",
    "zero data retention",
)

_TIMEOUT_TOKENS = (
    "timeout",
    "timed out",
    "deadline exceeded",
)


def _message_haystack(message: Any, provider: Any = None) -> str:
    return " ".join(str(part or "") for part in (message, provider)).lower()


def classify_model_failure(
    *,
    status: Any = None,
    message: Any = None,
    provider: Any = None,
) -> ModelFailureKind:
    """Map HTTP status + message heuristics to a stable failure kind."""
    haystack = _message_haystack(message, provider)

    if any(token in haystack for token in _CONTEXT_TOKENS):
        return ModelFailureKind.CONTEXT_EXCEEDED
    if any(token in haystack for token in _PRIVACY_TOKENS):
        return ModelFailureKind.PRIVACY_BLOCKED
    if any(token in haystack for token in _TIMEOUT_TOKENS):
        return ModelFailureKind.TIMEOUT

    try:
        code = int(status)
    except (TypeError, ValueError):
        return ModelFailureKind.UNKNOWN

    if code == 429:
        return ModelFailureKind.RATE_LIMIT
    if code in {404, 403}:
        return ModelFailureKind.POLICY_BLOCKED
    if code >= 500:
        return ModelFailureKind.SERVER_ERROR
    if code >= 400:
        return ModelFailureKind.CLIENT_ERROR
    return ModelFailureKind.UNKNOWN


def failure_status_class(
    failure: Optional[Dict[str, Any]] = None,
    *,
    status: Any = None,
    message: Any = None,
    provider: Any = None,
    failure_kind: Any = None,
) -> str:
    """Prometheus-safe status_class label for a failure record."""
    if failure_kind:
        kind = str(failure_kind)
    elif failure:
        kind = str(failure.get("failure_kind") or "")
        if not kind:
            kind = classify_model_failure(
                status=failure.get("status"),
                message=failure.get("message"),
                provider=failure.get("provider"),
            ).value
    else:
        kind = classify_model_failure(status=status, message=message, provider=provider).value

    if kind in {k.value for k in ModelFailureKind}:
        return kind
    return ModelFailureKind.UNKNOWN.value


def recommendation_for_failure_kind(kind: ModelFailureKind) -> str:
    """Actionable agent recommendation for a classified failure kind."""
    return {
        ModelFailureKind.RATE_LIMIT: (
            "Rate limited — wait and retry the same models; do not shrink context or "
            "switch to summarization as the first fix."
        ),
        ModelFailureKind.POLICY_BLOCKED: (
            "Provider blocked this model or endpoint — try a paid/non-free model or a "
            "different provider route."
        ),
        ModelFailureKind.PRIVACY_BLOCKED: (
            "OpenRouter privacy settings blocked the request — disable training/logging "
            "restrictions for this provider or choose a compatible model."
        ),
        ModelFailureKind.CONTEXT_EXCEEDED: (
            "Context window exceeded — retry with @tokenbudget, fewer RAG chunks, or "
            "a larger-context model; do not treat as a transient rate limit."
        ),
        ModelFailureKind.SERVER_ERROR: (
            "Upstream server error — retry once; if persistent, swap the failing model."
        ),
        ModelFailureKind.CLIENT_ERROR: (
            "Client/request error — verify model id, prompt size, and OpenRouter account limits."
        ),
        ModelFailureKind.TIMEOUT: (
            "Request timed out — retry with fewer models in parallel or a faster model."
        ),
        ModelFailureKind.UNKNOWN: (
            "Unclassified model failure — read metadata.model_failures and retry or inform the user."
        ),
    }[kind]


def enrich_failure_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Attach failure_kind to a model_failures metadata entry."""
    enriched = dict(record)
    kind = classify_model_failure(
        status=enriched.get("status"),
        message=enriched.get("message"),
        provider=enriched.get("provider"),
    )
    enriched["failure_kind"] = kind.value
    return enriched


def collect_failure_recommendations(failures: List[Dict[str, Any]]) -> List[str]:
    """Deduplicated recommendations ordered by failure severity."""
    priority = [
        ModelFailureKind.CONTEXT_EXCEEDED,
        ModelFailureKind.PRIVACY_BLOCKED,
        ModelFailureKind.RATE_LIMIT,
        ModelFailureKind.POLICY_BLOCKED,
        ModelFailureKind.TIMEOUT,
        ModelFailureKind.SERVER_ERROR,
        ModelFailureKind.CLIENT_ERROR,
        ModelFailureKind.UNKNOWN,
    ]
    seen_kinds: set[str] = set()
    ordered_kinds: List[ModelFailureKind] = []
    for failure in failures:
        kind_value = failure.get("failure_kind") or failure_status_class(failure)
        if kind_value in seen_kinds:
            continue
        seen_kinds.add(kind_value)
        try:
            ordered_kinds.append(ModelFailureKind(kind_value))
        except ValueError:
            ordered_kinds.append(ModelFailureKind.UNKNOWN)

    recs: List[str] = []
    for kind in priority:
        if kind in ordered_kinds:
            recs.append(recommendation_for_failure_kind(kind))
    for kind in ordered_kinds:
        if kind not in priority:
            recs.append(recommendation_for_failure_kind(kind))
    return recs