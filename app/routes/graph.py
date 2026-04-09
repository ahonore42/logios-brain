"""Routes for recall and graph operations."""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import verify_key
from app.models import Entity, Memory
from app.schemas import EntityOut, GraphSearchRequest, MemoryOut, RecallRequest


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


async def _search_entities_by_name(
    db: AsyncSession, entity_name: str
) -> List[EntityOut]:
    """Search entities by name (case-insensitive contains)."""
    stmt = (
        select(Entity)
        .where(func.lower(Entity.name).contains(func.lower(entity_name)))
        .order_by(Entity.id.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [EntityOut.model_validate(r) for r in rows]


@router.post("/recall", response_model=List[MemoryOut], status_code=200)
async def recall_route(
    data: RecallRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    return await _recall_memories(db, data)


@router.post("/search", response_model=List[EntityOut], status_code=200)
async def graph_search_route(
    data: GraphSearchRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    return await _search_entities_by_name(db, data.entity_name)
