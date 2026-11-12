import asyncio
import logging
import os
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from .audit import append, digest
from .db import SessionLocal
from .models import Case, Mandate, Operation, Payment, Proposal, ReconciliationLease, now
from .payments.paypal import PayPalClient, PayPalError
from .settlement import lock_payment, offer_digest, settle_capture, settle_order, settle_refund
from .vault import VaultConfigError, decrypt_vault_token
from .webhooks import retry_events

logger = logging.getLogger(__name__)
UNRESOLVED = ('DISPATCHED', 'UNKNOWN')
# Orders retain request IDs for six hours; leave an hour for skew and network delay.
RETRY_WINDOW = timedelta(hours=5)
MAX_ATTEMPTS = 5


def claim_operation():
    with SessionLocal() as db, db.begin():
        candidates = select(Operation.id, Operation.created_at, Operation.created_at).where(Operation.status.in_(UNRESOLVED))
        db.execute(insert(ReconciliationLease).from_select(['operation_id', 'available_at', 'lease_until'], candidates).on_conflict_do_nothing())
        lease = db.scalar(select(ReconciliationLease).join(Operation, Operation.id == ReconciliationLease.operation_id).where(
            Operation.status.in_(UNRESOLVED), ReconciliationLease.available_at <= now(),
            ReconciliationLease.lease_until <= now()).order_by(ReconciliationLease.available_at).with_for_update(skip_locked=True, of=ReconciliationLease).limit(1))
        if lease is None:
            return None
        lease.lease_until = now() + timedelta(seconds=120)
        return lease.operation_id


def prepare_retry(operation_id):
    with SessionLocal() as db, db.begin():
        operation = db.get(Operation, operation_id)
        owner, payment = lock_payment(db, operation.payment_id)
        db.refresh(operation, with_for_update=True)
        payload = operation.request_payload
        if (operation.status not in UNRESOLVED or operation.attempts >= MAX_ATTEMPTS
                or not now() - RETRY_WINDOW < operation.created_at <= now()
                or not payload or digest(payload) != operation.payload_hash
                or payload.get('merchant_id') != os.getenv('PAYPAL_MERCHANT_ID')):
            return None
        proposal = db.get(Proposal, payment.proposal_id)
        if digest(proposal.cart) != proposal.cart_hash:
            return None
        if operation.kind == 'CREATE':
            if digest(payload.get('cart')) != proposal.cart_hash:
                return None
        elif operation.kind == 'CAPTURE':
            if payload.get('order_id') != payment.provider_order_id or payload.get('cart_hash') != proposal.cart_hash:
                return None
        elif operation.kind == 'REFUND':
            case = db.get(Case, operation.entity_key)
            if (not case or case.payment_id != payment.id or case.status not in {'REFUND_PENDING', 'UNKNOWN'}
                    or offer_digest(case) != case.offer_hash or payload.get('offer_hash') != case.offer_hash
                    or payload.get('amount_cents') != case.offer_cents or payload.get('capture_id') != payment.provider_capture_id):
                return None
        else:
            return None
        operation.status = 'UNKNOWN'
        operation.attempts += 1
        append(db, owner, 'PROVIDER_OPERATION_RETRIED', payment.id,
               {'operation_id': operation.id, 'kind': operation.kind, 'attempt': operation.attempts})
        return payload, operation.request_id


