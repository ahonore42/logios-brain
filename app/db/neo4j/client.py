"""Neo4j driver management and index creation."""
from neo4j import GraphDatabase

from app import config

_driver = None

DEFAULT_TIMEOUT = 30.0


def get_driver():
    """Return the singleton Neo4j driver. Creates it on first call."""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD),
        )
    return _driver


def close():
    """Close the driver and reset the singleton."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def ensure_indexes():
    """Create all constraints and indexes. Safe to call on startup."""
    driver = get_driver()
    with driver.session() as session:
        # MemoryChunk
        session.run("""
            CREATE CONSTRAINT memory_chunk_id IF NOT EXISTS
            FOR (m:MemoryChunk) REQUIRE m.id IS UNIQUE
        """)
        # Event
        session.run("""
            CREATE CONSTRAINT event_id IF NOT EXISTS
            FOR (e:Event) REQUIRE e.id IS UNIQUE
        """)
        # Fact
        session.run("""
            CREATE CONSTRAINT fact_id IF NOT EXISTS
            FOR (f:Fact) REQUIRE f.id IS UNIQUE
        """)
        # EvidencePath
        session.run("""
            CREATE CONSTRAINT evidence_path_id IF NOT EXISTS
            FOR (e:EvidencePath) REQUIRE e.id IS UNIQUE
        """)
        # EvidenceStep
        session.run("""
            CREATE CONSTRAINT evidence_step_id IF NOT EXISTS
            FOR (e:EvidenceStep) REQUIRE e.id IS UNIQUE
        """)
        # Agent
        session.run("""
            CREATE CONSTRAINT agent_id IF NOT EXISTS
            FOR (a:Agent) REQUIRE a.id IS UNIQUE
        """)
        # Output
        session.run("""
            CREATE CONSTRAINT output_id IF NOT EXISTS
            FOR (o:Output) REQUIRE o.id IS UNIQUE
        """)
        # Date
        session.run("""
            CREATE CONSTRAINT date_value IF NOT EXISTS
            FOR (d:Date) REQUIRE d.date IS UNIQUE
        """)
        # Period
        session.run("""
            CREATE CONSTRAINT period_name IF NOT EXISTS
            FOR (p:Period) REQUIRE p.name IS UNIQUE
        """)
