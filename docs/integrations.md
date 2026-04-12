# Agent Framework Integrations

How to connect any supported agent framework to Logios Brain as its memory backend.

---

## Overview

Logios Brain exposes a server-side HTTP API. Each agent framework connects via a client library that wraps that API. The framework integration is chosen at **agent build time** — you pick the integration for the framework you're using.

```
Your agent code
└── app/integrations.<framework>
    └── connect(api_base_url, api_key, session_id, ...)
        └── HTTP calls → Logios Brain API
```

All integrations require:
- **Logios Brain** running at some URL (e.g. `http://localhost:8000` for local dev)
- **API key** for authentication (from Logios Brain's owner setup)
- **Session ID** to scope episodic memories per agent session

---

## Quick Start

Install Logios Brain and the required dependencies:

```bash
# Clone and start Logios Brain
git clone https://github.com/your-org/logios-brain
cd logios-brain
docker compose up -d

# Complete owner setup at http://localhost:8000 to get your API key
```

Install the client package (or import from source):

```python
# If using pip installable package
pip install logios-brain

# Or import directly from the repo
import sys
sys.path.insert(0, "/path/to/logios-brain/app")
```

---

## Hermes Agent

**Hermes** (NousResearch) uses a provider-based memory architecture. Register Logios as an external `MemoryManager` provider.

### Install

```bash
pip install hermes-agent
```

### Connect

```python
from app.integrations.hermes import connect

memory_manager = connect(
    api_base_url="http://localhost:8000",
    api_key="tok_your_api_key",
    session_id="unique-session-id",
    agent_id="unique-agent-id",
    redis_url="redis://localhost:6379",
    snapshot_threshold=20,
)

# Register with Hermes
from hermes import HermesAgent
agent = HermesAgent(external_memory_manager=memory_manager)
```

### What happens

| Hermes event | Logios call |
|---|---|
| `on_turn_start()` | `POST /memories/context` → injects identity + episodic memories |
| `on_session_end()` | Flushes working memory as `type=checkpoint` via `POST /memories/remember` |
| `on_pre_compress()` | `POST /memories/search` → provides memories for compression context |
| Tool call buffered | Stored in Redis; auto-snapshot after `snapshot_threshold` calls |

### Snapshot threshold

Controls how many tool calls fire before Logios writes a checkpoint memory. Default is 20. Lower values = more memories, higher values = less noise.

---

## OpenClaw

**OpenClaw** uses a Gateway WebSocket control plane with extensions. Load Logios as a Gateway extension that exposes memory commands.

### Install

```bash
pip install openclaw
```

### Connect

```python
from app.integrations.openclaw import connect

extension = connect(
    api_base_url="http://localhost:8000",
    api_key="tok_your_api_key",
    session_id="unique-session-id",
)

# Register with OpenClaw Gateway
gateway.register_extension("logios", extension)
```

### Available commands

| Command | Description |
|---|---|
| `/remember <content>` | Persist a memory |
| `/recall <query>` | Semantic search over memories |
| `/forget <query>` | Revoke memories matching query |
| `/knowledge` | List all identity memories |
| `/digest` | Show memory digest for review |

### What happens

Each `/command` is translated into the corresponding Logios API call. The agent uses OpenClaw's normal tool invocation syntax — no framework-specific code needed beyond registration.

---

## Pi Coding Agent

**Pi Coding Agent** supports extension hooks for injecting memory into turns and handling compaction events.

### Install

```bash
pip install pi-coding-agent
```

### Connect

```python
from app.integrations.pi import connect

extension = connect(
    api_base_url="http://localhost:8000",
    api_key="tok_your_api_key",
    session_id="unique-session-id",
)

pi_agent.register_extension("logios", extension)
```

### What happens

| Pi event | Logios call |
|---|---|
| `pre_turn()` | `POST /memories/context` → injects memories before each turn |
| `on_compact()` | `POST /memories/remember` with `type=checkpoint` when Pi auto-compacts |
| Generation recorded | `POST /skills/record` with evidence manifest |

### Recording generations

After Pi generates output, record it with evidence:

```python
extension.record_generation(
    skill_name="coding",
    output=agent_output,
    model="anthropic/claude-3-5-sonnet",
    machine="desktop-mac",
    evidence=[
        {"memory_id": "...", "rank": 1, "retrieval_type": "vector", "relevance_score": "0.89"}
    ],
    prompt_used=full_prompt,
    chain_of_thought=agent_thought,
)
```

---

## GoClaw

**GoClaw** uses an 8-stage pipeline. Add Logios as memory and summarize stages that run on every turn.

### Install

```bash
pip install goclaw
```

### Connect

```python
from app.integrations.goclaw import connect

# Returns [LogiosMemoryStage, LogiosSummarizeStage]
stages = connect(
    api_base_url="http://localhost:8000",
    api_key="tok_your_api_key",
    session_id="unique-session-id",
    agent_id="unique-agent-id",
    include_summarize=True,
)

for stage in stages:
    pipeline.add_stage(stage)
```

### What happens

GoClaw's continuous per-turn memory consolidation model means Logios writes a checkpoint on **every agent turn**:

| Pipeline stage | Logios call |
|---|---|
| `logios_memory` (order 6) | `POST /memories/context` → fetches memories for next turn |
| `logios_summarize` (order 7) | `POST /memories/remember` with `type=checkpoint` summarizing the turn |

### Memory-only mode

If you want Logios for retrieval but not per-turn checkpointing:

```python
stages = connect(..., include_summarize=False)
```

---

## Claude Agent SDK

**Claude Agent SDK** (Anthropic) uses storage adapters you implement. `LogiosStorageAdapter` provides a complete implementation backed by Logios.

### Install

```bash
pip install anthropic-agent-sdk
```

### Connect

```python
from app.integrations.claude_agent_sdk import LogiosStorageAdapter

adapter = LogiosStorageAdapter(
    api_base_url="http://localhost:8000",
    api_key="tok_your_api_key",
    session_id="unique-session-id",
    agent_id="unique-agent-id",
    redis_url="redis://localhost:6379",
    snapshot_threshold=20,
)

agent = ClaudeAgent(storage=adapter)
```

### Hook into tool calls

Use `PreToolUse` and `PostToolUse` callbacks for working memory buffering:

```python
# PreToolUse — buffer the tool call
def before_tool(tool_name, tool_input):
    adapter.buffer_tool_call(tool_name, tool_input)

# PostToolUse — record the result
def after_tool(tool_name, tool_input, tool_output):
    adapter.record_tool_result(tool_name, tool_input, tool_output)
    # Working memory auto-snapshots when threshold is reached
```

### What happens

| SDK hook | Logios call |
|---|---|
| `retrieve_memories(query)` | `POST /memories/context` |
| `save_session(messages)` | `POST /memories/remember` with `type=checkpoint` |
| `buffer_tool_call()` | Redis buffer; auto-snapshot at threshold |
| `record_generation()` | `POST /skills/record` with evidence |

---

## ZeroClaw

**ZeroClaw** exposes memory tools via MCP (Model Context Protocol). Run Logios as an MCP server that ZeroClaw connects to.

### Install

```bash
pip install zeroclaw
```

### Option 1: Run Logios MCP server standalone

```bash
python -m app.integrations.zeroclaw \
    --url http://localhost:8000 \
    --key tok_your_api_key \
    --session-id default-session
```

### Option 2: Connect via Python

```python
from app.integrations.zeroclaw import LogiosMCPServer

mcp_server = LogiosMCPServer(
    api_base_url="http://localhost:8000",
    api_key="tok_your_api_key",
    session_id="unique-session-id",
)

# Register with ZeroClaw's MCP server
from mcp.server import MCPServer
server = MCPServer(name="logios")
server.add_tool_provider(mcp_server)
server.start()
```

### Available tools

| Tool | Description |
|---|---|
| `logios_recall` | Semantic search over long-term memory |
| `logios_store` | Store a memory (standard, identity, checkpoint, or manual) |
| `logios_forget` | Revoke memories matching a query |
| `logios_knowledge` | List all identity memories |
| `logios_digest` | Show unused, low-relevance, and recent checkpoint memories |

### ZeroClaw Gateway config

In `zeroclaw.yaml`:

```yaml
mcpServers:
  logios:
    command: python
    args:
      - -m
      - app.integrations.zeroclaw
      - --url
      - http://localhost:8000
      - --key
      - tok_your_api_key
```

---

## Shared Concepts

### Identity memories

All integrations fetch identity memories (`type='identity'`) on every context load. These are **persistent human-authored instructions** — never modified by agents, owner-only writes.

Owner creates identity memories via:

```bash
curl -X POST http://localhost:8000/memories/identity \
  -H "Authorization: Bearer tok_your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"content": "You are a Python expert. Always use type hints."}'
```

### Session scoping

`session_id` scopes episodic memories to a specific conversation thread. Two agents with different session IDs have isolated memory contexts.

### API key

Get your API key from Logios Brain's owner dashboard at `http://localhost:8000`. All integrations require it as the `Authorization: Bearer` header.

### Redis (working memory)

Hermes, Claude Agent SDK, and ZeroClaw integrations use Redis to buffer tool call results before snapshotting. Ensure Redis is available at the `redis_url` you provide.

For integrations that don't use Redis (OpenClaw, Pi, GoClaw), no Redis dependency is required.

---

## Troubleshooting

### `401 Unauthorized`

Your API key is invalid or missing. Ensure you're passing the correct key from Logios Brain's owner setup.

### No memories returned

Check that:
1. Logios Brain is running and accessible at `api_base_url`
2. You've created some memories via `POST /memories/remember` or the `/remember` command
3. `session_id` matches the session you're querying

### Redis connection errors

For Hermes and Claude Agent SDK integrations, ensure Redis is running:

```bash
docker compose up -d redis
```

Or provide the correct `redis_url` parameter.

### Snapshot threshold too high/low

`snapshot_threshold` controls how many tool calls fire before a checkpoint is written. If you get too many memories, increase it. If you lose too much context between snapshots, decrease it.

### Import errors

If importing from `app.integrations` fails, ensure the Logios Brain source is on your `PYTHONPATH`:

```python
import sys
sys.path.insert(0, "/path/to/logios-brain/app")
```

Or install as a package: `pip install -e /path/to/logios-brain`
