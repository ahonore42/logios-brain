"""
Deterministic pre-filter for entity extraction.

Runs before the LLM call to extract high-confidence entities via:
  - spaCy NER for Person and Location labels
  - Dictionary lookup for Tool labels

Returns entities in the same schema as extract_entities() so results
can be merged and deduplicated transparently.

This stage never raises — failures return an empty list, consistent
with the best-effort contract of the extraction pipeline.

If spaCy or the model is absent, the module degrades gracefully —
Person/Location extraction is skipped and only the Tool dictionary runs.
"""

import re
from typing import Any

# ---------------------------------------------------------------------------
# Tool dictionary — extend this as your stack grows.
# Keys are canonical names; values are aliases / common abbreviations.
# All matching is case-insensitive.
# ---------------------------------------------------------------------------
KNOWN_TOOLS: dict[str, list[str]] = {
    "Neo4j": ["neo4j"],
    "Qdrant": ["qdrant"],
    "PostgreSQL": ["postgres", "postgresql", "pg", "pgvector"],
    "Redis": ["redis"],
    "Celery": ["celery"],
    "FastAPI": ["fastapi"],
    "SQLAlchemy": ["sqlalchemy"],
    "Alembic": ["alembic"],
    "Docker": ["docker", "docker compose", "docker-compose"],
    "Supabase": ["supabase"],
    "NVIDIA NIM": ["nvidia nim", "nim api", "nvidia api"],
    "spaCy": ["spacy", "spaCy"],
    "React Native": ["react native"],
    "Slack": ["slack"],
    "GitHub": ["github"],
    "Hetzner": ["hetzner"],
    "Telegram": ["telegram"],
}

# Build a flat lookup: lowercased alias → canonical name
_TOOL_ALIAS_MAP: dict[str, str] = {}
for canonical, aliases in KNOWN_TOOLS.items():
    _TOOL_ALIAS_MAP[canonical.lower()] = canonical
    for alias in aliases:
        _TOOL_ALIAS_MAP[alias.lower()] = canonical


def _load_spacy():
    """
    Lazy-load spaCy and the English model.
    Returns the nlp pipeline or None if spaCy is not installed.
    Kept lazy so the module imports cleanly even without spaCy present.
    """
    try:
        import spacy  # type: ignore

        try:
            return spacy.load("en_core_web_sm")
        except OSError:
            # Model not downloaded — caller will skip spaCy extraction
            return None
    except ImportError:
        return None


_nlp = None  # module-level cache; populated on first call


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = _load_spacy()
    return _nlp


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def preflight_extract(text: str) -> list[dict[str, Any]]:
    """
    Run deterministic entity extraction on *text*.

    Returns a list of entity dicts matching the pipeline schema:
        [{"name": str, "label": str, "relationships": [], "source": "preflight"}]

    The "source" key is added to allow downstream deduplication to prefer
    preflight entities over LLM-produced duplicates.

    Extraction order:
      1. spaCy NER → Person, Location
      2. Dictionary scan → Tool
    """
    text = text.strip()
    if not text:
        return []

    entities: dict[str, dict[str, Any]] = {}  # name → entity, deduped by name

    # -- 1. spaCy: Person and Location --
    nlp = _get_nlp()
    if nlp is not None:
        try:
            doc = nlp(text)
            for ent in doc.ents:
                if ent.label_ == "PERSON":
                    label = "Person"
                elif ent.label_ in ("GPE", "LOC"):
                    label = "Location"
                else:
                    continue

                name = ent.text.strip()
                # Skip if this name is a known tool — dictionary scan handles it as Tool
                if (
                    name
                    and name not in entities
                    and name.lower() not in _TOOL_ALIAS_MAP
                ):
                    entities[name] = {
                        "name": name,
                        "label": label,
                        "relationships": [],
                        "source": "preflight",
                    }
        except Exception:
            pass  # spaCy failure is non-fatal

    # -- 2. Dictionary scan: Tool --
    text_lower = text.lower()
    for alias_lower, canonical in _TOOL_ALIAS_MAP.items():
        # Word-boundary match — avoids "redis" matching "credentials"
        pattern = r"\b" + re.escape(alias_lower) + r"\b"
        if re.search(pattern, text_lower):
            if canonical not in entities:
                entities[canonical] = {
                    "name": canonical,
                    "label": "Tool",
                    "relationships": [],
                    "source": "preflight",
                }

    return list(entities.values())


def merge_entities(
    preflight: list[dict[str, Any]],
    llm_entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge preflight and LLM entity lists.

    Rules:
    - Preflight entities win on name collisions (deterministic beats probabilistic).
    - LLM entities for names not already covered are appended.
    - The "source" key is stripped from the final output to keep the
      schema identical to what callers already expect.
    """
    seen: dict[str, dict[str, Any]] = {}

    for entity in preflight:
        name = entity["name"]
        out = {k: v for k, v in entity.items() if k != "source"}
        seen[name] = out

    for entity in llm_entities:
        name = entity.get("name", "").strip()
        if not name:
            continue
        if name not in seen:
            seen[name] = entity

    return list(seen.values())
