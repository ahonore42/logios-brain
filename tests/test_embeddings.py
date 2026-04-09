"""Test NVIDIA NIM embeddings API."""
import pytest
import pytest_asyncio

from app.embeddings import embed, embed_query


@pytest.mark.asyncio
async def test_embed_returns_4096_dim_vector():
    result = await embed("test memory embedding")
    assert isinstance(result, list)
    assert len(result) == 4096
    assert all(isinstance(x, float) for x in result)


@pytest.mark.asyncio
async def test_embed_query_returns_4096_dim_vector():
    result = await embed_query("test search query")
    assert isinstance(result, list)
    assert len(result) == 4096
    assert all(isinstance(x, float) for x in result)
