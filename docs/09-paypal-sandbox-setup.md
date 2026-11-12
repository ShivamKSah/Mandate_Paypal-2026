# PayPal sandbox setup and submission checks

Updated November 9, 2026 for GroqCloud. This application uses PayPal sandbox only. The implemented checkout asks the buyer to approve each order. Saved-payment vaulting is a separate, unfinished feature.

## 1. Create the test accounts

Sign in to the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/) using your developer login. Open Testing Tools > Sandbox Accounts. You need a Business account for the seller and a Personal account for the buyer. Defaults may already exist. Choose USD-capable test accounts with enough sandbox balance for the $349 demo purchase. Store the buyer's sandbox email/password privately for checkout. [PayPal sandbox accounts](https://developer.paypal.com/sandbox-testing/accounts)

Use the sandbox buyer at checkout, and the sandbox business account for the merchant. The buyer's login credentials are not application environment variables.

## 2. Create the sandbox application

In Apps & Credentials, select Sandbox and create a REST app named Mandate. Choose Merchant and associate the app with your sandbox Business account. Copy the app's Client ID and Secret into the corresponding variables below. Use the same app for orders, refunds, and webhook registration. [PayPal REST setup](https://developer.paypal.com/api/get-started/)

Obtain the merchant ID for that same sandbox business. If its account details do not show it, sign in to [sandbox PayPal](https://www.sandbox.paypal.com/) with the business test login and open Account Settings > Business information > PayPal Merchant ID. Copy the merchant ID, not the email, app ID, or client ID. [PayPal merchant ID instructions](https://www.paypal.com/us/cshelp/article/how-do-i-find-my-secure-merchant-id-on-my-paypal-account-help538)

Vault does not need to be enabled for the current buyer-approved checkout. Enabling a dashboard setting alone does not implement unattended purchases.

## 3. Update the existing root .env

Keep your current `DATABASE_URL` and `POSTGRES_PASSWORD`. The local database already has generated credentials; replacing the entire file with an example will break its connection. Fill the empty integration values in the existing file.

```dotenv
# Local native PostgreSQL; preserve the actual values already in your .env.
DATABASE_URL=postgresql+psycopg://mandate:<existing-password>@127.0.0.1:55432/mandate
POSTGRES_PASSWORD=<existing-password>

# Local browser origin for the compiled frontend served by FastAPI.
APP_ENV=development
PUBLIC_BASE_URL=http://localhost:8000
COOKIE_SECURE=false
APP_ACCESS_KEY=<unique-random-secret-of-at-least-32-characters>

# All four values come from the same sandbox merchant/application.
PAYPAL_ENV=sandbox
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_CLIENT_ID=<sandbox-app-client-id>
PAYPAL_CLIENT_SECRET=<sandbox-app-secret>
PAYPAL_MERCHANT_ID=<sandbox-business-merchant-id>
PAYPAL_WEBHOOK_ID=<webhook-subscription-id-from-step-4>

# Required for the shopping agent. The model override is optional.
GROQ_API_KEY=<your-groqcloud-api-key>
GROQ_MODEL=openai/gpt-oss-20b
```

Angle-bracket values are placeholders. Do not paste this block over your existing database credentials. Keep all secrets in the server environment and out of chat, Git, recordings, and `VITE_` variables. The app obtains its own temporary PayPal OAuth access tokens; you do not need a `PAYPAL_ACCESS_TOKEN` variable.

| Variable | Where it comes from | Used for |
| --- | --- | --- |
| PAYPAL_CLIENT_ID | Sandbox REST app credentials | Identify the server's PayPal app |
| PAYPAL_CLIENT_SECRET | Same app, reveal its secret | Server authentication |
| PAYPAL_MERCHANT_ID | Associated sandbox business account | Bind orders/captures to the trusted seller |
| PAYPAL_WEBHOOK_ID | Webhook registration in that app | Verify incoming event signatures |
| GROQ_API_KEY | Your GroqCloud project | Run the shopping model |
| GROQ_MODEL | Optional GroqCloud model ID | Select a catalog cart through the restricted tool |
| APP_ACCESS_KEY | A random secret you generate | Sign in to the protected operator workspace |
| PUBLIC_BASE_URL | The exact browser-facing origin | PayPal return/cancel redirects and Origin checks |

The default, `openai/gpt-oss-20b`, supports function calling on GroqCloud and is listed on its Free plan. Check your project's quota in the GroqCloud console. [GroqCloud model documentation](https://console.groq.com/docs/model/openai/gpt-oss-20b), [GroqCloud rate limits](https://console.groq.com/docs/rate-limits)

The access key is this application's login, not your PayPal password. There is one protected operator workspace. Logging in rotates the prior cookie and restores that workspace's history; anonymous development sessions remain isolated.

## 4. Register an HTTPS webhook

PayPal cannot deliver events to localhost. Obtain a public HTTPS URL that forwards to the running API on port 8000, using a tunnel or your eventual hosted deployment. Opening a tunnel exposes the application publicly, so start it only when you intend to test public access. Use the compiled frontend through this same URL rather than exposing Vite.

For a temporary test, install Cloudflare's `cloudflared` using its official instructions and run the command below in a separate terminal. It prints a temporary HTTPS address. Keep the process running and use that address consistently for the browser origin and webhook. Quick Tunnels are intended for testing; choose persistent hosting or a stable named tunnel for judging. [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

```powershell
cloudflared tunnel --url http://localhost:8000
```

Set the browser-facing origin in `.env` to that HTTPS URL:

```dotenv
APP_ENV=production
PUBLIC_BASE_URL=https://<your-public-host>
COOKIE_SECURE=true
APP_ACCESS_KEY=<your-random-32-or-more-character-secret>
```

Keep the database and sandbox/model variables. Restart the API and visit that exact HTTPS origin. Production startup requires HTTPS, secure cookies, an access key, a current database schema, and a compiled frontend. A custom port inside the tunnel may forward to 8000; the public webhook endpoint must be HTTPS on standard port 443.

In your sandbox REST app, add a webhook URL:

```text
https://<your-public-host>/api/webhooks/paypal
```

Subscribe to `PAYMENT.CAPTURE.COMPLETED`. Save the registration and put its Webhook ID in `PAYPAL_WEBHOOK_ID`. This is the subscription's ID, not an individual event ID, order ID, or capture ID. Restart the API once more. [PayPal webhook registration and verification](https://developer.paypal.com/api/rest/webhooks/rest/)

The code settles capture-completed events and reconciles its own requested refunds. It does not yet account automatically for every refund/reversal initiated directly in PayPal. For this demo, issue refunds through Mandate. Do not advertise external refund/reversal automation.

The current callback URLs are generated automatically:

```text
<PUBLIC_BASE_URL>/?checkout=approved
<PUBLIC_BASE_URL>/?checkout=cancelled
```

They are browser redirects, not webhook URLs. If your tunnel hostname changes, update both `PUBLIC_BASE_URL` and the registered webhook URL. Keep the same host open throughout checkout so the session cookie remains available.

## 5. Run the application and readiness check

From the repository root:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.lock.txt -e "./apps/api[test]"
npm.cmd --prefix apps/web ci
npm.cmd --prefix apps/web run build
.venv/Scripts/python.exe -m mandate.migrate
.venv/Scripts/python.exe -m mandate.check_setup
./scripts/run-api.ps1
```

The existing local database was backed up and migrated during this work. For a fresh database, the normal migrate command initializes it. An old unversioned prototype needs a backup and explicit adoption; do not force-stamp a schema that the migration tool rejects.

The readiness command prints variable names and status, never their values. It does not make provider calls. `MISSING` causes a nonzero exit status. Restart the API after environment changes. Browse `http://localhost:8000` locally, or your configured HTTPS origin when testing webhooks. `/api/ready` checks the database, required frontend bundle, and running reconciliation task.

For Docker later, use the separate production Compose file and `.env.production`. Its `DATABASE_URL` must use database host `db` and port `5432`, not the native workstation's `127.0.0.1:55432`. See [operations packaging](reviews/2026-10-30-thermo/04-operations.md). Local image execution has not been verified because the Docker engine is unavailable.

## 6. Prove the complete sandbox flow

1. Sign in with the application access key. Create a $500 grant for the demo merchant, furniture, and width 160 cm.
2. Run the shopping agent to submit the $349 desk proposal. Confirm that policy approves it and reserves $349. This must be a real model call, not just an attack preset.
3. In Payments, start checkout. Open PayPal and sign in as the sandbox Personal buyer. Approve the order and return to Mandate.
4. Click the capture action for the stored approved order. A return URL alone does not prove payment success.
5. Confirm the provider capture ID, $349 gross spent, $0 reserved, and $151 available. Confirm the real capture-completed webhook reaches the app and is processed.
6. Run the $800 untrusted gift-card scenario. Confirm DENY and no additional payment.
7. Report the clearly labeled wrong-delivery fixture, choose seller error, and enter $60 freight plus $87.25 resale loss. Review and accept the $314.10 demo-policy refund.
8. Confirm its refund ID and final provider status. Gross spending stays $349; refunded becomes $314.10; net outflow is $34.90. Refunds do not replenish the grant.
9. Verify the audit chain. Retain redacted provider IDs, timestamps, screenshots, and webhook evidence. Never record secrets or buyer passwords.

Use events from an actual sandbox purchase for this signature test. PayPal's simulator does not support the API postback verification used here, so a simulator failure is not proof that a real signed event will fail. [PayPal simulator limitation](https://developer.paypal.com/api/rest/webhooks/rest/#test-the-listener-with-mock-events)

## 7. Submission gate

Configuration alone does not make the entry submission-ready. Finish the real flow above, the [acceptance checklist](06-validation-and-demo.md), public repository/license, complete judge-access instructions, and a public YouTube demo below three minutes. Provide a working demo or complete run instructions and maintain judge access through December 15. The official cutoff is November 12, 2026 at noon PST, or November 13 at 1:30 AM IST. The internal target remains November 10. [Official competition rules](https://paypalaihackathon.devpost.com/rules)

State the shipped scope accurately: the model proposes, code enforces the policy, the buyer approves checkout, and the human accepts a bounded refund. Do not claim unattended saved-payment execution until that separate flow is implemented and demonstrated.
