from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from app.database import get_db_connection
from app.schemas import SMTPConfigUpdate, SMTPConfigResponse

router = APIRouter(prefix="/api/config", tags=["config"])


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
        return SMTPConfigResponse(
            smtp_host=row["smtp_host"] or "",
            smtp_port=row["smtp_port"] or 587,
            smtp_user=row["smtp_user"] or "",
            smtp_from=row["smtp_from"] or "",
            smtp_tls=bool(row["smtp_tls"]),
            password_set=bool(row["smtp_password"]),
        )
    finally:
        conn.close()


@router.put("/smtp", response_model=SMTPConfigResponse)
def update_smtp_config(data: SMTPConfigUpdate):
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO smtp_config (id, smtp_host, smtp_port, smtp_user, smtp_password, smtp_from, smtp_tls, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               smtp_host = ?, smtp_port = ?, smtp_user = ?, smtp_password = ?,
               smtp_from = ?, smtp_tls = ?, updated_at = ?""",
            (data.smtp_host, data.smtp_port, data.smtp_user, data.smtp_password, data.smtp_from,
             data.smtp_tls, datetime.now(timezone.utc).isoformat(),
             data.smtp_host, data.smtp_port, data.smtp_user, data.smtp_password, data.smtp_from,
             data.smtp_tls, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
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


def _load_smtp_config():
    """Load SMTP config from the DB as a dict."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM smtp_config WHERE id = 1").fetchone()
        if not row:
            return {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                "smtp_from": "statuspage@example.com",
                "smtp_tls": True,
            }
        return {
            "smtp_host": row["smtp_host"] or "smtp.example.com",
            "smtp_port": row["smtp_port"] or 587,
            "smtp_user": row["smtp_user"] or "",
            "smtp_password": row["smtp_password"] or "",
            "smtp_from": row["smtp_from"] or "statuspage@example.com",
            "smtp_tls": bool(row["smtp_tls"]),
        }
    finally:
        conn.close()
