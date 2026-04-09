# Step 4: Neo4j

Neo4j is the reasoner in your stack. It holds the knowledge graph — entities, concepts, people, projects, and the typed relationships between them. Every node links back to a `memory_id` in PostgreSQL, keeping the graph anchored to the source of truth.

Neo4j runs locally on your Hetzner VPS in Docker as part of your Compose stack. With 16GB RAM you have substantial headroom to give it a generous heap.

---

## What lives in Neo4j

| Node label | What it represents | Example |
|---|---|---|
| `Project` | Active or past projects | Logios Brain |
| `Concept` | Ideas, techniques, frameworks | MCP protocol, vector search, evidence layer |
| `Person` | People you interact with | Names from captured memories |
| `Session` | A discrete working session | A conversation, a build session |
| `Event` | Meetings, calls, milestones | Client call, launch, decision point |
| `Decision` | Recorded decisions | "Chose Neo4j over pgvector for graph queries" |
| `Tool` | Software and services | FastAPI, Qdrant, PostgreSQL |
| `Location` | Physical or virtual places | Hetzner, Seattle |

Relationships are typed:
- `RELATES_TO` — general semantic connection
- `PART_OF` — containment (Concept is PART_OF Project)
- `CREATED_BY` — authorship
- `MENTIONS` — a memory mentions an entity
- `CAUSED_BY` — causal chain
- `DEPENDS_ON` — dependency

---

## Docker Compose configuration

This block belongs in your `/opt/logios-brain/docker-compose.yml`. It is included here for reference — the full Compose file is in `docs/03-mcp-server.md`.

```yaml
neo4j:
  image: neo4j:5-community
  container_name: logios-neo4j
  restart: unless-stopped
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
    - "127.0.0.1:7474:7474"   # Browser UI — localhost only
    - "127.0.0.1:7687:7687"   # Bolt protocol — localhost only
  healthcheck:
    test: ["CMD-SHELL", "cypher-shell -u neo4j -p ${NEO4J_PASSWORD} 'RETURN 1' || exit 1"]
    interval: 15s
    timeout: 10s
    retries: 10
```

The heap settings (`512m` initial, `2g` max, `1g` page cache) are appropriate for a CX43 with 16GB RAM. Neo4j's JVM will use up to `2g` for the heap plus `1g` for the page cache — roughly 3GB total under load, well within your budget.

The `NEO4J_PLUGINS: '["apoc"]'` line installs the APOC plugin automatically on first start. APOC is used for subgraph traversal queries. The first startup takes longer than usual while it downloads.

**Ports are bound to `127.0.0.1` only.** Neo4j is not accessible from outside the VPS. If you want to access the Browser UI from your local machine, use an SSH tunnel (see below).

---

## `.env` additions

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=generate_with_openssl_rand_hex_16
```

Generate the password:
```bash
openssl rand -hex 16
```

---

## Starting Neo4j

```bash
cd /opt/logios-brain
docker compose up -d neo4j
docker compose logs -f neo4j
```

Wait until the logs show `Started.` — Neo4j takes 30–60 seconds on first start, longer if downloading APOC. Once healthy:

```bash
docker compose ps   # neo4j should show "healthy"
```

---

## Accessing the Neo4j Browser

The Browser UI is the web-based Cypher console where you will run schema setup queries. Since the port is bound to localhost only, access it via SSH tunnel from your local machine:

```bash
# Run this on your local machine
ssh -L 7474:localhost:7474 -L 7687:localhost:7687 your_user@YOUR_HETZNER_IP -N
```

Then open `http://localhost:7474` in your browser.

Connect with:
- **Connect URL:** `bolt://localhost:7687`
- **Username:** `neo4j`
- **Password:** your `NEO4J_PASSWORD` from `.env`

---

## Schema setup in Cypher

Run these in the Neo4j Browser, one block at a time.

### Constraints

```cypher
CREATE CONSTRAINT project_name IF NOT EXISTS
FOR (n:Project) REQUIRE n.name IS UNIQUE;

CREATE CONSTRAINT concept_name IF NOT EXISTS
FOR (n:Concept) REQUIRE n.name IS UNIQUE;

CREATE CONSTRAINT person_name IF NOT EXISTS
FOR (n:Person) REQUIRE n.name IS UNIQUE;

CREATE CONSTRAINT tool_name IF NOT EXISTS
FOR (n:Tool) REQUIRE n.name IS UNIQUE;

CREATE CONSTRAINT location_name IF NOT EXISTS
FOR (n:Location) REQUIRE n.name IS UNIQUE;

CREATE CONSTRAINT decision_name IF NOT EXISTS
FOR (n:Decision) REQUIRE n.name IS UNIQUE;
```

### Indexes

```cypher
CREATE INDEX entity_memory_id IF NOT EXISTS
FOR (n:Project) ON (n.memory_id);

CREATE INDEX entity_created_at IF NOT EXISTS
FOR (n:Project) ON (n.created_at);

CREATE FULLTEXT INDEX entity_name_search IF NOT EXISTS
FOR (n:Project|Concept|Person|Tool|Location|Decision|Event|Session)
ON EACH [n.name];
```

