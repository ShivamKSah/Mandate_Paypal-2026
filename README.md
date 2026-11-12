# Mandate

Mandate has a React dashboard, FastAPI API, PostgreSQL persistence, policy enforcement, budget reservations, and a hash-chained ledger. The shopping agent passed a live GroqCloud test. A real PayPal sandbox capture, refund, and signed webhook delivery still need verification.

Mandate gives an AI shopping agent limited spending authority, checks each proposed purchase in ordinary application code, and offers a human-approved recovery flow for mistakes.

## Run locally

On this workstation, the isolated PostgreSQL 17 cluster uses port 55432. The ignored root `.env` contains its credentials. The compiled dashboard and API can run together at [localhost:8000](http://localhost:8000).

For a fresh setup, install Python 3.11 or newer, Node.js 22.12 or newer, and PostgreSQL 17. With Docker available, copy `.env.example` to `.env` and use `docker compose up -d db`. Choose either the native local cluster or Docker for port 55432, not both. Change the example local database password and keep it consistent in `DATABASE_URL` and `POSTGRES_PASSWORD`.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.lock.txt -e "./apps/api[test]"
npm.cmd --prefix apps/web ci
npm.cmd --prefix apps/web run build
.venv/Scripts/python.exe -m mandate.migrate
```

Set `PUBLIC_BASE_URL=http://localhost:8000` in `.env`, then start the compiled application from the repository root:

```powershell
./scripts/run-api.ps1
```

Open [the dashboard](http://localhost:8000). Authorize a grant, visit Proposals, and try a catalog item or attack preset. All policy decisions and reservations use the real local API/database. An approved proposal reserves budget. Recovery becomes available only after a confirmed capture. For frontend development with live reload, run `./scripts/run-web.ps1` separately and use port 5173 with a matching `PUBLIC_BASE_URL`.

To restart the isolated native cluster on this workstation after a reboot:

```powershell
& 'C:/Program Files/PostgreSQL/17/bin/pg_ctl.exe' -D .local/postgres -l .local/postgres.log -o '-p 55432 -h 127.0.0.1' -w start
```

## Enable external integrations

Configure sandbox application credentials, merchant ID, and webhook ID in the ignored root `.env`. See [the PayPal setup guide](docs/work/payments.md). Restart the API after configuration changes. Buyer-present approval is the first checkout path; reusable saved-method consent is still a feasibility gate. Never use live payment credentials.

Follow [the current PayPal sandbox and submission setup guide](docs/09-paypal-sandbox-setup.md) for the exact dashboard steps, environment variables, HTTPS webhook registration, and real-purchase verification. Run `.venv/Scripts/python.exe -m mandate.check_setup` for a read-only configuration check.

Production mode requires an HTTPS `PUBLIC_BASE_URL`, `COOKIE_SECURE=true`, and a random `APP_ACCESS_KEY` of at least 32 characters. It protects a single operator workspace. Login rotates the previous cookie while retaining that workspace's records; logout and expiry revoke access server-side. Anonymous development sessions remain separate.

The shopping agent needs `GROQ_API_KEY` in `.env`. It defaults to `openai/gpt-oss-20b`, with `GROQ_MODEL` available as an optional override. It makes one bounded GroqCloud Responses request and sends the returned cart through the same policy checks. The model has one catalog proposal tool. [GroqCloud Responses API](https://console.groq.com/docs/responses-api)

## Check the build

```powershell
.venv/Scripts/python.exe -m pytest apps/api/tests -q
npm.cmd --prefix apps/web run build
```

PostgreSQL tests create and remove unique disposable schemas. Provider/model contract tests use explicit HTTP fixtures. They do not establish real sandbox feasibility. GitHub Actions checks are configured but have not run remotely.

Current results and remaining gates are in [implementation status](docs/08-implementation-status.md) and the [review summary](docs/reviews/2026-10-30-thermo/00-summary.md). Startup checks the migration head and schema; run upgrades explicitly. The old local prototype was backed up and adopted without removing financial or audit records. Old prototype cookies were invalidated. Docker/Compose packaging and pinned CI are included; container execution and hosted CI remain unverified.

## Plans and specifications

| Read | Document | Purpose |
| --- | --- | --- |
| 1 | [Product plan](docs/01-product-plan.md) | Product promise, MVP, assumptions, and scope cuts |
| 2 | [Architecture](docs/02-architecture.md) | Components, trust boundaries, policy rules, payment accounting, and recovery |
| 3 | [Build plan](docs/03-build-plan.md) | Dated milestones, dependencies, task IDs, and completion gates |
| 4 | [Subagent work split](docs/04-subagent-work-split.md) | Responsibilities, file ownership, parallel work, and handoffs |
| 5 | [Research and decisions](docs/05-research-and-decisions.md) | Recent primary sources and the decisions they support |
| 6 | [Validation and demo](docs/06-validation-and-demo.md) | Acceptance scenarios, demo sequence, and release checklist |

The PayPal feasibility gate remains pending. Prove saved-payment checkout, capture, partial refund, and webhook verification with sandbox credentials before claiming autonomous purchasing. If vaulting is unavailable, use explicit buyer approval for each order and label that limitation.

The design targets a controlled merchant in PayPal sandbox. Charging or refunding unrelated merchants, production payments, and AP2 compatibility are outside this MVP.

The source is the 12-page [Mandate Research Dossier and Build Blueprint](<Mandate Research Dossier and Build Blueprint.pdf>), dated October 21, 2026. These plans preserve its core idea and correct several implementation risks. Research was checked on October 28, 2026; links and verification limits are recorded in the research document.

The repository was initialized during this build. Execution details and worker evidence are under `docs/work/`. No remote repository, public deployment, or paid hosting was created.
