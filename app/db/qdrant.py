"""Qdrant client for vector storage."""
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app import config

COLLECTION_NAME = "memories"
DIM = config.EMBEDDING_DIM  # 4096 from NVIDIA NIM

_client: QdrantClient | None = None


def get_qdrant() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)
    return _client


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
