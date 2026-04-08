# Logios Brain

Personal AI memory infrastructure. One shared knowledge layer that every AI you run can read from and write to through the Model Context Protocol (MCP).

Built on three stores: PostgreSQL for the ledger, Qdrant for semantic retrieval, and Neo4j for the knowledge graph.

---

## What It Does

Logios Brain captures every memory you store and makes it searchable by semantic similarity, source, or graph relationships. It tracks every AI generation with a full evidence receipt — which memories were retrieved, which graph nodes were traversed, which model ran, on which machine.

When you run a skill (e.g. weekly review, competitive analysis, memory migration), Logios builds an evidence manifest before the AI produces output. The receipt is stored alongside the output so you can trace it later.

---

## Architecture

```
Client (Claude Code, agent, Telegram bot)
           │
           │  HTTP + X-Brain-Key auth
           ▼
     FastAPI MCP Server
     ┌────────────────────────────────┐
     │  remember / search / recall /   │
     │  graph_search / relate /        │
     │  run_skill / record_generation  │
     └──────┬──────────┬─────────┬─────┘
            │          │         │
            ▼          ▼         ▼
       PostgreSQL    Qdrant   Neo4j
      (pgvector)   (vectors) (graph)
        Ledger    Retriever  Reasoner
            │
            └──► Gemini API (embeddings)

```

### The Three Stores

| Store | Role | What lives here |
|---|---|---|
| **PostgreSQL** | Ledger | Every raw memory, chunk, entity, generation record, evidence receipt |
| **Qdrant** | Retriever | Chunk embeddings (3072-dim) for semantic search |
| **Neo4j** | Reasoner | Entity graph — projects, concepts, people, relationships, provenance |

The `memory_id` is the spine that connects all three stores.

---

## Quick Start

### 1. Clone and start containers

```bash
git clone https://github.com/YOUR_HANDLE/logios-brain.git
cd logios-brain
docker compose up -d
```

Wait for all three containers to be healthy:

```bash
docker compose ps
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials — all required keys are documented inline
```

At minimum you need:
- `GEMINI_API_KEY` — for embeddings (free tier, 3072-dim `text-embedding-004`)
- `NEO4J_PASSWORD` — generate with `openssl rand -hex 16`
- `POSTGRES_PASSWORD` — generate with `openssl rand -hex 16`
- `MCP_ACCESS_KEY` — the key your clients use to authenticate

### 3. Run schema migrations

```bash
docker compose exec postgres psql -U logios -d logios_brain -f /schema/migrations/001_core_tables.sql
docker compose exec postgres psql -U logios -d logios_brain -f /schema/migrations/002_skills_table.sql
docker compose exec postgres psql -U logios -d logios_brain -f /schema/migrations/003_generations_table.sql
docker compose exec postgres psql -U logios -d logios_brain -f /schema/migrations/004_evidence_table.sql
docker compose exec postgres psql -U logios -d logios_brain -f /schema/migrations/005_access_control.sql
docker compose exec postgres psql -U logios -d logios_brain -f /schema/migrations/006_functions.sql
```

### 4. Set up Python and start the server

```bash
cd server
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. uvicorn main:app --port 8000 &
```

### 5. Seed skills and test

```bash
# Seed the six skill templates
python ../scripts/seed_skills.py

# Run connectivity tests (PostgreSQL, Qdrant, Neo4j, embeddings)
python ../scripts/test_connection.py
```

---

## MCP Tools

All tools authenticate via `X-Brain-Key: YOUR_KEY` header or `?key=YOUR_KEY` query param.

| Tool | What it does |
|---|---|
| `POST /tools/remember` | Store a memory — writes to Postgres, Qdrant (embedding), and Neo4j (entity extraction) |
| `POST /tools/search` | Semantic search over memories — Qdrant vector + Postgres hydration |
| `POST /tools/recall` | Structured recall by source or date range |
| `POST /tools/graph_search` | Traverse the knowledge graph from an entity (APOC subgraph) |
| `POST /tools/relate` | Manually create a relationship between two entities |
| `POST /tools/run_skill` | Load a skill template, run evidence search, return prompt + manifest (no LLM call) |
| `POST /tools/record_generation` | Record an AI generation with evidence manifest |
| `POST /tools/get_evidence` | Retrieve the evidence receipt for a generation |

