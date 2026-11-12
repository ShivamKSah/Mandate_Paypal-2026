"""Adversarial money-path tests; provider responses are explicit fixtures."""
import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from mandate.models import Case, Mandate, Operation, Payment, now
from mandate.payments.paypal import PayPalError
from mandate.settlement import settle_capture, settle_refund
from test_money_flow import captured, provider, purchase


def make_case(client, proposal):
    return client.post('/api/cases', json={'payment_id': proposal['payment_id'], 'cause': 'seller_error',
        'evidence': 'Fixture delivery mismatch', 'avoided_freight_cents': 0, 'resale_loss_cents': 0}).json()


def test_late_capture_failure_cannot_revert_reconciled_capture(client, database, provider, monkeypatch):
    mandate, proposal, path = purchase(client)
    assert client.post(path + '/checkout').status_code == 200
    original = provider.capture_order

    async def complete_then_timeout(order_id, request_id):
        result = await original(order_id, request_id)
        with database.begin() as db:
            assert settle_capture(db, proposal['payment_id'], result)
        raise PayPalError('late timeout', code='NETWORK_ERROR', ambiguous=True)

    monkeypatch.setattr(provider, 'capture_order', complete_then_timeout)
    client.post(path + '/capture')
    with database() as db:
        assert db.get(Payment, proposal['payment_id']).status == 'CAPTURED'
        assert db.scalar(select(Operation).where(Operation.kind == 'CAPTURE')).status == 'COMPLETED'
        grant = db.get(Mandate, mandate['id'])
        assert (grant.spent_cents, grant.reserved_cents) == (34900, 0)


@pytest.mark.parametrize('late_failure', [False, True])
def test_refund_response_after_reconciliation_accounts_once(client, database, provider, monkeypatch, late_failure):
    _, proposal, _ = captured(client)
    case = make_case(client, proposal)
    original = provider.refund_capture

    async def complete_before_response(capture_id, amount, request_id):
        result = await original(capture_id, amount, request_id)
        with database.begin() as db:
            operation = db.scalar(select(Operation).where(Operation.kind == 'REFUND'))
            operation.result = {'id': result['id']}
            db.flush()
            assert settle_refund(db, operation.id, result)
        if late_failure:
            raise PayPalError('late definitive error', code='PROVIDER_REJECTED', ambiguous=False)
        return result

    monkeypatch.setattr(provider, 'refund_capture', complete_before_response)
    client.post('/api/cases/' + case['id'] + '/accept', json={'offer_hash': case['offer_hash']})
    with database() as db:
        assert db.get(Case, case['id']).status == 'REFUNDED'
        payment = db.get(Payment, proposal['payment_id'])
        assert (payment.refunded_cents, payment.refund_reserved_cents) == (31410, 0)
        assert db.scalar(select(Operation).where(Operation.kind == 'REFUND')).status == 'COMPLETED'
        events = client.get('/api/ledger').json()
        assert len([event for event in events if event['event_type'] == 'PAYMENT_REFUNDED']) == 1


def test_refund_settlement_refreshes_stale_case(client, database, provider):
    _, proposal, _ = captured(client)
    case = make_case(client, proposal)
    provider.fail_refund = True
    client.post('/api/cases/' + case['id'] + '/accept', json={'offer_hash': case['offer_hash']})
    result = {'id': 'REFUND-1', 'status': 'COMPLETED', 'amount': {'currency_code': 'USD', 'value': '314.10'}}
    with database.begin() as db:
        operation = db.scalar(select(Operation).where(Operation.kind == 'REFUND'))
        operation.result = {'id': result['id']}
        operation_id = operation.id
    with database() as stale:
        stale.get(Case, case['id'])
        stale_case = stale.get(Case, case['id'])
        stale_operation = stale.get(Operation, operation_id)
        with database.begin() as db:
            assert settle_refund(db, operation_id, result)
        assert settle_refund(stale, operation_id, result)
        assert stale_case.status == 'REFUNDED'
        assert stale_operation.status == 'COMPLETED'


