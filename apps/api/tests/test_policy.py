from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from mandate.main import app
from mandate.models import AuditEvent, Mandate, now


def grant(client, **overrides):
    values = {"budget_cents": 50000, "per_transaction_cents": 50000, "allowed_categories": ["furniture"],
              "allowed_merchants": ["demo-merchant"], "constraints": {"width_cm": 160}, "instruction": "Buy a 160 cm desk"}
    result = client.post("/api/mandates", json={**values, **overrides})
    assert result.status_code == 200, result.text
    return result.json()


def propose(client, mandate, intent="desk", product="desk-160", **overrides):
    return client.post("/api/proposals", json={"mandate_id": mandate["id"], "purchase_intent_id": intent,
                                              "items": [{"product_id": product, "quantity": 1}], **overrides})


def test_valid_reservation_idempotency_and_audit(client):
    mandate = grant(client)
    first = propose(client, mandate).json()
    assert first["decision"] == "APPROVE"
    assert len(first["rules"]) == 11
    assert first["payment_id"]
    assert propose(client, mandate).json()["id"] == first["id"]
    assert propose(client, mandate, product="desk-120").status_code == 409
    stored = client.get("/api/mandates/" + mandate["id"]).json()
    assert stored["reserved_cents"] == 34900 and stored["spent_cents"] == 0
    assert client.get("/api/ledger/verify").json()["valid"]


def test_constraints_price_and_category(client):
    mandate = grant(client)
    assert propose(client, mandate, "missing", "desk-unknown").json()["decision"] == "ESCALATE"
    mismatch = propose(client, mandate, "mismatch", "desk-120").json()
    assert mismatch["decision"] == "DENY"
    assert next(r for r in mismatch["rules"] if r["id"] == "P09")["status"] == "DENY"
    assert propose(client, mandate, "price", claimed_total_cents=1).json()["decision"] == "DENY"
    assert propose(client, mandate, "attack", "gift-card").json()["decision"] == "DENY"
    assert propose(client, mandate, "usd", currency="EUR").json()["decision"] == "DENY"
    assert propose(client, mandate, "sub", "subscription").json()["decision"] == "DENY"
    assert client.post("/api/proposals/" + mismatch["id"] + "/approve", json={"cart_hash": mismatch["cart_hash"]}).status_code == 409


def test_human_hash_approval_and_capability_separation(client):
    mandate = grant(client)
    proposal = propose(client, mandate, product="desk-unknown").json()
    path = "/api/proposals/" + proposal["id"] + "/approve"
    assert client.post(path, json={"cart_hash": "0" * 64}).status_code == 409
    assert client.post(path, json={"cart_hash": proposal["cart_hash"]}, headers={"Authorization": "Bearer agent"}).status_code == 403
    approved = client.post(path, json={"cart_hash": proposal["cart_hash"]})
    assert approved.status_code == 200 and approved.json()["payment_id"]


def test_session_isolation_csrf_and_strict_money(client):
    mandate = grant(client)
    assert client.post("/api/mandates/" + mandate["id"] + "/revoke", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    with TestClient(app) as other:
        session = other.get("/api/session").json()
        other.headers["X-CSRF-Token"] = session["csrf_token"]
        assert other.get("/api/mandates/" + mandate["id"]).status_code == 404
        assert other.get("/api/ledger").json() == []
        assert other.post("/api/mandates/" + mandate["id"] + "/revoke").status_code == 404
    response = client.post("/api/mandates", json={"budget_cents": True, "per_transaction_cents": "50000", "allowed_categories": ["furniture"], "allowed_merchants": ["demo-merchant"], "instruction": "x"})
    assert response.status_code == 422


def test_expiry_revocation_and_velocity(client, database):
    mandate = grant(client)
    with database.begin() as db:
        db.get(Mandate, mandate["id"]).expires_at = now() - timedelta(seconds=1)
    assert propose(client, mandate).json()["decision"] == "DENY"
    mandate = grant(client, velocity_limit=1, constraints={})
    assert propose(client, mandate, "one", "desk-120").json()["decision"] == "APPROVE"
    assert propose(client, mandate, "two", "desk-120").json()["decision"] == "DENY"
    revoked = client.post("/api/mandates/" + mandate["id"] + "/revoke").json()
    assert revoked["reserved_cents"] == 0
    assert propose(client, mandate, "three").json()["decision"] == "DENY"


def test_concurrent_budget_lock(client, monkeypatch):
    from mandate.catalog import CATALOG
    monkeypatch.setitem(CATALOG, "desk-unknown", {**CATALOG["desk-unknown"], "unit_price_cents": 30000})
    mandate = grant(client, constraints={})
    cookies, headers = dict(client.cookies), dict(client.headers)

    def run(index):
        with TestClient(app, cookies=cookies, headers=headers) as parallel:
            return propose(parallel, mandate, str(index), "desk-unknown").json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [1, 2]))
    assert sorted(result["decision"] for result in results) == ["APPROVE", "DENY"]
    stored = client.get("/api/mandates/" + mandate["id"]).json()
    assert stored["reserved_cents"] == 30000
    assert stored["spent_cents"] + stored["reserved_cents"] <= 50000


def test_audit_detects_alteration(client, database):
    grant(client)
    checkpoint = client.get("/api/ledger/verify").json()["checkpoint"]
    with database.begin() as db:
        row = db.scalar(select(AuditEvent))
        row.details = {"budget_cents": 1}
    result = client.get("/api/ledger/verify").json()
    assert result["checkpoint"] == checkpoint and not result["valid"]
