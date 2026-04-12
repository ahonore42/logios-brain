"""Integration tests for MCP server running as a standalone process.

The MCP server runs on its own port (LOGIOS_MCP_PORT env var, default 8001).
Auth is handled by the global AuthMiddleware in app/auth.py on the FastAPI side —
when running standalone, the MCP server relies on transport-level security
(no built-in auth in the MCP transport itself).
"""
import os
import subprocess
import time

import pytest
import requests

from app import config

MCP_PORT = int(os.getenv("LOGIOS_MCP_PORT", "8001"))
MCP_BASE_URL = f"http://127.0.0.1:{MCP_PORT}"


@pytest.fixture(scope="module")
def mcp_server():
    """Start the standalone MCP server as a subprocess, then clean up."""
    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "uvicorn", "app.mcp.server:app",
         "--host", "127.0.0.1", "--port", str(MCP_PORT)],
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    time.sleep(2)
    yield proc
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def base_url():
    return MCP_BASE_URL


@pytest.fixture
def json_headers():
    return {"Accept": "application/json", "Content-Type": "application/json"}


@pytest.fixture
def auth_headers():
    return {"Accept": "application/json", "Authorization": f"Bearer {config.LOGIOS_BRAIN_KEY}"}


class TestMCPStandaloneServer:
    """MCP server runs as a standalone process on LOGIOS_MCP_PORT."""

    def test_server_is_running(self, mcp_server):
        """MCP server process is alive and accepting connections."""
        assert mcp_server.poll() is None

    def test_server_accepts_valid_initialize(self, mcp_server, base_url, json_headers, auth_headers):
        """POST /mcp with initialize returns server name and version."""
        resp = requests.post(
            f"{base_url}/mcp",
            headers={**json_headers, **auth_headers},
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "test", "version": "1.0"},
                    "capabilities": {},
                },
                "id": 1,
            },
            timeout=10,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        assert resp.json()["result"]["serverInfo"]["name"] == "Logios Brain"

    def test_tools_list_returns_all_7(self, mcp_server, base_url, json_headers, auth_headers):
        """tools/list returns all 7 registered tools."""
        resp = requests.post(
            f"{base_url}/mcp",
            headers={**json_headers, **auth_headers},
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            timeout=10,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        tools_json = resp.json().get("result", {}).get("tools", [])
        tool_names = [t["name"] for t in tools_json]
        for expected in ["remember", "search", "recall", "graph_search",
                         "assert_fact", "get_fact", "run_skill"]:
            assert expected in tool_names, f"{expected} missing from {tool_names}"