Health check:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Tool list:

```bash
curl -H "X-Brain-Key: YOUR_KEY" http://localhost:8000/mcp/tools
```

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `USE_LOCAL_STORES` | Use local Docker stores | `true` |
| `USE_SUPABASE` | Use cloud Supabase instead | `false` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://logios:...@127.0.0.1:5432/logios_brain` |
| `QDRANT_URL` | Qdrant HTTP URL | `http://localhost:6333` |
| `NEO4J_URI` | Neo4j bolt URL | `bolt://localhost:7687` |
| `NEO4J_USERNAME` | Neo4j user | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | — |
| `GEMINI_API_KEY` | Gemini API key for embeddings | — |
| `MCP_ACCESS_KEY` | Access key for tool auth | — |
| `OLLAMA_URL` | Ollama URL for entity extraction | `http://localhost:11434` |
| `ENTITY_MODEL` | Ollama model for entity extraction | `mistral:7b` |

---

## Repository Structure

```
logios-brain/
├── docker-compose.yml        # PostgreSQL, Qdrant, Neo4j containers
├── .env                    # Credentials (gitignored)
├── .env.example            # Template with all variables documented
├── conf/
│   ├── neo4j.conf          # Neo4j config (strict_validation disabled before APOC loads)
│   └── apoc.conf           # APOC plugin settings (loaded after plugin init)
├── schema/migrations/      # Six SQL migration files
├── server/
│   ├── main.py             # FastAPI MCP server
│   ├── config.py            # Environment variable resolver
│   ├── embeddings.py        # Gemini text-embedding-004
│   ├── entity_extraction.py # Ollama LLM entity extraction (best-effort)
│   ├── db/
│   │   ├── postgres.py      # psycopg2 ThreadedConnectionPool client
│   │   ├── supabase.py      # Supabase client (cloud alternative)
│   │   ├── qdrant.py        # Qdrant client
│   │   └── neo4j_client.py  # Neo4j GraphDatabase driver
│   └── tools/
│       ├── remember.py      # Write path: memory + embedding + entity extraction
│       ├── search.py        # Read path: vector search + graph search + recall
│       ├── relate.py        # Manual graph relationship creation
│       ├── run_skill.py     # Skill execution with evidence manifest
│       └── get_evidence.py  # Generation receipt retrieval
├── scripts/
│   ├── test_connection.py   # Connectivity verification script
│   ├── seed_skills.py       # Seeds six skill templates to Postgres
│   ├── backup.sh            # pg_dump + Qdrant snapshot + neo4j-admin backup
│   └── deploy.sh           # Hetzner VPS deployment script
└── .github/workflows/
    ├── ci.yml              # ruff, mypy, import chain on push/PR
    └── deploy.yml           # Docker build/push + Hetzner SSH deploy
```

---

## Deploy to Hetzner

```bash
# On the VPS, clone once:
git clone https://github.com/YOUR_HANDLE/logios-brain.git ~/logios-brain

# Run the deploy script (from your local machine):
HETZNER_IP=your.vps.ip HETZNER_USER=your_user ./scripts/deploy.sh
```

Prerequisites on Hetzner: Docker, Docker Compose, Python 3.11, SSH access.

---

## CI/CD

Every push to `main` and every PR runs:

- `ruff format` — code formatting
- `ruff check --fix` — linting with auto-fix
- `mypy --ignore-missing-imports` — type checking
- Import chain verification — all modules must resolve without errors

The deploy workflow builds and pushes a Docker image to GitHub Container Registry, then SSHs to Hetzner to pull and restart the service.
