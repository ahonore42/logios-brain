# Connecting Agents to Logios Brain

Logios Brain is a server-side memory API. Agents authenticate with a Bearer token and call the HTTP API directly — no agent-type detection, no special discovery protocol.

## First-time setup

Logios Brain runs in Docker. One command brings up all services:

```bash
git clone https://github.com/your-org/logios-brain.git
cd logios-brain
cp .env.example .env
# Fill in .env — see .env.example for required values
docker compose up -d
```

The server starts on port 8000 with all stores (Postgres, Qdrant, Neo4j, Redis) running as sibling containers.

---

## Create an agent token

All API calls require a Bearer token. Tokens are created via the owner account.

### 1. Provision the owner account

Since `EMAILS_ENABLED=false` in the default config, the OTP is returned directly:

```bash
# Start the server first
docker compose up -d

# Create owner account
curl -X POST http://localhost:8000/auth/setup \
  -H "X-Secret-Key: YOUR_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your-password"}'
```

Response:
```json
{
  "pending_token": "eyJ...",
  "otp": "482731",
  "message": "Emails disabled — use the OTP below to complete setup."
}
```

### 2. Complete owner setup

```bash
curl -X POST http://localhost:8000/auth/verify-setup \
  -H "X-Secret-Key: YOUR_SECRET_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "pending_token=YOUR_PENDING_TOKEN&otp=YOUR_OTP"
```

Response:
```json
{
  "id": 1,
  "email": "you@example.com",
  "is_setup": true,
  "created_at": "2026-04-12T00:00:00Z"
}
```

### 3. Get an access token

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your-password"}'
```

Response:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### 4. Create an agent token

```bash
curl -X POST http://localhost:8000/auth/tokens \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-agent"}'
```

Response:
```json
{
  "id": 1,
  "agent_id": "agn_abc123",
  "token": "raw-agent-token-shown-only-once",
  "name": "my-agent",
  "created_at": "2026-04-12T00:00:00Z"
}
```

Save the `token` — it's shown only once. This is what the agent uses as its Bearer token.

---

## Connect an agent

Every agent connects the same way: HTTP POST to the Logios API with the Bearer token.

```python
import httpx

LOGIOS_URL = "http://your-server:8000"
AGENT_TOKEN = "raw-agent-token"

headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}
```

### Store a memory

```python
response = httpx.post(
    f"{LOGIOS_URL}/memories/remember",
    headers=headers,
    json={
        "content": "User asked me to refactor the auth middleware",
        "source": "hermes-agent",
        "session_id": "sess_abc123",
    },
    timeout=10.0,
)
memory = response.json()
print(memory["id"])  # UUID of the created memory
```

### Search memories

```python
response = httpx.post(
    f"{LOGIOS_URL}/memories/search",
    headers=headers,
    json={"query": "auth middleware refactor", "top_k": 5},
    timeout=10.0,
)
results = response.json()  # list of MemoryOut objects
```

### Get full context for an agent turn

```python
response = httpx.post(
    f"{LOGIOS_URL}/memories/context",
    headers=headers,
    json={"query": "what was I working on last session?", "top_k": 8},
    timeout=10.0,
)
ctx = response.json()
# ctx["identity_memories"] — core instructions (always included)
# ctx["episodic_memories"]  — session history from Qdrant
```

### Server-side working memory (hooks API)

Instead of running their own Redis, agents can buffer tool results on the server and snapshot them on a trigger:

```python
# Register a snapshot trigger
httpx.post(f"{LOGIOS_URL}/hooks/trigger", headers=headers, json={
    "session_id": "sess_abc123",
    "agent_id": "hermes-1",
    "mode": "call_count",
    "threshold": 20,
})

# After each tool call, buffer the result
httpx.post(f"{LOGIOS_URL}/hooks/buffer", headers=headers, json={
    "session_id": "sess_abc123",
    "agent_id": "hermes-1",
    "tool_name": "read_file",
    "result_summary": "auth/middleware.py: 120 lines, routes: /auth/setup, /auth/verify",
    "turn_index": 14,
})

# After each agent turn, check if trigger fired
resp = httpx.post(f"{LOGIOS_URL}/hooks/check", headers=headers, json={
    "session_id": "sess_abc123",
    "agent_id": "hermes-1",
    "current_turn": 14,
})
result = resp.json()
if result["should_fire"]:
    print(f"Snapshot created: {result['memory_id']}")
    print(result["snapshot_content"])  # synthesized checkpoint text
```

Available hook endpoints:

| Endpoint | Purpose |
|---|---|
| `POST /hooks/trigger` | Register/update a snapshot trigger |
| `POST /hooks/buffer` | Buffer a tool call result |
| `POST /hooks/check` | Evaluate trigger; snapshot if fired |
| `POST /hooks/flush` | Drain buffer without snapshotting |
| `POST /hooks/snapshot` | Force a snapshot regardless of trigger |

---

## Framework integrations

`app/integrations/` provides native adapters for specific agent frameworks. Each exposes a `connect()` factory that returns the appropriate interface for the framework:

```python
# Hermes Agent
from app.integrations.hermes import connect as hermes_connect
memory_manager = hermes_connect(
    api_base_url=LOGIOS_URL, api_key=AGENT_TOKEN, session_id="sess_abc123"
)

# OpenClaw
from app.integrations.openclaw import connect as openclaw_connect
gateway = openclaw_connect(
    api_base_url=LOGIOS_URL, api_key=AGENT_TOKEN, session_id="sess_abc123"
)

# Pi Coding Agent
from app.integrations.pi import connect as pi_connect
ext = pi_connect(
    api_base_url=LOGIOS_URL, api_key=AGENT_TOKEN, session_id="sess_abc123"
)

# GoClaw
from app.integrations.goclaw import connect as goclaw_connect
memory_stage, summarize_stage = goclaw_connect(
    api_base_url=LOGIOS_URL, api_key=AGENT_TOKEN, session_id="sess_abc123"
)

# Claude Agent SDK
from app.integrations.claude_agent_sdk import LogiosStorageAdapter
adapter = LogiosStorageAdapter(api_base_url=LOGIOS_URL, api_key=AGENT_TOKEN)

# ZeroClaw MCP
from app.integrations.zeroclaw import LogiosMCPServer
server = LogiosMCPServer(api_key=AGENT_TOKEN)
```

Each adapter implements the native interface of its framework — memory operations route through to the Logios API transparently.

---

## Test the connection

```bash
# Health check
curl http://localhost:8000/health
# {"status": "ok"}

# Write and search
curl -X POST http://localhost:8000/memories/remember \
  -H "Authorization: Bearer YOUR_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "Test memory", "source": "curl-test"}'

curl -X POST http://localhost:8000/memories/search \
  -H "Authorization: Bearer YOUR_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}'
```

---

## Production deployment

On a VPS, expose port 8000 and point agents at `http://YOUR_VPS_IP:8000`. The Bearer token authenticates all traffic — keep it secret, treat it like a password.

For HTTPS in production, put Nginx in front of the app with a Let's Encrypt certificate and proxy to port 8000.
