# Evidence Layer

## Purpose

The evidence layer is the provenance trace for every AI output. When an AI produces an analysis, plan, or summary, the evidence layer records: which memories were read, which graph edges were traversed, which model ran, on which machine, at what time — and in what order.

Six months later, any output can be traced back to understand exactly what the system was thinking.

---

## Two Sides

### Postgres: `generations` + `evidence` tables

Every generation creates a `Generation` row and one `Evidence` row per retrieved memory:

```sql
generations (
  id UUID PRIMARY KEY,
  skill_id UUID REFERENCES skills(id),
  skill_name TEXT,
  output TEXT,
  model TEXT,
  machine TEXT,
  session_id UUID,
  prompt_used TEXT,
  generated_at TIMESTAMPTZ,
  metadata JSONB
)

evidence (
  id UUID PRIMARY KEY,
  generation_id UUID REFERENCES generations(id),
  memory_id UUID REFERENCES memories(id),
  chunk_id UUID REFERENCES chunks(id),
  neo4j_node_id TEXT,
  neo4j_rel_type TEXT,
  relevance_score FLOAT,
  retrieval_type TEXT,  -- "semantic", "graph", "keyword"
  rank INT,
  created_at TIMESTAMPTZ
)
```

`evidence_with_content` is a pre-joined view that joins evidence to full memory and chunk content — used by `GET /skills/evidence` to return enriched receipts without N+1 queries.

### Neo4j: `EvidencePath` + `EvidenceStep` chain

Built atomically in Neo4j when `POST /skills/record` is called.

---

## Neo4j Evidence Path Structure

### Nodes

```cypher
(:EvidencePath {
  id: string,
  output_id: string,     -- matches Generation.id
  tenant_id: string,
  agent_id: string,
  query_hash: string,
  machine_id: string,
  timestamp: string
})

(:EvidenceStep { id: string, step_type: string, order: int })
-- step_types: "read_memory", "query_policy", "merge_context", "generate_output"

(:Output { id: string, tenant_id: string, type: string, timestamp: string })
(:Agent { id: string, tenant_id: string, name: string, role: string, model_used: string })
(:Edge { type: string })  -- placeholder for edge types traversed
```

### Relationships

```cypher
-- Evidence path links to what was read
(:EvidencePath)-[:USED]->(:MemoryChunk)
(:EvidencePath)-[:USED]->(:Event)
(:EvidencePath)-[:USED]->(:Fact)

-- Evidence path links to which edge types were traversed
(:EvidencePath)-[:FOLLOWED]->(:Edge)

-- Evidence path links to the output and who produced it
(:EvidencePath)-[:PRODUCED]->(:Output)
(:EvidencePath)-[:GENERATED_BY]->(:Agent)

-- Scoping
(:EvidencePath)-[:BELONGS_TO]->(:Tenant)

-- Ordered reasoning steps
(:EvidenceStep)-[:BELONGS_TO]->(:EvidencePath)
(:EvidenceStep)-[:NEXT]->(:EvidenceStep)  -- ordered chain: step 0 → step 1 → step 2 → step 3
```

---

## Write Flow

```
POST /skills/record
  1. Write Generation + Evidence rows to Postgres (sync)
  2. Create EvidencePath node + USED + FOLLOWED links (Neo4j transaction)
  3. Add EvidenceStep chain: 4 ordered steps with [:BELONGS_TO] and [:NEXT]
  4. Link EvidencePath → Output, EvidencePath → Agent
```

Three functions in `app/db/neo4j/evidence.py`:

```python
# 1. Create the path and memory/edge links
create_evidence_path(
    evidence_path_id: str,
    output_id: str,
    tenant_id: str,
    agent_id: str | None,
    query_hash: str,
    machine_id: str | None,
    used_memory_ids: list[str],    -- MemoryChunk node IDs
    used_edge_types: list[str],    -- e.g. ["DESCRIBES", "RELATES_TO"]
    timestamp: str,
) -> str  # returns the EvidencePath id

# 2. Add ordered reasoning steps
add_evidence_step(
    evidence_path_id: str,
    step_id: str,
    step_type: str,   # "read_memory", "query_policy", "merge_context", "generate_output"
    order: int,
) -> None

# 3. Link to Output and Agent
link_evidence_to_output(
    evidence_path_id: str,
    output_id: str,
    agent_id: str | None,
    tenant_id: str,
) -> None
```

All three run inside a single Neo4j transaction per call to `POST /skills/record`.

---

## Retrieval

### `POST /skills/evidence`

Returns a `GenerationReceipt` with the generation record and enriched evidence list:

```python
class GenerationReceipt(BaseModel):
    generation: GenerationOut
    evidence: List[EvidenceWithContentOut]
```

The Postgres `evidence_with_content` join view materializes full memory content per evidence row — no N+1 queries.

### `POST /graph/search` — Fact Resolution

Facts in the Neo4j graph support `REPLACES` versioning chains. When a traversal returns a fact, `get_latest_fact()` resolves through the chain to return the newest valid descendant:

```python
def get_latest_fact(fact_id: str) -> dict | None:
    # Traverse REPLACES chain forward to newest valid fact
    # Falls back to original if no newer version exists
```

This ensures that `POST /graph/search` always returns the current state of a fact, not a superseded version.

---

## Evidence Step Types

| Step | `step_type` | Meaning |
|---|---|---|
| 0 | `read_memory` | Agent retrieved top-k memories via vector search |
| 1 | `query_policy` | Agent checked applicable policies or constraints |
| 2 | `merge_context` | Agent combined retrieved memories into context |
| 3 | `generate_output` | Agent produced the final output |

The `NEXT` chain enforces ordering: step 0 must happen before step 1, etc.

---

## Key Design Decisions

- **Postgres as source of truth for evidence records**: `Generation` and `Evidence` rows are the primary evidence store. Neo4j augments this with graph traversal and edge-type tracking.
- **`evidence_with_content` join view**: Materializes full memory/chunk content per evidence row at insert time — avoids expensive joins at query time.
- **Atomic Neo4j evidence writes**: `create_evidence_path`, `add_evidence_step`, and `link_evidence_to_output` all run in a single transaction — evidence is all-or-nothing.
- **`query_hash` on `EvidencePath`**: Hash of the original retrieval query — enables deduplication and auditability of repeated queries.
- **Step chain over flat list**: The ordered `[:NEXT]` chain makes the reasoning process traversable as a path, not just a set of disconnected steps.
- **`FOLLOWED` edges to `Edge` placeholder nodes**: Records which relationship types were traversed during retrieval — useful for understanding how the agent navigated the graph.
