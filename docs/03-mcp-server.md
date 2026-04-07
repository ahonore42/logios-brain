# Step 3: MCP Server

The FastAPI server is the front door to your brain. It runs on your Hetzner VPS, speaks the MCP protocol over HTTP/SSE, and routes every tool call to the right combination of Supabase, Qdrant, and Neo4j.

This doc gives you the complete server code and the deployment steps to get it running on Hetzner behind a systemd service.

---

## Directory structure on Hetzner

```
/opt/logios-brain/
├── .env                  ← your credentials (never in git)
├── venv/                 ← Python virtual environment
└── server/
    ├── main.py
    ├── requirements.txt
    ├── embeddings.py
    ├── entity_extraction.py
    ├── db/
    │   ├── __init__.py
    │   ├── supabase.py
    │   ├── qdrant.py
    │   └── neo4j_client.py
    └── tools/
        ├── __init__.py
        ├── remember.py
        ├── search.py
        ├── relate.py
        ├── run_skill.py
        └── get_evidence.py
```

---

## requirements.txt

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
python-dotenv==1.0.1
supabase==2.7.4
qdrant-client==1.10.1
neo4j==5.23.1
google-generativeai==0.7.2
httpx==0.27.2
pydantic==2.8.2
```

---

## server/db/supabase.py

```python
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv("/opt/logios-brain/.env")

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = create_client(url, key)
    return _client
```

---

## server/db/qdrant.py

```python
import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from dotenv import load_dotenv

load_dotenv("/opt/logios-brain/.env")

COLLECTION_NAME = "memories"
EMBEDDING_DIM   = 3072   # gemini-embedding-001 dimension

_client: QdrantClient | None = None


def get_qdrant() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(
            url=os.environ["QDRANT_URL"],
            api_key=os.environ["QDRANT_API_KEY"],
        )
    return _client


def ensure_collection() -> None:
    """Create the memories collection if it does not exist."""
    client = get_qdrant()
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE,
            ),
        )
```

---

## server/db/neo4j_client.py

```python
import os
from neo4j import GraphDatabase, Driver
from dotenv import load_dotenv

load_dotenv("/opt/logios-brain/.env")

_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )
    return _driver


def run_query(cypher: str, params: dict | None = None) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        result = session.run(cypher, params or {})
        return [dict(record) for record in result]


def close() -> None:
    global _driver
    if _driver:
        _driver.close()
        _driver = None
```

---

## server/embeddings.py

```python
import os
import time
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv("/opt/logios-brain/.env")

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = "models/text-embedding-004"   # gemini-embedding-001 via SDK


def embed(text: str, retries: int = 3) -> list[float]:
    """
    Embed a single text string using Gemini.
    Retries with exponential backoff on rate limit errors.
    """
    for attempt in range(retries):
        try:
            result = genai.embed_content(
                model=MODEL,
                content=text,
                task_type="retrieval_document",
            )
            return result["embedding"]
        except Exception as exc:
            if "429" in str(exc) and attempt < retries - 1:
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            raise

    raise RuntimeError(f"Embedding failed after {retries} attempts")


def embed_query(text: str) -> list[float]:
    """
    Embed a query string (uses retrieval_query task type for better recall).
    """
    result = genai.embed_content(
        model=MODEL,
        content=text,
        task_type="retrieval_query",
    )
    return result["embedding"]
```

---

## server/entity_extraction.py

```python
import json
import httpx
import os
from dotenv import load_dotenv

load_dotenv("/opt/logios-brain/.env")

# Uses your local Ollama instance on the System76 if reachable,
# falls back to a small model via any available local endpoint.
# Adjust OLLAMA_URL to point to wherever your local models run.
OLLAMA_URL  = os.getenv("OLLAMA_URL", "http://localhost:11434")
ENTITY_MODEL = os.getenv("ENTITY_MODEL", "mistral:7b")

SYSTEM_PROMPT = """
You are an entity extraction assistant. Given a text, extract named entities
and return ONLY valid JSON with no additional text, markdown, or explanation.

Return this structure:
{
  "entities": [
    {
      "name": "entity name",
      "label": "one of: Project, Concept, Person, Session, Event, Decision, Tool, Location",
      "relationships": [
        {"target": "other entity name", "type": "RELATES_TO | PART_OF | CREATED_BY | MENTIONS | CAUSED_BY"}
      ]
    }
  ]
}

If there are no entities, return: {"entities": []}
""".strip()