def test_lost_create_response_recovers_same_request(client, database, provider, monkeypatch):
    from mandate.reconciliation import reconcile_operation
    _, proposal, path = purchase(client)
    provider.fail_create = True
    assert client.post(path + '/checkout').status_code == 502
    provider.fail_create = False
    monkeypatch.setattr('mandate.reconciliation.SessionLocal', database)
    with database() as db:
        operation_id = db.scalar(select(Operation.id).where(Operation.kind == 'CREATE'))
    assert asyncio.run(reconcile_operation(provider, operation_id))
    assert len(provider.calls) == 2 and provider.calls[0][1] == provider.calls[1][1]
    with database() as db:
        payment = db.get(Payment, proposal['payment_id'])
        assert payment.status == 'ORDER_CREATED' and payment.approval_url


@pytest.mark.parametrize('expired', [False, True])
def test_lost_refund_retries_only_within_retention(client, database, provider, monkeypatch, expired):
    from mandate.reconciliation import reconcile_operation
    _, proposal, _ = captured(client)
    case = make_case(client, proposal)
    provider.fail_refund = True
    assert client.post('/api/cases/' + case['id'] + '/accept', json={'offer_hash': case['offer_hash']}).status_code == 502
    provider.fail_refund = False
    monkeypatch.setattr('mandate.reconciliation.SessionLocal', database)
    with database.begin() as db:
        operation = db.scalar(select(Operation).where(Operation.kind == 'REFUND'))
        operation_id = operation.id
        if expired:
            operation.created_at = now() - timedelta(days=46)
    assert asyncio.run(reconcile_operation(provider, operation_id)) is not expired
    refunds = [call for call in provider.calls if call[0] == 'refund']
    assert len(refunds) == (1 if expired else 2)
    assert all(call[1] == refunds[0][1] for call in refunds)
    with database() as db:
        payment = db.get(Payment, proposal['payment_id'])
        assert (payment.refunded_cents, payment.refund_reserved_cents) == ((0, 31410) if expired else (31410, 0))


def test_verified_webhook_outage_remains_retryable(client, database, provider, monkeypatch):
    from test_reconciliation import webhook_event, webhook_provider
    _, _, path = purchase(client)
    assert client.post(path + '/checkout').status_code == 200
    webhook_provider(provider, monkeypatch)

    async def unavailable(order_id):
        raise PayPalError('lookup outage', code='NETWORK_ERROR')

    monkeypatch.setattr(provider, 'get_order', unavailable)
    response = client.post('/api/webhooks/paypal', json=webhook_event())
    # Non-2xx asks PayPal to redeliver; durable retry also covers a lost redelivery.
    assert response.status_code == 503
    with database() as db:
        from mandate.models import WebhookEvent
        stored = db.get(WebhookEvent, 'EVENT-1')
        assert stored.status == 'RETRY_REQUIRED' and stored.raw_body


@pytest.mark.parametrize('drift', [False, True])
def test_capture_refreshes_only_the_exact_original_quote(client, database, provider, monkeypatch, drift):
    from mandate.catalog import CATALOG
    from mandate.models import Proposal
    _, proposal, path = purchase(client)
    assert client.post(path + '/checkout').status_code == 200
    with database.begin() as db:
        db.get(Proposal, proposal['id']).quote_expires_at = now() - timedelta(seconds=1)
    if drift:
        monkeypatch.setitem(CATALOG, 'desk-160', {**CATALOG['desk-160'], 'unit_price_cents': 35000})
    response = client.post(path + '/capture')
    assert response.status_code == (409 if drift else 200)
    assert len([call for call in provider.calls if call[0] == 'capture']) == (0 if drift else 1)


