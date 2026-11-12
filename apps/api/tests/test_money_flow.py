import pytest
from sqlalchemy import select

from mandate.models import Case, Mandate, Operation, Payment, Proposal
from mandate.payments.paypal import PayPalError

from test_policy import grant, propose


class Provider:
    configured = True

    def __init__(self):
        self.calls = []
        self.fail_create = False
        self.fail_capture = False
        self.fail_refund = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def create_order(self, cart, request_id, return_url, cancel_url):
        self.calls.append(("create", request_id, cart))
        if self.fail_create:
            raise PayPalError("Lost response", code="NETWORK_ERROR", ambiguous=True)
        return {"id": "ORDER-1", "status": "PAYER_ACTION_REQUIRED", "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-1"}]}

    async def capture_order(self, order_id, request_id):
        self.calls.append(("capture", request_id, order_id))
        if self.fail_capture:
            raise PayPalError("Lost capture", code="NETWORK_ERROR", ambiguous=True)
        return {"id": order_id, "purchase_units": [{"payee": {"merchant_id": "MERCHANT-TEST"}, "payments": {"captures": [
            {"id": "CAPTURE-1", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "349.00"}}]}}]}

    async def refund_capture(self, capture_id, amount, request_id):
        self.calls.append(("refund", request_id, amount))
        if self.fail_refund:
            raise PayPalError("Lost refund", code="NETWORK_ERROR", ambiguous=True)
        return {"id": "REFUND-1", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": f"{amount // 100}.{amount % 100:02d}"}}


@pytest.fixture
def provider(monkeypatch):
    provider = Provider()
    monkeypatch.setattr("mandate.payments_api.configured_client", lambda: provider)
    monkeypatch.setattr("mandate.recovery.configured_client", lambda: provider)
    monkeypatch.setenv("PAYPAL_MERCHANT_ID", "MERCHANT-TEST")
    return provider


def purchase(client):
    mandate = grant(client)
    proposal = propose(client, mandate).json()
    return mandate, proposal, "/api/payments/" + proposal["payment_id"]


def captured(client):
    mandate, proposal, path = purchase(client)
    assert client.post(path + "/checkout").json()["status"] == "ORDER_CREATED"
    assert client.post(path + "/capture").json()["status"] == "CAPTURED"
    return mandate, proposal, path


def test_buyer_checkout_capture_and_human_refund(client, provider):
    mandate, proposal, path = captured(client)
    assert client.post(path + "/capture").json()["status"] == "CAPTURED"
    stored = client.get("/api/mandates/" + mandate["id"]).json()
    assert stored["spent_cents"] == 34900 and stored["reserved_cents"] == 0
    case = client.post("/api/cases", json={"payment_id": proposal["payment_id"], "cause": "seller_error",
        "evidence": "Explicit demo fixture: delivered a 120 cm desk instead of the purchased 160 cm desk.",
        "avoided_freight_cents": 5000, "resale_loss_cents": 1000}).json()
    assert case["offer_cents"] == 31410
    assert not any(call[0] == "refund" for call in provider.calls)
    accept_path = "/api/cases/" + case["id"] + "/accept"
    assert client.post(accept_path, json={"offer_hash": "0" * 64}).status_code == 409
    assert client.post(accept_path, json={"offer_hash": case["offer_hash"], "amount": 1}).status_code == 422
    assert client.post(accept_path, json={"offer_hash": case["offer_hash"]}).json()["status"] == "REFUNDED"
    assert client.post(accept_path, json={"offer_hash": case["offer_hash"]}).json()["status"] == "REFUNDED"
    assert [call[0] for call in provider.calls] == ["create", "capture", "refund"]
    assert client.get("/api/mandates/" + mandate["id"]).json()["spent_cents"] == 34900
    assert client.get("/api/payments").json()[0]["refunded_cents"] == 31410
    assert client.get("/api/ledger/verify").json()["valid"]


def test_lost_create_is_persisted_without_duplicate_dispatch(client, database, provider):
    mandate, proposal, path = purchase(client)
    provider.fail_create = True
    assert client.post(path + "/checkout").status_code == 502
    assert client.post(path + "/checkout").status_code == 409
    assert len(provider.calls) == 1
    with database() as db:
        payment = db.get(Payment, proposal["payment_id"])
        operation = db.scalar(select(Operation).where(Operation.payment_id == payment.id))
        assert operation.status == payment.status == "UNKNOWN"
        assert db.get(Mandate, mandate["id"]).reserved_cents == 34900
    revoked = client.post("/api/mandates/" + mandate["id"] + "/revoke").json()
    assert revoked["reserved_cents"] == 34900


def test_lost_capture_keeps_money_reserved(client, database, provider):
    mandate, proposal, path = purchase(client)
    assert client.post(path + "/checkout").status_code == 200
    provider.fail_capture = True
    assert client.post(path + "/capture").status_code == 502
    assert client.post(path + "/capture").status_code == 409
    with database() as db:
        stored = db.get(Mandate, mandate["id"])
        assert stored.spent_cents == 0 and stored.reserved_cents == 34900


def test_tampered_stored_cart_cannot_dispatch(client, database, provider):
    _, proposal, path = purchase(client)
    with database.begin() as db:
        stored = db.get(Proposal, proposal["id"])
        stored.cart = {**stored.cart, "total_cents": 1}
    assert client.post(path + "/checkout").status_code == 409
    assert provider.calls == []


def test_unknown_refund_retains_hold_and_prevents_double_accept(client, database, provider):
    _, proposal, _ = captured(client)
    case = client.post("/api/cases", json={"payment_id": proposal["payment_id"], "cause": "seller_error", "evidence": "Wrong delivery fixture",
        "avoided_freight_cents": 0, "resale_loss_cents": 0}).json()
    provider.fail_refund = True
    path, body = "/api/cases/" + case["id"] + "/accept", {"offer_hash": case["offer_hash"]}
    assert client.post(path, json=body).status_code == 502
    assert client.post(path, json=body).json()["status"] == "UNKNOWN"
    with database() as db:
        payment = db.get(Payment, proposal["payment_id"])
        assert payment.refund_reserved_cents == 31410 and payment.refunded_cents == 0
    assert len([call for call in provider.calls if call[0] == "refund"]) == 1


def test_unconfigured_checkout_remains_reserved(client, monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    _, proposal, path = purchase(client)
    assert client.post(path + "/checkout").status_code == 503
    assert client.get("/api/payments").json()[0]["status"] == "RESERVED"


def test_definitive_capture_failure_allows_same_key_retry(client, provider, monkeypatch):
    _, _, path = purchase(client)
    assert client.post(path + "/checkout").status_code == 200
    capture = provider.capture_order

    async def reject(order_id, request_id):
        provider.calls.append(("rejected_capture", request_id, order_id))
        raise PayPalError("Authentication unavailable before capture", code="AUTHENTICATION_FAILED", ambiguous=False)

    monkeypatch.setattr(provider, "capture_order", reject)
    assert client.post(path + "/capture").status_code == 502
    assert client.get("/api/payments").json()[0]["status"] == "ORDER_CREATED"
    monkeypatch.setattr(provider, "capture_order", capture)
    assert client.post(path + "/capture").json()["status"] == "CAPTURED"
    request_ids = [call[1] for call in provider.calls if call[0] in {"rejected_capture", "capture"}]
    assert len(request_ids) == 2 and request_ids[0] == request_ids[1]
