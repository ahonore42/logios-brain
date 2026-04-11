# MCP Server Architecture

## Overview

Logios Brain exposes its capabilities as an MCP server. Agents (Claude Code, Claude Desktop, custom agents) connect via the MCP protocol to discover and invoke tools — `remember`, `search`, `graph_search`, `assert_fact`, `get_fact`, `run_skill` — without making raw HTTP calls. The MCP server acts as the canonical interface for all agent-to-brain interaction.

## Why MCP

MCP gives agents:
- **Tool discovery** — agents call `tools/list` and receive a typed manifest of every available tool with input schemas
- **Structured invocation** — agents call `tools/call` with typed arguments; responses are structured content arrays
- **Transport neutrality** — works over Streamable HTTP (remote) or stdio (local); the protocol is the same either way
- **Client ecosystem** — Claude Code, Claude Desktop, Cursor, VS Code, and any MCP-compatible host already speaks this protocol

The alternative — a custom REST client library per agent — requires each agent to hardcode or dynamically load route paths, auth headers, and request shapes. MCP collapses that to one connection with a known protocol.

## Transport

**Streamable HTTP** is the transport for Logios Brain. It runs on the same VPS as the existing FastAPI server, accessible at `https://<host>/mcp`.

- HTTP POST from client to server carries JSON-RPC requests
- SSE (Server-Sent Events) from server to client carries responses and server-initiated notifications
- Session IDs (`MCP-Session-Id` header) maintain stateful context across requests
- Auth is bearer token via `Authorization: Bearer <LOGIOS_BRAIN_KEY>` on every request

stdio transport is not used — Logios Brain is a remote server, not a local subprocess launched by the agent.

## Primitives Exposed

### Tools

| Tool | Description |
|---|---|
| `remember` | Store a memory in all three stores. Wraps `POST /memories/remember`. |
| `search` | Semantic vector search over memories. Wraps `POST /memories/search`. |
| `recall` | Structured recall by source and/or date range. Wraps `POST /graph/recall`. |
| `graph_search` | Traverse the knowledge graph from a named entity. Wraps `POST /graph/search`. |
| `assert_fact` | Manually assert a Fact into the graph with optional REPLACES link. Wraps `POST /graph/facts`. |
| `get_fact` | Retrieve a Fact by ID, resolved through its REPLACES chain. Wraps `GET /graph/facts/{id}`. |
| `run_skill` | Execute a skill with evidence context. Wraps `POST /skills/run_skill`. |

### Resources

| Resource URI | Description |
|---|---|
| `logios://schema/tools` | Tool manifest — current list of all tools with input/output schemas. Agents read this at session start to understand available operations. |
| `logios://health` | Server health status |

Prompts are not currently exposed.

## Auth

The MCP server uses **bearer token authentication** via Streamable HTTP:

- Every request from the agent includes `Authorization: Bearer <LOGIOS_BRAIN_KEY>`
- The MCP server validates the token on every request before processing
- The token is the same `LOGIOS_BRAIN_KEY` env var used by the REST API — no separate MCP credential
- Failed auth returns HTTP 401 with a `WWW-Authenticate` header

This is simpler than OAuth 2.1 and appropriate for a single-user personal deployment. The key is the access boundary — whoever holds the key has full read/write access to the brain.

## Relationship to Existing REST API

The REST API (`app/main.py`) and the MCP server coexist as two faces of the same service:

```
Agent (MCP client)
  └─► MCP Server (Streamable HTTP)
        └─► Tool handlers call existing route logic
              ├─► Postgres (memories, chunks, skills, evidence)
              ├─► Qdrant (vector search)
              └─► Neo4j (graph, facts, entities)
```

The MCP server is a routing and translation layer on top of the existing write/read logic. It does not duplicate business logic — it wraps it. Agents get MCP tool discovery and invocation; direct clients (scripts, other services) continue using REST.

## Session Model

The Streamable HTTP transport supports optional sessions:

- The server may assign an `MCP-Session-Id` header on the `InitializeResult` response
- If assigned, all subsequent requests must include it
- Sessions allow the server to correlate requests without requiring the client to manage cookies or tokens beyond the bearer auth

For Logios Brain's single-user deployment model, sessions are optional. Auth is the primary security boundary; session IDs add correlation context for debugging and audit trails.

## Tool Definitions

### `remember`

