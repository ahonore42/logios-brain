"""Async ORM CRUD for memories and chunks."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import TypeDecorator, JSON

from app.models import Chunk, Memory
from app.schemas import MemoryOut, RememberRequest, SearchRequest


class JsonDict(TypeDecorator):
    """Coerce JSONB to plain dict after load."""
    impl = JSON
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        return dict(value)


async def upsert_memory(db: AsyncSession, data: RememberRequest) -> MemoryOut:
    """Deduplication-safe memory insert via raw SQL (uses the DB function)."""
    from sqlalchemy import text
    import json

    result = await db.execute(
        text("SELECT upsert_memory(:content, :source, cast(:metadata as jsonb), :session_id)"),
        {
            "content": data.content,
            "source": data.source,
            "metadata": json.dumps(data.metadata),
            "session_id": data.session_id,
        },
    )
    memory_id = result.scalar()
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


async def get_memories_by_ids(
    db: AsyncSession, memory_ids: list[UUID]
) -> dict[UUID, MemoryOut]:
    """Hydrate memory content from a list of memory_ids."""
    if not memory_ids:
        return {}
    stmt = select(Memory).where(Memory.id.in_(memory_ids))
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {row.id: MemoryOut.model_validate(row) for row in rows}


async def search_memories(db: AsyncSession, data: SearchRequest) -> list[MemoryOut]:
    """Full-text search over memory content, ordered by captured_at desc."""
    stmt = (
        select(Memory)
        .where(Memory.content.ilike(f"%{data.query}%"))
        .order_by(Memory.captured_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [MemoryOut.model_validate(r) for r in rows[: data.top_k]]


async def insert_chunk(
    db: AsyncSession,
    memory_id: UUID,
    content: str,
    qdrant_id: Optional[UUID] = None,
    chunk_index: int = 0,
) -> Chunk:
    """Insert a chunk record."""
    chunk = Chunk(
        memory_id=memory_id,
        content=content,
        chunk_index=chunk_index,
        qdrant_id=qdrant_id,
    )
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)
    return chunk
