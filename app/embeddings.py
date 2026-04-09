"""
app/embeddings.py

Gemini embedding calls for text-embedding-004.
Uses retrieval_document for storing, retrieval_query for searching.
Retries on 429 with exponential backoff.
All embedding calls run in a thread pool to avoid blocking the asyncio event loop.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.genai import Client

from app import config

MODEL = "models/text-embedding-004"

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


async def embed(text: str, retries: int = 3) -> list[float]:
    """
    Embed a single text string for storage (retrieval_document task type).
    Runs in a thread pool to avoid blocking the event loop.
    Retries with exponential backoff on rate limit errors.
    """

    async def _sync_call():
        for attempt in range(retries):
            try:
                result = _get_client().models.embed_content(
                    model=MODEL,
                    content=text,
                    task_type="retrieval_document",
                )
                return result.embeddings[0].values
            except Exception as exc:
                if "429" in str(exc) and attempt < retries - 1:
                    wait = 2**attempt
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError(f"Embedding failed after {retries} attempts")

    return await asyncio.to_thread(_sync_call)


async def embed_query(text: str) -> list[float]:
    """
    Embed a query string (retrieval_query task type for better recall).
    Runs in a thread pool to avoid blocking the event loop.
    """

    async def _sync_call():
        result = _get_client().models.embed_content(
            model=MODEL,
            content=text,
            task_type="retrieval_query",
        )
        return result.embeddings[0].values

    return await asyncio.to_thread(_sync_call)
