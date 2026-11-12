# Implementation status

Updated November 11, 2026 after the full functional and code-quality review. The initial October 28 worker records remain under `docs/work/` as history.

## Current verification

- The backend suite passed **154 tests** against PostgreSQL and explicit provider/model fixtures. One Starlette TestClient/httpx deprecation warning remains.
- A live GroqCloud `/api/agent-runs` request in a disposable schema proposed the $349 desk. Mandate approved the proposal, reserved $349, and verified the audit chain. No checkout was started.
- The frontend passed **12 boundary tests**, TypeScript checking, and the production build. npm audit reported zero vulnerabilities; pip check reported no broken requirements.
- The local database was backed up, validated, and migrated to `0002_hardening`. All pre-existing financial/audit row counts were retained; old prototype cookie access was revoked.
- A clean installed API wheel booted in production mode and passed static frontend, access-gate, security-header, migration-head, and readiness checks. This was local ASGI verification, not Docker execution or an HTTPS hosting test.
- The compiled application was driven against the actual local API/database on port 8000. A $500 grant reserved $349 for the valid desk and denied the $800 gift card, leaving $151 available and $0 spent. No provider success was fabricated.
- PayPal sandbox authentication, the webhook ID, and the corrected `/api/webhooks/paypal` URL were verified. The public HTTPS endpoint rejected a malformed request, and operator sign-in issued a Secure, HttpOnly cookie. PayPal confirmed $349 sandbox orders for the configured merchant. Mandate verified signed `CHECKOUT.ORDER.APPROVED` events. The first proposal expired before capture, and PayPal rejected capture on the second. The affected grants showed zero spent. A completed capture, its signed `PAYMENT.CAPTURE.COMPLETED` event, and the partial refund still need verification. Docker runtime and hosted CI also remain unverified.

The [review summary](reviews/2026-10-30-thermo/00-summary.md) links the subsystem reports. Follow the [PayPal sandbox setup guide](09-paypal-sandbox-setup.md) for the remaining external checks.

The [November 11 functional audit](reviews/2026-11-11-functional-audit.md) records 15 resolved findings and the browser/API/PostgreSQL verification matrix. A complete fixture capture and refund journey passed; real sandbox capture and refund evidence remain pending.

## Model assignments and ownership

| Assignment | Model and effort | Reason | Evidence |
| --- | --- | --- | --- |
| Backend foundation, policy, and accounting | GPT-6.1 Sol, high | Authorization, row locking, lifecycle transitions, and money handling need careful reasoning | [Backend record](work/backend.md) |
| PayPal adapter and contract checks | GPT-6.1 Sol, high | Ambiguous outcomes, provider identity, and retry behavior are sensitive | [Payments record](work/payments.md) |
| Dashboard and bounded UI fixes | GPT-6 Luna, medium | UI consumes frozen contracts and can be verified with type checks and browser interactions | [Dashboard record](work/dashboard.md) |
| Independent boundary review | GPT-6.1 Sol, high | Separate verification of accounting and authorization | [Review record](work/verification.md) |
| Shared contracts, environment, model adapter, and integration | Parent coordinator | One owner integrates shared files and checks the final application | This record and README |

At most three workers ran together. Bootstrap used one shared checkout with exclusive directory ownership because the repository had no initial commit. Shared contracts preceded worker implementation; later changes stayed with their file owner.

## Task status

| Task | State | Completed behavior | Remaining |
| --- | --- | --- | --- |
| T00 | Waiting for sandbox transaction evidence | Sandbox-only adapter, readiness reporting, sandbox OAuth, corrected webhook registration, and real order creation | Real vault/capture/refund/webhook evidence |
| T01 | Hardened and locally verified | FastAPI/React, PostgreSQL, versioned migrations, exact locks, non-root packaging, pinned CI | Docker boot and remote CI |
| T02 | Locally verified | Sessions/CSRF, scoped records, catalog, P01-P11, reservation, idempotency, audit | External catalog integration is deferred |
| T03 | Implemented, provider-unverified | Buyer-present checkout, monotone settlement, durable payloads/IDs, bounded same-ID recovery, quote refresh, durable raw-event webhooks | Real transactions, vault execution, external refund/reversal import |
| T04 | Local browser journey verified | Grants, proposals, attack presets, payments, case views, and ledger; mobile layout checked | Real PayPal callback/capture browser journey |
| T05 | Live model run verified | One permitted cart-proposal tool, bounded GroqCloud call, catalog/schema validation, ordinary policy submission, missing-config failure | External agent capabilities and fuller operational limits |
| T06 | Core locally verified | Human cause/evidence review, deterministic policy bands, immutable offers, refund reservation and dispatch | Real refund, AI cause suggestion, complete recovery operations |
| T07 | Hardening review integrated | Accounting races, sessions/access, retries, strict UI boundaries, migrations and packaging reviewed | Real sandbox matrix and final submission evidence |
| T08-T09 | Planned | Local run instructions and development services | Hosting, license choice, operational runbook, public source, video, and submission |

## Verified evidence

- The automated suite covers policy/accounting against real PostgreSQL and explicit mocked provider/model responses. The independent reviewer added boundary tests and found a definitive capture failure that stranded retries. The fix restores ORDER_CREATED after a confirmed no-charge failure and reuses the original request identity.
- Concurrency verification submits two $300 canonical fixtures under a $500 grant and permits only one reservation.
- Browser verification created a $500 grant, approved and reserved the $349 desk, rejected the $800 untrusted gift card, and showed $151 available, $349 reserved, and $0 spent. No provider capture was represented as successful.
- Desktop and 390-pixel mobile layouts were inspected. Screenshots are retained locally under `output/playwright/`.
- Restart verification checks persistent session records and the audit chain after restarting the API. The database is a separate persistent local PostgreSQL 17 cluster, not SQLite.

Final commands and results are recorded below.

## Known limits and next work

1. Approve a sandbox order with the buyer account, then verify capture, signed delivery, and refund. Keep the webhook and application origin aligned with the active tunnel hostname.
2. Rehearse the Docker image and eventual hosted environment. Versioned upgrades and a clean installed-wheel boot now pass locally.
3. Verify actual buyer approval timing in sandbox. Identical canonical quotes refresh and approved purchases revalidate the active grant at dispatch. Changed carts, expired grants, and revoked grants block execution. Escalation review still requires a fresh proposal.
4. Prove bounded unknown-operation recovery with provider evidence. External PayPal refunds/reversals and operator repair after retry exhaustion remain manual; never release unknown holds based solely on elapsed time.
5. Optional model work includes recovery classification and externally scoped agent capabilities.
6. Finish judge access, deployment, operational controls, and the full release checklist after the external gates pass.

No remote repository or hosting purchase was made. The local API was exposed through a temporary HTTPS tunnel for sandbox verification.

## Historical first-build verification, October 28

- `.venv/Scripts/python.exe -m pytest apps/api/tests -q` passed 82 tests in 17.54 seconds. One Starlette TestClient/httpx deprecation warning remains; no test failed or skipped in that run.
- `npm.cmd --prefix apps/web run build` passed TypeScript checking and the Vite production build.
- The coordinator restarted the API, reloaded the same browser session, and observed the persisted $500 grant, $349 reservation, $151 available balance, both proposal records, and a verified audit-chain indicator.
- Desktop and mobile screenshots were inspected. The only initial browser error was a missing favicon; the UI worker added it and subsequent page reloads showed no browser errors.
- The root `.env`, local database password file, virtual environment, and local artifacts are ignored by Git. Provider keys remain empty.
- API and dashboard are left running at `http://localhost:8000` and `http://localhost:5173` for local review.
