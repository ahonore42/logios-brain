"""Shared FastAPI dependencies for Logios Brain."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.db.database import get_db
from app.auth import AuthContext


# ── Legacy auth (deprecated) ──────────────────────────────────────────────────


def verify_key(
    x_brain_key: Annotated[str | None, Header()] = None,
    key: str | None = None,
) -> AuthContext:
    """Authenticate a request via X-Brain-Key header or ?key= query param.

    Deprecated — use require_owner or require_agent instead.
    """
    raise HTTPException(status_code=401, detail="Invalid access key")


# ── Token auth deps ──────────────────────────────────────────────────────────


async def get_session():
    """Database session for auth router."""
    async for session in get_db():
        yield session


def get_current_token(request: Request) -> AuthContext:
    """Validate bearer token from Authorization header and return AuthContext.

    Checks:
    1. Authorization header is present and starts with "Bearer "
    2. JWT is valid and not expired
    3. Token scope is 'agent' or 'owner' (not 'refresh')

    Raises HTTPException 401 if any check fails.
    """
    from app.auth import decode_access_token

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_token",
                "error_description": "Missing bearer token",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_header[7:]  # strip "Bearer "
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_token",
                "error_description": "Invalid or expired token",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    scope = payload.get("scope", "")
    subject = payload.get("sub", "")

    if scope == "refresh":
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_token",
                "error_description": "Refresh tokens cannot access resources",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    if scope == "owner":
        return AuthContext(
            token_hash=subject,
            owner_id=int(subject) if subject.isdigit() else None,
            token_scope="owner",
        )

    if scope == "agent":
        return AuthContext(
            token_hash=subject,
            agent_id=subject,
            token_scope="agent",
        )

    raise HTTPException(
        status_code=401,
        detail={"error": "invalid_token", "error_description": "Unknown token scope"},
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_owner(ctx: AuthContext = Depends(get_current_token)) -> AuthContext:
    """Require token_scope == 'owner'. Returns 403 otherwise."""
    if ctx.token_scope != "owner":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "insufficient_scope",
                "error_description": "Owner privileges required",
            },
        )
    return ctx


def require_agent(ctx: AuthContext = Depends(get_current_token)) -> AuthContext:
    """Require token_scope == 'agent'. Returns 403 otherwise."""
    if ctx.token_scope != "agent":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "insufficient_scope",
                "error_description": "Agent privileges required",
            },
        )
    return ctx
