"""Pydantic request/response schemas for all MCP tool endpoints."""

from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ── Request schemas ──────────────────────────────────────────────────────────


class RememberRequest(BaseModel):
    content: str
    source: str = "manual"
    type: Optional[str] = "standard"
    session_id: Optional[UUID] = None
    metadata: dict = {}


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    threshold: float = 0.65
    as_of: Optional[datetime] = None  # time-bounded retrieval filter


class ContextRequest(BaseModel):
    """Request context for an agent turn: identity + episodic memories."""

    query: str
    session_id: Optional[UUID] = None
    top_k: int = 8
    include_identity: bool = True


class ContextResponse(BaseModel):
    """Response for /memories/context — identity memories always, episodic on query."""

    identity_memories: list["MemoryOut"]
    episodic_memories: list["MemoryOut"]


class IdentityRequest(BaseModel):
    """Create a type='identity' memory. Owner-only."""

    content: str
    metadata: dict = {}


class IdentityResponse(BaseModel):
    """Response after creating an identity memory."""

    memory: "MemoryOut"
    message: str


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
    type: str
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


# ── Auth schemas ──────────────────────────────────────────────────────────────


class Token(BaseModel):
    """OAuth2-style token response."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int  # seconds


class OwnerSetup(BaseModel):
    """First-time owner setup."""

    email: EmailStr
    password: Annotated[str, Field(min_length=8)]


class OwnerPublic(BaseModel):
    """Public owner info (no sensitive fields)."""

    id: int
    email: str | None
    is_setup: bool
    created_at: datetime


class TokenCreate(BaseModel):
    """Request to create a new agent token."""

    name: str = Field(..., min_length=1, max_length=200)
    expires_in_days: int | None = None  # None = never expires


class TokenResponse(BaseModel):
    """Agent token info (no raw token)."""

    id: int
    agent_id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None
    is_active: bool  # revoked_at is None

    @classmethod
    def from_row(cls, row) -> "TokenResponse":
        return cls(
            id=row.id,
            agent_id=row.agent_id,
            name=row.name,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            is_active=row.revoked_at is None,
        )


class TokenCreateResponse(BaseModel):
    """Response when creating a token — raw token shown ONLY here."""

    id: int
    agent_id: str
    token: str  # raw token, shown only once
    name: str
    created_at: datetime


class TokenList(BaseModel):
    """List of token info objects."""

    data: list[TokenResponse]
    count: int


class Message(BaseModel):
    """Generic string message response."""

    message: str


# ── Form request models ───────────────────────────────────────────────────────


class LoginForm(BaseModel):
    """Owner login form."""

    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class VerifySetupForm(BaseModel):
    """Complete owner setup with OTP."""

    pending_token: str = Field(...)
    otp: str = Field(..., min_length=6, max_length=6)


class RefreshTokenForm(BaseModel):
    """Exchange a refresh token for a new access token."""

    refresh_token: str = Field(...)


class AgentTokenExchangeForm(BaseModel):
    """Exchange a raw agent token for a short-lived access token."""

    authorization: str = Field(...)  # Bearer <raw_token>


# ── Auth runtime types ─────────────────────────────────────────────────────────


class PendingSetup:
    """Temporary container for pending owner setup data (not a Pydantic schema)."""

    def __init__(self, email: str, hashed_password: str, otp_hash: str) -> None:
        self.email = email
        self.hashed_password = hashed_password
        self.otp_hash = otp_hash


class AuthContext:
    """Auth context attached to request.state after middleware validates the token."""

    def __init__(
        self,
        token_hash: str | None = None,
        agent_id: str | None = None,
        owner_id: int | None = None,
        token_scope: str | None = None,
    ) -> None:
        self.token_hash = token_hash
        self.agent_id = agent_id
        self.owner_id = owner_id
        self.token_scope = token_scope

    @property
    def is_owner(self) -> bool:
        return self.token_scope == "owner"

    @property
    def is_agent(self) -> bool:
        return self.token_scope == "agent"
