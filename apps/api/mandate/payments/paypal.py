"""Direct-merchant PayPal sandbox checkout. No provider result is simulated."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
REQUIRED_ENVIRONMENT = (
    "PAYPAL_CLIENT_ID",
    "PAYPAL_CLIENT_SECRET",
    "PAYPAL_MERCHANT_ID",
    "PAYPAL_WEBHOOK_ID",
)


def missing_environment(environ: Mapping[str, str] | None = None) -> list[str]:
    """Report missing variable names without making requests or exposing values."""
    source = os.environ if environ is None else environ
    return [name for name in REQUIRED_ENVIRONMENT if not source.get(name, "").strip()]


def _safe_token(value: Any, max_len: int = 64) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_len or not re.fullmatch(r"[A-Za-z0-9_.:-]+", cleaned):
        return None
    return cleaned


class PayPalError(Exception):
    """A redacted adapter failure; ambiguous mutations must keep reservations."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int | None = None,
        ambiguous: bool = False,
        retryable: bool = False,
        issue: str | None = None,
        error_name: str | None = None,
        issues: tuple[str, ...] | list[str] | None = None,
        debug_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.ambiguous = ambiguous
        self.retryable = retryable
        cleaned_issues = tuple(dict.fromkeys(tok for tok in (_safe_token(i) for i in (issues or ())) if tok))
        cleaned_single = _safe_token(issue)
        if cleaned_single and cleaned_single not in cleaned_issues:
            cleaned_issues = (cleaned_single, *cleaned_issues)
        self.issues: tuple[str, ...] = cleaned_issues
        self.issue = cleaned_single or (cleaned_issues[0] if cleaned_issues else None)
        self.error_name = _safe_token(error_name)
        self.debug_id = _safe_token(debug_id)


def error_diagnostic_fields(error: PayPalError) -> dict[str, Any]:
    """Return safe, redacted PayPal error metadata for audit logs without secrets or tokens."""
    fields: dict[str, Any] = {}
    if error.status_code is not None:
        fields["provider_status"] = error.status_code
    if error.error_name:
        fields["provider_error"] = error.error_name
    if error.issues:
        fields["provider_issues"] = list(error.issues)
    if error.issue:
        fields["provider_issue"] = error.issue
    if error.debug_id:
        fields["provider_debug_id"] = error.debug_id
    return fields


def provider_failure_message(error: PayPalError, fallback: str) -> str:
    summary = fallback
    if not error.ambiguous:
        if error.issue == "ORDER_NOT_APPROVED":
            summary = "Approve this order in PayPal before capturing; the reservation is retained"
        elif error.issue == "INSTRUMENT_DECLINED":
            summary = "PayPal declined the funding source; return to PayPal and choose another payment method"
        elif error.status_code in {401, 403}:
            summary = "PayPal rejected the application credentials or merchant permissions; check the sandbox configuration"
    parts = [f"code={error.code}"]
    if error.status_code is not None:
        parts.append(f"status={error.status_code}")
    if error.error_name:
        parts.append(f"name={error.error_name}")
    if error.issues:
        parts.append(f"issues={','.join(error.issues)}")
    elif error.issue:
        parts.append(f"issues={error.issue}")
    if error.debug_id:
        parts.append(f"debug_id={error.debug_id}")
    return f"{summary} [{', '.join(parts)}]"


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _money(cents: int) -> dict[str, str]:
    if not _positive_int(cents):
        raise PayPalError("Amounts must be positive integer USD cents.", code="INVALID_AMOUNT")
    return {"currency_code": "USD", "value": f"{cents // 100}.{cents % 100:02d}"}


def _provider_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", value):
        raise PayPalError("Invalid provider object ID.", code="INVALID_PROVIDER_ID")
    return value


