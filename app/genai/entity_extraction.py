"""
Entity extraction via NVIDIA NIM chat completions API.
Uses microsoft/phi-3-mini-128k-instruct for speed — narrow structured task.

Pipeline:
  1. preflight_extract() — deterministic spaCy NER + dictionary scan
     Covers: Person, Location, Tool (high confidence, no API call)
  2. LLM call — phi-3-mini via NVIDIA NIM, unmodified system prompt
     Covers: Decision, Concept, Project, Event, Document, and anything
     the pre-filter missed.
  3. merge_entities() — preflight wins on name collisions
"""

import json

import httpx

from app import config
from app.genai.entity_preflight import merge_entities, preflight_extract

COMPLETION_URL = config.ENTITY_COMPLETION_URL
ENTITY_MODEL = config.ENTITY_MODEL

VALID_REL_TYPES = {"RELATES_TO", "PART_OF", "CREATED_BY", "MENTIONS", "CAUSED_BY"}
VALID_LABELS = {
    "Project",
    "Person",
    "Concept",
    "Decision",
    "Tool",
    "Event",
    "Location",
    "Document",
}

SYSTEM_PROMPT = """You are an entity extraction model. Return ONLY valid JSON, no explanation, no markdown.

IMPORTANT: Extract ONLY the entities that appear in the input text. Do NOT invent or assume any entity not explicitly present.

Examples:

Input: "Alice worked on Project Alpha."
Output: {"entities": [{"name": "Alice", "label": "Person", "relationships": [{"target": "Project Alpha", "type": "RELATES_TO"}]}, {"name": "Project Alpha", "label": "Project", "relationships": []}]}

Input: "The weather is nice today."
Output: {"entities": []}

Input: "After reviewing the Q1 infrastructure costs with Alex and the platform team, we agreed to migrate the Logios Brain ingestion pipeline from Supabase to self-hosted PostgreSQL on Hetzner to reduce costs and regain control of the data layer."
Output: {"entities": [{"name": "Logios Brain", "label": "Project", "relationships": []}, {"name": "migrate from Supabase to PostgreSQL", "label": "Decision", "relationships": [{"target": "Logios Brain", "type": "RELATES_TO"}]}]}

Input: "The concept of zero-shot learning was discussed."
Output: {"entities": [{"name": "zero-shot learning", "label": "Concept", "relationships": []}]}

Rules:
- Extract ONLY entities that appear verbatim in the input text.
- DO NOT extract generic words like "weather", "nice", "report", "data", "today", "team", "meeting", "concept", "pipeline", "infrastructure", "costs".
- Extract only specific named instances: a particular person, project, tool, event, location, concept, decision, or tool by its specific name.
- If the input contains no extractable named entities, return: {"entities": []}
- Relationship targets must also be entities in the input.
- Extract only the most significant entities — the anchors worth traversing from in a knowledge graph. Do not catalog every noun. Prefer entities that represent decisions, commitments, or key subjects of work.

Schema: {"entities": [{"name": str, "label": "Project|Person|Concept|Decision|Tool|Event|Location|Document", "relationships": [{"target": str, "type": "RELATES_TO|PART_OF|CREATED_BY|MENTIONS|CAUSED_BY"}]}]}"""


def extract_entities(text: str, retries: int = 2) -> list[dict]:
    """
    Extract named entities from a memory string.

    Step 1 — deterministic pre-filter (no API call, always runs).
    Step 2 — LLM call, independent of the pre-filter.
    Step 3 — merge, with preflight winning on name collisions.

    Synchronous — called from Celery worker context.
    Best-effort: returns pre-filter results on LLM failure rather than [].
    """
    text = text.strip()
    if not text:
        return []

    # -- Step 1: deterministic pre-filter --
    preflight = preflight_extract(text)

    # -- Step 2: LLM extraction --
    llm_entities: list[dict] = []

    for attempt in range(retries):
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(
                    COMPLETION_URL,
                    json={
                        "model": ENTITY_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": f"Extract entities from:\n\n{text}",
                            },
                        ],
                        "max_tokens": 512,
                        "temperature": 0.0,
                    },
                    headers={
                        "Authorization": f"Bearer {config.LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"].strip()
                if "```" in content:
                    content = content.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(content)

                # Validate and sanitize LLM output
                raw = parsed.get("entities", [])
                for entity in raw:
                    entity["relationships"] = [
                        rel
                        for rel in entity.get("relationships", [])
                        if rel.get("type", "").upper() in VALID_REL_TYPES
                        and rel.get("target", "").strip()
                    ]
                llm_entities = [e for e in raw if e.get("label", "") in VALID_LABELS]
                break  # success — exit retry loop

        except Exception:
            if attempt < retries - 1:
                continue
            # LLM failed after all retries — return preflight results rather than []
            return preflight

    # -- Step 3: merge --
    return merge_entities(preflight, llm_entities)
