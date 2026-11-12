import asyncio
from datetime import timedelta
import hashlib
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .audit import append, event_payload, verify
from .config import PUBLIC_BASE_URL
from .db import get_db
from .models import AuditEvent, Mandate, Operation, Payment, Proposal, now
from .payments.paypal import PayPalClient, PayPalError
from .schemas import GrantCompleteInput, MandateInput
from .security import human, owned
from .settlement import approval_link
from .vault import VaultConfigError, encrypt_vault_token, mask_token, vault_key_configured

router = APIRouter(prefix="/api")


def grant_view(grant):
    return {"id": grant.id, "status": grant.status if grant.expires_at > now() or grant.status != "ACTIVE" else "EXPIRED",
            "budget_cents": grant.budget_cents, "per_transaction_cents": grant.per_transaction_cents,
            "allowed_categories": grant.allowed_categories, "allowed_merchants": grant.allowed_merchants,
            "constraints": grant.constraints, "instruction": grant.instruction, "expires_at": grant.expires_at,
            "velocity_limit": grant.velocity_limit, "spent_cents": grant.spent_cents, "reserved_cents": grant.reserved_cents,
            "available_cents": grant.budget_cents - grant.spent_cents - grant.reserved_cents, "version": grant.version,
            "vault_status": grant.vault_status, "grant_order_id": grant.grant_order_id}


def configured_vault_client():
    return PayPalClient()


def _extract_vault_info(payload):
    vault = payload.get("payment_source", {}).get("paypal", {}).get("attributes", {}).get("vault", {})
    if not isinstance(vault, dict):
        return None, None
    vault_id = vault.get("id")
    vault_state = vault.get("status")
    return (vault_id.strip() if isinstance(vault_id, str) and vault_id.strip() else None), vault_state


def _extract_capture_id(payload):
    units = payload.get("purchase_units", [])
    if not isinstance(units, list):
        return None
    for unit in units:
        if not isinstance(unit, dict):
            continue
        captures = unit.get("payments", {}).get("captures", [])
        if isinstance(captures, list):
            for capture in captures:
                if isinstance(capture, dict) and isinstance(capture.get("id"), str) and capture["id"]:
                    return capture["id"]
    return None


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
    if grant.vault_status in {"PENDING", "GRANTED"} or grant.vault_token_ref is not None:
        grant.vault_status = "REVOKED"
    grant.vault_token_ref = None
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


@router.post("/mandates/{mandate_id}/grant/init")
async def grant_init(mandate_id: str, owner=Depends(human), db: DBSession = Depends(get_db)):
    grant = owned(db, Mandate, mandate_id, owner, lock=True)
    if grant.status != "ACTIVE" or grant.expires_at <= now():
        raise HTTPException(409, "Grant is revoked or expired")
    if grant.vault_status == "GRANTED" and grant.vault_token_ref:
        raise HTTPException(409, "Vault grant is already active")
    if not vault_key_configured():
        raise HTTPException(503, "Configure VAULT_ENCRYPTION_KEY before enabling autonomous vault grants")
    async with configured_vault_client() as client:
        if not client.configured:
            raise HTTPException(503, "PayPal sandbox credentials and merchant are not configured")
        request_id = f"gi-{uuid4().hex[:32]}"
        return_url = PUBLIC_BASE_URL + "/?grant=approved"
        cancel_url = PUBLIC_BASE_URL + "/?grant=cancelled"
        try:
            result = await client.create_vault_setup_order(grant.id, request_id, return_url, cancel_url)
        except PayPalError:
            raise HTTPException(502, "PayPal vault setup failed; verify sandbox configuration and try again") from None
        link = approval_link(result)
        order_id = result.get("id")
        if not isinstance(order_id, str) or not order_id or not link:
            raise HTTPException(502, "PayPal returned an invalid vault approval response")
        grant.vault_status = "PENDING"
        grant.grant_order_id = order_id
        append(db, owner, "GRANT_INITIATED", grant.id, {"order_id": mask_token(order_id)})
        return {"mandate": grant_view(grant), "order_id": order_id, "approval_url": link}


