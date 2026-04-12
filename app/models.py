"""SQLAlchemy ORM models for Logios Brain."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as pg_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[UUID] = mapped_column(
        pg_UUID, primary_key=True, server_default=func.gen_random_uuid()
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[Optional[UUID]] = mapped_column(pg_UUID)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'")
    )
    content_fingerprint: Mapped[Optional[str]] = mapped_column(
        String, unique=True, nullable=True
    )

    chunks: Mapped[list["Chunk"]] = relationship("Chunk", back_populates="memory")
    entities: Mapped[list["Entity"]] = relationship("Entity", back_populates="memory")

    __table_args__ = (
        CheckConstraint(
            "source IN ('telegram', 'claude', 'agent', 'manual', 'import', 'system')",
            name="memories_source_check",
        ),
        Index("idx_memories_source", "source"),
        Index("idx_memories_captured_at", "captured_at"),
        Index("idx_memories_session_id", "session_id"),
        Index("idx_memories_metadata", "metadata", postgresql_using="gin"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(
        pg_UUID, primary_key=True, server_default=func.gen_random_uuid()
    )
    memory_id: Mapped[UUID] = mapped_column(
        pg_UUID, ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[Optional[int]] = mapped_column(Integer)
    qdrant_id: Mapped[Optional[UUID]] = mapped_column(pg_UUID, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    memory: Mapped["Memory"] = relationship("Memory", back_populates="chunks")

    __table_args__ = (
        Index("idx_chunks_memory_id", "memory_id"),
        Index("idx_chunks_qdrant_id", "qdrant_id"),
    )


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[UUID] = mapped_column(
        pg_UUID, primary_key=True, server_default=func.gen_random_uuid()
    )
    memory_id: Mapped[UUID] = mapped_column(
        pg_UUID, ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )
    neo4j_node_id: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    memory: Mapped["Memory"] = relationship("Memory", back_populates="entities")

    __table_args__ = (
        CheckConstraint(
            "label IN ('Project', 'Concept', 'Person', 'Session', 'Event', 'Decision', 'Tool', 'Location')",
            name="entities_label_check",
        ),
        Index("idx_entities_memory_id", "memory_id"),
        Index("idx_entities_neo4j_node_id", "neo4j_node_id"),
        Index("idx_entities_label", "label"),
        Index("idx_entities_neo4j_unique", "neo4j_node_id", unique=True),
    )


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[UUID] = mapped_column(
        pg_UUID, primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column("active", Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    generations: Mapped[list["Generation"]] = relationship(
        "Generation", back_populates="skill"
    )

    __table_args__ = (
        Index(
            "idx_skills_active_where_active",
            "active",
            postgresql_where=(text("active = true")),
        ),
    )


class Generation(Base):
    __tablename__ = "generations"

    id: Mapped[UUID] = mapped_column(
        pg_UUID, primary_key=True, server_default=func.gen_random_uuid()
    )
    skill_id: Mapped[Optional[UUID]] = mapped_column(
        pg_UUID, ForeignKey("skills.id", ondelete="SET NULL")
    )
    skill_name: Mapped[Optional[str]] = mapped_column(String, index=True)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    machine: Mapped[Optional[str]] = mapped_column(String)
    session_id: Mapped[Optional[UUID]] = mapped_column(pg_UUID)
    prompt_used: Mapped[Optional[str]] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'")
    )

    skill: Mapped[Optional["Skill"]] = relationship(
        "Skill", back_populates="generations"
    )
    evidence: Mapped[list["Evidence"]] = relationship(
        "Evidence", back_populates="generation"
    )

    __table_args__ = (
        Index("idx_generations_skill_id", "skill_id"),
        Index("idx_generations_skill_name", "skill_name"),
        Index("idx_generations_generated_at", "generated_at"),
        Index("idx_generations_session_id", "session_id"),
        Index("idx_generations_machine", "machine"),
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[UUID] = mapped_column(
        pg_UUID, primary_key=True, server_default=func.gen_random_uuid()
    )
    generation_id: Mapped[UUID] = mapped_column(
        pg_UUID, ForeignKey("generations.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[Optional[UUID]] = mapped_column(
        pg_UUID, ForeignKey("memories.id", ondelete="SET NULL")
    )
    chunk_id: Mapped[Optional[UUID]] = mapped_column(
        pg_UUID, ForeignKey("chunks.id", ondelete="SET NULL")
    )
    neo4j_node_id: Mapped[Optional[str]] = mapped_column(String)
    neo4j_rel_type: Mapped[Optional[str]] = mapped_column(String)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float)
    retrieval_type: Mapped[str] = mapped_column(String, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    generation: Mapped["Generation"] = relationship(
        "Generation", back_populates="evidence"
    )

    __table_args__ = (
        Index("idx_evidence_generation_id", "generation_id"),
        Index("idx_evidence_memory_id", "memory_id"),
        Index("idx_evidence_chunk_id", "chunk_id"),
    )


class EvidenceWithContent(Base):
    __tablename__ = "evidence_with_content"

    id: Mapped[UUID] = mapped_column(pg_UUID, primary_key=True)
    generation_id: Mapped[UUID] = mapped_column(pg_UUID)
    memory_id: Mapped[Optional[UUID]] = mapped_column(pg_UUID)
    memory_content: Mapped[Optional[str]] = mapped_column(Text)
    memory_source: Mapped[Optional[str]] = mapped_column(String)
    captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    chunk_content: Mapped[Optional[str]] = mapped_column(Text)
    neo4j_node_id: Mapped[Optional[str]] = mapped_column(String)
    neo4j_rel_type: Mapped[Optional[str]] = mapped_column(String)
    rank: Mapped[int] = mapped_column(Integer)
    retrieval_type: Mapped[str] = mapped_column(String)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float)


class Owner(Base):
    """Single owner account. Created once via /auth/setup."""

    __tablename__ = "owner"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False, default="")
    is_setup: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentToken(Base):
    """Named token for an agent. Raw token shown once at creation; only hash stored."""

    __tablename__ = "agent_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    agent_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_agent_tokens_agent_id_active", "agent_id", "revoked_at"),
    )
