"""Integration tests for MCP server running as a standalone process.

The MCP server runs on its own port (LOGIOS_MCP_PORT env var, default 8001).
Auth is handled by the global AuthMiddleware — requests to the standalone MCP
server need a valid owner access token as a Bearer token.
"""

import os
import subprocess
import time

import pytest
import requests
from starlette.testclient import TestClient

from app.main import app as main_app
from app.config import DATABASE_URL

MCP_PORT = int(os.getenv("LOGIOS_MCP_PORT", "8001"))
MCP_BASE_URL = f"http://127.0.0.1:{MCP_PORT}"

# Fixed test credentials — isolated per module session
TEST_OWNER_EMAIL = "mcp@example.com"
TEST_OWNER_PASSWORD = "mcp-test-password-123"
TEST_SECRET_HEADER = {"X-Secret-Key": "test-deployer-secret-for-testing-only"}


@pytest.fixture(scope="module")
def mcp_server():
    """Start the standalone MCP server as a subprocess, then clean up."""
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "python",
            "-m",
            "uvicorn",
            "app.mcp.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(MCP_PORT),
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    time.sleep(2)
    yield proc
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def auth_headers():
    """Set up owner account via two-step OTP flow. Returns a valid JWT Bearer token."""
    import re
    from unittest.mock import patch

    # Clean DB synchronously via psycopg
    import psycopg

    sync_dsn = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(sync_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agent_tokens")
            cur.execute("DELETE FROM owner")

    captured_otp = {}

    def mock_send_email(*, email_to, subject, html_content):
        match = re.search(r">(\d{6})<", html_content)
        if match:
            captured_otp["otp"] = match.group(1)

    client = TestClient(main_app, raise_server_exceptions=False)

    with patch("app.email.send_email", side_effect=mock_send_email):
        setup_resp = client.post(
            "/auth/setup",
            json={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
            headers=TEST_SECRET_HEADER,
        )
        assert setup_resp.status_code == 201, f"setup failed: {setup_resp.text}"
        pending_token = setup_resp.json()["pending_token"]

        verify_resp = client.post(
            "/auth/verify-setup",
            data={"pending_token": pending_token, "otp": captured_otp["otp"]},
            headers=TEST_SECRET_HEADER,
        )
        assert verify_resp.status_code == 201, f"verify failed: {verify_resp.text}"

    login_resp = client.post(
        "/auth/login",
        data={"email": TEST_OWNER_EMAIL, "password": TEST_OWNER_PASSWORD},
        headers=TEST_SECRET_HEADER,
    )
    token = login_resp.json()["access_token"]
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }


@pytest.fixture
def base_url():
    return MCP_BASE_URL


@pytest.fixture
def json_headers():
    return {"Accept": "application/json", "Content-Type": "application/json"}


class TestMCPStandaloneServer:
    """MCP server runs as a standalone process on LOGIOS_MCP_PORT."""

    def test_server_is_running(self, mcp_server):
        """MCP server process is alive and accepting connections."""
        assert mcp_server.poll() is None

    def test_server_accepts_valid_initialize(
        self, mcp_server, base_url, json_headers, auth_headers
    ):
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
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        assert resp.json()["result"]["serverInfo"]["name"] == "Logios Brain"

    def test_tools_list_returns_all_7(
        self, mcp_server, base_url, json_headers, auth_headers
    ):
        """tools/list returns all 7 registered tools."""
        resp = requests.post(
            f"{base_url}/mcp",
            headers={**json_headers, **auth_headers},
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            timeout=10,
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        tools_json = resp.json().get("result", {}).get("tools", [])
        tool_names = [t["name"] for t in tools_json]
        for expected in [
            "remember",
            "search",
            "recall",
            "graph_search",
            "assert_fact",
            "get_fact",
            "run_skill",
        ]:
            assert expected in tool_names, f"{expected} missing from {tool_names}"
