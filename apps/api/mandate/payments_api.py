import os
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .audit import append, digest
from .catalog import quote
from .config import PUBLIC_BASE_URL
from .db import get_db
from .models import Mandate, Operation, Payment, Proposal, ReconciliationLease, Session, now
from .payments.paypal import PayPalClient, PayPalError, error_diagnostic_fields, provider_failure_message
from .policy import evaluate
from .security import human, owned
from .schemas import ItemInput
from .settlement import capture_from_order, lock_payment, settle_capture, settle_order
from .vault import VaultConfigError, decrypt_vault_token, mask_token

router = APIRouter(prefix="/api/payments")


def payment_view(payment, db):
    operation = db.scalar(select(Operation).where(Operation.payment_id == payment.id, Operation.kind == "CREATE")) if payment.status == "RESERVED" else None
    return {**{key: getattr(payment, key) for key in ("id", "proposal_id", "status", "amount_cents", "refunded_cents", "provider_order_id", "provider_capture_id", "approval_url", "created_at")},
            "can_cancel": bool(operation and operation.status == "WAITING" and operation.attempts == 0)}


def payment_context(db, owner, payment_id):
    relock_owner(db, owner)
    payment = owned(db, Payment, payment_id, owner, lock=True)
    grant = owned(db, Mandate, payment.mandate_id, owner, lock=True)
    proposal = owned(db, Proposal, payment.proposal_id, owner)
    return payment, grant, proposal


def relock_owner(db, owner):
    db.scalar(select(Session).where(Session.id == owner.id).with_for_update().execution_options(populate_existing=True))


def dispatch_guard(db, grant, proposal, payment):
    if proposal.status != "APPROVED" or proposal.decision != "APPROVE":
        raise HTTPException(409, "Proposal is not approved")
    if digest(proposal.cart) != proposal.cart_hash:
        raise HTTPException(409, "Stored cart integrity failure")
    if proposal.grant_version != grant.version:
        raise HTTPException(409, "Grant changed; submit a fresh intent")
    if proposal.quote_expires_at <= now():
        cart, missing = quote([ItemInput(product_id=item["product_id"], quantity=item["quantity"]) for item in proposal.cart["items"]], proposal.cart["currency"])
        if missing or digest(cart) != proposal.cart_hash:
            raise HTTPException(409, "Quote changed; the original payment cannot be dispatched")
        proposal.quote_expires_at = now() + timedelta(seconds=60)
    decision, _ = evaluate(db, grant, proposal.cart, [], proposal_id=proposal.id,
                          human_approved=proposal.human_approved, reserved_credit=payment.amount_cents, payment_id=payment.id)
    if decision != "APPROVE" or grant.reserved_cents < payment.amount_cents:
        raise HTTPException(409, "Current grant policy prevents dispatch")


def configured_client():
    return PayPalClient()


def begin_operation(db, payment, kind, payload):
    payload_hash = digest(payload)
    operation = db.scalar(select(Operation).where(Operation.payment_id == payment.id, Operation.kind == kind, Operation.entity_key == "").with_for_update())
    if operation is None:
        operation = Operation(payment_id=payment.id, kind=kind, payload_hash=payload_hash, request_payload=payload)
        db.add(operation)
        db.flush()
    elif operation.status == "WAITING" and operation.attempts == 0:
        operation.payload_hash, operation.request_payload = payload_hash, payload
    if operation.payload_hash != payload_hash:
        raise HTTPException(409, "Operation payload integrity failure")
    if operation.status in {"DISPATCHED", "UNKNOWN"}:
        raise HTTPException(409, "Provider result requires reconciliation; reservation retained")
    if operation.status == "COMPLETED":
        return operation
    if operation.status == "CANCELLED":
        raise HTTPException(409, "Operation was cancelled")
    operation.status = "DISPATCHED"
    operation.attempts += 1
    lease = db.get(ReconciliationLease, operation.id)
    if lease is None:
        db.add(ReconciliationLease(operation_id=operation.id, available_at=now() + timedelta(seconds=60)))
    return operation


