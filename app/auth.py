"""Global auth middleware for Logios Brain.

Applies bearer token validation to every request — REST API, MCP, all of it.
Houses AuthContext so any route or dependency can access the resolved identity.
"""
from dataclasses import dataclass
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app import config


@dataclass
class AuthContext:
    """Resolved identity for a request. agent_id is None until per-key agent mapping is added."""
    tenant_id: str
    agent_id: str | None = None


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate bearer token on every request and attach AuthContext to scope."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not token or token != config.LOGIOS_BRAIN_KEY:
            return Response(
                content='{"error": "invalid_token", "error_description": "Authentication required"}',
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
                media_type="application/json",
            )
        # Attach auth context to request state for downstream access
        request.state.auth_context = AuthContext(
            tenant_id=config.TENANT_ID,
            agent_id=None,
        )
        return await call_next(request)