```json
{
  "name": "remember",
  "description": "Store a memory in all three stores. Embeds the content, writes to Postgres, Qdrant, and Neo4j, then extracts entities.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "content": {
        "type": "string",
        "description": "The memory content — a self-contained statement any AI can understand with zero prior context"
      },
      "source": {
        "type": "string",
        "enum": ["telegram", "claude", "agent", "manual", "import", "system"],
        "default": "manual",
        "description": "Where the memory originated"
      },
      "session_id": {
        "type": "string",
        "description": "Optional UUID to group this memory with a session"
      },
      "metadata": {
        "type": "object",
        "description": "Optional key-value settings (importance, confidence, revoked, valid_until, policy_version)"
      }
    },
    "required": ["content"]
  }
}
```

### `search`

```json
{
  "name": "search",
  "description": "Semantic vector search over memories using cosine similarity.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": { "type": "string" },
      "top_k": { "type": "integer", "default": 10 },
      "threshold": { "type": "number", "default": 0.65 }
    },
    "required": ["query"]
  }
}
```

### `recall`

```json
{
  "name": "recall",
  "description": "Structured recall of memories by source and/or date range.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "source": { "type": "string", "description": "Filter by source (e.g. 'telegram', 'claude')" },
      "since": { "type": "string", "description": "ISO date string — only memories captured after this date" },
      "limit": { "type": "integer", "default": 20 }
    }
  }
}
```

### `graph_search`

```json
{
  "name": "graph_search",
  "description": "Traverse the Neo4j knowledge graph from a named entity to all reachable MemoryChunks and Facts.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "entity_name": { "type": "string" },
      "depth": { "type": "integer", "default": 2 }
    },
    "required": ["entity_name"]
  }
}
```

### `assert_fact`

```json
{
  "name": "assert_fact",
  "description": "Manually assert a Fact into the graph. Optionally links to an existing Fact via REPLACES for version chains.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "content": { "type": "string" },
      "valid_from": { "type": "string", "description": "ISO datetime when this fact becomes valid" },
      "valid_until": { "type": "string", "description": "Optional ISO datetime when this fact expires" },
      "version": { "type": "integer", "default": 1 },
      "replaces_id": { "type": "string", "description": "Optional ID of the Fact this newer Fact supersedes via REPLACES" }
    },
    "required": ["content", "valid_from"]
  }
}
```

### `get_fact`

```json
{
  "name": "get_fact",
  "description": "Retrieve a Fact by ID, resolved through its REPLACES chain. Returns the newest valid Fact.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "fact_id": { "type": "string", "description": "The prefixed Fact ID (e.g. 'fact:<uuid>')" }
    },
    "required": ["fact_id"]
  }
}
```

### `run_skill`

```json
{
  "name": "run_skill",
  "description": "Execute a skill with evidence context — loads relevant memories, builds evidence manifest, returns prompt + context for local execution.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "skill_name": { "type": "string" },
      "context": { "type": "object", "description": "Skill-specific context dict (query, entity, etc.)" },
      "model": { "type": "string", "default": "unknown" },
      "machine": { "type": "string", "default": "unknown" }
    },
    "required": ["skill_name"]
  }
}
```

## Security Considerations

- **Bearer token**: Whoever has `LOGIOS_BRAIN_KEY` has full read/write access. Treat it like a password.
- **DNS rebinding**: The Streamable HTTP transport requires Origin header validation. Servers MUST reject requests with invalid Origin headers.
- **No token audience enforcement** in the single-key model. If multi-tenancy is added later, each key would need scope/audience validation.
- **Localhost binding**: When running the MCP server locally, bind to `127.0.0.1` only, not `0.0.0.0`.

## Implementation

The MCP server is built with the official `mcp` Python SDK (`mcp.server.fastmcp.FastMCP`). It:

1. mounts at `/mcp` as a FastAPI route on the existing app
2. uses `streamable-http` transport
3. wraps existing route logic via tool decorators
4. validates `LOGIOS_BRAIN_KEY` on every request via a middleware guard

Dependencies: `mcp[cli]` added to `pyproject.toml`.

## Future Extensions

- **OAuth 2.1** — if multi-user access is added, replace bearer token with OAuth authorization code flow
- **Prompts** — expose reusable prompt templates (weekly_review, memory_migration) as MCP prompts
- **Resources** — expose memory content via `memory://{memory_id}` resource URIs
- **Per-agent key mapping** — if multiple agents are registered, derive `agent_id` from the bearer key and record it on EvidencePath nodes
