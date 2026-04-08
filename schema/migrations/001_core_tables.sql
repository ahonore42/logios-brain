-- ============================================================
-- MIGRATION 001: Core tables
-- pgvector/pgvector:pg16 image includes vector binary,
-- but the extension still needs to be enabled per database.
-- Run: docker exec -it logios-postgres psql -U logios -d logios_brain -f /tmp/001_core_tables.sql
-- Or pipe: cat 001_core_tables.sql | docker exec -i logios-postgres psql -U logios -d logios_brain
-- ============================================================

create extension if not exists vector;
create extension if not exists "uuid-ossp";

-- ------------------------------------------------------------
-- memories: The append-only source of truth for everything captured
-- ------------------------------------------------------------
create table memories (
  id           uuid primary key default gen_random_uuid(),
  content      text not null,
  source       text not null check (source in (
                 'telegram', 'claude', 'agent', 'manual', 'import', 'system'
               )),
  session_id   uuid,
  captured_at  timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  metadata     jsonb not null default '{}'::jsonb,

  -- Deduplication fingerprint: SHA-256 of normalized content
  content_fingerprint text unique
);

create index idx_memories_source       on memories (source);
create index idx_memories_captured_at on memories (captured_at desc);
create index idx_memories_session_id   on memories (session_id);
create index idx_memories_metadata    on memories using gin (metadata);

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