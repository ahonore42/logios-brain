# Step 10: Backups

All three stores run locally in Docker on your Hetzner VPS. Each has a different backup mechanism. This doc covers manual backup commands, the automated backup script, scheduling, and the full procedure for migrating to a new server.

---

## What needs backing up

| Store | Data | Backup method |
|---|---|---|
| PostgreSQL | All memories, chunks, entities, skills, generations, evidence | `pg_dump` — standard, portable |
| Qdrant | Embedding vectors and payloads | Native snapshot API |
| Neo4j | Knowledge graph nodes and relationships | `neo4j-admin database dump` — requires stop |

Your `.env` file also needs to be preserved — without it you cannot connect to anything. Back it up separately and keep it off the VPS (a password manager or encrypted local file works).

---

## Manual backup commands

### PostgreSQL

PostgreSQL can be backed up while running — no downtime required.

```bash
# Create the dump inside the container
docker exec logios-postgres pg_dump \
  -U logios \
  -d logios_brain \
  --format=custom \
  --file=/tmp/logios_brain.dump

# Copy it out to the host
docker cp logios-postgres:/tmp/logios_brain.dump \
  /opt/logios-brain/backups/postgres_$(date +%Y%m%d_%H%M%S).dump

# Clean up the temp file inside the container
docker exec logios-postgres rm /tmp/logios_brain.dump
```

`--format=custom` produces a compressed binary. It is smaller than plain SQL and supports selective restore. Restore with `pg_restore`, not `psql`.

### Qdrant

Qdrant can be snapshotted while running — no downtime required.

```bash
# Trigger a snapshot
SNAP_RESPONSE=$(curl -s -X POST http://localhost:6333/collections/memories/snapshots)

# Extract the snapshot filename from the response
SNAP_NAME=$(echo "$SNAP_RESPONSE" | python3 -c \
  "import sys, json; print(json.load(sys.stdin)['result']['name'])")

# Wait a moment for Qdrant to finish writing the file
sleep 5

# Copy it out of the container
docker cp "logios-qdrant:/qdrant/snapshots/memories/${SNAP_NAME}" \
  "/opt/logios-brain/backups/qdrant_$(date +%Y%m%d_%H%M%S).snapshot"
```

List existing snapshots at any time:
```bash
curl http://localhost:6333/collections/memories/snapshots
```

### Neo4j

Neo4j **must be stopped** before dumping. The `neo4j-admin dump` command refuses to run against a live database.

```bash
# Stop Neo4j
docker compose -f /opt/logios-brain/docker-compose.yml stop neo4j

# Dump
docker exec logios-neo4j neo4j-admin database dump \
  --to-path=/tmp \
  neo4j

# Copy out
docker cp logios-neo4j:/tmp/neo4j.dump \
  /opt/logios-brain/backups/neo4j_$(date +%Y%m%d_%H%M%S).dump

# Clean up and restart
docker exec logios-neo4j rm /tmp/neo4j.dump
docker compose -f /opt/logios-brain/docker-compose.yml start neo4j
```

Neo4j is typically down for 30–60 seconds during this process. Your MCP server will return errors during that window — this is expected. It reconnects automatically once Neo4j is back.

---

## Automated backup script

Create this file at `/opt/logios-brain/scripts/backup.sh`:

```bash
#!/bin/bash
# backup.sh — backs up all three stores to /opt/logios-brain/backups/
# Safe to run from cron. Neo4j will be briefly unavailable during its dump.

set -euo pipefail

BACKUP_DIR="/opt/logios-brain/backups"
COMPOSE="/opt/logios-brain/docker-compose.yml"
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
  -d logios_brain \
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
```

Make it executable:

```bash
chmod +x /opt/logios-brain/scripts/backup.sh
```

Test it manually before scheduling:

```bash
/opt/logios-brain/scripts/backup.sh
ls -lh /opt/logios-brain/backups/
```

You should see three files — one `.dump` for Postgres, one `.snapshot` for Qdrant, one `.dump` for Neo4j.

---

## Scheduling with cron

Run the backup daily at 3am:

```bash
crontab -e
```

Add this line:

```
0 3 * * * /opt/logios-brain/scripts/backup.sh >> /opt/logios-brain/backups/cron.log 2>&1
```

The `>> cron.log 2>&1` redirects both stdout and stderr to a log file separate from `backup.log`, so you can see exactly what cron ran and when.

Verify the cron job is registered:

```bash
crontab -l
```

---

## Verifying backups

Check that recent backup files exist and are not empty:

```bash
ls -lh /opt/logios-brain/backups/ | tail -20
```

Verify the Postgres dump is readable:

```bash
docker exec logios-postgres pg_restore \
  --list /tmp/logios_brain.dump 2>/dev/null | head -20

# Or check the file size — a valid dump of even a small database
# will be at least a few KB
du -sh /opt/logios-brain/backups/postgres_*.dump | tail -5
```

