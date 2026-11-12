"""[MOCKED] Hypothesis property-based tests for Mandate safety and accounting invariants (fixed seed=42)."""
from datetime import timedelta
from uuid import uuid4

from hypothesis import HealthCheck, given, seed, settings, strategies as st
import httpx
from sqlalchemy import select

from mandate.catalog import quote
from mandate.models import Case, Mandate, Operation, Payment, Proposal, Session, now
from mandate.payments.paypal import PayPalClient
from mandate.policy import evaluate
from mandate.proposals import submit
from mandate.schemas import ItemInput, ProposalInput
from mandate.settlement import settle_capture


@seed(42)
@settings(max_examples=25, deadline=None, derandomize=True, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    budget_cents=st.integers(min_value=5000, max_value=200000),
    quantities=st.lists(st.integers(min_value=1, max_value=4), min_size=1, max_size=6),
)
def test_spent_plus_reserved_never_exceeds_budget_property(database, budget_cents, quantities):
    """Property: Across any sequence of proposals and captures, spent + reserved <= budget always holds."""
    with database() as db, db.begin():
        owner = Session(csrf_token="prop-csrf")
        db.add(owner)
        db.flush()
        grant = Mandate(
            session_id=owner.id,
            status="ACTIVE",
            budget_cents=budget_cents,
            per_transaction_cents=budget_cents,
            allowed_categories=["electronics"],
            allowed_merchants=["demo-merchant"],
            constraints={},
            instruction="Property budget test",
            expires_at=now() + timedelta(hours=1),
            velocity_limit=50,
        )
        db.add(grant)
        db.flush()

        for qty in quantities:
            remaining_before = grant.budget_cents - grant.spent_cents - grant.reserved_cents
            cost = 8900 * qty
            proposal = submit(db, owner, ProposalInput(
                mandate_id=grant.id,
                purchase_intent_id=f"prop-{uuid4()}",
                items=[ItemInput(product_id="keyboard", quantity=qty)],
                currency="USD",
            ))
            if cost > remaining_before:
                assert proposal.decision == "DENY"
            assert grant.spent_cents + grant.reserved_cents <= grant.budget_cents
            if proposal.status == "APPROVED":
                payment = db.scalar(select(Payment).where(Payment.proposal_id == proposal.id))
                grant.reserved_cents -= payment.amount_cents
                grant.spent_cents += payment.amount_cents
                payment.status = "CAPTURED"
            assert grant.spent_cents + grant.reserved_cents <= grant.budget_cents


