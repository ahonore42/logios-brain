"""Test NVIDIA NIM embeddings API."""

import os

import pytest

from app.genai.embeddings import embed, embed_query


requires_api_key = pytest.mark.skipif(
    not os.getenv("LLM_API_KEY"),
    reason="LLM_API_KEY not set",
)


@pytest.mark.asyncio
@requires_api_key
async def test_embed_returns_4096_dim_vector():
    result = await embed("test memory embedding")
    assert isinstance(result, list)
    assert len(result) == 4096
    assert all(isinstance(x, float) for x in result)


@pytest.mark.asyncio
@requires_api_key
async def test_embed_query_returns_4096_dim_vector():
    result = await embed_query("test search query")
    assert isinstance(result, list)
    assert len(result) == 4096
    assert all(isinstance(x, float) for x in result)
