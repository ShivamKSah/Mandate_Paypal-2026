import os
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .audit import append, digest
from .db import get_db
from .models import Case, Operation, Payment, ReconciliationLease, now
from .payments.paypal import PayPalError
from .payments_api import configured_client, provider_failure_message
from .schemas import AcceptInput, CaseInput, EmptyInput
from .security import human, owned
from .settlement import lock_payment, offer_digest, settle_refund

router = APIRouter(prefix="/api/cases")
BANDS = {"seller_error": (90, 100), "ambiguous_listing": (40, 70), "agent_error": (70, 100), "vague_instruction": (0, 30)}


def case_view(case):
    return {key: getattr(case, key) for key in ("id", "payment_id", "status", "cause", "evidence", "offer_cents", "offer_hash", "explanation", "created_at")}


@router.get("")
def listing(owner=Depends(human), db: DBSession = Depends(get_db)):
    return [case_view(row) for row in db.scalars(select(Case).where(Case.session_id == owner.id).order_by(Case.created_at.desc()))]


@router.post("")
def create(body: CaseInput, owner=Depends(human), db: DBSession = Depends(get_db)):
    payment = owned(db, Payment, body.payment_id, owner, lock=True)
    if payment.status != "CAPTURED":
        raise HTTPException(409, "Recovery requires a confirmed captured payment")
    active = db.scalar(select(Case.id).where(Case.payment_id == payment.id, Case.status.not_in(["REJECTED", "REFUNDED", "REFUND_FAILED"])))
    if active:
        raise HTTPException(409, "Payment already has an active case")
    remaining = payment.amount_cents - payment.refunded_cents - payment.refund_reserved_cents
    if remaining <= 0:
        raise HTTPException(409, "No refundable balance remains")
    low, high = BANDS[body.cause]
    economics = body.avoided_freight_cents + body.resale_loss_cents
    amount = min(remaining, max(payment.amount_cents * low // 100, min(economics, payment.amount_cents * high // 100)))
    explanation = f"Human-selected {body.cause}; demo merchant policy {low}-{high}%. Avoided freight plus resale loss totals {economics} cents; offer is clamped to the policy band and remaining captured balance. This is a policy assumption, not a model decision."
    case = Case(session_id=owner.id, payment_id=payment.id, cause=body.cause, evidence=body.evidence,
                offer_cents=amount, explanation=explanation, offer_hash=digest({"payment_id": payment.id, "cause": body.cause,
                "evidence": body.evidence, "offer_cents": amount, "policy_version": 1}))
    db.add(case)
    db.flush()
    append(db, owner, "RECOVERY_PROPOSED", case.id, {"payment_id": payment.id, "offer_cents": amount, "offer_hash": case.offer_hash})
    return case_view(case)


@router.post("/{case_id}/reject")
def reject(case_id: str, body: EmptyInput, owner=Depends(human), db: DBSession = Depends(get_db)):
    case = owned(db, Case, case_id, owner, lock=True)
    if case.status == "REJECTED":
        return case_view(case)
    if case.status != "PROPOSED":
        raise HTTPException(409, "Only an unaccepted offer can be rejected")
    case.status = "REJECTED"
    append(db, owner, "RECOVERY_REJECTED", case.id, {"offer_hash": case.offer_hash})
    return case_view(case)


@router.post("/{case_id}/accept")
async def accept(case_id: str, body: AcceptInput, owner=Depends(human), db: DBSession = Depends(get_db)):
    case = owned(db, Case, case_id, owner, lock=True)
    if body.offer_hash != case.offer_hash or offer_digest(case) != case.offer_hash:
        raise HTTPException(409, "Offer hash mismatch")
    if case.status in {"REFUNDED", "REFUND_PENDING", "UNKNOWN", "ACCEPTED"}:
        return case_view(case)
    if case.status != "PROPOSED":
        raise HTTPException(409, "Offer cannot be accepted in its current state")
    payment = owned(db, Payment, case.payment_id, owner, lock=True)
    if payment.status != "CAPTURED" or not payment.provider_capture_id:
        raise HTTPException(409, "Payment has no refundable confirmed capture")
    if case.offer_cents <= 0:
        case.status = "ACCEPTED"
        append(db, owner, "RECOVERY_ACCEPTED", case.id, {"offer_hash": case.offer_hash, "offer_cents": 0})
        return case_view(case)
    if case.offer_cents > payment.amount_cents - payment.refunded_cents - payment.refund_reserved_cents:
        raise HTTPException(409, "Refundable balance has changed")
    async with configured_client() as client:
        if not client.configured:
            raise HTTPException(503, "PayPal sandbox is not configured; no refund sent")
        payload = {"capture_id": payment.provider_capture_id, "amount_cents": case.offer_cents,
                   "offer_hash": case.offer_hash, "merchant_id": os.getenv("PAYPAL_MERCHANT_ID")}
        operation = Operation(payment_id=payment.id, kind="REFUND", entity_key=case.id, payload_hash=digest(payload),
                              request_payload=payload, status="DISPATCHED", attempts=1)
        db.add(operation)
        db.flush()
        db.add(ReconciliationLease(operation_id=operation.id, available_at=now() + timedelta(seconds=60)))
        payment.refund_reserved_cents += case.offer_cents
        case.status = "REFUND_PENDING"
        append(db, owner, "REFUND_DISPATCHED", case.id, {"offer_hash": case.offer_hash, "amount_cents": case.offer_cents, "operation_id": operation.id})
        operation_id, capture_id, amount, request_id = operation.id, payment.provider_capture_id, case.offer_cents, operation.request_id
        db.commit()
        result = None
        try:
            result = await client.refund_capture(capture_id, amount, request_id)
            expected = {"currency_code": "USD", "value": f"{amount // 100}.{amount % 100:02d}"}
            if result.get("status") != "COMPLETED" or not result.get("id") or result.get("amount") != expected:
                raise PayPalError("Refund needs reconciliation", code="UNCONFIRMED_REFUND", ambiguous=True)
        except PayPalError as error:
            owner, payment = lock_payment(db, payment.id)
            db.refresh(case, with_for_update=True)
            operation = db.get(Operation, operation_id)
            db.refresh(operation, with_for_update=True)
            if operation.status == "COMPLETED" or case.status == "REFUNDED":
                return case_view(case)
            if result and result.get("id"):
                operation.result = {"id": result["id"], "status": result.get("status")}
            ambiguous = error.ambiguous or operation.status == "UNKNOWN"
            operation.status = case.status = "UNKNOWN" if ambiguous else "REFUND_FAILED"
            if not ambiguous:
                payment.refund_reserved_cents -= amount
            append(db, owner, "REFUND_UNRESOLVED" if ambiguous else "REFUND_FAILED", case.id,
                   {"operation_id": operation_id, "code": error.code, "provider_status": error.status_code,
                    "provider_issue": error.issue, "reservation_retained": ambiguous})
            db.commit()
            raise HTTPException(502, provider_failure_message(error, "Refund has no confirmed success; review its recorded state")) from None
        if not settle_refund(db, operation_id, result):
            raise HTTPException(409, "Refund result requires reconciliation; reservation retained")
        return case_view(case)
