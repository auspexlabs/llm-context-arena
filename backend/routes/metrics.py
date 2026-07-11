"""Prometheus metrics exposition (DEC-018 A10)."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from ..metrics import render_prometheus

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def get_metrics() -> PlainTextResponse:
    """Prometheus text exposition of in-process arena metrics."""
    return PlainTextResponse(render_prometheus(), media_type="text/plain; version=0.0.4")