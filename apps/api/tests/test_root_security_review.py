import pytest
from mandate import models  # Register the tables before the disposable database fixture runs.


@pytest.fixture(autouse=True)
def development_session(monkeypatch):
    from mandate import config

    monkeypatch.setattr(config, "ACCESS_REQUIRED", False)
    monkeypatch.setattr(config, "PRODUCTION", False)


def test_non_ascii_csrf_is_rejected_without_a_server_error(client):
    response = client.post("/api/logout", headers=[(b"x-csrf-token", b"\xff")])
    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid CSRF token"}
