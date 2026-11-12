from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .audit import append, event_payload, verify
from .db import get_db
from .models import AuditEvent, Mandate, Operation, Payment, Proposal, now
from .schemas import MandateInput
from .security import human, owned

router = APIRouter(prefix="/api")


def grant_view(grant):
    return {"id": grant.id, "status": grant.status if grant.expires_at > now() or grant.status != "ACTIVE" else "EXPIRED",
            "budget_cents": grant.budget_cents, "per_transaction_cents": grant.per_transaction_cents,
            "allowed_categories": grant.allowed_categories, "allowed_merchants": grant.allowed_merchants,
            "constraints": grant.constraints, "instruction": grant.instruction, "expires_at": grant.expires_at,
            "velocity_limit": grant.velocity_limit, "spent_cents": grant.spent_cents, "reserved_cents": grant.reserved_cents,
            "available_cents": grant.budget_cents - grant.spent_cents - grant.reserved_cents, "version": grant.version}


@router.post("/mandates")
def create(body: MandateInput, owner=Depends(human), db: DBSession = Depends(get_db)):
    values = body.model_dump(exclude={"expires_in_minutes"})
    grant = Mandate(session_id=owner.id, expires_at=now() + timedelta(minutes=body.expires_in_minutes), **values)
    db.add(grant)
    db.flush()
    append(db, owner, "MANDATE_CREATED", grant.id, {"budget_cents": grant.budget_cents, "constraints": grant.constraints, "version": grant.version})
    return grant_view(grant)


@router.get("/mandates")
def listing(owner=Depends(human), db: DBSession = Depends(get_db)):
    return [grant_view(row) for row in db.scalars(select(Mandate).where(Mandate.session_id == owner.id).order_by(Mandate.created_at.desc()))]


@router.get("/mandates/{mandate_id}")
def get(mandate_id: str, owner=Depends(human), db: DBSession = Depends(get_db)):
    return grant_view(owned(db, Mandate, mandate_id, owner))


@router.post("/mandates/{mandate_id}/revoke")
def revoke(mandate_id: str, owner=Depends(human), db: DBSession = Depends(get_db)):
    grant = owned(db, Mandate, mandate_id, owner, lock=True)
    if grant.status == "REVOKED":
        return grant_view(grant)
    grant.status = "REVOKED"
    grant.version += 1
    for payment in db.scalars(select(Payment).where(Payment.mandate_id == grant.id, Payment.status == "RESERVED").with_for_update()):
        operation = db.scalar(select(Operation).where(Operation.payment_id == payment.id, Operation.kind == "CREATE").with_for_update())
        if operation and operation.status == "WAITING":
            payment.status, operation.status = "RELEASED", "CANCELLED"
            grant.reserved_cents -= payment.amount_cents
            proposal = db.get(Proposal, payment.proposal_id)
            proposal.status = "CANCELLED"
            append(db, owner, "RESERVATION_RELEASED", payment.id, {"reason": "Revoked before dispatch", "amount_cents": payment.amount_cents})
    append(db, owner, "MANDATE_REVOKED", grant.id, {"version": grant.version})
    return grant_view(grant)


@router.get("/ledger")
def ledger(owner=Depends(human), db: DBSession = Depends(get_db)):
    return [{**event_payload(row), "row_hash": row.row_hash} for row in db.scalars(select(AuditEvent).where(AuditEvent.session_id == owner.id).order_by(AuditEvent.sequence))]


@router.get("/ledger/verify")
def ledger_verify(owner=Depends(human), db: DBSession = Depends(get_db)):
    return verify(db, owner)
