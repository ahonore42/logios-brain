"""Routes for memory operations — remember and search."""

import uuid
from typing import List

from fastapi import APIRouter, Depends
from qdrant_client.models import PointStruct
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import JSON

from app import embeddings
from app.db import qdrant as qdrant_db
from app.database import get_db
from app.dependencies import verify_key
from app.models import Chunk, Memory
from app.schemas import MemoryOut, RememberRequest, SearchRequest


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
    1. Upsert memory to Postgres (dedup via content_fingerprint)
    2. NVIDIA NIM: text → vector
    3. Store chunk + vector in Qdrant (permanent)
    """
    import json as _json

    # 1. Postgres upsert
    result = await db.execute(
        text(
            "SELECT upsert_memory(:content, :source, cast(:metadata as jsonb), :session_id)"
        ),
        {
            "content": data.content,
            "source": data.source,
            "metadata": _json.dumps(data.metadata),
            "session_id": data.session_id,
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

    # 4. Qdrant: permanently store vector, indexed by memory_id
    qdrant_db.get_qdrant().upsert(
        collection_name=qdrant_db.COLLECTION_NAME,
        points=[
            PointStruct(
                id=qdrant_id,
                vector=vector,
                payload={
                    "memory_id": str(memory_id),
                    "chunk_id": str(chunk.id),
                    "source": data.source,
                    "session_id": str(data.session_id) if data.session_id else None,
                },
            )
        ],
    )

    # Fetch and return
    stmt = select(Memory).where(Memory.id == memory_id)
    memory = (await db.execute(stmt)).scalar_one()

    return MemoryOut(
        id=memory.id,
        content=memory.content,
        source=memory.source,
        session_id=memory.session_id,
        captured_at=memory.captured_at,
        updated_at=memory.updated_at,
        metadata=memory.metadata_,
        content_fingerprint=memory.content_fingerprint,
    )


async def _search_memories(db: AsyncSession, data: SearchRequest) -> List[MemoryOut]:
    """
    Search path:
    1. NVIDIA NIM: query text → vector (one-time)
    2. Qdrant: similarity search → memory_ids
    3. Postgres: hydrate full memory records
    """
    # 1. NVIDIA NIM: translate query → vector
    vector = await embeddings.embed_query(data.query)

    # 2. Qdrant: find closest vectors → returns scored memory_ids
    results = qdrant_db.get_qdrant().search(
        collection_name=qdrant_db.COLLECTION_NAME,
        query_vector=vector,
        limit=data.top_k,
        score_threshold=data.threshold,
        with_payload=True,
    )

    if not results:
        return []

    # 3. Postgres: hydrate full records
    memory_ids = [uuid.UUID(r.payload["memory_id"]) for r in results]
    stmt = select(Memory).where(Memory.id.in_(memory_ids))
    result = await db.execute(stmt)
    rows = result.scalars().all()
    memories = {row.id: row for row in rows}

    # Preserve Qdrant score order
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
