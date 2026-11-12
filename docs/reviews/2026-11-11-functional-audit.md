# Functional and code-quality review

November 11, 2026. Reviewed the complete application with the thermo-nuclear security/correctness and maintainability skills, followed by Ponytail's whole-repository audit. The user requested the whole codebase, so this review covers existing behavior as well as the current changes.

Mandate is a single-operator sandbox shopping application. A model proposes catalog purchases, ordinary code checks spending authority, and the buyer approves PayPal checkout. A human reviews refund offers. The assumed load is one protected operator workspace with concurrent browser requests and a durable payment worker.

## Resolved findings

All findings below have focused changes in the working tree. Severity reflects the effect at the application's current operating scope.

| # | Severity | Concrete failure | Resolution |
| --- | --- | --- | --- |
| 1 | P1 | A buyer could approve an order, then lose the ability to capture it when the proposal's five-minute review deadline elapsed. | Approved reservations revalidate the active grant, version, budget, velocity, and canonical cart at dispatch. An expired quote refreshes only when the current cart hash is identical. Escalation review still requires a fresh proposal and quote. |
| 2 | P1 | A later duplicate proposal could retroactively prevent capture of an earlier approved purchase. | Duplicate review during reevaluation considers only proposals that preceded the current proposal. |
| 3 | P2 | A user could reserve budget but had no way to cancel it while retaining the grant. | Added an idempotent cancellation endpoint and UI action. The server exposes `can_cancel` only for an untouched local reservation. Dispatched and unknown operations retain their holds. |
| 4 | P2 | A capture handler could return HTTP 200 after settlement rejected the provider result. | Unsettled results return a conflict and retain the durable recovery state. |
| 5 | P2 | A missing buyer approval, declined funding source, and invalid merchant credentials all produced the same generic capture failure. | Allowlisted provider issue/status information is retained in the audit event and mapped to actionable messages. Raw provider bodies remain private. |
| 6 | P2 | A delayed capture-completed event could retry forever when PayPal now reported that capture as partially or fully refunded. | An already-settled capture can be recognized by the same capture ID, payee, and original amount. It cannot create a new capture or alter refund totals. |
| 7 | P2 | Checkout/capture controls remained available for expired, revoked, or changed grants. | UI actions now use the current grant status, expiry, version, and proposal approval. Cancellation remains available when authorized by the server. |
| 8 | P2 | An active grant hid the creation form, preventing a second grant from being created. | Added create-another and cancel-form actions, then select the newly created grant. |
| 9 | P2 | Expired grants disappeared from the active selection and had no revocation control, leaving untouched reservations inaccessible. | Grant history now exposes revocation for expired grants. |
| 10 | P2 | A newer proposal hid an older escalation's approval action. | Eligible escalations can be approved from history, with the exact server review deadline and grant version checked. |
| 11 | P2 | Attack presets inherited a custom quantity, changing their advertised scenario and outcome. | Presets submit one item. Custom proposals retain their entered quantity. |
| 12 | P2 | The recovery form offered fully refunded payments and payments that already had an active case. Paid acceptance also remained enabled with PayPal unavailable. | Recovery eligibility now matches the backend, and provider configuration gates paid acceptance. |
| 13 | P2 | The payment view showed capture and refund amounts without the resulting net outflow. | Confirmed captures display gross amount, refunded amount, and net outflow separately. |
| 14 | P2 | CI built the frontend but omitted its existing behavior tests. | The frontend CI job now runs `npm test`. |
| 15 | P2 | PayPal approval and capture controls overflowed narrow phone screens. | Payment actions wrap, long labels break within the available width, and touch targets retain a usable height. Checks passed at 320px and 390px. |

