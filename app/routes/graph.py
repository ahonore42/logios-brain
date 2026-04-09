"""Routes for recall and graph operations."""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.graph import recall_memories, search_entities_by_name
from app.database import get_db
from app.dependencies import verify_key
from app.schemas import EntityOut, GraphSearchRequest, MemoryOut, RecallRequest

router = APIRouter(prefix="/graph", tags=["mcp-graph"])


@router.post("/recall", response_model=List[MemoryOut], status_code=200)
async def recall_route(
    data: RecallRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    return await recall_memories(db, data)


@router.post("/search", response_model=List[EntityOut], status_code=200)
async def graph_search_route(
    data: GraphSearchRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    return await search_entities_by_name(db, data.entity_name)
