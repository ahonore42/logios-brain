"""
server/tools/run_skill.py

Skill execution with evidence recording.
Does NOT call the LLM — returns prompt + evidence manifest for the caller to execute.
"""

from db import postgres
from tools.search import search, graph_search


def run_skill(
    skill_name: str,
    context: dict,
    model: str = "unknown",
    machine: str = "unknown",
) -> dict:
    """
    Execute a skill:
    1. Load prompt template from Postgres
    2. Retrieve relevant memories (Qdrant + Neo4j)
    3. Build evidence manifest
    4. Return prompt + context for local model to execute
    5. Record the generation and evidence receipt

    Note: this function prepares and records everything but does NOT
    call the local LLM directly — that is done by the calling agent.
    The agent calls run_skill, gets back the prompt + evidence manifest,
    executes the LLM call locally, then calls record_generation with the output.
    """
    # 1. Load skill
    skill = postgres.get_skill(skill_name)
    if not skill:
        return {"error": f"Skill '{skill_name}' not found or inactive"}

    # 2. Retrieve context
    query_str = context.get("query", skill_name)
    vector_hits = search(query_str, top_k=8)
    graph_hits = []

    if context.get("entity"):
        graph_hits = graph_search(context["entity"], depth=2)

    # 3. Build evidence manifest
    evidence_manifest = [
        {
            "rank": i + 1,
            "retrieval_type": "vector",
            "relevance_score": hit["score"],
            "memory_id": hit["memory_id"],
            "content": hit["content"],
            "source": hit["source"],
            "captured_at": hit["captured_at"],
        }
        for i, hit in enumerate(vector_hits)
    ]

    for i, node in enumerate(graph_hits):
        evidence_manifest.append(
            {
                "rank": len(vector_hits) + i + 1,
                "retrieval_type": "graph",
                "neo4j_node_id": node.get("node_id"),
                "name": node.get("name"),
                "memory_id": node.get("memory_id"),
            }
        )

    # 4. Return everything for the local agent to execute
    return {
        "skill_id": skill["id"],
        "skill_name": skill_name,
        "prompt_template": skill["prompt_template"],
        "evidence_manifest": evidence_manifest,
        "context": context,
        "instructions": (
            "Execute this skill using your local model. "
            "Once you have the output, call record_generation with: "
            "skill_id, output, model, machine, prompt_used, evidence_manifest."
        ),
    }


def record_generation(
    skill_id: str,
    skill_name: str,
    output: str,
    model: str,
    machine: str,
    prompt_used: str,
    evidence_manifest: list[dict],
    session_id: str | None = None,
) -> dict:
    """
    Write the generation record and all evidence rows to Postgres.
    Call this after your local LLM has produced its output.
    """
    # Write generation
    generation_id = postgres.insert_generation(
        skill_id=skill_id,
        skill_name=skill_name,
        output=output,
        model=model,
        machine=machine,
        prompt_used=prompt_used,
        session_id=session_id,
    )

    # Write evidence rows
    evidence_rows = []
    for item in evidence_manifest:
        evidence_rows.append(
            {
                "generation_id": generation_id,
                "memory_id": item.get("memory_id"),
                "chunk_id": item.get("chunk_id"),
                "neo4j_node_id": item.get("neo4j_node_id"),
                "relevance_score": item.get("relevance_score"),
                "retrieval_type": item.get("retrieval_type", "vector"),
                "rank": item.get("rank", 0),
            }
        )

    if evidence_rows:
        postgres.insert_evidence_batch(evidence_rows)

    return {
        "generation_id": generation_id,
        "evidence_count": len(evidence_rows),
        "status": "recorded",
    }
