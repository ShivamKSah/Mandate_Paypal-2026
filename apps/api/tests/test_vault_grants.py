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
    monkeypatch.setattr("mandate.payments_api.PUBLIC_BASE_URL", "https://example.test")


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
            assert body["purchase_units"][0]["payee"] == {"merchant_id": "MERCHANT123"}
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


def test_grant_complete_order_not_approved_audits_and_redacts_mocked(client, database, monkeypatch):
    """[MOCKED] ORDER_NOT_APPROVED on grant/complete keeps 502 with redacted PayPal metadata and GRANT_FAILED reason."""
    _vault_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            return httpx.Response(201, json={
                "id": "UNAPPROVEDORDER12",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=UNAPPROVEDORDER12"}],
            })
        if request.method == "POST" and request.url.path == "/v2/checkout/orders/UNAPPROVEDORDER12/capture":
            return httpx.Response(422, json={
                "name": "UNPROCESSABLE_ENTITY",
                "debug_id": "DBG-NOTAPP-001",
                "message": "secret payer session details",
                "details": [{"issue": "ORDER_NOT_APPROVED", "description": "Payer has not yet approved the Order"}],
            })
        raise AssertionError(f"Unexpected call: {request.method} {request.url.path}")

    _install_mock_paypal(monkeypatch, handler)
    grant = _create_grant(client)
    assert client.post(f"/api/mandates/{grant['id']}/grant/init", json={}).status_code == 200

    res = client.post(f"/api/mandates/{grant['id']}/grant/complete", json={})
    assert res.status_code == 502
    detail = res.json()["detail"]
    assert "status=422" in detail
    assert "name=UNPROCESSABLE_ENTITY" in detail
    assert "issues=ORDER_NOT_APPROVED" in detail
    assert "debug_id=DBG-NOTAPP-001" in detail
    assert "secret payer session details" not in res.text

    with database() as db:
        row = db.get(Mandate, grant["id"])
        assert row.vault_status == "FAILED"
        failed = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "GRANT_FAILED")).all()[-1]
        assert failed.details["phase"] == "capture"
        assert failed.details["reason"] == "ORDER_NOT_APPROVED"
        assert failed.details["provider_status"] == 422
        assert failed.details["provider_error"] == "UNPROCESSABLE_ENTITY"
        assert failed.details["provider_issues"] == ["ORDER_NOT_APPROVED"]
        assert failed.details["provider_debug_id"] == "DBG-NOTAPP-001"


