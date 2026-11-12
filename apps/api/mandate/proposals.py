from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .audit import append, digest
from .catalog import quote
from .constraints import constraints_to_dict, extract_constraints
from .db import get_db
from .models import Mandate, Operation, Payment, Proposal, now
from .policy import evaluate
from .schemas import ApprovalInput, ProposalInput
from .security import human, owned

router = APIRouter(prefix="/api/proposals")


def view(db, proposal):
    payment = db.scalar(select(Payment).where(Payment.proposal_id == proposal.id))
    return {"id": proposal.id, "mandate_id": proposal.mandate_id,
            "decision": proposal.decision, "status": proposal.status,
            "total_cents": proposal.cart["total_cents"], "currency": proposal.cart["currency"],
            "cart_hash": proposal.cart_hash, "rules": proposal.rules,
            "items": proposal.cart["items"], "created_at": proposal.created_at,
            "expires_at": proposal.expires_at, "quote_expires_at": proposal.quote_expires_at,
            "grant_version": proposal.grant_version,
            "payment_id": payment.id if payment else None}


def reserve(db, owner, grant, proposal):
    grant.reserved_cents += proposal.cart["total_cents"]
    payment = Payment(session_id=owner.id, mandate_id=grant.id, proposal_id=proposal.id, amount_cents=proposal.cart["total_cents"])
    db.add(payment)
    db.flush()
    # Durable work waits for the explicit buyer-present checkout action.
    db.add(Operation(payment_id=payment.id, kind="CREATE", payload_hash=proposal.cart_hash))
    append(db, owner, "PAYMENT_RESERVED", payment.id, {"proposal_id": proposal.id, "amount_cents": payment.amount_cents})


def submit(db, owner, body: ProposalInput, *, extracted_constraints=None, extraction_failed: bool = False):
    grant = owned(db, Mandate, body.mandate_id, owner, lock=True)
    payload_hash = digest(body.model_dump())
    existing = db.scalar(select(Proposal).where(Proposal.mandate_id == grant.id, Proposal.purchase_intent_id == body.purchase_intent_id))
    if existing:
        if existing.payload_hash != payload_hash:
            raise HTTPException(409, "Purchase intent already exists with a different payload")
        return existing
    if extracted_constraints is None and not extraction_failed and body.instruction:
        extracted_constraints, extraction_failed = constraints_to_dict(extract_constraints(body.instruction))
    cart, missing = quote(body.items, body.currency)
    decision, rules = evaluate(
        db, grant, cart, missing,
        claimed_total=body.claimed_total_cents,
        extracted_constraints=extracted_constraints,
        extraction_failed=extraction_failed,
    )
    proposal = Proposal(session_id=owner.id, mandate_id=grant.id, purchase_intent_id=body.purchase_intent_id,
                        payload_hash=payload_hash, cart=cart, cart_hash=digest(cart), grant_version=grant.version,
                        decision=decision, status={"APPROVE": "APPROVED", "ESCALATE": "ESCALATED", "DENY": "DENIED"}[decision],
                        rules=rules, expires_at=now() + timedelta(minutes=5), quote_expires_at=now() + timedelta(seconds=60))
    db.add(proposal)
    db.flush()
    append(db, owner, "PROPOSAL_DECIDED", proposal.id, {"decision": decision, "cart_hash": proposal.cart_hash, "rules": rules})
    if decision == "APPROVE":
        reserve(db, owner, grant, proposal)
    return proposal


@router.post("")
def create(body: ProposalInput, owner=Depends(human), db: DBSession = Depends(get_db)):
    return view(db, submit(db, owner, body))


@router.get("")
def listing(owner=Depends(human), db: DBSession = Depends(get_db)):
    return [view(db, row) for row in db.scalars(select(Proposal).where(Proposal.session_id == owner.id).order_by(Proposal.created_at.desc()))]


@router.get("/{proposal_id}")
def get(proposal_id: str, owner=Depends(human), db: DBSession = Depends(get_db)):
    return view(db, owned(db, Proposal, proposal_id, owner))


@router.post("/{proposal_id}/approve")
def approve(proposal_id: str, body: ApprovalInput, owner=Depends(human), db: DBSession = Depends(get_db)):
    proposal = owned(db, Proposal, proposal_id, owner, lock=True)
    grant = owned(db, Mandate, proposal.mandate_id, owner, lock=True)
    if body.cart_hash != proposal.cart_hash or digest(proposal.cart) != proposal.cart_hash:
        raise HTTPException(409, "Cart hash mismatch")
    if proposal.decision == "DENY":
        raise HTTPException(409, "A human cannot waive a hard denial")
    if proposal.status == "APPROVED":
        return view(db, proposal)
    if proposal.status != "ESCALATED" or proposal.expires_at <= now() or proposal.quote_expires_at <= now() or proposal.grant_version != grant.version:
        raise HTTPException(409, "Proposal or quote expired; submit a fresh purchase intent")
    decision, rules = evaluate(db, grant, proposal.cart, [], proposal_id=proposal.id, human_approved=True)
    if decision != "APPROVE":
        raise HTTPException(409, "Current policy no longer permits approval")
    proposal.decision, proposal.status, proposal.rules, proposal.human_approved = decision, "APPROVED", rules, True
    append(db, owner, "HUMAN_APPROVED", proposal.id, {"cart_hash": proposal.cart_hash})
    reserve(db, owner, grant, proposal)
    return view(db, proposal)
