# Qdrant Architecture

## Role

Qdrant is the **retriever** — it stores vector embeddings for semantic similarity search. When you ask "what memories feel like this?", Qdrant finds the closest stored vectors without needing the exact words to match.

---

## Collection

**Collection name**: `memories`

| Parameter | Value |
|---|---|
| Vector size | 4096 dimensions |
| Distance metric | Cosine similarity |
| Vector model | `nvidia/nv-embed-v1` via NVIDIA NIM API |
| Storage | Docker volume `qdrant_data:/qdrant/storage` |

---

## Vector Embedding

All embeddings are produced by `nvidia/nv-embed-v1` via the NVIDIA NIM API:

```python
# app/embeddings.py
EMBEDDING_URL = "https://integrate.api.nvidia.com/v1/embeddings"

async def embed(text: str) -> list[float]:
    response = await client.post(
        EMBEDDING_URL,
        json={
            "input": [text],
            "model": "nvidia/nv-embed-v1",
            "input_type": "passage",      # storage
            "encoding_format": "float",
            "truncate": "NONE",
        },
    )
    return response.json()["data"][0]["embedding"]
```

Two separate embedding calls are used:

- **`embed(text)`** — `input_type: "passage"` — used when storing memories
- **`embed_query(text)`** — `input_type: "query"` — used when searching; optimized for query recall

---

## Point Structure

Every memory chunk is stored as a `PointStruct` with a UUID-based ID and rich payload:

```python
from qdrant_client.models import PointStruct

PointStruct(
    id=qdrant_id,           # str(uuid.uuid4())
    vector=embedding,         # list[float] 4096-dim
    payload={
        "memory_id": str(uuid),
        "chunk_id": str(uuid),
        "source": "manual",
        "session_id": str(uuid) | None,
        "valid_from": "2026-04-09T12:00:00Z",
        "valid_until": "2026-07-09T12:00:00Z" | None,
        "revoked": False,
        "policy_version": 1,
    }
)
```

The `payload` mirrors the Postgres `Chunk` record — Qdrant holds the vector, Postgres holds the source of truth.

---

## Payload Indexes

Three payload fields are indexed for efficient filtering on every boot via `_create_payload_indexes()`:

| Field | Schema Type | Purpose |
|---|---|---|
| `revoked` | `BOOL` | Soft delete filter |
| `valid_from` | `DATETIME` | Time-aware retrieval: memory must be valid at `as_of` |
| `valid_until` | `DATETIME` | Time-aware retrieval: open-ended memories have `null` |

Indexes are created idempotently — safe to call on every application boot.

---

## Time-Aware Retrieval

The `POST /memories/search` endpoint accepts an optional `as_of` datetime. The Qdrant filter uses a `should` clause to correctly handle both bounded and open-ended memories:

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue, DatetimeRange, IsNullCondition

search_kwargs["query_filter"] = Filter(must=[
    FieldCondition(key="revoked", match=MatchValue(value=False)),
    FieldCondition(key="valid_from", range=DatetimeRange(lte=data.as_of)),
    Filter(should=[
        FieldCondition(key="valid_until", range=DatetimeRange(gte=data.as_of)),
        IsNullCondition(key="valid_until", is_null=True),  # open-ended
    ]),
])
```

- `valid_from <= as_of`: memory existed at query time
- `valid_until >= as_of` OR `valid_until IS NULL`: memory was still valid at query time (not superseded or expired)

---

## Search Flow

```
POST /memories/search
  → embed_query(text)  → 4096-dim vector (NVIDIA NIM)
  → qdrant.search(
      collection_name="memories",
      query_vector=vector,
      limit=top_k,
      score_threshold=threshold,
      query_filter=...,
      with_payload=True,
    )
  → memory_ids from payload
  → Postgres: hydrate full Memory records
  → Return MemoryOut[] ordered by Qdrant score
```

The `score_threshold` (default 0.65) filters low-similarity results. `top_k` (default 10) limits results.

---

## Write Path

Vectors are written synchronously from the FastAPI route handler on `/memories/remember` before the Celery chain is dispatched. This keeps the embedding operation in the request path (fast, NVIDIA NIM is quick) while Qdrant and Neo4j writes happen async via Celery.

```
RememberRequest
  → Postgres upsert (sync)
  → embed(content) → vector (async httpx, NVIDIA NIM)
  → Celery chain: task_upsert_qdrant → task_upsert_neo4j → task_extract_entities
  → Return MemoryOut immediately
```

`task_upsert_qdrant` writes the `PointStruct` to Qdrant and returns the `qdrant_id`, which Celery pipes to `task_upsert_neo4j` for storage on the `MemoryChunk` node.

---

## Key Design Decisions

- **`qdrant_id` cross-reference**: Stored on both the Qdrant point and the Neo4j `MemoryChunk` node — the graph can resolve vectors without going through Postgres.
- **Separate query vs. passage embedding**: `input_type: "query"` for search (optimized for recall on natural language queries) vs `input_type: "passage"` for storage (optimized for representation).
- **No on-disk model**: All embedding computation runs on NVIDIA's GPU servers via the NIM API — the application only stores and retrieves vectors.
- **`truncate: "NONE"`**: Prevents silently dropping long memory content; raises on oversized input instead.
- **Idempotent index creation**: `_create_payload_indexes()` is called on every boot — safe because the `CREATE` is idempotent and the `except` silently handles already-existing indexes.
