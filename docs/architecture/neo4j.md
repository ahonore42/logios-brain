# Neo4j Architecture

## Role

Neo4j is the **map maker** and **evidence layer**. It stores memories as nodes, draws typed relationships between them, and records full provenance traces for every AI output — enabling traversal queries that answer "why" things are connected, not just "what" exists.

---

## Node Types

All nodes use prefixed IDs: `memc:<uuid>`, `evt:<uuid>`, `fact:<uuid>`, `out:<uuid>`, `agt:<uuid>`.

### `MemoryChunk`

Written on every `/memories/remember` call via Celery chain. Links back to Qdrant via `qdrant_id`.

```cypher
(:MemoryChunk {
  id: string,           -- prefixed: "memc:<uuid>"
  tenant_id: string,
  timestamp_utc: string,
  type: string,         -- "manual", "telegram", "claude", etc.
  qdrant_id: string,    -- cross-reference to Qdrant vector
  revoked: bool,        -- soft delete; filter in all traversals
  version: int,
  importance: float,
  confidence: float
})
```

### `Event`

Written on every memory ingest. Represents the moment of capture.

```cypher
(:Event {
  id: string,           -- prefixed: "evt:<uuid>"
  tenant_id: string,
  agent_id: string,
  type: string,         -- "meeting", "decision", "tool_call", "approval", "error"
  description: string,
  timestamp_utc: string
})
```

### `Fact`

Derived assertions with temporal validity. Supports `REPLACES` chains for versioning.

```cypher
(:Fact {
  id: string,           -- prefixed: "fact:<uuid>"
  tenant_id: string,
  content: string,
  valid_from: string,
  valid_until: string,  -- null means open-ended
  version: int
})
```

### `EvidencePath`

Root node for every AI generation receipt. Links to memories read, edges traversed, agent, machine, and timestamp.

```cypher
(:EvidencePath {
  id: string,
  output_id: string,
  tenant_id: string,
  agent_id: string,
  query_hash: string,
  machine_id: string,
  timestamp: string
})
```

### `EvidenceStep`

Ordered reasoning chain steps linked via `NEXT`.

```cypher
(:EvidenceStep {
  id: string,
  step_type: string,   -- "read_memory", "query_policy", "merge_context", "generate_output"
  order: int
})
```

### Structural Nodes

```cypher
(:Agent { id: string, tenant_id: string, name: string, role: string, model_used: string })
(:Output { id: string, tenant_id: string, type: string, timestamp: string })
(:Session { id: string, tenant_id: string })
(:Date { date: string })                    -- "2026-04-09"
(:Period { name: string })                   -- "Q1-2026"
(:Tenant { id: string })
(:Edge { type: string })                    -- placeholder for FOLLOWED edge types
```

---

## Relationship Types

### Memory / Event / Fact

```cypher
(:MemoryChunk)-[:DESCRIBES]->(:Event)
(:Event)-[:DESCRIBES]->(:MemoryChunk)
(:Fact)-[:DERIVED_FROM]->(:MemoryChunk)
(:Fact)-[:REPLACES]->(:Fact)    -- versioning: newer replaces older
(:Fact)-[:OVERRIDES]->(:Fact)
```

### Temporal

```cypher
(:Event)-[:OCCURRED_ON]->(:Date)
(:Fact)-[:APPLIES_DURING]->(:Period)
(:Event)-[:HAPPENED_BEFORE]->(:Event)
(:Event)-[:HAPPENED_AFTER]->(:Event)
```

### Policy / Contract

```cypher
(:Policy)-[:APPLIES_TO]->(:Tenant)
(:Policy)-[:APPLIES_TO]->(:Agent)
(:Policy)-[:REQUIRES]->(:Fact)
(:Contract)-[:GOVERNS]->(:Agent)
(:Contract)-[:GOVERNS]->(:Tenant)
(:Agent)-[:AUTHORIZED_BY]->(:Contract)
```

### Evidence Layer

```cypher
(:EvidencePath)-[:USED]->(:MemoryChunk | :Event | :Fact)
(:EvidencePath)-[:FOLLOWED]->(:Edge)
(:EvidencePath)-[:PRODUCED]->(:Output)
(:EvidencePath)-[:GENERATED_BY]->(:Agent)
(:EvidencePath)-[:BELONGS_TO]->(:Tenant)
(:EvidenceStep)-[:BELONGS_TO]->(:EvidencePath)
(:EvidenceStep)-[:NEXT]->(:EvidenceStep)
```

### Structural

