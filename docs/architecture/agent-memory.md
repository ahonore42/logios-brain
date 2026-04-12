# Agent Memory Architecture

How leading agent frameworks handle memory persistence, checkpoints, and session continuity.

---

## Hermes Agent (NousResearch)

**Repository**: https://github.com/NousResearch/hermes-agent

### Memory System

Provider-based architecture. A `MemoryManager` coordinates one built-in provider + one external plugin:

- `on_turn_start()` — per-turn tick with runtime context
- `on_session_end()` — end-of-session extraction
- `on_pre_compress()` — gather context before compression
- `on_memory_write()` — mirror writes to external providers

The built-in provider uses **FTS5 SQLite full-text search** over session messages.

### Checkpoint System

`CheckpointManager` — automatic git-based filesystem snapshots:

- Snapshots taken **before file-mutating operations**, not on agent request
- One snapshot per directory per turn maximum (deduplication via `_new_turn()`)
- Stores as isolated git repos in `~/.hermes/checkpoints/{sha256(dir)[:16]}/`
- Uses `GIT_DIR` + `GIT_WORK_TREE` to isolate from user's project git
- `ensure_checkpoint(dir, reason)` — takes snapshot if not already done this turn
- `list_checkpoints(dir)` / `diff(dir, hash)` / `restore(dir, hash, file?)`
- Max 50,000 files, skips root/home directories
- **Server-controlled, not agent-called**

### Session Persistence

- `SessionDB` in `hermes_state.py` — SQLite with WAL mode
- `BEGIN IMMEDIATE` for writer lock contention detection
- WAL checkpoints every 50 writes (PASSIVE mode)
- Session metadata, token counts, billing info, titles
- Parent-child session chains for compression-triggered splitting
- Thread-safe with Python locks

### Context Compression

`ContextCompressor` runs automatically when approaching model token limits.

---

## OpenClaw

**Repository**: https://github.com/openclaw/openclaw
**Docs**: https://docs.openclaw.ai

### Memory System

Session-level commands:

- `/compact` — summarize and compress context history
- `/prune` — prune old history
- Session tree enables navigation to any past state

Gateway WebSocket control plane persists sessions with presence and routing.

### Checkpoint System

Tree-structured sessions — all branches in one file, navigable via `/tree`:

- `/tree` — navigate to any previous point in the session tree
- `/fork` — branch from current point into new session
- Branching IS the checkpoint mechanism — no explicit snapshot call needed
- All history preserved in place; can return to any prior node

### Session Persistence

Sessions stored via Gateway WebSocket control plane. Per-session config: `thinkingLevel`, `verboseLevel`, `model`, `sendPolicy`, `groupActivation`. Workspace isolation per agent.

---

## Pi Coding Agent

**Site**: https://shittycodingagent.ai/
**Repository**: https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent

### Memory System

- **Compaction** — auto-summarizes older messages when approaching context limits. Triggered automatically or via `/compact` command.
- Extensions can inject memory via hooks: "inject messages before each turn, filter history, implement RAG, build long-term memory"
- Project-level `AGENTS.md` and `SYSTEM.md` for persistent instructions

> "Compaction is lossy. The full history remains in the JSONL file; use /tree to revisit."

### Checkpoint System

Tree-structured sessions — branching IS the checkpoint:

- `/tree` — navigate to any previous point in the session tree
- `/fork` — fork current branch into new session file
- All branches coexist in a single JSONL file per session
- No explicit checkpoint call needed
- History is append-only; can navigate to any prior state

### Session Persistence

JSONL files in `~/.pi/agent/sessions/`, organized by working directory:

```
pi -c          continue most recent session
pi -r          browse and select past session
pi --no-session ephemeral mode (no persistence)
pi --session <path> specific session
pi --fork <path>  fork a session
```

---

## GoClaw

**Site**: https://goclaw.sh/
**Repository**: https://github.com/nextlevelbuilder/goclaw

### Memory System

Three distinct tiers with **progressive loading** (L0/L1/L2):

- **Working Memory** — current conversation context, short-lived
- **Episodic Memory** — session summaries for longer-term recall
- **Semantic Memory** — knowledge graph for conceptual understanding

The pipeline has a dedicated **memory stage** (captures relevant context) followed immediately by a **summarize stage** (consolidates learned information for future reference). Both stages run on every agent turn as consecutive pipeline steps.

**Knowledge Vault** — document registry with `[[wikilinks]]` for bidirectional linking, hybrid search combining BM25 full-text and semantic (pgvector) retrieval, filesystem synchronization keeps the vault consistent with on-disk files.

### Checkpoint System

No explicit tree navigation or `/tree` equivalent found. GoClaw's memory consolidation happens as a **pipeline stage on every turn** — not a user-triggered or timeout-triggered compaction. The agent continuously summaries into episodic memory rather than waiting for a threshold to fire.

