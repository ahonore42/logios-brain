# Entity Extraction

## Role

Entity extraction identifies named entities in memory content — people, places, tools, decisions, concepts — and surfaces them as a structured list for storage in Neo4j. The pipeline also generates relationship edges between entities that reference each other.

---

## Pipeline

The pipeline runs in three steps, from cheapest to most expensive:

```
Text
  └─► Step 1: preflight_extract()     — spaCy NER + dictionary scan (no API call)
        └─► Step 2: LLM extraction    — phi-3-mini via NVIDIA NIM (API call)
              └─► Step 3: merge_entities()  — preflight wins on collision
                    └─► List[Entity]
```

### Step 1 — Deterministic Preflight (`preflight_extract`)

Runs entirely offline. Two sources:

**Dictionary scan** — `KNOWN_TOOLS` maps canonical tool names to aliases:

```python
KNOWN_TOOLS = {
    "Neo4j": ["neo4j"],
    "Qdrant": ["qdrant"],
    "PostgreSQL": ["postgres", "postgresql", "pg", "pgvector"],
    "Redis": ["redis"],
    "FastAPI": ["fastapi"],
    "Celery": ["celery"],
    "Docker": ["docker", "docker compose", "docker-compose"],
    ...
}
```

Matching is case-insensitive with word-boundary enforcement (`\b` regex) to prevent e.g. "redis" matching inside "credentials". Returns `Tool` label.

**spaCy NER** (`en_core_web_sm`) — extracts `Person` and `Location` entities:

| spaCy label | Returned label |
|---|---|
| `PERSON` | `Person` |
| `GPE`, `LOC` | `Location` |

If spaCy or the model is absent, Person/Location extraction is skipped silently. Known tools take precedence over spaCy — if spaCy labels "Docker" as a person, the dictionary scan re-labels it as `Tool`.

Preflight entities always have `source: "preflight"` and `relationships: []`.

### Step 2 — LLM Extraction

Calls `microsoft/phi-3-mini-128k-instruct` via the NVIDIA NIM chat completions API:

```
POST https://integrate.api.nvidia.com/v1/chat/completions
```

The system prompt uses few-shot examples to guide extraction toward significant entities only:

```
Input: "Alice worked on Project Alpha."
Output: {"entities": [{"name": "Alice", "label": "Person", ...}, {"name": "Project Alpha", "label": "Project", ...}]}

Input: "The weather is nice today."
Output: {"entities": []}
```

Allowed labels (whitelist): `Project`, `Person`, `Concept`, `Decision`, `Tool`, `Event`, `Location`, `Document`

Allowed relationship types: `RELATES_TO`, `PART_OF`, `CREATED_BY`, `MENTIONS`, `CAUSED_BY`

Any other label or relationship type produced by the model is silently dropped.

If the API call fails, Step 2 retries up to 2 times. After all retries are exhausted, the pipeline returns preflight results rather than an empty list — partial results are preferred over none.

### Step 3 — Merge (`merge_entities`)

Combines preflight and LLM results:

- **Name collision**: preflight wins (deterministic beats probabilistic)
- **Unique names**: LLM entities are appended
- **`source` key**: stripped from all entities in final output

---

## Schema

```python
{
    "name": str,           # entity text
    "label": str,          # Project | Person | Concept | Decision | Tool | Event | Location | Document
    "relationships": [
        {
            "target": str, # name of another entity in the list
            "type": str,   # RELATES_TO | PART_OF | CREATED_BY | MENTIONS | CAUSED_BY
        }
    ]
}
```

---

## Write Path

```
POST /memories/remember
  → Postgres: upsert Memory + Chunk
  → embed(content) → vector  (NVIDIA NIM, sync)
  → Celery chain:
      task_upsert_qdrant      → Qdrant PointStruct
      task_upsert_neo4j       → Neo4j MemoryChunk node
      task_extract_entities   → entity extraction pipeline
        → task_upsert_neo4j_entities  → MERGE entity nodes + edges into Neo4j
```

---

## Key Design Decisions

- **Preflight before LLM**: High-confidence entities (known tools, clear names) are extracted without an API call, reducing latency and cost. The LLM handles ambiguous or abstract entities (Decisions, Concepts).
- **Preflight wins on collision**: Deterministic extraction takes precedence over probabilistic LLM output — avoids spaCy false-positives like "Docker" → Person being returned instead of Tool.
- **Graceful degradation**: spaCy absence → only dictionary runs. LLM failure → return preflight results. Neither step can cause a full pipeline failure.
- **No hallucination of entities**: LLM output is filtered against `VALID_LABELS` and `VALID_REL_TYPES` after parsing. Unknown labels/types are dropped silently.
- **Significance guidance in prompt**: The system prompt instructs the model to "extract only the most significant entities — the anchors worth traversing from in a knowledge graph" to avoid cataloging every noun.
