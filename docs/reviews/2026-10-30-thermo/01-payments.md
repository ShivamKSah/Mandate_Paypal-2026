# Payment correctness and recovery review

Review by GPT-6 Astra; integrated and documented by the coordinator on October 31, 2026. The worker's final handoff was interrupted by a usage limit, so this report relies on the saved code and reproducible tests rather than an unverified completion claim.

## Confirmed defects and structural repair

`payments_api.py` and `recovery.py` applied results to ORM instances loaded before an awaited provider call. Another transaction could complete settlement while the first request was waiting. Tests reproduced a late capture timeout replacing CAPTURED with UNKNOWN, a late refund error replacing REFUNDED with REFUND_FAILED, and a duplicate refund audit/accounting path. `settlement.py` now owns refreshed locked success transitions. Initial responses, reconciliation, and webhooks reuse it. Failure handlers preserve completed outcomes and do not clear a hold for an earlier uncertain attempt.

`Operation` previously retained a request ID without the full original payload. A lost create/refund response without an object ID had no safe recovery mechanism. The operation now stores a hashed snapshot including trusted merchant and operation-specific inputs before dispatch. Retries preserve the same identity, compare the snapshot and current trusted merchant, and stop after five attempts or five hours. The conservative window remains inside the documented default order request-retention period. Expired/tampered requests keep their hold for manual review.

`dispatch_guard` previously rejected an unchanged quote after 60 seconds, even if the buyer had just approved the order. It now obtains a fresh canonical quote and requires its hash to equal the stored approved cart. Grant/proposal expiry, revocation, policy, and reservation checks remain in force. Price or product drift is never silently accepted.

`webhooks.py` previously could acknowledge a verified event after provider lookup failed, leaving no durable processing path. Verified bodies are now stored before processing, provider outages return a retryable response, and the poller retries saved events with leases and bounded backoff. Raw payloads are retained. Verification calls have a separate shared rate limit. Duplicate IDs with changed content are rejected.

The coordinator also corrected `PayPalClient.verify_webhook`. JSON parsing followed by ordinary serialization changes the event representation that PayPal documents as signature-sensitive. The endpoint now forwards the original event string inside the postback request; tests assert preserved whitespace and escaped bytes. [PayPal verification guidance](https://developer.paypal.com/api/rest/webhooks/rest/)

## Evidence

`test_payment_hardening.py` covers late capture/refund errors, duplicate refund responses, stale ORM state, no-ID retries, retention expiry, snapshot tampering, merchant changes, quote refresh/drift, verified-webhook outages, restarted processing, worker lease reclaim, concurrent capture settlement, and forged-event rate limits. `test_paypal.py` covers sandbox-only URLs, exact money and payee binding, error ambiguity, OAuth handling, request identities, and original webhook representation.

Run `.venv/Scripts/python.exe -m pytest apps/api/tests/test_paypal.py apps/api/tests/test_reconciliation.py apps/api/tests/test_payment_hardening.py -q`. The coordinator's final result is recorded in the summary/status documents. These are actual PostgreSQL tests with controlled external HTTP responses, not live sandbox transactions.

## Remaining release boundaries

The current event handler settles PAYMENT.CAPTURE.COMPLETED. Refunds initiated through Mandate are settled through their direct result or reconciliation. Refunds/reversals initiated independently in PayPal and all possible provider dispute/failure transitions are not automatically imported. Do not present those as shipped functionality.

After retry exhaustion, uncertain operations stay held. There is no operator repair UI that can safely resolve every provider situation. Use provider evidence and an audited maintenance procedure; never clear holds because a timer elapsed. Live app/account permissions, actual checkout, refund and signature evidence remain unverified until sandbox credentials are supplied.