def extract_entities(text: str) -> list[dict]:
    """
    Call local Ollama to extract entities from a memory text.
    Returns a list of entity dicts ready to write to Neo4j.
    """
    try:
        response = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": ENTITY_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Extract entities from:\n\n{text}"},
                ],
                "stream": False,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        parsed  = json.loads(content)
        return parsed.get("entities", [])
    except Exception:
        # Entity extraction is best-effort — never block a memory write
        return []
```

---

## server/tools/remember.py

This is the write path. One inbound memory fans out to three writes.

```python
import uuid
from db.supabase import get_supabase
from db.qdrant   import get_qdrant, COLLECTION_NAME
from db.neo4j_client import run_query
from embeddings  import embed
from entity_extraction import extract_entities
from qdrant_client.models import PointStruct
import asyncio


def remember(content: str, source: str = "manual", session_id: str | None = None, metadata: dict | None = None) -> dict:
    """
    Write a memory to all three stores.

    1. Supabase: upsert_memory (deduplication-safe, returns memory_id)
    2. Qdrant:   embed and upsert the chunk point
    3. Neo4j:    extract entities and merge into the graph (async, best-effort)

    Returns the memory_id and whether this was a new or duplicate memory.
    """
    sb = get_supabase()

    # 1. Supabase write — get canonical memory_id
    result = sb.rpc("upsert_memory", {
        "p_content":    content,
        "p_source":     source,
        "p_metadata":   metadata or {},
        "p_session_id": session_id,
    }).execute()

    memory_id = str(result.data)

    # 2. Write chunk record to Supabase and embed to Qdrant
    qdrant_id = str(uuid.uuid4())
    vector    = embed(content)

    sb.table("chunks").insert({
        "memory_id":   memory_id,
        "content":     content,
        "chunk_index": 0,
        "qdrant_id":   qdrant_id,
    }).execute()

    get_qdrant().upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=qdrant_id,
                vector=vector,
                payload={
                    "memory_id":   memory_id,
                    "source":      source,
                    "session_id":  session_id,
                },
            )
        ],
    )

    # 3. Entity extraction and Neo4j write — best-effort, non-blocking
    try:
        _write_entities(content, memory_id)
    except Exception:
        pass  # Never fail a memory write because of entity extraction

    return {
        "memory_id": memory_id,
        "status":    "stored",
        "source":    source,
    }


def _write_entities(content: str, memory_id: str) -> None:
    entities = extract_entities(content)
    if not entities:
        return

    for entity in entities:
        name  = entity.get("name", "").strip()
        label = entity.get("label", "Concept")
        if not name:
            continue

        # Merge node into Neo4j (create if not exists, update if exists)
        result = run_query(
            f"""
            MERGE (e:{label} {{name: $name}})
            ON CREATE SET e.created_at = datetime(), e.memory_id = $memory_id
            ON MATCH  SET e.last_seen  = datetime()
            RETURN elementId(e) as node_id
            """,
            {"name": name, "memory_id": memory_id},
        )

        if not result:
            continue

        neo4j_node_id = result[0]["node_id"]

        # Register in Supabase entity registry
        from db.supabase import get_supabase
        get_supabase().table("entities").upsert(
            {
                "memory_id":     memory_id,
                "neo4j_node_id": neo4j_node_id,
                "label":         label,
                "name":          name,
            },
            on_conflict="neo4j_node_id",
        ).execute()

        # Write relationships between entities
        for rel in entity.get("relationships", []):
            target   = rel.get("target", "").strip()
            rel_type = rel.get("type", "RELATES_TO").upper()
            if not target:
                continue
            run_query(
                f"""
                MERGE (a {{name: $source_name}})
                MERGE (b {{name: $target_name}})
                MERGE (a)-[r:{rel_type}]->(b)
                ON CREATE SET r.created_at = datetime(), r.memory_id = $memory_id
                """,
                {
                    "source_name": name,
                    "target_name": target,
                    "memory_id":   memory_id,
                },
            )
```

---

## server/tools/search.py

The read path — routes queries to Qdrant and/or Neo4j depending on the query type.

```python
from db.supabase     import get_supabase
from db.qdrant       import get_qdrant, COLLECTION_NAME
from db.neo4j_client import run_query
from embeddings      import embed_query


