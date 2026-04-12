"""MCP bearer token authentication guard."""
from mcp.server.auth.provider import AccessToken, TokenVerifier

from app import config


class BearerTokenVerifier(TokenVerifier):
    """
    Simple token verifier for single-key deployments.

    Verifies bearer tokens against LOGIOS_BRAIN_KEY.
    Returns an AccessToken with the client_id set to the key hash.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != config.LOGIOS_BRAIN_KEY:
            return None
        return AccessToken(
            token=token,
            client_id="logios-brain",
            scopes=["default"],
        )
