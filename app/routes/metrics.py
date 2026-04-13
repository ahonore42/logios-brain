"""Prometheus /metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics(response: Response):
    """Prometheus metrics endpoint.

    Exposes all logios_* metrics plus default HTTP request metrics.
    Scraped by Prometheus or an OTel collector.
    """
    response.headers["Content-Type"] = CONTENT_TYPE_LATEST
    return generate_latest()