def search(query: str, top_k: int = 10, threshold: float = 0.65) -> list[dict]:
    """
    Semantic search over Qdrant, hydrated with full memory content from Supabase.
    """
    vector  = embed_query(query)
    results = get_qdrant().search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=top_k,
        score_threshold=threshold,
        with_payload=True,
    )

    if not results:
        return []

    memory_ids = [r.payload["memory_id"] for r in results]
    scores     = {r.payload["memory_id"]: r.score for r in results}

    sb_result = (
        get_supabase()
        .table("memories")
        .select("id, content, source, captured_at, metadata")
        .in_("id", memory_ids)
        .execute()
    )

    memories = {m["id"]: m for m in sb_result.data}

    return [
        {
            "memory_id":    mid,
            "score":        scores[mid],
            "content":      memories[mid]["content"] if mid in memories else None,
            "source":       memories[mid]["source"]  if mid in memories else None,
            "captured_at":  memories[mid]["captured_at"] if mid in memories else None,
        }
        for mid in memory_ids
        if mid in memories
    ]


def graph_search(entity_name: str, depth: int = 2) -> list[dict]:
    """
    Graph traversal from an entity — returns connected nodes and relationships.
    """
    results = run_query(
        """
        MATCH (start {name: $name})
        CALL apoc.path.subgraphNodes(start, {maxLevel: $depth}) YIELD node
        RETURN
          elementId(node) as node_id,
          labels(node)    as labels,
          node.name       as name,
          node.memory_id  as memory_id
        LIMIT 50
        """,
        {"name": entity_name, "depth": depth},
    )
    return results


def recall(
    source: str | None = None,
    since: str | None  = None,
    limit: int         = 20,
) -> list[dict]:
    """
    Structured recall from Supabase — by source, date range, or both.
    """
    sb    = get_supabase()
    query = sb.table("memories").select("id, content, source, captured_at, metadata")

    if source:
        query = query.eq("source", source)
    if since:
        query = query.gte("captured_at", since)

    result = query.order("captured_at", desc=True).limit(limit).execute()
    return result.data
```

---

## server/tools/get_evidence.py

```python
from db.supabase import get_supabase


def get_evidence(generation_id: str) -> dict:
    """
    Return the full evidence receipt for a generation.
    """
    sb     = get_supabase()
    result = sb.rpc("get_generation_receipt", {
        "p_generation_id": generation_id,
    }).execute()

    return result.data or {}
```

---

## server/tools/relate.py

```python
from db.neo4j_client import run_query


def relate(entity_a: str, entity_b: str, relationship_type: str = "RELATES_TO") -> dict:
    """
    Manually create or reinforce a relationship between two entities in Neo4j.
    Useful for building the graph from outside the automatic extraction path.
    """
    rel_type = relationship_type.upper().replace(" ", "_")

    run_query(
        f"""
        MERGE (a {{name: $entity_a}})
        MERGE (b {{name: $entity_b}})
        MERGE (a)-[r:{rel_type}]->(b)
        ON CREATE SET r.created_at = datetime(), r.manual = true
        ON MATCH  SET r.last_updated = datetime()
        """,
        {"entity_a": entity_a, "entity_b": entity_b},
    )

    return {
        "status": "related",
        "from":   entity_a,
        "to":     entity_b,
        "type":   rel_type,
    }
```

---

## server/tools/run_skill.py

```python
import uuid
from db.supabase import get_supabase
from tools.search import search, graph_search


def run_skill(skill_name: str, context: dict, model: str = "unknown", machine: str = "unknown") -> dict:
    """
    Execute a skill:
    1. Load prompt template from Supabase
    2. Retrieve relevant memories (Qdrant + Neo4j)
    3. Build evidence manifest
    4. Return prompt + context for local model to execute
    5. Record the generation and evidence receipt

    Note: this function prepares and records everything but does NOT
    call the local LLM directly — that is done by the calling agent.
    The agent calls run_skill, gets back the prompt + evidence manifest,
    executes the LLM call locally, then calls record_generation with the output.
    """
    sb = get_supabase()

    # 1. Load skill
    skill_result = (
        sb.table("skills")
        .select("id, name, prompt_template")
        .eq("name", skill_name)
        .eq("active", True)
        .single()
        .execute()
    )

    if not skill_result.data:
        return {"error": f"Skill '{skill_name}' not found or inactive"}

    skill = skill_result.data

    # 2. Retrieve context
    query_str    = context.get("query", skill_name)
    vector_hits  = search(query_str, top_k=8)
    graph_hits   = []

    if context.get("entity"):
        graph_hits = graph_search(context["entity"], depth=2)

    # 3. Build evidence manifest
    evidence_manifest = [
        {
            "rank":            i + 1,
            "retrieval_type":  "vector",
            "relevance_score": hit["score"],
            "memory_id":       hit["memory_id"],
            "content":         hit["content"],
            "source":          hit["source"],
            "captured_at":     hit["captured_at"],
        }
        for i, hit in enumerate(vector_hits)
    ]

    for i, node in enumerate(graph_hits):
        evidence_manifest.append({
            "rank":           len(vector_hits) + i + 1,
            "retrieval_type": "graph",
            "neo4j_node_id":  node.get("node_id"),
            "name":           node.get("name"),
            "memory_id":      node.get("memory_id"),
        })

    # 4. Return everything for the local agent to execute
    return {
        "skill_id":         skill["id"],
        "skill_name":       skill_name,
        "prompt_template":  skill["prompt_template"],
        "evidence_manifest": evidence_manifest,
        "context":          context,
        "instructions":     (
            "Execute this skill using your local model. "
            "Once you have the output, call record_generation with: "
            "skill_id, output, model, machine, prompt_used, evidence_manifest."
        ),
    }


