"""
app/embeddings.py

NVIDIA NIM API embeddings via httpx async client.
Uses nvidia/nv-embed-v1 at 4096 dimensions.
"""

import httpx

from app import config

EMBEDDING_URL = config.EMBEDDING_URL
MODEL = config.EMBEDDING_MODEL
DIM = config.EMBEDDING_DIM


async def embed(text: str, retries: int = 3) -> list[float]:
    """
    Embed a text string for storage (retrieval_document / passage).
    Uses NVIDIA NIM API. Runs fully on the provider's GPU servers.
    """
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    EMBEDDING_URL,
                    json={
                        "input": [text],
                        "model": MODEL,
                        "input_type": "passage",
                        "encoding_format": "float",
                        "truncate": "NONE",
                    },
                    headers={
                        "Authorization": f"Bearer {config.LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["data"][0]["embedding"]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < retries - 1:
                import time

                time.sleep(2**attempt)
                continue
            raise
    raise RuntimeError(f"Embedding failed after {retries} attempts")


async def embed_query(text: str) -> list[float]:
    """
    Embed a query string (retrieval_query / query).
    Uses NVIDIA NIM API for better recall on search queries.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            EMBEDDING_URL,
            json={
                "input": [text],
                "model": MODEL,
                "input_type": "query",
                "encoding_format": "float",
                "truncate": "NONE",
            },
            headers={
                "Authorization": f"Bearer {config.LLM_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]
