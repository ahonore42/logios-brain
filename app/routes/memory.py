"""Routes for memory operations — remember and search."""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.memory import search_memories, upsert_memory
from app.database import get_db
from app.dependencies import verify_key
from app.schemas import MemoryOut, RememberRequest, SearchRequest

router = APIRouter(prefix="/memories", tags=["mcp-memory"])


@router.post("/remember", response_model=MemoryOut, status_code=201)
async def remember_route(
    data: RememberRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    return await upsert_memory(db, data)


@router.post("/search", response_model=List[MemoryOut], status_code=200)
async def search_route(
    data: SearchRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    return await search_memories(db, data)
