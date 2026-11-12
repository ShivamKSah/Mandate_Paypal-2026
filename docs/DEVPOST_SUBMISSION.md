# Mandate — Bounded Spending Authority for AI Shopping Agents

## Inspiration and Problem
AI shopping agents are starting to browse stores, fill carts, and click checkout buttons on our behalf. The problem is that giving an LLM a raw payment token or unrestricted checkout access is an all-or-nothing bet: prompt injection on a merchant page, an inflated price, a wrong category, or a runaway retry loop can spend money the user never intended to authorize.

Mandate separates **shopping intent** from **payment authority**. An AI agent can propose a cart, but deterministic server-side policy rules decide whether money can move—and every dollar is bounded by a time-limited, category-restricted, merchant-allowlisted spending grant.

## What It Does
1. **Spending Grants & Vault Autonomy**: A human sets a spending grant (`Mandate.per_transaction_cents`, `Mandate.vault_status`, e.g., `$500.00` budget, `$400.00` per-purchase cap, `demo-merchant`, `furniture` and `electronics`, `width_cm: 160`, 60-minute expiry; session TTL 8h). The user can either approve each purchase in PayPal or complete a one-time `$1.00` PayPal Vault setup (immediately auto-refunded) so future policy-approved purchases execute autonomously via `vault_id`.
2. **Deterministic Policy Gate (`P01`–`P11`) & `cart_hash` Binding**: Every proposal is re-priced from a trusted server catalog and evaluated against 11 deterministic rules (quote TTL 60s `quote_expires_at`, proposal TTL 5m `expires_at`, velocity window 1h, duplicate window 1h). Approved carts reserve integer-cent funds atomically in PostgreSQL.
3. **Break the Mandate (Adversarial Testing)**: 15 scripted attacks (`over_budget`, `over_cap`, `off_list_merchant`, `lookalike_merchant`, `mislabeled_category`, `inflated_price`, `hidden_line_item`, `quantity_inflation`, `currency_swap`, `expired_mandate`, `revoked_mandate`, `velocity_burst`, `duplicate_replay`, `subscription_upsell`, `cart_swap_after_approval`) prove zero breaches and zero PayPal calls when blocked.
4. **Durable Execution, Reconciliation & Bounded Recovery**: Every PayPal mutation writes a durable `Operation` outbox row (`Operation.attempts`, `Operation.payload_hash`) before calling PayPal with a stable `PayPal-Request-Id`. Ambiguous timeouts/5xx hold the reservation in `UNKNOWN` until the background lease worker resolves it via `GET` order lookup. When something goes wrong after capture, a human opens a recovery case with evidence and economics to issue a bounded partial refund.
5. **Hash-Chained Audit Ledger**: Every grant, policy verdict, reservation, capture, refund, and webhook is appended to a SHA-256 hash chain verifiable at `/api/ledger/verify`.

## How We Built It
- **Backend**: Python 3.11+, FastAPI, SQLAlchemy, Alembic (`0001_prototype`, `0002_hardening`, `0003_vault_grants`, `0004_challenge_attempts`), PostgreSQL 17 with `SELECT ... FOR UPDATE` row-level locking and `CHECK` constraints enforcing `spent_cents + reserved_cents <= budget_cents` in integer cents.
- **Frontend**: React 19, TypeScript, Vite 8, Zod runtime boundary schemas, CSRF + `HttpOnly`/`SameSite=Strict` session cookies, and `PUBLIC_DEMO` isolated visitor workspaces.
- **Security**: Fernet encryption at rest for PayPal vault tokens (`VAULT_ENCRYPTION_KEY`), strict PayPal Sandbox-only URL/env guards, redacted diagnostics, and DB-backed rate limits.

## PayPal Technologies Used
- **PayPal Orders v2 (`POST /v2/checkout/orders`, `POST /v2/checkout/orders/{id}/capture`)**: Supports both buyer-present checkout fallback and `$1.00` Vault setup orders (`store_in_vault: ON_SUCCESS`, `usage_type: MERCHANT`, `customer_type: CONSUMER`).
- **PayPal Vault Payment Tokens (`payment_source.paypal.vault_id`)**: Enables one-time buyer consent followed by autonomous server-side charges without further browser redirects.
- **PayPal Payments Refunds (`POST /v2/payments/captures/{id}/refund`)**: Used both to auto-refund the `$1.00` vault verification hold and to execute human-accepted partial refunds from Recovery cases.
- **PayPal Webhooks & Signature Verification (`POST /v1/notifications/verify-webhook-signature`)**: Handles `PAYMENT.CAPTURE.COMPLETED` and `PAYMENT.CAPTURE.REFUNDED`, re-verifying against authoritative PayPal `GET` calls before updating ledger state.
- **PayPal Order Lookup (`GET /v2/checkout/orders/{id}`)**: Polls missing/pending vault tokens after setup capture and drives the background reconciliation worker for `UNKNOWN` operations.

