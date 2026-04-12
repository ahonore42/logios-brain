"""Pi Coding Agent integration — Logios as a Pi extension for long-term memory.

Pi Coding Agent supports extension hooks that can:
- Inject messages before each turn
- Filter history
- Implement RAG / long-term memory retrieval

This module provides a Pi extension that injects relevant Logios memories
into each turn's context, and snapshots working memory on compaction events.

Usage::

    from app.integrations.pi import LogiosExtension, connect
    extension = connect("http://localhost:8000", "your-api-key", session_id="my-session")
    pi_agent.register_extension("logios", extension)
"""

from typing import Any, Optional

import httpx

__all__ = ["connect", "LogiosExtension"]


class LogiosExtension:
    """
    Pi Coding Agent extension backed by Logios Brain.

    Implements the extension hook interface Pi Coding Agent expects:
    - pre_turn()     → inject identity + episodic memories before each turn
    - on_compact()   → snapshot buffered working memory when Pi compacts context
    - on_message()   → optionally persist noteworthy messages
    """

    name = "logios"
    description = "Long-term memory via Logios Brain"

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        session_id: str,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = session_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # ── Pi extension hooks ──────────────────────────────────────────────────────

    def pre_turn(self, turn_context: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Called before each agent turn.

        Returns a list of messages to inject into the conversation.
        Each message dict has ``role`` and ``content``.
        """
        query = turn_context.get("query", "")
        if not query:
            query = f"session {self.session_id}"

        payload = {
            "query": query,
            "session_id": self.session_id,
            "top_k": 6,
            "include_identity": True,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.api_base_url}/memories/context",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError:
            return []

        injected = []
        for mem in data.get("identity_memories", []):
            injected.append({
                "role": "system",
                "content": f"[identity] {mem['content']}",
            })
        for mem in data.get("episodic_memories", []):
            injected.append({
                "role": "system",
                "content": f"[memory] {mem['content']}",
            })
        return injected

    def on_compact(self, compaction_context: dict[str, Any]) -> Optional[str]:
        """
        Called when Pi auto-compacts context due to overflow.

        The agent's compressed summary is passed in the context.
        Persist it to Logios as a checkpoint.
        Returns the Logios memory ID.
        """
        summary = compaction_context.get("summary", "")
        turn_count = compaction_context.get("turn_count", 0)

        if not summary:
            return None

        payload = {
            "content": f"[checkpoint] {summary}",
            "source": "pi",
            "type": "checkpoint",
            "session_id": self.session_id,
            "metadata": {
                "turn_count": turn_count,
                "trigger": "pi_compact",
            },
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.api_base_url}/memories/remember",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return str(resp.json()["id"])
        except httpx.HTTPError:
            return None

    def on_message(self, message: dict[str, Any]) -> None:
        """
        Called after each message in the session.

        Can be used to persist noteworthy messages to Logios.
        Currently a no-op — Pi sessions are already persisted in JSONL.
        """
        pass

    # ── Evidence recording ─────────────────────────────────────────────────────

    def record_generation(
        self,
        skill_name: str,
        output: str,
        model: str,
        machine: str,
        evidence: list[dict],
        prompt_used: str,
        chain_of_thought: Optional[str] = None,
    ) -> Optional[str]:
        """
        Record an agent generation with evidence to Logios.

        Call this in Pi's post-generation hook.
        Returns the generation ID.
        """
        payload = {
            "skill_name": skill_name,
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


def connect(
    api_base_url: str,
    api_key: str,
    session_id: str,
) -> LogiosExtension:
    """
    Factory: build a Logios-backed Pi Coding Agent extension.

    Args:
        api_base_url: Logios Brain HTTP base (e.g. "http://localhost:8000")
        api_key:      API key for Logios
        session_id:   Pi session identifier

    Returns:
        LogiosExtension instance — pass to ``pi_agent.register_extension()``
    """
    return LogiosExtension(
        api_base_url=api_base_url,
        api_key=api_key,
        session_id=session_id,
    )
