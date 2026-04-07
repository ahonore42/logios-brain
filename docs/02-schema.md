# Step 2: Supabase Schema

Run these SQL blocks in order in your Supabase SQL Editor (**SQL Editor → New query**). Run each migration as its own query. Do not combine them into one block.

The schema covers six tables, two functions, Row Level Security policies, and all necessary indexes.

---

## Migration 001 — Core tables

This creates the three primary tables: `memories` (the raw ledger), `chunks` (embedded fragments), and `entities` (the Neo4j node registry).

```sql
-- ============================================================
-- MIGRATION 001: Core tables
-- ============================================================

-- Enable required extensions
create extension if not exists vector;
create extension if not exists "uuid-ossp";

-- ------------------------------------------------------------
-- memories: The append-only source of truth for everything captured
-- ------------------------------------------------------------
create table memories (
  id           uuid primary key default gen_random_uuid(),
  content      text not null,
  source       text not null check (source in (
                 'telegram', 'claude', 'exo', 'manual', 'import', 'system'
               )),
  session_id   uuid,
  captured_at  timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  metadata     jsonb not null default '{}'::jsonb,

  -- Deduplication fingerprint: SHA-256 of normalized content
  content_fingerprint text unique
);

-- Indexes for common query patterns
create index idx_memories_source       on memories (source);
create index idx_memories_captured_at  on memories (captured_at desc);
create index idx_memories_session_id   on memories (session_id);
create index idx_memories_metadata     on memories using gin (metadata);

-- Auto-update updated_at
create or replace function touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger memories_updated_at
  before update on memories
  for each row execute function touch_updated_at();

-- ------------------------------------------------------------
-- chunks: Embedded fragments of memories, indexed in Qdrant
-- ------------------------------------------------------------
create table chunks (
  id          uuid primary key default gen_random_uuid(),
  memory_id   uuid not null references memories (id) on delete cascade,
  content     text not null,
  chunk_index int  not null default 0,
  token_count int,
  qdrant_id   uuid unique,   -- cross-reference to Qdrant point ID
  created_at  timestamptz not null default now()
);

create index idx_chunks_memory_id on chunks (memory_id);
create index idx_chunks_qdrant_id on chunks (qdrant_id);

-- ------------------------------------------------------------
-- entities: Registry of Neo4j nodes — keeps Postgres as the ledger
-- ------------------------------------------------------------
create table entities (
  id             uuid primary key default gen_random_uuid(),
  memory_id      uuid not null references memories (id) on delete cascade,
  neo4j_node_id  text not null,
  label          text not null check (label in (
                   'Project', 'Concept', 'Person', 'Session',
                   'Event', 'Decision', 'Tool', 'Location'
                 )),
  name           text not null,
  created_at     timestamptz not null default now()
);

create index idx_entities_memory_id     on entities (memory_id);
create index idx_entities_neo4j_node_id on entities (neo4j_node_id);
create index idx_entities_label         on entities (label);
create unique index idx_entities_neo4j_unique on entities (neo4j_node_id);
```

---

## Migration 002 — Skills table

Skills are versioned prompt templates stored in Postgres. The MCP server loads them by name when `run_skill` is called.

```sql
-- ============================================================
-- MIGRATION 002: Skills table
-- ============================================================

create table skills (
  id               uuid primary key default gen_random_uuid(),
  name             text not null unique,
  description      text,
  prompt_template  text not null,
  version          int  not null default 1,
  active           boolean not null default true,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index idx_skills_name   on skills (name);
create index idx_skills_active on skills (active) where active = true;

create trigger skills_updated_at
  before update on skills
  for each row execute function touch_updated_at();
```

---

## Migration 003 — Generations table

Every AI output produced through this system is recorded here. This is the parent record for the evidence layer.

```sql
-- ============================================================
-- MIGRATION 003: Generations table
-- ============================================================

create table generations (
  id            uuid primary key default gen_random_uuid(),
  skill_id      uuid references skills (id) on delete set null,
  skill_name    text,           -- denormalized for resilience if skill is deleted
  output        text not null,
  model         text not null,  -- e.g. "llama3.3:70b", "qwen3-coder:480b"
  machine       text,           -- e.g. "serval-ws", "hetzner"
  session_id    uuid,
  prompt_used   text,           -- the full prompt sent to the model
  generated_at  timestamptz not null default now(),
  metadata      jsonb not null default '{}'::jsonb
);

create index idx_generations_skill_id     on generations (skill_id);
create index idx_generations_skill_name   on generations (skill_name);
create index idx_generations_generated_at on generations (generated_at desc);
create index idx_generations_session_id   on generations (session_id);
create index idx_generations_machine      on generations (machine);
```

---

## Migration 004 — Evidence table

This is the receipt layer. One row per source used in a generation. This is what makes every output accountable.

```sql
-- ============================================================
-- MIGRATION 004: Evidence table
-- ============================================================

create type retrieval_type as enum ('vector', 'graph', 'hybrid', 'direct');

create table evidence (
  id               uuid primary key default gen_random_uuid(),
  generation_id    uuid not null references generations (id) on delete cascade,
  memory_id        uuid references memories (id) on delete set null,
  chunk_id         uuid references chunks (id) on delete set null,
  neo4j_node_id    text,           -- graph node that was traversed
  neo4j_rel_type   text,           -- relationship type if via graph edge
  relevance_score  float,          -- cosine similarity or graph distance
  retrieval_type   retrieval_type not null,
  rank             int not null,   -- ordering of evidence used (1 = most relevant)
  created_at       timestamptz not null default now()
);

create index idx_evidence_generation_id on evidence (generation_id);
create index idx_evidence_memory_id     on evidence (memory_id);
create index idx_evidence_chunk_id      on evidence (chunk_id);

-- Convenience view: full evidence with memory content
create view evidence_with_content as
  select
    e.id,
    e.generation_id,
    e.rank,
    e.retrieval_type,
    e.relevance_score,
    e.neo4j_node_id,
    e.neo4j_rel_type,
    m.id         as memory_id,
    m.content    as memory_content,
    m.source     as memory_source,
    m.captured_at,
    c.content    as chunk_content
  from evidence e
  left join memories m on m.id = e.memory_id
  left join chunks c   on c.id = e.chunk_id;
```

