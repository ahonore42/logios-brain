# Neo4j Architecture

## Role

Neo4j is the **map maker**. It stores every memory as a node and draws typed relationships between them, enabling traversal queries that answer "why" things are connected, not just "what" exists.

## Data Model

### Memory Node

```cypher
(:Memory {
  id: UUID,           -- matches Postgres memory.id
  content: string,    -- full text
  source: string,     -- 'telegram', 'claude', 'agent', 'manual'
  captured_at: datetime,
  session_id: UUID    -- optional grouping
})
```

Labels: `Memory`
Indexes: `id` (unique), `captured_at`, `source`

### Session Node

```cypher
(:Session {
  id: UUID,           -- matches session_id
  created_at: datetime
})
```

Sessions group related memories. A memory without a session_id is a standalone thought.

### Relationship Types

Relationships are **typed** and **directional**:

```cypher
-- Memory belongs to a session
(m:Memory)-[:IN_SESSION]->(s:Session)

-- Agent-discovered: these memories are topically related
(m1:Memory)-[:RELATED_TO {reason: "discussed in same planning meeting"}]->(m2:Memory)

-- Agent-discovered: causal chain
(m1:Memory)-[:CAUSED {by: "decision made in 2024-Q3"}]->(m2:Memory)

-- Similarity link from vector search (Qdrant)
(m1:Memory)-[:SIMILAR_TO {score: 0.94}]->(m2:Memory)
```

Relationship types are defined by the agent that writes them. The graph schema is open — agents create relationship types as needed.

## Write Path

When a memory is stored via `/memories/remember`:

1. **PostgreSQL** — memory record (source of truth)
2. **Qdrant** — vector embedding for similarity search
3. **Neo4j** — memory node created via MERGE (idempotent)

```python
# Pseudocode
def write_memory_to_neo4j(memory_id, content, source, captured_at, session_id):
    with driver.session() as session:
        # Upsert memory node
        session.run("""
            MERGE (m:Memory {id: $id})
            SET m.content = $content,
                m.source = $source,
                m.captured_at = $captured_at
        """, id=memory_id, content=content, source=source, captured_at=captured_at)

        # Link to session if present
        if session_id:
            session.run("""
                MERGE (s:Session {id: $session_id})
                WITH s
                MATCH (m:Memory {id: $id})
                MERGE (m)-[:IN_SESSION]->(s)
            """, session_id=session_id, id=memory_id)
```

## Traversal Queries

### "What memories are connected to this one?"

```cypher
MATCH (m:Memory {id: $id})-[r]-(other)
RETURN other, type(r) as relationship, r.reason as note
```

### "Show me the full session this memory belongs to"

```cypher
MATCH (m:Memory {id: $id})-[:IN_SESSION]->(s:Session)<-[:IN_SESSION]-(related)
RETURN collect(related) as session_memories
```

### "Find all memories that caused this decision"

```cypher
MATCH (m:Memory)-[r:CAUSED]->(dec:Memory {id: $id})
RETURN m.content as cause, r.by as reason
```

### "What topics is this person associated with?"

```cypher
MATCH (p:Person {name: $name})-[:MENTIONS|RELATED_TO*1..3]->(m:Memory)
RETURN m.content, m.captured_at
```

## Indexes

Create before any writes:

```cypher
CREATE CONSTRAINT memory_id IF NOT EXISTS FOR (m:Memory) REQUIRE m.id IS UNIQUE;
CREATE INDEX memory_captured_at IF NOT EXISTS FOR (m:Memory) ON (m.captured_at);
CREATE INDEX session_id IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE;
```

## Key Properties of Neo4j

- **Relationships are first-class citizens** — stored as typed, directed edges with properties
- **MERGE is upsert** — `MERGE (m:Memory {id: $id})` finds or creates atomically
- **Pattern matching scales** — traversal depth doesn't degrade as the graph grows
- **Open schema** — agents define new relationship types dynamically
- **Provenance** — every relationship can carry a `reason` or `by` property explaining why it exists

## Interaction with Evidence Layer

The evidence layer (see [skills.md](./skills.md)) stores generation receipts. Each receipt references memory nodes via `memory_id`. Neo4j traversal answers follow-up questions like:

- "Which memories led to this decision?"
- "Show me the reasoning chain for this analysis"
- "What sessions were involved in this output?"

The graph is the **traceability layer** — it maps every AI output back to the memories and relationships that informed it.
