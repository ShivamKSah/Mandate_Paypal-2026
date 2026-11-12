# Validation and demo

The matrix below defines product acceptance goals. Local automated and browser verification has started; see [implementation status](08-implementation-status.md) for actual evidence. Real sandbox acceptance remains pending credentials. Record setup, expected result, observed result, and redacted evidence when running scenarios. Task owners implement checks; the independent verifier reruns critical scenarios on the integrated build.

## Acceptance matrix

| ID | Scenario | Required observable result | Owner |
| --- | --- | --- | --- |
| V01 | Grant and valid $349 desk proposal under $500 limits | One stored approval, one sandbox capture, spent $349, remaining $151 | Payments + UI |
| V02 | Injected proposal adds an $800 gift card or disallowed merchant | Deterministic denial; no create/capture request sent to PayPal | Policy |
| V03 | Agent relabels a product or invents a lower price | Trusted category and quote control the verdict; invented values never reach execution | Policy |
| V04 | Required width is missing, then explicitly mismatched | Missing attribute escalates; mismatch denies; agent cannot approve either | Policy |
| V05 | Two simultaneous $300 proposals under a fresh $500 grant | At most one reserves; spent plus reserved never exceeds $500 | Policy |
| V06 | Retry after timeout or submit the same intent twice | Same operation/result; no additional capture; altered payload under the same key fails | Payments |
| V07 | Crash before dispatch, after dispatch, and after provider success | Persisted jobs resume; unknown money stays reserved until reconciled | Payments |
| V08 | Duplicate, invalid, delayed, and out-of-order webhooks | Signature and identity checks hold; accounting changes once; no state regression | Payments |
| V09 | Revoke or expire a grant before dispatch | New execution fails; already-dispatched work remains visible and reconciles | Policy + payments |
| V10 | Request another session's grant, case, ledger, or reset | Access denied with no cross-session disclosure or change | Verification |
| V11 | Modify cart, payee, or offer after approval | Stored hash/version binding rejects the replacement | Verification |
| V12 | Five purchase slots already used or in flight | Sixth attempt denied; parallel requests cannot evade the limit | Policy |
| V13 | Known subscription, non-USD amount, or invalid money | Proposal denied before payment | Policy |
| V14 | Human confirms a wrong-item case and accepts $314.10 refund | One provider refund; gross spending stays $349; net outflow becomes $34.90 | AI/recovery + payments |
| V15 | Two refund accepts, excessive refund, or lost refund response | Accepted offer remains fixed; completed plus pending refunds stay within capture | AI/recovery + payments |
| V16 | Model outage, injected refund instruction, or invalid model output | No unauthorized payment/refund; visible review or retry state | AI/recovery |
| V17 | Change an old audit event without changing the retained checkpoint | Chain verification detects mismatch; limitation is explained | Policy |
| V18 | Restart deployment and repeat the browser journey | Persistent records survive; pending jobs resume; judge access works | Coordinator |

Use real PostgreSQL connections for concurrency checks and deterministic adapter fault injection for interruption cases. Use actual sandbox transactions for V01, V14, and the signature-verification part of V08. Simulated provider responses alone cannot satisfy those cases.

## Demo narrative, 2 minutes 50 seconds

| Time | Show | Point to make |
| --- | --- | --- |
| 0:00-0:15 | Agent shopping request and brief product statement | The agent can request a purchase; spending authority is enforced by the application |
| 0:15-0:40 | $500 grant, approved merchant, confirmed 160 cm constraint, and payment-method status | The human defines the limits and PayPal consent is recorded |
| 0:40-1:10 | Live model proposes the $349 desk; capture appears in ledger | A valid purchase completes through PayPal sandbox |
| 1:10-1:35 | Run the $800 gift-card attack | Named rules deny it and no payment call is sent |
| 1:35-2:15 | Clearly labeled wrong-delivery fixture; cause review; accept $314.10 refund | Recovery handles a problem that matched the purchase-time listing |
| 2:15-2:40 | Capture/refund IDs, reserved/spent/refunded totals, webhook status, and audit verification | Show evidence behind the claims |
| 2:40-2:50 | Working URL and one-sentence boundary | Controlled sandbox merchant; production and arbitrary merchant refunds are future work |

Complete payment-method setup before the main recording where practical and show that prior consent honestly. If using the fallback, include buyer approval during checkout and change the autonomy claim. If provider latency requires cuts, label them; never display a pending operation as completed.

The wrong-delivery evidence is a demo fixture, while the capture and refund are real sandbox operations. Keep those labels visible. The illustrated 90% settlement is a merchant policy assumption accepted by the human.

## Release checklist

- [ ] All required acceptance scenarios pass on the release revision, with failures resolved rather than hidden.
- [ ] At least one live model run, sandbox capture, sandbox partial refund, and verified real webhook have retained evidence.
- [ ] A fresh checkout works from the documented setup procedure.
- [ ] Public repository includes source, assets, license, setup, AI usage, limitations, and judge-access instructions.
- [ ] Secrets are absent from commits, screenshots, recordings, model prompts, and public documentation.
- [ ] Functional hosted demo and persistent database remain available through judging; local run instructions are also complete.
- [ ] Video is public on YouTube, below three minutes, and uses permitted visual/audio material.
- [ ] Human owner reviews the concrete package and submits by November 10 at 8:00 PM IST.

Submission requirements were rechecked against the [official rules](https://paypalaihackathon.devpost.com/rules). The proposed 2:50 runtime and November 10 submission time provide working buffers.

## After submission

Keep the submitted revision tagged, preserve the evidence, and check hosting/database expiry dates. Assign an operator for provider incidents and access failures. Do not silently change the submitted feature set; handle any permitted maintenance according to the competition rules. The planning task does not create monitoring automations or publish anything.