## AI Used (and Where It Is Deliberately Kept Out of the Payment Decision)
- **Where AI is used**: GroqCloud (`openai/gpt-oss-20b`, OpenAI-compatible tool-calling API with `45s` timeout, retries, and a labeled deterministic fallback) powers:
  1. **Shopping Agent**: picks catalog items from user instructions (`POST /api/agent/run`).
  2. **Instruction Constraint Extraction**: parses natural-language instructions into `ESCALATE`-only checks (`P09`)—never relaxing hard `DENY` rules.
  3. **Advisory Refund-Cause Suggestion**: suggests a recovery cause (`POST /api/cases/suggest-cause`) for human review.
- **Where AI is deliberately kept out**: The LLM **never** approves payments, **never** touches `vault_token_ref` or PayPal credentials, **never** computes prices or refunds, and **never** overrides `P01`–`P11` or `cart_hash` binding.

## Deterministic Policy Invariants (`P01`–`P11`)

Every proposed cart is evaluated synchronously against active grant parameters before any reservation or payment execution occurs (`apps/api/mandate/policy.py`).

| Rule ID | Rule Name | What It Checks | Failure Action |
| :--- | :--- | :--- | :---: |
| **`P01`** | **Active authority** | Verifies `grant.status == "ACTIVE"` and `grant.expires_at > now()`. | `DENY` |
| **`P02`** | **Budget** | Verifies canonical cart total plus spent and reserved funds fits the grant budget (`total + spent_cents + reserved_cents - reserved_credit <= budget_cents`). | `DENY` |
| **`P03`** | **Transaction cap** | Verifies canonical cart total does not exceed the single-purchase transaction cap (`total <= per_transaction_cents`). | `DENY` |
| **`P04`** | **Trusted merchant** | Verifies merchant is `demo-merchant` and is present in `grant.allowed_merchants` allowlist (`all(i["merchant_id"] == "demo-merchant" and i["merchant_id"] in grant.allowed_merchants for i in items)`). | `DENY` |
| **`P05`** | **Category** | Verifies all cart item categories are present in `grant.allowed_categories` allowlist (`all(i["category"] in grant.allowed_categories for i in items)`). | `DENY` |
| **`P06`** | **Exact quote** | Verifies all items exist in catalog, currency is USD, total > 0, quantity <= 100, and claimed total equals canonical total (`claimed_total is None or claimed_total == total`). | `DENY` |
| **`P07`** | **Velocity** | Verifies hourly reserved/completed purchases are within velocity limit (`used < grant.velocity_limit`). | `DENY` |
| **`P08`** | **Purchase identity** | Verifies purchase intent deduplication under row-level grant lock. | `PASS` (Deduplicated) |
| **`P09`** | **Confirmed constraints** | Checks item attributes against grant constraints and natural language instruction constraints. Fails `DENY` on explicit mismatch against grant constraints; yields `ESCALATE` if required grant attributes are missing or if extracted instruction constraints require operator review. | `DENY` (mismatch) / `ESCALATE` (missing / unlisted attribute) |
| **`P10`** | **Non-recurring** | Verifies no items in the cart are marked recurring (`recurring == True`). | `DENY` |
| **`P11`** | **Additional review** | Flags duplicate cart submitted within 1 hour or total exceeding 80% of transaction cap (`total * 100 > grant.per_transaction_cents * 80 or duplicate`). | `ESCALATE` |

### Cryptographic Cart-Hash Binding (Separate from P01–P11)
- **`cart_hash`**: `cart_hash = digest(cart)` computes the SHA-256 digest over the canonical items, quantities, unit prices, and currency.
- It binds the proposal, the atomic database reservation, the durable operation outbox record (`Operation.payload_hash`), and the PayPal order.
- If a cart payload is modified after policy evaluation, the cryptographic hash binding rejects execution before any PayPal API call can be initiated.

## Sponsor Technologies

