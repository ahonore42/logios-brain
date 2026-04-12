"""Tests for auth security primitives."""

import time
from datetime import timedelta

import pytest

from app.auth import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    generate_raw_token,
    get_password_hash,
    hash_token,
    verify_password,
    verify_token,
)


class TestTokenHashing:
    def test_hash_token_hex_encoded(self):
        h = hash_token("my-secret-token")
        assert len(h) == 64  # SHA256 = 32 bytes = 64 hex chars
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_token_same_input_same_output(self):
        h1 = hash_token("token")
        h2 = hash_token("token")
        assert h1 == h2

    def test_hash_token_different_input_different_output(self):
        h1 = hash_token("token1")
        h2 = hash_token("token2")
        assert h1 != h2

    def test_hash_token_irreversible(self):
        """SHA256 is one-way — cannot recover plain from hash."""
        h = hash_token("my-secret-token")
        assert "my-secret-token" not in h

    def test_verify_token_correct(self):
        plain = "agent-laptop-token-abc123"
        hashed = hash_token(plain)
        assert verify_token(plain, hashed) is True

    def test_verify_token_wrong(self):
        plain = "agent-laptop-token-abc123"
        hashed = hash_token(plain)
        assert verify_token("wrong-token", hashed) is False

    def test_verify_token_same_hash_fails(self):
        plain = "token"
        hashed = hash_token(plain)
        # Verify using the hash itself should fail (not a valid plain)
        assert verify_token(hashed, hashed) is False


class TestAccessToken:
    def test_create_and_decode_valid_token(self):
        token = create_access_token(
            subject="agent-1",
            expires_delta=timedelta(minutes=30),
            scope="agent",
        )
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "agent-1"
        assert payload["scope"] == "agent"
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload

    def test_decode_tampered_token_returns_none(self):
        token = create_access_token(
            subject="agent-1",
            expires_delta=timedelta(minutes=30),
        )
        tampered = token[:-5] + "XXXXX"
        assert decode_access_token(tampered) is None

    def test_decode_expired_token_returns_none(self):
        token = create_access_token(
            subject="agent-1",
            expires_delta=timedelta(seconds=1),
        )
        time.sleep(1.2)  # let it expire
        assert decode_access_token(token) is None

    def test_create_access_token_zero_duration_raises(self):
        with pytest.raises(ValueError, match="expires_delta must be positive"):
            create_access_token(
                subject="agent-1",
                expires_delta=timedelta(seconds=0),
            )

    def test_create_access_token_negative_duration_raises(self):
        with pytest.raises(ValueError, match="expires_delta must be positive"):
            create_access_token(
                subject="agent-1",
                expires_delta=timedelta(seconds=-1),
            )

    def test_create_access_token_with_extra_claims(self):
        token = create_access_token(
            subject="agent-1",
            expires_delta=timedelta(minutes=30),
            extra_claims={"machine": "laptop-1"},
        )
        payload = decode_access_token(token)
        assert payload["machine"] == "laptop-1"


class TestRefreshToken:
    def test_create_refresh_token_has_scope_refresh(self):
        token = create_refresh_token(subject="agent-1")
        payload = decode_access_token(token)
        assert payload["scope"] == "refresh"

    def test_refresh_token_longer_than_access(self):
        access = create_access_token(
            subject="agent-1", expires_delta=timedelta(minutes=60)
        )
        refresh = create_refresh_token(subject="agent-1")
        access_payload = decode_access_token(access)
        refresh_payload = decode_access_token(refresh)
        assert refresh_payload["exp"] > access_payload["exp"]


class TestPasswordHashing:
    def test_password_hash_is_different_each_time(self):
        """bcrypt includes random salt, so identical passwords produce different hashes."""
        h1 = get_password_hash("secret123")
        h2 = get_password_hash("secret123")
        assert h1 != h2
        assert h1.startswith("$2b$") and h2.startswith("$2b$")

    def test_verify_password_correct(self):
        ok, value = verify_password("secret123", get_password_hash("secret123"))
        assert ok is True
        assert value == "secret123"

    def test_verify_password_wrong(self):
        hashed = get_password_hash("correct-password")
        ok, value = verify_password("wrong-password", hashed)
        assert ok is False
        assert value == ""


class TestGenerateRawToken:
    def test_generate_raw_token_64_chars(self):
        token = generate_raw_token()
        assert len(token) == 64

    def test_generate_raw_token_unique(self):
        tokens = [generate_raw_token() for _ in range(100)]
        assert len(set(tokens)) == 100
