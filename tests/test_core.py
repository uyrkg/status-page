import pytest
import sqlite3
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Test DB setup — each test gets a fresh temp DB
# ---------------------------------------------------------------------------

TEST_DB = tempfile.mktemp(suffix=".db")


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Override DATABASE_URL to use a temp db for every test."""
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    # Force reload of modules that cached config at import time
    import importlib
    import app.config
    importlib.reload(app.config)
    import app.database
    importlib.reload(app.database)
    # Init fresh schema
    from app.database import init_db
    init_db()
    yield
    try:
        os.unlink(TEST_DB)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    from app.database import get_db_connection
    c = get_db_connection()
    yield c
    c.close()


@pytest.fixture
def sample_endpoint(conn):
    cursor = conn.execute(
        """INSERT INTO endpoints (name, url, check_type, check_interval, timeout, expected_status, is_enabled)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("Test Endpoint", "https://httpbin.org/status/200", "http", 60, 5, 200, 1)
    )
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# monitor.py — check functions (pure unit tests, no I/O)
# ---------------------------------------------------------------------------

class TestCheckHttp:
    def test_success_returns_up(self):
        from app.monitor import check_http
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.Client") as mc:
            mc.return_value.__enter__.return_value.get.return_value = mock_resp
            result = check_http("https://example.com", 5, 200)
        assert result.success is True
        assert result.status_code == 200
        assert result.response_time_ms is not None

    def test_unexpected_status_returns_down(self):
        from app.monitor import check_http
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("httpx.Client") as mc:
            mc.return_value.__enter__.return_value.get.return_value = mock_resp
            result = check_http("https://example.com", 5, 200)
        assert result.success is False
        assert "Unexpected status 500" in result.error_message

    def test_timeout_returns_down(self):
        from app.monitor import check_http
        import httpx
        with patch("httpx.Client") as mc:
            mc.return_value.__enter__.return_value.get.side_effect = httpx.TimeoutException("timed out")
            result = check_http("https://slow.example.com", 2, 200)
        assert result.success is False
        assert "timed out" in result.error_message

    def test_request_error_returns_down(self):
        from app.monitor import check_http
        import httpx
        with patch("httpx.Client") as mc:
            mc.return_value.__enter__.return_value.get.side_effect = httpx.RequestError("no route to host")
            result = check_http("https://dead.example.com", 5, 200)
        assert result.success is False
        assert "no route to host" in result.error_message


class TestCheckTcp:
    def test_success_returns_up(self):
        from app.monitor import check_tcp
        with patch("httpx.Client") as mc:
            mc.return_value.__enter__.return_value.get.return_value = MagicMock()
            result = check_tcp("example.com", 443, 5)
        assert result.success is True

    def test_timeout_returns_down(self):
        from app.monitor import check_tcp
        import httpx
        with patch("httpx.Client") as mc:
            mc.return_value.__enter__.return_value.get.side_effect = httpx.TimeoutException("timeout")
            result = check_tcp("unreachable.example.com", 80, 2)
        assert result.success is False
        assert "timed out" in result.error_message


class TestCheckPing:
    def test_success_returns_up(self):
        from app.monitor import check_ping
        with patch("ping3.ping", return_value=0.042):
            result = check_ping("google.com", 5)
        assert result.success is True
        assert result.response_time_ms == 42

    def test_failure_returns_down(self):
        from app.monitor import check_ping
        with patch("ping3.ping", return_value=None):
            result = check_ping("unreachable.example.com", 5)
        assert result.success is False
        assert "unreachable" in result.error_message


