# Memory System Architecture

How Logios Brain captures, stores, and retrieves agent memory across sessions, and how evidence chains serve as the agent's own episodic memory.

---

## Design Principles

### 1. Agents are bad at deciding what's worth remembering

Every leading agent framework that relies on the agent to call a checkpoint or memory-write function fails at this. ZeroClaw's `store`/`forget` tools are the outlier, and memory quality under that model depends entirely on the agent's judgment.

Logios fires memory writes **without the agent's knowledge or consent.** The agent cannot prevent a snapshot and cannot request one. The server controls the trigger.

### 2. Memory writes are server-controlled; retrieval is agent-controlled

The agent can query Logios at any time via `/memories/search` and `/graph/search`. The agent can also use `forget()` to apply negative filters to its own retrieval — "don't surface memories matching X in future context windows." These filters only affect retrieval; they do not delete data.

The agent has no mechanism to call `/memories/remember` directly.

### 3. Evidence is the agent's own memory, not just a human audit tool

The evidence layer answers: "what did I do, why did I do it, and what was I thinking?" For the human, it's traceability. For the agent, it's episodic memory of its own actions.

### 4. Improvement flows through human review, not agent self-modification

No path exists for the agent to write `type='identity'` memories. Behavioral evolution requires a human to read evidence and create or update identity memories. The evidence layer makes that review possible.

---

## Three-Tier Memory Model

| Tier | Name | Store | Content | Memory type | Lifetime |
|------|------|-------|---------|-------------|----------|
| 1 | Working | Redis | Buffered tool call results | — (ephemeral) | Per-session, cleared on snapshot |
| 2 | Episodic | Postgres + Qdrant | Structured snapshots + evidence paths | `type='checkpoint'` | Persistent |
| 3 | Semantic | Neo4j | Entity graph from entity extraction | — (entities table) | Persistent |

This maps directly onto GoClaw's memory architecture, adapted for Logios's existing stores.

**Memory `type` column** — all memories in Postgres carry a `type` field:

| Type | Description | Written by | Loaded at session start |
|------|-------------|------------|------------------------|
| `standard` | General memories, events, facts | System, hook library | No — retrieved on query |
| `identity` | Core agent instructions | Human only | Yes, always — read-only |
| `checkpoint` | Episodic snapshots | Hook library (server-triggered) | No — retrieved on query |
| `manual` | Human written directly | Human via API | No — retrieved on query |

`type='identity'` memories are the persistent instruction layer — human-authored, always injected at session start, never modified by the agent. This replaces any file-based `BRAIN.md` approach.

---

## Tier 1 — Working Memory (Redis)

The hook library buffers every tool call result in Redis before a snapshot fires.

**Buffered entry shape:**

```json
{
  "session_id": "sess_abc123",
  "agent_id": "agent_xyz",
  "tool_name": "read_file",
  "result_summary": "600-line auth/middleware.py, extracted key routes: POST /auth/setup, POST /auth/verify, POST /auth/refresh",
  "result_embedding": [4096-dim vector],
  "raw_result_ref": "redis:working:sess_abc123:tool:0001",
  "timestamp_utc": "2026-04-12T14:23:01Z",
  "turn_index": 14,
  "forget_patterns": []
}
```

`result_summary` is a short text description extracted from the raw result — not the full output. The full output stays in Redis under `raw_result_ref` for reconstruction if needed.

**Forget filters** are stored per-session in Redis. When the agent calls `forget("*.py")`, all buffered entries with `tool_name` matching that pattern have their `forget_patterns` list appended. Matching entries are excluded from the snapshot and from retrieval queries. This only affects retrieval — the raw result is still in Redis until the snapshot fires.

---

## Tier 2 — Episodic Memory (Postgres + Qdrant)

When the trigger fires, the hook library synthesizes buffered entries into one memory and calls `POST /memories/remember`.

**Snapshot contents:**

