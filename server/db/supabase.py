"""
server/db/supabase.py

Supabase client — used when USE_SUPABASE=true.
The local Docker default uses postgres.py instead.
"""

from supabase import Client, create_client

import config

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    return _client


def upsert_memory(
    content: str,
    source: str,
    metadata: dict | None = None,
    session_id: str | None = None,
) -> str:
    """Deduplication-safe memory insert via Supabase RPC."""
    sb = get_supabase()
    result = sb.rpc(
        "upsert_memory",
        {
            "p_content": content,
            "p_source": source,
            "p_metadata": metadata or {},
            "p_session_id": session_id,
        },
    ).execute()
    return str(result.data)


def insert_chunk(
    memory_id: str, content: str, qdrant_id: str, chunk_index: int = 0
) -> str:
    """Insert a chunk record via Supabase client."""
    sb = get_supabase()
    result = (
        sb.table("chunks")
        .insert(
            {
                "memory_id": memory_id,
                "content": content,
                "chunk_index": chunk_index,
                "qdrant_id": qdrant_id,
            }
        )
        .execute()
    )
    return str(result.data[0]["id"])


def upsert_entity(
    memory_id: str,
    neo4j_node_id: str,
    label: str,
    name: str,
) -> None:
    """Insert or update an entity record via Supabase client."""
    sb = get_supabase()
    sb.table("entities").upsert(
        {
            "memory_id": memory_id,
            "neo4j_node_id": neo4j_node_id,
            "label": label,
            "name": name,
        },
        on_conflict="neo4j_node_id",
    ).execute()


def get_memories(memory_ids: list[str]) -> dict[str, dict]:
    """Hydrate memory content from Supabase."""
    if not memory_ids:
        return {}
    sb = get_supabase()
    result = (
        sb.table("memories")
        .select("id, content, source, captured_at, metadata")
        .in_("id", memory_ids)
        .execute()
    )
    return {m["id"]: m for m in result.data}


def get_skill(skill_name: str) -> dict | None:
    """Get an active skill by name."""
    sb = get_supabase()
    result = (
        sb.table("skills")
        .select("id, name, description, prompt_template")
        .eq("name", skill_name)
        .eq("active", True)
        .single()
        .execute()
    )
    return result.data if result.data else None


def insert_generation(
    skill_id: str | None,
    skill_name: str | None,
    output: str,
    model: str,
    machine: str,
    prompt_used: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Insert a generation record via Supabase client."""
    sb = get_supabase()
    result = (
        sb.table("generations")
        .insert(
            {
                "skill_id": skill_id,
                "skill_name": skill_name,
                "output": output,
                "model": model,
                "machine": machine,
                "prompt_used": prompt_used,
                "session_id": session_id,
                "metadata": metadata or {},
            }
        )
        .execute()
    )
    return str(result.data[0]["id"])


def insert_evidence_batch(evidence_rows: list[dict]) -> None:
    """Bulk insert evidence rows via Supabase client."""
    if not evidence_rows:
        return
    sb = get_supabase()
    sb.table("evidence").insert(evidence_rows).execute()


def get_generation_receipt(p_generation_id: str) -> dict:
    """Return the full evidence receipt for a generation via Supabase RPC."""
    sb = get_supabase()
    result = sb.rpc(
        "get_generation_receipt",
        {"p_generation_id": p_generation_id},
    ).execute()
    return result.data or {}