### Session Persistence

Multi-tenant PostgreSQL with per-user workspace isolation. Lite edition uses SQLite for local-only operation (up to 5 agents).

### Self-Evolution

Agents improve through a 3-stage guardrailed pipeline: **metrics collection → suggestion analysis → auto-adaptation**. Refines communication style and domain expertise via `CAPABILITIES.md` while maintaining core identity constraints (name and fundamental purpose never change).

### 8-Stage Agent Pipeline

```
context → history → prompt → think → act → observe → memory → summarize
```

Each stage is pluggable with always-on execution — enables granular control at each step.

### Key Distinction

GoClaw is the only framework with **continuous per-turn memory consolidation** rather than threshold-based compaction. Memory summarization is a pipeline stage, not a background job triggered on overflow. The 3-tier progressive loading (L0/L1/L2) also distinguishes it — the agent decides which tier to load from based on relevance scoring.

---

## ZeroClaw

**Site**: https://www.zeroclawlabs.ai/docs
**Repository**: https://github.com/zeroclaw-labs/zeroclaw

### Memory System

Memory tools: `recall`, `store`, `forget`, `knowledge`, `project intel`. The workspace injection system uses `MEMORY.md` for "long-term facts and lessons" — human-authored persistent context similar to Claude Code's `CLAUDE.md`. The web dashboard has a dedicated Memory section for browsing and managing entries. Memories can be migrated from OpenClaw.

### Checkpoint System

No explicit tree navigation or checkpoint command found. Memory consolidation is driven by the agent calling `store` and `forget` tools explicitly — there is no auto-triggered compaction documented. The agent decides what to write.

### Session Persistence

**Local-first Gateway** serves as HTTP/WS/SSE control plane managing sessions, presence, config, cron, webhooks, SOPs, and events. Configuration and cron jobs persist across restarts. Per-session security policy enforcement with autonomy levels.

### Autonomy Levels

Three levels with approval gating:

- `ReadOnly` — observe only, no mutations
- `Supervised` (default) — requires approval for medium/high risk operations
- `Full` — autonomous within policy bounds

Safety layers: workspace isolation, path traversal blocking, command allowlisting, forbidden paths (`/etc`, `/root`, `~/.ssh`), rate limiting (max actions/hour, cost/day caps), emergency shutdown.

### Multi-Agent Orchestration ("Hands")

Autonomous agent swarms that run on schedule and "grow smarter over time". Advanced tools: `delegate` (agent-to-agent), `swarm`, `model switch/routing`.

### SOPs

Standard Operating Procedures — event-driven workflow automation with MQTT, webhook, cron, and peripheral triggers.

### Key Distinction

ZeroClaw is the only framework with **explicit autonomy levels and approval gating** as a first-class security model. Memory is also the only one with a `forget` tool — the agent can actively unlearn, not just write. Built on OpenClaw-compatible architecture, inheriting its session model.

---

## NemoClaw

**Repository**: https://github.com/NVIDIA/NemoClaw
**Docs**: https://docs.nvidia.com/nemoclaw/latest/

### Memory System

NemoClaw has no independent memory system. It is a deployment and security wrapper around OpenClaw — memory and session management are inherited directly from OpenClaw (see above).

### Checkpoint System

No checkpoint system. NemoClaw's snapshot mechanism is for **sandbox migration** — transferring a running OpenClaw agent between host machines with credential stripping and integrity verification. This is infrastructure-level state transfer, not agent-level memory persistence.

### Session Persistence

Sessions are managed by OpenClaw's Gateway WebSocket control plane (see OpenClaw above). NemoClaw contributes:

- `~/.nemoclaw/sandboxes.json` — sandbox metadata registry
- `~/.nemoclaw/credentials.json` — provider credentials (not persisted to sandbox)
- `~/.openclaw/openclaw.json` — OpenClaw config, snapped/restored during migration

### Key Distinction

NemoClaw is an **infrastructure layer**, not an agent framework. It handles secure sandbox provisioning, network policy enforcement, and runtime migration — but delegates all memory and session behavior to OpenClaw.

---

## Claude Code

**Site**: https://claude.com/claude-code

### Memory System

Claude Code has two persistent memory mechanisms:

- **`/remember`** — explicit command for the agent to record something it wants to retain across sessions. The agent decides what to remember; there is no auto-extraction of facts.
- **Auto memory** — the agent periodically writes summaries of the current working state to `~/.claude/memory/` when it judges the information worth preserving.

**`CLAUDE.md`** — a human-written file in the project root that provides persistent instructions to the agent. This is the inverse of memory: it's human-authored context that the agent always has available, not agent-generated recollections.

### Checkpoint System

No explicit checkpoint API. Claude Code is session-based:

