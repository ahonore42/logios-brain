"""Auth — JWT token auth, middleware, and owner/agent account management."""

from app.auth.security import (
    hash_token,
    verify_token,
    create_access_token,
    decode_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    generate_raw_token,
)
from app.auth.middleware import AuthMiddleware
from app.auth.pending import (
    create_pending_setup,
    verify_pending_setup,
)
from app.schemas import AuthContext, PendingSetup

__all__ = [
    # security
    "hash_token",
    "verify_token",
    "create_access_token",
    "decode_access_token",
    "create_refresh_token",
    "get_password_hash",
    "verify_password",
    "generate_raw_token",
    # context
    "AuthContext",
    # middleware
    "AuthMiddleware",
    # pending setup
    "create_pending_setup",
    "verify_pending_setup",
    "PendingSetup",
]
