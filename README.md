# Logios Brain

Personal AI memory infrastructure. One shared knowledge layer that every AI you run can read from and write to through the Model Context Protocol (MCP).

Built on three stores: PostgreSQL for the ledger, Qdrant for semantic retrieval, and Neo4j for the knowledge graph.

---

## What It Does

Logios Brain captures every memory you store and makes it searchable by semantic similarity, source, or graph relationships. It tracks every AI generation with a full evidence receipt — which memories were retrieved, which graph nodes were traversed, which model ran, on which machine.

When you run a skill (e.g. weekly review, competitive analysis, memory migration), Logios builds an evidence manifest before the AI produces output. The receipt is stored alongside the output so you can trace it later.


The server is the front door. When an AI wants to remember something or look something up, it knocks on this door.

Behind that door are three helpers, each with one job:
- PostgreSQL is the filing cabinet. Every single thing that ever gets remembered goes in here first. It never forgets and never loses anything.
- Qdrant is the "find me something similar" helper. It turns memories into numbers so it can ask "what else did we capture that feels like this?" — even if the exact words are different. It needs the NVIDIA API to do the number-crunching, which is why there's a free API call happening there.
- Neo4j is the map maker. It doesn't just store memories — it draws lines between them. "This project connects to this concept, which came up in that session." It's what lets you ask why things are related, not just what exists.

The evidence layer at the bottom is the most important piece. Every time an AI produces something — an analysis, a plan, a summary — it doesn't just hand you the answer. It staples a receipt to it: here are the 5 memories I read, here's which connection in Neo4j I followed, here's which model produced this, at this time, on this machine. Six months later you can look back at any output and know exactly what the system was thinking.
A concrete example of what each does:
You capture a memory: "met with client about pricing strategy"

NVIDIA reads that sentence and returns a list of ~3000 numbers that mathematically represent its meaning. It then forgets it ever existed — it has no memory between calls.
Qdrant stores those numbers permanently, tagged with your memory_id. Later when you ask "what do I know about client negotiations?", Qdrant compares the numbers for that query against every stored memory and returns the closest matches — without NVIDIA being involved at all in the search.

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
uv sync
source .venv/bin/activate
uvicorn server.main:app --port 8000 &
```

### 5. Seed skills and test

```bash
# Seed the six skill templates
python scripts/seed_skills.py

# Run connectivity tests (PostgreSQL, Qdrant, Neo4j, embeddings)
python scripts/test_connection.py
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

## Security

PostgreSQL is bound to `127.0.0.1` only — no external network access. The `logios` database user is the sole application user with full access to the `logios_brain` database.

For dashboards or read-only access, create a separate user:

```sql
create user logios_readonly with password 'your_generated_password';
grant connect on database logios_brain to logios_readonly;
grant usage on schema public to logios_readonly;
grant select on all tables in schema public to logios_readonly;
alter default privileges in schema public grant select on tables to logios_readonly;
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
