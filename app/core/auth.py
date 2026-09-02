"""
API-key authentication gate.

Design goal: the rate limiter already special-cases requests carrying a
recognised `X-API-Key` (see `_rate_limit_key` in app/main.py), which made it
look — to anyone reading the code — like the API was access-controlled. It
wasn't: an unrecognised or missing key just fell back to IP-based rate
limiting rather than being rejected. This module closes that gap by turning
"has a valid key" into an actual authorization check.

Behaviour is controlled by two env vars:

- API_KEYS: comma-separated list of accepted keys.
- REQUIRE_AUTH: "true" (default) enforces the check; set to "false" to run
  the API open (e.g. local development or a low-stakes demo). This is a
  conscious, documented toggle rather than a silent gap — the startup log
  makes the current mode explicit either way.
"""

from __future__ import annotations

import logging
import os
import time
import hmac
import hashlib
from typing import Optional

from fastapi import Header, HTTPException, Request, status

from pathlib import Path

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

logger = logging.getLogger("email_verifier.auth")


def _reload_env_if_needed():
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=True)
    except ImportError:
        pass


def _configured_keys() -> set[str]:
    raw = os.getenv("API_KEYS", "")
    if not raw:
        _reload_env_if_needed()
        raw = os.getenv("API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def is_valid_api_key(api_key: Optional[str]) -> bool:
    """Return whether an API key is allowed in the current deployment mode."""
    return not _require_auth() or bool(api_key and api_key in _configured_keys())


def _token_secret() -> bytes:
    secret = os.getenv("SESSION_TOKEN_SECRET", "")
    if not secret:
        _reload_env_if_needed()
        secret = os.getenv("SESSION_TOKEN_SECRET", "")
    if not secret:
        raise RuntimeError("SESSION_TOKEN_SECRET must be configured when authentication is enabled.")
    return secret.encode()


def issue_browser_token(api_key: str, scope: str, ttl_seconds: int) -> str:
    """Issue a signed opaque token without placing the API key in a cookie/URL."""
    expires = int(time.time()) + ttl_seconds
    fingerprint = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    payload = f"{scope}.{expires}.{fingerprint}"
    signature = hmac.new(_token_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def validate_browser_token(token: Optional[str], scope: str) -> Optional[str]:
    if not token:
        return None
    try:
        token_scope, expiry, fingerprint, signature = token.split(".", 3)
        payload = f"{token_scope}.{expiry}.{fingerprint}"
        expected = hmac.new(_token_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if token_scope != scope or int(expiry) < time.time() or not hmac.compare_digest(signature, expected):
            return None
        return next((key for key in _configured_keys() if hashlib.sha256(key.encode()).hexdigest()[:16] == fingerprint), None)
    except (ValueError, RuntimeError):
        return None


def _require_auth() -> bool:
    return os.getenv("REQUIRE_AUTH", "true").strip().lower() not in ("false", "0", "no")


async def require_api_key(request: Request, x_api_key: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency: raises 401 unless a valid API key is supplied.

    Returns the validated key so endpoints can use it as an identity/quota
    key without a second lookup.
    """
    if not _require_auth():
        # Explicitly disabled — return a sentinel identity for logging/ownership.
        return x_api_key or "anonymous"

    keys = _configured_keys()
    if not keys:
        # Fail closed: auth is required but nothing is configured. This is a
        # deployment misconfiguration, not a "let everyone in" situation.
        logger.error(
            "REQUIRE_AUTH is enabled but API_KEYS is empty — rejecting all requests. "
            "Set API_KEYS or REQUIRE_AUTH=false."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is not yet configured for authenticated access.",
        )

    authenticated_key = x_api_key if x_api_key in keys else validate_browser_token(request.cookies.get("ev_session"), "session")
    if not authenticated_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Supply a valid X-API-Key header.",
        )

    return authenticated_key


def startup_log_message() -> str:
    if not _require_auth():
        return "[startup] REQUIRE_AUTH=false — API is running WITHOUT authentication."
    n = len(_configured_keys())
    return f"[startup] REQUIRE_AUTH=true — {n} API key(s) configured."
