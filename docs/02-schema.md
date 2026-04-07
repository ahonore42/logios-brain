# Step 2: PostgreSQL Schema

PostgreSQL is your ledger — the system of record that every other store references by `memory_id`. It runs locally on your Hetzner VPS in Docker alongside Qdrant and Neo4j.

Run the migrations below after your Docker Compose stack is up and healthy. Each migration is a separate SQL block — run them in order, one at a time.

---

## Prerequisites

Your Docker Compose stack must be running before you apply migrations. If you have not set it up yet, see the Docker Compose section in `docs/03-mcp-server.md` first.

```bash
cd /opt/logios-brain
docker compose up -d
docker compose ps   # all three services should show "healthy"
```

---

## Connecting to the local database

**Option A — interactive psql session (recommended for running migrations manually):**
```bash
docker exec -it logios-postgres psql -U logios -d logios_brain
```

Paste each migration block at the prompt and press Enter to run it.

**Option B — pipe a file directly:**
```bash
docker exec -i logios-postgres psql -U logios -d logios_brain \
  < schema/migrations/001_core_tables.sql
```

Run this for each migration file in sequence.

---

## Migration 001 — Core tables

Creates `memories` (the ledger), `chunks` (embedded fragments), and `entities` (the Neo4j node registry).

```sql
-- ============================================================
-- MIGRATION 001: Core tables
-- ============================================================

-- The pgvector/pgvector:pg16 Docker image includes the vector
-- extension binary — it still needs to be enabled per database.
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

create index idx_memories_source       on memories (source);
create index idx_memories_captured_at  on memories (captured_at desc);
create index idx_memories_session_id   on memories (session_id);
create index idx_memories_metadata     on memories using gin (metadata);

-- Auto-update updated_at on every row change
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
-- chunks: Embedded fragments of memories, cross-referenced to Qdrant
-- ------------------------------------------------------------
create table chunks (
  id          uuid primary key default gen_random_uuid(),
  memory_id   uuid not null references memories (id) on delete cascade,
  content     text not null,
  chunk_index int  not null default 0,
  token_count int,
  qdrant_id   uuid unique,   -- point ID in Qdrant
  created_at  timestamptz not null default now()
);

create index idx_chunks_memory_id on chunks (memory_id);
create index idx_chunks_qdrant_id on chunks (qdrant_id);

-- ------------------------------------------------------------
-- entities: Registry of Neo4j nodes — Postgres as the ledger
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

```sql
-- ============================================================
-- MIGRATION 003: Generations table
-- ============================================================

create table generations (
  id            uuid primary key default gen_random_uuid(),
  skill_id      uuid references skills (id) on delete set null,
  skill_name    text,
  output        text not null,
  model         text not null,
  machine       text,
  session_id    uuid,
  prompt_used   text,
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
  neo4j_node_id    text,
  neo4j_rel_type   text,
  relevance_score  float,
  retrieval_type   retrieval_type not null,
  rank             int not null,
  created_at       timestamptz not null default now()
);

create index idx_evidence_generation_id on evidence (generation_id);
create index idx_evidence_memory_id     on evidence (memory_id);
create index idx_evidence_chunk_id      on evidence (chunk_id);

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

## Migration 005 — Access control

Local PostgreSQL does not use Supabase's Row Level Security. Access control is handled at the infrastructure level: the `logios` database user is the only application user, and the PostgreSQL port is bound to `127.0.0.1` only in Docker Compose — never exposed externally.

Verify ownership is correct:

```sql
select tablename, tableowner
from pg_tables
where schemaname = 'public'
order by tablename;
```

All tables should show `tableowner = logios`.

If you want an additional read-only user for dashboards or inspection:

```sql
-- Optional read-only user
create user logios_readonly with password 'your_generated_password';
grant connect on database logios_brain to logios_readonly;
grant usage on schema public to logios_readonly;
grant select on all tables in schema public to logios_readonly;
alter default privileges in schema public grant select on tables to logios_readonly;
```

---

## Migration 006 — Database functions

