# Logios Brain

Personal AI memory infrastructure. One shared knowledge layer that every AI you run, locally or remotely, can read from and write to through the Model Context Protocol (MCP).

Built on the architectural patterns of [OB1/Open Brain](https://github.com/NateBJones-Projects/OB1) with a richer storage backend designed for a personal knowledge graph.

---

## What This Is

A self-hosted, always-on memory system for your AI agents and local LLMs. Instead of each AI session starting from zero, every session connects to a shared brain that accumulates everything you capture, generates, and reason about with full provenance on every output.

This is not a notes app. It is infrastructure.

---

## Architecture

```
Your Machines (desktop, laptop, Telegram bot)
              │
              │  MCP over HTTP/SSE
              ▼
     FastAPI MCP Server (Hetzner VPS)
     ┌────────────────────────────────┐
     │  remember / search / relate /  │
     │  run_skill / get_evidence      │
     └──────┬──────────┬─────────┬───┘
            │          │         │
            ▼          ▼         ▼
       Supabase      Qdrant    Neo4j
      (Postgres)    (Cloud)   (AuraDB)
       Ledger       Retriever  Reasoner
            │
            └──► Gemini API (embeddings, free tier)
```

### The Three Stores

| Store | Role | What lives here |
|---|---|---|
| **Supabase (Postgres)** | Ledger | Every raw memory, session log, generation record, evidence receipt |
| **Qdrant** | Retriever | Chunk embeddings for semantic search |
| **Neo4j** | Reasoner | Entity graph — projects, concepts, people, relationships, provenance |

The `memory_id` from Supabase is the spine that connects all three stores. Every Qdrant point and every Neo4j node references it.

### The Skills + Evidence Layer

Every AI output produced through this system comes with a receipt: which memories were retrieved, which graph nodes were traversed, which model produced the output, on which machine, at what time. Six months later you can reconstruct exactly what the system was thinking when it wrote anything.

---

## Stack

| Component | Service | Cost |
|---|---|---|
| Structured store | Supabase (free tier) | $0 |
| Vector store | Qdrant Cloud (free tier) | $0 |
| Graph store | Neo4j AuraDB (free tier) | $0 |
| Embeddings | `gemini-embedding-001` (free tier) | $0 |
| MCP server | FastAPI on Hetzner (existing VPS) | $0 marginal |
| LLM inference | Local models via Ollama / llama.cpp | $0 |

Realistic monthly cost: **$0–$1.50** (embedding + entity extraction LLM calls at personal volume).

---

## Repository Structure

```
logios-brain/
├── README.md
├── docs/
│   ├── 01-setup.md              # Service accounts and credentials
│   ├── 02-schema.md             # Full Supabase SQL schema
│   ├── 03-mcp-server.md         # FastAPI server, code and Hetzner deployment
│   ├── 04-neo4j.md              # Neo4j AuraDB setup and Cypher schema
│   ├── 05-qdrant.md             # Qdrant Cloud setup and collection config
│   ├── 06-gemini-embeddings.md  # Embedding integration
│   ├── 07-skills-evidence.md    # Skills + evidence layer design and schema
│   ├── 08-connecting-clients.md # Local machines, agent, Telegram
│   └── 09-companion-prompts.md  # Prompts for memory migration and weekly review
├── server/
│   ├── main.py                  # FastAPI MCP server entrypoint
│   ├── tools/
│   │   ├── remember.py          # Write path, memory ingestion
│   │   ├── search.py            # Read path, Qdrant + Neo4j retrieval
│   │   ├── relate.py            # Manual graph edge creation
│   │   ├── run_skill.py         # Skill execution with evidence recording
│   │   └── get_evidence.py      # Receipt retrieval
│   ├── db/
│   │   ├── supabase.py          # Supabase client
│   │   ├── qdrant.py            # Qdrant client
│   │   └── neo4j.py             # Neo4j client
│   ├── embeddings.py            # Gemini embedding calls
│   ├── entity_extraction.py     # LLM entity extraction for Neo4j
│   └── requirements.txt
├── schema/
│   ├── migrations/
│   │   ├── 001_core_tables.sql
│   │   ├── 002_skills_table.sql
│   │   ├── 003_generations_table.sql
│   │   ├── 004_evidence_table.sql
│   │   └── 005_rls_policies.sql
│   └── functions/
│       ├── search_memories.sql
│       └── upsert_memory.sql
├── scripts/
│   ├── seed_skills.py           # Load initial skill templates
│   └── test_connection.py       # Verify all three stores are reachable
├── skills/                      # Skill prompt templates (markdown)
│   └── README.md
└── integrations/
    └── telegram/
        └── README.md
```

---

## Build Order

Build in this sequence. Each step depends on the previous one being complete.

1. **[Service Setup](docs/01-setup.md)** — Create accounts, generate API keys, save credentials
2. **[Supabase Schema](docs/02-schema.md)** — Run SQL migrations to create all tables and functions
3. **[Neo4j Setup](docs/04-neo4j.md)** — Create AuraDB instance and apply Cypher schema
4. **[Qdrant Setup](docs/05-qdrant.md)** — Create Cloud cluster and configure collection
5. **[MCP Server](docs/03-mcp-server.md)** — Deploy FastAPI server to Hetzner
6. **[Embeddings](docs/06-gemini-embeddings.md)** — Wire Gemini into the server write path
7. **[Skills + Evidence](docs/07-skills-evidence.md)** — Understand and seed the evidence layer
8. **[Connect Clients](docs/08-connecting-clients.md)** — Connect Computer, Slack, Telegram
9. **[Companion Prompts](docs/09-companion-prompts.md)** — Seed your brain with existing context

---

## Relationship to OB1

This project uses OB1's core patterns: MCP protocol, Supabase as the backbone, semantic search over captured memories.
It extends them with:

- **Neo4j** for a true knowledge graph over entities and relationships
- **Qdrant** as a dedicated vector store replacing pgvector
- **Skills + evidence layer** so every AI output has a provenance receipt
- **FastAPI** instead of Supabase Edge Functions, giving full control over the server runtime and enabling local or Hetzner deployment without vendor lock-in
- **Gemini embeddings** (`gemini-embedding-001`) replacing OpenRouter embeddings: free, high quality, 3072-dimensional

OB1's companion prompts, skill patterns, and import recipes are compatible with this stack. The MCP tool names are intentionally similar so existing OB1 skills work with minimal adaptation.

---

## License

MIT