def save_failure(db, owner, operation_id, payment_id, error, result=None):
    owner, payment = lock_payment(db, payment_id)
    operation = db.get(Operation, operation_id)
    db.refresh(operation, with_for_update=True)
    if operation.status == "COMPLETED" or payment.status == "CAPTURED":
        db.commit()
        return
    ambiguous = error.ambiguous or operation.status == "UNKNOWN"
    operation.status = "UNKNOWN" if ambiguous else "FAILED"
    if ambiguous:
        payment.status = "UNKNOWN"
    elif operation.kind == "CAPTURE":
        payment.status = "ORDER_CREATED"
    elif operation.kind == "CREATE" and (operation.request_payload or {}).get("mode") == "VAULT_CHARGE" and not payment.provider_order_id:
        payment.status = "RESERVED"
    if result and result.get("id"):
        operation.result = {"id": result["id"], "status": result.get("status")}
        if operation.kind == "CREATE" and not payment.provider_order_id:
            payment.provider_order_id = result["id"]
    append(db, owner, "PROVIDER_OPERATION_UNRESOLVED" if ambiguous else "PROVIDER_OPERATION_FAILED", payment.id,
           {"operation_id": operation.id, "kind": operation.kind, "code": error.code,
            "reservation_retained": True, **error_diagnostic_fields(error)})
    db.commit()


def _payee_mismatch(result):
    expected = (os.getenv("PAYPAL_MERCHANT_ID") or "").strip()
    units = result.get("purchase_units") if isinstance(result, dict) else None
    if not expected or not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], dict):
        return False
    payee = units[0].get("payee")
    return isinstance(payee, dict) and str(payee.get("merchant_id") or "").strip() != expected


@router.get("")
def listing(owner=Depends(human), db: DBSession = Depends(get_db)):
    return [payment_view(row, db) for row in db.scalars(select(Payment).where(Payment.session_id == owner.id).order_by(Payment.created_at.desc()))]


@router.post("/{payment_id}/cancel")
def cancel(payment_id: str, owner=Depends(human), db: DBSession = Depends(get_db)):
    payment, grant, proposal = payment_context(db, owner, payment_id)
    if payment.status == "RELEASED":
        return payment_view(payment, db)
    operation = db.scalar(select(Operation).where(Operation.payment_id == payment.id, Operation.kind == "CREATE").with_for_update())
    if payment.status != "RESERVED" or not operation or operation.status != "WAITING" or operation.attempts != 0:
        raise HTTPException(409, "Only a reservation that has never been dispatched can be cancelled")
    payment.status, operation.status, proposal.status = "RELEASED", "CANCELLED", "CANCELLED"
    grant.reserved_cents -= payment.amount_cents
    append(db, owner, "RESERVATION_RELEASED", payment.id, {"reason": "Cancelled before dispatch", "amount_cents": payment.amount_cents})
    return payment_view(payment, db)


@router.post("/{payment_id}/checkout")
async def checkout(payment_id: str, owner=Depends(human), db: DBSession = Depends(get_db)):
    payment, grant, proposal = payment_context(db, owner, payment_id)
    if payment.status in {"ORDER_CREATED", "CAPTURED"}:
        return payment_view(payment, db)
    if payment.status != "RESERVED":
        raise HTTPException(409, "Payment is not ready for checkout")
    dispatch_guard(db, grant, proposal, payment)
    async with configured_client() as client:
        if not client.configured:
            raise HTTPException(503, "PayPal sandbox credentials and merchant are not configured; reservation remains local")
        payload = {"cart": proposal.cart, "return_url": PUBLIC_BASE_URL + "/?checkout=approved",
                   "cancel_url": PUBLIC_BASE_URL + "/?checkout=cancelled", "merchant_id": os.getenv("PAYPAL_MERCHANT_ID")}
        operation = begin_operation(db, payment, "CREATE", payload)
        append(db, owner, "ORDER_DISPATCHED", payment.id, {"operation_id": operation.id, "cart_hash": proposal.cart_hash})
        request_id, operation_id = operation.request_id, operation.id
        db.commit()
        result = None
        try:
            result = await client.create_order(payload["cart"], request_id, payload["return_url"], payload["cancel_url"])
            if not settle_order(db, operation_id, result):
                if _payee_mismatch(result):
                    raise PayPalError("Payee mismatch on created order", code="PAYEE_MISMATCH", ambiguous=True)
                raise PayPalError("Order response needs reconciliation", code="INVALID_ORDER_RESPONSE", ambiguous=True)
        except PayPalError as error:
            save_failure(db, owner, operation_id, payment_id, error, result)
            raise HTTPException(502, provider_failure_message(error, "PayPal checkout failed; reservation retained for review")) from None
        return payment_view(payment, db)


