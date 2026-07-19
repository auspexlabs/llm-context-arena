"""Typed OpenRouter transport and Curia failure normalization."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from .config import OPENROUTER_API_KEY, OPENROUTER_API_URL
from .model_failures import enrich_failure_record

logger = logging.getLogger(__name__)
ModelPayload = dict[str, Any]
Message = dict[str, str]


def is_query_failure(response: ModelPayload | None) -> bool:
    return bool(response and response.get("_failed") is True)


def is_usable_response(response: ModelPayload | None) -> bool:
    if not response or is_query_failure(response):
        return False
    return bool(str(response.get("content") or "").strip())


def _failure_response(model: str, error: ModelPayload) -> ModelPayload:
    return {
        "_failed": True,
        "model": model,
        "content": None,
        "error_status": error.get("code"),
        "error_message": error.get("message"),
        "error_provider": error.get("provider"),
        "error_raw": error.get("raw"),
        "usage": {},
    }


def failure_record(
    model: str,
    response: ModelPayload | None,
    *,
    stage: str,
    role: str,
) -> ModelPayload:
    """Project one provider result into Curia's canonical failure metadata."""
    if is_query_failure(response):
        assert response is not None
        detail = {
            "model": model,
            "stage": stage,
            "role": role,
            "status": response.get("error_status"),
            "message": response.get("error_message"),
            "provider": response.get("error_provider"),
            "raw": response.get("error_raw"),
        }
    else:
        detail = {
            "model": model,
            "stage": stage,
            "role": role,
            "status": None,
            "message": "Model call produced no response",
            "provider": None,
            "raw": None,
        }
    return enrich_failure_record(detail)


def _parse_error_body(response: httpx.Response) -> ModelPayload:
    """Extract the stable subset of an OpenRouter/provider error response."""
    fallback = response.text[:500]
    try:
        decoded = response.json()
    except Exception:
        decoded = {}

    envelope = decoded if isinstance(decoded, dict) else {}
    error = envelope.get("error", envelope)
    error = error if isinstance(error, dict) else {"message": str(error)}
    metadata = error.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    raw = metadata.get("raw") or fallback
    return {
        "message": error.get("message") or fallback or "OpenRouter request failed",
        "code": error.get("code") or response.status_code,
        "provider": metadata.get("provider_name"),
        "raw": str(raw)[:500],
    }


class OpenRouterClient:
    """One-call transport; lifecycle is explicit so tests and future pools can inject it."""

    def __init__(
        self,
        *,
        api_key: str | None = OPENROUTER_API_KEY,
        endpoint: str = OPENROUTER_API_URL,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.client_factory = client_factory

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key or ''}",
            "Content-Type": "application/json",
        }

    async def complete(
        self,
        model: str,
        messages: Sequence[Message],
        *,
        timeout: float,
        log_error: bool,
    ) -> ModelPayload:
        try:
            async with self.client_factory(timeout=timeout) as client:
                response = await client.post(
                    self.endpoint,
                    headers=self._headers(),
                    json={"model": model, "messages": list(messages)},
                )
        except Exception as exc:
            return self._transport_failure(model, exc, log_error=log_error)

        if response.is_error:
            error = _parse_error_body(response)
            self._log_provider_failure(model, error, enabled=log_error)
            return _failure_response(model, error)

        try:
            payload = response.json()
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            error = {
                "code": response.status_code,
                "message": f"Malformed OpenRouter response: {exc}",
                "provider": None,
                "raw": response.text[:500],
            }
            self._log_provider_failure(model, error, enabled=log_error)
            return _failure_response(model, error)

        content = str(message.get("content") or "").strip()
        if not content:
            error = {
                "code": response.status_code,
                "message": "Model returned empty content",
                "provider": payload.get("provider"),
                "raw": str(message)[:500],
            }
            self._log_provider_failure(model, error, enabled=log_error)
            return _failure_response(model, error)

        return {
            "content": message.get("content"),
            "reasoning_details": message.get("reasoning_details"),
            "usage": payload.get("usage") or {},
            "model": payload.get("model") or model,
        }

    @staticmethod
    def _log_provider_failure(model: str, error: ModelPayload, *, enabled: bool) -> None:
        if enabled:
            logger.warning(
                "OpenRouter rejected model=%s status=%s provider=%s message=%s",
                model,
                error.get("code"),
                error.get("provider"),
                str(error.get("message") or "")[:200],
            )

    @staticmethod
    def _transport_failure(model: str, exc: Exception, *, log_error: bool) -> ModelPayload:
        if log_error:
            logger.warning("OpenRouter transport failed model=%s error=%s", model, exc)
        return _failure_response(
            model,
            {
                "code": None,
                "message": str(exc),
                "provider": None,
                "raw": str(exc)[:500],
            },
        )


async def query_model(
    model: str,
    messages: list[Message],
    timeout: float = 120.0,
    log_error: bool = True,
) -> ModelPayload:
    """Execute one model completion through the default OpenRouter transport."""
    return await OpenRouterClient().complete(
        model,
        messages,
        timeout=timeout,
        log_error=log_error,
    )


async def query_models_parallel(
    models: list[str],
    messages: list[Message],
) -> dict[str, ModelPayload]:
    """Run the same prompt across models while retaining model-keyed results."""
    results = await asyncio.gather(*(query_model(model, messages) for model in models))
    return dict(zip(models, results))
