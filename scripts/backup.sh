#!/bin/bash
# backup.sh — backs up all three stores to $HOME/logios-brain/backups/
# Safe to run from cron. Neo4j will be briefly unavailable during its dump.

set -euo pipefail

BACKUP_DIR="$HOME/logios-brain/backups"
COMPOSE="$HOME/logios-brain/docker-compose.yml"

# Load env vars from .env (for POSTGRES_DB)
set -a
source "$HOME/logios-brain/.env" 2>/dev/null || true
set +a
DATE=$(date +%Y%m%d_%H%M%S)
LOG="${BACKUP_DIR}/backup.log"

mkdir -p "$BACKUP_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"
}

log "Starting backup (${DATE})"

# ── PostgreSQL ─────────────────────────────────────────────────────────────
log "PostgreSQL: dumping..."

docker exec logios-postgres pg_dump \
  -U logios \
  -d "${POSTGRES_DB}" \
  --format=custom \
  --file=/tmp/logios_brain.dump

docker cp logios-postgres:/tmp/logios_brain.dump \
  "${BACKUP_DIR}/postgres_${DATE}.dump"

docker exec logios-postgres rm /tmp/logios_brain.dump

log "PostgreSQL: done → postgres_${DATE}.dump"

# ── Qdrant ─────────────────────────────────────────────────────────────────
log "Qdrant: creating snapshot..."

SNAP_RESPONSE=$(curl -sf -X POST http://localhost:6333/collections/memories/snapshots)
SNAP_NAME=$(echo "$SNAP_RESPONSE" | python3 -c \
  "import sys, json; print(json.load(sys.stdin)['result']['name'])")

sleep 5

docker cp "logios-qdrant:/qdrant/snapshots/memories/${SNAP_NAME}" \
  "${BACKUP_DIR}/qdrant_${DATE}.snapshot"

log "Qdrant: done → qdrant_${DATE}.snapshot"

# ── Neo4j ──────────────────────────────────────────────────────────────────
log "Neo4j: stopping for dump..."

docker compose -f "$COMPOSE" stop neo4j

docker exec logios-neo4j neo4j-admin database dump \
  --to-path=/tmp \
  neo4j

docker cp logios-neo4j:/tmp/neo4j.dump \
  "${BACKUP_DIR}/neo4j_${DATE}.dump"

docker exec logios-neo4j rm -f /tmp/neo4j.dump

docker compose -f "$COMPOSE" start neo4j

log "Neo4j: done → neo4j_${DATE}.dump (restarting)"

# ── Prune old backups ──────────────────────────────────────────────────────
log "Pruning backups older than 14 days..."

find "$BACKUP_DIR" -name "postgres_*.dump"    -mtime +14 -delete
find "$BACKUP_DIR" -name "qdrant_*.snapshot"  -mtime +14 -delete
find "$BACKUP_DIR" -name "neo4j_*.dump"       -mtime +14 -delete

log "Backup complete."