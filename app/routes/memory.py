"""Routes for memory operations — remember and search."""

import uuid
from typing import List

from celery import chain
from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import JSON

from app.genai import embeddings
from app.db.database import get_db
from app.db import qdrant as qdrant_db
from app.db.neo4j.client import NodeId, prefixed_id
from app.dependencies import require_owner, verify_key
from app.models import Chunk, Memory
from app.schemas import (
    ContextRequest,
    ContextResponse,
    IdentityRequest,
    IdentityResponse,
    MemoryOut,
    RememberRequest,
    SearchRequest,
)
from app.automation.tasks import (
    task_extract_entities,
    task_upsert_neo4j,
    task_upsert_qdrant,
)


class JsonDict(JSON):
    """Coerce JSONB to plain dict after load."""

    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        return dict(value)


router = APIRouter(prefix="/memories", tags=["mcp-memory"])


async def _upsert_memory(db: AsyncSession, data: RememberRequest) -> MemoryOut:
    """
    Write path:
    1. Upsert memory to Postgres (dedup via content_fingerprint) — sync
    2. NVIDIA NIM: text → vector — sync
    3. Qdrant + Neo4j writes — dispatched to Celery background task
    """
    import json as _json

    # 1. Postgres upsert
    result = await db.execute(
        text(
            "SELECT upsert_memory(:content, :source, cast(:metadata as jsonb), :session_id, :type)"
        ),
        {
            "content": data.content,
            "source": data.source,
            "metadata": _json.dumps(data.metadata),
            "session_id": data.session_id,
            "type": data.type or "standard",
        },
    )
    memory_id = result.scalar()

    # 2. NVIDIA NIM: translate text → vector (one-time, stateless)
    vector = await embeddings.embed(data.content)
    qdrant_id = str(uuid.uuid4())

    # 3. Insert chunk record
    chunk = Chunk(
        memory_id=memory_id,
        content=data.content,
        chunk_index=0,
        qdrant_id=qdrant_id,
    )
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)

    # Fetch memory for return (Neo4j needs captured_at)
    stmt = select(Memory).where(Memory.id == memory_id)
    memory = (await db.execute(stmt)).scalar_one()

    # 4. Dispatch Qdrant + Neo4j writes as a Celery chain.
    #    task_upsert_qdrant runs first; task_upsert_neo4j only runs if it succeeds.
    #    Each task has its own retry budget.
    chunk_node_dict = {
        "id": prefixed_id(NodeId.MEMORY_CHUNK, str(memory_id)),
        "timestamp_utc": str(memory.captured_at),
        "type": data.source,
        "revoked": data.metadata.get("revoked", False),
        "version": 1,
        "importance": data.metadata.get("importance", 0.5),
        "confidence": data.metadata.get("confidence", 1.0),
    }
    event_id = prefixed_id(NodeId.EVENT, str(uuid.uuid4()))
    chain(
        task_upsert_qdrant.s(
            qdrant_id=qdrant_id,
            vector=vector,
            payload={
                "memory_id": str(memory_id),
                "chunk_id": str(chunk.id),
                "source": data.source,
                "session_id": str(data.session_id) if data.session_id else None,
                "valid_from": str(memory.captured_at),
                "valid_until": data.metadata.get("valid_until"),
                "revoked": data.metadata.get("revoked", False),
                "policy_version": data.metadata.get("policy_version", 1),
            },
        ),
        task_upsert_neo4j.s(
            chunk_node=chunk_node_dict,
            session_id=str(data.session_id) if data.session_id else None,
            event_id=event_id,
            event_type=data.source,
            event_description=f"Memory captured: {data.source}",
        ),
        task_extract_entities.s(
            content=data.content,
            chunk_node_id=prefixed_id(NodeId.MEMORY_CHUNK, str(memory_id)),
        ),
    ).delay()

    return MemoryOut(
        id=memory.id,
        content=memory.content,
        source=memory.source,
        type=memory.type,
        session_id=memory.session_id,
        captured_at=memory.captured_at,
        updated_at=memory.updated_at,
        metadata=memory.metadata_,
        content_fingerprint=memory.content_fingerprint,
    )


