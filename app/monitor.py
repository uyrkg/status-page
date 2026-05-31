import asyncio
import logging
import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

import httpx
from ping3 import ping

from app.config import config
from app.database import get_db_connection
from app.models import CheckResult
from app.history import prune_old_history

logger = logging.getLogger(__name__)


# Track consecutive failure count per endpoint to determine severity
_failure_counts: dict[int, int] = {}


# --- Check implementations ---
def check_http(url: str, timeout: int, expected_status: int) -> CheckResult:
    """Perform an HTTP check."""
    try:
        start = time.time()
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
        elapsed_ms = int((time.time() - start) * 1000)
        success = expected_status and response.status_code == expected_status
        return CheckResult(
            success=success,
            response_time_ms=elapsed_ms,
            status_code=response.status_code,
            error_message=None if success else f"Unexpected status {response.status_code}",
        )
    except httpx.TimeoutException:
        return CheckResult(success=False, response_time_ms=int(timeout * 1000), error_message="Request timed out")
    except httpx.RequestError as e:
        return CheckResult(success=False, error_message=str(e))


def check_tcp(host: str, port: int, timeout: int) -> CheckResult:
    """Perform a TCP check."""
    try:
        start = time.time()
        with httpx.Client(timeout=timeout) as client:
            client.get(f"http://{host}:{port}", timeout=timeout)
        elapsed_ms = int((time.time() - start) * 1000)
        return CheckResult(success=True, response_time_ms=elapsed_ms)
    except httpx.TimeoutException:
        return CheckResult(success=False, error_message="TCP connection timed out")
    except httpx.RequestError as e:
        return CheckResult(success=False, error_message=str(e))
    except Exception as e:
        return CheckResult(success=False, error_message=str(e))


def check_ping(host: str, timeout: int) -> CheckResult:
    """Perform an ICMP ping check."""
    try:
        start = time.time()
        lat = ping(host, timeout=timeout)
        elapsed_ms = int((time.time() - start) * 1000)
        if lat is None or lat is False:
            return CheckResult(success=False, error_message="Host unreachable")
        return CheckResult(success=True, response_time_ms=int(lat * 1000))
    except Exception as e:
        return CheckResult(success=False, error_message=str(e))