@pytest.mark.parametrize('tamper', ['payload', 'merchant', 'expired', 'attempts'])
def test_unsafe_unknown_create_retry_stays_reserved(client, database, provider, monkeypatch, tamper):
    from mandate.reconciliation import reconcile_operation
    mandate, proposal, path = purchase(client)
    provider.fail_create = True
    assert client.post(path + '/checkout').status_code == 502
    provider.fail_create = False
    with database.begin() as db:
        operation = db.scalar(select(Operation).where(Operation.kind == 'CREATE'))
        operation_id = operation.id
        if tamper == 'payload':
            operation.request_payload = {**operation.request_payload, 'return_url': 'https://attacker.example'}
        elif tamper == 'expired':
            operation.created_at = now() - timedelta(hours=7)
        elif tamper == 'attempts':
            operation.attempts = 5
    if tamper == 'merchant':
        monkeypatch.setenv('PAYPAL_MERCHANT_ID', 'OTHER-MERCHANT')
    assert not asyncio.run(reconcile_operation(provider, operation_id))
    assert len(provider.calls) == 1
    with database() as db:
        assert db.get(Mandate, mandate['id']).reserved_cents == 34900
        assert db.get(Payment, proposal['payment_id']).status == 'UNKNOWN'


def test_retry_rejection_cannot_release_earlier_unknown_refund(client, database, provider, monkeypatch):
    from mandate.reconciliation import reconcile_operation
    _, proposal, _ = captured(client)
    case = make_case(client, proposal)
    provider.fail_refund = True
    client.post('/api/cases/' + case['id'] + '/accept', json={'offer_hash': case['offer_hash']})

    async def reject(*args):
        raise PayPalError('current request rejected', code='PROVIDER_REJECTED', ambiguous=False)

    monkeypatch.setattr(provider, 'refund_capture', reject)
    with database() as db:
        operation_id = db.scalar(select(Operation.id).where(Operation.kind == 'REFUND'))
    assert not asyncio.run(reconcile_operation(provider, operation_id))
    with database() as db:
        assert db.get(Payment, proposal['payment_id']).refund_reserved_cents == 31410
        assert db.get(Case, case['id']).status == 'UNKNOWN'


def test_verified_webhook_retries_after_restart_without_redelivery(client, database, provider, monkeypatch):
    from mandate.models import WebhookEvent
    from mandate.webhooks import retry_events
    from test_reconciliation import webhook_event, webhook_provider
    mandate, _, path = purchase(client)
    assert client.post(path + '/checkout').status_code == 200
    webhook_provider(provider, monkeypatch)
    original = provider.get_order

    async def unavailable(order_id):
        raise PayPalError('lookup unavailable', code='NETWORK_ERROR')

    monkeypatch.setattr(provider, 'get_order', unavailable)
    assert client.post('/api/webhooks/paypal', json=webhook_event()).status_code == 503
    monkeypatch.setattr(provider, 'get_order', original)
    with database.begin() as db:
        db.get(WebhookEvent, 'EVENT-1').available_at = now() - timedelta(seconds=1)
    asyncio.run(retry_events(provider, database))
    with database() as db:
        assert db.get(WebhookEvent, 'EVENT-1').status == 'PROCESSED'
        assert db.get(Mandate, mandate['id']).spent_cents == 34900


def test_expired_worker_lease_can_be_reclaimed(client, database, provider):
    from mandate.models import ReconciliationLease
    from mandate.reconciliation import claim_operation
    _, _, path = purchase(client)
    provider.fail_create = True
    client.post(path + '/checkout')
    with database.begin() as db:
        operation_id = db.scalar(select(Operation.id).where(Operation.kind == 'CREATE'))
        lease = db.get(ReconciliationLease, operation_id)
        lease.available_at = lease.lease_until = now() - timedelta(seconds=1)
    assert claim_operation() == operation_id
    assert claim_operation() is None
    with database.begin() as db:
        db.get(ReconciliationLease, operation_id).lease_until = now() - timedelta(seconds=1)
    assert claim_operation() == operation_id


