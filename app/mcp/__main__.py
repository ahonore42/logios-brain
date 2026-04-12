"""MCP server entrypoint for standalone process."""
from app.mcp.server import mcp

if __name__ == "__main__":
    mcp.run(transport="streamable-http")