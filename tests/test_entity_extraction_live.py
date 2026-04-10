"""Live integration tests for entity extraction — real API, real content."""
import json

from app.entity_extraction import extract_entities, VALID_REL_TYPES, VALID_LABELS


class TestExtractEntitiesLive:
    """Live I/O validation for extract_entities() with real NVIDIA NIM API."""

    def test_returns_valid_json_structure(self):
        """API response must be parseable JSON with an entities list."""
        result = extract_entities("Alice worked on Project Alpha with Bob.")

        assert isinstance(result, list)
        for entity in result:
            assert "name" in entity
            assert "label" in entity
            assert "relationships" in entity
            assert isinstance(entity["relationships"], list)

    def test_all_labels_are_valid(self):
        """Every entity label must be one of the permitted node labels."""
        result = extract_entities("Alice and Bob discussed the Q1 roadmap.")

        for entity in result:
            assert entity["label"] in VALID_LABELS

    def test_all_relationship_types_are_valid(self):
        """Every relationship type must be in VALID_REL_TYPES."""
        result = extract_entities("The report was created by Alice and relates to Project Phoenix.")

        for entity in result:
            for rel in entity["relationships"]:
                assert rel["type"] in VALID_REL_TYPES, f"Invalid rel type: {rel['type']}"

    def test_known_entities_are_extracted(self):
        """Known entities in the input must appear in the output with correct labels."""
        result = extract_entities("Alice worked on Project Alpha.")

        names = {e["name"] for e in result}
        assert "Alice" in names
        assert "Project Alpha" in names

        alice = next(e for e in result if e["name"] == "Alice")
        assert alice["label"] == "Person"

    def test_relationship_targets_reference_real_entities(self):
        """Every relationship target must also be a named entity in the output."""
        result = extract_entities("Alice created Project Alpha and shared it with Bob.")

        # Collect all named entities
        all_names = {e["name"] for e in result}

        # Every target must appear as an entity
        for entity in result:
            for rel in entity.get("relationships", []):
                target = rel.get("target", "").strip()
                if target:
                    assert target in all_names, f"Target '{target}' is not a named entity"

    def test_no_hallucinated_entities(self):
        """Entity names must not contain obviously hallucinated content."""
        result = extract_entities("Alice went to Paris.")

        for entity in result:
            name = entity["name"]
            # Reject names that look like JSON fragments, UUIDs, or template artifacts
            assert not name.startswith("{"), f"Hallucinated name: {name}"
            assert not name.startswith("["), f"Hallucinated name: {name}"
            assert len(name) < 200, f"Implausibly long name: {name}"

    def test_unambiguous_input_returns_empty(self):
        """Input with no extractable entities must return an empty list."""
        result = extract_entities("The weather is nice today.")
        assert result == []

    def test_verbose_realistic_input(self):
        """Verbose realistic memory input — ~500 chars of rich context."""
        text = (
            "Sarah from the growth team pitched a new idea during Friday's all-hands: "
            "use vector embeddings to surface relevant institutional memory in Slack threads. "
            "The engineering team will prototype it in the context-agent service using pgvector "
            "backed by Postgres. If the latency numbers look acceptable, we'll roll it out to "
            "the broader team in phases. Mike also mentioned we should consider a lightweight "
            "feedback loop with the sales team before committing engineering time."
        )
        assert len(text) >= 400, f"Input too short: {len(text)} chars"
        result = extract_entities(text)
        assert isinstance(result, list)
        for entity in result:
            assert "name" in entity
            assert "label" in entity
            assert entity["label"] in VALID_LABELS
        print(f"\nVerbose input ({len(text)} chars):")
        print(f"Entities extracted ({len(result)}): {json.dumps(result, indent=2)}")
