"""Async ORM CRUD for recall and entity graph search."""


from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity, Memory
from app.schemas import EntityOut, MemoryOut, RecallRequest


async def recall_memories(
    db: AsyncSession, data: RecallRequest
) -> list[MemoryOut]:
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


async def search_entities_by_name(
    db: AsyncSession, entity_name: str
) -> list[EntityOut]:
    """Search entities by name (case-insensitive contains)."""
    stmt = (
        select(Entity)
        .where(func.lower(Entity.name).contains(func.lower(entity_name)))
        .order_by(Entity.id.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [EntityOut.model_validate(r) for r in rows]
