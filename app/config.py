import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AppConfig:
    database_url: str = os.getenv("DATABASE_URL", "data/status.db")
    check_interval: int = int(os.getenv("CHECK_INTERVAL", "60"))
    history_retention_days: int = int(os.getenv("HISTORY_RETENTION_DAYS", "30"))
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.example.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "statuspage@example.com")
    smtp_tls: bool = os.getenv("SMTP_TLS", "true").lower() in ("true", "1", "yes")
    app_url: str = os.getenv("APP_URL", "http://localhost:8000")
    alert_cooldown_minutes: int = int(os.getenv("ALERT_COOLDOWN_MINUTES", "5"))
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")

    db_dir: str = field(init=False)

    def __post_init__(self):
        self.db_dir = os.path.dirname(self.database_url)
        if self.db_dir and not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir, exist_ok=True)


config = AppConfig()
