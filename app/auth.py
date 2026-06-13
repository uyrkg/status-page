"""
Authentication module for the admin panel.

Uses itsdangerous for signed session tokens (stateless, no DB needed).
Admin password is read from the ADMIN_PASSWORD environment variable.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException, status
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

logger = logging.getLogger(__name__)

_TOKEN_TTL_HOURS = 24


def _get_secret() -> str:
    """Return the secret used for signing tokens."""
    pw = os.getenv("ADMIN_PASSWORD", "")
    return pw if pw else "fallback-insecure-secret-do-not-use"


def _get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_get_secret(), salt="admin-session")


def _get_admin_password() -> str:
    """Return the configured admin password."""
    return os.getenv("ADMIN_PASSWORD", "")


def create_session_token() -> str:
    """Create a signed session token valid for TOKEN_TTL_HOURS."""
    expires = datetime.now(timezone.utc) + timedelta(hours=_TOKEN_TTL_HOURS)
    return _get_serializer().dumps({"expires": expires.isoformat()})


def verify_session_token(token: str) -> bool:
    """Verify a session token. Returns True if valid."""
    if not token:
        return False
    try:
        _get_serializer().loads(token, max_age=_TOKEN_TTL_HOURS * 3600)
        return True
    except (BadSignature, SignatureExpired):
        return False


def verify_password(password: str) -> bool:
    """Check if the provided password matches ADMIN_PASSWORD."""
    expected = _get_admin_password()
    if not expected:
        logger.warning("ADMIN_PASSWORD is not set — admin login disabled")
        return False
    return password == expected


async def require_admin(request: Request):
    """FastAPI dependency: require a valid admin session cookie.

    Returns None on success, raises 401 on failure.
    """
    token = request.cookies.get("admin_session")
    if not token or not verify_session_token(token):
        # If it's an API call, return JSON 401
        accept = request.headers.get("accept", "")
        if "/json" in accept or request.url.path.startswith("/api/"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized — please log in at /admin/login",
            )
        # For page loads, redirect to login
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
