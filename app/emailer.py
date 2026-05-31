import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional

from app.config import config
from app.routers.config import _load_smtp_config

logger = logging.getLogger(__name__)


async def send_email(
    recipient: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
) -> bool:
    """
    Send an email via SMTP. Returns True on success, False on failure.
    All operations are non-blocking using aiosmtplib where available,
    falling back to smtplib in a thread executor.
    """
    cfg = _load_smtp_config()
    if not cfg["smtp_host"]:
        logger.warning("SMTP host not configured; skipping email")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["smtp_from"]
    msg["To"] = recipient

    text_part = MIMEText(body, "plain")
    msg.attach(text_part)

    if html_body:
        html_part = MIMEText(html_body, "html")
        msg.attach(html_part)

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    def _send_sync():
        try:
            if cfg["smtp_tls"]:
                server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"])
                server.starttls()
            else:
                server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"])
            if cfg["smtp_user"] and cfg["smtp_password"]:
                server.login(cfg["smtp_user"], cfg["smtp_password"])
            server.sendmail(cfg["smtp_from"], [recipient], msg.as_string())
            server.quit()
            return True
        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return False

    try:
        success = await loop.run_in_executor(None, _send_sync)
        return success
    except Exception as e:
        logger.error(f"SMTP send failed: {e}")
        return False


async def build_and_send_incident_email(
    endpoint_name: str,
    incident_id: int,
    incident_title: str,
    severity: str,
    description: Optional[str],
    status: str,
    started_at: datetime,
    recipient: str,
) -> bool:
    """Compose and send an incident alert email."""
    app_url = config.app_url.rstrip("/")
    status_url = f"{app_url}"

    status_map = {
        "investigating": "Investigating",
        "identified": "Identified",
        "monitoring": "Monitoring",
        "resolved": "Resolved",
    }
    status_label = status_map.get(status, status)

    body = f"""Status Page Incident Update

Service: {endpoint_name}
Incident: {incident_title}
Severity: {severity.upper()}
Status: {status_label}
Started: {started_at.isoformat()}

Description:
{description or "No description provided."}

View Status Page: {status_url}
"""
    html = f"""
<html><body>
<h2>Status Page Incident Update</h2>
<table>
<tr><td><strong>Service</strong></td><td>{endpoint_name}</td></tr>
<tr><td><strong>Incident</strong></td><td>{incident_title}</td></tr>
<tr><td><strong>Severity</strong></td><td>{severity.upper()}</td></tr>
<tr><td><strong>Status</strong></td><td>{status_label}</td></tr>
<tr><td><strong>Started</strong></td><td>{started_at.isoformat()}</td></tr>
</table>
<h3>Description</h3>
<p>{description or "No description provided."}</p>
<p><a href="{status_url}">View Status Page</a></p>
</body></html>
"""
    subject = f"[{severity.upper()}] {status_label}: {incident_title} ({endpoint_name})"
    return await send_email(recipient, subject, body, html)


async def send_recovery_email(
    endpoint_name: str,
    incident_id: int,
    incident_title: str,
    started_at: datetime,
    resolved_at: datetime,
    recipient: str,
) -> bool:
    """Send a recovery notification email."""
    app_url = config.app_url.rstrip("/")

    body = f"""Status Page Recovery Notification

Service: {endpoint_name}
Incident: {incident_title}
Status: RESOLVED
Started: {started_at.isoformat()}
Resolved: {resolved_at.isoformat()}

Your service has recovered.

View Status Page: {app_url}
"""
    html = f"""
<html><body>
<h2>✅ Service Recovered</h2>
<table>
<tr><td><strong>Service</strong></td><td>{endpoint_name}</td></tr>
<tr><td><strong>Incident</strong></td><td>{incident_title}</td></tr>
<tr><td><strong>Status</strong></td><td><span style="color:green">RESOLVED</span></td></tr>
<tr><td><strong>Started</strong></td><td>{started_at.isoformat()}</td></tr>
<tr><td><strong>Resolved</strong></td><td>{resolved_at.isoformat()}</td></tr>
</table>
<p><a href="{app_url}">View Status Page</a></p>
</body></html>
"""
    subject = f"[RECOVERED] {incident_title} ({endpoint_name})"
    return await send_email(recipient, subject, body, html)
