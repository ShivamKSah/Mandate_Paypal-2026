# Backend implementation record

October 28, 2026. Initial local implementation, PostgreSQL 17.

## Completed locally

- FastAPI application at `mandate.main:app`, with SQLAlchemy and psycopg. Configuration loads the repository `.env`, requires PostgreSQL, and rejects live PayPal endpoints. No SQLite path exists.
- Opaque HttpOnly, SameSite session cookies, per-session CSRF tokens, and server-side ownership checks. Browser human routes reject Authorization headers so an agent capability cannot borrow browser authority. Secure cookies are configurable for HTTPS deployment; local HTTP uses `COOKIE_SECURE=false`.
- Strict integer money and quantity inputs, canonical trusted catalog snapshots, immutable cart hashes, named P01-P11 rules, hard-denial precedence, hash-bound human escalation approval, expiry/version/revocation checks.
- Purchase intents deduplicate under the grant lock. Changed payloads conflict. Grant locking reserves budget and velocity together. A concurrent test submits two exact $300 catalog fixtures against $500 and proves that only one reserves.
- Buyer-present checkout and capture use stored cart data. Separate persisted CREATE/CAPTURE/REFUND identities precede network calls. Transactions close before provider calls. Unknown outcomes retain financial holds and block blind mutation retries. A definitive capture failure permits retry under the same identity after revalidation.
- Confirmed captures move reserved money to gross spent exactly once. Human-selected recovery causes use explicit demo policy bands and supplied evidence/economics. Offer hashes bind amounts and evidence. Human acceptance reserves refundable balance before dispatch; refunds do not restore spending authority.
- Per-session audit serialization and a canonical UTC SHA-256 chain. Verification compares the rows with the persisted session checkpoint. Tests alter an earlier event and detect it.
- A narrow polling worker claims durable reconciliation leases and uses provider GET calls to settle known orders/refunds. It never blindly reissues an unknown create/capture/refund. Capture webhooks require successful PayPal signature verification, known order identity, matching resource data, trusted payee and provider-confirmed exact amount. Duplicate and delayed pending notifications cannot repeat or revert capture accounting.

## Validation

From the repository root, with its PostgreSQL `DATABASE_URL` available through `.env`:

```powershell
$env:PYTHONPATH='apps/api'
.venv/Scripts/python.exe -m pytest apps/api/tests -q
```

Final local run: **82 passed**, one Starlette/httpx deprecation warning. This includes adapter and model-worker tests, policy/accounting integration tests against disposable PostgreSQL schemas, independent review tests, and three narrow reconciliation/webhook tests. Provider responses in these tests are explicitly controlled fixtures, not real PayPal transactions.

## Limits and unverified work

- No PayPal or model credentials were available. Actual sandbox checkout, capture, partial refund, live model run, and real signed webhook evidence remain unverified. Unconfigured checkout returns 503 and its payment stays RESERVED.
- Startup uses `create_all` to bootstrap a fresh schema. There are no versioned schema migrations or deployment upgrade guarantees.
- Reconciliation is intentionally narrow. A lost create response without a provider order ID remains UNKNOWN with its hold retained for manual review. A lost refund response without a refund ID also requires manual reconciliation. Refund webhooks are currently recorded as ignored; only capture-completed notifications drive settlement.
- The polling worker settles known completed outcomes. It does not implement all provider failure/reversal/chargeback transitions, dead-letter controls, reconciliation dashboards, or a full operations runbook. A process/network failure is not treated as no-charge evidence.
- Expired unexecuted proposals cannot dispatch. Their reservations remain visible until safe revocation releases never-dispatched CREATE work. Orders already created keep reservations until provider evidence resolves them. Timers alone never free uncertain money.
- Quotes expire after 60 seconds and proposals after five minutes. Buyer approval can outlast a quote and then capture is rejected pending a new proposal. There is no quote-refresh UI/API yet.
- Recovery explanations are deterministic policy explanations. No model recovery classifier, fulfillment integrations, vault consent flow, saved-method execution, public deployment, or production abuse protection is claimed.
- The audit checkpoint is stored in the same database. An administrator who rewrites the whole chain and checkpoint can defeat this check; retain exported checkpoints outside the database for stronger evidence.
