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