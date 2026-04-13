"""Auth endpoints — owner setup, login, token management."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.auth import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    generate_raw_token,
    get_password_hash,
    hash_token,
    verify_password,
)
from app.dependencies import (
    AuthContext,
    get_session,
    require_owner,
)
from app.models import AgentToken, Owner
from app.schemas import (
    Message,
    OwnerPublic,
    OwnerSetup,
    Token,
    TokenCreate,
    TokenCreateResponse,
    TokenList,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/setup", status_code=status.HTTP_201_CREATED)
async def setup_owner(
    body: OwnerSetup,
    x_secret_key: str = Header(..., alias="X-Secret-Key"),
    session: AsyncSession = Depends(get_session),
):
    """Initiate owner account setup. Sends OTP to the provided email.

    Returns a pending_token. Complete setup by calling POST /auth/verify-setup
    with the OTP sent to the owner's email.
    """
    if x_secret_key != config.SECRET_KEY:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Invalid secret key"},
        )

    result = await session.execute(select(Owner))
    existing = result.scalar_one_or_none()
    if existing is not None and existing.is_setup:
        raise HTTPException(
            status_code=409,
            detail={"error": "conflict", "message": "Owner already set up"},
        )

    hashed_password = get_password_hash(body.password)

    from app.auth.pending import create_pending_setup
    from app.email import generate_setup_otp_email, send_email

    pending_token, otp = create_pending_setup(body.email, hashed_password)

    subject, html_content = generate_setup_otp_email(body.email, otp)
    send_email(email_to=body.email, subject=subject, html_content=html_content)

    response: dict[str, str] = {
        "pending_token": pending_token,
        "message": "Verification code sent to email. Complete setup within 10 minutes.",
    }

    # When emails are disabled (dev mode), return the OTP directly so setup can complete
    if not config.EMAILS_ENABLED:
        response["otp"] = otp
        response["message"] = "Emails disabled — use the OTP below to complete setup."

    return response


@router.post(
    "/verify-setup", response_model=OwnerPublic, status_code=status.HTTP_201_CREATED
)
async def verify_setup(
    pending_token: str = Form(...),
    otp: str = Form(...),
    x_secret_key: str = Header(..., alias="X-Secret-Key"),
    session: AsyncSession = Depends(get_session),
):
    """Complete owner account setup with the OTP from the verification email.

    The pending_token was returned by POST /auth/setup. The OTP was sent to the
    owner's email. Both expire after 10 minutes.
    """
    if x_secret_key != config.SECRET_KEY:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Invalid secret key"},
        )

    from app.auth.pending import verify_pending_setup

    ok, email, hashed_password = verify_pending_setup(pending_token, otp)
    if not ok:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_pending_or_otp",
                "message": "Invalid or expired verification code",
            },
        )

    result = await session.execute(select(Owner))
    existing = result.scalar_one_or_none()
    if existing is not None and existing.is_setup:
        raise HTTPException(
            status_code=409,
            detail={"error": "conflict", "message": "Owner already set up"},
        )

    if existing is None:
        owner = Owner(email=email, hashed_password=hashed_password, is_setup=True)
        session.add(owner)
    else:
        existing.email = email
        assert hashed_password is not None
        existing.hashed_password = hashed_password
        existing.is_setup = True
        owner = existing

    await session.commit()
    await session.refresh(owner)
    return OwnerPublic(
        id=owner.id,
        email=owner.email,
        is_setup=owner.is_setup,
        created_at=owner.created_at,
    )


@router.post("/login", response_model=Token)
async def login(
    email: str = Form(...),
    password: str = Form(...),
    x_secret_key: str = Header(..., alias="X-Secret-Key"),
    session: AsyncSession = Depends(get_session),
):
    """Owner login with email + password. Returns access + refresh tokens."""
    if x_secret_key != config.SECRET_KEY:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Invalid secret key"},
        )

    result = await session.execute(select(Owner).where(Owner.email == email))
    owner = result.scalar_one_or_none()

    if owner is None or not owner.is_setup:
        # Same message for email not found to prevent enumeration
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_credentials",
                "message": "Incorrect email or password",
            },
        )

    ok, _ = verify_password(password, owner.hashed_password)
    if not ok:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_credentials",
                "message": "Incorrect email or password",
            },
        )

    access_token = create_access_token(
        subject=str(owner.id),
        expires_delta=timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES),
        scope="owner",
    )
    refresh_token = create_refresh_token(subject=str(owner.id))

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/token/refresh", response_model=Token)
async def refresh_token(
    refresh_token: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """Exchange a refresh token for a new access token."""
    payload = decode_access_token(refresh_token)
    if payload is None or payload.get("scope") != "refresh":
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_token",
                "message": "Invalid or expired refresh token",
            },
        )

    access_token = create_access_token(
        subject=payload["sub"],
        expires_delta=timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES),
        scope="owner",
    )
    new_refresh = create_refresh_token(subject=payload["sub"])

    return Token(
        access_token=access_token,
        refresh_token=new_refresh,
        token_type="bearer",
        expires_in=config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/token/agent", response_model=Token)
async def agent_token_login(
    authorization: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """Exchange a raw agent token for a short-lived access token.

    Agents receive their raw token once at provisioning time via POST /auth/tokens.
    They call this endpoint with that raw token to get a JWT to use for
    subsequent authenticated requests to /mcp.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_token",
                "message": "Expected Bearer <raw_agent_token>",
            },
        )

    raw_token = authorization[7:]
    token_hash = hash_token(raw_token)

    result = await session.execute(
        select(AgentToken).where(AgentToken.token_hash == token_hash)
    )
    agent_token = result.scalar_one_or_none()

    if agent_token is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_token", "message": "Invalid agent token"},
        )

    if agent_token.revoked_at is not None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "token_revoked",
                "message": "Agent token has been revoked",
            },
        )

    # Update last_used_at
    agent_token.last_used_at = datetime.utcnow()
    await session.commit()

    access_token = create_access_token(
        subject=agent_token.agent_id,
        expires_delta=timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES),
        scope="agent",
    )

    return Token(
        access_token=access_token,
        refresh_token="",  # agents don't get refresh tokens
        token_type="bearer",
        expires_in=config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/tokens", response_model=TokenCreateResponse, status_code=status.HTTP_201_CREATED
)
async def create_agent_token(
    body: TokenCreate,
    owner: AuthContext = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    """Create a new agent token. Owner only."""
    raw_token = generate_raw_token()
    token_hash = hash_token(raw_token)
    agent_id = f"agent-{hash_token(raw_token)[:16]}"  # deterministic ID

    token = AgentToken(
        token_hash=token_hash,
        agent_id=agent_id,
        name=body.name,
    )
    session.add(token)
    await session.commit()
    await session.refresh(token)

    return TokenCreateResponse(
        id=token.id,
        agent_id=agent_id,
        token=raw_token,  # shown ONLY here
        name=body.name,
        created_at=token.created_at,
    )


@router.get("/tokens", response_model=TokenList)
async def list_tokens(
    owner: AuthContext = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    """List all agent tokens. Owner only. Never returns raw tokens."""
    result = await session.execute(
        select(AgentToken).order_by(AgentToken.created_at.desc())
    )
    tokens = result.scalars().all()

    return TokenList(
        data=[TokenResponse.from_row(t) for t in tokens],
        count=len(tokens),
    )


@router.delete("/tokens/{token_hash}", response_model=Message)
async def revoke_token(
    token_hash: str,
    owner: AuthContext = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    """Revoke an agent token by its hash. Owner only."""
    result = await session.execute(
        select(AgentToken).where(AgentToken.token_hash == token_hash)
    )
    token = result.scalar_one_or_none()
    if token is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "message": "Token not found"}
        )
    token.revoked_at = datetime.utcnow()
    await session.commit()
    return Message(message="Token revoked")


@router.get("/me", response_model=OwnerPublic)
async def get_me(
    owner: AuthContext = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    """Get current owner info."""
    result = await session.execute(select(Owner))
    db_owner = result.scalar_one_or_none()
    if db_owner is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "message": "Owner not found"}
        )
    return OwnerPublic(
        id=db_owner.id,
        email=db_owner.email,
        is_setup=db_owner.is_setup,
        created_at=db_owner.created_at,
    )


@router.get("/tokens/verify/{raw_token}", response_model=TokenResponse | None)
async def verify_token(
    raw_token: str,
    session: AsyncSession = Depends(get_session),
):
    """Check if a raw token is valid (not revoked). Returns token info or 404."""
    token_hash = hash_token(raw_token)
    result = await session.execute(
        select(AgentToken).where(AgentToken.token_hash == token_hash)
    )
    token = result.scalar_one_or_none()
    if token is None or token.revoked_at is not None:
        return None
    return TokenResponse.from_row(token)
