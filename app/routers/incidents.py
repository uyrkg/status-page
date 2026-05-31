from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
from app.database import get_db_connection
from app.schemas import IncidentCreate, IncidentUpdate, IncidentResponse

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=list[IncidentResponse])
def list_incidents(include_resolved: bool = Query(True)):
    conn = get_db_connection()
    try:
        if include_resolved:
            rows = conn.execute("SELECT * FROM incidents ORDER BY started_at DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM incidents WHERE resolved_at IS NULL ORDER BY started_at DESC"
            ).fetchall()
        return [_row_to_response(r) for r in rows]
    finally:
        conn.close()


@router.post("", response_model=IncidentResponse, status_code=201)
def create_incident(data: IncidentCreate):
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO incidents
               (endpoint_id, title, description, status, severity, started_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (data.endpoint_id, data.title, data.description, data.status, data.severity,
             datetime.utcnow().isoformat())
        )
        conn.commit()
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _row_to_response(row)
    finally:
        conn.close()


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(incident_id: int):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Incident not found")
        return _row_to_response(row)
    finally:
        conn.close()


@router.put("/{incident_id}", response_model=IncidentResponse)
def update_incident(incident_id: int, data: IncidentUpdate):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Incident not found")

        updates = {}
        for field, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                updates[field] = value

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            conn.execute(
                f"UPDATE incidents SET {set_clause} WHERE id = ?",
                (*updates.values(), incident_id)
            )
            conn.commit()

        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return _row_to_response(row)
    finally:
        conn.close()


@router.delete("/{incident_id}", status_code=204)
def delete_incident(incident_id: int):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Incident not found")
        conn.execute("DELETE FROM incidents WHERE id = ?", (incident_id,))
        conn.commit()
    finally:
        conn.close()


@router.post("/{incident_id}/resolve", response_model=IncidentResponse)
def resolve_incident(incident_id: int):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Incident not found")
        conn.execute(
            "UPDATE incidents SET status = 'resolved', resolved_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), incident_id)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return _row_to_response(row)
    finally:
        conn.close()


def _row_to_response(row) -> IncidentResponse:
    return IncidentResponse(
        id=row["id"],
        endpoint_id=row["endpoint_id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        severity=row["severity"],
        started_at=row["started_at"],
        resolved_at=row["resolved_at"],
        created_at=row["created_at"],
    )
