# Step 8: Connecting AI Clients

Your MCP server is running on Hetzner. This step connects every client that should be able to read from and write to your brain.

The pattern is the same for every client: point it at `http://YOUR_HETZNER_IP:8000` with your `MCP_ACCESS_KEY`.

---

## Connection URL format

Every client authenticates using either:

**Header-based (preferred for clients that support custom headers):**
```
URL:    http://YOUR_HETZNER_IP:8000
Header: x-brain-key: YOUR_MCP_ACCESS_KEY
```

**Query parameter (for clients that embed auth in the URL):**
```
URL: http://YOUR_HETZNER_IP:8000?key=YOUR_MCP_ACCESS_KEY
```

Both work. The `verify_key` dependency in `main.py` checks both.

---

## 1. Claude Code

One command:

```bash
claude mcp add --transport http logios-brain \
  http://YOUR_HETZNER_IP:8000 \
  --header "x-brain-key: YOUR_MCP_ACCESS_KEY"
```

Verify it is connected:
```bash
claude mcp list
```

You should see `logios-brain` in the list with status `connected`.

Test it in a Claude Code session:
```
Use the logios-brain remember tool to store: "Testing Logios Brain MCP connection from Your Machine."
```

---

## 2. Claude Desktop

1. Open Claude Desktop → **Settings → Connectors**
2. Click **Add custom connector**
3. Name: `Logios Brain`
4. Remote MCP server URL: `http://YOUR_HETZNER_IP:8000?key=YOUR_MCP_ACCESS_KEY`
5. Click **Add**

Enable it per conversation via the `+` button → Connectors.

> If you have HTTPS set up on your Hetzner VPS (via Nginx + Let's Encrypt), use `https://` instead of `http://`. Claude Desktop works better with HTTPS.

---

## 3. OpenClaw

OpenClaw already has MCP support via OpenClaw. Add Logios Brain as a tool source in OpenClaw's configuration.

In your OpenClaw config (typically at `~/.openclaw/config.yaml`), add:

```yaml
mcp_servers:
  logios-brain:
    url: "http://YOUR_HETZNER_IP:8000"
    headers:
      x-brain-key: "YOUR_MCP_ACCESS_KEY"
    tools:
      - remember
      - search
      - recall
      - graph_search
      - relate
      - run_skill
      - record_generation
      - get_evidence
```

Restart OpenClaw after updating the config.

OpenClaw can now call `remember` at session end to persist important outputs, and `search` at session start to load relevant context automatically. This is the foundation of continuous memory across OpenClaw sessions.

**Recommended OpenClaw session protocol:**

At the start of each OpenClaw session, have it run:
```
search(query="[current task or topic]", top_k=5)
```

At the end of each session, have it run:
```
remember(content="[session summary and key outputs]", source="openclaw-bot", session_id="[session uuid]")
```

This creates a self-reinforcing loop: each OpenClaw session reads what past sessions produced and contributes back to the shared brain.

---

## 4. Telegram bot

Your existing bot can be extended to write to Logios Brain. Every message sent to the bot becomes a memory.

Add this handler to your bot code (wherever you handle incoming messages):

```python
import httpx

LOGIOS_URL = "http://YOUR_HETZNER_IP:8000"
LOGIOS_KEY = "YOUR_MCP_ACCESS_KEY"


def send_to_brain(text: str, session_id: str | None = None) -> dict:
    """
    Forward a Telegram message to the Logios Brain MCP server.
    """
    response = httpx.post(
        f"{LOGIOS_URL}/tools/remember",
        headers={"x-brain-key": LOGIOS_KEY},
        json={
            "content":    text,
            "source":     "telegram",
            "session_id": session_id,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


# In your message handler:
# result = send_to_brain(message.text, session_id=str(message.chat.id))
# bot.reply_to(message, f"Stored. memory_id: {result['memory_id']}")
```

**Searching from Telegram:**

```python
def search_brain(query: str) -> list[dict]:
    response = httpx.post(
        f"{LOGIOS_URL}/tools/search",
        headers={"x-brain-key": LOGIOS_KEY},
        json={"query": query, "top_k": 5},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()
```

Add a command handler so you can type `/search [query]` in Telegram and get results back inline.

---

## 5. Any other local AI (Ollama, llama.cpp, etc.)

Any tool that can make HTTP POST requests can use your MCP server. The API is plain JSON over HTTP — no special MCP client library required.

Quick test from anywhere:

```bash
curl -X POST http://YOUR_HETZNER_IP:8000/tools/remember \
  -H "x-brain-key: YOUR_MCP_ACCESS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"content": "Test from curl", "source": "manual"}'
```

```bash
curl -X POST http://YOUR_HETZNER_IP:8000/tools/search \
  -H "x-brain-key: YOUR_MCP_ACCESS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "top_k": 3}'
```

---

## Verifying the full stack

Run this test sequence from your local machine after all clients are connected:

**1. Write a memory from Claude Code:**
```
Use logios-brain to remember: "Full stack test from Claude Code on local machine. All three stores should receive this."
```

**2. Search for it:**
```
Use logios-brain to search for: "full stack test"
```

**3. Check Supabase:** Open Table Editor → memories. You should see the new row.

**4. Check Qdrant:** Log into cloud.qdrant.io → your cluster → collections → memories. Vector count should have increased by 1.

**5. Check Neo4j:** Open AuraDB Browser and run:
```cypher
MATCH (n)
WHERE n.created_at > datetime() - duration('PT5M')
RETURN n
LIMIT 10;
```

This shows nodes created in the last 5 minutes. If entity extraction found anything in your test text, you will see nodes here.

---

## Troubleshooting

**Connection refused:**
- Confirm the server is running: `sudo systemctl status logios-brain`
- Confirm port 8000 is open: `sudo ufw status`
- Test locally on Hetzner first: `curl http://localhost:8000/health`

**401 Unauthorized:**
- Your `MCP_ACCESS_KEY` in the client does not match what is in `/opt/logios-brain/.env`
- Check for extra spaces or newline characters when copying the key

**Embedding errors:**
- Confirm your `GEMINI_API_KEY` is valid: test it manually (see step 6)
- Check server logs: `journalctl -u logios-brain -f`

**Neo4j connection errors:**
- The AuraDB free instance may be paused — log in and resume it
- Check that your Neo4j credentials in `.env` match the downloaded credentials file exactly

---

**Next: [Companion Prompts](09-companion-prompts.md)**