async def _search_memories(db: AsyncSession, data: SearchRequest) -> List[MemoryOut]:
    vector = await embeddings.embed_query(data.query)

    query_filter = None
    if data.as_of is not None:
        from qdrant_client.models import (
            DatetimeRange,
            FieldCondition,
            Filter,
            IsNullCondition,
            MatchValue,
            PayloadField,
        )

        query_filter = Filter(
            must=[
                FieldCondition(
                    key="revoked",
                    match=MatchValue(value=False),
                ),
                FieldCondition(
                    key="valid_from",
                    range=DatetimeRange(lte=data.as_of),
                ),
                Filter(
                    should=[
                        FieldCondition(
                            key="valid_until",
                            range=DatetimeRange(gte=data.as_of),
                        ),
                        IsNullCondition(is_null=PayloadField(key="valid_until")),
                    ]
                ),
            ]
        )

    response = qdrant_db.get_qdrant().query_points(
        collection_name=qdrant_db.COLLECTION_NAME,
        query=vector,
        limit=data.top_k,
        score_threshold=data.threshold,
        with_payload=True,
        query_filter=query_filter,
    )
    results = response.points

    if not results:
        return []

    memory_ids = [uuid.UUID(r.payload["memory_id"]) for r in results if r.payload]
    stmt = select(Memory).where(Memory.id.in_(memory_ids))
    result = await db.execute(stmt)
    rows = result.scalars().all()
    memories = {row.id: row for row in rows}

    ordered = [memories[mid] for mid in memory_ids if mid in memories]
    return [MemoryOut.model_validate(r) for r in ordered]


@router.post("/remember", response_model=MemoryOut, status_code=201)
async def remember_route(
    data: RememberRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    return await _upsert_memory(db, data)


@router.post("/search", response_model=List[MemoryOut], status_code=200)
async def search_route(
    data: SearchRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    return await _search_memories(db, data)


@router.post("/context", response_model=ContextResponse, status_code=200)
async def context_route(
    data: ContextRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
) -> ContextResponse:
    """
    Return memory context for an agent turn.

    Always includes type='identity' memories (human-authored core instructions).
    Episodic memories (checkpoints from prior sessions) are retrieved via
    Qdrant vector search filtered by session_id.
    """
    # 1. Identity memories — always loaded, always first
    identity_stmt = select(Memory).where(Memory.type == "identity")
    identity_result = await db.execute(identity_stmt)
    identity_memories = [MemoryOut.model_validate(r) for r in identity_result.scalars().all()]

    # 2. Episodic memories — Qdrant search filtered by session
    episodic_memories: List[MemoryOut] = []
    vector = await embeddings.embed_query(data.query)

    session_filter = None
    if data.session_id:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        session_filter = Filter(
            must=[
                FieldCondition(key="session_id", match=MatchValue(value=str(data.session_id))),
                FieldCondition(key="revoked", match=MatchValue(value=False)),
            ]
        )

    response = qdrant_db.get_qdrant().query_points(
        collection_name=qdrant_db.COLLECTION_NAME,
        query=vector,
        limit=data.top_k,
        score_threshold=0.65,
        with_payload=True,
        query_filter=session_filter,
    )

    results = response.points
    if results:
        memory_ids = [uuid.UUID(r.payload["memory_id"]) for r in results if r.payload]
        episodic_stmt = select(Memory).where(Memory.id.in_(memory_ids))
        episodic_result = await db.execute(episodic_stmt)
        rows = episodic_result.scalars().all()
        memories_by_id = {row.id: row for row in rows}
        ordered = [memories_by_id[mid] for mid in memory_ids if mid in memories_by_id]
        episodic_memories = [MemoryOut.model_validate(r) for r in ordered]

    return ContextResponse(
        identity_memories=identity_memories,
        episodic_memories=episodic_memories,
    )


@router.post("/identity", response_model=IdentityResponse, status_code=201)
async def create_identity_route(
    data: IdentityRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_owner),
) -> IdentityResponse:
    """
    Create a type='identity' memory. Owner-only.

    Identity memories are the persistent instruction layer — human-authored,
    always injected at session start, never modified by agents.
    """
    identity_request = RememberRequest(
        content=data.content,
        source="system",
        type="identity",
        metadata=data.metadata,
    )
    memory = await _upsert_memory(db, identity_request)
    return IdentityResponse(
        memory=memory,
        message="Identity memory created. It will be loaded at the start of every session.",
    )
