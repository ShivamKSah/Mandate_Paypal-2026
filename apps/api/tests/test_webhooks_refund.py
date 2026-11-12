"""[MOCKED] Tests for PAYMENT.CAPTURE.REFUNDED webhook verification/settlement and advisory cause suggestions."""
import json

import httpx
import pytest
from sqlalchemy import select

from mandate.models import AuditEvent, Case, Operation, Payment, WebhookEvent
from mandate.payments.paypal import PayPalError
from mandate.recovery import suggest_cause_advisory
from test_money_flow import Provider, captured, provider, purchase


def _install_webhook_provider(provider, monkeypatch, *, verified=True, refund_status="COMPLETED", refund_value="314.10"):
    provider.missing_environment = lambda **_: []

    async def verify(headers, event, *, raw_body=None):
        return {"verification_status": "SUCCESS" if verified else "FAILURE"}

    async def get_refund(refund_id):
        return {
            "id": refund_id,
            "status": refund_status,
            "amount": {"currency_code": "USD", "value": refund_value},
            "supplementary_data": {"related_ids": {"capture_id": "CAPTURE-1"}},
        }

    provider.verify_webhook = verify
    provider.get_refund = get_refund
    monkeypatch.setattr("mandate.webhooks.PayPalClient", lambda: provider)


def test_refund_webhook_verifies_get_refund_settles_pending_case_and_dedupes_mocked(client, database, provider, monkeypatch):
    """[MOCKED] PAYMENT.CAPTURE.REFUNDED verifies signature, confirms via GET refund, settles pending case, dedupes event ID, and audits."""
    _mandate, _proposal, path = captured(client)
    case = client.post("/api/cases", json={
        "payment_id": path.rsplit("/", 1)[-1],
        "cause": "seller_error",
        "evidence": "Damaged desk arrived",
        "avoided_freight_cents": 6000,
        "resale_loss_cents": 8725,
    }).json()

    # Simulate an UNKNOWN / REFUND_PENDING refund where PayPal processed it and notifies via webhook
    provider.fail_refund = True
    assert client.post(f"/api/cases/{case['id']}/accept", json={"offer_hash": case["offer_hash"]}).status_code == 502
    provider.fail_refund = False

    _install_webhook_provider(provider, monkeypatch, verified=True, refund_status="COMPLETED", refund_value="314.10")
    event = {
        "id": "WH-REF-1",
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "resource": {
            "id": "REFUND-WH-1",
            "status": "COMPLETED",
            "amount": {"currency_code": "USD", "value": "314.10"},
            "supplementary_data": {"related_ids": {"capture_id": "CAPTURE-1"}},
        },
    }
    first = client.post("/api/webhooks/paypal", json=event)
    assert first.status_code == 200
    assert first.json() == {"status": "processed"}

    # Duplicate event ID returns duplicate without double-refunding
    dup = client.post("/api/webhooks/paypal", json=event)
    assert dup.status_code == 200
    assert dup.json() == {"status": "duplicate"}

    # Different event ID for the same refund ID is also idempotent (never double-credits)
    second_event = {**event, "id": "WH-REF-1B"}
    assert client.post("/api/webhooks/paypal", json=second_event).json() == {"status": "processed"}

    with database() as db:
        pay = db.get(Payment, path.rsplit("/", 1)[-1])
        assert pay.refunded_cents == 31410
        assert pay.refund_reserved_cents == 0
        assert db.get(Case, case["id"]).status == "REFUNDED"
        assert db.get(WebhookEvent, "WH-REF-1").status == "PROCESSED"
        refund_events = list(db.scalars(select(AuditEvent).where(AuditEvent.event_type == "PAYMENT_REFUNDED")))
        assert len(refund_events) == 1

    assert client.get("/api/ledger/verify").json()["valid"] is True


def test_refund_webhook_external_refund_and_retry_on_unconfirmed_mocked(client, database, provider, monkeypatch):
    """[MOCKED] External refund settles via authoritative GET; unconfirmed GET returns 503 RETRY_REQUIRED."""
    _mandate, _proposal, path = captured(client)
    payment_id = path.rsplit("/", 1)[-1]

    # Authoritative GET says PENDING -> must NOT settle and must return 503
    _install_webhook_provider(provider, monkeypatch, verified=True, refund_status="PENDING", refund_value="100.00")
    pending_event = {
        "id": "WH-REF-2",
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "resource": {
            "id": "REFUND-EXT-2",
            "status": "COMPLETED",
            "amount": {"currency_code": "USD", "value": "100.00"},
            "supplementary_data": {"related_ids": {"capture_id": "CAPTURE-1"}},
        },
    }
    assert client.post("/api/webhooks/paypal", json=pending_event).status_code == 503
    with database() as db:
        assert db.get(Payment, payment_id).refunded_cents == 0
        assert db.get(WebhookEvent, "WH-REF-2").status == "RETRY_REQUIRED"

    # Now authoritative GET confirms COMPLETED -> settles external refund
    _install_webhook_provider(provider, monkeypatch, verified=True, refund_status="COMPLETED", refund_value="100.00")
    completed_event = {**pending_event, "id": "WH-REF-3"}
    assert client.post("/api/webhooks/paypal", json=completed_event).json() == {"status": "processed"}
    with database() as db:
        assert db.get(Payment, payment_id).refunded_cents == 10000
    assert client.get("/api/ledger/verify").json()["valid"] is True


@pytest.mark.asyncio
async def test_recovery_suggest_cause_llm_and_fallback_mocked(monkeypatch):
    """[MOCKED] Advisory root cause supports LLM JSON and deterministic fallback without touching policy bands."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    def ok(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "suggested_cause": "ambiguous_listing",
            "explanation": "Width was omitted from listing.",
        })}}]})

    res = await suggest_cause_advisory("Width was missing", "160 cm desk", transport=httpx.MockTransport(ok))
    assert res["suggested_cause"] == "ambiguous_listing"
    assert res["policy_band_pct"] == [40, 70]
    assert res["llm_fallback"] is False

    def fail(_request):
        return httpx.Response(503, text="down")

    fb = await suggest_cause_advisory("Item arrived broken and damaged", "160 cm desk", transport=httpx.MockTransport(fail))
    assert fb["suggested_cause"] == "seller_error"
    assert fb["policy_band_pct"] == [90, 100]
    assert fb["llm_fallback"] is True


def test_recovery_suggest_cause_endpoint_never_alters_human_band_or_accept(client, provider, monkeypatch):
    """Advisory endpoint requires captured payment + CSRF and never overrides human cause selection or BANDS."""
    _mandate, _proposal, path = captured(client)
    payment_id = path.rsplit("/", 1)[-1]
    monkeypatch.setenv("GROQ_API_KEY", "")

    sug = client.post("/api/cases/suggest-cause", json={
        "payment_id": payment_id,
        "evidence": "Item arrived broken",
    })
    assert sug.status_code == 200
    assert sug.json()["suggested_cause"] == "seller_error"
    assert sug.json()["llm_fallback"] is True

    # Human can still select vague_instruction (0-30%) regardless of suggestion
    case = client.post("/api/cases", json={
        "payment_id": payment_id,
        "cause": "vague_instruction",
        "evidence": "Item arrived broken",
        "avoided_freight_cents": 34900,
        "resale_loss_cents": 0,
    }).json()
    assert case["offer_cents"] == 34900 * 30 // 100
    assert case["status"] == "PROPOSED"
