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