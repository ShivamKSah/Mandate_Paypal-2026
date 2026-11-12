"""[MOCKED] Offline tests for PayPal vault grant, Fernet token storage, autonomous vault-charge, and reconciliation."""
import asyncio
import json
import logging
import socket

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from mandate.models import AuditEvent, Mandate, Operation, Payment
from mandate.payments.paypal import PayPalClient
from mandate.reconciliation import claim_operation, reconcile_operation
from mandate.vault import decrypt_vault_token, mask_token


def _create_grant(client):
    response = client.post("/api/mandates", json={
        "budget_cents": 50000,
        "per_transaction_cents": 50000,
        "allowed_categories": ["furniture"],
        "allowed_merchants": ["demo-merchant"],
        "constraints": {"width_cm": 160},
        "instruction": "160 cm standing desk",
        "expires_in_minutes": 60,
        "velocity_limit": 5,
    })
    assert response.status_code == 200
    return response.json()


def _create_approved_proposal(client, mandate_id, intent="vault-intent-1"):
    response = client.post("/api/proposals", json={
        "mandate_id": mandate_id,
        "purchase_intent_id": intent,
        "items": [{"product_id": "desk-160", "quantity": 1}],
        "currency": "USD",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "APPROVED"
    return data


def _vault_env(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("PAYPAL_MERCHANT_ID", "MERCHANT123")
    monkeypatch.setenv("VAULT_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr("mandate.resources.PUBLIC_BASE_URL", "https://example.test")


def _install_mock_paypal(monkeypatch, handler):
    def factory():
        return PayPalClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    monkeypatch.setattr("mandate.resources.configured_vault_client", factory)
    monkeypatch.setattr("mandate.payments_api.configured_client", factory)
    return factory


def test_offline_socket_guard_blocks_external_hosts():
    with pytest.raises(Exception):
        socket.create_connection(("93.184.216.34", 80), timeout=1)


def test_vault_grant_init_and_complete_with_auto_refund_mocked(client, database, monkeypatch, caplog):
    """[MOCKED] Grant init creates $1 setup order; complete extracts/encrypts vault token, refunds $1, and masks audit logs."""
    _vault_env(monkeypatch)
    caplog.set_level(logging.DEBUG)
    raw_vault_id = "VAULT-SECRET-TOKEN-998877"
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        body = json.loads(request.content.decode()) if request.content else {}
        seen_requests.append((request.method, request.url.path, dict(request.headers), body))
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            vault_attrs = body["payment_source"]["paypal"]["attributes"]["vault"]
            assert vault_attrs == {"store_in_vault": "ON_SUCCESS", "usage_type": "MERCHANT", "customer_type": "CONSUMER"}
            assert body["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "1.00"}
            return httpx.Response(201, json={
                "id": "GRANTORDER1234567",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=GRANTORDER1234567"}],
            })
        if request.method == "POST" and request.url.path == "/v2/checkout/orders/GRANTORDER1234567/capture":
            return httpx.Response(201, json={
                "id": "GRANTORDER1234567",
                "status": "COMPLETED",
                "payment_source": {"paypal": {"attributes": {"vault": {"id": raw_vault_id, "status": "VAULTED"}}}},
                "purchase_units": [{"payments": {"captures": [{"id": "GRANTCAP123456789", "status": "COMPLETED"}]}}],
            })
        if request.method == "POST" and request.url.path == "/v2/payments/captures/GRANTCAP123456789/refund":
            assert body["amount"] == {"currency_code": "USD", "value": "1.00"}
            return httpx.Response(201, json={"id": "GRANTREF123456789", "status": "COMPLETED"})
        raise AssertionError(f"Unexpected PayPal call: {request.method} {request.url.path}")

    _install_mock_paypal(monkeypatch, handler)
    grant = _create_grant(client)

    init_res = client.post(f"/api/mandates/{grant['id']}/grant/init", json={})
    assert init_res.status_code == 200
    init_body = init_res.json()
    assert init_body["order_id"] == "GRANTORDER1234567"
    assert init_body["approval_url"].startswith("https://www.sandbox.paypal.com/")
    assert init_body["mandate"]["vault_status"] == "PENDING"
    assert raw_vault_id not in init_res.text

    comp_res = client.post(f"/api/mandates/{grant['id']}/grant/complete", json={})
    assert comp_res.status_code == 200
    comp_body = comp_res.json()
    assert comp_body["vault_status"] == "GRANTED"
    assert comp_body["refund_status"] == "COMPLETED"
    assert comp_body["masked_vault_id"] == mask_token(raw_vault_id)
    assert raw_vault_id not in comp_res.text
    assert "vault_token_ref" not in comp_body["mandate"]

    # Stable PayPal-Request-Id sent on refund
    refund_calls = [req for req in seen_requests if req[1].endswith("/refund")]
    assert len(refund_calls) == 1
    assert refund_calls[0][2]["paypal-request-id"].startswith("gr-")

    with database() as db:
        row = db.get(Mandate, grant["id"])
        assert row.vault_status == "GRANTED"
        assert row.vault_token_ref != raw_vault_id
        assert decrypt_vault_token(row.vault_token_ref) == raw_vault_id
        events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.sequence)))
        types = [ev.event_type for ev in events]
        assert "GRANT_INITIATED" in types and "GRANT_COMPLETED" in types
        for ev in events:
            assert raw_vault_id not in json.dumps(ev.details)

    assert raw_vault_id not in caplog.text
    assert raw_vault_id not in json.dumps(client.get(f"/api/mandates/{grant['id']}").json())


def test_vault_grant_complete_polls_missing_then_succeeds_mocked(client, database, monkeypatch):
    """[MOCKED] If capture omits vault ID initially, complete polls GET order with backoff and succeeds."""
    _vault_env(monkeypatch)
    raw_vault_id = "VAULT-POLLED-554433"
    get_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_calls
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            return httpx.Response(201, json={
                "id": "POLLORDER12345678",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=POLLORDER12345678"}],
            })
        if request.method == "POST" and request.url.path == "/v2/checkout/orders/POLLORDER12345678/capture":
            return httpx.Response(201, json={
                "id": "POLLORDER12345678",
                "status": "COMPLETED",
                "payment_source": {"paypal": {"attributes": {"vault": {"status": "PENDING"}}}},
                "purchase_units": [{"payments": {"captures": [{"id": "POLLCAP1234567890", "status": "COMPLETED"}]}}],
            })
        if request.method == "GET" and request.url.path == "/v2/checkout/orders/POLLORDER12345678":
            get_calls += 1
            if get_calls == 1:
                return httpx.Response(200, json={"id": "POLLORDER12345678", "status": "COMPLETED"})
            return httpx.Response(200, json={
                "id": "POLLORDER12345678",
                "status": "COMPLETED",
                "payment_source": {"paypal": {"attributes": {"vault": {"id": raw_vault_id, "status": "VAULTED"}}}},
            })
        if request.method == "POST" and request.url.path == "/v2/payments/captures/POLLCAP1234567890/refund":
            return httpx.Response(201, json={"id": "POLLREF1234567890", "status": "COMPLETED"})
        raise AssertionError(f"Unexpected call: {request.method} {request.url.path}")

    _install_mock_paypal(monkeypatch, handler)
    grant = _create_grant(client)
    assert client.post(f"/api/mandates/{grant['id']}/grant/init", json={}).status_code == 200
    comp = client.post(f"/api/mandates/{grant['id']}/grant/complete", json={})
    assert comp.status_code == 200
    assert get_calls == 2
    assert comp.json()["vault_status"] == "GRANTED"


def test_vault_charge_success_and_never_leaks_token_mocked(client, database, monkeypatch, caplog):
    """[MOCKED] Vault charge revalidates dispatch_guard, commits outbox before calling PayPal, settles capture, and masks token."""
    _vault_env(monkeypatch)
    caplog.set_level(logging.DEBUG)
    raw_vault_id = "VAULT-CHARGE-SECRET-1122"
    seen_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        body = json.loads(request.content.decode()) if request.content else {}
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            if "vault_id" in body.get("payment_source", {}).get("paypal", {}):
                seen_payloads.append((dict(request.headers), body))
                assert body["intent"] == "CAPTURE"
                assert body["payment_source"]["paypal"]["vault_id"] == raw_vault_id
                assert body["purchase_units"][0]["payee"]["merchant_id"] == "MERCHANT123"
                assert body["purchase_units"][0]["amount"]["value"] == "349.00"
                return httpx.Response(201, json={
                    "id": "VAULTORDER1234567",
                    "status": "COMPLETED",
                    "purchase_units": [{
                        "payee": {"merchant_id": "MERCHANT123"},
                        "payments": {"captures": [{
                            "id": "VAULTCAP123456789",
                            "status": "COMPLETED",
                            "amount": {"currency_code": "USD", "value": "349.00"},
                        }]},
                    }],
                })
            return httpx.Response(201, json={
                "id": "SETUPORDER1234567",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=SETUPORDER1234567"}],
            })
        if request.method == "POST" and request.url.path == "/v2/checkout/orders/SETUPORDER1234567/capture":
            return httpx.Response(201, json={
                "id": "SETUPORDER1234567",
                "status": "COMPLETED",
                "payment_source": {"paypal": {"attributes": {"vault": {"id": raw_vault_id, "status": "VAULTED"}}}},
                "purchase_units": [{"payments": {"captures": [{"id": "SETUPCAP123456789", "status": "COMPLETED"}]}}],
            })
        if request.method == "POST" and request.url.path == "/v2/payments/captures/SETUPCAP123456789/refund":
            return httpx.Response(201, json={"id": "SETUPREF123456789", "status": "COMPLETED"})
        raise AssertionError(f"Unexpected call: {request.method} {request.url.path}")

    _install_mock_paypal(monkeypatch, handler)
    grant = _create_grant(client)
    assert client.post(f"/api/mandates/{grant['id']}/grant/init", json={}).status_code == 200
    assert client.post(f"/api/mandates/{grant['id']}/grant/complete", json={}).status_code == 200

    proposal = _create_approved_proposal(client, grant["id"])
    charge = client.post(f"/api/payments/{proposal['payment_id']}/vault-charge", json={})
    assert charge.status_code == 200
    data = charge.json()
    assert data["status"] == "CAPTURED"
    assert data["provider_order_id"] == "VAULTORDER1234567"
    assert data["provider_capture_id"] == "VAULTCAP123456789"
    assert raw_vault_id not in charge.text

    updated_grant = client.get(f"/api/mandates/{grant['id']}").json()
    assert updated_grant["spent_cents"] == 34900
    assert updated_grant["reserved_cents"] == 0
    assert updated_grant["available_cents"] == 15100

    with database() as db:
        op = db.scalar(select(Operation).where(Operation.payment_id == proposal["payment_id"], Operation.kind == "CREATE"))
        assert op.status == "COMPLETED"
        assert raw_vault_id not in json.dumps(op.request_payload)
        assert len(seen_payloads) == 1
        assert seen_payloads[0][0]["paypal-request-id"] == op.request_id

    assert raw_vault_id not in caplog.text


def test_vault_charge_timeout_keeps_unknown_and_reconciles_mocked(client, database, monkeypatch):
    """[MOCKED] Timeout during vault-charge preserves UNKNOWN + reservation and reconciles via PayPal retry/GET."""
    _vault_env(monkeypatch)
    raw_vault_id = "VAULT-TIMEOUT-7788"
    phase = {"timed_out": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        body = json.loads(request.content.decode()) if request.content else {}
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            if "vault_id" in body.get("payment_source", {}).get("paypal", {}):
                if not phase["timed_out"]:
                    phase["timed_out"] = True
                    raise httpx.ReadTimeout("Simulated PayPal timeout", request=request)
                return httpx.Response(201, json={
                    "id": "RECONORDER1234567",
                    "status": "COMPLETED",
                    "purchase_units": [{
                        "payee": {"merchant_id": "MERCHANT123"},
                        "payments": {"captures": [{
                            "id": "RECONCAP123456789",
                            "status": "COMPLETED",
                            "amount": {"currency_code": "USD", "value": "349.00"},
                        }]},
                    }],
                })
            return httpx.Response(201, json={
                "id": "TOGRANT1234567890",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=TOGRANT1234567890"}],
            })
        if request.method == "POST" and request.url.path == "/v2/checkout/orders/TOGRANT1234567890/capture":
            return httpx.Response(201, json={
                "id": "TOGRANT1234567890",
                "status": "COMPLETED",
                "payment_source": {"paypal": {"attributes": {"vault": {"id": raw_vault_id, "status": "VAULTED"}}}},
                "purchase_units": [{"payments": {"captures": [{"id": "TOCAP123456789012", "status": "COMPLETED"}]}}],
            })
        if request.method == "POST" and request.url.path == "/v2/payments/captures/TOCAP123456789012/refund":
            return httpx.Response(201, json={"id": "TOREF123456789012", "status": "COMPLETED"})
        raise AssertionError(f"Unexpected call: {request.method} {request.url.path}")

    factory = _install_mock_paypal(monkeypatch, handler)
    monkeypatch.setattr("mandate.reconciliation.SessionLocal", database)

    grant = _create_grant(client)
    assert client.post(f"/api/mandates/{grant['id']}/grant/init", json={}).status_code == 200
    assert client.post(f"/api/mandates/{grant['id']}/grant/complete", json={}).status_code == 200
    proposal = _create_approved_proposal(client, grant["id"], intent="vault-timeout")

    res = client.post(f"/api/payments/{proposal['payment_id']}/vault-charge", json={})
    assert res.status_code == 502

    # Reservation held while UNKNOWN
    after_timeout_grant = client.get(f"/api/mandates/{grant['id']}").json()
    assert after_timeout_grant["reserved_cents"] == 34900
    assert after_timeout_grant["spent_cents"] == 0
    payment = next(p for p in client.get("/api/payments").json() if p["id"] == proposal["payment_id"])
    assert payment["status"] == "UNKNOWN"

    # Reconcile worker resolves UNKNOWN operation
    with database() as db:
        op = db.scalar(select(Operation).where(Operation.payment_id == proposal["payment_id"], Operation.kind == "CREATE"))
        assert op.status == "UNKNOWN"
        op_id = op.id

    async def run_reconcile():
        async with factory() as pp:
            return await reconcile_operation(pp, op_id)

    assert asyncio.run(run_reconcile()) is True

    final_grant = client.get(f"/api/mandates/{grant['id']}").json()
    assert final_grant["reserved_cents"] == 0
    assert final_grant["spent_cents"] == 34900
    assert client.get("/api/ledger/verify").json()["valid"] is True


def test_revoked_mandate_clears_vault_token_and_refuses_charge_mocked(client, database, monkeypatch):
    """[MOCKED] Revoking a vaulted mandate wipes its encrypted token, marks vault_status REVOKED, and refuses charges."""
    _vault_env(monkeypatch)
    charge_attempted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal charge_attempted
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        body = json.loads(request.content.decode()) if request.content else {}
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            if "vault_id" in body.get("payment_source", {}).get("paypal", {}):
                charge_attempted = True
            return httpx.Response(201, json={
                "id": "REVGRANT123456789",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=REVGRANT123456789"}],
            })
        if request.method == "POST" and request.url.path == "/v2/checkout/orders/REVGRANT123456789/capture":
            return httpx.Response(201, json={
                "id": "REVGRANT123456789",
                "status": "COMPLETED",
                "payment_source": {"paypal": {"attributes": {"vault": {"id": "VAULT-TO-REVOKE", "status": "VAULTED"}}}},
                "purchase_units": [{"payments": {"captures": [{"id": "REVCAP1234567890", "status": "COMPLETED"}]}}],
            })
        if request.method == "POST" and request.url.path == "/v2/payments/captures/REVCAP1234567890/refund":
            return httpx.Response(201, json={"id": "REVREF1234567890", "status": "COMPLETED"})
        raise AssertionError(f"Unexpected call: {request.method} {request.url.path}")

    _install_mock_paypal(monkeypatch, handler)
    grant = _create_grant(client)
    assert client.post(f"/api/mandates/{grant['id']}/grant/init", json={}).status_code == 200
    assert client.post(f"/api/mandates/{grant['id']}/grant/complete", json={}).status_code == 200
    proposal = _create_approved_proposal(client, grant["id"], intent="vault-revoke")

    revoked = client.post(f"/api/mandates/{grant['id']}/revoke", json={}).json()
    assert revoked["status"] == "REVOKED"
    assert revoked["vault_status"] == "REVOKED"

    with database() as db:
        row = db.get(Mandate, grant["id"])
        assert row.vault_token_ref is None

    refused = client.post(f"/api/payments/{proposal['payment_id']}/vault-charge", json={})
    assert refused.status_code == 409
    assert charge_attempted is False


def test_vault_grant_requires_encryption_key_and_csrf_ownership_mocked(client, monkeypatch):
    """[MOCKED] Missing VAULT_ENCRYPTION_KEY fails closed with 503; cross-session and missing CSRF are rejected."""
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("PAYPAL_MERCHANT_ID", "MERCHANT123")
    monkeypatch.setenv("VAULT_ENCRYPTION_KEY", "")

    grant = _create_grant(client)
    assert client.post(f"/api/mandates/{grant['id']}/grant/init", json={}).status_code == 503
    assert client.post(f"/api/mandates/{grant['id']}/grant/init", headers={"X-CSRF-Token": "bad"}, json={}).status_code == 403

    from mandate.main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as other:
        other.headers["X-CSRF-Token"] = other.get("/api/session").json()["csrf_token"]
        assert other.post(f"/api/mandates/{grant['id']}/grant/init", json={}).status_code == 404

