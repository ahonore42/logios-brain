"""Environment variable resolver. Single source of truth for which store is active."""

import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

USE_LOCAL_STORES = os.getenv("USE_LOCAL_STORES", "true").lower() == "true"
USE_SUPABASE = os.getenv("USE_SUPABASE", "false").lower() == "true"

# ── PostgreSQL ───────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── Supabase ─────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# ── Qdrant ───────────────────────────────────────────────────────────────────
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "") or None

# ── Neo4j ─────────────────────────────────────────────────────────────────────
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# ── Tenant ────────────────────────────────────────────────────────────────────
# Single-tenant for now. Multi-tenant support deferred.
TENANT_ID = os.getenv("TENANT_ID", "default")

# ── Embeddings (NVIDIA NIM) ───────────────────────────────────────────────────
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
EMBEDDING_MODEL = "nvidia/nv-embed-v1"
EMBEDDING_DIM = 4096

# ── MCP Server ───────────────────────────────────────────────────────────────
MCP_ACCESS_KEY = os.getenv("MCP_ACCESS_KEY", "")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
