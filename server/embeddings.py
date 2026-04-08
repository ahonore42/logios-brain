"""
server/embeddings.py

Gemini embedding calls for text-embedding-004 (gemini-embedding-001 via SDK).
Uses retrieval_document for storing, retrieval_query for searching.
Retries on 429 with exponential backoff.
"""

import time

import google.generativeai as genai

import config

genai.configure(api_key=config.GEMINI_API_KEY)

MODEL = "models/text-embedding-004"


def embed(text: str, retries: int = 3) -> list[float]:
    """
    Embed a single text string for storage (retrieval_document task type).
    Retries with exponential backoff on rate limit errors.
    """
    for attempt in range(retries):
        try:
            result = genai.embed_content(
                model=MODEL,
                content=text,
                task_type="retrieval_document",
            )
            return result["embedding"]
        except Exception as exc:
            if "429" in str(exc) and attempt < retries - 1:
                wait = 2**attempt
                time.sleep(wait)
                continue
            raise

    raise RuntimeError(f"Embedding failed after {retries} attempts")


def embed_query(text: str) -> list[float]:
    """
    Embed a query string (retrieval_query task type for better recall).
    """
    result = genai.embed_content(
        model=MODEL,
        content=text,
        task_type="retrieval_query",
    )
    return result["embedding"]
