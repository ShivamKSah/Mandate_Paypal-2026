"""Independent boundary checks. Provider outcomes are deterministic test fixtures."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from mandate.main import app
from mandate.models import Case, Mandate, Operation, Payment, Proposal, now
from mandate.payments.paypal import PayPalError


class Provider:
    configured = True

    def __init__(self):
        self.calls = []
        self.capture_error = None
        self.refund_error = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def create_order(self, cart, request_id, *urls):
        self.calls.append(("create", request_id))
        return {"id": "ORDER-REVIEW", "status": "PAYER_ACTION_REQUIRED", "links": [
            {"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-REVIEW"}]}

    async def capture_order(self, order_id, request_id):
        self.calls.append(("capture", request_id))
        if self.capture_error:
            raise self.capture_error
        return {"id": order_id, "status": "COMPLETED", "purchase_units": [{
            "payee": {"merchant_id": "REVIEW-MERCHANT"}, "payments": {"captures": [{
                "id": "CAPTURE-REVIEW", "status": "COMPLETED",
                "amount": {"currency_code": "USD", "value": "349.00"}}]}}]}

    async def refund_capture(self, capture_id, amount_cents, request_id):
        self.calls.append(("refund", request_id))
        if self.refund_error:
            raise self.refund_error
        return {"id": "REFUND-REVIEW", "status": "COMPLETED", "amount": {
            "currency_code": "USD", "value": f"{amount_cents // 100}.{amount_cents % 100:02d}"}}


def setup_purchase(client, monkeypatch):
    from mandate import payments_api, recovery
    provider = Provider()
    monkeypatch.setenv("PAYPAL_MERCHANT_ID", "REVIEW-MERCHANT")
    monkeypatch.setattr(payments_api, "configured_client", lambda: provider)
    monkeypatch.setattr(recovery, "configured_client", lambda: provider)
    grant = client.post("/api/mandates", json={
        "budget_cents": 50000, "per_transaction_cents": 50000,
        "allowed_categories": ["furniture"], "allowed_merchants": ["demo-merchant"],
        "constraints": {"width_cm": 160}, "instruction": "Buy a 160 cm desk"}).json()
    proposal = client.post("/api/proposals", json={
        "mandate_id": grant["id"], "purchase_intent_id": "review-intent",
        "items": [{"product_id": "desk-160", "quantity": 1}]}).json()
    assert proposal["decision"] == "APPROVE"
    return provider, grant, proposal


def checkout_and_capture(client, proposal):
    prefix = "/api/payments/" + proposal["payment_id"]
    assert client.post(prefix + "/checkout").status_code == 200
    response = client.post(prefix + "/capture")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CAPTURED"


def new_case(client, proposal):
    response = client.post("/api/cases", json={
        "payment_id": proposal["payment_id"], "cause": "seller_error",
        "evidence": "Test fixture: seller delivered a different desk.",
        "avoided_freight_cents": 2000, "resale_loss_cents": 3000})
    assert response.status_code == 200, response.text
    return response.json()


def test_review_capture_and_refund_account_once(client, database, monkeypatch):
    provider, grant, proposal = setup_purchase(client, monkeypatch)
    checkout_and_capture(client, proposal)
    assert client.post("/api/payments/" + proposal["payment_id"] + "/capture").status_code == 200
    case = new_case(client, proposal)
    for _ in range(2):
        response = client.post("/api/cases/" + case["id"] + "/accept", json={"offer_hash": case["offer_hash"]})
        assert response.status_code == 200 and response.json()["status"] == "REFUNDED"
    assert [kind for kind, _ in provider.calls] == ["create", "capture", "refund"]
    with database() as db:
        payment = db.get(Payment, proposal["payment_id"])
        mandate = db.get(Mandate, grant["id"])
        assert (payment.refunded_cents, payment.refund_reserved_cents) == (31410, 0)
        assert (mandate.spent_cents, mandate.reserved_cents) == (34900, 0)
    assert client.get("/api/ledger/verify").json()["valid"]


def test_review_unknown_capture_survives_retry_and_revocation(client, database, monkeypatch):
    provider, grant, proposal = setup_purchase(client, monkeypatch)
    prefix = "/api/payments/" + proposal["payment_id"]
    assert client.post(prefix + "/checkout").status_code == 200
    provider.capture_error = PayPalError("Test timeout", code="NETWORK_ERROR", ambiguous=True)
    assert client.post(prefix + "/capture").status_code == 502
    assert client.post(prefix + "/capture").status_code == 409
    revoked = client.post("/api/mandates/" + grant["id"] + "/revoke").json()
    assert revoked["reserved_cents"] == 34900 and revoked["spent_cents"] == 0
    with database() as db:
        assert db.get(Payment, proposal["payment_id"]).status == "UNKNOWN"
        operation = db.scalar(select(Operation).where(Operation.kind == "CAPTURE"))
        assert operation.status == "UNKNOWN" and operation.attempts == 1
    assert [kind for kind, _ in provider.calls] == ["create", "capture"]


def test_review_capture_can_retry_confirmed_no_charge_with_same_identity(client, database, monkeypatch):
    provider, grant, proposal = setup_purchase(client, monkeypatch)
    prefix = "/api/payments/" + proposal["payment_id"]
    assert client.post(prefix + "/checkout").status_code == 200
    # OAuth rejected before a capture request was sent. There is no charge ambiguity.
    provider.capture_error = PayPalError("Test OAuth rejection", code="PROVIDER_REJECTED", status_code=401)
    assert client.post(prefix + "/capture").status_code == 502
    with database() as db:
        mandate = db.get(Mandate, grant["id"])
        assert mandate.reserved_cents == 34900 and mandate.spent_cents == 0
    provider.capture_error = None
    retry = client.post(prefix + "/capture")
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "CAPTURED"
    capture_requests = [request_id for kind, request_id in provider.calls if kind == "capture"]
    assert len(capture_requests) == 2 and capture_requests[0] == capture_requests[1]
    with database() as db:
        mandate = db.get(Mandate, grant["id"])
        assert mandate.reserved_cents == 0 and mandate.spent_cents == 34900


def test_review_unknown_refund_reserves_balance_and_blocks_new_case(client, database, monkeypatch):
    provider, grant, proposal = setup_purchase(client, monkeypatch)
    checkout_and_capture(client, proposal)
    case = new_case(client, proposal)
    provider.refund_error = PayPalError("Test timeout", code="NETWORK_ERROR", ambiguous=True)
    path = "/api/cases/" + case["id"] + "/accept"
    assert client.post(path, json={"offer_hash": case["offer_hash"]}).status_code == 502
    assert client.post(path, json={"offer_hash": case["offer_hash"]}).json()["status"] == "UNKNOWN"
    assert client.post("/api/cases", json={
        "payment_id": proposal["payment_id"], "cause": "seller_error", "evidence": "Repeat",
        "avoided_freight_cents": 2000, "resale_loss_cents": 3000}).status_code == 409
    with database() as db:
        payment = db.get(Payment, proposal["payment_id"])
        assert (payment.refunded_cents, payment.refund_reserved_cents) == (0, 31410)
    assert [kind for kind, _ in provider.calls].count("refund") == 1


def test_review_grant_expiry_blocks_dispatch_without_calling_provider(client, database, monkeypatch):
    provider, grant, proposal = setup_purchase(client, monkeypatch)
    with database.begin() as db:
        db.get(Mandate, grant["id"]).expires_at = now() - timedelta(seconds=1)
    assert client.post("/api/payments/" + proposal["payment_id"] + "/checkout").status_code == 409
    assert provider.calls == []


def test_review_changed_offer_and_foreign_session_cannot_refund(client, database, monkeypatch):
    provider, grant, proposal = setup_purchase(client, monkeypatch)
    checkout_and_capture(client, proposal)
    case = new_case(client, proposal)
    path = "/api/cases/" + case["id"] + "/accept"
    with TestClient(app) as other:
        session = other.get("/api/session").json()
        other.headers["X-CSRF-Token"] = session["csrf_token"]
        assert other.post(path, json={"offer_hash": case["offer_hash"]}).status_code == 404
        assert other.get("/api/cases").json() == []
        assert other.post("/api/payments/" + proposal["payment_id"] + "/capture").status_code == 404
    with database.begin() as db:
        db.get(Case, case["id"]).offer_cents = 34900
    assert client.post(path, json={"offer_hash": case["offer_hash"]}).status_code == 409
    assert [kind for kind, _ in provider.calls] == ["create", "capture"]