# ---------------------------------------------------------------------------
# monitor.py — _run_endpoint_check (full cycle)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRunEndpointCheck:
    async def test_successful_check_records_history(self, conn, sample_endpoint):
        from app.monitor import _run_endpoint_check
        with patch("app.monitor.check_http") as mc:
            mc.return_value = MagicMock(success=True, response_time_ms=42,
                                       status_code=200, error_message=None)
            await _run_endpoint_check(sample_endpoint)

        row = conn.execute(
            "SELECT * FROM check_history WHERE endpoint_id=? ORDER BY id DESC LIMIT 1",
            (sample_endpoint,)
        ).fetchone()
        assert row is not None
        assert row["success"] == 1
        assert row["response_time_ms"] == 42

    async def test_failed_check_creates_incident(self, conn, sample_endpoint):
        from app.monitor import _run_endpoint_check, _failure_counts
        _failure_counts.clear()
        with patch("app.monitor.check_http") as mc:
            mc.return_value = MagicMock(success=False, response_time_ms=5000,
                                       status_code=None, error_message="Connection refused")
            await _run_endpoint_check(sample_endpoint)

        incident = conn.execute(
            "SELECT * FROM incidents WHERE endpoint_id=? AND resolved_at IS NULL",
            (sample_endpoint,)
        ).fetchone()
        assert incident is not None
        assert incident["severity"] == "cosmetic"  # first failure = 1 consecutive

    async def test_recovery_resolves_open_incident(self, conn, sample_endpoint):
        from app.monitor import _run_endpoint_check, _failure_counts
        _failure_counts.clear()
        # Pre-create an open incident
        conn.execute(
            """INSERT INTO incidents (endpoint_id, title, status, severity, started_at)
               VALUES (?, ?, 'investigating', 'major', ?)""",
            (sample_endpoint, "Prior incident", datetime.utcnow().isoformat())
        )
        conn.commit()
        incident_id = conn.execute("SELECT id FROM incidents ORDER BY id DESC LIMIT 1").fetchone()["id"]

        with patch("app.monitor.check_http") as mc:
            mc.return_value = MagicMock(success=True, response_time_ms=30,
                                       status_code=200, error_message=None)
            await _run_endpoint_check(sample_endpoint)

        incident = conn.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        assert incident["resolved_at"] is not None

    async def test_skipped_during_active_maintenance(self, conn, sample_endpoint):
        from app.monitor import _run_endpoint_check
        now = datetime.utcnow()
        conn.execute(
            """INSERT INTO maintenance_windows
               (endpoint_id, title, scheduled_start, scheduled_end, is_active)
               VALUES (?, ?, ?, ?, 1)""",
            (sample_endpoint, "Maintenance",
             (now - timedelta(hours=1)).isoformat(),
             (now + timedelta(hours=1)).isoformat())
        )
        conn.commit()

        with patch("app.monitor.check_http") as mc:
            await _run_endpoint_check(sample_endpoint)
            mc.assert_not_called()

        history = conn.execute(
            "SELECT COUNT(*) as cnt FROM check_history WHERE endpoint_id=?",
            (sample_endpoint,)
        ).fetchone()["cnt"]
        assert history == 0

    async def test_disabled_endpoint_not_checked(self, conn, sample_endpoint):
        from app.monitor import _run_endpoint_check
        conn.execute("UPDATE endpoints SET is_enabled=0 WHERE id=?",
                     (sample_endpoint,))
        conn.commit()

        with patch("app.monitor.check_http") as mc:
            await _run_endpoint_check(sample_endpoint)
            mc.assert_not_called()

    async def test_severity_escalation(self, conn, sample_endpoint):
        from app.monitor import _run_endpoint_check, _failure_counts
        # Run 5 consecutive failures to reach "critical"
        for i in range(5):
            _failure_counts.clear()
            with patch("app.monitor.check_http") as mc:
                mc.return_value = MagicMock(success=False, response_time_ms=1000,
                                           status_code=None, error_message="Fail")
                await _run_endpoint_check(sample_endpoint)

        incident = conn.execute(
            "SELECT severity FROM incidents WHERE endpoint_id=? AND resolved_at IS NULL",
            (sample_endpoint,)
        ).fetchone()
        # Last run should have set severity to critical (>= 5 failures)
        assert incident["severity"] == "critical"


# ---------------------------------------------------------------------------
# history.py
# ---------------------------------------------------------------------------

