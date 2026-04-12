"""GoClaw integration — Logios as a GoClaw pipeline memory/summarize stage.

GoClaw uses an 8-stage pipeline::

    context → history → prompt → think → act → observe → memory → summarize

The ``memory`` stage captures relevant context. The ``summarize`` stage consolidates
learned information. This module provides a LogiosMemoryStage that replaces or
augments GoClaw's built-in memory stage.

Usage::

    from app.integrations.goclaw import LogiosMemoryStage, LogiosSummarizeStage
    pipeline.add_stage(LogiosMemoryStage("http://localhost:8000", "your-api-key"))
    pipeline.add_stage(LogiosSummarizeStage("http://localhost:8000", "your-api-key"))
"""

from typing import Any, Optional

import httpx

__all__ = ["connect", "LogiosMemoryStage", "LogiosSummarizeStage"]


class LogiosMemoryStage:
    """
    GoClaw pipeline stage — replaces the built-in memory stage.

    Called on every agent turn. Fetches identity + episodic memories from
    Logios and injects them as structured context for the agent's next turn.
    """

    name = "logios_memory"
    order = 6  # matches GoClaw's memory stage position (after observe)

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        session_id: str,
        top_k: int = 8,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = session_id
        self.top_k = top_k

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def execute(self, turn_context: dict[str, Any]) -> dict[str, Any]:
        """
        Execute the memory stage.

        Called by GoClaw's pipeline runner. Takes the current turn context
        (which includes the agent's query/action) and returns enriched context
        with Logios memories injected.
        """
        query = turn_context.get("query", "")
        if not query:
            action = turn_context.get("action", "")
            query = f"{action}" if action else f"session {self.session_id}"

        payload = {
            "query": query,
            "session_id": self.session_id,
            "top_k": self.top_k,
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
            return turn_context

        # Inject memories into the context dict for the next pipeline stage
        enriched = dict(turn_context)
        enriched["logios_identity_memories"] = data.get("identity_memories", [])
        enriched["logios_episodic_memories"] = data.get("episodic_memories", [])

        return enriched


class LogiosSummarizeStage:
    """
    GoClaw pipeline stage — replaces the built-in summarize stage.

    Called immediately after the memory stage. Consolidates the current
    turn's actions into a checkpoint memory in Logios.

    Runs on every turn (per GoClaw's continuous consolidation model).
    """

    name = "logios_summarize"
    order = 7  # matches GoClaw's summarize stage position (after memory)

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        session_id: str,
        agent_id: Optional[str] = None,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = session_id
        self.agent_id = agent_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def execute(self, turn_context: dict[str, Any]) -> dict[str, Any]:
        """
        Execute the summarize stage.

        Called after logios_memory. Takes the agent's action/observation and
        writes a checkpoint memory to Logios representing what was learned.
        """
        action = turn_context.get("action", "")
        observation = turn_context.get("observation", "")
        decision = turn_context.get("decision", "")
        turn_count = turn_context.get("turn_index", 0)

        content_parts = []
        if action:
            content_parts.append(f"Action: {action}")
        if observation:
            content_parts.append(f"Observation: {observation}")
        if decision:
            content_parts.append(f"Decision: {decision}")

        if not content_parts:
            return turn_context

        content = "; ".join(content_parts)

        payload = {
            "content": content,
            "source": "goclaw",
            "type": "checkpoint",
            "session_id": self.session_id,
            "metadata": {
                "turn_index": turn_count,
                "agent_id": self.agent_id,
                "trigger": "goclaw_summarize_stage",
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
        except httpx.HTTPError:
            pass

        return turn_context


def connect(
    api_base_url: str,
    api_key: str,
    session_id: str,
    agent_id: Optional[str] = None,
    include_summarize: bool = True,
) -> list[Any]:
    """
    Factory: build one or two Logios-backed GoClaw pipeline stages.

    Args:
        api_base_url:     Logios Brain HTTP base (e.g. "http://localhost:8000")
        api_key:          API key for Logios
        session_id:       GoClaw session identifier
        agent_id:         GoClaw agent identifier (for checkpoint metadata)
        include_summarize: If True (default), return [memory_stage, summarize_stage].
                           If False, return [memory_stage].

    Returns:
        List of pipeline stage instances to add to GoClaw's pipeline.
    """
    stages: list[Any] = [LogiosMemoryStage(api_base_url, api_key, session_id)]
    if include_summarize:
        stages.append(LogiosSummarizeStage(api_base_url, api_key, session_id, agent_id))
    return stages