```cypher
(:MemoryChunk)-[:IN_SESSION]->(:Session)
```

---

## Write Paths

### Memory Ingest (Celery chain)

```
POST /memories/remember
  → task_upsert_qdrant (Qdrant vector write)
  → task_upsert_neo4j (MemoryChunk + Event nodes)
  → task_extract_entities (entity nodes + DESCRIBES links)
```

`task_upsert_neo4j` writes the `MemoryChunk` with `qdrant_id` cross-reference and an `Event` node linked via `DESCRIBES`. The `qdrant_id` makes the graph self-contained — any `MemoryChunk` can resolve its vector directly from Qdrant.

### Entity Extraction

`task_extract_entities` (3rd chain link) calls `microsoft/phi-3-mini-128k-instruct` via NVIDIA NIM, validates against `VALID_LABELS` and `VALID_REL_TYPES`, then writes labeled entity nodes (`Person`, `Project`, `Concept`, `Decision`, `Tool`, `Event`, `Location`, `Document`) to Neo4j with `DESCRIBES` links to the `MemoryChunk`, plus typed entity-to-entity relationships.

Extraction is conservative — the system prompt instructs the model to extract only the most significant anchors worth traversing from, not every noun.

### Evidence Path (on `POST /skills/record`)

```
POST /skills/record
  → write Generation + Evidence rows to Postgres
  → create_evidence_path() in Neo4j
    - EvidencePath node
    - [:USED] links to each MemoryChunk
    - [:FOLLOWED] links to each traversed Edge type
  → add_evidence_step() — 4 ordered steps with [:BELONGS_TO] and [:NEXT] chains
  → link_evidence_to_output()
    - [:PRODUCED] → Output
    - [:GENERATED_BY] → Agent
    - [:BELONGS_TO] → Tenant
```

---

## Traversal Queries

### Graph Search (`POST /graph/search`)

Single-pass Cypher traversal from a named entity — one `MATCH` anchor shared across two `OPTIONAL MATCH` clauses:

```cypher
MATCH (e {name: $name})
WITH e
OPTIONAL MATCH (e)-[*1..$depth]-(m:MemoryChunk)
WHERE m.revoked IS NULL OR m.revoked = false
WITH e, collect(DISTINCT {memory_id: m.id, qdrant_id: m.qdrant_id}) as mem_records
OPTIONAL MATCH (e)-[*1..$depth]-(f:Fact)
RETURN mem_records, collect(DISTINCT {fact_id: f.id}) as fact_records
```

`OPTIONAL MATCH` shares the entity anchor without double lookup. `collect(DISTINCT {...})` aggregates results; null guards needed since `OPTIONAL MATCH` produces null-filled rows when no matches exist.

`MemoryChunk` nodes are hydrated from Postgres. `Fact` nodes are resolved through `REPLACES` chains via `get_latest_fact()` to return the newest valid version.

### `get_latest_fact()`

```cypher
MATCH (newer)-[:REPLACES]->(old {id: $fact_id})
WHERE old.valid_from <= datetime() < coalesce(old.valid_until, datetime())
RETURN newer
ORDER BY newer.valid_from DESC
LIMIT 1
```

Falls back to the original fact if no newer version exists.

---

## Indexes and Constraints

Created on every application boot via `ensure_indexes()`:

```python
# Unique constraints
MemoryChunk(id), Event(id), Fact(id), EvidencePath(id),
EvidenceStep(id), Agent(id), Output(id), Date(date), Period(name)

# MemoryChunk revoked filter
# (handled via WHERE clause in queries, not a separate index)
```

---

## Key Design Decisions

- **`qdrant_id` on `MemoryChunk`**: Makes the graph self-contained — any node can resolve its vector directly from Qdrant without going through Postgres.
- **`revoked` on `MemoryChunk`**: Soft delete via `WHERE m.revoked IS NULL OR m.revoked = false` in all traversals.
- **Independent Celery retry budgets**: Each task (`task_upsert_qdrant`, `task_upsert_neo4j`, `task_extract_entities`) has its own `max_retries=3` with exponential backoff. Failure in one domain doesn't affect the others.
- **`valid_until` null for open-ended**: Qdrant filter uses a `should` clause combining `DatetimeRange(gte=as_of)` + `IsNullCondition(is_null=True)` to correctly handle both bounded and unbounded memories.
- **Entity allowlists**: `VALID_LABELS` and `VALID_REL_TYPES` filter hallucinated types before they reach Neo4j.
- **MERGE everywhere**: All writes use `MERGE` for idempotency — re-running the same memory ingest produces the same nodes.