def test_grant_complete_and_vault_charge_payee_mismatch_mocked(client, database, monkeypatch):
    """[MOCKED] Payee merchant mismatch rejects grant/complete and retains UNKNOWN reservation on vault-charge."""
    _vault_env(monkeypatch)
    raw_vault_id = "VAULT-PAYEE-9988"

    def grant_mismatch_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            return httpx.Response(201, json={
                "id": "PAYEEMISMATCH1234",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=PAYEEMISMATCH1234"}],
            })
        if request.method == "POST" and request.url.path == "/v2/checkout/orders/PAYEEMISMATCH1234/capture":
            return httpx.Response(201, json={
                "id": "PAYEEMISMATCH1234",
                "status": "COMPLETED",
                "payment_source": {"paypal": {"attributes": {"vault": {"id": raw_vault_id, "status": "VAULTED"}}}},
                "purchase_units": [{"payee": {"merchant_id": "ATTACKER999"}, "payments": {"captures": [{"id": "CAP999", "status": "COMPLETED"}]}}],
            })
        raise AssertionError(f"Unexpected call: {request.method} {request.url.path}")

    _install_mock_paypal(monkeypatch, grant_mismatch_handler)
    g1 = _create_grant(client)
    assert client.post(f"/api/mandates/{g1['id']}/grant/init", json={}).status_code == 200
    bad_comp = client.post(f"/api/mandates/{g1['id']}/grant/complete", json={})
    assert bad_comp.status_code == 502
    assert "PAYEE_MISMATCH" in bad_comp.json()["detail"]
    assert raw_vault_id not in bad_comp.text
    with database() as db:
        row = db.get(Mandate, g1["id"])
        assert row.vault_status == "FAILED"
        assert row.vault_token_ref is None
        ev = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "GRANT_FAILED", AuditEvent.entity_id == g1["id"])).first()
        assert ev.details["reason"] == "payee_mismatch"
        assert ev.details["code"] == "PAYEE_MISMATCH"

    def charge_mismatch_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        body = json.loads(request.content.decode()) if request.content else {}
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            if "vault_id" in body.get("payment_source", {}).get("paypal", {}):
                return httpx.Response(201, json={
                    "id": "VCMISMATCH1234567",
                    "status": "COMPLETED",
                    "purchase_units": [{
                        "payee": {"merchant_id": "WRONGMERCHANT"},
                        "payments": {"captures": [{"id": "VCCAP999", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "349.00"}}]},
                    }],
                })
            return httpx.Response(201, json={
                "id": "GOODGRANT12345678",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=GOODGRANT12345678"}],
            })
        if request.method == "POST" and request.url.path == "/v2/checkout/orders/GOODGRANT12345678/capture":
            return httpx.Response(201, json={
                "id": "GOODGRANT12345678",
                "status": "COMPLETED",
                "payment_source": {"paypal": {"attributes": {"vault": {"id": raw_vault_id, "status": "VAULTED"}}}},
                "purchase_units": [{"payee": {"merchant_id": "MERCHANT123"}, "payments": {"captures": [{"id": "GOODCAP1", "status": "COMPLETED"}]}}],
            })
        if request.method == "POST" and request.url.path == "/v2/payments/captures/GOODCAP1/refund":
            return httpx.Response(201, json={"id": "GOODREF1", "status": "COMPLETED"})
        raise AssertionError(f"Unexpected call: {request.method} {request.url.path}")

    _install_mock_paypal(monkeypatch, charge_mismatch_handler)
    g2 = _create_grant(client)
    assert client.post(f"/api/mandates/{g2['id']}/grant/init", json={}).status_code == 200
    assert client.post(f"/api/mandates/{g2['id']}/grant/complete", json={}).status_code == 200
    proposal = _create_approved_proposal(client, g2["id"], intent="vc-payee-mismatch")

    vc_res = client.post(f"/api/payments/{proposal['payment_id']}/vault-charge", json={})
    assert vc_res.status_code == 502
    assert "PAYEE_MISMATCH" in vc_res.json()["detail"]
    assert raw_vault_id not in vc_res.text

    updated = client.get(f"/api/mandates/{g2['id']}").json()
    assert updated["reserved_cents"] == 34900
    assert updated["spent_cents"] == 0
    payment = next(p for p in client.get("/api/payments").json() if p["id"] == proposal["payment_id"])
    assert payment["status"] == "UNKNOWN"


def test_grant_complete_missing_vault_id_after_poll_audits_reason_mocked(client, database, monkeypatch):
    """[MOCKED] Missing vault ID after GET polls returns 409 and records specific GRANT_FAILED vault_lookup reason."""
    _vault_env(monkeypatch)
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            return httpx.Response(201, json={
                "id": "NOVALUTIDORDER123",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=NOVALUTIDORDER123"}],
            })
        if request.method == "POST" and request.url.path == "/v2/checkout/orders/NOVALUTIDORDER123/capture":
            return httpx.Response(201, json={
                "id": "NOVALUTIDORDER123",
                "status": "COMPLETED",
                "purchase_units": [{"payee": {"merchant_id": "MERCHANT123"}, "payments": {"captures": [{"id": "NOCAP1", "status": "COMPLETED"}]}}],
            })
        if request.method == "GET" and request.url.path == "/v2/checkout/orders/NOVALUTIDORDER123":
            poll_count += 1
            return httpx.Response(200, json={"id": "NOVALUTIDORDER123", "status": "COMPLETED"})
        raise AssertionError(f"Unexpected call: {request.method} {request.url.path}")

    _install_mock_paypal(monkeypatch, handler)
    grant = _create_grant(client)
    assert client.post(f"/api/mandates/{grant['id']}/grant/init", json={}).status_code == 200
    comp = client.post(f"/api/mandates/{grant['id']}/grant/complete", json={})
    assert comp.status_code == 409
    assert poll_count == 3
    assert "vault_token_missing" in comp.json()["detail"]

    with database() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "GRANT_FAILED", AuditEvent.entity_id == grant["id"])).first()
        assert ev.details["phase"] == "vault_lookup"
        assert ev.details["reason"] == "vault_token_missing"
        assert ev.details["vault_state"] == "MISSING"
        assert ev.details["poll_attempts"] == 3


