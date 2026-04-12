"""Tests for auth endpoints — setup, login, token CRUD."""

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models import AgentToken, Owner
from app.auth import hash_token

# Deployer secret used in tests (set in conftest.py via SECRET_KEY env var)
TEST_SECRET_HEADER = {"X-Secret-Key": "test-deployer-secret-for-testing-only"}


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
async def clean_auth_tables():
    """Wipe owner and agent_tokens before each test."""
    from app.db.database import get_db
    from sqlalchemy import delete

    async for session in get_db():
        await session.execute(delete(AgentToken))
        await session.execute(delete(Owner))
        await session.commit()
        break


@pytest.fixture
def setup_owner(client):
    """Create a fresh owner via the two-step OTP flow. Returns (client, access_token)."""
    import re
    from unittest.mock import patch

    captured_otp = {}

    def mock_send_email(*, email_to, subject, html_content):
        match = re.search(r">(\d{6})<", html_content)
        if match:
            captured_otp["otp"] = match.group(1)

    with patch("app.email.send_email", side_effect=mock_send_email):
        setup_resp = client.post(
            "/auth/setup",
            json={"email": "owner@example.com", "password": "secretpassword123"},
            headers=TEST_SECRET_HEADER,
        )
        assert setup_resp.status_code == 201, f"setup failed: {setup_resp.text}"
        pending_token = setup_resp.json()["pending_token"]

        assert "otp" in captured_otp, f"OTP not captured from email: {captured_otp}"

        verify_resp = client.post(
            "/auth/verify-setup",
            data={"pending_token": pending_token, "otp": captured_otp["otp"]},
            headers=TEST_SECRET_HEADER,
        )
        assert verify_resp.status_code == 201, f"verify failed: {verify_resp.text}"

    login_resp = client.post(
        "/auth/login",
        data={"email": "owner@example.com", "password": "secretpassword123"},
        headers=TEST_SECRET_HEADER,
    )
    access_token = login_resp.json()["access_token"]
    return client, access_token


class TestSecretKey:
    def test_setup_requires_secret_key(self, client):
        """Missing X-Secret-Key header returns 422."""
        response = client.post(
            "/auth/setup",
            json={"email": "owner@example.com", "password": "secretpassword123"},
        )
        assert response.status_code == 422

    def test_setup_wrong_secret_key_returns_401(self, client):
        """Wrong X-Secret-Key returns 401."""
        response = client.post(
            "/auth/setup",
            json={"email": "owner@example.com", "password": "secretpassword123"},
            headers={"X-Secret-Key": "wrong-secret"},
        )
        assert response.status_code == 401

    def test_login_requires_secret_key(self, client):
        """Missing X-Secret-Key header returns 422."""
        response = client.post(
            "/auth/login",
            data={"email": "owner@example.com", "password": "any-password"},
        )
        assert response.status_code == 422

    def test_login_wrong_secret_key_returns_401(self, client):
        """Wrong X-Secret-Key returns 401."""
        response = client.post(
            "/auth/login",
            data={"email": "owner@example.com", "password": "any-password"},
            headers={"X-Secret-Key": "wrong-secret"},
        )
        assert response.status_code == 401


class TestOwnerSetup:
    def test_setup_initiate_returns_pending_token(self, client):
        """POST /auth/setup returns 201 and a pending_token (no owner created yet)."""
        response = client.post(
            "/auth/setup",
            json={"email": "owner@example.com", "password": "secretpassword123"},
            headers=TEST_SECRET_HEADER,
        )
        assert response.status_code == 201
        assert "pending_token" in response.json()

    def test_setup_twice_returns_409(self, client, setup_owner):
        """Once owner is set up, /auth/setup returns 409 on subsequent calls."""
        # setup_owner already created the owner
        response = client.post(
            "/auth/setup",
            json={"email": "owner@example.com", "password": "different123"},
            headers=TEST_SECRET_HEADER,
        )
        assert response.status_code == 409

    def test_setup_password_too_short(self, client):
        response = client.post(
            "/auth/setup",
            json={"email": "test@example.com", "password": "short"},
            headers=TEST_SECRET_HEADER,
        )
        assert response.status_code == 422

    def test_setup_invalid_email(self, client):
        response = client.post(
            "/auth/setup",
            json={"email": "not-an-email", "password": "secretpassword123"},
            headers=TEST_SECRET_HEADER,
        )
        assert response.status_code == 422


