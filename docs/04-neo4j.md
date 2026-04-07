# Step 4: Neo4j AuraDB

Neo4j is the reasoner in your stack. It holds the knowledge graph — entities, concepts, people, projects, and the relationships between them. Every node links back to a `memory_id` in Supabase, keeping the graph anchored to the source of truth.

---

## What lives in Neo4j

| Node label | What it represents | Example |
|---|---|---|
| `Project` | Active or past projects | Logios Brain, Subtrack, Exo |
| `Concept` | Ideas, techniques, frameworks | MCP protocol, vector search, evidence layer |
| `Person` | People you interact with | names from captured memories |
| `Session` | A discrete working session | a conversation, a build session |
| `Event` | Meetings, calls, milestones | client call, launch, decision point |
| `Decision` | Recorded decisions | "chose Neo4j over pgvector for graph queries" |
| `Tool` | Software and services | FastAPI, Qdrant, Supabase |
| `Location` | Physical or virtual places | Hetzner, AuraDB, Seattle |

Relationships are typed:
- `RELATES_TO` — general semantic connection
- `PART_OF` — containment (Concept is PART_OF Project)
- `CREATED_BY` — authorship
- `MENTIONS` — a memory mentions an entity
- `CAUSED_BY` — causal chain
- `DEPENDS_ON` — dependency

---

## Connecting to AuraDB

Once your AuraDB instance is running, open the **Neo4j Browser** from the AuraDB dashboard. This is a web-based Cypher console. Run all the setup queries below in this browser.

Your connection credentials are in your `.env` file from step 1.

---

## Schema setup in Cypher

Run these in the Neo4j Browser, one block at a time.

### Constraints (uniqueness + indexes)

```cypher
// Ensure each entity label has a unique name constraint
// This enables MERGE to find existing nodes reliably

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

### Indexes for common query patterns

```cypher
// Index on memory_id so you can quickly find all nodes from one memory
CREATE INDEX entity_memory_id IF NOT EXISTS
FOR (n:Project) ON (n.memory_id);

CREATE INDEX entity_created_at IF NOT EXISTS
FOR (n:Project) ON (n.created_at);

// Full text search index across all node names
CREATE FULLTEXT INDEX entity_name_search IF NOT EXISTS
FOR (n:Project|Concept|Person|Tool|Location|Decision|Event|Session)
ON EACH [n.name];
```

### Verify constraints and indexes

```cypher
SHOW CONSTRAINTS;
SHOW INDEXES;
```

---

## Seed a test node

Confirm your connection is working by running a test write and read:

```cypher
// Write
MERGE (p:Project {name: "Logios Brain"})
ON CREATE SET
  p.created_at  = datetime(),
  p.description = "Personal AI memory infrastructure",
  p.status      = "active"
RETURN p;

// Confirm it exists
MATCH (p:Project {name: "Logios Brain"})
RETURN p;

// Clean up the test node if you want a fresh start
// MATCH (p:Project {name: "Logios Brain"}) DELETE p;
```

---

## Example graph queries

These are the kinds of queries your MCP server will run. You can also run them manually in the Neo4j Browser to explore your graph as it grows.

### Find everything connected to a project

```cypher
MATCH (p:Project {name: "Logios Brain"})-[r]-(connected)
RETURN p, r, connected
LIMIT 50;
```

### Find all concepts mentioned across memories

```cypher
MATCH (c:Concept)
RETURN c.name, c.memory_id, c.created_at
ORDER BY c.created_at DESC
LIMIT 20;
```

### Trace the provenance chain for a concept

```cypher
MATCH path = (c:Concept {name: "evidence layer"})-[*1..3]-(other)
RETURN path
LIMIT 20;
```

### Find memories that have never been cited in any generation

```cypher
// This requires a cross-store query — run the Supabase side first
// to get all memory_ids that appear in the evidence table,
// then find nodes in Neo4j whose memory_id is NOT in that set.
// This is best handled in the MCP server as a combined query.

// Neo4j side: get all node memory_ids
MATCH (n)
WHERE n.memory_id IS NOT NULL
RETURN DISTINCT n.memory_id AS memory_id;
```

### Find concepts that appear most frequently

```cypher
MATCH (m)-[r:MENTIONS]->(c:Concept)
RETURN c.name, count(r) AS mention_count
ORDER BY mention_count DESC
LIMIT 20;
```

---

## AuraDB Free tier notes

**Pause behavior:** The free instance pauses after 3 days of no connections. When your MCP server starts and tries to connect, Neo4j will return a connection error if the instance is paused. You will need to log into the AuraDB console and click **Resume**.

To avoid this in production: set up a lightweight cron job on Hetzner that pings Neo4j every 48 hours to keep it alive.

```bash
# On Hetzner, add to crontab:
# crontab -e
# 0 */48 * * * /opt/logios-brain/scripts/ping_neo4j.sh
```

Create the ping script at `/opt/logios-brain/scripts/ping_neo4j.sh`:

```bash
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
```

**Self-hosting alternative:** If you find yourself hitting the 200K node limit or the pause behavior is annoying, the cleanest alternative is running Neo4j Community Edition on your Hetzner VPS directly:

```bash
docker run \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/YOUR_PASSWORD \
  -v $HOME/neo4j/data:/data \
  -d neo4j:5-community
```

This gives you unlimited nodes, no pausing, and no dependency on an external service. The downside is RAM usage (~512MB minimum). Only do this if your Hetzner VPS has 4GB+ RAM.

---

**Next: [Qdrant Setup](05-qdrant.md)**