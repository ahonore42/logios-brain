"""Shared FastAPI dependencies for Logios Brain."""

from typing import Annotated

from fastapi import Header, HTTPException

from app import config


def verify_key(
    x_brain_key: Annotated[str | None, Header()] = None,
    key: str | None = None,
) -> str:
    """Authenticate requests via X-Brain-Key header or ?key= query param."""
    provided = x_brain_key or key
    if provided != config.MCP_ACCESS_KEY:
        raise HTTPException(status_code=401, detail="Invalid access key")
    return provided
