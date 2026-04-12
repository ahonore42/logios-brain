"""
Unit tests for entity_preflight.py — fully deterministic, no API calls.

These tests run offline and should always pass regardless of external
service availability. They cover the dictionary scan, merge logic, and
spaCy NER. spaCy tests are skipped gracefully if the model is absent.
"""

import pytest

from app.genai.entity_preflight import KNOWN_TOOLS, merge_entities, preflight_extract

# ---------------------------------------------------------------------------
# Tool dictionary tests
# ---------------------------------------------------------------------------


class TestToolDictionaryExtraction:
    def test_canonical_name_matched(self):
        result = preflight_extract("We use Neo4j for the knowledge graph.")
        names = {e["name"] for e in result}
        assert "Neo4j" in names

    def test_alias_matched_and_canonical_returned(self):
        """'postgres' alias should return canonical 'PostgreSQL'."""
        result = preflight_extract("Migrating from postgres to a new store.")
        names = {e["name"] for e in result}
        assert "PostgreSQL" in names
        assert "postgres" not in names  # alias must not leak through

    def test_pgvector_alias(self):
        result = preflight_extract("Using pgvector backed by Postgres.")
        names = {e["name"] for e in result}
        assert "PostgreSQL" in names

    def test_case_insensitive_match(self):
        result = preflight_extract("REDIS is the task broker.")
        names = {e["name"] for e in result}
        assert "Redis" in names

    def test_word_boundary_no_false_positive(self):
        """'redis' must not match inside 'credentials'."""
        result = preflight_extract("Store your credentials safely.")
        names = {e["name"] for e in result}
        assert "Redis" not in names

    def test_multiple_tools_in_one_string(self):
        result = preflight_extract("The stack uses FastAPI, Celery, Redis, and Qdrant.")
        names = {e["name"] for e in result}
        assert "FastAPI" in names
        assert "Celery" in names
        assert "Redis" in names
        assert "Qdrant" in names

    def test_tool_label_is_correct(self):
        result = preflight_extract("We deployed on Docker.")
        tools = [e for e in result if e["name"] == "Docker"]
        assert tools, "Docker not found"
        assert tools[0]["label"] == "Tool"

    def test_no_tools_in_generic_text(self):
        result = preflight_extract("The weather is nice today.")
        tool_entities = [e for e in result if e["label"] == "Tool"]
        assert tool_entities == []

    def test_all_known_tools_have_at_least_one_alias(self):
        """Sanity check on the dictionary itself."""
        for canonical, aliases in KNOWN_TOOLS.items():
            assert isinstance(aliases, list), f"{canonical} aliases must be a list"
            assert len(aliases) >= 1, f"{canonical} must have at least one alias"


# ---------------------------------------------------------------------------
# spaCy NER tests (skipped if model unavailable)
# ---------------------------------------------------------------------------


def _spacy_available() -> bool:
    try:
        import spacy

        spacy.load("en_core_web_sm")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _spacy_available(), reason="spaCy en_core_web_sm not installed")
class TestSpacyExtraction:
    def test_person_extracted(self):
        result = preflight_extract("Alice worked on the project.")
        names = {e["name"] for e in result}
        assert "Alice" in names

    def test_person_label_correct(self):
        result = preflight_extract("Bob reviewed the pull request.")
        people = [e for e in result if e["label"] == "Person"]
        assert any(e["name"] == "Bob" for e in people)

    def test_location_extracted(self):
        result = preflight_extract("The team is based in Berlin.")
        names = {e["name"] for e in result}
        assert "Berlin" in names

    def test_location_label_correct(self):
        result = preflight_extract("We deployed servers in Frankfurt.")
        locations = [e for e in result if e["label"] == "Location"]
        assert any(e["name"] == "Frankfurt" for e in locations)

    def test_person_and_tool_combined(self):
        result = preflight_extract(
            "Sarah migrated the database from Supabase to PostgreSQL."
        )
        names = {e["name"] for e in result}
        assert "Sarah" in names
        assert "PostgreSQL" in names

    def test_spacy_failure_is_non_fatal(self, monkeypatch):
        """If spaCy raises, preflight still returns tool results."""
        import app.genai.entity_preflight as module

        monkeypatch.setattr(module, "_nlp", "broken_nlp")  # will raise on call
        result = preflight_extract("Sarah uses Redis.")
        names = {e["name"] for e in result}
        # Tool match must still work even if spaCy path errored
        assert "Redis" in names


