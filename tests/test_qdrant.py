"""Tests for Qdrant vector store."""

import pytest

from app.db import qdrant as qdrant_db


@pytest.mark.asyncio
async def test_ensure_collection_is_idempotent():
    """ensure_collection should be callable multiple times without error."""
    client = qdrant_db.get_qdrant()

    # Delete if exists
    try:
        client.delete_collection(qdrant_db.COLLECTION_NAME)
    except Exception:
        pass

    # Create twice - second call should not fail
    qdrant_db.ensure_collection()
    qdrant_db.ensure_collection()

    # Collection should exist
    collections = client.get_collections().collections
    names = [c.name for c in collections]
    assert qdrant_db.COLLECTION_NAME in names
