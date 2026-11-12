# Dashboard implementation notes

The local React/Vite dashboard lives in `apps/web`. It uses the `/api` development proxy to `127.0.0.1:8000`, sends cookies and the session CSRF token on mutations, and validates JSON responses at the API boundary with Zod.

## Views

- Overview: grant creation with the $500 demo defaults, spending/reservation totals, revoke control, recent decisions and ledger status.
- Proposals: five policy-engine attack/demo presets and a custom catalog cart. Escalations can be approved against the returned cart hash in the backend workflow.
- Payments: reservation/capture states, and provider approval/capture actions only when backend state and configuration allow them.
- Recovery: case creation is gated on a real captured payment; pending offers show the proposed amount, evidence, and human accept/reject actions.
- Ledger: session events and backend chain verification.

The provider banner stays visible whenever PayPal is unconfigured. There are no fabricated capture/refund controls or canned model responses. A model run can return a 503 if no model key is configured.

## Local commands

From `apps/web`: `npm install`, `npm run dev`, `npm run typecheck`, and `npm run build`. Vite serves on port 5173 and proxies `/api` to `http://127.0.0.1:8000`.

The UI depends on backend capabilities matching the frozen contract in `docs/07-api-contract.md`. It cannot demonstrate PayPal settlement or refund unless provider configuration and a real buyer-approved sandbox capture exist.