def apply_result(operation_id, result):
    with SessionLocal() as db, db.begin():
        operation = db.get(Operation, operation_id)
        _, payment = lock_payment(db, operation.payment_id)
        db.refresh(operation, with_for_update=True)
        if operation.kind == 'REFUND':
            settled = settle_refund(db, operation_id, result)
        elif operation.kind == 'CAPTURE':
            settled = settle_capture(db, payment.id, result)
        elif (operation.request_payload or {}).get('mode') == 'VAULT_CHARGE':
            if isinstance(result.get('id'), str) and result['id'] and not payment.provider_order_id:
                payment.provider_order_id = result['id']
                db.flush()
            settled = settle_capture(db, payment.id, result)
            if settled:
                operation.status = 'COMPLETED'
                operation.result = {'id': result['id'], 'status': 'COMPLETED'}
        else:
            settled = settle_order(db, operation_id, result)
            if not settled and result.get('id') == payment.provider_order_id:
                settled = settle_capture(db, payment.id, result)
                if settled:
                    operation.status = 'COMPLETED'
        if not settled and operation.status in UNRESOLVED:
            operation.status = 'UNKNOWN'
            if isinstance(result.get('id'), str) and result['id']:
                known_id = (operation.result or {}).get('id')
                if not known_id or known_id == result['id']:
                    operation.result = {'id': result['id'], 'status': result.get('status')}
                    if operation.kind == 'CREATE' and not payment.provider_order_id:
                        payment.provider_order_id = result['id']
            if operation.kind != 'REFUND' and payment.status != 'CAPTURED':
                payment.status = 'UNKNOWN'
        return settled


async def reconcile_operation(client, operation_id):
    with SessionLocal() as db, db.begin():
        operation = db.get(Operation, operation_id)
        if not operation or operation.status not in UNRESOLVED:
            return False
        _, payment = lock_payment(db, operation.payment_id)
        db.refresh(operation, with_for_update=True)
        if operation.status not in UNRESOLVED:
            return False
        kind = operation.kind
        operation.status = 'UNKNOWN'
        if kind == 'REFUND':
            case = db.get(Case, operation.entity_key)
            if case.status == 'REFUND_PENDING':
                case.status = 'UNKNOWN'
        elif payment.status != 'CAPTURED':
            payment.status = 'UNKNOWN'
        provider_id = (operation.result or {}).get('id') if kind == 'REFUND' else payment.provider_order_id
    if provider_id:
        result = await (client.get_refund(provider_id) if kind == 'REFUND' else client.get_order(provider_id))
        if kind == 'CREATE' and not isinstance(result.get('purchase_units'), list):
            return False
        if apply_result(operation_id, result):
            return True
        # Pending provider objects are observed, never replaced with a new mutation.
        if kind != 'CAPTURE' or result.get('status') != 'APPROVED':
            return False
    prepared = prepare_retry(operation_id)
    if prepared is None:
        return False
    payload, request_id = prepared
    try:
        if kind == 'CREATE' and payload.get('mode') == 'VAULT_CHARGE':
            with SessionLocal() as db:
                operation = db.get(Operation, operation_id)
                payment = db.get(Payment, operation.payment_id)
                grant = db.get(Mandate, payment.mandate_id)
                if not grant or grant.status != 'ACTIVE' or grant.vault_status != 'GRANTED' or not grant.vault_token_ref:
                    return False
                vault_token = decrypt_vault_token(grant.vault_token_ref)
            result = await client.charge_vault(payload['cart'], vault_token, request_id)
        elif kind == 'CREATE':
            result = await client.create_order(payload['cart'], request_id, payload['return_url'], payload['cancel_url'])
        elif kind == 'CAPTURE':
            result = await client.capture_order(payload['order_id'], request_id)
        else:
            result = await client.refund_capture(payload['capture_id'], payload['amount_cents'], request_id)
    except (PayPalError, VaultConfigError):
        # A rejection on this retry cannot disprove the earlier unknown outcome.
        return False
    return apply_result(operation_id, result)


async def poll(stop):
    while not stop.is_set():
        try:
            async with PayPalClient() as client:
                if client.configured:
                    operation_id = claim_operation()
                    if operation_id:
                        try:
                            await reconcile_operation(client, operation_id)
                        finally:
                            with SessionLocal() as db, db.begin():
                                lease = db.get(ReconciliationLease, operation_id)
                                operation = db.get(Operation, operation_id)
                                if lease:
                                    delay = min(30 * 2 ** min(operation.attempts, 5), 900)
                                    lease.available_at = lease.lease_until = now() + timedelta(seconds=delay)
                    await retry_events(client, SessionLocal)
        except (PayPalError, OSError, SQLAlchemyError):
            logger.warning('Payment reconciliation unavailable; durable operations will be retried')
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
