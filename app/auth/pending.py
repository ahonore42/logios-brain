"""Pending owner account setup — OTP email verification flow.

The flow:
1. POST /auth/setup     → create pending setup JWT, send OTP email, return pending_token
2. POST /auth/verify-setup → verify OTP, create owner account

Pending setup JWT is signed with ACCESS_SECRET_KEY. It encodes:
  - email
  - hashed_password
  - otp_hash (bcrypt of the 6-digit OTP — the JWT alone can't create an account)
  - jti (unique ID, stored to prevent replay if needed)
  - exp (10 minutes)
  - purpose ("owner_setup")
"""

from __future__ import annotations

import secrets

import bcrypt
import jwt

from app import config


def _generate_otp() -> str:
    """Generate a 6-digit OTP."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_otp(otp: str) -> str:
    """One-way bcrypt hash of the OTP."""
    return bcrypt.hashpw(otp.encode(), bcrypt.gensalt()).decode()


def _verify_otp(otp: str, otp_hash: str) -> bool:
    """Constant-time verify OTP against its bcrypt hash."""
    try:
        return bcrypt.checkpw(otp.encode(), otp_hash.encode())
    except Exception:
        return False


def create_pending_setup(email: str, hashed_password: str) -> tuple[str, str]:
    """
    Create a pending setup JWT and return it alongside the plaintext OTP.

    The OTP is sent to the user's email. The JWT encodes the hashed_password
    and a bcrypt hash of the OTP — only a correct OTP can redeem the JWT.

    Returns (pending_jwt, plaintext_otp).
    """
    otp = _generate_otp()
    otp_hash = _hash_otp(otp)

    now = config.ACCESS_SECRET_KEY  # must be set
    import datetime

    payload = {
        "sub": email,
        "hashed_password": hashed_password,
        "otp_hash": otp_hash,
        "purpose": "owner_setup",
        "jti": secrets.token_urlsafe(16),
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "exp": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=config.EMAIL_OTP_EXPIRE_MINUTES),
    }

    jwt_token = jwt.encode(payload, now, algorithm="HS256")
    return jwt_token, otp


def verify_pending_setup(
    pending_jwt: str, otp: str
) -> tuple[bool, str | None, str | None]:
    """
    Verify a pending setup JWT and OTP.

    Returns (success, email, hashed_password).
    On failure: (False, None, None).
    """
    try:
        payload = jwt.decode(
            pending_jwt,
            config.ACCESS_SECRET_KEY,
            algorithms=["HS256"],
            options={
                "require": ["exp", "sub", "hashed_password", "otp_hash", "purpose"]
            },
        )
    except jwt.ExpiredSignatureError:
        return False, None, None
    except jwt.InvalidTokenError:
        return False, None, None

    if payload.get("purpose") != "owner_setup":
        return False, None, None

    if not _verify_otp(otp, payload["otp_hash"]):
        return False, None, None

    return True, payload["sub"], payload["hashed_password"]
