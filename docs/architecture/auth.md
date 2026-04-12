# Auth Architecture

## Overview

Logios Brain uses JWT-based authentication with a two-step owner account setup guarded by email OTP verification. There are two actor types: **owner** (the human deploying the system) and **agent** (any AI client that reads from or writes to the brain).

## Actors

| Actor | Identity | Can authenticate via |
|---|---|---|
| Owner | Email + password | `POST /auth/login` (after setup) |
| Agent | Raw token provisioned by owner | `POST /auth/token/agent` exchange |

## Tokens

### Access token (JWT)
Short-lived token (default: 60 minutes) authorizing API requests.

**Payload:**
```json
{
  "sub": "<owner_id or agent_id>",
  "scope": "owner | agent | refresh",
  "iat": "<issued at UTC>",
  "exp": "<expires at UTC>",
  "jti": "<unique token id>"
}
```

### Refresh token (JWT)
Long-lived token (default: 30 days) used only to obtain new access tokens via `POST /auth/token/refresh`.

### Raw agent token
A 64-character hex string generated once when the owner creates an agent token. This is shown **only at creation time** and must be transmitted securely to the agent. The agent exchanges it for a short-lived access token.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/auth/setup` | `X-Secret-Key` header | Initiate owner account creation (sends OTP email) |
| `POST` | `/auth/verify-setup` | `X-Secret-Key` header + `pending_token` + `otp` | Complete owner account creation |
| `POST` | `/auth/login` | `X-Secret-Key` header | Owner login → access + refresh tokens |
| `POST` | `/auth/token/refresh` | Refresh token (body) | Exchange refresh token for new access + refresh |
| `POST` | `/auth/tokens` | Owner JWT | Create a new agent raw token |
| `GET` | `/auth/tokens` | Owner JWT | List all agent tokens |
| `DELETE` | `/auth/tokens/{hash}` | Owner JWT | Revoke an agent token |
| `POST` | `/auth/token/agent` | Raw agent token (body) | Exchange raw token for access token |

## Sequence Diagrams

### Owner account setup

```
Owner                    Server                     Email
  │                        │                         │
  │── POST /auth/setup ────►│                         │
  │   X-Secret-Key          │                         │
  │   {email, password}     │                         │
  │                         │──── Email (OTP) ───────►│
  │                         │   6-digit code           │
  │◄─ 201 {pending_token} ─│                         │
  │                         │                         │
  │── POST /auth/verify ───►│                         │
  │   X-Secret-Key          │                         │
  │   {pending_token, otp}   │                         │
  │                         │                         │
  │◄─ 201 {owner info} ────│                         │
```

### Owner login

```
Owner                    Server
  │                        │
  │── POST /auth/login ───►│
  │   X-Secret-Key          │
  │   {email, password}     │
  │                         │
  │◄─ 200 {                │
  │     access_token,       │
  │     refresh_token,       │
  │     expires_in}         │
```

### Agent provisioning and first connection

```
Owner                    Server
  │                        │
  │── POST /auth/tokens ──►│  (Bearer <owner_token>)
  │   {name: "laptop"}     │
  │◄─ 201 {                │
  │     agent_id,           │
  │     token: "abc..."}    │  ← Owner sends "abc..." to agent via secure channel
  │                         │
```

```
Agent                    Server
  │                        │
  │── POST /auth/token/agent ──►│
  │   authorization: Bearer abc...  │
  │                              │
  │◄─ 200 {access_token: "eyJ..."} │
  │                              │
  │── POST /mcp ───────────────►│
  │   Authorization: Bearer eyJ...│
  │◄─ 200 {result} ─────────────│
```

### Agent reconnection (token refresh)

Agents use the same `POST /auth/token/agent` flow each time their access token expires. The raw token never changes — only the short-lived access token is refreshed.

```
Agent                    Server
  │                        │
  │── POST /auth/token/agent ──►│  (Bearer <raw_token>)
  │◄─ 200 {access_token} ───────│
  │                              │
  │── POST /mcp ───────────────►│  (new access token)
  │◄─ 200 {result} ─────────────│
```

## Middleware

`AuthMiddleware` (Starlette `BaseHTTPMiddleware`) validates the `Authorization: Bearer <JWT>` on every request to non-exempt paths.

**Exempt paths** (no auth required):
- `/health`
- `/docs`, `/redoc`, `/openapi.json`
- `/auth/setup`, `/auth/verify-setup`, `/auth/login`
- `/auth/token/refresh`, `/auth/token/agent`

**Scope enforcement:** The middleware validates token signature and expiry but does not enforce scope at the middleware level. Individual routes use `Depends(require_owner)` or `Depends(require_agent)` to enforce scope.

## Environment Variables

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Deployer secret — protects `/auth/setup`, `/auth/verify-setup`, and `/auth/login` |
| `ACCESS_SECRET_KEY` | JWT signing key for access and refresh tokens |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime (default: 60) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime (default: 30) |
| `EMAIL_OTP_EXPIRE_MINUTES` | OTP and pending token lifetime (default: 10) |

## Pending Setup JWT

The `POST /auth/setup` response contains a **pending JWT** that encodes:
- Owner email
- Bcrypt hash of the password
- Bcrypt hash of the 6-digit OTP

The OTP is **never stored server-side**. Only the bcrypt hash of the OTP is in the JWT. Verification succeeds only if the OTP matches the hash — and the JWT must not be expired (10 minutes).

## Database Tables

### `owner`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | Primary key |
| `email` | string | Unique, indexed |
| `hashed_password` | string | Bcrypt hash |
| `is_setup` | boolean | True after email verification |
| `created_at` | datetime | UTC |

### `agent_tokens`

| Column | Type | Notes |
|---|---|---|
| `id` | integer | Primary key |
| `token_hash` | string | SHA256 of raw token, unique |
| `agent_id` | string | e.g. `agent-a1b2c3...`, indexed |
| `name` | string | Human label |
| `created_at` | datetime | UTC |
| `revoked_at` | datetime | Null if active |
| `last_used_at` | datetime | Updated on each `/auth/token/agent` call |