PayPal documents refunded capture states in its API schema. The late-event fix validates the previously recorded capture before accepting those states. [PayPal capture status schema](https://developer.paypal.com/api/payments/v2/definitions/capture_status/)

## Code and regression evidence

- Findings 1-4 are implemented in [payments_api.py](../../apps/api/mandate/payments_api.py) and [policy.py](../../apps/api/mandate/policy.py), with focused cases in [test_checkout_lifecycle.py](../../apps/api/tests/test_checkout_lifecycle.py).
- Findings 5-6 are implemented in [paypal.py](../../apps/api/mandate/payments/paypal.py), [settlement.py](../../apps/api/mandate/settlement.py), and [webhooks.py](../../apps/api/mandate/webhooks.py). Provider and late-event regressions are in [test_paypal.py](../../apps/api/tests/test_paypal.py) and [test_payment_hardening.py](../../apps/api/tests/test_payment_hardening.py).
- Findings 7-12 are implemented in [domain.ts](../../apps/web/src/domain.ts), [Overview.tsx](../../apps/web/src/Overview.tsx), [Proposals.tsx](../../apps/web/src/Proposals.tsx), [Payments.tsx](../../apps/web/src/Payments.tsx), and [Recovery.tsx](../../apps/web/src/Recovery.tsx). Frontend boundary cases are in [boundaries.test.mjs](../../apps/web/tests/boundaries.test.mjs).
- Finding 13 is in [Payments.tsx](../../apps/web/src/Payments.tsx), finding 14 in [checks.yml](../../.github/workflows/checks.yml), and finding 15 in [responsive.css](../../apps/web/src/responsive.css).

## Verification

- Backend suite passed **154 tests** against disposable PostgreSQL schemas. Regression cases cover quote refresh, checkout after the review deadline, duplicate ordering, cancellation ownership and CSRF, exactly-once release, dispatched/unknown reservation protection, provider error redaction, and late capture events after refunds.
- Frontend suite passed **12 tests**. TypeScript and the Vite production build passed.
- The compiled frontend was driven through the real FastAPI handlers and PostgreSQL persistence on a separate local verification server. Only the external PayPal and model HTTP boundaries used explicit fixtures. The verification schema was isolated from operator records.
- The browser journey exercised invalid/valid login, empty-state navigation, create/cancel/select grants, five preset scenarios, custom proposals, current/history escalation approval, cancellation, checkout links, rejected premature capture, approved capture after the review deadline, recovery reject/accept, model proposals, ledger disclosure, refresh, active/expired revocation, logout, and restored history after login.
- The fixture flow produced exactly one order, one capture, one refund, one model response, and one verified capture-completed webhook. The capture was $349, the refund was $314.10, and net outflow was $34.90. These are verification fixtures, not new sandbox transactions.
- Existing stored responses for four grants, seventeen proposals, and four payments passed the updated frontend schemas without changing the operator records.
- Mobile checkout/capture controls were checked at 320px and 390px after the wrapping fix.
- `npm audit` reported zero vulnerabilities. `pip check` reported no broken requirements. The diff passed whitespace checks.

The review kept policy, accounting, and provider authority in the existing backend modules. It added no production dependency, database migration, workflow framework, or parallel payment abstraction.

## Remaining verification and planned functionality

The working local application still needs a successful real PayPal sandbox capture, its real signed capture-completed notification, and a real sandbox partial refund. Earlier live checks verified OAuth, merchant/order creation, buyer approval, and signed order-approval events. The last real capture was rejected. Its old generic error cannot be reconstructed; future failures now retain a safe diagnostic category.

Saved-payment unattended execution, import of refunds/reversals initiated directly in PayPal, and AI recovery-cause suggestions remain planned work. The current UI supports the controlled catalog, USD, explicit buyer checkout, and human acceptance of bounded refund offers.

Unknown provider outcomes deliberately retain reservations. After bounded automatic retries, a recorded provider outcome is required before money can be released. There is no complete operator repair interface for exhausted unknown operations.

Docker execution and hosted CI were not run in this review. PR discussion could not be read through the available public GitHub API. A Starlette TestClient/httpx deprecation warning remains in the backend suite.

The current code and UI paths passed the local review. The release gate remains the real sandbox capture/refund evidence and the unverified runtime environments above.
