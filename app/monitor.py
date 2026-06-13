import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
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

# Module-level scheduler reference
_scheduler = None


def _parse_dt(value):
    """Parse a datetime from DB string or datetime object."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value) if value else datetime.now(timezone.utc)


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


# --- Per-endpoint check job ---
async def _run_endpoint_check(endpoint_id: int):
    """Run a single check for one endpoint by ID."""
    from app.emailer import build_and_send_incident_email, send_recovery_email

    conn = get_db_connection()
    try:
        ep = conn.execute(
            "SELECT * FROM endpoints WHERE id = ? AND is_enabled = 1", (endpoint_id,)
        ).fetchone()
        if not ep:
            return

        now = datetime.now(timezone.utc)

        # Check if in maintenance
        maint_row = conn.execute(
            """SELECT id FROM maintenance_windows
               WHERE (endpoint_id = ? OR endpoint_id IS NULL)
               AND is_active = 1
               AND scheduled_start <= ? AND scheduled_end > ?""",
            (endpoint_id, now.isoformat(), now.isoformat())
        ).fetchone()
        if maint_row:
            logger.debug(f"Endpoint {endpoint_id} is in maintenance window, skipping")
            return

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

            if failures >= 5:
                severity = "critical"
            elif failures >= 3:
                severity = "major"
            elif failures >= 2:
                severity = "minor"
            else:
                severity = "cosmetic"

            open_incident = conn.execute(
                "SELECT id FROM incidents WHERE endpoint_id = ? AND resolved_at IS NULL",
                (endpoint_id,)
            ).fetchone()

            if not open_incident:
                title = f"Health check failed for {ep['name']}"
                cursor = conn.execute(
                    """INSERT INTO incidents
                       (endpoint_id, title, description, status, severity, started_at)
                       VALUES (?, ?, ?, 'investigating', ?, ?)""",
                    (endpoint_id, title, result.error_message, severity, now.isoformat())
                )
                incident_id = cursor.lastrowid
                conn.commit()
                await _queue_alert(conn, endpoint_id, incident_id, "down", ep["name"])
            else:
                # Escalate existing open incident
                conn.execute(
                    "UPDATE incidents SET severity = ?, description = ? WHERE id = ?",
                    (severity, result.error_message, open_incident["id"])
                )
                conn.commit()

            logger.warning(
                f"Endpoint {endpoint_id} ({ep['name']}) check failed: {result.error_message}"
            )
        else:
            _failure_counts[endpoint_id] = 0

            open_incident = conn.execute(
                "SELECT id, title, started_at FROM incidents WHERE endpoint_id = ? AND resolved_at IS NULL",
                (endpoint_id,)
            ).fetchone()
            if open_incident:
                conn.execute(
                    "UPDATE incidents SET status = 'resolved', resolved_at = ? WHERE id = ?",
                    (now.isoformat(), open_incident["id"])
                )
                conn.commit()
                logger.info(f"Endpoint {endpoint_id} recovered; incident {open_incident['id']} auto-resolved")
                await _queue_recovery_alert(conn, open_incident["id"], ep["name"])

        prune_old_history()

    finally:
        conn.close()


def _sync_run_endpoint_check(endpoint_id: int):
    """Sync wrapper for APScheduler."""
    asyncio.run(_run_endpoint_check(endpoint_id))


# --- Alert helpers ---
async def _queue_alert(conn, endpoint_id: int, incident_id: int, event: str, endpoint_name: str):
    """Send an email alert with 5-minute cooldown suppression."""
    from app.routers.config import _load_smtp_config
    cfg = _load_smtp_config()
    if not cfg["smtp_host"]:
        return

    cooldown = datetime.now(timezone.utc) - timedelta(minutes=config.alert_cooldown_minutes)
    recent = conn.execute(
        """SELECT id FROM email_alerts
           WHERE endpoint_id = ? AND sent_at >= ? AND success = 1""",
        (endpoint_id, cooldown.isoformat())
    ).fetchone()
    if recent:
        logger.debug(f"Alert suppressed for endpoint {endpoint_id} (cooldown active)")
        return

    incident = conn.execute(
        "SELECT * FROM incidents WHERE id = ?", (incident_id,)
    ).fetchone()

    recipients = _get_alert_recipients(conn)
    for recipient in recipients:
        from app.emailer import build_and_send_incident_email
        success = await build_and_send_incident_email(
            endpoint_name=endpoint_name,
            incident_id=incident_id,
            incident_title=incident["title"],
            severity=incident["severity"],
            description=incident["description"],
            status=incident["status"],
            started_at=_parse_dt(incident["started_at"]),
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
    from app.routers.config import _load_smtp_config
    cfg = _load_smtp_config()
    if not cfg["smtp_host"]:
        return

    incident = conn.execute(
        "SELECT * FROM incidents WHERE id = ?", (incident_id,)
    ).fetchone()

    recipients = _get_alert_recipients(conn)
    for recipient in recipients:
        from app.emailer import send_recovery_email
        success = await send_recovery_email(
            endpoint_name=endpoint_name,
            incident_id=incident_id,
            incident_title=incident["title"],
            started_at=_parse_dt(incident["started_at"]),
            resolved_at=_parse_dt(incident["resolved_at"]) if incident["resolved_at"] else datetime.now(timezone.utc),
            recipient=recipient,
        )
        conn.execute(
            """INSERT INTO email_alerts (endpoint_id, incident_id, recipient, subject, body, success)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (incident["endpoint_id"], incident_id, recipient, f"Recovery: {endpoint_name}", "", success)
        )
    conn.commit()


