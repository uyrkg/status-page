import pytest


@pytest.fixture(autouse=True)
def suppress_scheduler(monkeypatch):
    """Prevent the scheduler from starting during tests."""
    monkeypatch.setattr("app.monitor.start_scheduler", lambda app: None)


@pytest.fixture
def client():
    """Return a TestClient with the app fully loaded (no scheduler)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture
def auth_client(client):
    """Return a TestClient that is already logged in with a valid session.

    Injects a session token directly (bypasses login endpoint) to avoid
    consuming rate limit slots.
    """
    from app.auth import create_session_token
    token = create_session_token()
    client.cookies.set("admin_session", token)
    return client
