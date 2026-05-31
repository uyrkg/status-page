from fastapi import APIRouter, HTTPException
from datetime import datetime
from app.database import get_db_connection
from app.schemas import MaintenanceCreate, MaintenanceUpdate, MaintenanceResponse

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


@router.get("", response_model=list[MaintenanceResponse])
def list_maintenance():
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM maintenance_windows ORDER BY scheduled_start DESC"
        ).fetchall()
        return [_row_to_response(r) for r in rows]
    finally:
        conn.close()


@router.post("", response_model=MaintenanceResponse, status_code=201)
def create_maintenance(data: MaintenanceCreate):
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO maintenance_windows
               (endpoint_id, title, description, scheduled_start, scheduled_end, is_active)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (data.endpoint_id, data.title, data.description,
             data.scheduled_start.isoformat(), data.scheduled_end.isoformat(), data.is_active)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM maintenance_windows WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _row_to_response(row)
    finally:
        conn.close()


@router.get("/{maintenance_id}", response_model=MaintenanceResponse)
def get_maintenance(maintenance_id: int):
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM maintenance_windows WHERE id = ?", (maintenance_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Maintenance window not found")
        return _row_to_response(row)
    finally:
        conn.close()


@router.put("/{maintenance_id}", response_model=MaintenanceResponse)
def update_maintenance(maintenance_id: int, data: MaintenanceUpdate):
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM maintenance_windows WHERE id = ?", (maintenance_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Maintenance window not found")

        updates = {}
        for field, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                if field in ("scheduled_start", "scheduled_end"):
                    updates[field] = value.isoformat()
                else:
                    updates[field] = value

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            conn.execute(
                f"UPDATE maintenance_windows SET {set_clause} WHERE id = ?",
                (*updates.values(), maintenance_id)
            )
            conn.commit()

        row = conn.execute(
            "SELECT * FROM maintenance_windows WHERE id = ?", (maintenance_id,)
        ).fetchone()
        return _row_to_response(row)
    finally:
        conn.close()


@router.delete("/{maintenance_id}", status_code=204)
def delete_maintenance(maintenance_id: int):
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id FROM maintenance_windows WHERE id = ?", (maintenance_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Maintenance window not found")
        conn.execute(
            "DELETE FROM maintenance_windows WHERE id = ?", (maintenance_id,)
        )
        conn.commit()
    finally:
        conn.close()


def _row_to_response(row) -> MaintenanceResponse:
    return MaintenanceResponse(
        id=row["id"],
        endpoint_id=row["endpoint_id"],
        title=row["title"],
        description=row["description"],
        scheduled_start=row["scheduled_start"],
        scheduled_end=row["scheduled_end"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
    )