```json
{
  "content": "Refactored auth package: moved token hashing to auth/security.py, pending OTP to auth/pending.py, middleware to auth/middleware.py. auth/__init__.py now only re-exports. Dataclass models PendingSetup and AuthContext moved to schemas.py. 17 files changed across app/auth/, app/routes/, tests/. Key decisions: Form(...) params stay in routes (not Pydantic models), dataclasses converted to plain __init__ classes in schemas.py.",
  "embedding": [4096-dim vector],
  "metadata": {
    "type": "checkpoint",
    "session_id": "sess_abc123",
    "agent_id": "agent_xyz",
    "tool_calls": [
      {"tool": "read_file", "result_ref": "redis:working:sess_abc123:tool:0001"},
      {"tool": "read_file", "result_ref": "redis:working:sess_abc123:tool:0002"},
      {"tool": "git_diff", "result_ref": "redis:working:sess_abc123:tool:0003"}
    ],
    "turn_count": 14,
    "snapshot_trigger": "token_threshold",
    "agent_annotation": null
  }
}
```

**Evidence path** is also written to Neo4j at this point, linking the snapshot into the agent's episodic history (see Evidence as Episodic Memory below).

**Trigger conditions (server-side, not agent-controlled):**

| Trigger | Description |
|---------|-------------|
| `token` | Agent framework measures context length; fires at N% of limit |
| `call_count` | Fires every N tool calls regardless of token count |
| `time_based` | Fires if N minutes have passed since last snapshot |

Trigger logic lives in the hook library client (`SnapshotTrigger`) and is also available server-side via `POST /hooks/check`.

**Agent annotation** is optional. The hook library can prompt the agent (via the agent framework) to provide a one-line summary before the snapshot fires. If provided, it goes into `metadata.agent_annotation`. If the agent doesn't respond within a timeout, the snapshot fires without it.

---

## Tier 3 — Semantic Memory (Neo4j)

Entity extraction runs as a Celery task after a memory is written. `POST /memories/remember` dispatches the chain: Qdrant write → Neo4j write → entity extraction.

The entity extraction LLM (phi-3-mini) reads the memory content and extracts named entities with relationship types. These become nodes in Neo4j — the agent's **semantic memory** of what concepts, projects, people, and decisions exist and how they relate.

The agent queries this at turn start via `/graph/search` — "what projects are connected to this decision?" — rather than retrieving full memories.

---

## Evidence as Episodic Memory

Evidence paths serve two audiences:

1. **Human audit** — trace why a generation was produced, which memories informed it
2. **Agent's own episodic memory** — the agent navigating its own history

**Evidence path written on `POST /skills/record`:**

```
EvidencePath {id, generation_id, agent_id, machine_id, timestamp_utc}
  └── EvidenceStep {id, step_type, content, rank}
        ├── NEXT → EvidenceStep (ordered chain: read_memory → query_policy → merge_context → generate_output)
        ├── USED → MemoryChunk (read from episodic tier)
        ├── FOLLOWED → [Relationship type] (e.g. :RELATES_TO from semantic tier)
        └── PRODUCED → Output (the generation itself)
```

**What makes evidence agent-usable:**

The `content` field of each `EvidenceStep` should capture the agent's chain of thought if exposed by the framework. Not just "read memory 3" but "read memory 3 because it contained prior decision to use Form() in routes, not Pydantic models."

The agent can then answer:
- "Why did I choose that approach?" → look at the EvidenceStep chain for that generation
- "What was I working on when I built the auth system?" → query evidence paths by topic/memory content
- "What changed between session A and session B?" → diff two evidence paths

**Bidirectional retrieval:**

```
Human asks agent a question
    ↓
Agent detects self-referential query ("what did I do last time?")
    ↓
Agent calls GET /skills/evidence?generation_id=X
    ↓
Evidence path returned with full step chain and memory content
    ↓
Agent answers from its own evidence
```

`/skills/evidence` is already implemented. It returns a generation plus enriched evidence records with full memory content. The hook library exposes this to the agent when the query is self-referential.

---

## Hook Library

The hook library (`app/hooks/`) provides both a client-side Python package and a server-side HTTP API for working memory:

### Client-side package (`app/hooks/`)