def test_paypal_500_returns_and_audits_redacted_details_across_endpoints_mocked(client, database, monkeypatch):
    """[MOCKED] PayPal 500 across grant/init, grant/complete, checkout, capture, and vault-charge preserves status + redacted metadata."""
    _vault_env(monkeypatch)
    raw_vault_id = "VAULT-500-SECRET-123"
    mode = {"fail_500": True, "allow_checkout_order": False}

    def err_500():
        return httpx.Response(500, json={
            "name": "INTERNAL_SERVER_ERROR",
            "debug_id": "DBG-500-TRACE",
            "message": "top-secret-upstream-stack-client-secret",
            "details": [{"issue": "INTERNAL_ERROR"}],
        })

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        body = json.loads(request.content.decode()) if request.content else {}
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            if mode["fail_500"]:
                return err_500()
            if "vault_id" in body.get("payment_source", {}).get("paypal", {}):
                return err_500()
            order_id = "CHK500ORDER123456" if mode["allow_checkout_order"] else "GRANT500ORDER1234"
            return httpx.Response(201, json={
                "id": order_id,
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "approve", "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}"}],
            })
        if request.method == "POST" and request.url.path.endswith("/capture"):
            if mode["fail_500"]:
                return err_500()
            return httpx.Response(201, json={
                "id": "GRANT500ORDER1234",
                "status": "COMPLETED",
                "payment_source": {"paypal": {"attributes": {"vault": {"id": raw_vault_id, "status": "VAULTED"}}}},
                "purchase_units": [{"payments": {"captures": [{"id": "GRANT500CAP1", "status": "COMPLETED"}]}}],
            })
        if request.method == "POST" and request.url.path == "/v2/payments/captures/GRANT500CAP1/refund":
            return httpx.Response(201, json={"id": "GRANT500REF1", "status": "COMPLETED"})
        raise AssertionError(f"Unexpected call: {request.method} {request.url.path}")

    _install_mock_paypal(monkeypatch, handler)
    grant = _create_grant(client)

    # 1. grant/init 500
    r_init = client.post(f"/api/mandates/{grant['id']}/grant/init", json={})
    assert r_init.status_code == 502
    for marker in ("status=500", "name=INTERNAL_SERVER_ERROR", "issues=INTERNAL_ERROR", "debug_id=DBG-500-TRACE"):
        assert marker in r_init.json()["detail"]
    assert "top-secret-upstream" not in r_init.text

    # 2. grant/init succeeds, grant/complete hits 500
    mode["fail_500"] = False
    assert client.post(f"/api/mandates/{grant['id']}/grant/init", json={}).status_code == 200
    mode["fail_500"] = True
    r_comp = client.post(f"/api/mandates/{grant['id']}/grant/complete", json={})
    assert r_comp.status_code == 502
    assert "debug_id=DBG-500-TRACE" in r_comp.json()["detail"]
    assert "name=INTERNAL_SERVER_ERROR" in r_comp.json()["detail"]
    assert "top-secret-upstream" not in r_comp.text

    # 3. checkout hits 500
    p_chk = _create_approved_proposal(client, grant["id"], intent="chk-500")
    r_chk = client.post(f"/api/payments/{p_chk['payment_id']}/checkout")
    assert r_chk.status_code == 502
    assert "debug_id=DBG-500-TRACE" in r_chk.json()["detail"]

    # 4. capture hits 500
    mode["fail_500"] = False
    mode["allow_checkout_order"] = True
    g_cap = _create_grant(client)
    p_cap = _create_approved_proposal(client, g_cap["id"], intent="cap-500")
    assert client.post(f"/api/payments/{p_cap['payment_id']}/checkout").status_code == 200
    mode["fail_500"] = True
    r_cap = client.post(f"/api/payments/{p_cap['payment_id']}/capture")
    assert r_cap.status_code == 502
    assert "debug_id=DBG-500-TRACE" in r_cap.json()["detail"]

    # 5. grant completes, vault-charge hits 500
    mode["fail_500"] = False
    mode["allow_checkout_order"] = False
    g_vc = _create_grant(client)
    assert client.post(f"/api/mandates/{g_vc['id']}/grant/init", json={}).status_code == 200
    assert client.post(f"/api/mandates/{g_vc['id']}/grant/complete", json={}).status_code == 200
    p_vc = _create_approved_proposal(client, g_vc["id"], intent="vc-500")
    r_vc = client.post(f"/api/payments/{p_vc['payment_id']}/vault-charge")
    assert r_vc.status_code == 502
    assert "status=500" in r_vc.json()["detail"]
    assert "name=INTERNAL_SERVER_ERROR" in r_vc.json()["detail"]
    assert "issues=INTERNAL_ERROR" in r_vc.json()["detail"]
    assert "debug_id=DBG-500-TRACE" in r_vc.json()["detail"]
    assert raw_vault_id not in r_vc.text

    with database() as db:
        grant_failures = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "GRANT_FAILED")).all()
        assert len(grant_failures) == 2
        assert {ev.details["phase"] for ev in grant_failures} == {"init", "capture"}
        for ev in grant_failures:
            assert ev.details["provider_status"] == 500
            assert ev.details["provider_error"] == "INTERNAL_SERVER_ERROR"
            assert ev.details["provider_issues"] == ["INTERNAL_ERROR"]
            assert ev.details["provider_debug_id"] == "DBG-500-TRACE"
        op_failures = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "PROVIDER_OPERATION_UNRESOLVED")).all()
        assert len(op_failures) == 3
        for ev in op_failures:
            assert ev.details["provider_status"] == 500
            assert ev.details["provider_error"] == "INTERNAL_SERVER_ERROR"
            assert ev.details["provider_issues"] == ["INTERNAL_ERROR"]
            assert ev.details["provider_debug_id"] == "DBG-500-TRACE"
            assert raw_vault_id not in json.dumps(ev.details)


