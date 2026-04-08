"""
server/tools/search.py

The read path — semantic search via Qdrant + graph traversal via Neo4j.
"""

from db import postgres, qdrant as qdrant_db, neo4j_client
from embeddings import embed_query


def search(query: str, top_k: int = 10, threshold: float = 0.65) -> list[dict]:
    """
    Semantic search over Qdrant, hydrated with full memory content from Postgres.
    """
    vector = embed_query(query)
    results = qdrant_db.get_qdrant().search(
        collection_name=qdrant_db.COLLECTION_NAME,
        query_vector=vector,
        limit=top_k,
        score_threshold=threshold,
        with_payload=True,
    )

    if not results:
        return []

    memory_ids = [r.payload["memory_id"] for r in results]
    scores = {r.payload["memory_id"]: r.score for r in results}

    memories = postgres.get_memories(memory_ids)

    return [
        {
            "memory_id": mid,
            "score": scores[mid],
            "content": memories[mid]["content"] if mid in memories else None,
            "source": memories[mid]["source"] if mid in memories else None,
            "captured_at": memories[mid]["captured_at"] if mid in memories else None,
        }
        for mid in memory_ids
        if mid in memories
    ]


def graph_search(entity_name: str, depth: int = 2) -> list[dict]:
    """
    Graph traversal from an entity — returns connected nodes and relationships.
    Uses APOC path traversal.
    """
    results = neo4j_client.run_query(
        """
        MATCH (start {name: $name})
        CALL apoc.path.subgraphNodes(start, {maxLevel: $depth}) YIELD node
        RETURN
          elementId(node) as node_id,
          labels(node)    as labels,
          node.name       as name,
          node.memory_id  as memory_id
        LIMIT 50
        """,
        {"name": entity_name, "depth": depth},
    )
    return results


def recall(
    source: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Structured recall from Postgres — by source, date range, or both.
    """
    conditions = []
    params = []

    if source:
        conditions.append("source = %s")
        params.append(source)
    if since:
        conditions.append("captured_at >= %s")
        params.append(since)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    rows = postgres.run_query(
        f"""
        SELECT id, content, source, captured_at, metadata
        FROM memories
        WHERE {where_clause}
        ORDER BY captured_at DESC
        LIMIT %s
        """,
        tuple(params + [limit]),
    )
    return rows
