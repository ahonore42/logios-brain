"""Hermes Agent integration — implements Hermes MemoryManager provider interface.

Hermes uses a provider-based memory architecture where a MemoryManager coordinates
one built-in FTS5 SQLite provider + one external plugin. This module provides a
Logios-backed external provider.

Hook points:
- on_turn_start()    → inject identity + episodic memories from Logios
- on_session_end()   → flush any buffered working memory to Logios
- on_pre_compress()   → provide relevant memories for compression context
- on_memory_write()   → mirror writes to Logios (if agent writes to memory)

Usage::

    from app.integrations.hermes import connect
    memory_manager = connect("http://localhost:8000", "your-api-key")
    agent = HermesAgent(external_memory_manager=memory_manager)
"""

from typing import Any, Optional

import httpx

from app.hooks import WorkingMemory, SnapshotTrigger


class LogiosMemoryManager:
    """
    Hermes MemoryManager provider backed by Logios Brain.

    Implements the full MemoryManager interface expected by Hermes Agent.
    Buffers tool call results via WorkingMemory and fires snapshots on
    server-controlled thresholds.
    """

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        session_id: str,
        agent_id: str,
        redis_url: str,
        snapshot_threshold: int = 20,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = session_id
        self.agent_id = agent_id

        self._working = WorkingMemory(
            redis_url=redis_url,
            session_id=session_id,
            agent_id=agent_id,
        )
        self._trigger = SnapshotTrigger(
            mode="call_count",
            threshold=snapshot_threshold,
            working_memory=self._working,
        )
        self._turn_index = 0

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ── MemoryManager interface ────────────────────────────────────────────────

    def on_turn_start(
        self, runtime_context: Optional[dict[str, Any]] = None
    ) -> list[dict]:
        """
        Called at the start of each agent turn.

        Fetches identity memories (always injected) and episodic memories
        relevant to the current query from Logios.
        """
        query = runtime_context.get("query", "") if runtime_context else ""
        if not query:
            query = f"session {self.session_id}"

        payload = {
            "query": query,
            "session_id": str(self.session_id),
            "top_k": 8,
            "include_identity": True,
        }

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{self.api_base_url}/memories/context",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        # Flatten into Hermes's expected format: list of memory dicts
        memories = []
        for mem in data.get("identity_memories", []):
            mem["_source"] = "identity"
            memories.append(mem)
        for mem in data.get("episodic_memories", []):
            mem["_source"] = "episodic"
            memories.append(mem)

        return memories

    def on_session_end(self) -> None:
        """
        Called when a session ends.

        Flushes any remaining working memory entries as a checkpoint to Logios.
        """
        if self._trigger.should_fire(self._turn_index):
            self._working.snapshot(
                api_base_url=self.api_base_url,
                api_key=self.api_key,
                turn_count=self._turn_index,
            )
            self._trigger.mark_fired(self._turn_index)

    def on_pre_compress(self, query: str) -> list[dict]:
        """
        Called before context compression.

        Returns memories relevant to the query so Hermes can include them
        in the compression context.
        """
        payload = {"query": query, "top_k": 10, "include_identity": False}

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{self.api_base_url}/memories/search",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def on_memory_write(self, content: str, metadata: Optional[dict] = None) -> str:
        """
        Called when the agent writes something to memory.

        Persists it to Logios as a standard memory record.
        Returns the memory ID.
        """
        payload = {
            "content": content,
            "source": "hermes",
            "type": "standard",
            "session_id": str(self.session_id),
            "metadata": metadata or {},
        }

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{self.api_base_url}/memories/remember",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()["id"]

    # ── Tool call buffering ─────────────────────────────────────────────────────

    def buffer_tool_result(
        self,
        tool_name: str,
        result_summary: str,
        result_embedding: list[float],
    ) -> str:
        """
        Buffer a tool result for future snapshot.

        Call this in Hermes's PostToolUse hook.
        Returns the buffer entry key.
        """
        entry_key = self._working.buffer(tool_name, result_summary, result_embedding)
        self._turn_index += 1

        if self._trigger.should_fire(self._turn_index):
            self._working.snapshot(
                api_base_url=self.api_base_url,
                api_key=self.api_key,
                turn_count=self._turn_index,
            )
            self._trigger.mark_fired(self._turn_index)

        return entry_key

    def forget(self, pattern: str) -> None:
        """
        Mark all buffered entries matching the pattern for forgetting.

        Call this in Hermes's PreToolUse hook to allow the agent to
        express what it wants to forget.
        """
        self._working.forget(pattern)


def connect(
    api_base_url: str,
    api_key: str,
    session_id: str,
    agent_id: str,
    redis_url: str = "redis://localhost:6379",
    snapshot_threshold: int = 20,
) -> LogiosMemoryManager:
    """
    Factory: build a Logios-backed Hermes MemoryManager.

    Args:
        api_base_url:  Logios Brain HTTP base (e.g. "http://localhost:8000")
        api_key:       API key for Logios
        session_id:    Unique session identifier (UUID string or str)
        agent_id:      Unique agent identifier (str)
        redis_url:     Redis URL for working memory buffer
        snapshot_threshold: Number of tool calls before auto-snapshot

    Returns:
        LogiosMemoryManager instance — pass to ``HermesAgent(...)``
    """
    return LogiosMemoryManager(
        api_base_url=api_base_url,
        api_key=api_key,
        session_id=session_id,
        agent_id=agent_id,
        redis_url=redis_url,
        snapshot_threshold=snapshot_threshold,
    )