---

## Migration 005 — Row Level Security

Lock everything down so only the service role (your MCP server) can read and write.

```sql
-- ============================================================
-- MIGRATION 005: Row Level Security
-- ============================================================

alter table memories    enable row level security;
alter table chunks      enable row level security;
alter table entities    enable row level security;
alter table skills      enable row level security;
alter table generations enable row level security;
alter table evidence    enable row level security;

-- Service role has full access to everything
create policy "service_role_memories"    on memories    for all using (auth.role() = 'service_role');
create policy "service_role_chunks"      on chunks      for all using (auth.role() = 'service_role');
create policy "service_role_entities"    on entities    for all using (auth.role() = 'service_role');
create policy "service_role_skills"      on skills      for all using (auth.role() = 'service_role');
create policy "service_role_generations" on generations for all using (auth.role() = 'service_role');
create policy "service_role_evidence"    on evidence    for all using (auth.role() = 'service_role');

-- Explicit grants (required on newer Supabase projects)
grant select, insert, update, delete on memories    to service_role;
grant select, insert, update, delete on chunks      to service_role;
grant select, insert, update, delete on entities    to service_role;
grant select, insert, update, delete on skills      to service_role;
grant select, insert, update, delete on generations to service_role;
grant select, insert, update, delete on evidence    to service_role;
grant select                         on evidence_with_content to service_role;
```

---

## Migration 006 — Database functions

Two functions: one for deduplication-safe memory upsert, one for structured evidence retrieval.

```sql
-- ============================================================
-- MIGRATION 006: Functions
-- ============================================================

-- upsert_memory: inserts a new memory or updates metadata on duplicate
-- Returns the memory_id regardless of whether it was inserted or already existed
create or replace function upsert_memory(
  p_content   text,
  p_source    text,
  p_metadata  jsonb default '{}'::jsonb,
  p_session_id uuid default null
)
returns uuid
language plpgsql
as $$
declare
  v_fingerprint text;
  v_id          uuid;
begin
  -- Normalize and fingerprint
  v_fingerprint := encode(
    sha256(convert_to(
      lower(trim(regexp_replace(p_content, '\s+', ' ', 'g'))),
      'UTF8'
    )),
    'hex'
  );

  insert into memories (content, source, session_id, metadata, content_fingerprint)
  values (p_content, p_source, p_session_id, p_metadata, v_fingerprint)
  on conflict (content_fingerprint) do update
    set updated_at = now(),
        metadata   = memories.metadata || excluded.metadata
  returning id into v_id;

  return v_id;
end;
$$;

-- get_generation_receipt: returns the full evidence receipt for a generation
create or replace function get_generation_receipt(p_generation_id uuid)
returns jsonb
language plpgsql
as $$
declare
  v_generation jsonb;
  v_evidence   jsonb;
begin
  select to_jsonb(g) into v_generation
  from generations g
  where g.id = p_generation_id;

  select jsonb_agg(
    jsonb_build_object(
      'rank',             e.rank,
      'retrieval_type',   e.retrieval_type,
      'relevance_score',  e.relevance_score,
      'memory_id',        e.memory_id,
      'memory_content',   e.memory_content,
      'memory_source',    e.memory_source,
      'captured_at',      e.captured_at,
      'chunk_content',    e.chunk_content,
      'neo4j_node_id',    e.neo4j_node_id,
      'neo4j_rel_type',   e.neo4j_rel_type
    )
    order by e.rank
  )
  into v_evidence
  from evidence_with_content e
  where e.generation_id = p_generation_id;

  return jsonb_build_object(
    'generation', v_generation,
    'evidence',   coalesce(v_evidence, '[]'::jsonb)
  );
end;
$$;

grant execute on function upsert_memory      to service_role;
grant execute on function get_generation_receipt to service_role;
```

---

## Verification

After running all six migrations, verify the schema is correct:

**Check tables exist:**
```sql
select table_name
from information_schema.tables
where table_schema = 'public'
order by table_name;
```

Expected output: `chunks`, `entities`, `evidence`, `generations`, `memories`, `skills`

**Check functions exist:**
```sql
select routine_name
from information_schema.routines
where routine_schema = 'public';
```

Expected output: `get_generation_receipt`, `touch_updated_at`, `upsert_memory`

**Check the view exists:**
```sql
select viewname
from pg_views
where schemaname = 'public';
```

Expected output: `evidence_with_content`

**Check RLS is enabled:**
```sql
select tablename, rowsecurity
from pg_tables
where schemaname = 'public'
order by tablename;
```

All six tables should show `rowsecurity = true`.

---

## What You Have Now

- A complete ledger for every memory, chunk, entity, skill, generation, and evidence record
- Deduplication on every memory write via content fingerprinting
- A full provenance receipt system — every AI output can be traced to its sources
- RLS that ensures only your server can read or write anything

**Next: [Neo4j Setup](04-neo4j.md)**