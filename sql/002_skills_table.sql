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