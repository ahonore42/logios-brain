"""MCP server for Logios Brain."""
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from app.mcp.auth import BearerTokenVerifier
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
    token_verifier=BearerTokenVerifier(),
    json_response=True,
    auth=AuthSettings(issuer_url="http://localhost", resource_server_url="http://localhost"),
)


@mcp.tool()
async def remember(
    content: str,
    source: str = "manual",
    session_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """
    Store a memory in all three stores: Postgres, Qdrant, and Neo4j.

    Embeds the content, writes the memory record, and triggers async entity
    extraction into the knowledge graph.
    """
    return await tools.remember(content, source, session_id, metadata)


@mcp.tool()
async def search(
    query: str,
    top_k: int = 10,
    threshold: float = 0.65,
) -> list[dict]:
    """
    Semantic vector search over memories using cosine similarity.

    Returns memories ranked by relevance, hydrated with full content.
    """
    return await tools.search(query, top_k, threshold)


@mcp.tool()
async def recall(
    source: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Structured recall of memories by source and/or date range.

    source: filter by origin (e.g. 'telegram', 'claude', 'manual')
    since: ISO date string — only memories captured after this date
    limit: maximum number of results (default 20)
    """
    return await tools.recall(source, since, limit)


@mcp.tool()
async def graph_search(
    entity_name: str,
    depth: int = 2,
) -> dict:
    """
    Traverse the knowledge graph from a named entity to all reachable
    MemoryChunks and Facts.

    Facts are automatically resolved through their REPLACES chains
    to return the newest valid version. depth controls traversal depth.
    """
    return await tools.graph_search(entity_name, depth)


@mcp.tool()
async def assert_fact(
    content: str,
    valid_from: str,
    valid_until: str | None = None,
    version: int = 1,
    replaces_id: str | None = None,
) -> dict:
    """
    Manually assert a Fact into the graph.

    Optionally links to an existing Fact via REPLACES, enabling version chains
    without going through the memory extraction pipeline.

    replaces_id: optional ID of the Fact this newer Fact supersedes
    """
    return await tools.assert_fact(content, valid_from, valid_until, version, replaces_id)


@mcp.tool()
async def get_fact(fact_id: str) -> dict | None:
    """
    Retrieve a Fact by ID, resolved through its REPLACES chain.

    Returns the newest valid Fact that supersedes the given ID,
    or None if the ID is not found.
    """
    return await tools.get_fact(fact_id)


@mcp.tool()
async def run_skill(
    skill_name: str,
    context: dict | None = None,
    model: str = "unknown",
    machine: str = "unknown",
) -> dict:
    """
    Execute a skill with evidence context.

    Loads the skill's prompt template, retrieves relevant memories from Qdrant,
    builds an evidence manifest, and returns everything needed for local execution.

    After executing, call record_generation with the output.
    """
    return await tools.run_skill(skill_name, context, model, machine)
