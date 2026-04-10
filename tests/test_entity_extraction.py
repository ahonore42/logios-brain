"""Tests for entity extraction — robust I/O validation."""
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest


class MockResponse:
    """Constructable mock for httpx.Response."""

    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=MagicMock(),
                response=self,
            )

    def json(self):
        return self._json_data


@pytest.fixture
def mock_httpx_client():
    """Patch httpx.Client so we can control API responses without real I/O."""
    with patch("app.entity_extraction.httpx.Client") as mock_client:
        yield mock_client


class TestExtractEntities:
    """I/O validation for extract_entities()."""

    def test_returns_parsed_entities_on_success(self, mock_httpx_client):
        """Valid API response with entities should return the entities list."""
        from app.entity_extraction import extract_entities

        mock_httpx_client.return_value.__enter__.return_value.post.return_value = MockResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "entities": [
                                        {
                                            "name": "Project Alpha",
                                            "label": "Project",
                                            "relationships": [
                                                {
                                                    "target": "Alice",
                                                    "type": "CREATED_BY",
                                                }
                                            ],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
        )

        result = extract_entities("Alice worked on Project Alpha")

        assert len(result) == 1
        assert result[0]["name"] == "Project Alpha"
        assert result[0]["label"] == "Project"
        assert result[0]["relationships"][0]["target"] == "Alice"
        assert result[0]["relationships"][0]["type"] == "CREATED_BY"

    def test_returns_empty_list_when_no_entities(self, mock_httpx_client):
        """Model returns {"entities": []} when text contains no entities."""
        from app.entity_extraction import extract_entities

        mock_httpx_client.return_value.__enter__.return_value.post.return_value = MockResponse(
            {"choices": [{"message": {"content": '{"entities": []}'}}]}
        )

        result = extract_entities("The weather is nice today.")

        assert result == []

    def test_filters_invalid_relationship_types(self, mock_httpx_client):
        """Relationship types not in VALID_REL_TYPES must be dropped."""
        from app.entity_extraction import extract_entities

        mock_httpx_client.return_value.__enter__.return_value.post.return_value = MockResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "entities": [
                                        {
                                            "name": "Report Q1",
                                            "label": "Document",
                                            "relationships": [
                                                {"target": "Alice", "type": "RELATES_TO"},
                                                {
                                                    "target": "Bob",
                                                    "type": "HALLUCINATED_TYPE",
                                                },
                                                {"target": "", "type": "PART_OF"},
                                                {
                                                    "target": "Carol",
                                                    "type": "LIKES",
                                                },
                                            ],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
        )

        result = extract_entities("Report Q1 relates to Alice")

        assert len(result) == 1
        rel_types = {r["type"] for r in result[0]["relationships"]}
        assert rel_types == {"RELATES_TO"}  # only this is valid
        # Bob's type is invalid, Carol's type is invalid, empty target is dropped

    def test_filters_empty_target_relationships(self, mock_httpx_client):
        """Relationships with empty or whitespace-only targets are dropped."""
        from app.entity_extraction import extract_entities

        mock_httpx_client.return_value.__enter__.return_value.post.return_value = MockResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "entities": [
                                        {
                                            "name": "Project X",
                                            "label": "Project",
                                            "relationships": [
                                                {"target": "Alice", "type": "PART_OF"},
                                                {"target": "", "type": "CREATED_BY"},
                                                {"target": "  ", "type": "MENTIONS"},
                                                {"target": "Bob", "type": "RELATES_TO"},
                                            ],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
        )

        result = extract_entities("Project X")

        rels = result[0]["relationships"]
        assert len(rels) == 2
        targets = {r["target"] for r in rels}
        assert targets == {"Alice", "Bob"}

    def test_retries_on_http_error(self, mock_httpx_client):
        """HTTP non-2xx response should trigger retry and return [] after exhaustion."""
        from app.entity_extraction import extract_entities

        # First call fails, second call succeeds
        mock_responses = [
            MockResponse({}, status_code=503),
            MockResponse(
                {"choices": [{"message": {"content": '{"entities": []}'}}]}
            ),
        ]
        mock_httpx_client.return_value.__enter__.return_value.post.side_effect = (
            lambda *args, **kwargs: mock_responses.pop(0)
        )

        result = extract_entities("any text")

        assert result == []

    def test_retries_on_malformed_json(self, mock_httpx_client):
        """Non-JSON response body should trigger retry and return [] after exhaustion."""
        from app.entity_extraction import extract_entities

        mock_responses = [
            MockResponse(
                {"choices": [{"message": {"content": "not valid json"}}]}
            ),
            MockResponse(
                {"choices": [{"message": {"content": '{"entities": []}'}}]}
            ),
        ]
        mock_httpx_client.return_value.__enter__.return_value.post.side_effect = (
            lambda *args, **kwargs: mock_responses.pop(0)
        )

        result = extract_entities("any text")

        assert result == []

    def test_returns_empty_after_all_retries_exhausted(self, mock_httpx_client):
        """When all retry attempts fail, extract_entities returns [] without raising."""
        from app.entity_extraction import extract_entities

        def always_fail(*args, **kwargs):
            raise httpx.TimeoutException("timed out")

        mock_httpx_client.return_value.__enter__.return_value.post.side_effect = (
            always_fail
        )

        result = extract_entities("any text", retries=3)

        assert result == []
        assert mock_httpx_client.return_value.__enter__.return_value.post.call_count == 3

    def test_passes_correct_request_payload(self, mock_httpx_client):
        """Request body should contain system prompt, user text, temperature=0, max_tokens=512."""
        from app.entity_extraction import extract_entities, ENTITY_MODEL, SYSTEM_PROMPT

        captured_json = {}

        def capture_post(*args, **kwargs):
            captured_json.update(kwargs.get("json", {}))
            return MockResponse({"choices": [{"message": {"content": '{"entities": []}'}}]})

        mock_httpx_client.return_value.__enter__.return_value.post.side_effect = (
            capture_post
        )

        extract_entities("Alice created Project Alpha")

        assert captured_json["model"] == ENTITY_MODEL
        assert captured_json["temperature"] == 0.0
        assert captured_json["max_tokens"] == 512
        assert any(
            msg["role"] == "system" and msg["content"] == SYSTEM_PROMPT
            for msg in captured_json["messages"]
        )
        assert any(
            msg["role"] == "user"
            and "Alice created Project Alpha" in msg["content"]
            for msg in captured_json["messages"]
        )
