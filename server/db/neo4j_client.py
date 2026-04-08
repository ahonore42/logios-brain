"""
server/db/neo4j_client.py

Neo4j driver for the knowledge graph.
Works for both local Docker Neo4j (bolt://) and AuraDB (neo4j+s://).
"""

from neo4j import GraphDatabase

import config

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD),
        )
    return _driver


def run_query(cypher: str, params: dict | None = None) -> list[dict]:
    """Execute a Cypher query and return list of dicts."""
    driver = get_driver()
    with driver.session() as session:
        result = session.run(cypher, params or {})
        return [dict(record) for record in result]


def close() -> None:
    global _driver
    if _driver:
        _driver.close()
        _driver = None
