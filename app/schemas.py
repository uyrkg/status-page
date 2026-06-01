from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# --- Endpoint schemas ---
class EndpointCreate(BaseModel):
    name: str
    url: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    check_type: str = "http"
    check_interval: int = 60
    timeout: int = 5
    expected_status: int = 200
    is_enabled: bool = True


class EndpointUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    check_type: Optional[str] = None
    check_interval: Optional[int] = None
    timeout: Optional[int] = None
    expected_status: Optional[int] = None
    is_enabled: Optional[bool] = None


class EndpointResponse(BaseModel):
    id: int
    name: str
    url: Optional[str]
    host: Optional[str]
    port: Optional[int]
    check_type: str
    check_interval: int
    timeout: int
    expected_status: int
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    current_status: Optional[str] = None  # 'up', 'down', 'maintenance', 'unknown'


# --- Incident schemas ---
class IncidentCreate(BaseModel):
    endpoint_id: int
    title: str
    description: Optional[str] = None
    status: str = "investigating"
    severity: str = "major"


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    severity: Optional[str] = None


class IncidentResponse(BaseModel):
    id: int
    endpoint_id: int
    title: str
    description: Optional[str]
    status: str
    severity: str
    started_at: datetime
    resolved_at: Optional[datetime]
    created_at: datetime
    endpoint_name: Optional[str] = None  # denormalized from JOIN with endpoints table


# --- Maintenance schemas ---
class MaintenanceCreate(BaseModel):
    endpoint_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    scheduled_start: datetime
    scheduled_end: datetime
    is_active: bool = True


class MaintenanceUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    is_active: Optional[bool] = None


class MaintenanceResponse(BaseModel):
    id: int
    endpoint_id: Optional[int]
    title: str
    description: Optional[str]
    scheduled_start: datetime
    scheduled_end: datetime
    is_active: bool
    created_at: datetime


# --- Status schemas ---
class StatusResponse(BaseModel):
    status: str  # 'all_operational', 'degraded', 'partial_outage', 'major_outage', 'maintenance'
    endpoints_affected: int = 0
    active_incidents: int = 0


class UptimeStat(BaseModel):
    endpoint_id: int
    endpoint_name: str
    uptime_7d: float
    uptime_30d: float


class StatsResponse(BaseModel):
    endpoints: list[UptimeStat]


# --- SMTP Config schemas ---
class SMTPConfigUpdate(BaseModel):
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True


class SMTPConfigResponse(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_from: str
    smtp_tls: bool
    password_set: bool = False
