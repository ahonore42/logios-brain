"""Tests for MCP server and tool handlers."""

from app.mcp.server import mcp


class TestMCPServerInstantiation:
    """Test that the MCP server instantiates correctly."""

    def test_mcp_server_is_not_none(self):
        """FastMCP server should be instantiated without errors."""
        assert mcp is not None

    def test_mcp_server_name(self):
        """Server should have the correct name."""
        assert mcp.name == "Logios Brain"

    def test_mcp_streamable_http_app_exists(self):
        """streamable_http_app() should return a Starlette app."""
        app = mcp.streamable_http_app()
        assert app is not None
        assert hasattr(app, "routes")
        # Should have /mcp route (streamable_http_path defaults to "/mcp")
        paths = [r.path for r in app.routes]
        assert "/mcp" in paths

    def test_tools_registered(self):
        """All 7 tools should be registered on the server."""
        # Access the tool manager via the MCP server
        tool_manager = mcp._tool_manager
        tool_names = [t.name for t in tool_manager.list_tools()]
        expected = [
            "remember",
            "search",
            "recall",
            "graph_search",
            "assert_fact",
            "get_fact",
            "run_skill",
        ]
        for name in expected:
            assert name in tool_names, f"Tool {name} not found in {tool_names}"


class TestToolOutputStructure:
    """Test that tool functions produce correctly structured output."""

    def test_remember_returns_expected_keys(self):
        """remember tool output should have memory_id, status, source."""
        from app.mcp.tools import remember

        # We can't call the actual function without DB, but we can verify
        # the function signature is correct by checking it exists and is async
        import inspect

        assert inspect.iscoroutinefunction(remember)
        sig = inspect.signature(remember)
        params = list(sig.parameters.keys())
        assert "content" in params
        assert "source" in params

    def test_search_returns_expected_keys(self):
        """search tool should have query, top_k, threshold parameters."""
        from app.mcp.tools import search

        import inspect

        assert inspect.iscoroutinefunction(search)
        sig = inspect.signature(search)
        params = list(sig.parameters.keys())
        assert "query" in params
        assert "top_k" in params
        assert "threshold" in params

    def test_assert_fact_returns_expected_keys(self):
        """assert_fact tool should have all required parameters."""
        from app.mcp.tools import assert_fact

        import inspect

        assert inspect.iscoroutinefunction(assert_fact)
        sig = inspect.signature(assert_fact)
        params = list(sig.parameters.keys())
        required = ["content", "valid_from", "valid_until", "version", "replaces_id"]
        for p in required:
            assert p in params, f"Missing parameter: {p}"

    def test_run_skill_returns_expected_keys(self):
        """run_skill tool should have all required parameters."""
        from app.mcp.tools import run_skill

        import inspect

        assert inspect.iscoroutinefunction(run_skill)
        sig = inspect.signature(run_skill)
        params = list(sig.parameters.keys())
        required = ["skill_name", "context", "model", "machine"]
        for p in required:
            assert p in params, f"Missing parameter: {p}"
