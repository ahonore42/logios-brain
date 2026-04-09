"""
app/entity_extraction.py

Entity extraction via local Ollama. Extracts named entities and relationships
from memory text and returns them as a list of entity dicts ready for Neo4j.

Best-effort: if Ollama is unreachable, returns [] silently.
Never blocks a memory write.
"""

import json

import httpx

from app import config

SYSTEM_PROMPT = """
You are an entity extraction assistant. Given a text, extract named entities
and return ONLY valid JSON with no additional text, markdown, or explanation.

Return this structure:
{
  "entities": [
    {
      "name": "entity name",
      "label": "one of: Project, Concept, Person, Session, Event, Decision, Tool, Location",
      "relationships": [
        {"target": "other entity name", "type": "RELATES_TO | PART_OF | CREATED_BY | MENTIONS | CAUSED_BY | DEPENDS_ON"}
      ]
    }
  ]
}

If there are no entities, return: {"entities": []}
""".strip()


async def extract_entities(text: str) -> list[dict]:
    """
    Call local Ollama to extract entities from a memory text.
    Returns a list of entity dicts ready to write to Neo4j.
    Uses httpx async client to avoid blocking the event loop.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{config.OLLAMA_URL}/api/chat",
                json={
                    "model": config.ENTITY_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Extract entities from:\n\n{text}"},
                    ],
                    "stream": False,
                },
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            parsed = json.loads(content)
            return parsed.get("entities", [])
    except Exception:
        # Entity extraction is best-effort — never block a memory write
        return []