class TestPruneHistory:
    def test_prunes_old_records_keeps_recent(self, conn, sample_endpoint):
        from app.history import prune_old_history
        old = (datetime.utcnow() - timedelta(days=31)).isoformat()
        recent = (datetime.utcnow() - timedelta(days=5)).isoformat()

        conn.execute(
            """INSERT INTO check_history (endpoint_id, check_type, success, response_time_ms, checked_at)
               VALUES (?, ?, 0, 100, ?)""",
            (sample_endpoint, "http", old)
        )
        conn.execute(
            """INSERT INTO check_history (endpoint_id, check_type, success, response_time_ms, checked_at)
               VALUES (?, ?, 1, 50, ?)""",
            (sample_endpoint, "http", recent)
        )
        conn.commit()

        prune_old_history()

        rows = conn.execute(
            "SELECT * FROM check_history WHERE endpoint_id=?",
            (sample_endpoint,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["success"] == 1  # the recent one kept


# ---------------------------------------------------------------------------
# endpoints router (integration via TestClient)
# ---------------------------------------------------------------------------

class TestEndpointsRouter:
    def test_create_endpoint(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/endpoints", json={
            "name": "New Endpoint",
            "url": "https://example.com",
            "check_type": "http",
            "check_interval": 30,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "New Endpoint"
        assert data["check_interval"] == 30

    def test_create_endpoint_default_interval(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/endpoints", json={
            "name": "Minimal Endpoint",
            "url": "https://example.com",
        })
        assert resp.status_code == 201
        assert resp.json()["check_interval"] == 60  # default

    def test_list_endpoints(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/endpoints")
        assert resp.status_code == 200
        ids = [e["id"] for e in resp.json()]
        assert sample_endpoint in ids

    def test_get_endpoint_404(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/endpoints/99999")
        assert resp.status_code == 404

    def test_update_check_interval(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.put(f"/api/endpoints/{sample_endpoint}",
                          json={"check_interval": 120})
        assert resp.status_code == 200
        assert resp.json()["check_interval"] == 120

    def test_update_check_type(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.put(f"/api/endpoints/{sample_endpoint}",
                          json={"check_type": "ping", "url": None})
        assert resp.status_code == 200
        assert resp.json()["check_type"] == "ping"

    def test_delete_endpoint(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.delete(f"/api/endpoints/{sample_endpoint}")
        assert resp.status_code == 204
        assert client.get(f"/api/endpoints/{sample_endpoint}").status_code == 404

    def test_get_endpoint_history(self, conn, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        from datetime import datetime
        # Insert a history record
        conn.execute(
            """INSERT INTO check_history (endpoint_id, check_type, success, response_time_ms, checked_at)
               VALUES (?, ?, 1, 40, ?)""",
            (sample_endpoint, "http", datetime.utcnow().isoformat())
        )
        conn.commit()

        client = TestClient(app)
        resp = client.get(f"/api/endpoints/{sample_endpoint}/history")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# incidents router
# ---------------------------------------------------------------------------

class TestIncidentsRouter:
    def test_create_incident(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/incidents", json={
            "endpoint_id": sample_endpoint,
            "title": "Test Incident",
            "severity": "major"
        })
        assert resp.status_code == 201
        assert resp.json()["severity"] == "major"

    def test_list_incidents(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        client.post("/api/incidents", json={
            "endpoint_id": sample_endpoint,
            "title": "List Test"
        })
        resp = client.get("/api/incidents")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_list_incidents_exclude_resolved(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/incidents?include_resolved=false")
        assert resp.status_code == 200

    def test_get_incident_404(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/incidents/99999")
        assert resp.status_code == 404

    def test_resolve_incident(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        create_resp = client.post("/api/incidents", json={
            "endpoint_id": sample_endpoint,
            "title": "To Resolve"
        })
        incident_id = create_resp.json()["id"]
        resp = client.post(f"/api/incidents/{incident_id}/resolve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"

    def test_update_incident(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        create = client.post("/api/incidents", json={
            "endpoint_id": sample_endpoint,
            "title": "Old Title",
            "severity": "minor"
        })
        incident_id = create.json()["id"]
        resp = client.put(f"/api/incidents/{incident_id}",
                          json={"severity": "critical", "title": "Escalated"})
        assert resp.status_code == 200
        assert resp.json()["severity"] == "critical"
        assert resp.json()["title"] == "Escalated"


# ---------------------------------------------------------------------------
# maintenance router
# ---------------------------------------------------------------------------

class TestMaintenanceRouter:
    def test_create_maintenance(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        from datetime import datetime, timedelta
        client = TestClient(app)
        start = datetime.utcnow()
        end = start + timedelta(hours=2)
        resp = client.post("/api/maintenance", json={
            "endpoint_id": sample_endpoint,
            "title": "Planned downtime",
            "scheduled_start": start.isoformat(),
            "scheduled_end": end.isoformat()
        })
        assert resp.status_code == 201
        assert resp.json()["title"] == "Planned downtime"

    def test_create_global_maintenance_no_endpoint(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from datetime import datetime, timedelta
        client = TestClient(app)
        start = datetime.utcnow()
        end = start + timedelta(hours=1)
        resp = client.post("/api/maintenance", json={
            "title": "Global maintenance",
            "scheduled_start": start.isoformat(),
            "scheduled_end": end.isoformat()
        })
        assert resp.status_code == 201
        assert resp.json()["endpoint_id"] is None

    def test_get_maintenance_404(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/maintenance/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# status router
# ---------------------------------------------------------------------------

class TestStatusRouter:
    def test_status_all_operational_clean(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "all_operational"

    def test_status_degraded_on_minor_incident(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        client.post("/api/incidents", json={
            "endpoint_id": sample_endpoint,
            "title": "Minor degradation",
            "severity": "minor"
        })
        resp = client.get("/api/status")
        assert resp.json()["status"] == "degraded"

    def test_status_partial_outage_on_major(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        client.post("/api/incidents", json={
            "endpoint_id": sample_endpoint,
            "title": "Major outage",
            "severity": "major"
        })
        resp = client.get("/api/status")
        assert resp.json()["status"] == "partial_outage"

    def test_status_major_outage_on_critical(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        client.post("/api/incidents", json={
            "endpoint_id": sample_endpoint,
            "title": "Critical!",
            "severity": "critical"
        })
        resp = client.get("/api/status")
        assert resp.json()["status"] == "major_outage"

    def test_stats_endpoint(self, sample_endpoint):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "endpoints" in data
        ep = next((e for e in data["endpoints"] if e["endpoint_id"] == sample_endpoint), None)
        assert ep is not None
        assert "uptime_7d" in ep
        assert "uptime_30d" in ep


# ---------------------------------------------------------------------------
# config router
# ---------------------------------------------------------------------------

class TestConfigRouter:
    def test_get_smtp_default(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/config/smtp")
        assert resp.status_code == 200
        data = resp.json()
        assert "smtp_host" in data
        assert data["password_set"] is False

    def test_update_smtp_config(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.put("/api/config/smtp", json={
            "smtp_host": "mail.example.com",
            "smtp_port": 587,
            "smtp_user": "alerts@example.com",
            "smtp_password": "hunter2",
            "smtp_from": "status@example.com",
            "smtp_tls": True
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["smtp_host"] == "mail.example.com"
        assert data["password_set"] is True

        # Verify persisted across requests
        resp2 = client.get("/api/config/smtp")
        assert resp2.json()["smtp_host"] == "mail.example.com"


# ---------------------------------------------------------------------------
# schemas validation
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_endpoint_create_required_fields(self):
        from app.schemas import EndpointCreate
        ep = EndpointCreate(name="Test")
        assert ep.name == "Test"
        assert ep.check_type == "http"
        assert ep.check_interval == 60
        assert ep.is_enabled is True

    def test_endpoint_create_all_fields(self):
        from app.schemas import EndpointCreate
        ep = EndpointCreate(
            name="Full",
            url="https://a.com",
            host="a.com",
            port=443,
            check_type="tcp",
            check_interval=30,
            timeout=10,
            expected_status=200,
            is_enabled=False,
        )
        assert ep.check_type == "tcp"
        assert ep.is_enabled is False

    def test_incident_create_defaults(self):
        from app.schemas import IncidentCreate
        inc = IncidentCreate(endpoint_id=1, title="Down")
        assert inc.severity == "major"
        assert inc.status == "investigating"

    def test_maintenance_create(self):
        from app.schemas import MaintenanceCreate
        from datetime import datetime, timedelta
        m = MaintenanceCreate(
            endpoint_id=5,
            title="Win",
            scheduled_start=datetime.utcnow(),
            scheduled_end=datetime.utcnow() + timedelta(hours=1),
        )
        assert m.title == "Win"
        assert m.is_active is True

    def test_status_response(self):
        from app.schemas import StatusResponse
        s = StatusResponse(status="major_outage", endpoints_affected=3, active_incidents=2)
        assert s.status == "major_outage"
        assert s.endpoints_affected == 3

    def test_smtp_config_update(self):
        from app.schemas import SMTPConfigUpdate
        cfg = SMTPConfigUpdate(smtp_host="smtp.gmail.com", smtp_port=587)
        assert cfg.smtp_port == 587
        assert cfg.smtp_tls is True  # default
