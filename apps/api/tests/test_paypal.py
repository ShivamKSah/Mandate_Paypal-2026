"""Contract checks use HTTP responses only; no PayPal account is needed."""

import asyncio
import base64
import copy
import json
import time

import httpx
import pytest

from mandate.payments.paypal import (
    REQUIRED_ENVIRONMENT,
    SANDBOX_BASE_URL,
    PayPalClient,
    PayPalError,
    missing_environment,
)

CART = {
    "merchant_id": "demo-merchant", "currency": "USD", "total_cents": 34900,
    "items": [{"product_id": "desk-160", "name": "160 cm desk", "quantity": 1,
               "unit_price_cents": 34900, "merchant_id": "demo-merchant"}],
}
RETURN_URL = "http://localhost:5173/payments/return"
CANCEL_URL = "http://localhost:5173/payments/cancel"
WEBHOOK_HEADERS = {
    "PayPal-Auth-Algo": "SHA256withRSA",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-ID",
    "paypal-transmission-id": "TRANSMISSION-ID",
    "PayPal-Transmission-Sig": "signed-value",
    "PayPal-Transmission-Time": "2026-10-28T16:00:00Z",
}


class MockProvider:
    def __init__(self):
        self.requests = []
        self.responses = []
        self.token_response = {"access_token": "access-secret", "expires_in": 3600, "token_type": "Bearer"}
        self.token_status = 200
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle))
        self.client = PayPalClient(
            client_id="client-id", client_secret="client-secret", merchant_id="ABCD23456789A",
            webhook_id="WH-CONFIGURED", http_client=self.http,
        )

    def handle(self, request):
        self.requests.append(request)
        assert str(request.url).startswith(SANDBOX_BASE_URL + "/")
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(self.token_status, json=self.token_response)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def result(self, body, status=200):
        self.responses.append(httpx.Response(status, json=body))

    @property
    def financial_requests(self):
        return [request for request in self.requests if request.url.path != "/v1/oauth2/token"]


