# Connecting Hermes Agent to Logios Brain

This guide covers two steps: generating an agent token from Logios Brain, then configuring Hermes Agent to use it.

---

## Step 1 — Generate an Agent Token

### 1a. Get the Owner Secret Key

The secret key is printed to the app logs on first startup. If you don't have it:

```bash
docker compose logs app | grep SECRET_KEY
```

Or from inside the running container:

```bash
docker exec logios-app uv run python -c "from app import config; print(config.SECRET_KEY)"
```

### 1b. Login at the API Docs

Open `http://localhost:8000/docs` in your browser.

**Login as owner:**

1. Expand `POST /auth/login`
2. Fill in:
   - `email` — your owner email (e.g. `you@example.com`)
   - `password` — your owner password
   - Header `X-Secret-Key` — the secret key from step 1a
3. Click **Execute**
4. Copy the `access_token` from the response

**Create an agent token:**

1. Expand `POST /auth/tokens`
2. Add header: `Authorization: Bearer <access_token>` (from login response)
3. Fill in `name` — e.g. `"hermes-agent"`
4. Click **Execute**
5. Copy the returned `token` (starts with `tok_`)

---

## Step 2 — Connect Hermes Agent

### Environment Variables

On the machine running Hermes Agent, set:

```bash
export LOGIOS_URL=http://localhost:8000
export LOGIOS_TOKEN=tok_your_agent_token_here
export LOGIOS_SESSION_ID=my-session       # unique per conversation thread
export LOGIOS_AGENT_ID=my-agent           # unique per agent
export REDIS_URL=redis://localhost:6379   # Redis on same host
```

### Python Configuration

```python
from app.integrations.hermes import connect

provider = connect(
    api_base_url=os.environ["LOGIOS_URL"],
    api_key=os.environ["LOGIOS_TOKEN"],
    session_id=os.environ["LOGIOS_SESSION_ID"],
    agent_id=os.environ["LOGIOS_AGENT_ID"],
    redis_url=os.environ["REDIS_URL"],
    snapshot_threshold=20,  # checkpoint every N tool calls
)

memory_manager.add_provider(provider)
```

### Hermes Agent Startup

The exact flags depend on how Hermes Agent is installed. The standard pattern:

```bash
hermes-agent \
  --memory.external logios \
  --logios.url $LOGIOS_URL \
  --logios.token $LOGIOS_TOKEN \
  --logios.session-id $LOGIOS_SESSION_ID \
  --logios.agent-id $LOGIOS_AGENT_ID \
  --logios.redis-url $REDIS_URL \
  --logios.snapshot-threshold 20
```

Or via `hermes.yaml`:

```yaml
memory:
  external: logios
  logios:
    url: http://localhost:8000
    token: tok_your_agent_token
    session_id: my-session
    agent_id: my-agent
    redis_url: redis://localhost:6379
    snapshot_threshold: 20
```

---

## What Happens

Once connected, Logios Brain provides:

| Hermes Event | What Logios Does |
|---|---|
| `initialize()` | Connects Redis working memory buffer |
| `prefetch(query)` | Returns episodic + identity memories before each turn |
| `queue_prefetch(query)` | Background recall for next turn |
| `sync_turn()` | Buffers turn in Redis; auto-snapshots at threshold |
| `on_session_end()` | Flushes working memory as checkpoint |
| `on_pre_compress()` | Contributes memories before context compression |
| `on_memory_write()` | Mirrors Hermes built-in memory writes to Logios |

Redis is required for working memory buffering. Run `docker compose up -d redis` if not already running.

---

## Troubleshooting

**`prefetch()` returns empty**: Check the agent token is valid and has `tok_` prefix.

**Redis connection errors**: Ensure Redis is running (`docker compose up -d redis`) and `REDIS_URL` is correct for the agent's host (`localhost` if on same machine, `redis://redis:6379` if inside Docker).

**`401 Unauthorized`**: The agent token is missing or invalid. Re-generate from `http://localhost:8000/docs`.
