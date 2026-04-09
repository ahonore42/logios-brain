"""Tests for Neo4j graph storage."""
import pytest
import pytest_asyncio
from uuid import uuid4

from app.db import neo4j as neo4j_db


@pytest.fixture(scope="module", autouse=True)
def setup_indexes():
    """Ensure Neo4j indexes exist before tests."""
    try:
        neo4j_db.ensure_indexes()
    except Exception:
        pass  # Indexes may already exist


@pytest.mark.asyncio
async def test_write_memory_creates_node():
    """Memory node should be created in Neo4j."""
    memory_id = str(uuid4())
    neo4j_db.write_memory(
        memory_id=memory_id,
        content="Test memory content",
        source="pytest",
        captured_at="2024-01-01T00:00:00Z",
        session_id=None,
    )

    driver = neo4j_db.get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (m:Memory {id: $id}) RETURN m.id as id, m.content as content",
            id=memory_id,
        )
        record = result.single()
        assert record is not None
        assert record["content"] == "Test memory content"


@pytest.mark.asyncio
async def test_write_memory_with_session():
    """Memory with session_id should create IN_SESSION relationship."""
    memory_id = str(uuid4())
    session_id = str(uuid4())

    neo4j_db.write_memory(
        memory_id=memory_id,
        content="Session test memory",
        source="pytest",
        captured_at="2024-01-01T00:00:00Z",
        session_id=session_id,
    )

    driver = neo4j_db.get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (m:Memory {id: $mid})-[r:IN_SESSION]->(s:Session {id: $sid})
            RETURN type(r) as rel_type
            """,
            mid=memory_id,
            sid=session_id,
        )
        record = result.single()
        assert record is not None
        assert record["rel_type"] == "IN_SESSION"


@pytest.mark.asyncio
async def test_write_memory_is_idempotent():
    """Writing same memory twice should not duplicate the node."""
    memory_id = str(uuid4())

    neo4j_db.write_memory(
        memory_id=memory_id,
        content="First write",
        source="pytest",
        captured_at="2024-01-01T00:00:00Z",
        session_id=None,
    )
    neo4j_db.write_memory(
        memory_id=memory_id,
        content="Second write (should not create new node)",
        source="pytest",
        captured_at="2024-01-01T00:00:00Z",
        session_id=None,
    )

    driver = neo4j_db.get_driver()
    with driver.session() as session:
        count = session.run(
            "MATCH (m:Memory {id: $id}) RETURN count(m) as cnt",
            id=memory_id,
        ).single()["cnt"]
        assert count == 1