def test_live_vault_check_http_error_reporting_prints_redacted_detail(capsys):
    """Verify scripts/live_vault_check.check_response prints status, detail, and likely cause on HTTP error."""
    import importlib.util
    from pathlib import Path

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "live_vault_check.py"
    spec = importlib.util.spec_from_file_location("live_vault_check", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class FakeResponse:
        status_code = 502
        is_success = False
        text = ""

        def json(self):
            return {
                "detail": "Approve this order in PayPal before capturing [code=PROVIDER_REJECTED, status=422, name=UNPROCESSABLE_ENTITY, issues=ORDER_NOT_APPROVED, debug_id=DBG-422]"
            }

    with pytest.raises(SystemExit) as exc:
        mod.check_response(FakeResponse(), "POST /api/mandates/****/grant/complete")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "HTTP 502" in err
    assert "ORDER_NOT_APPROVED" in err
    assert "DBG-422" in err
    assert "Likely cause:" in err


def test_grant_complete_payee_not_consented_diagnostics_mocked(client, database, monkeypatch, capsys):
    """[MOCKED] 403 PAYEE_NOT_CONSENTED surfaces actionable Sandbox Business account mismatch detail."""
    _vault_env(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
        if request.method == "POST" and request.url.path == "/v2/checkout/orders":
            return httpx.Response(201, json={
                "id": "CONSENTORDER12345",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=CONSENTORDER12345"}],
            })
        if request.method == "POST" and request.url.path == "/v2/checkout/orders/CONSENTORDER12345/capture":
            return httpx.Response(403, json={
                "name": "NOT_AUTHORIZED",
                "debug_id": "DBG-CONSENT-403",
                "details": [{"issue": "PAYEE_NOT_CONSENTED"}],
            })
        raise AssertionError(f"Unexpected call: {request.method} {request.url.path}")

    _install_mock_paypal(monkeypatch, handler)
    grant = _create_grant(client)
    assert client.post(f"/api/mandates/{grant['id']}/grant/init", json={}).status_code == 200
    res = client.post(f"/api/mandates/{grant['id']}/grant/complete", json={})
    assert res.status_code == 502
    detail = res.json()["detail"]
    assert "PAYEE_NOT_CONSENTED" in detail
    assert "PAYPAL_MERCHANT_ID" in detail
    assert "debug_id=DBG-CONSENT-403" in detail

    with database() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "GRANT_FAILED", AuditEvent.entity_id == grant["id"])).first()
        assert ev.details["reason"] == "PAYEE_NOT_CONSENTED"
        assert ev.details["provider_status"] == 403
        assert ev.details["provider_error"] == "NOT_AUTHORIZED"
        assert ev.details["provider_debug_id"] == "DBG-CONSENT-403"

    import importlib.util
    from pathlib import Path
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "live_vault_check.py"
    spec = importlib.util.spec_from_file_location("live_vault_check", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "PAYEE_NOT_CONSENTED" in mod.likely_cause(502, detail)
    assert "Sandbox Business account" in mod.likely_cause(502, detail)

