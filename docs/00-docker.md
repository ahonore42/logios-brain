# Step 0: Docker and Environment Setup

This is the first thing you do after creating your service accounts in `docs/01-setup.md`. Everything else — schema migrations, the MCP server, backups — depends on these containers being up and healthy.

By the end of this doc you will have:
- Docker installed on your Hetzner VPS
- A working `.env` file with all credentials
- All three stores (PostgreSQL, Qdrant, Neo4j) running in Docker
- Verified that each container is healthy before proceeding

---

## 1. Install Docker on Hetzner

SSH into your VPS:

```bash
ssh your_user@YOUR_HETZNER_IP
```

Install Docker using the official convenience script:

```bash
curl -fsSL https://get.docker.com | sh
```

Add your user to the `docker` group so you can run Docker commands without `sudo`:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

Verify both Docker and Compose are working:

```bash
docker --version
docker compose version
```

Expected output (versions will vary):
```
Docker version 26.x.x, build ...
Docker Compose version v2.x.x
```

> If `docker compose version` fails, your Docker installation may be older and use the standalone `docker-compose` binary instead. Run `sudo apt install docker-compose-plugin` to get the modern plugin version.

---

## 2. Create the project directory

```bash
sudo mkdir -p /opt/logios-brain
sudo chown $USER:$USER /opt/logios-brain
cd /opt/logios-brain
```

Clone your repository here (or create the directory structure manually if you have not pushed to GitHub yet):

```bash
git clone https://github.com/YOUR_USERNAME/logios-brain.git .
```

Create the directories that are not tracked by git:

```bash
mkdir -p backups scripts
```

---

## 3. Create the `.env` file

This file holds every credential the system needs. It is read by Docker Compose (for the container environment variables) and by the FastAPI server (via `python-dotenv`).

Create it:

```bash
nano /opt/logios-brain/.env
```

Paste the full template below, then fill in every value:

```env
# ── PostgreSQL ─────────────────────────────────────────────────────────────
# Local Docker — no external account needed
# Generate with: openssl rand -hex 16
POSTGRES_USER=logios
POSTGRES_DB=logios_brain
POSTGRES_PASSWORD=

# Connection string used by the FastAPI server
DATABASE_URL=postgresql://logios:PASTE_POSTGRES_PASSWORD_HERE@localhost:5432/logios_brain

# ── Qdrant ─────────────────────────────────────────────────────────────────
# Local Docker — no API key needed
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=

# ── Neo4j ──────────────────────────────────────────────────────────────────
# Local Docker
# Generate with: openssl rand -hex 16
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=

# ── Gemini API ─────────────────────────────────────────────────────────────
# Free tier — get from aistudio.google.com
GEMINI_API_KEY=

# ── MCP Server ─────────────────────────────────────────────────────────────
# Used by every AI client to authenticate to the server
# Generate with: openssl rand -hex 32
MCP_ACCESS_KEY=

# Server bind port — 8000 is fine unless something else is already using it
SERVER_PORT=8000

# ── Ollama (entity extraction) ─────────────────────────────────────────────
# Points to your local machine if running Ollama locally there,
# or http://localhost:11434 if running Ollama on Hetzner
OLLAMA_URL=http://YOUR_LOCAL_IP:11434
ENTITY_MODEL=mistral:7b
```

Generate the three random values now (run each separately, paste the output into `.env`):

```bash
# POSTGRES_PASSWORD
openssl rand -hex 16

# NEO4J_PASSWORD
openssl rand -hex 16

# MCP_ACCESS_KEY
openssl rand -hex 32
```

After filling in `POSTGRES_PASSWORD`, also update the `DATABASE_URL` line — it needs to contain the same password inline:

```
DATABASE_URL=postgresql://logios:YOUR_ACTUAL_PASSWORD@localhost:5432/logios_brain
```

Save and exit (`Ctrl+X`, `Y`, `Enter` in nano).

