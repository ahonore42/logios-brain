"""Background tasks for vector and graph storage writes."""
from qdrant_client.models import PointStruct

from app.celery import celery_app
from app.db import qdrant as qdrant_db
from app.db.neo4j import write_memory_chunk, MemoryChunk


@celery_app.task(bind=True, max_retries=3)
def task_upsert_qdrant(
    self,
    qdrant_id: str,
    vector: list[float],
    payload: dict,
) -> str:
    """
    Write a memory vector to Qdrant.

    Retries independently of Neo4j writes. On success, the qdrant_id
    is passed to task_upsert_neo4j via a Celery chain.
    """
    try:
        qdrant_db.get_qdrant().upsert(
            collection_name=qdrant_db.COLLECTION_NAME,
            points=[
                PointStruct(
                    id=qdrant_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )
    except Exception as exc:
        self.retry(exc=exc, countdown=2 ** self.request.retries)
    return qdrant_id


@celery_app.task(bind=True, max_retries=3)
def task_upsert_neo4j(
    self,
    qdrant_id: str,
    chunk_node: dict,
    session_id: str | None,
    event_id: str,
    event_type: str,
    event_description: str,
) -> None:
    """
    Write a MemoryChunk and Event node to Neo4j.

    qdrant_id is stored on the MemoryChunk node so the graph is
    self-contained — any MemoryChunk can resolve its vector directly.

    Retries independently of Qdrant writes. Each retry is its own attempt
    with a fresh countdown budget.
    """
    try:
        chunk = MemoryChunk(
            id=chunk_node["id"],
            tenant_id=chunk_node["tenant_id"],
            timestamp_utc=chunk_node["timestamp_utc"],
            type=chunk_node["type"],
            qdrant_id=qdrant_id,
            version=chunk_node["version"],
            importance=chunk_node["importance"],
            confidence=chunk_node["confidence"],
        )
        write_memory_chunk(
            chunk=chunk,
            session_id=session_id,
            event_id=event_id,
            event_type=event_type,
            event_description=event_description,
        )
    except Exception as exc:
        self.retry(exc=exc, countdown=2 ** self.request.retries)
