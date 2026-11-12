# Independent local verification

Date: October 28, 2026. The checkout was uncommitted during verification, so no immutable revision identifier is available.

Reviewed the architecture and initial API contract, then inspected session authentication, ownership checks, proposal identity and approval, policy reservations, audit serialization, checkout, and recovery. Production code was not edited by this worker.

## Executed checks

The root `.venv/Scripts/python.exe` ran pytest against PostgreSQL using the repository's disposable per-test schema fixture. No existing records were cleared, and configuration secrets were not printed.

The original suite passed 72 tests before the independent tests were added. After the backend retry fix and integrated reconciliation changes, a complete rerun of `python -m pytest apps/api/tests -q` passed 79 tests in 16.29 seconds. Pytest reported one Starlette TestClient/httpx deprecation warning. `apps/api/tests/test_review.py` adds six integration checks and currently passes all six:

- A repeated capture or accepted refund accounts once, sends one provider mutation for each action, and leaves gross spending unchanged by refunds.
- A capture timeout retains its reservation through a repeated capture attempt and grant revocation.
- A refund timeout retains its refundable balance reservation, and a second case cannot reserve that balance.
- An expired quote prevents checkout before any provider call.
- A changed offer fails its hash binding. A different browser session cannot capture or accept another session's refund case.
- A confirmed no-charge capture failure can retry with the original capture operation request ID and then account exactly once.

Provider responses in these tests are explicit deterministic fixtures. They do not establish that PayPal accepted a request or moved money.

## Defect found and resolved

A definitive capture failure initially left the payment in `CAPTURE_PENDING` while its operation became `FAILED`. A subsequent attempt could not pass the endpoint's `ORDER_CREATED` guard. This included an OAuth rejection before the financial request was dispatched, so an otherwise valid order was stranded.

The coordinator's backend worker changed the definitive failure transition to restore `ORDER_CREATED`. The independent regression test verifies successful retry, stable request identity, retained reservation before success, and the final spent/reserved balances. The fix arrived before this regression test's first execution, so its original failure was established by source tracing rather than a retained failing pytest run.

## Remaining evidence boundary

No live model call, real sandbox capture, partial refund, or real signed sandbox webhook was verified by this worker. Missing PayPal credentials remain a visible setup state. The acceptance matrix's live provider gates remain open. Browser interaction and restart recovery still require integrated verification. Unknown operations without a known provider object ID must remain reserved until an operator can reconcile them.
