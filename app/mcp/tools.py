"""MCP tool implementations wrapping existing route logic."""

from uuid import UUID, uuid4

from app.db.neo4j.client import NodeId, prefixed_id
from app.db.neo4j import get_latest_fact, write_fact, Fact
from app.db.database import get_session_maker
from app.schemas import (
    GraphTraversalResult,
    MemoryOut,
    RecallRequest,
    RememberRequest,
    RunSkillRequest,
    SearchRequest,
)


def _db():
    """Sync db session for use in async tool handlers."""
    return get_session_maker()


# ── remember ────────────────────────────────────────────────────────────────


async def remember(
    content: str,
    source: str = "manual",
    session_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Store a memory in Postgres, Qdrant, and Neo4j."""
    from app.routes.memory import _upsert_memory

    request = RememberRequest(
        content=content,
        source=source,
        session_id=UUID(session_id) if session_id else None,
        metadata=metadata or {},
    )
    async with _db()() as db:
        result: MemoryOut = await _upsert_memory(db, request)
        return {
            "memory_id": str(result.id),
            "status": "stored",
            "source": result.source,
        }


# ── search ─────────────────────────────────────────────────────────────────


async def search(
    query: str,
    top_k: int = 10,
    threshold: float = 0.65,
) -> list[dict]:
    """Semantic vector search over memories."""
    from app.routes.memory import _search_memories

    request = SearchRequest(query=query, top_k=top_k, threshold=threshold)
    async with _db()() as db:
        results: list[MemoryOut] = await _search_memories(db, request)
        return [
            {
                "memory_id": str(r.id),
                "content": r.content,
                "source": r.source,
                "captured_at": r.captured_at.isoformat(),
            }
            for r in results
        ]


# ── recall ─────────────────────────────────────────────────────────────────


async def recall(
    source: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Structured recall by source and/or date range."""
    from app.routes.graph import _recall_memories

    request = RecallRequest(source=source, since=since, limit=limit)
    async with _db()() as db:
        results: list[MemoryOut] = await _recall_memories(db, request)
        return [
            {
                "id": str(r.id),
                "content": r.content,
                "source": r.source,
                "session_id": str(r.session_id) if r.session_id else None,
                "captured_at": r.captured_at.isoformat(),
            }
            for r in results
        ]


# ── graph_search ───────────────────────────────────────────────────────────


async def graph_search(
    entity_name: str,
    depth: int = 2,
) -> dict:
    """Traverse the knowledge graph from a named entity."""
    from app.routes.graph import _traverse_from_entity

    async with _db()() as db:
        result: GraphTraversalResult = await _traverse_from_entity(
            db, entity_name, depth
        )
        return {
            "memories": [
                {
                    "id": str(m.id),
                    "content": m.content,
                    "source": m.source,
                    "captured_at": m.captured_at.isoformat(),
                }
                for m in result.memories
            ],
            "facts": [
                {
                    "id": f.id,
                    "content": f.content,
                    "valid_from": f.valid_from.isoformat(),
                    "valid_until": f.valid_until.isoformat() if f.valid_until else None,
                    "version": f.version,
                }
                for f in result.facts
            ],
        }


# ── assert_fact ─────────────────────────────────────────────────────────────


async def assert_fact(
    content: str,
    valid_from: str,
    valid_until: str | None = None,
    version: int = 1,
    replaces_id: str | None = None,
) -> dict:
    """Manually assert a Fact into the graph with optional REPLACES link."""
    fact_id = prefixed_id(NodeId.FACT, str(uuid4()))
    fact = Fact(
        id=fact_id,
        content=content,
        valid_from=valid_from,
        valid_until=valid_until or "2099-12-31T23:59:59Z",
        version=version,
    )
    derived_from_ids = [replaces_id] if replaces_id else None
    write_fact(fact=fact, derived_from_ids=derived_from_ids)
    return {
        "id": fact.id,
        "content": fact.content,
        "valid_from": fact.valid_from,
        "valid_until": fact.valid_until,
        "version": fact.version,
    }


# ── get_fact ───────────────────────────────────────────────────────────────


async def get_fact(fact_id: str) -> dict | None:
    """Retrieve a Fact resolved through its REPLACES chain."""
    resolved = get_latest_fact(fact_id)
    if resolved is None:
        return None
    return {
        "id": resolved["id"],
        "content": resolved["content"],
        "valid_from": resolved["valid_from"],
        "valid_until": resolved.get("valid_until"),
        "version": resolved["version"],
    }


# ── run_skill ───────────────────────────────────────────────────────────────


async def run_skill(
    skill_name: str,
    context: dict | None = None,
    model: str = "unknown",
    machine: str = "unknown",
) -> dict:
    """Prepare a skill execution with evidence context."""
    from app.routes.skills import _get_or_create_skill
    from app.routes.memory import _search_memories

    request = RunSkillRequest(
        skill_name=skill_name,
        context=context or {},
        model=model,
        machine=machine,
    )

    async with _db()() as db:
        skill = await _get_or_create_skill(db, skill_name)
        query_str = request.context.get("query", skill_name)
        search_data = SearchRequest(query=query_str, top_k=8)
        vector_hits = await _search_memories(db, search_data)

        return {
            "skill_id": str(skill.id),
            "skill_name": skill_name,
            "prompt_template": skill.prompt_template,
            "evidence_manifest": [
                {
                    "rank": i + 1,
                    "retrieval_type": "vector",
                    "memory_id": str(hit.id),
                    "content": hit.content,
                    "source": hit.source,
                    "captured_at": str(hit.captured_at),
                }
                for i, hit in enumerate(vector_hits)
            ],
            "context": request.context,
            "model": model,
            "machine": machine,
        }
