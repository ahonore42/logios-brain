"""Tests for observability endpoints — /metrics, /health, and telemetry module."""

from unittest.mock import patch, MagicMock

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """TestClient without server exceptions so we see HTTP status codes."""
    return TestClient(app, raise_server_exceptions=False)


# ── /health ────────────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── /health/ready store checks (unit tests on the helper functions) ───────────


class TestStoreCheckHelpers:
    """Unit tests for the individual _check_* helper functions.

    These test the logic directly without going through the HTTP layer,
    avoiding auth middleware complications.
    """

    def test_check_postgres_returns_healthy_on_success(self):
        from app.routes.health import _check_postgres

        with patch("app.routes.health.create_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_engine.return_value.__enter__.return_value.connect.return_value.__enter__.return_value = mock_conn
            result = _check_postgres()

            assert result.healthy is True
            assert result.latency_ms is not None
            assert result.error is None

    def test_check_postgres_returns_unhealthy_on_failure(self):
        from app.routes.health import _check_postgres

        with patch("app.routes.health.create_engine") as mock_engine:
            # create_engine itself raises (e.g. invalid DSN)
            mock_engine.side_effect = Exception("connection refused")
            result = _check_postgres()

            assert result.healthy is False
            assert "connection refused" in result.error

    def test_check_qdrant_returns_healthy_on_success(self):
        from app.routes.health import _check_qdrant

        with patch("app.routes.health.QdrantClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            result = _check_qdrant()

            assert result.healthy is True
            assert result.latency_ms is not None
            assert result.error is None
            mock_client.http.collections_api.get_collections.assert_called_once()

    def test_check_qdrant_returns_unhealthy_on_failure(self):
        from app.routes.health import _check_qdrant

        with patch("app.routes.health.QdrantClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.http.collections_api.get_collections.side_effect = Exception("timeout")
            result = _check_qdrant()

            assert result.healthy is False
            assert "timeout" in result.error

    def test_check_neo4j_returns_healthy_on_success(self):
        from app.routes.health import _check_neo4j

        with patch("neo4j.GraphDatabase") as mock_gdb:
            mock_driver = MagicMock()
            mock_gdb.driver.return_value = mock_driver
            result = _check_neo4j()

            assert result.healthy is True
            assert result.latency_ms is not None
            assert result.error is None
            mock_driver.session.assert_called_once()

    def test_check_neo4j_returns_unhealthy_on_failure(self):
        from app.routes.health import _check_neo4j

        with patch("neo4j.GraphDatabase") as mock_gdb:
            mock_gdb.driver.side_effect = Exception("auth failure")
            result = _check_neo4j()

            assert result.healthy is False
            assert "auth failure" in result.error

    def test_check_redis_returns_healthy_on_success(self):
        from app.routes.health import _check_redis

        with patch("app.routes.health.redis") as mock_redis:
            mock_r = MagicMock()
            mock_redis.from_url.return_value = mock_r
            result = _check_redis()

            assert result.healthy is True
            assert result.latency_ms is not None
            assert result.error is None
            mock_r.ping.assert_called_once()

    def test_check_redis_returns_unhealthy_on_failure(self):
        from app.routes.health import _check_redis

        with patch("app.routes.health.redis") as mock_redis:
            mock_r = MagicMock()
            mock_redis.from_url.side_effect = Exception("redis connection error")
            result = _check_redis()

            assert result.healthy is False
            assert "redis connection error" in result.error


# ── /metrics endpoint ───────────────────────────────────────────────────────────


class TestMetricsEndpoint:
    """Test /metrics endpoint responses.

    /metrics is exempt from auth — Prometheus scrapes without a bearer token.
    """

    def test_metrics_returns_200(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type_is_prometheus(self, client):
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers["Content-Type"]

    def test_metrics_includes_logios_memory_count(self, client):
        resp = client.get("/metrics")
        assert b"logios_memory_count" in resp.content

    def test_metrics_includes_logios_memory_total(self, client):
        resp = client.get("/metrics")
        assert b"logios_memory_total" in resp.content

    def test_metrics_includes_logios_generation_total(self, client):
        resp = client.get("/metrics")
        assert b"logios_generation_total" in resp.content

    def test_metrics_includes_logios_evidence_total(self, client):
        resp = client.get("/metrics")
        assert b"logios_evidence_total" in resp.content

    def test_metrics_includes_logios_http_request_latency_seconds(self, client):
        resp = client.get("/metrics")
        assert b"logios_http_request_latency_seconds" in resp.content

    def test_metrics_includes_logios_retrieval_latency_seconds(self, client):
        resp = client.get("/metrics")
        assert b"logios_retrieval_latency_seconds" in resp.content

    def test_metrics_includes_logios_celery_task_latency_seconds(self, client):
        resp = client.get("/metrics")
        assert b"logios_celery_task_latency_seconds" in resp.content

    def test_metrics_includes_logios_checkpoint_fired_total(self, client):
        resp = client.get("/metrics")
        assert b"logios_checkpoint_fired_total" in resp.content

    def test_metrics_includes_logios_errors_total(self, client):
        resp = client.get("/metrics")
        assert b"logios_errors_total" in resp.content

    def test_metrics_includes_logios_info(self, client):
        resp = client.get("/metrics")
        assert b"logios_info" in resp.content


# ── Telemetry module ─────────────────────────────────────────────────────────────


class TestTelemetryModule:
    """Test that telemetry metrics are properly defined and can be manipulated."""

    def test_telemetry_module_imports_successfully(self):
        from app import telemetry
        assert hasattr(telemetry, "MEMORY_COUNT")
        assert hasattr(telemetry, "GENERATION_COUNT")
        assert hasattr(telemetry, "RETRIEVAL_LATENCY")
        assert hasattr(telemetry, "QUERY_LATENCY")
        assert hasattr(telemetry, "CELERY_TASK_LATENCY")
        assert hasattr(telemetry, "CHECKPOINT_FIRED")
        assert hasattr(telemetry, "ERROR_COUNT")
        assert hasattr(telemetry, "EVIDENCE_COUNT_METRIC")

    def test_span_attribute_keys_are_defined(self):
        from app import telemetry

        assert telemetry.OPERATION == "logios.operation"
        assert telemetry.AGENT_ID == "logios.agent_id"
        assert telemetry.SESSION_ID == "logios.session_id"
        assert telemetry.MEMORY_TYPE == "logios.memory_type"
        assert telemetry.EVIDENCE_COUNT == "logios.evidence.count"
        assert telemetry.STORE == "logios.store"
        assert telemetry.TENANT_ID == "logios.tenant_id"

    def test_memory_count_gauge_can_be_set_and_decorate(self):
        from app import telemetry

        # Should not raise
        telemetry.MEMORY_COUNT.labels(agent_id="test-agent", memory_type="standard").set(42)
        telemetry.MEMORY_TOTAL.inc()
        telemetry.MEMORY_TOTAL.dec()

    def test_generation_counter_can_increment(self):
        from app import telemetry

        # Should not raise
        telemetry.GENERATION_COUNT.labels(agent_id="test-agent", skill_name="analysis").inc()
        telemetry.GENERATION_COUNT.labels(agent_id="test-agent", skill_name="analysis").inc(3)

    def test_evidence_counter_can_increment(self):
        from app import telemetry

        # Should not raise
        telemetry.EVIDENCE_COUNT_METRIC.labels(retrieval_type="vector").inc()
        telemetry.EVIDENCE_COUNT_METRIC.labels(retrieval_type="graph").inc(5)

    def test_checkpoint_counter_can_increment(self):
        from app import telemetry

        # Should not raise
        telemetry.CHECKPOINT_FIRED.labels(trigger_mode="call_count", agent_id="test-agent").inc()
        telemetry.CHECKPOINT_FIRED.labels(trigger_mode="token", agent_id="test-agent").inc()

    def test_error_counter_can_increment(self):
        from app import telemetry

        # Should not raise
        telemetry.ERROR_COUNT.labels(operation="remember", error_type="validation").inc()
        telemetry.ERROR_COUNT.labels(operation="search", error_type="store_error").inc()

    def test_retrieval_latency_histogram_observe(self):
        from app import telemetry

        # Should not raise
        telemetry.RETRIEVAL_LATENCY.labels(operation="search").observe(0.05)
        telemetry.RETRIEVAL_LATENCY.labels(operation="upsert").observe(0.12)

    def test_http_latency_histogram_observe(self):
        from app import telemetry

        # Should not raise
        telemetry.QUERY_LATENCY.labels(method="POST", endpoint="/memories/search", status_code="200").observe(0.12)
        telemetry.QUERY_LATENCY.labels(method="GET", endpoint="/health/ready", status_code="503").observe(0.05)

    def test_celery_task_latency_histogram_observe(self):
        from app import telemetry

        # Should not raise
        telemetry.CELERY_TASK_LATENCY.labels(task_name="task_extract_entities").observe(1.5)
        telemetry.CELERY_TASK_LATENCY.labels(task_name="task_upsert_qdrant").observe(0.8)

    def test_span_context_manager(self):
        from app import telemetry

        # Should not raise when OTel is not configured
        with telemetry.span("test.operation", {"logios.operation": "test"}):
            pass

    def test_set_span_attrs_from_auth_none(self):
        from app import telemetry

        # Should not raise with None auth context
        telemetry.set_span_attrs_from_auth(None)
