"""Transaction functions for atomic graph writes."""
from app.db.neo4j.client import get_driver
from app.db.neo4j.nodes import MemoryChunk, Event, Fact


def write_memory_chunk(
    chunk: MemoryChunk,
    session_id: str | None = None,
    event_id: str | None = None,
    event_type: str | None = None,
    event_description: str | None = None,
    timeout: float | None = None,
) -> None:
    """
    Write a MemoryChunk node and optionally link to a Session atomically.

    If event_id is provided, also creates an Event node and links it to the
    MemoryChunk via [:DESCRIBES], representing the memory-ingestion event.

    Uses a session transaction so all nodes and links are committed together.
    """
    driver = get_driver()
    with driver.session() as session:
        with session.begin_transaction() as tx:
            tx.run(
                """
                MERGE (m:MemoryChunk {id: $id})
                SET m.tenant_id = $tenant_id,
                    m.timestamp_utc = $timestamp_utc,
                    m.type = $type,
                    m.qdrant_id = $qdrant_id,
                    m.version = $version,
                    m.importance = $importance,
                    m.confidence = $confidence
                """,
                id=chunk.id,
                tenant_id=chunk.tenant_id,
                timestamp_utc=chunk.timestamp_utc,
                type=chunk.type,
                qdrant_id=chunk.qdrant_id,
                version=chunk.version,
                importance=chunk.importance,
                confidence=chunk.confidence,
            )

            if session_id:
                tx.run(
                    """
                    MERGE (s:Session {id: $session_id})
                    MERGE (m:MemoryChunk {id: $id})
                    MERGE (m)-[:IN_SESSION]->(s)
                    """,
                    session_id=session_id,
                    id=chunk.id,
                )

            if event_id:
                tx.run(
                    """
                    MERGE (e:Event {id: $event_id})
                    SET e.tenant_id = $tenant_id,
                        e.agent_id = $agent_id,
                        e.type = $event_type,
                        e.description = $event_description,
                        e.timestamp_utc = $timestamp_utc
                    """,
                    event_id=event_id,
                    tenant_id=chunk.tenant_id,
                    agent_id=None,
                    event_type=event_type or chunk.type,
                    event_description=event_description or f"Memory captured: {chunk.type}",
                    timestamp_utc=chunk.timestamp_utc,
                )
                tx.run(
                    """
                    MERGE (e:Event {id: $event_id})
                    MERGE (m:MemoryChunk {id: $chunk_id})
                    MERGE (e)-[:DESCRIBES]->(m)
                    """,
                    event_id=event_id,
                    chunk_id=chunk.id,
                )
            tx.commit()


def write_event(
    event: Event,
    date_str: str | None = None,
    period: str | None = None,
    timeout: float | None = None,
) -> None:
    """Write an Event node with optional DateNode and PeriodNode links atomically."""
    driver = get_driver()
    with driver.session() as session:
        with session.begin_transaction() as tx:
            tx.run(
                """
                MERGE (e:Event {id: $id})
                SET e.tenant_id = $tenant_id,
                    e.agent_id = $agent_id,
                    e.type = $type,
                    e.description = $description,
                    e.timestamp_utc = $timestamp_utc
                """,
                id=event.id,
                tenant_id=event.tenant_id,
                agent_id=event.agent_id,
                type=event.type,
                description=event.description,
                timestamp_utc=event.timestamp_utc,
            )

            if date_str:
                tx.run(
                    """
                    MERGE (d:Date {date: $date})
                    WITH d
                    MERGE (e:Event {id: $id})
                    MERGE (e)-[:OCCURRED_ON]->(d)
                    """,
                    date=date_str,
                    id=event.id,
                )

            if period:
                tx.run(
                    """
                    MERGE (p:Period {name: $name})
                    WITH p
                    MERGE (e:Event {id: $id})
                    MERGE (e)-[:APPLIES_DURING]->(p)
                    """,
                    name=period,
                    id=event.id,
                )
            tx.commit()


def write_fact(
    fact: Fact,
    derived_from_ids: list[str] | None = None,
    timeout: float | None = None,
) -> None:
    """Write a Fact node with optional DERIVED_FROM links to MemoryChunks atomically."""
    driver = get_driver()
    with driver.session() as session:
        with session.begin_transaction() as tx:
            tx.run(
                """
                MERGE (f:Fact {id: $id})
                SET f.tenant_id = $tenant_id,
                    f.content = $content,
                    f.valid_from = $valid_from,
                    f.valid_until = $valid_until,
                    f.version = $version
                """,
                id=fact.id,
                tenant_id=fact.tenant_id,
                content=fact.content,
                valid_from=fact.valid_from,
                valid_until=fact.valid_until,
                version=fact.version,
            )

            for source_id in (derived_from_ids or []):
                tx.run(
                    """
                    MERGE (f:Fact {id: $fact_id})
                    MERGE (m:MemoryChunk {id: $source_id})
                    MERGE (f)-[:DERIVED_FROM]->(m)
                    """,
                    fact_id=fact.id,
                    source_id=source_id,
                )
            tx.commit()


def get_latest_fact(fact_id: str, timeout: float | None = None) -> dict | None:
    """
    Return the latest valid Fact in a REPLACES chain.

    Given a Fact ID, traverses any REPLACES edges to find the newest
    Fact that supersedes it. If no REPLACES edge exists, returns the
    original fact. This ensures evidence paths always resolve to the
    current valid Fact, not a superseded one.

    Returns a dict with fact properties or None if not found.
    """
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (newer:Fact)-[:REPLACES]->(old:Fact {id: $fact_id})
            RETURN newer.id as id, newer.content as content,
                   newer.valid_from as valid_from, newer.valid_until as valid_until,
                   newer.version as version
            ORDER BY newer.valid_from DESC
            LIMIT 1
            """,
            fact_id=fact_id,
        )
        record = result.single()
        if record:
            return dict(record)

        # No replacement found — return the original fact
        result = session.run(
            "MATCH (f:Fact {id: $fact_id}) RETURN f.id as id, f.content as content, f.valid_from as valid_from, f.valid_until as valid_until, f.version as version",
            fact_id=fact_id,
        )
        record = result.single()
        return dict(record) if record else None