Lock down the file permissions — only your user should be able to read it:

```bash
chmod 600 /opt/logios-brain/.env
```

Verify it looks right:

```bash
cat /opt/logios-brain/.env
```

---

## 4. Create the Docker Compose file

Create `/opt/logios-brain/docker-compose.yml`:

```bash
nano /opt/logios-brain/docker-compose.yml
```

Paste the full configuration:

```yaml
services:

  postgres:
    image: pgvector/pgvector:pg16
    container_name: logios-postgres
    restart: unless-stopped
    env_file:
      - .env
    environment:
      POSTGRES_USER:     ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB:       ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5

  qdrant:
    image: qdrant/qdrant:latest
    container_name: logios-qdrant
    restart: unless-stopped
    volumes:
      - qdrant_data:/qdrant/storage
    ports:
      - "127.0.0.1:6333:6333"
      - "127.0.0.1:6334:6334"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:6333/healthz || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5

  neo4j:
    image: neo4j:5-community
    container_name: logios-neo4j
    restart: unless-stopped
    env_file:
      - .env
    environment:
      NEO4J_AUTH:                           neo4j/${NEO4J_PASSWORD}
      NEO4J_PLUGINS:                        '["apoc"]'
      NEO4J_dbms_memory_heap_initial__size: 512m
      NEO4J_dbms_memory_heap_max__size:     2g
      NEO4J_dbms_memory_pagecache_size:     1g
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    ports:
      - "127.0.0.1:7474:7474"
      - "127.0.0.1:7687:7687"
    healthcheck:
      test: ["CMD-SHELL", "cypher-shell -u neo4j -p ${NEO4J_PASSWORD} 'RETURN 1' || exit 1"]
      interval: 15s
      timeout: 10s
      retries: 10

volumes:
  postgres_data:
  qdrant_data:
  neo4j_data:
  neo4j_logs:
```

Save and exit.

### Notes on this configuration

**Ports are bound to `127.0.0.1`** on every service. This means PostgreSQL (5432), Qdrant (6333/6334), and Neo4j (7474/7687) are not accessible from outside the VPS. Only the FastAPI server — running on the same machine — can reach them. This is the correct security posture. Your MCP clients connect to the FastAPI server only, never to the databases directly.

**`restart: unless-stopped`** means Docker will restart all three containers if the VPS reboots, as long as you started them with `docker compose up -d` at least once. You do not need a separate systemd service for the containers.

**Neo4j heap settings** (`512m` initial, `2g` max, `1g` page cache) are calibrated for your 16GB CX43. Neo4j's JVM will consume up to approximately 3GB under load. Adjust these upward if you want to give Neo4j more room, or downward if you add other services to the VPS later.

**`NEO4J_PLUGINS: '["apoc"]'`** installs the APOC plugin on first start by downloading it from the internet. The first startup takes longer than subsequent ones. If your VPS is in a region with restricted outbound access, this may fail — check Neo4j's logs if the container does not reach healthy status.

**`pgvector/pgvector:pg16`** is the official pgvector image. It bundles PostgreSQL 16 with the vector extension pre-installed. The extension still needs to be enabled per database (done in Migration 001).

---

## 5. Start the containers

```bash
cd /opt/logios-brain
docker compose up -d
```

This pulls all three images on first run. Expect 1–3 minutes depending on your VPS network speed.

Watch the startup:

```bash
docker compose logs -f
```

Press `Ctrl+C` to stop following logs once things settle. The containers keep running in the background.

---

## 6. Verify all three are healthy

```bash
docker compose ps
```

Expected output (all three should show `healthy`):

```
NAME                IMAGE                    STATUS
logios-neo4j        neo4j:5-community        Up 2 minutes (healthy)
logios-postgres     pgvector/pgvector:pg16   Up 2 minutes (healthy)
logios-qdrant       qdrant/qdrant:latest     Up 2 minutes (healthy)
```

