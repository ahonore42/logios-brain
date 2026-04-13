"""OpenTelemetry tracing and Prometheus metrics for Logios Brain.

Tracing is opt-in (OTEL_ENABLED=true). Metrics are always initialized.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    ParentBasedTraceIdRatio,
    TraceIdRatioBased,
)
from opentelemetry.semconv.resource import ResourceAttributes
from prometheus_client import Counter, Gauge, Histogram, Info

if TYPE_CHECKING:
    from opentelemetry.metrics import Meter
    from app.schemas import AuthContext

# ── Standard span attribute keys ───────────────────────────────────────────────

AGENT_ID = "logios.agent_id"
SESSION_ID = "logios.session_id"
MEMORY_TYPE = "logios.memory_type"
EVIDENCE_COUNT = "logios.evidence.count"
STORE = "logios.store"
OPERATION = "logios.operation"
TENANT_ID = "logios.tenant_id"

# ── Span attribute defaults ────────────────────────────────────────────────────

_SPAN_ATTRS_DEFAULTS: dict[str, str] = {
    ResourceAttributes.SERVICE_NAME: "logios-brain",
    ResourceAttributes.SERVICE_VERSION: "0.1.0",
}

# ── Metrics ───────────────────────────────────────────────────────────────────

# Service info (useful in Grafana for filtering by version)
SERVICE_INFO = Info("logios", "Logios Brain service information")
SERVICE_INFO.info({"version": "0.1.0", "service": "logios-brain"})

# Memory metrics
MEMORY_COUNT = Gauge(
    "logios_memory_count",
    "Number of memories in the system",
    ["agent_id", "memory_type"],
)
MEMORY_TOTAL = Gauge(
    "logios_memory_total",
    "Total number of memories across all agents",
    [],
)

# Generation / evidence metrics
GENERATION_COUNT = Counter(
    "logios_generation_total",
    "Total number of generations recorded",
    ["agent_id", "skill_name"],
)
EVIDENCE_COUNT_METRIC = Counter(
    "logios_evidence_total",
    "Total number of evidence records created",
    ["retrieval_type"],
)

# Latency histograms
RETRIEVAL_LATENCY = Histogram(
    "logios_retrieval_latency_seconds",
    "Latency of vector retrieval operations",
    ["operation"],  # search, upsert
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
QUERY_LATENCY = Histogram(
    "logios_http_request_latency_seconds",
    "Latency of HTTP requests to Logios endpoints",
    ["method", "endpoint", "status_code"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
CELERY_TASK_LATENCY = Histogram(
    "logios_celery_task_latency_seconds",
    "Latency of Celery tasks",
    ["task_name"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# Checkpoint metrics
CHECKPOINT_FIRED = Counter(
    "logios_checkpoint_fired_total",
    "Total number of checkpoint snapshots triggered",
    ["trigger_mode", "agent_id"],  # call_count, token, time_based
)

# Error counters
ERROR_COUNT = Counter(
    "logios_errors_total",
    "Total number of errors",
    ["operation", "error_type"],
)

# ── Tracer ─────────────────────────────────────────────────────────────────────

_tracer: trace.Tracer | None = None


def tracer() -> trace.Tracer:
    """Return the configured tracer. Initializes on first call."""
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer(__name__)
    return _tracer


# ── Configuration ──────────────────────────────────────────────────────────────


def configure() -> None:
    """Initialize OTel tracing and metrics. Call once at startup."""
    _configure_tracing()
    _configure_celery_instrumentation()


def _configure_tracing() -> None:
    """Set up the OTel tracer provider with OTLP exporter and instrumentors."""
    if not os.getenv("OTEL_ENABLED", "false").lower() == "true":
        return

    from opentelemetry import metrics
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    # Build Resource with standard attributes
    resource = Resource.create(_SPAN_ATTRS_DEFAULTS)

    # Determine sampler from env
    sampler = _build_sampler()

    # Tracer provider
    tracer_provider = TracerProvider(resource=resource, sampler=sampler)
    trace.set_tracer_provider(tracer_provider)

    # OTLP exporter — export spans to the collector
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    span_exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")

    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))

    # Auto-instrument httpx (used by integrations for LLM API calls)
    _instrument_httpx()

    # Metrics exporter — push metrics to OTLP endpoint
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{otlp_endpoint}/v1/metrics"),
        export_interval_millis=30_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)


def _build_sampler():
    """Build a sampler based on OTEL_TRACES_SAMPLER env var."""
    sampler_arg = os.getenv("OTEL_TRACES_SAMPLER_ARG", "0.1")
    sampler_rate = float(sampler_arg)

    sampler_name = os.getenv("OTEL_TRACES_SAMPLER", "parentbased_traceidratio")

    if sampler_name == "traceidratio":
        return TraceIdRatioBased(sampler_rate)
    elif sampler_name == "always_on":
        from opentelemetry.sdk.trace.sampling import AlwaysOn

        return AlwaysOn()
    elif sampler_name == "always_off":
        from opentelemetry.sdk.trace.sampling import AlwaysOff

        return AlwaysOff()
    else:
        # Default: parent-based — respects parent span's sampling decision,
        # falling back to traceidratio for root spans
        return ParentBasedTraceIdRatio(sampler_rate)


def _instrument_httpx() -> None:
    """Auto-instrument httpx (used by the integrations for LLM API calls)."""
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    except ImportError:
        return

    HTTPXClientInstrumentor().instrument()


def _configure_celery_instrumentation() -> None:
    """Configure Celery task instrumentation with context propagation."""
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
    except ImportError:
        return

    CeleryInstrumentor().instrument()


# ── FastAPI instrumentation helper ─────────────────────────────────────────────
# Called from main.py after the app is created


def instrument_app(app) -> None:
    """Apply FastAPI auto-instrumentation to the app instance.

    Call this after the FastAPI app is created. Health and metrics endpoints
    are excluded from tracing to reduce noise.
    """
    if not os.getenv("OTEL_ENABLED", "false").lower() == "true":
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        return

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health,health/ready,metrics",
    )


# ── Context helpers ─────────────────────────────────────────────────────────────


@contextmanager
def span(
    name: str,
    attributes: dict[str, str | int | float] | None = None,
):
    """Convenience context manager for creating a named span.

    Usage:
        with span("upsert_memory", {"logios.operation": "remember"}):
            ...
    """
    t = tracer()
    with t.start_as_current_span(name) as s:
        if attributes:
            for k, v in attributes.items():
                s.set_attribute(k, v)
        yield s


def set_span_attrs_from_auth(auth_context: "AuthContext | None") -> None:
    """Add standard logios span attributes from an AuthContext, if present."""
    if auth_context is None:
        return
    span_ = trace.get_current_span()
    if span_ and span_.is_recording():
        if auth_context.agent_id:
            span_.set_attribute(AGENT_ID, auth_context.agent_id)
        if auth_context.owner_id:
            span_.set_attribute("logios.owner_id", str(auth_context.owner_id))


# ── Meter helpers ──────────────────────────────────────────────────────────────


def get_meter() -> "Meter":
    """Return the OTel meter for creating custom metrics."""
    from opentelemetry import metrics

    return metrics.get_meter(__name__)
