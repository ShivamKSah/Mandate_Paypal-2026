# Working on Mandate

Read README.md, docs/02-architecture.md, docs/07-api-contract.md, and the task's relevant sections before editing. The accepted plan is in docs/03-build-plan.md. The user has authorized implementation and delegated workers with lighter models for bounded tasks.

- Use integer cents, trusted catalog records, session ownership, and PostgreSQL transactions.
- Never expose PayPal secrets or vault tokens to a browser or model. Sandbox only.
- Do not invent completed provider operations. Missing credentials are a visible setup state.
- Preserve reservations when provider outcomes are unknown. Reuse operation identity for retries.
- Only a human session may approve escalations or accept refund offers.
- Current bootstrap uses one shared checkout with exclusive write directories; do not edit another worker's files. The coordinator handles shared contracts and integration.
- Run meaningful tests for policy, accounting, retries, and authorization. Use a disposable database schema; never clear another worker's records.
- No deployment, hosting purchases, or public publication during the initial local build.

The root `.env`, `.venv`, and `.local` are ignored local configuration. Never print credentials or commit them.
