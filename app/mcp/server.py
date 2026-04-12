"""MCP server for Logios Brain."""

from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from app.mcp import tools

mcp = FastMCP(
    "Logios Brain",
    instructions=(
        "Logios Brain is a personal knowledge system. "
        "Use remember() to capture memories, search() to find them semantically, "
        "recall() to list by source or date, graph_search() to traverse the knowledge graph, "
        "assert_fact() and get_fact() to manage structured facts, "
        "and run_skill() to execute skills with evidence context."
    ),
    json_response=True,
    transport_security=None,
    stateless_http=True,
    streamable_http_path="/mcp",
)


# Uvicorn-compatible ASGI app with session manager lifespan
@asynccontextmanager
async def _lifespan(app):
    async with mcp.session_manager.run():
        yield


app = Starlette(
    debug=False,
    routes=mcp.streamable_http_app().routes,
    lifespan=_lifespan,
)


@mcp.tool()
async def remember(
    content: str,
    source: str = "manual",
    session_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Store a memory in all three stores: Postgres, Qdrant, and Neo4j."""
    return await tools.remember(content, source, session_id, metadata)


@mcp.tool()
async def search(
    query: str,
    top_k: int = 10,
    threshold: float = 0.65,
) -> list[dict]:
    """Semantic vector search over memories using cosine similarity."""
    return await tools.search(query, top_k, threshold)


@mcp.tool()
async def recall(
    source: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Structured recall of memories by source and/or date range."""
    return await tools.recall(source, since, limit)


@mcp.tool()
async def graph_search(
    entity_name: str,
    depth: int = 2,
) -> dict:
    """Traverse the knowledge graph from a named entity to all reachable nodes."""
    return await tools.graph_search(entity_name, depth)


@mcp.tool()
async def assert_fact(
    content: str,
    valid_from: str,
    valid_until: str | None = None,
    version: int = 1,
    replaces_id: str | None = None,
) -> dict:
    """Manually assert a Fact into the graph with optional REPLACES link."""
    return await tools.assert_fact(
        content, valid_from, valid_until, version, replaces_id
    )


@mcp.tool()
async def get_fact(fact_id: str) -> dict | None:
    """Retrieve a Fact by ID, resolved through its REPLACES chain."""
    return await tools.get_fact(fact_id)


@mcp.tool()
async def run_skill(
    skill_name: str,
    context: dict | None = None,
    model: str = "unknown",
    machine: str = "unknown",
) -> dict:
    """Execute a skill with evidence context."""
    return await tools.run_skill(skill_name, context, model, machine)
