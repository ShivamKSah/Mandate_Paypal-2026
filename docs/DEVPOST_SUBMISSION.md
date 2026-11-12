# Mandate — Bounded Spending Authority for AI Shopping Agents

## Inspiration and Problem
AI shopping agents are starting to browse stores, fill carts, and click checkout buttons on our behalf. The problem is that giving an LLM a raw payment token or unrestricted checkout access is an all-or-nothing bet: prompt injection on a merchant page, an inflated price, a wrong category, or a runaway retry loop can spend money the user never intended to authorize.

Mandate separates **shopping intent** from **payment authority**. An AI agent can propose a cart, but deterministic server-side policy rules decide whether money can move—and every dollar is bounded by a time-limited, category-restricted, merchant-allowlisted spending grant.

## What It Does
1. **Spending Grants & Vault Autonomy**: A human sets a spending grant (e.g., `$500.00` budget, `$400.00` per-purchase cap, `demo-merchant`, `furniture` and `electronics`, `width_cm: 160`, 60-minute expiry). The user can either approve each purchase in PayPal or complete a one-time `$1.00` PayPal Vault setup (immediately auto-refunded) so future policy-approved purchases execute autonomously via `vault_id`.
2. **Deterministic Policy Gate (`P01`–`P11`) & `cart_hash` Binding**: Every proposal is re-priced from a trusted server catalog and evaluated against 11 deterministic rules (lifecycle, budget, cap, merchant, category, canonical total/currency, velocity, recurring/subscription block, attribute ambiguity `ESCALATE` gate, and duplicate/near-cap escalation). Approved carts reserve integer-cent funds atomically in PostgreSQL.
3. **Break the Mandate (Adversarial Testing)**: 15 scripted attacks (budget/cap overflow, lookalike/off-list merchants, mislabeled gift cards, inflated prices, currency swaps, velocity bursts, duplicate replays, subscriptions, post-approval cart swaps) prove zero breaches and zero PayPal calls when blocked.
4. **Durable Execution, Reconciliation & Bounded Recovery**: Every PayPal mutation writes a durable `Operation` outbox row before calling PayPal with a stable `PayPal-Request-Id`. Ambiguous timeouts/5xx hold the reservation in `UNKNOWN` until the background lease worker resolves it via `GET` order lookup. When something goes wrong after capture, a human opens a recovery case with evidence and economics to issue a bounded partial refund.
5. **Hash-Chained Audit Ledger**: Every grant, policy verdict, reservation, capture, refund, and webhook is appended to a SHA-256 hash chain verifiable at `/api/ledger/verify`.

## How We Built It
- **Backend**: Python 3.11+, FastAPI, SQLAlchemy, Alembic (`0001`–`0004`), PostgreSQL 17 with `SELECT ... FOR UPDATE` row-level locking and `CHECK` constraints enforcing `spent_cents + reserved_cents <= budget_cents` in integer cents.
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

## Sponsor Technologies Used

- **AG Grid (Official Hackathon Sponsor — Best Use of AG Grid / AG Studio)**:
  - Patterned after the official [`paypaldev/hackathon-paypal-ag-grid-boilerplate`](https://github.com/paypaldev/hackathon-paypal-ag-grid-boilerplate) reference architecture.
  - Integrated `ag-grid-react` and `ag-grid-community` into both the **Decision Ledger** (`/ledger`) and **Payments & Reservations** (`/payments`) dashboards.
  - Delivers an interactive, self-serve financial analytics experience with real-time quick search, multi-column sorting, CSV data export, and dynamic light/dark theming (`ag-theme-quartz` / `ag-theme-quartz-dark`).
  - Master-detail interaction: clicking any row in the AG Grid ledger seamlessly opens the audit drawer to display the payload and cryptographic SHA-256 P01–P11 invariant check results.
- **Render (Official Hackathon Sponsor)**:
  - Complete `render.yaml` infrastructure-as-code Blueprint featuring Docker containerization, health check probes (`/api/health`), automated pre-deploy PostgreSQL migrations, and isolated evaluation sessions (`PUBLIC_DEMO=true`).
- **Postman (Official Hackathon Sponsor)**:
  - Complete OpenAPI-derived Postman collection ([`docs/mandate.postman_collection.json`](mandate.postman_collection.json)) covering all 36 REST endpoints across session management, autonomous agent runs, policy evaluations, PayPal orders, vault grants, capture webhooks, and cryptographic audit ledger verification.
- **Zapier (Official Hackathon Sponsor)**:
  - Non-blocking webhook notification dispatcher (`apps/api/mandate/zapier.py`) triggering automated Zapier workflows whenever a policy violation is blocked (`DENY`), an ambiguity requires human approval (`ESCALATE`), or an autonomous PayPal vault payment completes.
  - Includes interactive test dispatch (`POST /api/integrations/zapier/test`) and status inspection (`GET /api/integrations/status`).
- **Channel3 (Official Hackathon Sponsor)**:
  - E-commerce catalog adapter (`apps/api/mandate/channel3.py`) bringing product search across 25,000+ retailers into the autonomous shopping agent with fallback resolution.
  - Crucially, Mandate's deterministic policy engine validates Channel3 items against the user's spending grant and caps before PayPal execution—proving safe autonomous commerce across external merchant networks.

## Challenges
- **Eliminating silent state drift**: Mapping ambiguous PayPal timeouts/5xx to `UNKNOWN` with held reservations and durable outbox `PayPal-Request-Id` retries required careful row locking so retries never double-charge or leak budget.
- **Sandbox `PAYEE_NOT_CONSENTED` / `PAYEE_MISMATCH` debugging**: During live sandbox integration, vault setup captures failed with `403 PAYEE_NOT_CONSENTED` because the configured `PAYPAL_MERCHANT_ID` belonged to a different sandbox account than the REST app's owner. Adding redacted PayPal error diagnostics and an unapproved-order `discover_merchant.py` helper pinpointed the exact sandbox business merchant ID (`Q6K...FCY`) and fixed the flow.

## Accomplishments
- **Verified Live PayPal Sandbox Run (Nov 12, 2026)**: End-to-end execution of `scripts/live_vault_check.py` passed in PayPal Sandbox: vault grant stored (Fernet-encrypted) + `$1.00` setup auto-refunded, `$349.00` proposal approved, autonomous `vault-charge` captured, PayPal `GET` order confirmed `COMPLETED`, `$314.10` (`31410` cents) partial refund executed via recovery case, and SHA-256 audit chain verified valid (`10` events).
- **Automated Offline Verification**: **202 backend tests** passed (`pytest`, loopback-only socket guard, `[MOCKED]` PayPal/Groq transports, Hypothesis property tests) and **14 frontend boundary tests** passed (`npm test`).
- **Synthetic Policy Benchmark** (*Synthetic: scripted scenarios written by the author*): `8 attack kinds, 50 variants` -> **50 of 50 blocked** (`95% CI 92.86–100.0%`), **0 of 50 false positives** (`95% CI 0.0–7.14%`), `10 of 50` legitimate carts escalated (`95% CI 11.24–33.04%`), `p50=0.918 ms`, `p95=1.311 ms`.
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
