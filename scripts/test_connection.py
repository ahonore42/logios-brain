"""
scripts/test_connection.py

Verifies connectivity to all three stores and the embedding API.
Run from the Hetzner VPS after deployment:

  cd /opt/logios-brain
  source venv/bin/activate
  python3 scripts/test_connection.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from dotenv import load_dotenv

load_dotenv("/opt/logios-brain/.env")

results = {}


def check(name: str, fn):
    try:
        fn()
        results[name] = "OK"
        print(f"  ✓  {name}")
    except Exception as e:
        results[name] = f"FAILED: {e}"
        print(f"  ✗  {name}: {e}")


print("\nLogios Brain — Connection Test\n")


# Supabase
def test_supabase():
    from db.supabase import get_supabase

    sb = get_supabase()
    sb.table("memories").select("id").limit(1).execute()


check("Supabase", test_supabase)


# Qdrant
def test_qdrant():
    from db.qdrant import get_qdrant, ensure_collection

    ensure_collection()
    client = get_qdrant()
    info = client.get_collection("memories")
    assert info.status is not None


check("Qdrant", test_qdrant)


# Neo4j
def test_neo4j():
    from db.neo4j_client import run_query

    result = run_query("RETURN 1 as n")
    assert result[0]["n"] == 1


check("Neo4j", test_neo4j)


# Gemini embeddings
def test_embeddings():
    from embeddings import embed

    vector = embed("Connection test")
    assert len(vector) == 3072


check("Gemini embeddings", test_embeddings)


# Full write path
def test_write_path():
    from tools.remember import remember

    result = remember(
        content="Connection test write — safe to delete",
        source="manual",
        metadata={"test": True},
    )
    assert "memory_id" in result


check("Full write path (remember)", test_write_path)


# Summary
print()
failed = [k for k, v in results.items() if v != "OK"]
if not failed:
    print("All checks passed. Logios Brain is ready.\n")
else:
    print(f"{len(failed)} check(s) failed: {', '.join(failed)}")
    print("Check your .env credentials and service status.\n")
    sys.exit(1)