# --- Main scheduler job ---
async def run_checks():
    """
    Run checks for all enabled endpoints not in a maintenance window.
    Creates incidents on failure, resolves on recovery.
    Prunes old history after each run.
    """
    from app.emailer import build_and_send_incident_email, send_recovery_email
    from app.routers.config import _load_smtp_config

    logger.info("Running endpoint checks")

    conn = get_db_connection()
    try:
        endpoints = conn.execute(
            "SELECT * FROM endpoints WHERE is_enabled = 1"
        ).fetchall()

        now = datetime.utcnow()

        for ep in endpoints:
            endpoint_id = ep["id"]

            # Check if in maintenance
            maint_row = conn.execute(
                """SELECT id FROM maintenance_windows
                   WHERE (endpoint_id = ? OR endpoint_id IS NULL)
                   AND is_active = 1
                   AND scheduled_start <= ? AND scheduled_end > ?""",
                (endpoint_id, now.isoformat(), now.isoformat())
            ).fetchone()

            if maint_row:
                # Don't check during maintenance; record as skipped
                logger.debug(f"Endpoint {endpoint_id} is in maintenance window, skipping")
                continue

            # Perform the appropriate check
            if ep["check_type"] == "http":
                result = check_http(ep["url"] or "", ep["timeout"], ep["expected_status"])
            elif ep["check_type"] == "tcp":
                result = check_tcp(ep["host"] or "", ep["port"] or 80, ep["timeout"])
            elif ep["check_type"] == "ping":
                result = check_ping(ep["host"] or "", ep["timeout"])
            else:
                result = CheckResult(success=False, error_message=f"Unknown check type: {ep['check_type']}")

            # Record in check_history
            conn.execute(
                """INSERT INTO check_history
                   (endpoint_id, check_type, success, response_time_ms, status_code, error_message, checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (endpoint_id, ep["check_type"], result.success, result.response_time_ms,
                 result.status_code, result.error_message, now.isoformat())
            )
            conn.commit()

            # Handle incident logic
            if not result.success:
                failures = _failure_counts.get(endpoint_id, 0) + 1
                _failure_counts[endpoint_id] = failures

                # Determine severity based on consecutive failures
                if failures >= 5:
                    severity = "critical"
                elif failures >= 3:
                    severity = "major"
                elif failures >= 2:
                    severity = "minor"
                else:
                    severity = "cosmetic"

                # Check if there is already an open incident
                open_incident = conn.execute(
                    "SELECT id FROM incidents WHERE endpoint_id = ? AND resolved_at IS NULL",
                    (endpoint_id,)
                ).fetchone()

                if not open_incident:
                    # Create new incident
                    title = f"Health check failed for {ep['name']}"
                    cursor = conn.execute(
                        """INSERT INTO incidents
                           (endpoint_id, title, description, status, severity, started_at)
                           VALUES (?, ?, ?, 'investigating', ?, ?)""",
                        (endpoint_id, title, result.error_message, severity, now.isoformat())
                    )
                    incident_id = cursor.lastrowid
                    conn.commit()

                    # Queue email alert (suppress dupes within cooldown)
                    await _queue_alert(conn, endpoint_id, incident_id, "down", ep["name"])

                logger.warning(
                    f"Endpoint {endpoint_id} ({ep['name']}) check failed: {result.error_message}"
                )
            else:
                _failure_counts[endpoint_id] = 0

                # Auto-resolve open incident if any
                open_incident = conn.execute(
                    "SELECT id, title, started_at FROM incidents WHERE endpoint_id = ? AND resolved_at IS NULL",
                    (endpoint_id,)
                ).fetchone()
                if open_incident:
                    conn.execute(
                        "UPDATE incidents SET resolved_at = ? WHERE id = ?",
                        (now.isoformat(), open_incident["id"])
                    )
                    conn.commit()
                    logger.info(f"Endpoint {endpoint_id} recovered; incident {open_incident['id']} auto-resolved")
                    await _queue_recovery_alert(conn, open_incident["id"], ep["name"])

        # Prune old history after each run
        prune_old_history()

    finally:
        conn.close()


async def _queue_alert(conn, endpoint_id: int, incident_id: int, event: str, endpoint_name: str):
    """Send an email alert with 5-minute cooldown suppression."""
    cfg = _load_smtp_config()
    if not cfg["smtp_host"]:
        return  # SMTP not configured; skip

    # Check cooldown - no duplicate alerts within ALERT_COOLDOWN_MINUTES
    cooldown = datetime.utcnow() - timedelta(minutes=config.alert_cooldown_minutes)
    recent = conn.execute(
        """SELECT id FROM email_alerts
           WHERE endpoint_id = ? AND sent_at >= ? AND success = 1""",
        (endpoint_id, cooldown.isoformat())
    ).fetchone()
    if recent:
        logger.debug(f"Alert suppressed for endpoint {endpoint_id} (cooldown active)")
        return

    # Get incident details
    incident = conn.execute(
        "SELECT * FROM incidents WHERE id = ?", (incident_id,)
    ).fetchone()

    recipients = _get_alert_recipients(conn)
    for recipient in recipients:
        success = await build_and_send_incident_email(
            endpoint_name=endpoint_name,
            incident_id=incident_id,
            incident_title=incident["title"],
            severity=incident["severity"],
            description=incident["description"],
            status=incident["status"],
            started_at=incident["started_at"],
            recipient=recipient,
        )
        conn.execute(
            """INSERT INTO email_alerts (endpoint_id, incident_id, recipient, subject, body, success)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (endpoint_id, incident_id, recipient, f"Alert for {endpoint_name}", "", success)
        )
    conn.commit()


async def _queue_recovery_alert(conn, incident_id: int, endpoint_name: str):
    """Send a recovery notification."""
    cfg = _load_smtp_config()
    if not cfg["smtp_host"]:
        return

    incident = conn.execute(
        "SELECT * FROM incidents WHERE id = ?", (incident_id,)
    ).fetchone()

    recipients = _get_alert_recipients(conn)
    for recipient in recipients:
        success = await send_recovery_email(
            endpoint_name=endpoint_name,
            incident_id=incident_id,
            incident_title=incident["title"],
            started_at=incident["started_at"],
            resolved_at=incident["resolved_at"] or datetime.utcnow(),
            recipient=recipient,
        )
        conn.execute(
            """INSERT INTO email_alerts (endpoint_id, incident_id, recipient, subject, body, success)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (incident["endpoint_id"], incident_id, recipient,
             f"Recovery: {endpoint_name}", "", success)
        )
    conn.commit()


def _get_alert_recipients(conn) -> list[str]:
    """
    Recipients list. Stored recipients could be added via a future 'alert_recipients' table.
    For now, use a simple config approach: SMTP_USER is the recipient if set,
    otherwise the smtp_from address.
    """
    cfg = _load_smtp_config()
    user = cfg.get("smtp_user", "")
    if user and "@" in user:
        return [user]
    # Fall back to configured from address
    from_addr = cfg.get("smtp_from", "")
    if from_addr:
        return [from_addr]
    return []


def start_scheduler(app):
    """Register APScheduler jobs on app startup."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()

    def _sync_run_checks():
        asyncio.run(run_checks())

    scheduler.add_job(
        _sync_run_checks,
        "interval",
        seconds=config.check_interval,
        id="run_checks",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info("Scheduler started")

    @app.on_event("shutdown")
    async def shutdown():
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
