"""OpenClaw Gateway integration — Logios as a Gateway memory extension.

OpenClaw's Gateway exposes a WebSocket control plane that manages sessions,
presence, routing, and extensions. This module provides a Gateway extension
that registers Logios memory tools (``/remember``, ``/recall``, ``/forget``,
``/knowledge``) on the Gateway.

The extension translates OpenClaw tool calls into Logios Brain API calls.

Usage::

    from app.integrations.openclaw import connect
    extension = connect("http://localhost:8000", "your-api-key")
    gateway.register_extension("logios", extension)

    # Agent then calls tools via OpenClaw's normal tool invocation:
    # /remember <content>   → POST /memories/remember
    # /recall <query>       → POST /memories/search
    # /forget <query>      → POST /memories/forget
    # /knowledge           → GET /memories/identity
"""

from typing import Any, Optional

import httpx

__all__ = ["connect"]


class LogiosGatewayExtension:
    """
    OpenClaw Gateway extension that exposes Logios memory tools.

    Registers the following commands on the OpenClaw Gateway:
    - /remember <content>   persist a memory
    - /recall <query>      semantic search over memories
    - /forget <query>      revoke memories matching a query
    - /knowledge           list identity memories
    - /digest              show memory digest for review
    """

    name = "logios"
    description = "Long-term memory powered by Logios Brain"

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        session_id: Optional[str] = None,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = session_id
        self._client = httpx.Client(timeout=30.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _session_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.session_id:
            payload["session_id"] = self.session_id
        return payload

    # ── Gateway extension interface ─────────────────────────────────────────────

    async def on_load(self, gateway_context: dict[str, Any]) -> dict[str, Any]:
        """Called when the extension is loaded into the Gateway."""
        return {
            "name": self.name,
            "description": self.description,
            "commands": ["remember", "recall", "forget", "knowledge", "digest"],
        }

    async def on_command(
        self,
        command: str,
        args: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Handle a command from the agent.

        Translates OpenClaw commands into Logios Brain API calls.
        """
        self.session_id = context.get("session_id", self.session_id)
        cmd = command.lower().strip()

        if cmd == "remember":
            return await self._remember(args, context)
        elif cmd == "recall":
            return await self._recall(args, context)
        elif cmd == "forget":
            return await self._forget(args, context)
        elif cmd == "knowledge":
            return await self._knowledge(args, context)
        elif cmd == "digest":
            return await self._digest(args, context)
        else:
            return {"error": f"Unknown command: {command}"}

    # ── Command handlers ────────────────────────────────────────────────────────

    async def _remember(self, content: str, context: dict[str, Any]) -> dict[str, Any]:
        """/remember <content> — persist a memory to Logios."""
        payload = {
            "content": content.strip(),
            "source": "openclaw",
            "type": "standard",
            **self._session_payload(),
        }
        resp = self._client.post(
            f"{self.api_base_url}/memories/remember",
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return {"ok": True, "memory_id": str(data["id"])}

    async def _recall(self, query: str, context: dict[str, Any]) -> dict[str, Any]:
        """recall <query> — semantic search over Logios memories."""
        payload = {
            "query": query.strip(),
            "top_k": 8,
            "threshold": 0.65,
            **self._session_payload(),
        }
        resp = self._client.post(
            f"{self.api_base_url}/memories/search",
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        memories = resp.json()
        return {
            "ok": True,
            "count": len(memories),
            "memories": [
                {"id": str(m["id"]), "content": m["content"], "source": m["source"]}
                for m in memories
            ],
        }

    async def _forget(self, query: str, context: dict[str, Any]) -> dict[str, Any]:
        """forget <query> — revoke memories matching a semantic query."""
        payload = {"query": query.strip()}
        resp = self._client.post(
            f"{self.api_base_url}/memories/forget",
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return {"ok": True, "revoked": data.get("revoked", 0)}

    async def _knowledge(self, _args: str, context: dict[str, Any]) -> dict[str, Any]:
        """knowledge — list all identity memories."""
        resp = self._client.get(
            f"{self.api_base_url}/memories/identity",
            headers=self._headers(),
        )
        resp.raise_for_status()
        memories = resp.json()
        return {
            "ok": True,
            "count": len(memories),
            "memories": [
                {"id": str(m["id"]), "content": m["content"]} for m in memories
            ],
        }

    async def _digest(self, _args: str, context: dict[str, Any]) -> dict[str, Any]:
        """digest — show memory digest for human review."""
        resp = self._client.get(
            f"{self.api_base_url}/memories/digest",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def on_unload(self) -> None:
        """Called when the extension is unloaded."""
        self._client.close()


def connect(
    api_base_url: str,
    api_key: str,
    session_id: Optional[str] = None,
) -> LogiosGatewayExtension:
    """
    Factory: build a Logios-backed OpenClaw Gateway extension.

    Args:
        api_base_url: Logios Brain HTTP base (e.g. "http://localhost:8000")
        api_key:      API key for Logios
        session_id:   Default session ID (can be overridden per-command via context)

    Returns:
        LogiosGatewayExtension instance — pass to ``gateway.register_extension()``
    """
    return LogiosGatewayExtension(
        api_base_url=api_base_url,
        api_key=api_key,
        session_id=session_id,
    )
