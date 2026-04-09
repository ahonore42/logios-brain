"""Qdrant client for vector storage."""
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PayloadSchemaType

from app import config

COLLECTION_NAME = "memories"
DIM = config.EMBEDDING_DIM  # 4096 from NVIDIA NIM

_client: QdrantClient | None = None


def get_qdrant() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)
    return _client


def _create_payload_indexes() -> None:
    """Create payload field indexes for temporal filtering fields.

    These indexes allow Qdrant to efficiently filter by revoked, valid_from,
    and valid_until without scanning every point in the collection.
    """
    client = get_qdrant()
    for field, schema in [
        ("revoked", PayloadSchemaType.BOOL),
        ("valid_from", PayloadSchemaType.DATETIME),
        ("valid_until", PayloadSchemaType.DATETIME),
    ]:
        try:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field,
                field_schema=schema,
            )
        except Exception:
            pass  # Index may already exist


def ensure_collection() -> None:
    """Create the memories collection if it doesn't exist."""
    client = get_qdrant()
    collections = client.get_collections().collections
    names = [c.name for c in collections]
    if COLLECTION_NAME not in names:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
        )
    # Always ensure payload indexes exist — idempotent, safe to call on every boot
    _create_payload_indexes()
