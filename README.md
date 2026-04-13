# Logios Brain

<center>

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11+-green.svg)](pyproject.toml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy](https://img.shields.io/badge/mypy-checked-blue.svg)](http://mypy-lang.org/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ed.svg?logo=docker)](docker-compose.yml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)

</center>

Personal AI memory infrastructure. One shared knowledge layer that every AI you run can read from and write to.

Built on four stores: **PostgreSQL** for the ledger, **Qdrant** for semantic retrieval, **Neo4j** for the knowledge graph, and **Redis** for Celery task brokering.

---

## Key Features

| | |
|---|---|
| **Three-tier memory** | Working (Redis) → Episodic (Postgres+Qdrant) → Semantic (Neo4j) |
| **Evidence receipts** | Every AI generation stores full provenance — which memories were read, which graph edges were traversed, which model ran |
| **Server-controlled snapshots** | Agents cannot skip or prevent checkpoints; the server fires them on configurable thresholds |
| **Identity memories** | Human-authored persistent instructions, owner-only writes, read-only for agents |
| **Skills with evidence** | Structured skill execution builds an evidence manifest before output; the receipt is stored alongside the result |
| **Multi-agent ready** | One shared memory layer across all agents; session-scoped episodic context |

---

## Quick Start

### 1. Clone and start everything

```bash
git clone https://github.com/YOUR_HANDLE/logios-brain.git
cd logios-brain
cp .env.example .env
# Edit .env with your credentials
docker compose up -d
```

Docker starts all five services (postgres, qdrant, neo4j, redis, app) and runs migrations automatically.

Wait for all containers to be healthy:

```bash
docker compose ps
```

### 2. Create an agent token

The server needs a Bearer token for all API calls. Provision an owner account, then create an agent token:

```bash
# Get the OTP (emails disabled in default config)
curl -X POST http://localhost:8000/auth/setup \
  -H "X-Secret-Key: YOUR_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "password"}'

# Complete setup with the OTP from the response
curl -X POST http://localhost:8000/auth/verify-setup \
  -H "X-Secret-Key: YOUR_SECRET_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "pending_token=YOUR_TOKEN&otp=YOUR_OTP"

# Log in to get an access token
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "password"}'

# Create an agent token (save the token field — shown only once)
curl -X POST http://localhost:8000/auth/tokens \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-agent"}'
```

Use the agent `token` as the Bearer token in all subsequent API calls.

Health check:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

For the full connection guide including framework integrations, see [`docs/connecting-agents.md`](docs/connecting-agents.md).

---

## Architecture

```
Agent (Hermes, OpenClaw, Claude Code, any HTTP client)
           │
           │  HTTP + Bearer token auth
           ▼
     FastAPI (app/)
     ┌────────────────────────────────┐
     │  /memories/remember            │
     │  /memories/search              │
     │  /memories/context             │
     │  /memories/identity            │
     │  /memories/forget              │
     │  /memories/digest              │
     │  /hooks/trigger                │
     │  /hooks/buffer                  │
     │  /hooks/check                  │
     │  /hooks/flush                  │
     │  /hooks/snapshot               │
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
     (Celery broker + server-side hooks buffer)
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

## Memory Types

| Type | Description | Who writes |
|---|---|---|
| `standard` | General-purpose memories | Agents via `/memories/remember` |
| `identity` | Human-authored persistent instructions | Owners only via `/memories/identity` |
| `checkpoint` | Server-controlled session snapshots | Server auto-fires on threshold |
| `manual` | Explicit agent memories | Agents via `/memories/remember` |

---

## Evidence Layer

Every AI generation gets a full provenance trace in Neo4j:

- **EvidencePath** — records which memories were read, which graph edge types were traversed, which agent acted, which machine ran it, and the timestamp
- **EvidenceStep** — ordered reasoning chain: `read_memory` → `query_policy` → `merge_context` → `generate_output`, linked via `NEXT` relationships
- **Facts** support `REPLACES` versioning chains — `get_latest_fact()` resolves to the newest valid version, not superseded ones

On the Postgres side, `Evidence` rows store each retrieval item with `generation_id`, `memory_id`, `chunk_id`, `neo4j_node_id`, `relevance_score`, `retrieval_type`, and `rank`. The `evidence_with_content` join view materializes full memory content for evidence receipts.

---

## Agent Framework Integrations

Logios ships client libraries for every major agent framework. Import the integration for your framework:

```python
# Hermes Agent
from app.integrations.hermes import connect
memory_manager = connect("http://localhost:8000", api_key, session_id, agent_id)
agent = HermesAgent(external_memory_manager=memory_manager)

# OpenClaw Gateway extension
from app.integrations.openclaw import connect
gateway.register_extension("logios", connect("http://localhost:8000", api_key))

# Pi Coding Agent
from app.integrations.pi import connect
pi_agent.register_extension("logios", connect("http://localhost:8000", api_key, session_id))

# GoClaw pipeline stage
from app.integrations.goclaw import connect
for stage in connect("http://localhost:8000", api_key, session_id, agent_id):
    pipeline.add_stage(stage)

# Claude Agent SDK
from app.integrations.claude_agent_sdk import LogiosStorageAdapter
adapter = LogiosStorageAdapter("http://localhost:8000", api_key, session_id, agent_id)

# ZeroClaw MCP server
from app.integrations.zeroclaw import LogiosMCPServer
server.add_tool_provider(LogiosMCPServer("http://localhost:8000", api_key))
```

See [`docs/integrations.md`](docs/integrations.md) for the full guide.

---

## API Endpoints

All endpoints except `/health` require `Authorization: Bearer YOUR_TOKEN` header.

### Memories

| Endpoint | Method | Description |
|---|---|---|
| `/memories/remember` | POST | Store a memory (async Qdrant + Neo4j writes) |
| `/memories/search` | POST | Semantic search via Qdrant |
| `/memories/context` | POST | Identity + episodic memories for agent turn |
| `/memories/identity` | POST, GET, PATCH, DELETE | Owner-only identity memory management |
| `/memories/forget` | POST | Revoke memories by ID or semantic query |
| `/memories/digest` | GET | Memory digest: unused, low-relevance, recent checkpoints |

### Hooks (server-side working memory)

| Endpoint | Method | Description |
|---|---|---|
| `/hooks/trigger` | POST | Register/update a snapshot trigger |
| `/hooks/buffer` | POST | Buffer a tool call result on the server |
| `/hooks/check` | POST | Evaluate trigger; snapshot and clear if fired |
| `/hooks/flush` | POST | Drain buffer without snapshotting |
| `/hooks/snapshot` | POST | Force a checkpoint regardless of trigger |

### Graph

| Endpoint | Method | Description |
|---|---|---|
| `/graph/recall` | POST | Structured recall by source/date range |
| `/graph/search` | POST | Neo4j traversal from a named entity |

### Skills

| Endpoint | Method | Description |
|---|---|---|
| `/skills/run` | POST | Load a skill template with evidence manifest |
| `/skills/record` | POST | Record an AI generation with full evidence path |
| `/skills/evidence` | POST | Retrieve evidence receipt for a generation |

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
├── docker-compose.yml          # postgres, qdrant, neo4j, redis, app
├── Dockerfile                  # App image — runs alembic migrations on start
├── conf/
│   ├── neo4j.conf             # Neo4j config (strict_validation disabled before APOC)
│   └── apoc.conf               # APOC plugin settings
├── alembic/                    # Database migrations
├── alembic.ini
├── app/
│   ├── main.py                # FastAPI entrypoint, route mounting
│   ├── celery.py              # Celery app with Redis broker
│   ├── config.py              # Environment variable resolver
│   ├── dependencies.py        # Auth dependencies (get_current_token, require_owner)
│   ├── embeddings.py          # NVIDIA NIM embeddings (nvidia/nv-embed-v1)
│   ├── entity_extraction.py   # NVIDIA NIM entity extraction (phi-3-mini)
│   ├── tasks.py               # Celery tasks: upsert_qdrant, upsert_neo4j, extract_entities
│   ├── models.py              # SQLAlchemy models
│   ├── schemas.py             # Pydantic request/response schemas
│   ├── routes/
│   │   ├── health.py         # GET /health
│   │   ├── auth.py           # /auth/* — setup, login, token management
│   │   ├── memory.py         # /memories/* endpoints
│   │   ├── hooks.py          # /hooks/* — server-side working memory
│   │   ├── graph.py          # /graph/* endpoints
│   │   └── skills.py         # /skills/* endpoints
│   ├── hooks/                  # Client-side hook library (WorkingMemory, SnapshotTrigger)
│   ├── integrations/          # Agent framework integrations (Hermes, OpenClaw, Pi, GoClaw, etc.)
│   └── db/
│       ├── qdrant.py         # Qdrant client + payload indexes
│       └── neo4j/
│           ├── __init__.py   # Public API exports
│           ├── client.py     # Neo4j driver singleton + indexes
│           ├── nodes.py      # Typed node dataclasses
│           ├── relationships.py
│           ├── transactions.py
│           └── evidence.py   # EvidencePath, EvidenceStep, Evidence relations
├── docs/
│   ├── architecture/          # System and agent memory architecture docs
│   ├── integrations.md         # Agent framework integration guide
│   └── connecting-agents.md   # Agent connection and provisioning guide
├── scripts/
│   ├── seed_skills.py         # Seeds skill templates to Postgres
│   └── test_connection.py      # Connectivity verification
└── tests/                     # pytest test suite
```

---

## CI/CD

Every push to `main` and every PR runs:

- `ruff format` — code formatting
- `ruff check` — linting
- `mypy --ignore-missing-imports` — type checking
- `pytest` — all tests (mocked + live integration)

---

## Deploy to a VPS

```bash
# On the server, clone once:
git clone https://github.com/YOUR_HANDLE/logios-brain.git ~/logios-brain

# Run the deploy script from your local machine:
SERVER_IP=your.vps.ip SSH_USER=your_user ./scripts/deploy.sh
```

Prerequisites on the server: Docker, Docker Compose, SSH access.

---

## Documentation

| Guide | Description |
|---|---|
| [`docs/connecting-agents.md`](docs/connecting-agents.md) | Connect an agent to Logios Brain — provisioning, auth, API usage |
| [`docs/integrations.md`](docs/integrations.md) | Framework-specific integration libraries |

### Architecture

| Doc | Description |
|---|---|
| [`docs/architecture/memory-system.md`](docs/architecture/memory-system.md) | Three-tier memory model (working/episodic/semantic) |
| [`docs/architecture/agent-memory.md`](docs/architecture/agent-memory.md) | How agents interact with each memory tier |
| [`docs/architecture/evidence-layer.md`](docs/architecture/evidence-layer.md) | Provenance tracking for every generation |
| [`docs/architecture/postgres.md`](docs/architecture/postgres.md) | PostgreSQL/pgvector schema and design |
| [`docs/architecture/qdrant.md`](docs/architecture/qdrant.md) | Qdrant vector store configuration |
| [`docs/architecture/neo4j.md`](docs/architecture/neo4j.md) | Neo4j graph structure and Cypher patterns |
| [`docs/architecture/entity-extraction.md`](docs/architecture/entity-extraction.md) | LLM-based entity extraction pipeline |
| [`docs/architecture/mcp.md`](docs/architecture/mcp.md) | MCP server interface |
| [`docs/architecture/auth.md`](docs/architecture/auth.md) | Auth flow, token scopes, owner/agent separation |
| [`docs/architecture/spacy.md`](docs/architecture/spacy.md) | spaCy NER preflight and graceful degradation |

---

## Contributing

Contributions are welcome. Please ensure `ruff check` and `mypy` pass before submitting a PR.
