"""Neo4j client for graph storage."""
from neo4j import GraphDatabase

from app import config

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD),
        )
    return _driver


def close():
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def write_memory(
    memory_id: str,
    content: str,
    source: str,
    captured_at: str,
    session_id: str | None = None,
) -> None:
    """
    Write a Memory node to Neo4j and optionally link to a Session.

    Uses MERGE for idempotent upsert — safe to call multiple times.
    """
    driver = get_driver()
    with driver.session() as session:
        # Upsert Memory node
        session.run(
            """
            MERGE (m:Memory {id: $memory_id})
            SET m.content = $content,
                m.source = $source,
                m.captured_at = $captured_at
            """,
            memory_id=memory_id,
            content=content,
            source=source,
            captured_at=captured_at,
        )

        # Link to session if present
        if session_id:
            session.run(
                """
                MERGE (s:Session {id: $session_id})
                WITH s
                MERGE (m:Memory {id: $memory_id})
                MERGE (m)-[:IN_SESSION]->(s)
                """,
                session_id=session_id,
                memory_id=memory_id,
            )


def find_related_memories(memory_id: str, relationship_type: str | None = None, depth: int = 1):
    """
    Find memories connected to the given memory.

    Args:
        memory_id: UUID of the source memory
        relationship_type: Optional filter by relationship type (e.g., 'RELATED_TO')
        depth: Traversal depth (1 = directly connected)

    Returns list of (related_memory_id, relationship_type, properties)
    """
    driver = get_driver()
    with driver.session() as session:
        if relationship_type:
            query = """
                MATCH (m:Memory {id: $memory_id})-[r:%s*1..%d]-(related:Memory)
                RETURN related.id as memory_id, type(r[0]) as rel_type,
                       properties(r[0]) as rel_props, m.id = related.id as is_self
                """ % (relationship_type, depth)
        else:
            query = """
                MATCH (m:Memory {id: $memory_id})-[r]-(related:Memory)
                RETURN related.id as memory_id, type(r) as rel_type,
                       properties(r) as rel_props, m.id = related.id as is_self
                LIMIT 100
            """
        result = session.run(query, memory_id=memory_id)
        return [dict(record) for record in result]


def ensure_indexes():
    """Create constraints and indexes. Safe to call on startup."""
    driver = get_driver()
    with driver.session() as session:
        session.run("""
            CREATE CONSTRAINT memory_id IF NOT EXISTS
            FOR (m:Memory) REQUIRE m.id IS UNIQUE
        """)
        session.run("""
            CREATE INDEX memory_captured_at IF NOT EXISTS
            FOR (m:Memory) ON (m.captured_at)
        """)
        session.run("""
            CREATE CONSTRAINT session_id IF NOT EXISTS
            FOR (s:Session) REQUIRE s.id IS UNIQUE
        """)
