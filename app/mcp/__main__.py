"""MCP server entrypoint for standalone process.

Run as: python -m app.mcp

This is used by tests/test_mcp_http.py to spin up a live MCP subprocess,
and by operators who want to run the MCP server as a standalone HTTP service
separate from the main FastAPI app."""



from app.mcp.server import mcp

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
