# Initial implementation contract

Version 1, October 28, 2026. API paths have an `/api` prefix. This file freezes the first local implementation's wire contract. Only the coordinator changes it.

Hardening update, October 31, 2026. GET `/api/session` now returns a public opaque `id` separate from the secret cookie, plus `authenticated` and `access_required` booleans. It returns 401 when operator access is required. POST `/api/login` accepts `{ "access_key": "..." }` and returns the session shape. POST `/api/logout` requires CSRF and returns 204, invalidating the server-side credential. The protected operator workspace survives re-login; a new valid login rotates the previous cookie. `/api/ready` checks database access, the required frontend bundle, and worker availability. Current setup is documented in [the sandbox guide](09-paypal-sandbox-setup.md).

## Transport and sessions

JSON request/response bodies, integer USD cents, ISO-8601 UTC timestamps, opaque string IDs. Errors return `{ "detail": "message" }`. Never return secrets or provider vault tokens. Browser requests include cookies. GET `/api/session` creates or reads an opaque HttpOnly session cookie and returns `id`, `csrf_token`, `mode` (`sandbox` or `unconfigured`), and `paypal_configured`. Browser mutations require `X-CSRF-Token`. Development origin is http://localhost:5173, proxied to http://127.0.0.1:8000.

The unconfigured mode runs real local policy and persisted reservations, but does not simulate successful provider transactions. Display an explicit setup notice. All ownership checks happen server-side.

## Resources

- GET `/api/health` returns `status`, `database`.
- GET `/api/catalog` returns an array of products with `id`, `name`, `merchant_id`, `category`, `unit_price_cents`, `currency`, `attributes`, `recurring`, and `description`. Catalog IDs: `desk-160` ($349), `desk-unknown` ($299, missing width), `desk-120` ($249), `gift-card` ($800), `subscription` ($25), `keyboard` ($89). Trusted merchant ID is `demo-merchant`; gift cards use `untrusted-merchant`.
- POST `/api/mandates` accepts `budget_cents`, `per_transaction_cents`, `allowed_categories`, `allowed_merchants`, `constraints` (object, e.g. `width_cm: 160`), `instruction`, `expires_in_minutes` (default 60), `velocity_limit` (default 5). GET `/api/mandates` returns an array; GET `/api/mandates/{id}` returns one. A mandate has those fields plus `id`, `status`, `expires_at`, `spent_cents`, `reserved_cents`, `available_cents`, `version`.
- POST `/api/mandates/{id}/revoke` returns the updated mandate.
- POST `/api/proposals` accepts `mandate_id`, `purchase_intent_id`, `items` (array of `product_id`, `quantity`), `currency` (default USD), and optional `claimed_total_cents`. Return `id`, `mandate_id`, `decision` (`APPROVE`, `ESCALATE`, `DENY`), `status`, `total_cents`, `currency`, `cart_hash`, `rules` (array of `id`, `name`, `status` (`PASS`, `DENY`, `ESCALATE`, `NOT_RUN`), `message`), `items` (canonical product data), `created_at`, `expires_at`, `quote_expires_at`, `grant_version`, and optional `payment_id`.
- GET `/api/proposals` returns a session-filtered array; GET `/api/proposals/{id}` returns one.
- POST `/api/proposals/{id}/approve` accepts `cart_hash` and returns the updated proposal. Only addresses escalation, never a DENY.
- GET `/api/payments` returns an array with `id`, `proposal_id`, `status`, `amount_cents`, `refunded_cents`, `provider_order_id`, `provider_capture_id`, `approval_url`, `created_at`, and `can_cancel`. No successful provider result is invented.
- POST `/api/payments/{id}/cancel` releases a reservation only when its create operation is still WAITING with zero attempts. Repeated cancellation returns the same RELEASED payment. Dispatched and unknown operations remain reserved.
- POST `/api/payments/{id}/checkout` creates a sandbox order from its stored cart, returning the updated payment and optional PayPal approval URL. Buyer-present approval is the initial integration; saved-method feasibility stays pending until demonstrated.
- POST `/api/payments/{id}/capture` captures a buyer-approved stored order, returning updated payment. It must bind session/CSRF and immutable proposal data.
- POST `/api/cases` accepts `payment_id`, `cause` (`seller_error`, `ambiguous_listing`, `agent_error`, `vague_instruction`), `evidence`, `avoided_freight_cents`, `resale_loss_cents`. Returns `id`, `payment_id`, `status`, `cause`, `evidence`, `offer_cents`, `offer_hash`, `explanation`, `created_at`.
- GET `/api/cases` returns a session-filtered array. POST `/api/cases/{id}/accept` accepts only `offer_hash`; POST `/api/cases/{id}/reject` accepts an empty body. Return updated case. Provider refund only after human acceptance.
- GET `/api/ledger` returns an array of `id`, `event_type`, `entity_id`, `details`, `created_at`, `prev_hash`, `row_hash`. GET `/api/ledger/verify` returns `valid`, `event_count`, `checkpoint`.
- POST `/api/agent-runs` accepts `mandate_id`, `instruction`. If no model key exists, return a clear 503 rather than a canned result.

The UI may construct attack proposals through `/api/proposals`; it must not bypass the policy engine. Never offer a fake capture or refund button in unconfigured mode. Recovery forms may be disabled until a captured payment exists.

## Internal adapter contract

The payment worker owns `mandate.payments.paypal.PayPalClient` with async methods `create_order(cart, request_id, return_url, cancel_url)`, `capture_order(order_id, request_id)`, `refund_capture(capture_id, amount_cents, request_id)`, `get_order(order_id)`, `get_capture(capture_id)`, `get_refund(refund_id)`, and `verify_webhook(headers, event)`. Constructor reads explicit settings or environment, uses sandbox only, and never logs secrets. All methods return provider JSON or raise a typed `PayPalError`; ambiguous/network failures must be distinguishable from definitive rejection. Cart contains `items`, `total_cents`, `currency`, `merchant_id`; trusted payee comes from server config. The backend worker integrates only after reviewing this adapter.

The live webhook endpoint calls `verify_webhook(headers, event, raw_body=original_body)` so PayPal receives the original event representation during signature postback. A stale quote can be refreshed only when its current canonical cart hash is identical; a changed price/product still blocks capture. Unknown operations retain their holds and may replay only their stored payload and request ID within the bounded provider retention window.

Functional review update, November 11, 2026. An already-approved reserved purchase revalidates the active grant, its version, the canonical cart, current budget, and velocity before checkout or capture. Its earlier proposal review deadline does not strand the order. Human escalation approval still requires a fresh proposal and quote. Payment cancellation is exposed as a server-owned capability through `can_cancel`. Sanitized PayPal issue/status diagnostics distinguish missing buyer approval, declined funding, and rejected app credentials.