# ---------------------------------------------------------------------------
# merge_entities tests
# ---------------------------------------------------------------------------


class TestMergeEntities:
    def test_preflight_wins_on_collision(self):
        """If both preflight and LLM extract the same name, preflight label wins."""
        preflight = [
            {
                "name": "Alice",
                "label": "Person",
                "relationships": [],
                "source": "preflight",
            }
        ]
        llm = [{"name": "Alice", "label": "Concept", "relationships": []}]
        result = merge_entities(preflight, llm)
        alice = next(e for e in result if e["name"] == "Alice")
        assert alice["label"] == "Person"

    def test_llm_only_entities_are_included(self):
        """Entities only found by LLM (Decision, Concept) must appear in output."""
        preflight = [
            {
                "name": "Alice",
                "label": "Person",
                "relationships": [],
                "source": "preflight",
            }
        ]
        llm = [
            {"name": "Alice", "label": "Person", "relationships": []},
            {
                "name": "migrate to self-hosted Postgres",
                "label": "Decision",
                "relationships": [],
            },
        ]
        result = merge_entities(preflight, llm)
        names = {e["name"] for e in result}
        assert "Alice" in names
        assert "migrate to self-hosted Postgres" in names

    def test_source_key_stripped_from_output(self):
        """'source' is internal — must not appear in final merged entities."""
        preflight = [
            {
                "name": "Neo4j",
                "label": "Tool",
                "relationships": [],
                "source": "preflight",
            }
        ]
        result = merge_entities(preflight, [])
        for entity in result:
            assert "source" not in entity

    def test_empty_preflight_returns_llm_entities(self):
        llm = [{"name": "Logios Brain", "label": "Project", "relationships": []}]
        result = merge_entities([], llm)
        assert result == llm

    def test_empty_llm_returns_preflight_entities(self):
        preflight = [
            {
                "name": "Redis",
                "label": "Tool",
                "relationships": [],
                "source": "preflight",
            }
        ]
        result = merge_entities(preflight, [])
        assert len(result) == 1
        assert result[0]["name"] == "Redis"

    def test_both_empty_returns_empty(self):
        assert merge_entities([], []) == []

    def test_llm_entity_with_empty_name_is_dropped(self):
        preflight = []
        llm = [{"name": "", "label": "Concept", "relationships": []}]
        result = merge_entities(preflight, llm)
        assert result == []

    def test_deduplication_preserves_all_unique_entities(self):
        preflight = [
            {
                "name": "Alice",
                "label": "Person",
                "relationships": [],
                "source": "preflight",
            },
            {
                "name": "Redis",
                "label": "Tool",
                "relationships": [],
                "source": "preflight",
            },
        ]
        llm = [
            {"name": "Logios Brain", "label": "Project", "relationships": []},
            {"name": "Redis", "label": "Tool", "relationships": []},  # duplicate
        ]
        result = merge_entities(preflight, llm)
        names = [e["name"] for e in result]
        assert len(names) == len(set(names)), "Duplicate names in merged output"
        assert set(names) == {"Alice", "Redis", "Logios Brain"}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string_returns_empty(self):
        assert preflight_extract("") == []

    def test_whitespace_only_returns_empty(self):
        assert preflight_extract("   \n\t  ") == []

    def test_no_duplicate_tool_entries(self):
        """'postgres' and 'pgvector' both alias PostgreSQL — only one entry."""
        result = preflight_extract("We use pgvector backed by postgres.")
        postgresql_entries = [e for e in result if e["name"] == "PostgreSQL"]
        assert len(postgresql_entries) == 1

    def test_relationships_default_to_empty_list(self):
        """Pre-filter never generates relationships — that is the LLM's job."""
        result = preflight_extract("Alice uses Neo4j.")
        for entity in result:
            assert entity["relationships"] == []
