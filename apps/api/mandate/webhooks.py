import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DBSession

from .audit import digest
from .db import get_db
from .models import Payment, WebhookEvent, now
from .payments.paypal import PayPalClient, PayPalError
from .rate_limits import consume
from .settlement import capture_from_order, settle_capture

router = APIRouter(prefix='/api/webhooks')


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