### Verify

```cypher
SHOW CONSTRAINTS;
SHOW INDEXES;
```

---

## Seed a test node

```cypher
MERGE (p:Project {name: "Logios Brain"})
ON CREATE SET
  p.created_at  = datetime(),
  p.description = "Personal AI memory infrastructure",
  p.status      = "active"
RETURN p;

// Confirm
MATCH (p:Project {name: "Logios Brain"}) RETURN p;
```

---

## Example graph queries

These are the kinds of queries your MCP server will run. Run them manually in the Browser to explore your graph as it grows.

```cypher
// Find everything connected to a project
MATCH (p:Project {name: "Logios Brain"})-[r]-(connected)
RETURN p, r, connected
LIMIT 50;

// Find all concepts across memories
MATCH (c:Concept)
RETURN c.name, c.memory_id, c.created_at
ORDER BY c.created_at DESC
LIMIT 20;

// Trace the provenance chain for a concept
MATCH path = (c:Concept {name: "evidence layer"})-[*1..3]-(other)
RETURN path
LIMIT 20;

// Find most-mentioned concepts
MATCH (m)-[r:MENTIONS]->(c:Concept)
RETURN c.name, count(r) AS mention_count
ORDER BY mention_count DESC
LIMIT 20;

// Find nodes created in the last 5 minutes (useful during testing)
MATCH (n)
WHERE n.created_at > datetime() - duration('PT5M')
RETURN n LIMIT 20;
```

---

## Backup and export

Neo4j must be stopped before dumping. The automated backup script in `scripts/backup.sh` handles this automatically. For a manual export:

```bash
# Stop Neo4j
docker compose stop neo4j

# Dump
docker exec logios-neo4j neo4j-admin database dump \
  --to-path=/tmp \
  neo4j

# Copy out
docker cp logios-neo4j:/tmp/neo4j.dump \
  /opt/logios-brain/backups/neo4j_$(date +%Y%m%d).dump

# Restart
docker compose start neo4j
```

Restore on a new server:

```bash
docker compose stop neo4j

docker cp /path/to/neo4j.dump logios-neo4j:/tmp/neo4j.dump

docker exec logios-neo4j neo4j-admin database load \
  --from-path=/tmp \
  --overwrite-destination \
  neo4j

docker compose start neo4j
```

---

## Alternative: Neo4j AuraDB (cloud-hosted)

If you prefer not to run Neo4j in Docker, AuraDB is Neo4j's managed cloud service. The free tier gives you one instance with 200MB storage and 200K nodes.

### Setup

1. Go to [neo4j.com/cloud/aura](https://neo4j.com/cloud/aura) and sign up
2. Click **Create a free instance**, name it `logios-brain`
3. Download the credentials file immediately — the password is only shown once
4. Once running, open the **Neo4j Browser** from the AuraDB dashboard
5. Run the same Cypher schema blocks above in that browser

### `.env` changes

```env
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=from_the_downloaded_credentials_file
```

The URI scheme changes from `bolt://` (local, no TLS) to `neo4j+s://` (AuraDB, TLS required). No other code changes are needed — the Neo4j Python driver handles both.

### Remove Neo4j from Docker Compose

If using AuraDB, remove the `neo4j` service block from `docker-compose.yml` and the `neo4j_data` / `neo4j_logs` volumes.

### Trade-offs

| | Local Docker | AuraDB Free |
|---|---|---|
| Cost | $0 (your existing VPS) | $0 |
| Node limit | Unlimited | 200K |
| Availability | Continuous | Pauses after 3 days inactivity |
| RAM usage | ~3GB under load | None on your VPS |
| Backup | `neo4j-admin dump` | Console download |
| Browser UI | Via SSH tunnel | Direct web access |

**AuraDB pause behavior:** The free instance pauses after 3 days without a connection. Your server will get a connection error when it tries to connect to a paused instance. You must log into the AuraDB console and click **Resume**. To work around this, add a cron job that pings Neo4j every 48 hours:

```bash
# /opt/logios-brain/scripts/ping_neo4j.sh
#!/bin/bash
source /opt/logios-brain/.env
python3 -c "
from neo4j import GraphDatabase
driver = GraphDatabase.driver('$NEO4J_URI', auth=('$NEO4J_USERNAME', '$NEO4J_PASSWORD'))
with driver.session() as s:
    s.run('RETURN 1')
driver.close()
print('Neo4j ping ok')
"
```

```bash
chmod +x /opt/logios-brain/scripts/ping_neo4j.sh
# Add to crontab:
# 0 */48 * * * /opt/logios-brain/scripts/ping_neo4j.sh
```

For a system intended to run continuously and accumulate a large graph over time, the local Docker setup is the better choice. AuraDB makes sense if you want to skip the SSH tunnel for browser access and are comfortable with the pause behavior and 200K node ceiling.

---

**Next: [Qdrant Setup](05-qdrant.md)**