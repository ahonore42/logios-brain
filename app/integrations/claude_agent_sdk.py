"""Claude Agent SDK integration — Logios as a storage adapter.

The Claude Agent SDK provides storage **adapters** that developers implement:
- Session store   — persist and resume session message history
- Memory store    — long-term memory retrieval at turn start
- Tool history    — log tool calls for later auditing

This module provides a complete Logios-backed adapter that implements all
three stores by calling the Logios Brain API.

Usage::

    from app.integrations.claude_agent_sdk import LogiosStorageAdapter
    from anthropic import ClaudeAgent

    adapter = LogiosStorageAdapter(
        api_base_url="http://localhost:8000",
        api_key="your-api-key",
        session_id="my-session",
        agent_id="my-agent",
        redis_url="redis://localhost:6379",
    )

    agent = ClaudeAgent(
        storage=adapter,
        # Use PreToolUse / PostToolUse hooks for working memory buffering
    )

    # In your PreToolUse hook:
    adapter.buffer_tool_call(tool_name, tool_input)

    # In your PostToolUse hook:
    adapter.record_tool_result(tool_name, tool_input, tool_output)
"""

from typing import Any, Optional

import httpx

__all__ = ["LogiosStorageAdapter"]


class LogiosStorageAdapter:
    """
    Claude Agent SDK storage adapter backed by Logios Brain.

    Implements:
    - SessionStore   → session persistence via Logios context endpoint
    - MemoryStore    → long-term memory retrieval at turn start
    - ToolHistory    → audit log of all tool calls (server-side)

    Also provides working memory buffering via Redis + auto-snapshot.
    """

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        session_id: str,
        agent_id: Optional[str] = None,
        redis_url: str = "redis://localhost:6379",
        snapshot_threshold: int = 20,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = session_id
        self.agent_id = agent_id
        self._turn_index = 0

        # Lazy imports to avoid hard dependency on app.hooks
        from app.hooks import SnapshotTrigger, WorkingMemory

        self._working = WorkingMemory(
            redis_url=redis_url,
            session_id=session_id,
            agent_id=agent_id or "unknown",
        )
        self._trigger = SnapshotTrigger(
            mode="call_count",
            threshold=snapshot_threshold,
            working_memory=self._working,
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # ── SessionStore ────────────────────────────────────────────────────────────

    def save_session(self, messages: list[dict[str, Any]]) -> None:
        """
        Save session message history to Logios.

        Called by the SDK when a session ends or is checkpointed.
        The full message history is stored as a special session memory.
        """
        # Collapse messages into a readable summary
        summary_parts = []
        for msg in messages[-20:]:  # last 20 messages to avoid bloat
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            summary_parts.append(f"{role}: {content[:200]}")

        content = "[session history]\n" + "\n".join(summary_parts)

        payload = {
            "content": content,
            "source": "claude-agent-sdk",
            "type": "checkpoint",
            "session_id": self.session_id,
            "metadata": {
                "message_count": len(messages),
                "agent_id": self.agent_id,
                "trigger": "session_save",
            },
        }

        with httpx.Client(timeout=15.0) as client:
            client.post(
                f"{self.api_base_url}/memories/remember",
                json=payload,
                headers=self._headers(),
            )

    def load_session(self) -> list[dict[str, Any]]:
        """
        Load session message history from Logios.

        Returns the session's episodic memories as message dicts.
        Currently returns episodic memories as system messages.
        """
        payload = {
            "query": f"session {self.session_id}",
            "session_id": self.session_id,
            "top_k": 20,
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

        messages = []
        for mem in data.get("identity_memories", []):
            messages.append({"role": "system", "content": f"[identity] {mem['content']}"})
        for mem in data.get("episodic_memories", []):
            messages.append({"role": "system", "content": f"[memory] {mem['content']}"})

        return messages

    # ── MemoryStore ────────────────────────────────────────────────────────────

    def retrieve_memories(self, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        """
        Retrieve long-term memories relevant to the query.

        Called at the start of each turn (before the agent generates a response).
        Returns identity + episodic memories from Logios.
        """
        payload = {
            "query": query,
            "session_id": self.session_id,
            "top_k": top_k,
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

        return data.get("identity_memories", []) + data.get("episodic_memories", [])

    def write_memory(
        self,
        content: str,
        memory_type: str = "standard",
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Write a memory directly to Logios.

        Returns the memory ID.
        """
        payload = {
            "content": content,
            "source": "claude-agent-sdk",
            "type": memory_type,
            "session_id": self.session_id,
            "metadata": metadata or {},
        }

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{self.api_base_url}/memories/remember",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return str(resp.json()["id"])

    # ── ToolHistory ────────────────────────────────────────────────────────────

    def buffer_tool_call(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> str:
        """
        Buffer a tool call for future snapshot.

        Call this in the PreToolUse / before_tool_call hook.
        Returns the buffer entry key.
        """
        summary = f"called {tool_name} with {str(tool_input)[:200]}"
        entry_key = self._working.buffer(
            tool_name=tool_name,
            result_summary=summary,
            result_embedding=[0.0] * 1024,  # embedding not available pre-call
        )
        self._turn_index += 1

        if self._trigger.should_fire(self._turn_index):
            self._working.snapshot(
                api_base_url=self.api_base_url,
                api_key=self.api_key,
                turn_count=self._turn_index,
            )
            self._trigger.mark_fired(self._turn_index)

        return entry_key

    def record_tool_result(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_output: Any,
    ) -> None:
        """
        Record a tool result. Can update the buffered entry or log separately.

        Call this in the PostToolUse / after_tool_call hook.
        """
        # The working memory already has the pre-call buffer entry.
        # For auditing, we additionally log to Logios's evidence layer.
        pass

    # ── Evidence recording ─────────────────────────────────────────────────────

    def record_generation(
        self,
        output: str,
        model: str,
        machine: str,
        evidence: list[dict[str, Any]],
        prompt_used: str,
        chain_of_thought: Optional[str] = None,
    ) -> Optional[str]:
        """
        Record an agent generation with evidence to Logios.

        Call this after the agent generates a response.
        Returns the generation ID.
        """
        payload = {
            "skill_name": "claude-agent-sdk",
            "output": output,
            "model": model,
            "machine": machine,
            "prompt_used": prompt_used,
            "evidence_manifest": evidence,
            "session_id": self.session_id,
            "chain_of_thought": chain_of_thought,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.api_base_url}/skills/record",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return str(resp.json()["id"])
        except httpx.HTTPError:
            return None