@pytest.fixture(autouse=True)
def clean_paypal_environment(monkeypatch):
    for name in (*REQUIRED_ENVIRONMENT, "PAYPAL_BASE_URL", "PAYPAL_ENV", "PAYPAL_ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def provider():
    provider = MockProvider()
    yield provider
    asyncio.run(provider.http.aclose())


def test_create_order_exact_amount_and_configured_payee(provider):
    cart = copy.deepcopy(CART)
    cart["payee"] = {"merchant_id": "attacker"}
    cart["items"][0]["payee"] = {"merchant_id": "attacker"}
    provider.result({"id": "ORDER1", "status": "PAYER_ACTION_REQUIRED"}, 201)
    result = asyncio.run(provider.client.create_order(cart, "create-operation", RETURN_URL, CANCEL_URL))
    request = provider.financial_requests[0]
    payload = json.loads(request.content)
    assert result == {"id": "ORDER1", "status": "PAYER_ACTION_REQUIRED"}
    assert request.headers["PayPal-Request-Id"] == "create-operation"
    assert request.extensions["timeout"]["read"] == 15
    assert payload["intent"] == "CAPTURE"
    unit = payload["purchase_units"][0]
    assert unit["payee"] == {"merchant_id": "ABCD23456789A"}
    assert unit["amount"] == {
        "value": "349.00", "currency_code": "USD",
        "breakdown": {"item_total": {"value": "349.00", "currency_code": "USD"}},
    }
    assert unit["items"] == [{"name": "160 cm desk", "quantity": "1",
                              "unit_amount": {"currency_code": "USD", "value": "349.00"}}]
    assert payload["payment_source"]["paypal"]["experience_context"] == {
        "return_url": RETURN_URL, "cancel_url": CANCEL_URL, "user_action": "PAY_NOW",
    }
    assert "vault_id" not in json.dumps(payload)


def test_partial_refund_uses_integer_cents(provider):
    provider.result({"id": "REFUND1", "status": "PENDING"}, 201)
    result = asyncio.run(provider.client.refund_capture("CAPTURE1", 31410, "refund-operation"))
    request = provider.financial_requests[0]
    assert request.url.path == "/v2/payments/captures/CAPTURE1/refund"
    assert request.headers["PayPal-Request-Id"] == "refund-operation"
    assert json.loads(request.content) == {"amount": {"currency_code": "USD", "value": "314.10"}}
    assert result["status"] == "PENDING"


def test_lost_capture_retry_preserves_operation_identity(provider):
    provider.responses.append(httpx.ReadTimeout("a sensitive transport message"))
    provider.result({"id": "ORDER1", "status": "COMPLETED"}, 201)

    async def flow():
        with pytest.raises(PayPalError) as caught:
            await provider.client.capture_order("ORDER1", "same-operation-id")
        assert caught.value.ambiguous and caught.value.retryable
        assert caught.value.code == "NETWORK_ERROR"
        assert "sensitive" not in str(caught.value)
        assert len(provider.financial_requests) == 1
        return await provider.client.capture_order("ORDER1", "same-operation-id")

    assert asyncio.run(flow())["status"] == "COMPLETED"
    requests = provider.financial_requests
    assert [request.headers["PayPal-Request-Id"] for request in requests] == ["same-operation-id"] * 2
    assert requests[0].content == requests[1].content == b"{}"
    assert requests[0].url == requests[1].url


def test_oauth_basic_auth_cache_and_expiry(provider):
    for _ in range(3):
        provider.result({"id": "ORDER1", "status": "APPROVED"})

    async def flow():
        await provider.client.get_order("ORDER1")
        assert time.monotonic() < provider.client._token_expires_at <= time.monotonic() + 3570
        await provider.client.get_order("ORDER1")
        assert len(provider.requests) == 3
        provider.client._token_expires_at = 0
        await provider.client.get_order("ORDER1")

    asyncio.run(flow())
    oauth = [request for request in provider.requests if request.url.path == "/v1/oauth2/token"]
    assert len(oauth) == 2
    expected = base64.b64encode(b"client-id:client-secret").decode()
    assert oauth[0].headers["Authorization"] == "Basic " + expected
    assert oauth[0].content == b"grant_type=client_credentials"
    assert all(request.headers["Authorization"] == "Bearer access-secret" for request in provider.financial_requests)


def test_definitive_rejection_is_redacted(provider):
    provider.result({"name": "UNPROCESSABLE_ENTITY", "message": "client-secret buyer@email.test",
                     "details": [{"issue": "INSTRUMENT_DECLINED"}]}, 422)
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.capture_order("ORDER1", "capture-id"))
    error = caught.value
    assert not error.ambiguous and not error.retryable
    assert error.status_code == 422 and error.code == "PROVIDER_REJECTED"
    assert error.issue == "INSTRUMENT_DECLINED"
    assert "client-secret" not in str(error) and "buyer@email.test" not in str(error)


@pytest.mark.parametrize("status", [408, 409, 429, 500, 503])
def test_provider_uncertainty_keeps_mutation_unknown(provider, status):
    provider.result({"message": "unavailable"}, status)
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.refund_capture("CAPTURE1", 1, "refund-id"))
    assert caught.value.ambiguous and caught.value.retryable
    assert caught.value.status_code == status
    assert len(provider.financial_requests) == 1


def test_already_captured_is_not_proof_of_no_charge(provider):
    provider.result({"details": [{"issue": "ORDER_ALREADY_CAPTURED"}]}, 422)
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.capture_order("ORDER1", "capture-id"))
    assert caught.value.ambiguous


@pytest.mark.parametrize("body", [{}, {"details": [{"issue": "UNKNOWN_PROVIDER_ERROR"}]}])
def test_unknown_4xx_is_not_proof_of_no_refund(provider, body):
    provider.result(body, 422)
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.refund_capture("CAPTURE1", 1, "refund-id"))
    assert caught.value.ambiguous


@pytest.mark.parametrize("body", [None, [], {}, {"id": "ORDER1"}])
def test_malformed_success_is_unknown(provider, body):
    provider.result(body, 201)
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.capture_order("ORDER1", "capture-id"))
    assert caught.value.ambiguous and caught.value.retryable
    assert caught.value.code == "INVALID_PROVIDER_RESPONSE"


