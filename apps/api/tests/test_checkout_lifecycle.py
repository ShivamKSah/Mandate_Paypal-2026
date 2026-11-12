from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mandate.main import app
from mandate.models import Mandate, Operation, Payment, Proposal, now
from mandate.payments.paypal import PayPalError
from test_money_flow import provider, purchase
from test_policy import propose


@pytest.mark.parametrize("stage", ["checkout", "capture"])
def test_approved_purchase_revalidates_after_proposal_ttl(client, database, provider, stage):
    _, proposal, path = purchase(client)
    assert proposal["expires_at"] and proposal["quote_expires_at"] and proposal["grant_version"] == 1
    if stage == "capture":
        assert client.post(path + "/checkout").status_code == 200
    with database.begin() as db:
        stored = db.get(Proposal, proposal["id"])
        stored.expires_at = stored.quote_expires_at = now() - timedelta(minutes=1)
    response = client.post(path + "/" + stage)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == ("CAPTURED" if stage == "capture" else "ORDER_CREATED")


def test_later_duplicate_cannot_block_original_capture(client, provider):
    grant, _, path = purchase(client)
    assert client.post(path + "/checkout").status_code == 200
    assert propose(client, grant, intent="later-duplicate").json()["decision"] == "DENY"
    assert client.post(path + "/capture").json()["status"] == "CAPTURED"


def test_cancel_local_reservation_releases_exactly_once(client, database, provider):
    grant, proposal, path = purchase(client)
    assert client.get("/api/payments").json()[0]["can_cancel"]
    for _ in range(2):
        response = client.post(path + "/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "RELEASED" and not response.json()["can_cancel"]
    assert client.post(path + "/checkout").status_code == 409
    assert provider.calls == []
    with database() as db:
        assert db.get(Mandate, grant["id"]).reserved_cents == 0
        assert db.get(Proposal, proposal["id"]).status == "CANCELLED"
        assert db.scalar(select(Operation)).status == "CANCELLED"
    events = client.get("/api/ledger").json()
    assert sum(event["event_type"] == "RESERVATION_RELEASED" for event in events) == 1
    assert client.get("/api/ledger/verify").json()["valid"]


@pytest.mark.parametrize("stage", ["created", "unknown_create", "unknown_capture", "captured", "failed_create"])
def test_cancel_cannot_release_dispatched_money(client, database, provider, monkeypatch, stage):
    grant, proposal, path = purchase(client)
    provider.fail_create = stage == "unknown_create"
    if stage == "failed_create":
        async def rejected(*args):
            raise PayPalError("Rejected", code="PROVIDER_REJECTED", status_code=401)
        monkeypatch.setattr(provider, "create_order", rejected)
    client.post(path + "/checkout")
    if stage in {"unknown_capture", "captured"}:
        provider.fail_capture = stage == "unknown_capture"
        client.post(path + "/capture")
    assert not client.get("/api/payments").json()[0]["can_cancel"]
    assert client.post(path + "/cancel").status_code == 409
    with database() as db:
        stored = db.get(Mandate, grant["id"])
        assert stored.reserved_cents == (0 if stage == "captured" else 34900)
        assert db.get(Payment, proposal["payment_id"]).status != "RELEASED"


def test_cancel_requires_owner_and_csrf(client, provider):
    _, _, path = purchase(client)
    assert client.post(path + "/cancel", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    with TestClient(app) as other:
        other.headers["X-CSRF-Token"] = other.get("/api/session").json()["csrf_token"]
        assert other.post(path + "/cancel").status_code == 404


def test_capture_rejection_has_actionable_redacted_reason(client, provider, monkeypatch):
    _, _, path = purchase(client)
    assert client.post(path + "/checkout").status_code == 200
    async def rejected(*args):
        raise PayPalError("private provider content", code="PROVIDER_REJECTED", status_code=422, issue="ORDER_NOT_APPROVED")
    monkeypatch.setattr(provider, "capture_order", rejected)
    response = client.post(path + "/capture")
    assert response.status_code == 502 and "Approve this order in PayPal" in response.json()["detail"]
    assert "private" not in response.text
    failure = client.get("/api/ledger").json()[-1]
    assert failure["details"]["provider_issue"] == "ORDER_NOT_APPROVED"
    assert failure["details"]["provider_status"] == 422


def test_unsettled_capture_response_is_not_reported_successful(client, provider, monkeypatch):
    _, _, path = purchase(client)
    assert client.post(path + "/checkout").status_code == 200
    monkeypatch.setattr("mandate.payments_api.settle_capture", lambda *args: False)
    assert client.post(path + "/capture").status_code == 409
    assert client.get("/api/payments").json()[0]["status"] == "CAPTURE_PENDING"
