"""Typed node classes for Neo4j graph."""
from dataclasses import dataclass


@dataclass
class MemoryChunk:
    """A memory stored in the system. Mirrors PostgreSQL memory.id."""
    id: str
    tenant_id: str = ""  # kept for schema compatibility; hardcoded on write
    timestamp_utc: str = ""
    type: str = ""  # "conversation", "decision", "event", "fact-summary"
    qdrant_id: str | None = None  # cross-reference to vector store
    revoked: bool = False  # soft-deletion — filters apply at traversal time
    version: int = 1
    importance: float = 0.5
    confidence: float = 1.0


@dataclass
class Event:
    """Something that happened — meeting, decision, tool call, approval, error."""
    id: str
    tenant_id: str = ""  # kept for schema compatibility; hardcoded on write
    agent_id: str | None = None
    type: str = ""  # "meeting", "decision", "tool_call", "approval", "error"
    description: str = ""
    timestamp_utc: str = ""


@dataclass
class Fact:
    """A structured, time-bounded piece of knowledge."""
    id: str
    tenant_id: str = ""  # kept for schema compatibility; hardcoded on write
    content: str = ""
    valid_from: str = ""
    valid_until: str = ""
    version: int = 1


@dataclass
class DateNode:
    """A calendar date."""
    date: str  # "2026-04-09"


@dataclass
class PeriodNode:
    """A named time period."""
    name: str  # "Q1-2026"


@dataclass
class AgentNode:
    """An AI agent that acted."""
    id: str
    tenant_id: str
    name: str
    role: str  # "planner", "legal-advisor", "executor"
    model_used: str | None = None


@dataclass
class OutputNode:
    """An AI-generated output."""
    id: str
    tenant_id: str
    type: str  # "analysis", "plan", "summary", "decision_recommendation"
    timestamp: str


@dataclass
class EvidencePath:
    """The reasoning trace for one AI output — which memories were read,
    which edges were followed, which agent acted."""
    id: str
    output_id: str
    tenant_id: str
    agent_id: str | None
    query_hash: str
    machine_id: str | None
    timestamp: str


@dataclass
class EvidenceStep:
    """One step in the reasoning chain."""
    id: str
    step_type: str  # "read_memory", "query_policy", "merge_context", "generate_output"
    order: int
