"""ZeroClaw integration — Logios as a ZeroClaw MCP memory server.

ZeroClaw exposes memory tools via its MCP (Model Context Protocol) gateway:
``recall``, ``store``, ``forget``, ``knowledge``, ``project intel``.

This module provides an MCP server that implements these tools backed by Logios Brain.
ZeroClaw's Gateway connects to MCP servers as tools providers.

Usage::

    from app.integrations.zeroclaw import LogiosMCPServer
    from mcp.server import MCPServer

    server = MCPServer(name="logios")
    logios_mcp = LogiosMCPServer("http://localhost:8000", "your-api-key")
    server.add_tool_provider(logios_mcp)
    server.start()

    # ZeroClaw Gateway config (zeroclaw.yaml):
    # mcpServers:
    #   logios:
    #     command: python
    #     args: [-m, app.integrations.zeroclaw, --url, http://localhost:8000, --key, <key>]
"""

import argparse
import sys
from typing import Any, Optional

import httpx

__all__ = ["LogiosMCPServer", "main"]


class LogiosMCPServer:
    """
    MCP server that exposes Logios Brain memory tools.

    Implements the MCP tool interface expected by ZeroClaw's Gateway.
    Tools: recall, store, forget, knowledge, digest
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

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _session_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.session_id:
            payload["session_id"] = self.session_id
        return payload

    # ── MCP tool definitions ───────────────────────────────────────────────────

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the list of tools this MCP server provides."""
        return [
            {
                "name": "logios_recall",
                "description": "Search long-term memory for information relevant to a query",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Semantic search query"},
                        "top_k": {"type": "integer", "description": "Max results (default 8)", "default": 8},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "logios_store",
                "description": "Store a memory in Logios Brain",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Memory content to store"},
                        "memory_type": {
                            "type": "string",
                            "enum": ["standard", "identity", "checkpoint", "manual"],
                            "description": "Type of memory (default standard)",
                            "default": "standard",
                        },
                        "metadata": {"type": "object", "description": "Optional metadata dict"},
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "logios_forget",
                "description": "Remove memories matching a query from active retrieval",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Query describing memories to revoke"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "logios_knowledge",
                "description": "List all identity memories (core persistent instructions)",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "logios_digest",
                "description": "Show memory digest: unused, low-relevance, and recent checkpoint memories",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "days_unused": {"type": "integer", "default": 30},
                        "days_recent": {"type": "integer", "default": 7},
                    },
                },
            },
        ]

    # ── MCP tool execution ────────────────────────────────────────────────────

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool call and return the result."""
        try:
            if tool_name == "logios_recall":
                return await self._recall(arguments)
            elif tool_name == "logios_store":
                return await self._store(arguments)
            elif tool_name == "logios_forget":
                return await self._forget(arguments)
            elif tool_name == "logios_knowledge":
                return await self._knowledge(arguments)
            elif tool_name == "logios_digest":
                return await self._digest(arguments)
            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except Exception as exc:
            return {"error": str(exc)}

    # ── Tool handlers ─────────────────────────────────────────────────────────

    async def _recall(self, args: dict[str, Any]) -> dict[str, Any]:
        """recall — semantic search over Logios memories."""
        query = args.get("query", "")
        top_k = args.get("top_k", 8)

        payload = {
            "query": query,
            "top_k": top_k,
            "threshold": 0.65,
            **self._session_payload(),
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.api_base_url}/memories/search",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            memories = resp.json()

        return {
            "content": [
                {"id": str(m["id"]), "content": m["content"], "source": m["source"]}
                for m in memories
            ],
            "count": len(memories),
        }

    async def _store(self, args: dict[str, Any]) -> dict[str, Any]:
        """store — persist a memory to Logios."""
        content = args.get("content", "")
        memory_type = args.get("memory_type", "standard")
        metadata = args.get("metadata", {})

        payload = {
            "content": content,
            "source": "zeroclaw",
            "type": memory_type,
            **self._session_payload(),
            "metadata": metadata,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.api_base_url}/memories/remember",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        return {"memory_id": str(data["id"]), "ok": True}

    async def _forget(self, args: dict[str, Any]) -> dict[str, Any]:
        """forget — revoke memories matching a query."""
        query = args.get("query", "")

        payload = {"query": query}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.api_base_url}/memories/forget",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        return {"revoked": data.get("revoked", 0), "ok": True}

    async def _knowledge(self, args: dict[str, Any]) -> dict[str, Any]:
        """knowledge — list all identity memories."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.api_base_url}/memories/identity",
                headers=self._headers(),
            )
            resp.raise_for_status()
            memories = resp.json()

        return {
            "content": [
                {"id": str(m["id"]), "content": m["content"]}
                for m in memories
            ],
            "count": len(memories),
        }

    async def _digest(self, args: dict[str, Any]) -> dict[str, Any]:
        """digest — show memory digest for human review."""
        days_unused = args.get("days_unused", 30)
        days_recent = args.get("days_recent", 7)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.api_base_url}/memories/digest",
                params={"days_unused": days_unused, "days_recent": days_recent},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()


def main() -> None:
    """CLI entry point for running the Logios MCP server standalone."""
    parser = argparse.ArgumentParser(description="Logios Brain MCP Server for ZeroClaw")
    parser.add_argument("--url", default="http://localhost:8000", help="Logios Brain base URL")
    parser.add_argument("--key", default="", help="API key for Logios Brain")
    parser.add_argument("--session-id", default=None, help="Default session ID")
    args = parser.parse_args()

    server = LogiosMCPServer(
        api_base_url=args.url,
        api_key=args.key,
        session_id=args.session_id,
    )

    # This is a simplified main loop. In production, use the MCP server library.
    print(f"Logios MCP Server started — {args.url}", file=sys.stderr)
    print("Tools:", [t["name"] for t in server.list_tools()], file=sys.stderr)

    # Keep the process alive
    import time
    while True:
        time.sleep(86400)


if __name__ == "__main__":
    main()