def test_redirect_does_not_send_credentials_to_another_host(provider):
    provider.responses.append(httpx.Response(302, headers={"Location": "https://api-m.paypal.com/steal"}))
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.capture_order("ORDER1", "capture-id"))
    assert caught.value.status_code == 302
    assert len(provider.financial_requests) == 1


@pytest.mark.parametrize("status", ["SUCCESS", "FAILURE"])
def test_webhook_verification_uses_provider_result_and_original_event(provider, status):
    event = {"id": "EVENT1", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "CAPTURE1"}}
    provider.result({"verification_status": status})
    result = asyncio.run(provider.client.verify_webhook(WEBHOOK_HEADERS, event))
    assert result == {"verification_status": status}
    request = provider.financial_requests[0]
    assert request.url.path == "/v1/notifications/verify-webhook-signature"
    body = json.loads(request.content)
    assert body["webhook_id"] == "WH-CONFIGURED"
    assert body["webhook_event"] == event
    assert body["cert_url"] == WEBHOOK_HEADERS["PAYPAL-CERT-URL"]
    assert body["transmission_sig"] == "signed-value"


def test_webhook_outage_never_becomes_verified(provider):
    provider.result({"message": "unavailable"}, 503)
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.verify_webhook(WEBHOOK_HEADERS, {"id": "EVENT1"}))
    assert caught.value.retryable


def test_webhook_without_headers_never_contacts_provider(provider):
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.verify_webhook({}, {"id": "EVENT1"}))
    assert caught.value.code == "INVALID_WEBHOOK"
    assert not provider.requests


def test_webhook_postback_preserves_original_json_bytes(provider):
    raw = '{\n  "id": "EVENT1", "summary": "desk \\u003c160cm",\n  "resource": {}\n}'
    provider.result({"verification_status": "SUCCESS"})
    asyncio.run(provider.client.verify_webhook(WEBHOOK_HEADERS, json.loads(raw), raw_body=raw))
    request = provider.financial_requests[0]
    assert b'"webhook_event":' + raw.encode() in request.content
    assert request.headers["content-type"] == "application/json"


@pytest.mark.parametrize("kind,identifier,path", [
    ("get_order", "ORDER1", "/v2/checkout/orders/ORDER1"),
    ("get_capture", "CAPTURE1", "/v2/payments/captures/CAPTURE1"),
    ("get_refund", "REFUND1", "/v2/payments/refunds/REFUND1"),
])
def test_reconciliation_reads_provider_objects(provider, kind, identifier, path):
    body = {"id": identifier, "status": "COMPLETED"}
    provider.result(body)
    assert asyncio.run(getattr(provider.client, kind)(identifier)) == body
    assert provider.financial_requests[0].method == "GET"
    assert provider.financial_requests[0].url.path == path


@pytest.mark.parametrize("change,code", [
    ({"total_cents": 349.0}, "INVALID_AMOUNT"),
    ({"total_cents": True}, "INVALID_AMOUNT"),
    ({"total_cents": 0}, "INVALID_AMOUNT"),
    ({"total_cents": 34901}, "INVALID_CART"),
    ({"currency": "EUR"}, "INVALID_CURRENCY"),
    ({"merchant_id": "untrusted-merchant"}, "UNTRUSTED_MERCHANT"),
    ({"items": []}, "INVALID_CART"),
])
def test_invalid_carts_never_contact_provider(provider, change, code):
    cart = {**copy.deepcopy(CART), **change}
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.create_order(cart, "create-id", RETURN_URL, CANCEL_URL))
    assert caught.value.code == code
    assert not provider.requests


def test_mixed_merchant_items_are_rejected(provider):
    cart = copy.deepcopy(CART)
    cart["items"][0]["merchant_id"] = "untrusted-merchant"
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.create_order(cart, "create-id", RETURN_URL, CANCEL_URL))
    assert caught.value.code == "UNTRUSTED_MERCHANT"
    assert not provider.requests


@pytest.mark.parametrize("request_id", ["", "a" * 39, "bad\r\nheader", None])
def test_stable_request_id_is_required_before_dispatch(provider, request_id):
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.capture_order("ORDER1", request_id))
    assert caught.value.code == "INVALID_REQUEST_ID"
    assert not provider.requests


