"""Routes for skills — run, record generation, and evidence."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import verify_key
from app.models import Evidence, EvidenceWithContent, Generation, Skill
from app.schemas import (
    EvidenceWithContentOut,
    GenerationOut,
    GenerationReceipt,
    GetEvidenceRequest,
    RecordGenerationRequest,
    RunSkillRequest,
    SearchRequest,
)


router = APIRouter(prefix="/skills", tags=["mcp-skills"])


# ── Internal database functions ────────────────────────────────────────────────


async def _get_skill_by_name(db: AsyncSession, name: str) -> Optional[Skill]:
    stmt = select(Skill).where(Skill.name == name, Skill.active)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_or_create_skill(db: AsyncSession, name: str) -> Skill:
    skill = await _get_skill_by_name(db, name)
    if skill is None:
        skill = Skill(
            name=name,
            description=None,
            prompt_template="DEFAULT",
            version=1,
            active=True,
        )
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
    return skill


async def _record_generation(
    db: AsyncSession, data: RecordGenerationRequest
) -> GenerationOut:
    """Write a generation record, evidence rows, and Neo4j evidence path."""
    import hashlib

    from app import config
    from app.db.neo4j import create_evidence_path

    skill = await _get_or_create_skill(db, data.skill_name)

    generation = Generation(
        skill_id=skill.id,
        skill_name=data.skill_name,
        output=data.output,
        model=data.model,
        machine=data.machine,
        session_id=data.session_id,
        prompt_used=data.prompt_used,
        metadata_=data.evidence_manifest,
    )
    db.add(generation)
    await db.commit()
    await db.refresh(generation)

    for item in data.evidence_manifest:
        evidence = Evidence(
            generation_id=generation.id,
            memory_id=item.get("memory_id"),
            chunk_id=item.get("chunk_id"),
            neo4j_node_id=item.get("neo4j_node_id"),
            neo4j_rel_type=item.get("neo4j_rel_type"),
            relevance_score=item.get("relevance_score"),
            retrieval_type=item.get("retrieval_type", "vector"),
            rank=item.get("rank", 0),
        )
        db.add(evidence)

    await db.commit()

    # Extract memory IDs and edge types from evidence manifest for Neo4j
    used_memory_ids = [
        item["memory_id"]
        for item in data.evidence_manifest
        if item.get("memory_id")
    ]
    used_edge_types = list(set(
        item.get("neo4j_rel_type")
        for item in data.evidence_manifest
        if item.get("neo4j_rel_type")
    ))
    if not used_edge_types:
        used_edge_types = ["IN_SESSION"]  # default traversal type

    query_hash = hashlib.sha256(
        data.prompt_used.encode()
    ).hexdigest()

    # Write evidence path to Neo4j
    create_evidence_path(
        evidence_path_id=str(generation.id),
        output_id=str(generation.id),
        tenant_id=config.TENANT_ID,
        agent_id=None,
        query_hash=query_hash,
        machine_id=data.machine,
        used_memory_ids=used_memory_ids,
        used_edge_types=used_edge_types,
        timestamp=str(generation.generated_at),
    )

    return GenerationOut.model_validate(generation)


async def _get_generation(
    db: AsyncSession, generation_id: UUID
) -> Optional[Generation]:
    stmt = select(Generation).where(Generation.id == generation_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_evidence_with_content(
    db: AsyncSession, generation_id: UUID
) -> list[EvidenceWithContentOut]:
    stmt = select(EvidenceWithContent).where(
        EvidenceWithContent.generation_id == generation_id
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [EvidenceWithContentOut.model_validate(r) for r in rows]


async def _get_generation_receipt(
    db: AsyncSession, generation_id: UUID
) -> Optional[GenerationReceipt]:
    generation = await _get_generation(db, generation_id)
    if not generation:
        return None

    evidence = await _get_evidence_with_content(db, generation_id)

    return GenerationReceipt(
        generation=GenerationOut.model_validate(generation),
        evidence=evidence,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/run", status_code=202)
async def run_skill_route(
    data: RunSkillRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    """Prepare a skill execution — returns prompt template and evidence manifest."""
    from app.routes.memory import _search_memories

    stmt = select(Skill).where(Skill.name == data.skill_name, Skill.active)
    result = await db.execute(stmt)
    skill = result.scalar_one_or_none()

    if not skill:
        raise HTTPException(404, f"Skill '{data.skill_name}' not found or inactive")

    query_str = data.context.get("query", data.skill_name)
    search_data = SearchRequest(query=query_str, top_k=8)
    vector_hits = await _search_memories(db, search_data)

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
    return await _record_generation(db, data)


@router.post("/evidence", response_model=GenerationReceipt, status_code=200)
async def get_evidence_route(
    data: GetEvidenceRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_key),
):
    receipt = await _get_generation_receipt(db, data.generation_id)
    if not receipt:
        raise HTTPException(404, "Generation not found")
    return receipt
