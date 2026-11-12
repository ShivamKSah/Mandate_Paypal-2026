# Garuda (Mandate) — Bounded Spending Authority for AI Shopping Agents

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![React 19](https://img.shields.io/badge/react-19-cyan.svg)](https://react.dev/)
[![PayPal Sandbox](https://img.shields.io/badge/PayPal-Sandbox%20v2-003087.svg)](https://developer.paypal.com/)
[![PostgreSQL 17](https://img.shields.io/badge/PostgreSQL-17-336791.svg)](https://www.postgresql.org/)
[![AG Grid](https://img.shields.io/badge/AG%20Grid-Community-brightgreen.svg)](https://www.ag-grid.com/)

Garuda (Mandate) is a production-grade, bounded-authority AI shopping and payment-control system built with **FastAPI**, **React 19**, **PostgreSQL 17**, **Alembic**, and a **PayPal Sandbox** execution engine. 

A human sets a time-, merchant-, and budget-capped spending grant. An AI shopping agent (powered by Groq or fallback rules) browses and proposes carts. Server-side deterministic policy rules (`P01`–`P11`) and cryptographic `cart_hash` binding evaluate every item against canonical catalog prices before any money moves. Approved purchases reserve funds atomically via PostgreSQL row-level locks, and execute through either **Autonomous (vaulted) PayPal charges** (`payment_source.paypal.vault_id`) or **Buyer-present approvals**, backed by a durable outbox, automated reconciliation, and a SHA-256 hash-chained audit ledger.

---

## Detailed System Workflows

### 1. End-to-End Autonomous Shopping Workflow

```mermaid
sequenceDiagram
    autonumber
    actor User as Human Operator / Judge
    participant UI as React 19 Dashboard
    participant API as FastAPI Trust Boundary
    participant Agent as AI Shopping Agent (Groq)
    participant Policy as Policy Engine (P01-P11)
    participant DB as PostgreSQL 17 (Atomic Locks)
    participant PayPal as PayPal Sandbox REST API

    User->>UI: Set Spending Grant ($500 budget, $400 cap, furniture/electronics, 1hr)
    UI->>API: POST /api/mandates
    API->>DB: INSERT INTO mandates (status='ACTIVE')
    
    opt One-Time Vault Authorization
        User->>UI: Click "Enable Autonomous (Vaulted)"
        UI->>API: POST /api/vault/setup-order
        API->>PayPal: POST /v2/checkout/orders ($1.00 auth, store_in_vault=ON_SUCCESS)
        User->>PayPal: Buyer Consents in Sandbox
        PayPal-->>API: Capture & Auto-Refund $1.00 hold
        API->>DB: Store encrypted vault_token_ref (Fernet) & set vault_status='GRANTED'
    end

    User->>UI: Give Agent Prompt ("Find an ergonomic desk under $400")
    UI->>API: POST /api/agent/run
    API->>Agent: Extract constraints & search catalog
    Agent-->>API: Propose items [desk-standing-electric: $349.00]
    API->>Policy: Evaluate canonical cart against active grant
    Policy->>Policy: Verify P01-P11 rules + SHA-256 cart_hash
    Policy-->>API: Verdict: APPROVE

    API->>DB: SELECT ... FOR UPDATE (Check spent + reserved + total <= budget)
    DB-->>API: Row locked & reservation placed (status='APPROVED')

    alt Autonomous Execution (Vault Enabled)
        API->>DB: Write durable Operation row (outbox pattern)
        API->>PayPal: POST /v2/checkout/orders (vault_id, capture immediately)
        PayPal-->>API: Order status COMPLETED
        API->>DB: Mark Operation COMPLETED, spent_cents += 34900, reserved_cents -= 34900
        API->>DB: Append event to SHA-256 Audit Ledger
    else Buyer Checkout (Vault Disabled)
        API->>PayPal: Create Order for buyer redirection
        User->>PayPal: Buyer manually approves purchase
        API->>PayPal: POST /v2/checkout/orders/{id}/capture
    end
```

### 2. Ambiguity & Constraint Escalation Workflow (`P09` / `P11`)

```mermaid
flowchart TD
    Cart["Cart Proposed by Agent"] --> Reprice["Re-price with Server Catalog"]
    Reprice --> Hash["Compute SHA-256 cart_hash"]
    Hash --> P01P08["P01-P08: Lifecycle, Budget, Cap, Merchant, Category, Quote, Velocity"]
    P01P08 -- Hard Violation --> Deny["DENY: Atomic Rollback, Zero PayPal Calls"]
    P01P08 -- Valid --> P09{"P09: Attribute Constraints"}
    P09 -- Attribute Mismatch --> Deny
    P09 -- Missing / Ambiguous Attribute --> Escalate["ESCALATE: Flag for Human Review"]
    P09 -- Fully Matched --> P10{"P10: Non-Recurring"}
    P10 -- Recurring Subscription Found --> Deny
    P10 -- One-time Purchase --> P11{"P11: Review Thresholds"}
    P11 -- Duplicate cart OR Total > 80% Cap --> Escalate
    P11 -- Normal --> Approve["APPROVE: Row-Locked Reservation & Execution"]
    
    Escalate --> Human["Operator Reviews in Dashboard (/proposals)"]
    Human -- "Reject" --> Deny
    Human -- "Approve Exception" --> Approve
```

### 3. Durable Outbox & Reconciliation Worker Workflow

```mermaid
flowchart LR
    Reserve["Atomic Reservation Placed"] --> Outbox["Write Operation (PENDING, PayPal-Request-Id)"]
    Outbox --> Send["Dispatch to PayPal API"]
    Send -- HTTP 200/201 --> Done["Mark COMPLETED & Finalize Spent Balance"]
    Send -- Network Timeout / 5xx --> Unknown["Mark UNKNOWN & Hold Reservation"]
    
    subgraph Background Recovery Worker
        Unknown --> Lease["Acquire Reconciliation Lease (Row Lock)"]
        Lease --> Query["GET /v2/checkout/orders/{id}"]
        Query -- COMPLETED --> Finalize["Resolve COMPLETED & Deduct Budget"]
        Query -- NOT_FOUND / CREATED --> Release["Release Reservation & Refund Budget"]
    end
```

---

## Current Verification Status (Honest Summary)

### Verified by Live Runs (Nov 12, 2026)
- **Live PayPal Sandbox end-to-end vault check passed** (`scripts/live_vault_check.py`, no IDs or secrets stored):
  - Vault grant stored (Fernet-encrypted) and `$1.00` setup authorization auto-refunded.
  - `$349.00` catalog proposal approved against policy and `cart_hash` binding.
  - Autonomous `vault-charge` captured (`COMPLETED` confirmed via `PayPal GET /v2/checkout/orders/{id}`).
  - Partial refund of `$314.10` (`31410` cents) executed through a bounded recovery case.
  - SHA-256 hash-chained audit ledger verified valid across `10` events.
- **Live Channel3 product search check passed** (`scripts/check_channel3.py`):
  - Live search verified Nov 12, 2026 (one query, 200 OK, returned 1 product).
  - Channel3 products from merchants outside the grant allowlist remain strictly denied by `P04`.

### Verified by Automated Offline Tests
- **211 backend tests passed** (`pytest apps/api/tests -q --tb=short`, loopback-only socket guard `127.0.0.1,::1`, mocked PayPal/Groq HTTP transports, PostgreSQL 17 disposable schemas):
  - Hypothesis property tests (`@seed(42)`), 15 Break-the-Mandate attack simulations (`0` breaches, `0` payment rows created), Fernet vault grant/charge/reconciliation mocks, `PAYMENT.CAPTURE.REFUNDED` + `PAYMENT.CAPTURE.COMPLETED` webhook signature/authoritative-`GET` mocks, LLM retry/backoff/fallback mocks, instruction constraint extraction (`ESCALATE`-only in `P09`), `PUBLIC_DEMO` isolation/rate-limits, offline `scripts/predeploy_check.py`, `scripts/discover_merchant.py`, Zapier webhook dispatch mocks, and Channel3 allowlist/constraint/API schema mocks.
- **15 frontend boundary tests passed** (`npm.cmd --prefix apps/web test`), plus TypeScript typecheck (`tsc -b`) and Vite production build (`vite build`).
- **Synthetic 100-scenario evaluation passed** (`scripts/run_evals.py` -> [eval_results.json](eval_results.json), labeled *Synthetic: scripted scenarios written by the author*): **`8 attack kinds, 50 variants`** with **`50 of 50 blocked (95% CI 92.86-100.0%)`**, **`0 of 50 false positives (95% CI 0.0-7.14%)`**, **`10 of 50 escalated (95% CI 11.24-33.04%)`** on legitimate carts, `p50=0.918 ms`, `p95=1.311 ms`.

### Still Unverified in External Environments
- Signed PayPal webhook delivery (`PAYMENT.CAPTURE.COMPLETED` and `PAYMENT.CAPTURE.REFUNDED`) over a public HTTPS URL.
- Live hosted Render deployment (`render.yaml`) and Docker Compose execution (`compose.production.yaml`).
- Live GroqCloud API tool-calling response (`scripts/check_llm.py` — placeholder: `<TODO: run scripts/check_llm.py and paste timestamp/model>`).

## Demo Defaults and What Is Real vs. Mocked

- **Demo defaults**: **$500.00 budget**, **$400.00 per-purchase cap**, allowed merchant **`demo-merchant`**, allowed categories **`office_furniture` (`furniture` in catalog) and `electronics`**.
- **What is real**: FastAPI backend, PostgreSQL 17 persistence and row-locked atomic reservations (`spent_cents + reserved_cents <= budget_cents`), Alembic schema migrations (`0001_prototype`, `0002_hardening`, `0003_vault_grants`, `0004_challenge_attempts`), `P01`–`P11` policy engine, SHA-256 hash-chained audit ledger, CSRF + `HttpOnly`/`SameSite=Strict` sessions, DB-backed rate limits, Fernet encryption for `vault_token_ref`, durable `Operation` outbox + `ReconciliationLease` worker, 15 Break-the-Mandate attacks, and React dashboard.
- **What is mocked in tests**: All 211 backend tests replace external PayPal and GroqCloud HTTP endpoints with `httpx.MockTransport` / fixture clients and enforce `pytest-socket --allow-hosts=127.0.0.1,::1` so no external network calls ever run during `pytest`. Real PayPal Sandbox and GroqCloud calls only execute when running the app or operator scripts (`scripts/live_vault_check.py`, `scripts/check_llm.py`) with real credentials.

## Try It as a Judge

- **Hosted public demo URL**: `https://<TODO-RENDER-HOST>.onrender.com` (set `PUBLIC_DEMO=true` so every browser visitor automatically gets an isolated session with pre-seeded demo data or can reset via **Reset demo session**).
- **PayPal Sandbox Buyer credentials (for PayPal approval steps only)**:
  - Buyer email: `<TODO_SANDBOX_BUYER_EMAIL>`
  - Buyer password: `<TODO_SANDBOX_BUYER_PASSWORD>`
- **Screens that need NO PayPal login** (work immediately in any browser, even when PayPal is unconfigured):
  - **Overview**: inspect budget vs reserved/captured balances, create a spending grant, or revoke a grant.
  - **Shopping / Proposals**: run the shopping agent (or deterministic fallback) against the demo catalog and inspect `P01`–`P11` verdicts and `cart_hash` bindings.
  - **Break the Mandate (Attacks)**: trigger any of the 15 adversarial carts individually or run all 15 to verify zero breaches and zero payment rows created, plus view the synthetic evaluation summary.
  - **Audit Ledger**: inspect the hash-chained event log and open the `P01`–`P11` per-rule evaluation drawer on any decision row.
  - **Recovery**: open a case with **Suggest cause from description** to get a deterministic/advisory cause classification (`Accept offer` only calls PayPal when a real captured payment with a refundable balance exists and PayPal is configured).
- **Screens that DO need the PayPal Sandbox Buyer login** (if PayPal is not configured, buttons disable with an explicit notice instead of failing):
  - **Vault Grant Setup (Overview -> Enable Autonomous (vaulted) / Complete vault grant)**: opens a `$1.00` PayPal Sandbox approval flow, stores the vaulted token Fernet-encrypted, and immediately auto-refunds the `$1.00`. Once `GRANTED`, **Payments -> Charge vaulted PayPal** executes autonomously without further buyer login.
  - **Buyer-Present Checkout (Payments -> Start checkout / Fallback: buyer checkout -> Capture order after buyer approval)**: redirects to PayPal Sandbox for manual buyer approval on that single purchase.

## Why This Matters

Giving an AI agent unrestricted checkout access turns prompt injection and model hallucinations directly into financial loss. Security research from **Guardio Labs** (Scamlexity tests of agentic browsers), **Brave**, and **Palo Alto Unit 42** has demonstrated indirect prompt injection attacks against browser and shopping agents, and **OpenAI** has stated publicly that prompt injection remains an unsolved security problem. Rather than trying to make the LLM un-trickable, Mandate enforces a deterministic spending boundary between the agent and PayPal.

## How Mandate Differs

| Control / Initiative | What It Does | Gap Mandate Fills |
| --- | --- | --- |
| **OAuth scopes** | Restricts coarse API capabilities (read/write orders) | Cannot enforce integer-cent budgets, per-cart caps, item attributes, or `cart_hash` binding |
| **Card limits** | Caps total spend or velocity at the card/issuer level | Lacks per-merchant/category allowlists, ambiguity `ESCALATE` gates, and bounded refund recovery |
| **Google AP2 mandates** | Defines cryptographically signed agent payment mandate specifications | *Note: Mandate's name is AP2-inspired, not an AP2 implementation.* Mandate provides a runnable FastAPI/PostgreSQL + PayPal Sandbox reference enforcement loop today |
| **Visa and Mastercard agent controls** | Network-level tokenization and agentic commerce rails | Focuses on card-network authorization rather than local pre-dispatch `P01`–`P11` policy + post-capture bounded recovery |
| **PayPal Agent Ready** | Enables agent-initiated PayPal checkout/payment experiences | Mandate adds the local deterministic policy engine (`P01`–`P11`), outbox + `UNKNOWN` reconciliation holds, and hash-chained audit ledger in front of PayPal |

## Architecture

```mermaid
flowchart LR
  User["Human Operator / Judge"] -->|Sets grant & approves escalations| UI["React 19 Dashboard"]
  Agent["AI Shopping Agent (Groq)"] -->|Proposes product IDs| TrustBoundary["Trust Boundary (FastAPI)"]
  UI --> TrustBoundary
  TrustBoundary -->|Canonical catalog quote & cart_hash| Policy["Policy Engine (P01-P11)"]
  Policy -->|DENY / ESCALATE| Audit["SHA-256 Hash-Chained Audit Ledger"]
  Policy -->|APPROVE: atomic row-locked reservation| Outbox["Durable Operation Outbox (PostgreSQL 17)"]
  Outbox -->|Stable PayPal-Request-Id + Fernet vault_id| PayPal["PayPal Sandbox (Orders v2 / Vault / Refunds)"]
  PayPal -->|Timeout / 5xx -> UNKNOWN hold| Recon["Background Reconciliation Worker (GET Order)"]
  Recon --> Audit
  PayPal -->|Signed Webhooks + Authoritative GET| Audit
```

## Deterministic Policy Invariants (`P01`–`P11`)

Every proposed cart is evaluated synchronously against the active grant parameters before any reservation or payment execution occurs (`apps/api/mandate/policy.py`).

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

## Break the Mandate — Adversarial Security Matrix

Mandate includes 15 automated attack simulations in [apps/api/mandate/attacks.py](apps/api/mandate/attacks.py) testing boundary limits against prompt injections, compromised agents, or malicious merchant catalogs:

| # | Attack Scenario | Vector Description | Enforcing Rule | Outcome |
| :-: | :--- | :--- | :---: | :---: |
| 1 | **`over_budget`** | Agent proposes cart exceeding remaining grant budget | `P02` | `DENY` |
| 2 | **`over_cap`** | Single transaction exceeds per-purchase cap | `P03` | `DENY` |
| 3 | **`off_list_merchant`** | Purchase routed to unapproved merchant (`untrusted-store`) | `P04` | `DENY` |
| 4 | **`lookalike_merchant`** | Phishing merchant masquerading as legitimate store (`demo-merchant-fake`) | `P04` | `DENY` |
| 5 | **`mislabeled_category`** | Restricted category (e.g., prepaid gift cards) | `P05` | `DENY` |
| 6 | **`inflated_price`** | Agent claims lower price than canonical server catalog quote | `P06` | `DENY` |
| 7 | **`hidden_line_item`** | Unquoted hidden items bundled into payload | `P06` | `DENY` |
| 8 | **`quantity_inflation`** | Unreasonable item quantity (> 100 units) | `P06` | `DENY` |
| 9 | **`currency_swap`** | Attempt to bill in unsupported foreign currency (`EUR`) | `P06` | `DENY` |
| 10 | **`expired_mandate`** | Transaction submitted after spending grant expiry | `P01` | `DENY` |
| 11 | **`revoked_mandate`** | Transaction submitted against manually revoked grant | `P01` | `DENY` |
| 12 | **`velocity_burst`** | Rapid purchases exceeding hourly rate limit | `P07` | `DENY` |
| 13 | **`duplicate_replay`** | Exact cart replayed within 1-hour duplicate window | `P11` | `ESCALATE` |
| 14 | **`subscription_upsell`** | Covert recurring billing subscription sneak-in | `P10` | `DENY` |
| 15 | **`cart_swap_after_approval`** | Cart modified post-approval before PayPal execution | `cart_hash` | Execution Aborted |

*Result across all 15 attacks: 0 breaches, 0 unauthorized database mutations, and 0 external PayPal calls.*

---

## Repository Structure

```text
├── apps/
│   ├── api/                     # FastAPI backend application
│   │   ├── alembic/             # Database migrations (0001_prototype -> 0004_challenge_attempts)
│   │   ├── mandate/             # Core business logic
│   │   │   ├── policy.py        # Deterministic P01–P11 invariant policy engine
│   │   │   ├── models.py        # SQLAlchemy models (Mandate, Proposal, Operation, LedgerEntry)
│   │   │   ├── catalog.py       # Canonical catalog pricing & quoting
│   │   │   ├── attacks.py       # 15 Break-the-Mandate attack definitions
│   │   │   ├── channel3.py      # Channel3 product search adapter
│   │   │   ├── zapier.py        # Non-blocking Zapier webhook dispatcher
│   │   │   ├── agents/          # Groq LLM tool-calling shopping agent & fallback
│   │   │   └── payments/        # PayPal REST API v2 client (Orders, Vault, Refunds)
│   │   └── tests/               # 211 offline backend tests (Hypothesis, socket guard)
│   └── web/                     # React 19 + TypeScript frontend dashboard
│       ├── src/
│       │   ├── Overview.tsx     # Grant management & Vault setup screen
│       │   ├── Proposals.tsx    # AI shopping proposals & escalation approvals
│       │   ├── Payments.tsx     # AG Grid payment queues & PayPal checkout triggers
│       │   ├── Ledger.tsx       # AG Grid cryptographic SHA-256 audit log
│       │   ├── Attacks.tsx      # Break-the-Mandate adversarial attack simulator
│       │   └── Recovery.tsx     # Bounded post-purchase refund case manager
│       └── tests/               # 15 boundary & schema validation tests
├── docs/                        # Specifications, Postman collection & submission writeups
├── scripts/                     # Operator utilities & evaluation runners
│   ├── check_channel3.py        # Channel3 live search connectivity check (operator)
│   ├── check_llm.py             # Groq LLM live model response check (operator)
│   ├── live_vault_check.py      # E2E live PayPal sandbox verification test
│   ├── predeploy_check.py       # Pre-deploy production environment validator
│   └── run_evals.py             # Synthetic 100-scenario policy evaluation runner
├── render.yaml                  # Render Infrastructure-as-Code Blueprint
├── compose.production.yaml      # Multi-container Docker Compose definition
└── LICENSE                      # Open-source MIT License
```

---

## Sponsor Technologies

| Sponsor | Implementation & Role in Mandate | Status |
| :--- | :--- | :--- |
| **AG Grid** | Integrated via `ag-grid-react` & `ag-grid-community` into two screens: **Decision Ledger** (`/ledger`) and **Payments Queue** (`/payments`), providing interactive data grids with sorting, filtering, CSV export, and light/dark theme synchronization. | Integrated & verified in web build |
| **Render** | Infrastructure-as-code Blueprint in [`render.yaml`](render.yaml) building Docker runtime with PostgreSQL, pre-deploy migrations, and health checks. | Blueprint ready; hosted URL pending deployment |
| **Postman** | OpenAPI-derived 36-endpoint collection in [`docs/mandate.postman_collection.json`](docs/mandate.postman_collection.json) covering all REST routes and schemas. | Collection committed in repo; not published to Postman Network |
| **Zapier** | Background webhook dispatcher ([`apps/api/mandate/zapier.py`](apps/api/mandate/zapier.py)) emitting events on policy evaluations, captures, and refunds. Test endpoint at `POST /api/integrations/zapier/test`. | Built & optional; active when `ZAPIER_WEBHOOK_URL` is set in `.env` |
| **Channel3** | E-commerce product search adapter ([`apps/api/mandate/channel3.py`](apps/api/mandate/channel3.py)) implementing POST `https://api.trychannel3.com/v1/search` with `x-api-key`. When `CHANNEL3_API_KEY` is not set, uses curated fallback items. Items are strictly bounded by Mandate's merchant allowlist (`P04`) and budget limits. Default guided demo uses trusted local catalog. | Built & optional adapter; live search verified Nov 12, 2026 (one query, 200 OK); non-allowlisted merchants denied by P04 |

## Tools Used

- **Backend & Persistence**: Python 3.11+, FastAPI, SQLAlchemy, Alembic (`0001_prototype`, `0002_hardening`, `0003_vault_grants`, `0004_challenge_attempts`), PostgreSQL 17, `cryptography` (Fernet)
- **Payments**: PayPal Sandbox REST API v2 (Orders, Vault `vault_id`, Refunds, Webhook Signature Verification)
- **AI (Advisory / Proposal Only)**: GroqCloud (`openai/gpt-oss-20b` with labeled deterministic rules fallback)
- **Frontend & Data Grids**: React 19, TypeScript 7, Vite 8, **AG Grid** (`ag-grid-react` & `ag-grid-community`), Zod, Lucide Icons
- **Deployment & Cloud (Sponsor)**: Render Blueprint ([render.yaml](render.yaml)) with Docker runtime, pre-deploy migrations, and health checks
- **Testing & Verification**: `pytest`, `pytest-socket` (loopback-only offline guard), `httpx.MockTransport`, Hypothesis (`@seed(42)`), Node test runner
- **API & Integration Artifacts**: [docs/mandate.postman_collection.json](docs/mandate.postman_collection.json) (36 endpoints generated from FastAPI OpenAPI) and [examples/guarded_agent.py](examples/guarded_agent.py) (minimal external agent proposal example)

## Run Locally

1. Install Python `3.11+`, Node.js `22.12+`, and PostgreSQL 17 (native cluster on port `55432` or `docker compose up -d db`).
2. Copy `.env.example` to `.env` and fill in `DATABASE_URL`, `POSTGRES_PASSWORD`, `VAULT_ENCRYPTION_KEY`, `PAYPAL_*` sandbox credentials, and `GROQ_API_KEY`.
3. Install dependencies, build the frontend, migrate the database, and start the server:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.lock.txt -e "./apps/api[test]"
npm.cmd --prefix apps/web ci
npm.cmd --prefix apps/web run build
.venv/Scripts/python.exe -m mandate.migrate
.venv/Scripts/python.exe -m mandate.check_setup
./scripts/run-api.ps1
```

Open [http://localhost:8000](http://localhost:8000). Use `./scripts/run-web.ps1` (`http://localhost:5173`) only when developing the frontend with Vite HMR.

## Test and Evaluation Commands

```powershell
# Offline backend test suite (loopback-only socket guard, 60s timeout)
.venv/Scripts/python.exe -m pytest apps/api/tests -q --tb=short

# Synthetic 100-scenario policy evaluation (isolated temp PostgreSQL schema, offline)
.venv/Scripts/python.exe scripts/run_evals.py

# Frontend typecheck, build, and boundary tests
npm.cmd --prefix apps/web run typecheck
npm.cmd --prefix apps/web run build
npm.cmd --prefix apps/web test

# Operator-run live checks (require real sandbox/Groq credentials in .env)
.venv/Scripts/python.exe scripts/check_llm.py
.venv/Scripts/python.exe scripts/live_vault_check.py
```

## Deploy

- **Pre-deploy offline check**: Run `.venv/Scripts/python.exe scripts/predeploy_check.py` (or `--env-file path/to/.env.prod`) before deploying. It verifies production env vars (`APP_ENV`, `PUBLIC_DEMO`, `COOKIE_SECURE`, `PUBLIC_BASE_URL` HTTPS origin, `ALLOWED_HOSTS` includes its hostname, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_MERCHANT_ID`, `PAYPAL_WEBHOOK_ID`, valid Fernet `VAULT_ENCRYPTION_KEY`, `GROQ_API_KEY`, and PostgreSQL `DATABASE_URL`) and prints a PASS/FAIL summary without printing any values.
- **PayPal Sandbox Vault & Webhooks**: In the PayPal Developer Dashboard under **Apps & Credentials -> Mandate -> Features**, enable **Vault** (Reference Transactions / PayPal Vault) so autonomous vaulted grants work; register webhook URL `https://<host>/api/webhooks/paypal` subscribed to `PAYMENT.CAPTURE.COMPLETED` and `PAYMENT.CAPTURE.REFUNDED`, and store the resulting ID in `PAYPAL_WEBHOOK_ID` (see [docs/09-paypal-sandbox-setup.md](docs/09-paypal-sandbox-setup.md)).
- **Render Blueprint**: [render.yaml](render.yaml) builds [Dockerfile](Dockerfile), runs `python -m mandate.migrate` before starting Uvicorn, sets `PUBLIC_DEMO=true`, `APP_ENV=production`, `COOKIE_SECURE=true`, `PAYPAL_ENV=sandbox`, and binds a managed PostgreSQL database (`mandate-db` — remember to upgrade from Render's free Postgres tier before the 30-day expiry during judging).
- **Docker Compose**: [compose.production.yaml](compose.production.yaml) runs PostgreSQL 17, one-shot `migrate`, and the non-root `app` container with `APP_ACCESS_KEY` operator authentication.
