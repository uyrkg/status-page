import sqlite3
import os
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from app.config import config


def get_db():
    """Yield dict-like row connections to SQLite."""
    conn = sqlite3.connect(config.database_url, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_db_connection():
    """Get a direct connection (no context manager needed)."""
    conn = sqlite3.connect(config.database_url, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    os.makedirs(config.db_dir or ".", exist_ok=True)
    conn = sqlite3.connect(config.database_url, check_same_thread=False)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS endpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT,
            host TEXT,
            port INTEGER,
            check_type TEXT NOT NULL DEFAULT 'http',
            check_interval INTEGER DEFAULT 60,
            timeout INTEGER DEFAULT 5,
            expected_status INTEGER DEFAULT 200,
            is_enabled BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_id INTEGER NOT NULL REFERENCES endpoints(id),
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'investigating',
            severity TEXT NOT NULL DEFAULT 'major',
            started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS maintenance_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_id INTEGER REFERENCES endpoints(id),
            title TEXT NOT NULL,
            description TEXT,
            scheduled_start DATETIME NOT NULL,
            scheduled_end DATETIME NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS check_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_id INTEGER NOT NULL REFERENCES endpoints(id),
            check_type TEXT NOT NULL,
            success BOOLEAN NOT NULL,
            response_time_ms INTEGER,
            status_code INTEGER,
            error_message TEXT,
            checked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS email_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_id INTEGER REFERENCES endpoints(id),
            incident_id INTEGER REFERENCES incidents(id),
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            success BOOLEAN
        );

        CREATE TABLE IF NOT EXISTS smtp_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            smtp_host TEXT,
            smtp_port INTEGER DEFAULT 587,
            smtp_user TEXT,
            smtp_password TEXT,
            smtp_from TEXT,
            smtp_tls BOOLEAN DEFAULT 1,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    conn.close()
