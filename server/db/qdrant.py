"""
server/db/qdrant.py

Qdrant client for vector storage.
Works for both local Docker Qdrant (no API key) and Qdrant Cloud (API key auth).
"""

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

import config

COLLECTION_NAME = "memories"
EMBEDDING_DIM = 3072  # gemini-embedding-001 / text-embedding-004

_client: QdrantClient | None = None


def get_qdrant() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(
            url=config.QDRANT_URL,
            api_key=config.QDRANT_API_KEY,
        )
    return _client


def ensure_collection() -> None:
    """Create the memories collection if it does not exist."""
    client = get_qdrant()
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE,
            ),
        )
        # Create payload indexes for source and session_id filtering
        try:
            from qdrant_client.models import PayloadSchemaIndex, TokenizerType

            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="source",
                field_schema=PayloadSchemaIndex(
                    data_type="keyword",
                    tokenizer=TokenizerType.KEYWORD,
                ),
            )
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="session_id",
                field_schema=PayloadSchemaIndex(
                    data_type="keyword",
                    tokenizer=TokenizerType.KEYWORD,
                ),
            )
        except Exception:
            # Index creation is best-effort; collection works without them
            pass