@router.post("/mandates/{mandate_id}/grant/complete")
async def grant_complete(
    mandate_id: str,
    body: GrantCompleteInput = Body(default_factory=GrantCompleteInput),
    owner=Depends(human),
    db: DBSession = Depends(get_db),
):
    grant = owned(db, Mandate, mandate_id, owner, lock=True)
    if grant.status != "ACTIVE" or grant.expires_at <= now():
        raise HTTPException(409, "Grant is revoked or expired")
    if grant.vault_status == "GRANTED" and grant.vault_token_ref:
        return {"mandate": grant_view(grant), "vault_status": "GRANTED", "refund_status": "ALREADY_PROCESSED"}
    order_id = body.order_id or grant.grant_order_id
    if not order_id:
        raise HTTPException(409, "Initialize a vault setup order first")
    if grant.grant_order_id and body.order_id and body.order_id != grant.grant_order_id:
        raise HTTPException(409, "Order ID does not match the grant setup order")
    if not vault_key_configured():
        raise HTTPException(503, "Configure VAULT_ENCRYPTION_KEY before completing a vault grant")
    async with configured_vault_client() as client:
        if not client.configured:
            raise HTTPException(503, "PayPal sandbox credentials and merchant are not configured")
        cap_req = "gc-" + hashlib.sha256(f"{grant.id}:{order_id}".encode()).hexdigest()[:32]
        try:
            result = await client.capture_order(order_id, cap_req)
        except PayPalError as error:
            grant.vault_status = "FAILED"
            append(db, owner, "GRANT_FAILED", grant.id, {"order_id": mask_token(order_id), "code": error.code})
            db.commit()
            raise HTTPException(502, "Could not capture the $1.00 vault setup order; confirm buyer approval in PayPal") from None
        vault_id, vault_state = _extract_vault_info(result)
        capture_id = _extract_capture_id(result)
        for delay in (0.5, 1.0, 2.0):
            if vault_id and vault_state not in {"PENDING"}:
                break
            await asyncio.sleep(delay)
            try:
                polled = await client.get_order(order_id)
            except PayPalError:
                continue
            polled_id, polled_state = _extract_vault_info(polled)
            if polled_id:
                vault_id, vault_state = polled_id, polled_state
            capture_id = capture_id or _extract_capture_id(polled)
        if not vault_id or vault_state in {"PENDING", "FAILED"}:
            grant.vault_status = "FAILED"
            append(db, owner, "GRANT_FAILED", grant.id, {"order_id": mask_token(order_id), "reason": "vault_token_unavailable"})
            db.commit()
            raise HTTPException(409, "PayPal did not return an active vault token for this order")
        try:
            grant.vault_token_ref = encrypt_vault_token(vault_id)
        except VaultConfigError as exc:
            raise HTTPException(503, str(exc)) from exc
        grant.vault_status = "GRANTED"
        grant.grant_order_id = order_id
        refund_status = "SKIPPED"
        refund_id = None
        if capture_id:
            refund_req = "gr-" + hashlib.sha256(f"{grant.id}:{order_id}".encode()).hexdigest()[:32]
            try:
                refund_res = await client.refund_capture(capture_id, 100, refund_req)
                refund_id = refund_res.get("id")
                refund_status = refund_res.get("status", "UNKNOWN")
            except PayPalError:
                refund_status = "FAILED"
        append(db, owner, "GRANT_COMPLETED", grant.id, {
            "order_id": mask_token(order_id),
            "vault_id": mask_token(vault_id),
            "capture_id": mask_token(capture_id),
            "refund_id": mask_token(refund_id),
            "refund_status": refund_status,
        })
        return {
            "mandate": grant_view(grant),
            "vault_status": "GRANTED",
            "masked_vault_id": mask_token(vault_id),
            "refund_status": refund_status,
        }


@router.get("/ledger")
def ledger(owner=Depends(human), db: DBSession = Depends(get_db)):
    return [{**event_payload(row), "row_hash": row.row_hash} for row in db.scalars(select(AuditEvent).where(AuditEvent.session_id == owner.id).order_by(AuditEvent.sequence))]


@router.get("/ledger/verify")
def ledger_verify(owner=Depends(human), db: DBSession = Depends(get_db)):
    return verify(db, owner)