Verify the Qdrant snapshot is accessible:

```bash
curl http://localhost:6333/collections/memories/snapshots
```

---

## Offsite backup

Keeping backups on the same VPS as the data is better than nothing but does not protect against Hetzner losing the server. Consider syncing your backup directory to an offsite location.

**Option A — rsync to another machine:**

```bash
# Add to crontab, runs after the main backup
30 3 * * * rsync -avz /opt/logios-brain/backups/ \
  your_user@offsite_host:/backups/logios-brain/ \
  >> /opt/logios-brain/backups/rsync.log 2>&1
```

**Option B — Hetzner Storage Box:**

Hetzner offers Storage Boxes starting at €1.37/month for 100GB, accessible via rsync, SFTP, or SMB. Straightforward if you are already on Hetzner.

```bash
rsync -avz /opt/logios-brain/backups/ \
  your-storage-box.your-server.de::backup/logios-brain/
```

**Option C — rclone to S3-compatible storage:**

```bash
# Install rclone, configure a remote, then:
rclone sync /opt/logios-brain/backups/ remote:logios-brain-backups/
```

Cloudflare R2 has a generous free tier (10GB, no egress fees) and works with rclone's S3 driver.

---

## Restore procedures

### PostgreSQL restore

```bash
# Copy the backup file into the container
docker cp /opt/logios-brain/backups/postgres_YYYYMMDD_HHMMSS.dump \
  logios-postgres:/tmp/logios_brain.dump

# Restore — --clean drops existing objects before recreating them
docker exec logios-postgres pg_restore \
  -U logios \
  -d logios_brain \
  --clean \
  --if-exists \
  /tmp/logios_brain.dump

# Clean up
docker exec logios-postgres rm /tmp/logios_brain.dump
```

> If restoring to a brand new database, create it first:
> ```bash
> docker exec logios-postgres createdb -U logios logios_brain
> ```
> Then enable the `vector` extension before restoring:
> ```bash
> docker exec logios-postgres psql -U logios -d logios_brain \
>   -c "create extension if not exists vector;"
> ```

### Qdrant restore

```bash
# Upload the snapshot file to the running Qdrant instance
curl -X POST "http://localhost:6333/collections/memories/snapshots/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "snapshot=@/opt/logios-brain/backups/qdrant_YYYYMMDD_HHMMSS.snapshot"
```

If the collection already exists, Qdrant will overwrite it with the snapshot contents.

If the collection does not exist yet (fresh server), create it first by starting your MCP server once — `ensure_collection()` will create it — then upload the snapshot.

### Neo4j restore

```bash
# Stop Neo4j
docker compose -f /opt/logios-brain/docker-compose.yml stop neo4j

# Copy the backup into the container
docker cp /opt/logios-brain/backups/neo4j_YYYYMMDD_HHMMSS.dump \
  logios-neo4j:/tmp/neo4j.dump

# Load — overwrites the existing database
docker exec logios-neo4j neo4j-admin database load \
  --from-path=/tmp \
  --overwrite-destination \
  neo4j

# Clean up and restart
docker exec logios-neo4j rm /tmp/neo4j.dump
docker compose -f /opt/logios-brain/docker-compose.yml start neo4j
```

---

## Full server migration

Use this procedure when moving to a new Hetzner server.

**On the old server:**

```bash
# Run a fresh backup
/opt/logios-brain/scripts/backup.sh

# Verify
ls -lh /opt/logios-brain/backups/
```

**On the new server:**

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Clone the repo
sudo mkdir -p /opt/logios-brain
sudo chown $USER:$USER /opt/logios-brain
cd /opt/logios-brain
git clone https://github.com/YOUR_USERNAME/logios-brain.git .

# Copy .env from old server (or recreate from your credential file)
scp old_user@OLD_SERVER_IP:/opt/logios-brain/.env /opt/logios-brain/.env
chmod 600 /opt/logios-brain/.env

# Start services
docker compose up -d

# Wait for all three to be healthy
docker compose ps

# Copy backups from old server
rsync -avz old_user@OLD_SERVER_IP:/opt/logios-brain/backups/ \
  /opt/logios-brain/backups/
```

**Restore each store** using the procedures above (PostgreSQL, then Qdrant, then Neo4j).

**Deploy and verify the FastAPI server:**

```bash
cd /opt/logios-brain/server
python3 -m venv /opt/logios-brain/venv
source /opt/logios-brain/venv/bin/activate
pip install -r requirements.txt

sudo systemctl daemon-reload
sudo systemctl enable logios-brain
sudo systemctl start logios-brain

python3 /opt/logios-brain/scripts/test_connection.py
```

**Update MCP client configs** on your local machines if the Hetzner IP has changed.

The full migration should take under 30 minutes for a personal knowledge base that has been running for months.