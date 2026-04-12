"""Evidence recording: call POST /skills/record after an agent generates output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

import httpx


@dataclass
class EvidenceEntry:
    """A single memory or entity that informed a generation."""

    memory_id: Optional[UUID] = None
    chunk_id: Optional[UUID] = None
    neo4j_node_id: Optional[str] = None
    neo4j_rel_type: Optional[str] = None
    relevance_score: float = 0.0
    retrieval_type: str = "unknown"
    rank: int = 0


@dataclass
class GenerationRecord:
    """
    Record an agent generation with its evidence manifest.

    Call record_generation() after the agent produces output. This writes
    the full evidence path to Logios so the agent can later query
    "what did I do and why" via GET /skills/evidence.

    Usage::

        record = GenerationRecord(
            skill_name="weekly-review",
            output="Summary: Q1 revenue up 12%...",
            model="microsoft/phi-3-mini-128k-instruct",
            machine="desktop-mac",
            session_id=session_id,
            prompt_used="Produce a weekly review for week of 2026-04-12",
            evidence=[
                EvidenceEntry(memory_id=mem_id, relevance_score=0.9, retrieval_type="semantic", rank=0),
                EvidenceEntry(memory_id=mem_id2, relevance_score=0.7, retrieval_type="episodic", rank=1),
            ],
        )
        receipt = record_generation(
            api_base_url="http://localhost:8000",
            api_key="your-brain-key",
            record=record,
        )
    """

    skill_name: str
    output: str
    model: str
    machine: str
    evidence: list[EvidenceEntry] = field(default_factory=list)
    session_id: Optional[UUID] = None
    skill_id: Optional[UUID] = None
    prompt_used: str = ""


def record_generation(
    api_base_url: str,
    api_key: str,
    record: GenerationRecord,
) -> dict:
    """
    POST /skills/record with generation output and evidence manifest.

    Returns the full generation receipt from Logios.

    Raises httpx.HTTPStatusError on non-2xx response.
    """
    evidence_manifest = [
        {
            "memory_id": str(e.memory_id) if e.memory_id else None,
            "chunk_id": str(e.chunk_id) if e.chunk_id else None,
            "neo4j_node_id": e.neo4j_node_id,
            "neo4j_rel_type": e.neo4j_rel_type,
            "relevance_score": e.relevance_score,
            "retrieval_type": e.retrieval_type,
            "rank": e.rank,
        }
        for e in record.evidence
    ]

    payload: dict[str, Any] = {
        "skill_name": record.skill_name,
        "output": record.output,
        "model": record.model,
        "machine": record.machine,
        "evidence_manifest": evidence_manifest,
        "prompt_used": record.prompt_used,
    }

    if record.skill_id:
        payload["skill_id"] = str(record.skill_id)
    if record.session_id:
        payload["session_id"] = str(record.session_id)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{api_base_url.rstrip('/')}/skills/record",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