- Each session resumes from where the last one left off, with access to auto memory contents and `CLAUDE.md`.
- Sessions are not tree-structured — there is no built-in navigation to prior session states.
- The agent can explicitly request to start a fresh session, but no history is preserved in that new context.

### Session Persistence

Sessions stored locally in `~/.claude/projects/{project_id}/sessions/`. Each session file contains the full message history (prompt → response pairs). The agent can:

```
/chat <message>     continue current session
/new               start fresh session, preserving auto memory
```

---

## Claude Agent SDK

**Repository**: https://github.com/anthropics/claude-agent-sdk
**Docs**: https://docs.anthropic.com/en/docs/agent-sdk

### Memory System

The SDK is a framework for building custom agents, not a pre-built agent with its own memory. It provides storage **adapters** that developers implement:

- **Session store** — persist and resume session message history
- **Memory store** — long-term memory retrieval at turn start
- **Tool history** — log tool calls for later auditing

The SDK itself does not decide what to remember. Developers hook into `PostToolUse` and `PreToolUse` callbacks to capture tool results and decide what to write to their storage adapter.

### Checkpoint System

No built-in checkpoint mechanism. The SDK provides:

- **`before_tool_call(tool_name, input)`** — PreToolUse equivalent
- **`after_tool_call(tool_name, input, result)`** — PostToolUse equivalent

These are the natural injection points for buffering tool calls server-side (exactly the pattern described in the Logios Brain implications).

### Session Persistence

Session state is managed by the **client**, not the SDK. The SDK passes session ID to storage adapters; the adapter implementation decides the backing store (PostgreSQL, SQLite, file system, etc.).

---

## Common Patterns

### Checkpoint Triggers

| Agent | Trigger | Agent-called? |
|-------|---------|--------------|
| Hermes | Auto (before file mutations, per turn) | No |
| OpenClaw | User command or branching | No |
| Pi | Auto (on context overflow) + `/tree` | No |
| GoClaw | Continuous (per-turn pipeline stage) | No |
| ZeroClaw | Agent calls `store`/`forget` explicitly | Yes (opt-in) |
| Claude Code | None (session-based, agent uses `/remember`) | N/A |
| Claude Agent SDK | None (client decides via hooks) | N/A |
| NemoClaw | Inherited from OpenClaw | No |

### Memory Writes

All three frameworks treat memory as a background/auto process:
- Hermes: provider hooks, auto FTS5 indexing
- OpenClaw: gateway-persisted sessions, compaction on demand
- Pi: compaction is lossy but full history preserved; extensions handle long-term memory

### Session Models

- **Hermes**: SQLite WAL, parent-child chains, FTS5 search
- **OpenClaw**: WebSocket gateway, per-session config
- **Pi**: JSONL files, tree structure per session
- **GoClaw**: Multi-tenant PostgreSQL, 3-tier progressive memory loading
- **ZeroClaw**: Local-first Gateway HTTP/WS/SSE, OpenClaw-compatible
- **Claude Code**: Local session files, auto memory in `~/.claude/memory/`
- **Claude Agent SDK**: Client-controlled storage adapters, SDK-agnostic backing store
- **NemoClaw**: Inherited from OpenClaw + sandbox migration snapshots

### Key Insight

**Agents are bad at deciding what's worth remembering.** Auto-triggered compaction (Hermes, Pi) or tree navigation (Pi, OpenClaw) keeps the agent honest. The server controls when history is summarized, not the agent.

For custom agents built on the Claude Agent SDK, `PostToolUse` / `PreToolUse` hooks are the natural injection point — the SDK client (not the agent) decides what to buffer and when to write a memory. This is exactly the pattern Logios Brain should implement: server-side tool call buffering with auto-triggered snapshots on context overflow.

---

## Implications for Logios Brain

### What to Avoid

- Requiring agents to explicitly call `checkpoint()` — **all** frameworks except ZeroClaw use server-controlled triggers. ZeroClaw relies on the agent calling `store`/`forget` explicitly, which is opt-in but leaves memory quality to the agent's judgment
- One memory per session — sessions can last days/weeks, too sparse
- Recording every tool call — memory explosion, noisy retrieval

### Recommended Approach

**Auto-triggered structured snapshots:**

1. Server buffers tool calls per session in memory (or Redis)
2. On context overflow or configurable threshold (N calls / T minutes), server writes one memory with:
   - Structured summary: decisions made, facts asserted, key state changes
   - Full tool chain in metadata for reconstruction
   - Agent's own summary text if provided (optional, not required)
3. Agent continues immediately; buffer clears
4. Tree navigation: agent can review past checkpoints and continue from any point

**No timeout on checkpoints** — buffer indefinitely until auto-trigger fires. Agent can optionally annotate a checkpoint with a summary comment, but the server owns the trigger.

**One memory per meaningful work unit**, not per session and not per tool call.
