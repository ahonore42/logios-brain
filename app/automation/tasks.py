"""Background tasks for vector and graph storage writes."""

from datetime import datetime, timedelta, timezone

from qdrant_client.models import PointStruct

from app.automation.celery import celery_app
from app.db import qdrant as qdrant_db
from app.db.database import get_engine
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
        self.retry(exc=exc, countdown=2**self.request.retries)
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
            timestamp_utc=chunk_node["timestamp_utc"],
            type=chunk_node["type"],
            qdrant_id=qdrant_id,
            revoked=chunk_node.get("revoked", False),
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
        self.retry(exc=exc, countdown=2**self.request.retries)


@celery_app.task(bind=True, max_retries=3)
def task_extract_entities(
    self,
    _result,  # absorbs return value piped from task_upsert_neo4j (None)
    content: str,
    chunk_node_id: str,
) -> None:
    """
    Extract entities from memory content and write labeled nodes to Neo4j.

    Third link in the Celery chain — runs only after Neo4j MemoryChunk
    is confirmed. Best-effort: failures are retried but never block the
    write path. Produces Person, Project, Concept, Decision, Tool,
    Event, and Location nodes linked to the MemoryChunk via DESCRIBES.
    """
    from app.genai.entity_extraction import extract_entities
    from app.db.neo4j.client import get_driver

    try:
        entities = extract_entities(content)
        if not entities:
            return

        driver = get_driver()
        with driver.session() as session:
            for entity in entities:
                name = entity.get("name", "").strip()
                label = entity.get("label", "Concept")
                if not name:
                    continue

                # Write labeled entity node and link to MemoryChunk
                with session.begin_transaction() as tx:
                    tx.run(
                        f"""
                        MERGE (e:{label} {{name: $name}})
                        ON CREATE SET e.created_at = datetime()
                        ON MATCH SET e.last_seen = datetime()
                        WITH e
                        MERGE (m:MemoryChunk {{id: $chunk_id}})
                        MERGE (e)-[:DESCRIBES]->(m)
                        """,
                        name=name,
                        chunk_id=chunk_node_id,
                    )

                    # Write relationships between entities
                    for rel in entity.get("relationships", []):
                        target = rel.get("target", "").strip()
                        rel_type = rel.get("type", "RELATES_TO")
                        if not target:
                            continue
                        tx.run(
                            f"""
                            MERGE (a {{name: $source}})
                            MERGE (b {{name: $target}})
                            MERGE (a)-[r:{rel_type}]->(b)
                            ON CREATE SET r.created_at = datetime()
                            """,
                            source=name,
                            target=target,
                        )
                    tx.commit()

    except Exception as exc:
        self.retry(exc=exc, countdown=2**self.request.retries)


def _memory_digest_sync(
    days_unused: int = 30,
    days_recent: int = 7,
    low_score_threshold: float = 0.3,
) -> dict:
    """
    Generate a memory digest for human review.

    Returns three categories:
    - never_retrieved: memories with no associated Evidence rows in the last N days
    - low_relevance: memories with low relevance_score in recent evidence
    - recent_checkpoints: type='checkpoint' memories created in the last week

    Use this output to decide which memories to promote to type='identity',
    rewrite, or delete.
    """
    from sqlalchemy import text

    engine = get_engine()

    with engine.connect() as conn:
        now = datetime.now(timezone.utc)
        cutoff_unused = now - timedelta(days=days_unused)
        cutoff_recent = now - timedelta(days=days_recent)

        # Memories never retrieved in last N days
        never_retrieved = conn.execute(
            text("""
                SELECT m.id, m.content, m.type, m.captured_at
                FROM memories m
                LEFT JOIN evidence e ON e.memory_id = m.id
                  AND e.created_at > :cutoff
                WHERE m.type IN ('standard', 'checkpoint')
                  AND m.metadata_->'revoked' IS DISTINCT FROM 'true'
                  AND e.id IS NULL
                ORDER BY m.captured_at DESC
                LIMIT 20
            """),
            {"cutoff": cutoff_unused},
        ).fetchall()

        # Memories with low relevance scores in recent evidence
        low_relevance = conn.execute(
            text("""
                SELECT DISTINCT m.id, m.content, m.type, m.captured_at,
                       e.relevance_score
                FROM memories m
                JOIN evidence e ON e.memory_id = m.id
                WHERE e.created_at > :cutoff
                  AND e.relevance_score < :threshold
                  AND m.type IN ('standard', 'checkpoint')
                ORDER BY e.relevance_score ASC
                LIMIT 20
            """),
            {"cutoff": cutoff_recent, "threshold": low_score_threshold},
        ).fetchall()

        # Recent checkpoints
        recent_checkpoints = conn.execute(
            text("""
                SELECT m.id, m.content, m.captured_at, m.metadata_
                FROM memories m
                WHERE m.type = 'checkpoint'
                  AND m.captured_at > :cutoff
                ORDER BY m.captured_at DESC
                LIMIT 10
            """),
            {"cutoff": cutoff_recent},
        ).fetchall()

    return {
        "generated_at": now.isoformat(),
        "days_unused": days_unused,
        "never_retrieved": [
            {
                "id": str(row.id),
                "content": row.content[:200],
                "type": row.type,
                "captured_at": row.captured_at.isoformat() if row.captured_at else None,
            }
            for row in never_retrieved
        ],
        "low_relevance": [
            {
                "id": str(row.id),
                "content": row.content[:200],
                "type": row.type,
                "relevance_score": row.relevance_score,
                "captured_at": row.captured_at.isoformat() if row.captured_at else None,
            }
            for row in low_relevance
        ],
        "recent_checkpoints": [
            {
                "id": str(row.id),
                "content": row.content[:200],
                "captured_at": row.captured_at.isoformat() if row.captured_at else None,
                "turn_count": row.metadata_.get("turn_count") if row.metadata_ else None,
            }
            for row in recent_checkpoints
        ],
    }


@celery_app.task(bind=True, max_retries=3)
def task_memory_digest(
    self,
    days_unused: int = 30,
    days_recent: int = 7,
    low_score_threshold: float = 0.3,
) -> dict:
    """Celery wrapper for _memory_digest_sync."""
    return _memory_digest_sync(
        days_unused=days_unused,
        days_recent=days_recent,
        low_score_threshold=low_score_threshold,
    )
