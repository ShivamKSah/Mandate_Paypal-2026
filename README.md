# Mandate

Mandate is a bounded-authority AI shopping and payment-control system built with FastAPI, React, PostgreSQL 17, Alembic, and PayPal Sandbox. It lets a human grant a time- and budget-capped spending authority, forces an AI shopping agent (or direct proposal client) through deterministic `P01`–`P11` policy checks and `cart_hash` binding, reserves funds atomically in PostgreSQL, supports both **Autonomous (vaulted)** and **Buyer approves each purchase** PayPal Sandbox execution with a durable outbox + reconciliation worker, and records every event in a SHA-256 hash-chained audit ledger.

## Current Verification Status (Honest Summary)

- **Verified by automated offline tests (loopback-only socket guard, mocked PayPal/LLM HTTP transports)**:
  - **182 backend tests** (`pytest apps/api/tests -q --tb=short`) against PostgreSQL 17 disposable schemas, including Hypothesis property tests (`@seed(42)`), 15 Break-the-Mandate attack simulations (`0` breaches, `0` payment rows created), Fernet vault grant/charge/reconciliation mocks, `PAYMENT.CAPTURE.REFUNDED` + `PAYMENT.CAPTURE.COMPLETED` webhook signature/authoritative-`GET` mocks, LLM retry/backoff/fallback mocks, instruction constraint extraction (`ESCALATE`-only), and `PUBLIC_DEMO` isolation/rate-limits.
  - **14 frontend boundary tests** (`npm test`), TypeScript typecheck (`tsc -b`), and Vite production build (`vite build`).
  - **Synthetic 100-scenario evaluation** (`scripts/run_evals.py` -> `eval_results.json`, labeled *Synthetic: scripted scenarios written by the author*): `50 of 50` attacks blocked (`95% CI 92.86-100.0%`), `0 of 50` false positives (`95% CI 0.0-7.14%`), `10 of 50` legitimate carts escalated (`95% CI 11.24-33.04%`), `p50=0.943 ms`, `p95=1.241 ms`.
- **Live scripts included for operator execution (not run by automated suites)**:
  - `scripts/live_vault_check.py`: full PayPal Sandbox vault grant ($1.00 setup -> browser approval -> vault token capture -> $1.00 refund -> `$349` autonomous `vault-charge` -> `GET` order confirmation -> partial refund -> audit verify).
  - `scripts/check_llm.py`: live GroqCloud OpenAI-compatible `/chat/completions` connectivity check (`60s` timeout).
- **Still unverified in live external environments**:
  - Live PayPal Sandbox vault setup capture, live autonomous `vault-charge`, live buyer-present capture, live partial refund, and real signed webhook deliveries (`PAYMENT.CAPTURE.COMPLETED` and `PAYMENT.CAPTURE.REFUNDED`) over a public HTTPS tunnel.
  - Live Render deployment (`render.yaml`) and Docker Compose execution (`compose.production.yaml`).

## What Is Real and What Is Mocked

- **Real in the running app**: PostgreSQL 17 persistence, Alembic migrations (`0001`–`0004`), atomic row-locked budget reservations (`spent_cents + reserved_cents <= budget_cents`), `P01`–`P11` policy engine, SHA-256 hash-chained audit ledger, CSRF + `HttpOnly`/`SameSite=Strict` sessions, DB-backed rate limits, Fernet encryption for `vault_token_ref`, durable `Operation` outbox + `ReconciliationLease` worker, and React dashboard.
- **Demo catalog**: Local server-side catalog in [catalog.py](apps/api/mandate/catalog.py) with demo defaults: **$500.00 budget**, **$400.00 per-purchase cap**, merchant **`demo-merchant`**, and categories **`office_furniture` (`furniture` in catalog) and `electronics`**.
- **Mocked in automated tests**: `apps/api/tests/*` replaces PayPal (`httpx.MockTransport` / fixture client) and GroqCloud (`httpx.MockTransport` / empty keys) and blocks all non-loopback network sockets via `pytest-socket --allow-hosts=127.0.0.1,::1`. Live PayPal Sandbox and GroqCloud calls only happen when running the server or `scripts/live_vault_check.py` / `scripts/check_llm.py` with real sandbox credentials in `.env`.

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

- **Render Blueprint**: [render.yaml](render.yaml) builds [Dockerfile](Dockerfile), runs `python -m mandate.migrate` before starting Uvicorn, sets `PUBLIC_DEMO=true`, `APP_ENV=production`, `COOKIE_SECURE=true`, `PAYPAL_ENV=sandbox`, and binds a managed PostgreSQL database (`mandate-db` — remember to upgrade from Render's free Postgres tier before the 30-day expiry during judging).
- **Docker Compose**: [compose.production.yaml](compose.production.yaml) runs PostgreSQL 17, one-shot `migrate`, and the non-root `app` container with `APP_ACCESS_KEY` operator authentication.
- **PayPal Sandbox & Webhooks**: Follow [docs/09-paypal-sandbox-setup.md](docs/09-paypal-sandbox-setup.md) to enable Sandbox Vault, register `https://<host>/api/webhooks/paypal`, and subscribe to `PAYMENT.CAPTURE.COMPLETED` and `PAYMENT.CAPTURE.REFUNDED`.
