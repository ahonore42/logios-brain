"""Live integration tests: simulate Hermes Agent lifecycle against Logios Brain.

Run with: uv run pytest tests/test_hermes_live.py -v
Requires: docker compose up (postgres, qdrant, redis, app)

These are live integration tests — skipped in CI.
"""

import pytest
import os

SKIP_LIVE = os.environ.get("CI", "").lower() in ("1", "true", "yes")

API_BASE = "http://localhost:8000"
SESSION_ID = "live-hermes-test"
AGENT_ID = "hermes-live-agent"


@pytest.fixture
def provider():
    """Create a LogiosMemoryProvider connected to the live app."""
    import sys
    sys.path.insert(0, "app")

    import importlib.util

    # Load hermes.py directly to avoid app.integrations __init__ path issues
    spec = importlib.util.spec_from_file_location(
        "hermes_live", "app/integrations/hermes.py"
    )
    hermes = importlib.util.module_from_spec(spec)
    sys.modules["hermes_live"] = hermes
    spec.loader.exec_module(hermes)

    provider = hermes.LogiosMemoryProvider(
        api_base_url=API_BASE,
        api_key="tok_placeholder",
        session_id=SESSION_ID,
        agent_id=AGENT_ID,
        redis_url="redis://localhost:6379",
        snapshot_threshold=3,
    )
    return provider


@pytest.mark.skipif(SKIP_LIVE, reason="Live integration test — requires running Docker services")
class TestHermesLiveIntegration:
    def test_is_available(self, provider):
        assert provider.is_available() is True

    def test_initialize(self, provider):
        provider.initialize(session_id=SESSION_ID)
        assert provider._initialized is True
        assert provider._working is not None
        assert provider._trigger is not None

    def test_system_prompt_block_returns_empty(self, provider):
        block = provider.system_prompt_block()
        assert block == ""

    def test_get_tool_schemas_returns_empty_list(self, provider):
        schemas = provider.get_tool_schemas()
        assert schemas == []

    def test_sync_turn_buffers_turns(self, provider):
        provider.initialize(session_id=SESSION_ID)
        provider.sync_turn(user_content="Hello", assistant_content="Hi there!")
        assert provider._turn_index == 1
        provider.sync_turn(user_content="How are you?", assistant_content="Fine thanks")
        assert provider._turn_index == 2

    def test_prefetch_returns_context_or_empty(self, provider):
        provider.initialize(session_id=SESSION_ID)
        result = provider.prefetch("test query")
        # Without valid auth, returns empty string (non-fatal)
        assert isinstance(result, str)

    def test_shutdown_completes(self, provider):
        provider.initialize(session_id=SESSION_ID)
        provider.sync_turn(user_content="test", assistant_content="test")
        provider.shutdown()  # should not raise
