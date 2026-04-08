"""
server/db/postgres.py

Local PostgreSQL client via psycopg2.
Used when USE_LOCAL_STORES=true (the default for local Docker deployment).
"""

import hashlib
from contextlib import contextmanager

from psycopg2 import pool
from psycopg2.extras import Json

import config

_pool: pool.ThreadedConnectionPool | None = None


def _get_pool() -> pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=config.DATABASE_URL,
        )
    return _pool


@contextmanager
def _get_conn():
    """Context manager that auto-returns connection to pool."""
    conn = _get_pool().getconn()
    try:
        yield conn
    finally:
        _get_pool().putconn(conn)


def run_query(sql: str, params: tuple | None = None, fetch: bool = True) -> list[dict]:
    """Generic query executor. Returns list of dicts."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            if fetch and cur.description:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            conn.commit()
            return []


def execute(sql: str, params: tuple | None = None, fetch: bool = True) -> list[dict]:
    """Alias for run_query — used by seed_skills.py."""
    return run_query(sql, params, fetch)


# ── Memory operations ────────────────────────────────────────────────────────


def _normalize_fingerprint(content: str) -> str:
    """SHA-256 of lower-case, stripped, whitespace-normalized content."""
    normalized = " ".join(content.lower().strip().split())
    return hashlib.sha256(normalized.encode("utf8")).hexdigest()


def upsert_memory(
    content: str,
    source: str,
    metadata: dict | None = None,
    session_id: str | None = None,
) -> str:
    """
    Deduplication-safe memory insert. Returns memory_id as string.
    Mirrors the Supabase RPC behavior using ON CONFLICT on content_fingerprint.
    """
    fingerprint = _normalize_fingerprint(content)
    meta = Json(metadata) if metadata else Json({})

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memories (content, source, session_id, metadata, content_fingerprint)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (content_fingerprint) DO UPDATE
                  SET updated_at = now(),
                      metadata = memories.metadata || EXCLUDED.metadata
                RETURNING id::text
                """,
                (content, source, session_id, meta, fingerprint),
            )
            memory_id = cur.fetchone()[0]
            conn.commit()
            return memory_id


def insert_chunk(
    memory_id: str, content: str, qdrant_id: str, chunk_index: int = 0
) -> str:
    """Insert a chunk record. Returns chunk id."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chunks (memory_id, content, chunk_index, qdrant_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id::text
                """,
                (memory_id, content, chunk_index, qdrant_id),
            )
            chunk_id = cur.fetchone()[0]
            conn.commit()
            return chunk_id


def upsert_entity(
    memory_id: str,
    neo4j_node_id: str,
    label: str,
    name: str,
) -> None:
    """Insert or update an entity record. On conflict, update name."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO entities (memory_id, neo4j_node_id, label, name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (neo4j_node_id) DO UPDATE SET name = EXCLUDED.name
                """,
                (memory_id, neo4j_node_id, label, name),
            )
            conn.commit()


def get_memories(memory_ids: list[str]) -> dict[str, dict]:
    """Hydrate memory content from a list of memory_ids. Returns {id: {content, source, captured_at, metadata}}."""
    if not memory_ids:
        return {}
    # Use format for list of UUIDs
    placeholder = ",".join(["%s"] * len(memory_ids))
    rows = run_query(
        f"SELECT id, content, source, captured_at, metadata FROM memories WHERE id IN ({placeholder})",
        tuple(memory_ids),
    )
    return {str(row["id"]): row for row in rows}


def get_skill(skill_name: str) -> dict | None:
    """Get an active skill by name. Returns skill dict or None."""
    rows = run_query(
        "SELECT id, name, description, prompt_template FROM skills WHERE name = %s AND active = true",
        (skill_name,),
    )
    return rows[0] if rows else None


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
    """Insert a generation record. Returns generation_id as string."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO generations (skill_id, skill_name, output, model, machine, prompt_used, session_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id::text
                """,
                (
                    skill_id,
                    skill_name,
                    output,
                    model,
                    machine,
                    prompt_used,
                    session_id,
                    Json(metadata or {}),
                ),
            )
            generation_id = cur.fetchone()[0]
            conn.commit()
            return generation_id


def insert_evidence_batch(evidence_rows: list[dict]) -> None:
    """Bulk insert evidence rows."""
    if not evidence_rows:
        return
    with _get_conn() as conn:
        with conn.cursor() as cur:
            for row in evidence_rows:
                cur.execute(
                    """
                    INSERT INTO evidence (generation_id, memory_id, chunk_id, neo4j_node_id, relevance_score, retrieval_type, rank)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row["generation_id"],
                        row.get("memory_id"),
                        row.get("chunk_id"),
                        row.get("neo4j_node_id"),
                        row.get("relevance_score"),
                        row.get("retrieval_type", "vector"),
                        row.get("rank", 0),
                    ),
                )
            conn.commit()


def get_generation_receipt(p_generation_id: str) -> dict:
    """Return the full evidence receipt for a generation."""
    result = run_query(
        "SELECT get_generation_receipt(%s::uuid)",
        (p_generation_id,),
    )
    return result[0] if result else {}


def close() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
