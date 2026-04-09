"""Routes for skills — run, record generation, and evidence."""


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.skills import (
    get_generation_receipt,
    record_generation,
)
from app.database import get_db
from app.dependencies import verify_key
from app.schemas import (
    GenerationOut,
    GenerationReceipt,
    GetEvidenceRequest,
    RecordGenerationRequest,
    RunSkillRequest,
)

router = APIRouter(prefix="/skills", tags=["mcp-skills"])


@router.post("/run", status_code=202)
async def run_skill_route(
    data: RunSkillRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    """Prepare a skill execution — returns prompt template and evidence manifest."""
    from app.crud.memory import search_memories
    from app.schemas import SearchRequest

    from sqlalchemy import select
    from app.models import Skill

    stmt = select(Skill).where(Skill.name == data.skill_name, Skill.active)
    result = await db.execute(stmt)
    skill = result.scalar_one_or_none()

    if not skill:
        raise HTTPException(404, f"Skill '{data.skill_name}' not found or inactive")

    # Retrieve context
    query_str = data.context.get("query", data.skill_name)
    search_data = SearchRequest(query=query_str, top_k=8)
    vector_hits = await search_memories(db, search_data)

    return {
        "skill_id": str(skill.id),
        "skill_name": data.skill_name,
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
        "context": data.context,
        "model": data.model,
        "machine": data.machine,
    }


@router.post("/record", response_model=GenerationOut, status_code=201)
async def record_generation_route(
    data: RecordGenerationRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    return await record_generation(db, data)


@router.post("/evidence", response_model=GenerationReceipt, status_code=200)
async def get_evidence_route(
    data: GetEvidenceRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    receipt = await get_generation_receipt(db, data.generation_id)
    if not receipt:
        raise HTTPException(404, "Generation not found")
    return receipt
