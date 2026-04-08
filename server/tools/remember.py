"""
server/tools/remember.py

The write path. One inbound memory fans out to three writes:
1. Supabase/Postgres: upsert_memory (deduplication-safe, returns memory_id)
2. Qdrant: embed and upsert the chunk point
3. Neo4j: extract entities and merge into the graph (best-effort, non-blocking)
"""

import uuid

from qdrant_client.models import PointStruct

from db import postgres, qdrant as qdrant_db, neo4j_client
from embeddings import embed
from entity_extraction import extract_entities


def remember(
    content: str,
    source: str = "manual",
    session_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """
    Write a memory to all three stores.

    Returns: {"memory_id": str, "status": "stored", "source": str}
    """
    # 1. Get canonical memory_id from Postgres
    memory_id = postgres.upsert_memory(content, source, metadata, session_id)

    # 2. Embed and write to Qdrant
    vector = embed(content)
    qdrant_id = str(uuid.uuid4())

    postgres.insert_chunk(memory_id, content, qdrant_id, chunk_index=0)

    qdrant_db.get_qdrant().upsert(
        collection_name=qdrant_db.COLLECTION_NAME,
        points=[
            PointStruct(
                id=qdrant_id,
                vector=vector,
                payload={
                    "memory_id": memory_id,
                    "source": source,
                    "session_id": session_id,
                },
            )
        ],
    )

    # 3. Entity extraction → Neo4j (best-effort, never fails a memory write)
    try:
        _write_entities(content, memory_id)
    except Exception:
        pass

    return {
        "memory_id": memory_id,
        "status": "stored",
        "source": source,
    }


def _write_entities(content: str, memory_id: str) -> None:
    """Extract entities and write them to Neo4j + Postgres entity registry."""
    entities = extract_entities(content)
    if not entities:
        return

    for entity in entities:
        name = entity.get("name", "").strip()
        label = entity.get("label", "Concept")
        if not name or label not in (
            "Project",
            "Concept",
            "Person",
            "Session",
            "Event",
            "Decision",
            "Tool",
            "Location",
        ):
            continue

        # Merge node into Neo4j
        result = neo4j_client.run_query(
            f"""
            MERGE (e:{label} {{name: $name}})
            ON CREATE SET e.created_at = datetime(), e.memory_id = $memory_id
            ON MATCH  SET e.last_seen = datetime()
            RETURN elementId(e) as node_id
            """,
            {"name": name, "memory_id": memory_id},
        )

        if not result:
            continue

        neo4j_node_id = result[0]["node_id"]

        # Register in Postgres entity registry
        postgres.upsert_entity(memory_id, neo4j_node_id, label, name)

        # Write relationships
        for rel in entity.get("relationships", []):
            target = rel.get("target", "").strip()
            rel_type = rel.get("type", "RELATES_TO").upper().replace(" ", "_")
            if not target:
                continue

            neo4j_client.run_query(
                f"""
                MERGE (a {{name: $source_name}})
                MERGE (b {{name: $target_name}})
                MERGE (a)-[r:{rel_type}]->(b)
                ON CREATE SET r.created_at = datetime(), r.memory_id = $memory_id
                """,
                {
                    "source_name": name,
                    "target_name": target,
                    "memory_id": memory_id,
                },
            )
