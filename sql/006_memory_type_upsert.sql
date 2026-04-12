-- ============================================================
-- MIGRATION 006: Add type parameter to upsert_memory
-- ============================================================

-- upsert_memory: now accepts p_type to support checkpoint/identity memory types
create or replace function upsert_memory(
  p_content    text,
  p_source     text,
  p_metadata   jsonb default '{}'::jsonb,
  p_session_id uuid default null,
  p_type      text default 'standard'
)
returns uuid
language plpgsql
as $$
declare
  v_fingerprint text;
  v_id         uuid;
begin
  v_fingerprint := encode(
    sha256(convert_to(
      lower(trim(regexp_replace(p_content, '\s+', ' ', 'g'))),
      'UTF8'
    )),
    'hex'
  );

  insert into memories (content, source, session_id, metadata, content_fingerprint, type)
  values (p_content, p_source, p_session_id, p_metadata, v_fingerprint, p_type)
  on conflict (content_fingerprint) do update
    set updated_at = now(),
        metadata   = memories.metadata || excluded.metadata,
        type      = excluded.type
  returning id into v_id;

  return v_id;
end;
$$;
