"""Security primitives — hashing, JWT creation/verification, password handling."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app import config


def hash_token(plain: str) -> str:
    """One-way SHA256 hash of a plain token. Hex-encoded."""
    return hashlib.sha256(plain.encode()).hexdigest()


def verify_token(plain: str, hashed: str) -> bool:
    """Constant-time compare of plain token against SHA256 hash."""
    return secrets.compare_digest(hash_token(plain), hashed)


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    scope: str = "agent",
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token with jti, iat, exp, sub, scope."""
    if expires_delta is None or expires_delta.total_seconds() <= 0:
        raise ValueError("expires_delta must be positive")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "scope": scope,
        "iat": now,
        "exp": now + expires_delta,
        "jti": secrets.token_urlsafe(16),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, config.ACCESS_SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Verify and decode a JWT access token. Returns None if invalid or expired."""
    try:
        payload = jwt.decode(token, config.ACCESS_SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def create_refresh_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT refresh token (longer-lived)."""
    if expires_delta is None:
        expires_delta = timedelta(days=30)
    return create_access_token(subject, expires_delta, scope="refresh")


def get_password_hash(password: str) -> str:
    """Bcrypt hash of a password."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> tuple[bool, str]:
    """Verify a password against a bcrypt hash. Returns (True, password) or (False, "")."""
    ok = bcrypt.checkpw(plain.encode(), hashed.encode())
    return (ok, plain if ok else "")


def generate_raw_token() -> str:
    """Generate a cryptographically random 32-byte hex token (64 chars)."""
    return secrets.token_hex(32)
