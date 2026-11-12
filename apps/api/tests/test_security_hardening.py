from datetime import timedelta
import hashlib

from sqlalchemy import select
from fastapi import HTTPException
from concurrent.futures import ThreadPoolExecutor
import pytest

from mandate.models import Session, now
from mandate.security import COOKIE_NAME


def test_cookie_secret_is_not_the_public_session_id(client, database):
    session = client.get("/api/session").json()
    token = client.cookies.get(COOKIE_NAME)
    assert token != session["id"]
    with database() as db:
        owner = db.get(Session, session["id"])
        assert owner.token_hash == hashlib.sha256(token.encode()).hexdigest()


def test_expired_session_cannot_read_private_records(client, database):
    session = client.get("/api/session").json()
    with database() as db, db.begin():
        db.get(Session, session["id"]).expires_at = now() - timedelta(seconds=1)
    assert client.get("/api/mandates").status_code == 401


def test_logout_invalidates_stolen_cookie_server_side(client):
    stolen = client.cookies.get(COOKIE_NAME)
    assert client.post("/api/logout").status_code == 204
    client.cookies.set(COOKIE_NAME, stolen)
    assert client.get("/api/mandates").status_code == 401


def test_request_body_limit_precedes_json_validation(client):
    assert client.post("/api/mandates", content=b"x" * 300_000).status_code == 413


def test_sensitive_responses_have_safe_browser_headers(client):
    response = client.get("/api/session")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


def test_access_gate_login_rotation_and_logout(client, monkeypatch):
    from mandate import config
    monkeypatch.setattr(config, "ACCESS_REQUIRED", True)
    monkeypatch.setattr(config, "APP_ACCESS_KEY", "test-access-key-that-is-long-enough")
    old_cookie = client.cookies.get(COOKIE_NAME)
    assert client.get("/api/session").status_code == 401
    assert client.get("/api/mandates").status_code == 401
    assert client.post("/api/login", json={"access_key": config.APP_ACCESS_KEY}, headers={"Origin": "https://attacker.invalid"}).status_code == 403
    response = client.post("/api/login", json={"access_key": config.APP_ACCESS_KEY})
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["access_required"] is True
    assert client.cookies.get(COOKIE_NAME) != old_cookie
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    assert client.get("/api/mandates").status_code == 200
    assert client.post("/api/logout").status_code == 204
    assert client.get("/api/session").status_code == 401


def test_failed_logins_count_even_though_requests_fail(client, monkeypatch):
    from mandate import config
    monkeypatch.setattr(config, "APP_ACCESS_KEY", "a-real-looking-test-key-with-32-characters")
    for _ in range(5):
        assert client.post("/api/login", json={"access_key": "wrong"}).status_code == 401
    response = client.post("/api/login", json={"access_key": config.APP_ACCESS_KEY})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_relogin_keeps_operator_workspace_but_invalidates_old_cookie(client, monkeypatch):
    from mandate import config
    monkeypatch.setattr(config, "APP_ACCESS_KEY", "test-operator-key-that-is-long-enough")
    first = client.post("/api/login", json={"access_key": config.APP_ACCESS_KEY}).json()
    old_token = client.cookies.get(COOKIE_NAME)
    client.headers["X-CSRF-Token"] = first["csrf_token"]
    created = client.post("/api/mandates", json={"budget_cents": 50000, "per_transaction_cents": 50000,
        "allowed_categories": ["furniture"], "allowed_merchants": ["demo-merchant"], "instruction": "Buy a desk"})
    assert created.status_code == 200
    assert client.post("/api/logout").status_code == 204
    second = client.post("/api/login", json={"access_key": config.APP_ACCESS_KEY}).json()
    assert second["id"] == first["id"]
    assert second["csrf_token"] != first["csrf_token"]
    assert client.get("/api/mandates").json()[0]["id"] == created.json()["id"]
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, old_token)
    assert client.get("/api/mandates").status_code == 401


def test_atomic_rate_limit_across_database_connections(database):
    from mandate.rate_limits import consume

    def attempt(_):
        with database() as db:
            try:
                consume(db, "test-global", "same-identity", 3)
                db.commit()
                return True
            except HTTPException:
                db.rollback()
                return False
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(attempt, range(6))) == 3


def test_cross_origin_mutation_and_untrusted_host_rejected(client):
    assert client.post("/api/logout", headers={"Origin": "https://attacker.invalid"}).status_code == 403
    assert client.get("/api/session", headers={"Host": "attacker.invalid"}).status_code == 400


def test_production_configuration_fails_closed(monkeypatch):
    import runpy
    from pathlib import Path
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("APP_ACCESS_KEY", "")
    source = Path(__file__).parents[1] / "mandate/config.py"
    with pytest.raises(RuntimeError, match="Production requires"):
        runpy.run_path(str(source))
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://mandate.example")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("APP_ACCESS_KEY", "a-valid-test-application-access-key-long-enough")
    assert runpy.run_path(str(source))["ACCESS_REQUIRED"] is True


def test_database_outage_has_no_internal_details(client):
    from mandate.db import get_db
    from mandate.main import app
    from sqlalchemy.exc import SQLAlchemyError

    previous = app.dependency_overrides[get_db]
    def unavailable():
        raise SQLAlchemyError("private database configuration must not appear in response")
        yield
    app.dependency_overrides[get_db] = unavailable
    try:
        response = client.get("/api/health")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable; retry later"}
    finally:
        app.dependency_overrides[get_db] = previous
