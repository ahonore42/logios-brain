-- ============================================================
-- MIGRATION 006: Database functions
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