def record_generation(
    skill_id:          str,
    skill_name:        str,
    output:            str,
    model:             str,
    machine:           str,
    prompt_used:       str,
    evidence_manifest: list[dict],
    session_id:        str | None = None,
) -> dict:
    """
    Write the generation record and all evidence rows to Supabase.
    Call this after your local LLM has produced its output.
    """
    sb = get_supabase()

    # Write generation
    gen_result = (
        sb.table("generations")
        .insert({
            "skill_id":    skill_id,
            "skill_name":  skill_name,
            "output":      output,
            "model":       model,
            "machine":     machine,
            "prompt_used": prompt_used,
            "session_id":  session_id,
        })
        .execute()
    )

    generation_id = gen_result.data[0]["id"]

    # Write evidence rows
    evidence_rows = []
    for item in evidence_manifest:
        evidence_rows.append({
            "generation_id":   generation_id,
            "memory_id":       item.get("memory_id"),
            "chunk_id":        item.get("chunk_id"),
            "neo4j_node_id":   item.get("neo4j_node_id"),
            "relevance_score": item.get("relevance_score"),
            "retrieval_type":  item.get("retrieval_type", "vector"),
            "rank":            item.get("rank", 0),
        })

    if evidence_rows:
        sb.table("evidence").insert(evidence_rows).execute()

    return {
        "generation_id": generation_id,
        "evidence_count": len(evidence_rows),
        "status": "recorded",
    }
```

---

## server/main.py

The FastAPI entrypoint. Exposes all tools as MCP-compatible endpoints.

```python
import os
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from dotenv import load_dotenv

from db.qdrant    import ensure_collection
from tools.remember     import remember
from tools.search       import search, recall, graph_search
from tools.relate       import relate
from tools.run_skill    import run_skill, record_generation
from tools.get_evidence import get_evidence

load_dotenv("/opt/logios-brain/.env")

app = FastAPI(title="Logios Brain MCP Server")
ACCESS_KEY = os.environ["MCP_ACCESS_KEY"]


# ── Auth dependency ────────────────────────────────────────────
def verify_key(x_brain_key: str = Header(default=None), key: str = None):
    provided = x_brain_key or key
    if provided != ACCESS_KEY:
        raise HTTPException(status_code=401, detail="Invalid access key")
    return provided


# ── Startup ────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    ensure_collection()


# ── Health ─────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


# ── MCP tool schemas ───────────────────────────────────────────
class RememberRequest(BaseModel):
    content:    str
    source:     str = "manual"
    session_id: str | None = None
    metadata:   dict = {}

class SearchRequest(BaseModel):
    query:     str
    top_k:     int   = 10
    threshold: float = 0.65

class RecallRequest(BaseModel):
    source: str | None = None
    since:  str | None = None
    limit:  int        = 20

class GraphSearchRequest(BaseModel):
    entity_name: str
    depth:       int = 2

class RelateRequest(BaseModel):
    entity_a:          str
    entity_b:          str
    relationship_type: str = "RELATES_TO"

class RunSkillRequest(BaseModel):
    skill_name: str
    context:    dict = {}
    model:      str  = "unknown"
    machine:    str  = "unknown"

class RecordGenerationRequest(BaseModel):
    skill_id:          str
    skill_name:        str
    output:            str
    model:             str
    machine:           str
    prompt_used:       str
    evidence_manifest: list[dict]
    session_id:        str | None = None

class GetEvidenceRequest(BaseModel):
    generation_id: str

class RelateRequest(BaseModel):
    entity_a:          str
    entity_b:          str
    relationship_type: str = "RELATES_TO"


