"""Health check endpoints.

GET /health      — liveness probe: app is running
GET /health/ready — readiness probe: all stores are reachable
"""

from __future__ import annotations

import time

import redis
from fastapi import APIRouter, Response
from pydantic import BaseModel
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, text

from app.config import (
    DATABASE_URL,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USERNAME,
    QDRANT_API_KEY,
    QDRANT_URL,
    REDIS_URL,
)

router = APIRouter(tags=["health"])


# ── Response models ────────────────────────────────────────────────────────────


class StoreStatus(BaseModel):
    healthy: bool
    latency_ms: float | None = None
    error: str | None = None


class ReadinessResponse(BaseModel):
    postgres: StoreStatus
    qdrant: StoreStatus
    neo4j: StoreStatus
    redis: StoreStatus


# ── Store checks ───────────────────────────────────────────────────────────────


def _check_postgres() -> StoreStatus:
    try:
        # Use a separate sync engine for the health check.
        # The main app uses async SQLAlchemy; this is a lightweight sync probe.
        engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            start = time.perf_counter()
            conn.execute(text("SELECT 1"))
            latency_ms = (time.perf_counter() - start) * 1000
        engine.dispose()
        return StoreStatus(healthy=True, latency_ms=round(latency_ms, 2))
    except Exception as e:
        return StoreStatus(healthy=False, error=str(e))


def _check_qdrant() -> StoreStatus:
    try:
        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        start = time.perf_counter()
        # get_collections returns a valid JSON response — use as lightweight probe
        client.http.collections_api.get_collections()
        latency_ms = (time.perf_counter() - start) * 1000
        return StoreStatus(healthy=True, latency_ms=round(latency_ms, 2))
    except Exception as e:
        return StoreStatus(healthy=False, error=str(e))


def _check_neo4j() -> StoreStatus:
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
        start = time.perf_counter()
        with driver.session() as session:
            session.run("RETURN 1")
        latency_ms = (time.perf_counter() - start) * 1000
        driver.close()
        return StoreStatus(healthy=True, latency_ms=round(latency_ms, 2))
    except Exception as e:
        return StoreStatus(healthy=False, error=str(e))


def _check_redis() -> StoreStatus:
    try:
        r = redis.from_url(REDIS_URL, socket_connect_timeout=5)
        start = time.perf_counter()
        r.ping()
        latency_ms = (time.perf_counter() - start) * 1000
        return StoreStatus(healthy=True, latency_ms=round(latency_ms, 2))
    except Exception as e:
        return StoreStatus(healthy=False, error=str(e))


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/health")
def health():
    """Liveness probe — returns 200 if the app process is running."""
    return {"status": "ok"}


@router.get("/health/ready", response_model=ReadinessResponse)
def readiness(response: Response):
    """
    Readiness probe — checks all four stores.

    Returns HTTP 200 if all stores are healthy, HTTP 503 if any are down.
    Each store reports its own healthy status, latency, and error message.
    """
    postgres = _check_postgres()
    qdrant = _check_qdrant()
    neo4j = _check_neo4j()
    redis_status = _check_redis()

    all_healthy = postgres.healthy and qdrant.healthy and neo4j.healthy and redis_status.healthy

    if not all_healthy:
        response.status_code = 503

    return ReadinessResponse(
        postgres=postgres,
        qdrant=qdrant,
        neo4j=neo4j,
        redis=redis_status,
    )