If any service shows `starting` instead of `healthy`, wait another 30 seconds and run `docker compose ps` again. Neo4j is the slowest — on first start it may take 2–3 minutes to reach healthy while APOC downloads and installs.

If a service shows `unhealthy` or keeps restarting, check its logs:

```bash
docker compose logs neo4j     # or postgres, qdrant
```

---

## 7. Verify each store is reachable

### PostgreSQL

```bash
docker exec logios-postgres psql -U logios -d logios_brain -c "SELECT version();"
```

Expected: a line containing `PostgreSQL 16.x`.

### Qdrant

```bash
curl http://localhost:6333/
```

Expected: a JSON response containing `"title": "qdrant"` and a version string.

### Neo4j

```bash
docker exec logios-neo4j cypher-shell \
  -u neo4j \
  -p YOUR_NEO4J_PASSWORD \
  "RETURN 'Neo4j is up' AS status;"
```

Expected:
```
status
"Neo4j is up"
```

---

## 8. Common startup issues

**Neo4j stays in `starting` for more than 5 minutes:**
APOC may have failed to download. Check the logs:
```bash
docker compose logs neo4j | grep -i "apoc\|error\|fail"
```
If APOC failed, try removing the plugin line temporarily to get Neo4j running, then add it back:
```yaml
# Comment out for initial test:
# NEO4J_PLUGINS: '["apoc"]'
```

**PostgreSQL healthcheck fails immediately:**
Usually a password mismatch. Confirm `POSTGRES_PASSWORD` in `.env` matches the value in `DATABASE_URL`. If you change `.env` after first start, the password in the Docker volume is already set — you either need to change it via `ALTER USER` inside psql or wipe the volume and start fresh:
```bash
docker compose down -v   # WARNING: deletes all data
docker compose up -d
```

**Port already in use:**
If something on your VPS is already listening on 5432, 6333, or 7687, the container will fail to bind. Check:
```bash
sudo ss -tlnp | grep -E '5432|6333|7687'
```
If a conflict exists, either stop the conflicting service or change the host port in `docker-compose.yml` (the left side of the colon in the ports mapping).

---

## 9. Useful Docker commands

```bash
# Start all services
docker compose up -d

# Stop all services (containers stop, data is preserved)
docker compose down

# Stop and delete all data volumes (irreversible)
docker compose down -v

# Restart a single service
docker compose restart neo4j

# View logs for one service (follow mode)
docker compose logs -f postgres

# Open a shell inside a container
docker exec -it logios-postgres bash
docker exec -it logios-neo4j bash

# Open psql directly
docker exec -it logios-postgres psql -U logios -d logios_brain

# Check resource usage
docker stats
```

---

## 10. Auto-start on VPS reboot

Because all containers use `restart: unless-stopped`, they will restart automatically after a reboot as long as the Docker daemon itself starts on boot. Verify Docker is set to start on boot:

```bash
sudo systemctl is-enabled docker
```

Expected: `enabled`. If it shows `disabled`:

```bash
sudo systemctl enable docker
```

Test the full reboot cycle if you want to be sure:

```bash
sudo reboot
# Wait 60 seconds, then SSH back in
ssh your_user@YOUR_HETZNER_IP
docker compose -f /opt/logios-brain/docker-compose.yml ps
```

All three containers should be healthy within 2–3 minutes of boot.

---

## Checkpoint

Before moving to schema setup, confirm all of the following:

- [ ] Docker and Docker Compose are installed
- [ ] `/opt/logios-brain/.env` exists, has `chmod 600`, and all values are filled in
- [ ] `/opt/logios-brain/docker-compose.yml` exists
- [ ] `docker compose ps` shows all three services as `healthy`
- [ ] PostgreSQL responds to `psql`
- [ ] Qdrant responds to `curl http://localhost:6333/`
- [ ] Neo4j responds to `cypher-shell`

**Do not proceed to [Step 2: Schema](02-schema.md) until every item above is checked.**