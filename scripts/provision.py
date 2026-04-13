#!/usr/bin/env python3
"""
scripts/provision.py

One-command agent provisioning for Logios Brain.

Usage:
    python scripts/provision.py --email you@example.com --password your-password

Environment variables (fallback):
    LOGIOS_URL      Default: http://localhost:8000
    SECRET_KEY      Required: the X-Secret-Key for owner setup
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request
import urllib.parse
import urllib.error


def _request(method: str, url: str, *, data: dict | None = None, headers: dict | None = None) -> dict:
    headers = dict(headers or {})
    headers.setdefault("Content-Type", "application/json")

    body = None
    if data is not None:
        import json
        body = json.dumps(data).encode()

    req = urllib.request.Request(url, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        import json
        body = e.read()
        try:
            detail = json.loads(body).get("detail", str(body))
        except Exception:
            detail = str(body)
        raise SystemExit(f"HTTP {e.code}: {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision an agent token for Logios Brain.")
    parser.add_argument("--email", required=True, help="Owner email address")
    parser.add_argument("--password", required=True, help="Owner password (min 8 chars)")
    parser.add_argument("--agent-name", default="default-agent", help="Name for the agent token")
    parser.add_argument(
        "--url",
        default=os.getenv("LOGIOS_URL", "http://localhost:8000"),
        help="Logios Brain URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--secret-key",
        default=os.getenv("SECRET_KEY"),
        help="X-Secret-Key for owner setup (or set SECRET_KEY env var)",
    )
    args = parser.parse_args()

    if not args.secret_key:
        raise SystemExit("Error: --secret-key or SECRET_KEY env var is required")

    base = args.url.rstrip("/")
    headers = {"X-Secret-Key": args.secret_key}

    # Step 1: Initiate owner setup
    print(f"[1/5] Creating owner account for {args.email}...")
    result = _request("POST", f"{base}/auth/setup", data={"email": args.email, "password": args.password}, headers=headers)
    pending_token = result["pending_token"]
    otp = result.get("otp") or result.get("code")
    if not otp:
        raise SystemExit("Error: OTP not returned in setup response. Is EMAILS_ENABLED=true?")
    print(f"[1/5] OTP received: {otp}")

    # Step 2: Complete owner setup
    print(f"[2/5] Completing owner setup with OTP...")
    data_encoded = urllib.parse.urlencode({"pending_token": pending_token, "otp": otp}).encode()
    req = urllib.request.Request(
        f"{base}/auth/verify-setup",
        method="POST",
        data=data_encoded,
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        import json
        owner = json.loads(resp.read())
    print(f"[2/5] Owner created: {owner.get('email')}")

    # Step 3: Login to get access token
    print(f"[3/5] Logging in to get access token...")
    login = _request("POST", f"{base}/auth/login", data={"email": args.email, "password": args.password})
    access_token = login["access_token"]
    print(f"[3/5] Logged in.")

    # Step 4: Create agent token
    print(f"[4/5] Creating agent token '{args.agent_name}'...")
    agent_resp = _request(
        "POST",
        f"{base}/auth/tokens",
        data={"name": args.agent_name},
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
    )
    agent_token = agent_resp["token"]
    agent_id = agent_resp["agent_id"]

    # Step 5: Done
    print()
    print("=" * 60)
    print("Agent token created successfully.")
    print()
    print(f"  Agent ID: {agent_id}")
    print(f"  Token:    {agent_token}")
    print()
    print("  Add to your agent config:")
    print(f"    LOGIOS_URL={base}")
    print(f"    AGENT_TOKEN={agent_token}")
    print("=" * 60)


if __name__ == "__main__":
    main()
