import json
from datetime import timedelta
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DBSession

from .audit import append, digest
from .db import get_db
from .models import Case, Operation, Payment, WebhookEvent, now
from .payments.paypal import PayPalClient, PayPalError
from .rate_limits import consume
from .settlement import capture_from_order, lock_payment, settle_capture, settle_refund

router = APIRouter(prefix='/api/webhooks')


def _parse_usd_cents(amount):
    if not isinstance(amount, dict) or amount.get('currency_code') != 'USD':
        return None
    value = amount.get('value')
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d{2}', value):
        return None
    dollars, cents = value.split('.')
    total = int(dollars) * 100 + int(cents)
    return total if total > 0 else None


def _extract_capture_id(resource, refund_res):
    for obj in (refund_res, resource):
        if not isinstance(obj, dict):
            continue
        related = obj.get('supplementary_data', {}).get('related_ids', {})
        if isinstance(related, dict) and isinstance(related.get('capture_id'), str) and related['capture_id']:
            return related['capture_id']
        for link in obj.get('links', []):
            if isinstance(link, dict) and link.get('rel') == 'up' and isinstance(link.get('href'), str):
                match = re.search(r'/captures/([A-Za-z0-9-]+)', link['href'])
                if match:
                    return match.group(1)
    return None


async def process_event(client, db, event_id):
    stored = db.scalar(select(WebhookEvent).where(WebhookEvent.provider_event_id == event_id).with_for_update().execution_options(populate_existing=True))
    if stored.status in {'PROCESSED', 'IGNORED'}:
        return stored.status
    if stored.available_at > now():
        db.commit()
        return 'RETRY_REQUIRED'
    stored.available_at = now() + timedelta(seconds=120)
    stored.attempts += 1
    event = stored.payload
    resource = event.get('resource', {})
    supplementary = resource.get('supplementary_data', {})
    related = supplementary.get('related_ids', {}) if isinstance(supplementary, dict) else {}
    order_id = related.get('order_id') if isinstance(related, dict) else None
    payment = db.scalar(select(Payment).where(Payment.provider_order_id == order_id)) if isinstance(order_id, str) else None
    payment_id = payment.id if payment else None
    db.commit()
    status = 'IGNORED'
    if event['event_type'] == 'PAYMENT.CAPTURE.COMPLETED':
        status = 'RETRY_REQUIRED'
        if payment_id:
            try:
                result = await client.get_order(order_id)
            except PayPalError:
                result = None
            if result:
                payment = db.get(Payment, payment_id)
                capture = capture_from_order(result, payment)
                matches = capture and resource.get('status') == 'COMPLETED' and all(resource.get(key) == capture.get(key) for key in ('id', 'amount'))
                if matches and settle_capture(db, payment_id, result):
                    status = 'PROCESSED'
    elif event['event_type'] == 'PAYMENT.CAPTURE.REFUNDED':
        status = 'RETRY_REQUIRED'
        refund_id = resource.get('id')
        if isinstance(refund_id, str) and refund_id:
            try:
                refund_res = await client.get_refund(refund_id)
            except PayPalError:
                refund_res = None
            refund_cents = _parse_usd_cents(refund_res.get('amount')) if refund_res else None
            matches = (
                refund_res
                and refund_res.get('id') == refund_id
                and refund_res.get('status') == 'COMPLETED'
                and resource.get('status') == 'COMPLETED'
                and refund_cents is not None
                and refund_res.get('amount') == resource.get('amount')
            )
            if matches:
                capture_id = _extract_capture_id(resource, refund_res)
                target_payment = db.scalar(select(Payment).where(Payment.provider_capture_id == capture_id)) if capture_id else None
                if target_payment is None:
                    op_match = next(
                        (op for op in db.scalars(select(Operation).where(Operation.kind == 'REFUND'))
                         if (op.result or {}).get('id') == refund_id),
                        None,
                    )
                    if op_match:
                        target_payment = db.get(Payment, op_match.payment_id)
                if target_payment is not None:
                    owner, locked_payment = lock_payment(db, target_payment.id)
                    refund_ops = list(db.scalars(select(Operation).where(
                        Operation.payment_id == locked_payment.id, Operation.kind == 'REFUND',
                    ).with_for_update()))
                    if any(op.status == 'COMPLETED' and (op.result or {}).get('id') == refund_id for op in refund_ops):
                        status = 'PROCESSED'
                    else:
                        pending_case = db.scalar(select(Case).where(
                            Case.payment_id == locked_payment.id,
                            Case.status.in_(['REFUND_PENDING', 'UNKNOWN']),
                            Case.offer_cents == refund_cents,
                        ).with_for_update())
                        pending_op = next(
                            (op for op in refund_ops if pending_case and op.entity_key == pending_case.id),
                            None,
                        )
                        if pending_op and settle_refund(db, pending_op.id, refund_res):
                            status = 'PROCESSED'
                        elif (locked_payment.status == 'CAPTURED'
                              and locked_payment.refunded_cents + locked_payment.refund_reserved_cents + refund_cents <= locked_payment.amount_cents):
                            db.add(Operation(
                                payment_id=locked_payment.id,
                                kind='REFUND',
                                entity_key=f'webhook:{refund_id}',
                                payload_hash=digest({'refund_id': refund_id, 'amount_cents': refund_cents}),
                                status='COMPLETED',
                                result={'id': refund_id, 'status': 'COMPLETED'},
                            ))
                            locked_payment.refunded_cents += refund_cents
                            append(db, owner, 'PAYMENT_REFUNDED', locked_payment.id, {
                                'payment_id': locked_payment.id,
                                'amount_cents': refund_cents,
                                'provider_refund_id': refund_id,
                                'source': 'webhook',
                            })
                            status = 'PROCESSED'
                    db.commit()
    stored = db.scalar(select(WebhookEvent).where(WebhookEvent.provider_event_id == event_id).with_for_update().execution_options(populate_existing=True))
    if stored.status not in {'PROCESSED', 'IGNORED'}:
        stored.status = status
        stored.available_at = now() + timedelta(seconds=min(30 * 2 ** min(stored.attempts, 5), 900))
    db.commit()
    return stored.status


