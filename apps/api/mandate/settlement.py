import os
from urllib.parse import urlsplit

from sqlalchemy import select

from .audit import append, digest
from .config import mask_merchant_id, normalize_merchant_id
from .models import Case, Mandate, Operation, Payment, Proposal, Session


def payee_mismatch_info(payload) -> tuple[bool, str, str]:
    """Check whether purchase_units[0].payee.merchant_id mismatches configured PAYPAL_MERCHANT_ID."""
    expected = normalize_merchant_id(os.getenv("PAYPAL_MERCHANT_ID"))
    units = payload.get("purchase_units") if isinstance(payload, dict) else None
    if not expected or not isinstance(units, list) or not units or not isinstance(units[0], dict):
        return False, mask_merchant_id(expected), "(missing)"
    payee = units[0].get("payee")
    actual = normalize_merchant_id(payee.get("merchant_id") if isinstance(payee, dict) else None)
    if not actual:
        return False, mask_merchant_id(expected), "(missing)"
    return actual != expected, mask_merchant_id(expected), mask_merchant_id(actual)


def payee_mismatch_detail(expected_masked: str, actual_masked: str, context: str = "PayPal order") -> str:
    return (
        f"{context} payee does not match configured PAYPAL_MERCHANT_ID "
        f"(expected={expected_masked}, actual={actual_masked}). "
        f"Update PAYPAL_MERCHANT_ID in .env to match PayPal's Sandbox Business account ({actual_masked}), "
        f"or use PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET owned by {expected_masked}"
    )


def lock_payment(db, payment_id):
    payment = db.get(Payment, payment_id)
    owner = db.scalar(select(Session).where(Session.id == payment.session_id).with_for_update().execution_options(populate_existing=True))
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update().execution_options(populate_existing=True))
    return owner, payment


def offer_digest(case):
    return digest({"payment_id": case.payment_id, "cause": case.cause, "evidence": case.evidence,
                   "offer_cents": case.offer_cents, "policy_version": 1})


def approval_link(result):
    links = result.get("links", [])
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict) or link.get("rel") not in {"approve", "payer-action"}:
                continue
            href = link.get("href")
            if not isinstance(href, str):
                continue
            try:
                url = urlsplit(href)
                if url.scheme == "https" and url.hostname in {"www.sandbox.paypal.com", "sandbox.paypal.com"} and not url.username and not url.password and url.port in {None, 443}:
                    return href
            except ValueError:
                continue
    return None


def settle_order(db, operation_id, result):
    operation = db.get(Operation, operation_id)
    owner, payment = lock_payment(db, operation.payment_id)
    db.refresh(operation, with_for_update=True)
    order_id = result.get("id")
    if not isinstance(order_id, str) or not order_id or (payment.provider_order_id and payment.provider_order_id != order_id):
        return False
    if "purchase_units" in result:
        units = result["purchase_units"]
        if not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], dict):
            return False
        payee, amount = units[0].get("payee"), units[0].get("amount")
        expected = f"{payment.amount_cents // 100}.{payment.amount_cents % 100:02d}"
        if (not isinstance(payee, dict) or normalize_merchant_id(payee.get("merchant_id")) != normalize_merchant_id(os.getenv("PAYPAL_MERCHANT_ID"))
                or not isinstance(amount, dict) or amount.get("currency_code") != "USD" or amount.get("value") != expected):
            return False
    if operation.status == "COMPLETED":
        return payment.provider_order_id == order_id
    link = approval_link(result)
    if result.get("status") not in {"CREATED", "SAVED", "APPROVED", "PAYER_ACTION_REQUIRED"} or (result["status"] != "APPROVED" and not link):
        return False
    if payment.status not in {"RESERVED", "UNKNOWN", "ORDER_CREATED"}:
        return False
    payment.provider_order_id, payment.approval_url, payment.status = order_id, link, "ORDER_CREATED"
    operation.status, operation.result = "COMPLETED", {"id": order_id, "status": result["status"]}
    append(db, owner, "ORDER_CREATED", payment.id, {"provider_order_id": order_id})
    return True


