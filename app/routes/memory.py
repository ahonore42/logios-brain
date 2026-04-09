"""Routes for memory operations — remember and search."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import TypeDecorator, JSON

from app.database import get_db
from app.dependencies import verify_key
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


router = APIRouter(prefix="/memories", tags=["mcp-memory"])


async def _upsert_memory(db: AsyncSession, data: RememberRequest) -> MemoryOut:
    """Deduplication-safe memory insert via raw SQL (uses the DB function)."""
    from sqlalchemy import text
    import json

    result = await db.execute(
        text(
            "SELECT upsert_memory(:content, :source, cast(:metadata as jsonb), :session_id)"
        ),
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


async def _search_memories(db: AsyncSession, data: SearchRequest) -> List[MemoryOut]:
    """Full-text search over memory content, ordered by captured_at desc."""
    stmt = (
        select(Memory)
        .where(Memory.content.ilike(f"%{data.query}%"))
        .order_by(Memory.captured_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [MemoryOut.model_validate(r) for r in rows[: data.top_k]]


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