async def retry_events(client, session_factory):
    with session_factory() as db:
        event_ids = list(db.scalars(select(WebhookEvent.provider_event_id).where(
            WebhookEvent.status.in_(['VERIFIED', 'RETRY_REQUIRED']), WebhookEvent.available_at <= now()).order_by(WebhookEvent.available_at).limit(10)))
    for event_id in event_ids:
        with session_factory() as db:
            await process_event(client, db, event_id)


@router.post('/paypal')
async def paypal(request: Request, db: DBSession = Depends(get_db)):
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(413, 'Webhook body is too large')
    try:
        raw_body = body.decode('utf-8')
        event = json.loads(raw_body)
        if not isinstance(event, dict) or not isinstance(event.get('id'), str) or not 1 <= len(event['id']) <= 100:
            raise ValueError
        if not isinstance(event.get('event_type'), str) or not 1 <= len(event['event_type']) <= 100 or not isinstance(event.get('resource', {}), dict):
            raise ValueError
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(400, 'Invalid webhook event') from None
    async with PayPalClient() as client:
        if not client.configured or client.missing_environment(include_webhook=True):
            raise HTTPException(503, 'PayPal webhook verification is not configured')
        try:
            consume(db, 'paypal-webhook', 'verification', 60)
        except HTTPException:
            db.commit()
            raise
        db.commit()
        try:
            verification = await client.verify_webhook(dict(request.headers), event, raw_body=raw_body)
        except PayPalError:
            raise HTTPException(503, 'Webhook verification unavailable; event has not been accepted') from None
        if verification.get('verification_status') != 'SUCCESS':
            raise HTTPException(400, 'Invalid PayPal webhook signature')
        db.execute(insert(WebhookEvent).values(provider_event_id=event['id'], event_type=event['event_type'],
                   payload=event, raw_body=raw_body, status='VERIFIED').on_conflict_do_nothing())
        stored = db.get(WebhookEvent, event['id'])
        if digest(stored.payload) != digest(event):
            raise HTTPException(409, 'Webhook event ID has different content')
        if stored.status in {'PROCESSED', 'IGNORED'}:
            return {'status': 'duplicate'}
        db.commit()
        status = await process_event(client, db, event['id'])
        if status == 'RETRY_REQUIRED':
            # The verified event is durable before asking PayPal to redeliver it.
            raise HTTPException(503, 'Verified webhook awaits reconciliation')
        return {'status': status.lower()}
