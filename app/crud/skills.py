"""Async ORM CRUD for skills, generations, and evidence."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Evidence, EvidenceWithContent, Generation, Skill
from app.schemas import (
    GenerationOut,
    EvidenceWithContentOut,
    GenerationReceipt,
    RecordGenerationRequest,
)


async def get_skill_by_name(db: AsyncSession, name: str) -> Optional[Skill]:
    """Get an active skill by name."""
    stmt = select(Skill).where(Skill.name == name, Skill.active)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_skill(db: AsyncSession, name: str) -> Skill:
    """Get or create a skill by name."""
    skill = await get_skill_by_name(db, name)
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


async def record_generation(
    db: AsyncSession, data: RecordGenerationRequest
) -> GenerationOut:
    """Write a generation record and evidence rows."""
    skill = await get_or_create_skill(db, data.skill_name)

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

    # Write evidence rows
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
    return GenerationOut.model_validate(generation)


async def get_generation(db: AsyncSession, generation_id: UUID) -> Optional[Generation]:
    """Get a generation by ID."""
    stmt = select(Generation).where(Generation.id == generation_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_evidence_with_content(
    db: AsyncSession, generation_id: UUID
) -> list[EvidenceWithContentOut]:
    """Get evidence with full content for a generation."""
    stmt = select(EvidenceWithContent).where(
        EvidenceWithContent.generation_id == generation_id
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [EvidenceWithContentOut.model_validate(r) for r in rows]


async def get_generation_receipt(
    db: AsyncSession, generation_id: UUID
) -> Optional[GenerationReceipt]:
    """Get full generation receipt with evidence."""
    generation = await get_generation(db, generation_id)
    if not generation:
        return None

    evidence = await get_evidence_with_content(db, generation_id)

    return GenerationReceipt(
        generation=GenerationOut.model_validate(generation),
        evidence=evidence,
    )