class TestVerifySetup:
    def test_verify_setup_creates_owner(self, client):
        """POST /auth/verify-setup with correct OTP creates the owner."""
        import re
        from unittest.mock import patch

        captured = {}

        def mock_send_email(*, email_to, subject, html_content):
            match = re.search(r">(\d{6})<", html_content)
            if match:
                captured["otp"] = match.group(1)

        with patch("app.email.send_email", side_effect=mock_send_email):
            setup_resp = client.post(
                "/auth/setup",
                json={"email": "verify@example.com", "password": "secretpassword123"},
                headers=TEST_SECRET_HEADER,
            )
            pending_token = setup_resp.json()["pending_token"]

            verify_resp = client.post(
                "/auth/verify-setup",
                data={"pending_token": pending_token, "otp": captured["otp"]},
                headers=TEST_SECRET_HEADER,
            )
            assert verify_resp.status_code == 201
            body = verify_resp.json()
            assert body["email"] == "verify@example.com"
            assert body["is_setup"] is True

    def test_verify_setup_wrong_otp_returns_401(self, client):
        """Wrong OTP returns 401."""
        from unittest.mock import patch

        def mock_send_email(*, email_to, subject, html_content):
            pass  # don't capture

        with patch("app.email.send_email", side_effect=mock_send_email):
            setup_resp = client.post(
                "/auth/setup",
                json={"email": "otp@example.com", "password": "secretpassword123"},
                headers=TEST_SECRET_HEADER,
            )
            pending_token = setup_resp.json()["pending_token"]

            verify_resp = client.post(
                "/auth/verify-setup",
                data={"pending_token": pending_token, "otp": "000000"},
                headers=TEST_SECRET_HEADER,
            )
            assert verify_resp.status_code == 401

    def test_verify_setup_expired_pending_returns_401(self, client):
        """Expired pending token returns 401."""
        verify_resp = client.post(
            "/auth/verify-setup",
            data={"pending_token": "expired.jwt.token", "otp": "123456"},
            headers=TEST_SECRET_HEADER,
        )
        assert verify_resp.status_code == 401


class TestOwnerLogin:
    def test_login_returns_tokens(self, setup_owner):
        client, access_token = setup_owner
        assert access_token is not None

    def test_login_wrong_password_returns_401(self, client):
        client.post(
            "/auth/setup",
            json={"email": "owner@example.com", "password": "correct-password"},
            headers=TEST_SECRET_HEADER,
        )
        response = client.post(
            "/auth/login",
            data={"email": "owner@example.com", "password": "wrong-password"},
            headers=TEST_SECRET_HEADER,
        )
        assert response.status_code == 401
        assert (
            "incorrect email or password"
            in response.json()["detail"]["message"].lower()
        )

    def test_login_wrong_email_returns_401(self, client):
        response = client.post(
            "/auth/login",
            data={"email": "nonexistent@example.com", "password": "any-password"},
            headers=TEST_SECRET_HEADER,
        )
        assert response.status_code == 401

    def test_login_before_setup_returns_401(self, client):
        response = client.post(
            "/auth/login",
            data={"email": "notsetup@example.com", "password": "any-password"},
            headers=TEST_SECRET_HEADER,
        )
        assert response.status_code == 401