def capture_from_order(result, payment):
    if result.get("id") != payment.provider_order_id:
        return None
    units = result.get("purchase_units", [])
    if not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], dict):
        return None
    payee, payments = units[0].get("payee", {}), units[0].get("payments", {})
    if not isinstance(payee, dict) or normalize_merchant_id(payee.get("merchant_id")) != normalize_merchant_id(os.getenv("PAYPAL_MERCHANT_ID")) or not isinstance(payments, dict):
        return None
    captures = payments.get("captures", [])
    if not isinstance(captures, list) or len(captures) != 1 or not isinstance(captures[0], dict):
        return None
    capture = captures[0]
    expected = {"currency_code": "USD", "value": f"{payment.amount_cents // 100}.{payment.amount_cents % 100:02d}"}
    confirmed = capture.get("status") == "COMPLETED" or (
        payment.status == "CAPTURED" and capture.get("id") == payment.provider_capture_id
        and capture.get("status") in {"PARTIALLY_REFUNDED", "REFUNDED"})
    if not confirmed or capture.get("amount") != expected or not capture.get("id"):
        return None
    return capture


def settle_capture(db, payment_id, result):
    owner, payment = lock_payment(db, payment_id)
    capture = capture_from_order(result, payment)
    proposal = db.get(Proposal, payment.proposal_id)
    if capture is None or digest(proposal.cart) != proposal.cart_hash:
        return False
    if payment.status == "CAPTURED":
        return payment.provider_capture_id == capture["id"]
    if payment.status not in {"CAPTURE_PENDING", "UNKNOWN", "ORDER_CREATED"}:
        return False
    grant = db.scalar(select(Mandate).where(Mandate.id == payment.mandate_id).with_for_update().execution_options(populate_existing=True))
    if grant.reserved_cents < payment.amount_cents:
        return False
    payment.status, payment.provider_capture_id, payment.provider_status = "CAPTURED", capture["id"], "COMPLETED"
    grant.reserved_cents -= payment.amount_cents
    grant.spent_cents += payment.amount_cents
    for operation in db.scalars(select(Operation).where(Operation.payment_id == payment.id, Operation.kind == "CAPTURE")):
        operation.status, operation.result = "COMPLETED", {"id": capture["id"], "status": "COMPLETED"}
    append(db, owner, "PAYMENT_CAPTURED", payment.id, {"provider_capture_id": capture["id"], "amount_cents": payment.amount_cents})
    return True


def settle_refund(db, operation_id, result):
    operation = db.get(Operation, operation_id)
    owner, payment = lock_payment(db, operation.payment_id)
    db.refresh(operation, with_for_update=True)
    case = db.scalar(select(Case).where(Case.id == operation.entity_key).with_for_update().execution_options(populate_existing=True))
    if not case or operation.kind != "REFUND" or case.payment_id != payment.id:
        return False
    offer_hash = offer_digest(case)
    payload = operation.request_payload
    accepted_hash = payload.get("offer_hash") if payload else operation.payload_hash
    if offer_hash != case.offer_hash or accepted_hash != case.offer_hash or (payload and digest(payload) != operation.payload_hash):
        return False
    expected = {"currency_code": "USD", "value": f"{case.offer_cents // 100}.{case.offer_cents % 100:02d}"}
    known_id = (operation.result or {}).get("id")
    if not result.get("id") or (known_id and result["id"] != known_id) or result.get("status") != "COMPLETED" or result.get("amount") != expected:
        return False
    if case.status == "REFUNDED":
        return True
    if case.status not in {"REFUND_PENDING", "UNKNOWN"} or payment.refund_reserved_cents < case.offer_cents:
        return False
    payment.refund_reserved_cents -= case.offer_cents
    payment.refunded_cents += case.offer_cents
    case.status, operation.status = "REFUNDED", "COMPLETED"
    operation.result = {"id": result["id"], "status": "COMPLETED"}
    append(db, owner, "PAYMENT_REFUNDED", case.id, {"payment_id": payment.id, "amount_cents": case.offer_cents, "provider_refund_id": result["id"]})
    return True
