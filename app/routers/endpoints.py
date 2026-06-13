from fastapi import APIRouter, HTTPException, Query, Depends
from datetime import datetime, timedelta, timezone
from app.database import get_db_connection
from app.schemas import (
    EndpointCreate, EndpointUpdate, EndpointResponse,
)
from app.models import CheckResult
from app.auth import require_admin

router = APIRouter(prefix="/api/endpoints", tags=["endpoints"], dependencies=[Depends(require_admin)])


def _row_to_endpoint_response(row) -> EndpointResponse:
    return EndpointResponse(
        id=row["id"],
        name=row["name"],
        url=row["url"],
        host=row["host"],
        port=row["port"],
        check_type=row["check_type"],
        check_interval=row["check_interval"],
        timeout=row["timeout"],
        expected_status=row["expected_status"],
        is_enabled=bool(row["is_enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        current_status=_get_current_status(row["id"]),
    )


def _get_current_status(endpoint_id: int) -> str:
    """Get current status for an endpoint based on latest check and open incidents."""
    conn = get_db_connection()
    try:
        # Check if in maintenance
        now = datetime.now(timezone.utc)
        row = conn.execute(
            """SELECT id FROM maintenance_windows
               WHERE (endpoint_id = ? OR endpoint_id IS NULL)
               AND is_active = 1
               AND scheduled_start <= ? AND scheduled_end > ?""", 
            (endpoint_id, now.isoformat(), now.isoformat())
        ).fetchone()
        if row:
            return "maintenance"

        # Check latest incident
        incident_row = conn.execute(
            """SELECT severity FROM incidents
               WHERE endpoint_id = ? AND resolved_at IS NULL""",
            (endpoint_id,)
        ).fetchone()
        if incident_row:
            return "down"

        # Check latest check result
        check_row = conn.execute(
            """SELECT success FROM check_history
               WHERE endpoint_id = ?
               ORDER BY checked_at DESC LIMIT 1""",
            (endpoint_id,)
        ).fetchone()
        if check_row:
            return "up" if check_row["success"] else "down"
        return "unknown"
    finally:
        conn.close()


@router.get("", response_model=list[EndpointResponse])
def list_endpoints():
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM endpoints ORDER BY name").fetchall()
        return [_row_to_endpoint_response(r) for r in rows]
    finally:
        conn.close()


@router.post("", response_model=EndpointResponse, status_code=201)
def create_endpoint(data: EndpointCreate):
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO endpoints
               (name, url, host, port, check_type, check_interval, timeout, expected_status, is_enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.name, data.url, data.host, data.port, data.check_type,
             data.check_interval, data.timeout, data.expected_status, data.is_enabled)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM endpoints WHERE id = ?", (cursor.lastrowid,)).fetchone()
        resp = _row_to_endpoint_response(row)
        # Schedule the new endpoint
        from app.monitor import reschedule_endpoint
        reschedule_endpoint(row["id"])
        return resp
    finally:
        conn.close()


@router.get("/{endpoint_id}", response_model=EndpointResponse)
def get_endpoint(endpoint_id: int):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM endpoints WHERE id = ?", (endpoint_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Endpoint not found")
        return _row_to_endpoint_response(row)
    finally:
        conn.close()


@router.put("/{endpoint_id}", response_model=EndpointResponse)
def update_endpoint(endpoint_id: int, data: EndpointUpdate):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM endpoints WHERE id = ?", (endpoint_id,)).fetchone()
        if not row:
            raise HTTPException(code=404, detail="Endpoint not found")

        updates = {}
        for field, value in data.model_dump(exclude_unset=True).items():
            updates[field] = value
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            conn.execute(
                f"UPDATE endpoints SET {set_clause} WHERE id = ?",
                (*updates.values(), endpoint_id)
            )
            conn.commit()

        row = conn.execute("SELECT * FROM endpoints WHERE id = ?", (endpoint_id,)).fetchone()
        resp = _row_to_endpoint_response(row)
        # Reschedule with new interval/enabled state
        from app.monitor import reschedule_endpoint
        reschedule_endpoint(endpoint_id)
        return resp
    finally:
        conn.close()


@router.delete("/{endpoint_id}", status_code=204)
def delete_endpoint(endpoint_id: int):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id FROM endpoints WHERE id = ?", (endpoint_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Endpoint not found")
        conn.execute("DELETE FROM endpoints WHERE id = ?", (endpoint_id,))
        conn.commit()
    finally:
        conn.close()
    # Remove scheduler job
    from app.monitor import remove_endpoint_job
    remove_endpoint_job(endpoint_id)


@router.get("/{endpoint_id}/history")
def get_endpoint_history(
    endpoint_id: int,
    from_time: datetime = Query(None),
    to_time: datetime = Query(None),
    limit: int = Query(100, le=1000),
):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id FROM endpoints WHERE id = ?", (endpoint_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Endpoint not found")

        query = "SELECT * FROM check_history WHERE endpoint_id = ?"
        params = [endpoint_id]
        if from_time:
            query += " AND checked_at >= ?"
            params.append(from_time.isoformat())
        if to_time:
            query += " AND checked_at <= ?"
            params.append(to_time.isoformat())
        query += " ORDER BY checked_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": r["id"],
                "endpoint_id": r["endpoint_id"],
                "check_type": r["check_type"],
                "success": bool(r["success"]),
                "response_time_ms": r["response_time_ms"],
                "status_code": r["status_code"],
                "error_message": r["error_message"],
                "checked_at": r["checked_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()
