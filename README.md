# Logios Brain

Personal AI memory infrastructure. One shared knowledge layer that every AI you run can read from and write to through the Model Context Protocol (MCP).

Built on four stores: PostgreSQL for the ledger, Qdrant for semantic retrieval, Neo4j for the knowledge graph, and Redis for Celery task brokering.

---

## What It Does

Logios Brain captures every memory you store and makes it searchable by semantic similarity, source, or graph relationships. It tracks every AI generation with a full evidence receipt — which memories were retrieved, which graph nodes were traversed, which model ran, on which machine.

When you run a skill (e.g. weekly review, competitive analysis), Logios builds an evidence manifest before the AI produces output. The receipt is stored alongside the output so you can trace it later.

The server is the front door. When an AI wants to remember something or look something up, it knocks on this door.

Behind that door are four helpers, each with one job:

- **PostgreSQL** is the filing cabinet. Every single thing that ever gets remembered goes in here first. It never forgets and never loses anything.
- **Qdrant** is the "find me something similar" helper. It turns memories into numbers so it can ask "what else did we capture that feels like this?" — even if the exact words are different. It needs the NVIDIA API to do the number-crunching.
- **Neo4j** is the map maker. It doesn't just store memories — it draws lines between them. "This project connects to this concept, which came up in that session." It's what lets you ask why things are related, not just what exists.
- **Redis** is the task queue. It brokers background work — writing to Qdrant, Neo4j, and entity extraction happen asynchronously so the API response returns immediately.

The evidence layer is the most important piece. Every time an AI produces something — an analysis, a plan, a summary — it doesn't just hand you the answer. It staples a receipt to it: here are the memories I read, here's which connection in Neo4j I followed, here's which model produced this, at this time, on this machine. Six months later you can look back at any output and know exactly what the system was thinking.

---

## Architecture

```
Client (Claude Code, agent, Telegram bot)
           │
           │  HTTP + X-Brain-Key auth
           ▼
     FastAPI (app/)
     ┌────────────────────────────────┐
     │  /memories/remember            │
     │  /memories/search              │
     │  /graph/recall                 │
     │  /graph/search                 │
     │  /skills/run                   │
     │  /skills/record                │
     │  /skills/evidence              │
     └──────┬──────────┬─────────┬────┘
            │          │         │
            ▼          ▼         ▼
       PostgreSQL    Qdrant   Neo4j
      (pgvector)   (vectors) (graph)
        Ledger    Retriever  Reasoner
            │
            ▼
      NVIDIA NIM API
     (embeddings + entity extraction)
            │
            ▼
         Redis
     (Celery broker)
```

### The Four Stores

| Store | Role | What lives here |
|---|---|---|
| **PostgreSQL** | Ledger | Every raw memory, chunk, entity, generation record, evidence receipt. SQLAlchemy async with Alembic migrations. |
| **Qdrant** | Retriever | Chunk embeddings (4096-dim, `nvidia/nv-embed-v1`) for semantic search. Time-aware validity filtering via payload indexes. |
| **Neo4j** | Reasoner | Entity graph — MemoryChunks, Events, Facts (with REPLACES versioning), EvidencePath, EvidenceStep chains, Outputs, Agents. |
| **Redis** | Task broker | Celery broker for async background tasks: Qdrant writes, Neo4j writes, entity extraction. |

The `memory_id` / `qdrant_id` is the spine that connects all three stores.

---

## API Endpoints

All endpoints except `/health` require `X-Brain-Key: YOUR_KEY` header or `?key=YOUR_KEY` query param.

### Memories

**`POST /memories/remember`** — Store a memory
- Writes to Postgres (dedup via SHA256 fingerprint), dispatches a Celery chain: Qdrant write → Neo4j MemoryChunk+Event write → entity extraction
- Returns the memory immediately; background tasks run async

**`POST /memories/search`** — Semantic search
- Embeds query via NVIDIA NIM, searches Qdrant (with optional time-bounded validity filter), hydrates from Postgres

