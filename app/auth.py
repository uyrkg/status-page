"""
Authentication module for the admin panel.

Supports multiple users with username + bcrypt-hashed password login.
Session tokens are signed with itsdangerous (stateless, no DB needed).
The initial admin user is created from ADMIN_PASSWORD env var on first startup.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException, status
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import bcrypt

from app.database import get_db_connection

logger = logging.getLogger(__name__)

_TOKEN_TTL_HOURS = 24


def _get_secret() -> str:
    """Return the secret used for signing tokens."""
    pw = os.getenv("ADMIN_PASSWORD", "")
    return pw if pw else "fallback-insecure-secret-do-not-use"


def _get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_get_secret(), salt="admin-session")


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password_hash(plaintext: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plaintext.encode("utf-8"), password_hash.encode("utf-8"))


def ensure_admin_user():
    """Create the initial admin user from ADMIN_PASSWORD env var if no admin exists."""
    admin_pw = os.getenv("ADMIN_PASSWORD", "")
    if not admin_pw:
        return

    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = 'admin'"
        ).fetchone()
        if not existing:
            pw_hash = hash_password(admin_pw)
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                ("admin", pw_hash),
            )
            conn.commit()
            logger.info("Created initial admin user")
    finally:
        conn.close()


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


def authenticate_user(username: str, password: str) -> bool:
    """Check username/password against the users table. Returns True on success."""
    if not username or not password:
        return False
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return False
        return verify_password_hash(password, row["password_hash"])
    finally:
        conn.close()


async def require_admin(request: Request):
    """FastAPI dependency: require a valid admin session cookie.

    Returns None on success, raises 401 on failure.
    """
    token = request.cookies.get("admin_session")
    if not token or not verify_session_token(token):
        accept = request.headers.get("accept", "")
        if "/json" in accept or request.url.path.startswith("/api/"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized — please log in at /admin/login",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )