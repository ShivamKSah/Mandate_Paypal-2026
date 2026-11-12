"""Tests for PUBLIC_DEMO mode, session isolation, reset, daily LLM spend cap, and Render config."""
from pathlib import Path
import runpy

from fastapi.testclient import TestClient
import pytest

from mandate import config
from mandate.main import app


def test_public_demo_production_requires_https_and_secure_cookie(monkeypatch):
    source = Path(__file__).parents[1] / "mandate/config.py"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    monkeypatch.setenv("APP_ACCESS_KEY", "")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://demo.example.com")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    with pytest.raises(RuntimeError, match="Production requires"):
        runpy.run_path(str(source))

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://demo.example.com")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    loaded = runpy.run_path(str(source))
    assert loaded["PUBLIC_DEMO"] is True
    assert loaded["ACCESS_REQUIRED"] is False


def test_public_demo_isolates_visitors_seeds_grant_resets_and_caps_daily_llm(database, monkeypatch):
    from mandate.db import get_db

    def isolated_db():
        with database() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_db] = isolated_db
    app.state.testing = True
    monkeypatch.setattr("mandate.http_boundary.SessionLocal", database)
    monkeypatch.setattr("mandate.agents.router.SessionLocal", database)
    monkeypatch.setattr("mandate.recovery.SessionLocal", database)
    monkeypatch.setattr(config, "PUBLIC_DEMO", True)
    monkeypatch.setattr(config, "ACCESS_REQUIRED", False)
    monkeypatch.setattr(config, "DAILY_LLM_RUN_LIMIT", 2)

    try:
        with TestClient(app) as visitor_a, TestClient(app) as visitor_b:
            sess_a = visitor_a.get("/api/session").json()
            sess_b = visitor_b.get("/api/session").json()
            assert sess_a["public_demo"] is True
            assert sess_a["id"] != sess_b["id"]
            visitor_a.headers["X-CSRF-Token"] = sess_a["csrf_token"]
            visitor_b.headers["X-CSRF-Token"] = sess_b["csrf_token"]

            grants_a = visitor_a.get("/api/mandates").json()
            grants_b = visitor_b.get("/api/mandates").json()
            assert len(grants_a) == 1 and grants_a[0]["budget_cents"] == 50000
            assert len(grants_b) == 1 and grants_b[0]["id"] != grants_a[0]["id"]

            # Daily LLM cap (limit=2) enforced across public demo visitors
            prop_resp = visitor_a.post("/api/proposals", json={
                "mandate_id": grants_a[0]["id"],
                "purchase_intent_id": "demo-seed-cap",
                "items": [{"product_id": "desk-160", "quantity": 1}],
                "currency": "USD",
            })
            assert prop_resp.status_code == 200
            assert visitor_a.post("/api/agent-runs", json={
                "mandate_id": grants_a[0]["id"],
                "instruction": "Buy a desk",
                "allow_fallback": True,
            }).status_code == 200
            assert visitor_b.post("/api/agent-runs", json={
                "mandate_id": grants_b[0]["id"],
                "instruction": "Buy a desk",
                "allow_fallback": True,
            }).status_code == 200
            capped = visitor_b.post("/api/agent-runs", json={
                "mandate_id": grants_b[0]["id"],
                "instruction": "Buy a desk",
                "allow_fallback": True,
            })
            assert capped.status_code == 429

            # Reset rotates to a fresh session with a fresh seeded grant and revokes old session
            old_cookie = visitor_a.cookies.get("mandate_session")
            reset_resp = visitor_a.post("/api/session/reset", json={})
            assert reset_resp.status_code == 200
            reset_data = reset_resp.json()
            assert reset_data["id"] != sess_a["id"]
            visitor_a.headers["X-CSRF-Token"] = reset_data["csrf_token"]
            reset_grants = visitor_a.get("/api/mandates").json()
            assert len(reset_grants) == 1 and reset_grants[0]["id"] != grants_a[0]["id"]

            visitor_a.cookies.set("mandate_session", old_cookie)
            assert visitor_a.get("/api/mandates").status_code == 401
    finally:
        app.dependency_overrides.clear()
        app.state.testing = False


def test_render_yaml_has_no_secrets_and_PaidDb_todo():
    render_path = Path(__file__).resolve().parents[3] / "render.yaml"
    text = render_path.read_text(encoding="utf-8")
    assert "healthCheckPath: /api/health" in text
    assert "python -m mandate.migrate" in text
    assert "sync: false" in text
    assert "TODO:" in text and "Dec 15" in text