class PayPalClient:
    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        merchant_id: str | None = None,
        webhook_id: str | None = None,
        base_url: str | None = None,
        trusted_merchant_id: str = "demo-merchant",
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._client_id = os.getenv("PAYPAL_CLIENT_ID", "") if client_id is None else client_id
        self._client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "") if client_secret is None else client_secret
        self._merchant_id = os.getenv("PAYPAL_MERCHANT_ID", "") if merchant_id is None else merchant_id
        self._webhook_id = os.getenv("PAYPAL_WEBHOOK_ID", "") if webhook_id is None else webhook_id
        configured_url = os.getenv("PAYPAL_BASE_URL", SANDBOX_BASE_URL) if base_url is None else base_url
        if configured_url.rstrip("/") != SANDBOX_BASE_URL:
            raise PayPalError("Only the PayPal sandbox API is permitted.", code="UNSAFE_CONFIGURATION")
        if any(os.getenv(name, "sandbox").lower() != "sandbox" for name in ("PAYPAL_ENV", "PAYPAL_ENVIRONMENT")):
            raise PayPalError("Only the PayPal sandbox environment is permitted.", code="UNSAFE_CONFIGURATION")
        if not math.isfinite(timeout) or timeout <= 0:
            raise PayPalError("A finite positive timeout is required.", code="INVALID_CONFIGURATION")
        self._trusted_merchant_id = trusted_merchant_id
        self._timeout = timeout
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    def missing_environment(self, *, include_webhook: bool = True) -> list[str]:
        settings = dict(zip(REQUIRED_ENVIRONMENT, (
            self._client_id, self._client_secret, self._merchant_id, self._webhook_id,
        )))
        names = missing_environment(settings)
        return names if include_webhook else [name for name in names if name != "PAYPAL_WEBHOOK_ID"]

    @property
    def configured(self) -> bool:
        return not self.missing_environment(include_webhook=False)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> PayPalClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def _send(self, method: str, path: str, *, mutation: bool = False, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._http.request(
                method, SANDBOX_BASE_URL + path,
                timeout=self._timeout, follow_redirects=False, **kwargs,
            )
        except httpx.RequestError:
            raise PayPalError(
                "PayPal did not return a confirmed result.", code="NETWORK_ERROR",
                ambiguous=mutation, retryable=True,
            ) from None
        try:
            result = response.json()
        except ValueError:
            result = None
        if not 200 <= response.status_code < 300:
            raw_issues = [
                detail.get("issue") for detail in result.get("details", [])
                if isinstance(detail, dict)
            ] if isinstance(result, dict) and isinstance(result.get("details"), list) else []
            safe_issues = tuple(dict.fromkeys(tok for tok in (_safe_token(item) for item in raw_issues) if tok))
            issues = set(safe_issues)
            # Unknown provider errors must never release a possibly completed refund.
            definitive = response.status_code in {401, 403} or (
                response.status_code == 422 and bool(issues) and issues <= {"INSTRUMENT_DECLINED", "ORDER_NOT_APPROVED"}
            )
            uncertain = not definitive
            if response.status_code == 401:
                self._access_token = None
                self._token_expires_at = 0.0
            raise PayPalError(
                "PayPal rejected the request." if not uncertain else "PayPal result requires reconciliation.",
                code="PROVIDER_UNAVAILABLE" if uncertain else "PROVIDER_REJECTED",
                status_code=response.status_code,
                ambiguous=mutation and uncertain,
                retryable=uncertain,
                issue=safe_issues[0] if len(safe_issues) == 1 else None,
                error_name=result.get("name") if isinstance(result, dict) else None,
                issues=safe_issues,
                debug_id=result.get("debug_id") if isinstance(result, dict) else None,
            )
        if not isinstance(result, dict):
            raise PayPalError(
                "PayPal returned an invalid response.", code="INVALID_PROVIDER_RESPONSE",
                status_code=response.status_code, ambiguous=mutation, retryable=True,
            )
        return result

    async def _token(self) -> str:
        missing = self.missing_environment(include_webhook=False)
        if missing:
            raise PayPalError("Missing environment variables: " + ", ".join(missing), code="UNCONFIGURED")
        async with self._token_lock:
            if self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token
            started_at = time.monotonic()
            result = await self._send(
                "POST", "/v1/oauth2/token",
                auth=httpx.BasicAuth(self._client_id, self._client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
            )
            token, expires = result.get("access_token"), result.get("expires_in")
            if (
                not isinstance(token, str) or not token
                or isinstance(expires, bool) or not isinstance(expires, (int, float))
                or not math.isfinite(expires) or expires <= 0
                or str(result.get("token_type", "Bearer")).lower() != "bearer"
            ):
                raise PayPalError("PayPal returned an invalid OAuth response.", code="INVALID_OAUTH_RESPONSE", retryable=True)
            self._access_token = token
            self._token_expires_at = started_at + expires - min(30, expires / 10)
            return token

    async def _request(
        self, method: str, path: str, *, request_id: str | None = None,
        body: dict[str, Any] | None = None, mutation: bool = False, raw_json: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json", "Prefer": "return=representation"}
        if mutation:
            if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,38}", request_id):
                raise PayPalError("A stable operation request ID of at most 38 ASCII characters is required.", code="INVALID_REQUEST_ID")
            headers["PayPal-Request-Id"] = request_id
        headers["Authorization"] = "Bearer " + await self._token()
        if raw_json is not None:
            headers["Content-Type"] = "application/json"
            kwargs = {"content": raw_json.encode("utf-8")}
        else:
            kwargs = {"json": body} if body is not None else {}
        result = await self._send(method, path, headers=headers, mutation=mutation, **kwargs)
        if path != "/v1/notifications/verify-webhook-signature" and (
            not isinstance(result.get("id"), str) or not result["id"]
            or not isinstance(result.get("status"), str) or not result["status"]
        ):
            raise PayPalError(
                "PayPal returned an incomplete financial response.", code="INVALID_PROVIDER_RESPONSE",
                ambiguous=mutation, retryable=True,
            )
        return result

    def _build_purchase_unit(self, cart: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(cart, Mapping) or cart.get("merchant_id") != self._trusted_merchant_id:
            raise PayPalError("Cart merchant is not the configured trusted merchant.", code="UNTRUSTED_MERCHANT")
        if cart.get("currency") != "USD":
            raise PayPalError("Only USD is supported.", code="INVALID_CURRENCY")
        amount = _money(cart.get("total_cents"))
        items = cart.get("items")
        if not isinstance(items, list) or not items:
            raise PayPalError("A nonempty canonical cart is required.", code="INVALID_CART")
        paypal_items, computed_total = [], 0
        for item in items:
            if not isinstance(item, Mapping):
                raise PayPalError("Invalid cart item.", code="INVALID_CART")
            if item.get("merchant_id", cart["merchant_id"]) != self._trusted_merchant_id:
                raise PayPalError("Cart item merchant is not trusted.", code="UNTRUSTED_MERCHANT")
            quantity, name = item.get("quantity"), item.get("name")
            if not _positive_int(quantity) or not isinstance(name, str) or not 1 <= len(name) <= 127:
                raise PayPalError("Invalid cart item name or quantity.", code="INVALID_CART")
            unit_amount = _money(item.get("unit_price_cents"))
            computed_total += item["unit_price_cents"] * quantity
            paypal_items.append({"name": name, "quantity": str(quantity), "unit_amount": unit_amount})
        if computed_total != cart["total_cents"]:
            raise PayPalError("Cart total does not match its canonical items.", code="INVALID_CART")
        return {
            "payee": {"merchant_id": self._merchant_id},
            "amount": {**amount, "breakdown": {"item_total": amount.copy()}},
            "items": paypal_items,
        }

    def _validate_callback_urls(self, *urls: str) -> None:
        for url in urls:
            try:
                parsed = urlsplit(url)
                valid = isinstance(url, str) and parsed.scheme in {"https", "http"} and parsed.hostname
            except (ValueError, TypeError):
                valid = False
            if not valid or parsed.username or parsed.password:
                raise PayPalError("Valid server-configured callback URLs are required.", code="INVALID_CALLBACK")
            if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise PayPalError("Nonlocal callback URLs require HTTPS.", code="INVALID_CALLBACK")

    async def create_order(
        self, cart: Mapping[str, Any], request_id: str, return_url: str, cancel_url: str,
    ) -> dict[str, Any]:
        purchase_unit = self._build_purchase_unit(cart)
        self._validate_callback_urls(return_url, cancel_url)
        return await self._request(
            "POST", "/v2/checkout/orders", request_id=request_id, mutation=True,
            body={
                "intent": "CAPTURE",
                "purchase_units": [purchase_unit],
                "payment_source": {"paypal": {"experience_context": {
                    "return_url": return_url, "cancel_url": cancel_url, "user_action": "PAY_NOW",
                }}},
            },
        )

    async def create_vault_setup_order(
        self, mandate_id: str, request_id: str, return_url: str, cancel_url: str,
    ) -> dict[str, Any]:
        self._validate_callback_urls(return_url, cancel_url)
        return await self._request(
            "POST", "/v2/checkout/orders", request_id=request_id, mutation=True,
            body={
                "intent": "CAPTURE",
                "purchase_units": [{
                    "reference_id": f"grant-{_provider_id(mandate_id)}",
                    "payee": {"merchant_id": self._merchant_id},
                    "amount": {"currency_code": "USD", "value": "1.00"},
                    "description": "Mandate vault authorization ($1.00 refundable)",
                }],
                "payment_source": {
                    "paypal": {
                        "experience_context": {
                            "return_url": return_url,
                            "cancel_url": cancel_url,
                            "user_action": "PAY_NOW",
                            "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
                        },
                        "attributes": {
                            "vault": {
                                "store_in_vault": "ON_SUCCESS",
                                "usage_type": "MERCHANT",
                                "customer_type": "CONSUMER",
                            }
                        },
                    }
                },
            },
        )

    async def charge_vault(
        self, cart: Mapping[str, Any], vault_token: str, request_id: str,
    ) -> dict[str, Any]:
        if not isinstance(vault_token, str) or not vault_token.strip():
            raise PayPalError("A valid vault token is required.", code="INVALID_VAULT_TOKEN")
        purchase_unit = self._build_purchase_unit(cart)
        return await self._request(
            "POST", "/v2/checkout/orders", request_id=request_id, mutation=True,
            body={
                "intent": "CAPTURE",
                "purchase_units": [purchase_unit],
                "payment_source": {"paypal": {"vault_id": vault_token.strip()}},
            },
        )

    async def capture_order(self, order_id: str, request_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/v2/checkout/orders/{_provider_id(order_id)}/capture",
            request_id=request_id, mutation=True, body={},
        )

    async def refund_capture(self, capture_id: str, amount_cents: int, request_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/v2/payments/captures/{_provider_id(capture_id)}/refund",
            request_id=request_id, mutation=True, body={"amount": _money(amount_cents)},
        )

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v2/checkout/orders/{_provider_id(order_id)}")

    async def get_capture(self, capture_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v2/payments/captures/{_provider_id(capture_id)}")

    async def get_refund(self, refund_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v2/payments/refunds/{_provider_id(refund_id)}")

    async def verify_webhook(self, headers: Mapping[str, str], event: dict[str, Any], *, raw_body: str | None = None) -> dict[str, Any]:
        if not self._webhook_id.strip():
            raise PayPalError("Missing environment variables: PAYPAL_WEBHOOK_ID", code="UNCONFIGURED")
        if not isinstance(headers, Mapping):
            raise PayPalError("Missing webhook verification headers or event.", code="INVALID_WEBHOOK")
        normalized = {name.lower(): value for name, value in headers.items() if isinstance(name, str)}
        fields = {
            "auth_algo": "paypal-auth-algo", "cert_url": "paypal-cert-url",
            "transmission_id": "paypal-transmission-id", "transmission_sig": "paypal-transmission-sig",
            "transmission_time": "paypal-transmission-time",
        }
        if any(not isinstance(normalized.get(name), str) or not normalized[name].strip() for name in fields.values()) or not isinstance(event, dict):
            raise PayPalError("Missing webhook verification headers or event.", code="INVALID_WEBHOOK")
        original = json.dumps(event) if raw_body is None else raw_body
        try:
            if json.loads(original) != event:
                raise ValueError
        except (ValueError, TypeError, RecursionError):
            raise PayPalError("Webhook body and parsed event do not match.", code="INVALID_WEBHOOK") from None
        metadata = {**{field: normalized[name] for field, name in fields.items()}, "webhook_id": self._webhook_id}
        # PayPal postback verification requires the original event representation.
        payload = json.dumps(metadata)[:-1] + ',"webhook_event":' + original + '}'
        result = await self._request(
            "POST", "/v1/notifications/verify-webhook-signature",
            raw_json=payload,
        )
        if result.get("verification_status") not in {"SUCCESS", "FAILURE"}:
            raise PayPalError("PayPal returned an invalid verification result.", code="INVALID_PROVIDER_RESPONSE", retryable=True)
        return result
