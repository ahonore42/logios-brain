"""Neo4j graph storage client.

Import from here for the public API:
    from app.db.neo4j import write_memory_chunk, MemoryChunk, RelationshipType
"""

# Expose public API for `from app.db.neo4j import ...`
from .client import (
    get_driver,
    close,
    ensure_indexes,
    DEFAULT_TIMEOUT,
)
from .nodes import (
    MemoryChunk,
    Event,
    Fact,
    AgentNode,
    OutputNode,
    EvidencePath,
    EvidenceStep,
    DateNode,
    PeriodNode,
)
from .relationships import RelationshipType
from .transactions import (
    write_memory_chunk,
    write_event,
    write_fact,
)
from .evidence import (
    create_evidence_path,
    add_evidence_step,
    link_evidence_to_output,
)

# Explicit __all__ to silence Ruff F401 in __init__.py
__all__ = [
    "get_driver",
    "close",
    "ensure_indexes",
    "DEFAULT_TIMEOUT",
    "MemoryChunk",
    "Event",
    "Fact",
    "AgentNode",
    "OutputNode",
    "EvidencePath",
    "EvidenceStep",
    "DateNode",
    "PeriodNode",
    "RelationshipType",
    "write_memory_chunk",
    "write_event",
    "write_fact",
    "create_evidence_path",
    "add_evidence_step",
    "link_evidence_to_output",
]
