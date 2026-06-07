from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query
from app.database import get_db_connection
from app.schemas import StatusResponse, StatsResponse, UptimeStat

router = APIRouter(tags=["status"])


def _compute_aggregate_status() -> tuple[str, int, int]:
    """Return (status_label, endpoints_affected, active_incidents)."""
    conn = get_db_connection()
    try:
        # Count active incidents by severity
        incidents = conn.execute(
            "SELECT severity FROM incidents WHERE resolved_at IS NULL"
        ).fetchall()

        active_count = len(incidents)
        severities = [r["severity"] for r in incidents]

        if "critical" in severities:
            status = "major_outage"
        elif "major" in severities:
            status = "partial_outage"
        elif "minor" in severities:
            status = "degraded"
        else:
            status = "all_operational"

        # Check for active maintenance affecting endpoints
        now = datetime.now(timezone.utc)
        maint_rows = conn.execute(
            """SELECT COUNT(DISTINCT endpoint_id) as cnt FROM maintenance_windows
               WHERE is_active = 1
               AND scheduled_start <= ? AND scheduled_end > ?
               AND endpoint_id IS NOT NULL""",
            (now.isoformat(), now.isoformat())
        ).fetchone()
        maint_count = maint_rows["cnt"] if maint_rows else 0

        if status == "all_operational" and maint_count > 0:
            status = "maintenance"

        # Endpoints affected = those with open incidents or in maintenance
        affected = conn.execute(
            """SELECT COUNT(DISTINCT endpoint_id) as cnt FROM (
                SELECT endpoint_id FROM incidents WHERE resolved_at IS NULL
                UNION
                SELECT endpoint_id FROM maintenance_windows
                WHERE is_active = 1 AND scheduled_start <= ? AND scheduled_end > ?
                AND endpoint_id IS NOT NULL
            )""",
            (now.isoformat(), now.isoformat())
        ).fetchone()
        endpoints_affected = affected["cnt"] if affected else 0

        return status, endpoints_affected, active_count
    finally:
        conn.close()


@router.get("/api/status", response_model=StatusResponse)
def get_status():
    status, endpoints_affected, active_incidents = _compute_aggregate_status()
    return StatusResponse(
        status=status,
        endpoints_affected=endpoints_affected,
        active_incidents=active_incidents,
    )


@router.get("/api/stats", response_model=StatsResponse)
def get_stats():
    conn = get_db_connection()
    try:
        endpoints = conn.execute("SELECT id, name FROM endpoints").fetchall()
        result = []
        for ep in endpoints:
            uptime_7d = _compute_uptime(conn, ep["id"], 7)
            uptime_30d = _compute_uptime(conn, ep["id"], 30)
            result.append(
                UptimeStat(
                    endpoint_id=ep["id"],
                    endpoint_name=ep["name"],
                    uptime_7d=uptime_7d,
                    uptime_30d=uptime_30d,
                )
            )
        return StatsResponse(endpoints=result)
    finally:
        conn.close()


def _compute_uptime(conn, endpoint_id: int, days: int) -> float:
    """Compute uptime % for an endpoint over the given number of days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    total_row = conn.execute(
        "SELECT COUNT(*) as cnt FROM check_history WHERE endpoint_id = ? AND checked_at >= ?",
        (endpoint_id, since.isoformat())
    ).fetchone()
    total = total_row["cnt"] if total_row else 0
    if total == 0:
        return 100.0
    success_row = conn.execute(
        "SELECT COUNT(*) as cnt FROM check_history WHERE endpoint_id = ? AND checked_at >= ? AND success = 1",
        (endpoint_id, since.isoformat())
    ).fetchone()
    success = success_row["cnt"] if success_row else 0
    return round(success / total * 100, 2)