```python
from app.hooks import WorkingMemory, SnapshotTrigger, GenerationRecord, record_generation

working = WorkingMemory(redis_url=REDIS_URL, session_id="sess_abc123", agent_id="agent_xyz")
trigger = SnapshotTrigger(mode="call_count", threshold=20, working_memory=working)

# After each tool call
working.buffer("read_file", summarize(result), embedding)

# Check if trigger fired
if trigger.should_fire(current_turn=14):
    working.snapshot(api_base_url="http://localhost:8000", api_key=AGENT_TOKEN, trigger_mode="call_count")
    trigger.mark_fired(14)

# Record a generation with evidence
record_generation(
    api_base_url="http://localhost:8000",
    api_key=AGENT_TOKEN,
    record=GenerationRecord(skill_name="analysis", output=output, model="...", ...),
)
```

### Server-side HTTP API (`POST /hooks/*`)

Agents that don't want to run their own Redis can use the server-side hooks API instead:

```bash
# Register a trigger
POST /hooks/trigger  {session_id, agent_id, mode, threshold}

# Buffer a tool result
POST /hooks/buffer  {session_id, agent_id, tool_name, result_summary, turn_index}

# Check if trigger fired — synthesizes snapshot and POSTs to /memories/remember if so
POST /hooks/check  {session_id, agent_id, current_turn, token_percent}

# Drain buffer without snapshotting
POST /hooks/flush  {session_id, agent_id}

# Force a snapshot regardless of trigger
POST /hooks/snapshot  {session_id, agent_id, turn_count, annotation}
```

This allows fully server-side working memory — the agent only needs an HTTP client and a Bearer token.

### Registration

The hook library registers with the agent framework's native hooks:

| Framework | Hook point |
|-----------|------------|
| Claude Agent SDK | `after_tool_call`, `before_tool_call` |
| Hermes Agent | `on_turn_start`, `on_memory_write` |
| OpenClaw | Extension hook (injected before each turn) |
| Pi Coding Agent | Extension hook |

For agents without a formal hook API (Claude Code), the hook library runs as a sidecar process that proxies tool calls and intercepts results.

---

## Evidence-Driven Improvement (Human in the Loop)

Improvement requires human review. No path exists for the agent to modify its own instructions.

**What Logios records that enables this:**

- Every generation's evidence path: which memories were retrieved, which were used in the final output
- Memory usage frequency: which memories are retrieved repeatedly vs. never
- Tool call patterns: which tools consistently produce useful results

**What a human can do with this:**

| Signal | Action |
|--------|--------|
| Memory never retrieved | Candidate for deletion or rewrite |
| Memory consistently retrieved | Promoted to `BRAIN.md` as persistent instruction |
| Tool always useful | Increase its weight in retrieval ranking |
| Agent confidently wrong in output | Update the memory that informed the wrong decision |

**Memory digest (future):**

A periodic email digest summarizing:
- New memories created this week
- Memories that were never retrieved
- Evidence paths with low confidence scores

The human reviews and decides whether to create or update `type='identity'` memories or adjust hook library thresholds.

**GoClaw's self-evolution** (metrics → suggestions → auto-adaptation) is the long-term model, but only with human approval gates on every adaptation step. Logios has the evidence data to support this once enough history exists.

---

## Data Flow Summary

```
Agent calls tool
    ↓
working.buffer(tool_name, result_summary, embedding)
    ↓
Trigger fires (token %, call count, or time)
    ↓
POST /memories/remember
    ├── Writes to Postgres (ledger)
    ├── Writes to Qdrant (embedding)
    ├── Writes EvidencePath to Neo4j
    └── Celery: extract_entities → Neo4j (semantic memory)
    ↓
Redis working memory buffer cleared
    ↓
Agent's next turn:
    POST /memories/context
        ├── Identity: always loaded first
        ├── Episodic: Qdrant search on session memories → top-K
        └── Semantic: Neo4j graph traversal from query entities
    ↓
Agent generates output
    ↓
POST /skills/record — evidence path written (what memories used, chain of thought)
    ↓
Human (optionally) reviews evidence, creates or updates type='identity' memories
    ↓
Agent loads identity memories on session start — improved behavior
```

---

## What Logios Does Not Do

- **No agent self-modification** — the agent cannot write `type='identity'` memories; only the owner can create or update them
- **No automatic behavioral adaptation** — improvements require human review
- **No trust placed in the agent's memory quality** — the server owns what gets written
