"""
server/tools/relate.py

Manually create or reinforce a typed relationship between two entities in Neo4j.
"""

from db import neo4j_client


def relate(entity_a: str, entity_b: str, relationship_type: str = "RELATES_TO") -> dict:
    """
    Manually create or reinforce a relationship between two entities in Neo4j.
    Useful for building the graph from outside the automatic extraction path.
    """
    rel_type = relationship_type.upper().replace(" ", "_")

    neo4j_client.run_query(
        f"""
        MERGE (a {{name: $entity_a}})
        MERGE (b {{name: $entity_b}})
        MERGE (a)-[r:{rel_type}]->(b)
        ON CREATE SET r.created_at = datetime(), r.manual = true
        ON MATCH  SET r.last_updated = datetime()
        """,
        {"entity_a": entity_a, "entity_b": entity_b},
    )

    return {
        "status": "related",
        "from": entity_a,
        "to": entity_b,
        "type": rel_type,
    }
