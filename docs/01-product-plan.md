# Product plan

Status: proposed implementation plan, October 28, 2026. Read alongside the [architecture](02-architecture.md) and [build plan](03-build-plan.md).

## Product promise

A person gives an agent a spending grant. The agent can suggest a cart, but only Mandate can authorize the payment. The person can inspect the decision, revoke future spending, and approve a bounded refund when a purchase goes wrong.

The first users are developers adding purchases to AI assistants. The hackathon experience should let a judge understand the boundary and try to break it within a few minutes. Keep the working name Mandate with the subtitle "Spending controls and recovery for AI purchases." Do not claim AP2 compatibility without implementing and testing the protocol.

## Recommended scope

| Approach | Benefit | Cost or limitation | Decision |
| --- | --- | --- | --- |
| Controlled sandbox merchant, small catalog, one shopping agent | Demonstrates the entire payment and recovery lifecycle | Does not establish adoption by independent merchants | Build this |
| Discovery across external catalogs and merchants | Broader shopping story | Catalog discovery does not provide checkout or refund authority | Add after the core demo |
| General agent payments platform with AP2, MCP, multiple agents, and production rails | Wider integration potential | Too many authorization and operational dependencies for this deadline | Defer |

Use one sandbox merchant that the team controls. The catalog's merchant identity must map to that merchant's actual PayPal payee. Additional merchant records can demonstrate rejection, but cannot pretend to settle to unrelated sellers. Recovery works because the demo merchant authorizes its own refunds.

## MVP user journey

1. The person creates a grant with USD budget, transaction cap, expiry, approved merchant, permitted categories, and purchase constraints. The UI shows model-extracted constraints for confirmation.
2. The person authorizes a sandbox payment method through PayPal. The backend waits until the saved method is usable. App spending authority and PayPal payment consent remain separate records. If saving the method requires an initial purchase, that purchase must pass the same policy checks and count against its grant.
3. The shopping agent selects catalog items and submits a proposal using its restricted capability.
4. Mandate displays APPROVE, ESCALATE, or DENY with rule results. An approved proposal reserves budget and enters the payment queue.
5. The ledger shows provider status, reserved and spent amounts, and whether a signed webhook or provider lookup corroborated the result.
6. The person reports a problem. AI summarizes evidence and suggests a cause. Code computes the refund bounds, the human confirms the cause and amount, and the authorized merchant backend issues the refund.

## What ships

| Capability | Required behavior |
| --- | --- |
| Grant and revoke | Session isolation, explicit constraints, expiry, budget display, and revocation |
| Shopping agent | Real model tool use against catalog search and proposal submission only |
| Policy engine | All eleven dossier checks, with the refinements in the architecture |
| Payment execution | Stored cart binding, durable operation IDs, atomic reservations, and recovery after interruption |
| Decision ledger | Searchable history, rule evidence, provider identifiers, and audit-chain verification |
| Attack controls | Preset adversarial proposals and a bounded custom proposal form |
| Recovery | Evidence review, a proposed amount, human acceptance, and one real sandbox partial refund |
| Judge access | Hosted functional demo, reproducible run instructions, and clearly labeled sandbox data |

## Demo defaults

Use a $500 total budget, $500 transaction cap, USD only, five purchase slots per hour, and an 80% near-limit threshold. These are proposed demo settings, not provider limits. A $349 desk therefore fits without a near-limit escalation. The person explicitly pre-approves the demo merchant during grant creation. A merchant not already approved requires a new or revised human grant.

Use a catalog item described as a 160 cm desk and a separately labeled fulfillment fixture showing that a 120 cm desk arrived. This demonstrates a mistake that purchase-time catalog checks cannot prevent. A missing width field belongs in the ambiguity-blocking scenario, not in the recovery success story.

For a partial-refund demonstration, assume $60 avoided freight and $87.25 expected resale loss. Their $147.25 sum is below the demo seller-error band's 90% floor, so code proposes $314.10 on $349. The human must accept it. Label the economic inputs and percentages as demo business policy, not a statement of consumer entitlement or PayPal policy.

## Success criteria

- A judge can complete grant, proposal, decision, payment inspection, and recovery without reading backend documentation.
- The agent has no PayPal credential, saved payment token, refund tool, or human approval capability.
- Every required scenario in [validation](06-validation-and-demo.md) has recorded evidence before release.
- The main purchase, block, and recovery sequence can be demonstrated in 2 minutes 50 seconds.
- The demo exposes its limitations and distinguishes real sandbox transactions from fixtures or replays.

## Scope cuts

Exclude real money, production vault onboarding, arbitrary merchant checkout, escrow, dispute automation, subscription purchases, multi-currency accounting, reputation scoring, and claims to detect all prompt injection. A small internal tool wrapper is enough; a published SDK and general MCP gateway can wait. Use a local authoritative demo catalog first. Channel3 discovery is optional and cannot override payment identity or quote validation.

## Assumptions and decisions to resolve during the build

| Assumption | Owner | Resolve by | Safe default |
| --- | --- | --- | --- |
| One human builder can supervise roughly 4-6 focused hours daily | Human owner | Before starting the dated schedule | If less time is available, apply the scope cuts in the build plan |
| Sandbox application supports the intended vault flow | Payments worker | October 29 gate | Per-order buyer approval |
| One controlled merchant can authorize the refund demonstration | Human owner | October 29 gate | Keep recovery limited to that merchant |
| Always-on hosting and a persistent database fit the budget | Human owner | October 30 | Keep complete local setup instructions while selecting hosting |
| Model provider and key are available | Coordinator | October 29 | Pick one supported tool-calling model; document the selected version |

Do not treat unresolved assumptions as verified capabilities. This planning task does not authorize purchasing hosting or publishing the project.
