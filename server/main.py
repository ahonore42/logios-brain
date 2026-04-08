"""
server/main.py

FastAPI MCP server entrypoint. Exposes all tools as HTTP endpoints.
Authenticates via X-Brain-Key header or ?key= query parameter.
"""

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

import config
from db.qdrant import ensure_collection
from tools import remember, search, relate, run_skill, get_evidence


app = FastAPI(title="Logios Brain MCP Server")

ACCESS_KEY = config.MCP_ACCESS_KEY


# ── Auth dependency ──────────────────────────────────────────────────────────


def verify_key(
    x_brain_key: str | None = Header(default=None), key: str | None = None
) -> str:
    provided = x_brain_key or key
    if provided != ACCESS_KEY:
        raise HTTPException(status_code=401, detail="Invalid access key")
    return provided


# ── Startup ─────────────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup():
    ensure_collection()


# ── Health ─────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok"}


# ── MCP tool schemas ────────────────────────────────────────────────────────


class RememberRequest(BaseModel):
    content: str
    source: str = "manual"
    session_id: str | None = None
    metadata: dict = {}


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    threshold: float = 0.65


class RecallRequest(BaseModel):
    source: str | None = None
    since: str | None = None
    limit: int = 20


class GraphSearchRequest(BaseModel):
    entity_name: str
    depth: int = 2


class RelateRequest(BaseModel):
    entity_a: str
    entity_b: str
    relationship_type: str = "RELATES_TO"


class RunSkillRequest(BaseModel):
    skill_name: str
    context: dict = {}
    model: str = "unknown"
    machine: str = "unknown"


class RecordGenerationRequest(BaseModel):
    skill_id: str
    skill_name: str
    output: str
    model: str
    machine: str
    prompt_used: str
    evidence_manifest: list[dict]
    session_id: str | None = None


class GetEvidenceRequest(BaseModel):
    generation_id: str


# ── MCP tools ────────────────────────────────────────────────────────────────


@app.post("/tools/remember")
def tool_remember(req: RememberRequest, _=Depends(verify_key)):
    return remember.remember(req.content, req.source, req.session_id, req.metadata)


@app.post("/tools/search")
def tool_search(req: SearchRequest, _=Depends(verify_key)):
    return search.search(req.query, req.top_k, req.threshold)


@app.post("/tools/recall")
def tool_recall(req: RecallRequest, _=Depends(verify_key)):
    return search.recall(req.source, req.since, req.limit)


@app.post("/tools/graph_search")
def tool_graph_search(req: GraphSearchRequest, _=Depends(verify_key)):
    return search.graph_search(req.entity_name, req.depth)


@app.post("/tools/relate")
def tool_relate(req: RelateRequest, _=Depends(verify_key)):
    return relate.relate(req.entity_a, req.entity_b, req.relationship_type)


@app.post("/tools/run_skill")
def tool_run_skill(req: RunSkillRequest, _=Depends(verify_key)):
    return run_skill.run_skill(req.skill_name, req.context, req.model, req.machine)


@app.post("/tools/record_generation")
def tool_record_generation(req: RecordGenerationRequest, _=Depends(verify_key)):
    return run_skill.record_generation(
        req.skill_id,
        req.skill_name,
        req.output,
        req.model,
        req.machine,
        req.prompt_used,
        req.evidence_manifest,
        req.session_id,
    )


@app.post("/tools/get_evidence")
def tool_get_evidence(req: GetEvidenceRequest, _=Depends(verify_key)):
    return get_evidence.get_evidence(req.generation_id)


# ── MCP manifest (tool discovery) ───────────────────────────────────────────


@app.get("/mcp/tools")
def mcp_tools(_=Depends(verify_key)):
    return {
        "tools": [
            {"name": "remember", "description": "Store a memory in all three stores"},
            {"name": "search", "description": "Semantic search over memories"},
            {"name": "recall", "description": "Structured recall by source or date"},
            {
                "name": "graph_search",
                "description": "Traverse the knowledge graph from an entity",
            },
            {"name": "relate", "description": "Manually create a graph relationship"},
            {
                "name": "run_skill",
                "description": "Prepare a skill execution with evidence context",
            },
            {
                "name": "record_generation",
                "description": "Record a completed generation with evidence receipt",
            },
            {
                "name": "get_evidence",
                "description": "Retrieve the evidence receipt for a generation",
            },
        ]
    }
