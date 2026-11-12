import asyncio
from datetime import timedelta

from sqlalchemy import select

from mandate.models import Mandate, Operation, Payment, ReconciliationLease, WebhookEvent, now
from mandate.reconciliation import claim_operation, reconcile_operation

from test_money_flow import Provider, captured, provider, purchase


def test_unknown_capture_reconciles_once_after_restart(client, database, provider, monkeypatch):
    mandate, proposal, path = purchase(client)
    assert client.post(path + "/checkout").status_code == 200
    provider.fail_capture = True
    assert client.post(path + "/capture").status_code == 502
    provider.fail_capture = False
    monkeypatch.setattr("mandate.reconciliation.SessionLocal", database)
    with database() as db:
        operation_id = db.scalar(select(Operation.id).where(Operation.kind == "CAPTURE"))

    async def get_order(order_id):
        return await provider.capture_order(order_id, "read-only-test-fixture")

    provider.get_order = get_order
    with database.begin() as db:
        db.get(ReconciliationLease, operation_id).available_at = now() - timedelta(seconds=1)
    assert claim_operation() == operation_id
    assert claim_operation() is None
    assert asyncio.run(reconcile_operation(provider, operation_id))
    assert not asyncio.run(reconcile_operation(provider, operation_id))
    stored = client.get("/api/mandates/" + mandate["id"]).json()
    assert stored["reserved_cents"] == 0 and stored["spent_cents"] == 34900
    assert client.get("/api/ledger/verify").json()["valid"]


def webhook_event():
    return {"id": "EVENT-1", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {
        "id": "CAPTURE-1", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "349.00"},
        "supplementary_data": {"related_ids": {"order_id": "ORDER-1"}}}}


def webhook_provider(provider, monkeypatch, *, verified=True):
    provider.missing_environment = lambda **_: []

    async def verify(headers, event, *, raw_body=None):
        return {"verification_status": "SUCCESS" if verified else "FAILURE"}

    async def get_order(order_id):
        return await provider.capture_order(order_id, "read-only-test-fixture")

    provider.verify_webhook, provider.get_order = verify, get_order
    monkeypatch.setattr("mandate.webhooks.PayPalClient", lambda: provider)


def test_verified_webhook_matches_provider_and_is_idempotent(client, database, provider, monkeypatch):
    mandate, proposal, path = purchase(client)
    assert client.post(path + "/checkout").status_code == 200
    webhook_provider(provider, monkeypatch)
    assert client.post("/api/webhooks/paypal", json=webhook_event()).json()["status"] == "processed"
    assert client.post("/api/webhooks/paypal", json=webhook_event()).json()["status"] == "duplicate"
    with database() as db:
        assert db.get(Mandate, mandate["id"]).spent_cents == 34900
        assert db.get(WebhookEvent, "EVENT-1").status == "PROCESSED"
    # A delayed pending notification cannot revert captured accounting.
    event = {**webhook_event(), "id": "EVENT-PENDING", "event_type": "PAYMENT.CAPTURE.PENDING"}
    assert client.post("/api/webhooks/paypal", json=event).json()["status"] == "ignored"
    assert client.get("/api/payments").json()[0]["status"] == "CAPTURED"


def test_invalid_signature_or_mismatched_amount_cannot_capture(client, database, provider, monkeypatch):
    mandate, _, path = purchase(client)
    assert client.post(path + "/checkout").status_code == 200
    webhook_provider(provider, monkeypatch, verified=False)
    assert client.post("/api/webhooks/paypal", json=webhook_event()).status_code == 400
    with database() as db:
        assert db.get(WebhookEvent, "EVENT-1") is None
        assert db.get(Mandate, mandate["id"]).spent_cents == 0
    webhook_provider(provider, monkeypatch)
    event = webhook_event()
    event["resource"]["amount"]["value"] = "1.00"
    assert client.post("/api/webhooks/paypal", json=event).status_code == 503
    assert client.get("/api/mandates/" + mandate["id"]).json()["spent_cents"] == 0
