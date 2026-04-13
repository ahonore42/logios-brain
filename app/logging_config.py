"""Structured JSON logging configuration with request ID propagation."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import TENANT_ID

# Context variable for request-scoped request ID.
# Any logger call within a request handler automatically inherits this.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


# ── JSON Formatter ─────────────────────────────────────────────────────────────


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        msg: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Append explicit LogRecord attributes
        for key, value in vars(record).items():
            if key in (
                "request_id",
                "method",
                "path",
                "status_code",
                "latency_ms",
                "tenant_id",
                "user_agent",
            ):
                msg[key] = value

        # Fall back to contextvar for request_id (covers log calls from deep code)
        if "request_id" not in msg:
            ctx_val = request_id_var.get()
            if ctx_val:
                msg["request_id"] = ctx_val

        # Include exception info if present
        if record.exc_info:
            msg["exception"] = self.formatException(record.exc_info)

        return json.dumps(msg, default=str)


# ── Middleware ─────────────────────────────────────────────────────────────────


class RequestLogMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware that:

    1. Generates or propagates X-Request-ID
    2. Logs every request with method, path, status, latency, tenant_id
    3. Adds X-Request-ID to the response headers
    """

    def __init__(self, app: Any, logger: logging.Logger) -> None:
        super().__init__(app)
        self.logger = logger

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Propagate existing request ID or generate a new one
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.state.request_id = request_id

        # Set context var so all downstream loggers inherit the request ID
        token = request_id_var.set(request_id)

        start = time.perf_counter()
        response: Response | None = None

        try:
            response = await call_next(request)
        except Exception as exc:
            raise exc from None
        finally:
            latency_ms = (time.perf_counter() - start) * 1000

            self.logger.info(
                "",
                extra={
                    "request_id": request_id,
                    "tenant_id": TENANT_ID,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code if response else 0,
                    "latency_ms": round(latency_ms, 2),
                    "user_agent": request.headers.get("user-agent", ""),
                },
            )
            request_id_var.reset(token)

        # Always include request ID in response
        response.headers["X-Request-ID"] = request_id
        return response


# ── Configuration ─────────────────────────────────────────────────────────────


def configure_logging(json_format: bool = False) -> None:
    """
    Configure root logger.

    Args:
        json_format: If True, use structured JSON output. Otherwise human-readable.
    """
    handler = logging.StreamHandler(sys.stdout)

    if json_format:
        formatter: logging.Formatter = JsonFormatter()
    else:
        # Human-readable dev format: timestamp level name message
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)-20s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)

    # Root logger — capture everything
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Quiet down noisy third-party loggers
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