@seed(42)
@settings(max_examples=25, deadline=None, derandomize=True, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    over_budget_delta=st.integers(min_value=1, max_value=50000),
    product_id=st.sampled_from(["keyboard", "desk-160", "gift-card", "subscription"]),
)
def test_deny_verdict_never_calls_paypal_property(client, monkeypatch, over_budget_delta, product_id):
    """[MOCKED] Property: A DENY proposal never creates a payment row and never calls PayPal."""
    paypal_calls = 0

    def fail_paypal(*_args, **_kwargs):
        nonlocal paypal_calls
        paypal_calls += 1
        raise AssertionError("PayPal must never be called for a DENY verdict")

    with monkeypatch.context() as mp:
        mp.setattr("mandate.payments.paypal.PayPalClient.__init__", fail_paypal)
        grant = client.post("/api/mandates", json={
            "budget_cents": 5000,
            "per_transaction_cents": 5000,
            "allowed_categories": ["electronics"],
            "allowed_merchants": ["demo-merchant"],
            "constraints": {},
            "instruction": "Strict $50 cap",
            "expires_in_minutes": 60,
            "velocity_limit": 20,
        }).json()

        resp = client.post("/api/proposals", json={
            "mandate_id": grant["id"],
            "purchase_intent_id": f"prop-deny-{uuid4()}",
            "items": [{"product_id": product_id, "quantity": 1}],
            "currency": "USD",
            "claimed_total_cents": 5000 + over_budget_delta,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "DENY"
        assert data["payment_id"] is None
        assert client.post(f"/api/proposals/{data['id']}/approve", json={"cart_hash": data["cart_hash"]}).status_code == 409
        assert paypal_calls == 0


@seed(42)
@settings(max_examples=25, deadline=None, derandomize=True, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    freight=st.integers(min_value=0, max_value=60000),
    resale=st.integers(min_value=0, max_value=60000),
    cause=st.sampled_from(["seller_error", "ambiguous_listing", "agent_error", "vague_instruction"]),
    excess_cents=st.integers(min_value=1, max_value=10000),
)
def test_refund_never_exceeds_capture_property(client, monkeypatch, freight, resale, cause, excess_cents):
    """[MOCKED] Property: Refund offers and settled refunds never exceed the captured payment amount."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders":
            return httpx.Response(201, json={
                "id": f"PROPORD-{uuid4().hex[:10].upper()}",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=PROPORDER"}],
            })
        if request.url.path.endswith("/capture"):
            order_id = request.url.path.split("/")[4]
            return httpx.Response(201, json={
                "id": order_id,
                "status": "COMPLETED",
                "purchase_units": [{
                    "payee": {"merchant_id": "MERCHANT123"},
                    "payments": {"captures": [{"id": f"PROPCAP-{uuid4().hex[:10].upper()}", "status": "COMPLETED",
                                               "amount": {"currency_code": "USD", "value": "89.00"}}]},
                }],
            })
        if request.url.path.endswith("/refund"):
            import json as _json
            body = _json.loads(request.content.decode())
            return httpx.Response(201, json={"id": f"PROPREF-{uuid4().hex[:8].upper()}", "status": "COMPLETED", "amount": body["amount"]})
        raise AssertionError(f"Unexpected call {request.url.path}")

    def mock_client():
        return PayPalClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with monkeypatch.context() as mp:
        mp.setenv("PAYPAL_CLIENT_ID", "client-id")
        mp.setenv("PAYPAL_CLIENT_SECRET", "client-secret")
        mp.setenv("PAYPAL_MERCHANT_ID", "MERCHANT123")
        mp.setattr("mandate.payments_api.PUBLIC_BASE_URL", "https://example.test")
        mp.setattr("mandate.payments_api.configured_client", mock_client)
        mp.setattr("mandate.recovery.configured_client", mock_client)

        grant = client.post("/api/mandates", json={
            "budget_cents": 50000,
            "per_transaction_cents": 50000,
            "allowed_categories": ["electronics"],
            "allowed_merchants": ["demo-merchant"],
            "constraints": {},
            "instruction": "Mechanical keyboard",
            "expires_in_minutes": 60,
            "velocity_limit": 100,
        }).json()
        proposal = client.post("/api/proposals", json={
            "mandate_id": grant["id"],
            "purchase_intent_id": f"prop-ref-{uuid4()}",
            "items": [{"product_id": "keyboard", "quantity": 1}],
            "currency": "USD",
        }).json()
        pid = proposal["payment_id"]
        assert client.post(f"/api/payments/{pid}/checkout", json={}).status_code == 200
        assert client.post(f"/api/payments/{pid}/capture", json={}).status_code == 200

        case_resp = client.post("/api/cases", json={
            "payment_id": pid,
            "cause": cause,
            "evidence": "Property refund check",
            "avoided_freight_cents": freight,
            "resale_loss_cents": resale,
        })
        assert case_resp.status_code == 200
        case = case_resp.json()
        assert 0 <= case["offer_cents"] <= 8900

        acc = client.post(f"/api/cases/{case['id']}/accept", json={"offer_hash": case["offer_hash"]})
        assert acc.status_code == 200
        pay = next(p for p in client.get("/api/payments").json() if p["id"] == pid)
        assert pay["refunded_cents"] <= pay["amount_cents"]
        if pay["refunded_cents"] == pay["amount_cents"]:
            # Fully refunded captures cannot open another recovery case
            assert client.post("/api/cases", json={
                "payment_id": pid,
                "cause": cause,
                "evidence": f"Extra {excess_cents}",
                "avoided_freight_cents": excess_cents,
                "resale_loss_cents": 0,
            }).status_code == 409


@seed(42)
@settings(max_examples=25, deadline=None, derandomize=True, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(quantity=st.integers(min_value=1, max_value=3))
def test_same_cart_hash_never_captures_twice_property(database, quantity):
    """[MOCKED] Property: Re-settling or re-capturing the same payment/cart hash never captures or debits twice."""
    with database() as db, db.begin():
        owner = Session(csrf_token="prop-csrf")
        db.add(owner)
        db.flush()
        grant = Mandate(
            session_id=owner.id,
            status="ACTIVE",
            budget_cents=50000,
            per_transaction_cents=50000,
            allowed_categories=["electronics"],
            allowed_merchants=["demo-merchant"],
            constraints={},
            instruction="No double capture",
            expires_at=now() + timedelta(hours=1),
            velocity_limit=20,
        )
        db.add(grant)
        db.flush()
        proposal = submit(db, owner, ProposalInput(
            mandate_id=grant.id,
            purchase_intent_id=f"prop-once-{uuid4()}",
            items=[ItemInput(product_id="keyboard", quantity=quantity)],
            currency="USD",
        ))
        payment = db.scalar(select(Payment).where(Payment.proposal_id == proposal.id))
        payment.status = "ORDER_CREATED"
        payment.provider_order_id = f"ORDER-{uuid4().hex[:12]}"
        db.flush()

        expected_value = f"{payment.amount_cents // 100}.{payment.amount_cents % 100:02d}"
        import os
        old_merchant = os.environ.get("PAYPAL_MERCHANT_ID")
        os.environ["PAYPAL_MERCHANT_ID"] = "MERCHANT123"
        try:
            capture_payload = {
                "id": payment.provider_order_id,
                "purchase_units": [{
                    "payee": {"merchant_id": "MERCHANT123"},
                    "payments": {"captures": [{
                        "id": f"CAP-{uuid4().hex[:12]}",
                        "status": "COMPLETED",
                        "amount": {"currency_code": "USD", "value": expected_value},
                    }]},
                }],
            }
            assert settle_capture(db, payment.id, capture_payload) is True
            # Second settlement attempt (duplicate or conflicting capture ID) cannot double-charge
            assert settle_capture(db, payment.id, capture_payload) is True
            conflicting = {
                "id": payment.provider_order_id,
                "purchase_units": [{
                    "payee": {"merchant_id": "MERCHANT123"},
                    "payments": {"captures": [{
                        "id": "CAP-SECOND-ATTEMPT",
                        "status": "COMPLETED",
                        "amount": {"currency_code": "USD", "value": expected_value},
                    }]},
                }],
            }
            assert settle_capture(db, payment.id, conflicting) is False
            assert grant.spent_cents == payment.amount_cents
            assert grant.reserved_cents == 0
        finally:
            if old_merchant is None:
                os.environ.pop("PAYPAL_MERCHANT_ID", None)
            else:
                os.environ["PAYPAL_MERCHANT_ID"] = old_merchant