```sql
-- ============================================================
-- MIGRATION 006: Functions
-- ============================================================

-- upsert_memory: deduplication-safe insert
-- Returns the memory_id whether this is new or a duplicate
create or replace function upsert_memory(
  p_content    text,
  p_source     text,
  p_metadata   jsonb default '{}'::jsonb,
  p_session_id uuid default null
)
returns uuid
language plpgsql
as $$
declare
  v_fingerprint text;
  v_id          uuid;
begin
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

-- get_generation_receipt: full provenance receipt for one generation
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
```

---

## Verification

Run these after all six migrations.

```sql
-- Tables
select table_name from information_schema.tables
where table_schema = 'public' order by table_name;
-- Expected: chunks, entities, evidence, generations, memories, skills

-- Functions
select routine_name from information_schema.routines
where routine_schema = 'public' order by routine_name;
-- Expected: get_generation_receipt, touch_updated_at, upsert_memory

-- View
select viewname from pg_views where schemaname = 'public';
-- Expected: evidence_with_content

-- Quick write test
select upsert_memory('Schema verification test', 'manual', '{}', null);
select id, content, source, captured_at from memories
order by captured_at desc limit 1;
```

---

## Backup and export

```bash
# Export
docker exec logios-postgres pg_dump \
  -U logios -d logios_brain \
  --format=custom \
  --file=/tmp/logios_brain.dump

docker cp logios-postgres:/tmp/logios_brain.dump \
  /opt/logios-brain/backups/postgres_$(date +%Y%m%d).dump

# Restore on a new server
docker cp /path/to/backup.dump logios-postgres:/tmp/logios_brain.dump

docker exec logios-postgres pg_restore \
  -U logios -d logios_brain \
  --clean --if-exists \
  /tmp/logios_brain.dump
```

See `docs/01-setup.md` for the full automated backup script that covers all three stores.

---

## Alternative: Supabase (cloud-hosted PostgreSQL)

If you prefer not to manage PostgreSQL yourself, Supabase provides hosted PostgreSQL with a web dashboard, point-in-time recovery, and a REST API layer. The schema above is fully compatible — all six migrations run identically in Supabase's SQL Editor.

### What changes

**Docker Compose:** Remove the `postgres` service. Supabase is your database.

**`.env`:** Replace `DATABASE_URL` with:
```env
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_SERVICE_KEY=your_service_key
```

**`server/db/postgres.py`:** Replace the `psycopg2` client with the Supabase Python client:
```python
from supabase import create_client
client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
```

**Migration 005:** Replace the local access control migration with Supabase RLS:
```sql
alter table memories    enable row level security;
alter table chunks      enable row level security;
alter table entities    enable row level security;
alter table skills      enable row level security;
alter table generations enable row level security;
alter table evidence    enable row level security;

create policy "service_role_all" on memories    for all using (auth.role() = 'service_role');
create policy "service_role_all" on chunks      for all using (auth.role() = 'service_role');
create policy "service_role_all" on entities    for all using (auth.role() = 'service_role');
create policy "service_role_all" on skills      for all using (auth.role() = 'service_role');
create policy "service_role_all" on generations for all using (auth.role() = 'service_role');
create policy "service_role_all" on evidence    for all using (auth.role() = 'service_role');

grant select, insert, update, delete on memories, chunks, entities,
  skills, generations, evidence to service_role;
grant select on evidence_with_content to service_role;
grant execute on function upsert_memory, get_generation_receipt to service_role;
```

**Enabling pgvector in Supabase:** Go to **Database → Extensions**, search "vector", enable pgvector before running Migration 001.

### Trade-offs

| | Local PostgreSQL | Supabase |
|---|---|---|
| Cost | $0 (VPS you already pay for) | $0 free tier, then $25/month |
| Data sovereignty | Full — your disk | Supabase's infrastructure |
| Backups | Manual (`pg_dump`) or automated script | Automatic, point-in-time recovery |
| Web UI | None (psql or Adminer via Docker) | Full dashboard |
| Free tier limit | None | 500MB storage |
| Portability | `pg_dump` / `pg_restore` | Same, plus Supabase CLI |

For a personal system intended to grow over years, local PostgreSQL on a VPS you control is the more durable choice. Supabase is the right call if you want to skip database administration entirely and the free tier's limits are not a concern.

---

**Next: [Neo4j Setup](04-neo4j.md)**