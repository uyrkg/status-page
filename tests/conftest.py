import pytest


@pytest.fixture(autouse=True)
def suppress_scheduler(monkeypatch):
    """Prevent the scheduler from starting during tests."""
    monkeypatch.setattr("app.monitor.start_scheduler", lambda app: None)
