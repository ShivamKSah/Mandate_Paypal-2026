"""Tests for Break-the-Mandate 15-attack simulator and challenge statistics."""
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from mandate.attacks import ATTACK_CATALOG
from mandate.main import app
from mandate.models import ChallengeAttempt, Payment


def test_every_attack_triggers_expected_rule_without_payment_or_paypal(client, database, monkeypatch):
    paypal_called = False

    def fail_paypal(*_args, **_kwargs):
        nonlocal paypal_called
        paypal_called = True
        raise AssertionError("PayPal client must never be constructed during blocked attack simulations")

    monkeypatch.setattr("mandate.payments.paypal.PayPalClient.__init__", fail_paypal)

    catalog_resp = client.get("/api/attacks")
    assert catalog_resp.status_code == 200
    assert len(catalog_resp.json()) == 15

    for item in ATTACK_CATALOG:
        resp = client.post("/api/attacks/run", json={"attack_id": item["id"]})
        assert resp.status_code == 200, item["id"]
        data = resp.json()
        assert data["attack_id"] == item["id"]
        assert data["verdict"] != "APPROVE", data
        assert data["breached"] is False, data
        assert data["actual_rule"] == data["expected_rule"], data

    with database() as db:
        assert db.scalar(select(func.count(Payment.id))) == 0
        assert db.scalar(select(func.count(ChallengeAttempt.id))) == 15
    assert paypal_called is False


def test_run_all_and_session_scoped_challenge_stats(client, database):
    res = client.post("/api/attacks/run-all", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["attempts"] == 15
    assert body["breaches"] == 0
    assert body["blocked"] == 15
    assert all(row["actual_rule"] == row["expected_rule"] and not row["breached"] for row in body["results"])

    stats = client.get("/api/challenge/stats")
    assert stats.status_code == 200
    s = stats.json()
    assert s["attempts"] == 15
    assert s["breaches"] == 0
    assert sum(s["per_rule_counts"].values()) == 15
    assert s["per_rule_counts"]["P01"] == 2
    assert s["per_rule_counts"]["P04"] == 2
    assert s["per_rule_counts"]["P06"] == 4
    assert s["per_rule_counts"]["CART_HASH_BINDING"] == 1

    # Isolated per-session stats and CSRF/validation enforcement
    assert client.post("/api/attacks/run", json={"attack_id": "nonexistent"}).status_code == 400
    assert client.post("/api/attacks/run", json={"attack_id": "over_budget"}, headers={"X-CSRF-Token": "bad"}).status_code == 403
    with TestClient(app) as other:
        other.headers["X-CSRF-Token"] = other.get("/api/session").json()["csrf_token"]
        other_stats = other.get("/api/challenge/stats").json()
        assert other_stats == {"attempts": 0, "breaches": 0, "per_rule_counts": {}}

    assert client.get("/api/ledger/verify").json()["valid"] is True