def test_concurrent_capture_settlement_counts_money_once(client, database, provider):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    mandate, proposal, path = purchase(client)
    assert client.post(path + '/checkout').status_code == 200
    result = asyncio.run(provider.capture_order('ORDER-1', 'fixture-read'))
    barrier = Barrier(2)

    def settle():
        with database.begin() as db:
            payment = db.get(Payment, proposal['payment_id'])
            grant = db.get(Mandate, mandate['id'])
            barrier.wait(timeout=5)
            assert settle_capture(db, payment.id, result)
            return grant.spent_cents

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(settle) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)
    with database() as db:
        grant = db.get(Mandate, mandate['id'])
        assert (grant.spent_cents, grant.reserved_cents) == (34900, 0)
    events = client.get('/api/ledger').json()
    assert sum(event['event_type'] == 'PAYMENT_CAPTURED' for event in events) == 1


def test_late_initial_refund_rejection_cannot_clear_inflight_retry(client, database, provider, monkeypatch):
    _, proposal, _ = captured(client)
    case = make_case(client, proposal)

    async def retry_started_before_rejection(*args):
        with database.begin() as db:
            operation = db.scalar(select(Operation).where(Operation.kind == 'REFUND'))
            operation.status, operation.attempts = 'UNKNOWN', 2
        raise PayPalError('initial request rejected', code='PROVIDER_REJECTED', ambiguous=False)

    monkeypatch.setattr(provider, 'refund_capture', retry_started_before_rejection)
    assert client.post('/api/cases/' + case['id'] + '/accept', json={'offer_hash': case['offer_hash']}).status_code == 502
    with database() as db:
        assert db.get(Payment, proposal['payment_id']).refund_reserved_cents == 31410
        assert db.get(Case, case['id']).status == 'UNKNOWN'


def test_forged_webhook_verification_is_rate_limited(client, provider, monkeypatch):
    from mandate.rate_limits import consume
    from test_reconciliation import webhook_event, webhook_provider
    webhook_provider(provider, monkeypatch, verified=False)
    calls = []
    original = provider.verify_webhook

    async def verify(headers, event, *, raw_body=None):
        calls.append(event['id'])
        return await original(headers, event, raw_body=raw_body)

    monkeypatch.setattr(provider, 'verify_webhook', verify)
    monkeypatch.setattr('mandate.webhooks.consume', lambda db, scope, identity, limit: consume(db, scope, identity, 1))
    assert client.post('/api/webhooks/paypal', json=webhook_event()).status_code == 400
    assert client.post('/api/webhooks/paypal', json=webhook_event()).status_code == 429
    assert len(calls) == 1


@pytest.mark.parametrize('provider_status', ['PARTIALLY_REFUNDED', 'REFUNDED'])
def test_late_capture_webhook_after_refund_is_idempotent(client, database, provider, monkeypatch, provider_status):
    from test_reconciliation import webhook_event, webhook_provider
    mandate, proposal, _ = captured(client)
    case = make_case(client, proposal)
    assert client.post('/api/cases/' + case['id'] + '/accept', json={'offer_hash': case['offer_hash']}).status_code == 200
    webhook_provider(provider, monkeypatch)
    original = provider.get_order

    async def refunded_order(order_id):
        result = await original(order_id)
        result['purchase_units'][0]['payments']['captures'][0]['status'] = provider_status
        return result

    monkeypatch.setattr(provider, 'get_order', refunded_order)
    response = client.post('/api/webhooks/paypal', json=webhook_event())
    assert response.status_code == 200 and response.json()['status'] == 'processed'
    with database() as db:
        grant = db.get(Mandate, mandate['id'])
        assert (grant.spent_cents, grant.reserved_cents) == (34900, 0)
        payment = db.get(Payment, proposal['payment_id'])
        assert (payment.refunded_cents, payment.refund_reserved_cents) == (31410, 0)
    assert client.get('/api/ledger/verify').json()['valid']
