from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Check result returned by monitor functions
@dataclass
class CheckResult:
    success: bool
    response_time_ms: Optional[int] = None
    status_code: Optional[int] = None
    error_message: Optional[str] = None


@dataclass
class Endpoint:
    id: int
    name: str
    url: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    check_type: str = "http"
    check_interval: int = 60
    timeout: int = 5
    expected_status: int = 200
    is_enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Incident:
    id: int
    endpoint_id: int
    title: str
    description: Optional[str] = None
    status: str = "investigating"
    severity: str = "major"
    started_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MaintenanceWindow:
    id: int
    title: str
    endpoint_id: Optional[int] = None
    description: Optional[str] = None
    scheduled_start: datetime = field(default_factory=datetime.utcnow)
    scheduled_end: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CheckHistory:
    id: int
    endpoint_id: int
    check_type: str
    success: bool
    response_time_ms: Optional[int] = None
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    checked_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SMTPConfig:
    smtp_host: str = "smtp.example.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "statuspage@example.com"
    smtp_tls: bool = True