# ── MCP tools ──────────────────────────────────────────────────
@app.post("/tools/remember")
def tool_remember(req: RememberRequest, _=Depends(verify_key)):
    return remember(req.content, req.source, req.session_id, req.metadata)

@app.post("/tools/search")
def tool_search(req: SearchRequest, _=Depends(verify_key)):
    return search(req.query, req.top_k, req.threshold)

@app.post("/tools/recall")
def tool_recall(req: RecallRequest, _=Depends(verify_key)):
    return recall(req.source, req.since, req.limit)

@app.post("/tools/graph_search")
def tool_graph_search(req: GraphSearchRequest, _=Depends(verify_key)):
    return graph_search(req.entity_name, req.depth)

@app.post("/tools/relate")
def tool_relate(req: RelateRequest, _=Depends(verify_key)):
    return relate(req.entity_a, req.entity_b, req.relationship_type)

@app.post("/tools/run_skill")
def tool_run_skill(req: RunSkillRequest, _=Depends(verify_key)):
    return run_skill(req.skill_name, req.context, req.model, req.machine)

@app.post("/tools/record_generation")
def tool_record_generation(req: RecordGenerationRequest, _=Depends(verify_key)):
    return record_generation(
        req.skill_id, req.skill_name, req.output,
        req.model, req.machine, req.prompt_used,
        req.evidence_manifest, req.session_id,
    )

@app.post("/tools/get_evidence")
def tool_get_evidence(req: GetEvidenceRequest, _=Depends(verify_key)):
    return get_evidence(req.generation_id)


# ── MCP manifest (tool discovery) ─────────────────────────────
@app.get("/mcp/tools")
def mcp_tools(_=Depends(verify_key)):
    return {
        "tools": [
            {"name": "remember",          "description": "Store a memory in all three stores"},
            {"name": "search",            "description": "Semantic search over memories"},
            {"name": "recall",            "description": "Structured recall by source or date"},
            {"name": "graph_search",      "description": "Traverse the knowledge graph from an entity"},
            {"name": "relate",            "description": "Manually create a graph relationship"},
            {"name": "run_skill",         "description": "Prepare a skill execution with evidence context"},
            {"name": "record_generation", "description": "Record a completed generation with evidence receipt"},
            {"name": "get_evidence",      "description": "Retrieve the evidence receipt for a generation"},
        ]
    }
```

---

## Deployment on Hetzner

SSH into your VPS and run these commands in order.

### 1. Create the directory and clone your repo

```bash
sudo mkdir -p /opt/logios-brain
sudo chown $USER:$USER /opt/logios-brain
cd /opt/logios-brain
git clone https://github.com/YOUR_USERNAME/logios-brain.git .
```

### 2. Create and populate the `.env` file

```bash
nano /opt/logios-brain/.env
```

Paste in your credentials from the setup step. Save and exit.

Protect it:
```bash
chmod 600 /opt/logios-brain/.env
```

### 3. Create the virtual environment and install dependencies

```bash
cd /opt/logios-brain/server
python3 -m venv /opt/logios-brain/venv
source /opt/logios-brain/venv/bin/activate
pip install -r requirements.txt
```

### 4. Test it runs

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Hit `Ctrl+C` once you confirm it starts without errors.

### 5. Create the systemd service

```bash
sudo nano /etc/systemd/system/logios-brain.service
```

Paste:
```ini
[Unit]
Description=Logios Brain MCP Server
After=network.target

[Service]
Type=simple
User=YOUR_HETZNER_USERNAME
WorkingDirectory=/opt/logios-brain/server
ExecStart=/opt/logios-brain/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
EnvironmentFile=/opt/logios-brain/.env
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Replace `YOUR_HETZNER_USERNAME` with your actual username.

### 6. Enable and start the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable logios-brain
sudo systemctl start logios-brain
sudo systemctl status logios-brain
```

### 7. Verify it is running

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`

### 8. Open the port in your firewall

If you are using `ufw`:
```bash
sudo ufw allow 8000/tcp
```

Then verify from your local machine:
```bash
curl http://YOUR_HETZNER_IP:8000/health
```

> **Optional but recommended:** Put Nginx in front of this and terminate TLS so your MCP connections run over HTTPS. This is especially important if you are connecting from networks you do not control.

---

## Viewing logs

```bash
journalctl -u logios-brain -f
```

---

## Deploying updates

```bash
cd /opt/logios-brain
git pull
source venv/bin/activate
pip install -r server/requirements.txt
sudo systemctl restart logios-brain
```

---

**Next: [Neo4j Setup](04-neo4j.md)**