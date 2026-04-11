"""Shared FastAPI dependencies for Logios Brain."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException

from app import config


@dataclass
class AuthContext:
    """Resolved auth context for a request — tenant_id is always set; agent_id is optional."""

    tenant_id: str
    agent_id: str | None = None


def verify_key(
    x_brain_key: Annotated[str | None, Header()] = None,
    key: str | None = None,
) -> AuthContext:
    """Authenticate a request via X-Brain-Key header or ?key= query param.

    Resolves to the configured tenant. agent_id is left as None until
    per-key agent labels are configured.
    """
    provided = x_brain_key or key
    if provided != config.LOGIOS_BRAIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid access key")
    return AuthContext(tenant_id=config.TENANT_ID)