def test_missing_configuration_reports_only_variable_names(provider):
    assert missing_environment({"PAYPAL_CLIENT_ID": "do-not-report"}) == list(REQUIRED_ENVIRONMENT[1:])
    client = PayPalClient(http_client=provider.http)
    assert not client.configured
    assert client.missing_environment() == list(REQUIRED_ENVIRONMENT)
    with pytest.raises(PayPalError) as caught:
        asyncio.run(client.get_order("ORDER1"))
    assert caught.value.code == "UNCONFIGURED"
    assert "PAYPAL_CLIENT_ID" in str(caught.value)
    assert not provider.requests


@pytest.mark.parametrize("base_url", ["https://api-m.paypal.com", "http://api-m.sandbox.paypal.com", "https://attacker.test"])
def test_non_sandbox_hosts_are_rejected(base_url):
    with pytest.raises(PayPalError) as caught:
        PayPalClient(base_url=base_url)
    assert caught.value.code == "UNSAFE_CONFIGURATION"
    assert base_url not in str(caught.value)


def test_env_configuration_and_live_mode_rejection(provider, monkeypatch):
    for name, value in zip(REQUIRED_ENVIRONMENT, ["id", "secret", "merchant", "webhook"]):
        monkeypatch.setenv(name, value)
    client = PayPalClient(http_client=provider.http)
    assert client.configured and client.missing_environment() == []
    monkeypatch.setenv("PAYPAL_ENVIRONMENT", "live")
    with pytest.raises(PayPalError) as caught:
        PayPalClient(http_client=provider.http)
    assert caught.value.code == "UNSAFE_CONFIGURATION"


def test_oauth_rejection_never_dispatches_capture(provider):
    provider.token_status = 401
    provider.token_response = {"error": "invalid_client", "error_description": "client-secret"}
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.capture_order("ORDER1", "capture-id"))
    assert not caught.value.ambiguous
    assert "client-secret" not in str(caught.value)
    assert not provider.financial_requests


def test_oauth_outage_is_retryable_without_financial_ambiguity(provider):
    provider.token_status = 503
    provider.token_response = {"message": "unavailable"}
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.capture_order("ORDER1", "capture-id"))
    assert caught.value.retryable and not caught.value.ambiguous
    assert not provider.financial_requests


@pytest.mark.parametrize("expires", [0, -1, "3600", True, None])
def test_invalid_oauth_expiry_never_dispatches_financial_request(provider, expires):
    provider.token_response["expires_in"] = expires
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.capture_order("ORDER1", "capture-id"))
    assert caught.value.code == "INVALID_OAUTH_RESPONSE"
    assert not caught.value.ambiguous
    assert not provider.financial_requests


def test_expired_bearer_token_is_invalidated_for_next_attempt(provider):
    provider.result({"message": "expired token"}, 401)
    provider.result({"id": "ORDER1", "status": "APPROVED"})

    async def flow():
        with pytest.raises(PayPalError):
            await provider.client.get_order("ORDER1")
        assert provider.client._access_token is None
        await provider.client.get_order("ORDER1")

    asyncio.run(flow())
    assert len([request for request in provider.requests if request.url.path == "/v1/oauth2/token"]) == 2


@pytest.mark.parametrize("url", [None, "javascript:alert(1)", "http://attacker.test/return", "https://user:secret@example.com/return"])
def test_invalid_callback_urls_fail_before_dispatch(provider, url):
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.create_order(CART, "create-id", url, CANCEL_URL))
    assert caught.value.code == "INVALID_CALLBACK"
    assert not provider.requests


def test_invalid_provider_id_cannot_change_request_path(provider):
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.get_capture("../refunds/REFUND1"))
    assert caught.value.code == "INVALID_PROVIDER_ID"
    assert not provider.requests


def test_webhook_omitted_result_is_not_success(provider):
    provider.result({})
    with pytest.raises(PayPalError) as caught:
        asyncio.run(provider.client.verify_webhook(WEBHOOK_HEADERS, {"id": "EVENT1"}))
    assert caught.value.code == "INVALID_PROVIDER_RESPONSE"
