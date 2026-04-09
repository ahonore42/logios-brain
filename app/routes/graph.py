"""Routes for recall and graph operations."""

import uuid
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db.neo4j import get_latest_fact
from app.db.neo4j.client import get_driver, NodeId
from app.dependencies import verify_key
from app.models import Memory
# from app.models import Entity  # TODO: re-enable when entity-only search is needed
from app.schemas import FactOut, GraphSearchRequest, GraphTraversalResult, MemoryOut, RecallRequest
# EntityOut  # TODO: re-enable when entity-only search route is restored


router = APIRouter(prefix="/graph", tags=["mcp-graph"])


async def _recall_memories(db: AsyncSession, data: RecallRequest) -> List[MemoryOut]:
    """Structured recall by source and/or date range."""
    stmt = select(Memory)

    if data.source:
        stmt = stmt.where(Memory.source == data.source)

    if data.since:
        stmt = stmt.where(Memory.captured_at >= func.timezone("UTC", data.since))

    stmt = stmt.order_by(Memory.captured_at.desc()).limit(data.limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [MemoryOut.model_validate(r) for r in rows]


# async def _search_entities_by_name(
#     db: AsyncSession, entity_name: str
# ) -> List[EntityOut]:
#     """Search entities by name (case-insensitive contains)."""
#     stmt = (
#         select(Entity)
#         .where(func.lower(Entity.name).contains(func.lower(entity_name)))
#         .order_by(Entity.id.desc())
#     )
#     result = await db.execute(stmt)
#     rows = result.scalars().all()
#     return [EntityOut.model_validate(r) for r in rows]


async def _traverse_from_entity(
    db: AsyncSession, entity_name: str, depth: int = 2
) -> GraphTraversalResult:
    """
    Traverse Neo4j graph from a named entity node to reachable nodes.

    Cypher traversal: matches any node by name, then walks up to `depth` hops
    to any connected MemoryChunk or Fact.

    - MemoryChunks: revoked=false filter applied in Cypher. Hydrated from Postgres.
    - Facts: resolved through their REPLACES chains via get_latest_fact() before
      returning. Superseded facts are replaced by their newest valid descendant.

    Note: the unlabeled MATCH (e {name: $name}) is intentionally flexible —
    a Person, Project, Concept, etc. all resolve correctly. At scale,
    adding a label predicate (e.g. MATCH (e:Person {name: $name})) with a
    label index would avoid scanning all node types.

    qdrant_id on each MemoryChunk means the graph is self-contained —
    content can be resolved directly from Qdrant if Postgres is bypassed.
    """
    prefix = f"{NodeId.MEMORY_CHUNK.value}:"

    driver = get_driver()
    with driver.session() as session:
        # Single-pass traversal: entity anchor matched once, then walks to both
        # MemoryChunk and Fact in separate OPTIONAL MATCHes sharing the same start.
        result = session.run(
            """
            MATCH (e {name: $name})
            WITH e
            OPTIONAL MATCH (e)-[*1..$depth]-(m:MemoryChunk)
            WHERE m.revoked IS NULL OR m.revoked = false
            WITH e, collect(DISTINCT {memory_id: m.id, qdrant_id: m.qdrant_id}) as mem_records
            OPTIONAL MATCH (e)-[*1..$depth]-(f:Fact)
            RETURN mem_records, collect(DISTINCT {fact_id: f.id}) as fact_records
            """,
            name=entity_name,
            depth=depth,
        )
        row = result.single()
        records = []
        if row:
            mem_records = row.get("mem_records") or []
            fact_records = row.get("fact_records") or []
            for r in mem_records:
                if r.get("memory_id"):  # skip null rows from OPTIONAL MATCH with no matches
                    records.append({
                        "node_type": "MemoryChunk",
                        "memory_id": r.get("memory_id"),
                        "qdrant_id": r.get("qdrant_id"),
                    })
            for r in fact_records:
                if r.get("fact_id"):  # skip null rows from OPTIONAL MATCH with no matches
                    records.append({
                        "node_type": "Fact",
                        "fact_id": r.get("fact_id"),
                    })

    if not records:
        return GraphTraversalResult(memories=[], facts=[])

    # Separate MemoryChunks and Facts
    memory_ids = []
    fact_ids_seen = set()
    for r in records:
        if r.get("node_type") == "MemoryChunk":
            prefixed_id = r.get("memory_id")
            if prefixed_id and prefixed_id.startswith(prefix):
                uuid_str = prefixed_id[len(prefix):]
                memory_ids.append(uuid.UUID(uuid_str))
        elif r.get("node_type") == "Fact":
            fact_ids_seen.add(r.get("fact_id"))

    # Hydrate MemoryChunks from Postgres, preserving traversal order
    memories = []
    if memory_ids:
        stmt = select(Memory).where(Memory.id.in_(memory_ids))
        result = await db.execute(stmt)
        rows = result.scalars().all()
        memories_map = {row.id: row for row in rows}
        for mid in memory_ids:
            if mid in memories_map:
                memories.append(MemoryOut.model_validate(memories_map[mid]))

    # Resolve Facts through REPLACES chains, deduplicating superseded nodes.
    # If a superseded fact is encountered, get_latest_fact returns the newest
    # valid descendant — preventing older versions from appearing in results.
    resolved_facts: dict[str, FactOut] = {}
    for fact_id in fact_ids_seen:
        resolved = get_latest_fact(fact_id)
        if resolved:
            resolved_facts[resolved["id"]] = FactOut(
                id=resolved["id"],
                content=resolved["content"],
                valid_from=resolved["valid_from"],
                valid_until=resolved.get("valid_until"),
                version=resolved["version"],
            )

    return GraphTraversalResult(
        memories=memories,
        facts=list(resolved_facts.values()),
    )


@router.post("/recall", response_model=List[MemoryOut], status_code=200)
async def recall_route(
    data: RecallRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    return await _recall_memories(db, data)


@router.post("/search", response_model=GraphTraversalResult, status_code=200)
async def graph_search_route(
    data: GraphSearchRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    """
    Traverse the Neo4j graph from a named entity to all reachable nodes.

    Uses Cypher to walk up to `depth` hops from the entity node to any
    reachable MemoryChunk or Fact. Facts are resolved through their REPLACES
    chains — superseded facts are replaced by their newest valid descendant.

    Returns both resolved memories (hydrated from Postgres) and facts
    (resolved from Neo4j) in a single response.
    """
    return await _traverse_from_entity(db, data.entity_name, data.depth)
