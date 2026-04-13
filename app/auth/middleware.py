"""Auth middleware — validates bearer JWT on every request."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.auth.security import decode_access_token
from app.schemas import AuthContext


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate bearer JWT on every request. Attaches AuthContext to request.state."""

    EXEMPT_PATHS = {
        "/health",
        "/health/ready",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/auth/setup",
        "/auth/verify-setup",
        "/auth/login",
        "/auth/token/refresh",
        "/auth/token/agent",
    }

    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(p) for p in self.EXEMPT_PATHS):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return Response(
                content='{"error": "invalid_token", "error_description": "Authentication required"}',
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
                media_type="application/json",
            )

        token = auth_header[7:]
        payload = decode_access_token(token)
        if payload is None:
            return Response(
                content='{"error": "invalid_token", "error_description": "Invalid or expired token"}',
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
                media_type="application/json",
            )

        scope = payload.get("scope", "")
        subject = payload.get("sub", "")

        if scope == "owner":
            request.state.auth_context = AuthContext(
                owner_id=int(subject) if subject.isdigit() else None,
                token_scope="owner",
            )
        elif scope == "agent":
            request.state.auth_context = AuthContext(
                token_hash=subject,
                agent_id=subject,
                token_scope="agent",
            )
        else:
            return Response(
                content='{"error": "invalid_token", "error_description": "Invalid token scope"}',
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
                media_type="application/json",
            )

        return await call_next(request)
