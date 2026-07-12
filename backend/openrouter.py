"""OpenRouter API client for making LLM requests."""

import logging
from typing import Any, Dict, List, Optional

import httpx

from .config import OPENROUTER_API_KEY, OPENROUTER_API_URL
from .model_failures import enrich_failure_record

logger = logging.getLogger(__name__)


def is_query_failure(resp: Optional[Dict[str, Any]]) -> bool:
    """True when query_model returned a structured failure payload."""
    return bool(resp and resp.get("_failed"))


def is_usable_response(resp: Optional[Dict[str, Any]]) -> bool:
    """True when the response has usable model content."""
    if not resp or is_query_failure(resp):
        return False
    content = resp.get("content")
    return content is not None and str(content).strip() != ""


def failure_record(
    model: str,
    resp: Optional[Dict[str, Any]],
    *,
    stage: str,
    role: str,
) -> Dict[str, Any]:
    """Normalize a failed query into metadata.model_failures entry."""
    if resp and is_query_failure(resp):
        return enrich_failure_record(
            {
                "model": model,
                "stage": stage,
                "role": role,
                "status": resp.get("error_status"),
                "message": resp.get("error_message"),
                "provider": resp.get("error_provider"),
                "raw": resp.get("error_raw"),
            }
        )
    return enrich_failure_record(
        {
            "model": model,
            "stage": stage,
            "role": role,
            "status": None,
            "message": "No response from model (unknown error)",
            "provider": None,
            "raw": None,
        }
    )


def _parse_error_body(response: httpx.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {"message": response.text[:500], "code": response.status_code}

    err = data.get("error") or data
    meta = err.get("metadata") or {}
    return {
        "message": err.get("message") or str(err),
        "code": err.get("code") or response.status_code,
        "provider": meta.get("provider_name"),
        "raw": (meta.get("raw") or response.text)[:500],
    }


def _failure_response(model: str, error: Dict[str, Any]) -> Dict[str, Any]:
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


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    log_error: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API.

    Returns:
        Success: dict with 'content', optional 'reasoning_details', 'usage'
        Failure: dict with '_failed': True and error_* fields (never None)
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload,
            )
            if response.status_code >= 400:
                error = _parse_error_body(response)
                if log_error:
                    logger.warning(
                        "OpenRouter error model=%s status=%s provider=%s msg=%s",
                        model,
                        error.get("code"),
                        error.get("provider"),
                        (error.get("message") or "")[:200],
                    )
                return _failure_response(model, error)

            data = response.json()
            message = data["choices"][0]["message"]

            return {
                "content": message.get("content"),
                "reasoning_details": message.get("reasoning_details"),
                "usage": data.get("usage") or {},
                "model": data.get("model") or model,
            }

    except httpx.HTTPStatusError as e:
        error = _parse_error_body(e.response)
        if log_error:
            logger.warning(
                "OpenRouter HTTP error model=%s status=%s msg=%s",
                model,
                error.get("code"),
                (error.get("message") or "")[:200],
            )
        return _failure_response(model, error)
    except Exception as e:
        if log_error:
            logger.warning("OpenRouter request failed model=%s error=%s", model, e)
        return _failure_response(
            model,
            {"code": None, "message": str(e), "provider": None, "raw": str(e)[:500]},
        )


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]],
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Returns:
        Dict mapping model identifier to response dict (success or _failed)
    """
    import asyncio

    tasks = [query_model(model, messages) for model in models]
    responses = await asyncio.gather(*tasks)
    return {model: response for model, response in zip(models, responses)}