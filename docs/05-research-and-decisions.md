# Research and decisions

Research checked October 28, 2026. The local 12-page dossier dated October 21 is the starting source. The table below separates current primary-source evidence from recommendations made for this project. Publication dates are included where the source supplied them; a documentation check date is not a publication date.

## Recent practices for building with agents

| Source and date | Relevant finding | Application to Mandate |
| --- | --- | --- |
| [Anthropic: Redesigning source control](https://www.anthropic.com/research/redesigning-source-control), Oct 13, 2026; updated Oct 15 | Agent-generated change volume can make integration infrastructure the bottleneck. Human engineers still supply system constraints and design decisions. | Keep one integration owner, small changes, and explicit accounting invariants. Ordinary Git is adequate for this small project. |
| [Anthropic: Patterns and problems in emerging multiagent systems](https://www.anthropic.com/research/multiagent-systems), Aug 13, 2026 | Bounded agent calls with clear inputs and outputs are more established than loosely coordinated peer agents. Coordination creates its own failure modes. | Use explicit task contracts and a coordinator. Do not rely on a group of agents agreeing as proof of correctness. |
| [Anthropic: Harness design for long-running application development](https://www.anthropic.com/research/harness-design-long-running-apps), Mar 24, 2026 | The study separates planning, generation, and evaluation, and passes structured artifacts between work sessions. | Separate coding ownership from acceptance review. Preserve evidence and next actions between sessions. |
| [OpenAI: Harness engineering](https://openai.com/index/harness-engineering/), Feb 11, 2026 | Repository documentation serves as the durable knowledge source. A short navigation file points agents to task-relevant material. | Keep these focused Markdown files. Add a short repository agent guide during T01, not a large repeated prompt. |
| [Anthropic: Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents), Nov 26, 2025 | Incremental feature work, explicit progress, and end-to-end checks address incomplete work and premature completion claims. | Each task has a completion gate. Preserve one working purchase flow as new work lands. |
| [Anthropic: Multi-agent research system](https://www.anthropic.com/research/multi-agent-research-system), Jun 13, 2025 | Delegation benefits from explicit objectives, outputs, and boundaries. Parallel agents also add token cost and fit some tasks better than others. | Limit parallel work to independently owned modules. Use at most three workers and reduce that when dependencies dominate. |

These are engineering reports and research observations, not universal guarantees. The October and August 2026 sources provide the newest relevant evidence reviewed here; the older sources remain useful because they describe concrete delegation and continuity practices. Do not transfer vendor benchmark gains or large-scale operating claims into a delivery estimate for Mandate.

## Rechecked external dependencies

| Source | Verified in documentation | Still requires project evidence |
| --- | --- | --- |
| [Devpost official rules](https://paypalaihackathon.devpost.com/rules), checked Oct 28 | Nov 12 noon PST deadline; sandbox PayPal plus AI; functional demo; public licensed source; judging access through Dec 15 | Team submission, judge access, and final package completeness |
| [PayPal saved customer information](https://developer.paypal.com/checkout/save-customer-info/), updated Jun 23, 2026 | A consented saved PayPal method can support later payments without repeated buyer approval | This application's permissions, usable token shape, and successful second sandbox payment |
| [PayPal idempotency](https://developer.paypal.com/api/rest/reference/idempotency/), updated Aug 11, 2026 | PayPal-Request-Id supports retries on supported endpoints; retention and support depend on the API | Exact create/capture/refund behavior, including interruptions and retries |
| [PayPal capture refunds](https://developer.paypal.com/api/payments/v2/captures-refund), checked Oct 28 | Refund-by-capture endpoint, amount parameter, and request identity | Authorized merchant refund and its observed final status |
| [PayPal webhook verification](https://developer.paypal.com/api/webhooks/v1/verify-webhook-signature-post), checked Oct 28 | Provider endpoint for verifying webhook signatures | Verification of an actual sandbox transaction event |
| [Render free-service documentation](https://render.com/docs/free), checked Oct 28 | Free web services sleep after 15 idle minutes; free PostgreSQL expires after 30 days | A selected hosting setup that stays usable through judging |

No sandbox calls, account checks, deployment checks, or model evaluations were performed in this planning task. Documentation support is not the same as a proven integration.

## Corrections and explicit choices

| ID | Dossier gap or ambiguity | Planned resolution |
| --- | --- | --- |
| D01 | "Release on timeout" can free money after a successful but unobserved capture | Retain reservations for UNKNOWN outcomes until provider reconciliation |
| D02 | A cart hash is treated as the retry mechanism | Use durable purchase-intent and operation IDs; keep cart hashing for payload binding and duplicate warnings |
| D03 | Spent is moved only after webhook confirmation | Account for a completed synchronous capture immediately; track webhook evidence separately |
| D04 | SQLite locally diverges from PostgreSQL locking | Use PostgreSQL for development and integration verification |
| D05 | External catalog discovery appears to imply payment or refund authority | One controlled merchant with a trusted payee mapping; external discovery is optional |
| D06 | A "pre-approved buyer" fallback could imply reusable authorization that does not exist | Require actual buyer approval on each order when vaulting fails |
| D07 | A $349 purchase under a $400 cap triggers the 80% near-limit rule | Use a clearly labeled $500 cap/budget and pre-approve the demo merchant during the grant |
| D08 | Missing listing dimensions would be caught before payment, weakening the recovery story | Demonstrate wrong fulfillment after a valid listing; keep missing attributes as an escalation case |
| D09 | A model-selected cause indirectly chooses refund bounds | Human confirms the cause and exact offer; merchant policy and code cap the amount |
| D10 | A hash chain may be mistaken for tamper-proof storage | Describe its checkpoint-dependent tamper evidence and database-administrator limitation |
| D11 | Large agent teams can duplicate work and overwhelm integration | One coordinator, explicit ownership, a maximum of three workers, and independent acceptance review |
| D12 | New runtime orchestration infrastructure could consume the schedule | One modular backend, PostgreSQL jobs, and existing model tool calling |

The three-worker cap, task timeboxes, quote expiry, capability lifetime, refund bands, and dated schedule are project recommendations. They are not requirements from PayPal, Devpost, or the agent research sources.

## Deferred investigation

Verify Channel3 authentication and catalog fidelity only if the local catalog demo is complete. Verify AG Grid edition and licensing before using any paid functionality. Investigate AP2 interoperability and third-party merchant onboarding after the hackathon. Do not spend the critical path repeating the dossier's full competitor or prize analysis.