class TestTokenManagement:
    def test_create_agent_token(self, setup_owner):
        client, access_token = setup_owner
        response = client.post(
            "/auth/tokens",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": "Claude Code laptop"},
        )
        assert response.status_code == 201, (
            f"Got {response.status_code}: {response.text[:200]}"
        )
        body = response.json()
        assert "token" in body
        assert len(body["token"]) == 64  # 32 bytes hex
        assert body["name"] == "Claude Code laptop"
        assert "agent_id" in body

    def test_create_agent_token_requires_owner(self, client):
        response = client.post(
            "/auth/tokens",
            json={"name": "unauthorized agent"},
        )
        assert response.status_code == 401

    def test_list_tokens_returns_all_active(self, setup_owner):
        client, access_token = setup_owner
        for name in ["Claude Code", "Cursor"]:
            client.post(
                "/auth/tokens",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"name": name},
            )

        response = client.get(
            "/auth/tokens",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] >= 2
        for token_info in body["data"]:
            assert "token" not in token_info  # raw token never returned
            assert "agent_id" in token_info
            assert token_info["is_active"] is True

    def test_revoke_token(self, setup_owner):
        client, access_token = setup_owner
        create_resp = client.post(
            "/auth/tokens",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": "Temporary agent"},
        )
        token_hash = hash_token(create_resp.json()["token"])

        response = client.delete(
            f"/auth/tokens/{token_hash}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200, (
            f"Got {response.status_code}: {response.text[:200]}"
        )

        list_resp = client.get(
            "/auth/tokens",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        active = [t for t in list_resp.json()["data"] if t["is_active"]]
        assert len(active) == 0

    def test_revoke_nonexistent_token_returns_404(self, setup_owner):
        client, access_token = setup_owner
        response = client.delete(
            "/auth/tokens/nonexistent-hash-value",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 404


class TestRefreshToken:
    def test_refresh_token_returns_new_access_token(self, setup_owner):
        client, _ = setup_owner
        login_resp = client.post(
            "/auth/login",
            data={"email": "owner@example.com", "password": "secretpassword123"},
            headers=TEST_SECRET_HEADER,
        )
        refresh = login_resp.json()["refresh_token"]

        response = client.post("/auth/token/refresh", data={"refresh_token": refresh})
        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_refresh_with_access_token_returns_401(self, setup_owner):
        client, access_token = setup_owner
        response = client.post(
            "/auth/token/refresh",
            data={"refresh_token": access_token},
        )
        assert response.status_code == 401


class TestAgentTokenLogin:
    def test_agent_exchanges_raw_token_for_jwt(self, setup_owner):
        """POST /auth/token/agent with raw token returns a short-lived JWT."""
        client, access_token = setup_owner

        # Create an agent token
        create_resp = client.post(
            "/auth/tokens",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": "test-agent"},
        )
        assert create_resp.status_code == 201
        raw_token = create_resp.json()["token"]

        # Exchange raw token for JWT
        resp = client.post(
            "/auth/token/agent",
            data={"authorization": f"Bearer {raw_token}"},
        )
        assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["refresh_token"] == ""

        # The returned token is a valid JWT that can be used against /mcp
        from app.auth import decode_access_token

        payload = decode_access_token(body["access_token"])
        assert payload is not None
        assert payload["scope"] == "agent"

    def test_agent_token_wrong_raw_token_returns_401(self, setup_owner):
        """Invalid raw token returns 401."""
        client, access_token = setup_owner

        resp = client.post(
            "/auth/token/agent",
            data={"authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401

    def test_agent_token_revoked_returns_401(self, setup_owner):
        """Revoked agent token cannot be exchanged for a JWT."""
        client, access_token = setup_owner

        # Create and revoke a token
        create_resp = client.post(
            "/auth/tokens",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": "revoked-agent"},
        )
        raw_token = create_resp.json()["token"]
        token_hash = hash_token(raw_token)

        client.delete(
            f"/auth/tokens/{token_hash}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        # Exchange revoked token
        resp = client.post(
            "/auth/token/agent",
            data={"authorization": f"Bearer {raw_token}"},
        )
        assert resp.status_code == 401
        assert "revoked" in resp.json()["detail"]["message"].lower()

    def test_agent_token_missing_bearer_prefix_returns_401(self, setup_owner):
        """Raw token without Bearer prefix returns 401."""
        client, access_token = setup_owner

        create_resp = client.post(
            "/auth/tokens",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": "another-agent"},
        )
        raw_token = create_resp.json()["token"]

        resp = client.post(
            "/auth/token/agent",
            data={"authorization": raw_token},  # missing "Bearer " prefix
        )
        assert resp.status_code == 401
