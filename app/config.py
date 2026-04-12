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

# ── Redis (Celery broker) ────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── Neo4j ─────────────────────────────────────────────────────────────────────
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# ── Embeddings (NVIDIA NIM) ───────────────────────────────────────────────────
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "nvidia")  # nvidia | openai | anthropic | gemini
EMBEDDING_URL = os.getenv("EMBEDDING_URL", "https://integrate.api.nvidia.com/v1/embeddings")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nvidia/nv-embed-v1")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "4096"))

# ── Entity extraction (LLM completion) ───────────────────────────────────────
ENTITY_COMPLETION_URL = os.getenv("ENTITY_COMPLETION_URL", "https://integrate.api.nvidia.com/v1/chat/completions")
ENTITY_MODEL = os.getenv("ENTITY_MODEL", "microsoft/phi-3-mini-128k-instruct")

# ── Email (OTP delivery) ───────────────────────────────────────────────────────
EMAILS_ENABLED = os.getenv("EMAILS_ENABLED", "false").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_TLS = os.getenv("SMTP_TLS", "true").lower() == "true"
SMTP_SSL = os.getenv("SMTP_SSL", "false").lower() == "true"
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAILS_FROM_NAME = os.getenv("EMAILS_FROM_NAME", "Logios Brain")
EMAILS_FROM_EMAIL = os.getenv("EMAILS_FROM_EMAIL", "noreply@logios.local")
EMAIL_OTP_EXPIRE_MINUTES = int(os.getenv("EMAIL_OTP_EXPIRE_MINUTES", "10"))

# ── Logios Brain Auth ───────────────────────────────────────────────────────────
# Deployer secret — protects initial owner account creation. Only the person
# with access to the server environment can set up the first owner.
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable must be set")

# JWT signing key — must be set in environment, 32+ bytes recommended
ACCESS_SECRET_KEY = os.getenv("ACCESS_SECRET_KEY", "")
if not ACCESS_SECRET_KEY:
    raise RuntimeError("ACCESS_SECRET_KEY environment variable must be set")

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