def _get_alert_recipients(conn) -> list[str]:
    from app.routers.config import _load_smtp_config
    cfg = _load_smtp_config()
    user = cfg.get("smtp_user", "")
    if user and "@" in user:
        return [user]
    from_addr = cfg.get("smtp_from", "")
    if from_addr:
        return [from_addr]
    return []


# --- Scheduler management ---
def _load_endpoint_jobs(scheduler):
    """Load or reload all endpoint jobs into the scheduler."""
    conn = get_db_connection()
    try:
        endpoints = conn.execute("SELECT id, check_interval FROM endpoints WHERE is_enabled = 1").fetchall()
        for ep in endpoints:
            interval = ep["check_interval"] or config.check_interval
            job_id = f"endpoint_{ep['id']}"
            scheduler.add_job(
                _sync_run_endpoint_check,
                "interval",
                seconds=interval,
                id=job_id,
                replace_existing=True,
                max_instances=1,
                kwargs={"endpoint_id": ep["id"]},
            )
            logger.debug(f"Scheduled endpoint {ep['id']} every {interval}s")
    finally:
        conn.close()


def reschedule_endpoint(endpoint_id: int):
    """Add or update the scheduler job for a single endpoint (call after create/update)."""
    if _scheduler is None:
        return
    conn = get_db_connection()
    try:
        ep = conn.execute(
            "SELECT id, check_interval, is_enabled FROM endpoints WHERE id = ?", (endpoint_id,)
        ).fetchone()
        if not ep:
            return
        job_id = f"endpoint_{endpoint_id}"
        if not ep["is_enabled"]:
            _scheduler.remove_job(job_id)
            return
        interval = ep["check_interval"] or config.check_interval
        _scheduler.add_job(
            _sync_run_endpoint_check,
            "interval",
            seconds=interval,
            id=job_id,
            replace_existing=True,
            max_instances=1,
            kwargs={"endpoint_id": endpoint_id},
        )
        logger.info(f"Rescheduled endpoint {endpoint_id} to run every {interval}s")
    finally:
        conn.close()


def remove_endpoint_job(endpoint_id: int):
    """Remove the scheduler job for a deleted endpoint."""
    if _scheduler is None:
        return
    job_id = f"endpoint_{endpoint_id}"
    try:
        _scheduler.remove_job(job_id)
        logger.info(f"Removed scheduler job for endpoint {endpoint_id}")
    except Exception:
        pass


def start_scheduler(app):
    """Register APScheduler jobs on app startup."""
    global _scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    _scheduler = AsyncIOScheduler()
    _load_endpoint_jobs(_scheduler)
    _scheduler.start()
    logger.info("Scheduler started")

    @app.on_event("shutdown")
    async def shutdown():
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