@router.post("/{payment_id}/capture")
async def capture(payment_id: str, owner=Depends(human), db: DBSession = Depends(get_db)):
    payment, grant, proposal = payment_context(db, owner, payment_id)
    if payment.status == "CAPTURED":
        return payment_view(payment, db)
    if payment.status != "ORDER_CREATED" or not payment.provider_order_id:
        raise HTTPException(409, "Payment needs a buyer-approved PayPal order")
    dispatch_guard(db, grant, proposal, payment)
    async with configured_client() as client:
        if not client.configured:
            raise HTTPException(503, "PayPal sandbox is not configured")
        operation = begin_operation(db, payment, "CAPTURE", {"order_id": payment.provider_order_id,
                                    "cart_hash": proposal.cart_hash, "merchant_id": os.getenv("PAYPAL_MERCHANT_ID")})
        payment.status = "CAPTURE_PENDING"
        append(db, owner, "CAPTURE_DISPATCHED", payment.id, {"operation_id": operation.id, "provider_order_id": payment.provider_order_id})
        order_id, operation_id, request_id = payment.provider_order_id, operation.id, operation.request_id
        db.commit()
        result = None
        try:
            result = await client.capture_order(order_id, request_id)
            confirmed = capture_from_order(result, payment)
            if confirmed is None:
                if _payee_mismatch(result):
                    raise PayPalError("Payee mismatch on captured order", code="PAYEE_MISMATCH", ambiguous=True)
                raise PayPalError("Capture requires reconciliation", code="UNCONFIRMED_CAPTURE", ambiguous=True)
        except PayPalError as error:
            save_failure(db, owner, operation_id, payment_id, error, result)
            raise HTTPException(502, provider_failure_message(error, "Capture has no confirmed success; reservation retained")) from None
        if not settle_capture(db, payment_id, result):
            raise HTTPException(409, "Capture result requires reconciliation; reservation retained")
        payment = db.get(Payment, payment_id)
        return payment_view(payment, db)


@router.post("/{payment_id}/vault-charge")
async def vault_charge(payment_id: str, owner=Depends(human), db: DBSession = Depends(get_db)):
    payment, grant, proposal = payment_context(db, owner, payment_id)
    if payment.status == "CAPTURED":
        return payment_view(payment, db)
    if payment.status != "RESERVED":
        raise HTTPException(409, "Payment is not ready for autonomous vault charge")
    if grant.vault_status != "GRANTED" or not grant.vault_token_ref:
        raise HTTPException(409, "Grant does not have an active PayPal vault token")
    dispatch_guard(db, grant, proposal, payment)
    try:
        vault_token = decrypt_vault_token(grant.vault_token_ref)
    except VaultConfigError as exc:
        raise HTTPException(503, str(exc)) from exc
    async with configured_client() as client:
        if not client.configured:
            raise HTTPException(503, "PayPal sandbox credentials and merchant are not configured; reservation remains local")
        payload = {"cart": proposal.cart, "merchant_id": os.getenv("PAYPAL_MERCHANT_ID"), "mode": "VAULT_CHARGE"}
        operation = begin_operation(db, payment, "CREATE", payload)
        payment.status = "CAPTURE_PENDING"
        append(db, owner, "VAULT_CHARGE_DISPATCHED", payment.id,
               {"operation_id": operation.id, "cart_hash": proposal.cart_hash, "vault_id": mask_token(vault_token)})
        request_id, operation_id = operation.request_id, operation.id
        db.commit()
        result = None
        try:
            result = await client.charge_vault(payload["cart"], vault_token, request_id)
            order_id = result.get("id")
            if not isinstance(order_id, str) or not order_id or (payment.provider_order_id and payment.provider_order_id != order_id):
                raise PayPalError("Vault charge order requires reconciliation", code="INVALID_ORDER_RESPONSE", ambiguous=True)
            payment.provider_order_id = order_id
            db.flush()
            if capture_from_order(result, payment) is None or not settle_capture(db, payment_id, result):
                if _payee_mismatch(result):
                    raise PayPalError("Payee mismatch on vaulted order", code="PAYEE_MISMATCH", ambiguous=True)
                raise PayPalError("Vault charge capture requires reconciliation", code="UNCONFIRMED_CAPTURE", ambiguous=True)
            op = db.get(Operation, operation_id)
            op.status, op.result = "COMPLETED", {"id": order_id, "status": "COMPLETED"}
        except PayPalError as error:
            save_failure(db, owner, operation_id, payment_id, error, result)
            raise HTTPException(502, provider_failure_message(error, "Autonomous vault charge has no confirmed success; reservation retained")) from None
        payment = db.get(Payment, payment_id)
        return payment_view(payment, db)
