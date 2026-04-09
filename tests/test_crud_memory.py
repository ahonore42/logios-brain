"""Tests for memory routes."""

import pytest
import pytest_asyncio
from uuid import uuid4

from app.routes.memory import _upsert_memory
from app.schemas import RememberRequest
from app.database import get_db


@pytest_asyncio.fixture
async def db_session():
    async for session in get_db():
        yield session


@pytest.mark.asyncio
async def test_upsert_memory_inserts_and_returns_memory(db_session):
    req = RememberRequest(
        content=f"test memory {uuid4()}",
        source="manual",
        metadata={"test": True},
    )
    result = await _upsert_memory(db_session, req)

    assert result.id is not None
    assert result.content == req.content
    assert result.source == req.source


@pytest.mark.asyncio
async def test_upsert_memory_deduplication(db_session):
    content = f"dedup test {uuid4()}"
    req1 = RememberRequest(content=content, source="manual", metadata={})
    req2 = RememberRequest(content=content, source="telegram", metadata={})

    result1 = await _upsert_memory(db_session, req1)
    result2 = await _upsert_memory(db_session, req2)

    assert result1.id == result2.id


@pytest.mark.asyncio
async def test_upsert_memory_stores_and_returns_metadata(db_session):
    """Metadata dict should be stored and returned correctly."""
    meta = {"key": "value", "nested": {"foo": "bar"}}
    req = RememberRequest(
        content=f"metadata test {uuid4()}",
        source="manual",
        metadata=meta,
    )
    result = await _upsert_memory(db_session, req)

    assert result.metadata == meta
