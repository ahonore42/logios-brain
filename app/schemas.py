"""Pydantic request/response schemas for all MCP tool endpoints."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ── Request schemas ──────────────────────────────────────────────────────────


class RememberRequest(BaseModel):
    content: str
    source: str = "manual"
    session_id: Optional[UUID] = None
    metadata: dict = {}


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    threshold: float = 0.65
    as_of: Optional[datetime] = None  # time-bounded retrieval filter


class RecallRequest(BaseModel):
    source: Optional[str] = None
    since: Optional[str] = None
    limit: int = 20


class GraphSearchRequest(BaseModel):
    entity_name: str
    depth: int = 2


class RelateRequest(BaseModel):
    entity_a: str
    entity_b: str
    relationship_type: str = "RELATES_TO"


class RunSkillRequest(BaseModel):
    skill_name: str
    context: dict = {}
    model: str = "unknown"
    machine: str = "unknown"


class RecordGenerationRequest(BaseModel):
    skill_id: UUID
    skill_name: str
    output: str
    model: str
    machine: str
    prompt_used: str
    evidence_manifest: list[dict]
    session_id: Optional[UUID] = None


class GetEvidenceRequest(BaseModel):
    generation_id: UUID


class CreateFactRequest(BaseModel):
    tenant_id: str
    content: str
    valid_from: datetime
    valid_until: Optional[datetime] = None
    version: int = 1
    replaces_id: Optional[str] = None  # optional REPLACES link to an older Fact


# ── Response schemas ──────────────────────────────────────────────────────────


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content: str
    source: str
    session_id: Optional[UUID] = None
    captured_at: datetime
    updated_at: datetime
    metadata: dict
    content_fingerprint: Optional[str] = None


class FactOut(BaseModel):
    """A Fact node from Neo4j, resolved through its REPLACES chain."""

    id: str  # prefixed: "fact:<uuid>"
    content: str
    valid_from: datetime
    valid_until: Optional[datetime] = None
    version: int = 1


class GraphTraversalResult(BaseModel):
    """Combined result of a graph traversal — reachable memories and resolved facts."""

    memories: list[MemoryOut]
    facts: list[FactOut]


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    memory_id: UUID
    content: str
    chunk_index: int
    token_count: Optional[int] = None
    qdrant_id: Optional[UUID] = None
    created_at: datetime


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    memory_id: UUID
    neo4j_node_id: str
    label: str
    name: str
    created_at: datetime


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str] = None
    prompt_template: str
    version: int
    active: bool
    created_at: datetime
    updated_at: datetime


class GenerationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    skill_id: Optional[UUID] = None
    skill_name: Optional[str] = None
    output: str
    model: str
    machine: Optional[str] = None
    session_id: Optional[UUID] = None
    prompt_used: Optional[str] = None
    generated_at: datetime
    metadata: dict


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    generation_id: UUID
    memory_id: Optional[UUID] = None
    chunk_id: Optional[UUID] = None
    neo4j_node_id: Optional[str] = None
    neo4j_rel_type: Optional[str] = None
    relevance_score: Optional[str] = None
    retrieval_type: str
    rank: int
    created_at: datetime


class EvidenceWithContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    generation_id: UUID
    memory_id: Optional[UUID] = None
    memory_content: Optional[str] = None
    memory_source: Optional[str] = None
    captured_at: Optional[datetime] = None
    chunk_content: Optional[str] = None
    neo4j_node_id: Optional[str] = None
    neo4j_rel_type: Optional[str] = None
    rank: int
    retrieval_type: str
    relevance_score: Optional[str] = None


class GenerationReceipt(BaseModel):
    generation: GenerationOut
    evidence: list[EvidenceWithContentOut]
