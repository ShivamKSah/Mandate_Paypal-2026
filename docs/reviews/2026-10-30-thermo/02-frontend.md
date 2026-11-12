# Frontend maintainability and boundary review

GPT-6.1 Sol reviewed and changed the frontend. The coordinator integrated it on October 31, 2026. The worker completed code and fixture checks before a usage limit interrupted its final handoff.

## Findings and repairs

The original App.tsx and stylesheet compressed whole components into very long lines. The frontend is now readable, with focused Overview, Proposals, Payments, Recovery, Ledger and Login modules, a shared typed API boundary, domain helpers, and a dashboard loading hook. This separates financial input parsing and lifecycle decisions from JSX without introducing a general UI framework.

The original current-grant fallback could treat expired/revoked history as a spending grant. The selector now accepts only active, unexpired grants and preserves history separately. Money fields parse decimal strings into exact cents and reject unsupported precision rather than silently rounding it.

React's initial requests could create competing session cookies, and refreshes or double clicks could race actions. A single in-flight session request, action serialization, and dashboard request epochs now control these transitions. Errors refresh authoritative records because a failed response may follow a committed reservation. Logout clears private state.

Purchase retry identity originally lived only in component memory. A lost response followed by reload could generate another intent. A schema-validated sessionStorage record now retains the pending intent for its unchanged grant/cart until the server confirms the result.

Payment buttons now follow explicit lifecycle states. UNKNOWN payments do not expose stale approval links or capture actions. A PayPal return URL displays a truthful return notice and does not imply a confirmed capture. Financial responses reject fractional cents, unknown states, malformed timestamps and unsafe approval URLs.

The production login gate handles 401 without pretending the backend is unavailable. Its session contract includes authenticated/access_required flags and CSRF logout. Backend review additionally found the malformed non-ASCII CSRF failure; the coordinator repaired it and retained the failing-then-passing regression test.

## Verification

`npm.cmd --prefix apps/web test` passes eight Node boundary tests. `npm.cmd --prefix apps/web run build` passes TypeScript and compiles the production bundle. The dependency inventory found no reported npm vulnerabilities.

`tests/browser-review.js` exercises explicit API fixtures for initial session single-flight, invalid/valid login, callback notices, UNKNOWN payment controls, grant history, mobile layout, retry identity after reload, strict money and logout. Those fixture results do not prove actual PayPal or model integration. The coordinator separately checks the compiled application against the real local API/database and records that evidence in implementation status.