| Sponsor | Implementation & Role in Mandate | Status |
| :--- | :--- | :--- |
| **AG Grid** | Integrated via `ag-grid-react` & `ag-grid-community` into two screens: **Decision Ledger** (`/ledger`) and **Payments Queue** (`/payments`), providing interactive data grids with sorting, filtering, CSV export, and light/dark theme synchronization (`ag-theme-quartz` / `ag-theme-quartz-dark`). Master-detail interaction opens the audit drawer for row inspection. | Integrated & verified in web build |
| **Render** | Infrastructure-as-code Blueprint in [`render.yaml`](render.yaml) building Docker runtime with PostgreSQL, pre-deploy migrations, and health check probes (`/api/health`). | Blueprint ready; hosted URL pending deployment |
| **Postman** | OpenAPI-derived 36-endpoint collection in [`docs/mandate.postman_collection.json`](mandate.postman_collection.json) covering all REST routes and schemas. | Collection committed in repo; not published to Postman Network |
| **Zapier** | Background webhook dispatcher ([`apps/api/mandate/zapier.py`](../apps/api/mandate/zapier.py)) emitting events on policy evaluations, captures, and refunds. Test endpoint at `POST /api/integrations/zapier/test`. | Built & optional; active when `ZAPIER_WEBHOOK_URL` is set in `.env` |
| **Channel3** | E-commerce product search adapter ([`apps/api/mandate/channel3.py`](../apps/api/mandate/channel3.py)) implementing POST `https://api.trychannel3.com/v1/search` with `x-api-key`. When `CHANNEL3_API_KEY` is not set, uses curated fallback items. Items are strictly bounded by Mandate's merchant allowlist (`P04`) and budget limits. Default guided demo uses trusted local catalog. | Built & optional adapter; live search verified Nov 12, 2026 (one query, 200 OK); non-allowlisted merchants denied by P04 |

## Challenges
- **Eliminating silent state drift**: Mapping ambiguous PayPal timeouts/5xx to `UNKNOWN` with held reservations and durable outbox `PayPal-Request-Id` retries required careful row locking so retries never double-charge or leak budget.
- **Sandbox `PAYEE_NOT_CONSENTED` / `PAYEE_MISMATCH` debugging**: During live sandbox integration, vault setup captures failed with `403 PAYEE_NOT_CONSENTED` because the configured `PAYPAL_MERCHANT_ID` belonged to a different sandbox account than the REST app's owner. Adding redacted PayPal error diagnostics and an unapproved-order `discover_merchant.py` helper pinpointed the exact sandbox business merchant ID (`Q6K...FCY`) and fixed the flow.

## Accomplishments
- **Verified Live Runs (Nov 12, 2026)**: End-to-end execution of `scripts/live_vault_check.py` passed in PayPal Sandbox: vault grant stored (Fernet-encrypted) + `$1.00` setup auto-refunded, `$349.00` proposal approved, autonomous `vault-charge` captured, PayPal `GET` order confirmed `COMPLETED`, `$314.10` (`31410` cents) partial refund executed via recovery case, and SHA-256 audit chain verified valid (`10` events). Live Channel3 product search check passed (`scripts/check_channel3.py`, one query, 200 OK, 1 product).
- **Automated Offline Verification**: **211 backend tests** passed (`pytest`, loopback-only socket guard, `[MOCKED]` PayPal/Groq transports, Hypothesis property tests) and **15 frontend boundary tests** passed (`npm test`).
- **Synthetic Policy Benchmark** (*Synthetic: scripted scenarios written by the author*): `8 attack kinds (currency_swap, inflated_price, lookalike_merchant, mislabeled_category, off_list_merchant, over_budget, over_cap, subscription_upsell), 50 variants` -> **50 of 50 blocked** (`95% CI 92.86–100.0%`), **0 of 50 false positives** (`95% CI 0.0–7.14%`), `10 of 50` legitimate carts escalated (`95% CI 11.24–33.04%`), `p50=0.918 ms`, `p95=1.311 ms`.
- *(Still unverified externally: signed PayPal webhook delivery over public HTTPS and hosted Render deployment.)*

## What We Learned
Giving an agent narrow, deterministic guardrails—canonical server pricing, `cart_hash` binding, integer-cent atomic reservations, and explicit `ESCALATE` gates for missing attributes—makes autonomous payments practical without trusting model outputs with money.

## What Is Next
- Complete live Render Blueprint deployment and verify signed `PAYMENT.CAPTURE.COMPLETED` / `PAYMENT.CAPTURE.REFUNDED` webhooks over public HTTPS.
- Extend multi-merchant catalog adapters and full AP2-compatible signed mandate payloads.

## Try It
- **Hosted Demo URL**: `https://<TODO-RENDER-HOST>.onrender.com`
- **GitHub Repository**: `<TODO-GITHUB-REPO-URL>`
- **Demo Video**: `<TODO-YOUTUBE-VIDEO-URL>`
- **PayPal Sandbox Buyer (for Vault Setup / Buyer Checkout screens)**:
  - Email: `<TODO_SANDBOX_BUYER_EMAIL>`
  - Password: `<TODO_SANDBOX_BUYER_PASSWORD>`
