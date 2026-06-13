import os
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_db_connection
from app.schemas import SMTPConfigUpdate, SMTPConfigResponse
from app.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"], dependencies=[Depends(require_admin)])

# Path to the .env file (relative to project root)
_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")


def _read_env() -> dict[str, str]:
    """Read the .env file into a dict."""
    env = {}
    if not os.path.exists(_ENV_PATH):
        return env
    with open(_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip()
    return env


def _write_env(updates: dict[str, str]):
    """Update specific keys in .env, preserving other content."""
    lines = []
    updated_keys = set(updates.keys())
    found = set()

    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH) as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    lines.append(line)
                    continue
                key, _, _ = stripped.partition("=")
                key = key.strip()
                if key in updates:
                    lines.append(f"{key}={updates[key]}\n")
                    found.add(key)
                else:
                    lines.append(line)

    # Add any keys that weren't found
    for key in updated_keys:
        if key not in found:
            lines.append(f"{key}={updates[key]}\n")

    with open(_ENV_PATH, "w") as f:
        f.writelines(lines)


@router.get("/smtp", response_model=SMTPConfigResponse)
def get_smtp_config():
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM smtp_config WHERE id = 1").fetchone()
        if not row:
            return SMTPConfigResponse(
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_user="",
                smtp_from="statuspage@example.com",
                smtp_tls=True,
                password_set=False,
            )
        # Check if SMTP_PASSWORD is set in .env
        env = _read_env()
        password_set = bool(env.get("SMTP_PASSWORD", ""))
        return SMTPConfigResponse(
            smtp_host=row["smtp_host"] or "",
            smtp_port=row["smtp_port"] or 587,
            smtp_user=row["smtp_user"] or "",
            smtp_from=row["smtp_from"] or "",
            smtp_tls=bool(row["smtp_tls"]),
            password_set=password_set,
        )
    finally:
        conn.close()


@router.put("/smtp", response_model=SMTPConfigResponse)
def update_smtp_config(data: SMTPConfigUpdate):
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO smtp_config (id, smtp_host, smtp_port, smtp_user, smtp_from, smtp_tls, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               smtp_host = ?, smtp_port = ?, smtp_user = ?,
               smtp_from = ?, smtp_tls = ?, updated_at = ?""",
            (data.smtp_host, data.smtp_port, data.smtp_user, data.smtp_from,
             data.smtp_tls, datetime.now(timezone.utc).isoformat(),
             data.smtp_host, data.smtp_port, data.smtp_user, data.smtp_from,
             data.smtp_tls, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()

        # Write SMTP password to .env instead of DB
        if data.smtp_password:
            _write_env({"SMTP_PASSWORD": data.smtp_password})
            logger.info("SMTP password written to .env file")

        return SMTPConfigResponse(
            smtp_host=data.smtp_host,
            smtp_port=data.smtp_port,
            smtp_user=data.smtp_user,
            smtp_from=data.smtp_from,
            smtp_tls=data.smtp_tls,
            password_set=bool(data.smtp_password),
        )
    finally:
        conn.close()


def _load_smtp_config() -> dict:
    """Load SMTP config from the DB as a dict, with password from .env."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM smtp_config WHERE id = 1").fetchone()
        env = _read_env()
        smtp_password = env.get("SMTP_PASSWORD", "")

        if not row:
            return {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": smtp_password,
                "smtp_from": "statuspage@example.com",
                "smtp_tls": True,
            }
        return {
            "smtp_host": row["smtp_host"] or "smtp.example.com",
            "smtp_port": row["smtp_port"] or 587,
            "smtp_user": row["smtp_user"] or "",
            "smtp_password": smtp_password,
            "smtp_from": row["smtp_from"] or "statuspage@example.com",
            "smtp_tls": bool(row["smtp_tls"]),
        }
    finally:
        conn.close()