### Graph

**`POST /graph/recall`** — Structured recall by source/date range
- Direct Postgres SQL query, timezone-aware

**`POST /graph/search`** — Traverse from a named entity
- Neo4j Cypher traversal up to N hops to reachable MemoryChunks and Facts
- Facts resolved through REPLACES chains to return newest valid version
- MemoryChunks hydrated from Postgres

### Skills

**`POST /skills/run`** — Load a skill template with evidence
- Looks up active skill, retrieves top-8 relevant memories as evidence manifest
- Returns prompt template + evidence so an external AI can generate output

**`POST /skills/record`** — Record an AI generation
- Writes Generation to Postgres, builds full Neo4j evidence path (EvidencePath + USED/FOLLOWED/PRODUCED links)

**`POST /skills/evidence`** — Retrieve evidence for a generation
- Returns generation + enriched evidence records with full memory content

---

## Quick Start

### 1. Clone and start containers

```bash
git clone https://github.com/YOUR_HANDLE/logios-brain.git
cd logios-brain
docker compose up -d
```

Wait for all containers to be healthy:

```bash
docker compose ps
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

At minimum you need:
- `LLM_API_KEY` — from your LLM provider (NVIDIA NIM, OpenAI, Anthropic, or Gemini)
- `NEO4J_PASSWORD` — generate with `openssl rand -hex 16`
- `POSTGRES_PASSWORD` — generate with `openssl rand -hex 16`

### 3. Run database migrations

```bash
uv sync
alembic upgrade head
```

### 4. Start the server

```bash
uvicorn app.main:app --port 8000 --reload
```

### 5. Seed skills and test connectivity

```bash
# Seed skill templates
python scripts/seed_skills.py

# Test all store connections
python scripts/test_connection.py
```

Health check:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

## Entity Extraction

Entity extraction runs as the third link in the Celery chain (after Qdrant and Neo4j writes are confirmed). It calls `microsoft/phi-3-mini-128k-instruct` via NVIDIA NIM to extract named entities from memory content, then writes labeled nodes to Neo4j.

**Valid entity labels**: `Project`, `Person`, `Concept`, `Decision`, `Tool`, `Event`, `Location`, `Document`

**Valid relationship types**: `RELATES_TO`, `PART_OF`, `CREATED_BY`, `MENTIONS`, `CAUSED_BY`

Extraction is conservative — only significant anchors worth traversing from, not every noun mentioned. Extracted entities are validated against allowlists before writing to Neo4j. The system prompt instructs the model to extract only entities that appear verbatim in the source text.

---

## Evidence Layer

Every AI generation gets a full provenance trace in Neo4j:

- **EvidencePath** — records which memories were read, which graph edge types were traversed, which agent acted, which machine ran it, and the timestamp
- **EvidenceStep** — ordered reasoning chain: `read_memory` → `query_policy` → `merge_context` → `generate_output`, linked via `NEXT` relationships
- **Facts** support `REPLACES` versioning chains — `get_latest_fact()` resolves to the newest valid version, not superseded ones

On the Postgres side, `Evidence` rows store each retrieval item with `generation_id`, `memory_id`, `chunk_id`, `neo4j_node_id`, `relevance_score`, `retrieval_type`, and `rank`. The `evidence_with_content` join view materializes full memory content for evidence receipts.

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `USE_LOCAL_STORES` | Use local Docker stores | `true` |
| `USE_SUPABASE` | Use cloud Supabase instead | `false` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://logios:...@127.0.0.1:5432/logios_brain` |
| `SUPABASE_URL` | Supabase project URL | — |
| `SUPABASE_SERVICE_KEY` | Supabase service key | — |
| `QDRANT_URL` | Qdrant HTTP URL | `http://localhost:6333` |
| `QDRANT_API_KEY` | Qdrant API key | `None` |
| `REDIS_URL` | Redis connection (Celery broker) | `redis://localhost:6379/0` |
| `NEO4J_URI` | Neo4j Bolt URL | `bolt://localhost:7687` |
| `NEO4J_USERNAME` | Neo4j user | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | — |
| `TENANT_ID` | Single-tenant ID | `default` |
| `LLM_API_KEY` | LLM API key | — |
| `LLM_PROVIDER` | LLM provider (nvidia, openai, anthropic, gemini) | `nvidia` |
| `EMBEDDING_URL` | Embedding API endpoint | NVIDIA NIM default |
| `EMBEDDING_MODEL` | Embedding model | `nvidia/nv-embed-v1` |
| `EMBEDDING_DIM` | Embedding dimensions | `4096` |
| `ENTITY_COMPLETION_URL` | Entity extraction completion URL | NVIDIA NIM default |
| `ENTITY_MODEL` | Entity extraction model | `microsoft/phi-3-mini-128k-instruct` |
| `SERVER_PORT` | FastAPI server port | `8000` |

---

## Repository Structure

```
logios-brain/
├── docker-compose.yml          # postgres, qdrant, neo4j, redis
├── conf/
│   ├── neo4j.conf             # Neo4j config (strict_validation disabled before APOC)
│   └── apoc.conf              # APOC plugin settings
├── alembic/                   # Database migrations
├── alembic.ini
├── app/
│   ├── main.py                # FastAPI entrypoint, route mounting
│   ├── celery.py              # Celery app with Redis broker
│   ├── config.py              # Environment variable resolver
│   ├── dependencies.py         # verify_key() auth dependency
│   ├── embeddings.py          # NVIDIA NIM embeddings (nvidia/nv-embed-v1)
│   ├── entity_extraction.py   # NVIDIA NIM entity extraction (phi-3-mini)
│   ├── tasks.py               # Celery tasks: upsert_qdrant, upsert_neo4j, extract_entities
│   ├── database.py            # SQLAlchemy async engine + session
│   ├── models.py              # SQLAlchemy models
│   ├── schemas.py             # Pydantic request/response schemas
│   ├── routes/
│   │   ├── health.py          # GET /health
│   │   ├── memory.py          # POST /memories/remember, /memories/search
│   │   ├── graph.py           # POST /graph/recall, /graph/search
│   │   └── skills.py          # POST /skills/run, /skills/record, /skills/evidence
│   └── db/
│       ├── qdrant.py          # Qdrant client + payload indexes
│       └── neo4j/
│           ├── __init__.py     # Public API exports
│           ├── client.py       # Neo4j driver singleton + indexes
│           ├── nodes.py        # Typed node dataclasses
│           ├── relationships.py # RelationshipType enum
│           ├── transactions.py # write_memory_chunk, write_event, get_latest_fact
│           └── evidence.py     # create_evidence_path, add_evidence_step, link_evidence_to_output
├── scripts/
│   ├── seed_skills.py         # Seeds skill templates to Postgres
│   └── test_connection.py     # Connectivity verification
└── tests/
    ├── conftest.py             # Pytest fixtures, CELERY_TASK_ALWAYS_EAGER=true
    ├── test_entity_extraction.py       # 8 mocked I/O tests
    └── test_entity_extraction_live.py  # 8 live integration tests
```

---

## CI/CD

Every push to `main` and every PR runs:

- `ruff format` — code formatting
- `ruff check` — linting
- `mypy --ignore-missing-imports` — type checking
- `pytest` — all tests (mocked + live integration)

---

## Deploy to Hetzner

```bash
# On the VPS, clone once:
git clone https://github.com/YOUR_HANDLE/logios-brain.git ~/logios-brain

# Run the deploy script from your local machine:
HETZNER_IP=your.vps.ip HETZNER_USER=your_user ./scripts/deploy.sh
```

Prerequisites on Hetzner: Docker, Docker Compose, Python 3.11, SSH access.
