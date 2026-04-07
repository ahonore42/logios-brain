# Step 5: Qdrant

Qdrant is the retriever. It stores 3072-dimensional embedding vectors for every memory chunk and handles semantic similarity search. It runs locally on your Hetzner VPS in Docker — no API key required, no cloud dependency, no storage limits.

---

## Docker Compose configuration

This block belongs in your `/opt/logios-brain/docker-compose.yml`. The full Compose file is in `docs/03-mcp-server.md`.

```yaml
qdrant:
  image: qdrant/qdrant:latest
  container_name: logios-qdrant
  restart: unless-stopped
  volumes:
    - qdrant_data:/qdrant/storage
  ports:
    - "127.0.0.1:6333:6333"   # REST API — localhost only
    - "127.0.0.1:6334:6334"   # gRPC — localhost only
  healthcheck:
    test: ["CMD-SHELL", "curl -sf http://localhost:6333/healthz || exit 1"]
    interval: 10s
    timeout: 5s
    retries: 5
```

Both ports are bound to `127.0.0.1` — Qdrant is not accessible from outside the VPS. Your FastAPI server connects to it directly over the Docker network at `http://localhost:6333`.

Qdrant uses approximately 200MB RAM at idle. On a 16GB CX43 this is negligible.

---

## `.env` for local Qdrant

```env
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
```

Leave `QDRANT_API_KEY` empty. Local Qdrant requires no authentication. The client code in `server/db/qdrant.py` passes `api_key=None` when the value is empty or absent.

---

## Starting Qdrant

```bash
cd /opt/logios-brain
docker compose up -d qdrant
docker compose ps   # qdrant should show "healthy"
```

---

## Collection setup

Your server calls `ensure_collection()` on startup, which creates the `memories` collection automatically if it does not exist. You do not need to create it manually.

The collection is configured with:

```python
VectorParams(
    size=3072,           # gemini-embedding-001 output dimension
    distance=Distance.COSINE,
)
```

**Why cosine?** Gemini embeddings are not normalized by default. Cosine similarity normalizes internally, making it robust across texts of different lengths. If you switch to a model that produces pre-normalized embeddings, dot product is equivalent and marginally faster.

---

## Verifying the collection

After your server starts for the first time:

```bash
curl http://localhost:6333/collections/memories
```

Expected response includes `"status": "green"` and `"vectors_count": 0` before any memories are stored.

Or use the Qdrant web dashboard. Since the port is localhost-only, access it via SSH tunnel:

```bash
# On your local machine:
ssh -L 6333:localhost:6333 your_user@YOUR_HETZNER_IP -N
```

Then open `http://localhost:6333/dashboard` in your browser.

---

## Payload structure

Every Qdrant point stores a vector alongside a payload:

```json
{
  "memory_id":  "uuid from PostgreSQL",
  "source":     "telegram | claude | exo | manual | import | system",
  "session_id": "uuid or null"
}
```

The payload enables filtered searches — for example, retrieving only memories from a specific source:

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue

results = qdrant.search(
    collection_name="memories",
    query_vector=vector,
    query_filter=Filter(
        must=[FieldCondition(key="source", match=MatchValue(value="telegram"))]
    ),
    limit=10,
)
```

Filtering is handled server-side in Qdrant before vector comparison — fast, no post-filtering needed in Python.

---

## Payload indexes

Add these after your collection is created to speed up filtered searches:

```bash
curl -X PUT http://localhost:6333/collections/memories/index \
  -H "Content-Type: application/json" \
  -d '{"field_name": "source", "field_schema": "keyword"}'

curl -X PUT http://localhost:6333/collections/memories/index \
  -H "Content-Type: application/json" \
  -d '{"field_name": "session_id", "field_schema": "keyword"}'
```

At personal knowledge base scale these are optional but worth adding now so you do not forget.

---

## Backup and export

Qdrant supports native snapshots via its REST API:

```bash
# Create a snapshot
curl -X POST http://localhost:6333/collections/memories/snapshots

# List snapshots to get the filename
curl http://localhost:6333/collections/memories/snapshots

# Copy the snapshot file out of the container
docker cp logios-qdrant:/qdrant/snapshots/memories/YOUR_SNAPSHOT.snapshot \
  /opt/logios-brain/backups/qdrant_$(date +%Y%m%d).snapshot
```

Restore on a new server:

```bash
curl -X POST "http://localhost:6333/collections/memories/snapshots/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "snapshot=@/path/to/qdrant_backup.snapshot"
```

For a full server migration, copying the Docker volume directly is faster than snapshot/restore:

```bash
# Stop Qdrant first for a consistent copy
docker compose stop qdrant

rsync -avz /var/lib/docker/volumes/logios-brain_qdrant_data/ \
  your_user@NEW_SERVER_IP:/var/lib/docker/volumes/logios-brain_qdrant_data/

docker compose start qdrant
```

See `scripts/backup.sh` for the automated backup that runs snapshots on a schedule.

---

## Testing the connection

```bash
source /opt/logios-brain/.env
python3 -c "
from qdrant_client import QdrantClient
client = QdrantClient(url='http://localhost:6333')
collections = client.get_collections()
print('Collections:', [c.name for c in collections.collections])
info = client.get_collection('memories')
print('Status:', info.status)
"
```

Expected:
```
Collections: ['memories']
Status: green
```

---

## Alternative: Qdrant Cloud

If you prefer not to run Qdrant in Docker, Qdrant Cloud offers a managed cluster with a free tier.

### Setup

1. Go to [cloud.qdrant.io](https://cloud.qdrant.io) and sign up
2. Click **Create cluster → Free tier**
3. Name it `logios-brain`, choose the region closest to your Hetzner VPS
4. Once provisioned, go to **API Keys → Create API Key**

### `.env` changes

```env
QDRANT_URL=https://YOUR_CLUSTER_ID.region.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key
```

### Payload index commands for Qdrant Cloud

Add the API key header:

```bash
curl -X PUT \
  -H "api-key: $QDRANT_API_KEY" \
  -H "Content-Type: application/json" \
  "$QDRANT_URL/collections/memories/index" \
  -d '{"field_name": "source", "field_schema": "keyword"}'
```

### Remove Qdrant from Docker Compose

Remove the `qdrant` service block and `qdrant_data` volume from `docker-compose.yml`.

### Trade-offs

| | Local Docker | Qdrant Cloud Free |
|---|---|---|
| Cost | $0 (your existing VPS) | $0 |
| Storage | Your full disk | 4GB |
| RAM usage | ~200MB on your VPS | None |
| Vector limit | Unlimited | ~300K at 3072 dims |
| Availability | Continuous | Continuous (no pause) |
| Backup | Native snapshot API | Console download |
| Dashboard | Via SSH tunnel | Direct web access |

Qdrant Cloud's free tier does not pause like AuraDB — it stays available indefinitely. The meaningful constraints are the 4GB storage limit and 1GB RAM. For a personal knowledge base expected to grow large over time, local Docker is the cleaner choice. Qdrant Cloud is reasonable if you want to avoid the SSH tunnel for dashboard access and are confident the storage limit is not a concern.

---

**Next: [Gemini Embeddings](06-gemini-embeddings.md)**